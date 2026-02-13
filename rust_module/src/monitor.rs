use pyo3::prelude::*;
use pyo3::exceptions::PyValueError;
use ethers::prelude::*;
use ethers::providers::{Provider, Http, Ws, StreamExt};
use ethers::types::{Address, U256, H256, Filter, BlockNumber, Bytes};
use std::str::FromStr;
use std::sync::{Arc, RwLock};
use std::sync::atomic::Ordering;
use tokio::time::{sleep, timeout, Duration, Instant};
use url::Url;
use std::collections::{HashSet, HashMap};
use futures::future::join_all;

use crate::state::{
    RUNTIME, SHUTDOWN_FLAG, CORE_STATE, TRACKED_WALLETS, MONITOR_HANDLE, 
    EVENT_QUEUE, BotState, TransferEvent, GLOBAL_HTTP_CLIENT, 
    BEST_POOL_STATE, POOL_SCANNER_HANDLE, RPC_POOL, RpcNode
};

// --- ВСПОМОГАТЕЛЬНАЯ ФУНКЦИЯ для получения провайдера из пула ---
fn get_provider_from_pool() -> Result<Provider<Http>, String> {
    let url_str = {
        let mut pool = RPC_POOL.write().unwrap();
        pool.get_next_url().ok_or("В пуле нет доступных RPC нод".to_string())?
    };
    let url = Url::parse(&url_str).map_err(|e| format!("Неверный RPC URL из пула: {}", e))?;
    let client = GLOBAL_HTTP_CLIENT.clone();
    Ok(Provider::new(Http::new_with_client(url, client)))
}


// --- ВОРКЕР ПРОВЕРКИ ЗДОРОВЬЯ RPC ---
async fn rpc_health_checker(private_rpc: String, public_rpcs: Vec<String>) {
    let mut all_urls = public_rpcs;
    all_urls.push(private_rpc.clone());
    all_urls.sort();
    all_urls.dedup();

    let client = GLOBAL_HTTP_CLIENT.clone();

    while !SHUTDOWN_FLAG.load(Ordering::Relaxed) {
        let mut checks = Vec::new();
        for url in &all_urls {
            let client_clone = client.clone();
            let url_clone = url.clone();
            checks.push(async move {
                let start = Instant::now();
                let provider = Provider::new(Http::new_with_client(Url::parse(&url_clone).unwrap(), client_clone));
                // Используем запрос, который требует от ноды актуальных данных (получение последнего блока)
                match provider.get_block(BlockNumber::Latest).await {
                    Ok(Some(_)) => Some((url_clone, start.elapsed())),
                    _ => None,
                }
            });
        }

        let results: Vec<_> = join_all(checks).await.into_iter().flatten().collect();

        let mut healthy_nodes: Vec<RpcNode> = results.into_iter().map(|(url, duration)| {
            RpcNode { url, latency: duration.as_secs_f32() }
        }).collect();

        // Сортируем: приватный RPC всегда первый, если здоров, остальные по скорости
        healthy_nodes.sort_by(|a, b| {
            let a_is_private = a.url == private_rpc;
            let b_is_private = b.url == private_rpc;
            if a_is_private && !b_is_private { std::cmp::Ordering::Less }
            else if !a_is_private && b_is_private { std::cmp::Ordering::Greater }
            else { a.latency.partial_cmp(&b.latency).unwrap_or(std::cmp::Ordering::Equal) }
        });

        if !healthy_nodes.is_empty() {
             let mut pool = RPC_POOL.write().unwrap();
             pool.nodes = healthy_nodes;
             pool.current_index = 0; // Сбрасываем индекс, чтобы начать с самой быстрой ноды
        }

        // Проверяем здоровье каждые 30 секунд
        sleep(Duration::from_secs(30)).await;
    }
}


async fn fetch_and_update_nonce(state_arc: Arc<RwLock<BotState>>, wallet_addr: Address) {
    if let Ok(provider) = get_provider_from_pool() {
        if let Ok(Ok(nonce)) = timeout(Duration::from_secs(5), provider.get_transaction_count(wallet_addr, Some(BlockNumber::Pending.into()))).await {
            let mut state = state_arc.write().unwrap();
            let current = state.nonce_map.entry(wallet_addr).or_insert(0);
            if nonce.as_u64() > *current {
                *current = nonce.as_u64();
            }
        }
    }
}

