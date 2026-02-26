from typing import Dict, List, Any

try:
    import dexbot_core
    RUST_AVAILABLE = True
except ImportError:
    dexbot_core = None
    RUST_AVAILABLE = False

APPROVE_GAS_LIMIT = 100_000
TRANSFER_EVENT_TOPIC = "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef"

class Config:
    def __init__(self, network_settings: Dict[str, Any]):
        self.CURRENT_VERSION: str = "1.0.0"

        # Настройки из JSON
        self.NAME = network_settings['name']
        self.DB_PATH = network_settings['db_path']
        self.CHAIN_ID = network_settings['chain_id']
        self.RPC_URL = network_settings['rpc_url']
        if network_settings.get('wss_url'):
            self.WSS_URL = network_settings['wss_url']
        else:
            self.WSS_URL = self.RPC_URL.replace("https://", "wss://").replace("http://", "ws://")
        
        self.NATIVE_CURRENCY_SYMBOL = network_settings['native_currency_symbol']
        self.NATIVE_CURRENCY_ADDRESS = network_settings['native_currency_address']
        self.EXPLORER_URL = network_settings['explorer_url']
        self.DEX_ROUTER_ADDRESS = network_settings['dex_router_address']

        self.V2_FACTORY_ADDRESS = network_settings.get('v2_factory_address', '')
        self.V3_FACTORY_ADDRESS = network_settings.get('v3_factory_address', '')
        self.V2_ROUTER_ADDRESS = network_settings.get('v2_router_address', '') 
        self.V3_QUOTER_ADDRESS = network_settings.get('v3_quoter_address', '')
        
        self.PUBLIC_RPC_URLS = network_settings.get('public_rpc_urls', [])
        self.FEE_RECEIVER = network_settings.get('fee_receiver', '').lower()
        
        self.QUOTE_TOKENS = network_settings['quote_tokens']
        self.DEFAULT_QUOTE_CURRENCY = network_settings['default_quote_currency']
        self.ERC20_QUOTES_TICKERS: List[str] = self._generate_tickers()

        self.APPROVE_GAS_LIMIT = 100_000
        self.DEFAULT_GAS_PRICE_GWEI = 0.1

    def _generate_tickers(self) -> List[str]:
        """
        Формирует список тикеров на основе quote_tokens из JSON, 
        для запроса цены квотируемого токена к доллару у бинанса
        """
        tickers = set()
        
        # Стейблы из конфигов, которые не мониторим к USDT (цена ~1.0)
        stables_to_skip = {"USDT", "USDC", "BUSD", "USD1"}
        
        # Всегда мониторим нативку (BNB/USDT)
        if self.NATIVE_CURRENCY_SYMBOL not in stables_to_skip:
            tickers.add(f"{self.NATIVE_CURRENCY_SYMBOL}/USDT")

        for symbol in self.QUOTE_TOKENS.keys():
            # Очистка W для Бинанса
            clean_sym = symbol
            if symbol == "WBNB": 
                clean_sym = "BNB"
            elif symbol == "WETH": 
                clean_sym = "ETH"
            
            # Пропускаем, если это стейбл из твоего списка
            if clean_sym in stables_to_skip:
                continue
            
            # Добавляем всё остальное, что есть в JSON (ASTER, U и т.д.)
            tickers.add(f"{clean_sym}/USDT")

        return list(tickers)

    def get(self, key, default=None):
        return getattr(self, key.upper(), default)