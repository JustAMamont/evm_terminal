pub mod models;
pub mod transport;

use std::sync::RwLock;
use once_cell::sync::Lazy;
use pyo3::prelude::*;
pub use models::{EngineEvent, EngineCommand};
use transport::{send_to_python, BRIDGE_QUEUE};

// ===================== КЭШ ДЕДУПЛИКАЦИИ =====================
// Каждый тип события хранит только ОДИН предыдущий кадр

static LAST_BALANCE: Lazy<RwLock<Option<String>>> = Lazy::new(|| RwLock::new(None));
static LAST_POOL: Lazy<RwLock<Option<String>>> = Lazy::new(|| RwLock::new(None));
static LAST_GAS: Lazy<RwLock<Option<u64>>> = Lazy::new(|| RwLock::new(None));
static LAST_CONN: Lazy<RwLock<Option<String>>> = Lazy::new(|| RwLock::new(None));
static LAST_IMPACT: Lazy<RwLock<Option<u64>>> = Lazy::new(|| RwLock::new(None));

// ===================== PYO3 ФУНКЦИИ =====================

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

// ----- ПРОБРОС И ДЕДУПЛИКАЦИЯ ИВЕНТОВ В ПАЙТОН -----

pub fn emit_event(event: EngineEvent) {
    let should_send = match &event {
        EngineEvent::BalanceUpdate { wei, .. } => {
            let mut cache = LAST_BALANCE.write().unwrap();
            match cache.as_ref() {
                Some(prev) if prev == wei => false,
                _ => { *cache = Some(wei.clone()); true }
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
                Some(prev) if prev == &current => false,
                _ => { *cache = Some(current); true }
            }
        }

        EngineEvent::GasPriceUpdate { gas_price_gwei } => {
            let mut cache = LAST_GAS.write().unwrap();
            match *cache {
                Some(prev) if prev == gas_price_gwei.to_bits() => false,
                _ => { *cache = Some(gas_price_gwei.to_bits()); true }
            }
        }

        EngineEvent::ConnectionStatus { connected, message } => {
            let current = format!("{}:{}", connected, message);
            let mut cache = LAST_CONN.write().unwrap();
            match cache.as_ref() {
                Some(prev) if prev == &current => false,
                _ => { *cache = Some(current); true }
            }
        }

        EngineEvent::ImpactUpdate { impact_pct, .. } => {
            let mut cache = LAST_IMPACT.write().unwrap();
            match *cache {
                Some(prev) if prev == impact_pct.to_bits() => false,
                _ => { *cache = Some(impact_pct.to_bits()); true }
            }
        }

        _ => true,
    };

    if should_send {
        if let Ok(json) = serde_json::to_string(&event) {
            send_to_python(json);
        }
    }
}

// ----- ПРОБРОС ЛОГОВ В ПАЙТОН -----

pub const DEBUG_MODE: bool = true;

pub fn emit_log(level: &str, message: String) {
    if !DEBUG_MODE && level == "DEBUG" { return; }
    emit_event(EngineEvent::Log { level: level.to_string(), message });
}
