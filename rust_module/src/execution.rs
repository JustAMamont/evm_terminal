use ethers::prelude::*;
use ethers::abi::AbiEncode;
use ethers::types::transaction::eip2718::TypedTransaction;
use ethers::utils::{parse_units, format_units};
use crate::state::{RPC_POOL, GLOBAL_HTTP_CLIENT, CORE_STATE};
use crate::bridge::{EngineEvent, emit_event, emit_log};
use futures::future::join_all;
use url::Url;
use std::sync::Arc;

abigen!(
    ITaxRouter, 
    r#"[
        function swapExactTokensForTokens(uint amountIn, uint amountOutMin, address[] calldata path, address to, uint deadline) external
        function swapExactETHForTokens(uint amountOutMin, address[] calldata path, address to, uint deadline) external payable
        function swapExactTokensForETH(uint amountIn, uint amountOutMin, address[] calldata path, address to, uint deadline) external
        function swapV3Single(address tokenIn, address tokenOut, uint24 pool_fee, uint256 amountIn, uint256 amountOutMinimum, address recipient, uint256 deadline) external returns (uint256 amountOut)
    ]"#
);

abigen!(
    IQuoter, 
    r#"[{"inputs":[{"components":[{"internalType":"address","name":"tokenIn","type":"address"},{"internalType":"address","name":"tokenOut","type":"address"},{"internalType":"uint256","name":"amountIn","type":"uint256"},{"internalType":"uint24","name":"fee","type":"uint24"},{"internalType":"uint160","name":"sqrtPriceLimitX96","type":"uint160"}],"internalType":"struct IQuoterV2.QuoteExactInputSingleParams","name":"params","type":"tuple"}],"name":"quoteExactInputSingle","outputs":[{"internalType":"uint256","name":"amountOut","type":"uint256"},{"internalType":"uint160","name":"sqrtPriceX96After","type":"uint160"},{"internalType":"uint32","name":"initializedTicksCrossed","type":"uint32"},{"internalType":"uint256","name":"gasEstimate","type":"uint256"}],"stateMutability":"nonpayable","type":"function"}]"#
);

abigen!(
    IERC20,
    r#"[
        function allowance(address owner, address spender) external view returns (uint256)
        function approve(address spender, uint256 amount) external returns (bool)
        function balanceOf(address owner) external view returns (uint256)
        function symbol() external view returns (string)
        function name() external view returns (string)
        function decimals() external view returns (uint8)
    ]"#
);

pub fn u256_to_f64_safe(val: U256, decimals: u32) -> f64 {
    if val.is_zero() { return 0.0; }
    let s = format_units(val, decimals).unwrap_or_else(|_| "0.0".to_string());
    s.parse::<f64>().unwrap_or(0.0)
}

fn gas_gwei_to_wei(gas_gwei: f64) -> u64 {
    if gas_gwei <= 0.0 { return 1_000_000_000; }
    let wei = (gas_gwei * 1e9) as u64;
    wei
}

/// Текущее время в миллисекундах (Unix timestamp)
fn current_timestamp_ms() -> u64 {
    std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .unwrap()
        .as_millis() as u64
}

/// Получить баланс ERC20 токена для адреса
pub async fn get_token_balance(token: Address, wallet: Address) -> U256 {
    let url_opt = { RPC_POOL.read().unwrap().get_fastest_node() };
    if let Some(url) = url_opt {
        if let Ok(u) = Url::parse(&url) {
            let p = Arc::new(Provider::new(Http::new_with_client(u, GLOBAL_HTTP_CLIENT.clone())));
            let erc20 = IERC20::new(token, p);
            if let Ok(balance) = erc20.balance_of(wallet).call().await {
                return balance;
            }
        }
    }
    U256::zero()
}

