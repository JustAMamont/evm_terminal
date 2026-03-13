import asyncio
import socket
import struct
from typing import Optional, Callable, Dict, List
from dataclasses import dataclass


try:
    import dexbot_core
    RUST_AVAILABLE = True
except ImportError:
    dexbot_core = None
    RUST_AVAILABLE = False


# ===================== EVENT TYPE REGISTRY =====================

class EventType:
    """Must match Rust EventType enum"""
    EngineReady      = 0x0000
    Log              = 0x0001
    ConnectionStatus = 0x0002
    GasPriceUpdate   = 0x0003
    BalanceUpdate    = 0x0100
    PoolDetected     = 0x0200
    PoolUpdate       = 0x0201
    PoolNotFound     = 0x0202
    ImpactUpdate     = 0x0203
    TxSent           = 0x0300
    TxConfirmed      = 0x0301
    TradeStatus      = 0x0302
    AutoFuelError    = 0x0303
    PnLUpdate        = 0x0400


class CommandType:
    """Must match Rust CommandType enum"""
    Init                = 0x0000
    Shutdown            = 0x0001
    SwitchToken         = 0x0100
    UnsubscribeToken    = 0x0101
    ExecuteTrade        = 0x0200
    CalcImpact          = 0x0201
    UpdatePrice         = 0x0300
    UpdateSettings      = 0x0301
    UpdateTokenDecimals = 0x0302
    RefreshBalance      = 0x0303
    AddWallet           = 0x0304
    RefreshAllBalances  = 0x0305


# ===================== PACK HELPERS =====================

def pack_u8(w: bytearray, v: int):
    w.append(v & 0xFF)

def pack_u16(w: bytearray, v: int):
    w.extend(struct.pack('<H', v))

def pack_u32(w: bytearray, v: int):
    w.extend(struct.pack('<I', v))

def pack_u64(w: bytearray, v: int):
    w.extend(struct.pack('<Q', v))

def pack_f64(w: bytearray, v: float):
    w.extend(struct.pack('<d', v))

def pack_bool(w: bytearray, v: bool):
    w.append(1 if v else 0)

def pack_string(w: bytearray, s: str):
    encoded = s.encode('utf-8')
    pack_u16(w, len(encoded))
    w.extend(encoded)


# ===================== UNPACK HELPERS =====================

class ByteReader:
    def __init__(self, data: bytes):
        self.data = data
        self.pos = 0
    
    def read(self, n: int) -> bytes:
        if self.pos + n > len(self.data):
            raise ValueError("Unexpected end of data")
        result = self.data[self.pos:self.pos + n]
        self.pos += n
        return result
    
    def u8(self) -> int:
        return self.read(1)[0]
    
    def u16(self) -> int:
        return struct.unpack('<H', self.read(2))[0]
    
    def u32(self) -> int:
        return struct.unpack('<I', self.read(4))[0]
    
    def u64(self) -> int:
        return struct.unpack('<Q', self.read(8))[0]
    
    def f64(self) -> float:
        return struct.unpack('<d', self.read(8))[0]
    
    def bool_(self) -> bool:
        return self.u8() != 0
    
    def string(self) -> str:
        length = self.u16()
        return self.read(length).decode('utf-8')
    
    def exhausted(self) -> bool:
        return self.pos >= len(self.data)


# ===================== AUTO-FUEL SETTINGS =====================

@dataclass
class AutoFuelSettings:
    auto_fuel_enabled: bool = False
    auto_fuel_threshold: float = 0.005
    auto_fuel_amount: float = 0.01
    fuel_quote_address: str = ""
    
    def pack(self, w: bytearray):
        pack_bool(w, self.auto_fuel_enabled)
        pack_f64(w, self.auto_fuel_threshold)
        pack_f64(w, self.auto_fuel_amount)
        pack_string(w, self.fuel_quote_address)
    
    def to_dict(self) -> dict:
        return {
            "auto_fuel_enabled": self.auto_fuel_enabled,
            "auto_fuel_threshold": self.auto_fuel_threshold,
            "auto_fuel_amount": self.auto_fuel_amount,
            "fuel_quote_address": self.fuel_quote_address
        }


# ===================== ENGINE COMMAND PACKER =====================

