import sys
import os
import asyncio
import signal
from pathlib import Path
from typing import Optional

from rich.console import Console
from rich.prompt import Prompt

try:
    import dexbot_core
except ImportError:
    print("WARNING: Rust core module not found.")
    dexbot_core = None

from bot.inner_api.router import APIRouter
from bot.inner_api.endpoints.trading import TradingEndpoint
from bot.inner_api.endpoints.wallets import WalletsEndpoint
from bot.inner_api.endpoints.system import SystemEndpoint
from bot.inner_api.endpoints.config import ConfigEndpoint
from bot.services.bot_service import BotService
from bot.services.market_data_service import MarketDataService
from utils.aiologger import log
from bot.cache import GlobalCache
from bot.core.db_manager import DatabaseManager
from tui.app import TradingApp
from bot.core.config import Config
from bot.core.integrities import load_resource_bundle, enumerate_adapters

console = Console()
SHUTDOWN_REQUESTED = False
TUI_APP_INSTANCE: Optional[TradingApp] = None
CURRENT_VERSION = "1.0.0"

def force_restore_terminal():
    """Восстанавливает настройки терминала после выхода из TUI."""
    if sys.platform != "win32":
        try: os.system("stty sane")
        except: pass
    try:
        if console and console.is_terminal:
            console.show_cursor(True)
    except: pass

async def secure_db_unlock(db_manager: DatabaseManager, network_name: str) -> str:
    """Логика авторизации и разблокировки БД. Возвращает пароль."""
    console.print(f"\n[bold cyan]--- АВТОРИЗАЦИЯ: Сеть {network_name.upper()} ---[/bold cyan]")
    if not await db_manager.is_encrypted():
        console.print("[bold yellow]ВНИМАНИЕ: Придумайте и введите мастер-пароль![/bold yellow]\n[dim yellow]   (Пароль используется для шифрования ключей в БД)[/dim yellow]")
        while True:
            pwd1 = Prompt.ask("Новый пароль", password=True)
            pwd2 = Prompt.ask("Повторите пароль", password=True)
            if pwd1 == pwd2 and len(pwd1) > 0:
                await db_manager.set_password(pwd1)
                return pwd1
            else:
                console.print("[bold red]Пароли не совпадают. Попробуйте снова.[/bold red]")
    else:
        attempts = 3
        while attempts > 0:
            pwd = Prompt.ask(f"Введите пароль для {network_name.upper()}", password=True)
            if await db_manager.unlock_db(pwd):
                return pwd
            attempts -= 1
            console.print(f"[bold red]Неверный пароль. Осталось попыток: {attempts}[/bold red]")
        sys.exit(1)

async def save_last_network(db_manager: DatabaseManager, network_name: str):
    try: await db_manager.update_config({"last_network": network_name})
    except: pass

async def load_last_network(db_manager: DatabaseManager, available_networks: list) -> str:
    try:
        config = await db_manager.get_config()
        last = config.get('last_network')
        if last in available_networks: return last # type: ignore
    except: pass
    return available_networks[0]

