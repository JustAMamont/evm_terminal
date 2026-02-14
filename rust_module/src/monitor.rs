use pyo3::prelude::*;
use pyo3::exceptions::PyValueError;
use ethers::prelude::*;
use ethers::providers::{Provider, Http, Ws, StreamExt};
use ethers::types::{Address, U256, H256, Filter, BlockNumber, Bytes, Log, U64, TransactionRequest};
use ethers::types::transaction::eip2718::TypedTransaction;
use std::str::FromStr;
use std::sync::{Arc, RwLock};
use std::sync::atomic::Ordering;
use tokio::time::{sleep, timeout, Duration, Instant};
use url::Url;
use std::collections::{HashSet, HashMap, VecDeque};
use futures::future::join_all;

use crate::state::{
    RUNTIME, SHUTDOWN_FLAG, CORE_STATE, TRACKED_WALLETS, MONITOR_HANDLE,
    EVENT_QUEUE, BotState, TransferEvent, GLOBAL_HTTP_CLIENT,
    BEST_POOL_STATE, POOL_SCANNER_HANDLE, RPC_POOL, RpcNode
};

// --- ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ---

/// Получает HTTP провайдер из пула доступных нод (Load Balancer)
fn get_provider_from_pool() -> Result<Provider<Http>, String> {
    let url_str = {
        let mut pool = RPC_POOL.write().unwrap();
        match pool.get_next_url() {
            Some(url) => url,
            None => return Err("No RPC nodes available in pool".to_string()),
        }
    };

    let url = match Url::parse(&url_str) {
        Ok(u) => u,
        Err(e) => return Err(format!("Invalid RPC URL: {}", e)),
    };

    let client = GLOBAL_HTTP_CLIENT.clone();
    Ok(Provider::new(Http::new_with_client(url, client)))
}

/// Воркер проверки здоровья нод. Обновляет задержки и фильтрует мертвые RPC.
async fn rpc_health_checker(private_rpc: String, public_rpcs: Vec<String>) {
    let mut all_urls = public_rpcs;
    all_urls.push(private_rpc.clone());
    all_urls.sort();
    all_urls.dedup();

    while !SHUTDOWN_FLAG.load(Ordering::Relaxed) {
        let mut checks = Vec::new();
        
        for url in &all_urls {
            let url_clone = url.clone();
            checks.push(async move {
                let start = Instant::now();
                let client = GLOBAL_HTTP_CLIENT.clone();
                
                let parsed_url = match Url::parse(&url_clone) {
                    Ok(u) => u,
                    Err(_) => return None,
                };
                
                let provider = Provider::new(Http::new_with_client(parsed_url, client));
                
                // Используем тайм-аут 2 секунды для проверки отклика
                match timeout(Duration::from_secs(2), provider.get_block_number()).await {
                    Ok(Ok(_)) => Some((url_clone, start.elapsed())),
                    _ => None,
                }
            });
        }

        let results: Vec<_> = join_all(checks).await.into_iter().flatten().collect();
        
        let mut healthy_nodes: Vec<RpcNode> = results.into_iter().map(|(url, duration)| {
            RpcNode { 
                url, 
                latency: duration.as_secs_f32() 
            }
        }).collect();

        // Сортировка: приватный RPC в приоритете, остальные по задержке
        healthy_nodes.sort_by(|a, b| {
            let a_is_private = a.url == private_rpc;
            let b_is_private = b.url == private_rpc;
            
            if a_is_private && !b_is_private {
                std::cmp::Ordering::Less
            } else if !a_is_private && b_is_private {
                std::cmp::Ordering::Greater
            } else {
                a.latency.partial_cmp(&b.latency).unwrap_or(std::cmp::Ordering::Equal)
            }
        });

        // Обновляем глобальный пул
        if !healthy_nodes.is_empty() {
             let mut pool = RPC_POOL.write().unwrap();
             pool.nodes = healthy_nodes;
             pool.current_index = 0;
        }
        
        sleep(Duration::from_secs(10)).await;
    }
}

