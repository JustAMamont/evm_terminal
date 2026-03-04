# 📁 Конфигурация сетей (networks/)

Папка содержит JSON-файлы конфигурации для каждой поддерживаемой EVM-сети.

Имя файла = идентификатор сети (например `bsc.json`, `eth.json`, `polygon.json`).

**Предупреждение:** 
> Пока проверена и отлажена работа только с `BSC (mainnet, testnet)`, остальные теоретически должны работать без проблем, так как контракты роутеров, квотеров унифицированы для всех EVM-сетей (опять же теоретически). `Потому вся инфа ниже что не касается BNB нуждается в проверках`. Файл будет со временем дополняться и редактироваться.

---

## Структура конфига

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

## Параметры

### Основные

| Параметр | Тип | Описание |
|----------|-----|----------|
| `name` | string | Отображаемое имя сети в интерфейсе |
| `db_path` | string | Путь к файлу БД для данной сети |
| `chain_id` | number | Chain ID сети |

### RPC endpoints

| Параметр | Тип | Обязательный | Описание |
|----------|-----|--------------|----------|
| `rpc_url` | string | Да | HTTP RPC endpoint (fallback из JSON) |
| `wss_url` | string | Нет | WebSocket endpoint. Если пусто — генерируется из `rpc_url` |
| `public_rpc_urls` | array | Да | Список публичных RPC для распределения нагрузки |

### Нативная валюта

| Параметр | Тип | Описание |
|----------|-----|----------|
| `native_currency_symbol` | string | Символ нативной валюты (BNB, ETH, MATIC, ARB) |
| `native_currency_address` | string | Адрес нативной валюты (обычно `0xee...ee`) |

### DEX контракты

| Параметр | Тип | Обязательный | Описание |
|----------|-----|--------------|----------|
| `dex_router_address` | string | Да | Адрес нашего TaxRouter контракта |
| `v2_factory_address` | string | Рекомендуется | Factory V2 для поиска пулов |
| `v3_factory_address` | string | Рекомендуется | Factory V3 для поиска пулов |
| `v2_router_address` | string | Рекомендуется | Router V2 для свапов |
| `v3_quoter_address` | string | Рекомендуется | Quoter V3 для получения цен |

### Прочее

| Параметр | Тип | Описание |
|----------|-----|----------|
| `explorer_url` | string | URL блокчейн-эксплорера |
| `fee_receiver` | string | Адрес получателя комиссий проекта |
| `default_quote_currency` | string | Quote-валюта по умолчанию (должна быть в `quote_tokens`) |
| `quote_tokens` | object | Словарь quote-токенов {symbol: address} |
| `min_native_for_gas` | number | Минимум нативной валюты для предупреждения |
| `requires_private_rpc` | boolean | Требуется ли приватный RPC от пользователя |

---

## Поддерживаемые сети

### BSC (Binance Smart Chain)

| Сеть | Chain ID | Файл |
|------|----------|------|
| BSC Mainnet | 56 | `bsc.json` |
| BSC Testnet | 97 | `bsc_testnet.json` |

### Ethereum

| Сеть | Chain ID | Файл |
|------|----------|------|
| Ethereum Mainnet | 1 | `eth.json` |
| Sepolia Testnet | 11155111 | `eth_sepolia.json` |

### Polygon

| Сеть | Chain ID | Файл |
|------|----------|------|
| Polygon Mainnet | 137 | `polygon.json` |
| Mumbai Testnet | 80001 | `polygon_mumbai.json` |

### Arbitrum

| Сеть | Chain ID | Файл |
|------|----------|------|
| Arbitrum One | 42161 | `arbitrum.json` |
| Arbitrum Sepolia | 421614 | `arbitrum_sepolia.json` |

---

## Примеры конфигураций

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

### BSC Testnet (требует приватный RPC)

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

**Ключевые отличия:**
- `requires_private_rpc: true` — пользователь обязан ввести приватный RPC
- `wss_url: ""` — публичный WebSocket недоступен

---

### Ethereum Mainnet

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

**Особенности Ethereum:**
- `requires_private_rpc: true` — публичные RPC ненадёжны
- `min_native_for_gas: 0.001` — ETH дороже, нужно больше на газ
- Uniswap V2/V3 контракты

---

### Polygon Mainnet

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

### Arbitrum One

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

## DEX контракты по сетям

### Uniswap V2 Compatible

| Сеть | Factory | Router |
|------|---------|--------|
| Ethereum | `0x5C69bEe701ef814a2B6a3EDD4B1652CB9cc5aA6f` | `0x7a250d5630B4cF539739dF2C5dAcb4c659F2488D` |
| BSC (PancakeSwap) | `0xcA143Ce32Fe78f1f7019d7d551a6402fC5350c73` | `0x10ED43C718714eb63d5aA57B78B54704E256024E` |
| Polygon (QuickSwap) | `0x5757371414417b8C6CAad45bAeF941aBc7d3Ab32` | `0xa5E0829CaCEd8fFDD4De3c43696c57F7D7A678ff` |
| Arbitrum (SushiSwap) | `0xf1D7CC64Fb4452F05c498126312eBE29f30Fbcf9` | `0x4752ba5dbc23f44d87826276bf6fd6b1c372ad24` |

