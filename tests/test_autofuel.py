import pytest
import asyncio
from unittest.mock import MagicMock, AsyncMock, patch
from bot.services.bot_service import BotService

@pytest.mark.asyncio
async def test_autofuel_trigger(cache, mock_config):
    queue = asyncio.Queue()
    bot = BotService(cache, queue, mock_config)
    
    wallet_addr = "0x1234567890123456789012345678901234567890"
    await cache.add_wallet(wallet_addr, "0xPrivKey", "Test", True)
    
    # Включаем авто-заправку в кэше/бд
    await cache.update_config({"auto_fuel_enabled": True, "auto_fuel_threshold": 0.05, "auto_fuel_amount": 0.1})
    
    mock_w3 = MagicMock()
    with patch.object(bot, '_get_rpc_w3', new_callable=AsyncMock) as mock_w3_getter:
        mock_w3_getter.return_value = mock_w3
        
        # Настройка балансов (USDT есть, нативки мало)
        cache.set_wallet_balance(wallet_addr, "0xUSDT", 100.0) 
        cache.set_token_decimals("0xUSDT", 18)
        
        mock_router = MagicMock()
        # Возвращаем awaitable для .call()
        mock_router.functions.getAmountsIn.return_value.call = AsyncMock(return_value=[5000000, 0])
        
        mock_w3.eth.contract.return_value = mock_router
        mock_w3.to_checksum_address.side_effect = lambda x: x 
        mock_w3.to_wei.side_effect = lambda val, unit: int(val * 10**18)

        # Сброс кулдаунов
        bot._refuel_cooldowns = {}
        
        # Запуск (баланс 0.01 < порога 0.05)
        await bot.check_and_execute_autofuel(wallet_addr, 0.01)
        
        assert not bot.swap_queue.empty()
        command = await bot.swap_queue.get()
        assert command['action'] == 'buy'
        assert command['method_type'] == 'TokensForETH'