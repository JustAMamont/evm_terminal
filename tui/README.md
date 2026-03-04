# TUI Module — Textual Interface

Текстовый интерфейс терминала на базе **Textual**. Event-driven архитектура с реактивным обновлением UI.

---

## Архитектура

```
+-----------------------------------------------------------+
|                     TradingApp (App)                      |
+-----------------------------------------------------------+
|  +----------------+  +---------------------------------+  |
|  | Event Loop     |  | Rust Event Listener             |  |
|  | - status_update|  | - _rust_event_listener()        |  |
|  | - ui_updater   |  | - handle_rust_event()           |  |
|  | - notifications|  | - _rust_event_handlers dispatch |  |
|  +----------------+  +---------------------------------+  |
+-----------------------------------------------------------+
|  +----------------+  +---------------------------------+  |
|  | TxStatusTracker|  | State                           |  |
|  | - pending_txs  |  | - _current_token_address        |  |
|  | - positions    |  | - _current_pool_info            |  |
|  | - latency      |  | - _market_data                  |  |
|  +----------------+  | - wallets_cache_ui              |  |
|                      +---------------------------------+  |
+-----------------------------------------------------------+
|                    UI Components                          |
|  +----------+ +----------+ +----------+ +--------------+  |
|  |StatusRPC | |StatusGas | |StatusWS  | |StatusWallets |  |
|  +----------+ +----------+ +----------+ +--------------+  |
|  +-----------------------------------------------------+  |
|  |                   TabbedContent                     |  |
|  |  [Trade] [Wallets] [Settings] [Logs] [Help]         |  |
|  +-----------------------------------------------------+  |
+-----------------------------------------------------------+
```

---

## Компоненты

### Статус-бар

| Widget | Описание | Обновление |
|--------|----------|------------|
| `StatusRPC` | Статус RPC ноды | `_evt_rpc_status`, `_evt_engine_ready` |
| `StatusConnection` | WebSocket статус | `_evt_connection_status` |
| `StatusGas` | Текущая цена газа | `_evt_gas_price` |
| `StatusWallets` | Наличие активных кошельков | `ui_updater_worker` |

### Вкладки

```
trade_tab     --> Token input, amount, BUY/SELL panels, market data
wallets_tab   --> Wallets table, add form
settings_tab  --> RPC, quote currency, auto-fuel, slippage, gas
logs_tab      --> RichLog with 500 message buffer
help_tab      --> Markdown help
```

---

## Event Dispatcher

События от Rust ядра обрабатываются через словарь `_rust_event_handlers`:

```python
_rust_event_handlers = {
    "EngineReady": _evt_engine_ready,
    "ConnectionStatus": _evt_connection_status,
    "RPCError": _evt_rpc_error,
    "RPCStatus": _evt_rpc_status,
    "GasPriceUpdate": _evt_gas_price,
    "BalanceUpdate": _evt_balance_update,
    "PoolDetected": _evt_pool_detected,
    "PoolError": _evt_pool_error,
    "PoolUpdate": _evt_pool_update,
    "PoolNotFound": _evt_pool_not_found,
    "ImpactUpdate": _evt_impact_update,
    "TxSent": _evt_tx_sent,
    "TxConfirmed": _evt_tx_confirmed,
    "TradeStatus": _handle_trade_status,
    "AutoFuelError": _evt_autofuel_error,
    "Log": _evt_log
}
```

### Цепочка обработки

```
Rust Event -> _rust_event_listener() -> handle_rust_event()
                                              |
                                              v
                                    _rust_event_handlers[type](data)
                                              |
                                              v
                                    UI Update / State Change
```

---

## Состояние UI

### `_market_data`

```python
{
    'pool_type': str,        # V2/V3
    'pool_address': str,
    'tvl_usd': float,
    'fee_bps': int,
    'impact_buy': float,     # Price impact для покупки
    'impact_sell': float,    # Price impact для продажи
    'current_price': float,
    'pos_cost_quote': float, # Стоимость позиции в quote
    'pos_amount': float,     # Количество токенов в позиции
    'token_symbol': str
}
```

### `_current_pool_info`

```python
{
    'pool_type': str,
    'address': str,
    'fee': int,
    'liquidity_usd': float,
    'token': str
}
```

---

## Горячие клавиши

