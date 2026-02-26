use serde::{Serialize, Deserialize};

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