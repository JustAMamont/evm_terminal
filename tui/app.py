import asyncio
from typing import Optional, Dict, List, Any, Tuple
from collections import deque
import re
import pyperclip
import time

from web3 import Web3
from eth_account import Account

from textual.app import App, ComposeResult
from textual.containers import Container, Horizontal, Vertical, VerticalScroll
from textual.widgets import (
    Button, DataTable, Footer, Input, Label, RichLog,
    Static, TabbedContent, TabPane, Markdown, Select
)
from textual.binding import Binding
from textual.validation import Validator, ValidationResult, Regex, URL
from textual import on
from rich.text import Text
from rich.style import Style
from textual.message import Message

from utils.aiologger import log, LogLevel
from bot.cache import GlobalCache
from bot.core.bridge import BridgeManager, EngineCommand, AutoFuelSettings
from bot.core.config import Config
from tui.help import HELP_TEXT

try:
    import dexbot_core
    RUST_AVAILABLE = True
except ImportError:
    dexbot_core = None
    RUST_AVAILABLE = False


# ===================== ВАЛИДАТОРЫ =====================

class AmountValidator(Validator):
    def validate(self, value: str) -> ValidationResult:
        v = value.strip()
        if not v:
            return self.failure("Поле не может быть пустым.")
        if v.endswith('%'):
            try:
                n = float(v[:-1])
                if not (0 < n <= 100):
                    return self.failure("Процент должен быть от 0 до 100.")
            except ValueError:
                return self.failure("Неверный формат процента.")
        else:
            try:
                n = float(v)
                if n <= 0:
                    return self.failure("Сумма должна быть > 0.")
            except ValueError:
                return self.failure("Нужно число или процент.")
        return self.success()

class FloatValidator(Validator):
    def validate(self, value: str) -> ValidationResult:
        try:
            val = float(value)
            if val <= 0:
                return self.failure("Должно быть > 0")
        except ValueError:
            return self.failure("Нужно число")
        return self.success()

class IntegerValidator(Validator):
    def validate(self, value: str) -> ValidationResult:
        try:
            val = int(value)
            if val <= 0:
                return self.failure("Должно быть > 0")
        except ValueError:
            return self.failure("Нужно целое число")
        return self.success()

class AddressValidator(Regex):
    def __init__(self):
        super().__init__(r'^0x[a-fA-F0-9]{40}$', failure_description="Неверный формат адреса 0x...")

# ===================== TX STATUS TRACKER =====================

class TxStatusTracker:
    def __init__(self):
        self._pending_txs: Dict[str, Dict[str, Any]] = {}
        self._positions: Dict[str, List[Dict[str, Any]]] = {}
    
    def record_tx_sent(self, tx_hash: str, wallet: str, action: str, amount: float, token: str) -> float:
        send_time = time.time()
        self._pending_txs[tx_hash.lower()] = {
            'send_time': send_time,
            'wallet': wallet.lower(),
            'action': action.lower(),
            'amount': amount,
            'token': token.lower()
        }
        return send_time
    
    def confirm_tx(self, tx_hash: str, gas_used: int = 0, status: int = 1) -> Optional[Dict[str, Any]]:
        tx_hash_lower = tx_hash.lower()
        if tx_hash_lower not in self._pending_txs:
            return None
        
        tx_info = self._pending_txs.pop(tx_hash_lower)
        confirm_time = time.time()
        latency_ms = (confirm_time - tx_info['send_time']) * 1000
        
        result = {
            **tx_info,
            'latency_ms': latency_ms,
            'confirm_time': confirm_time,
            'gas_used': gas_used,
            'status': status 
        }
        
        if tx_info['action'] == 'buy' and status == 1:
            position_key = f"{tx_info['wallet']}:{tx_info['token']}"
            if position_key not in self._positions:
                self._positions[position_key] =[]
            self._positions[position_key].append({
                'amount': tx_info['amount'],
                'tx_hash': tx_hash,
                'timestamp': tx_info['send_time'],
                'latency_ms': latency_ms
            })
        
        return result
    
    def get_position(self, wallet: str, token: str) -> List[Dict[str, Any]]:
        position_key = f"{wallet.lower()}:{token.lower()}"
        return self._positions.get(position_key,[])
    
    def get_total_bought(self, wallet: str, token: str) -> float:
        positions = self.get_position(wallet, token)
        return sum(p['amount'] for p in positions)
    
    def clear_position(self, wallet: str, token: str):
        position_key = f"{wallet.lower()}:{token.lower()}"
        if position_key in self._positions:
            del self._positions[position_key]

# ===================== ЛОГ-ХЕНДЛЕР =====================

class LogMessage(Message):
    def __init__(self, rich_text: Text) -> None:
        self.rich_text = rich_text
        super().__init__()

class TextualRichLogHandler:
    def __init__(self, app: App, max_messages: int = 500):
        self._app = app
        self._message_buffer = deque(maxlen=max_messages)

    async def emit(self, dt_str: str, level: LogLevel, message: str, dt):
        level_style_map = {
            LogLevel.DEBUG: Style(color="cyan"), 
            LogLevel.INFO: Style(color="blue"),
            LogLevel.SUCCESS: Style(color="green"), 
            LogLevel.WARNING: Style(color="yellow"),
            LogLevel.ERROR: Style(color="red"), 
            LogLevel.CRITICAL: Style(bgcolor="red", color="white", bold=True),
        }
        prefix_style = level_style_map.get(level, Style(color="white"))
        rich_prefix = Text(f"{dt_str} -[{level.name}] - ", style=prefix_style)
        
        formatted_message = re.sub(r"<(\w+)>(.*?)</\1>", r"[\1]\2[/\1]", message)
        full_message_text = rich_prefix + Text.from_markup(formatted_message)
        
        self._message_buffer.append(full_message_text)
        self._app.post_message(LogMessage(full_message_text))

    def get_last_messages(self) -> list:
        return list(self._message_buffer)

# ===================== СТАТУС-БАР ВИДЖЕТЫ =====================

class StatusRPC(Static):
    def update_content(self, status: str, healthy: bool, latency_ms: int = 0):
        icon = "🟢" if healthy else "🔴"
        color = "green" if healthy else "red"
        if latency_ms > 0 and healthy:
            self.update(f"{icon} RPC: [bold {color}]{status}[/] ({latency_ms}ms)")
        else:
            self.update(f"{icon} RPC: [bold {color}]{status}[/]")

class StatusWallets(Static):
    def update_content(self, has_active: bool):
        icon = "✅" if has_active else "❌"
        color = "green" if has_active else "red"
        self.update(f"Wallets: [bold {color}]{icon}[/]")

class StatusGas(Static):
    def update_content(self, gas_gwei: float):
        color = "green" if gas_gwei < 3 else "yellow" if gas_gwei < 5 else "red"
        self.update(f"⛽ Gas: [bold {color}]{gas_gwei:.1f} Gwei[/]")

class StatusConnection(Static):
    def update_content(self, connected: bool, message: str = ""):
        icon = "🟢" if connected else "🔴"
        status = "WS: Connected" if connected else f"WS: {message[:15]}"
        color = "green" if connected else "red"
        self.update(f"{icon} [{color}]{status}[/]")

# ===================== ГЛАВНОЕ ПРИЛОЖЕНИЕ =====================

