import asyncio
import socket
import orjson
from typing import Optional, Callable, Dict, List
from dataclasses import dataclass

try:
    import dexbot_core
    RUST_AVAILABLE = True
except ImportError:
    dexbot_core = None
    RUST_AVAILABLE = False


# ===================== AUTO-FUEL SETTINGS =====================

@dataclass
class AutoFuelSettings:
    """Настройки авто-закупки газа"""
    auto_fuel_enabled: bool = False
    auto_fuel_threshold: float = 0.005
    auto_fuel_amount: float = 0.01
    fuel_quote_address: str = ""
    
    def to_dict(self) -> dict:
        return {
            "auto_fuel_enabled": self.auto_fuel_enabled,
            "auto_fuel_threshold": self.auto_fuel_threshold,
            "auto_fuel_amount": self.auto_fuel_amount,
            "fuel_quote_address": self.fuel_quote_address
        }


# ===================== ENGINE COMMANDS =====================

class EngineCommand:
    """
    Построитель команд для Rust ядра.
    
    Формат соответствует Rust enum:
    - Варианты с данными: {"type": "Name", "data": {...}}
    - Unit variants: {"type": "Name"}
    """
    
    @staticmethod
    def init(
        rpc: str,
        wss: str,
        chain_id: int,
        router: str,
        quoter: str,
        v2_factory: str,
        v3_factory: str,
        wrapped_native: str,
        native_address: str,
        wallets: List[tuple],
        public_rpc_urls: List[str],
        fuel,
        quote_symbol: str,
        quote_tokens: list
    ) -> dict:
        fuel_dict = fuel.to_dict() if hasattr(fuel, 'to_dict') else fuel
        return {
            "type": "Init",
            "data": {
                "rpc_url": rpc,
                "wss_url": wss,
                "chain_id": chain_id,
                "router": router,
                "quoter": quoter,
                "v2_factory": v2_factory,
                "v3_factory": v3_factory,
                "wrapped_native": wrapped_native,
                "native_address": native_address,
                "wallets": wallets,
                "public_rpc_urls": public_rpc_urls,
                "fuel_settings": fuel_dict,
                "quote_symbol": quote_symbol,
                "quote_tokens": quote_tokens
            }
        }
    
    @staticmethod
    def switch_token(token_address: str, quote_address: str, quote_symbol: str) -> dict:
        return {
            "type": "SwitchToken",
            "data": {
                "token_address": token_address,
                "quote_address": quote_address,
                "quote_symbol": quote_symbol
            }
        }
    
    @staticmethod
    def unsubscribe_token(token_address: str) -> dict:
        """Отписаться от обновлений токена"""
        return {
            "type": "UnsubscribeToken",
            "data": {
                "token_address": token_address
            }
        }
    
    @staticmethod
    def calc_impact(
        token_address: str,
        quote_address: str,
        amount_in: float,
        is_buy: bool
    ) -> dict:
        return {
            "type": "CalcImpact",
            "data": {
                "token_address": token_address,
                "quote_address": quote_address,
                "amount_in": amount_in,
                "is_buy": is_buy
            }
        }
    
    @staticmethod
    def execute_trade(
        action: str,
        token: str,
        quote_token: str,
        amount: float,
        wallets: List[str],
        gas_gwei: float,
        slippage: float,
        v3_fee: int = 2500,
        amounts_wei: Optional[Dict[str, str]] = None
    ) -> dict:
        return {
            "type": "ExecuteTrade",
            "data": {
                "action": action,
                "token": token,
                "quote_token": quote_token,
                "amount": amount,
                "wallets": wallets,
                "gas_gwei": gas_gwei,
                "slippage": slippage,
                "v3_fee": v3_fee,
                "amounts_wei": amounts_wei if amounts_wei else {}
            }
        }
    
    @staticmethod
    def update_settings(
        gas_price_gwei: Optional[float] = None,
        slippage: Optional[float] = None,
        fuel_enabled: Optional[bool] = None,
        fuel_quote_address: Optional[str] = None,
        rpc_url: Optional[str] = None,
        wss_url: Optional[str] = None,
        quote_symbol: Optional[str] = None
    ) -> dict:
        return {
            "type": "UpdateSettings",
            "data": {
                "gas_price_gwei": gas_price_gwei,
                "slippage": slippage,
                "fuel_enabled": fuel_enabled,
                "fuel_quote_address": fuel_quote_address,
                "rpc_url": rpc_url,
                "wss_url": wss_url,
                "quote_symbol": quote_symbol
            }
        }
    
    @staticmethod
    def update_price(symbol: str, price: float) -> dict:
        return {
            "type": "UpdatePrice",
            "data": {
                "symbol": symbol,
                "price": price
            }
        }
    
    @staticmethod
    def update_token_decimals(address: str, decimals: int) -> dict:
        return {
            "type": "UpdateTokenDecimals",
            "data": {
                "address": address,
                "decimals": decimals
            }
        }
    
    @staticmethod
    def add_wallet(address: str, private_key: str) -> dict:
        return {
            "type": "AddWallet",
            "data": {"address": address, "private_key": private_key}
        }
    
    @staticmethod
    def refresh_balance(wallet: str, token: str) -> dict:
        return {
            "type": "RefreshBalance",
            "data": {"wallet": wallet, "token": token}
        }
    
    @staticmethod
    def refresh_all_balances() -> dict:
        """Unit variant - БЕЗ data!"""
        return {"type": "RefreshAllBalances"}
    
    @staticmethod
    def shutdown() -> dict:
        """Unit variant - БЕЗ data!"""
        return {"type": "Shutdown"}