/// Синхронизация Нонса для кошелька (Агрессивная)
async fn fetch_and_update_nonce(state_arc: Arc<RwLock<BotState>>, wallet_addr: Address) {
    let provider = match get_provider_from_pool() {
        Ok(p) => p,
        Err(_) => return,
    };

    match timeout(Duration::from_secs(2), provider.get_transaction_count(wallet_addr, Some(BlockNumber::Pending.into()))).await {
        Ok(Ok(nonce)) => {
            let mut state = state_arc.write().unwrap();
            let current = state.nonce_map.entry(wallet_addr).or_insert(0);
            if nonce.as_u64() > *current {
                *current = nonce.as_u64();
            }
        },
        _ => {
            // Игнорируем ошибки сети, попробуем в следующий раз
        }
    }
}

/// Гибридный мониторинг цены газа (WSS + HTTP Fallback)
async fn hybrid_gas_monitor(wss_url: String, state_arc: Arc<RwLock<BotState>>) {
    loop {
        if SHUTDOWN_FLAG.load(Ordering::Relaxed) { break; }
        
        // Попытка подключения к WSS
        let provider_ws = match Provider::<Ws>::connect(&wss_url).await {
            Ok(p) => Arc::new(p),
            Err(_) => {
                // Если WSS упал, берем цену по HTTP
                if let Ok(http) = get_provider_from_pool() {
                    if let Ok(gas) = http.get_gas_price().await {
                        let mut s = state_arc.write().unwrap();
                        s.gas_price = gas;
                    }
                }
                sleep(Duration::from_millis(500)).await;
                continue;
            }
        };

        // Snapshot при старте/реконнекте
        if let Ok(gas) = provider_ws.get_gas_price().await {
            let mut s = state_arc.write().unwrap();
            s.gas_price = gas;
        }

        // Подписка на новые блоки
        if let Ok(mut stream) = provider_ws.subscribe_blocks().await {
            while let Some(_) = stream.next().await {
                if SHUTDOWN_FLAG.load(Ordering::Relaxed) { break; }
                
                if let Ok(gas) = provider_ws.get_gas_price().await {
                    let mut s = state_arc.write().unwrap();
                    if s.gas_price != gas {
                        s.gas_price = gas;
                    }
                }
            }
        }
        
        sleep(Duration::from_millis(100)).await;
    }
}

/// Обработка лога Transfer для токенов
fn process_token_log(log: Log) {
    if log.topics.len() >= 3 {
        let to_addr = Address::from(log.topics[2]);
        let amount = U256::from_big_endian(&log.data);
        let tx_hash = log.transaction_hash.unwrap_or_default();
        
        let event: TransferEvent = (
            format!("{:?}", to_addr), 
            format!("{:?}", log.address), 
            amount.to_string(), 
            format!("{:?}", tx_hash)
        );
        
        match EVENT_QUEUE.lock() {
            Ok(mut queue) => {
                queue.push(event);
            },
            Err(_) => {
                eprintln!("[RUST ERR] Event queue lock poisoned");
            }
        }
    }
}

