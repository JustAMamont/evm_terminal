# 📑 TaxRouter: Smart Contract Overview

Source code of the **TaxRouter** smart contract for executing trading operations in EVM-compatible networks via **EVM_TERMINAL**.

## 📌 Purpose

**TaxRouter** — a custom router middleware aggregating liquidity from V2 and V3 protocols (PancakeSwap-style).

### Features:
- **Unified interface** — trades in V2/V3 pools through a single contract
- **0.1% fee** — automatic 10 BPS deduction on each trade
- **Quote tokens** — fee only in liquid assets (USDT, WBNB), no "shitcoins"
- **Fee-on-Transfer** — correct handling of deflationary tokens
- **Auto-Fuel** — functions for swapping native coins to tokens

---

## ⚙️ Compilation Specifications

| Parameter | Value |
|-----------|-------|
| Language | Solidity |
| Version | `0.8.33` |
| EVM Version | `Shanghai` |
| Optimization | `Enabled` (200 runs) |
| License | `MIT` |

---

## 🚀 Deployment

### Constructor Arguments (BSC Mainnet):

```
_factory:     0xcA143Ce32Fe78f1f7019d7d551a6402fC5350c73 (V2 Factory)
_WETH:        0xbb4CdB9CBd36B01bD1cBaEBF2De08d9173bc095c (WBNB)
_feeReceiver: <YOUR_ADDRESS_FOR_FEES>
_v3Router:    0x1b81D678ffb9C0263b24A97847620C99d213eB14 (V3 Smart Router)
```

### After Deployment:

1. **Verify** the contract in the explorer
2. **Add Quote tokens** via `setQuoteToken()`:
   ```
   USDT: 0x55d398326f99059fF775485246999027B3197955
   USDC: 0x8AC76a51cc950d9822D68b83fE1Ad97B32Cd580d
   ```
   WBNB is added automatically.

3. **Enter the address** in the network config `networks/bsc.json`:
   ```json
   "dex_router_address": "0xYOUR_CONTRACT_ADDRESS"
   ```

---

## 🛠 Admin Functions

| Function | Description |
|----------|-------------|
| `setFeeReceiver(address)` | Change fee recipient address |
| `setQuoteToken(address, bool)` | Add/remove Quote token |
| `transferOwnership(address)` | Transfer ownership rights |
| `rescueTokens(address, uint)` | Withdraw stuck tokens/BNB |

---

## 🔍 Fee Logic

**Buy:** Accepts Quote token → deducts 0.1% → sends to pool → user receives token

**Sell:** Exchanges token for Quote → deducts 0.1% from result → sends to user

`amountOutMin` is checked **after** fee deduction — this prevents reverts.

---

## ⚠️ Important

### Address Configuration

Contract address is configured in `networks/<network>.json`:

```json
{
    "dex_router_address": "0x...",
    ...
}
```

### Contract Modification

You can modify or remove the fee:
```solidity
uint public constant FEE_BASIS_POINTS = 0;  // No fee
```

**Important:** Do not change function names and parameter structure — the bot uses a specific interface.

### Bot Integration

1. Deploy contract (Remix/Hardhat/Foundry)
2. Configure Quote tokens
3. Enter address in `networks/*.json`
4. Run the bot — it will pick up config automatically

---

## Disclaimer

The code is provided "as is". The author is not responsible for financial losses. Deployment errors, incorrect router addresses, or improper configuration can result in loss of funds.

**Recommendation:** Before Mainnet, test on BSC Testnet. Testnet config: `networks/bsc_testnet.json`.
