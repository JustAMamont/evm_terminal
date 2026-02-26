"""
BotService - координация между TUI и Rust ядром.

Python отвечает за:
- БД (сохранение метаданных, позиций)
- Восстановление PnL трекеров при старте
- Подготовка команд для Rust

Вся бизнес-логика (транзакции, approve, autofuel) - в Rust!
"""
import asyncio
from typing import List, Dict, Any, Optional, Set

from bot.core.config import Config
from bot.core.abis import ERC20_ABI
from bot.core.bridge import BridgeManager, EngineCommand
from utils.aiologger import log
from bot.cache import GlobalCache
from web3 import AsyncWeb3

try:
    import dexbot_core
    RUST_AVAILABLE = True
except ImportError:
    dexbot_core = None
    RUST_AVAILABLE = False
    print("КРИТИЧЕСКОЕ ПРЕДУПРЕЖДЕНИЕ: Rust-модуль 'dexbot_core' не найден.")


class BotService:
    """
    Тонкий слой координации между TUI и Rust ядром.
    
    Не выполняет бизнес-логику! Только:
    - Работает с БД через cache.db
    - Отправляет команды в Rust через bridge
    - Управляет PnL трекерами
    """

    def __init__(self, cache: GlobalCache, notification_queue: Optional[asyncio.Queue], config: Config):
        self.cache = cache
        self.notification_queue = notification_queue
        self.config = config
        
        # Bridge для отправки команд в Rust (устанавливается извне)
        self.bridge: Optional[BridgeManager] = None
        
        # Воркеры
        self.workers: List[asyncio.Task] = []
        self._is_running = False
        
        # Активные PnL трекеры
        self._active_pnl_trackers: Set[str] = set()

    # ==================== TOKEN METADATA (БД) ====================

    async def fetch_and_store_token_metadata(self, token_address: str):
        """
        Получить name/symbol токена и сохранить в БД.
        Это операция с БД, поэтому в Python.
        """
        try:
            # Проверяем кэш БД
            metadata = await self.cache.db.get_token_metadata(token_address)
            if metadata and metadata.get('name') and metadata.get('symbol'):
                return

            # Получаем через RPC (простой вызов, не бизнес-логика)
            w3 = await self._get_w3()
            token_cs = w3.to_checksum_address(token_address)
            token_contract = w3.eth.contract(address=token_cs, abi=ERC20_ABI)

            results = await asyncio.gather(
                token_contract.functions.name().call(),
                token_contract.functions.symbol().call(),
                return_exceptions=True
            )
            
            name = results[0] if not isinstance(results[0], Exception) else "Unknown"
            symbol = results[1] if not isinstance(results[1], Exception) else "???"
            
            # Сохраняем в БД
            await self.cache.db.add_or_update_recent_token(token_address, name=name, symbol=symbol)
            await log.debug(f"[DB] Token metadata saved: {symbol} ({name})")

        except Exception as e:
            await log.error(f"Ошибка получения метаданных токена: {e}")
            # Сохраняем заглушку
            await self.cache.db.add_or_update_recent_token(token_address, name="Unknown", symbol="???")

    async def _get_w3(self) -> AsyncWeb3:
        """Получить Web3 инстанс для простых запросов к БД."""
        rpc_url = self.cache.get_config().get('rpc_url', self.config.RPC_URL)
        return AsyncWeb3(AsyncWeb3.AsyncHTTPProvider(rpc_url))

    # ==================== PnL MANAGEMENT ====================

    async def _pnl_management_worker(self):
        """
        Восстанавливает PnL трекеры для активных позиций из БД.
        Запускается при старте бота.
        """
        if not RUST_AVAILABLE:
            return
            
        await asyncio.sleep(2)  # Ждём инициализации Rust
        
        while self._is_running:
            try:
                config = self.cache.get_config()
                rpc_url = config.get('rpc_url', self.config.RPC_URL)
                quote_symbol = config.get('default_quote_currency', self.config.DEFAULT_QUOTE_CURRENCY)
                quote_address = self.config.QUOTE_TOKENS.get(quote_symbol, "").lower()
                
                # Получаем все кэшированные балансы из БД
                cached_balances = await self.cache.db.get_all_cached_balances()
                
                for row in cached_balances:
                    w_addr = row['wallet_address']
                    t_addr = row['token_address']
                    balance_wei = int(row['balance_wei'])
                    
                    # Пропускаем ненужные
                    if balance_wei <= 0:
                        continue
                    if t_addr.lower() == quote_address:
                        continue
                    if t_addr.lower() == self.config.NATIVE_CURRENCY_ADDRESS.lower():
                        continue
                    
                    pnl_key = f"{w_addr}:{t_addr}"
                    if pnl_key in self._active_pnl_trackers:
                        continue
                    
                    # Получаем позицию из БД
                    pos = await self.cache.db.get_position(w_addr, t_addr)
                    if pos['total_cost'] <= 0:
                        continue
                    
                    # Находим пул
                    pool_info = self.cache.get_best_pool(t_addr, quote_address)
                    if not pool_info or "error" in pool_info:
                        continue
                    
                    # Запускаем PnL трекер в Rust
                    pool_type = pool_info['type']
                    v3_fee = pool_info.get('fee', 0)
                    
                    await asyncio.to_thread(
                        dexbot_core.start_pnl_tracker,
                        rpc_url, w_addr, t_addr, quote_address,
                        str(balance_wei), str(pos['total_cost']),
                        pool_type, v3_fee,
                        self.config.V2_ROUTER_ADDRESS,
                        self.config.V3_QUOTER_ADDRESS
                    )
                    
                    self._active_pnl_trackers.add(pnl_key)
                    await log.info(f"[PnL] Трекер запущен: {w_addr[:6]}... / {t_addr[:10]}...")

            except asyncio.CancelledError:
                break
            except Exception as e:
                await log.error(f"Ошибка в PnL Manager: {e}")
            
            await asyncio.sleep(10)

    def stop_pnl_tracker(self, wallet_address: str, token_address: str):
        """Остановить PnL трекер после продажи."""
        if not RUST_AVAILABLE:
            return
        
        pnl_key = f"{wallet_address.lower()}:{token_address.lower()}"
        self._active_pnl_trackers.discard(pnl_key)
        
        # Запускаем в фоне
        try:
            asyncio.create_task(asyncio.to_thread(
                dexbot_core.stop_pnl_tracker,
                wallet_address,
                token_address
            ))
        except Exception as e:
            asyncio.create_task(log.error(f"Ошибка остановки PnL трекера: {e}"))

    def start_pnl_tracker(self, wallet_address: str, token_address: str, balance_wei: int, cost_wei: int):
        """Запустить PnL трекер после покупки."""
        if not RUST_AVAILABLE:
            return
        
        pnl_key = f"{wallet_address.lower()}:{token_address.lower()}"
        if pnl_key in self._active_pnl_trackers:
            return
        
        config = self.cache.get_config()
        quote_symbol = config.get('default_quote_currency', self.config.DEFAULT_QUOTE_CURRENCY)
        quote_address = self.config.QUOTE_TOKENS.get(quote_symbol, "").lower()
        
        pool_info = self.cache.get_best_pool(token_address, quote_address)
        if not pool_info or "error" in pool_info:
            return
        
        pool_type = pool_info['type']
        v3_fee = pool_info.get('fee', 0)
        rpc_url = config.get('rpc_url', self.config.RPC_URL)
        
        # Запускаем в фоне
        try:
            asyncio.create_task(asyncio.to_thread(
                dexbot_core.start_pnl_tracker,
                rpc_url, wallet_address, token_address, quote_address,
                str(balance_wei), str(cost_wei),
                pool_type, v3_fee,
                self.config.V2_ROUTER_ADDRESS,
                self.config.V3_QUOTER_ADDRESS
            ))
            self._active_pnl_trackers.add(pnl_key)
        except Exception as e:
            asyncio.create_task(log.error(f"Ошибка запуска PnL трекера: {e}"))

    # ==================== TRADE SCHEDULING ====================

    async def schedule_trades(self, trade: dict) -> Dict[str, Any]:
        """
        Подготовить и отправить команду торговли в Rust ядро.
        
        trade = {
            'action': 'buy' | 'sell',
            'token_address': '0x...',
            'quote_token': 'WBNB',
            'amount': 0.01,
            'wallets': ['0x...'],
            'slippage': 15.0,      # опционально
            'gas_price_gwei': 1.0, # опционально
            'amounts_wei': {'0x...': '1000000'} # опционально
        }
        
        Returns:
            {'status': 'success' | 'error', 'message': '...'}
        """
        if not self.bridge:
            return {"status": "error", "message": "Bridge не инициализирован"}
        
        if not RUST_AVAILABLE:
            return {"status": "error", "message": "Rust ядро недоступно"}
        
        action = trade.get('action', 'buy').lower()
        token_address = trade['token_address']
        quote_token = trade.get('quote_token', 'WBNB')
        amount = trade['amount']
        wallets = trade['wallets']
        slippage = trade.get('slippage') or self.cache.get_config().get('slippage', 15.0)
        gas_gwei = trade.get('gas_price_gwei') or self.cache.get_config().get('default_gas_price_gwei', 1.0)
        amounts_wei = trade.get('amounts_wei')
        
        # Определяем адрес quote токена
        native_symbol = self.config.NATIVE_CURRENCY_SYMBOL
        if quote_token == native_symbol:
            quote_address = self.config.QUOTE_TOKENS.get(f"W{native_symbol}", "")
        else:
            quote_address = self.config.QUOTE_TOKENS.get(quote_token, "")
        
        if not quote_address:
            return {"status": "error", "message": f"Quote токен {quote_token} не найден"}
        
        # Находим пул
        pool_info = self.cache.get_best_pool(token_address, quote_address)
        if not pool_info or "error" in pool_info:
            return {"status": "error", "message": f"Пул не найден для {quote_token}"}
        
        pool_type = pool_info['type']
        v3_fee = pool_info.get('fee', 0)
        
        # Проверка ликвидности для BUY (предупреждение)
        if action == "buy":
            liq_usd = pool_info.get('liquidity_usd', 0)
            if liq_usd > 0 and amount > liq_usd * 0.15:
                await log.warning(f"⚠️ Сделка > 15% ликвидности пула!")
        
        # Определяем V3 fee
        if pool_type != 'V3':
            v3_fee = 0
        
        # Сохраняем активный трейд для последующего обновления БД
        self.cache.set_active_trade_token(token_address)
        self.cache.set_active_trade_amount_for_quote(amount)
        
        # Отправляем команду в Rust через Bridge
        command = EngineCommand.execute_trade(
            action=action,
            token=token_address,
            quote_token=quote_address,
            amount=amount,
            wallets=wallets,
            gas_gwei=gas_gwei,
            slippage=slippage,
            v3_fee=v3_fee,
            amounts_wei=amounts_wei
        )
        
        self.bridge.send(command)
        
        action_ru = "Покупка" if action == "buy" else "Продажа"
        await log.info(f"[BRIDGE] {action_ru} отправлена в Rust: {token_address[:10]}... | {amount} | {pool_type}")
        
        return {
            "status": "success",
            "message": f"{action_ru} отправлена (Пул: {pool_type})"
        }

    # ==================== LIFECYCLE ====================

    def start(self):
        """Запуск сервиса."""
        if self._is_running:
            return
        
        self._is_running = True
        
        # Запускаем PnL менеджер
        self.workers.append(asyncio.create_task(self._pnl_management_worker()))
        
        asyncio.create_task(log.info("BotService запущен"))

    def stop(self):
        """Остановка сервиса."""
        if not self._is_running:
            return
        
        self._is_running = False
        
        for worker in self.workers:
            worker.cancel()
        
        self._active_pnl_trackers.clear()
        
        asyncio.create_task(log.info("BotService остановлен"))

    # ==================== HELPER (для TUI) ====================

    async def refresh_all_balances(self):
        """Запросить обновление всех балансов из Rust."""
        if self.bridge:
            self.bridge.send(EngineCommand.refresh_all_balances())
    
    async def switch_token(self, token_address: str, quote_address: str):
        """Переключить мониторинг на новый токен."""
        if self.bridge:
            self.bridge.send(EngineCommand.switch_token(token_address, quote_address))