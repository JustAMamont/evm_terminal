import sys

try:
    import dexbot_core
except ImportError:
    dexbot_core = None

def load_resource_bundle(bundle_name: str) -> dict:
    """
    Загружает конфигурацию сети напрямую из защищенного Rust-ядра.
    """
    if not dexbot_core:
        raise RuntimeError("CRITICAL: Secure Core (dexbot_core) not found. Cannot load network config.")
    
    try:
        # Вызов Rust-функции, которая вернет Python-словарь
        # Адреса роутеров расшифровываются внутри Rust "на лету"
        return dexbot_core.get_network_config(bundle_name) # type: ignore
    except Exception as e:
        # Rust выбросит исключение, если сеть не найдена
        raise ValueError(f"Secure resource '{bundle_name}' load failed: {e}")

def enumerate_adapters() -> list:
    """
    Возвращает список доступных сетей из Rust-ядра.
    """
    if not dexbot_core:
        print("WARNING: dexbot_core not loaded, no networks available.")
        return []
    
    try:
        return dexbot_core.get_available_networks() # type: ignore
    except Exception as e:
        print(f"Error enumerating adapters from Core: {e}")
        return []