/// Получить symbol и name токена
pub async fn get_token_info(token: Address) -> (String, String) {
    let url_opt = { RPC_POOL.read().unwrap().get_fastest_node() };
    if let Some(url) = url_opt {
        if let Ok(u) = Url::parse(&url) {
            let p = Arc::new(Provider::new(Http::new_with_client(u, GLOBAL_HTTP_CLIENT.clone())));
            let erc20 = IERC20::new(token, p);
            
            let symbol = erc20.symbol().call().await.unwrap_or_default();
            let name = erc20.name().call().await.unwrap_or_default();
            
            return (symbol, name);
        }
    }
    (String::new(), String::new())
}

pub async fn check_and_auto_approve_background(token: Address, quote: Address) {
    let (router, chain_id, wallets_keys) = {
        let s = CORE_STATE.read().unwrap();
        (s.router_address, s.chain_id, s.wallet_keys.clone())
    };
    
    let url_opt = { RPC_POOL.read().unwrap().get_fastest_node() };
    if let Some(url) = url_opt {
        if let Ok(u) = Url::parse(&url) {
            let p = Arc::new(Provider::new(Http::new_with_client(u, GLOBAL_HTTP_CLIENT.clone())));
            let tokens_to_check = vec![token, quote];

            for (w_addr, pk) in wallets_keys {
                for t_addr in &tokens_to_check {
                    if *t_addr == Address::from_low_u64_be(0xeeeeeeeeeeeeeeee) || *t_addr == Address::zero() { continue; }
                    
                    let erc20 = IERC20::new(*t_addr, p.clone());
                    if let Ok(allowance) = erc20.allowance(w_addr, router).call().await {
                        if allowance < (U256::max_value() / 2) {
                            emit_log("INFO", format!("🛡️ Фоновый Check: Апрув для {:?}...", w_addr));
                            
                            // Восстановленная логика фонового апрува
                            if let Ok(wallet) = pk.parse::<LocalWallet>() {
                                let wallet = wallet.with_chain_id(chain_id);
                                let data = erc20.approve(router, U256::max_value()).tx.data().cloned().unwrap();
                                
                                // Берем текущий газ сети
                                if let Ok(gas_price) = p.get_gas_price().await {
                                     let nonce = p.get_transaction_count(w_addr, None).await.unwrap_or(U256::zero());
                                     let tx = TransactionRequest::new()
                                        .to(*t_addr)
                                        .value(0)
                                        .nonce(nonce)
                                        .data(data)
                                        .gas(60000)
                                        .gas_price(gas_price);
                                     
                                     let typed_tx: TypedTransaction = tx.into();
                                     if let Ok(sig) = wallet.sign_transaction_sync(&typed_tx) {
                                         // Отправляем "fire and forget"
                                         let _ = p.send_raw_transaction(typed_tx.rlp_signed(&sig)).await;
                                     }
                                }
                            }
                        }
                    }
                }
            }
        }
    }
}

/// Берёт reserves из выбранного пула (selected_pool_address)
pub fn calculate_expected_out_v2_pure(token_in: Address, token_out: Address, amount_in: U256) -> U256 {
    if amount_in.is_zero() { return U256::zero(); }
    
    let s = CORE_STATE.read().unwrap();
    
    // Берём reserves конкретного выбранного пула
    let pool_addr = match s.selected_pool_address {
        Some(addr) => addr,
        None => {
            emit_log("WARNING", "calculate_expected_out_v2_pure: selected_pool_address is None".to_string());
            return U256::zero();
        }
    };
    
    let (r0, r1) = match s.v2_reserves.get(&pool_addr) {
        Some(reserves) => reserves.clone(),
        None => {
            emit_log("WARNING", format!("calculate_expected_out_v2_pure: no reserves for pool {:?}", pool_addr));
            return U256::zero();
        }
    };
    
    if r0.is_zero() || r1.is_zero() {
        emit_log("WARNING", "calculate_expected_out_v2_pure: zero reserves".to_string());
        return U256::zero();
    }
    
    // token0 < token1 по адресу, reserve0 для token0, reserve1 для token1
    let (token0, _token1) = if token_in < token_out {
        (token_in, token_out)
    } else {
        (token_out, token_in)
    };
    
    // Если token_in == token0, то r_in = reserve0, r_out = reserve1
    // Иначе r_in = reserve1, r_out = reserve0
    let (r_in, r_out) = if token_in == token0 {
        (r0, r1)
    } else {
        (r1, r0)
    };
    
    // Формула Uniswap V2: amountOut = (amountIn * 997 * reserveOut) / (reserveIn * 1000 + amountIn * 997)
    let amount_in_with_fee = U512::from(amount_in) * U512::from(9970);
    let numerator = amount_in_with_fee * U512::from(r_out);
    let denominator = (U512::from(r_in) * U512::from(10000)) + amount_in_with_fee;
    
    if !denominator.is_zero() {
        let res = (numerator / denominator).0;
        return U256([res[0], res[1], res[2], res[3]]);
    }
    
    U256::zero()
}