class EngineCommand:
    """Builds binary commands for Rust core"""
    
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
        quote_tokens: dict
    ) -> bytes:
        w = bytearray()
        pack_u16(w, CommandType.Init)
        
        pack_string(w, rpc)
        pack_string(w, wss)
        pack_u64(w, chain_id)
        pack_string(w, router)
        pack_string(w, quoter)
        pack_string(w, v2_factory)
        pack_string(w, v3_factory)
        pack_string(w, wrapped_native)
        pack_string(w, native_address)
        
        pack_u16(w, len(wallets))
        for addr, key in wallets:
            pack_string(w, addr)
            pack_string(w, key)
        
        pack_u16(w, len(public_rpc_urls))
        for url in public_rpc_urls:
            pack_string(w, url)
        
        if hasattr(fuel, 'pack'):
            fuel.pack(w)
        else:
            fs = AutoFuelSettings(**fuel) if isinstance(fuel, dict) else fuel
            fs.pack(w)
        
        pack_string(w, quote_symbol)
        
        pack_u16(w, len(quote_tokens))
        for sym, addr in quote_tokens.items():
            pack_string(w, sym)
            pack_string(w, addr)
        
        return bytes(w)
    
    @staticmethod
    def switch_token(token_address: str, quote_address: str, quote_symbol: str) -> bytes:
        w = bytearray()
        pack_u16(w, CommandType.SwitchToken)
        pack_string(w, token_address)
        pack_string(w, quote_address)
        pack_string(w, quote_symbol)
        return bytes(w)
    
    @staticmethod
    def unsubscribe_token(token_address: str) -> bytes:
        w = bytearray()
        pack_u16(w, CommandType.UnsubscribeToken)
        pack_string(w, token_address)
        return bytes(w)
    
    @staticmethod
    def calc_impact(
        token_address: str,
        quote_address: str,
        amount_in: float,
        is_buy: bool
    ) -> bytes:
        w = bytearray()
        pack_u16(w, CommandType.CalcImpact)
        pack_string(w, token_address)
        pack_string(w, quote_address)
        pack_f64(w, amount_in)
        pack_bool(w, is_buy)
        return bytes(w)
    
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
    ) -> bytes:
        w = bytearray()
        pack_u16(w, CommandType.ExecuteTrade)
        
        pack_string(w, action)
        pack_string(w, token)
        pack_string(w, quote_token)
        pack_f64(w, amount)
        
        pack_u16(w, len(wallets))
        for wallet in wallets:
            pack_string(w, wallet)
        
        pack_f64(w, gas_gwei)
        pack_f64(w, slippage)
        pack_u32(w, v3_fee)
        
        if amounts_wei:
            pack_bool(w, True)
            pack_u16(w, len(amounts_wei))
            for k, v in amounts_wei.items():
                pack_string(w, k)
                pack_string(w, v)
        else:
            pack_bool(w, False)
        
        return bytes(w)
    
    @staticmethod
    def update_settings(
        gas_price_gwei: Optional[float] = None,
        slippage: Optional[float] = None,
        fuel_enabled: Optional[bool] = None,
        fuel_quote_address: Optional[str] = None,
        rpc_url: Optional[str] = None,
        wss_url: Optional[str] = None,
        quote_symbol: Optional[str] = None
    ) -> bytes:
        w = bytearray()
        pack_u16(w, CommandType.UpdateSettings)
        
        if gas_price_gwei is not None:
            pack_bool(w, True)
            pack_f64(w, gas_price_gwei)
        else:
            pack_bool(w, False)
        
        if slippage is not None:
            pack_bool(w, True)
            pack_f64(w, slippage)
        else:
            pack_bool(w, False)
        
        if fuel_enabled is not None:
            pack_bool(w, True)
            pack_bool(w, fuel_enabled)
        else:
            pack_bool(w, False)
        
        if fuel_quote_address is not None:
            pack_bool(w, True)
            pack_string(w, fuel_quote_address)
        else:
            pack_bool(w, False)
        
        if rpc_url is not None:
            pack_bool(w, True)
            pack_string(w, rpc_url)
        else:
            pack_bool(w, False)
        
        if wss_url is not None:
            pack_bool(w, True)
            pack_string(w, wss_url)
        else:
            pack_bool(w, False)
        
        if quote_symbol is not None:
            pack_bool(w, True)
            pack_string(w, quote_symbol)
        else:
            pack_bool(w, False)
        
        return bytes(w)
    
    @staticmethod
    def update_price(symbol: str, price: float) -> bytes:
        w = bytearray()
        pack_u16(w, CommandType.UpdatePrice)
        pack_string(w, symbol)
        pack_f64(w, price)
        return bytes(w)
    
    @staticmethod
    def update_token_decimals(address: str, decimals: int) -> bytes:
        w = bytearray()
        pack_u16(w, CommandType.UpdateTokenDecimals)
        pack_string(w, address)
        pack_u8(w, decimals)
        return bytes(w)
    
    @staticmethod
    def add_wallet(address: str, private_key: str) -> bytes:
        w = bytearray()
        pack_u16(w, CommandType.AddWallet)
        pack_string(w, address)
        pack_string(w, private_key)
        return bytes(w)
    
    @staticmethod
    def refresh_balance(wallet: str, token: str) -> bytes:
        w = bytearray()
        pack_u16(w, CommandType.RefreshBalance)
        pack_string(w, wallet)
        pack_string(w, token)
        return bytes(w)
    
    @staticmethod
    def refresh_all_balances() -> bytes:
        w = bytearray()
        pack_u16(w, CommandType.RefreshAllBalances)
        return bytes(w)
    
    @staticmethod
    def shutdown() -> bytes:
        w = bytearray()
        pack_u16(w, CommandType.Shutdown)
        return bytes(w)


