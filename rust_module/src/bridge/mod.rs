pub mod models;
pub mod transport;
pub mod pack;
pub mod ring;

use std::sync::RwLock;
use once_cell::sync::Lazy;
use pyo3::prelude::*;
pub use models::{EngineEvent, EngineCommand};
use transport::{send_to_python, BRIDGE_QUEUE};
use ring::RingBuffer;
use pack::Packable;

// ===================== RING BUFFERS =====================
pub static EVENT_RING: Lazy<RingBuffer> = Lazy::new(RingBuffer::new);
pub static COMMAND_RING: Lazy<RingBuffer> = Lazy::new(RingBuffer::new);

// ===================== DEDUPLICATION CACHE =====================
static LAST_BALANCE: Lazy<RwLock<Option<String>>> = Lazy::new(|| RwLock::new(None));
static LAST_POOL: Lazy<RwLock<Option<String>>> = Lazy::new(|| RwLock::new(None));
static LAST_GAS: Lazy<RwLock<Option<u64>>> = Lazy::new(|| RwLock::new(None));
static LAST_CONN: Lazy<RwLock<Option<String>>> = Lazy::new(|| RwLock::new(None));
static LAST_IMPACT: Lazy<RwLock<Option<u64>>> = Lazy::new(|| RwLock::new(None));

// ===================== PYO3 FUNCS =====================

#[pyfunction]
pub fn init_bridge_signal(_py: Python<'_>, socket_fd: u64) -> PyResult<()> {
    transport::set_signal_socket(socket_fd).map_err(|e| pyo3::exceptions::PyRuntimeError::new_err(e))
}

#[pyfunction]
pub fn pop_from_bridge(_py: Python<'_>) -> PyResult<Option<String>> {
    match BRIDGE_QUEUE.1.try_recv() {
        Ok(json_str) => Ok(Some(json_str)),
        Err(_) => Ok(None),
    }
}

// ----- Event Forwarding with Deduplication -----

pub fn emit_event(event: EngineEvent) {
    // Deduplication for high-frequency events
    match &event {
        EngineEvent::BalanceUpdate { wei, .. } => {
            let mut cache = LAST_BALANCE.write().unwrap();
            match cache.as_ref() {
                Some(prev) if prev == wei => return,
                _ => *cache = Some(wei.clone()),
            }
        }
        EngineEvent::PoolUpdate { reserve0, reserve1, spot_price, .. } => {
            let current = format!(
                "{}:{}:{}",
                reserve0.as_deref().unwrap_or("0"),
                reserve1.as_deref().unwrap_or("0"),
                spot_price.map(|p| p.to_bits()).unwrap_or(0)
            );
            let mut cache = LAST_POOL.write().unwrap();
            match cache.as_ref() {
                Some(prev) if prev == &current => return,
                _ => *cache = Some(current),
            }
        }
        EngineEvent::GasPriceUpdate { gas_price_gwei } => {
            let mut cache = LAST_GAS.write().unwrap();
            match *cache {
                Some(prev) if prev == gas_price_gwei.to_bits() => return,
                _ => *cache = Some(gas_price_gwei.to_bits()),
            }
        }
        EngineEvent::ConnectionStatus { connected, message } => {
            let current = format!("{}:{}", connected, message);
            let mut cache = LAST_CONN.write().unwrap();
            match cache.as_ref() {
                Some(prev) if prev == &current => return,
                _ => *cache = Some(current),
            }
        }
        EngineEvent::ImpactUpdate { impact_pct, .. } => {
            let mut cache = LAST_IMPACT.write().unwrap();
            match *cache {
                Some(prev) if prev == impact_pct.to_bits() => return,
                _ => *cache = Some(impact_pct.to_bits()),
            }
        }
        _ => {}
    }
    
    // All events go directly to Ring Buffer
    let mut payload = Vec::with_capacity(ring::MAX_MSG_SIZE);
    event.pack(&mut payload);
    if EVENT_RING.push(&payload).is_err() {
        // Fallback to JSON if Ring is full
        if let Ok(json) = serde_json::to_string(&event) {
            send_to_python(json);
        }
    } else {
        // ИСПРАВЛЕНИЕ: Всегда сигналить Python, без проверки IN_PROCESSING
        transport::signal_python();
    }
}

// ====== SENDING LOGS TO PYTHON ======

pub const DEBUG_MODE: bool = false;

pub fn emit_log(level: &str, message: String) {
    if !DEBUG_MODE && level == "DEBUG" { return; }
    
    let mut payload = Vec::with_capacity(ring::MAX_MSG_SIZE);
    EngineEvent::Log { level: level.to_string(), message }.pack(&mut payload);
    if EVENT_RING.push(&payload).is_ok() {
        // ИСПРАВЛЕНИЕ: Сигналить Python о новом событии
        transport::signal_python();
    }
}

// ===================== PYTHON API =====================

/// Python reads events from EVENT_RING
#[pyfunction]
pub fn pop_event_from_ring(_py: Python<'_>) -> PyResult<Option<PyObject>> {
    Ok(EVENT_RING.pop().map(|data| {
        pyo3::types::PyBytes::new(_py, &data).into()
    }))
}

/// Python pushes command to COMMAND_RING
#[pyfunction]
pub fn push_command_to_ring(_py: Python<'_>, data: Vec<u8>) -> PyResult<bool> {
    let result = COMMAND_RING.push(&data);
    emit_log("DEBUG", format!("[Rust] push_command_to_ring: len={} ok={}", data.len(), result.is_ok()));
    Ok(result.is_ok())
}

/// Python checks pending event count
#[pyfunction]
pub fn ring_available(_py: Python<'_>) -> PyResult<usize> {
    Ok(EVENT_RING.len())
}

/// Process commands from COMMAND_RING and send to engine
#[pyfunction]
pub fn process_commands(_py: Python<'_>) -> PyResult<()> {
    let ring_len = COMMAND_RING.len();
    emit_log("DEBUG", format!("[Rust] process_commands START: ring_len={}", ring_len));
    
    // УБРАНО: IN_PROCESSING.store(true, ...) - больше не нужен
    
    while let Some(data) = COMMAND_RING.pop() {
        match EngineCommand::unpack(&mut data.as_slice()) {
            Ok(cmd) => {
                emit_log("DEBUG", format!("[Rust] unpacked OK: {:?}", std::mem::discriminant(&cmd)));
                let _ = crate::engine::send_command(cmd);
            }
            Err(e) => {
                emit_log("ERROR", format!("[Rust] unpack ERROR: {:?}", e));
            }
        }
    }
    
    // Сигналим Python о событиях после обработки команд
    transport::signal_python();
    
    Ok(())
}