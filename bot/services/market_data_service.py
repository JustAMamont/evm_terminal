import asyncio
import ccxt.pro as ccxtpro
from web3 import AsyncWeb3
from bot.core.abis import ERC20_ABI, PANCAKESWAP_V2_ROUTER_ABI, V2_FACTORY_ABI, V3_FACTORY_ABI
from bot.core.config import Config
from bot.cache import GlobalCache
from utils.aiologger import log
from typing import Optional, Any, Dict

try:
    import dexbot_core
    RUST_AVAILABLE = True
except ImportError:
    dexbot_core = None
    RUST_AVAILABLE = False

class MarketDataService:
    def __init__(self, cache: GlobalCache, config: Config):
        self.cache = cache
        self.config = config
        self.workers = []
        self._is_running = False
        self.exchange: Optional[ccxtpro.binance] = None 
        self._current_monitored_token: Optional[str] = None
        self.bot_service: Any = None 
        
        self._pool_discovery_tasks: Dict[str, asyncio.Task] = {}
        
        # Кэш метаданных пулов (Address -> Info)
        self._pool_metadata_cache: Dict[str, Dict[str, Any]] = {}

    async def _get_rpc_w3(self) -> AsyncWeb3:
        # NOTE: Этот метод теперь используется в основном как фолбэк или для разовых задач (warmup)
        config_from_cache = self.cache.get_config()
        rpc_url = config_from_cache.get('rpc_url', self.config.RPC_URL)
        if RUST_AVAILABLE:
            try:
                # Пытаемся получить самый быстрый URL, если он есть
                best_url = dexbot_core.get_best_rpc_url() # type: ignore
                if best_url:
                    rpc_url = best_url
            except Exception:
                pass
        return AsyncWeb3(AsyncWeb3.AsyncHTTPProvider(rpc_url))

    async def _get_token_decimals_from_rpc(self, token_address: str) -> Optional[int]:
        try:
            w3 = await self._get_rpc_w3()
            token_cs = w3.to_checksum_address(token_address)
            cached = self.cache.get_token_decimals(token_cs)
            if cached is not None: return cached
            
            token_contract = w3.eth.contract(address=token_cs, abi=ERC20_ABI)
            decimals = await token_contract.functions.decimals().call()
            self.cache.set_token_decimals(token_cs, decimals)
            return decimals
        except Exception:
            return None 

    async def find_and_cache_best_pool(self, token_address: str, quote_symbol: Optional[str] = None, **kwargs): # type: ignore
        """
        Ищет пулы, проверяет их балансы (snapshot) и запускает Rust-мониторинг.
        """
        if RUST_AVAILABLE:
            try: dexbot_core.clear_pool_balances() # type: ignore
            except: pass

        w3 = await self._get_rpc_w3()
        v2_factory_contract = w3.eth.contract(address=w3.to_checksum_address(self.config.V2_FACTORY_ADDRESS), abi=V2_FACTORY_ABI)
        v3_factory_contract = w3.eth.contract(address=w3.to_checksum_address(self.config.V3_FACTORY_ADDRESS), abi=V3_FACTORY_ABI)

        token_cs = w3.to_checksum_address(token_address)
        self._pool_metadata_cache.clear()

        if not quote_symbol:
            cfg = self.cache.get_config()
            quote_symbol = cfg.get('default_quote_currency', self.config.DEFAULT_QUOTE_CURRENCY)

        tasks = []
        task_metadata = []
        v3_fees = [100, 500, 2500, 10000]

        for q_symbol, q_addr in self.config.QUOTE_TOKENS.items():
            q_cs = w3.to_checksum_address(q_addr)
            
            tasks.append(v2_factory_contract.functions.getPair(token_cs, q_cs).call())
            task_metadata.append({'type': 'V2', 'symbol': q_symbol, 'quote_addr': q_addr, 'quote_cs': q_cs})
            
            for fee in v3_fees:
                tasks.append(v3_factory_contract.functions.getPool(token_cs, q_cs, fee).call())
                task_metadata.append({'type': 'V3', 'symbol': q_symbol, 'quote_addr': q_addr, 'quote_cs': q_cs, 'fee': fee})

        results = await asyncio.gather(*tasks, return_exceptions=True)

        valid_pools = []
        balance_tasks = []
        
        for i, pool_addr in enumerate(results):
            if isinstance(pool_addr, Exception) or not pool_addr or pool_addr == "0x0000000000000000000000000000000000000000":
                continue
            
            meta = task_metadata[i]
            meta['address'] = pool_addr
            valid_pools.append(meta)
            
            quote_contract = w3.eth.contract(address=meta['quote_cs'], abi=ERC20_ABI)
            balance_tasks.append(quote_contract.functions.balanceOf(pool_addr).call())

        if not valid_pools:
            target_q_addr = self.config.QUOTE_TOKENS.get(quote_symbol, "").lower()
            self.cache.set_best_pool(token_address, target_q_addr, {"error": "No pools found"})
            return

        balances = await asyncio.gather(*balance_tasks, return_exceptions=True)

        best_pool_per_currency = {}
        all_pools_addresses_for_rust = {}

        for i, meta in enumerate(valid_pools):
            balance = balances[i]
            if isinstance(balance, Exception): balance = 0
            
            pool_addr = meta['address']
            pool_addr_low = pool_addr.lower()
            all_pools_addresses_for_rust[pool_addr] = meta['quote_addr'].lower()
            
            pool_info = {
                'type': meta['type'], 
                'symbol': meta['symbol'], 
                'address': pool_addr, 
                'fee': meta.get('fee', 2500),
                'balance': balance 
            }
            self._pool_metadata_cache[pool_addr_low] = pool_info

            sym = meta['symbol']
            if sym not in best_pool_per_currency or balance > best_pool_per_currency[sym]['balance']:
                best_pool_per_currency[sym] = pool_info

        if quote_symbol in best_pool_per_currency:
            winner = best_pool_per_currency[quote_symbol]
            target_q_addr = self.config.QUOTE_TOKENS.get(quote_symbol).lower()
            self.cache.set_best_pool(token_address, target_q_addr, winner)
        else:
            target_q_addr = self.config.QUOTE_TOKENS.get(quote_symbol, "").lower()
            self.cache.set_best_pool(token_address, target_q_addr, {"error": "Pool empty"})

        if all_pools_addresses_for_rust and RUST_AVAILABLE:
            await asyncio.to_thread(
                dexbot_core.start_pool_scanner,  # type: ignore
                self.config.WSS_URL, 
                all_pools_addresses_for_rust
            )

    async def _rust_pool_sync_worker(self):
        current_best_liquidity = 0.0

        while self._is_running:
            try:
                if RUST_AVAILABLE:
                    best_pool_data = await asyncio.to_thread(dexbot_core.get_best_pool_address) # type: ignore
                    
                    if best_pool_data:
                        addr, liq_wei = best_pool_data
                        addr_lower = addr.lower()
                        
                        if addr_lower in self._pool_metadata_cache:
                            info = self._pool_metadata_cache[addr_lower].copy()
                            
                            active_token = self.cache.get_active_trade_token()
                            if active_token:
                                config = self.cache.get_config()
                                quote_symbol = config.get('default_quote_currency', self.config.DEFAULT_QUOTE_CURRENCY)
                                quote_address = self.config.QUOTE_TOKENS.get(quote_symbol, "").lower()
                                
                                decimals = self.cache.get_token_decimals(quote_address) or 18
                                new_liquidity_float = float(liq_wei) / (10**decimals)

                                current_pool = self.cache.get_best_pool(active_token, quote_address)
                                current_pool_addr = current_pool.get('address', '').lower() if current_pool else ""
                                
                                should_switch = False
                                if not current_pool or "error" in current_pool:
                                    should_switch = True
                                elif current_pool_addr != addr_lower:
                                    if new_liquidity_float > (current_best_liquidity * 1.05):
                                        should_switch = True
                                
                                if should_switch:
                                    current_best_liquidity = new_liquidity_float
                                    await log.success(f"💎 Rust: Смена лидера -> {info['type']} {info.get('fee_tier', '')} | Liq: {new_liquidity_float:.2f}")
                                    self.cache.set_best_pool(active_token, quote_address, info)
                                else:
                                    if current_pool_addr == addr_lower:
                                        current_best_liquidity = new_liquidity_float

                await asyncio.sleep(0.5)
            except asyncio.CancelledError: break
            except Exception: await asyncio.sleep(1)

    async def _rust_event_listener_worker(self):
        if not RUST_AVAILABLE: return
        await log.info("Rust Event Listener: запуск...")
        while self._is_running:
            try:
                events = await asyncio.to_thread(dexbot_core.get_pending_events) # type: ignore
                if events:
                    for (wallet_addr, token_addr, amount_wei_str, tx_hash) in events:
                        try:
                            amount_wei = int(amount_wei_str)
                            self.cache.set_exact_balance_wei(wallet_addr, token_addr, amount_wei)
                            decimals = self.cache.get_token_decimals(token_addr) or 18
                            balance_float = amount_wei / (10**decimals)
                            self.cache.set_wallet_balance(wallet_addr, token_addr, balance_float)
                            await log.success(f"⚡ RUST WSS: {wallet_addr[:6]} rcvd {balance_float:.4f}. Tx: {tx_hash[:10]}...")
                            await self.cache.db.save_cached_balance(wallet_addr, token_addr, amount_wei, decimals)
                        except Exception as e: await log.error(f"Error processing Rust event: {e}")
                await asyncio.sleep(0.05)
            except Exception: await asyncio.sleep(1)

    async def switch_token_monitor(self, token_address: str):
        if not RUST_AVAILABLE or not self.config.WSS_URL: return
        if self._current_monitored_token == token_address.lower(): return
        self._current_monitored_token = token_address.lower()
        try:
            await asyncio.to_thread(dexbot_core.start_token_monitor, self.config.WSS_URL, token_address) # type: ignore
            await log.info(f"🔄 WSS Monitor switched to: {token_address}")
        except Exception as e: await log.error(f"Failed to switch WSS monitor: {e}")

    async def stop_token_monitor(self):
        if RUST_AVAILABLE:
            self._current_monitored_token = None
            await asyncio.to_thread(dexbot_core.stop_token_monitor) # type: ignore
            await asyncio.to_thread(dexbot_core.stop_pool_scanner) # type: ignore

    async def _balances_worker(self):
        """
        Воркер, который теперь распределяет запросы на балансы
        по пулу самых быстрых RPC нод.
        """
        await log.info("Balances Worker (Load Balanced): запуск...")

        # --- Одноразовый Warmup (прогрев кэша) при старте ---
        try:
            wallets_for_warmup = self.cache.get_all_wallets(enabled_only=True)
            if wallets_for_warmup:
                # Для warmup используем только одну, самую быструю ноду, чтобы не нагружать систему на старте
                w3 = await self._get_rpc_w3()
                warmup_tasks = []
                tracked_tokens = self.cache.get_all_tracked_token_addresses()
                for wallet in wallets_for_warmup:
                    wallet_address = w3.to_checksum_address(wallet['address'])
                    warmup_tasks.append(self._fetch_native_balance(w3, wallet_address))
                    for t_addr in tracked_tokens:
                        token_cs = w3.to_checksum_address(t_addr)
                        warmup_tasks.append(self._fetch_erc20_balance(w3, wallet_address, token_cs))
                if warmup_tasks:
                    await asyncio.gather(*warmup_tasks)
                    await log.info(f"⚡ Balances Warmup Complete.")
        except Exception as e:
            await log.error(f"Balances Warmup failed: {e}")
        # --- Конец Warmup ---

        while self._is_running:
            try:
                wallets = self.cache.get_all_wallets(enabled_only=True)
                if not wallets:
                    await asyncio.sleep(2)
                    continue

                # 1. Получаем ПУЛ быстрых RPC из Rust-ядра
                providers = []
                if RUST_AVAILABLE:
                    try:
                        # Запрашиваем до 5 самых быстрых и здоровых нод
                        healthy_urls = dexbot_core.get_healthy_rpc_urls(5) # type: ignore
                        if healthy_urls:
                            providers = [AsyncWeb3(AsyncWeb3.AsyncHTTPProvider(url)) for url in healthy_urls]
                    except Exception:
                        pass
                
                # Если Rust-балансировщик недоступен, работаем по старой схеме с одной нодой (фолбэк)
                if not providers:
                    providers = [await self._get_rpc_w3()]

                config_from_cache = self.cache.get_config()
                quote_symbol = config_from_cache.get('default_quote_currency', self.config.DEFAULT_QUOTE_CURRENCY)
                quote_address = self.config.QUOTE_TOKENS.get(quote_symbol)
                
                tasks = []
                # 2. Распределяем задачи по пулу провайдеров (Round-robin)
                for i, wallet in enumerate(wallets):
                    # Циклически выбираем провайдер из пула
                    w3 = providers[i % len(providers)]
                    
                    wallet_address = w3.to_checksum_address(wallet['address'])
                    
                    # Задачи на проверку нативного баланса и авто-заправки
                    tasks.append(self._fetch_native_balance(w3, wallet_address))
                    if RUST_AVAILABLE and self.bot_service:
                        native_bal = self.cache.get_wallet_balances(wallet_address).get(self.config.NATIVE_CURRENCY_ADDRESS.lower(), 0.0)
                        asyncio.create_task(self.bot_service.check_and_execute_autofuel(wallet_address, native_bal))
                    
                    # Задачи на проверку баланса QUOTE токена
                    if quote_address and quote_address.lower() != self.config.NATIVE_CURRENCY_ADDRESS.lower():
                        token_cs = w3.to_checksum_address(quote_address)
                        tasks.append(self._fetch_erc20_balance(w3, wallet_address, token_cs))
                    
                    # Задачи на проверку баланса активного ТОРГУЕМОГО токена
                    active_token = self.cache.get_active_trade_token()
                    if active_token and active_token.lower() != (quote_address or "").lower() and active_token.lower() != self.config.NATIVE_CURRENCY_ADDRESS.lower():
                         token_cs = w3.to_checksum_address(active_token)
                         tasks.append(self._fetch_erc20_balance(w3, wallet_address, token_cs))

                if tasks:
                    await asyncio.gather(*tasks)
                
                await asyncio.sleep(2) # Пауза между циклами опроса

            except asyncio.CancelledError: 
                break
            except Exception as e:
                await log.error(f"Критическая ошибка в воркере балансов: {e}", exc_info=True)
                await asyncio.sleep(5)

    async def _fetch_native_balance(self, w3: AsyncWeb3, wallet_address: str):
        try:
            native_balance_wei = await w3.eth.get_balance(wallet_address) # type: ignore
            native_balance = w3.from_wei(native_balance_wei, 'ether')
            self.cache.set_wallet_balance(wallet_address, self.config.NATIVE_CURRENCY_ADDRESS, float(native_balance))
            self.cache.set_exact_balance_wei(wallet_address, self.config.NATIVE_CURRENCY_ADDRESS, native_balance_wei)
        except Exception: 
            # Не обнуляем баланс при ошибке сети, оставляем старое значение
            pass

    async def _fetch_token_decimals(self, w3: AsyncWeb3, token_cs: str) -> int:
        try:
            # Проверяем кэш, чтобы не делать лишних запросов
            cached = self.cache.get_token_decimals(token_cs)
            if cached is not None:
                return cached
            
            token_contract = w3.eth.contract(address=token_cs, abi=ERC20_ABI) # type: ignore
            decimals = await token_contract.functions.decimals().call()
            self.cache.set_token_decimals(token_cs, decimals)
            return decimals 
        except Exception:
            self.cache.set_token_decimals(token_cs, 18) # Фолбэк на 18, если RPC-вызов не удался
            return 18

    async def _fetch_erc20_balance(self, w3: AsyncWeb3, wallet_address: str, token_cs: str):
        try:
            decimals = await self._fetch_token_decimals(w3, token_cs)
            token_contract = w3.eth.contract(address=token_cs, abi=ERC20_ABI) # type: ignore
            
            balance_wei = await token_contract.functions.balanceOf(wallet_address).call()
            
            # ЗАЩИТА ОТ "ЗАЛАГАВШЕГО" RPC
            # Если RPC вернул 0, а в кэше есть баланс (полученный от WSS/TxWatcher мгновение назад),
            # мы игнорируем этот 0, считая его отставанием ноды.
            current_cached_wei = self.cache.get_exact_balance_wei(wallet_address, token_cs)
            if balance_wei == 0 and current_cached_wei is not None and current_cached_wei > 0:
                return # Пропускаем обновление, верим более быстрым источникам

            self.cache.set_exact_balance_wei(wallet_address, token_cs, balance_wei)
            balance = balance_wei / (10**decimals)
            self.cache.set_wallet_balance(wallet_address, token_cs, balance)
        except Exception: 
            # Не обнуляем баланс при ошибке сети, оставляем старый
            pass

    async def _quotes_price_worker(self):
        """
        Получает икэширует стоимость квотируемых токенов 
        с бинанса по вебсокетам в USD для расчета TVL, PnL и лимитов
        (не стейблов, для них предполагается цена в 1$, 
        т.к разница в курсах незначительна)
        """
        await log.info(f"Quotes Price Worker: запуск...")
        self.exchange = ccxtpro.binance()
        symbols = self.config.ERC20_QUOTES_TICKERS

        first_i = True
        while self._is_running:
            try:
                if first_i:
                    tickers = await self.exchange.fetch_tickers(symbols)
                    first_i = False
                else:
                    tickers = await self.exchange.watch_tickers(symbols)

                for sym, data in tickers.items():
                    base = sym.split("/")[0]
                    self.cache.set_quote_price(base, float(data['last']))
            except asyncio.CancelledError: 
                break 
            except Exception: 
                await log.error("Ошибка получения цены цены", exc_info=True)
                await asyncio.sleep(2)
                

    async def _expected_amount_out_worker(self):
        await log.info("Expected Amount Worker: запуск...")
        while self._is_running:
            try:
                token_addr = self.cache.get_active_trade_token()
                amount_in = self.cache.get_active_trade_amount_for_quote()
                if not token_addr or not amount_in or amount_in <= 0:
                    await asyncio.sleep(1); continue
                
                w3 = await self._get_rpc_w3()
                router_rpc_contract = w3.eth.contract(
                    address=w3.to_checksum_address(self.config.DEX_ROUTER_ADDRESS),
                    abi=PANCAKESWAP_V2_ROUTER_ABI
                )
                config = self.cache.get_config()
                quote_symbol = config.get('default_quote_currency', self.config.DEFAULT_QUOTE_CURRENCY)
                token_in_cs = None
                if quote_symbol == self.config.NATIVE_CURRENCY_SYMBOL:
                    token_in_cs = w3.to_checksum_address(self.config.NATIVE_CURRENCY_ADDRESS)
                elif quote_symbol in self.config.QUOTE_TOKENS:
                    token_in_cs = w3.to_checksum_address(self.config.QUOTE_TOKENS[quote_symbol])
                else: await asyncio.sleep(1); continue

                token_out_cs = w3.to_checksum_address(token_addr)
                path = [token_in_cs, token_out_cs]
                if path[0] == w3.to_checksum_address(self.config.NATIVE_CURRENCY_ADDRESS):
                     path[0] = w3.to_checksum_address(self.config.QUOTE_TOKENS[f"W{self.config.NATIVE_CURRENCY_SYMBOL}"])

                amount_wei: int
                if token_in_cs == w3.to_checksum_address(self.config.NATIVE_CURRENCY_ADDRESS):
                    amount_wei = w3.to_wei(amount_in, 'ether')
                else:
                    decimals = await self._get_token_decimals_from_rpc(token_in_cs)
                    if decimals is None: 
                        await asyncio.sleep(1); 
                        continue
                    amount_wei = int(amount_in * (10**decimals))

                amounts_out = await router_rpc_contract.functions.getAmountsOut(amount_wei, path).call()
                self.cache.set_expected_amount_out(token_in_cs, token_out_cs, amount_in, amounts_out[-1])
                await asyncio.sleep(0.5) 

            except asyncio.CancelledError: 
                break
            except Exception: 
                await asyncio.sleep(2)

    def start(self):
        if self._is_running: return
        self._is_running = True
        self.workers.append(asyncio.create_task(self._quotes_price_worker()))
        self.workers.append(asyncio.create_task(self._balances_worker()))
        self.workers.append(asyncio.create_task(self._expected_amount_out_worker()))
        self.workers.append(asyncio.create_task(self._rust_event_listener_worker()))
        self.workers.append(asyncio.create_task(self._rust_pool_sync_worker()))
        asyncio.create_task(log.info("MarketDataService: все воркеры запущены."))

    async def stop(self):
        if not self._is_running: return
        await log.info("MarketDataService: остановка...")
        self._is_running = False
        for worker in self.workers: 
            worker.cancel()
        if self.exchange: 
            await self.exchange.close()