use ethers::prelude::*;
use ethers::utils::format_units;
use std::time::{Instant, Duration};
use tokio::time::{sleep, timeout, interval};

use crate::state::{RPC_POOL, SHUTDOWN_FLAG, GLOBAL_HTTP_CLIENT, CORE_STATE, TRACKED_WALLETS, V3PoolState};
use crate::state::app::FxDashMap;
use crate::bridge::{emit_event, EngineEvent, emit_log};
use crate::execution;
use futures::StreamExt;
use std::sync::Arc;
use url::Url;

abigen!(
    UniversalABI,
    r#"[
        event Transfer(address indexed from, address indexed to, uint256 value)
        event Sync(uint112 reserve0, uint112 reserve1)
        event Swap(address indexed sender, address indexed recipient, int256 amount0, int256 amount1, uint160 sqrtPriceX96, uint128 liquidity, int24 tick)
        function decimals() external view returns (uint8)
        function getPair(address, address) external view returns (address)
        function getPool(address, address, uint24) external view returns (address)
        function getReserves() external view returns (uint112 reserve0, uint112 reserve1, uint32 blockTimestampLast)
        function slot0() external view returns (uint160 sqrtPriceX96, int24 tick, uint16 observationIndex, uint16 observationCardinality, uint16 observationCardinalityNext, uint8 feeProtocol, bool unlocked)
        function liquidity() external view returns (uint128)
        function balanceOf(address) external view returns (uint256)
    ]"#
);

#[derive(Debug, Clone)]
#[allow(dead_code)]
struct PoolCandidate {
    address: H160,
    pool_type: String,
    liquidity_usd: f64,
    fee_bps: u32,
    sqrt_price_x96: Option<U256>,
    tick: Option<i32>,
    reserves: Option<(U256, U256)>,
    score: f64,
    spot_price: f64,
}

const DEFAULT_TRADE_USD: f64 = 1000.0;
const WEIGHT_LIQUIDITY: f64 = 0.50;
const WEIGHT_FEE: f64 = 0.20;
const WEIGHT_PRICE_IMPACT: f64 = 0.30;
const RECONNECT_DELAY_SECS: u64 = 3;
const PREFETCH_TIMEOUT_SECS: u64 = 5;
const IDLE_TIMEOUT_SECS: u64 = 30;

fn current_timestamp_ms() -> u64 {
    std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .unwrap()
        .as_millis() as u64
}

fn get_quote_price_usd(quote_symbol: &str, usd_prices: &FxDashMap<String, f64>) -> f64 {
    if quote_symbol.is_empty() { return 1.0; }
    if let Some(price) = usd_prices.get(quote_symbol) { return *price; }
    if quote_symbol.starts_with('W') && quote_symbol.len() > 1 {
        let without_w = &quote_symbol[1..];
        if let Some(price) = usd_prices.get(without_w) { return *price; }
    }
    let with_w = format!("W{}", quote_symbol);
    if let Some(price) = usd_prices.get(&with_w) { return *price; }
    1.0
}

pub async fn get_decimals_cached(token: Address) -> u8 {
    if let Some(dec) = CORE_STATE.read().unwrap().decimals_cache.get(&token) { return *dec; }
    let urls = { RPC_POOL.read().get_fastest_pool(3) };
    for url_str in urls {
        if let Ok(url) = Url::parse(&url_str) {
            let provider = Arc::new(Provider::new(Http::new_with_client(url, GLOBAL_HTTP_CLIENT.clone())));
            let contract = UniversalABI::new(token, provider);
            if let Ok(dec) = contract.decimals().call().await {
                if dec <= 77 {
                    CORE_STATE.write().unwrap().decimals_cache.insert(token, dec);
                    return dec;
                }
            }
        }
    }
    18
}

fn wei_to_float(wei_value: U256, decimals: u8) -> f64 {
    if wei_value.is_zero() { return 0.0; }
    let safe_decimals = decimals.min(77) as i32;
    let wei_f64 = if wei_value > U256::from(u128::MAX) {
        let s = format_units(wei_value, safe_decimals as u32).unwrap_or_else(|_| "0.0".to_string());
        return s.parse::<f64>().unwrap_or(0.0);
    } else {
        wei_value.as_u128() as f64
    };
    let divisor = 10f64.powi(safe_decimals);
    if divisor == 0.0 { return 0.0; }
    wei_f64 / divisor
}

// ===================== HTTP PREFETCH =====================

