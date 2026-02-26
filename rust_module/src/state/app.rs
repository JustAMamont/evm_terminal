use std::collections::HashMap;
use std::sync::{Arc, RwLock};
use once_cell::sync::Lazy;
use ethers::types::{Address, U256, H256, H160};

#[derive(Clone, Default, Debug)]
pub struct V3PoolState {
    pub liquidity: U256,
    pub sqrt_price_x96: U256,
    pub tick: i32,
    pub pool_fee: u32,
}

pub struct BotState {
    // Network
    pub chain_id: u64,
    pub router_address: Address,
    pub quoter_address: Address,
    pub v2_factory_address: Address,
    pub v3_factory_address: Address,
    pub native_address: Address,
    pub wrapped_native_address: Address,
    pub wss_url: String,
    
    // Gas & Trading
    pub gas_price: U256,
    pub slippage: f64,
    pub manual_gas_price_gwei: f64,
    
    // Wallets
    pub wallet_keys: HashMap<Address, String>,
    pub nonce_map: HashMap<Address, u64>,
    
    // Prices & Decimals
    pub usd_prices: HashMap<String, f64>,
    pub decimals_cache: HashMap<Address, u8>,
    
    // V2 Pools
    pub v2_reserves: HashMap<H160, (U256, U256)>,
    
    // V3 Pools
    pub v3_states: HashMap<H160, V3PoolState>,
    
    // Auto-fuel
    pub fuel_enabled: bool,
    pub fuel_threshold: U256,
    pub fuel_amount: U256,
    pub fuel_quote_address: Address,
    pub auto_fuel_attempts: HashMap<Address, (u32, u64)>, // (count, last_timestamp_ms)
    
    // Quote Symbol - для динамического получения USD цены
    pub quote_symbol: String,

    // Quote_Tokens - для поиска и фильтрации пулов 
    // по квотируемым токенам
    pub quote_tokens: HashMap<String, Address>,
    
    // === ВЫБОР ЛУЧШЕГО ПУЛА ===
    pub selected_pool_address: Option<H160>,
    pub selected_pool_type: Option<String>,
    pub selected_pool_fee: u32,
    pub selected_pool_liquidity_usd: f64,
    pub selected_pool_spot_price: f64,
    
    // === ОТСЛЕЖИВАНИЕ ТРАНЗАКЦИЙ ===
    pub pending_txs: std::collections::HashSet<H256>,
}

pub static CORE_STATE: Lazy<Arc<RwLock<BotState>>> = Lazy::new(|| {
    Arc::new(RwLock::new(BotState {
        chain_id: 0,
        nonce_map: HashMap::new(),
        gas_price: U256::zero(),
        slippage: 15.0,
        manual_gas_price_gwei: 0.1,
        usd_prices: HashMap::new(),
        router_address: Address::zero(),
        quoter_address: Address::zero(),
        v2_factory_address: Address::zero(),
        v3_factory_address: Address::zero(),
        native_address: Address::zero(),
        wrapped_native_address: Address::zero(),
        wallet_keys: HashMap::new(),
        wss_url: String::new(),
        decimals_cache: HashMap::new(),
        v2_reserves: HashMap::new(),
        v3_states: HashMap::new(),
        fuel_enabled: false,
        fuel_threshold: U256::zero(),
        fuel_amount: U256::zero(),
        fuel_quote_address: Address::zero(),
        auto_fuel_attempts: HashMap::new(),
        quote_symbol: String::new(),
        quote_tokens: HashMap::new(),
        selected_pool_address: None,
        selected_pool_type: None,
        selected_pool_fee: 0,
        selected_pool_liquidity_usd: 0.0,
        selected_pool_spot_price: 0.0,
        pending_txs: std::collections::HashSet::new(),
    }))
});
