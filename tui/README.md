# TUI Module — Textual Interface

Terminal text interface based on **Textual**. Event-driven architecture with reactive UI updates.

---

## Architecture

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

## Components

### Status Bar

| Widget | Description | Update |
|--------|-------------|--------|
| `StatusRPC` | RPC node status | `_evt_rpc_status`, `_evt_engine_ready` |
| `StatusConnection` | WebSocket status | `_evt_connection_status` |
| `StatusGas` | Current gas price | `_evt_gas_price` |
| `StatusWallets` | Active wallets presence | `ui_updater_worker` |

### Tabs

```
trade_tab     --> Token input, amount, BUY/SELL panels, market data
wallets_tab   --> Wallets table, add form
settings_tab  --> RPC, quote currency, auto-fuel, slippage, gas
logs_tab      --> RichLog with 500 message buffer
help_tab      --> Markdown help
```

---

## Event Dispatcher

Events from the Rust core are processed via the `_rust_event_handlers` dictionary:

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

### Processing Chain

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

## UI State

### `_market_data`

```python
{
    'pool_type': str,        # V2/V3
    'pool_address': str,
    'tvl_usd': float,
    'fee_bps': int,
    'impact_buy': float,     # Price impact for buy
    'impact_sell': float,    # Price impact for sell
    'current_price': float,
    'pos_cost_quote': float, # Position cost in quote
    'pos_amount': float,     # Token amount in position
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

## Hotkeys

| Binding | Action | Description |
|---------|--------|-------------|
| `Ctrl+Q` | `quit` | Exit |
| `Ctrl+R` | `reload_wallets` | Resync balances |
| `T` | `switch_tab('trade_tab')` | Trade tab |
| `W` | `switch_tab('wallets_tab')` | Wallets tab |
| `S` | `switch_tab('settings_tab')` | Settings tab |
| `L` | `switch_tab('logs_tab')` | Logs tab |
| `F` | `switch_tab('help_tab')` | Help |
| `↑` | `set_trade_mode('BUY')` | Buy mode |
| `↓` | `set_trade_mode('SELL')` | Sell mode |
| `Enter` | `execute_trade` | Execute order |
| `Delete` | `clear_token_input` | Clear token |
| `Shift+↑` | `change_slippage(+0.5)` | +0.5% slippage |
| `Shift+↓` | `change_slippage(-0.5)` | -0.5% slippage |
| `Shift+→` | `change_gas(+0.1)` | +0.1 Gwei |
| `Shift+←` | `change_gas(-0.1)` | -0.1 Gwei |

---

## Background Tasks

On `on_mount`, the following start:

```python
_background_tasks = [
    ui_updater_worker(),       # Process ui_update_queue
    _rust_event_listener(),    # Read events from bridge
    status_update_loop(),      # Periodic status updates
    _notification_watcher()    # Process notification_queue
]
```

### `ui_update_queue`

Update types:
- `"refresh_balances"` → `_refresh_wallet_table()`
- `"refresh_all"` → `_load_and_apply_settings()` + `_refresh_wallet_table()`
- `"refresh_market_data"` → `_update_market_data_table()`
- `"wallets"` → `_refresh_wallet_table()`

---

## Trading

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

Transaction tracking with latency measurement:

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

## Cache Integration

| Cache Method | Usage |
|--------------|-------|
| `get_all_wallets()` | Load into `wallets_cache_ui` |
| `get_position_memory()` | PnL calculation |
| `update_position_memory()` | On BUY |
| `close_position_memory()` | On SELL success |
| `get_exact_balance_wei()` | Token amount for SELL |
| `set_exact_balance_wei()` | On BalanceUpdate |
| `get_active_trade_token()` | Current token |
| `set_active_trade_token()` | On address input |

---

## CSS Classes

File: `app.css`

Key classes:
- `.active-panel` — highlight active BUY/SELL panel
- `.button-pressed` — button press animation
- `.label-row` — row with label and value
- `.settings-group` — settings group
- `.input-row` — row with inputs

---

## Validators

| Validator | Field | Rules |
|-----------|-------|-------|
| `AmountValidator` | `#amount_input` | Number > 0 or percentage 1-100% |
| `FloatValidator` | Gas, Slippage | Number > 0 |
| `IntegerValidator` | Gas Limit | Integer > 0 |
| `AddressValidator` | `#token_input` | `0x[a-fA-F0-9]{40}` |

