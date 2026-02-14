use pyo3::prelude::*;
use pyo3::exceptions::PyValueError;
use std::collections::HashMap;
use std::sync::{Arc, RwLock};
use once_cell::sync::Lazy;
use ethers::prelude::*;
use ethers::providers::{Provider, Http};
use ethers::types::{Address, U256};
use std::str::FromStr;
use std::time::Duration;
use tokio::time::sleep;
use tokio::task::JoinHandle; 
use crate::state::{RUNTIME, SHUTDOWN_FLAG};
use url::Url;
use std::sync::atomic::Ordering;

// --- ABI Definitions ---
abigen!(
    IUniswapV2Router,
    r#"[
        function getAmountsOut(uint amountIn, address[] memory path) public view returns (uint[] memory amounts)
    ]"#,
);

abigen!(
    IQuoterV2,
    r#"[
        struct QuoteExactInputSingleParams { address tokenIn; address tokenOut; uint256 amountIn; uint24 fee; uint160 sqrtPriceLimitX96; }
        function quoteExactInputSingle(QuoteExactInputSingleParams memory params) external returns (uint256 amountOut)
    ]"#,
);

#[derive(Clone, Debug)]
pub struct PnlInfo {
    pub pnl_percent: f64,
    pub current_value_wei: U256,
    pub cost_basis_wei: U256,
    pub is_loading: bool,
}

/// Глобальное состояние PnL данных для Python TUI
pub static PNL_STATE: Lazy<Arc<RwLock<HashMap<String, PnlInfo>>>> = Lazy::new(|| {
    Arc::new(RwLock::new(HashMap::new()))
});

/// Хранилище дескрипторов задач (JoinHandle) для контроля жизненного цикла воркеров
static PNL_TASKS: Lazy<Arc<RwLock<HashMap<String, JoinHandle<()>>>>> = Lazy::new(|| {
    Arc::new(RwLock::new(HashMap::new()))
});

/// Создание оптимизированного HTTP провайдера
fn create_provider(rpc_url: &str) -> Result<Arc<Provider<Http>>, String> {
    let url = match Url::parse(rpc_url) {
        Ok(u) => u,
        Err(e) => return Err(format!("Invalid RPC URL: {}", e)),
    };
    let provider = Provider::new(Http::new(url));
    Ok(Arc::new(provider))
}

/// Основной цикл расчета PnL
pub async fn pnl_worker_task(
    key: String,
    rpc_url: String,
    token_in: Address, 
    token_out: Address, 
    amount_in: U256, 
    cost_basis: U256, 
    pool_type: String, 
    fee: u32,
    v2_router_addr: Address,
    v3_quoter_addr: Address
) {
    let provider = match create_provider(&rpc_url) {
        Ok(p) => p,
        Err(e) => {
            eprintln!("[RUST PNL] Error initializing provider for {}: {}", key, e);
            return;
        }
    };

    let v2_router = IUniswapV2Router::new(v2_router_addr, provider.clone());
    let v3_quoter = IQuoterV2::new(v3_quoter_addr, provider.clone());
    
    // Единица измерения (1.0) для запроса прайса
    let unit_amount = U256::from(10).pow(U256::from(18));

    loop {
        if SHUTDOWN_FLAG.load(Ordering::Relaxed) { break; }
        
        let mut unit_price_result = U256::zero();
        let mut success = false;

        // 1. Получение цены из соответствующего протокола
        if pool_type == "V3" {
            let params = QuoteExactInputSingleParams {
                token_in,
                token_out,
                amount_in: unit_amount,
                fee,
                sqrt_price_limit_x96: U256::zero(),
            };
            
            match v3_quoter.quote_exact_input_single(params).call().await {
                Ok(amount_out) => {
                    unit_price_result = amount_out;
                    success = true;
                },
                Err(e) => { 
                    // Не спамим в консоль при временных ошибках сети
                    if !e.to_string().contains("timeout") {
                        eprintln!("[RUST PNL V3] Quoter Error for {}: {}", key, e); 
                    }
                }
            }
        } else {
            let path = vec![token_in, token_out];
            match v2_router.get_amounts_out(unit_amount, path).call().await {
                Ok(amounts) => {
                    if amounts.len() >= 2 {
                        unit_price_result = *amounts.last().unwrap();
                        success = true;
                    }
                },
                Err(e) => { 
                    if !e.to_string().contains("timeout") {
                        eprintln!("[RUST PNL V2] Router Error for {}: {}", key, e); 
                    }
                }
            }
        }

        // 2. Расчет PnL с учетом комиссий (Saturating Math для безопасности)
        if success {
            let gross_value = (unit_price_result * amount_in) / unit_amount;

            // Налог роутера 0.1%
            let fee_tax = (gross_value * 10) / 10000;
            
            // Налог DEX
            let fee_dex = if pool_type == "V3" {
                (gross_value * U256::from(fee)) / U256::from(1_000_000)
            } else {
                (gross_value * 25) / 10000 // 0.25% V2
            };
            
            let net_value = gross_value.saturating_sub(fee_tax).saturating_sub(fee_dex);

            let mut pnl_percent = 0.0;
            if !cost_basis.is_zero() {
                let val_f = net_value.as_u128() as f64;
                let cost_f = cost_basis.as_u128() as f64;
                pnl_percent = ((val_f - cost_f) / cost_f) * 100.0;
            }

            // 3. Атомарное обновление состояния
            {
                let mut state = PNL_STATE.write().unwrap();
                state.insert(key.clone(), PnlInfo {
                    pnl_percent,
                    current_value_wei: net_value,
                    cost_basis_wei: cost_basis,
                    is_loading: false
                });
            }
        }

        // Интервал опроса - 1 секунда для баланса нагрузки
        sleep(Duration::from_millis(1000)).await;
    }
}