async fn prefetch_all_data(
    provider: Arc<Provider<Http>>,
    wallets: Vec<Address>,
    quote_token: Option<Address>,
    pool_targets: Vec<Address>,
    token: Address,
    quote: Address
) {
    emit_log("INFO", "⚡ HTTP Prefetch: Начинаем загрузку начальных данных...".into());
    let start = Instant::now();
    
    let gas_provider = provider.clone();
    let gas_price = gas_provider.get_gas_price().await.ok();
    if let Some(gas) = gas_price {
        CORE_STATE.write().unwrap().gas_price = gas;
        emit_log("DEBUG", format!("⚡ Prefetch: Gas price = {} Gwei", gas.as_u64() / 1_000_000_000));
    }
    
    let mut native_balance_tasks = Vec::with_capacity(wallets.len());
    for wallet in wallets.clone() {
        let p = provider.clone();
        native_balance_tasks.push(async move {
            let balance = p.get_balance(wallet, None).await.ok()?;
            Some((wallet, balance))
        });
    }
    
    let native_results = futures::future::join_all(native_balance_tasks).await;
    for result in native_results {
        if let Some((wallet, balance)) = result {
            let float_val = wei_to_float(balance, 18);
            emit_event(EngineEvent::BalanceUpdate {
                wallet: format!("{:?}", wallet),
                token: "0xeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee".into(),
                wei: balance.to_string(),
                float_val,
                symbol: "NATIVE".into()
            });
        }
    }
    
    if let Some(quote_addr) = quote_token {
        if quote_addr != Address::zero() {
            let quote_decimals = get_decimals_cached(quote_addr).await;
            for wallet in wallets.clone() {
                let contract = UniversalABI::new(quote_addr, provider.clone());
                if let Ok(balance) = contract.balance_of(wallet).call().await {
                    let float_val = wei_to_float(balance, quote_decimals);
                    emit_event(EngineEvent::BalanceUpdate {
                        wallet: format!("{:?}", wallet),
                        token: format!("{:?}", quote_addr),
                        wei: balance.to_string(),
                        float_val,
                        symbol: "QUOTE".into()
                    });
                }
            }
        }
    }
    
    if !pool_targets.is_empty() {
        let quote_price = {
            let s = CORE_STATE.read().unwrap();
            get_quote_price_usd(&s.quote_symbol, &s.usd_prices)
        };
        let t_dec = get_decimals_cached(token).await;
        let q_dec = get_decimals_cached(quote).await;
        let (t0, _) = if token < quote { (token, quote) } else { (quote, token) };
        let t0_is_quote = t0 == quote;
        let mut candidates = Vec::with_capacity(pool_targets.len());

        for &addr in &pool_targets {
            let contract = UniversalABI::new(addr, provider.clone());

            // V2
            if let Ok((r0, r1, _)) = contract.get_reserves().call().await {
                let (d0, d1) = if t0_is_quote { (q_dec, t_dec) } else { (t_dec, q_dec) };
                let (liq, prc) = calculate_v2_liquidity_usd_and_price(r0.into(), r1.into(), d0, d1, t0_is_quote, quote_price);
                CORE_STATE.write().unwrap().v2_reserves.insert(addr, (r0.into(), r1.into()));
                candidates.push(PoolCandidate { 
                    address: addr, pool_type: "V2".into(), liquidity_usd: liq, fee_bps: 30, 
                    sqrt_price_x96: None, tick: None, reserves: Some((r0.into(), r1.into())), 
                    score: 0.0, spot_price: prc 
                });
                continue;
            }
            
            /* V3 
            ** NOTE **: Ликвидность для простоты в этом типе пулов берется из первого активного слота - там где цена 
            иначе пришлось бы городить дополнительные апи запросы и усложнять алгоритм.
            Данная реализация - компромис между точностью и производительностью. 

            Этого достаточно для:
              1. сравнения пулов (какой ликвиднее) и выбора лучшего из них
              2. оценки примерного price impact

            Для чего НЕ достаточно:
              - Показывать точный TVL как на DexScreener к примеру */
            if let Ok((sqrt_p, tick, _, _, _, _, _)) = contract.slot_0().call().await {
                let liq_raw = contract.liquidity().call().await.unwrap_or(0);
                let fee = { CORE_STATE.read().unwrap().v3_states.get(&addr).map(|s| s.pool_fee).unwrap_or(2500) };
                let (d0, d1) = if t0_is_quote { (q_dec, t_dec) } else { (t_dec, q_dec) };
                let (liq, prc) = calculate_v3_liquidity_usd_and_price(sqrt_p, liq_raw, d0, d1, t0_is_quote, quote_price);
                CORE_STATE.write().unwrap().v3_states.insert(addr, V3PoolState { 
                    liquidity: liq_raw.into(), sqrt_price_x96: sqrt_p, tick, pool_fee: fee 
                });
                candidates.push(PoolCandidate { 
                    address: addr, pool_type: "V3".into(), liquidity_usd: liq, fee_bps: fee, 
                    sqrt_price_x96: Some(sqrt_p), tick: Some(tick), reserves: None, 
                    score: 0.0, spot_price: prc 
                });
            } else {
                emit_log("WARNING", format!("⚠️ Пул {:?} не V2 и не V3", addr));
            }
        }
        
        emit_log("DEBUG", format!("📊 candidates: {}", candidates.len()));

        if let Some(best) = select_best_pool(candidates, DEFAULT_TRADE_USD) {
            {
                let mut s = CORE_STATE.write().unwrap();
                s.selected_pool_address = Some(best.address);
                s.selected_pool_type = Some(best.pool_type.clone());
                s.selected_pool_fee = best.fee_bps;
                s.selected_pool_liquidity_usd = best.liquidity_usd;
                s.selected_pool_spot_price = best.spot_price;
            }
            // Получаем информацию о токене
            let (token_symbol, token_name) = execution::get_token_info(token).await;

            let pool_type = best.pool_type.clone();
            let pool_address = best.address;
            let liquidity_usd = best.liquidity_usd;

            emit_event(EngineEvent::PoolDetected { 
                pool_type: best.pool_type, 
                address: format!("{:?}", best.address), 
                token: format!("{:?}", token), 
                quote: format!("{:?}", quote),
                liquidity_usd: best.liquidity_usd, 
                fee: best.fee_bps,
                spot_price: best.spot_price,
                token_symbol,
                token_name
            });
            emit_log("DEBUG", format!(" Лучший пул: {:?}, тип: {}, Liq.: {} $, ", pool_address, pool_type, liquidity_usd));
        }
    }
    
    let elapsed = start.elapsed();
    emit_log("SUCCESS", format!("⚡ HTTP Prefetch завершен за {}ms", elapsed.as_millis()));
}

