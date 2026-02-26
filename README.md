# EVM_TERMINAL 🚀

![Демонстрация работы терминала](media/term_preview.gif)

Высокоскоростной торговый терминал (TUI) для DEX. Гибрид Python + Rust.

> **Важно:** Бот архитектурно поддерживает любые EVM-совместимые сети. На данный момент реализована и протестирована только **BSC (Binance Smart Chain)**. Добавление новых сетей требует конфигурации (см. `networks/*.json`).

---

## Коммерческое прошлое (Legacy Context)

Изначально **EVM_TERMINAL** разрабатывался как коммерческий B2C продукт для русскоязычного крипто-комьюнити.

**Бизнес-модель:** Монетизация через фиксированную комиссию **0.1%** с каждой транзакции, проходящей через кастомный `TaxRouter`.

**Централизованная инфраструктура (удалена):**
- Сбор телеметрии и торговой статистики (для реферальных пользователей)
- Система OTA-обновлений бинарных файлов
- Лицензирование с привязкой к HWID

**Текущий статус:** Вся централизованная логика **полностью вырезана**. Код очищен от запросов к управляющим серверам. Терминал работает автономно.

**Почему build.py такой замысловатый:** Скрипт содержит механизмы обфускации (компиляция в байт-код, `marshal`, `base64`, Cython) — технический атавизм коммерческой версии для защиты от реверс-инжиниринга. Сохранён как демонстрация подхода к сборке self-contained приложений.

---

## Архитектура

```
┌───────────────────────────────────────────────────────────────┐
│                        PYTHON LAYER                           │
│  ┌───────────────┐  ┌─────────────┐ ┌────────────────────┐    │
│  │  TUI (Textual)│  │ GlobalCache │ │ BridgeManager      │    │
│  │  - Render UI  │  │ - Balances  │ │ - Commands → Rust  │    │
│  │  - User Input │  │ - Positions │ │ - Events ← Rust    │    │
│  └────────┬──────┘  │ - PnL       │ └──────────┬─────────┘    │
│           │         └─────┬───────┘            │              │
│           │               │                    │              │
│           └───────────────┼────────────────────┘              │
│                           │ PyO3 FFI                          │
└───────────────────────────┼───────────────────────────────────┘
                            │
┌───────────────────────────┼───────────────────────────────────┐
│                      RUST CORE (dexbot_core)                  │
│  ┌─────────────────────────────────────────────────────────┐  │
│  │                    EVENT LOOP                           │  │
│  │  ┌───────────┐  ┌───────────┐  ┌───────────────────┐    │  │
│  │  │ Nonce     │  │ GasPrice  │  │ WebSocket Client  │    │  │
│  │  │ Monitor   │  │ Monitor   │  │ - Pool Updates    │    │  │
│  │  │ (prefetch)│  │ (prefetch)│  │ - Balance Updates │    │  │
│  │  └───────────┘  └───────────┘  └───────────────────┘    │  │
│  └─────────────────────────────────────────────────────────┘  │
│  ┌─────────────────────────────────────────────────────────┐  │
│  │                   RPC POOL                              │  │
│  │  [Node1] [Node2] [Node3] ... → Smart routing by latency │  │
│  └─────────────────────────────────────────────────────────┘  │
│  ┌─────────────────────────────────────────────────────────┐  │
│  │                 EXECUTION ENGINE                        │  │
│  │  - Подписание транзакций (secp256k1)                    │  │
│  │  - Nonce management                                     │  │
│  │  - Auto-approve для sell                                │  │
│  │  - Event deduplication                                  │  │
│  └─────────────────────────────────────────────────────────┘  │
└───────────────────────────────────────────────────────────────┘
                            │
                            ▼
                    ┌───────────────┐
                    │  EVM Network  │
                    │  RPC / WSS    │
                    └───────────────┘
```

---

## Поток данных

```
Пользователь нажимает "КУПИТЬ"
         │
         ▼
┌─────────────────────┐
│ TUI: action_execute │
│ - Валидация         │
│ - Сбор данных       │
└────────┬────────────┘
         │ EngineCommand.ExecuteTrade
         ▼
┌─────────────────────┐
│ BridgeManager.send()│
│ - JSON сериализация │
│ - Crossbeam channel │
└────────┬────────────┘
         │
         ▼
┌─────────────────────────────────────┐
│ RUST: Execution Engine              │
│ 1. Взять nonce из CORE_STATE (RAM)  │  ← prefetch, 0ms
│ 2. Взять gas_price из CORE_STATE    │  ← prefetch, 0ms
│ 3. Подписать tx (secp256k1)         │  ← ~50μs
│ 4. Выбрать fastest RPC node         │  ← smart pool
│ 5. sendRawTransaction               │
└────────┬────────────────────────────┘
         │
         ▼
┌─────────────────────┐
│ EVM Mempool         │
│ Latency: 0.3-0.7s   │
└────────┬────────────┘
         │
         ▼
┌─────────────────────┐
│ RUST: Event → Python│
│ - TxSent            │
│ - TxConfirmed       │
│ - BalanceUpdate     │
└────────┬────────────┘
         │
         ▼
┌─────────────────────┐
│ TUI: Обновление UI  │
│ - Статус транзакции │
│ - Баланс            │
│ - PnL               │
└─────────────────────┘
```

