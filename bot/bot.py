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

from bot.services.market_data_service import MarketDataService
from utils.aiologger import log
from bot.cache import GlobalCache
from bot.core.db_manager import DatabaseManager
from tui.app import TradingApp
from bot.core.config import Config
from bot.core.integrities import load_resource_bundle, enumerate_adapters
from bot.core.bridge import BridgeManager, EngineCommand, AutoFuelSettings

console = Console()
SHUTDOWN_REQUESTED = False
USER_INITIATED_SHUTDOWN = False
TUI_APP_INSTANCE: Optional[TradingApp] = None
CURRENT_VERSION = "1.0.0"

def force_restore_terminal():
    if sys.platform != "win32":
        try: os.system("stty sane")
        except: pass
    try:
        if console and console.is_terminal:
            console.show_cursor(True)
    except: pass

async def secure_db_unlock(db_manager: DatabaseManager, network_name: str) -> str:
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
            pwd = Prompt.ask(f"Введите ваш пароль", password=True)
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
        if last in available_networks: 
            return last
    except: 
        pass
    return available_networks[0]

async def run_bot_instance(network_name: str, available_networks: list) -> Optional[str]:
    global TUI_APP_INSTANCE
    
    network_settings = load_resource_bundle(network_name)
    app_config = Config(network_settings)
    app_config.CURRENT_VERSION = CURRENT_VERSION 
    
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
    
    await save_last_network(db_manager, network_name)
    
    try:
        master_password = await secure_db_unlock(db_manager, network_name)
    except KeyboardInterrupt:
        await db_manager.close()
        os._exit(0)
    except Exception as e:
        print(f"\nКритическая ошибка авторизации: {e}")
        await db_manager.close()
        sys.exit(1)

    cache = GlobalCache(db_manager)
    await cache.initialize()
    
    notification_queue = asyncio.Queue()
    
    config_db = await cache.db.get_config()
    default_quote = config_db.get('default_quote_currency', 'WBNB')
    quote_address = app_config.QUOTE_TOKENS.get(default_quote, "")
    
    if not quote_address or default_quote == app_config.NATIVE_CURRENCY_SYMBOL:
        quote_address = app_config.QUOTE_TOKENS.get(f"W{app_config.NATIVE_CURRENCY_SYMBOL}", "")
    
    TUI_APP_INSTANCE = TradingApp(
        cache=cache, 
        notification_queue=notification_queue,
        current_network=network_name,
        available_networks=available_networks,
        app_config=app_config
    )
    
    TUI_APP_INSTANCE._current_quote_symbol = default_quote
    TUI_APP_INSTANCE._current_quote_address = quote_address

    bridge = BridgeManager(event_handler_callback=TUI_APP_INSTANCE.handle_rust_event)
    bridge.start() 
    TUI_APP_INSTANCE.bridge = bridge

    wallets_raw = await db_manager.get_all_wallets_raw()
    wallets_for_rust = []
    for w in wallets_raw:
        try:
            private_key = db_manager.security.decrypt(w['private_key'])
            wallets_for_rust.append((w['address'], private_key))
        except Exception:
            await log.error(f"Не удалось расшифровать ключ для {w['address']}")
            continue
    
    user_rpc = config_db.get('rpc_url')
    final_rpc = user_rpc if user_rpc else app_config.RPC_URL
    
    if user_rpc and user_rpc != app_config.RPC_URL:
        final_wss = user_rpc.replace("https://", "wss://").replace("http://", "ws://")
    else:
        final_wss = app_config.WSS_URL

    fuel = AutoFuelSettings(
        auto_fuel_enabled=config_db.get('auto_fuel_enabled', False),
        auto_fuel_threshold=config_db.get('auto_fuel_threshold', 0.005),
        auto_fuel_amount=config_db.get('auto_fuel_amount', 0.01),
        fuel_quote_address=quote_address
    )

    init_cmd = EngineCommand.init(
        rpc=final_rpc,
        wss=final_wss,
        chain_id=app_config.CHAIN_ID,
        router=app_config.DEX_ROUTER_ADDRESS,
        quoter=app_config.V3_QUOTER_ADDRESS,
        v2_factory=app_config.V2_FACTORY_ADDRESS,
        v3_factory=app_config.V3_FACTORY_ADDRESS,
        wrapped_native=app_config.QUOTE_TOKENS.get(f"W{app_config.NATIVE_CURRENCY_SYMBOL}", ""),
        native_address=app_config.NATIVE_CURRENCY_ADDRESS,
        wallets=wallets_for_rust,
        public_rpc_urls=app_config.PUBLIC_RPC_URLS,
        fuel=fuel,
        quote_symbol=default_quote,
        quote_tokens=app_config.QUOTE_TOKENS
    )
    bridge.send(init_cmd)
    
    bridge.send(EngineCommand.update_settings(
        gas_price_gwei=float(config_db.get('default_gas_price_gwei', 0.1)),
        slippage=float(config_db.get('slippage', 15.0)),
        fuel_enabled=fuel.auto_fuel_enabled
    ))

    await log.info(f"--- Ядро Rust инициализировано для сети: {app_config.NAME} ---")
    await log.info(f"--- Quote токен: {default_quote} ({quote_address[:10]}...) ---")

    market_data_service = MarketDataService(cache=cache, config=app_config)
    market_data_service.bridge = bridge
    market_data_service.start()

    bridge.send(EngineCommand.refresh_all_balances())

    next_network = await TUI_APP_INSTANCE.run_async()
    
    if next_network:
        await save_last_network(db_manager, next_network)

    await market_data_service.stop()
    bridge.stop()
    await db_manager.close()
    
    TUI_APP_INSTANCE = None
    
    # Отладка
    await log.info(f"DEBUG: next_network={next_network}, USER_INITIATED_SHUTDOWN={USER_INITIATED_SHUTDOWN}, current={network_name}")
    
    # ПОЛНЫЙ ПЕРЕЗАПУСК ТОЛЬКО при смене сети
    if next_network and not USER_INITIATED_SHUTDOWN and next_network != network_name:
        await log.info(f"Перезапуск для сети: {next_network}")
        await asyncio.sleep(1)
        os.execv(sys.executable, [sys.executable] + sys.argv)
    
    return next_network

