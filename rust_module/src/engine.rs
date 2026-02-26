use pyo3::prelude::*;
use tokio::sync::mpsc;
use once_cell::sync::Lazy;
use ethers::prelude::*;
use std::sync::atomic::Ordering;
use std::str::FromStr;

use crate::bridge::{EngineCommand, EngineEvent, emit_event, emit_log};
use crate::state::{RUNTIME, SHUTDOWN_FLAG, CORE_STATE, RPC_POOL, RpcNode, TRACKED_WALLETS, MONITOR_HANDLE, INTERNAL_HANDLE, RPC_CHECKER_HANDLE, PNL_HANDLE};
use crate::monitor;
use crate::execution;
use crate::pnl;

pub static COMMAND_TX: Lazy<mpsc::UnboundedSender<EngineCommand>> = Lazy::new(|| {
    let (tx, rx) = mpsc::unbounded_channel::<EngineCommand>();
    RUNTIME.spawn(engine_loop(rx));
    tx
});

fn bnb_to_wei(bnb: f64) -> U256 {
    if bnb <= 0.0 { return U256::zero(); }
    U256::from((bnb * 1e18) as u128)
}

async fn engine_loop(mut rx: mpsc::UnboundedReceiver<EngineCommand>) {
    emit_log("SUCCESS", "Rust Engine Core: Active".into());
    
    while let Some(cmd) = rx.recv().await {
        match cmd {
            EngineCommand::Init { 
                rpc_url, wss_url, chain_id, router, quoter, v2_factory, v3_factory, 
                wrapped_native, native_address, wallets, public_rpc_urls, fuel_settings,
                quote_symbol, quote_tokens
            } => {
                SHUTDOWN_FLAG.store(true, Ordering::Relaxed);
                
                if let Some(h) = MONITOR_HANDLE.lock().unwrap().take() { h.abort(); }
                if let Some(h) = INTERNAL_HANDLE.lock().unwrap().take() { h.abort(); }
                if let Some(h) = PNL_HANDLE.lock().unwrap().take() { h.abort(); }
                if let Some(h) = RPC_CHECKER_HANDLE.lock().unwrap().take() { h.abort(); }
                
                tokio::time::sleep(std::time::Duration::from_millis(50)).await;
                SHUTDOWN_FLAG.store(false, Ordering::Relaxed);

                let router_addr = Address::from_str(&router).unwrap();
                let quoter_addr = Address::from_str(&quoter).unwrap();
                let v2_fact = Address::from_str(&v2_factory).unwrap_or(Address::zero());
                let v3_fact = Address::from_str(&v3_factory).unwrap_or(Address::zero());
                let w_native = Address::from_str(&wrapped_native).unwrap_or(Address::zero());
                let native = Address::from_str(&native_address).unwrap_or(Address::zero());

                let fuel_threshold = bnb_to_wei(fuel_settings.auto_fuel_threshold);
                let fuel_amount = bnb_to_wei(fuel_settings.auto_fuel_amount);
                let fuel_quote_address = Address::from_str(&fuel_settings.fuel_quote_address).unwrap_or(Address::zero());
                let fuel_enabled = fuel_settings.auto_fuel_enabled;

                let mut all_urls = public_rpc_urls; 
                all_urls.push(rpc_url.clone());
                RPC_POOL.write().unwrap().nodes = all_urls.iter().map(|u| RpcNode { 
                    url: u.clone(), latency: u128::MAX, is_private: u == &rpc_url, fails: 0 
                }).collect();

                {
                    let mut s = CORE_STATE.write().unwrap();
                    
                    s.v2_reserves.clear();
                    s.v3_states.clear();
                    s.decimals_cache.clear(); 
                    s.usd_prices.clear();
                    s.nonce_map.clear();
                    s.pending_txs.clear();
                    s.wallet_keys.clear();

                    s.chain_id = chain_id; 
                    s.router_address = router_addr; 
                    s.quoter_address = quoter_addr; 
                    s.v2_factory_address = v2_fact; 
                    s.v3_factory_address = v3_fact; 
                    s.wrapped_native_address = w_native; 
                    s.native_address = native;
                    s.wss_url = wss_url.clone(); 
                    
                    s.fuel_enabled = fuel_enabled;
                    s.fuel_threshold = fuel_threshold;
                    s.fuel_amount = fuel_amount;
                    s.fuel_quote_address = fuel_quote_address;
                    s.quote_symbol = quote_symbol.clone();
                    s.quote_tokens = quote_tokens.into_iter()
                        .filter_map(|(k, v)| Address::from_str(&v).ok().map(|a| (k, a)))
                        .collect();
                    
                    TRACKED_WALLETS.write().unwrap().clear();
                    for (a, k) in wallets { 
                        if let Ok(addr) = Address::from_str(&a) { 
                            s.wallet_keys.insert(addr, k); 
                            TRACKED_WALLETS.write().unwrap().push(addr); 
                        } 
                    }
                }
                
                if fuel_enabled {
                    emit_log("INFO", format!(
                        "⛽ Auto-Fuel включен: порог={:.6}, amount={:.6}, quote={:?}", 
                        fuel_settings.auto_fuel_threshold,
                        fuel_settings.auto_fuel_amount,
                        fuel_quote_address
                    ));
                }
                
                if !quote_symbol.is_empty() {
                    emit_log("INFO", format!("💱 Quote symbol установлен: {}", quote_symbol));
                }
                
                *RPC_CHECKER_HANDLE.lock().unwrap() = Some(RUNTIME.spawn(monitor::rpc_health_checker(all_urls)).abort_handle());
                
                let wss_bg = wss_url.clone();
                *INTERNAL_HANDLE.lock().unwrap() = Some(RUNTIME.spawn(monitor::start_background_worker(wss_bg)).abort_handle());
                
                *PNL_HANDLE.lock().unwrap() = Some(RUNTIME.spawn(pnl::start_pnl_worker()).abort_handle());
                
                emit_event(EngineEvent::EngineReady);
                emit_event(EngineEvent::ConnectionStatus {
                    connected: true,
                    message: "Ядро инициализировано".into()
                });
            }

            EngineCommand::SwitchToken { token_address, quote_address, quote_symbol } => {
                let t = Address::from_str(&token_address).unwrap();
                let q = Address::from_str(&quote_address).unwrap();

                let all_quotes: Vec<(String, Address)> = {
                    let s = CORE_STATE.read().unwrap();
                    s.quote_tokens.iter().map(|(k, v)| (k.clone(), *v)).collect()
                };
                
                {
                    let mut s = CORE_STATE.write().unwrap();
                    // ОЧИСТКА ДАННЫХ ПРЕДЫДУЩЕГО ПУЛА
                    s.selected_pool_type = None;
                    s.selected_pool_fee = 0;
                    s.selected_pool_address = None;
                    s.selected_pool_liquidity_usd = 0.0;
                    s.selected_pool_spot_price = 0.0;
                    s.v2_reserves.clear();
                    s.v3_states.clear();
                    
                    s.fuel_quote_address = q;
                    s.quote_symbol = quote_symbol.clone();
                    emit_log("INFO", format!("🔄 Quote токен установлен: {:?} ({})", q, quote_symbol));
                }
                
                RUNTIME.spawn(async move {
                    execution::check_and_auto_approve_background(t, q).await;
                });

                if let Some(old) = MONITOR_HANDLE.lock().unwrap().take() { 
                    old.abort(); 
                }
                
                let wss = { CORE_STATE.read().unwrap().wss_url.clone() };
                let handle = RUNTIME.spawn(monitor::start_unified_websocket_monitor(wss, t, q, all_quotes));
                *MONITOR_HANDLE.lock().unwrap() = Some(handle.abort_handle());
            }

            EngineCommand::UnsubscribeToken { token_address } => {
                // Отписка от токена - очистка состояния
                emit_log("INFO", format!("📭 Отписка от токена: {}", token_address));
                
                let mut s = CORE_STATE.write().unwrap();
                s.selected_pool_address = None;
                s.selected_pool_type = None;
                s.selected_pool_fee = 0;
                s.selected_pool_liquidity_usd = 0.0;
                s.selected_pool_spot_price = 0.0;
                
                emit_log("SUCCESS", "📭 Состояние токена очищено".into());
            }
            
            EngineCommand::CalcImpact { token_address, quote_address, amount_in, is_buy } => {
                let t_addr = Address::from_str(&token_address).unwrap();
                let q_addr = Address::from_str(&quote_address).unwrap();
                RUNTIME.spawn(async move {
                    let (t_in, t_out) = if is_buy { (q_addr, t_addr) } else { (t_addr, q_addr) };
                    let (p_type, p_fee, quoter) = { 
                        let s = CORE_STATE.read().unwrap(); 
                        (s.selected_pool_type.clone().unwrap_or_default(), s.selected_pool_fee, s.quoter_address) 
                    };
                    
                    let dec_in = monitor::get_decimals_cached(t_in).await;
                    let dec_out = monitor::get_decimals_cached(t_out).await;
                    
                    let amt_wei: U256 = match ethers::utils::parse_units(amount_in, dec_in as u32) { 
                        Ok(v) => v.into(), 
                        Err(_) => {
                            emit_event(EngineEvent::ImpactUpdate { 
                                token: token_address, quote: quote_address.clone(), amount_in, impact_pct: 0.0, expected_out: "0".into(), is_buy
                            });
                            return;
                        }
                    };
                    
                    if amt_wei.is_zero() { 
                        emit_event(EngineEvent::ImpactUpdate { 
                            token: token_address, quote: quote_address.clone(), amount_in, impact_pct: 0.0, expected_out: "0".into(), is_buy
                        });
                        return; 
                    }

                    if p_type.is_empty() {
                        emit_event(EngineEvent::ImpactUpdate { 
                            token: token_address, quote: quote_address.clone(), amount_in, impact_pct: 0.0, expected_out: "0".into(), is_buy
                        });
                        return;
                    }

                    let exp_out = if p_type == "V3" { 
                        // Проверяем что V3 пул реально существует
                        let has_v3_state = { 
                            let s = CORE_STATE.read().unwrap(); 
                            !s.v3_states.is_empty() && s.selected_pool_address.is_some()
                        };
                        if !has_v3_state {
                            emit_log("DEBUG", "CalcImpact: V3 pool not selected, skipping quoter".to_string());
                            U256::zero()
                        } else {
                            execution::calculate_expected_out_v3_quoted(t_in, t_out, amt_wei, p_fee, quoter).await 
                        }
                    } else { 
                        // Проверяем что V2 пул реально существует
                        let has_v2_reserves = { 
                            let s = CORE_STATE.read().unwrap(); 
                            !s.v2_reserves.is_empty() && s.selected_pool_address.is_some()
                        };
                        if !has_v2_reserves {
                            emit_log("DEBUG", "CalcImpact: V2 pool not selected".to_string());
                            U256::zero()
                        } else {
                            execution::calculate_expected_out_v2_pure(t_in, t_out, amt_wei) 
                        }
                    };
                    
                    let idl_out = execution::calculate_ideal_out(t_in, t_out, amt_wei, dec_in, is_buy, dec_out);
                    
                    let impact = if !idl_out.is_zero() && exp_out <= idl_out {
                        let idl_f = execution::u256_to_f64_safe(idl_out, dec_out as u32);
                        let exp_f = execution::u256_to_f64_safe(exp_out, dec_out as u32);
                        if idl_f > 0.0 { ((idl_f - exp_f) / idl_f) * 100.0 } else { 0.0 }
                    } else { 0.0 };
                    
                    emit_event(EngineEvent::ImpactUpdate { 
                        token: token_address, quote: quote_address, amount_in, impact_pct: impact, expected_out: exp_out.to_string(), is_buy
                    });
                });
            }
            
            EngineCommand::ExecuteTrade { action, token, quote_token, amount, wallets, gas_gwei, slippage, v3_fee, amounts_wei } => {
                let t_addr = Address::from_str(&token).unwrap();
                let q_addr = Address::from_str(&quote_token).unwrap();
                let (r, k, g, c) = {
                    let s = CORE_STATE.read().unwrap();
                    let keys = wallets.iter()
                        .filter_map(|w| Address::from_str(w).ok().and_then(|a| s.wallet_keys.get(&a).cloned()))
                        .collect();
                    (s.router_address, keys, if gas_gwei > 0.0 { gas_gwei } else { s.manual_gas_price_gwei }, s.chain_id)
                };
                RUNTIME.spawn(async move {
                    let evs = execution::run_batch_trade(k, r, action, t_addr, q_addr, amount, g, slippage, v3_fee, c, amounts_wei).await;
                    for e in evs { emit_event(e); }
                });
            }

            EngineCommand::UpdatePrice { symbol, price } => { 
                CORE_STATE.write().unwrap().usd_prices.insert(symbol, price); 
            }
            
            EngineCommand::UpdateTokenDecimals { address, decimals } => {
                if let Ok(a) = Address::from_str(&address) { 
                    CORE_STATE.write().unwrap().decimals_cache.insert(a, decimals); 
                }
            }
            
            EngineCommand::UpdateSettings { gas_price_gwei, slippage, fuel_enabled, fuel_quote_address, rpc_url, wss_url, quote_symbol } => {
                let mut s = CORE_STATE.write().unwrap();
                if let Some(v) = gas_price_gwei { s.manual_gas_price_gwei = v; }
                if let Some(v) = slippage { s.slippage = v; }
                
                if let Some(enabled) = fuel_enabled {
                    s.fuel_enabled = enabled;
                    emit_log("INFO", format!("⛽ Auto-Fuel: {}", if enabled { "ВКЛЮЧЕН" } else { "ВЫКЛЮЧЕН" }));
                }
                
                if let Some(quote_addr_str) = fuel_quote_address {
                    if let Ok(quote_addr) = Address::from_str(&quote_addr_str) {
                        s.fuel_quote_address = quote_addr;
                        emit_log("INFO", format!("🔄 Quote токен для мониторинга: {:?}", quote_addr));
                    }
                }
                
                if let Some(sym) = quote_symbol {
                    s.quote_symbol = sym.clone();
                    emit_log("INFO", format!("💱 Quote symbol обновлен: {}", sym));
                }
                
                if let Some(new_rpc) = rpc_url {
                    let mut pool = RPC_POOL.write().unwrap(); 
                    pool.nodes.clear();
                    pool.nodes.push(RpcNode { url: new_rpc.clone(), latency: 0, is_private: true, fails: 0 });
                }
                
                if let Some(new_wss) = wss_url {
                    s.wss_url = new_wss.clone();
                    if let Some(h) = INTERNAL_HANDLE.lock().unwrap().take() { h.abort(); }
                    *INTERNAL_HANDLE.lock().unwrap() = Some(RUNTIME.spawn(monitor::start_background_worker(new_wss)).abort_handle());
                }
            }
            
            EngineCommand::RefreshBalance { wallet, token } => {
                let wallet_addr = Address::from_str(&wallet).ok();
                let token_addr = Address::from_str(&token).ok();
                
                if let (Some(w), Some(t)) = (wallet_addr, token_addr) {
                    RUNTIME.spawn(async move {
                        if t == Address::zero() || t == Address::from_str("0xeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee").unwrap() {
                            let url_opt = { let p = RPC_POOL.read().unwrap(); p.get_fastest_node() };
                            if let Some(url_str) = url_opt {
                                if let Ok(url) = url::Url::parse(&url_str) {
                                    let provider = Provider::new(Http::new_with_client(url, crate::state::GLOBAL_HTTP_CLIENT.clone()));
                                    if let Ok(balance) = provider.get_balance(w, None).await {
                                        let float_val = balance.as_u128() as f64 / 1e18;
                                        emit_event(EngineEvent::BalanceUpdate {
                                            wallet: format!("{:?}", w),
                                            token: "0xeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee".into(),
                                            wei: balance.to_string(),
                                            float_val,
                                            symbol: "NATIVE".into()
                                        });
                                    }
                                }
                            }
                        } else {
                            let balance = execution::get_token_balance(t, w).await;
                            let decimals = monitor::get_decimals_cached(t).await;
                            let float_val = execution::u256_to_f64_safe(balance, decimals as u32);
                            emit_event(EngineEvent::BalanceUpdate {
                                wallet: format!("{:?}", w),
                                token: format!("{:?}", t),
                                wei: balance.to_string(),
                                float_val,
                                symbol: "TOKEN".into()
                            });
                        }
                    });
                }
            }

            EngineCommand::AddWallet { address, private_key } => {
                if let Ok(addr) = Address::from_str(&address) {
                    CORE_STATE.write().unwrap().wallet_keys.insert(addr, private_key);
                    emit_log("INFO", format!("🔑 Кошелек добавлен: {:?}", addr));
                }
            }
            
            EngineCommand::RefreshAllBalances => {
                let wallets: Vec<Address> = TRACKED_WALLETS.read().unwrap().clone();
                let quote_token = { CORE_STATE.read().unwrap().fuel_quote_address };
                
                RUNTIME.spawn(async move {
                    let url_opt = { let p = RPC_POOL.read().unwrap(); p.get_fastest_node() };
                    if let Some(url_str) = url_opt {
                        if let Ok(url) = url::Url::parse(&url_str) {
                            let provider = Provider::new(Http::new_with_client(url, crate::state::GLOBAL_HTTP_CLIENT.clone()));
                            
                            for wallet in &wallets {
                                if let Ok(balance) = provider.get_balance(*wallet, None).await {
                                    let float_val = balance.as_u128() as f64 / 1e18;
                                    emit_event(EngineEvent::BalanceUpdate {
                                        wallet: format!("{:?}", wallet),
                                        token: "0xeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee".into(),
                                        wei: balance.to_string(),
                                        float_val,
                                        symbol: "NATIVE".into()
                                    });
                                }
                            }
                            
                            if quote_token != Address::zero() {
                                let decimals = monitor::get_decimals_cached(quote_token).await;
                                for wallet in &wallets {
                                    let balance = execution::get_token_balance(quote_token, *wallet).await;
                                    let float_val = execution::u256_to_f64_safe(balance, decimals as u32);
                                    emit_event(EngineEvent::BalanceUpdate {
                                        wallet: format!("{:?}", wallet),
                                        token: format!("{:?}", quote_token),
                                        wei: balance.to_string(),
                                        float_val,
                                        symbol: "QUOTE".into()
                                    });
                                }
                            }
                        }
                    }
                });
            }
            
            EngineCommand::Shutdown => { 
                SHUTDOWN_FLAG.store(true, Ordering::Relaxed); 
                if let Some(h) = MONITOR_HANDLE.lock().unwrap().take() { h.abort(); }
                if let Some(h) = INTERNAL_HANDLE.lock().unwrap().take() { h.abort(); }
                if let Some(h) = PNL_HANDLE.lock().unwrap().take() { h.abort(); }
                if let Some(h) = RPC_CHECKER_HANDLE.lock().unwrap().take() { h.abort(); }
                break;
            }
        }
    }
}

#[pyfunction]
pub fn push_to_engine(_py: Python<'_>, command_json: String) -> PyResult<()> {
    let cmd: EngineCommand = match serde_json::from_str(&command_json) { 
        Ok(c) => c, 
        Err(e) => return Err(pyo3::exceptions::PyValueError::new_err(e.to_string())) 
    };
    let _ = COMMAND_TX.send(cmd);
    Ok(())
}