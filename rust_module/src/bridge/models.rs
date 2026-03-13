use serde::{Serialize, Deserialize};
use super::pack::*;

// ===================== ENGINE EVENTS =====================

#[derive(Serialize, Clone, Debug)]
#[serde(tag = "type", content = "data")]
pub enum EngineEvent {
    EngineReady,
    
    Log { 
        level: String, 
        message: String 
    },

    BalanceUpdate { 
        wallet: String, 
        token: String, 
        wei: String, 
        float_val: f64, 
        symbol: String 
    },

    PoolDetected { 
        pool_type: String, 
        address: String, 
        token: String, 
        quote: String,
        liquidity_usd: f64, 
        fee: u32, 
        spot_price: f64,
        token_symbol: String,
        token_name: String
    },

    PoolUpdate { 
        pool_address: String, 
        pool_type: String, 
        token: String, 
        quote: String,
        reserve0: Option<String>, 
        reserve1: Option<String>, 
        sqrt_price_x96: Option<String>, 
        tick: Option<i32>, 
        liquidity: Option<u128>, 
        spot_price: Option<f64>, 
        liquidity_usd: Option<f64> 
    },

    PoolNotFound { 
        token: String,
        selected_quote: String,
        available_quotes: Vec<(String, String)> // (Symbol, Address)
    },

    PnLUpdate { 
        wallet: String, 
        token: String, 
        pnl_pct: f64, 
        pnl_abs: String, 
        current_value: String, 
        current_price: f64, 
        is_loading: bool 
    },

    ImpactUpdate { 
        token: String, 
        quote: String,
        amount_in: f64, 
        impact_pct: f64, 
        expected_out: String, 
        is_buy: bool 
    },

    TradeStatus { 
        wallet: String, 
        action: String, 
        status: String, 
        message: String, 
        tx_hash: Option<String>,
        token_address: String,
        amount: f64,
        tokens_received: Option<String>,
        tokens_sold: Option<String>,
        token_decimals: u8
    },

    GasPriceUpdate { gas_price_gwei: f64 },

    ConnectionStatus { connected: bool, message: String },

    TxSent { 
        tx_hash: String, 
        wallet: String, 
        action: String, 
        amount: f64, 
        token: String, 
        timestamp_ms: u64 
    },

    TxConfirmed { 
        tx_hash: String, 
        wallet: String, 
        gas_used: u64, 
        status: String, 
        confirm_block: u64, 
        timestamp_ms: u64 
    },

    AutoFuelError {
        wallet: String,
        reason: String
    }
}

// ===================== AUTO-FUEL SETTINGS =====================

#[derive(Deserialize, Debug, Clone)]
pub struct AutoFuelSettingsData {
    #[serde(default)]
    pub auto_fuel_enabled: bool,
    #[serde(default = "default_threshold")]
    pub auto_fuel_threshold: f64,
    #[serde(default = "default_amount")]
    pub auto_fuel_amount: f64,
    #[serde(default)]
    pub fuel_quote_address: String,
}

fn default_threshold() -> f64 { 0.005 }
fn default_amount() -> f64 { 0.01 }

// ===================== ENGINE COMMANDS =====================

#[derive(Deserialize, Debug)]
#[serde(tag = "type", content = "data")]
pub enum EngineCommand {
    Init { 
        rpc_url: String, 
        wss_url: String, 
        chain_id: u64, 
        router: String, 
        quoter: String,
        v2_factory: String,
        v3_factory: String,
        wrapped_native: String,
        native_address: String,
        wallets: Vec<(String, String)>,
        public_rpc_urls: Vec<String>,
        fuel_settings: AutoFuelSettingsData,
        #[serde(default)]
        quote_symbol: String,
        #[serde(default)]
        quote_tokens: std::collections::HashMap<String, String>
    },
    
    ExecuteTrade {
        action: String,
        token: String,
        quote_token: String, 
        amount: f64,
        wallets: Vec<String>,
        gas_gwei: f64,
        slippage: f64,
        v3_fee: u32,
        #[serde(default)]
        amounts_wei: Option<std::collections::HashMap<String, String>>,
    },
    