// ===================== WEBSOCKET MANAGER =====================

#[derive(Debug, Clone)]
enum DisconnectReason {
    StreamEnded(String),
    Error(String),
    IdleTimeout,
    Shutdown,
}

pub struct WebSocketManager {
    wss_url: String,
    provider: Option<Arc<Provider<Ws>>>,
}

impl WebSocketManager {
    pub fn new(wss_url: String) -> Self {
        Self { wss_url, provider: None }
    }

    pub async fn run_forever(
        &mut self,
        wallets: Vec<Address>,
        quote_token: Address,
        pool_targets: Vec<Address>,
        token: Address,
        quote: Address
    ) {
        let mut attempt = 0u32;
        
        loop {
            if SHUTDOWN_FLAG.load(std::sync::atomic::Ordering::Relaxed) { 
                emit_log("INFO", "🔌 WebSocket: Shutdown signal received".into());
                break; 
            }
            
            attempt += 1;
            emit_log("INFO", format!("🔌 WebSocket: Попытка подключения #{} к {}", attempt, self.wss_url));
            emit_event(EngineEvent::ConnectionStatus {
                connected: false,
                message: format!("Подключение... (попытка #{})", attempt)
            });
            
            if let Some(http_provider) = self.get_http_provider().await {
                timeout(
                    Duration::from_secs(PREFETCH_TIMEOUT_SECS),
                    prefetch_all_data(
                        http_provider,
                        wallets.clone(),
                        Some(quote_token),
                        pool_targets.clone(),
                        token,
                        quote
                    )
                ).await.ok();
            }
            
            match Provider::<Ws>::connect(&self.wss_url).await {
                Ok(ws_provider) => {
                    let ws = Arc::new(ws_provider);
                    self.provider = Some(ws.clone());
                    
                    attempt = 0;
                    emit_log("SUCCESS", "🔌 WebSocket: Подключено успешно!".into());
                    emit_event(EngineEvent::ConnectionStatus {
                        connected: true,
                        message: "WebSocket подключен".into()
                    });
                    
                    let reason = self.run_subscriptions_and_wait(
                        ws, 
                        wallets.clone(), 
                        quote_token, 
                        pool_targets.clone(),
                        token
                    ).await;
                    
                    match &reason {
                        DisconnectReason::StreamEnded(stream_name) => {
                            emit_log("WARNING", format!("🔌 WebSocket: Поток '{}' завершён, переподключение...", stream_name));
                        }
                        DisconnectReason::Error(err) => {
                            emit_log("ERROR", format!("🔌 WebSocket: Ошибка - {}, переподключение...", err));
                        }
                        DisconnectReason::IdleTimeout => {
                            emit_log("WARNING", "🔌 WebSocket: Нет данных более 30 сек, переподключение...".into());
                        }
                        DisconnectReason::Shutdown => {
                            emit_log("INFO", "🔌 WebSocket: Завершение работы".into());
                            break;
                        }
                    }
                    
                    emit_event(EngineEvent::ConnectionStatus {
                        connected: false,
                        message: format!("{:?}", reason)
                    });
                }
                Err(e) => {
                    emit_log("ERROR", format!("🔌 WebSocket: Ошибка подключения - {:?}", e));
                    emit_event(EngineEvent::ConnectionStatus {
                        connected: false,
                        message: format!("Ошибка подключения: {:?}", e)
                    });
                }
            }
            
            let delay = std::cmp::min(RECONNECT_DELAY_SECS * (1 + attempt / 3) as u64, 30);
            emit_log("INFO", format!("🔌 WebSocket: Повторное подключение через {} сек...", delay));
            sleep(Duration::from_secs(delay)).await;
        }
    }

    async fn get_http_provider(&self) -> Option<Arc<Provider<Http>>> {
        let urls = { RPC_POOL.read().get_fastest_pool(3) };
        for url_str in urls {
            if let Ok(url) = Url::parse(&url_str) {
                let provider = Arc::new(Provider::new(Http::new_with_client(url, GLOBAL_HTTP_CLIENT.clone())));
                if timeout(Duration::from_secs(2), provider.get_block_number()).await.is_ok() {
                    return Some(provider);
                }
            }
        }
        None
    }

