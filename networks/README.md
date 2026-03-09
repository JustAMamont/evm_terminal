# 📁 Network Configuration (networks/)

This folder contains JSON configuration files for each supported EVM network.

Filename = network identifier (e.g., `bsc.json`, `eth.json`, `polygon.json`).

**Warning:**
> Only `BSC (mainnet, testnet)` has been tested and debugged so far. Others should theoretically work without issues, as router and quoter contracts are unified for all EVM networks (again, theoretically). `Therefore, all information below not related to BNB requires verification`.

---

## Config Structure

```json
{
    "name": "BSC Mainnet",
    "db_path": "data/bsc_mainnet.db",
    "chain_id": 56,
    "rpc_url": "https://bsc-rpc.publicnode.com",
    "wss_url": "wss://bsc-rpc.publicnode.com",
    "native_currency_symbol": "BNB",
    "native_currency_address": "0xeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee",
    "explorer_url": "https://bscscan.com/",
    "dex_router_address": "0xcdcc4feee010fcd5301fd823085e3d3e7d414a46",
    "v2_factory_address": "0xcA143Ce32Fe78f1f7019d7d551a6402fC5350c73",
    "v3_factory_address": "0x0BFbCF9fa4f9C56B0F40a671Ad40E0805A091865",
    "v2_router_address": "0x10ED43C718714eb63d5aA57B78B54704E256024E",
    "v3_quoter_address": "0xB048Bbc1Ee6b733FFfCFb9e9CeF7375518e25997",
    "public_rpc_urls": [...],
    "fee_receiver": "0x01216B94f054BCA3ba15ce1C7C4Bd16892ba9B24",
    "default_quote_currency": "WBNB",
    "quote_tokens": {...},
    "min_native_for_gas": 0.00005,
    "requires_private_rpc": false
}
```

---

## Parameters

### Basic

| Parameter | Type | Description |
|-----------|------|-------------|
| `name` | string | Display name of network in interface |
| `db_path` | string | Path to database file for this network |
| `chain_id` | number | Chain ID of the network |

### RPC Endpoints

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `rpc_url` | string | Yes | HTTP RPC endpoint (fallback from JSON) |
| `wss_url` | string | No | WebSocket endpoint. If empty — generated from `rpc_url` |
| `public_rpc_urls` | array | Yes | List of public RPCs for load distribution |

### Native Currency

| Parameter | Type | Description |
|-----------|------|-------------|
| `native_currency_symbol` | string | Native currency symbol (BNB, ETH, MATIC, ARB) |
| `native_currency_address` | string | Native currency address (usually `0xee...ee`) |

### DEX Contracts

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `dex_router_address` | string | Yes | Our TaxRouter contract address |
| `v2_factory_address` | string | Recommended | V2 Factory for pool discovery |
| `v3_factory_address` | string | Recommended | V3 Factory for pool discovery |
| `v2_router_address` | string | Recommended | V2 Router for swaps |
| `v3_quoter_address` | string | Recommended | V3 Quoter for price fetching |

### Other

| Parameter | Type | Description |
|-----------|------|-------------|
| `explorer_url` | string | Blockchain explorer URL |
| `fee_receiver` | string | Project fee recipient address |
| `default_quote_currency` | string | Default quote currency (must be in `quote_tokens`) |
| `quote_tokens` | object | Dictionary of quote tokens {symbol: address} |
| `min_native_for_gas` | number | Minimum native currency for warning |
| `requires_private_rpc` | boolean | Whether private RPC from user is required |

---

## Supported Networks

### BSC (Binance Smart Chain)

| Network | Chain ID | File |
|---------|----------|------|
| BSC Mainnet | 56 | `bsc.json` |
| BSC Testnet | 97 | `bsc_testnet.json` |

### Ethereum

| Network | Chain ID | File |
|---------|----------|------|
| Ethereum Mainnet | 1 | `eth.json` |
| Sepolia Testnet | 11155111 | `eth_sepolia.json` |

### Polygon

| Network | Chain ID | File |
|---------|----------|------|
| Polygon Mainnet | 137 | `polygon.json` |
| Mumbai Testnet | 80001 | `polygon_mumbai.json` |

### Arbitrum

| Network | Chain ID | File |
|---------|----------|------|
| Arbitrum One | 42161 | `arbitrum.json` |
| Arbitrum Sepolia | 421614 | `arbitrum_sepolia.json` |

---

## Configuration Examples

### BSC Mainnet

