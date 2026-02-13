import pytest
from unittest.mock import patch
from bot.services.bot_service import BotService
from bot.inner_api.schemas import TradeRequest, TradeAction

@pytest.mark.asyncio
async def test_schedule_trade_buy(cache, mock_config):
    bot = BotService(cache, None, mock_config)
    
    # 1. Подготовка данных
    wallet_addr = "0xWallet1"
    token_addr = "0xTokenToBuy"
    await cache.add_wallet(wallet_addr, "0xPrivKey1", "W1", True)
    
    # Имитируем, что пул найден
    cache.set_best_pool(token_addr, "0xUSDT", {
        "address": "0xPoolAddr", 
        "type": "V2", 
        "fee": 3000
    })
    
    # Мокаем проверку ликвидности Rust (чтобы не фейлилось на get_all_pool_balances)
    with patch("dexbot_core.get_all_pool_balances", return_value={"0xpooladdr": "1000000000000000000000"}):
        req = TradeRequest(
            token_address=token_addr,
            quote_token="USDT",
            action=TradeAction.BUY,
            amount=0.5, # 0.5 USDT
            wallets=[wallet_addr],
            slippage=10.0
        )
        
        # 2. Запуск
        response = await bot.schedule_trades(req)
        
        # 3. Проверки
        assert response['status'] == 'success'
        assert not bot.swap_queue.empty()
        
        cmd = await bot.swap_queue.get()
        assert cmd['action'] == 'buy'
        assert cmd['wallet_addresses'] == [wallet_addr]
        assert cmd['private_keys'] == ["0xPrivKey1"]
        assert cmd['path'] == ["0xusdt", token_addr.lower()] # USDT -> Token
        assert cmd['amount_in'] == 0.5