    async fn run_subscriptions_and_wait(
        &self,
        ws: Arc<Provider<Ws>>,
        wallets: Vec<Address>,
        quote_token: Address,
        pool_targets: Vec<Address>,
        target_token: Address
    ) -> DisconnectReason {
        let ws_blocks = ws.clone();
        let wallets_blocks = wallets.clone();
        let ws_balances = ws.clone();
        
        let blocks_task = tokio::spawn(async move {
            match ws_blocks.subscribe_blocks().await {
                Ok(mut block_stream) => {
                    emit_log("INFO", "📡 Подписка на блоки активна".into());
                    let idle_timeout = Duration::from_secs(IDLE_TIMEOUT_SECS);
                    
                    loop {
                        if SHUTDOWN_FLAG.load(std::sync::atomic::Ordering::Relaxed) {
                            return DisconnectReason::Shutdown;
                        }
                        
                        match tokio::time::timeout(idle_timeout, block_stream.next()).await {
                            Ok(Some(_block)) => {
                                if let Ok(gas) = ws_blocks.get_gas_price().await {
                                    CORE_STATE.write().unwrap().gas_price = gas;
                                    emit_event(EngineEvent::GasPriceUpdate {
                                        gas_price_gwei: gas.as_u64() as f64 / 1e9
                                    });
                                }
                                
                                for wallet in wallets_blocks.clone() {
                                    if let Ok(balance) = ws_balances.get_balance(wallet, None).await {
                                        let float_val = wei_to_float(balance, 18);
                                        
                                        let fuel_job = {
                                            let s = CORE_STATE.read().unwrap();
                                            if s.fuel_enabled && balance < s.fuel_threshold && s.fuel_quote_address != Address::zero() {
                                                // Проверяем лимит попыток (максимум 5, не чаще раза в 60 сек)
                                                let now = current_timestamp_ms();
                                                let (attempts, last_ts) = s.auto_fuel_attempts.get(&wallet).unwrap_or(&(0, 0));
                                                
                                                if *attempts < 5 && (now - last_ts) > 60000 {
                                                    s.wallet_keys.get(&wallet).map(|pk| {
                                                        (pk.clone(), wallet, s.router_address, s.fuel_quote_address, s.fuel_amount, s.chain_id)
                                                    })
                                                } else {
                                                    None
                                                }
                                            } else { None }
                                        };
                                        
                                        if let Some((pk, w, r, q, a, cid)) = fuel_job { 
                                            // Увеличиваем счётчик попыток перед вызовом
                                            let new_count = {
                                                let s = CORE_STATE.read().unwrap();
                                                let (count, _) = s.auto_fuel_attempts.get(&w).unwrap_or(&(0, 0));
                                                count + 1
                                            };
                                            CORE_STATE.write().unwrap().auto_fuel_attempts.insert(w, (new_count, current_timestamp_ms()));
                                            
                                            // Вызываем auto_fuel
                                            let success = execution::run_auto_fuel(pk, w, r, q, a, cid).await;
                                            
                                            // При успехе сбрасываем счётчик
                                            if success {
                                                CORE_STATE.write().unwrap().auto_fuel_attempts.insert(w, (0, 0));
                                            }
                                        }
                                        
                                        emit_event(EngineEvent::BalanceUpdate {
                                            wallet: format!("{:?}", wallet),
                                            token: "0xeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee".into(),
                                            wei: balance.to_string(),
                                            float_val,
                                            symbol: "NATIVE".into()
                                        });
                                    }
                                }
                            }
                            Ok(None) => return DisconnectReason::StreamEnded("blocks".into()),
                            Err(_) => return DisconnectReason::IdleTimeout,
                        }
                    }
                }
                Err(e) => DisconnectReason::Error(format!("subscribe_blocks: {:?}", e))
            }
        });

        let ws_transfers = ws.clone();
        let wallets_transfers = wallets.clone();
        let quote_transfers = quote_token;
        let target_token_addr_transfer = target_token;
        
        let transfers_task = tokio::spawn(async move {
            // Отслеживание target_token, чтобы видеть приход монет
            let mut all_addresses: Vec<Address> = vec![target_token_addr_transfer];
            if quote_transfers != Address::zero() {
                all_addresses.push(quote_transfers);
            }
            
            let filter = Filter::new()
                .event("Transfer(address,address,uint256)")
                .address(all_addresses);
                
            match ws_transfers.subscribe_logs(&filter).await {
                Ok(mut transfer_stream) => {
                    emit_log("INFO", "📡 Подписка на Transfer события активна".into());
                    
                    while let Some(log) = transfer_stream.next().await {
                        if SHUTDOWN_FLAG.load(std::sync::atomic::Ordering::Relaxed) {
                            return DisconnectReason::Shutdown;
                        }
                        
                        let raw = log.clone().into();
                        if let Ok(transfer) = <TransferFilter as EthEvent>::decode_log(&raw) {
                            let is_incoming = wallets_transfers.contains(&transfer.to);
                            let is_outgoing = wallets_transfers.contains(&transfer.from);
                            
                            if is_incoming || is_outgoing {
                                let ws_clone = ws_transfers.clone();
                                let addr = log.address;
                                
                                if is_incoming {
                                    let to_addr = transfer.to;
                                    let ws_inner = ws_clone.clone();
                                    tokio::spawn(async move {
                                        let decimals = get_decimals_cached(addr).await;
                                        let contract = UniversalABI::new(addr, ws_inner);
                                        if let Ok(new_balance) = contract.balance_of(to_addr).call().await {
                                            let float_val = wei_to_float(new_balance, decimals);
                                            emit_event(EngineEvent::BalanceUpdate {
                                                wallet: format!("{:?}", to_addr),
                                                token: format!("{:?}", addr),
                                                wei: new_balance.to_string(),
                                                float_val,
                                                symbol: "TOKEN".into()
                                            });
                                        }
                                    });
                                }
                                
                                if is_outgoing {
                                    let from_addr = transfer.from;
                                    let ws_inner = ws_clone.clone();
                                    tokio::spawn(async move {
                                        let decimals = get_decimals_cached(addr).await;
                                        let contract = UniversalABI::new(addr, ws_inner);
                                        if let Ok(new_balance) = contract.balance_of(from_addr).call().await {
                                            let new_float = wei_to_float(new_balance, decimals);
                                            emit_event(EngineEvent::BalanceUpdate {
                                                wallet: format!("{:?}", from_addr),
                                                token: format!("{:?}", addr),
                                                wei: new_balance.to_string(),
                                                float_val: new_float,
                                                symbol: "TOKEN".into()
                                            });
                                        }
                                    });
                                }
                            }
                        }
                    }
                    
                    DisconnectReason::StreamEnded("transfers".into())
                }
                Err(e) => DisconnectReason::Error(format!("subscribe_logs(Transfer): {:?}", e))
            }
        });

        let ws_pools = ws.clone();
        let pools_list = pool_targets.clone();
        let target_token_addr = target_token; 
        
        let pools_task = tokio::spawn(async move {
            if pools_list.is_empty() {
                loop {
                    if SHUTDOWN_FLAG.load(std::sync::atomic::Ordering::Relaxed) {
                        return DisconnectReason::Shutdown;
                    }
                    sleep(Duration::from_secs(60)).await;
                }
            }
            
            let t_dec = get_decimals_cached(target_token_addr).await;
            let q_dec = get_decimals_cached(quote_token).await;
            let (t0, _) = if target_token_addr < quote_token { (target_token_addr, quote_token) } else { (quote_token, target_token_addr) };
            let t0_is_quote = t0 == quote_token;
            
            let filter = Filter::new().address(pools_list.clone());
            match ws_pools.subscribe_logs(&filter).await {
                Ok(mut pool_stream) => {
                    emit_log("INFO", format!("📡 Подписка на {} пул(ов) активна", pools_list.len()));
                    
                    while let Some(log) = pool_stream.next().await {
                        if SHUTDOWN_FLAG.load(std::sync::atomic::Ordering::Relaxed) {
                            return DisconnectReason::Shutdown;
                        }
                        
                        let raw = log.clone().into();
                        
                        let quote_price_usd = {
                            let s = CORE_STATE.read().unwrap();
                            get_quote_price_usd(&s.quote_symbol, &s.usd_prices)
                        };

                        if let Ok(sync) = <SyncFilter as EthEvent>::decode_log(&raw) {
                            CORE_STATE.write().unwrap().v2_reserves.insert(log.address, (sync.reserve_0.into(), sync.reserve_1.into()));
                            
                            let (liq_usd, price) = calculate_v2_liquidity_usd_and_price(
                                sync.reserve_0.into(), sync.reserve_1.into(), 
                                t_dec, q_dec, t0_is_quote, quote_price_usd 
                            );
                            
                            {
                                let mut s = CORE_STATE.write().unwrap();
                                if s.selected_pool_address == Some(log.address) {
                                    s.selected_pool_spot_price = price;
                                    s.selected_pool_liquidity_usd = liq_usd;
                                }
                            }

                            emit_event(EngineEvent::PoolUpdate {
                                pool_address: format!("{:?}", log.address),
                                pool_type: "V2".into(),
                                token: format!("{:?}", target_token_addr),
                                quote: format!("{:?}", quote_token),
                                reserve0: Some(sync.reserve_0.to_string()),
                                reserve1: Some(sync.reserve_1.to_string()),
                                sqrt_price_x96: None,
                                tick: None,
                                liquidity: None,
                                spot_price: Some(price),
                                liquidity_usd: Some(liq_usd)
                            });
                        }
                        
                        if let Ok(swap) = <SwapFilter as EthEvent>::decode_log(&raw) {
                            let mut s = CORE_STATE.write().unwrap();
                            if let Some(mut pool) = s.v3_states.get_mut(&log.address) {
                                pool.sqrt_price_x96 = swap.sqrt_price_x96;
                                pool.liquidity = swap.liquidity.into();
                                pool.tick = swap.tick;
                            }
                            
                            let (liq_usd, price) = calculate_v3_liquidity_usd_and_price(
                                swap.sqrt_price_x96.into(), swap.liquidity, 
                                t_dec, q_dec, t0_is_quote, quote_price_usd
                            );

                            if s.selected_pool_address == Some(log.address) {
                                s.selected_pool_spot_price = price;
                                s.selected_pool_liquidity_usd = liq_usd;
                            }

                            emit_event(EngineEvent::PoolUpdate {
                                pool_address: format!("{:?}", log.address),
                                pool_type: "V3".into(),
                                token: format!("{:?}", target_token_addr),
                                quote: format!("{:?}", quote_token),
                                reserve0: None,
                                reserve1: None,
                                sqrt_price_x96: Some(swap.sqrt_price_x96.to_string()),
                                tick: Some(swap.tick),
                                liquidity: Some(swap.liquidity),
                                spot_price: Some(price),
                                liquidity_usd: Some(liq_usd)
                            });
                        }
                    }
                    
                    DisconnectReason::StreamEnded("pools".into())
                }
                Err(e) => DisconnectReason::Error(format!("subscribe_logs(pools): {:?}", e))
            }
        });

        let ws_pending = ws.clone();
        
        let pending_txs_task = tokio::spawn(async move {
            emit_log("INFO", "📡 Подписка на pending transactions активна".into());
            let mut check_interval = interval(Duration::from_millis(500));
            
            loop {
                check_interval.tick().await;
                
                if SHUTDOWN_FLAG.load(std::sync::atomic::Ordering::Relaxed) {
                    return DisconnectReason::Shutdown;
                }
                
                let txs_to_check: Vec<H256> = {
                    CORE_STATE.read().unwrap().pending_txs.iter().cloned().collect()
                };
                
                if txs_to_check.is_empty() {
                    continue;
                }
                
                for tx_hash in txs_to_check {
                    match ws_pending.get_transaction_receipt(tx_hash).await {
                        Ok(Some(receipt)) => {
                            let status = if receipt.status.unwrap_or(U64::zero()) == U64::from(1) { "success" } else { "failed" };
                            let gas_used = receipt.gas_used.unwrap_or(U256::zero()).as_u64();
                            let block_num = receipt.block_number.unwrap_or(U64::zero()).as_u64();
                            let from_addr = receipt.from;
                            
                            emit_log("INFO", format!("✅ TX подтверждена: {:?} (статус: {})", tx_hash, status));
                            
                            emit_event(EngineEvent::TxConfirmed {
                                tx_hash: format!("{:?}", tx_hash),
                                wallet: format!("{:?}", from_addr),
                                gas_used,
                                status: status.to_string(),
                                confirm_block: block_num,
                                timestamp_ms: current_timestamp_ms()
                            });
                            
                            CORE_STATE.write().unwrap().pending_txs.remove(&tx_hash);
                        }
                        Ok(None) => {}
                        Err(e) => {
                            emit_log("WARNING", format!("Ошибка проверки receipt {:?}: {:?}", tx_hash, e));
                        }
                    }
                }
            }
        });

        let reason = tokio::select! {
            result = blocks_task => {
                match result {
                    Ok(r) => r,
                    Err(e) => DisconnectReason::Error(format!("blocks_task join error: {:?}", e))
                }
            }
            result = transfers_task => {
                match result {
                    Ok(r) => r,
                    Err(e) => DisconnectReason::Error(format!("transfers_task join error: {:?}", e))
                }
            }
            result = pools_task => {
                match result {
                    Ok(r) => r,
                    Err(e) => DisconnectReason::Error(format!("pools_task join error: {:?}", e))
                }
            }
            result = pending_txs_task => {
                match result {
                    Ok(r) => r,
                    Err(e) => DisconnectReason::Error(format!("pending_txs_task join error: {:?}", e))
                }
            }
            _ = async {
                while !SHUTDOWN_FLAG.load(std::sync::atomic::Ordering::Relaxed) {
                    sleep(Duration::from_millis(100)).await;
                }
            } => {
                DisconnectReason::Shutdown
            }
        };

        reason
    }
}

