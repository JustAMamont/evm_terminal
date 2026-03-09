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
|                                                             |
|  +------------+     +--------------+     +---------------+  |
|  | TUI        |     | GlobalCache  |     | BridgeManager |  |
|  | (Textual)  |---->| - Balances   |---->| - Commands    |  |
|  | - Render   |     | - Positions  |     | - Events      |  |
|  | - Input    |     | - PnL        |     |               |  |
|  +------------+     +--------------+     +---------------+  |
|                                                             |
+---------------------------|---------------------------------+
                            | PyO3 FFI
+---------------------------|---------------------------------+
|                     RUST CORE (dexbot_core)                 |
|                                                             |
|  EVENT LOOP                                                 |
|  +-- Nonce Monitor (prefetch)    --> 0ms execution          |
|  +-- GasPrice Monitor (prefetch) --> 0ms execution          |
|  +-- WebSocket Client                                       |
|      +-- Pool Updates                                       |
|      +-- Balance Updates                                    |
|                                                             |
|  RPC POOL                                                   |
|  +-- [Node1] [Node2] [Node3] --> Smart routing by latency   |
|                                                             |
|  EXECUTION ENGINE                                           |
|  +-- Transaction signing (secp256k1)                        |
|  +-- Nonce management                                       |
|  +-- Auto-approve for sell                                  |
|  +-- Event deduplication                                    |
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
TUI: action_execute
  +-- Validation
  +-- Collect data
        |
        | EngineCommand.ExecuteTrade
        v
BridgeManager.send()
  +-- JSON serialization
  +-- Crossbeam channel
        |
        v
RUST: Execution Engine
  +-- 1. Get nonce from CORE_STATE (RAM)    <-- prefetch, 0ms
  +-- 2. Get gas_price from CORE_STATE      <-- prefetch, 0ms
  +-- 3. Sign tx (secp256k1)                <-- ~50us
  +-- 4. Select fastest RPC node            <-- smart pool
  +-- 5. sendRawTransaction
        |
        v
EVM Mempool (Latency: 0.3-0.7s)
        |
        v
RUST: Event -> Python
  +-- TxSent
  +-- TxConfirmed
  +-- BalanceUpdate
        |
        v
TUI: UI Update
  +-- Transaction status
  +-- Balance
  +-- PnL
```

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