---

## Что изменилось (v2)

| Компонент | Было | Стало |
|-----------|------|-------|
| **Архитектура** | API Router + BotService | Event-driven BridgeManager |
| **Данные из Rust** | Polling `get_all_pool_balances()` | Push-события через канал |
| **Статус TX** | Нет | TxStatusTracker с latency |
| **Позиции** | Нет | DCA + PnL tracking |
| **Продажа** | Ввод суммы | 100% купленных токенов |
| **UI** | Базовый | Статус-бар (RPC, Gas, WS) |
| **Дедупликация** | Нет | Rust-side event dedup |

### Новые события от Rust

```python
_rust_event_handlers = {
    "EngineReady": ...,
    "ConnectionStatus": ...,
    "GasPriceUpdate": ...,
    "BalanceUpdate": ...,
    "PoolDetected": ...,
    "PoolUpdate": ...,
    "ImpactUpdate": ...,
    "TxSent": ...,
    "TxConfirmed": ...,
    "TradeStatus": ...,
}
```

---

## 🚧 TODO (v2)

### Архитектура
- [ ] **Мульти-сетевая поддержка** — абстракция Router/Quoter для разных DEX (Uniswap, Sushi, etc.)
- [ ] **Конфигурация сетей** — вынести адреса контрактов в `networks/*.json`, добавить ETH Mainnet, Arbitrum, Base
- [ ] **Hot-reload конфига** — переключение сети без restart

### UX
- [ ] **История транзакций** — таблица с фильтрацией по токену/кошельку
- [ ] **Экспорт PnL** — CSV/JSON выгрузка для анализа
- [ ] **Ценовые алерты** — уведомления при достижении target price

### Безопасность
- [ ] **Rate limiting RPC** — защита от бана публичных нод
- [ ] **Retry с backoff** — умный ретрай при network errors

---

## TaxRouter

Смарт-контракт для маршрутизации V2/V3 с комиссией.

**Адрес (BSC):** `0xcdcc4feee010fcd5301fd823085e3d3e7d414a46`

| Операция | Комиссия |
|----------|----------|
| Buy | 0.1% вычитается из входящей суммы |
| Sell | 0.1% вычитается из полученной суммы |

---

## Работа с TaxRouter

### Деплой контракта

Для работы в новой сети нужно задеплоить `TaxRouter` с параметрами конструктора (исходный код находится в папке `contract` данного репозитория):

```solidity
constructor(
    address _factory,    // V2 Factory (например PancakeSwap)
    address _WETH,       // Wrapped native token
    address _feeReceiver, // Куда отправлять 0.1% комиссии
    address _v3Router    // V3 SwapRouter
)
```

**Пример для BSC:**
```
Factory:    0xcA143Ce32Fe78f1f7019d7d551a6402fC5350c73
WETH:       0xbb4CdB9CBd36B01bD1cBaEBF2De08d9173bc095c
V3 Router:  0x1b81D678ffb9C0263b24A97847620C99d213eB14
```

### Настройка после деплоя

**1. Добавить Quote токены**

Только токены из списка `isQuoteToken` участвуют в логике комиссии. Без этого бот не будет знать, с какой стороны брать fee.

```solidity
function setQuoteToken(address token, bool status) external onlyOwner
```

Токены для добавления (BSC):
- WBNB: `0xbb4CdB9CBd36B01bD1cBaEBF2De08d9173bc095c`
- USDT: `0x55d398326f99059fF775485246999027B3197955`
- USDC: `0x8AC76a51cc950d9822D68b83fE1Ad97B32Cd580d`

**2. Смена Fee Receiver**

```solidity
function setFeeReceiver(address _newReceiver) external onlyOwner
```

**3. Передача владения**

```solidity
function transferOwnership(address newOwner) external onlyOwner
```

### Торговля без комиссий

Если хотите использовать бот без отчислений:

**Вариант 1: Свой контракт, свой кошелек**
Задеплойте TaxRouter и укажите `feeReceiver = свой_адрес`. Комиссия будет приходить вам.

