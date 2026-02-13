import asyncio
import time
import json
from typing import List, Dict, Any, Optional, Set

from bot.inner_api.schemas import TradeRequest, TradeAction
from bot.services.account_manager import AccountManager
from bot.core.config import Config, TRANSFER_EVENT_TOPIC
from bot.core.abis import ERC20_ABI, PANCAKESWAP_V2_ROUTER_ABI
from utils.aiologger import log
from bot.cache import GlobalCache
from web3 import AsyncWeb3

try:
    import dexbot_core
    RUST_AVAILABLE = True
except ImportError:
    dexbot_core = None
    RUST_AVAILABLE = False
    print("КРИТИЧЕСКОЕ ПРЕДУПРЕЖДЕНИЕ: Rust-модуль 'dexbot_core' не найден. Торговля не будет функционировать.")

# TODO: класс перегружен. В идеале нужно разнести MarketData и Execution в разные микросервисы, 
# но для MVP я оставил это в одном сервисе для упрощения коммуникации
class BotService:
    def __init__(self, cache: GlobalCache, notification_queue: Optional[asyncio.Queue], config: Config):
        self.cache = cache
        self.config = config
        self.swap_queue: asyncio.Queue[Dict[str, Any]] = asyncio.Queue()
        self.tx_watcher_queue: asyncio.Queue[Dict[str, Any]] = asyncio.Queue()
        self.workers: List[asyncio.Task] = []
        self._is_running = False
        self.notification_queue = notification_queue
        
        self.post_buy_tasks: Set[asyncio.Task] = set()
        self.active_buy_txs: Set[bytes] = set()
        self._sell_task: Optional[asyncio.Task] = None
        
        self._active_pnl_trackers: Set[str] = set()
        
        self._refuel_cooldowns: Dict[str, float] = {}
        self._gas_warn_cooldowns: Dict[str, float] = {}
        
        self._approve_check_cooldowns: Dict[str, float] = {}

    async def _get_rpc_w3(self) -> AsyncWeb3:
        # Приоритетно используем балансировщик Rust для получения лучшего RPC
        rpc_url = None
        if RUST_AVAILABLE:
            try:
                # Получаем самый быстрый URL из нашего Rust-балансировщика
                rpc_url = dexbot_core.get_best_rpc_url() # type: ignore
            except Exception:
                pass  # В случае ошибки просто перейдем к фолбэку

        if not rpc_url:
            # Фолбэк на URL из конфига, если Rust недоступен или вернул None
            config_from_cache = self.cache.get_config()
            rpc_url = config_from_cache.get('rpc_url', self.config.RPC_URL)

        return AsyncWeb3(AsyncWeb3.AsyncHTTPProvider(rpc_url))

    async def fetch_and_store_token_metadata(self, token_address: str):
        try:
            metadata = await self.cache.db.get_token_metadata(token_address)
            if metadata and metadata.get('name') and metadata.get('symbol'):
                return

            w3 = await self._get_rpc_w3()
            token_cs = w3.to_checksum_address(token_address)
            token_contract = w3.eth.contract(address=token_cs, abi=ERC20_ABI)

            results = await asyncio.gather(
                token_contract.functions.name().call(),
                token_contract.functions.symbol().call(),
                return_exceptions=True
            )
            
            name = results[0] if not isinstance(results[0], Exception) else "N/A"
            symbol = results[1] if not isinstance(results[1], Exception) else "N/A"

            await self.cache.db.add_or_update_recent_token(token_address, name=name, symbol=symbol) # type: ignore

        except Exception:
            await self.cache.db.add_or_update_recent_token(token_address, name="Unknown", symbol="???")

    async def check_and_execute_autofuel(self, wallet_address: str, current_native_balance: float):
        config = self.cache.get_config()
        threshold = float(config.get('auto_fuel_threshold', 0.005))
        now = time.time()

        if current_native_balance < threshold:
            if not config.get('auto_fuel_enabled', False):
                last_warn = self._gas_warn_cooldowns.get(wallet_address, 0)
                if now - last_warn > 600:
                    msg = f"Мало газа на {wallet_address[:6]}... ({current_native_balance:.4f} < {threshold}). Auto-Fuel выключен."
                    await log.warning(f"<yellow>[LOW GAS]</yellow> {msg}")
                    if self.notification_queue:
                        await self.notification_queue.put({"status": "warning", "message": msg, "wallet": wallet_address})
                    self._gas_warn_cooldowns[wallet_address] = now
                return

            last_attempt = self._refuel_cooldowns.get(wallet_address, 0)
            if now - last_attempt < 300: 
                return

            target_bnb_amount = float(config.get('auto_fuel_amount', 0.02))
            quote_symbol = config.get('default_quote_currency', self.config.DEFAULT_QUOTE_CURRENCY)
            if quote_symbol == self.config.NATIVE_CURRENCY_SYMBOL: return 
                
            quote_address = self.config.QUOTE_TOKENS.get(quote_symbol)
            if not quote_address: return

            balances = self.cache.get_wallet_balances(wallet_address)
            quote_balance_float = balances.get(quote_address.lower(), 0.0)
            
            if quote_balance_float <= 0:
                last_warn = self._gas_warn_cooldowns.get(wallet_address, 0)
                if now - last_warn > 600:
                    msg = f"Невозможно купить газ: нет {quote_symbol} на балансе."
                    await log.error(f"<red>[AUTO-FUEL ERROR]</red> {msg}")
                    if self.notification_queue:
                        await self.notification_queue.put({"status": "warning", "message": msg, "wallet": wallet_address})
                    self._gas_warn_cooldowns[wallet_address] = now
                return

            await log.info(f"<magenta>[AUTO-FUEL]</magenta> ⛽ Initiating for {wallet_address[:6]}... Target: {target_bnb_amount} {self.config.NATIVE_CURRENCY_SYMBOL}")
            self._refuel_cooldowns[wallet_address] = now 

            try:
                w3 = await self._get_rpc_w3()
                quote_cs = w3.to_checksum_address(quote_address)
                weth_address = w3.to_checksum_address(self.config.QUOTE_TOKENS[f"W{self.config.NATIVE_CURRENCY_SYMBOL}"])
                
                if quote_cs == weth_address:
                    if quote_balance_float < target_bnb_amount:
                        await log.error(f"<red>[AUTO-FUEL]</red> Недостаточно WBNB для Unwrap.")
                        return

                    wallet_data = self.cache.get_wallet_by_address(wallet_address)
                    if not wallet_data: return
                    
                    amount_wei = w3.to_wei(target_bnb_amount, 'ether')
                    wbnb_contract = w3.eth.contract(address=weth_address, abi=ERC20_ABI)
                    
                    nonce = await w3.eth.get_transaction_count(wallet_address) # type: ignore
                    gas_price = await w3.eth.gas_price
                    
                    tx = await wbnb_contract.functions.withdraw(amount_wei).build_transaction({
                        'from': wallet_address, 'nonce': nonce, 'gasPrice': gas_price, 'gas': 60000 
                    })
                    
                    private_key = wallet_data['private_key']
                    try: signed_tx = w3.eth.account.sign_transaction(tx, private_key)
                    except Exception:
                        clean_pk = private_key
                        if not clean_pk.startswith("0x") and len(clean_pk) == 64: clean_pk = "0x" + clean_pk
                        signed_tx = w3.eth.account.sign_transaction(tx, clean_pk)

                    tx_hash = await w3.eth.send_raw_transaction(signed_tx.raw_transaction)
                    await log.success(f"<magenta>[AUTO-FUEL]</magenta> ✅ Unwrap Sent: {tx_hash.hex()}")
                    return

                v2_router_address = self.config.V2_ROUTER_ADDRESS 
                if not v2_router_address: return

                v2_router = w3.eth.contract(address=w3.to_checksum_address(v2_router_address), abi=PANCAKESWAP_V2_ROUTER_ABI)
                target_amount_out_wei = w3.to_wei(target_bnb_amount, 'ether')
                path = [quote_cs, weth_address]
                
                try:
                    amounts_in = await v2_router.functions.getAmountsIn(target_amount_out_wei, path).call()
                    raw_amount_in_wei = amounts_in[0]
                except Exception as e:
                    await log.error(f"<magenta>[AUTO-FUEL]</magenta> Price Calc Error: {e}")
                    return
                
                amount_in_wei_adjusted = int(raw_amount_in_wei * 1.011) 
                quote_decimals = self.cache.get_token_decimals(quote_address) or 18
                amount_in_float = amount_in_wei_adjusted / (10**quote_decimals)

                if amount_in_float > quote_balance_float: return

                wallet_data = self.cache.get_wallet_by_address(wallet_address)
                if not wallet_data: return
                gas_wei = int(float(config.get('default_gas_price_gwei', self.config.DEFAULT_GAS_PRICE_GWEI)) * 10**9)

                command = {
                    "type": "batch", "action": "buy", "private_keys": [wallet_data['private_key']], "wallet_addresses": [wallet_address],
                    "amount_in": amount_in_float, "slippage": 5.0, "max_fee_cents": 100, "gas_limit": 500000,
                    "token_for_history": self.config.NATIVE_CURRENCY_ADDRESS, "gas_price_wei": gas_wei,
                    "token_in": quote_address, "method_type": "TokensForETH",
                    "path": [quote_address.lower(), weth_address.lower()]
                }
                await self.swap_queue.put(command)
                if self.notification_queue:
                    await self.notification_queue.put({"status": "autofuel_success", "message": f"{target_bnb_amount} BNB (Swap via TaxRouter)", "wallet": wallet_address})

            except Exception as e:
                await log.error(f"<red>[AUTO-FUEL]</red> Critical Error: {e}", exc_info=True)

    async def _pnl_management_worker(self):
        if not RUST_AVAILABLE: return
        while self._is_running:
            try:
                rpc_url = self.cache.get_config().get('rpc_url', self.config.RPC_URL)
                v2_router = self.config.V2_ROUTER_ADDRESS
                v3_quoter = self.config.V3_QUOTER_ADDRESS
                if not v2_router or not v3_quoter:
                    await asyncio.sleep(10); 
                    continue

                config = self.cache.get_config()
                quote_symbol = config.get('default_quote_currency', self.config.DEFAULT_QUOTE_CURRENCY)
                quote_address = self.config.QUOTE_TOKENS.get(quote_symbol, "").lower()
                cached_balances = await self.cache.db.get_all_cached_balances()
                
                for row in cached_balances:
                    w_addr = row['wallet_address']
                    t_addr = row['token_address']
                    balance_wei = int(row['balance_wei'])
                    
                    if balance_wei <= 0: continue
                    if t_addr.lower() == quote_address or t_addr.lower() == self.config.NATIVE_CURRENCY_ADDRESS.lower(): continue
                    pnl_key = f"{w_addr}:{t_addr}"
                    if pnl_key in self._active_pnl_trackers: continue
                    
                    pos = await self.cache.db.get_position(w_addr, t_addr)
                    total_cost = pos['total_cost']
                    if total_cost > 0:
                        pool_info = self.cache.get_best_pool(t_addr, quote_address)
                        if pool_info and "error" not in pool_info:
                            pool_type = pool_info['type']
                            v3_fee = pool_info.get('fee', 0)
                            await asyncio.to_thread(
                                dexbot_core.start_pnl_tracker, # type: ignore
                                rpc_url, w_addr, t_addr, quote_address,
                                str(balance_wei), str(total_cost),
                                pool_type, v3_fee, v2_router, v3_quoter
                            )
                            self._active_pnl_trackers.add(pnl_key)
            except asyncio.CancelledError: break
            except Exception as e: await log.error(f"Ошибка в PnL Manager: {e}")
            await asyncio.sleep(5) 

    async def _post_buy_actions(self, wallet_address: str, token_address: str, amount_received_wei: Optional[int]):
        async with self.cache.get_wallet_lock(wallet_address):
            try:
                w3 = await self._get_rpc_w3()
                
                cached_wei = self.cache.get_exact_balance_wei(wallet_address, token_address)
                if not (cached_wei and cached_wei > 0):
                    token_cs_addr = w3.to_checksum_address(token_address)
                    token_contract = w3.eth.contract(address=token_cs_addr, abi=ERC20_ABI)
                    wallet_cs = w3.to_checksum_address(wallet_address)
                    for _ in range(10): 
                        try:
                            bal = await token_contract.functions.balanceOf(wallet_cs).call()
                            if bal > 0:
                                self.cache.set_exact_balance_wei(wallet_address, token_address, bal)
                                break
                        except: pass
                        await asyncio.sleep(0.3)

                wallet_data = self.cache.get_wallet_by_address(wallet_address)
                if not wallet_data: return
                
                manager = AccountManager(
                    private_key=wallet_data['private_key'], 
                    cache=self.cache, 
                    config=self.config,
                    w3=w3
                )

                allowance = await manager.get_allowance(token_address)
                if isinstance(allowance, int) and allowance < (2**255): 
                    await log.warning(f"[{wallet_address[:6]}] Need Approve for future sale! Sending tx...")
                    config = self.cache.get_config()
                    gwei = float(config.get('default_gas_price_gwei', self.config.DEFAULT_GAS_PRICE_GWEI))
                    gas_price_wei = int(gwei * 10**9)

                    tx_hash_bytes = await manager.execute_approve(
                        token_address=token_address,
                        gas_limit=self.config.APPROVE_GAS_LIMIT, 
                        gas_price_wei=gas_price_wei
                    )
                    
                    if tx_hash_bytes != b'\x00' * 32:
                        await self.tx_watcher_queue.put({
                            "tx_hash": tx_hash_bytes, 
                            "wallet_address": wallet_address, 
                            "action": "approve_sell_post_buy", 
                            "token": token_address
                        })
            
            except Exception as e:
                await log.error(f"[{wallet_address[:6]}] Post-buy error: {e}", exc_info=True)


    async def _tx_watcher_worker(self):
        await log.info("TxWatcher started.")
        while self._is_running:
            tx_data = None
            try:
                tx_data = await self.tx_watcher_queue.get()
                tx_hash_bytes, wallet_address = tx_data['tx_hash'], tx_data['wallet_address']
                trade_action, token_address = tx_data.get('action'), tx_data.get('token')
                
                w3 = await self._get_rpc_w3()
                receipt = await w3.eth.wait_for_transaction_receipt(tx_hash_bytes, timeout=300)
                
                if receipt.status == 1 and trade_action == 'buy' and token_address: # type: ignore
                    try:
                        my_addr_lower = wallet_address.lower()
                        total_received = 0
                        for log_entry in receipt['logs']:
                            if log_entry['address'].lower() != token_address.lower(): continue
                            if len(log_entry['topics']) > 0 and log_entry['topics'][0].hex() == TRANSFER_EVENT_TOPIC.replace("0x", ""):
                                if len(log_entry['topics']) >= 3:
                                    to_topic = "0x" + log_entry['topics'][2].hex()[-40:]
                                    if to_topic.lower() == my_addr_lower:
                                        amount = int(log_entry['data'].hex(), 16)
                                        total_received += amount
                        
                        if total_received > 0:
                            self.cache.set_exact_balance_wei(wallet_address, token_address, total_received)
                            await log.success(f"[{wallet_address[:6]}] 🚀 INSTANT BALANCE (Logs): {total_received}")
                    except Exception as e:
                        await log.error(f"Error parsing instant balance: {e}")

                if trade_action == 'buy' and tx_hash_bytes in self.active_buy_txs:
                    self.active_buy_txs.discard(tx_hash_bytes)

                action_str = "Покупка" if 'buy' in (trade_action or '') else "Продажа"
                if trade_action == 'approve_sell_post_buy' or trade_action == 'approve_on_demand': action_str = "Approve"
                if trade_action == 'approve_quote_token': action_str = "Approve USDT/BNB"

                if receipt.status == 1:  # type: ignore
                    await log.success(f"TxWatcher: Транзакция {tx_hash_bytes.hex()} УСПЕШНА.")
                    if self.notification_queue and trade_action and ('buy' in trade_action or 'sell' in trade_action):
                        await self.notification_queue.put({"status": "success", "wallet": wallet_address, "action": action_str})

                    if token_address and (trade_action == 'buy' or trade_action == 'sell'):
                        asyncio.create_task(self.cache.db.add_or_update_recent_token(token_address))
                        asyncio.create_task(self.fetch_and_store_token_metadata(token_address))

                    if trade_action == 'sell' and token_address:
                        await self.cache.db.delete_cached_balance(wallet_address, token_address)
                        self.cache.set_exact_balance_wei(wallet_address, token_address, 0)
                        self.cache.set_wallet_balance(wallet_address, token_address, 0.0)
                        await log.info(f"[{wallet_address}] Кэш баланса очищен после продажи.")
                        
                        await self.cache.db.close_position(wallet_address, token_address)
                        if RUST_AVAILABLE:
                            await asyncio.to_thread(dexbot_core.stop_pnl_tracker, wallet_address, token_address) # type: ignore
                        pnl_key = f"{wallet_address.lower()}:{token_address.lower()}"
                        self._active_pnl_trackers.discard(pnl_key)

                    if trade_action == 'buy' and token_address:
                        try:
                            spent_amount_float = self.cache.get_active_trade_amount_for_quote()
                            if spent_amount_float:
                                cost_wei = int(spent_amount_float * 10**18) 
                                await self.cache.db.update_position(wallet_address, token_address, cost_wei, 0)
                        except Exception as e:
                            await log.error(f"Ошибка обновления PnL позиции: {e}")

                        post_buy_task = asyncio.create_task(
                            self._post_buy_actions(wallet_address, token_address, None)
                        )
                        self.post_buy_tasks.add(post_buy_task)
                        post_buy_task.add_done_callback(self.post_buy_tasks.discard)
                else:
                    await log.error(f"TxWatcher: Транзакция {tx_hash_bytes.hex()} ПРОВАЛЕНА (reverted).")
                    if self.notification_queue and trade_action and ('buy' in trade_action or 'sell' in trade_action or 'approve' in trade_action):
                        await self.notification_queue.put({"status": "error", "message": f"{action_str} провалена (reverted)", "wallet": wallet_address, "action": action_str})
                
                self.tx_watcher_queue.task_done()

            except asyncio.CancelledError: break
            except (asyncio.TimeoutError, Exception) as e:
                hex_hash = tx_data.get('tx_hash', b'').hex() if tx_data else '?'
                await log.critical(f"Критическая ошибка в TxWatcher для {hex_hash}: {e}", exc_info=False)
                if tx_data: self.tx_watcher_queue.task_done()

    async def _worker(self, worker_id: int):
        await log.info(f"SwapWorker-{worker_id} (Dynamic Batch) запущен.")
        chain_id = self.config.CHAIN_ID
        router_address = self.config.DEX_ROUTER_ADDRESS

        while self._is_running:
            command = None
            try:
                command = await self.swap_queue.get()
                max_retries = 3
                attempt = 0
                
                while attempt < max_retries:
                    attempt += 1
                    try:
                        if command.get("type") == "batch":
                            is_buy_with_native = False
                            if command['action'] == 'buy':
                                native_addr = self.config.NATIVE_CURRENCY_ADDRESS.lower()
                                is_buy_with_native = (command.get('token_in', '').lower() == native_addr)

                            is_sell_action = command['action'] == 'sell'
                            final_private_keys, final_amounts_in, final_amounts_min, final_wallets_log = [], [], [], []
                            token_in_addr_for_decimals = command['path'][0]
                            decimals = self.cache.get_token_decimals(token_in_addr_for_decimals) or 18
                            
                            for idx, wallet_addr in enumerate(command['wallet_addresses']):
                                pk = command['private_keys'][idx]
                                current_amount_in_wei = 0
                                if is_sell_action:
                                    token_in_for_sell = command['path'][0]
                                    exact_bal = self.cache.get_exact_balance_wei(wallet_addr, token_in_for_sell)
                                    if exact_bal and exact_bal > 0: current_amount_in_wei = exact_bal
                                    else: continue
                                else: 
                                    if is_buy_with_native: current_amount_in_wei = int(command['amount_in'] * 10**18)
                                    else: current_amount_in_wei = int(command['amount_in'] * (10**decimals))
                                
                                if current_amount_in_wei <= 0: continue
                                
                                amount_out_min_str = "0"
                                if not is_sell_action:
                                    expected_out = self.cache.get_expected_amount_out(command['path'][0], command['path'][1], command['amount_in'], 5)
                                    if expected_out:
                                        min_wei = int(expected_out * (1 - command['slippage'] / 100.0))
                                        amount_out_min_str = str(min_wei)
                                
                                final_private_keys.append(pk)
                                final_amounts_in.append(str(current_amount_in_wei))
                                final_amounts_min.append(amount_out_min_str)
                                final_wallets_log.append(wallet_addr)
                            
                            if not final_private_keys:
                                await log.warning(f"Batch пропущен: суммы для трейда 0.")
                                break 
                                
                            value_wei_str = final_amounts_in[0] if is_buy_with_native else "0"
                            gas_price_wei = command.get('gas_price_wei', 0)
                            v3_pool_fee_val = command.get('v3_pool_fee', 0)

                            results = await asyncio.to_thread(
                                dexbot_core.execute_batch_swap, # type: ignore
                                final_private_keys, router_address, chain_id, 
                                command['method_type'], final_amounts_in, final_amounts_min, 
                                command['path'], int(time.time()) + 300, command['gas_limit'], 
                                value_wei_str, gas_price_wei, v3_pool_fee_val 
                            )

                            retryable_error_found = False
                            fatal_error_found = False
                            
                            for i, res in enumerate(results):
                                w_addr = final_wallets_log[i]
                                if "Error" in res:
                                    res_lower = res.lower()
                                    if "insufficient funds" in res_lower or "gas limit" in res_lower:
                                        fatal_error_found = True
                                        err_msg = "Недостаточно BNB для газа" if "insufficient funds" in res_lower else "Ошибка Gas Limit"
                                        await log.error(f"[{w_addr[:6]}] 🛑 FATAL: {err_msg}. Отмена.")
                                        if self.notification_queue:
                                            await self.notification_queue.put({"status": "error", "message": err_msg, "wallet": w_addr, "action": command.get('action', 'Сделка')})
                                    
                                    elif "nonce" in res_lower or "reverted" in res_lower or "replacement transaction underpriced" in res_lower:
                                        retryable_error_found = True
                                        await log.warning(f"[{w_addr[:6]}] Network Error (Attempt {attempt}): {res}")
                                        if ("nonce" in res_lower or "underpriced" in res_lower) and RUST_AVAILABLE:
                                            await asyncio.to_thread(dexbot_core.force_resync_nonce, w_addr) # type: ignore
                                    else:
                                        fatal_error_found = True
                                        await log.error(f"[{w_addr[:6]}] 🛑 Unknown Error: {res}")
                                        if self.notification_queue:
                                            await self.notification_queue.put({"status": "error", "message": res, "wallet": w_addr, "action": command.get('action', 'Сделка')})
                                else: 
                                    tx_clean = res.replace('"', '').replace("'", "")
                                    await log.success(f"[{w_addr[:6]}] 🔥 BATCH ({command['method_type']}, Gas {gas_price_wei/1e9} Gwei): {tx_clean}")
                                    try:
                                        tx_bytes = bytes.fromhex(tx_clean.replace("0x", ""))
                                        if command.get('action') == 'buy':
                                            self.active_buy_txs.add(tx_bytes)
                                        await self.tx_watcher_queue.put({
                                            "tx_hash": tx_bytes, "wallet_address": w_addr,
                                            "action": command.get('action'), "token": command.get('token_for_history'),
                                            "expected_amount_out_wei": None
                                        })
                                    except: pass
                            
                            if fatal_error_found: break 
                            if retryable_error_found:
                                if attempt < max_retries:
                                    await log.warning(f"⚠️ Ретрай через 0.3с (попытка {attempt+1}/{max_retries})...")
                                    await asyncio.sleep(0.3)
                                    continue
                                else:
                                    await log.error("❌ Попытки ретрая исчерпаны.")
                                    if self.notification_queue:
                                        await self.notification_queue.put({"status": "error", "message": "Сбой сети (Nonce/Revert)", "wallet": "Multiple", "action": command.get('action', 'Сделка')})
                            break 
                    except Exception as e:
                        await log.error(f"Critical Worker Exception: {e}")
                        if self.notification_queue:
                            await self.notification_queue.put({"status": "error", "message": f"Ошибка подготовки: {str(e)}", "wallet": "N/A", "action": command.get('action', 'Сделка')})
                        break
                
                self.swap_queue.task_done()
            except asyncio.CancelledError: break
            except Exception as e:
                await log.error(f"Worker Loop Error: {e}")
                if command: self.swap_queue.task_done()

    def start(self):
        if self._is_running: return
        self._is_running = True
        num_workers = self.cache.get_config().get('max_workers', 1)
        for i in range(num_workers):
            self.workers.append(asyncio.create_task(self._worker(i + 1)))
        self.workers.append(asyncio.create_task(self._tx_watcher_worker()))
        self.workers.append(asyncio.create_task(self._pnl_management_worker()))

    def stop(self):
        if not self._is_running: return
        self._is_running = False
        for worker in self.workers: worker.cancel()
        
    async def prefetch_token_decimals(self, token_address: str):
        w3 = await self._get_rpc_w3()
        try:
            token_cs = w3.to_checksum_address(token_address)
            if self.cache.get_token_decimals(token_cs) is not None: return
            token_contract = w3.eth.contract(address=token_cs, abi=ERC20_ABI)
            decimals = await token_contract.functions.decimals().call()
            self.cache.set_token_decimals(token_cs, decimals)
        except Exception: pass

    async def schedule_quote_token_approvals(self, wallets: Optional[List[str]] = None, gas_price_gwei: Optional[float] = None):
        target_wallets = wallets or [w['address'] for w in self.cache.get_all_wallets(enabled_only=True)]
        if not target_wallets: return

        now = time.time()
        wallets_to_check = []
        for address in target_wallets:
            last_check_time = self._approve_check_cooldowns.get(address, 0)
            if now - last_check_time > 60:
                wallets_to_check.append(address)
                self._approve_check_cooldowns[address] = now
        
        if not wallets_to_check:
            return

        gas_wei = 0
        if gas_price_gwei: gas_wei = int(gas_price_gwei * 10**9)
        else:
            config = self.cache.get_config()
            gwei = float(config.get('default_gas_price_gwei', self.config.DEFAULT_GAS_PRICE_GWEI))
            gas_wei = int(gwei * 10**9)

        async def _check_and_approve(wallet_address: str):
            async with self.cache.get_wallet_lock(wallet_address):
                try:
                    w3 = await self._get_rpc_w3()
                    config_from_cache = self.cache.get_config()
                    quote_symbol = config_from_cache.get('default_quote_currency', self.config.DEFAULT_QUOTE_CURRENCY)
                    if quote_symbol == self.config.NATIVE_CURRENCY_SYMBOL: return
                    
                    quote_address = self.config.QUOTE_TOKENS.get(quote_symbol)
                    if not quote_address: return

                    wallet_data = self.cache.get_wallet_by_address(wallet_address)
                    if not wallet_data or not wallet_data.get('private_key'): return

                    manager = AccountManager(private_key=wallet_data['private_key'], cache=self.cache, config=self.config, w3=w3)
                    allowance = await manager.get_allowance(quote_address)
                    if allowance > (2**255): 
                        return
                    
                    await log.warning(f"[{wallet_address[:6]}] Требуется Approve для {quote_symbol}. Отправка...")
                    tx_hash_bytes = await manager.execute_approve(quote_address, gas_price_wei=gas_wei)
                    
                    if tx_hash_bytes != b'\x00' * 32:
                        await self.tx_watcher_queue.put({"tx_hash": tx_hash_bytes, "wallet_address": wallet_address, "action": "approve_quote_token", "token": quote_address})
                    else:
                        await log.error(f"[{wallet_address[:6]}] Не удалось отправить транзакцию Approve (Rust вернул ошибку).")

                except Exception as e: 
                    await log.error(f"Ошибка в фоновой задаче Approve для {wallet_address}: {e}")

        tasks = [_check_and_approve(address) for address in wallets_to_check]
        await asyncio.gather(*tasks)

    async def _wait_and_execute_sell(self, trade_request: TradeRequest, best_pool: Dict[str, Any]):
        try:
            await log.info(f"⚡ HFT SELL Triggered. Checking balances...")

            token_in = trade_request.token_address
            balance_found = False
            
            start_time = time.time()
            while time.time() - start_time < 20:
                for w in trade_request.wallets:
                    bal = self.cache.get_exact_balance_wei(w, token_in)
                    if bal and bal > 0:
                        balance_found = True
                        break
                
                if balance_found:
                    break
                
                await asyncio.sleep(0.005) 

            if not balance_found:
                 await log.warning(f"⚠️ HFT Timeout: Баланс 0. Отправляем продажу на удачу...")
            else:
                 await log.success("✅ Баланс обнаружен. Мгновенная продажа.")

            config_from_cache = self.cache.get_config()
            private_keys, wallet_addresses = [], []
            for wallet_address in trade_request.wallets:
                wallet_data = self.cache.get_wallet_by_address(wallet_address)
                if wallet_data and 'private_key' in wallet_data:
                    private_keys.append(wallet_data['private_key'])
                    wallet_addresses.append(wallet_address)

            gas_wei = int((trade_request.gas_price_gwei or config_from_cache.get('default_gas_price_gwei', self.config.DEFAULT_GAS_PRICE_GWEI)) * 10**9)

            command = {
                "type": "batch", "action": "sell", "private_keys": private_keys, "wallet_addresses": wallet_addresses,
                "amount_in": trade_request.amount,
                "slippage": trade_request.slippage or config_from_cache.get('slippage', 15.0),
                "max_fee_cents": trade_request.max_fee_cents,
                "gas_limit": config_from_cache.get('gas_limit', 350000),
                "token_for_history": trade_request.token_address,
                "gas_price_wei": gas_wei
            }

            pool_type = best_pool['type']
            
            native_symbol = self.config.NATIVE_CURRENCY_SYMBOL
            quote_symbol = trade_request.quote_token
            
            if quote_symbol == native_symbol:
                token_out_address = self.config.QUOTE_TOKENS[f"W{native_symbol}"]
            else:
                token_out_address = self.config.QUOTE_TOKENS[quote_symbol]
            
            if pool_type == 'V3':
                command['method_type'] = "V3Swap"
                command['path'] = [trade_request.token_address, token_out_address]
                command['v3_pool_fee'] = best_pool['fee'] 
            else: 
                command['method_type'] = "TokensForTokens"
                command['path'] = [trade_request.token_address.lower(), token_out_address.lower()]
            
            await self.swap_queue.put(command)

        except asyncio.CancelledError:
            await log.warning("Ожидание продажи отменено.")
        except Exception as e:
            await log.error(f"Ошибка при отложенной продаже: {e}")
        finally:
            self._sell_task = None

    async def schedule_trades(self, trade_request: TradeRequest) -> Dict[str, Any]:
        if trade_request.action == TradeAction.BUY and self._sell_task and not self._sell_task.done():
            self._sell_task.cancel()
            await log.info("🛑 Предыдущая задача продажи отменена из-за новой покупки.")

        config_from_cache = self.cache.get_config()
        quote_token_symbol = trade_request.quote_token
        token_address = trade_request.token_address
        native_symbol = self.config.NATIVE_CURRENCY_SYMBOL

        if quote_token_symbol == native_symbol:
            search_quote_addr = self.config.QUOTE_TOKENS.get(f"W{native_symbol}", "")
        else:
            search_quote_addr = self.config.QUOTE_TOKENS.get(quote_token_symbol, "")

        if not search_quote_addr:
             return {"status": "error", "message": f"Адрес для {quote_token_symbol} не найден в конфиге."}

        best_pool = self.cache.get_best_pool(token_address, search_quote_addr)
        if not best_pool or "error" in best_pool:
            return {"status": "error", "message": f"Пул для {quote_token_symbol} не найден! Проверьте ликвидность."}

        pool_address = best_pool['address']
        pool_type = best_pool['type']

        if trade_request.action == TradeAction.BUY and RUST_AVAILABLE:
            try:
                all_balances = await asyncio.to_thread(dexbot_core.get_all_pool_balances) # type: ignore
                pool_liq_wei = 0.0
                target_key = pool_address.lower()
                
                for k, v in all_balances.items():
                    clean_key = k.replace('"', '').replace("'", "").lower()
                    if clean_key == target_key:
                        pool_liq_wei = float(v)
                        break
                
                if pool_liq_wei > 0:
                    quote_decimals = self.cache.get_token_decimals(search_quote_addr) or 18
                    trade_amount_wei = float(trade_request.amount) * (10**quote_decimals)
                    pool_share_percent = (trade_amount_wei / pool_liq_wei) * 100.0
                    MAX_SAFE_SHARE = 15.0 
                    
                    liq_readable = pool_liq_wei / (10**quote_decimals)
                    liq_usd = liq_readable * self.cache.get_quote_price(quote_token_symbol)

                    if pool_share_percent > MAX_SAFE_SHARE:
                        err_msg = (
                            f"🛑 ОПАСНО! Низкая ликвидность в {quote_token_symbol}!\n"
                            f"   Пул: {pool_address} (${liq_usd:,.0f})\n"
                            f"   Ваша сделка: {pool_share_percent:.1f}% от пула (Лимит 15%).\n"
                            f"   Сделка отменена."
                        )
                        await log.error(f"[{trade_request.wallets[0][:6]}] {err_msg}")
                        return {"status": "error", "message": err_msg}
                    
                    await log.info(
                        f"✅ Pool Selected: {pool_address} ({pool_type})\n"
                        f"   Liquidity: ${liq_usd:,.0f} ({liq_readable:.2f} {quote_token_symbol})\n"
                        f"   Impact Risk: {pool_share_percent:.2f}% (Safe)"
                    )
                else:
                    await log.warning(f"⚠️ Rust не знает баланс пула {pool_address}. Проверка пропущена (Риск!).")

            except Exception as e:
                await log.error(f"Ошибка проверки ликвидности: {e}")
        
        token_addr_clean = trade_request.token_address
        quote_addr_clean = ""
        
        if quote_token_symbol == native_symbol:
            quote_addr_clean = self.config.QUOTE_TOKENS.get(f"W{native_symbol}")
        else:
            quote_addr_clean = self.config.QUOTE_TOKENS.get(quote_token_symbol)

        if trade_request.action == TradeAction.BUY:
            token_in = quote_addr_clean
            token_out = token_addr_clean
        else: 
            token_in = token_addr_clean
            token_out = quote_addr_clean

        if trade_request.action == TradeAction.SELL:
            if self._sell_task and not self._sell_task.done():
                return {"status": "success", "message": "Продажа уже в очереди ожидания..."}
            
            self._sell_task = asyncio.create_task(self._wait_and_execute_sell(trade_request, best_pool))
            return {"status": "success", "message": f"Продажа поставлена в очередь (Пул: {pool_type})"}

        private_keys, wallet_addresses = [], []
        for wallet_address in trade_request.wallets:
            wallet_data = self.cache.get_wallet_by_address(wallet_address)
            if wallet_data and 'private_key' in wallet_data:
                private_keys.append(wallet_data['private_key'])
                wallet_addresses.append(wallet_address)
        
        if not private_keys: 
            return {"status": "error", "message": "Нет доступных ключей."}

        gas_wei = int((trade_request.gas_price_gwei or config_from_cache.get('default_gas_price_gwei', self.config.DEFAULT_GAS_PRICE_GWEI)) * 10**9)

        command = {
            "type": "batch", 
            "action": trade_request.action.value, 
            "private_keys": private_keys, 
            "wallet_addresses": wallet_addresses,
            "amount_in": trade_request.amount,
            "slippage": trade_request.slippage or config_from_cache.get('slippage', 15.0),
            "max_fee_cents": trade_request.max_fee_cents,
            "gas_limit": config_from_cache.get('gas_limit', 350000),
            "token_for_history": token_address,
            "gas_price_wei": gas_wei,
            "token_in": token_in 
        }

        if pool_type == 'V3':
            command['method_type'] = "V3Swap"
            command['path'] = [token_in, token_out]
            command['v3_pool_fee'] = best_pool.get('fee', 2500)
        else:
            command['method_type'] = "TokensForTokens"
            command['path'] = [token_in.lower(), token_out.lower()]

        await self.swap_queue.put(command)
        return {"status": "success", "message": f"🚀 Пакет ({pool_type}) на {len(private_keys)} кошельков отправлен!"}