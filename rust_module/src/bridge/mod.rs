pub mod models;
pub mod transport;
pub mod pack;
pub mod ring;

use parking_lot::RwLock;
use std::sync::atomic::{AtomicBool, Ordering};
use once_cell::sync::Lazy;
use pyo3::prelude::*;
use pyo3::types::PyAny;
use pyo3_asyncio::tokio::future_into_py;
pub use models::{EngineEvent, EngineCommand};
use transport::{send_to_python, BRIDGE_QUEUE, signal_python};
use ring::RingBuffer;
use pack::Packable;
use tokio::sync::Notify;

// ===================== RING BUFFERS =====================
pub static EVENT_RING: Lazy<RingBuffer> = Lazy::new(RingBuffer::new);
pub static COMMAND_RING: Lazy<RingBuffer> = Lazy::new(RingBuffer::new);

// ===================== BACKGROUND PROCESSOR =====================
static PROCESSOR_RUNNING: AtomicBool = AtomicBool::new(false);
static COMMAND_NOTIFY: Lazy<Notify> = Lazy::new(Notify::new);

// ===================== DEDUPLICATION CACHE =====================
static LAST_BALANCE: Lazy<RwLock<Option<String>>> = Lazy::new(|| RwLock::new(None));
static LAST_POOL: Lazy<RwLock<Option<String>>> = Lazy::new(|| RwLock::new(None));
static LAST_GAS: Lazy<RwLock<Option<u64>>> = Lazy::new(|| RwLock::new(None));
static LAST_CONN: Lazy<RwLock<Option<String>>> = Lazy::new(|| RwLock::new(None));
static LAST_IMPACT: Lazy<RwLock<Option<u64>>> = Lazy::new(|| RwLock::new(None));

// ===================== ASYNC INTERNAL FUNCTIONS =====================

//async fn push_command_async(data: Vec<u8>) -> bool {
//    let result = COMMAND_RING.push(&data).is_ok();
//    if result {
//        COMMAND_NOTIFY.notify_one();
//    }
//    result
//}

//async fn pop_event_async() -> Option<Vec<u8>> {
//    EVENT_RING.pop()
//}

async fn pop_from_bridge_async() -> Option<String> {
    BRIDGE_QUEUE.1.try_recv().ok()
}

async fn ring_available_async() -> usize {
    EVENT_RING.len()
}

// ===================== BACKGROUND PROCESSOR =====================

fn start_background_processor() {
    if PROCESSOR_RUNNING.swap(true, Ordering::SeqCst) {
        return;
    }
    
    crate::state::RUNTIME.spawn(async {
        loop {
            COMMAND_NOTIFY.notified().await;
            
            while let Some(data) = COMMAND_RING.pop() {
                match EngineCommand::unpack(&mut data.as_slice()) {
                    Ok(cmd) => {
                        let _ = crate::engine::send_command(cmd);
                    }
                    Err(e) => {
                        emit_log("ERROR", format!("unpack error: {:?}", e));
                    }
                }
            }
        }
    });
}

// ===================== PYO3 ASYNC FUNCTIONS =====================

#[pyfunction]
pub fn init_bridge_signal<'py>(py: Python<'py>, socket_fd: u64) -> PyResult<&'py PyAny> {
    future_into_py(py, async move {
        transport::set_signal_socket(socket_fd)
            .map_err(|e| pyo3::exceptions::PyRuntimeError::new_err(e))?;
        start_background_processor();
        Ok(())
    })
}

#[pyfunction]
pub fn push_command_to_ring(_py: Python<'_>, data: Vec<u8>) -> PyResult<bool> {
    let result = COMMAND_RING.push(&data).is_ok();
    if result {
        COMMAND_NOTIFY.notify_one();
    }
    Ok(result)
}

#[pyfunction]
pub fn pop_event_from_ring(_py: Python<'_>) -> PyResult<Option<PyObject>> {
    Ok(EVENT_RING.pop().map(|data| {
        pyo3::types::PyBytes::new(_py, &data).into()
    }))
}

#[pyfunction]
pub fn pop_from_bridge<'py>(py: Python<'py>) -> PyResult<&'py PyAny> {
    future_into_py(py, async move {
        Ok(pop_from_bridge_async().await)
    })
}

#[pyfunction]
pub fn ring_available<'py>(py: Python<'py>) -> PyResult<&'py PyAny> {
    future_into_py(py, async move {
        Ok(ring_available_async().await)
    })
}

#[pyfunction]
pub fn process_commands<'py>(py: Python<'py>) -> PyResult<&'py PyAny> {
    future_into_py(py, async move { Ok(()) })
}

// ===================== EVENT FORWARDING WITH DEDUPLICATION =====================

pub fn emit_event(event: EngineEvent) {
    match &event {
        EngineEvent::BalanceUpdate { wei, .. } => {
            let mut cache = LAST_BALANCE.write();
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
            let mut cache = LAST_POOL.write();
            match cache.as_ref() {
                Some(prev) if prev == &current => return,
                _ => *cache = Some(current),
            }
        }
        EngineEvent::GasPriceUpdate { gas_price_gwei } => {
            let mut cache = LAST_GAS.write();
            match *cache {
                Some(prev) if prev == gas_price_gwei.to_bits() => return,
                _ => *cache = Some(gas_price_gwei.to_bits()),
            }
        }
        EngineEvent::ConnectionStatus { connected, message } => {
            let current = format!("{}:{}", connected, message);
            let mut cache = LAST_CONN.write();
            match cache.as_ref() {
                Some(prev) if prev == &current => return,
                _ => *cache = Some(current),
            }
        }
        EngineEvent::ImpactUpdate { impact_pct, .. } => {
            let mut cache = LAST_IMPACT.write();
            match *cache {
                Some(prev) if prev == impact_pct.to_bits() => return,
                _ => *cache = Some(impact_pct.to_bits()),
            }
        }
        _ => {}
    }
    
    let mut payload = Vec::with_capacity(ring::MAX_MSG_SIZE);
    event.pack(&mut payload);
    if EVENT_RING.push(&payload).is_err() {
        if let Ok(json) = serde_json::to_string(&event) {
            send_to_python(json);
        }
    } else {
        signal_python();
    }
}

// ===================== LOGGING =====================

pub const DEBUG_MODE: bool = false;

pub fn emit_log(level: &str, message: String) {
    if !DEBUG_MODE && level == "DEBUG" { return; }
    
    let mut payload = Vec::with_capacity(ring::MAX_MSG_SIZE);
    EngineEvent::Log { level: level.to_string(), message }.pack(&mut payload);
    if EVENT_RING.push(&payload).is_ok() {
        signal_python();
    }
}