/// V3: вызывает quoter для получения ожидаемого выхода
pub async fn calculate_expected_out_v3_quoted(
    token_in: Address, 
    token_out: Address, 
    amount_in: U256, 
    fee: u32, 
    quoter: Address
) -> U256 {
    if amount_in.is_zero() { return U256::zero(); }
    
    let url_opt = { RPC_POOL.read().unwrap().get_fastest_node() };
    if let Some(url_str) = url_opt {
        if let Ok(url) = Url::parse(&url_str) {
            let provider = Arc::new(Provider::new(Http::new_with_client(url, GLOBAL_HTTP_CLIENT.clone())));
            let quoter_contract = IQuoter::new(quoter, provider);
            
            let params = QuoteExactInputSingleParams {
                token_in,
                token_out,
                amount_in,
                fee,
                sqrt_price_limit_x96: U256::zero(),
            };
            
            match quoter_contract.quote_exact_input_single(params).call().await {
                Ok((amount_out, _, _, _)) => {
                    emit_log("DEBUG", format!("V3 quoter result: {}", amount_out));
                    return amount_out;
                }
                Err(e) => {
                    emit_log("WARNING", format!("V3 quoter error: {:?}", e));
                }
            }
        }
    }
    U256::zero()
}

/// Вычисляет идеальный выход на основе спотовой цены (без учёта slippage/impact)
pub fn calculate_ideal_out(_token_in: Address, _token_out: Address, amount_in: U256, decimals_in: u8, is_buy: bool, decimals_out: u8) -> U256 {
    // emit_log("DEBUG", format!("ideal_out: in={:?}, out={:?}, is_buy={}", _token_in, _token_out, is_buy));
    if amount_in.is_zero() { return U256::zero(); }
    
    let s = CORE_STATE.read().unwrap();
    let price = s.selected_pool_spot_price;  // quote_per_token
    
    if price > 0.0 {
        // BUY: вводим quote → получаем token → нужен token_per_quote = 1/price
        // SELL: вводим token → получаем quote → нужен quote_per_token = price
        let actual_p = if is_buy { 1.0 / price } else { price };
        
        let amount_f = u256_to_f64_safe(amount_in, decimals_in as u32);
        let out_f = amount_f * actual_p;
        
        if out_f.is_nan() || out_f.is_infinite() || out_f <= 0.0 {
            return U256::zero();
        }
        
        // Конвертируем обратно в wei (используем decimals_out, но можно approx)
        match ethers::utils::parse_units(out_f, decimals_out as u32) {
            Ok(v) => v.into(),
            Err(_) => U256::zero()
        }
    } else {
        U256::zero()
    }
}

