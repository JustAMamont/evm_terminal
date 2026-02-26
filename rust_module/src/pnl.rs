use crate::state::{CORE_STATE, SHUTDOWN_FLAG};
use crate::bridge::{emit_event, EngineEvent};
use tokio::time::{sleep, Duration};
use std::sync::atomic::Ordering;
use ethers::utils::format_units;
use ethers::types::U256;

/// Безопасная конвертация U256 в f64 (работает даже если значение > u128::MAX)
fn u256_to_f64_safe(val: U256) -> f64 {
    if val.is_zero() {
        return 0.0;
    }
    
    // Если значение > u128::MAX, используем строковую конвертацию
    if val > U256::from(u128::MAX) {
        let s = format_units(val, 0).unwrap_or_else(|_| "0".to_string());
        return s.parse::<f64>().unwrap_or(0.0);
    }
    
    val.as_u128() as f64
}

pub async fn start_pnl_worker() {
    loop {
        if SHUTDOWN_FLAG.load(Ordering::SeqCst) { break; }
        
        let (prices, reserves, states, quote_symbol) = {
            let s = CORE_STATE.read().unwrap();
            (s.usd_prices.clone(), s.v2_reserves.clone(), s.v3_states.clone(), s.quote_symbol.clone())
        };

        // Получаем цену quote токена из usd_prices по динамическому символу
        let quote_price = prices.get(&quote_symbol).cloned().unwrap_or(1.0);

        for (pool_addr, (r_token, r_quote)) in reserves {
            if r_token.is_zero() || r_quote.is_zero() { 
                continue; 
            }
            
            // Безопасная конвертация резервов
            let r_token_f = u256_to_f64_safe(r_token);
            let r_quote_f = u256_to_f64_safe(r_quote);
            
            if r_token_f <= 0.0 {
                continue;
            }
            
            let price_in_quote = r_quote_f / r_token_f;
            
            if !price_in_quote.is_finite() || price_in_quote <= 0.0 {
                continue;
            }
            
            let final_price = price_in_quote * quote_price;

            emit_event(EngineEvent::PnLUpdate {
                wallet: "V2".into(),
                token: format!("{:?}", pool_addr),
                pnl_pct: 0.0,
                pnl_abs: format!("{:.4}$", final_price),
                current_value: format!("{:.2}$", final_price),
                current_price: final_price,
                is_loading: false,
            });
        }
        
        for (pool_addr, state) in states {
            if state.sqrt_price_x96.is_zero() { 
                continue; 
            }
            
            // Безопасная конвертация sqrt_price_x96
            let sqrt_p = u256_to_f64_safe(state.sqrt_price_x96) / 2.0f64.powi(96);
            let price = sqrt_p * sqrt_p;
            
            if !price.is_finite() || price <= 0.0 {
                continue;
            }
            
            let final_price = price * quote_price;

            emit_event(EngineEvent::PnLUpdate {
                wallet: "V3".into(),
                token: format!("{:?}", pool_addr),
                pnl_pct: 0.0,
                pnl_abs: format!("{:.4}$", final_price),
                current_value: format!("{:.2}$", final_price),
                current_price: final_price,
                is_loading: false,
            });
        }
        
        sleep(Duration::from_secs(2)).await;
    }
}