async fn wss_gas_monitor(wss_url: String, state_arc: Arc<RwLock<BotState>>) {
    loop {
        if SHUTDOWN_FLAG.load(Ordering::Relaxed) { break; }
        let ws_client = match Provider::<Ws>::connect(&wss_url).await {
            Ok(ws) => ws,
            Err(_) => { 
                // HTTP-фолбэк, в случае сбоя WSS
                if let Ok(provider) = get_provider_from_pool() {
                    if let Ok(gas) = provider.get_gas_price().await {
                         let mut state = state_arc.write().unwrap();
                         state.gas_price = gas;
                    }
                }
                sleep(Duration::from_secs(5)).await; 
                continue; 
            }
        };
        let provider = Arc::new(ws_client);
        if let Ok(gas) = provider.get_gas_price().await {
            let mut state = state_arc.write().unwrap();
            state.gas_price = gas;
        }
        match provider.subscribe_blocks().await {
            Ok(mut stream) => {
                loop {
                    if SHUTDOWN_FLAG.load(Ordering::Relaxed) { break; }
                    match timeout(Duration::from_secs(2), stream.next()).await {
                        Ok(Some(_)) => {
                            if let Ok(gas) = provider.get_gas_price().await {
                                let mut state = state_arc.write().unwrap();
                                state.gas_price = gas;
                            }
                        },
                        Ok(None) => break, 
                        Err(_) => continue,
                    }
                }
            }
            Err(_) => { sleep(Duration::from_secs(2)).await; }
        };
    }
}

async fn wss_token_log_monitor(wss_url: String, token_address: Address, wallets_arc: Arc<RwLock<Vec<Address>>>) {
    loop {
        if SHUTDOWN_FLAG.load(Ordering::Relaxed) { break; }
        let provider = match Provider::<Ws>::connect(&wss_url).await {
            Ok(p) => p,
            Err(_) => { sleep(Duration::from_secs(1)).await; continue; }
        };
        let my_wallets = {
            let guard = wallets_arc.read().unwrap();
            guard.clone()
        };
        if my_wallets.is_empty() { sleep(Duration::from_secs(1)).await; continue; }
        let wallets_h256: Vec<H256> = my_wallets.iter().map(|w| H256::from(*w)).collect();
        let filter = Filter::new().address(token_address).event("Transfer(address,address,uint256)").topic2(wallets_h256);
        match provider.subscribe_logs(&filter).await {
            Ok(mut stream) => {
                loop {
                    match stream.next().await {
                        Some(log) => {
                            if log.topics.len() >= 3 {
                                let to_addr = Address::from(log.topics[2]);
                                let amount = U256::from_big_endian(&log.data);
                                let tx_hash = log.transaction_hash.unwrap_or_default();
                                let event: TransferEvent = (format!("{:?}", to_addr), format!("{:?}", token_address), amount.to_string(), format!("{:?}", tx_hash));
                                {
                                    let mut queue = EVENT_QUEUE.lock().unwrap();
                                    queue.push(event);
                                }
                            }
                        },
                        None => break, 
                    }
                }
            },
            Err(_) => { sleep(Duration::from_secs(2)).await; }
        };
    }
}

