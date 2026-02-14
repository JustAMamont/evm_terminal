import asyncio
from typing import Optional, Dict, List, Any
from collections import deque
import pyperclip
import re
from pathlib import Path

from textual.app import App, ComposeResult
from textual.containers import Container, Horizontal, Vertical, VerticalScroll
from textual.widgets import (
    Button, DataTable, Footer, Input, Label, RichLog,
    Static, TabbedContent, TabPane, Markdown, Select
)
from textual.binding import Binding, BindingType
from textual.validation import Validator, ValidationResult, Regex, URL
from textual import on
from rich.text import Text
from rich.style import Style
from web3 import Web3

from utils.aiologger import log, LogLevel
from bot.inner_api.schemas import APICommand, WalletCreate, TradeRequest, ConfigUpdate
from bot.inner_api.router import APIRouter
from bot.cache import GlobalCache
from bot.services.bot_service import BotService

try:
    import dexbot_core
    RUST_AVAILABLE = True
except ImportError:
    dexbot_core = None
    RUST_AVAILABLE = False


from rich.text import Text

HELP_TEXT = """
---

# 🚀 Руководство пользователя EVM_TRADER

**EVM_TRADER** — это высокоскоростной терминал для торговли на децентрализованных биржах (DEX).

---

### 1. Первичная настройка (Безопасность)
При первом запуске бот попросит создать **Мастер-пароль**.
- Он шифрует ваши приватные ключи локально в папке `data`.
- Бот работает полностью автономно.

### 2. Подключение к сети (Вкладка Settings)
- Используйте быстрый **RPC URL** (желательно приватный).
- Выберите **Стейблкоин** для торгов (обычно WBNB или USDT).

### 3. Управление кошельками (Вкладка Wallets)
- Добавьте приватные ключи ваших кошельков.
- Убедитесь, что на кошельках есть нативная монета для оплаты газа.

### 4. Торговля (Вкладка Trade)
**Покупка (BUY):**
1. Вставьте адрес токена.
2. Введите сумму (число или %).
3. Нажмите **КУПИТЬ** или `Enter`.

**Продажа (SELL):**
1. Токен должен быть активен (выбран в поле адреса).
2. Нажмите `Down` или выберите панель **SELL**.
3. Нажмите **ПРОДАТЬ**.

---

### ⌨️ Горячие клавиши
*   `T`: Торговля
*   `W`: Кошельки
*   `S`: Настройки
*   `L`: Логи
*   `↑ / ↓`: Смена режима BUY / SELL.
*   `Enter`: Выполнить операцию.

---
"""

class AmountValidator(Validator):
    def validate(self, value: str) -> ValidationResult:
        value = value.strip()
        if not value:
            return self.failure("Поле не может быть пустым.")
        if value.endswith('%'):
            try:
                num = float(value[:-1])
                if not (0 < num <= 100):
                    return self.failure("Процент должен быть от 0 до 100.")
            except ValueError:
                return self.failure("Неверный формат процента.")
        else:
            try:
                num = float(value)
                if num <= 0:
                    return self.failure("Сумма должна быть > 0.")
            except ValueError:
                return self.failure("Нужно число или процент.")
        return self.success()

class FloatValidator(Validator):
    def validate(self, value: str) -> ValidationResult:
        try:
            val = float(value)
            if val <= 0: return self.failure("Должно быть > 0")
        except ValueError: return self.failure("Нужно число")
        return self.success()

class IntegerValidator(Validator):
    def validate(self, value: str) -> ValidationResult:
        try:
            val = int(value)
            if val <= 0: return self.failure("Должно быть > 0")
        except ValueError: return self.failure("Нужно целое число")
        return self.success()

class AddressValidator(Regex):
    def __init__(self):
        super().__init__(r'^0x[a-fA-F0-9]{40}$', failure_description="Неверный формат адреса 0x...")


class TextualRichLogHandler:
    def __init__(self, rich_log_widget: RichLog, max_messages: int = 200):
        self._widget = rich_log_widget
        self._message_buffer = deque(maxlen=max_messages)

    async def emit(self, dt_str: str, level: LogLevel, message: str, dt):
        level_style_map = {
            LogLevel.DEBUG: Style(color="cyan"), LogLevel.INFO: Style(color="blue"),
            LogLevel.SUCCESS: Style(color="green"), LogLevel.WARNING: Style(color="yellow"),
            LogLevel.ERROR: Style(color="red"), LogLevel.CRITICAL: Style(bgcolor="red", color="white", bold=True),
        }
        prefix_style = level_style_map.get(level, Style(color="white"))
        rich_prefix = Text(f"{dt_str} - [{level.name}] - ", style=prefix_style)
        
        formatted_message = re.sub(r"<(\w+)>(.*?)</\1>", r"[\1]\2[/\1]", message)
        
        full_message_text = rich_prefix + Text.from_markup(formatted_message)
        
        self._message_buffer.append(full_message_text)
        if self._widget.is_running and self._widget.visible: self._widget.write(full_message_text)

    def get_last_messages(self) -> list[Text]:
        return list(self._message_buffer)


class StatusRPC(Static):
    def update_content(self, status: str, healthy: bool):
        self.update(f"Sys: [bold {'green' if healthy else 'red'}]{status}[/]")

class StatusWallets(Static):
    def update_content(self, has_active: bool):
        icon = "✅" if has_active else "❌"
        color = "green" if has_active else "red"
        self.update(f"Wallets: [bold {color}]{icon}[/]")


