use pyo3::prelude::*;

mod state;
mod config;
mod monitor;
mod execution;
mod crypto;
mod pnl;

use crate::config::{get_network_config, get_available_networks};
use crate::monitor::{
    start_state_workers, start_token_monitor, stop_token_monitor, 
    get_pending_events, add_wallet_to_monitor, remove_wallet_from_monitor, 
    force_resync_nonce, shutdown_rust_workers,
    start_pool_scanner, stop_pool_scanner, get_best_pool_address,
    get_all_pool_balances, clear_pool_balances, get_best_rpc_url, get_healthy_rpc_urls
};
use crate::execution::{execute_swap_hot, execute_batch_swap, execute_approve_hot};
use crate::crypto::{init_or_load_keys, get_public_key};
use crate::pnl::{start_pnl_tracker, stop_pnl_tracker, get_pnl_status};

#[pymodule]
fn dexbot_core(_py: Python, m: &PyModule) -> PyResult<()> {
    m.add_function(wrap_pyfunction!(get_network_config, m)?)?;
    m.add_function(wrap_pyfunction!(get_available_networks, m)?)?;

    m.add_function(wrap_pyfunction!(start_state_workers, m)?)?;
    m.add_function(wrap_pyfunction!(start_token_monitor, m)?)?;
    m.add_function(wrap_pyfunction!(stop_token_monitor, m)?)?;
    m.add_function(wrap_pyfunction!(get_pending_events, m)?)?;
    m.add_function(wrap_pyfunction!(add_wallet_to_monitor, m)?)?;
    m.add_function(wrap_pyfunction!(remove_wallet_from_monitor, m)?)?;
    m.add_function(wrap_pyfunction!(force_resync_nonce, m)?)?;
    m.add_function(wrap_pyfunction!(shutdown_rust_workers, m)?)?;

    m.add_function(wrap_pyfunction!(start_pool_scanner, m)?)?;
    m.add_function(wrap_pyfunction!(stop_pool_scanner, m)?)?;
    m.add_function(wrap_pyfunction!(get_best_pool_address, m)?)?;
    m.add_function(wrap_pyfunction!(get_all_pool_balances, m)?)?;
    m.add_function(wrap_pyfunction!(clear_pool_balances, m)?)?;
    m.add_function(wrap_pyfunction!(get_best_rpc_url, m)?)?;
    m.add_function(wrap_pyfunction!(get_healthy_rpc_urls, m)?)?;

    m.add_function(wrap_pyfunction!(execute_swap_hot, m)?)?;

    #[pyfn(m)]
    #[pyo3(name = "execute_approve_hot")]
    fn execute_approve_hot_py(py: Python<'_>, private_key_hex: String, token_address_str: String, 
    spender_address_str: String, chain_id: u64, amount_in_str: String, gas_limit: u64, manual_gas_price: u64) -> PyResult<String> {
        execute_approve_hot(py, private_key_hex, token_address_str, spender_address_str, chain_id, amount_in_str, gas_limit, manual_gas_price)
    }
    
    #[pyfn(m)]
    #[pyo3(name = "execute_batch_swap")]
    fn execute_batch_swap_py(
        py: Python<'_>, private_keys: Vec<String>, router_address_str: String, 
        chain_id: u64, method_type: String, amounts_in_strs: Vec<String>, 
        amounts_out_min_strs: Vec<String>, path_strs: Vec<String>, 
        deadline: u64, gas_limit: u64, value_str: String, 
        manual_gas_price: u64, v3_pool_fee: Option<u32> 
    ) -> PyResult<Vec<String>> {
        let fee = v3_pool_fee.unwrap_or(0); 
        execute_batch_swap(py, private_keys, router_address_str, chain_id, method_type, amounts_in_strs, amounts_out_min_strs, path_strs, 
            deadline, gas_limit, value_str, manual_gas_price, fee)
    }

    m.add_function(wrap_pyfunction!(init_or_load_keys, m)?)?;
    m.add_function(wrap_pyfunction!(get_public_key, m)?)?;
    
    #[pyfn(m)]
    #[pyo3(name = "start_pnl_tracker")]
    fn start_pnl_tracker_py(
        py: Python<'_>, rpc_url: String, wallet_addr: String, token_addr: String, quote_addr: String, 
        balance_wei_str: String, cost_wei_str: String, pool_type: String, v3_fee: u32, v2_router: String, v3_quoter: String   
    ) -> PyResult<()> {
        start_pnl_tracker(py, rpc_url, wallet_addr, token_addr, quote_addr, balance_wei_str, cost_wei_str, pool_type, v3_fee, v2_router, v3_quoter)
    }
    
    m.add_function(wrap_pyfunction!(stop_pnl_tracker, m)?)?;
    m.add_function(wrap_pyfunction!(get_pnl_status, m)?)?;

    Ok(())
}