async def run_bot_instance(network_name: str, available_networks: list) -> Optional[str]:
    """Запуск одного экземпляра бота для конкретной сети."""
    global TUI_APP_INSTANCE
    network_settings = load_resource_bundle(network_name)
    app_config = Config(network_settings)
    app_config.CURRENT_VERSION = CURRENT_VERSION # type: ignore
    
    if getattr(sys, 'frozen', False):
        application_path = Path(sys.executable).parent.resolve() 
    else:
        application_path = Path(__file__).parent.parent.resolve()
    os.chdir(application_path)
    
    db_manager = DatabaseManager(
        db_path=app_config.DB_PATH,
        global_db_path="data/global.db"
    )
    await db_manager.connect()
    
    try:
        master_password = await secure_db_unlock(db_manager, network_name)
        if dexbot_core:
            try:
                dexbot_core.init_or_load_keys("data/bot_id.key", master_password) # type: ignore
                await log.info("🔐 dexbot_core инициализирован.")
            except Exception as e:
                await log.critical(f"Ошибка dexbot_core: {e}")
                sys.exit(1)
        
    except KeyboardInterrupt:
        try: await db_manager.close()
        except: pass 
        os._exit(0)
    except Exception as e:
        print(f"\nКритическая ошибка инициализации: {e}")
        await db_manager.close()
        sys.exit(1)

    await log.info(f"--- Запуск сети: {app_config.NAME} ---")
    
    cache = GlobalCache(db_manager)
    await cache.initialize()

    config_from_db = cache.get_config()
    if not config_from_db.get('rpc_url'):
        default_settings = {
            'rpc_url': app_config.RPC_URL,
            'default_quote_currency': app_config.DEFAULT_QUOTE_CURRENCY,
            'default_gas_price_gwei': app_config.DEFAULT_GAS_PRICE_GWEI,
            'slippage': 15.0,
            'default_trade_amount': '0.1',
            'max_workers': 3,
            'gas_limit': 500000,
            'max_fee_cents': 10
        }
        await cache.update_config(default_settings)
        config_from_db = cache.get_config()
    
    private_rpc_url = config_from_db.get('rpc_url', app_config.RPC_URL)
    public_rpc_urls = app_config.PUBLIC_RPC_URLS
    
    notification_queue = asyncio.Queue()
    bot_service = BotService(cache=cache, notification_queue=notification_queue, config=app_config)
    market_data_service = MarketDataService(cache=cache, config=app_config)
    
    market_data_service.bot_service = bot_service
    
    api_router = APIRouter()
    api_router.register_route('trading', TradingEndpoint(cache=cache, bot_service=bot_service).execute)
    api_router.register_route('wallets', WalletsEndpoint(cache=cache).execute)
    api_router.register_route('system', SystemEndpoint(cache=cache).execute)
    api_router.register_route('config', ConfigEndpoint(cache=cache).execute)
    
    if dexbot_core:
        all_wallets = cache.get_all_wallets()
        wallet_addresses = [w['address'] for w in all_wallets]
        try:
            dexbot_core.start_state_workers(private_rpc_url, public_rpc_urls, wallet_addresses, app_config.WSS_URL) # type: ignore
            await log.info(f"<green>---  CoreState с RPC Pool запущен ---</green>")
        except Exception as e:
            await log.error(f"Failed to start Rust workers: {e}")
    
    bot_service.start()
    market_data_service.start()

    TUI_APP_INSTANCE = TradingApp(
        api_router=api_router, 
        cache=cache, 
        notification_queue=notification_queue,
        bot_service=bot_service, 
        market_data_service=market_data_service, 
        current_network=network_name, 
        available_networks=available_networks
    )
    
    next_network = await TUI_APP_INSTANCE.run_async()
    TUI_APP_INSTANCE = None
    
    await log.info("Остановка сервисов...")
    await cache.dump_state_to_db()
    await save_last_network(db_manager, network_name)
    
    bot_service.stop()
    await market_data_service.stop()
    
    all_workers = bot_service.workers + market_data_service.workers
    if all_workers:
        try: await asyncio.wait_for(asyncio.gather(*all_workers, return_exceptions=True), timeout=2.0)
        except: pass
        
    await db_manager.close()
    return next_network

async def main_loop():
    try:
        available_networks = enumerate_adapters()
        if not available_networks: return
        temp_settings = load_resource_bundle(available_networks[0])
        temp_db = DatabaseManager(temp_settings['db_path'], "data/global.db")
        await temp_db.connect()
        current_network = await load_last_network(temp_db, available_networks)
        await temp_db.close()
        
        while current_network and not SHUTDOWN_REQUESTED:
            next_network = await run_bot_instance(current_network, available_networks)
            if next_network == "RESTART_SAME_NETWORK":
                await asyncio.sleep(1); continue
            current_network = next_network
    except Exception as e:
        import traceback
        traceback.print_exc()

def signal_handler(sig, frame):
    global SHUTDOWN_REQUESTED
    if SHUTDOWN_REQUESTED: force_restore_terminal(); os._exit(1)
    SHUTDOWN_REQUESTED = True
    if dexbot_core:
        try: dexbot_core.shutdown_rust_workers() # type: ignore
        except: pass
    if TUI_APP_INSTANCE:
        TUI_APP_INSTANCE.exit()

def run():
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    try:
        loop.run_until_complete(main_loop())
    except: pass
    finally:
        loop.close()
        force_restore_terminal()
        os._exit(0)

if __name__ == "__main__":
    run()