class TradingApp(App):
    """
    EVM Trader TUI Application - Реактивная версия с WebSocket
    Мгновенные обновления балансов, газ цены и состояния пулов
    + TX Status Tracking с latency measurement
    + DCA positioning + Sell 100% of bought tokens
    """

    CSS_PATH = "app.css"
    
    BINDINGS =[
        Binding("ctrl+q", "quit", "Выход", priority=True),
        Binding("ctrl+r", "reload_wallets", "Перезагрузить кошельки", priority=True),
        Binding("ctrl+s", "save_settings", "Сохранить", show=False, priority=True),
        Binding("delete", "clear_token_input", "Очистить токен", show=False, priority=True),
        Binding("t", "switch_tab('trade_tab')", "Торговля"),
        Binding("w", "switch_tab('wallets_tab')", "Кошельки"),
        Binding("s", "switch_tab('settings_tab')", "Настройки"),
        Binding("l", "switch_tab('logs_tab')", "Логи"),
        Binding("f", "switch_tab('help_tab')", "Помощь"),
        Binding("enter", "execute_trade", "Выполнить", show=False),
        Binding("shift+up", "change_slippage(0.5)", "Slippage +0.5%", show=False),
        Binding("shift+down", "change_slippage(-0.5)", "Slippage -0.5%", show=False),
        Binding("shift+right", "change_gas(0.1)", "Gas +0.1 Gwei", show=False),
        Binding("shift+left", "change_gas(-0.1)", "Gas -0.1 Gwei", show=False),
    ]

    def __init__(
        self, 
        cache: GlobalCache, 
        notification_queue: asyncio.Queue, 
        current_network: str, 
        available_networks: list, 
        app_config: Config, 
        **kwargs
    ):
        super().__init__()
        self.cache = cache
        self.notification_queue = notification_queue
        self.current_network = current_network
        self.available_networks = available_networks
        self.app_config = app_config
        self.bridge: Optional[BridgeManager] = None
        self.ui_update_queue = asyncio.Queue()
        self._rich_log_handler: Optional[TextualRichLogHandler] = None
        
        self._background_tasks: List[asyncio.Task] =[]
        self._tx_tracker = TxStatusTracker()
        
        self._active_trade_mode = "BUY"
        self.current_slippage = 15.0
        self.current_gas_price_gwei = 1.0
        self.current_max_fee_cents: int = 10
        self.is_pool_loading = False
        self.wallets_cache_ui: List[Dict] =[]
        
        self._current_pool_info: Dict[str, Any] = {}
        self._current_token_address: Optional[str] = None
        self._current_quote_address: Optional[str] = None
        
        self._market_data: Dict[str, Any] = self._get_empty_market_data()
        self._balance_cache: Dict[str, Dict[str, float]] = {}
        
        self._token_debounce_task: Optional[asyncio.Task] = None
        self._amount_debounce_task: Optional[asyncio.Task] = None
        self._last_calc_msg: str = ""
        self.status_update_task: Optional[asyncio.Task] = None
        self._native_balance_loaded = False

        # Dispatcher для событий из Rust ядра
        self._rust_event_handlers = {
            "EngineReady": self._evt_engine_ready,
            "ConnectionStatus": self._evt_connection_status,
            "RPCError": self._evt_rpc_error,
            "RPCStatus": self._evt_rpc_status,
            "GasPriceUpdate": self._evt_gas_price,
            "BalanceUpdate": self._evt_balance_update,
            "PoolDetected": self._evt_pool_detected,
            "PoolError": self._evt_pool_error,
            "PoolUpdate": self._evt_pool_update,
            "PoolNotFound": self._evt_pool_not_found,
            "ImpactUpdate": self._evt_impact_update,
            "TxSent": self._evt_tx_sent,
            "TxConfirmed": self._evt_tx_confirmed,
            "TradeStatus": self._handle_trade_status,
            "AutoFuelError": self._evt_autofuel_error,
            "Log": self._evt_log
        }

    # ===================== ЛОГИКА ЖИЗНЕННОГО ЦИКЛА =====================

    def on_mount(self) -> None:
        self._rich_log_handler = TextualRichLogHandler(self)
        asyncio.create_task(log.set_custom_handler(self._rich_log_handler.emit))
        
        self._init_ui_defaults()
        
        self.wallets_cache_ui = self.cache.get_all_wallets(enabled_only=False)
        
        self._background_tasks =[
            asyncio.create_task(self.ui_updater_worker()),
            asyncio.create_task(self._rust_event_listener()),
            asyncio.create_task(self.status_update_loop()),
            asyncio.create_task(self._notification_watcher()),
        ]
        
        self.notify("🚀 Интерфейс загружен", severity="information", title="TUI")
        self.ui_update_queue.put_nowait("wallets")
        self._init_market_data_table()

    def on_unmount(self) -> None:
        for task in self._background_tasks:
            task.cancel()
        self._background_tasks.clear()
        
        if self._token_debounce_task:
            self._token_debounce_task.cancel()
        if self._amount_debounce_task:
            self._amount_debounce_task.cancel()

    # ===================== ВСПОМОГАТЕЛЬНЫЕ МЕТОДЫ =====================

    def _get_empty_market_data(self) -> Dict[str, Any]:
        return {
            'pool_type': '-',
            'pool_address': '-',
            'tvl_usd': 0.0,
            'fee_bps': 0,
            'impact_buy': 0.0,
            'impact_sell': 0.0,
            'current_price': 0.0,
            'pos_cost_quote': 0.0,
            'pos_amount': 0.0,
            'reserves': (0, 0),
            'token_symbol': 'TOKEN'
        }

    def _get_quote_info(self) -> Tuple[str, str]:
        """Возвращает (символ котируемой валюты, адрес котируемой валюты)"""
        config = self.cache.get_config()
        quote_symbol = config.get('default_quote_currency', self.app_config.DEFAULT_QUOTE_CURRENCY)
        quote_address = self.app_config.QUOTE_TOKENS.get(quote_symbol, "")
        return quote_symbol, quote_address

    def _short_wallet(self, wallet: str) -> str:
        """Сокращает адрес кошелька для отображения в логах"""
        if not wallet: return ""
        return f"{wallet[:6]}...{wallet[-4:]}" if len(wallet) > 10 else wallet

    def _update_status_widget(self, widget_class, *args, **kwargs):
        """Безопасное обновление виджетов статуса без дублирования try-except"""
        try:
            self.query_one(widget_class).update_content(*args, **kwargs)
        except Exception:
            pass

    def _trigger_wallets_refresh(self):
        """Обновляет кэш кошельков и запрашивает перерисовку таблицы"""
        self.wallets_cache_ui = self.cache.get_all_wallets(enabled_only=False)
        self.ui_update_queue.put_nowait("wallets")

    def _init_ui_defaults(self):
        try:
            quote_tokens = list(self.app_config.QUOTE_TOKENS.keys())
            quote_select = self.query_one("#trade_quote_select", Select)
            quote_select.set_options([(token, token) for token in sorted(quote_tokens)])
            
            config = self.cache.get_config()
            default_quote = config.get('default_quote_currency', self.app_config.DEFAULT_QUOTE_CURRENCY)
            if default_quote in quote_tokens:
                quote_select.value = default_quote
                
            default_amount = config.get('default_trade_amount', '0.01')
            amount_input = self.query_one("#amount_input", Input)
            amount_input.value = str(default_amount)
        except Exception:
            pass

    def _init_market_data_table(self):
        try:
            table = self.query_one("#market_data_table", DataTable)
            table.clear()
            if not table.columns:
                table.add_columns("Пара", "Пул", "TVL", "Цена", "Impact BUY", "Impact SELL", "PnL")
        except Exception:
            pass

    def _is_event_for_current_pair(self, event_token: str, event_quote: Optional[str] = None) -> bool:
        """Проверяет что событие относится к текущей паре token/quote"""
        if not self._current_token_address:
            return False
        if event_token and event_token != self._current_token_address.lower():
            return False
        if event_quote and self._current_quote_address:
            if event_quote.lower() != self._current_quote_address.lower():
                return False
        return True

    # ===================== СОБЫТИЯ ВЗАИМОДЕЙСТВИЯ (KEYS & CLICKS) =====================

    def on_log_message(self, event: LogMessage) -> None:
        try:
            self.query_one("#log_output", RichLog).write(event.rich_text)
        except Exception:
            pass

    async def on_key(self, event) -> None:
        if event.key not in ("up", "down"):
            return
        try:
            if self.query_one(TabbedContent).active != "trade_tab":
                return
        except Exception:
            return
        
        focused = self.focused
        if focused and type(focused).__name__ in ("Input", "Select", "TextArea", "TextAreaInput"):
            return
        
        event.stop()
        new_mode = "BUY" if event.key == "up" else "SELL"
        
        if self._active_trade_mode != new_mode:
            self._active_trade_mode = new_mode
            mode_ru = "Покупка" if new_mode == "BUY" else "Продажа"
            self.notify(f"Режим: {mode_ru}", timeout=1)
            self._update_panel_visuals()
            await self._trigger_impact_calc()

    @on(Select.Changed, "#network_select")
    def on_network_change(self, event: Select.Changed):
        new_net = str(event.value)
        if new_net != self.current_network:
            self.notify(f"Переключение на сеть {new_net.upper()}...", timeout=2)
            self.exit(new_net)

    @on(TabbedContent.TabActivated, "#main_tabs")
    async def on_tab_activated(self, event: TabbedContent.TabActivated):
        if event.pane.id == "logs_tab" and self._rich_log_handler:
            log_output = self.query_one("#log_output", RichLog)
            log_output.clear()
            for msg in self._rich_log_handler.get_last_messages():
                log_output.write(msg)
        elif event.pane.id in ("wallets_tab", "trade_tab"):
            self._trigger_wallets_refresh()
        elif event.pane.id == "settings_tab":
            await self._load_and_apply_settings()

    # ===================== RUST EVENT HANDLERS (DISPATCHER) =====================

    async def handle_rust_event(self, event: dict):
        etype = event.get("type")
        data = event.get("data", {})
        
        handler = self._rust_event_handlers.get(etype)
        if handler:
            await handler(data)

    async def _evt_engine_ready(self, data: dict):
        await log.success("<green>[ENGINE]</green> Rust ядро готово к работе")
        self.notify("⚡ Ядро Rust готово", severity="information", title="System")
        self.ui_update_queue.put_nowait("refresh_all")
        if self.bridge: 
            await self.bridge.send(EngineCommand.refresh_all_balances())
            
            # Обновляем балансы токенов из открытых позиций (один раз при старте)
            open_positions = self.cache.get_open_positions_tokens()
            if open_positions:
                await log.info(f"🔄 Обновление балансов для {len(open_positions)} открытых позиций...")
                for wallet, token in open_positions:
                    await self.bridge.send(EngineCommand.refresh_balance(wallet, token))
            
        self._update_status_widget(StatusRPC, "OK", True)

    async def _evt_connection_status(self, data: dict):
        connected = data.get("connected", False)
        message = data.get("message", "")
        self._update_status_widget(StatusConnection, connected, message)
        self._update_status_widget(StatusRPC, "OK" if connected else "ERROR", connected)
        
        if connected: 
            await log.success(f"<green>[WS]</green> WebSocket подключен: {message}")
            self.notify("🔌 WebSocket подключен", severity="information")
        else: 
            await log.error(f"<red>[WS]</red> WebSocket отключен: {message}")
            self.notify(f"🔴 WS отключен: {message[:30]}", severity="error")

    async def _evt_rpc_error(self, data: dict):
        rpc_url = data.get("rpc_url", "unknown")
        error_msg = data.get("error", "Unknown error")
        is_critical = data.get("critical", False)
        
        await log.error(f"<red>[RPC ERROR]</red> {rpc_url[:30]}... | {error_msg}")
        if is_critical: 
            self.notify(f"🚨 КРИТИЧЕСКАЯ ОШИБКА RPC: {error_msg[:50]}", severity="error", timeout=10)
            self._update_status_widget(StatusRPC, "ERROR", False)
        else: 
            self.notify(f"⚠️ RPC Error: {error_msg[:40]}", severity="warning", timeout=4)

    async def _evt_rpc_status(self, data: dict):
        healthy = data.get("healthy", False)
        latency_ms = data.get("latency_ms", 0)
        self._update_status_widget(StatusRPC, "OK" if healthy else "ERROR", healthy, latency_ms)

    async def _evt_gas_price(self, data: dict):
        self.current_gas_price_gwei = data.get("gas_price_gwei", 1.0)
        self._update_status_widget(StatusGas, self.current_gas_price_gwei)

    async def _evt_balance_update(self, data: dict):
        wallet = data.get('wallet', '').lower()
        token = data.get('token', '').lower()
        wei = data.get('wei', '0')
        float_val = data.get('float_val', 0.0)

        if wallet not in self._balance_cache: 
            self._balance_cache[wallet] = {}

        self._balance_cache[wallet][token] = float_val
        self.cache.set_exact_balance_wei(wallet, token, int(wei) if str(wei).isdigit() else 0)
        self.cache.set_wallet_balance(wallet, token, float_val)

        if token == self.app_config.NATIVE_CURRENCY_ADDRESS.lower(): 
            self._native_balance_loaded = True

        self.ui_update_queue.put_nowait("refresh_balances")

    async def _evt_pool_detected(self, data: dict):
        event_token = data.get('token', '').lower()
        event_quote = data.get('quote', '').lower()
        if not self._is_event_for_current_pair(event_token, event_quote):
            return

        self._update_pool_cache(data)
        self.is_pool_loading = False
        self._update_trade_buttons_state()
        await self._trigger_impact_calc()
        
        token_symbol = data.get('token_symbol')
        if token_symbol:
            self._market_data['token_symbol'] = token_symbol
            if self._current_token_address:
                # КЭШИРУЕМ В ПАМЯТЬ - мгновенный доступ
                self.cache.set_token_metadata_cache(
                    self._current_token_address,
                    symbol=token_symbol,
                    name=data.get('token_name')
                )
                # БД запрос в фоне, не блокирует
                asyncio.create_task(
                    self.cache.db.add_or_update_recent_token(
                        self._current_token_address,
                        name=data.get('token_name'),
                        symbol=token_symbol
                    )
                )
        
        await self._update_token_pair_display()
        await log.success(f"<green>[POOL]</green> {data.get('pool_type')} found: {data.get('address', '')[:10]}... TVL=${data.get('liquidity_usd', 0):,.0f}")
        self.notify(f"🏊 Пул: {data.get('pool_type')} TVL ${data.get('liquidity_usd', 0):,.0f}", severity="information", timeout=4)
        
    async def _evt_pool_error(self, data: dict):
        await log.error(f"[POOL_ERROR] FULL DATA: {data}")
        event_token = data.get('token', '').lower()
        event_quote = data.get('quote', '').lower()
        if not self._is_event_for_current_pair(event_token, event_quote):
            return
        
        await log.error(f"<red>[POOL ERROR]</red> {data.get('error')}")
        self.notify(f"❌ Пул не найден", severity="warning", timeout=4)
        self.is_pool_loading = False
        self._update_trade_buttons_state()

    async def _evt_pool_update(self, data: dict):
        event_token = data.get('token', '').lower()
        event_quote = data.get('quote', '').lower()
        if not self._is_event_for_current_pair(event_token, event_quote):
            return
                
        self._current_pool_info['pool_type'] = data.get('pool_type', '')
        self._current_pool_info['address'] = data.get('pool_address', '')

        if data.get('spot_price') is not None:
            self._market_data['current_price'] = float(data.get('spot_price'))

        if data.get('liquidity_usd') is not None:
            self._market_data['tvl_usd'] = float(data.get('liquidity_usd', 0))

        if data.get('reserve0') and data.get('reserve1'):
            try: 
                self._market_data['reserves'] = (int(data.get('reserve0', '0')), int(data.get('reserve1', '0')))
            except Exception: pass
        
        if self._current_token_address and not self.is_pool_loading:
            await self._trigger_impact_calc()
        self.ui_update_queue.put_nowait("refresh_market_data")

    async def _evt_pool_not_found(self, data: dict):
        await log.error(f"[POOL_NOT_FOUND] FULL DATA: {data}")
        event_token = data.get('token', '').lower()
        event_quote = data.get('quote', '').lower()
        if not self._is_event_for_current_pair(event_token, event_quote):
            return
        
        selected = data.get("selected_quote", "")
        available = data.get("available_quotes", [])

        try:
            metadata_display = self.query_one("#token_metadata_display", Static)
            
            if not available:
                metadata_display.update("[bold red]❌ No Pools[/]")
                self.notify("❌ Пулы не найдены", severity="error", timeout=10)
            else:
                symbols = [q[0] for q in available]
                metadata_display.update(f"[bold yellow]💡 Try: {', '.join(symbols)}[/]")
                self.notify(f"⚠️ Нет пулов для {selected}. Попробуйте: {', '.join(symbols)}", severity="warning", timeout=10)
            
            self.is_pool_loading = False
            self._update_trade_buttons_state()
        except Exception:
            # Виджет не найден - игнорируем
            self.is_pool_loading = False
            self._update_trade_buttons_state()

    async def _evt_impact_update(self, data: dict):
        event_token = data.get('token', '').lower()
        event_quote = data.get('quote', '').lower()
        if not self._is_event_for_current_pair(event_token, event_quote):
            return
        
        is_buy = data.get('is_buy', True)
        impact_pct = data.get('impact_pct', 0.0)

        if is_buy: 
            self._market_data['impact_buy'] = impact_pct
        else: 
            self._market_data['impact_sell'] = impact_pct

        self.ui_update_queue.put_nowait("refresh_market_data")

    async def _evt_tx_sent(self, data: dict):
        """Обрабатывает событие отправки транзакции"""
        tx_hash = data.get('tx_hash', '')
        wallet = data.get('wallet', '')
        action = data.get('action', '')
        amount = data.get('amount', 0)
        token = data.get('token', '')
        
        # === DEBUG: Что пришло из Rust ===
        #await log.debug(f"[TX_SENT] INCOMING | tx_hash={tx_hash[:16] if tx_hash else 'None'}... | action='{action}' | wallet={wallet[:10] if wallet else 'None'}... | token={token[:10] if token else 'None'}... | amount={amount}")
        
        # Записываем в трекер
        self._tx_tracker.record_tx_sent(tx_hash, wallet, action, amount, token)
        
        # === DEBUG: Проверяем что записалось ===
        #tx_hash_lower = tx_hash.lower() if tx_hash else ''
        #if tx_hash_lower in self._tx_tracker._pending_txs:
            #stored = self._tx_tracker._pending_txs[tx_hash_lower]
        #    await log.debug(f"[TX_SENT] STORED OK | action='{stored.get('action')}' | wallet='{stored.get('wallet', '')[:10]}...' | token='{stored.get('token', '')[:10]}...'")
        #else:
        #    await log.debug(f"[TX_SENT] STORE FAILED! tx_hash_lower={tx_hash_lower[:16]}...")
        
        short_wallet = self._short_wallet(wallet) if wallet else "???"
        await log.info(f"<cyan>[TX SENT]</cyan> {action.upper()} {short_wallet} Hash: {tx_hash[:16]}...")


    async def _evt_tx_confirmed(self, data: dict):
        """Обрабатывает событие подтверждения транзакции"""
        tx_hash = data.get('tx_hash', '')
        status_raw = data.get('status', '')
        gas_used = data.get('gas_used', 0)
        
        # Нормализуем status
        status = status_raw.lower() if isinstance(status_raw, str) else str(status_raw)
        
        # === DEBUG: Что пришло ===
        #await log.debug(f"[TX_CONFIRMED] INCOMING | tx_hash={tx_hash[:16] if tx_hash else 'None'}... | status_raw='{status_raw}' | status_normalized='{status}' | gas_used={gas_used}")
        
        # Ищем в трекере
        tx_result = self._tx_tracker.confirm_tx(tx_hash, gas_used, 1 if status == 'success' else 0)
        
        # === DEBUG: Результат поиска в трекере ===
        #if tx_result:
        #    await log.debug(f"[TX_CONFIRMED] FOUND IN TRACKER | keys={list(tx_result.keys())}")
        #else:
        #    await log.debug(f"[TX_CONFIRMED] NOT IN TRACKER! tx_hash={tx_hash[:16] if tx_hash else 'None'}... | Checking all pending: {list(self._tx_tracker._pending_txs.keys())[:3]}...")
        
        if tx_result:
            latency_ms = tx_result.get('latency_ms', 0)
            action = tx_result.get('action', '')
            wallet = tx_result.get('wallet', '')
            token = tx_result.get('token', '')
            amount = tx_result.get('amount', 0)
            
            # === DEBUG: Извлечённые значения ===
            #await log.debug(f"[TX_CONFIRMED] EXTRACTED | action='{action}' | wallet='{wallet[:10] if wallet else 'EMPTY'}' | token='{token[:10] if token else 'EMPTY'}' | amount={amount}")
            
            action_ru = "Покупка" if action == "buy" else "Продажа" if action == "sell" else f"???({action})"
            action_emoji = "🟢" if action == "buy" else "🔴" if action == "sell" else "❓"
            #short_wallet = self._short_wallet(wallet) if wallet else "???"
            
            if status == "success":
                await log.success(f"<green>[TX CONFIRMED]</green> {action_ru} | Latency: {latency_ms:.0f}ms")
                self.notify(f"{action_emoji} {action_ru} успешна!\nLatency: {latency_ms:.0f}ms", severity="information", title=f"{action_ru}")
                
                # === DEBUG: Проверка условия закрытия позиции ===
                #cond_action = action == "sell"
                #cond_wallet = bool(wallet)
                #cond_token = bool(token)
                #await log.debug(f"[TX_CONFIRMED] CLOSE CONDITION | action=='sell': {cond_action} | wallet: {cond_wallet} | token: {cond_token} | ALL: {cond_action and cond_wallet and cond_token}")
                
                if action == "sell" and wallet and token:
                    # Позиция ДО закрытия
                    #pos_before = self.cache.get_position_memory(wallet, token)
                    #await log.debug(f"[BEFORE CLOSE] wallet={short_wallet} | token={token[:10]}... | cost={pos_before.get('cost', 0)} | amount={pos_before.get('amount', 0)}")
                    
                    # Закрываем
                    self.cache.close_position_memory(wallet, token)
                    
                    # Позиция ПОСЛЕ закрытия
                    #pos_after = self.cache.get_position_memory(wallet, token)
                    #await log.debug(f"[AFTER CLOSE] wallet={short_wallet} | token={token[:10]}... | cost={pos_after.get('cost', 0)} | amount={pos_after.get('amount', 0)}")
                    
                    # Сбрасываем impact
                    self._market_data['impact_sell'] = 0.0
                    self.ui_update_queue.put_nowait("refresh_market_data")
                #else:
                #    await log.debug(f"[TX_CONFIRMED] NOT CLOSING POSITION | reason: action='{action}' (need 'sell'), wallet={'SET' if wallet else 'EMPTY'}, token={'SET' if token else 'EMPTY'}")
            else:
                await log.error(f"<red>[TX FAILED]</red> {action_ru} | Latency: {latency_ms:.0f}ms")
                self.notify(f"❌ {action_ru} ошибка!\nLatency: {latency_ms:.0f}ms", severity="error", title=f"{action_ru}")
        else:
            # Транзакция не найдена в трекере - возможно перезапуск или пропущенный TxSent
            await log.warning(f"<yellow>[TX_CONFIRMED]</yellow> tx_hash={tx_hash[:16] if tx_hash else 'None'}... NOT FOUND in tracker (restart or missed TxSent?)")

    async def _evt_autofuel_error(self, data: dict):
        reason = data.get("reason", "unknown_error")
        self.notify(f"⛽ Ошибка автозакупки газа: {reason}", severity="error", timeout=20)

    async def _evt_log(self, data: dict):
        level = data.get('level', 'INFO')
        msg = data.get('message', '')

        if level == "ERROR": 
            await log.error(msg)
        elif level == "WARN": 
            await log.warning(msg)
        elif level == "DEBUG": 
            await log.debug(msg)
        else: 
            await log.info(msg)

    async def _handle_trade_status(self, data: dict):
        """Обрабатывает статус торговли из Rust ядра"""
        wallet = data.get('wallet', '')
        status = data.get('status', '').lower()
        action = data.get('action', '').lower()
        tx_hash = data.get('tx_hash', '')
        message = data.get('message', '')
        
        # Берём ПОЛНЫЙ token_address, а не обрезанный token
        token_address = data.get('token_address', '')
        #token_display = token_address[:10] if token_address else '???'
        
        amount = data.get('amount', 0)
        #gas_price = data.get('gas_price_gwei', 0)
        gas_used = data.get('gas_used', 0)
        
        tokens_received = data.get('tokens_received')
        tokens_sold = data.get('tokens_sold')
        token_decimals = data.get('token_decimals', 18)
        
        action_ru = "Покупка" if action == "buy" else "Продажа"
        action_emoji = "🟢" if action == "buy" else "🔴"
        short_wallet = self._short_wallet(wallet) if wallet else "???"
        explorer_url = f"{self.app_config.EXPLORER_URL}tx/{tx_hash}" if tx_hash else ""
        
        #await log.debug(f"[TRADE_STATUS] status={status} | action={action} | wallet={short_wallet} | token={token_display}...")
        
        if status == "sent":
            #await log.debug(f"[TRADE SENT] action={action} | amount={amount} | tokens_received={tokens_received} | tokens_sold={tokens_sold}")
            
            if token_address and wallet:
                await self._update_position_memory_on_send(
                    action, wallet, token_address, amount, 
                    tokens_received, tokens_sold, token_decimals
                )
            self.ui_update_queue.put_nowait("refresh_balances")
            
        elif status == "success":
            tx_result = self._tx_tracker.confirm_tx(tx_hash, gas_used, 1)
            latency_ms = tx_result.get('latency_ms', 0) if tx_result else 0
            
            await log.success(f"<green>[TX SUCCESS]</green> {action_ru} {short_wallet} | Latency: {latency_ms:.0f}ms | {explorer_url}")
            self.notify(f"{action_emoji} {action_ru} успешна!\nLatency: {latency_ms:.0f}ms", severity="information", title=f"{action_ru}", timeout=4)
            
            if action == "sell" and token_address and wallet:
                #pos_before = self.cache.get_position_memory(wallet, token_address)
                #await log.debug(f"[BEFORE CLOSE] {short_wallet} | cost={pos_before['cost']}, amount={pos_before['amount']}")
                
                self.cache.close_position_memory(wallet, token_address)
                
                #pos_after = self.cache.get_position_memory(wallet, token_address)
                #await log.debug(f"[AFTER CLOSE] {short_wallet} | cost={pos_after['cost']}, amount={pos_after['amount']}")
                
                self._market_data['impact_sell'] = 0.0
                self.ui_update_queue.put_nowait("refresh_market_data")
                
        elif status in ("failed", "error"):
            tx_result = self._tx_tracker.confirm_tx(tx_hash, gas_used, 0)
            latency_ms = tx_result.get('latency_ms', 0) if tx_result else 0
            
            # Проверка на недостаток газа/средств
            error_message = message if message else 'Unknown error'
            native_symbol = self.app_config.NATIVE_CURRENCY_SYMBOL
            
            if "insufficient funds" in error_message.lower() or "gas required exceeds" in error_message.lower():
                error_message = f"Недостаточно {native_symbol} для оплаты газа"
                await log.error(f"<red>[TX ERROR]</red> {action_ru} {short_wallet} | {error_message}")
            else:
                await log.error(f"<red>[TX FAILED]</red> {action_ru} {short_wallet} | Latency: {latency_ms:.0f}ms | Reason: {error_message}")
            
            self.notify(f"❌ {action_ru} ошибка!\n{error_message[:80] if error_message else 'Unknown error'}", severity="error", title=f"{action_ru}", timeout=8)
            
            # Откат баланса при ошибке продажи
            if action == "sell" and token_address and wallet and tokens_sold:
                try:
                    sold_wei = int(tokens_sold)
                    if sold_wei > 0:
                        self.cache.add_token_balance(wallet, token_address, sold_wei, decimals=token_decimals, save_to_db=True)
                except (ValueError, TypeError):
                    pass


    async def _update_position_memory_on_send(self, action: str, wallet: str, token_address: str, amount: float, tokens_received, tokens_sold, token_decimals: int):
        """Обновление позиции при отправке транзакции"""
        short_wallet = self._short_wallet(wallet)
        
        if action == "buy":
            try:
                _, quote_address = self._get_quote_info()
                quote_decimals = self.cache.get_token_decimals(quote_address) or 18
                cost_wei = int(float(amount) * (10**quote_decimals))
                
                #await log.debug(f"[BUY] cost_wei={cost_wei} | quote_decimals={quote_decimals} | amount={amount}")
                
                self.cache.update_position_memory(wallet, token_address, cost_wei, 0)
                
                if tokens_received:
                    received_wei = int(tokens_received)
                    if received_wei > 0:
                        self.cache.add_token_balance(wallet, token_address, received_wei, decimals=token_decimals, save_to_db=True)
                        self.cache.update_position_memory(wallet, token_address, 0, received_wei)
                        await log.success(f"<green>[BALANCE]</green> +{received_wei} tokens -> {short_wallet}")
            except Exception as e:
                await log.error(f"[PnL Error] {e}")
                    
        elif action == "sell" and tokens_sold:
            try:
                sold_wei = int(tokens_sold)
                if sold_wei > 0:
                    self.cache.subtract_token_balance(wallet, token_address, sold_wei, decimals=token_decimals, save_to_db=True)
                    await log.success(f"<green>[BALANCE]</green> -{sold_wei} tokens -> {short_wallet}")
            except Exception:
                pass

    def _update_pool_cache(self, data: dict):
        self._current_pool_info = {
            "pool_type": data.get('pool_type', '?'),
            "address": data.get('address', ''),
            "fee": data.get('fee', 0),
            "liquidity_usd": float(data.get('liquidity_usd', 0)),
            "token": data.get('token', '')
        }
        self._update_market_data_from_pool(data)
        self.ui_update_queue.put_nowait("refresh_market_data")
    
    def _update_market_data_from_pool(self, data: dict):
        self._market_data['pool_type'] = data.get('pool_type', '-')
        self._market_data['pool_address'] = data.get('address', '-')[:10] + '...'
        self._market_data['tvl_usd'] = data.get('liquidity_usd', 0)
        self._market_data['fee_bps'] = data.get('fee', 0)

        if data.get('spot_price'):
             self._market_data['current_price'] = float(data.get('spot_price'))

    # ===================== ФОНОВЫЕ ЦИКЛЫ =====================

    async def ui_updater_worker(self):
        while True:
            try:
                update_type = await self.ui_update_queue.get()
                
                if update_type == "refresh_balances": 
                    await self._refresh_wallet_table()
                elif update_type == "refresh_all": 
                    await self._load_and_apply_settings()
                    await self._refresh_wallet_table()
                elif update_type == "refresh_market_data": 
                    self._update_market_data_table()
                elif update_type == "wallets": 
                    await self._refresh_wallet_table()
                
                self._update_trade_buttons_state()
                self._update_status_widget(StatusWallets, any(w.get('enabled') for w in self.wallets_cache_ui))

                self.ui_update_queue.task_done()
            except asyncio.CancelledError: 
                break
            except Exception: 
                pass

    async def _rust_event_listener(self):
        while True:
            try:
                if not self.bridge or not self.bridge._is_running:
                    await asyncio.sleep(0.5)
                    continue
                
                try:
                    event = await asyncio.wait_for(self.bridge._event_queue.get(), timeout=5.0)
                except asyncio.TimeoutError:
                    continue 
                    
                asyncio.create_task(self.handle_rust_event(event))
            except asyncio.CancelledError: 
                break
            except Exception: 
                await asyncio.sleep(0.1)

    async def status_update_loop(self):
        counter = 0
        while True:
            try:
                if counter % 10 == 0: 
                    self._update_status_widget(StatusRPC, "OK", True)

                new_wallets_data = self.cache.get_all_wallets(enabled_only=False)
                if new_wallets_data != self.wallets_cache_ui:
                    self._trigger_wallets_refresh()

                active_token = self.cache.get_active_trade_token()
                
                try:
                    metadata_display = self.query_one("#token_metadata_display", Static)
                    
                    if active_token:
                        await self._calculate_total_position(active_token)
                        self.ui_update_queue.put_nowait("refresh_market_data")
                        
                        token_symbol = "TOKEN"
                        try:
                            # ИЗ КЭША - мгновенно, без БД
                            meta = self.cache.get_token_metadata_cached(active_token)
                            if meta and meta.get('symbol'): 
                                token_symbol = meta['symbol']
                        except Exception: 
                            pass
                        
                        pool_status = self._get_pool_status_display(active_token)
                        metadata_display.update(f"Token Info:[bold cyan]{token_symbol}[/] {pool_status}")
                    else:
                        metadata_display.update("Token Info: [dim]None[/]")
                except Exception:
                    # Виджет не на текущем экране - игнорируем
                    pass

                self._update_trade_buttons_state()
                counter += 1
            except Exception as e:
                await log.error(f"UI Loop Error: {e}")
            await asyncio.sleep(1.0)

    async def _calculate_total_position(self, active_token: str):
        _, quote_address = self._get_quote_info()
        total_cost = 0.0
        total_amount = 0.0
        q_dec = self.cache.get_token_decimals(quote_address) or 18
        t_dec = self.cache.get_token_decimals(active_token) or 18

        for w in self.wallets_cache_ui:
            if w.get('enabled'):
                try:
                    pos = self.cache.get_position_memory(w['address'], active_token)
                    total_cost += pos['cost'] / (10**q_dec)
                    
                    bal_wei = self.cache.get_exact_balance_wei(w['address'], active_token) or 0
                    total_amount += bal_wei / (10**t_dec)
                except Exception: pass
        
        self._market_data['pos_cost_quote'] = total_cost
        self._market_data['pos_amount'] = total_amount

    def _get_pool_status_display(self, active_token: str) -> str:
        _, quote_address = self._get_quote_info()
        
        if self._current_pool_info.get('pool_type'):
            self.is_pool_loading = False
            return f"[bold green]({self._current_pool_info.get('pool_type', '?')})[/]"
            
        pool_info = self.cache.get_best_pool(active_token, quote_address)
        if pool_info:
            self.is_pool_loading = False
            if "error" in pool_info: 
                return "[bold red](No Pool)[/]"
            else: 
                return f"[bold green]({pool_info.get('type', '?')})[/]"
        else:
            self.is_pool_loading = True
            return "[yellow](Searching...)[/]"

    # ===================== UI CALLBACKS (ON) =====================

    async def _update_token_pair_display(self):
        try:
            metadata_display = self.query_one("#token_metadata_display", Static)
            if not self._current_token_address:
                metadata_display.update("Token Info: [dim]None[/]")
                return
            
            token_symbol = self._market_data.get('token_symbol', 'TOKEN')
            if token_symbol == 'TOKEN':
                # ИЗ КЭША - мгновенно, без БД
                meta = self.cache.get_token_metadata_cached(self._current_token_address)
                if meta and meta.get('symbol'):
                    token_symbol = meta['symbol']
                    self._market_data['token_symbol'] = token_symbol
            
            quote_symbol, _ = self._get_quote_info()
            pool_type = self._current_pool_info.get('pool_type', '')
            
            if pool_type:
                metadata_display.update(f"[bold cyan]{token_symbol}/{quote_symbol}[/][dim]({pool_type})[/]")
            else:
                metadata_display.update(f"[bold cyan]{token_symbol}/{quote_symbol}[/] [yellow](Searching...)[/]")
        except Exception:
            pass

    def _update_trade_buttons_state(self):
        try:
            buy_btn = self.query_one("#buy_button")
            sell_btn = self.query_one("#sell_button")
            has_active = any(w.get('enabled') for w in self.wallets_cache_ui)
            is_ready = not self.is_pool_loading and has_active
            buy_btn.disabled = not is_ready
            sell_btn.disabled = not is_ready
        except Exception: pass

    @on(Input.Changed, "#token_input")
    async def on_token_input_changed(self, event: Input.Changed):
        token_address = event.value.strip()

        try: 
            self.query_one("#better_pool_suggestion").display = False
        except Exception: pass

        if self._token_debounce_task: 
            self._token_debounce_task.cancel()
            self._token_debounce_task = None

        self.query_one("#token_metadata_display", Static).update("Token Info: [dim]...[/]")

        if Web3.is_address(token_address):
            self._current_token_address = token_address.lower()
            self._current_pool_info = {} 
            self.is_pool_loading = True
            self._update_trade_buttons_state()
            self._token_debounce_task = asyncio.create_task(self._debounced_switch_token(token_address))
        else:
            await self._clear_token_state()

    async def _clear_token_state(self):
        try:
            token_to_unsubscribe = self._current_token_address
            self.cache.set_active_trade_token(None)
            self._current_token_address = None
            self._current_pool_info = {}
            self.is_pool_loading = False
            
            self._market_data = self._get_empty_market_data()
            
            try:
                self.query_one("#market_data_table", DataTable).clear()
            except Exception: pass
            
            self.query_one("#token_metadata_display", Static).update("Token Info: [dim]None[/]")
            self._update_trade_buttons_state()
            
            if self.bridge and token_to_unsubscribe:
                await self.bridge.send(EngineCommand.unsubscribe_token(token_to_unsubscribe))
        except Exception as e:
            await log.error(f"[TUI] Error clearing token state: {e}")

    async def _debounced_switch_token(self, token_address: str):
        await asyncio.sleep(0.3)
        if self._current_token_address != token_address.lower():
            return
        
        self.cache.set_active_trade_token(token_address)
        await log.info(f"[TUI] Новый активный токен: {token_address}")
        
        quote_symbol = str(self.query_one("#trade_quote_select").value)
        quote_address = self.app_config.QUOTE_TOKENS.get(quote_symbol, "")
        
        # await log.debug(f"[SWITCH_TOKEN] token={token_address[:16]}... | quote_symbol={quote_symbol} | quote_address={quote_address[:16] if quote_address else 'NONE'}...")
        # await log.debug(f"[SWITCH_TOKEN] v2_factory={self.app_config.V2_FACTORY_ADDRESS}")
        # await log.debug(f"[SWITCH_TOKEN] rpc_url={self.app_config.RPC_URL[:50]}...")
        
        # Сохраняем quote для фильтрации
        self._current_quote_address = quote_address.lower() if quote_address else None

        if self.bridge: 
            await self.bridge.send(EngineCommand.switch_token(token_address, quote_address, quote_symbol))

        self._trigger_impact_calc()

    @on(Input.Changed, "#amount_input")
    async def on_amount_input_changed(self, event: Input.Changed):
        if self._amount_debounce_task: 
            self._amount_debounce_task.cancel()

        self._amount_debounce_task = asyncio.create_task(self._delayed_impact_calc())
        await self._recalculate_trade_amount(event.value)

    async def _delayed_impact_calc(self):
        await asyncio.sleep(0.3)
        if not self._current_token_address:
            return
        await self._trigger_impact_calc()

    async def _trigger_impact_calc(self):
        """Пересчитывает ОБА импакта независимо от текущего режима"""
        if not self._current_token_address: return

        try:
            val_str = self.query_one("#amount_input").value.strip()
            final_amount = None
            if val_str and not val_str.endswith('%'):
                try: final_amount = float(val_str)
                except ValueError: pass
            
            if not final_amount:
                final_amount = self.cache.get_active_trade_amount_for_quote()
                if not final_amount or final_amount <= 0:
                    final_amount = float(self.cache.get_config().get('default_trade_amount', 0.01))
            
            quote_symbol = str(self.query_one("#trade_quote_select").value)
            quote_address = self.app_config.QUOTE_TOKENS.get(quote_symbol, "")
            
            if self.bridge:
                # === ВСЕГДА считаем BUY impact ===
                if final_amount > 0:
                    await self.bridge.send(EngineCommand.calc_impact(
                        token_address=self._current_token_address, quote_address=quote_address,
                        amount_in=final_amount, is_buy=True
                    ))
                
                # === ВСЕГДА считаем SELL impact ===
                wallets_to_trade = [w['address'] for w in self.wallets_cache_ui if w.get('enabled')]
                total_tokens_wei = sum(self.cache.get_exact_balance_wei(w, self._current_token_address) or 0 for w in wallets_to_trade)
                token_dec = self.cache.get_token_decimals(self._current_token_address) or 18
                amount_to_sell = total_tokens_wei / (10**token_dec)
                
                if amount_to_sell > 0:
                    await self.bridge.send(EngineCommand.calc_impact(
                        token_address=self._current_token_address, quote_address=quote_address,
                        amount_in=amount_to_sell, is_buy=False
                    ))
                else:
                    # Нет токенов - обнуляем sell impact
                    self._market_data['impact_sell'] = 0.0
                    self.ui_update_queue.put_nowait("refresh_market_data")
        except Exception: pass

    @on(Select.Changed, "#trade_quote_select")
    async def on_quote_change(self, event: Select.Changed):
        quote_symbol = str(event.value)
        quote_address = self.app_config.QUOTE_TOKENS.get(quote_symbol, "")
        
        # СНАЧАЛА обновляем quote - фильтр начнёт работать сразу
        self._current_quote_address = quote_address.lower() if quote_address else None
        
        await self.cache.update_config({"default_quote_currency": quote_symbol})
        self.notify(f"Валюта изменена на {quote_symbol}", timeout=1)

        if self._current_token_address:
            quote_address = self.app_config.QUOTE_TOKENS.get(quote_symbol, "")
            if self.bridge: 
                await self.bridge.send(EngineCommand.unsubscribe_token(self._current_token_address))
                self._market_data = self._get_empty_market_data()
                self._current_pool_info = {}
                self.is_pool_loading = True
                self._update_trade_buttons_state()
                await asyncio.sleep(0.3)
                await self.bridge.send(EngineCommand.switch_token(
                    self._current_token_address, quote_address, quote_symbol  
                ))

    @on(Select.Changed, "#setting_quote_currency_select")
    async def on_setting_quote_change(self, event: Select.Changed):
        quote_symbol = str(event.value)
        quote_address = self.app_config.QUOTE_TOKENS.get(quote_symbol, "")
        
        if not quote_address:
            await log.warning(f"[TUI] Quote address not found for symbol: {quote_symbol}")
            return
        
        self._current_quote_address = quote_address.lower()
        
        await self.cache.update_config({"default_quote_currency": quote_symbol})
        self.notify(f"Quote валюта: {quote_symbol}", timeout=1)
        
        if self.bridge:
            await self.bridge.send(EngineCommand.update_settings(quote_symbol=quote_symbol))
        
        if self._current_token_address and self.bridge:
            await self.bridge.send(EngineCommand.switch_token(
                self._current_token_address, quote_address, quote_symbol
            ))

    @on(DataTable.CellSelected, "#wallets_table")
    async def on_wallets_cell_clicked(self, event: DataTable.CellSelected):
        row_key = event.cell_key.row_key.value
        col_index = event.coordinate.column

        if col_index == 1: 
            await self._copy_to_clipboard(row_key, "Адрес кошелька")
        elif col_index == 2:
            target_wallet = next((w for w in self.wallets_cache_ui if w['address'] == row_key), None)
            if target_wallet:
                new_status = not target_wallet['enabled']
                await self.cache.update_wallet(row_key, {"enabled": new_status})
                self._trigger_wallets_refresh()
                self.notify(f"Кошелек {'Включен' if new_status else 'Выключен'}", timeout=1)

    @on(Button.Pressed, "#better_pool_suggestion")
    def on_suggestion_clicked(self, event: Button.Pressed):
        target_quote = event.button.name
        if target_quote:
            self.query_one("#trade_quote_select").value = target_quote
            event.button.display = False
            self.notify(f"Валюта переключена на {target_quote}", timeout=2)

    @on(Button.Pressed, "#buy_button")
    async def on_buy_button(self, event: Button.Pressed):
        self._active_trade_mode = "BUY"
        self._update_panel_visuals()
        await self.action_execute_trade()

    @on(Button.Pressed, "#sell_button")
    async def on_sell_button(self, event: Button.Pressed):
        self._active_trade_mode = "SELL"
        self._update_panel_visuals()
        await self.action_execute_trade()

    @on(Button.Pressed, "#save_new_wallet_button")
    async def on_save_wallet(self, event: Button.Pressed):
        name_input = self.query_one("#new_wallet_name_input", Input)
        pk_input = self.query_one("#new_wallet_pk_input", Input)
        name = name_input.value.strip()
        pk = pk_input.value.strip()
        
        if not name or not pk:
            return self.notify("Заполните все поля!", severity="error")
        
        try:
            if pk.startswith('0x'): pk = pk[2:]
            account = Account.from_key(pk)
            address = account.address
            
            await self.cache.add_wallet(address, pk, name, True)
            
            name_input.value = ""
            pk_input.value = ""
            self.notify(f"Кошелек {name} добавлен!", severity="information")
            
            self._trigger_wallets_refresh()
            
            if self.bridge:
                await self.bridge.send(EngineCommand.add_wallet(address, pk))
                await asyncio.sleep(0.3)
                await self.bridge.send(EngineCommand.refresh_balance(address, self.app_config.NATIVE_CURRENCY_ADDRESS))
                _, quote_address = self._get_quote_info()
                if quote_address:
                    await self.bridge.send(EngineCommand.refresh_balance(address, quote_address))
                
        except Exception as e:
            self.notify(f"Ошибка: {str(e)[:50]}", severity="error")

    @on(Button.Pressed, "#delete_wallet_button")
    async def on_delete_wallet(self, event: Button.Pressed):
        try:
            table = self.query_one("#wallets_table", DataTable)
            if table.cursor_coordinate:
                row_key = table.get_row_at(table.cursor_coordinate.row)[1]
                if isinstance(row_key, Text):
                    row_key = row_key.plain
                
                await self.cache.delete_wallet(row_key)
                self._trigger_wallets_refresh()
                self.notify("Кошелек удален", severity="information")
        except Exception as e:
            self.notify(f"Ошибка удаления: {str(e)[:30]}", severity="error")

    # ===================== ЛОГИКА ТОРГОВЛИ =====================

    async def _prepare_sell_data(self, token_address: str, wallets_to_trade: List[str], amounts_wei_dict: Dict[str, str]) -> Tuple[float, str]:
        total_tokens_wei = 0
        decimals = self.cache.get_token_decimals(token_address) or 18

        for w_addr in wallets_to_trade:
            wei = self.cache.get_or_load_balance_wei(w_addr, token_address)
            if wei:
                total_tokens_wei += wei
                amounts_wei_dict[w_addr.lower()] = str(wei)
        
        if total_tokens_wei > 0:
            final_amount = total_tokens_wei / (10**decimals)
            # ИЗ КЭША - мгновенно, без await и БД
            meta = self.cache.get_token_metadata_cached(token_address)
            display_symbol = meta.get('symbol', 'TOKEN') if meta else "TOKEN"
            return final_amount, display_symbol
        return 0.0, "TOKEN"

    async def _prepare_buy_data(self, wallets_to_trade: List[str], quote_symbol: str, quote_address: str) -> Tuple[float, str]:
        final_amount = self.cache.get_active_trade_amount_for_quote()
        
        if final_amount is None or final_amount <= 0:
            val_str = self.query_one("#amount_input").value.strip()
            if val_str:
                try:
                    if val_str.endswith('%'):
                        pct = float(val_str[:-1])
                        if quote_address:
                            total_bal = sum(self.cache.get_wallet_balances(w['address']).get(quote_address.lower(), 0.0) for w in wallets_to_trade)
                            final_amount = total_bal * (pct / 100.0)
                            if pct == 100: final_amount *= 0.999
                    else: 
                        final_amount = float(val_str)
                except Exception: pass

        return final_amount or 0.0, quote_symbol

    async def action_execute_trade(self):
        if self.query_one(TabbedContent).active != "trade_tab": 
            return
        
        try:
            btn_id = "#buy_button" if self._active_trade_mode == "BUY" else "#sell_button"
            btn = self.query_one(btn_id, Button)
            if not btn.disabled:
                btn.add_class("button-pressed")
                await asyncio.sleep(0.03)
                btn.remove_class("button-pressed")
        except Exception: pass
        
        token_address = self.query_one("#token_input").value.strip()
        if not Web3.is_address(token_address): 
            return self.notify("Введите корректный адрес токена!", severity="error")
        
        wallets_to_trade = [w['address'] for w in self.wallets_cache_ui if w.get('enabled')]
        if not wallets_to_trade: 
            return self.notify("Нет активных кошельков.", severity="error")

        quote_symbol, quote_address = self._get_quote_info()
        amounts_wei_dict = {}

        if self._active_trade_mode == "SELL":
            final_amount, display_symbol = await self._prepare_sell_data(token_address, wallets_to_trade, amounts_wei_dict)
            if final_amount <= 0:
                return self.notify("Нет токенов для продажи. Проверьте кэш и БД.", severity="error")
        else:
            final_amount, display_symbol = await self._prepare_buy_data(wallets_to_trade, quote_symbol, quote_address)
            if final_amount <= 0:
                return self.notify("Сумма 0 или ошибка расчета.", severity="error", timeout=5)
            
            # === ПРОВЕРКА БАЛАНСА QUOTE ТОКЕНА ===
                        # === ПРОВЕРКА БАЛАНСА QUOTE ТОКЕНА ===
            quote_address_lower = quote_address.lower()
            total_quote_balance = 0.0
            for w_addr in wallets_to_trade:
                total_quote_balance += self._balance_cache.get(w_addr.lower(), {}).get(quote_address_lower, 0.0)
            
            if final_amount > total_quote_balance:
                err_msg = f"Недостаточно {quote_symbol}: нужно {final_amount:.6f}, есть {total_quote_balance:.6f}"
                await log.error(err_msg)
                return self.notify(err_msg, severity="error", timeout=5
            )
            
            # === ПРОВЕРКА НАТИВНОЙ ВАЛЮТЫ ДЛЯ ГАЗА ===
            native_address = self.app_config.NATIVE_CURRENCY_ADDRESS.lower()
            native_symbol = self.app_config.NATIVE_CURRENCY_SYMBOL
            min_gas = self.app_config.MIN_NATIVE_FOR_GAS
            
            for w_addr in wallets_to_trade:
                native_bal = self._balance_cache.get(w_addr.lower(), {}).get(native_address, 0.0)
                if native_bal < min_gas:
                    await log.error(
                        f"<red>[BUY BLOCKED]</red> Недостаточно {native_symbol} для газа на кошельке "
                        f"{self._short_wallet(w_addr)}: {native_bal:.6f} < {min_gas}"
                    )
                    return self.notify(
                        f"❌ Недостаточно {native_symbol} для газа!\n"
                        f"Кошелек: {self._short_wallet(w_addr)}\n"
                        f"Баланс: {native_bal:.6f}, нужно: {min_gas}",
                        severity="error",
                        timeout=8
                    )

        await log.info(f"TUI: START TRADE -> {self._active_trade_mode} {final_amount:.6f} {display_symbol}")

        if self.bridge:
            await self.bridge.send(EngineCommand.execute_trade(
                action=self._active_trade_mode.lower(), 
                token=token_address, 
                quote_token=quote_address,
                amount=final_amount, 
                wallets=wallets_to_trade, 
                gas_gwei=self.current_gas_price_gwei, 
                slippage=self.current_slippage,
                amounts_wei=amounts_wei_dict
            ))

    # ===================== ACTIONS (HOTKEYS) =====================

    def action_change_slippage(self, change: float):
        self.current_slippage = max(0.1, self.current_slippage + change)
        try: 
            self.query_one("#setting_slippage_input").value = f"{self.current_slippage:.1f}"
        except Exception: pass
        self.notify(f"Slippage: {self.current_slippage:.1f}%", timeout=1)

    def action_change_gas(self, change: float):
        self.current_gas_price_gwei = max(0.1, self.current_gas_price_gwei + change)
        try: 
            self.query_one("#setting_gas_price_input").value = f"{self.current_gas_price_gwei:.2f}"
        except Exception: pass
        self.notify(f"Gas Price: {self.current_gas_price_gwei:.2f} Gwei", timeout=1)

    async def action_reload_wallets(self):
        self._trigger_wallets_refresh()
        if self.bridge: 
            await self.bridge.send(EngineCommand.refresh_all_balances())
        self.notify("Кошельки обновлены.", severity="information", timeout=1)

    def action_clear_token_input(self):
        try:
            self.query_one("#token_input").value = ""
            self.cache.set_active_trade_token(None)
            self._current_token_address = None
        except Exception: pass

    def action_switch_tab(self, tab_id: str): 
        self.query_one(TabbedContent).active = tab_id

    def action_save_settings(self): 
        asyncio.create_task(self._save_settings())

    # ===================== UI UPDATERS =====================

    def _update_panel_visuals(self):
        try:
            for panel_id, mode in[("buy_panel", "BUY"), ("sell_panel", "SELL")]:
                self.query_one(f"#{panel_id}").set_class(self._active_trade_mode == mode, "active-panel")
        except Exception: pass

    def _update_market_data_table(self):
        try:
            table = self.query_one("#market_data_table", DataTable)
            table.clear()
            
            pool_type = self._market_data.get('pool_type', '-')
            pool_fee = self._market_data.get('fee_bps', 0)
            liq_usd = self._market_data.get('tvl_usd', 0)
            impact_buy = self._market_data.get('impact_buy', 0.0)
            impact_sell = self._market_data.get('impact_sell', 0.0)
            
            current_price_in_quote = self._market_data.get('current_price', 0.0)
            pos_cost_quote = self._market_data.get('pos_cost_quote', 0.0) 
            pos_amount = self._market_data.get('pos_amount', 0.0)         
            
            quote_symbol, _ = self._get_quote_info()
            quote_price_usd = self.cache.get_quote_price(quote_symbol) or 1.0
            
            token_symbol = self._market_data.get('token_symbol', 'TOKEN')
            pair_str = f"{token_symbol}/{quote_symbol}" if pool_type != '-' else "-"
            
            pnl_str = "-"
            pnl_color = "white"
            
            if pos_amount > 0 and current_price_in_quote > 0 and pos_cost_quote > 0:
                current_val_quote = pos_amount * current_price_in_quote
                pnl_quote = current_val_quote - pos_cost_quote
                pnl_usd = pnl_quote * quote_price_usd
                pnl_pct = (pnl_quote / pos_cost_quote) * 100 if pos_cost_quote > 0 else 0.0
                
                sign = "+" if pnl_pct >= 0 else ""
                pnl_str = f"{sign}{pnl_pct:.2f}% ({sign}${pnl_usd:.2f})"
                pnl_color = "green" if pnl_pct >= 0 else "red"
            
            pool_str = f"{pool_type} ({pool_fee}bps)" if pool_type != '-' else '-'
            current_price_usd = current_price_in_quote * quote_price_usd
            
            ib_color = "green" if impact_buy < 2 else "yellow" if impact_buy < 5 else "red"
            is_color = "green" if impact_sell < 2 else "yellow" if impact_sell < 5 else "red"

            table.add_row(
                Text(pair_str, style="bold cyan"),
                Text(pool_str, style="cyan"),
                Text(f"${liq_usd:,.0f}", style="green"),
                Text(f"${current_price_usd:.8f}", style="yellow"),
                Text(f"{impact_buy:.2f}%", style=ib_color),
                Text(f"{impact_sell:.2f}%", style=is_color),
                Text(pnl_str, style=pnl_color)
            )
        except Exception: pass

    async def _recalculate_trade_amount(self, value: str, silent: bool = False):
        value = value.strip()
        final_amount: Optional[float] = None

        if not value:
            self.cache.set_active_trade_amount_for_quote(None)
            return
        
        if value.endswith('%'):
            try:
                pct = float(value[:-1])
                if not (0 < pct <= 100):
                    self.cache.set_active_trade_amount_for_quote(None)
                    return
                
                quote_symbol, quote_address = self._get_quote_info()
                if not quote_address: 
                    self.cache.set_active_trade_amount_for_quote(None)
                    return

                active_wallets =[w for w in self.wallets_cache_ui if w.get('enabled')]
                total_balance = sum(self.cache.get_wallet_balances(w['address']).get(quote_address.lower(), 0.0) for w in active_wallets)
                final_amount = total_balance * (pct / 100.0)
                if pct == 100: final_amount *= 0.999

                if not silent:
                    msg = f"Расчет: {final_amount:.12f} {quote_symbol}"
                    if msg != self._last_calc_msg:
                        self.notify(msg, timeout=2)
                        self._last_calc_msg = msg

            except (ValueError, TypeError): 
                self.cache.set_active_trade_amount_for_quote(None)
                return
        else:
            try: 
                final_amount = float(value)
                self._last_calc_msg = ""
            except ValueError: 
                final_amount = None

        self.cache.set_active_trade_amount_for_quote(final_amount)

    async def _refresh_wallet_table(self):
        try:
            self.wallets_cache_ui = self.cache.get_all_wallets(enabled_only=False)
            wallets_table = self.query_one("#wallets_table", DataTable)
            current_cursor = wallets_table.cursor_coordinate
            
            wallets_table.clear()
            if not wallets_table.columns: 
                wallets_table.add_columns("Название", "Адрес", "Статус (Клик)")

            for w in self.wallets_cache_ui:
                status_render = Text("▣ Активен", style="bold green") if w.get('enabled') else Text("▢ Выключен", style="dim white")
                wallets_table.add_row(w.get('name', 'Unknown'), Text(w['address']), status_render, key=w['address'])

            if current_cursor and current_cursor.row < len(self.wallets_cache_ui): 
                wallets_table.move_cursor(row=current_cursor.row, column=current_cursor.column, animate=False)
            
            balances_table = self.query_one("#balances_table", DataTable)
            balances_table.clear()
            
            quote_symbol, quote_address = self._get_quote_info()
            native_symbol = self.app_config.NATIVE_CURRENCY_SYMBOL
            native_address = self.app_config.NATIVE_CURRENCY_ADDRESS.lower()
            quote_address = quote_address.lower()
            
            balances_table.columns.clear()
            balances_table.add_columns("Кошелек", f"{native_symbol}(fee)", f"{quote_symbol}(quote)")
            
            for w in self.wallets_cache_ui:
                if w.get('enabled'):
                    w_addr = w['address'].lower()
                    native_bal = self._balance_cache.get(w_addr, {}).get(native_address, 0.0)
                    quote_bal = self._balance_cache.get(w_addr, {}).get(quote_address, 0.0)
                    balances_table.add_row(w.get('name', 'Unknown'), f"{native_bal:.6f}", f"{quote_bal:.6f}")
        except Exception: pass

    async def _load_and_apply_settings(self):
        config = self.cache.get_config()
        try:
            self.query_one("#setting_rpc_url_input").value = str(config.get('rpc_url', self.app_config.RPC_URL) or "")
            self.query_one("#setting_quote_currency_select").value = str(config.get('default_quote_currency', self.app_config.DEFAULT_QUOTE_CURRENCY) or "")
            self.query_one("#setting_slippage_input").value = str(config.get('slippage', 15.0))
            self.query_one("#setting_gas_price_input").value = str(config.get('default_gas_price_gwei', 1.0))
            self.query_one("#setting_trade_amount_input").value = str(config.get('default_trade_amount', '0.01'))
            self.query_one("#setting_gas_limit_input").value = str(config.get('gas_limit', 350000))
            self.query_one("#setting_autofuel_enable").value = str(config.get('auto_fuel_enabled', False))
            self.query_one("#setting_autofuel_threshold").value = str(config.get('auto_fuel_threshold', '0.005'))
            self.query_one("#setting_autofuel_amount").value = str(config.get('auto_fuel_amount', '0.02'))
            
            self.current_slippage = float(config.get('slippage', 15.0))
            self.current_gas_price_gwei = float(config.get('default_gas_price_gwei', 1.0))
            self.query_one("#amount_input").value = str(config.get('default_trade_amount', '0.01'))
        except Exception as e:
            await log.error(f"TUI CRITICAL: Не удалось загрузить настройки в виджеты: {e}")
            self.notify("Критическая ошибка загрузки настроек!", severity="error", timeout=10)

    async def _save_settings(self):
        if self.query_one(TabbedContent).active != "settings_tab": return
        try:
            fuel_enabled = self.query_one("#setting_autofuel_enable").value == "True"
            fuel_threshold = float(self.query_one("#setting_autofuel_threshold").value or "0.005")
            fuel_amount = float(self.query_one("#setting_autofuel_amount").value or "0.02")
            quote_symbol = str(self.query_one("#setting_quote_currency_select").value)
            quote_address = self.app_config.QUOTE_TOKENS.get(quote_symbol, "")
            
            current_rpc = self.cache.get_config().get('rpc_url', self.app_config.RPC_URL)
            new_rpc = self.query_one("#setting_rpc_url_input").value.strip()
            rpc_changed = new_rpc != current_rpc
            
            await self.cache.update_config({
                'rpc_url': new_rpc, 
                'default_quote_currency': quote_symbol, 
                'slippage': float(self.query_one("#setting_slippage_input").value or "15.0"),
                'default_gas_price_gwei': float(self.query_one("#setting_gas_price_input").value or "1.0"), 
                'default_trade_amount': self.query_one("#setting_trade_amount_input").value or "0.01",
                'gas_limit': int(self.query_one("#setting_gas_limit_input").value or "350000"), 
                'auto_fuel_enabled': fuel_enabled,
                'auto_fuel_threshold': fuel_threshold, 
                'auto_fuel_amount': fuel_amount
            })
            
            if self.bridge:
                await self.bridge.send(EngineCommand.update_settings(
                    gas_price_gwei=self.current_gas_price_gwei, 
                    slippage=self.current_slippage,
                    fuel_enabled=fuel_enabled, 
                    fuel_quote_address=quote_address if fuel_enabled else None,
                    quote_symbol=quote_symbol 
                ))
                
            if rpc_changed:
                self.notify("RPC изменен. Перезапуск...", severity="warning", timeout=3)
                await asyncio.sleep(1)
                self.exit(result="RESTART_SAME_NETWORK")
            else:
                self.notify("⚙️ Настройки сохранены", severity="information", title="Success")
                await self._load_and_apply_settings()
        except Exception as e: 
            self.notify(f"Ошибка сохранения: {e}", severity="error")

    async def _copy_to_clipboard(self, text: str, label: str):
        def blocking_copy():
            try: 
                pyperclip.copy(text)
                return True, ""
            except pyperclip.PyperclipException as e: 
                return False, str(e)
                
        try:
            success, _ = await asyncio.to_thread(blocking_copy)
            if success: 
                self.notify(f"{label} скопирован!", severity="information", timeout=2)
            else: 
                self.notify("Буфер обмена недоступен.", severity="error", timeout=2)
        except Exception: 
            self.notify("Не удалось скопировать.", severity="error", timeout=2)

    def compose(self) -> ComposeResult:
        with Horizontal(id="app_header"):
            yield Label(f"🌐 {self.current_network.upper()}", id="network_label")
            yield Select(options=[(net.upper(), net) for net in self.available_networks], value=self.current_network, id="network_select")
        
        with Container(id="status_bar_container"):
            with Container(id="status_bar"):
                yield StatusRPC("🔴 RPC: -")
                yield StatusConnection("🔴 WS: -")
                yield StatusGas("⛽ Gas: -")
                yield StatusWallets("Wallets: -")
                
        with TabbedContent(initial="trade_tab", id="main_tabs"):
            with TabPane("📊 Торговля", id="trade_tab"):
                with VerticalScroll(id="main_trade_scroller"):
                    with Horizontal(id="input_row_container"):
                        with Vertical(id="token_input_group"):
                            with Horizontal(classes="label-row"):
                                yield Label(" Пара:", classes="input-label")
                                yield Static("Token Info: [dim]None[/]", id="token_metadata_display")
                            yield Input(placeholder="Вставьте адрес токена", id="token_input", validators=[AddressValidator()])
                        
                        with Vertical(id="amount_input_group"):
                            yield Button("💡 Рекомендация", id="better_pool_suggestion", variant="warning")
                            yield Label(" Сумма / Валюта:", classes="input-label")
                            with Horizontal(classes="input-row"):
                                yield Input(id="amount_input", validators=[AmountValidator()], classes="half-width-input")
                                yield Select(options=[], id="trade_quote_select", classes="half-width-select")
                    
                    with Horizontal(id="trade_panels_container"):
                        with Vertical(id="buy_panel", classes="active-panel"):
                            yield Label("BUY", classes="trade-panel-title")
                            yield Button("КУПИТЬ", variant="success", id="buy_button", disabled=True)
                        with Vertical(id="sell_panel"):
                            yield Label("SELL (100%)", classes="trade-panel-title")
                            yield Button("ПРОДАТЬ", variant="error", id="sell_button", disabled=True)
                    
                    yield Label("📊 Рыночные данные:", id="market_data_label")
                    yield DataTable(id="market_data_table")
                    yield Label("💼 Активные кошельки:", id="balances_label")
                    yield DataTable(id="balances_table")
            
            with TabPane("👛 Кошельки", id="wallets_tab"):
                with VerticalScroll(id="wallets_scroll_container"):
                    yield DataTable(id="wallets_table")
                    with Vertical(id="add_wallet_form"):
                        yield Label("Добавить кошелек:", classes="form-title")
                        yield Input(placeholder="Название", id="new_wallet_name_input")
                        yield Input(placeholder="Приватный ключ", id="new_wallet_pk_input", password=True)
                        yield Button("Сохранить", variant="success", id="save_new_wallet_button")
                with Horizontal(classes="table-buttons"):
                    yield Button("Удалить выбранный", id="delete_wallet_button", variant="error")
            
            with TabPane("⚙️ Настройки", id="settings_tab"):
                with VerticalScroll(id="settings_scroll_container"):
                    with Vertical(classes="settings-group"):
                        yield Label("Основные настройки", classes="settings-title")
                        yield Label(" RPC URL:", classes="input-label")
                        yield Input(id="setting_rpc_url_input", validators=[URL()])
                        yield Label(" Стейблкоин:", classes="input-label")
                        quote_tokens = list(self.app_config.QUOTE_TOKENS.keys())
                        yield Select(options=[(token, token) for token in sorted(quote_tokens)], id="setting_quote_currency_select")
                    
                    with Vertical(classes="settings-group"):
                        yield Label("⛽ Авто-закупка газа (Auto-Fuel)", classes="settings-title")
                        yield Label("Включить авто-пополнение:", classes="input-label")
                        yield Select(options=[("Выкл", "False"), ("Вкл", "True")], id="setting_autofuel_enable", value="False")
                        yield Label(f"Порог ({self.app_config.NATIVE_CURRENCY_SYMBOL}):", classes="input-label")
                        yield Input(id="setting_autofuel_threshold", placeholder="0.005", validators=[FloatValidator()])
                        yield Label(f"Докупать ({self.app_config.NATIVE_CURRENCY_SYMBOL}):", classes="input-label")
                        yield Input(id="setting_autofuel_amount", placeholder="0.02", validators=[FloatValidator()])
                    
                    with Vertical(classes="settings-group"):
                        yield Label("Настройки транзакций", classes="settings-title")
                        yield Label(" Gas Price (Gwei):", classes="input-label")
                        yield Input(id="setting_gas_price_input", validators=[FloatValidator()])
                        yield Label(" Slippage (%):", classes="input-label")
                        yield Input(id="setting_slippage_input", validators=[FloatValidator()])
                        yield Label(" Сумма трейда:", classes="input-label")
                        yield Input(id="setting_trade_amount_input", validators=[AmountValidator()])
                        yield Label(" Gas Limit:", classes="input-label")
                        yield Input(id="setting_gas_limit_input", validators=[IntegerValidator()])
            
            with TabPane("📋 Логи", id="logs_tab"):
                yield RichLog(id="log_output", wrap=True, highlight=True)
            
            with TabPane("❓ Помощь", id="help_tab"):
                with VerticalScroll():   
                    yield Markdown(HELP_TEXT, id="help_markdown")
        yield Footer()

    async def _notification_watcher(self) -> None:
        while True:
            try:
                result = await self.notification_queue.get()
                status = result.get('status')
                status = status.lower() if status else "info"
                
                wallet = result.get('wallet', 'Unknown')
                message = result.get('message', '')
                short_wallet = self._short_wallet(wallet)

                if status == 'warning': 
                    self.notify(f"⚠️ {message}", title="Внимание", severity="warning", timeout=5)
                elif status == 'autofuel_success': 
                    self.notify(f"⛽ Закуплено {message}", title="AUTO-FUEL", severity="information", timeout=4)
                elif status == 'autofuel_error': 
                    self.notify(f"⛽ Ошибка закупки: {message}", title="AUTO-FUEL ERROR", severity="error", timeout=5)
                elif status == 'error':
                    msg = message if len(message) <= 100 else message[:100] + "..."
                    self.notify(f"❌ Ошибка у {short_wallet}: {msg}", severity="error", timeout=6)

                self.notification_queue.task_done()
            except asyncio.CancelledError: 
                break
            except Exception as e:
                await log.error(f"Notification watcher error: {e}")
                await asyncio.sleep(0.1)

