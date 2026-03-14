"""Lightweight i18n module for TUI and Auth"""

_TRANSLATIONS = {
    "en": {
        # === TABS ===
        "tab_trade": "Trade",
        "tab_wallets": "Wallets",
        "tab_settings": "Settings",
        "tab_logs": "Logs",
        "tab_help": "Help",
        
        # === TRADE PANEL ===
        "buy": "BUY",
        "sell": "SELL",
        "pair": "Pair",
        "token_info_none": "Token Info: None",
        "placeholder_token": "Token address 0x...",
        "suggestion": "💡 Better pool available",
        "amount_currency": "Amount / Currency",
        "sell_full": "SELL 100%",
        "market_data": "Market Data",
        "active_wallets": "Active Wallets",
        
        # === WALLETS ===
        "address": "Address",
        "balance": "Balance",
        "add_wallet": "Add Wallet",
        "remove": "Remove",
        "no_wallets": "No wallets added",
        "enter_private_key": "Enter private key",
        "placeholder_name": "Wallet name",
        "placeholder_pk": "Private key",
        "save": "Save",
        "delete_selected": "Delete Selected",
        
        # === SETTINGS ===
        "main_settings": "Main Settings",
        "rpc_url": "RPC URL",
        "stablecoin_quote": "Quote Currency (stablecoin)",
        "language": "Language",
        "autofuel_title": "Auto-Fuel Settings",
        "autofuel_enable": "Enable Auto-Fuel",
        "autofuel_on": "On",
        "autofuel_off": "Off",
        "tx_settings": "Transaction Settings",
        "gas_price": "Gas Price (Gwei)",
        "slippage": "Slippage (%)",
        "trade_amount": "Default Trade Amount",
        "gas_limit": "Gas Limit",
        
        # === STATUS ===
        "connecting": "Connecting...",
        "connected": "Connected",
        "disconnected": "Disconnected",
        "error": "Error",
        "syncing": "Syncing...",
        "ready": "Ready",
        
        # === MESSAGES ===
        "tx_sent": "Transaction sent",
        "tx_confirmed": "Transaction confirmed",
        "tx_failed": "Transaction failed",
        "insufficient_balance": "Insufficient balance",
        "invalid_address": "Invalid address",
        "invalid_amount": "Invalid amount",
        "copied": "Copied",
        "wallet_added": "Wallet added",
        "wallet_removed": "Wallet removed",
        "saved": "Settings saved",
        
        # === ERRORS ===
        "rpc_failed": "RPC connection failed",
        "ws_failed": "WebSocket failed",
        "no_wallet": "Add a wallet first",
        "no_token": "Enter token address",
        
        # === CONFIRMATIONS ===
        "confirm_exit": "Exit? (y/n)",
        "confirm_remove": "Remove wallet? (y/n)",
        
        # === HELP ===
        "hotkeys": "Hotkeys",
        "navigation": "Navigation",
        "trading": "Trading",
        
        # === FOOTER BINDINGS ===
        "footer_quit": "Quit",
        "footer_reload": "Reload",
        "footer_trade": "Trade",
        "footer_wallets": "Wallets",
        "footer_settings": "Settings",
        "footer_logs": "Logs",
        "footer_help": "Help",
        
        # === TABLE HEADERS ===
        "th_pair": "Pair",
        "th_pool": "Pool",
        "th_tvl": "TVL",
        "th_price": "Price",
        "th_bought": "Bought",
        "th_impact_buy": "Impact BUY",
        "th_impact_sell": "Impact SELL",
        "th_pnl": "PnL",
        "th_wallet": "Wallet",
        "th_name": "Name",
        "th_status": "Status",
        
        # === AUTH MESSAGES ===
        "auth_title": "AUTHORIZATION: {} Network",
        "auth_new_password_warning": "ATTENTION: Create a master password!",
        "auth_password_hint": "(Password is used to encrypt keys in the database)",
        "auth_new_password": "New password",
        "auth_repeat_password": "Repeat password",
        "auth_passwords_mismatch": "Passwords do not match. Please try again.",
        "auth_enter_password": "Enter your password",
        "auth_wrong_password": "Wrong password. Attempts left: {}",
        "auth_critical_error": "Critical authorization error: {}",
    },
    "ru": {
        # === TABS ===
        "tab_trade": "Торговля",
        "tab_wallets": "Кошельки",
        "tab_settings": "Настройки",
        "tab_logs": "Логи",
        "tab_help": "Помощь",
        
        # === TRADE PANEL ===
        "buy": "КУПИТЬ",
        "sell": "ПРОДАТЬ",
        "pair": "Пара",
        "token_info_none": "Токен: не выбран",
        "placeholder_token": "Адрес токена 0x...",
        "suggestion": "💡 Есть пул лучше",
        "amount_currency": "Сумма / Валюта",
        "sell_full": "ПРОДАТЬ 100%",
        "market_data": "Рыночные данные",
        "active_wallets": "Активные кошельки",
        
        # === WALLETS ===
        "address": "Адрес",
        "balance": "Баланс",
        "add_wallet": "Добавить кошелёк",
        "remove": "Удалить",
        "no_wallets": "Кошельки не добавлены",
        "enter_private_key": "Введите приватный ключ",
        "placeholder_name": "Имя кошелька",
        "placeholder_pk": "Приватный ключ",
        "save": "Сохранить",
        "delete_selected": "Удалить выбранное",
        
        # === SETTINGS ===
        "main_settings": "Основные настройки",
        "rpc_url": "RPC URL",
        "stablecoin_quote": "Валюта котировки (стейбл)",
        "language": "Язык",
        "autofuel_title": "Авто-заправка",
        "autofuel_enable": "Включить авто-заправку",
        "autofuel_on": "Вкл",
        "autofuel_off": "Выкл",
        "tx_settings": "Настройки транзакций",
        "gas_price": "Цена газа (Gwei)",
        "slippage": "Проскальзывание (%)",
        "trade_amount": "Сумма по умолчанию",
        "gas_limit": "Лимит газа",
        
        # === STATUS ===
        "connecting": "Подключение...",
        "connected": "Подключено",
        "disconnected": "Отключено",
        "error": "Ошибка",
        "syncing": "Синхронизация...",
        "ready": "Готов",
        
        # === MESSAGES ===
        "tx_sent": "Транзакция отправлена",
        "tx_confirmed": "Транзакция подтверждена",
        "tx_failed": "Транзакция отклонена",
        "insufficient_balance": "Недостаточно средств",
        "invalid_address": "Неверный адрес",
        "invalid_amount": "Неверное количество",
        "copied": "Скопировано",
        "wallet_added": "Кошелёк добавлен",
        "wallet_removed": "Кошелёк удалён",
        "saved": "Настройки сохранены",
        
        # === ERRORS ===
        "rpc_failed": "Ошибка RPC",
        "ws_failed": "Ошибка WebSocket",
        "no_wallet": "Добавьте кошелёк",
        "no_token": "Введите адрес токена",
        
        # === CONFIRMATIONS ===
        "confirm_exit": "Выйти? (y/n)",
        "confirm_remove": "Удалить кошелёк? (y/n)",
        
        # === HELP ===
        "hotkeys": "Горячие клавиши",
        "navigation": "Навигация",
        "trading": "Торговля",
        
        # === FOOTER BINDINGS ===
        "footer_quit": "Выход",
        "footer_reload": "Обновить",
        "footer_trade": "Торговля",
        "footer_wallets": "Кошельки",
        "footer_settings": "Настройки",
        "footer_logs": "Логи",
        "footer_help": "Помощь",
        
        # === TABLE HEADERS ===
        "th_pair": "Пара",
        "th_pool": "Пул",
        "th_tvl": "TVL",
        "th_price": "Цена",
        "th_bought": "Куплено",
        "th_impact_buy": "Импакт BUY",
        "th_impact_sell": "Импакт SELL",
        "th_pnl": "PnL",
        "th_wallet": "Кошелёк",
        "th_name": "Имя",
        "th_status": "Статус",
        
        # === AUTH MESSAGES ===
        "auth_title": "АВТОРИЗАЦИЯ: Сеть {}",
        "auth_new_password_warning": "ВНИМАНИЕ: Придумайте и введите мастер-пароль!",
        "auth_password_hint": "(Пароль используется для шифрования ключей в БД)",
        "auth_new_password": "Новый пароль",
        "auth_repeat_password": "Повторите пароль",
        "auth_passwords_mismatch": "Пароли не совпадают. Попробуйте снова.",
        "auth_enter_password": "Введите ваш пароль",
        "auth_wrong_password": "Неверный пароль. Осталось попыток: {}",
        "auth_critical_error": "Критическая ошибка авторизации: {}",
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


# === AUTH-SPECIFIC FUNCTIONS ===

def ta(key: str, *args) -> str:
    """
    Get translation with format args.
    Usage: ta("auth_title", "BSC") -> "AUTHORIZATION: BSC Network"
    """
    template = _TRANSLATIONS.get(_current_lang, {}).get(key, key)
    if args:
        try:
            return template.format(*args)
        except (IndexError, KeyError):
            return template
    return template


async def get_language_from_db(db_manager) -> str:
    """
    Load language setting from database using existing get_config() method.
    Language is stored in global_settings table with key 'language'.
    Returns 'en' by default or if error.
    """
    try:
        config = await db_manager.get_config()
        lang = config.get('language', 'en')
        if lang in _TRANSLATIONS:
            return lang
    except Exception:
        pass
    
    return "en"