# ===================== BRIDGE MANAGER =====================

class BridgeManager:
    """
    Менеджер моста между Python и Rust ядром.
    Использует socket pair для мгновенных сигналов.
    """
    
    def __init__(self, event_handler_callback: Callable[[dict], None]):
        self.event_handler = event_handler_callback
        self._rsock: Optional[socket.socket] = None
        self._wsock: Optional[socket.socket] = None
        self._is_running = False
        self._balance_cache: Dict[str, Dict[str, float]] = {}
        self._gas_price: float = 1.0
        self._connected: bool = False
        self._event_queue: asyncio.Queue = asyncio.Queue()
        
    @property
    def gas_price(self) -> float:
        return self._gas_price
    
    @property
    def is_connected(self) -> bool:
        return self._connected
    
    def get_balance(self, wallet: str, token: str) -> float:
        """Получить кэшированный баланс"""
        return self._balance_cache.get(wallet.lower(), {}).get(token.lower(), 0.0)
    
    def start(self):
        """Запуск моста"""
        if not RUST_AVAILABLE:
            print("[Bridge] Rust core not available")
            return
            
        if self._is_running:
            return
        
        self._rsock, self._wsock = socket.socketpair()
        self._rsock.setblocking(False)
        self._is_running = True
        
        loop = asyncio.get_running_loop()
        loop.add_reader(self._rsock.fileno(), self._on_rust_signal)
        
        dexbot_core.init_bridge_signal(self._wsock.fileno())
        asyncio.create_task(self._log("BridgeManager: Транспорт инициализирован"))
    
    def stop(self):
        """Остановка моста"""
        if not self._is_running:
            return
            
        self._is_running = False
        
        try:
            loop = asyncio.get_running_loop()
            loop.remove_reader(self._rsock.fileno())
        except:
            pass
        
        try:
            if self._rsock:
                self._rsock.close()
        except:
            pass
        try:
            if self._wsock:
                self._wsock.close()
        except:
            pass
            
        self._rsock = None
        self._wsock = None
    
    def _on_rust_signal(self):
        """Низкоуровневый обработчик: вычитывает все накопившиеся события"""
        try:
            self._rsock.recv(4096)
            
            while True:
                raw_json = dexbot_core.pop_from_bridge()
                if not raw_json:
                    break
                
                try:
                    event = orjson.loads(raw_json)
                    self._process_event(event)
                except Exception as e:
                    print(f"[Bridge] JSON parse error: {e}")
                    
        except BlockingIOError:
            pass
        except Exception as e:
            print(f"[Bridge] Signal error: {e}")
    
    def _process_event(self, event: dict):
        """Обработка события и обновление кэша"""
        etype = event.get("type", "")
        data = event.get("data", {})
        
        if etype == "ConnectionStatus":
            self._connected = data.get("connected", False)
            
        elif etype == "GasPriceUpdate":
            self._gas_price = data.get("gas_price_gwei", 1.0)
            
        elif etype == "BalanceUpdate":
            wallet = data.get("wallet", "").lower()
            token = data.get("token", "").lower()
            balance = data.get("float_val", 0.0)
            
            if wallet not in self._balance_cache:
                self._balance_cache[wallet] = {}
            self._balance_cache[wallet][token] = balance
        
        try:
            self._event_queue.put_nowait(event)
        except Exception as e:
            print(f"[Bridge] Queue put error: {e}")
    
    def send(self, command):
        """Отправка команды в Rust ядро"""
        if not RUST_AVAILABLE:
            return
            
        try:
            if hasattr(command, 'model_dump'):
                cmd_dict = command.model_dump()
            elif hasattr(command, 'dict'):
                cmd_dict = command.dict()
            elif hasattr(command, 'to_dict'):
                cmd_dict = command.to_dict()
            elif hasattr(command, '__dataclass_fields__'):
                from dataclasses import asdict
                cmd_dict = asdict(command)
            else:
                cmd_dict = command
            
            cmd_json = orjson.dumps(cmd_dict).decode('utf-8')
            dexbot_core.push_to_engine(cmd_json)
        except Exception as e:
            print(f"[Bridge] Send error: {e}")
    
    async def _log(self, message: str):
        from utils.aiologger import log
        await log.info(message)