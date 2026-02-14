import pytest
import dexbot_core
import asyncio
from bot.bot import run_bot_instance
from unittest.mock import patch, AsyncMock, MagicMock

@pytest.mark.asyncio
async def test_system_hard_reset_on_network_change():
    """Проверка вызова функций очистки Rust при старте инстанса."""
    
    # 1. Мокаем базу данных
    mock_db = MagicMock()
    mock_db.connect = AsyncMock()
    mock_db.close = AsyncMock()
    mock_db.is_encrypted = AsyncMock(return_value=True)
    mock_db.unlock_db = AsyncMock(return_value=True)
    mock_db.get_config = AsyncMock(return_value={})

    # 2. Мокаем Кэш
    mock_cache = MagicMock()
    mock_cache.initialize = AsyncMock()
    mock_cache.get_config.return_value = {"rpc_url": "http://test"}
    mock_cache.get_all_wallets.return_value = []
    mock_cache.dump_state_to_db = AsyncMock()

    # 3. Мокаем приложение (TUI)
    mock_app = MagicMock()
    mock_app.run_async = AsyncMock(return_value=None) # Чтобы сразу вышло из цикла

    with patch("bot.bot.load_resource_bundle", return_value={"name": "test", "db_path": "test.db", "chain_id": 1, "rpc_url": "http://test", "native_currency_symbol": "ETH", "native_currency_address": "0x", "explorer_url": "http://", "dex_router_address": "0x", "quote_tokens": {}, "default_quote_currency": "USDT"}), \
         patch("bot.bot.Config", return_value=MagicMock()), \
         patch("bot.bot.DatabaseManager", return_value=mock_db), \
         patch("bot.bot.secure_db_unlock", AsyncMock(return_value="password")), \
         patch("bot.bot.GlobalCache", return_value=mock_cache), \
         patch("bot.bot.BotService") as mock_bot_svc, \
         patch("bot.bot.MarketDataService") as mock_market_svc, \
         patch("bot.bot.TradingApp", return_value=mock_app), \
         patch("bot.bot.save_last_network", AsyncMock()):

        # Настраиваем методы стоп для сервисов
        mock_bot_svc.return_value.stop = MagicMock()
        mock_bot_svc.return_value.workers = []
        mock_market_svc.return_value.stop = AsyncMock()
        mock_market_svc.return_value.workers = []

        # ЗАПУСК
        await run_bot_instance("bsc", ["bsc", "eth"])
        
        # ПРОВЕРКА RUST
        assert dexbot_core.shutdown_rust_workers.called # type: ignore
        assert dexbot_core.reset_rust_state.called # type: ignore
        assert dexbot_core.clear_all_pnl_trackers.called # type: ignore