/// Гибридный монитор токена (WSS + HTTP Snapshot) с LRU-кэшем TX-хешей
async fn hybrid_token_log_monitor(wss_url: String, token_address: Address, wallets_arc: Arc<RwLock<Vec<Address>>>) {
    let mut processed_txs: HashSet<H256> = HashSet::with_capacity(1100);
    let mut tx_queue: VecDeque<H256> = VecDeque::with_capacity(1100);
    let mut last_sync_block: Option<U64> = None;

    loop {
        if SHUTDOWN_FLAG.load(Ordering::Relaxed) { break; }
        
        let provider_ws = match Provider::<Ws>::connect(&wss_url).await {
            Ok(p) => p,
            Err(_) => { 
                sleep(Duration::from_millis(200)).await; 
                continue; 
            }
        };

        // --- HTTP Snapshot (Наверстывание пропущенного) ---
        if let Ok(http_provider) = get_provider_from_pool() {
            let my_wallets = {
                let guard = wallets_arc.read().unwrap();
                guard.clone()
            };
            
            if !my_wallets.is_empty() {
                let wallets_h256: Vec<H256> = my_wallets.iter().map(|w| H256::from(*w)).collect();
                
                if let Ok(latest) = http_provider.get_block_number().await {
                    // Если это первый запуск, смотрим последние 15 блоков
                    let from = last_sync_block.map_or(latest.saturating_sub(U64::from(15)), |b| b + 1);
                    
                    let filter = Filter::new()
                        .address(token_address)
                        .event("Transfer(address,address,uint256)")
                        .topic2(wallets_h256)
                        .from_block(from)
                        .to_block(latest);
                    
                    if let Ok(logs) = http_provider.get_logs(&filter).await {
                        for log in logs {
                            if let Some(tx_hash) = log.transaction_hash {
                                if processed_txs.insert(tx_hash) {
                                    tx_queue.push_back(tx_hash);
                                    // Очистка старых хешей (LRU)
                                    if tx_queue.len() > 1000 {
                                        if let Some(old) = tx_queue.pop_front() {
                                            processed_txs.remove(&old);
                                        }
                                    }
                                    process_token_log(log);
                                }
                            }
                        }
                    }
                    last_sync_block = Some(latest);
                }
            }
        }

        // --- WSS Subscription (Слушаем новые) ---
        let my_wallets_ws = wallets_arc.read().unwrap().clone();
        let wallets_h256_ws: Vec<H256> = my_wallets_ws.iter().map(|w| H256::from(*w)).collect();
        
        let filter_ws = Filter::new()
            .address(token_address)
            .event("Transfer(address,address,uint256)")
            .topic2(wallets_h256_ws);

        if let Ok(mut stream) = provider_ws.subscribe_logs(&filter_ws).await {
            while let Some(log) = stream.next().await {
                if let Some(tx_hash) = log.transaction_hash {
                    if processed_txs.insert(tx_hash) {
                        tx_queue.push_back(tx_hash);
                        if tx_queue.len() > 1000 {
                            if let Some(old) = tx_queue.pop_front() {
                                processed_txs.remove(&old);
                            }
                        }
                        process_token_log(log);
                    }
                }
            }
        }
        
        sleep(Duration::from_millis(100)).await;
    }
}

/// Логика обновления баланса пула при получении лога
fn process_pool_log(log: Log, pool_map: &HashMap<Address, Address>) {
    if log.topics.len() < 3 { return; }
    let from = Address::from(log.topics[1]);
    let to = Address::from(log.topics[2]);
    
    let pool_to_check = if pool_map.contains_key(&from) { Some(from) } 
                        else if pool_map.contains_key(&to) { Some(to) } 
                        else { None };

    if let Some(pool_addr) = pool_to_check {
        let quote_token = log.address;
        
        // Запускаем асинхронную задачу на получение баланса
        tokio::spawn(async move {
            if let Ok(provider) = get_provider_from_pool() {
                // ERC20 balanceOf(address) selector
                let mut calldata = [0u8; 36];
                calldata[0..4].copy_from_slice(&[0x70, 0xa0, 0x82, 0x31]); 
                calldata[16..36].copy_from_slice(pool_addr.as_bytes());
                
                let tx_req = TransactionRequest::new()
                    .to(quote_token)
                    .data(Bytes::from(calldata.to_vec()));
                
                let tx = TypedTransaction::Legacy(tx_req);
                
                if let Ok(bytes) = provider.call(&tx, None).await {
                    if bytes.len() >= 32 {
                        let new_bal = U256::from_big_endian(&bytes[0..32]);
                        
                        // Обновляем глобальное состояние балансов пулов
                        let mut balances = crate::state::POOL_BALANCES.write().unwrap();
                        balances.insert(format!("{:?}", pool_addr), new_bal.to_string());
                    }
                }
            }
        });
    }
}

