HELP_TEXT_RU = """
---

# 🚀 Руководство пользователя EVM_TRADER

**EVM_TRADER** — высокоскоростной терминал для торговли на DEX (PancakeSwap).

---

## 1. Первичная настройка

### Безопасность
При первом запуске создайте **Мастер-пароль**. Он шифрует приватные ключи локально в папке `data/`.

### Сети (подключенные и протестированные на данный момент)
- **BSC Mainnet** — работает с публичными RPC из коробки
- **BSC Testnet** — **требует приватный RPC** (публичные не поддерживают WebSocket)

### Приватный RPC (для Testnet обязателен!)
1. Получите endpoint у провайдера (Chainstack, QuickNode, Alchemy)
2. Вставьте HTTP endpoint в **Settings → RPC URL**
3. При сохранении приложение перезапустится

---

## 2. Кошельки (Wallets)

| Действие | Описание |
|----------|----------|
| Добавить кошелёк | Введите имя и приватный ключ |
| Включить/Выключить | Клик по столбцу "Active" |
| Скопировать адрес | Клик по адресу |

**Важно:** На кошельках должна быть нативная валюта  (ETH or BNB) для оплаты газа.

---

## 3. Торговля (Trade)

### Покупка (BUY)
1. Вставьте адрес токена в поле ввода
2. Введите сумму в quote-валюте (WETH/USDT) или `%` от баланса
3. Нажмите **КУПИТЬ** или `Enter`

### Продажа (SELL)
1. Выберите токен (вставьте адрес или выберите из позиций)
2. Нажмите `↓` или кликните панель SELL
3. Нажмите **ПРОДАТЬ**
4. **SELL продаёт 100% баланса токена**

### Режимы ввода суммы
| Формат | Пример | Описание |
|--------|--------|----------|
| Число (abs) | `0.1` | Точная сумма в quote-валюте |
| Процент | `50%` | Процент от баланса quote-токена |
| 100% | `100%` | Весь баланс quote-токена |

---

## 4. Настройки (Settings)

| Параметр | Описание |
|----------|----------|
| RPC URL | Приватный endpoint (для Testnet обязателен) |
| Quote валюта | WBNB, WETH, USDT, USDC, USD1, etc. |
| Slippage | Допустимое проскальзывание в % |
| Gas Price | Цена газа в Gwei |
| Gas Limit | Лимит газа на транзакцию |
| Trade Amount | Сумма по умолчанию |
| Auto-Fuel | Автопополнение BNB из WBNB |

---

## 5. Горячие клавиши

| Клавиша | Действие |
|---------|----------|
| `T` | Вкладка Торговля |
| `W` | Вкладка Кошельки |
| `S` | Вкладка Настройки |
| `L` | Вкладка Логи |
| `F` | Это руководство |
| `↑` / `↓` | Смена режима BUY / SELL |
| `Enter` | Выполнить операцию |
| `Ctrl+R` | Обновить кошельки |
| `Ctrl+Q` | Выход |

### Вставка текста

| Клавиша | Действие |
|---------|----------|
| `Ctrl+Shift+V` | Вставить из буфера обмена |
| `Ctrl+V` | **Не работает** в TUI |

> ⚠️ **Важно:** Обычный `Ctrl+V` в терминальных приложениях не работает. Всегда используйте `Ctrl+Shift+V` для вставки адресов, ключей и других данных.

---

## 6. Статус-бар

| Индикатор | Значение |
|-----------|----------|
| 🟢 RPC | Подключено к ноде |
| 🔴 RPC | Ошибка подключения |
| 🟢 WS | WebSocket активен |
| 🔴 WS | WebSocket отключен |
| ⛽ Gas | Текущая цена газа |
| ✅ Wallets | Есть активные кошельки |

---

## 7. Устранение неполадок

### "Пулы не найдены"
- Проверьте правильность адреса токена
- Попробуйте другую quote-валюту (WETH → USDT)
- Убедитесь что токен есть на DEX

### "WebSocket отключен" (Testnet)
- **Обязательно** настройте приватный RPC в Settings
- К примеру публичные RPC BSC Testnet не поддерживают WebSocket

### "Недостаточно ETH для газа"
- Пополните кошелёк нативной валютой
- Включите Auto-Fuel для автоматического обмена WETH → ETH

### Транзакции не проходят
- Увеличьте Slippage (для волатильных токенов)
- Увеличьте Gas Price при перегрузке сети

### Не вставляется текст
- Используйте `Ctrl+Shift+V` вместо `Ctrl+V`

---

## 8. Авто-Fuel

Функция автоматически конвертирует часть WETH в ETH для оплаты газа.

**Настройка:**
- Threshold: минимальный ETH для триггера
- Amount: сколько WETH конвертировать

**Пример:** Threshold=0.001, Amount=0.005
- Когда ETH < 0.001 → обмен 0.005 WETH на ETH
"""

