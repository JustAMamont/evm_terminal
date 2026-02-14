from typing import List, Dict, Optional, Tuple, Any

"""
dexbot_core: Высокопроизводительное ядро для DEX-ботов на языке Rust.
Обеспечивает мониторинг блокчейна, управление ключами и исполнение транзакций.
"""

# --- СИСТЕМНЫЕ ФУНКЦИИ И КОНФИГУРАЦИЯ ---

def get_network_config(network_name: str) -> Dict[str, Any]:
    """
    Загружает конфигурацию сети из JSON файла в папке 'networks/'.
    """
    ...

def get_available_networks() -> List[str]:
    """Возвращает список имен доступных JSON-конфигураций из папки 'networks/'."""
    ...

def reset_rust_state() -> None:
    """
    Полностью сбрасывает внутреннее состояние Rust-ядра:
    - Снимает флаг SHUTDOWN (позволяет запускать новых воркеров).
    - Очищает кеш нонсов и цен газа.
    - Очищает пул RPC соединений и список отслеживаемых кошельков.
    - Сбрасывает балансы пулов и останавливает WSS-сканеры.
    Используется при смене сети в интерфейсе.
    """
    ...

def shutdown_rust_workers() -> None:
    """Команда на мягкую остановку всех фоновых потоков Rust."""
    ...


# --- МОНИТОРИНГ И СОБЫТИЯ ---

def start_state_workers(
    private_rpc: str, 
    public_rpcs: List[str], 
    initial_wallets: List[str], 
    wss_url: Optional[str] = None
) -> None:
    """
    Запускает фоновые воркеры в Rust-runtime:
    - Проверка здоровья RPC узлов (выбор самого быстрого).
    - Отслеживание актуальных Gas Price (WSS + HTTP префетч).
    - Фоновое обновление Nonce для всех указанных кошельков.
    """
    ...

def start_token_monitor(wss_url: str, token_address: str) -> None:
    """Запускает WebSocket-подписку с параллельным HTTP-префетчем на Transfer-события."""
    ...

def stop_token_monitor() -> None:
    """Останавливает мониторинг событий токена."""
    ...

def get_pending_events() -> List[Tuple[str, str, str, str]]:
    """
    Извлекает очередь накопленных событий (Transfer) из Rust.
    Returns:
        Список кортежей: (to_address, token_address, amount_wei, tx_hash).
    """
    ...

def add_wallet_to_monitor(wallet_str: str) -> None:
    """Добавляет адрес кошелька в список для авто-обновления нонса."""
    ...

def remove_wallet_from_monitor(wallet_str: str) -> None:
    """Удаляет кошелек из системы мониторинга нонсов."""
    ...

def force_resync_nonce(wallet_str: str) -> None:
    """Принудительно синхронизирует Nonce кошелька с блокчейном по HTTP."""
    ...


# --- СКАНЕР ПУЛОВ ЛИКВИДНОСТИ ---

def start_pool_scanner(wss_url: str, pool_to_quote_map: Dict[str, str]) -> None:
    """
    Запускает гибридный мониторинг (WSS + HTTP Snapshot) балансов пулов ликвидности.
    """
    ...

def stop_pool_scanner() -> None:
    """Останавливает сканер пулов."""
    ...

def get_best_pool_address() -> Optional[Tuple[str, str]]:
    """Возвращает (адрес_пула, ликвидность_wei) для самого глубокого пула."""
    ...

def get_all_pool_balances() -> Dict[str, str]:
    """Возвращает текущий кеш балансов всех пулов {address: balance_wei}."""
    ...

def clear_pool_balances() -> None:
    """Очищает внутренний кэш балансов пулов."""
    ...


# --- БАЛАНСИРОВЩИК RPC ---

def get_best_rpc_url() -> Optional[str]:
    """Возвращает URL RPC ноды с минимальной задержкой."""
    ...

def get_healthy_rpc_urls(count: int) -> List[str]:
    """Возвращает список из N самых быстрых и здоровых RPC нод."""
    ...


# --- ИСПОЛНЕНИЕ ТРАНЗАКЦИЙ ---

def execute_swap_hot(
    private_key_hex: str,
    router_address: str,
    chain_id: int,
    method_type: str,
    amount_in: str,
    amount_out_min: str,
    path: List[str],
    to_address: str,
    deadline: int,
    gas_limit: int,
    value_str: str,
    manual_gas_price: int
) -> str:
    """Выполняет одиночный Swap транзакцию напрямую через Rust."""
    ...

def execute_approve_hot(
    private_key_hex: str,
    token_address: str,
    spender_address: str,
    chain_id: int,
    amount_in: str,
    gas_limit: int,
    manual_gas_price: int
) -> str:
    """Выполняет Approve токена. amount_in может быть числом или 'MAX'."""
    ...

def execute_batch_swap(
    private_keys: List[str],
    router_address: str,
    chain_id: int,
    method_type: str,
    amounts_in: List[str],
    amounts_out_min: List[str],
    path: List[str],
    deadline: int,
    gas_limit: int,
    value_str: str,
    manual_gas_price: int,
    v3_pool_fee: int = 0
) -> List[str]:
    """
    Выполняет параллельную пакетную рассылку транзакций обмена.
    Транзакции улетают в runtime Rust одновременно для минимального джиттера.
    """
    ...


# --- КРИПТОГРАФИЯ И БЕЗОПАСНОСТЬ ---

def init_or_load_keys(key_path: str, master_password: str) -> None:
    """
    Инициализирует мастер-ключ бота (Ed25519) и сохраняет его 
    в зашифрованном виде (AES-256-GCM + PBKDF2).
    """
    ...

def get_public_key() -> str:
    """Возвращает PEM-представление публичного ключа бота."""
    ...


# --- ТРЕКЕР ПРИБЫЛИ (PnL) ---

def start_pnl_tracker(
    rpc_url: str,
    wallet_addr: str,
    token_addr: str,
    quote_addr: str,
    balance_wei: str,
    cost_wei: str,
    pool_type: str,
    v3_fee: int,
    v2_router: str,
    v3_quoter: str
) -> None:
    """
    Запускает фоновый цикл расчета PnL. 
    При повторном вызове для той же пары старый поток мгновенно уничтожается (Abort).
    """
    ...

def stop_pnl_tracker(wallet_addr: str, token_addr: str) -> None:
    """Останавливает расчет прибыли для конкретной пары."""
    ...

def get_pnl_status(wallet_addr: str, token_addr: str) -> Optional[Tuple[float, str, str, bool]]:
    """
    Возвращает актуальные данные из Rust-стейта:
    (процент_pnl, текущая_чистая_стоимость_wei, общие_затраты_wei, идет_ли_загрузка)
    """
    ...

def clear_all_pnl_trackers() -> None:
    """
    Мгновенно останавливает и удаляет все запущенные воркеры PnL.
    Необходимо вызывать при смене сети.
    """
    ...