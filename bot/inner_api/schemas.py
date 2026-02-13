from typing import Dict, Any, List, Optional
from pydantic import BaseModel, Field
from enum import Enum
import time

class APICommand(BaseModel):
    command_id: str = Field(default_factory=lambda: str(time.time()))
    type: str
    data: Dict[str, Any] = Field(default_factory=dict)


class APIResponse(BaseModel):
    command_id: str
    status: str
    data: Dict[str, Any] = Field(default_factory=dict)
    error: Optional[str] = None
    timestamp: float = Field(default_factory=time.time)


class TradeAction(str, Enum):
    BUY = "buy"
    SELL = "sell"


class WalletCreate(BaseModel):
    private_key: str
    name: str
    enabled: bool = True


class WalletUpdate(BaseModel):
    name: Optional[str] = None
    enabled: Optional[bool] = None


class ConfigUpdate(BaseModel):
    slippage: Optional[float] = None
    max_workers: Optional[int] = None
    rpc_url: Optional[str] = None
    default_trade_amount: Optional[str] = None       
    default_trade_percentage: Optional[float] = None   
    default_quote_currency: Optional[str] = None
    gas_limit: Optional[int] = None
    max_fee_cents: Optional[int] = None
    stake_percentage: Optional[float] = None
    default_gas_price_gwei: Optional[float] = None
    # --- AUTO FUEL SETTINGS ---
    auto_fuel_enabled: Optional[bool] = None
    auto_fuel_threshold: Optional[float] = None # Порог (например, 0.005 BNB)
    auto_fuel_amount: Optional[float] = None    # Сколько BNB докупать


class TradeRequest(BaseModel):
    token_address: str
    quote_token: str
    action: TradeAction
    amount: float
    wallets: List[str]
    slippage: Optional[float] = None
    max_fee_cents: Optional[int] = None
    gas_price_gwei: Optional[float] = None

# Не используется - на будущее
class PoolSearchRequest(BaseModel):
    token_address: str
    quote_currency: Optional[str] = None
    min_liquidity: Optional[float] = None
    protocols: Optional[List[str]] = None