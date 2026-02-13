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
use crate::state::{RUNTIME, SHUTDOWN_FLAG};
use url::Url;
use std::sync::atomic::Ordering;

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

pub static PNL_STATE: Lazy<Arc<RwLock<HashMap<String, PnlInfo>>>> = Lazy::new(|| {
    Arc::new(RwLock::new(HashMap::new()))
});

static PNL_TASKS: Lazy<Arc<RwLock<HashMap<String, bool>>>> = Lazy::new(|| {
    Arc::new(RwLock::new(HashMap::new()))
});

fn create_provider(rpc_url: &str) -> Result<Arc<Provider<Http>>, String> {
    let url = Url::parse(rpc_url).map_err(|e| format!("Invalid RPC: {}", e))?;
    Ok(Arc::new(Provider::new(Http::new(url))))
}

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
            eprintln!("[RUST PNL ERROR] Provider creation failed: {}", e);
            return;
        }
    };

    let v2_router = IUniswapV2Router::new(v2_router_addr, provider.clone());
    let v3_quoter = IQuoterV2::new(v3_quoter_addr, provider.clone());
    
    let unit_amount = U256::from(10).pow(U256::from(18));

    loop {
        if SHUTDOWN_FLAG.load(Ordering::Relaxed) { break; }
        
        {
            let tasks = PNL_TASKS.read().unwrap();
            if !tasks.contains_key(&key) { break; }
        }

        let mut unit_price_result = U256::zero();
        let mut success = false;

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
                Err(e) => { eprintln!("[RUST PNL-V3 ERROR] Quoter call failed: {}", e); } 
            }
        } else {
            let path = vec![token_in, token_out];
            match v2_router.get_amounts_out(unit_amount, path).call().await {
                Ok(amounts) => {
                    if amounts.len() > 1 {
                        unit_price_result = amounts[amounts.len() - 1];
                        success = true;
                    }
                },
                Err(e) => { eprintln!("[RUST PNL-V2 ERROR] GetAmountsOut call failed: {}", e); }
            }
        }

        if success {
            let gross_value = (unit_price_result * amount_in) / unit_amount;

            // --- Учитываем комиссии на продажу ---
            // 1. Комиссия TaxRouter (0.1% = 10 / 10000)
            let fee_tax_router = (gross_value * 10) / 10000;
            
            // 2. Комиссия PancakeSwap
            let fee_pancakeswap = if pool_type == "V3" {
                // fee = 500 для 0.05%. Формула: val * fee / 1_000_000
                (gross_value * U256::from(fee)) / U256::from(1_000_000)
            } else {
                // V2 стандартная комиссия 0.25% (25 / 10000)
                (gross_value * 25) / 10000
            };
            
            let net_value = gross_value - fee_tax_router - fee_pancakeswap;
            // ----------------------------------------------------

            let mut pnl_percent = 0.0;
            if !cost_basis.is_zero() {
                // Считаем PnL от ЧИСТОЙ выручки
                let val_f = net_value.as_u128() as f64;
                let cost_f = cost_basis.as_u128() as f64;
                pnl_percent = ((val_f - cost_f) / cost_f) * 100.0;
            }

            let mut state = PNL_STATE.write().unwrap();
            state.insert(key.clone(), PnlInfo {
                pnl_percent,
                current_value_wei: net_value, // Сохраняем ЧИСТУЮ стоимость
                cost_basis_wei: cost_basis,
                is_loading: false
            });
        }

        sleep(Duration::from_secs(1)).await;
    }
}

// --- PYTHON EXPORTS ---

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
    
    let token_in = Address::from_str(&token_addr).map_err(|e| PyValueError::new_err(e.to_string()))?;
    let token_out = Address::from_str(&quote_addr).map_err(|e| PyValueError::new_err(e.to_string()))?;
    let amount_in = U256::from_dec_str(&balance_wei_str).unwrap_or(U256::zero());
    let cost_basis = U256::from_dec_str(&cost_wei_str).unwrap_or(U256::zero());
    
    let v2_r = Address::from_str(&v2_router).map_err(|e| PyValueError::new_err(format!("Bad V2 Router: {}", e)))?;
    let v3_q = Address::from_str(&v3_quoter).map_err(|e| PyValueError::new_err(format!("Bad V3 Quoter: {}", e)))?;

    if amount_in.is_zero() { return Ok(()); }

    {
        let mut tasks = PNL_TASKS.write().unwrap();
        if tasks.contains_key(&key) { tasks.remove(&key); }
        tasks.insert(key.clone(), true);
    }
    
    {
        let mut state = PNL_STATE.write().unwrap();
        state.insert(key.clone(), PnlInfo {
            pnl_percent: 0.0,
            current_value_wei: U256::zero(),
            cost_basis_wei: cost_basis,
            is_loading: true
        });
    }

    RUNTIME.spawn(async move {
        pnl_worker_task(key, rpc_url, token_in, token_out, amount_in, cost_basis, pool_type, v3_fee, v2_r, v3_q).await;
    });

    Ok(())
}

#[pyfunction]
pub fn stop_pnl_tracker(_py: Python<'_>, wallet_addr: String, token_addr: String) -> PyResult<()> {
    let key = format!("{}:{}", wallet_addr.to_lowercase(), token_addr.to_lowercase());
    { let mut tasks = PNL_TASKS.write().unwrap(); tasks.remove(&key); }
    { let mut state = PNL_STATE.write().unwrap(); state.remove(&key); }
    Ok(())
}

#[pyfunction]
pub fn get_pnl_status(_py: Python<'_>, wallet_addr: String, token_addr: String) -> PyResult<Option<(f64, String, String, bool)>> {
    let key = format!("{}:{}", wallet_addr.to_lowercase(), token_addr.to_lowercase());
    let state = PNL_STATE.read().unwrap();
    if let Some(info) = state.get(&key) {
        Ok(Some((info.pnl_percent, info.current_value_wei.to_string(), info.cost_basis_wei.to_string(), info.is_loading)))
    } else { Ok(None) }
}