// ===================== POOL HELPERS =====================

fn calculate_v2_liquidity_usd_and_price(
    reserve0: U256, reserve1: U256, 
    token0_decimals: u8, token1_decimals: u8,
    token0_is_quote: bool, quote_price_usd: f64
) -> (f64, f64) {
    let r0_f = wei_to_float(reserve0, token0_decimals);
    let r1_f = wei_to_float(reserve1, token1_decimals);
    
    if r0_f == 0.0 || r1_f == 0.0 {
        return (0.0, 0.0);
    }
    
    let price_in_quote = if token0_is_quote { r0_f / r1_f } else { r1_f / r0_f };
    let liq = if token0_is_quote { 2.0 * r0_f * quote_price_usd } else { 2.0 * r1_f * quote_price_usd };
    (liq, price_in_quote)
}

fn calculate_v3_liquidity_usd_and_price(
    sqrt_price_x96: U256, liquidity: u128,
    token0_decimals: u8, token1_decimals: u8,
    token0_is_quote: bool, quote_price_usd: f64
) -> (f64, f64) {
    if sqrt_price_x96.is_zero() || liquidity == 0 { return (0.0, 0.0); }
    let sqrt_p = sqrt_price_x96.as_u128() as f64 / 2.0f64.powi(96);
    let price_token1_per_token0 = sqrt_p * sqrt_p;
    
    let price_in_quote = if token0_is_quote { 1.0 / price_token1_per_token0 } else { price_token1_per_token0 };
    
    let tvl = if token0_is_quote {
        let q_amt = (liquidity as f64 / sqrt_p) / 10f64.powi(token0_decimals as i32);
        q_amt * quote_price_usd
    } else {
        let q_amt = (liquidity as f64 * sqrt_p) / 10f64.powi(token1_decimals as i32);
        q_amt * quote_price_usd
    };
    (tvl, price_in_quote)
}