/// Мониторинг логов конкретного Quote-токена для обновления балансов всех связанных пулов
async fn single_quote_pool_monitor(wss_url: String, pool_map: Arc<HashMap<Address, Address>>, quote_addr: Address) {
    let mut processed_txs: HashSet<H256> = HashSet::with_capacity(1100);
    let mut tx_queue: VecDeque<H256> = VecDeque::with_capacity(1100);
    let mut last_sync_block: Option<U64> = None;

    loop {
        if SHUTDOWN_FLAG.load(Ordering::Relaxed) { break; }
        
        let provider_ws = match Provider::<Ws>::connect(&wss_url).await {
            Ok(p) => p,
            Err(_) => { 
                sleep(Duration::from_millis(200)).await; 
                continue; 
            }
        };

        // HTTP Snapshot при каждом реконнекте
        if let Ok(http) = get_provider_from_pool() {
            if let Ok(latest) = http.get_block_number().await {
                let from = last_sync_block.map_or(latest.saturating_sub(U64::from(5)), |b| b + 1);
                
                let filter = Filter::new()
                    .address(quote_addr)
                    .event("Transfer(address,address,uint256)")
                    .from_block(from)
                    .to_block(latest);
                
                if let Ok(logs) = http.get_logs(&filter).await {
                    for log in logs {
                        if let Some(tx_hash) = log.transaction_hash {
                            if processed_txs.insert(tx_hash) {
                                tx_queue.push_back(tx_hash);
                                if tx_queue.len() > 1000 {
                                    if let Some(old) = tx_queue.pop_front() {
                                        processed_txs.remove(&old);
                                    }
                                }
                                process_pool_log(log, &pool_map);
                            }
                        }
                    }
                }
                last_sync_block = Some(latest);
            }
        }

        // WSS Subscription
        let filter_ws = Filter::new()
            .address(quote_addr)
            .event("Transfer(address,address,uint256)");
            
        if let Ok(mut stream) = provider_ws.subscribe_logs(&filter_ws).await {
            while let Some(log) = stream.next().await {
                if let Some(tx_hash) = log.transaction_hash {
                    if processed_txs.insert(tx_hash) {
                        tx_queue.push_back(tx_hash);
                        if tx_queue.len() > 1000 {
                            if let Some(old) = tx_queue.pop_front() {
                                processed_txs.remove(&old);
                            }
                        }
                        process_pool_log(log, &pool_map);
                    }
                }
            }
        }
        
        sleep(Duration::from_millis(100)).await;
    }
}

/// Оркестратор гибридного мониторинга пулов
async fn hybrid_pool_monitor(wss_url: String, pool_to_quote_map: HashMap<Address, Address>) {
    // 1. Первичный Snapshot балансов всех пулов (HTTP)
    if let Ok(http_provider) = get_provider_from_pool() {
        let http_arc = Arc::new(http_provider);
        let mut sync_futures = Vec::new();
        
        for (&pool_addr, &quote_addr) in &pool_to_quote_map {
            let prov = http_arc.clone();
            sync_futures.push(async move {
                let mut calldata = [0u8; 36];
                calldata[0..4].copy_from_slice(&[0x70, 0xa0, 0x82, 0x31]); // balanceOf
                calldata[16..36].copy_from_slice(pool_addr.as_bytes());
                
                let tx = TypedTransaction::Legacy(
                    TransactionRequest::new().to(quote_addr).data(Bytes::from(calldata.to_vec()))
                );
                
                match prov.call(&tx, None).await {
                    Ok(bytes) if bytes.len() >= 32 => {
                        Some((pool_addr, U256::from_big_endian(&bytes[0..32])))
                    },
                    _ => None,
                }
            });
        }

        let results = join_all(sync_futures).await;
        
        {
            let mut b_guard = crate::state::POOL_BALANCES.write().unwrap();
            for res in results.into_iter().flatten() {
                b_guard.insert(format!("{:?}", res.0), res.1.to_string());
            }
        }
    }
    
    // 2. Группируем пулы по Quote-токенам для подписки
    let mut unique_quotes = HashSet::new();
    pool_to_quote_map.values().for_each(|&q| { unique_quotes.insert(q); });

    let mut tasks = Vec::new();
    let p_map_arc = Arc::new(pool_to_quote_map);
    
    for quote_addr in unique_quotes {
        tasks.push(tokio::spawn(single_quote_pool_monitor(wss_url.clone(), p_map_arc.clone(), quote_addr)));
    }
    
    join_all(tasks).await;
}

// --- ЭКСПОРТИРУЕМЫЕ ФУНКЦИИ (PYTHON) ---

#[pyfunction]
pub fn reset_rust_state(_py: Python<'_>) -> PyResult<()> {
    // 1. Сбрасываем флаг остановки
    SHUTDOWN_FLAG.store(false, Ordering::Relaxed);

    // 2. Очищаем состояние ядра
    if let Ok(mut state) = CORE_STATE.write() {
        state.nonce_map.clear();
        state.gas_price = U256::zero();
    }

    // 3. Очищаем пул RPC
    if let Ok(mut pool) = RPC_POOL.write() {
        pool.nodes.clear();
        pool.current_index = 0;
    }

    // 4. Очищаем список кошельков
    if let Ok(mut wallets) = TRACKED_WALLETS.write() {
        wallets.clear();
    }

    // 5. Очищаем балансы пулов
    if let Ok(mut balances) = crate::state::POOL_BALANCES.write() {
        balances.clear();
    }

    // 6. Убиваем WSS мониторы
    if let Some(handle) = MONITOR_HANDLE.lock().unwrap().take() {
        handle.abort();
    }
    if let Some(handle) = POOL_SCANNER_HANDLE.lock().unwrap().take() {
        handle.abort();
    }

    // 7. Очищаем очередь событий
    if let Ok(mut queue) = EVENT_QUEUE.lock() {
        queue.clear();
    }
    
    // 8. Сбрасываем лучший пул
    *BEST_POOL_STATE.write().unwrap() = None;

    Ok(())
}

