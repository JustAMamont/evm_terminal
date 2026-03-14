# EVM_TERMINAL 🚀

![Terminal Demo](media/term_preview.gif)

High-speed trading terminal (TUI) for DEX. Python + Rust hybrid.

> **Important:** The bot is architecturally designed to support any EVM-compatible networks. Currently, only **BSC (Binance Smart Chain)** is implemented and tested. Adding new networks — see [networks/README.md](networks/README.md).

---

## Tags

`dex` `trading-terminal` `evm` `bsc` `binance-smart-chain` `defi` `tui` `rust` `python` `cryptocurrency` `trading-bot` `websocket` `real-time` `swap` `pancakeswap` `uniswap`

---

## Table of Contents

- [Architecture](#architecture)
- [Requirements](#requirements)
- [Build](#build)
- [Usage](#usage)
- [Hotkeys](#hotkeys)
- [TaxRouter](#taxrouter)
- [Security](#security)
- [Legacy Context](#legacy-context)

---

## Architecture

```
+----------------------- PYTHON LAYER ------------------------+
|                        bot/bot.py                           |
|                    (Main Orchestrator)                      |
|                                                             |
|  +------------------+    +-------------------+              |
|  | DatabaseManager  |    |   GlobalCache     |              |
|  | (bot/core/db)    |    |   (bot/cache)     |              |
|  |                  |    |                   |              |
|  | Network DB:      |    | Memory Cache:     |              |
|  | - wallets        |--->| - balances (wei)  |              |
|  | - positions      |    | - positions       |              |
|  | - cached_pools   |    | - best_pools      |              |
|  | - config         |    | - token_metadata  |              |
|  |                  |    +-------------------+              |
|  | Global DB:       |              |                        |
|  | - security (pwd) |              v                        |
|  | - last_network   |    +-------------------+              |
|  | - language       |    |  BridgeManager    |              |
|  +------------------+    |  (bot/core/bridge)|              |
|                          |                   |              |
|  +------------------+    | EngineCommand:    |              |
|  | Config           |    | - init()          |              |
|  | (bot/core/config)|    | - execute_trade() |              |
|  |                  |    | - switch_token()  |              |
|  | From network JSON|    | - calc_impact()   |              |
|  +------------------+    +--------|----------+              |
|                                   |                         |
|  +------------------+    +--------|----------+              |
|  | MarketDataService|    |   TradingApp      |              |
|  | (bot/services)   |    |   (tui/app.py)    |              |
|  |                  |    |                   |              |
|  | Binance ccxt.pro |    | Textual TUI:      |              |
|  | Quote prices USD |    | - Trade tab       |              |
|  +------------------+    | - Wallets tab     |              |
|                          | - Settings tab    |              |
|  +------------------+    | - Logs tab        |              |
|  | SecurityManager  |    | - Help tab        |              |
|  | (utils/security) |    |                   |              |
|  |                  |    | tui/lang.py:      |              |
|  | PBKDF2 480K iter |    | - EN/RU i18n      |              |
|  | Fernet (AES)     |    |                   |              |
|  +------------------+    +-------------------+              |
|                                                             |
+---------------------------|---------------------------------+
                            | PyO3 FFI
+---------------------------|---------------------------------+
|                     RUST CORE (dexbot_core)                 |
|                                                             |
|  STATE (CoreState)                                          |
|  +-- nonce (prefetch from pending tx)                       |
|  +-- gas_price (prefetch via eth_gasPrice)                  |
|  +-- wallet_keys (address -> private_key)                   |
|  +-- tracked_tokens (subscribed token addresses)            |
|                                                             |
|  EVENT LOOP (tokio runtime)                                 |
|  +-- WebSocket Client (pool updates, balance updates)       |
|  +-- RPC Health Checker (latency monitoring)                |
|  +-- Background Worker (WSS subscription management)        |
|                                                             |
|  RPC POOL                                                   |
|  +-- [Node1] [Node2] [Node3] --> Smart routing by latency   |
|                                                             |
|  EXECUTION ENGINE                                           |
|  +-- Transaction signing (secp256k1, k256)                  |
|  +-- Nonce management (atomic, prefetch)                    |
|  +-- Auto-approve for sell (ERC20 approve)                  |
|  +-- Auto-fuel (swap quote -> native for gas)               |
|                                                             |
|  BRIDGE (Python FFI)                                        |
|  +-- Ring buffer (event queue)                              |
|  +-- Command parser (binary protocol)                       |
|  +-- Event emitter (EngineReady, BalanceUpdate, etc.)       |
|                                                             |
+---------------------------|---------------------------------+
                            v
                     EVM Network
                     RPC / WSS
```

### Data Flow

```
User presses "BUY"
        |
        v
TUI: action_execute_trade()
  +-- Validation (address, amount, wallets enabled)
  +-- Collect data (token, quote, wallets, amounts)
        |
        | EngineCommand.ExecuteTrade { token, quote, is_buy, amounts, ... }
        v
BridgeManager.send()
  +-- Binary serialization (pack_u16, pack_string, ...)
  +-- Crossbeam channel to Rust
        |
        v
RUST: handle_command()
  +-- 1. Get nonce from CoreState (RAM)     <-- prefetch, 0ms
  +-- 2. Get gas_price from CoreState       <-- prefetch, 0ms
  +-- 3. Build tx (encode function call)
  +-- 4. Sign tx (secp256k1, ~50us)
  +-- 5. Select fastest RPC node            <-- smart pool
  +-- 6. sendRawTransaction
        |
        v
EVM Mempool (Latency: 0.3-0.7s)
        |
        v
RUST: WebSocket Event
  +-- TxSent -> emit to Python
  +-- TxConfirmed -> emit to Python
  +-- BalanceUpdate -> emit to Python
        |
        v
Python: handle_rust_event()
  +-- _evt_tx_sent() -> TxStatusTracker.record()
  +-- _evt_tx_confirmed() -> notification, PnL update
  +-- _evt_balance_update() -> GlobalCache update, UI refresh
        |
        v
TUI: UI Update
  +-- Transaction status notification
  +-- Balance table refresh
  +-- Position memory update
```

### Key Components

| Component | File | Description |
|-----------|------|-------------|
| **Main Orchestrator** | `bot/bot.py` | Entry point, auth, initialization, shutdown |
| **DatabaseManager** | `bot/core/db_manager.py` | SQLite operations, dual DB (network + global) |
| **GlobalCache** | `bot/cache.py` | In-memory cache for balances, positions, pools |
| **BridgeManager** | `bot/core/bridge.py` | Python ↔ Rust communication, command packing |
| **Config** | `bot/core/config.py` | Network configuration from JSON |
| **TradingApp** | `tui/app.py` | Textual TUI, event handlers, user interaction |
| **MarketDataService** | `bot/services/market_data_service.py` | Binance price feed via ccxt.pro |
| **SecurityManager** | `utils/security.py` | AES encryption, PBKDF2 key derivation |
| **i18n** | `tui/lang.py` | EN/RU translations |

---

## Requirements

### Dependencies
- Python 3.12+
- Rust (stable) + maturin
- Linux: `build-essential python3-dev libssl-dev`
- Windows: VS Build Tools 2022 (C++ workload)

### Network
- VPS in Frankfurt/London (ping to BSC nodes)
- 50+ Mbit/s internet connection

### Windows
- **Required:** [Windows Terminal](https://apps.microsoft.com/store/detail/windows-terminal/9N0DX20HK701)
- Set as default terminal
- `cmd.exe` and PowerShell (legacy) will break rendering and hotkeys

---

## Build

```bash
git clone https://github.com/JustAMamont/evm_terminal
cd evm_terminal

python3.12 -m venv env
source env/bin/activate  # Windows: env\Scripts\activate

pip install -r requirements.txt

cd rust_module
maturin develop --release
cd ..

python main.py
```

---

## Usage

### Initial Setup

1. **Master password** — create a password for key encryption on first run
2. **Wallets** — add private keys in the Wallets tab
3. **RPC** — for BSC Mainnet, public RPCs work out of the box
4. **Quote currency** — select WBNB/USDT/USDC in Settings

### Testnet (BSC Testnet)

⚠️ **Important:** BSC Testnet requires private RPC!

BSC Testnet public RPCs do not support WebSocket. Before use:
1. Get a private endpoint (Chainstack, QuickNode, Alchemy)
2. Insert HTTP endpoint into **Settings → RPC URL**
3. Application will restart

### Trading

**Buy:**
1. Paste token address (`Ctrl+Shift+V`)
2. Enter amount or percentage (e.g., `0.1` or `50%`)
3. Press **BUY** or `Enter`

**Sell:**
1. Select token (paste address)
2. Press `↓` to switch to SELL mode
3. Press **SELL** — sells 100% of token balance

---

## Hotkeys

### Navigation

| Key | Action |
|-----|--------|
| `T` | Trade Tab |
| `W` | Wallets Tab |
| `S` | Settings Tab |
| `L` | Logs Tab |
| `F` | Help |
| `Ctrl+Q` | Exit |

### Trading

| Key | Action |
|-----|--------|
| `↑` / `↓` | Switch BUY / SELL mode |
| `Enter` | Execute operation |
| `Ctrl+R` | Refresh data |

### Paste

| Key | Action |
|-----|--------|
| `Ctrl+Shift+V` | Paste from clipboard |
| `Ctrl+V` | **Does not work** in TUI |

> ⚠️ **Important:** Standard `Ctrl+V` does not work in terminal applications. Always use `Ctrl+Shift+V` for pasting addresses, keys, and other data.

---

## TaxRouter

Smart contract for V2/V3 routing with fee.

**Address (BSC Mainnet):** `0xcdcc4feee010fcd5301fd823085e3d3e7d414a46`

| Operation | Fee |
|-----------|-----|
| Buy | 0.1% deducted from input amount |
| Sell | 0.1% deducted from output amount |

📖 **Deployment and configuration instructions:** see [contract/README.md](contract/README.md)

---

## Security

- AES-256-GCM encryption for private keys
- PBKDF2-HMAC-SHA256 (480K iterations)
- Rust isolation for cryptography
- No backends — operates autonomously

---

## Legacy Context

Originally **EVM_TERMINAL** was developed as a commercial B2C product for the Russian-speaking crypto community.

**Business model:** Monetization through a fixed **0.1%** fee on each transaction processed through the custom `TaxRouter`.

**Centralized infrastructure (removed):**
- Telemetry and trading statistics collection
- OTA update system for binaries
- Licensing with HWID binding

**Why the project shut down:** Due to architectural limitations of the client application — unstable operation on users' home devices (high ping, unstable internet). Achieving deterministic terminal logic behavior would require private MEV routers (bloXroute, Flashbots) or a personal node — resources unavailable to most retail traders.

**Current status:** All centralized logic has been **completely removed**. Code is cleaned of requests to controlling servers. Terminal operates autonomously. With good ping to nodes (VPS in data center regions), the program demonstrates stable and reliable operation.

**Why build.py is so elaborate:** The script contains obfuscation mechanisms (`base64`, Cython) — a technical remnant of the commercial version for protection against reverse engineering. Preserved as a demonstration of self-contained application assembly approach.

---

## 📁 Documentation

| Section | File |
|---------|------|
| Network Configuration | [networks/README.md](networks/README.md) |
| Contract Deployment | [contract/README.md](contract/README.md) |

---

## Disclaimer

AS IS. Author is not responsible for financial losses. The 0.1% fee for each transaction through TaxRouter is an integral part of the bot's logic. You are free to deploy/edit the contract for your needs.

---

**Telegram:** [@optional_username_37](https://t.me/optional_username_37)