fn select_best_pool(mut candidates: Vec<PoolCandidate>, trade_amount_usd: f64) -> Option<PoolCandidate> {
    emit_log("DEBUG", format!("📊 select_best_pool: {} candidates до фильтра", candidates.len()));
    for p in &candidates {
        emit_log("DEBUG", format!("  - {:?}: type={}, liq={}", p.address, p.pool_type, p.liquidity_usd));
    }
    
    if candidates.is_empty() { return None; }
    candidates.retain(|p| p.liquidity_usd > 10.0);
    
    emit_log("DEBUG", format!("📊 select_best_pool: {} candidates после фильтра (liq > 10)", candidates.len()));
    
    if candidates.is_empty() { 
        emit_log("WARNING", "⚠️ Все пулы отфильтрованы (liq <= 10)".into());
        return None; 
    }
    candidates.retain(|p| p.liquidity_usd > 10.0);
    let max_liq = candidates.iter().map(|p| p.liquidity_usd).fold(0.0, f64::max);
    let max_fee = candidates.iter().map(|p| p.fee_bps as f64).fold(0.0, f64::max);
    for p in &mut candidates {
        let norm_liq = if max_liq > 0.0 { p.liquidity_usd / max_liq } else { 0.0 };
        let norm_fee = if max_fee > 0.0 { p.fee_bps as f64 / max_fee } else { 1.0 };
        let impact = if p.liquidity_usd > 0.0 { (trade_amount_usd / p.liquidity_usd).min(1.0) } else { 1.0 };
        p.score = WEIGHT_LIQUIDITY * norm_liq + WEIGHT_FEE * (1.0 - norm_fee) + WEIGHT_PRICE_IMPACT * (1.0 - impact);
    }
    candidates.sort_by(|a, b| b.score.partial_cmp(&a.score).unwrap_or(std::cmp::Ordering::Equal));
    candidates.into_iter().next()
}