HELP_TEXT_EN = """
---

# 🚀 EVM_TRADER User Guide

**EVM_TRADER** — high-speed terminal for trading on DEX (PancakeSwap).

---

## 1. Initial Setup

### Security
On first launch, create a **Master Password**. It encrypts private keys locally in the `data/` folder.

### Networks (currently connected and tested)
- **BSC Mainnet** — works with public RPC out of the box
- **BSC Testnet** — **requires private RPC** (public ones don't support WebSocket)

### Private RPC (required for Testnet!)
1. Get an endpoint from a provider (Chainstack, QuickNode, Alchemy)
2. Paste the HTTP endpoint into **Settings → RPC URL**
3. When saving, the application will restart

---

## 2. Wallets

| Action | Description |
|--------|-------------|
| Add wallet | Enter name and private key |
| Enable/Disable | Click on "Active" column |
| Copy address | Click on the address |

**Important:** Wallets must have native currency (ETH or BNB) for gas fees.

---

## 3. Trading

### Buying (BUY)
1. Paste the token address in the input field
2. Enter amount in quote currency (WETH/USDT) or `%` of balance
3. Press **BUY** or `Enter`

### Selling (SELL)
1. Select token (paste address or choose from positions)
2. Press `↓` or click the SELL panel
3. Press **SELL**
4. **SELL sells 100% of the token balance**

### Amount Input Modes
| Format | Example | Description |
|--------|---------|-------------|
| Number (abs) | `0.1` | Exact amount in quote currency |
| Percentage | `50%` | Percentage of quote token balance |
| 100% | `100%` | Entire quote token balance |

---

## 4. Settings

| Parameter | Description |
|-----------|-------------|
| RPC URL | Private endpoint (required for Testnet) |
| Quote Currency | WBNB, WETH, USDT, USDC, USD1, etc. |
| Slippage | Acceptable slippage in % |
| Gas Price | Gas price in Gwei |
| Gas Limit | Gas limit per transaction |
| Trade Amount | Default amount |
| Auto-Fuel | Auto-swap BNB from WBNB |

---

## 5. Hotkeys

| Key | Action |
|-----|--------|
| `T` | Trade tab |
| `W` | Wallets tab |
| `S` | Settings tab |
| `L` | Logs tab |
| `F` | This guide |
| `↑` / `↓` | Switch BUY / SELL mode |
| `Enter` | Execute operation |
| `Ctrl+R` | Refresh wallets |
| `Ctrl+Q` | Exit |

### Pasting Text

| Key | Action |
|-----|--------|
| `Ctrl+Shift+V` | Paste from clipboard |
| `Ctrl+V` | **Does not work** in TUI |

> ⚠️ **Important:** Regular `Ctrl+V` doesn't work in terminal applications. Always use `Ctrl+Shift+V` to paste addresses, keys, and other data.

---

## 6. Status Bar

| Indicator | Meaning |
|-----------|---------|
| 🟢 RPC | Connected to node |
| 🔴 RPC | Connection error |
| 🟢 WS | WebSocket active |
| 🔴 WS | WebSocket disconnected |
| ⛽ Gas | Current gas price |
| ✅ Wallets | Active wallets available |

---

## 7. Troubleshooting

### "Pools not found"
- Check the token address is correct
- Try a different quote currency (WETH → USDT)
- Make sure the token exists on DEX

### "WebSocket disconnected" (Testnet)
- **Required** to configure private RPC in Settings
- For example, public BSC Testnet RPCs don't support WebSocket

### "Not enough ETH for gas"
- Top up your wallet with native currency
- Enable Auto-Fuel for automatic WETH → ETH swap

### Transactions not going through
- Increase Slippage (for volatile tokens)
- Increase Gas Price during network congestion

### Text not pasting
- Use `Ctrl+Shift+V` instead of `Ctrl+V`

---

## 8. Auto-Fuel

This feature automatically converts part of WETH to ETH for gas fees.

**Configuration:**
- Threshold: minimum ETH to trigger
- Amount: how much WETH to convert

**Example:** Threshold=0.001, Amount=0.005
- When ETH < 0.001 → swap 0.005 WETH to ETH
"""