// --- Python Exposed Functions ---

#[pyfunction]
pub fn start_pnl_tracker(
    _py: Python<'_>, 
    rpc_url: String, 
    wallet_addr: String, 
    token_addr: String, 
    quote_addr: String, 
    balance_wei_str: String, 
    cost_wei_str: String,
    pool_type: String,
    v3_fee: u32,
    v2_router: String,
    v3_quoter: String
) -> PyResult<()> {
    let key = format!("{}:{}", wallet_addr.to_lowercase(), token_addr.to_lowercase());
    
    let t_in = Address::from_str(&token_addr).map_err(|e| PyValueError::new_err(format!("Invalid token: {}", e)))?;
    let t_out = Address::from_str(&quote_addr).map_err(|e| PyValueError::new_err(format!("Invalid quote: {}", e)))?;
    let am_in = U256::from_dec_str(&balance_wei_str).unwrap_or(U256::zero());
    let c_ba = U256::from_dec_str(&cost_wei_str).unwrap_or(U256::zero());
    
    let v2_r = Address::from_str(&v2_router).map_err(|_| PyValueError::new_err("Bad V2 Router address"))?;
    let v3_q = Address::from_str(&v3_quoter).map_err(|_| PyValueError::new_err("Bad V3 Quoter address"))?;

    if am_in.is_zero() { return Ok(()); }

    // КРИТИЧЕСКИЙ БЛОК: Убийство старой задачи перед запуском новой (DCA поддержка)
    {
        let mut tasks = PNL_TASKS.write().unwrap();
        if let Some(old_handle) = tasks.remove(&key) {
            old_handle.abort(); 
        }
        
        // Предварительная установка состояния "Загрузка"
        {
            let mut state = PNL_STATE.write().unwrap();
            state.insert(key.clone(), PnlInfo {
                pnl_percent: 0.0,
                current_value_wei: U256::zero(),
                cost_basis_wei: c_ba,
                is_loading: true
            });
        }

        let worker_key = key.clone();
        let handle = RUNTIME.spawn(async move {
            pnl_worker_task(worker_key, rpc_url, t_in, t_out, am_in, c_ba, pool_type, v3_fee, v2_r, v3_q).await;
        });
        
        tasks.insert(key, handle);
    }

    Ok(())
}

#[pyfunction]
pub fn stop_pnl_tracker(_py: Python<'_>, wallet_addr: String, token_addr: String) -> PyResult<()> {
    let key = format!("{}:{}", wallet_addr.to_lowercase(), token_addr.to_lowercase());
    
    // 1. Остановка воркера
    {
        let mut tasks = PNL_TASKS.write().unwrap();
        if let Some(handle) = tasks.remove(&key) {
            handle.abort();
        }
    }
    
    // 2. Очистка состояния
    {
        let mut state = PNL_STATE.write().unwrap();
        state.remove(&key);
    }
    
    Ok(())
}

#[pyfunction]
pub fn get_pnl_status(_py: Python<'_>, wallet_addr: String, token_addr: String) -> PyResult<Option<(f64, String, String, bool)>> {
    let key = format!("{}:{}", wallet_addr.to_lowercase(), token_addr.to_lowercase());
    let state = PNL_STATE.read().unwrap();
    
    match state.get(&key) {
        Some(info) => {
            Ok(Some((
                info.pnl_percent, 
                info.current_value_wei.to_string(), 
                info.cost_basis_wei.to_string(), 
                info.is_loading
            )))
        },
        None => Ok(None)
    }
}

#[pyfunction]
pub fn clear_all_pnl_trackers(_py: Python<'_>) -> PyResult<()> {
    // 1. Физически убиваем ВСЕ потоки расчета PnL
    {
        let mut tasks = PNL_TASKS.write().unwrap();
        for (_, handle) in tasks.drain() {
            handle.abort();
        }
    }
    
    // 2. Очищаем данные из стейта
    {
        let mut state = PNL_STATE.write().unwrap();
        state.clear();
    }
    
    Ok(())
}