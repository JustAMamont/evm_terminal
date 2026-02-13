use pyo3::prelude::*;
use pyo3::exceptions::PyValueError;
use ethers::prelude::*;
use ethers::providers::{Provider, Http};
use ethers::types::{Address, U256, Bytes};
use ethers::abi::AbiEncode;
use ethers::types::transaction::eip2718::TypedTransaction;
use std::str::FromStr;
use std::sync::Arc;
use futures::future::join_all;
use url::Url;

use crate::state::{RUNTIME, CORE_STATE, GLOBAL_HTTP_CLIENT, RPC_POOL};

abigen!(
    ITaxRouter,
    r#"[
        function swapExactTokensForTokens(uint amountIn, uint amountOutMin, address[] calldata path, address to, uint deadline) external
        function swapExactTokensForETH(uint amountIn, uint amountOutMin, address[] calldata path, address to, uint deadline) external
        function swapExactETHForTokens(uint amountOutMin, address[] calldata path, address to, uint deadline) external payable
        function swapV3Single(address tokenIn, address tokenOut, uint24 poolFee, uint256 amountIn, uint256 amountOutMin, address recipient, uint256 deadline) external returns (uint256 amountOut)
    ]"#,
);

const FIXED_GAS_PRICE: u64 = 100_000_000;

// Helper to get a provider from the global pool
fn get_http_provider() -> Result<Provider<Http>, String> {
    let url_str = {
        let mut pool = RPC_POOL.write().unwrap();
        pool.get_next_url().ok_or("No healthy RPC nodes available".to_string())?
    };
    let url = Url::parse(&url_str).map_err(|e| format!("Invalid RPC URL: {}", e))?;
    let client = GLOBAL_HTTP_CLIENT.clone();
    Ok(Provider::new(Http::new_with_client(url, client)))
}


#[pyfunction]
pub fn execute_approve_hot(py: Python<'_>, private_key_hex: String, token_address_str: String, spender_address_str: String, chain_id: u64, amount_in_str: String, gas_limit: u64, manual_gas_price: u64) -> PyResult<String> {
    let token_addr = Address::from_str(&token_address_str).map_err(|e| PyValueError::new_err(format!("Bad token: {}", e)))?;
    let spender_addr = Address::from_str(&spender_address_str).map_err(|e| PyValueError::new_err(format!("Bad spender: {}", e)))?;
    
    let amount_to_approve = if amount_in_str == "MAX" {
        U256::MAX
    } else {
        U256::from_dec_str(&amount_in_str).map_err(|_| PyValueError::new_err("Invalid amount for approve"))?
    };

    let mut calldata = Vec::new();
    calldata.extend_from_slice(&[0x09, 0x5e, 0xa7, 0xb3]);
    calldata.extend_from_slice(&[0u8; 12]);
    calldata.extend_from_slice(spender_addr.as_bytes());
    
    let mut amount_bytes = [0u8; 32];
    amount_to_approve.to_big_endian(&mut amount_bytes);
    calldata.extend_from_slice(&amount_bytes);

    let wallet: LocalWallet = private_key_hex.parse().map_err(|e| PyValueError::new_err(format!("Bad PK: {:?}", e)))?;
    let wallet = wallet.with_chain_id(chain_id);
    let my_address = wallet.address();
    
    let (nonce, gas_price) = {
        let state = CORE_STATE.read().unwrap();
        let gp = if manual_gas_price > 0 { U256::from(manual_gas_price) } 
                 else if state.gas_price.is_zero() { U256::from(FIXED_GAS_PRICE) } else { state.gas_price };
        let n = match state.nonce_map.get(&my_address) {
            Some(&n) => U256::from(n),
            None => return Err(PyValueError::new_err("Nonce missing")),
        };
        (n, gp)
    };
    
    let tx_req = TransactionRequest::new()
        .to(token_addr)
        .nonce(nonce)
        .gas_price(gas_price)
        .gas(gas_limit)
        .data(Bytes::from(calldata)); 

    let typed_tx = TypedTransaction::Legacy(tx_req);
    let signature = wallet.sign_transaction_sync(&typed_tx).map_err(|e| PyValueError::new_err(format!("Sign failed: {:?}", e)))?;
    let signed = typed_tx.rlp_signed(&signature);
    
    let pending_res: Result<TxHash, String> = py.allow_threads(move || {
        let provider = get_http_provider()?;
        let res = RUNTIME.block_on(async { provider.send_raw_transaction(Bytes::from(signed)).await });
        res.map(|p| p.tx_hash()).map_err(|e| format!("Provider error: {}", e))
    });

    let tx_hash = pending_res.map_err(|e| PyValueError::new_err(format!("Broadcast failed: {}", e)))?;
    
    { let mut state_write = CORE_STATE.write().unwrap(); if let Some(n) = state_write.nonce_map.get_mut(&my_address) { *n += 1; } }
    Ok(format!("{:?}", tx_hash))
}