    CalcImpact {
        token_address: String,
        quote_address: String,
        amount_in: f64,
        is_buy: bool
    },
    
    UpdatePrice { symbol: String, price: f64 },
    UpdateTokenDecimals { address: String, decimals: u8 },
    
    UpdateSettings {
        gas_price_gwei: Option<f64>,
        slippage: Option<f64>,
        fuel_enabled: Option<bool>,
        fuel_quote_address: Option<String>,
        rpc_url: Option<String>,
        wss_url: Option<String>,
        #[serde(default)]
        quote_symbol: Option<String>,
    },
    
    SwitchToken { 
        token_address: String, 
        quote_address: String,
        #[serde(default)]
        quote_symbol: String,
    },
    UnsubscribeToken {
        token_address: String
    },
    AddWallet { address: String, private_key: String },
    RefreshBalance { wallet: String, token: String },
    RefreshAllBalances,
    Shutdown
}

// ===================== PACKABLE IMPL =====================

impl Packable for EngineEvent {
    fn pack(&self, w: &mut Vec<u8>) {
        match self {
            EngineEvent::EngineReady => {
                pack_u16(w, super::pack::EventType::EngineReady as u16);
            }
            EngineEvent::Log { level, message } => {
                pack_u16(w, super::pack::EventType::Log as u16);
                pack_string(w, level);
                pack_string(w, message);
            }
            EngineEvent::BalanceUpdate { wallet, token, wei, float_val, symbol } => {
                pack_u16(w, super::pack::EventType::BalanceUpdate as u16);
                pack_string(w, wallet);
                pack_string(w, token);
                pack_string(w, wei);
                pack_f64(w, *float_val);
                pack_string(w, symbol);
            }
            EngineEvent::PoolDetected { pool_type, address, token, quote, liquidity_usd, fee, spot_price, token_symbol, token_name } => {
                pack_u16(w, super::pack::EventType::PoolDetected as u16);
                pack_string(w, pool_type);
                pack_string(w, address);
                pack_string(w, token);
                pack_string(w, quote);
                pack_f64(w, *liquidity_usd);
                pack_u32(w, *fee);
                pack_f64(w, *spot_price);
                pack_string(w, token_symbol);
                pack_string(w, token_name);
            }
            EngineEvent::PoolUpdate { pool_address, pool_type, token, quote, reserve0, reserve1, sqrt_price_x96, tick, liquidity, spot_price, liquidity_usd } => {
                pack_u16(w, super::pack::EventType::PoolUpdate as u16);
                pack_string(w, pool_address);
                pack_string(w, pool_type);
                pack_string(w, token);
                pack_string(w, quote);
                pack_bool(w, reserve0.is_some()); if let Some(v) = reserve0 { pack_string(w, v); }
                pack_bool(w, reserve1.is_some()); if let Some(v) = reserve1 { pack_string(w, v); }
                pack_bool(w, sqrt_price_x96.is_some()); if let Some(v) = sqrt_price_x96 { pack_string(w, v); }
                pack_bool(w, tick.is_some()); if let Some(v) = tick { pack_u32(w, *v as u32); }
                pack_bool(w, liquidity.is_some()); if let Some(v) = liquidity { pack_u64(w, (*v >> 64) as u64); pack_u64(w, *v as u64); }
                pack_bool(w, spot_price.is_some()); if let Some(v) = spot_price { pack_f64(w, *v); }
                pack_bool(w, liquidity_usd.is_some()); if let Some(v) = liquidity_usd { pack_f64(w, *v); }
            }
            EngineEvent::PoolNotFound { token, selected_quote, available_quotes } => {
                pack_u16(w, super::pack::EventType::PoolNotFound as u16);
                pack_string(w, token);
                pack_string(w, selected_quote);
                pack_u16(w, available_quotes.len() as u16);
                for (s, a) in available_quotes { pack_string(w, s); pack_string(w, a); }
            }
            EngineEvent::PnLUpdate { wallet, token, pnl_pct, pnl_abs, current_value, current_price, is_loading } => {
                pack_u16(w, super::pack::EventType::PnLUpdate as u16);
                pack_string(w, wallet);
                pack_string(w, token);
                pack_f64(w, *pnl_pct);
                pack_string(w, pnl_abs);
                pack_string(w, current_value);
                pack_f64(w, *current_price);
                pack_bool(w, *is_loading);
            }
            EngineEvent::ImpactUpdate { token, quote, amount_in, impact_pct, expected_out, is_buy } => {
                pack_u16(w, super::pack::EventType::ImpactUpdate as u16);
                pack_string(w, token);
                pack_string(w, quote);
                pack_f64(w, *amount_in);
                pack_f64(w, *impact_pct);
                pack_string(w, expected_out);
                pack_bool(w, *is_buy);
            }
            EngineEvent::TradeStatus { wallet, action, status, message, tx_hash, token_address, amount, tokens_received, tokens_sold, token_decimals } => {
                pack_u16(w, super::pack::EventType::TradeStatus as u16);
                pack_string(w, wallet);
                pack_string(w, action);
                pack_string(w, status);
                pack_string(w, message);
                pack_bool(w, tx_hash.is_some()); if let Some(v) = tx_hash { pack_string(w, v); }
                pack_string(w, token_address);
                pack_f64(w, *amount);
                pack_bool(w, tokens_received.is_some()); if let Some(v) = tokens_received { pack_string(w, v); }
                pack_bool(w, tokens_sold.is_some()); if let Some(v) = tokens_sold { pack_string(w, v); }
                pack_u8(w, *token_decimals);
            }
            EngineEvent::GasPriceUpdate { gas_price_gwei } => {
                pack_u16(w, super::pack::EventType::GasPriceUpdate as u16);
                pack_f64(w, *gas_price_gwei);
            }
            EngineEvent::ConnectionStatus { connected, message } => {
                pack_u16(w, super::pack::EventType::ConnectionStatus as u16);
                pack_bool(w, *connected);
                pack_string(w, message);
            }
            EngineEvent::TxSent { tx_hash, wallet, action, amount, token, timestamp_ms } => {
                pack_u16(w, super::pack::EventType::TxSent as u16);
                pack_string(w, tx_hash);
                pack_string(w, wallet);
                pack_string(w, action);
                pack_f64(w, *amount);
                pack_string(w, token);
                pack_u64(w, *timestamp_ms);
            }
            EngineEvent::TxConfirmed { tx_hash, wallet, gas_used, status, confirm_block, timestamp_ms } => {
                pack_u16(w, super::pack::EventType::TxConfirmed as u16);
                pack_string(w, tx_hash);
                pack_string(w, wallet);
                pack_u64(w, *gas_used);
                pack_string(w, status);
                pack_u64(w, *confirm_block);
                pack_u64(w, *timestamp_ms);
            }
            EngineEvent::AutoFuelError { wallet, reason } => {
                pack_u16(w, super::pack::EventType::AutoFuelError as u16);
                pack_string(w, wallet);
                pack_string(w, reason);
            }
        }
    }
    