# ===================== EVENT UNPACKER =====================

def unpack_event(data: bytes) -> dict:
    """Unpack binary event to dict, matches Rust EngineEvent::unpack"""
    r = ByteReader(data)
    
    type_id = r.u16()
    
    if type_id == EventType.EngineReady:
        return {"type": "EngineReady"}
    
    elif type_id == EventType.Log:
        return {
            "type": "Log",
            "data": {
                "level": r.string(),
                "message": r.string()
            }
        }
    
    elif type_id == EventType.ConnectionStatus:
        return {
            "type": "ConnectionStatus",
            "data": {
                "connected": r.bool_(),
                "message": r.string()
            }
        }
    
    elif type_id == EventType.GasPriceUpdate:
        return {
            "type": "GasPriceUpdate",
            "data": {
                "gas_price_gwei": r.f64()
            }
        }
    
    elif type_id == EventType.BalanceUpdate:
        return {
            "type": "BalanceUpdate",
            "data": {
                "wallet": r.string(),
                "token": r.string(),
                "wei": r.string(),
                "float_val": r.f64(),
                "symbol": r.string()
            }
        }
    
    elif type_id == EventType.PoolDetected:
        return {
            "type": "PoolDetected",
            "data": {
                "pool_type": r.string(),
                "address": r.string(),
                "token": r.string(),
                "quote": r.string(),
                "liquidity_usd": r.f64(),
                "fee": r.u32(),
                "spot_price": r.f64(),
                "token_symbol": r.string(),
                "token_name": r.string()
            }
        }
    
    elif type_id == EventType.PoolUpdate:
        return {
            "type": "PoolUpdate",
            "data": {
                "pool_address": r.string(),
                "pool_type": r.string(),
                "token": r.string(),
                "quote": r.string(),
                "reserve0": r.string() if r.bool_() else None,
                "reserve1": r.string() if r.bool_() else None,
                "sqrt_price_x96": r.string() if r.bool_() else None,
                "tick": r.u32() if r.bool_() else None,
                "liquidity": r.u64() | (r.u64() << 64) if r.bool_() else None,
                "spot_price": r.f64() if r.bool_() else None,
                "liquidity_usd": r.f64() if r.bool_() else None
            }
        }
    
    elif type_id == EventType.PoolNotFound:
        token = r.string()
        selected_quote = r.string()
        count = r.u16()
        available_quotes = []
        for _ in range(count):
            available_quotes.append((r.string(), r.string()))
        
        return {
            "type": "PoolNotFound",
            "data": {
                "token": token,
                "selected_quote": selected_quote,
                "available_quotes": available_quotes
            }
        }
    
    elif type_id == EventType.PnLUpdate:
        return {
            "type": "PnLUpdate",
            "data": {
                "wallet": r.string(),
                "token": r.string(),
                "pnl_pct": r.f64(),
                "pnl_abs": r.string(),
                "current_value": r.string(),
                "current_price": r.f64(),
                "is_loading": r.bool_()
            }
        }
    
    elif type_id == EventType.ImpactUpdate:
        return {
            "type": "ImpactUpdate",
            "data": {
                "token": r.string(),
                "quote": r.string(),
                "amount_in": r.f64(),
                "impact_pct": r.f64(),
                "expected_out": r.string(),
                "is_buy": r.bool_()
            }
        }
    
    elif type_id == EventType.TradeStatus:
        return {
            "type": "TradeStatus",
            "data": {
                "wallet": r.string(),
                "action": r.string(),
                "status": r.string(),
                "message": r.string(),
                "tx_hash": r.string() if r.bool_() else None,
                "token_address": r.string(),
                "amount": r.f64(),
                "tokens_received": r.string() if r.bool_() else None,
                "tokens_sold": r.string() if r.bool_() else None,
                "token_decimals": r.u8()
            }
        }
    
    elif type_id == EventType.TxSent:
        return {
            "type": "TxSent",
            "data": {
                "tx_hash": r.string(),
                "wallet": r.string(),
                "action": r.string(),
                "amount": r.f64(),
                "token": r.string(),
                "timestamp_ms": r.u64()
            }
        }
    
    elif type_id == EventType.TxConfirmed:
        return {
            "type": "TxConfirmed",
            "data": {
                "tx_hash": r.string(),
                "wallet": r.string(),
                "gas_used": r.u64(),
                "status": r.string(),
                "confirm_block": r.u64(),
                "timestamp_ms": r.u64()
            }
        }
    
    elif type_id == EventType.AutoFuelError:
        return {
            "type": "AutoFuelError",
            "data": {
                "wallet": r.string(),
                "reason": r.string()
            }
        }
    
    else:
        return {"type": "Unknown", "data": {"type_id": type_id}}


