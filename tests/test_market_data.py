import pytest
from unittest.mock import MagicMock, AsyncMock, patch
from bot.services.market_data_service import MarketDataService

@pytest.mark.asyncio
async def test_find_best_pool(cache, mock_config):
    service = MarketDataService(cache, mock_config)
    
    token_addr = "0xNewToken"
    quote_addr = "0xUSDT" 
    
    # mock_w3 должен быть MagicMock (обычный объект), 
    # но возвращаться он должен через AsyncMock (так как _get_rpc_w3 асинхронный)
    mock_w3 = MagicMock() 
    service._get_rpc_w3 = AsyncMock(return_value=mock_w3)
    
    # Настраиваем синхронные методы Web3
    mock_w3.to_checksum_address.side_effect = lambda x: x
    
    # Имитируем Factory контракты
    mock_factory = MagicMock()
    # Теперь это вернет mock_factory сразу, а не корутину
    mock_w3.eth.contract.return_value = mock_factory
    
    async def factory_call_mock(*args, **kwargs):
        return "0xPoolAddress"

    # Настраиваем gather
    with patch("asyncio.gather", new_callable=AsyncMock) as mock_gather:
        # 1. Адреса пулов
        addresses_result = [
            "0xV2Pool", "0x0000000000000000000000000000000000000000", 
            "0xV3Pool", "0x0000000000000000000000000000000000000000", 
            "0x0000000000000000000000000000000000000000"              
        ] 
        addresses_result += ["0x0000000000000000000000000000000000000000"] * 5 
        
        # 2. Балансы
        balances_result = [100, 5000] 
        
        mock_gather.side_effect = [addresses_result, balances_result]

        await service.find_and_cache_best_pool(token_addr, "USDT")
        
        best_pool = cache.get_best_pool(token_addr, "0xUSDT")
        assert best_pool is not None
        assert "error" not in best_pool
        
        # Проверяем, что выиграл V3 пул с балансом 5000
        assert best_pool['address'] == "0xV3Pool"
        assert best_pool['balance'] == 5000
        assert best_pool['type'] == 'V3'
        assert best_pool['fee'] == 500