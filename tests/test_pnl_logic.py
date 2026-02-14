import pytest
from unittest.mock import patch, AsyncMock
from bot.services.bot_service import BotService

@pytest.mark.asyncio
async def test_pnl_cost_calculation_usdt(cache, mock_config):
    """Проверка расчета затрат для токена с 6 знаками (USDT)."""
    bot = BotService(cache, None, mock_config)
    
    # 100 USDT при 6 знаках
    cache.set_token_decimals("0xUSDT", 6)
    spent_amount = 100.0
    q_decimals = cache.get_token_decimals("0xUSDT")
    cost_wei = int(spent_amount * (10**q_decimals))
    
    assert cost_wei == 100_000_000

@pytest.mark.asyncio
async def test_pnl_tracker_triggering(cache, mock_config):
    """Проверка, что данные улетают в Rust правильно."""
    import dexbot_core
    bot = BotService(cache, None, mock_config)
    wallet = "0x1234567890123456789012345678901234567890"
    token = "0xTokenAddress"
    
    # Мокаем БД внутри кэша
    cache.db.get_position = AsyncMock(return_value={'total_cost': 10**6})
    cache.set_exact_balance_wei(wallet, token, 10**18)
    cache.set_best_pool(token, "0xUSDT", {"address": "0xPool", "type": "V2"})
    
    with patch("dexbot_core.start_pnl_tracker") as mock_rust_start:
        await bot.trigger_pnl_tracker(wallet, token)
        
        assert mock_rust_start.called
        args = mock_rust_start.call_args[0]
        assert args[4] == str(10**18) # Balance Wei
        assert args[5] == str(10**6)  # Cost Wei