// --- Мониторинг пула ---
async fn wss_pool_event_listener(wss_url: String, pool_to_quote_map: HashMap<Address, Address>) {
    let http_provider = match get_provider_from_pool() {
        Ok(p) => Arc::new(p),
        Err(_) => return, // Не можем продолжить без провайдера
    };
    
    // --- Снапшот ---
    let mut sync_futures = Vec::new();
    for (&pool_addr, &quote_addr) in &pool_to_quote_map {
        let prov = http_provider.clone();
        sync_futures.push(async move {
            let selector = [0x70, 0xa0, 0x82, 0x31]; // balanceOf(address)
            let mut calldata = [0u8; 36];
            calldata[0..4].copy_from_slice(&selector);
            calldata[16..36].copy_from_slice(pool_addr.as_bytes());
            let tx = ethers::types::transaction::eip2718::TypedTransaction::Legacy(
                ethers::types::TransactionRequest::new().to(quote_addr).data(Bytes::from(calldata.to_vec()))
            );
            match prov.call(&tx, None).await {
                Ok(bytes) => {
                    if bytes.len() >= 32 {
                        Some((pool_addr, U256::from_big_endian(&bytes[0..32])))
                    } else { None }
                },
                Err(_) => None
            }
        });
    }

    let initial_results = join_all(sync_futures).await;
    {
        let mut balances_guard = crate::state::POOL_BALANCES.write().unwrap();
        for res in initial_results.into_iter().flatten() {
            balances_guard.insert(format!("{:?}", res.0), res.1.to_string());
        }
    }

    let mut unique_quotes = HashSet::new();
    for quote_addr in pool_to_quote_map.values() { unique_quotes.insert(*quote_addr); }

    let mut tasks = Vec::new();
    for quote_addr in unique_quotes {
        let wss_url_clone = wss_url.clone();
        let pool_map_clone = Arc::new(pool_to_quote_map.clone());

        let task = tokio::spawn(async move {
            loop {
                if SHUTDOWN_FLAG.load(Ordering::Relaxed) { break; }
                let provider = match Provider::<Ws>::connect(&wss_url_clone).await {
                    Ok(p) => p, Err(_) => { sleep(Duration::from_secs(2)).await; continue; }
                };

                let filter = Filter::new().address(quote_addr).event("Transfer(address,address,uint256)");
                if let Ok(mut stream) = provider.subscribe_logs(&filter).await {
                    while let Some(log) = stream.next().await {
                        if log.topics.len() < 3 { continue; }
                        let from = Address::from(log.topics[1]);
                        let to = Address::from(log.topics[2]);

                        let pool_to_check = if pool_map_clone.contains_key(&from) { Some(from) }
                                            else if pool_map_clone.contains_key(&to) { Some(to) }
                                            else { None };

                        if let Some(pool_addr) = pool_to_check {
                            tokio::spawn(async move {
                                if let Ok(http_provider_clone) = get_provider_from_pool() {
                                    let mut calldata = [0u8; 36];
                                    calldata[0..4].copy_from_slice(&[0x70, 0xa0, 0x82, 0x31]);
                                    calldata[16..36].copy_from_slice(pool_addr.as_bytes());
                                    let tx = ethers::types::transaction::eip2718::TypedTransaction::Legacy(
                                        ethers::types::TransactionRequest::new().to(quote_addr).data(Bytes::from(calldata.to_vec()))
                                    );
                                    if let Ok(bytes) = http_provider_clone.call(&tx, None).await {
                                        if bytes.len() >= 32 {
                                            let new_bal = U256::from_big_endian(&bytes[0..32]);
                                            let mut balances = crate::state::POOL_BALANCES.write().unwrap();
                                            balances.insert(format!("{:?}", pool_addr), new_bal.to_string());
                                        }
                                    }
                                }
                            });
                        }
                    }
                }
                sleep(Duration::from_secs(2)).await;
            }
        });
        tasks.push(task);
    }
    join_all(tasks).await;
}

// --- ЭКСПОРТ В PYTHON ---
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
    // Возвращаем самую первую ноду, так как список отсортирован по качеству
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
        if let (Ok(p_addr), Ok(q_addr)) = (Address::from_str(&pool), Address::from_str(&quote)) {
            pool_to_quote_map.insert(p_addr, q_addr);
        }
    }
    
    if pool_to_quote_map.is_empty() { return Ok(()); }

    let mut handle_guard = POOL_SCANNER_HANDLE.lock().unwrap();
    if let Some(handle) = handle_guard.take() { handle.abort(); } 

    let join_handle = RUNTIME.spawn(async move {
        wss_pool_event_listener(wss_url, pool_to_quote_map).await;
    });
    
    *handle_guard = Some(join_handle.abort_handle());
    Ok(())
}

