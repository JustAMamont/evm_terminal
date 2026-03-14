# Help texts for EVM Trader

HELP_TEXT_EN = """
---

# EVM_TRADER User Guide

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
2. Enter amount in quote currency (WETH or WBNB or other) or `%` of balance
3. Press **BUY** or `Enter`

### Selling (SELL)
1. Select token (paste address or choose from positions)
2. Press `↓` or click the SELL panel
3. Press **SELL**
4. **SELL sells 100% of the token balance**

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
| `H` | Help tab |
| `↑` / `↓` | Switch BUY / SELL mode |
| `Enter` | Execute operation |
| `Ctrl+R` | Refresh wallets |
| `Ctrl+Q` | Exit |

---

## 6. Status Bar

| Indicator | Status | Meaning |
|-----------|--------|---------|
| RPC | Green | Connected to node |
| RPC | Red | Connection error |
| WS | Green | WebSocket active |
| WS | Red | WebSocket disconnected |
| Gas | Green | Gas price < 3 Gwei |
| Gas | Yellow | Gas price 3-5 Gwei |
| Gas | Red | Gas price > 5 Gwei |
| Wallets | Green checkmark | Active wallets available |
| Wallets | Red X | No active wallets |

---

## 7. Troubleshooting

### "Pools not found"
- Check the token address is correct
- Try a different quote currency (WETH → USDT)
- Make sure the token exists on DEX

### "WebSocket disconnected" (Testnet)
- **Required** to configure private RPC in Settings

### "Not enough ETH for gas"
- Top up your wallet with native currency
- Enable Auto-Fuel for automatic WETH → ETH swap

---

## 8. Auto-Fuel

This feature automatically converts part of WETH to ETH for gas fees.

**Configuration:**
- Threshold: minimum ETH to trigger
- Amount: how much WETH to convert

**Example:** Threshold=0.001, Amount=0.005
- When ETH < 0.001 → swap 0.005 WETH to ETH
"""

HELP_TEXT_RU = """
---

# Руководство пользователя EVM_TRADER

**EVM_TRADER** — высокоскоростной терминал для торговли на DEX (PancakeSwap).

---

## 1. Первичная настройка

### Безопасность
При первом запуске создайте **Мастер-пароль**. Он шифрует приватные ключи локально в папке `data/`.

### Сети (подключенные и протестированные)
- **BSC Mainnet** — работает с публичными RPC из коробки
- **BSC Testnet** — **требует приватный RPC** (публичные не поддерживают WebSocket)

### Приватный RPC (для Testnet обязателен!)
1. Получите endpoint у провайдера (Chainstack, QuickNode, Alchemy)
2. Вставьте HTTP endpoint в **Настройки → RPC URL**
3. При сохранении приложение перезапустится

---

## 2. Кошельки

| Действие | Описание |
|----------|----------|
| Добавить кошелёк | Введите имя и приватный ключ |
| Включить/Выключить | Клик по столбцу "Active" |
| Скопировать адрес | Клик по адресу |

**Важно:** На кошельках должна быть нативная валюта (ETH или BNB — зависит от сети) для оплаты газа.

---

## 3. Торговля

### Покупка (BUY)
1. Вставьте адрес токена в поле ввода
2. Введите сумму в quote-валюте (WETH, WBNB или др.) или `%` от баланса
3. Нажмите **КУПИТЬ** или `Enter`

### Продажа (SELL)
1. Выберите токен (вставьте адрес или выберите из позиций)
2. Нажмите `↓` или кликните панель SELL
3. Нажмите **ПРОДАТЬ**
4. **SELL продаёт 100% баланса токена**

---

## 4. Настройки

| Параметр | Описание |
|----------|----------|
| RPC URL | Приватный endpoint (для Testnet обязателен) |
| Quote валюта | WBNB, WETH, USDT, USDC, USD1 и др. |
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
| `H` | Вкладка Помощь |
| `↑` / `↓` | Смена режима BUY / SELL |
| `Enter` | Выполнить операцию |
| `Ctrl+R` | Обновить кошельки |
| `Ctrl+Q` | Выход |

---

## 6. Статус-бар

| Индикатор | Цвет | Значение |
|-----------|------|----------|
| RPC | Зелёный | Подключено к ноде |
| RPC | Красный | Ошибка подключения |
| WS | Зелёный | WebSocket активен |
| WS | Красный | WebSocket отключен |
| Gas | Зелёный | Цена газа < 3 Gwei |
| Gas | Жёлтый | Цена газа 3-5 Gwei |
| Gas | Красный | Цена газа > 5 Gwei |
| Wallets | Зелёная галочка | Есть активные кошельки |
| Wallets | Красный крестик | Нет активных кошельков |

---

## 7. Устранение неполадок

### "Пулы не найдены"
- Проверьте правильность адреса токена
- Попробуйте другую quote-валюту (WETH → USDT)
- Убедитесь что токен есть на DEX

### "WebSocket отключен" (Testnet)
- **Обязательно** настройте приватный RPC в Настройках

### "Недостаточно ETH для газа"
- Пополните кошелёк нативной валютой
- Включите Auto-Fuel для автоматического обмена WETH → ETH

---

## 8. Авто-Fuel

Функция автоматически конвертирует часть WETH в ETH для оплаты газа.

**Настройка:**
- Threshold: минимальный ETH для триггера
- Amount: сколько WETH конвертировать

**Пример:** Threshold=0.001, Amount=0.005
- Когда ETH < 0.001 → обмен 0.005 WETH на ETH
"""

HELP_TEXT = HELP_TEXT_EN


def get_help_text(lang: str = "en") -> str:
    """Get help text by language code."""
    if lang == "ru":
        return HELP_TEXT_RU
    return HELP_TEXT_EN