#[pyfunction]
pub fn execute_swap_hot(py: Python<'_>, private_key_hex: String, router_address_str: String, chain_id: u64, method_type: String, amount_in_str: String, amount_out_min_str: String, path_strs: Vec<String>, to_str: String, deadline: u64, gas_limit: u64, value_str: String, manual_gas_price: u64) -> PyResult<String> {
    let to_addr = Address::from_str(&to_str).unwrap();
    let router_addr = Address::from_str(&router_address_str).unwrap();
    let amount_in = U256::from_dec_str(&amount_in_str).unwrap();
    let amount_out_min = U256::from_dec_str(&amount_out_min_str).unwrap();
    let path: Vec<Address> = path_strs.iter().map(|s| Address::from_str(s).unwrap()).collect();
    let deadline_u256 = U256::from(deadline);
    let value = U256::from_dec_str(&value_str).unwrap();
    let wallet: LocalWallet = private_key_hex.parse().unwrap();
    let wallet = wallet.with_chain_id(chain_id);
    let my_address = wallet.address();
    
    let (nonce, gas_price) = {
        let state = CORE_STATE.read().unwrap();
        let gp = if manual_gas_price > 0 { U256::from(manual_gas_price) } 
                 else if state.gas_price.is_zero() { U256::from(FIXED_GAS_PRICE) } else { state.gas_price };
        let n = match state.nonce_map.get(&my_address) { Some(&n) => U256::from(n), None => return Err(PyValueError::new_err("Nonce missing")) };
        (n, gp)
    };
    
    let calldata = match method_type.as_str() {
        "TokensForTokens" => SwapExactTokensForTokensCall { amount_in, amount_out_min, path: path.clone(), to: to_addr, deadline: deadline_u256 }.encode(),
        "TokensForETH" => SwapExactTokensForETHCall { amount_in, amount_out_min, path: path.clone(), to: to_addr, deadline: deadline_u256 }.encode(),
        "ETHForTokens" => SwapExactETHForTokensCall { amount_out_min, path: path.clone(), to: to_addr, deadline: deadline_u256 }.encode(),
        _ => return Err(PyValueError::new_err("Unknown method")),
    };
    
    let tx_req = TransactionRequest::new().to(router_addr).nonce(nonce).gas_price(gas_price).gas(gas_limit).data(calldata).value(value);
    let typed_tx = TypedTransaction::Legacy(tx_req);
    let signature = wallet.sign_transaction_sync(&typed_tx).unwrap();
    let signed_tx_bytes = typed_tx.rlp_signed(&signature);
    
    let pending_res: Result<TxHash, String> = py.allow_threads(move || {
        let provider = get_http_provider()?;
        let res = RUNTIME.block_on(async { provider.send_raw_transaction(Bytes::from(signed_tx_bytes)).await });
        res.map(|p| p.tx_hash()).map_err(|e| format!("Provider error: {}", e))
    });

    let tx_hash = pending_res.map_err(|e| PyValueError::new_err(format!("Broadcast failed: {}", e)))?;

    { let mut state_write = CORE_STATE.write().unwrap(); if let Some(n) = state_write.nonce_map.get_mut(&my_address) { *n += 1; } }
    Ok(format!("{:?}", tx_hash))
}