// ===================== PUBLIC API =====================

pub async fn discover_pools(token: Address, quote: Address) -> Vec<Address> {
    let mut targets = vec![token];
    let (v2_f, v3_f) = { let s = CORE_STATE.read().unwrap(); (s.v2_factory_address, s.v3_factory_address) };
    let rpc_urls = { RPC_POOL.read().get_fastest_pool(5) };
    
    // === ДОБАВИТЬ ЛОГИ ===
    emit_log("DEBUG", format!("discover_pools: {} RPC URLs", rpc_urls.len()));
    for (i, url) in rpc_urls.iter().enumerate() {
        emit_log("DEBUG", format!("  RPC[{}]: {}...", i, &url[..50.min(url.len())]));
    }
    
    let provider_http = {
        let mut result = None;
        for url in rpc_urls {
            if let Ok(u) = Url::parse(&url) {
                let p = Arc::new(Provider::new(Http::new_with_client(u, GLOBAL_HTTP_CLIENT.clone())));
                match timeout(Duration::from_secs(3), p.get_block_number()).await {
                    Ok(_) => {
                        emit_log("DEBUG", format!("RPC OK: {}", &url[..50.min(url.len())]));
                        result = Some(p);
                        break;
                    }
                    Err(_) => {
                        emit_log("WARNING", format!("RPC TIMEOUT: {}", &url[..50.min(url.len())]));
                    }
                }
            }
        }
        result
    }; 
    
    let p = if let Some(provider) = provider_http { 
        emit_log("DEBUG", "Provider selected successfully".to_string());
        provider 
    } else { 
        emit_log("ERROR", "NO PROVIDER - all RPCs failed!".to_string());
        return targets; 
    };
    
    // === V2 ===
    emit_log("DEBUG", format!("V2 factory: {:?}", v2_f));
    if v2_f != Address::zero() {
        let f = UniversalABI::new(v2_f, p.clone());
        match f.get_pair(token, quote).call().await {
            Ok(pair) => {
                emit_log("DEBUG", format!("get_pair result: {:?}", pair));
                if pair != Address::zero() { targets.push(pair); }
            }
            Err(e) => {
                emit_log("ERROR", format!("get_pair error: {:?}", e));
            }
        }
    }
    
    // === V3 ===
    if v3_f != Address::zero() {
        let f = UniversalABI::new(v3_f, p.clone());
        for fee in [100, 500, 2500, 10000] {
            match f.get_pool(token, quote, fee).call().await {
                Ok(pool) => {
                    if pool != Address::zero() { 
                        emit_log("DEBUG", format!("V3 pool found: fee={}, addr={:?}", fee, pool));
                        targets.push(pool); 
                        CORE_STATE.write().unwrap().v3_states.insert(pool, V3PoolState { 
                            pool_fee: fee, ..Default::default() 
                        });
                    }
                }
                Err(e) => {
                    emit_log("DEBUG", format!("V3 fee {} error: {:?}", fee, e));
                }
            }
        }
    }
    
    emit_log("DEBUG", format!("discover_pools: {} targets found", targets.len()));
    targets
}