async def main_loop():
    global USER_INITIATED_SHUTDOWN
    
    try:
        available_networks = enumerate_adapters()
        if not available_networks: return
        
        temp_settings = load_resource_bundle(available_networks[0])
        temp_db = DatabaseManager(temp_settings['db_path'], "data/global.db")
        await temp_db.connect()
        current_network = await load_last_network(temp_db, available_networks)
        await temp_db.close()
        
        while current_network and not SHUTDOWN_REQUESTED:
            next_net = await run_bot_instance(current_network, available_networks)
            
            if next_net is None: 
                break
            
            if USER_INITIATED_SHUTDOWN:
                await log.info("Пользователь инициировал завершение (Ctrl+C). Выход...")
                break
            
            if next_net and next_net in available_networks:
                current_network = next_net
            
            if SHUTDOWN_REQUESTED: break
            await asyncio.sleep(1)

    except Exception as e:
        import traceback
        traceback.print_exc()

def signal_handler(sig, frame):
    global SHUTDOWN_REQUESTED, USER_INITIATED_SHUTDOWN
    
    if SHUTDOWN_REQUESTED: 
        force_restore_terminal()
        os._exit(1)
    
    USER_INITIATED_SHUTDOWN = True
    SHUTDOWN_REQUESTED = True
    
    if dexbot_core:
        try: dexbot_core.shutdown_rust_workers()
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
    except Exception as e:
        asyncio.run(log.critical("Критическая ошибка запуска", exc_info=True))
    finally:
        loop.close()
        force_restore_terminal()
        os._exit(0)

if __name__ == "__main__":
    run()