    fn unpack(r: &mut &[u8]) -> Result<Self, super::pack::PackError> {
        use super::pack::{unpack_u16, unpack_string, unpack_f64, unpack_bool, unpack_u8, unpack_u32, unpack_u64, EventType, PackError};
        
        let type_id = unpack_u16(r)?;
        match type_id {
            t if t == EventType::EngineReady as u16 => Ok(EngineEvent::EngineReady),
            t if t == EventType::Log as u16 => Ok(EngineEvent::Log { level: unpack_string(r)?, message: unpack_string(r)? }),
            t if t == EventType::BalanceUpdate as u16 => Ok(EngineEvent::BalanceUpdate { 
                wallet: unpack_string(r)?, token: unpack_string(r)?, wei: unpack_string(r)?, 
                float_val: unpack_f64(r)?, symbol: unpack_string(r)? 
            }),
            t if t == EventType::PoolDetected as u16 => Ok(EngineEvent::PoolDetected {
                pool_type: unpack_string(r)?, address: unpack_string(r)?, token: unpack_string(r)?, quote: unpack_string(r)?,
                liquidity_usd: unpack_f64(r)?, fee: unpack_u32(r)?, spot_price: unpack_f64(r)?,
                token_symbol: unpack_string(r)?, token_name: unpack_string(r)?
            }),
            t if t == EventType::PoolUpdate as u16 => Ok(EngineEvent::PoolUpdate {
                pool_address: unpack_string(r)?, pool_type: unpack_string(r)?, token: unpack_string(r)?, quote: unpack_string(r)?,
                reserve0: if unpack_bool(r)? { Some(unpack_string(r)?) } else { None },
                reserve1: if unpack_bool(r)? { Some(unpack_string(r)?) } else { None },
                sqrt_price_x96: if unpack_bool(r)? { Some(unpack_string(r)?) } else { None },
                tick: if unpack_bool(r)? { Some(unpack_u32(r)? as i32) } else { None },
                liquidity: if unpack_bool(r)? { let hi = unpack_u64(r)?; let lo = unpack_u64(r)?; Some((hi as u128) << 64 | lo as u128) } else { None },
                spot_price: if unpack_bool(r)? { Some(unpack_f64(r)?) } else { None },
                liquidity_usd: if unpack_bool(r)? { Some(unpack_f64(r)?) } else { None },
            }),
            t if t == EventType::PoolNotFound as u16 => {
                let token = unpack_string(r)?; let selected_quote = unpack_string(r)?;
                let len = unpack_u16(r)? as usize; let mut available_quotes = Vec::with_capacity(len);
                for _ in 0..len { available_quotes.push((unpack_string(r)?, unpack_string(r)?)); }
                Ok(EngineEvent::PoolNotFound { token, selected_quote, available_quotes })
            }
            t if t == EventType::PnLUpdate as u16 => Ok(EngineEvent::PnLUpdate {
                wallet: unpack_string(r)?, token: unpack_string(r)?, pnl_pct: unpack_f64(r)?,
                pnl_abs: unpack_string(r)?, current_value: unpack_string(r)?, current_price: unpack_f64(r)?, is_loading: unpack_bool(r)?
            }),
            t if t == EventType::ImpactUpdate as u16 => Ok(EngineEvent::ImpactUpdate {
                token: unpack_string(r)?, quote: unpack_string(r)?, amount_in: unpack_f64(r)?,
                impact_pct: unpack_f64(r)?, expected_out: unpack_string(r)?, is_buy: unpack_bool(r)?
            }),
            t if t == EventType::TradeStatus as u16 => Ok(EngineEvent::TradeStatus {
                wallet: unpack_string(r)?, action: unpack_string(r)?, status: unpack_string(r)?, message: unpack_string(r)?,
                tx_hash: if unpack_bool(r)? { Some(unpack_string(r)?) } else { None },
                token_address: unpack_string(r)?, amount: unpack_f64(r)?,
                tokens_received: if unpack_bool(r)? { Some(unpack_string(r)?) } else { None },
                tokens_sold: if unpack_bool(r)? { Some(unpack_string(r)?) } else { None },
                token_decimals: unpack_u8(r)?
            }),
            t if t == EventType::GasPriceUpdate as u16 => Ok(EngineEvent::GasPriceUpdate { gas_price_gwei: unpack_f64(r)? }),
            t if t == EventType::ConnectionStatus as u16 => Ok(EngineEvent::ConnectionStatus { connected: unpack_bool(r)?, message: unpack_string(r)? }),
            t if t == EventType::TxSent as u16 => Ok(EngineEvent::TxSent {
                tx_hash: unpack_string(r)?, wallet: unpack_string(r)?, action: unpack_string(r)?,
                amount: unpack_f64(r)?, token: unpack_string(r)?, timestamp_ms: unpack_u64(r)?
            }),
            t if t == EventType::TxConfirmed as u16 => Ok(EngineEvent::TxConfirmed {
                tx_hash: unpack_string(r)?, wallet: unpack_string(r)?, gas_used: unpack_u64(r)?,
                status: unpack_string(r)?, confirm_block: unpack_u64(r)?, timestamp_ms: unpack_u64(r)?
            }),
            t if t == EventType::AutoFuelError as u16 => Ok(EngineEvent::AutoFuelError { wallet: unpack_string(r)?, reason: unpack_string(r)? }),
            _ => Err(PackError::InvalidData),
        }
    }
}