pub async fn start_unified_websocket_monitor(
    wss_url: String,
    token: Address,
    quote: Address,
    all_quotes: Vec<(String, Address)>
) {
    emit_log("INFO", format!("🚀 Поиск пулов для токена {:?}", token));
    
    // Ищем пулы для выбранного quote
    let pools_for_selected = discover_pools(token, quote).await;
    let has_pools = pools_for_selected.len() > 1;
    
    if has_pools {
        emit_log("SUCCESS", format!("✅ Найдено {} пулов", pools_for_selected.len() - 1));
        let wallets: Vec<Address> = TRACKED_WALLETS.read().unwrap().clone();
        let mut ws_manager = WebSocketManager::new(wss_url);
        ws_manager.run_forever(wallets, quote, pools_for_selected, token, quote).await;
        return;
    }
    
    // Пулов нет для выбранного - ищем по другим quote
    emit_log("WARNING", "⚠️ Пулы не найдены для выбранного quote".to_string());
    
    let mut found_quotes: Vec<(String, Address)> = vec![];
    for (sym, q_addr) in all_quotes.iter() {
        if *q_addr == quote { continue; }
        let pools = discover_pools(token, *q_addr).await;
        if pools.len() > 1 {
            found_quotes.push((sym.clone(), *q_addr));
        }
    }
    
    if found_quotes.is_empty() {
        emit_log("ERROR", "❌ Пулы не найдены ни для одного quote токена".to_string());
        emit_event(EngineEvent::PoolNotFound { 
            token: format!("{:?}", token), 
            selected_quote: CORE_STATE.read().unwrap().quote_symbol.clone(),
            available_quotes: vec![]
        });
        return;
    }
    
    let symbols: Vec<String> = found_quotes.iter().map(|(s, _)| s.clone()).collect();
    emit_log("WARNING", format!("⚠️ Пулы найдены для: {}", symbols.join(", ")));
    
    emit_event(EngineEvent::PoolNotFound { 
        token: format!("{:?}", token), 
        selected_quote: CORE_STATE.read().unwrap().quote_symbol.clone(),
        available_quotes: found_quotes.iter().map(|(s, a)| (s.clone(), format!("{:?}", a))).collect()
    });
}

pub async fn rpc_health_checker(urls: Vec<String>) {
    let mut check_interval = interval(Duration::from_secs(10));
    
    loop {
        check_interval.tick().await;
        if SHUTDOWN_FLAG.load(std::sync::atomic::Ordering::Relaxed) { break; }
        
        for url_str in &urls {
            let start = Instant::now();
            if let Ok(url) = Url::parse(url_str) {
                let provider = Provider::new(Http::new_with_client(url, GLOBAL_HTTP_CLIENT.clone()));
                if timeout(Duration::from_secs(2), provider.get_block_number()).await.is_ok() {
                    RPC_POOL.write().update_latency(url_str, start.elapsed().as_micros());
                } else { 
                    RPC_POOL.write().mark_fail(url_str); 
                }
            }
        }
    }
}

pub async fn start_background_worker(_wss_url: String) {
    let mut last_quote_balance_update = Instant::now();
    
    loop {
        if SHUTDOWN_FLAG.load(std::sync::atomic::Ordering::Relaxed) { break; }
        
        let wallets: Vec<Address> = TRACKED_WALLETS.read().unwrap().clone();
        let url_opt = { let p = RPC_POOL.read(); p.get_fastest_node() };
        let quote_token = { CORE_STATE.read().unwrap().fuel_quote_address };
        
        if let Some(url_str) = url_opt {
            if let Ok(url) = Url::parse(&url_str) {
                let provider = Provider::new(Http::new_with_client(url, GLOBAL_HTTP_CLIENT.clone()));
                
                for wallet in &wallets {
                    if let Ok(nonce) = provider.get_transaction_count(*wallet, None).await {
                        CORE_STATE.write().unwrap().nonce_map.insert(*wallet, nonce.as_u64());
                    }
                }
                
                if last_quote_balance_update.elapsed().as_secs() > 5 {
                    if quote_token != Address::zero() {
                        let decimals = get_decimals_cached(quote_token).await;
                        for wallet in &wallets {
                            let balance = execution::get_token_balance(quote_token, *wallet).await;
                            if !balance.is_zero() {
                                let float_val = wei_to_float(balance, decimals);
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
                    last_quote_balance_update = Instant::now();
                }
            }
        }
        
        sleep(Duration::from_secs(1)).await;
    }
}