```json
{
    "name": "BSC Mainnet",
    "db_path": "data/bsc_mainnet.db",
    "chain_id": 56,
    "rpc_url": "https://bsc-rpc.publicnode.com",
    "wss_url": "wss://bsc-rpc.publicnode.com",
    "native_currency_symbol": "BNB",
    "native_currency_address": "0xeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee",
    "explorer_url": "https://bscscan.com/",
    "dex_router_address": "0xcdcc4feee010fcd5301fd823085e3d3e7d414a46",
    "v2_factory_address": "0xcA143Ce32Fe78f1f7019d7d551a6402fC5350c73",
    "v3_factory_address": "0x0BFbCF9fa4f9C56B0F40a671Ad40E0805A091865",
    "v2_router_address": "0x10ED43C718714eb63d5aA57B78B54704E256024E",
    "v3_quoter_address": "0xB048Bbc1Ee6b733FFfCFb9e9CeF7375518e25997",
    "public_rpc_urls": [
        "https://bsc-dataseed.binance.org",
        "https://bsc.publicnode.com"
    ],
    "fee_receiver": "0x01216B94f054BCA3ba15ce1C7C4Bd16892ba9B24",
    "default_quote_currency": "WBNB",
    "quote_tokens": {
        "WBNB": "0xbb4CdB9CBd36B01bD1cBaEBF2De08d9173bc095c",
        "USDT": "0x55d398326f99059fF775485246999027B3197955"
    },
    "min_native_for_gas": 0.00005,
    "requires_private_rpc": false
}
```

---

### BSC Testnet (requires private RPC)

```json
{
    "name": "BSC Testnet",
    "db_path": "data/bsc_testnet.db",
    "chain_id": 97,
    "rpc_url": "https://data-seed-prebsc-1-s1.binance.org:8545/",
    "wss_url": "",
    "native_currency_symbol": "BNB",
    "native_currency_address": "0xeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee",
    "explorer_url": "https://testnet.bscscan.com/",
    "dex_router_address": "0x9f47ccb579626b683ca3b9daa61eef6f17ce2439",
    "v2_factory_address": "0x6725F303b657a9451d8BA641348b6761A6CC7a17",
    "v3_factory_address": "0x0BFbCF9fa4f9C56B0F40a671Ad40E0805A091865",
    "v2_router_address": "0xD99D1c33F9fC3444f8101754aBC46c52416550D1",
    "v3_quoter_address": "0xbC203d7f83677c7ed3F7acEc959963E7F4ECC5C2",
    "public_rpc_urls": [
        "https://data-seed-prebsc-1-s1.binance.org:8545/",
        "https://data-seed-prebsc-2-s1.binance.org:8545/"
    ],
    "fee_receiver": "0xE54094d99d71F87D1f986E23F9ae3d1ABcD56647",
    "default_quote_currency": "WBNB",
    "quote_tokens": {
        "WBNB": "0xae13d989daC2f0dEbFf460aC112a837C89BAa7cd",
        "BUSD": "0x78867bbeef44f2326bf3816fb87fcc56783aefd7"
    },
    "min_native_for_gas": 0.00005,
    "requires_private_rpc": true
}
```

**Key differences:**
- `requires_private_rpc: true` — user must enter a private RPC
- `wss_url: ""` — public WebSocket unavailable

---

### Ethereum Mainnet (unverified)

```json
{
    "name": "Ethereum Mainnet",
    "db_path": "data/eth_mainnet.db",
    "chain_id": 1,
    "rpc_url": "https://eth.llamarpc.com",
    "wss_url": "",
    "native_currency_symbol": "ETH",
    "native_currency_address": "0xeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee",
    "explorer_url": "https://etherscan.io/",
    "dex_router_address": "YOUR_ROUTER_ADDRESS",
    "v2_factory_address": "0x5C69bEe701ef814a2B6a3EDD4B1652CB9cc5aA6f",
    "v3_factory_address": "0x1F98431c8aD98523631AE4a59f267346ea31F984",
    "v2_router_address": "0x7a250d5630B4cF539739dF2C5dAcb4c659F2488D",
    "v3_quoter_address": "0xb27308f9F90D607463bb33eA1BeBb41C27CE5AB6",
    "public_rpc_urls": [
        "https://eth.llamarpc.com",
        "https://ethereum.publicnode.com"
    ],
    "fee_receiver": "YOUR_FEE_RECEIVER",
    "default_quote_currency": "WETH",
    "quote_tokens": {
        "WETH": "0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2",
        "USDC": "0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48",
        "USDT": "0xdAC17F958D2ee523a2206206994597C13D831ec7"
    },
    "min_native_for_gas": 0.001,
    "requires_private_rpc": true
}
```