### Uniswap V3

| Сеть | Factory | Quoter |
|------|---------|--------|
| Ethereum | `0x1F98431c8aD98523631AE4a59f267346ea31F984` | `0xb27308f9F90D607463bb33eA1BeBb41C27CE5AB6` |
| BSC (PancakeSwap) | `0x0BFbCF9fa4f9C56B0F40a671Ad40E0805A091865` | `0xB048Bbc1Ee6b733FFfCFb9e9CeF7375518e25997` |
| Polygon | `0x1F98431c8aD98523631AE4a59f267346ea31F984` | `0xa1D0832a44073f59F1B2f5E3C2Ae52F8093d193d` |
| Arbitrum | `0x1F98431c8aD98523631AE4a59f267346ea31F984` | `0xb2190284063c4eD0a3239673C3672231E5922f70` |

---

## Quote-токены по сетям

### Ethereum

| Символ | Адрес | Описание |
|--------|-------|----------|
| WETH | `0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2` | Wrapped ETH |
| USDC | `0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48` | USD Coin |
| USDT | `0xdAC17F958D2ee523a2206206994597C13D831ec7` | Tether USD |

### BSC

| Символ | Адрес | Описание |
|--------|-------|----------|
| WBNB | `0xbb4CdB9CBd36B01bD1cBaEBF2De08d9173bc095c` | Wrapped BNB |
| USDT | `0x55d398326f99059fF775485246999027B3197955` | Tether USD |
| USDC | `0x8AC76a51cc950d9822D68b83fE1Ad97B32Cd580d` | USD Coin |
| ASTER | `0x000Ae314E2A2172a039B26378814C252734f556A` | Aster |
| U | `0xcE24439F2D9C6a2289F741120FE202248B666666` | U Token |
| USD1 | `0x8d0d000ee44948fc98c9b98a4fa4921476f08b0d` | World Liberty Financial USD |

### Polygon

| Символ | Адрес | Описание |
|--------|-------|----------|
| WMATIC | `0x0d500B1d8E8eF31E21C99d1Db9A6444d3ADf1270` | Wrapped MATIC |
| USDC | `0x3c499c542cEF5E3811e1192ce70d8cC03d5c3359` | USD Coin (native) |
| USDT | `0xc2132D05D31c914a87C6611C10748AEb04B58e8F` | Tether USD |

### Arbitrum

| Символ | Адрес | Описание |
|--------|-------|----------|
| WETH | `0x82aF49447D8a07e3bd95BD0d56f35241523fBab1` | Wrapped ETH |
| USDC | `0xaf88d065e77c8cC2239327C5EDb3A432268e5831` | USD Coin (native) |
| USDT | `0xFd086bC7CD5C481DCC9C85ebE478A1C0b69FCbb9` | Tether USD |

---

## requires_private_rpc

Флаг обязательности приватного RPC от пользователя.

| Значение | Когда ставить |
|----------|---------------|
| `false` | Публичные RPC стабильны и поддерживают WebSocket |
| `true` | Публичные RPC ненадёжны или не поддерживают WebSocket |

**Рекомендации:**

| Сеть | requires_private_rpc | Причина |
|------|---------------------|---------|
| BSC Mainnet | `false` | Много стабильных публичных RPC |
| BSC Testnet | `true` | Публичные не поддерживают WSS |
| Ethereum | `true` | Высокая нагрузка, публичные лимитированы |
| Polygon | `false` | Хорошие публичные RPC |
| Arbitrum | `false` | Официальные RPC стабильны |

---

## min_native_for_gas

Минимальный баланс нативной валюты для предупреждения.

**Рекомендации:**

| Сеть | Значение | В USD (~) |
|------|----------|-----------|
| BSC | 0.00005 | ~$0.03 |
| Ethereum | 0.001 | ~$3-5 |
| Polygon | 0.1 | ~$0.05 |
| Arbitrum | 0.001 | ~$3-5 |

---

## Добавление новой сети

1. Создайте файл `networks/<network_name>.json`
2. Заполните все обязательные поля
3. Найдите адреса DEX контрактов (Factory, Router, Quoter)
4. Определите quote-токены
5. Укажите `requires_private_rpc` в зависимости от доступности публичных RPC
6. Деплойте TaxRouter контракт в новую сеть
7. Укажите его адрес в `dex_router_address`

---

## Провайдеры приватного RPC

| Провайдер | Бесплатный тариф | Сети | WebSocket |
|-----------|------------------|------|-----------|
| Chainstack | 3M requests/мес | Все основные | ✅ |
| QuickNode | 10M credits/мес | Все основные | ✅ |
| Alchemy | 300M compute/мес | ETH, Polygon, Arb | ✅ |
| Ankr | 10M requests/мес | Все основные | ✅ |
| Infura | 100k requests/день | ETH, Polygon | ✅ |