**Вариант 2: Модификация контракта**
В исходнике `TaxRouter.sol` измените:
```solidity
// Было:
uint public constant FEE_BASIS_POINTS = 10; // 0.1%

// Стало:
uint public constant FEE_BASIS_POINTS = 0;  // 0%
```
Тогда комиссия не будет взиматься вообще.

**Вариант 3: Использовать стандартный роутер**
Если не нужна логика V2+V3 в одном контракте — можете адаптировать бот под любой DEX Router, изменив вызовы в Rust-ядре. Но это требует изменения кода.

---

## Добавление новой сети

### 1. Создать конфигурацию

Создайте файл `networks/<network_name>.json`:

```json
{
    "name": "Ethereum Mainnet",
    "db_path": "data/eth_mainnet.db",
    "chain_id": 1,
    "rpc_url": "https://eth.llamarpc.com",
    "wss_url": "wss://eth.llamarpc.com",
    "native_currency_symbol": "ETH",
    "native_currency_address": "0xeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee",
    "explorer_url": "https://etherscan.io/",
    "dex_router_address": "<YOUR_TAXROUTER_ADDRESS>",
    "v2_factory_address": "0x5C69bEe701ef814a2B6a3EDD4B1652CB9cc5aA6f",
    "v3_factory_address": "0x1F98431c8aD98523631AE4a59f267346ea31F984",
    "v2_router_address": "0x7a250d5630B4cF539739dF2C5dAcb4c659F2488D",
    "v3_quoter_address": "0xb27308f9F90D607463bb33eA1BeBb41C27CE5AB6",
    "public_rpc_urls": [
        "https://eth.llamarpc.com",
        "https://rpc.ankr.com/eth",
        "https://ethereum.publicnode.com"
    ],
    "fee_receiver": "<YOUR_FEE_RECEIVER_ADDRESS>",
    "default_quote_currency": "WETH",
    "quote_tokens": {
        "WETH": "0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2",
        "USDC": "0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48",
        "USDT": "0xdAC17F958D2ee523a2206206994597C13D831ec7"
    }
}
```

### 2. Деплой TaxRouter

Для работы в новой сети нужно задеплоить `TaxRouter`:

```bash
# Используя Remix или Hardhat
# 1. Откройте contracts/TaxRouter.sol
# 2. Скомпилируйте (Solidity 0.8.x)
# 3. Задеплойте в целевую сеть
# 4. Полученный адрес укажите в dex_router_address
```

**Важно:** Не меняйте наименования функций в контракте — бот использует специфичный интерфейс.

### 3. Проверить совместимость

Убедитесь, что в целевой сети есть:
- DEX с V2/V3 пулами (PancakeSwap-style интерфейс)
- Публичные RPC/WSS эндпоинты
- Низкие комиссии (или готовность ждать включения)

### Структура quote_tokens

`quote_tokens` — это токены, в которых будут проводиться торги. Ключ — символ, значение — адрес контракта. Бот автоматически определит decimals.

---

## Требования

### Зависимости
- Python 3.12+
- Rust (stable) + maturin
- Linux: `build-essential python3-dev libssl-dev`
- Windows: VS Build Tools 2022 (C++ workload)

### Сеть
- VPS во Франкфурте/Лондоне (пинг к BSC nodes)
- Или хотя бы проводной интернет 50+ Мбит/с
- **Wi-Fi/4G недопустимы** — джиттер убьёт отклик с возможными проблемами с которыми я не сталкивался при разработке

### Windows
- **Обязательно:** [Windows Terminal](https://apps.microsoft.com/store/detail/windows-terminal/9N0DX20HK701)
- Установить как терминал по умолчанию
- `cmd.exe` и PowerShell (legacy) сломают рендеринг и хоткеи

---

## Сборка

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

## Горячие клавиши

| Клавиша | Действие |
|---------|----------|
| T | Торговля |
| W | Кошельки |
| S | Настройки |
| L | Логи |
| ↑/↓ | BUY / SELL |
| Enter | Исполнить |
| Ctrl+R | Ресинк |
| Shift+↑/↓ | Slippage ±0.5% |
| Shift+←/→ | Gas ±0.1 Gwei |

---

## Безопасность

- AES-256-GCM шифрование приватных ключей
- PBKDF2-HMAC-SHA256 (480K итераций)
- Rust isolation для криптографии
- Нет бэкендов — работает автономно

---

## Disclaimer

AS IS. Автор не несёт ответственности за финансовые потери. Комиссия 0.1% за каждую транзакцию через TaxRouter — неотъемлемая часть логики бота. Можете свободно разворачивать/редактировать контракт под свои нужды, но не меняйте наименования функций. После деплоя контракта нужно внести адрес в конфиг соответствующей сети в поле `dex_router_address`.

---

**Telegram:** [@optional_username_37](https://t.me/optional_username_37)