**Ethereum specifics:**
- `requires_private_rpc: true` — public RPCs are unreliable
- `min_native_for_gas: 0.001` — ETH is more expensive, need more for gas
- Uniswap V2/V3 contracts

---

### Polygon Mainnet (unverified)

```json
{
    "name": "Polygon Mainnet",
    "db_path": "data/polygon_mainnet.db",
    "chain_id": 137,
    "rpc_url": "https://polygon-rpc.com",
    "wss_url": "wss://polygon-rpc.com",
    "native_currency_symbol": "MATIC",
    "native_currency_address": "0xeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee",
    "explorer_url": "https://polygonscan.com/",
    "dex_router_address": "YOUR_ROUTER_ADDRESS",
    "v2_factory_address": "0x5757371414417b8C6CAad45bAeF941aBc7d3Ab32",
    "v3_factory_address": "0x1F98431c8aD98523631AE4a59f267346ea31F984",
    "v2_router_address": "0xa5E0829CaCEd8fFDD4De3c43696c57F7D7A678ff",
    "v3_quoter_address": "0xa1D0832a44073f59F1B2f5E3C2Ae52F8093d193d",
    "public_rpc_urls": [
        "https://polygon-rpc.com",
        "https://polygon.publicnode.com"
    ],
    "fee_receiver": "YOUR_FEE_RECEIVER",
    "default_quote_currency": "WMATIC",
    "quote_tokens": {
        "WMATIC": "0x0d500B1d8E8eF31E21C99d1Db9A6444d3ADf1270",
        "USDC": "0x3c499c542cEF5E3811e1192ce70d8cC03d5c3359",
        "USDT": "0xc2132D05D31c914a87C6611C10748AEb04B58e8F"
    },
    "min_native_for_gas": 0.1,
    "requires_private_rpc": false
}
```

---

### Arbitrum One (unverified)

```json
{
    "name": "Arbitrum One",
    "db_path": "data/arbitrum_mainnet.db",
    "chain_id": 42161,
    "rpc_url": "https://arb1.arbitrum.io/rpc",
    "wss_url": "wss://arb1.arbitrum.io/ws",
    "native_currency_symbol": "ETH",
    "native_currency_address": "0xeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee",
    "explorer_url": "https://arbiscan.io/",
    "dex_router_address": "YOUR_ROUTER_ADDRESS",
    "v2_factory_address": "0xf1D7CC64Fb4452F05c498126312eBE29f30Fbcf9",
    "v3_factory_address": "0x1F98431c8aD98523631AE4a59f267346ea31F984",
    "v2_router_address": "0x4752ba5dbc23f44d87826276bf6fd6b1c372ad24",
    "v3_quoter_address": "0xb2190284063c4eD0a3239673C3672231E5922f70",
    "public_rpc_urls": [
        "https://arb1.arbitrum.io/rpc",
        "https://arbitrum.publicnode.com"
    ],
    "fee_receiver": "YOUR_FEE_RECEIVER",
    "default_quote_currency": "WETH",
    "quote_tokens": {
        "WETH": "0x82aF49447D8a07e3bd95BD0d56f35241523fBab1",
        "USDC": "0xaf88d065e77c8cC2239327C5EDb3A432268e5831",
        "USDT": "0xFd086bC7CD5C481DCC9C85ebE478A1C0b69FCbb9"
    },
    "min_native_for_gas": 0.001,
    "requires_private_rpc": false
}
```

---

## DEX Contracts by Network

### Uniswap V2 Compatible

| Network | Factory | Router |
|---------|---------|--------|
| Ethereum | `0x5C69bEe701ef814a2B6a3EDD4B1652CB9cc5aA6f` | `0x7a250d5630B4cF539739dF2C5dAcb4c659F2488D` |
| BSC (PancakeSwap) | `0xcA143Ce32Fe78f1f7019d7d551a6402fC5350c73` | `0x10ED43C718714eb63d5aA57B78B54704E256024E` |
| Polygon (QuickSwap) | `0x5757371414417b8C6CAad45bAeF941aBc7d3Ab32` | `0xa5E0829CaCEd8fFDD4De3c43696c57F7D7A678ff` |
| Arbitrum (SushiSwap) | `0xf1D7CC64Fb4452F05c498126312eBE29f30Fbcf9` | `0x4752ba5dbc23f44d87826276bf6fd6b1c372ad24` |

### Uniswap V3

