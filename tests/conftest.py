import pytest
import sys
from unittest.mock import MagicMock

# --- 1. Моки dexbot_core (Rust module) ---
mock_dexbot = MagicMock()
mock_dexbot.get_network_config.return_value = {
    "name": "TestNet",
    "db_path": ":memory:",
    "rpc_url": "https://testnode.com",
    "chain_id": 1337,
    "native_currency_symbol": "ETH",
    "native_currency_address": "0xeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee",
    "dex_router_address": "0xRouter",
    "quote_tokens": {"USDT": "0xUSDT", "WETH": "0xWETH"},
    "default_quote_currency": "USDT",
    "fee_receiver": "0xFee",
    "explorer_url": "https://scan.com",
    "v2_factory_address": "0xV2Fact",
    "v3_factory_address": "0xV3Fact",
    "v2_router_address": "0xV2Router",
    "v3_quoter_address": "0xV3Quoter",
}
mock_dexbot.execute_batch_swap.return_value = ["0xTxHash1", "0xTxHash2"]
mock_dexbot.init_or_load_keys.return_value = None

sys.modules["dexbot_core"] = mock_dexbot


from bot.core.db_manager import DatabaseManager
from bot.cache import GlobalCache
from bot.core.config import Config

@pytest.fixture
def mock_config():
    net_settings = mock_dexbot.get_network_config("test")
    return Config(net_settings)

@pytest.fixture
async def db_manager():
    # Используем in-memory базу данных
    db = DatabaseManager(":memory:", ":memory:")
    await db.connect()
    
    # Устанавливаем пароль, чтобы SecurityManager разблокировался
    await db.set_password("test_password_123")
    
    yield db
    await db.close()

@pytest.fixture
async def cache(db_manager):
    c = GlobalCache(db_manager)
    await c.initialize()
    await c.update_config({
        "rpc_url": "https://testnode.com",
        "default_quote_currency": "USDT",
        "slippage": 1.0,
        "auto_fuel_enabled": True,
        "auto_fuel_threshold": 0.05,
        "auto_fuel_amount": 0.1
    })
    return c