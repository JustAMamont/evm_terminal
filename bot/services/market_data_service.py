import asyncio
import ccxt.pro as ccxtpro
from bot.core.config import Config
from bot.cache import GlobalCache
from utils.aiologger import log
from bot.core.bridge import BridgeManager, EngineCommand
from typing import Optional

class MarketDataService:
    def __init__(self, cache: GlobalCache, config: Config):
        self.cache = cache
        self.config = config
        self.bridge: Optional[BridgeManager] = None  
        self.worker_task: Optional[asyncio.Task] = None
        self._is_running = False
        self.exchange: Optional[ccxtpro.binance] = None

    def start(self):
        """Запуск воркера цен Binance"""
        if self._is_running:
            return
        self._is_running = True
        self.worker_task = asyncio.create_task(self._quotes_price_worker())
        asyncio.create_task(log.info("MarketDataService: Запущен воркер цен Binance."))

    async def stop(self):
        """Полная остановка"""
        self._is_running = False
        if self.worker_task:
            self.worker_task.cancel()
        if self.exchange:
            try:
                await self.exchange.close()
            except:
                pass
        asyncio.create_task(log.info("MarketDataService: Остановлен."))

    async def _quotes_price_worker(self):
        """
        Получает цены с Binance и транслирует их в Rust 
        для реактивного расчета PnL и TVL.
        """
        self.exchange = ccxtpro.binance()
        symbols = self.config.ERC20_QUOTES_TICKERS
        
        if not symbols:
            return

        first_run = True
        while self._is_running:
            try:
                if first_run:
                    tickers = await self.exchange.fetch_tickers(symbols)
                    first_run = False
                else:
                    tickers = await self.exchange.watch_tickers(symbols)

                for sym, data in tickers.items():
                    base_symbol = sym.split("/")[0]
                    price = float(data['last'])
                    
                    # Обновляем локальный кэш
                    self.cache.set_quote_price(base_symbol, price)
                    
                    # Отправляем цену в Rust Engine
                    if self.bridge:
                        self.bridge.send(EngineCommand.update_price(
                            symbol=base_symbol, 
                            price=price
                        ))

            except asyncio.CancelledError:
                break
            except Exception as e:
                await log.error(f"MarketDataService (Binance): Ошибка получения цен: {e}")
                await asyncio.sleep(5)