/// Выполняет batch trade для списка кошельков
pub async fn run_batch_trade(
    keys: Vec<String>, 
    router: Address, 
    action: String, 
    token: Address, 
    quote: Address, 
    amount: f64, 
    gas: f64, 
    slippage: f64, 
    _v3_f: u32, 
    chain_id: u64,
    amounts_wei: Option<std::collections::HashMap<String, String>>
) -> Vec<EngineEvent> {
    let mut events = Vec::new();
    let (p_type, p_fee) = { 
        let s = CORE_STATE.read().unwrap(); 
        (s.selected_pool_type.clone().unwrap_or_default(), s.selected_pool_fee) 
    };
    
    if p_type.is_empty() { 
        return vec![EngineEvent::TradeStatus { 
            wallet: "SYSTEM".into(), 
            action, 
            status: "Error".into(), 
            message: "No pool selected!".into(), 
            tx_hash: None,
            token_address: format!("{:?}", token),
            amount,
            tokens_received: None,
            tokens_sold: None,
            token_decimals: 18
        }]; 
    }
    
    let url_opt = { RPC_POOL.read().unwrap().get_fastest_node() };
    
    for pk in keys {
        let wallet: LocalWallet = match pk.parse::<LocalWallet>() { 
            Ok(w) => w.with_chain_id(chain_id), 
            Err(_) => continue 
        };
        
        let wallet_addr = wallet.address();
        let (t_in, t_out) = if action == "buy" { (quote, token) } else { (token, quote) };
        let dec = { *CORE_STATE.read().unwrap().decimals_cache.get(&t_in).unwrap_or(&18) };
        
        // Безопасный парсинг суммы с учетом точной продажи 100%
        let mut amount_wei: U256 = match parse_units(amount, dec as u32) {
            Ok(v) => v.into(),
            Err(_) => U256::zero()
        };
        
        if action == "sell" {
            let mut exact_wei_from_python = None;
            if let Some(ref amounts) = amounts_wei {
                let wallet_str = format!("{:?}", wallet_addr).to_lowercase();
                if let Some(wei_str) = amounts.get(&wallet_str) {
                    if let Ok(w) = U256::from_dec_str(wei_str) {
                        exact_wei_from_python = Some(w);
                    }
                }
            }
            
            if let Some(w) = exact_wei_from_python {
                amount_wei = w;
            } else {
                amount_wei = U256::zero();
            }
        }
        
        if amount_wei.is_zero() {
            events.push(EngineEvent::TradeStatus {
                wallet: format!("{:?}", wallet_addr),
                action: action.clone(),
                status: "Error".into(),
                message: if action == "sell" { "Zero balance to sell".into() } else { "Invalid amount".into() },
                tx_hash: None,
                token_address: format!("{:?}", token),
                amount,
                tokens_received: None,
                tokens_sold: None,
                token_decimals: dec
            });
            continue;
        }
        
        let nonce = { *CORE_STATE.read().unwrap().nonce_map.get(&wallet_addr).unwrap_or(&0) };
        let deadline = U256::from(
            std::time::SystemTime::now()
                .duration_since(std::time::UNIX_EPOCH)
                .unwrap()
                .as_secs() + 300
        );
        
        // ================= АВТОМАТИЧЕСКАЯ ПРОВЕРКА ALLOWANCE ПРИ ПРОДАЖЕ =================
        if action == "sell" {
            let mut allowance = U256::zero();
            // Получаем провайдера для проверки allowance
            if let Some(url) = &url_opt {
                if let Ok(u) = Url::parse(url) {
                    let p = Arc::new(Provider::new(Http::new_with_client(u, GLOBAL_HTTP_CLIENT.clone())));
                    let erc20 = IERC20::new(t_in, p); // t_in is Token address on Sell
                    if let Ok(a) = erc20.allowance(wallet_addr, router).call().await {
                        allowance = a;
                    }
                }
            }
            
            if allowance < amount_wei {
                emit_log("WARNING", format!("🛡️ Auto-Approve required for {:?} (allowance: {})", wallet_addr, allowance));
                
                // Construct Approve Transaction INSTEAD of Swap
                let erc20_dummy = IERC20::new(t_in, Arc::new(Provider::new(Http::new(Url::parse("http://localhost").unwrap()))));
                let data = erc20_dummy.approve(router, U256::max_value()).tx.data().cloned().unwrap();
                
                let tx = TransactionRequest::new()
                    .to(t_in)
                    .value(0)
                    .nonce(nonce)
                    .data(data)
                    .gas(100000)
                    .gas_price(gas_gwei_to_wei(gas));
                    
                let typed_tx: TypedTransaction = tx.into();
                
                if let Ok(sig) = wallet.sign_transaction_sync(&typed_tx) {
                    let raw_tx = typed_tx.rlp_signed(&sig);
                    let hash = parallel_broadcast(raw_tx.clone()).await;
                    
                    emit_event(EngineEvent::TxSent {
                        tx_hash: hash.clone(),
                        wallet: format!("{:?}", wallet_addr),
                        action: "approve".into(),
                        amount: 0.0,
                        token: format!("{:?}", token),
                        timestamp_ms: current_timestamp_ms()
                    });
                    
                    events.push(EngineEvent::TradeStatus {
                        wallet: format!("{:?}", wallet_addr),
                        action: "approve".into(),
                        status: "Sent".into(),
                        message: "Auto-Approve sent. Please retry SELL after confirmation.".into(),
                        tx_hash: Some(hash),
                        token_address: format!("{:?}", t_in),
                        amount: 0.0,
                        tokens_received: None,
                        tokens_sold: None,
                        token_decimals: dec
                    });
                }
                continue; // Пропуск свапа для кошелька, ожидаем апрув
            }
        }
        // ===================================================================================
        
        // Извлекаем quoter ПЕРЕД await
        let exp_out = if p_type == "V3" {
            let quoter = CORE_STATE.read().unwrap().quoter_address;
            calculate_expected_out_v3_quoted(t_in, t_out, amount_wei, p_fee, quoter).await
        } else {
            calculate_expected_out_v2_pure(t_in, t_out, amount_wei)
        };
        
        // Безопасное вычисление min_out
        let slippage_factor = (10000.0 - slippage * 100.0).max(0.0).min(10000.0) as u64;
        let min_out = (exp_out * U256::from(slippage_factor)) / U256::from(10000);

        let calldata = if p_type == "V3" {
            SwapV3SingleCall { 
                token_in: t_in, 
                token_out: t_out, 
                pool_fee: p_fee, 
                amount_in: amount_wei, 
                amount_out_minimum: min_out, 
                recipient: wallet_addr, 
                deadline 
            }.encode()
        } else {
            SwapExactTokensForTokensCall { 
                amount_in: amount_wei, 
                amount_out_min: min_out, 
                path: vec![t_in, t_out], 
                to: wallet_addr, 
                deadline 
            }.encode()
        };

        let tx = TransactionRequest::new()
            .to(router)
            .value(0)
            .nonce(nonce)
            .data(calldata)
            .gas(500000)
            .gas_price(gas_gwei_to_wei(gas));
            
        let typed_tx: TypedTransaction = tx.into();
        
        if let Ok(sig) = wallet.sign_transaction_sync(&typed_tx) {
            let raw_tx = typed_tx.rlp_signed(&sig);
            let hash = parallel_broadcast(raw_tx.clone()).await;
            
            let is_success = hash.starts_with("0x");
            
            if is_success {
                let tx_hash_h256: H256 = hash.parse().unwrap_or(H256::zero());
                CORE_STATE.write().unwrap().pending_txs.insert(tx_hash_h256);
                
                emit_event(EngineEvent::TxSent {
                    tx_hash: hash.clone(),
                    wallet: format!("{:?}", wallet_addr),
                    action: action.clone(),
                    amount,
                    token: format!("{:?}", token),
                    timestamp_ms: current_timestamp_ms()
                });
            }
            
            let (tok_received, tok_sold) = if action == "buy" {
                (Some(exp_out.to_string()), None)
            } else {
                (None, Some(amount_wei.to_string()))
            };

            events.push(EngineEvent::TradeStatus { 
                wallet: format!("{:?}", wallet_addr), 
                action: action.clone(), 
                status: if is_success { "Sent".into() } else { "Error".into() }, 
                message: hash.clone(), 
                tx_hash: if is_success { Some(hash.clone()) } else { None },
                token_address: format!("{:?}", token),
                amount,
                tokens_received: tok_received,
                tokens_sold: tok_sold,
                token_decimals: dec
            });
        }
    }
    events
}

