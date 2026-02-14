import pytest
import asyncio
from unittest.mock import patch, MagicMock, AsyncMock
from bot.services.bot_service import BotService
from bot.inner_api.schemas import TradeRequest, TradeAction

@pytest.mark.asyncio
async def test_dca_balance_summing(cache, mock_config):
    """Проверка суммирования баланса при докупе (DCA)."""
    # Создаем сервис
    bot = BotService(cache, None, mock_config)
    bot._is_running = True
    
    wallet = "0x1234567890123456789012345678901234567890"
    token = "0x55d398326f99059ff775485246999027b3197955"
    
    # Подготовка данных
    await cache.add_wallet(wallet, "0xPriv", "W1", True)
    cache.set_exact_balance_wei(wallet, token, 1000) # Начальный баланс 1000
    cache.set_active_trade_amount_for_quote(1.0)     # Имитируем активную сумму покупки
    
    # Формируем объект квитанции
    mock_receipt = MagicMock()
    mock_receipt.status = 1
    
    # Имитируем лог Transfer (ERC20)
    log_entry = {
        'address': token,
        'topics': [
            # Topic 0: Transfer Signature
            bytes.fromhex("ddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef"),
            # Topic 1: From (Zero address)
            bytes.fromhex("0000000000000000000000000000000000000000000000000000000000000000"),
            # Topic 2: To (Наш кошелек)
            bytes.fromhex(f"000000000000000000000000{wallet[2:]}")
        ],
        'data': bytes.fromhex("00000000000000000000000000000000000000000000000000000000000001f4") # 500
    }
    
    mock_receipt.logs = [log_entry]
    
    # Позволяем обращаться к моку как к словарю: receipt['logs']
    mock_receipt.__getitem__.side_effect = lambda key: getattr(mock_receipt, key)

    mock_w3 = MagicMock()
    mock_w3.eth.wait_for_transaction_receipt = AsyncMock(return_value=mock_receipt)
    
    # Мокаем получение Web3
    with patch.object(bot, '_get_rpc_w3', AsyncMock(return_value=mock_w3)):
        # Кладем задачу в очередь TxWatcher
        tx_data = {
            "tx_hash": b"some_hash", 
            "wallet_address": wallet, 
            "action": "buy", 
            "token": token
        }
        await bot.tx_watcher_queue.put(tx_data)
        
        # Запускаем воркер
        worker_task = asyncio.create_task(bot._tx_watcher_worker())
        
        try:
            # Ждем обработки очереди
            await asyncio.wait_for(bot.tx_watcher_queue.join(), timeout=2.0)
        finally:
            bot._is_running = False
            worker_task.cancel()

    # ПРОВЕРКА: Баланс должен быть 1000 + 500 = 1500
    final_balance = cache.get_exact_balance_wei(wallet, token)
    assert final_balance == 1500, f"Ожидалось 1500, получили {final_balance}"


@pytest.mark.asyncio
async def test_schedule_trade_buy(cache, mock_config):
    """Тест планирования покупки."""
    bot = BotService(cache, None, mock_config)
    wallet_addr = "0x1234567890123456789012345678901234567890"
    token_addr = "0x55d398326f99059ff775485246999027b3197955"
    
    await cache.add_wallet(wallet_addr, "0xPrivKey1", "W1", True)
    # Имитируем найденный пул
    cache.set_best_pool(token_addr, "0xUSDT", {"address": "0xPoolAddr", "type": "V2", "fee": 3000})
    
    # Мокаем проверку ликвидности в Rust
    with patch("dexbot_core.get_all_pool_balances", return_value={"0xPoolAddr": "1000000000000000000000"}):
        req = TradeRequest(
            token_address=token_addr,
            quote_token="USDT",
            action=TradeAction.BUY,
            amount=0.5,
            wallets=[wallet_addr],
            slippage=10.0
        )
        
        response = await bot.schedule_trades(req)
        
        assert response['status'] == 'success'
        assert not bot.swap_queue.empty()
        
        cmd = await bot.swap_queue.get()
        assert cmd['action'] == 'buy'
        assert cmd['wallet_addresses'] == [wallet_addr]