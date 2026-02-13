import pytest
import asyncio
from unittest.mock import MagicMock, AsyncMock, patch
from bot.services.bot_service import BotService

@pytest.mark.asyncio
async def test_autofuel_trigger(cache, mock_config):
    queue = asyncio.Queue()
    bot = BotService(cache, queue, mock_config)
    
    wallet_addr = "0xTestWallet"
    # Теперь это сработает, так как в conftest мы разблокировали БД
    await cache.add_wallet(wallet_addr, "0xPrivKey", "Test", True)
    
    # Используем MagicMock для самого Web3, но оборачиваем в AsyncMock для геттера
    mock_w3 = MagicMock()
    
    with patch.object(bot, '_get_rpc_w3', new_callable=AsyncMock) as mock_w3_getter:
        mock_w3_getter.return_value = mock_w3
        
        cache.set_wallet_balance(wallet_addr, "0xUSDT", 100.0) 
        cache.set_token_decimals("0xUSDT", 18)
        
        # Мокаем контракт роутера
        mock_router = MagicMock()
        # .functions.getAmountsIn(...).call() -> это асинхронный вызов в коде бота?
        # Смотрим код BotService: await v2_router.functions.getAmountsIn(...).call()
        # Значит .call() должен возвращать awaitable (AsyncMock или корутину)
        
        mock_call = AsyncMock(return_value=[5000000000000000000, 0])
        mock_router.functions.getAmountsIn.return_value.call = mock_call
        
        mock_w3.eth.contract.return_value = mock_router
        mock_w3.to_checksum_address.side_effect = lambda x: x 

        # --- СЦЕНАРИЙ 1 ---
        await bot.check_and_execute_autofuel(wallet_addr, 0.1)
        assert bot.swap_queue.empty()

        # --- СЦЕНАРИЙ 2 ---
        bot._refuel_cooldowns = {} 
        
        await bot.check_and_execute_autofuel(wallet_addr, 0.01)
        
        assert not bot.swap_queue.empty()
        
        command = await bot.swap_queue.get()
        assert command['type'] == 'batch'
        assert command['action'] == 'buy'
        assert command['method_type'] == 'TokensForETH'