/// Параллельная отправка транзакции на несколько RPC
async fn parallel_broadcast(data: Bytes) -> String {
    let urls = { RPC_POOL.read().unwrap().get_fastest_pool(3) };
    let mut tasks = Vec::new();
    
    for url in urls {
        let d = data.clone();
        tasks.push(tokio::spawn(async move {
            let p = Provider::new(Http::new_with_client(
                Url::parse(&url).unwrap(), 
                GLOBAL_HTTP_CLIENT.clone()
            ));
            p.send_raw_transaction(d)
                .await
                .map(|r| format!("{:?}", r.tx_hash()))
                .map_err(|e| e.to_string())
        }));
    }
    
    for res in join_all(tasks).await { 
        if let Ok(Ok(h)) = res { 
            return h; 
        } 
    }
    "Error: all RPCs failed".into()
}

/// Auto-fuel: свапает токен на нативную валюту когда баланс ниже порога
pub async fn run_auto_fuel(
    pk: String, 
    wallet: Address, 
    router: Address, 
    quote: Address, 
    amount: U256, 
    chain_id: u64
) -> bool {
    use ethers::abi::{Token, encode};
    
    if amount.is_zero() { return false; }
    
    let wallet_signer: LocalWallet = pk.parse::<LocalWallet>().unwrap().with_chain_id(chain_id);
    let (w_n, gas_p) = { 
        let s = CORE_STATE.read().unwrap(); 
        (s.wrapped_native_address, s.gas_price)
    };
    
    // === WBNB → прямой withdraw ===
    if quote == w_n {
        emit_log("INFO", format!("⛽ Auto-Fuel: withdraw {} WBNB → BNB", amount));
        
        let withdraw_sig = ethers::utils::keccak256("withdraw(uint256)".as_bytes());
        let mut calldata: Vec<u8> = withdraw_sig[..4].to_vec();
        calldata.extend_from_slice(&encode(&[Token::Uint(amount)]));
        
        let nonce = { 
            let s = CORE_STATE.read().unwrap(); 
            *s.nonce_map.get(&wallet).unwrap_or(&0) 
        };
        
        let tx = TransactionRequest::new()
            .to(w_n)
            .nonce(nonce)
            .data(calldata)
            .gas(100000)
            .gas_price(gas_p);
            
        let typed_tx: TypedTransaction = tx.into();
        
        if let Ok(sig) = wallet_signer.sign_transaction_sync(&typed_tx) { 
            let raw_tx = typed_tx.rlp_signed(&sig);
            let hash = parallel_broadcast(raw_tx).await;
            emit_log("INFO", format!("⛽ Auto-Fuel withdraw tx: {}", hash));
            
            if hash.starts_with("0x") {
                let tx_hash: H256 = hash.parse().unwrap_or(H256::zero());
                CORE_STATE.write().unwrap().pending_txs.insert(tx_hash);
                CORE_STATE.write().unwrap().nonce_map.insert(wallet, nonce + 1);
                return true;
            }
        }
        return false;
    }
    
    // === Swap через TaxRouter ===
    emit_log("INFO", format!("⛽ Auto-Fuel: swap {:?} → BNB via TaxRouter", quote));
    
    let url_opt = { RPC_POOL.read().unwrap().get_fastest_node() };
    if let Some(url) = url_opt {
        if let Ok(u) = Url::parse(&url) {
            let p = Arc::new(Provider::new(Http::new_with_client(u, GLOBAL_HTTP_CLIENT.clone())));
            let erc20 = IERC20::new(quote, p.clone());
            
            // Проверяем баланс токена
            if let Ok(balance) = erc20.balance_of(wallet).call().await {
                if balance < amount {
                    let reason = format!("Недостаточно токена: есть {:.6}, нужно {:.6}", 
                        u256_to_f64_safe(balance, 18), u256_to_f64_safe(amount, 18));
                    emit_log("ERROR", format!("⛽ Auto-Fuel: {}", reason));
                    emit_event(EngineEvent::AutoFuelError {
                        wallet: format!("{:?}", wallet),
                        reason,
                    });
                    return false;
                }
            }
            
            // Проверяем и делаем approve если нужно
            if let Ok(allowance) = erc20.allowance(wallet, router).call().await {
                if allowance < amount {
                    emit_log("INFO", "⛽ Auto-Fuel: требуется approve...".to_string());
                    
                    let nonce = { 
                        let s = CORE_STATE.read().unwrap(); 
                        *s.nonce_map.get(&wallet).unwrap_or(&0) 
                    };
                    
                    let approve_data = erc20.approve(router, U256::max_value()).tx.data().cloned().unwrap();
                    
                    let tx = TransactionRequest::new()
                        .to(quote)
                        .nonce(nonce)
                        .data(approve_data)
                        .gas(60000)
                        .gas_price(gas_p);
                    
                    let typed_tx: TypedTransaction = tx.into();
                    
                    if let Ok(sig) = wallet_signer.sign_transaction_sync(&typed_tx) {
                        let raw_tx = typed_tx.rlp_signed(&sig);
                        let hash = parallel_broadcast(raw_tx).await;
                        emit_log("INFO", format!("⛽ Auto-Fuel approve tx: {}", hash));
                        
                        if hash.starts_with("0x") {
                            CORE_STATE.write().unwrap().nonce_map.insert(wallet, nonce + 1);
                            tokio::time::sleep(tokio::time::Duration::from_secs(3)).await;
                        } else {
                            let reason = "Approve failed: все RPC недоступны".to_string();
                            emit_event(EngineEvent::AutoFuelError {
                                wallet: format!("{:?}", wallet),
                                reason: reason.clone(),
                            });
                            return false;
                        }
                    }
                }
            }
            
            // Делаем swap
            let nonce = { 
                let s = CORE_STATE.read().unwrap(); 
                *s.nonce_map.get(&wallet).unwrap_or(&0) 
            };
            
            let deadline = U256::from(
                std::time::SystemTime::now()
                    .duration_since(std::time::UNIX_EPOCH)
                    .unwrap()
                    .as_secs() + 300
            );
            
            let func_sig = ethers::utils::keccak256("swapExactTokensForETH(uint256,uint256,address[],address,uint256)".as_bytes());
            let mut calldata: Vec<u8> = func_sig[..4].to_vec();
            
            let tokens = vec![
                Token::Uint(amount),
                Token::Uint(U256::zero()),
                Token::Array(vec![Token::Address(quote), Token::Address(w_n)]),
                Token::Address(wallet),
                Token::Uint(deadline),
            ];
            calldata.extend_from_slice(&encode(&tokens));
            
            let tx = TransactionRequest::new()
                .to(router)
                .nonce(nonce)
                .data(calldata)
                .gas(300000)
                .gas_price(gas_p);
                
            let typed_tx: TypedTransaction = tx.into();
            
            if let Ok(sig) = wallet_signer.sign_transaction_sync(&typed_tx) { 
                let raw_tx = typed_tx.rlp_signed(&sig);
                let hash = parallel_broadcast(raw_tx).await;
                
                if hash.starts_with("0x") {
                    emit_log("SUCCESS", format!("⛽ Auto-Fuel swap tx: {}", hash));
                    
                    let tx_hash: H256 = hash.parse().unwrap_or(H256::zero());
                    CORE_STATE.write().unwrap().pending_txs.insert(tx_hash);
                    CORE_STATE.write().unwrap().nonce_map.insert(wallet, nonce + 1);
                    
                    emit_event(EngineEvent::TxSent {
                        tx_hash: hash,
                        wallet: format!("{:?}", wallet),
                        action: "auto_fuel".into(),
                        amount: u256_to_f64_safe(amount, 18),
                        token: format!("{:?}", quote),
                        timestamp_ms: current_timestamp_ms()
                    });
                    
                    return true;
                } else {
                    let reason = "Swap failed: все RPC недоступны".to_string();
                    emit_event(EngineEvent::AutoFuelError {
                        wallet: format!("{:?}", wallet),
                        reason,
                    });
                }
            }
        }
    }
    
    false
}