#[pyfunction]
pub fn get_healthy_rpc_urls(_py: Python<'_>, count: usize) -> PyResult<Vec<String>> {
    let pool = RPC_POOL.read().unwrap();
    let urls = pool.nodes.iter()
        .take(count)
        .map(|node| node.url.clone())
        .collect();
    Ok(urls)
}

#[pyfunction]
pub fn get_best_rpc_url(_py: Python<'_>) -> PyResult<Option<String>> {
    let pool = RPC_POOL.read().unwrap();
    if let Some(node) = pool.nodes.get(0) {
        Ok(Some(node.url.clone()))
    } else {
        Ok(None)
    }
}

#[pyfunction]
pub fn start_pool_scanner(_py: Python<'_>, wss_url: String, pool_to_quote_map_py: HashMap<String, String>) -> PyResult<()> {
    let mut pool_to_quote_map: HashMap<Address, Address> = HashMap::new();
    
    for (pool, quote) in pool_to_quote_map_py {
        let p_addr = match Address::from_str(&pool) {
            Ok(a) => a,
            Err(_) => continue,
        };
        let q_addr = match Address::from_str(&quote) {
            Ok(a) => a,
            Err(_) => continue,
        };
        pool_to_quote_map.insert(p_addr, q_addr);
    }
    
    if pool_to_quote_map.is_empty() { return Ok(()); }
    
    let mut handle_guard = POOL_SCANNER_HANDLE.lock().unwrap();
    if let Some(handle) = handle_guard.take() { 
        handle.abort(); 
    }
    
    let join_handle = RUNTIME.spawn(async move {
        hybrid_pool_monitor(wss_url, pool_to_quote_map).await;
    });
    
    *handle_guard = Some(join_handle.abort_handle());
    Ok(())
}

#[pyfunction]
pub fn stop_pool_scanner(_py: Python<'_>) -> PyResult<()> {
    let mut handle_guard = POOL_SCANNER_HANDLE.lock().unwrap();
    if let Some(handle) = handle_guard.take() {
        handle.abort();
    }
    
    let mut state = BEST_POOL_STATE.write().unwrap();
    *state = None;
    Ok(())
}

#[pyfunction]
pub fn get_best_pool_address(_py: Python<'_>) -> PyResult<Option<(String, String)>> {
    let guard = BEST_POOL_STATE.read().unwrap();
    Ok(guard.clone())
}

#[pyfunction]
pub fn start_state_workers(
    _py: Python<'_>, 
    private_rpc: String, 
    public_rpcs: Vec<String>, 
    initial_wallets_strs: Vec<String>, 
    wss_url: Option<String>
) -> PyResult<()> {
    // Запускаем Health Checker
    RUNTIME.spawn(async move { 
        rpc_health_checker(private_rpc, public_rpcs).await; 
    });
    
    let state_arc = CORE_STATE.clone();
    let wallets_arc = TRACKED_WALLETS.clone();

    // Загружаем начальные кошельки
    { 
        let mut tracked_wallets = wallets_arc.write().unwrap(); 
        for s in initial_wallets_strs { 
            if let Ok(addr) = Address::from_str(&s) { 
                if !tracked_wallets.contains(&addr) { 
                    tracked_wallets.push(addr); 
                } 
            } 
        } 
    }
    
    // Запускаем монитор газа
    if let Some(ws) = wss_url {
        let state_gas = state_arc.clone();
        RUNTIME.spawn(async move { 
            hybrid_gas_monitor(ws, state_gas).await; 
        });
    }
    
    // Запускаем монитор нонсов
    let state_nonce = state_arc.clone(); 
    RUNTIME.spawn(async move { 
        while !SHUTDOWN_FLAG.load(Ordering::Relaxed) { 
            let current_wallets = { 
                let guard = wallets_arc.read().unwrap(); 
                guard.clone() 
            }; 
            
            let mut nonce_tasks = Vec::new();
            for wallet_addr in current_wallets { 
                nonce_tasks.push(fetch_and_update_nonce(state_nonce.clone(), wallet_addr));
            }
            
            join_all(nonce_tasks).await;
            sleep(Duration::from_millis(1500)).await; 
        } 
    });
    
    Ok(())
}