#[pyfunction]
pub fn execute_batch_swap(py: Python<'_>, private_keys: Vec<String>, router_address_str: String, chain_id: u64, method_type: String, amounts_in_strs: Vec<String>, amounts_out_min_strs: Vec<String>, path_strs: Vec<String>, deadline: u64, gas_limit: u64, value_str: String, manual_gas_price: u64, v3_pool_fee: u32) -> PyResult<Vec<String>> {
    let results = py.allow_threads(move || {
        let router_addr = Address::from_str(&router_address_str).unwrap();
        let path: Vec<Address> = path_strs.iter().map(|s| Address::from_str(s).unwrap()).collect();
        let deadline_u256 = U256::from(deadline);
        let value = U256::from_dec_str(&value_str).unwrap();
        
        let provider = match get_http_provider() {
            Ok(p) => Arc::new(p),
            Err(e) => return vec![format!("Error: {}", e)],
        };
        
        RUNTIME.block_on(async {
            let mut futures = Vec::new();
            for (i, pk) in private_keys.into_iter().enumerate() {
                let provider_clone = provider.clone();
                let method_clone = method_type.clone();
                let path_clone = path.clone();
                let amt_in_str = amounts_in_strs.get(i).unwrap_or(&"0".to_string()).clone();
                let amt_min_str = amounts_out_min_strs.get(i).unwrap_or(&"0".to_string()).clone();
                futures.push(async move {
                    let amount_in = U256::from_dec_str(&amt_in_str).unwrap_or_default();
                    let amount_out_min = U256::from_dec_str(&amt_min_str).unwrap_or_default();
                    let wallet: LocalWallet = match pk.parse() { Ok(w) => w, Err(_) => return "Error: Invalid PK".to_string() };
                    let wallet = wallet.with_chain_id(chain_id);
                    let my_address = wallet.address();
                    let (nonce, gas_price) = {
                        let state = CORE_STATE.read().unwrap();
                        let gp = if manual_gas_price > 0 { U256::from(manual_gas_price) } 
                                 else if state.gas_price.is_zero() { U256::from(FIXED_GAS_PRICE) } else { state.gas_price };
                        let n = match state.nonce_map.get(&my_address) { Some(&n) => U256::from(n), None => return "Error: Nonce not synced".to_string() };
                        (n, gp)
                    };

                    let calldata = match method_clone.as_str() {
                        // *** ВОЗВРАЩАЕМ `amount_in` ***
                        "TokensForTokens" => SwapExactTokensForTokensCall { amount_in, amount_out_min, path: path_clone, to: my_address, deadline: deadline_u256 }.encode(),
                        "TokensForETH" => SwapExactTokensForETHCall { amount_in, amount_out_min, path: path_clone, to: my_address, deadline: deadline_u256 }.encode(),
                        "ETHForTokens" => SwapExactETHForTokensCall { amount_out_min, path: path_clone, to: my_address, deadline: deadline_u256 }.encode(),
                        "V3Swap" => {
                            let token_in = path_clone[0];
                            let token_out = path_clone[1];
                            SwapV3SingleCall {
                                token_in,
                                token_out,
                                pool_fee: v3_pool_fee,
                                amount_in,
                                amount_out_min,
                                recipient: my_address,
                                deadline: deadline_u256,
                            }.encode()
                        },
                        _ => return "Error: Unknown method".to_string(),
                    };
                    let tx_req = TransactionRequest::new().to(router_addr).nonce(nonce).gas_price(gas_price).gas(gas_limit).data(calldata).value(value);
                    let typed_tx = TypedTransaction::Legacy(tx_req);
                    let signature = wallet.sign_transaction_sync(&typed_tx).unwrap();
                    let signed = typed_tx.rlp_signed(&signature);
                    match provider_clone.send_raw_transaction(Bytes::from(signed)).await {
                        Ok(pending) => { { let mut state_write = CORE_STATE.write().unwrap(); if let Some(n) = state_write.nonce_map.get_mut(&my_address) { *n += 1; } } format!("{:?}", pending.tx_hash()) },
                        Err(e) => format!("Error: Broadcast failed {}", e),
                    }
                });
            }
            join_all(futures).await
        })
    });
    
    Ok(results)
}