#[pyfunction]
pub fn stop_pool_scanner(_py: Python<'_>) -> PyResult<()> {
    let mut handle_guard = POOL_SCANNER_HANDLE.lock().unwrap();
    if let Some(handle) = handle_guard.take() { handle.abort(); }
    
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
pub fn start_state_workers(_py: Python<'_>, private_rpc: String, public_rpcs: Vec<String>, initial_wallets_strs: Vec<String>, wss_url: Option<String>) -> PyResult<()> {
    // Запускаем проверку здоровья RPC
    RUNTIME.spawn(async move { rpc_health_checker(private_rpc, public_rpcs).await; });
    
    let state_arc = CORE_STATE.clone();
    let wallets_arc = TRACKED_WALLETS.clone();

    { 
        let mut tracked_wallets = wallets_arc.write().unwrap(); 
        for s in initial_wallets_strs { 
            if let Ok(addr) = Address::from_str(&s) { 
                if !tracked_wallets.contains(&addr) { tracked_wallets.push(addr); } 
            } 
        } 
    }
    
    if let Some(ws) = wss_url { 
        let state_gas = state_arc.clone(); 
        RUNTIME.spawn(async move { wss_gas_monitor(ws, state_gas).await; }); 
    } else { 
        let state_gas = state_arc.clone(); 
        RUNTIME.spawn(async move { 
            while !SHUTDOWN_FLAG.load(Ordering::Relaxed) { 
                if let Ok(provider) = get_provider_from_pool() {
                    if let Ok(price) = provider.get_gas_price().await { 
                        let mut state = state_gas.write().unwrap(); 
                        state.gas_price = price; 
                    }
                }
                sleep(Duration::from_millis(1000)).await; 
            } 
        }); 
    }
    
    let state_nonce = state_arc.clone(); 
    RUNTIME.spawn(async move { 
        while !SHUTDOWN_FLAG.load(Ordering::Relaxed) { 
            let current_wallets = { let guard = wallets_arc.read().unwrap(); guard.clone() }; 
            let mut nonce_tasks = Vec::new();
            for wallet_addr in current_wallets { 
                nonce_tasks.push(fetch_and_update_nonce(state_nonce.clone(), wallet_addr));
            }
            join_all(nonce_tasks).await;
            sleep(Duration::from_secs(3)).await; 
        } 
    });
    
    Ok(())
}

#[pyfunction]
pub fn start_token_monitor(_py: Python<'_>, wss_url: String, token_address_str: String) -> PyResult<()> { 
    let token_addr = Address::from_str(&token_address_str).map_err(|e| PyValueError::new_err(format!("Bad token: {}", e)))?; 
    let mut handle_guard = MONITOR_HANDLE.lock().unwrap(); 
    if let Some(handle) = handle_guard.take() { 
        handle.abort(); 
    } 
    let wallets_arc = TRACKED_WALLETS.clone(); 
    let join_handle = RUNTIME.spawn(async move { 
        wss_token_log_monitor(wss_url, token_addr, wallets_arc).await; 
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
    let addr = Address::from_str(&wallet_str).unwrap(); 
    { 
        let mut tracked = TRACKED_WALLETS.write().unwrap(); 
        if !tracked.contains(&addr) { tracked.push(addr); } 
    } 
    let state_arc = CORE_STATE.clone(); 
    RUNTIME.spawn(async move { fetch_and_update_nonce(state_arc, addr).await; }); 
    Ok(()) 
}


#[pyfunction]
pub fn remove_wallet_from_monitor(wallet_str: String) -> PyResult<()> { let addr = Address::from_str(&wallet_str).unwrap(); let mut tracked = TRACKED_WALLETS.write().unwrap(); tracked.retain(|&x| x != addr); let mut state = CORE_STATE.write().unwrap(); state.nonce_map.remove(&addr); Ok(()) }

#[pyfunction]
pub fn force_resync_nonce(_py: Python<'_>, wallet_str: String) -> PyResult<()> { 
    let addr = Address::from_str(&wallet_str).unwrap(); 
    let state_arc = CORE_STATE.clone(); 
    RUNTIME.spawn(async move { fetch_and_update_nonce(state_arc, addr).await; }); 
    Ok(()) 
}


#[pyfunction]
pub fn shutdown_rust_workers() -> PyResult<()> { SHUTDOWN_FLAG.store(true, Ordering::Relaxed); Ok(()) }

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