class TradingApp(App):
    CSS_PATH = str(Path(__file__).parent / "app.css")
    BINDINGS: List[BindingType] = [ # type: ignore
        Binding("ctrl+q", "quit", "Выход", priority=True),
        Binding("ctrl+r", "reload_wallets", "Перезагрузить кошельки", priority=True),
        Binding("ctrl+s", "save_settings", "Сохранить настройки", show=False, priority=True),
        Binding("delete", "clear_token_input", "Очистить токен", show=False, priority=True),
        Binding("t,е", "switch_tab('trade_tab')", "Торговля", priority=True),
        Binding("w,ц", "switch_tab('wallets_tab')", "Кошельки", priority=True),
        Binding("s,ы", "switch_tab('settings_tab')", "Настройки", priority=True),
        Binding("l,д", "switch_tab('logs_tab')", "Логи", priority=True),
        Binding("f,а", "switch_tab('help_tab')", "Помощь", priority=True),
        Binding("down", "set_trade_mode('SELL')", "Продажа", show=False, priority=True),
        Binding("up", "set_trade_mode('BUY')", "Покупка", show=False, priority=True),
        Binding("enter", "execute_trade", "Выполнить", show=False, priority=True),
        
        Binding("shift+up", "change_slippage(0.5)", "Slippage +0.5%", show=False),
        Binding("shift+down", "change_slippage(-0.5)", "Slippage -0.5%", show=False),
        Binding("shift+right", "change_gas(0.1)", "Gas +0.1 Gwei", show=False),
        Binding("shift+left", "change_gas(-0.1)", "Gas -0.1 Gwei", show=False),
    ]

    def __init__(self, api_router: APIRouter, cache: GlobalCache, notification_queue: asyncio.Queue, bot_service: BotService, market_data_service, current_network: str, available_networks: list, update_queue: Any = None, version: str = "1.0.0"):
        super().__init__()
        self.api_router = api_router
        self.cache = cache
        self.notification_queue = notification_queue
        self.bot_service = bot_service
        self.market_data_service = market_data_service 
        self.current_network = current_network
        self.available_networks = available_networks
        self._rich_log_handler: Optional[TextualRichLogHandler] = None
        self._active_trade_mode = "BUY"

        self.ui_update_queue = asyncio.Queue()
        self.wallets_cache_ui: List[Dict] = []
        self.recent_tokens_cache_ui: List[Dict] = []

        self.status_update_task: Optional[asyncio.Task] = None
        
        self.current_slippage: float = 15.0
        self.current_gas_price_gwei: float = 0.1
        self.current_max_fee_cents: int = 10
        
        self._is_pool_loading = False
        
        self._last_calc_msg: str = ""


    async def trigger_background_approvals(self):
        raw_wallets = self.cache.get_all_wallets(enabled_only=True)
        enabled_wallets = [w['address'] for w in raw_wallets]
        
        if enabled_wallets:
            asyncio.create_task(self.bot_service.schedule_quote_token_approvals(
                enabled_wallets, 
                self.current_gas_price_gwei
            ))
            await log.info(f"[TUI] Запущена проверка апрувов для {len(enabled_wallets)} кошельков.")

    def _update_trade_buttons_state(self):
        try:
            buy_button = self.query_one("#buy_button", Button)
            sell_button = self.query_one("#sell_button", Button)
            
            has_active_wallets = any(w.get('enabled') for w in self.wallets_cache_ui)
            is_ready = not self._is_pool_loading and has_active_wallets
            
            buy_button.disabled = not is_ready
            sell_button.disabled = not is_ready
        except Exception:
            pass 

    @on(Input.Changed, "#token_input")
    async def on_token_input_changed(self, event: Input.Changed) -> None:
        token_address = event.value.strip()
        
        try: self.query_one("#better_pool_suggestion").display = False
        except: pass

        self._is_pool_loading = False
        self._update_trade_buttons_state()
        self.query_one("#token_metadata_display", Static).update("Token Info: [dim]...[/]")
        self.query_one("#pnl_tvl_table", DataTable).clear()

        if Web3.is_address(token_address):
            self._is_pool_loading = True
            self._update_trade_buttons_state()

            self.cache.set_active_trade_token(token_address)
            await log.info(f"[TUI] Новый активный токен: {token_address}")

            asyncio.create_task(self.bot_service.fetch_and_store_token_metadata(token_address))
            asyncio.create_task(self.market_data_service.find_and_cache_best_pool(token_address))
            asyncio.create_task(self._run_recommendation_engine(token_address))

            if self.market_data_service:
                asyncio.create_task(self.market_data_service.switch_token_monitor(token_address))
        else:
            self.cache.set_active_trade_token(None)
            if self.market_data_service:
                asyncio.create_task(self.market_data_service.stop_token_monitor())

    async def _run_recommendation_engine(self, token_address: str):
        meta_display = self.query_one("#token_metadata_display", Static)
        meta_display.update("[dim]Analyzing...[/]")

        balances = {}
        for _ in range(100):
            balances = await asyncio.to_thread(dexbot_core.get_all_pool_balances) # type: ignore
            if balances: break
            await asyncio.sleep(0.1)

        if not balances:
            meta_display.update("Token Info: [red]❌ Rust data timeout[/]")
            return

        current_quote_sym = self.query_one("#trade_quote_select", Select).value
        
        best_quote_sym = current_quote_sym
        max_tvl_usd = 0.0
        
        current_pool_tvl_usd = 0.0
        current_pool_addr = None

        for pool_addr_raw, balance_wei_str in balances.items():
            pool_addr = pool_addr_raw.replace('"', '').replace("'", "").lower()
            meta = self.market_data_service._pool_metadata_cache.get(pool_addr)
            if not meta: continue
            
            sym = meta['symbol']
            price = self.cache.get_quote_price(sym)
            if price <= 0: continue

            quote_addr = self.bot_service.config.QUOTE_TOKENS.get(sym)
            decimals = self.cache.get_token_decimals(quote_addr) or 18
            
            try:
                side_val = float(balance_wei_str) / (10**decimals)
                side_usd = side_val * price
                tvl_usd = side_usd * 2
            except: tvl_usd = 0
            
            if tvl_usd > max_tvl_usd:
                max_tvl_usd = tvl_usd
                best_quote_sym = sym
            
            if sym == current_quote_sym:
                if tvl_usd > current_pool_tvl_usd:
                    current_pool_tvl_usd = tvl_usd
                    current_pool_addr = pool_addr

        if current_pool_addr:
            await log.info(f"🎯 Active Pool ({current_quote_sym}): {current_pool_addr}")
        else:
            await log.warning(f"⚠️ No active pool found for {current_quote_sym}")

        if current_pool_tvl_usd > 0:
            self.notify(
                f"TVL Пула ({current_quote_sym}): ${current_pool_tvl_usd:,.0f}",
                title="Pool Liquidity",
                severity="information",
                timeout=4
            )

        token_symbol = "TOKEN"
        try:
            m = await self.cache.db.get_token_metadata(token_address)
            if m: token_symbol = m.get('symbol', 'TOKEN')
        except: pass

        base_text = f"Token Info: [bold cyan]{token_symbol}[/] "

        is_bad_pair = (best_quote_sym != current_quote_sym) and (current_pool_tvl_usd < 1000) and (max_tvl_usd > 5000)

        if is_bad_pair:
             alert_text = (
                f"\n[bold white on red] 🛑 ОШИБКА ВЫБОРА! [/] "
                f"[bold yellow]Идите в {best_quote_sym} (${max_tvl_usd:,.0f})[/]\n"
                f"[dim]Тут пусто: ${current_pool_tvl_usd:,.0f}[/]"
            )
             meta_display.update(base_text + alert_text)
             self.notify(f"В паре {current_quote_sym} нет денег! Переключитесь на {best_quote_sym}", severity="error", timeout=6)
        
        else:
            meta_display.update(base_text)

    @on(Button.Pressed, "#better_pool_suggestion")
    def on_suggestion_clicked(self, event: Button.Pressed):
        target_quote = event.button.name
        if target_quote:
            self.query_one("#trade_quote_select", Select).value = target_quote
            event.button.display = False
            self.notify(f"Валюта переключена на {target_quote}", timeout=2)

    async def _recalculate_trade_amount(self, value: str, silent: bool = False):
        value = value.strip()
        final_amount: Optional[float] = None

        if not value:
            self.cache.set_active_trade_amount_for_quote(None)
            return

        if value.endswith('%'):
            try:
                percentage_value = float(value[:-1])
                if not (0 < percentage_value <= 100):
                    self.cache.set_active_trade_amount_for_quote(None)
                    return

                config = self.cache.get_config()
                active_wallets = self.wallets_cache_ui or self.cache.get_all_wallets(enabled_only=True)
                
                if not active_wallets:
                    self.cache.set_active_trade_amount_for_quote(None)
                    return

                quote_symbol = config.get('default_quote_currency', self.bot_service.config.DEFAULT_QUOTE_CURRENCY) # type: ignore
                
                quote_address: Optional[str] = None
                if quote_symbol == self.bot_service.config.NATIVE_CURRENCY_SYMBOL: # type: ignore
                    quote_address = self.bot_service.config.NATIVE_CURRENCY_ADDRESS # type: ignore
                else:
                    quote_address = self.bot_service.config.QUOTE_TOKENS.get(quote_symbol) # type: ignore
                
                if not quote_address:
                    if not silent:
                        self.notify(f"Адрес квотируемой валюты {quote_symbol} не найден.", title="Ошибка", severity="error", timeout=3)
                    self.cache.set_active_trade_amount_for_quote(None)
                    return

                total_balance = sum(
                    self.cache.get_wallet_balances(w['address']).get(quote_address.lower(), 0.0)
                    for w in active_wallets if w.get('enabled')
                )

                final_amount = total_balance * (percentage_value / 100.0)
                
                if percentage_value == 100:
                    final_amount *= 0.999 

                if not silent:
                    msg = f"Расчет: {final_amount:.12f} {quote_symbol}"
                    if msg != self._last_calc_msg:
                        self.notify(msg, timeout=2)
                        self._last_calc_msg = msg

            except (ValueError, TypeError) as e:
                self.cache.set_active_trade_amount_for_quote(None)
                return
        else:
            try:
                final_amount = float(value)
                if final_amount <= 0:
                    final_amount = None
                self._last_calc_msg = ""
            except ValueError:
                final_amount = None

        self.cache.set_active_trade_amount_for_quote(final_amount)

    @on(Input.Changed, "#amount_input")
    async def on_amount_input_changed(self, event: Input.Changed) -> None:
        await self._recalculate_trade_amount(event.value, silent=False)
    
    @on(Select.Changed, "#trade_quote_select")
    async def on_quote_currency_changed(self, event: Select.Changed):
        if not event.value: return
        new_quote = str(event.value)
        
        await self.cache.update_config({"default_quote_currency": new_quote})
        self.notify(f"Валюта торговли изменена на {new_quote}", timeout=1)

        token_input = self.query_one("#token_input", Input)
        if token_input.value and len(token_input.value) > 40:
            token_addr = token_input.value.strip()
            
            self._is_pool_loading = True
            self.query_one("#token_metadata_display", Static).update(f"Token Info: [yellow]Searching Pool for {new_quote}...[/]")
            
            asyncio.create_task(self.market_data_service.find_and_cache_best_pool(token_addr, new_quote))
            asyncio.create_task(self._run_recommendation_engine(token_addr))
        
        await self.refresh_wallet_table()
        
        amount_input = self.query_one("#amount_input", Input)
        if amount_input.value:
            await self._recalculate_trade_amount(amount_input.value, silent=False)

        await self.trigger_background_approvals()


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
                self.notify("Буфер обмена недоступен.", title="Ошибка", severity="error", timeout=2)
        except Exception:
            self.notify("Не удалось скопировать.", title="Ошибка", severity="error", timeout=2)


    def _update_panel_visuals(self):
        try:
            for panel_id, mode in [("buy_panel", "BUY"), ("sell_panel", "SELL")]:
                self.query_one(f"#{panel_id}", Vertical).set_class(self._active_trade_mode == mode, "active-panel")
        except Exception:
            pass


    def action_change_slippage(self, change: float):
        self.current_slippage = max(0.1, self.current_slippage + change)
        try:
            setting_input = self.query_one("#setting_slippage_input", Input)
            setting_input.value = f"{self.current_slippage:.1f}"
        except Exception: pass
        self.notify(f"Slippage: {self.current_slippage:.1f}%", timeout=1)


    def action_change_gas(self, change: float):
        self.current_gas_price_gwei = max(0.1, self.current_gas_price_gwei + change)
        try:
            setting_gas = self.query_one("#setting_gas_price_input", Input)
            setting_gas.value = f"{self.current_gas_price_gwei:.2f}"
        except Exception: pass
        
        self.notify(f"Gas Price: {self.current_gas_price_gwei:.2f} Gwei", timeout=1)


    def action_set_trade_mode(self, mode: str):
        if self._active_trade_mode != mode:
            self._active_trade_mode = mode
            self.notify(f"Режим: {self._active_trade_mode}", timeout=1)
            self._update_panel_visuals()

    async def _animate_button(self, btn: Button):
        btn.add_class("button-pressed")
        await asyncio.sleep(0.1)
        btn.remove_class("button-pressed")

    async def action_execute_trade(self):
        if self.query_one(TabbedContent).active != "trade_tab": 
            return

        try:
            # Находим нужную кнопку
            btn_id = "#buy_button" if self._active_trade_mode == "BUY" else "#sell_button"
            btn = self.query_one(btn_id, Button)
            # Если она активна - запускаем анимацию "нажатия"
            if not btn.disabled:
                asyncio.create_task(self._animate_button(btn))
        except Exception:
            pass
        
        token_input = self.query_one("#token_input", Input)
        amount_input = self.query_one("#amount_input", Input) 

        token_addr = token_input.value.strip()
        if not token_addr or len(token_addr) < 40:
            return self.notify("Введите адрес токена!", title="Ошибка", severity="error")

        wallets_to_trade = [w['address'] for w in self.wallets_cache_ui if w.get('enabled')]
        if not wallets_to_trade:
            wallets_to_trade = [w['address'] for w in self.cache.get_all_wallets(enabled_only=True)]
            if not wallets_to_trade:
                return self.notify("Нет активных кошельков.", title="Ошибка", severity="error")

        config = self.cache.get_config()
        quote_token_symbol = config.get('default_quote_currency', self.bot_service.config.DEFAULT_QUOTE_CURRENCY) # type: ignore
        
        final_trade_amount = 0.0
        display_symbol = quote_token_symbol

        if self._active_trade_mode == "SELL":
            total_tokens_wei = 0
            decimals = self.cache.get_token_decimals(token_addr) or 18
            for w_addr in wallets_to_trade:
                wei = self.cache.get_exact_balance_wei(w_addr, token_addr)
                if wei:
                    total_tokens_wei += wei
                else:
                    bal_float = self.cache.get_wallet_balances(w_addr).get(token_addr.lower(), 0.0)
                    total_tokens_wei += int(bal_float * (10**decimals))
            
            if total_tokens_wei > 0:
                final_trade_amount = total_tokens_wei / (10**decimals)
                meta = await self.cache.db.get_token_metadata(token_addr)
                if meta and meta.get('symbol'): display_symbol = meta['symbol']
                else: display_symbol = "TOKENS"
            else:
                final_trade_amount = 0.0
                display_symbol = "PENDING TOKENS"

        else: # BUY
            final_trade_amount = self.cache.get_active_trade_amount_for_quote()
            
            if (final_trade_amount is None or final_trade_amount <= 0) and amount_input.value:
                val_str = amount_input.value.strip()
                try:
                    if val_str.endswith('%'):
                        try:
                            percentage_value = float(val_str[:-1])
                            if 0 < percentage_value <= 100:
                                quote_address = None
                                if quote_token_symbol == self.bot_service.config.NATIVE_CURRENCY_SYMBOL: # type: ignore
                                    quote_address = self.bot_service.config.NATIVE_CURRENCY_ADDRESS # type: ignore
                                else:
                                    quote_address = self.bot_service.config.QUOTE_TOKENS.get(quote_token_symbol) # type: ignore
                                
                                if quote_address:
                                    active_wallets_fresh = self.cache.get_all_wallets(enabled_only=True)
                                    total_balance = sum(
                                        self.cache.get_wallet_balances(w['address']).get(quote_address.lower(), 0.0)
                                        for w in active_wallets_fresh
                                    )
                                    final_trade_amount = total_balance * (percentage_value / 100.0)
                                    if percentage_value == 100: final_trade_amount *= 0.999
                        except Exception: pass
                    else:
                        val = float(val_str)
                        if val > 0: final_trade_amount = val
                except Exception: pass

        if self._active_trade_mode == "BUY":
            if final_trade_amount is None or final_trade_amount <= 0:
                return self.notify(f"Сумма 0 или ошибка расчета.", title="Ошибка суммы", severity="error")

        if not all(i.is_valid for i in [token_input, amount_input]):
            return self.notify("Проверьте поля ввода.", title="Ошибка ввода", severity="error")
        
        trade_req = TradeRequest(
            token_address=token_input.value, 
            quote_token=quote_token_symbol, 
            action=self._active_trade_mode.lower(), # type: ignore
            amount=final_trade_amount,  # type: ignore
            wallets=wallets_to_trade, 
            slippage=self.current_slippage, 
            max_fee_cents=self.current_max_fee_cents,
            gas_price_gwei=self.current_gas_price_gwei
        )
        
        await log.info(f"TUI: START TRADE -> {self._active_trade_mode} {final_trade_amount:.6f} {display_symbol} @ {self.current_gas_price_gwei} Gwei")

        response = await self.bot_service.schedule_trades(trade_req)

        if response.get("status") == "success":
            pass
        else:
            self.notify(response.get('message', 'Ошибка'), title="Ошибка трейда", severity="error")


    def action_switch_tab(self, tab_id: str):
        self.query_one(TabbedContent).active = tab_id

    def compose(self) -> ComposeResult:
        with Horizontal(id="app_header"):
            with Horizontal(id="network_selector_bar"):
                yield Label("Текущая сеть:", id="network_label")
                yield Select(options=[(net.upper(), net) for net in self.available_networks], value=self.current_network, id="network_select")
        
        with Container(id="status_bar_container"):
            with Container(id="status_bar"):
                yield StatusRPC("Sys: -")
                yield StatusWallets("Wallets: -")

        with TabbedContent(initial="trade_tab", id="main_tabs"):
            with TabPane("Торговля", id="trade_tab"):
                with VerticalScroll(id="main_trade_scroller"):
                    with Horizontal(id="input_row_container"):
                        with Vertical(id="token_input_group"):
                            with Horizontal(classes="label-row"):
                                yield Label(" Адрес токена (0x...):", classes="input-label")
                                yield Static("Token Info: -", id="token_metadata_display")
                            yield Input(placeholder="Вставьте адрес токена (Ctrl + Shift + V)", id="token_input", validators=[AddressValidator()])
                        
                        with Vertical(id="amount_input_group"):
                            yield Button("💡 Рекомендация", id="better_pool_suggestion", variant="warning")
                            yield Label(" Сумма / Валюта:", classes="input-label")
                            with Horizontal(classes="input-row"):
                                yield Input(id="amount_input", validators=[AmountValidator()], classes="half-width-input")
                                yield Select(options=[], id="trade_quote_select", classes="half-width-select")

                    with Horizontal(id="trade_panels_container"):
                        with Vertical(id="buy_panel"):
                            yield Label("BUY", classes="trade-panel-title")
                            yield Button("КУПИТЬ", variant="success", id="buy_button", disabled=True)
                        with Vertical(id="sell_panel"):
                            yield Label("SELL", classes="trade-panel-title")
                            yield Button("ПРОДАТЬ", variant="error", id="sell_button", disabled=True)

                    yield Label("Информация о токене:", id="pnl_tvl_label")
                    yield DataTable(id="pnl_tvl_table")
                    
                    yield Label("Активные кошельки:", id="balances_label")
                    yield DataTable(id="balances_table")

            with TabPane("Кошельки", id="wallets_tab"):
                with VerticalScroll(id="wallets_scroll_container"):
                    yield DataTable(id="wallets_table")
                    with Vertical(id="add_wallet_form"):
                        yield Label("Добавить новый кошелек:", classes="form-title")
                        yield Input(placeholder="Название", id="new_wallet_name_input")
                        yield Input(placeholder="Приватный ключ", id="new_wallet_pk_input", password=True)
                        yield Button("Сохранить", variant="success", id="save_new_wallet_button")
                with Horizontal(classes="table-buttons"):
                    yield Button("Удалить выбранный", id="delete_wallet_button", variant="error")

            with TabPane("Настройки", id="settings_tab"):
                with VerticalScroll(id="settings_scroll_container"):
                    with Vertical(classes="settings-group"):
                        yield Label("Основные настройки", classes="settings-title")
                        yield Label(" RPC URL:", classes="input-label")
                        yield Input(id="setting_rpc_url_input", validators=[URL()])
                        yield Label(" Стейблкоин:", classes="input-label")
                        quote_tokens = list(self.bot_service.config.QUOTE_TOKENS.keys()) # type: ignore
                        yield Select(options=[(token, token) for token in sorted(quote_tokens)], id="setting_quote_currency_select")
                    
                    with Vertical(classes="settings-group"):
                        yield Label("⛽ Авто-закупка газа (Auto-Fuel)", classes="settings-title")
                        yield Label("Включить авто-пополнение газа:", classes="input-label")
                        yield Select(options=[("Выкл", "False"), ("Вкл", "True")], id="setting_autofuel_enable", value="False")
                        
                        yield Label(f"Порог срабатывания ({self.bot_service.config.NATIVE_CURRENCY_SYMBOL}):", classes="input-label")
                        yield Input(id="setting_autofuel_threshold", placeholder="0.005", validators=[FloatValidator()])
                        
                        yield Label(f"Сколько докупать ({self.bot_service.config.NATIVE_CURRENCY_SYMBOL}):", classes="input-label")
                        yield Input(id="setting_autofuel_amount", placeholder="0.02", validators=[FloatValidator()])

                    with Vertical(classes="settings-group"):
                        yield Label("Настройки транзакций", classes="settings-title")
                        yield Label(" Default Gas Price (Gwei):", classes="input-label")
                        yield Input(id="setting_gas_price_input", validators=[FloatValidator()])
                        yield Label(" Проскальзывание по умолчанию (%):", classes="input-label")
                        yield Input(id="setting_slippage_input", validators=[FloatValidator()])
                        yield Label(" Сумма трейда по умолчанию (напр. 0.1 или 25%):", classes="input-label")
                        yield Input(id="setting_trade_amount_input", validators=[AmountValidator()])
                        yield Label(" Gas Limit (max units):", classes="input-label")
                        yield Input(id="setting_gas_limit_input", validators=[IntegerValidator()])

            with TabPane("Логи", id="logs_tab"):
                yield RichLog(id="log_output", wrap=True, highlight=True)

            with TabPane("Помощь", id="help_tab"):
                with VerticalScroll():   
                    yield Markdown(HELP_TEXT, id="help_markdown")

        yield Footer()
        
    async def load_and_apply_settings(self):
        config = self.cache.get_config()
        self.query_one("#setting_rpc_url_input", Input).value = config.get('rpc_url', self.bot_service.config.RPC_URL) # type: ignore
        self.query_one("#setting_quote_currency_select", Select).value = config.get('default_quote_currency', self.bot_service.config.DEFAULT_QUOTE_CURRENCY) # type: ignore
        
        self.query_one("#setting_slippage_input", Input).value = str(config.get('slippage', 15.0))
        self.query_one("#setting_trade_amount_input", Input).value = str(config.get('default_trade_amount', '0.01'))
        
        gas_limit = config.get('gas_limit', 350000)
        self.query_one("#setting_gas_limit_input", Input).value = str(gas_limit)
        
        gas_price_gwei = config.get('default_gas_price_gwei', self.bot_service.config.DEFAULT_GAS_PRICE_GWEI) # type: ignore
        self.query_one("#setting_gas_price_input", Input).value = str(gas_price_gwei)
        
        self.query_one("#amount_input", Input).value = str(config.get('default_trade_amount', '0.1'))
        
        self.query_one("#setting_autofuel_enable", Select).value = str(config.get('auto_fuel_enabled', 'False'))
        self.query_one("#setting_autofuel_threshold", Input).value = str(config.get('auto_fuel_threshold', '0.005'))
        self.query_one("#setting_autofuel_amount", Input).value = str(config.get('auto_fuel_amount', '0.02'))
        
        self.current_slippage = float(config.get('slippage', 15.0))
        self.current_gas_price_gwei = float(gas_price_gwei)
        self.current_max_fee_cents = int(config.get('max_fee_cents', 10))


    async def on_mount(self) -> None:
        self.title = f"DEX Bot - {self.bot_service.config.NAME}" # type: ignore
        log_widget = self.query_one("#log_output", RichLog)
        self._rich_log_handler = TextualRichLogHandler(log_widget)
        await log.set_custom_handler(self._rich_log_handler.emit)
        self.query_one("#wallets_table", DataTable).add_columns("Название", "Адрес", "Статус (Клик)")
        self.query_one("#pnl_tvl_table", DataTable).add_columns("Token", "TVL ($)", "PnL", "PnL Abs.")
        self.query_one("#balances_table", DataTable).add_columns("Кошелек", "NATIVE", "QUOTE")
        
        quote_tokens = list(self.bot_service.config.QUOTE_TOKENS.keys()) # type: ignore
        quote_tokens.sort(key=lambda x: x != self.bot_service.config.NATIVE_CURRENCY_SYMBOL) # type: ignore
        
        trade_select = self.query_one("#trade_quote_select", Select)
        trade_select.set_options([(token, token) for token in quote_tokens])
        
        current_config = self.cache.get_config()
        current_quote = current_config.get('default_quote_currency', self.bot_service.config.DEFAULT_QUOTE_CURRENCY) # type: ignore
        trade_select.value = current_quote

        self.status_update_task = asyncio.create_task(self.status_update_loop())
        self.run_worker(self._notification_watcher())
        self.run_worker(self.ui_updater_worker())

        await self.load_and_apply_settings()
        self.ui_update_queue.put_nowait("wallets")
        self._update_panel_visuals()
        await self.trigger_background_approvals()


    @on(Select.Changed, "#network_select")
    def on_network_changed(self, event: Select.Changed):
        new_network = str(event.value)
        if new_network != self.current_network:
            self.notify(f"Переключение на сеть {new_network.upper()}...", timeout=2)
            self.exit(result=new_network)


    async def on_unmount(self):
        if self.status_update_task: self.status_update_task.cancel()


    async def status_update_loop(self):
        counter = 0
        while True:
            try:
                try:
                    status_rpc_widget = self.query_one(StatusRPC)
                    status_wallets_widget = self.query_one(StatusWallets)
                    metadata_display = self.query_one("#token_metadata_display", Static)
                    pnl_tvl_table = self.query_one("#pnl_tvl_table", DataTable)
                except Exception:
                    await asyncio.sleep(1)
                    continue

                # 1. Системный чек (раз в 10 сек)
                if counter % 5 == 0:
                    command = APICommand(type="system", data={"action": "health"})
                    response = await self.api_router.process_command(command, self.cache)
                    status_rpc_widget.update_content("OK" if response.status == 'success' and response.data.get('healthy') else "ERROR", True)

                # 2. Проверка изменений в кошельках
                new_wallets_data = self.cache.get_all_wallets()
                if new_wallets_data != self.wallets_cache_ui:
                    self.wallets_cache_ui = new_wallets_data
                    self.ui_update_queue.put_nowait("wallets")
                
                active_token = self.cache.get_active_trade_token()
                if active_token:
                    config = self.cache.get_config()
                    quote_symbol = config.get('default_quote_currency', self.bot_service.config.DEFAULT_QUOTE_CURRENCY)
                    quote_address = self.bot_service.config.QUOTE_TOKENS.get(quote_symbol, "").lower()
                    
                    # Получаем корректные decimals для расчетов
                    q_decimals = self.cache.get_token_decimals(quote_address) or 18
                    
                    token_symbol_plain = "TOKEN"
                    meta = await self.cache.db.get_token_metadata(active_token)
                    if meta and meta.get('symbol'):
                        token_symbol_plain = meta['symbol']
                    
                    pool_info = self.cache.get_best_pool(active_token, quote_address)
                    pool_status_str = ""

                    if pool_info:
                        self._is_pool_loading = False 
                        if "error" in pool_info: 
                            pool_status_str = "[bold red](No Pool)[/]"
                        else:
                            pool_type = pool_info['type']
                            pool_status_str = f"[bold green]({pool_type})[/]"
                    else:
                        self._is_pool_loading = True
                        pool_status_str = "[yellow](Searching...)[/]"
                    
                    metadata_display.update(f"Active: [bold cyan]{token_symbol_plain}[/] {pool_status_str}")

                    # --- TVL (Обновляется из Python кэша) ---
                    tvl_val_str = "[dim]0[/]"
                    if RUST_AVAILABLE and pool_info and "address" in pool_info:
                        all_balances_raw = await asyncio.to_thread(dexbot_core.get_all_pool_balances) # type: ignore
                        if all_balances_raw:
                            all_balances = {k.strip('"').strip("'").lower(): v for k, v in all_balances_raw.items()}
                            pool_addr_lower = pool_info['address'].lower()
                            if pool_addr_lower in all_balances:
                                balance_wei = float(all_balances[pool_addr_lower])
                                price = self.cache.get_quote_price(quote_symbol) or 1.0
                                tvl_usd = (balance_wei / (10**q_decimals)) * price * 2
                                tvl_val_str = f"[green]${tvl_usd:,.0f}[/]"

                    # --- PnL (Обновляется напрямую из Rust Core) ---
                    pnl_percent_str, pnl_abs_str = "[dim]0%[/]", "[dim]0.00[/]"
                    total_balance_of_token = 0.0
                    
                    if RUST_AVAILABLE and self.wallets_cache_ui:
                        total_cost_usd, total_value_usd, any_loading = 0.0, 0.0, False
                        
                        for wallet in self.wallets_cache_ui:
                            w_addr = wallet['address']
                            total_balance_of_token += self.cache.get_wallet_balances(w_addr).get(active_token.lower(), 0.0)
                            
                            if not wallet.get('enabled'): continue
                            
                            # Запрашиваем состояние у Rust
                            pnl_data = await asyncio.to_thread(dexbot_core.get_pnl_status, w_addr, active_token) # type: ignore
                            if pnl_data:
                                p_pct, val_wei, cost_wei, is_load = pnl_data
                                if is_load: any_loading = True
                                
                                # ВАЖНО: Делим на ПРАВИЛЬНЫЕ decimals квотируемого токена!
                                total_value_usd += float(val_wei) / (10**q_decimals)
                                total_cost_usd += float(cost_wei) / (10**q_decimals)
                        
                        if total_balance_of_token <= 0:
                            pnl_percent_str, pnl_abs_str = "[dim]SOLD[/]", "[dim]0.00[/]"
                        elif any_loading:
                            pnl_percent_str, pnl_abs_str = "[yellow]Calc...[/]", "[yellow]...[/]"
                        elif total_cost_usd > 0:
                            abs_pnl = total_value_usd - total_cost_usd
                            pnl_pct = (abs_pnl / total_cost_usd) * 100.0
                            color = "green" if abs_pnl >= 0 else "red"
                            sign = "+" if abs_pnl >= 0 else ""
                            pnl_percent_str = f"[{color}]{sign}{pnl_pct:.2f}%[/]"
                            pnl_abs_str = f"[{color}]{sign}{abs_pnl:.12f} {quote_symbol}[/]"
                        else:
                            pnl_percent_str, pnl_abs_str = "0%", "0.00"

                    # Принудительное обновление строк таблицы
                    pnl_tvl_table.clear()
                    pnl_tvl_table.add_row(
                        token_symbol_plain, 
                        Text.from_markup(tvl_val_str), 
                        Text.from_markup(pnl_percent_str), 
                        Text.from_markup(pnl_abs_str)
                    )
                else:
                    metadata_display.update("Token Info: [dim]None[/]")
                    pnl_tvl_table.clear()
                
                self._update_trade_buttons_state()
                has_active = any(w.get('enabled') for w in self.wallets_cache_ui)
                status_wallets_widget.update_content(has_active)
                
                counter += 1
            except Exception as e:
                await log.error(f"UI Loop Error: {e}")
            
            await asyncio.sleep(1.0) 
    

    async def ui_updater_worker(self):
        while True:
            try:
                update_type = await self.ui_update_queue.get()
                if update_type == "wallets":
                    await self.refresh_wallet_table()
                self.ui_update_queue.task_done()
            except asyncio.CancelledError:
                break
            except Exception as e:
                await log.error(f"Ошибка в воркере обновления UI: {e}")


    @on(TabbedContent.TabActivated, "#main_tabs")
    async def on_tab_activated(self, event: TabbedContent.TabActivated):
        if event.pane.id == "logs_tab" and self._rich_log_handler:
            log_output = self.query_one("#log_output", RichLog)
            log_output.clear()
            [log_output.write(msg) for msg in self._rich_log_handler.get_last_messages()]
        elif event.pane.id == "wallets_tab":
            self.ui_update_queue.put_nowait("wallets")
        elif event.pane.id == "trade_tab":
            self.ui_update_queue.put_nowait("wallets")
        elif event.pane.id == "settings_tab":
            await self.load_and_apply_settings()


    @on(DataTable.CellSelected, "#wallets_table")
    async def on_wallets_cell_clicked(self, event: DataTable.CellSelected):
        row_key = event.cell_key.row_key.value
        col_index = event.coordinate.column
        if col_index == 1:
            await self._copy_to_clipboard(row_key, "Адрес кошелька") # type: ignore
        elif col_index == 2:
            target_wallet = next((w for w in self.wallets_cache_ui if w['address'] == row_key), None)
            if target_wallet:
                new_status = not target_wallet['enabled']
                command = APICommand(type="wallets", data={"action": "update", "address": row_key, "update": {"enabled": new_status}})
                self.notify(f"{'Включение' if new_status else 'Выключение'} кошелька...", timeout=1)
                response = await self.api_router.process_command(command, self.cache)
                if response.status == 'success':
                    if new_status:
                        await self.bot_service.schedule_quote_token_approvals([row_key], self.current_gas_price_gwei) # type: ignore
                else:
                    self.notify(f"Ошибка: {response.error}", severity="error")


    async def action_reload_wallets(self):
        self.ui_update_queue.put_nowait("wallets")
        await self.trigger_background_approvals()
        self.notify("Запрошено обновление кошельков, запущена проверка Approve.", severity="information")


    async def refresh_wallet_table(self):
        wallets_table = self.query_one("#wallets_table", DataTable)
        balances_table = self.query_one("#balances_table", DataTable)
        current_cursor = wallets_table.cursor_coordinate
        wallets_table.clear()
        balances_table.clear()
        config_from_db = self.cache.get_config()
        quote_symbol = config_from_db.get('default_quote_currency', self.bot_service.config.DEFAULT_QUOTE_CURRENCY) # type: ignore
        native_symbol = self.bot_service.config.NATIVE_CURRENCY_SYMBOL # type: ignore
        if not wallets_table.columns:
            wallets_table.add_columns("Название", "Адрес", "Статус (Клик)")
        balances_table.columns.clear()
        balances_table.add_columns("Кошелек", f"{native_symbol}(fee)", f"{quote_symbol}(quote)")
        for w in self.wallets_cache_ui:
            status_render = Text("▣ Активен", style="bold green") if w['enabled'] else Text("▢ Выключен", style="dim white")
            wallets_table.add_row(w['name'], Text(w['address']), status_render, key=w['address'])
            if w['enabled']:
                balances = self.cache.get_wallet_balances(w['address'])
                native_balance = balances.get(self.bot_service.config.NATIVE_CURRENCY_ADDRESS.lower(), 0.0) # type: ignore
                quote_address = self.bot_service.config.QUOTE_TOKENS.get(quote_symbol) # type: ignore
                quote_balance = 0.0
                if quote_address:
                        quote_balance = balances.get(quote_address.lower(), 0.0)
                elif quote_symbol == native_symbol:
                    quote_balance = native_balance
                balances_table.add_row(w['name'], f"{native_balance:.12f}", f"{quote_balance:.12f}")
        if current_cursor and current_cursor.row < len(self.wallets_cache_ui):
            wallets_table.move_cursor(row=current_cursor.row, column=current_cursor.column, animate=False)


    @on(Button.Pressed)
    async def on_button_pressed(self, event: Button.Pressed):
        button_id = event.button.id
        if button_id == "save_new_wallet_button":
            name_input, pk_input = self.query_one("#new_wallet_name_input", Input), self.query_one("#new_wallet_pk_input", Input)
            if not name_input.value or not pk_input.value:
                return self.notify("Название и приватный ключ не могут быть пустыми.", title="Ошибка", severity="error")
            private_key = pk_input.value.strip()
            if len(private_key) == 64 and not private_key.startswith("0x"):
                private_key = "0x" + private_key
            wallet_data = WalletCreate(name=name_input.value, private_key=private_key)
            command = APICommand(type="wallets", data={"action": "add", "wallet": wallet_data.model_dump()})
            response = await self.api_router.process_command(command, self.cache)
            if response.status == 'success':
                self.notify(f"Кошелек '{name_input.value}' добавлен", title="Успех")
                name_input.value, pk_input.value = "", ""
                new_wallet_address = response.data['address']

                if RUST_AVAILABLE:
                    try:
                        rpc_url = self.cache.get_config().get('rpc_url', self.bot_service.config.RPC_URL) # type: ignore
                        await asyncio.to_thread(dexbot_core.add_wallet_to_monitor, new_wallet_address) # type: ignore
                        await log.info(f"[TUI] Кошелек {new_wallet_address} добавлен в мониторинг Rust-ядра.")
                        await asyncio.to_thread(dexbot_core.force_resync_nonce, new_wallet_address) # type: ignore
                    except Exception as e:
                        await log.error(f"[TUI] Не удалось добавить кошелек в мониторинг Rust: {e}")
                
                await self.bot_service.schedule_quote_token_approvals([new_wallet_address], self.current_gas_price_gwei)
            else:
                self.notify(response.error, title="Ошибка добавления", severity="error") # type: ignore

        elif button_id == "delete_wallet_button":
            table = self.query_one("#wallets_table", DataTable)
            if table.cursor_row < 0:
                return self.notify("Сначала выберите кошелек в таблице", title="Внимание", severity="warning")
            row_data = table.get_row_at(table.cursor_row)
            if not row_data or len(row_data) < 2:
                return self.notify("Не удалось получить данные о кошельке", title="Ошибка", severity="error")
            address_to_delete = row_data[1].plain
            name_to_delete = row_data[0]
            command = APICommand(type="wallets", data={"action": "delete", "address": address_to_delete})
            response = await self.api_router.process_command(command, self.cache)
            if response.status == 'success':
                self.notify(f"Кошелек {name_to_delete} удален.", title="Успех")
                if RUST_AVAILABLE:
                    try:
                        await asyncio.to_thread(dexbot_core.remove_wallet_from_monitor, address_to_delete) # type: ignore
                        await log.info(f"[TUI] Кошелек {address_to_delete} удален из мониторинга Rust-ядра.")
                    except Exception as e:
                        await log.error(f"[TUI] Не удалось удалить кошелек из мониторинга Rust: {e}")
            else:
                self.notify(response.error, title="Ошибка удаления", severity="error") # type: ignore

        elif button_id == "buy_button":
            self.action_set_trade_mode("BUY")
            await self.action_execute_trade()

        elif button_id == "sell_button":
            self.action_set_trade_mode("SELL")
            await self.action_execute_trade()


    async def action_save_settings(self):
        if self.query_one(TabbedContent).active != "settings_tab":
            return

        inputs = {
            "rpc_url": self.query_one("#setting_rpc_url_input", Input),
            "default_quote_currency": self.query_one("#setting_quote_currency_select", Select),
            "slippage": self.query_one("#setting_slippage_input", Input),
            "default_trade_amount": self.query_one("#setting_trade_amount_input", Input),
            "gas_limit": self.query_one("#setting_gas_limit_input", Input),
            "gas_price": self.query_one("#setting_gas_price_input", Input),
            "fuel_thresh": self.query_one("#setting_autofuel_threshold", Input),
            "fuel_amount": self.query_one("#setting_autofuel_amount", Input),
        }

        if not all(i.is_valid for i in inputs.values() if isinstance(i, Input)):
            return self.notify("Проверьте правильность данных", title="Ошибка", severity="error")

        current_rpc = self.cache.get_config().get('rpc_url')
        if not current_rpc:
            current_rpc = self.bot_service.config.RPC_URL # type: ignore

        new_rpc = inputs["rpc_url"].value.strip()
        rpc_changed = new_rpc != current_rpc

        fuel_enable_str = str(self.query_one("#setting_autofuel_enable", Select).value)
        fuel_enabled = True if fuel_enable_str == "True" else False

        config_upd = ConfigUpdate(
            rpc_url=new_rpc,
            default_quote_currency=str(inputs["default_quote_currency"].value),
            slippage=float(inputs["slippage"].value),
            default_trade_amount=inputs["default_trade_amount"].value, 
            gas_limit=int(inputs["gas_limit"].value),
            default_gas_price_gwei=float(inputs["gas_price"].value),
            auto_fuel_enabled=fuel_enabled,
            auto_fuel_threshold=float(inputs["fuel_thresh"].value),
            auto_fuel_amount=float(inputs["fuel_amount"].value),
        )

        command = APICommand(type="config", data={"action": "update", "config":
                            config_upd.model_dump(exclude_unset=True)})

        response = await self.api_router.process_command(command, self.cache)
        if response.status == 'success':
            if rpc_changed:
                self.notify("RPC изменен. Перезапуск бота...", severity="warning", timeout=3)
                await asyncio.sleep(1)
                self.exit(result="RESTART_SAME_NETWORK")
            else:
                self.notify("Настройки сохранены.", title="Успех")
                await self.load_and_apply_settings()
                await self.trigger_background_approvals()
        else:
            self.notify(response.error, title="Ошибка сохранения", severity="error") # type: ignore


    async def _notification_watcher(self) -> None:
        while True:
            result = await self.notification_queue.get()
            status = result.get('status')
            wallet = result.get('wallet', 'Unknown')
            action_str = result.get("action", "Операция") or "Операция"
            short_wallet = f"{wallet[:6]}...{wallet[-4:]}" if len(wallet) > 10 else wallet
            message = result.get('message', '')

            if status == 'success':
                action_lower = action_str.lower()
                if "approve" in action_lower:
                    self.notification_queue.task_done()
                    continue

            if status == 'warning':
                self.notify(f"⚠️ {message}", title="Внимание", severity="warning", timeout=5)
            
            elif status == 'autofuel_success':
                self.notify(f"Закуплено {message}", title="⛽ AUTO-FUEL", severity="information", timeout=4)
            
            elif status == 'autofuel_error':
                self.notify(f"Ошибка закупки: {message}", title="⛽ AUTO-FUEL ERROR", severity="error", timeout=5)

            elif status == 'success':
                self.notify(f"Сделка успешна для {short_wallet}", title=f"✅ Успех {action_str}", severity="information", timeout=3)
            
            elif status == 'error':
                msg = message or 'Неизвестная ошибка'
                if len(msg) > 100: msg = msg[:100] + "..."
                self.notify(f"Ошибка у {short_wallet}: {msg}", title=f"❌ Ошибка {action_str}", severity="error", timeout=6)
            
            self.notification_queue.task_done()