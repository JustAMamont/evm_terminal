use std::collections::HashMap;
use std::sync::{Arc, RwLock, Mutex};
use once_cell::sync::Lazy;
use ethers::prelude::*;
use tokio::task::AbortHandle;
use std::sync::atomic::AtomicBool;
use reqwest::Client;
use std::time::Duration;

// --- RPC-POOL-манагер ---
#[derive(Debug, Clone)]
pub struct RpcNode {
    pub url: String,
    pub latency: f32,
}

#[derive(Debug, Default)]
pub struct RpcPoolState {
    pub nodes: Vec<RpcNode>,
    pub current_index: usize,
}

impl RpcPoolState {
    // Round-robin selection of a healthy node
    pub fn get_next_url(&mut self) -> Option<String> {
        if self.nodes.is_empty() {
            return None;
        }
        let node = &self.nodes[self.current_index];
        self.current_index = (self.current_index + 1) % self.nodes.len();
        Some(node.url.clone())
    }
}
// -----------------------

pub struct BotState {
    pub nonce_map: HashMap<Address, u64>,
    pub gas_price: U256,
}

/* NOTE: Глобальные состояния используются расточительно. 
В больших системах это антипаттерн (сложно тестировать),
но для микросервиса/бота это допустимое упрощение ради производительности, 
чтобы не прокидывать контекст через 10 слоев. 
Я понимаю риски, но здесь это осознанное архитектурное решение. */

pub static RUNTIME: Lazy<tokio::runtime::Runtime> = Lazy::new(|| {
    tokio::runtime::Builder::new_multi_thread()
        .enable_all()
        .build()
        .unwrap()
});

pub static GLOBAL_HTTP_CLIENT: Lazy<Client> = Lazy::new(|| {
    Client::builder()
        .timeout(Duration::from_secs(5))
        .connect_timeout(Duration::from_secs(3))
        .tcp_keepalive(Some(Duration::from_secs(60)))
        .pool_idle_timeout(Some(Duration::from_secs(90)))
        .pool_max_idle_per_host(50)
        .build()
        .expect("Failed to create global HTTP client")
});

pub static SHUTDOWN_FLAG: AtomicBool = AtomicBool::new(false);

pub static CORE_STATE: Lazy<Arc<RwLock<BotState>>> = Lazy::new(|| {
    Arc::new(RwLock::new(BotState {
        nonce_map: HashMap::new(),
        gas_price: U256::zero(),
    }))
});

// --- Хранилище RPC-менеджера ---
pub static RPC_POOL: Lazy<Arc<RwLock<RpcPoolState>>> = Lazy::new(|| Arc::new(RwLock::new(RpcPoolState::default())));
// ------------------------------------

pub static TRACKED_WALLETS: Lazy<Arc<RwLock<Vec<Address>>>> = Lazy::new(|| Arc::new(RwLock::new(Vec::new())));
pub static MONITOR_HANDLE: Lazy<Arc<Mutex<Option<AbortHandle>>>> = Lazy::new(|| Arc::new(Mutex::new(None)));

pub type TransferEvent = (String, String, String, String); 
pub static EVENT_QUEUE: Lazy<Arc<Mutex<Vec<TransferEvent>>>> = Lazy::new(|| Arc::new(Mutex::new(Vec::new())));

// --- Стейт мониторинга пулов ---
// (BestPoolAddress, LiquidityWei)
pub static BEST_POOL_STATE: Lazy<Arc<RwLock<Option<(String, String)>>>> = Lazy::new(|| {
    Arc::new(RwLock::new(None))
});
// Хендл для остановки WSS листенера пулов
pub static POOL_SCANNER_HANDLE: Lazy<Arc<Mutex<Option<AbortHandle>>>> = Lazy::new(|| Arc::new(Mutex::new(None)));

// Глобальное хранилище балансов всех пулов: {АдресПула: БалансWei}
pub static POOL_BALANCES: Lazy<Arc<RwLock<HashMap<String, String>>>> = Lazy::new(|| {
    Arc::new(RwLock::new(HashMap::new()))
});