impl Packable for AutoFuelSettingsData {
    fn pack(&self, w: &mut Vec<u8>) {
        pack_bool(w, self.auto_fuel_enabled);
        pack_f64(w, self.auto_fuel_threshold);
        pack_f64(w, self.auto_fuel_amount);
        pack_string(w, &self.fuel_quote_address);
    }
    fn unpack(r: &mut &[u8]) -> Result<Self, super::pack::PackError> {
        Ok(AutoFuelSettingsData {
            auto_fuel_enabled: unpack_bool(r)?,
            auto_fuel_threshold: unpack_f64(r)?,
            auto_fuel_amount: unpack_f64(r)?,
            fuel_quote_address: unpack_string(r)?,
        })
    }
}

impl Packable for EngineCommand {
    fn pack(&self, w: &mut Vec<u8>) {
        use super::pack::CommandType;
        match self {
            EngineCommand::Init { rpc_url, wss_url, chain_id, router, quoter, v2_factory, v3_factory, wrapped_native, native_address, wallets, public_rpc_urls, fuel_settings, quote_symbol, quote_tokens } => {
                pack_u16(w, CommandType::Init as u16);
                pack_string(w, rpc_url); pack_string(w, wss_url); pack_u64(w, *chain_id);
                pack_string(w, router); pack_string(w, quoter);
                pack_string(w, v2_factory); pack_string(w, v3_factory);
                pack_string(w, wrapped_native); pack_string(w, native_address);
                pack_u16(w, wallets.len() as u16); for (a, k) in wallets { pack_string(w, a); pack_string(w, k); }
                pack_u16(w, public_rpc_urls.len() as u16); for u in public_rpc_urls { pack_string(w, u); }
                fuel_settings.pack(w); pack_string(w, quote_symbol);
                pack_u16(w, quote_tokens.len() as u16); for (k, v) in quote_tokens { pack_string(w, k); pack_string(w, v); }
            }
            EngineCommand::ExecuteTrade { action, token, quote_token, amount, wallets, gas_gwei, slippage, v3_fee, amounts_wei } => {
                pack_u16(w, CommandType::ExecuteTrade as u16);
                pack_string(w, action); pack_string(w, token); pack_string(w, quote_token); pack_f64(w, *amount);
                pack_u16(w, wallets.len() as u16); for wlt in wallets { pack_string(w, wlt); }
                pack_f64(w, *gas_gwei); pack_f64(w, *slippage); pack_u32(w, *v3_fee);
                pack_bool(w, amounts_wei.is_some());
                if let Some(m) = amounts_wei { pack_u16(w, m.len() as u16); for (k, v) in m { pack_string(w, k); pack_string(w, v); } }
            }
            EngineCommand::CalcImpact { token_address, quote_address, amount_in, is_buy } => {
                pack_u16(w, CommandType::CalcImpact as u16);
                pack_string(w, token_address); pack_string(w, quote_address); pack_f64(w, *amount_in); pack_bool(w, *is_buy);
            }
            EngineCommand::UpdatePrice { symbol, price } => { pack_u16(w, CommandType::UpdatePrice as u16); pack_string(w, symbol); pack_f64(w, *price); }
            EngineCommand::UpdateTokenDecimals { address, decimals } => { pack_u16(w, CommandType::UpdateTokenDecimals as u16); pack_string(w, address); pack_u8(w, *decimals); }
            EngineCommand::UpdateSettings { gas_price_gwei, slippage, fuel_enabled, fuel_quote_address, rpc_url, wss_url, quote_symbol } => {
                pack_u16(w, CommandType::UpdateSettings as u16);
                pack_bool(w, gas_price_gwei.is_some()); if let Some(v) = gas_price_gwei { pack_f64(w, *v); }
                pack_bool(w, slippage.is_some()); if let Some(v) = slippage { pack_f64(w, *v); }
                pack_bool(w, fuel_enabled.is_some()); if let Some(v) = fuel_enabled { pack_bool(w, *v); }
                pack_bool(w, fuel_quote_address.is_some()); if let Some(v) = fuel_quote_address { pack_string(w, v); }
                pack_bool(w, rpc_url.is_some()); if let Some(v) = rpc_url { pack_string(w, v); }
                pack_bool(w, wss_url.is_some()); if let Some(v) = wss_url { pack_string(w, v); }
                pack_bool(w, quote_symbol.is_some()); if let Some(v) = quote_symbol { pack_string(w, v); }
            }
            EngineCommand::SwitchToken { token_address, quote_address, quote_symbol } => {
                pack_u16(w, CommandType::SwitchToken as u16); pack_string(w, token_address); pack_string(w, quote_address); pack_string(w, quote_symbol);
            }
            EngineCommand::UnsubscribeToken { token_address } => { pack_u16(w, CommandType::UnsubscribeToken as u16); pack_string(w, token_address); }
            EngineCommand::AddWallet { address, private_key } => { pack_u16(w, CommandType::AddWallet as u16); pack_string(w, address); pack_string(w, private_key); }
            EngineCommand::RefreshBalance { wallet, token } => { pack_u16(w, CommandType::RefreshBalance as u16); pack_string(w, wallet); pack_string(w, token); }
            EngineCommand::RefreshAllBalances => { pack_u16(w, CommandType::RefreshAllBalances as u16); }
            EngineCommand::Shutdown => { pack_u16(w, CommandType::Shutdown as u16); }
        }
    }
    fn unpack(r: &mut &[u8]) -> Result<Self, super::pack::PackError> {
        use super::pack::{unpack_u16, unpack_string, unpack_f64, unpack_bool, unpack_u8, unpack_u32, unpack_u64, CommandType, PackError};
        use std::collections::HashMap;
        
        let type_id = unpack_u16(r)?;
        match type_id {
            t if t == CommandType::Init as u16 => {
                let rpc_url = unpack_string(r)?; let wss_url = unpack_string(r)?; let chain_id = unpack_u64(r)?;
                let router = unpack_string(r)?; let quoter = unpack_string(r)?;
                let v2_factory = unpack_string(r)?; let v3_factory = unpack_string(r)?;
                let wrapped_native = unpack_string(r)?; let native_address = unpack_string(r)?;
                let wlen = unpack_u16(r)? as usize; let mut wallets = Vec::with_capacity(wlen); for _ in 0..wlen { wallets.push((unpack_string(r)?, unpack_string(r)?)); }
                let ulen = unpack_u16(r)? as usize; let mut public_rpc_urls = Vec::with_capacity(ulen); for _ in 0..ulen { public_rpc_urls.push(unpack_string(r)?); }
                let fuel_settings = AutoFuelSettingsData::unpack(r)?;
                let quote_symbol = unpack_string(r)?;
                let qtlen = unpack_u16(r)? as usize; let mut quote_tokens = HashMap::with_capacity(qtlen); for _ in 0..qtlen { quote_tokens.insert(unpack_string(r)?, unpack_string(r)?); }
                Ok(EngineCommand::Init { rpc_url, wss_url, chain_id, router, quoter, v2_factory, v3_factory, wrapped_native, native_address, wallets, public_rpc_urls, fuel_settings, quote_symbol, quote_tokens })
            }
            t if t == CommandType::ExecuteTrade as u16 => {
                let action = unpack_string(r)?; let token = unpack_string(r)?; let quote_token = unpack_string(r)?; let amount = unpack_f64(r)?;
                let wlen = unpack_u16(r)? as usize; let mut wallets = Vec::with_capacity(wlen); for _ in 0..wlen { wallets.push(unpack_string(r)?); }
                let gas_gwei = unpack_f64(r)?; let slippage = unpack_f64(r)?; let v3_fee = unpack_u32(r)?;
                let amounts_wei = if unpack_bool(r)? { let mlen = unpack_u16(r)? as usize; let mut m = HashMap::with_capacity(mlen); for _ in 0..mlen { m.insert(unpack_string(r)?, unpack_string(r)?); } Some(m) } else { None };
                Ok(EngineCommand::ExecuteTrade { action, token, quote_token, amount, wallets, gas_gwei, slippage, v3_fee, amounts_wei })
            }
            t if t == CommandType::CalcImpact as u16 => Ok(EngineCommand::CalcImpact { token_address: unpack_string(r)?, quote_address: unpack_string(r)?, amount_in: unpack_f64(r)?, is_buy: unpack_bool(r)? }),
            t if t == CommandType::UpdatePrice as u16 => Ok(EngineCommand::UpdatePrice { symbol: unpack_string(r)?, price: unpack_f64(r)? }),
            t if t == CommandType::UpdateTokenDecimals as u16 => Ok(EngineCommand::UpdateTokenDecimals { address: unpack_string(r)?, decimals: unpack_u8(r)? }),
            t if t == CommandType::UpdateSettings as u16 => Ok(EngineCommand::UpdateSettings {
                gas_price_gwei: if unpack_bool(r)? { Some(unpack_f64(r)?) } else { None },
                slippage: if unpack_bool(r)? { Some(unpack_f64(r)?) } else { None },
                fuel_enabled: if unpack_bool(r)? { Some(unpack_bool(r)?) } else { None },
                fuel_quote_address: if unpack_bool(r)? { Some(unpack_string(r)?) } else { None },
                rpc_url: if unpack_bool(r)? { Some(unpack_string(r)?) } else { None },
                wss_url: if unpack_bool(r)? { Some(unpack_string(r)?) } else { None },
                quote_symbol: if unpack_bool(r)? { Some(unpack_string(r)?) } else { None },
            }),
            t if t == CommandType::SwitchToken as u16 => Ok(EngineCommand::SwitchToken { token_address: unpack_string(r)?, quote_address: unpack_string(r)?, quote_symbol: unpack_string(r)? }),
            t if t == CommandType::UnsubscribeToken as u16 => Ok(EngineCommand::UnsubscribeToken { token_address: unpack_string(r)? }),
            t if t == CommandType::AddWallet as u16 => Ok(EngineCommand::AddWallet { address: unpack_string(r)?, private_key: unpack_string(r)? }),
            t if t == CommandType::RefreshBalance as u16 => Ok(EngineCommand::RefreshBalance { wallet: unpack_string(r)?, token: unpack_string(r)? }),
            t if t == CommandType::RefreshAllBalances as u16 => Ok(EngineCommand::RefreshAllBalances),
            t if t == CommandType::Shutdown as u16 => Ok(EngineCommand::Shutdown),
            _ => Err(PackError::InvalidData),
        }
    }
}



