use std::sync::{Arc, RwLock, Mutex};
use once_cell::sync::Lazy;
use ethers::types::Address;
use tokio::task::AbortHandle;

pub static TRACKED_WALLETS: Lazy<Arc<RwLock<Vec<Address>>>> = Lazy::new(|| Arc::new(RwLock::new(Vec::new())));

// Хендл для основного монитора (универсальный, который слушает пулы и свапы)
pub static MONITOR_HANDLE: Lazy<Arc<Mutex<Option<AbortHandle>>>> = Lazy::new(|| Arc::new(Mutex::new(None)));

// Хендл для внутренних воркеров (газ, балансы) 
pub static INTERNAL_HANDLE: Lazy<Arc<Mutex<Option<AbortHandle>>>> = Lazy::new(|| Arc::new(Mutex::new(None)));

// Хендл для RPC Health Checker
pub static RPC_CHECKER_HANDLE: Lazy<Arc<Mutex<Option<AbortHandle>>>> = Lazy::new(|| Arc::new(Mutex::new(None)));

// Хендл для PnL калькулятора
pub static PNL_HANDLE: Lazy<Arc<Mutex<Option<AbortHandle>>>> = Lazy::new(|| Arc::new(Mutex::new(None)));