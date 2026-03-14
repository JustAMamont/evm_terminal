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
        """Launch of the Binance Price Worker"""
        if self._is_running:
            return
        self._is_running = True
        self.worker_task = asyncio.create_task(self._quotes_price_worker())
        asyncio.create_task(log.info("MarketDataService: Binance Price Worker Launched."))

    async def stop(self):
        """Full stop"""
        self._is_running = False
        if self.worker_task:
            self.worker_task.cancel()
        if self.exchange:
            try:
                await self.exchange.close()
            except:
                pass
        asyncio.create_task(log.info("MarketDataService: Stopped."))

    async def _quotes_price_worker(self):
        """
        Fetches prices from Binance and translates them into Rust for reactive PnL and TVL calculation.
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
                        await self.bridge.send(EngineCommand.update_price(
                            symbol=base_symbol, 
                            price=price
                        ))

            except asyncio.CancelledError:
                break
            except Exception as e:
                await log.error(f"MarketDataService (Binance): Error retrieving prices: {e}")
                await asyncio.sleep(5)