// =============== TESTS ==============

#[cfg(test)]
mod tests {
    use super::*;
    
    #[test]
    fn test_event_roundtrip_engine_ready() {
        let event = EngineEvent::EngineReady;
        
        let mut w = Vec::new();
        event.pack(&mut w);
        
        let result = EngineEvent::unpack(&mut w.as_slice()).unwrap();
        matches!(result, EngineEvent::EngineReady);
    }
    
    #[test]
    fn test_event_roundtrip_log() {
        let event = EngineEvent::Log {
            level: "INFO".to_string(),
            message: "Test message".to_string(),
        };
        
        let mut w = Vec::new();
        event.pack(&mut w);
        
        let result = EngineEvent::unpack(&mut w.as_slice()).unwrap();
        if let EngineEvent::Log { level, message } = result {
            assert_eq!(level, "INFO");
            assert_eq!(message, "Test message");
        } else {
            panic!("Wrong event type");
        }
    }
    
    #[test]
    fn test_event_roundtrip_balance() {
        let event = EngineEvent::BalanceUpdate {
            wallet: "0x1234".to_string(),
            token: "0x5678".to_string(),
            wei: "1000000000000000000".to_string(),
            float_val: 1.5,
            symbol: "ETH".to_string(),
        };
        
        let mut w = Vec::new();
        event.pack(&mut w);
        
        let result = EngineEvent::unpack(&mut w.as_slice()).unwrap();
        if let EngineEvent::BalanceUpdate { wallet, float_val, .. } = result {
            assert_eq!(wallet, "0x1234");
            assert!((float_val - 1.5).abs() < 0.0001);
        } else {
            panic!("Wrong event type");
        }
    }
    