# ===================== BRIDGE MANAGER =====================

class BridgeManager:
    def __init__(self, event_handler_callback: Callable[[dict], None]):
        self.event_handler = event_handler_callback
        self._rsock: Optional[socket.socket] = None
        self._wsock: Optional[socket.socket] = None
        self._is_running = False
        self._balance_cache: Dict[str, Dict[str, float]] = {}
        self._gas_price: float = 1.0
        self._connected: bool = False
        self._event_queue: asyncio.Queue = asyncio.Queue()
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        
    @property
    def gas_price(self) -> float:
        return self._gas_price
    
    @property
    def is_connected(self) -> bool:
        return self._connected
    
    def get_balance(self, wallet: str, token: str) -> float:
        return self._balance_cache.get(wallet.lower(), {}).get(token.lower(), 0.0)
    
    async def start(self):
        self._loop = asyncio.get_running_loop()
        self._rsock, self._wsock = socket.socketpair()
        self._rsock.setblocking(False)
        self._is_running = True
        
        await dexbot_core.init_bridge_signal(self._wsock.fileno())
        
        self._loop.add_reader(self._rsock.fileno(), self._on_signal)

    def _on_signal(self):
        try:
            self._rsock.recv(4096)
        except BlockingIOError:
            pass
        
        while True:
            raw = dexbot_core.pop_event_from_ring()
            if not raw:
                break
            try:
                event = unpack_event(raw)
                self._process_event(event)
            except Exception:
                pass
    
    async def stop(self):
        if not self._is_running:
            return
        
        self._is_running = False
        
        if self._loop and self._rsock:
            try:
                self._loop.remove_reader(self._rsock.fileno())
            except Exception:
                pass
        
        if self._rsock:
            self._rsock.close()
        if self._wsock:
            self._wsock.close()
        self._rsock = None
        self._wsock = None
    

    async def _process_pending_events(self):
        while True:
            raw = await dexbot_core.pop_event_from_ring()
            if not raw:
                break
            try:
                event = unpack_event(raw)
                self._process_event(event)
            except Exception:
                pass
    
    def _process_event(self, event):
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
        
        self._event_queue.put_nowait(event)
    
    async def send(self, command: bytes):
        if not RUST_AVAILABLE:
            return
        dexbot_core.push_command_to_ring(command)