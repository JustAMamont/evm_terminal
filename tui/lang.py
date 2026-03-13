"""Lightweight i18n module for TUI"""

_TRANSLATIONS = {
    "en": {
        # Tabs
        "tab_trade": "Trade",
        "tab_wallets": "Wallets",
        "tab_settings": "Settings",
        "tab_logs": "Logs",
        "tab_help": "Help",
        
        # Trade
        "buy": "BUY",
        "sell": "SELL",
        "token_address": "Token Address",
        "amount": "Amount",
        "slippage": "Slippage",
        "gas_price": "Gas Price",
        "gas_limit": "Gas Limit",
        "price_impact": "Price Impact",
        "liquidity": "Liquidity",
        "pool_type": "Pool Type",
        "fee": "Fee",
        
        # Wallets
        "address": "Address",
        "balance": "Balance",
        "add_wallet": "Add Wallet",
        "remove": "Remove",
        "no_wallets": "No wallets added",
        "enter_private_key": "Enter private key",
        
        # Settings
        "rpc_url": "RPC URL",
        "quote_currency": "Quote Currency",
        "language": "Language",
        "auto_fuel": "Auto-Fuel",
        "save": "Save",
        "saved": "Settings saved",
        
        # Status
        "connecting": "Connecting...",
        "connected": "Connected",
        "disconnected": "Disconnected",
        "error": "Error",
        "syncing": "Syncing...",
        "ready": "Ready",
        
        # Messages
        "tx_sent": "Transaction sent",
        "tx_confirmed": "Transaction confirmed",
        "tx_failed": "Transaction failed",
        "insufficient_balance": "Insufficient balance",
        "invalid_address": "Invalid address",
        "invalid_amount": "Invalid amount",
        "copied": "Copied",
        "wallet_added": "Wallet added",
        "wallet_removed": "Wallet removed",
        
        # Errors
        "rpc_failed": "RPC connection failed",
        "ws_failed": "WebSocket failed",
        "no_wallet": "Add a wallet first",
        "no_token": "Enter token address",
        
        # Confirmations
        "confirm_exit": "Exit? (y/n)",
        "confirm_remove": "Remove wallet? (y/n)",
        
        # Help
        "hotkeys": "Hotkeys",
        "navigation": "Navigation",
        "trading": "Trading",
    },
    "ru": {
        # Tabs
        "tab_trade": "Торговля",
        "tab_wallets": "Кошельки",
        "tab_settings": "Настройки",
        "tab_logs": "Логи",
        "tab_help": "Помощь",
        
        # Trade
        "buy": "КУПИТЬ",
        "sell": "ПРОДАТЬ",
        "token_address": "Адрес токена",
        "amount": "Количество",
        "slippage": "Проскальзывание",
        "gas_price": "Цена газа",
        "gas_limit": "Лимит газа",
        "price_impact": "Влияние на цену",
        "liquidity": "Ликвидность",
        "pool_type": "Тип пула",
        "fee": "Комиссия",
        
        # Wallets
        "address": "Адрес",
        "balance": "Баланс",
        "add_wallet": "Добавить кошелёк",
        "remove": "Удалить",
        "no_wallets": "Кошельки не добавлены",
        "enter_private_key": "Введите приватный ключ",
        
        # Settings
        "rpc_url": "RPC URL",
        "quote_currency": "Валюта котировки",
        "language": "Язык",
        "auto_fuel": "Авто-заправка",
        "save": "Сохранить",
        "saved": "Настройки сохранены",
        
        # Status
        "connecting": "Подключение...",
        "connected": "Подключено",
        "disconnected": "Отключено",
        "error": "Ошибка",
        "syncing": "Синхронизация...",
        "ready": "Готов",
        
        # Messages
        "tx_sent": "Транзакция отправлена",
        "tx_confirmed": "Транзакция подтверждена",
        "tx_failed": "Транзакция отклонена",
        "insufficient_balance": "Недостаточно средств",
        "invalid_address": "Неверный адрес",
        "invalid_amount": "Неверное количество",
        "copied": "Скопировано",
        "wallet_added": "Кошелёк добавлен",
        "wallet_removed": "Кошелёк удалён",
        
        # Errors
        "rpc_failed": "Ошибка RPC",
        "ws_failed": "Ошибка WebSocket",
        "no_wallet": "Добавьте кошелёк",
        "no_token": "Введите адрес токена",
        
        # Confirmations
        "confirm_exit": "Выйти? (y/n)",
        "confirm_remove": "Удалить кошелёк? (y/n)",
        
        # Help
        "hotkeys": "Горячие клавиши",
        "navigation": "Навигация",
        "trading": "Торговля",
    }
}

_current_lang = "en"


def set_language(lang: str):
    global _current_lang
    if lang in _TRANSLATIONS:
        _current_lang = lang


def get_language() -> str:
    return _current_lang


def t(key: str) -> str:
    """Get translation by key"""
    return _TRANSLATIONS.get(_current_lang, {}).get(key, key)


def get_languages() -> list[str]:
    return list(_TRANSLATIONS.keys())