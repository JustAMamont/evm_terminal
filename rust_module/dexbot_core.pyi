from typing import List, Dict, Optional, Tuple, Any

"""
dexbot_core: Высокопроизводительное ядро для DEX-ботов на языке Rust.
Обеспечивает мониторинг блокчейна, управление ключами и исполнение транзакций.
"""

def get_network_config(network_name: str) -> Dict[str, Any]:
    """
    Загружает конфигурацию сети из JSON файла в папке 'networks/'.
    
    Args:
        network_name: Имя файла (например, 'bsc', 'polygon').
    Returns:
        Словарь с RPC, ID сети, адресами роутеров и токенов.
    """
    ...

def get_available_networks() -> List[str]:
    """Возвращает список имен доступных JSON-конфигураций из папки 'networks/'."""
    ...

def start_state_workers(
    private_rpc: str, 
    public_rpcs: List[str], 
    initial_wallets: List[str], 
    wss_url: Optional[str] = None
) -> None:
    """
    Запускает фоновые воркеры в Rust-runtime:
    - Проверка здоровья RPC узлов (выбор самого быстрого).
    - Отслеживание актуальных Gas Price.
    - Фоновое обновление Nonce для всех указанных кошельков.
    """
    ...

def start_token_monitor(wss_url: str, token_address: str) -> None:
    """Запускает WebSocket-подписку на Transfer-события конкретного токена."""
    ...

def stop_token_monitor() -> None:
    """Останавливает мониторинг событий токена."""
    ...

def get_pending_events() -> List[Tuple[str, str, str, str]]:
    """
    Извлекает очередь накопленных событий из Rust.
    Returns:
        Список кортежей: (to_address, token_address, amount_wei, tx_hash).
    """
    ...

def add_wallet_to_monitor(wallet_str: str) -> None:
    """Добавляет адрес кошелька в список для отслеживания (авто-обновление нонса)."""
    ...

def remove_wallet_from_monitor(wallet_str: str) -> None:
    """Удаляет кошелек из системы мониторинга."""
    ...

def force_resync_nonce(wallet_str: str) -> None:
    """Принудительно синхронизирует Nonce кошелька с блокчейном."""
    ...

def shutdown_rust_workers() -> None:
    """Команда на мягкую остановку всех фоновых потоков Rust."""
    ...

def start_pool_scanner(wss_url: str, pool_to_quote_map: Dict[str, str]) -> None:
    """
    Мониторит балансы пулов ликвидности в реальном времени.
    Нужно для мгновенного получения цены без лишних RPC-запросов.
    """
    ...

def stop_pool_scanner() -> None:
    """Останавливает сканер пулов."""
    ...

def get_best_pool_address() -> Optional[Tuple[str, str]]:
    """Возвращает (адрес_пула, ликвидность) для самого глубокого пула."""
    ...

def get_all_pool_balances() -> Dict[str, str]:
    """Возвращает текущий кеш балансов всех пулов {address: balance_wei}."""
    ...

def clear_pool_balances() -> None:
    """Очищает данные о балансах пулов."""
    ...

def get_best_rpc_url() -> Optional[str]:
    """Возвращает URL RPC ноды с минимальной задержкой в данный момент."""
    ...

def get_healthy_rpc_urls(count: int) -> List[str]:
    """Возвращает список из N самых быстрых RPC нод."""
    ...

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
    """Выполняет одиночный Swap (через TaxRouter или стандартный)."""
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
    """Делает Approve токена. amount_in может быть 'MAX'."""
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
    Выполняет пакетную рассылку транзакций обмена.
    Транзакции улетают параллельно из Rust-runtime для максимальной скорости.
    """
    ...

def init_or_load_keys(key_path: str, master_password: str) -> None:
    """
    Инициализирует мастер-ключ бота (Ed25519) и сохраняет его 
    в зашифрованном виде (AES-256-GCM) по указанному пути.
    """
    ...

def get_public_key() -> str:
    """Возвращает PEM-представление публичного ключа бота."""
    ...

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
    Запускает цикличный расчет прибыли (PnL). 
    Результат учитывает комиссии DEX и налог роутера (0.1%).
    """
    ...

def stop_pnl_tracker(wallet_addr: str, token_addr: str) -> None:
    """Останавливает отслеживание прибыли для пары."""
    ...

def get_pnl_status(wallet_addr: str, token_addr: str) -> Optional[Tuple[float, str, str, bool]]:
    """
    Возвращает статус позиции:
    (процент_pnl, чистая_стоимость_wei, затраты_wei, идет_ли_загрузка)
    """
    ...