#[pyfunction]
pub fn start_token_monitor(_py: Python<'_>, wss_url: String, token_address_str: String) -> PyResult<()> { 
    let token_addr = Address::from_str(&token_address_str)
        .map_err(|e| PyValueError::new_err(format!("Bad token address: {}", e)))?; 
        
    let mut handle_guard = MONITOR_HANDLE.lock().unwrap(); 
    if let Some(handle) = handle_guard.take() { 
        handle.abort(); 
    }

    let wallets_arc = TRACKED_WALLETS.clone(); 
    let join_handle = RUNTIME.spawn(async move { 
        hybrid_token_log_monitor(wss_url, token_addr, wallets_arc).await; 
    }); 
    
    *handle_guard = Some(join_handle.abort_handle()); 
    Ok(()) 
}

#[pyfunction]
pub fn stop_token_monitor(_py: Python<'_>) -> PyResult<()> { 
    let mut handle_guard = MONITOR_HANDLE.lock().unwrap(); 
    if let Some(handle) = handle_guard.take() { 
        handle.abort(); 
    } 
    Ok(()) 
}

#[pyfunction]
pub fn get_pending_events(_py: Python<'_>) -> PyResult<Vec<TransferEvent>> { 
    let mut queue = EVENT_QUEUE.lock().unwrap(); 
    if queue.is_empty() { 
        return Ok(Vec::new()); 
    } 
    let events = queue.drain(..).collect(); 
    Ok(events) 
}

#[pyfunction]
pub fn add_wallet_to_monitor(_py: Python<'_>, wallet_str: String) -> PyResult<()> { 
    let addr = Address::from_str(&wallet_str)
        .map_err(|_| PyValueError::new_err("Invalid wallet address"))?; 
        
    { 
        let mut tracked = TRACKED_WALLETS.write().unwrap(); 
        if !tracked.contains(&addr) { 
            tracked.push(addr); 
        } 
    } 
    
    let state_arc = CORE_STATE.clone(); 
    RUNTIME.spawn(async move { 
        fetch_and_update_nonce(state_arc, addr).await; 
    }); 
    Ok(()) 
}

#[pyfunction]
pub fn remove_wallet_from_monitor(_py: Python<'_>, wallet_str: String) -> PyResult<()> { 
    let addr = Address::from_str(&wallet_str)
        .map_err(|_| PyValueError::new_err("Invalid wallet address"))?; 
        
    let mut tracked = TRACKED_WALLETS.write().unwrap(); 
    tracked.retain(|&x| x != addr); 
    
    let mut state = CORE_STATE.write().unwrap(); 
    state.nonce_map.remove(&addr); 
    
    Ok(()) 
}

#[pyfunction]
pub fn force_resync_nonce(_py: Python<'_>, wallet_str: String) -> PyResult<()> { 
    let addr = Address::from_str(&wallet_str)
        .map_err(|_| PyValueError::new_err("Invalid wallet address"))?; 
        
    let state_arc = CORE_STATE.clone(); 
    RUNTIME.spawn(async move { 
        fetch_and_update_nonce(state_arc, addr).await; 
    }); 
    Ok(()) 
}

#[pyfunction]
pub fn shutdown_rust_workers() -> PyResult<()> { 
    SHUTDOWN_FLAG.store(true, Ordering::Relaxed); 
    Ok(()) 
}

#[pyfunction]
pub fn get_all_pool_balances(_py: Python<'_>) -> PyResult<HashMap<String, String>> {
    let guard = crate::state::POOL_BALANCES.read().unwrap();
    Ok(guard.clone())
}

#[pyfunction]
pub fn clear_pool_balances(_py: Python<'_>) -> PyResult<()> {
    let mut guard = crate::state::POOL_BALANCES.write().unwrap();
    guard.clear();
    Ok(())
}