    #[test]
    fn test_event_roundtrip_pool_update() {
        let event = EngineEvent::PoolUpdate {
            pool_address: "0xpool".to_string(),
            pool_type: "V3".to_string(),
            token: "0xtoken".to_string(),
            quote: "0xquote".to_string(),
            reserve0: Some("1000".to_string()),
            reserve1: None,
            sqrt_price_x96: Some("12345".to_string()),
            tick: Some(-12345),
            liquidity: Some(999999u128),
            spot_price: Some(1.234),
            liquidity_usd: None,
        };
        
        let mut w = Vec::new();
        event.pack(&mut w);
        
        let result = EngineEvent::unpack(&mut w.as_slice()).unwrap();
        if let EngineEvent::PoolUpdate { pool_type, tick, liquidity, .. } = result {
            assert_eq!(pool_type, "V3");
            assert_eq!(tick, Some(-12345));
            assert_eq!(liquidity, Some(999999u128));
        } else {
            panic!("Wrong event type");
        }
    }
    
    #[test]
    fn test_command_roundtrip_init() {
        let mut quote_tokens = std::collections::HashMap::new();
        quote_tokens.insert("WBNB".to_string(), "0xbb4CdB9CBd36B01bD1cBaEBF2De08d9173bc095c".to_string());
        
        let cmd = EngineCommand::Init {
            rpc_url: "https://rpc.example.com".to_string(),
            wss_url: "wss://ws.example.com".to_string(),
            chain_id: 56,
            router: "0xrouter".to_string(),
            quoter: "0xquoter".to_string(),
            v2_factory: "0xfactory".to_string(),
            v3_factory: "0xfactoryv3".to_string(),
            wrapped_native: "0xwnative".to_string(),
            native_address: "0xnative".to_string(),
            wallets: vec![("0xwallet".to_string(), "0xkey".to_string())],
            public_rpc_urls: vec!["https://public.example.com".to_string()],
            fuel_settings: AutoFuelSettingsData {
                auto_fuel_enabled: true,
                auto_fuel_threshold: 0.005,
                auto_fuel_amount: 0.01,
                fuel_quote_address: "0xquote".to_string(),
            },
            quote_symbol: "WBNB".to_string(),
            quote_tokens,
        };
        
        let mut w = Vec::new();
        cmd.pack(&mut w);
        
        let result = EngineCommand::unpack(&mut w.as_slice()).unwrap();
        if let EngineCommand::Init { chain_id, fuel_settings, .. } = result {
            assert_eq!(chain_id, 56);
            assert!(fuel_settings.auto_fuel_enabled);
        } else {
            panic!("Wrong command type");
        }
    }
    