| Binding | Action | Описание |
|---------|--------|----------|
| `Ctrl+Q` | `quit` | Выход |
| `Ctrl+R` | `reload_wallets` | Ресинк балансов |
| `T` | `switch_tab('trade_tab')` | Вкладка торговли |
| `W` | `switch_tab('wallets_tab')` | Вкладка кошельков |
| `S` | `switch_tab('settings_tab')` | Вкладка настроек |
| `L` | `switch_tab('logs_tab')` | Вкладка логов |
| `F` | `switch_tab('help_tab')` | Справка |
| `↑` | `set_trade_mode('BUY')` | Режим покупки |
| `↓` | `set_trade_mode('SELL')` | Режим продажи |
| `Enter` | `execute_trade` | Исполнить ордер |
| `Delete` | `clear_token_input` | Очистить токен |
| `Shift+↑` | `change_slippage(+0.5)` | +0.5% slippage |
| `Shift+↓` | `change_slippage(-0.5)` | -0.5% slippage |
| `Shift+→` | `change_gas(+0.1)` | +0.1 Gwei |
| `Shift+←` | `change_gas(-0.1)` | -0.1 Gwei |

---

## Фоновые задачи

При `on_mount` запускаются:

```python
_background_tasks = [
    ui_updater_worker(),       # Обработка ui_update_queue
    _rust_event_listener(),    # Чтение событий из bridge
    status_update_loop(),      # Периодическое обновление статуса
    _notification_watcher()    # Обработка notification_queue
]
```

### `ui_update_queue`

Типы обновлений:
- `"refresh_balances"` → `_refresh_wallet_table()`
- `"refresh_all"` → `_load_and_apply_settings()` + `_refresh_wallet_table()`
- `"refresh_market_data"` → `_update_market_data_table()`
- `"wallets"` → `_refresh_wallet_table()`

---

## Торговля

### BUY Flow

```
action_execute_trade()
    |
    +--> _prepare_buy_data() -> amount, quote_symbol
    |
    +--> bridge.send(EngineCommand.execute_trade(...))
              |
              v (Rust)
         TxSent -> _evt_tx_sent() -> record in _tx_tracker
              |
              v
         TradeStatus(sent) -> _update_position_memory_on_send()
              |
              v
         TxConfirmed -> _evt_tx_confirmed() -> notify user
```

### SELL Flow

```
action_execute_trade()
    |
    +--> _prepare_sell_data() -> amount from get_or_load_balance_wei()
    |
    +--> bridge.send(EngineCommand.execute_trade(...))
              |
              v (Rust)
         TxSent -> _evt_tx_sent()
              |
              v
         TradeStatus(sent) -> subtract_token_balance()
              |
              v
         TxConfirmed(success) -> close_position_memory()
              |
              v (if failed)
         Rollback -> add_token_balance()
```

---

## TxStatusTracker

Отслеживание транзакций с измерением latency:

```python
class TxStatusTracker:
    _pending_txs: Dict[str, Dict]  # tx_hash → tx_info
    _positions: Dict[str, List]    # "wallet:token" → [{amount, tx_hash, ...}]
    
    record_tx_sent(tx_hash, wallet, action, amount, token) → send_time
    confirm_tx(tx_hash, gas_used, status) → result with latency_ms
    get_position(wallet, token) → List[Dict]
    clear_position(wallet, token)
```

---

## Интеграция с Cache

| Метод Cache | Использование |
|-------------|---------------|
| `get_all_wallets()` | Загрузка в `wallets_cache_ui` |
| `get_position_memory()` | PnL расчет |
| `update_position_memory()` | При BUY |
| `close_position_memory()` | При SELL success |
| `get_exact_balance_wei()` | Количество токенов для SELL |
| `set_exact_balance_wei()` | При BalanceUpdate |
| `get_active_trade_token()` | Текущий токен |
| `set_active_trade_token()` | При вводе адреса |

---

## CSS Classes

Файл: `app.css`

Ключевые классы:
- `.active-panel` — подсветка активной панели BUY/SELL
- `.button-pressed` — анимация нажатия кнопки
- `.label-row` — строка с лейблом и значением
- `.settings-group` — группа настроек
- `.input-row` — строка с инпутами

---

## Валидаторы

| Validator | Поле | Правила |
|-----------|------|---------|
| `AmountValidator` | `#amount_input` | Число > 0 или процент 1-100% |
| `FloatValidator` | Gas, Slippage | Число > 0 |
| `IntegerValidator` | Gas Limit | Целое > 0 |
| `AddressValidator` | `#token_input` | `0x[a-fA-F0-9]{40}` |
