from .router import APIRouter
from .middleware.validation import *
from .endpoints.wallets import WalletsEndpoint
from .endpoints.config import ConfigEndpoint
from .endpoints.trading import TradingEndpoint
from .endpoints.pools import PoolsEndpoint
from .endpoints.system import SystemEndpoint

def create_api_router(cache, bot_service) -> APIRouter:
    """Создать и настроить API роутер"""
    router = APIRouter()
    
    # Регистрация middleware в правильном порядке
    router.add_middleware(rate_limit_middleware)
    router.add_middleware(auth_middleware)
    router.add_middleware(validate_wallet_address)
    router.add_middleware(validate_token_address)
    router.add_middleware(validate_trade_amount)
    
    # Создание эндпоинтов
    wallets_endpoint = WalletsEndpoint(cache)
    config_endpoint = ConfigEndpoint(cache)
    trading_endpoint = TradingEndpoint(cache, bot_service)
    pools_endpoint = PoolsEndpoint(cache, bot_service)
    system_endpoint = SystemEndpoint(cache)
    
    # Регистрация маршрутов
    router.register_route('wallets', wallets_endpoint.execute)
    router.register_route('config', config_endpoint.execute)
    router.register_route('trading', trading_endpoint.execute)
    router.register_route('pools', pools_endpoint.execute)
    router.register_route('system', system_endpoint.execute)
    
    return router