    #[test]
    fn test_command_roundtrip_execute_trade() {
        let mut amounts_wei = std::collections::HashMap::new();
        amounts_wei.insert("0xwallet".to_string(), "1000000000000000000".to_string());
        
        let cmd = EngineCommand::ExecuteTrade {
            action: "BUY".to_string(),
            token: "0xtoken".to_string(),
            quote_token: "0xquote".to_string(),
            amount: 1.5,
            wallets: vec!["0xwallet".to_string()],
            gas_gwei: 5.0,
            slippage: 0.5,
            v3_fee: 3000,
            amounts_wei: Some(amounts_wei),
        };
        
        let mut w = Vec::new();
        cmd.pack(&mut w);
        
        let result = EngineCommand::unpack(&mut w.as_slice()).unwrap();
        if let EngineCommand::ExecuteTrade { action, amount, v3_fee, .. } = result {
            assert_eq!(action, "BUY");
            assert!((amount - 1.5).abs() < 0.0001);
            assert_eq!(v3_fee, 3000);
        } else {
            panic!("Wrong command type");
        }
    }
    
    #[test]
    fn test_command_roundtrip_shutdown() {
        let cmd = EngineCommand::Shutdown;
        
        let mut w = Vec::new();
        cmd.pack(&mut w);
        
        let result = EngineCommand::unpack(&mut w.as_slice()).unwrap();
        matches!(result, EngineCommand::Shutdown);
    }
}