| Network | Factory | Quoter |
|---------|---------|--------|
| Ethereum | `0x1F98431c8aD98523631AE4a59f267346ea31F984` | `0xb27308f9F90D607463bb33eA1BeBb41C27CE5AB6` |
| BSC (PancakeSwap) | `0x0BFbCF9fa4f9C56B0F40a671Ad40E0805A091865` | `0xB048Bbc1Ee6b733FFfCFb9e9CeF7375518e25997` |
| Polygon | `0x1F98431c8aD98523631AE4a59f267346ea31F984` | `0xa1D0832a44073f59F1B2f5E3C2Ae52F8093d193d` |
| Arbitrum | `0x1F98431c8aD98523631AE4a59f267346ea31F984` | `0xb2190284063c4eD0a3239673C3672231E5922f70` |

---

## Quote Tokens by Network

### Ethereum

| Symbol | Address | Description |
|--------|---------|-------------|
| WETH | `0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2` | Wrapped ETH |
| USDC | `0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48` | USD Coin |
| USDT | `0xdAC17F958D2ee523a2206206994597C13D831ec7` | Tether USD |

### BSC

| Symbol | Address | Description |
|--------|---------|-------------|
| WBNB | `0xbb4CdB9CBd36B01bD1cBaEBF2De08d9173bc095c` | Wrapped BNB |
| USDT | `0x55d398326f99059fF775485246999027B3197955` | Tether USD |
| USDC | `0x8AC76a51cc950d9822D68b83fE1Ad97B32Cd580d` | USD Coin |
| ASTER | `0x000Ae314E2A2172a039B26378814C252734f556A` | Aster |
| U | `0xcE24439F2D9C6a2289F741120FE202248B666666` | U Token |
| USD1 | `0x8d0d000ee44948fc98c9b98a4fa4921476f08b0d` | World Liberty Financial USD |

### Polygon

| Symbol | Address | Description |
|--------|---------|-------------|
| WMATIC | `0x0d500B1d8E8eF31E21C99d1Db9A6444d3ADf1270` | Wrapped MATIC |
| USDC | `0x3c499c542cEF5E3811e1192ce70d8cC03d5c3359` | USD Coin (native) |
| USDT | `0xc2132D05D31c914a87C6611C10748AEb04B58e8F` | Tether USD |

### Arbitrum

| Symbol | Address | Description |
|--------|---------|-------------|
| WETH | `0x82aF49447D8a07e3bd95BD0d56f35241523fBab1` | Wrapped ETH |
| USDC | `0xaf88d065e77c8cC2239327C5EDb3A432268e5831` | USD Coin (native) |
| USDT | `0xFd086bC7CD5C481DCC9C85ebE478A1C0b69FCbb9` | Tether USD |

---

## requires_private_rpc

Flag indicating whether private RPC from user is required.

| Value | When to set |
|-------|-------------|
| `false` | Public RPCs are stable and support WebSocket |
| `true` | Public RPCs are unreliable or don't support WebSocket |

**Recommendations:**

| Network | requires_private_rpc | Reason |
|---------|---------------------|--------|
| BSC Mainnet | `false` | Many stable public RPCs |
| BSC Testnet | `true` | Public ones don't support WSS |
| Ethereum | `true` | High load, public ones are limited |
| Polygon | `false` | Good public RPCs |
| Arbitrum | `false` | Official RPCs are stable |

---

## min_native_for_gas

Minimum native currency balance for warning.

**Recommendations:**

| Network | Value | In USD (~) |
|---------|-------|------------|
| BSC | 0.00005 | ~$0.03 |
| Ethereum | 0.001 | ~$3-5 |
| Polygon | 0.1 | ~$0.05 |
| Arbitrum | 0.001 | ~$3-5 |

---

## Adding a New Network

1. Create file `networks/<network_name>.json`
2. Fill in all required fields
3. Find DEX contract addresses (Factory, Router, Quoter)
4. Define quote tokens
5. Set `requires_private_rpc` based on public RPC availability
6. Deploy TaxRouter contract to new network
7. Enter its address in `dex_router_address`

---

## Private RPC Providers

| Provider | Free Tier | Networks | WebSocket |
|----------|-----------|----------|-----------|
| Chainstack | 3M requests/month | All major | ✅ |
| QuickNode | 10M credits/month | All major | ✅ |
| Alchemy | 300M compute/month | ETH, Polygon, Arb | ✅ |
| Ankr | 10M requests/month | All major | ✅ |
| Infura | 100k requests/day | ETH, Polygon | ✅ |