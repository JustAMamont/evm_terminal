import time
import asyncio
from typing import Optional, Tuple

from web3 import AsyncWeb3
from bot.core.config import Config, APPROVE_GAS_LIMIT
from bot.core.abis import ERC20_ABI
from utils.aiologger import log
from bot.cache import GlobalCache 

try:
    import dexbot_core
    RUST_AVAILABLE = True
except ImportError:
    RUST_AVAILABLE = False
    print("CRITICAL WARNING: 'dexbot_core' extension not found.")


class AccountManager:
    def __init__(self, private_key: str, cache: GlobalCache, config: Config, w3: AsyncWeb3):
        self.w3 = w3
        self.config = config
        self.cache = cache 
        
        self._raw_private_key = private_key
        
        try:
            self.account = self.w3.eth.account.from_key(private_key)
        except Exception:
            clean = private_key.strip()
            if not clean.startswith("0x"): clean = "0x" + clean
            self.account = self.w3.eth.account.from_key(clean)

        self.address = str(self.account.address)
        
    def _get_clean_key(self) -> str:
        """Возвращает ключ БЕЗ '0x'."""
        key_hex = self.account.key.hex()
        if key_hex.startswith("0x"): key_hex = key_hex[2:]
        return key_hex.strip()

    async def get_allowance(self, token_address: str) -> int:
        token_cs = self.w3.to_checksum_address(token_address)
        router_cs = self.w3.to_checksum_address(self.config.DEX_ROUTER_ADDRESS)
        token_contract = self.w3.eth.contract(address=token_cs, abi=ERC20_ABI)
        allowance = await token_contract.functions.allowance(self.address, router_cs).call()
        return int(allowance)

    async def execute_approve(self, token_address: str, amount_in_wei: Optional[int] = None, gas_limit: int = APPROVE_GAS_LIMIT, gas_price_wei: int = 0) -> bytes:
        if not RUST_AVAILABLE: return b'\x00' * 32

        clean_pk = self._get_clean_key()

        quotes = self.config.get('QUOTE_TOKENS')
        
        if token_address.lower() in [q.lower() for q in quotes]: # type: ignore
            print(True)
            gas_limit = 100000 
            
            try:
                await log.warning(f"[{self.address[:6]}] 🛡️ Proxy Quote Detected: Boosting Gas & Resetting allowance...")
                
                tx_hash_zero_str = await asyncio.to_thread(
                    dexbot_core.execute_approve_hot, # type: ignore
                    clean_pk,
                    str(token_address),
                    str(self.config.DEX_ROUTER_ADDRESS),
                    int(self.config.CHAIN_ID),
                    "0", 
                    int(gas_limit), 
                    gas_price_wei 
                )
                
                if "Error" not in tx_hash_zero_str:
                    clean_hash = tx_hash_zero_str.replace('"', '').replace("'", "").strip()
                    await log.info(f"[{self.address[:6]}] 🛡️ Proxy Quote Reset TX sent: {clean_hash}. Waiting for confirmation...")
                    
                    try:
                        receipt = await self.w3.eth.wait_for_transaction_receipt(clean_hash, timeout=30) # type: ignore
                        if receipt.status != 1: # type: ignore
                            await log.error(f"[{self.address[:6]}] ❌ Proxy Quote Reset Transaction FAILED (Reverted). Aborting main approve.")
                            return b'\x00' * 32
                        
                        await log.success(f"[{self.address[:6]}] ✅ Proxy Quote Reset Confirmed. Proceeding to main approve...")
                        
                    except Exception as e:
                        await log.error(f"[{self.address[:6]}] Timeout/Error waiting for Proxy Quote reset: {e}")
                        return b'\x00' * 32
                else:
                    await log.error(f"[{self.address[:6]}] Failed to send Proxy Quote reset tx: {tx_hash_zero_str}")
                    return b'\x00' * 32

            except Exception as e:
                await log.error(f"Error during Proxy Quote reset logic: {e}")
                return b'\x00' * 32

        amount_str = str(amount_in_wei) if amount_in_wei is not None else "MAX"

        tx_hash_str = await asyncio.to_thread(
            dexbot_core.execute_approve_hot, # type: ignore
            clean_pk,
            str(token_address),
            str(self.config.DEX_ROUTER_ADDRESS),
            int(self.config.CHAIN_ID),
            amount_str,
            int(gas_limit), 
            gas_price_wei 
        )
        
        tx_clean = tx_hash_str.replace('"', '').replace("'", "").strip()
        if "Error" in tx_clean:
             await log.error(f"Approve Error: {tx_clean}")
             return b'\x00' * 32

        await log.info(f"[{self.address[:6]}] 🛡️ RUST APPROVE: {tx_clean}")
        try:
            return bytes.fromhex(tx_clean.replace("0x", ""))
        except: return b'\x00' * 32

    async def execute_swap(self, 
                           token_in: str,             
                           token_out: str,            
                           amount_in: float,          
                           slippage: float,           
                           gas_limit: int,            
                           token_in_decimals: Optional[int] = None, 
                           expected_amount_out_wei: Optional[int] = None,
                           gas_price_wei: int = 0
                           ) -> Tuple[bytes, Optional[int]]: 
        if not RUST_AVAILABLE: return b'\x00' * 32, None

        token_in_lower = str(token_in).lower()
        token_out_lower = str(token_out).lower()
        native_lower = str(self.config.NATIVE_CURRENCY_ADDRESS).lower()
        
        is_buy_with_native = (token_in_lower == native_lower)
        is_sell_action = (token_out_lower == native_lower) or \
                         (token_out_lower in [str(x).lower() for x in self.config.QUOTE_TOKENS.values()])

        amount_in_wei: int
        if is_buy_with_native:
            amount_in_wei = int(amount_in * 10**18)
        elif is_sell_action:
            balance_wei = self.cache.get_exact_balance_wei(self.address, token_in) 
            if balance_wei is None or balance_wei == 0:
                if token_in_decimals:
                    balance_wei = int(amount_in * (10**token_in_decimals))
                else:
                    balance_wei = int(amount_in * 10**18) 
            amount_in_wei = int(balance_wei)
        else:
            dec = token_in_decimals if token_in_decimals is not None else 18
            amount_in_wei = int(amount_in * (10**dec))

        wrapped_native = str(self.config.QUOTE_TOKENS[f"W{self.config.NATIVE_CURRENCY_SYMBOL}"]).lower()
        path = [token_in_lower, token_out_lower]
        if path[0] == native_lower: path[0] = wrapped_native
        if path[1] == native_lower: path[1] = wrapped_native

        method_type = "TokensForTokens"
        if token_out_lower == native_lower: method_type = "TokensForETH"
        elif is_buy_with_native: method_type = "ETHForTokens"
        
        value_wei_str = str(amount_in_wei) if is_buy_with_native else "0"
        amount_out_min_str = "0"
        if not is_sell_action and expected_amount_out_wei is not None:
            min_wei = int(expected_amount_out_wei * (1 - slippage / 100.0))
            amount_out_min_str = str(min_wei)

        clean_pk = self._get_clean_key()

        tx_hash_str = await asyncio.to_thread(
            dexbot_core.execute_swap_hot, # type: ignore
            clean_pk,
            str(self.config.DEX_ROUTER_ADDRESS),
            int(self.config.CHAIN_ID),
            str(method_type),
            str(amount_in_wei),
            amount_out_min_str,
            path,
            str(self.address),
            int(time.time()) + 300,
            int(gas_limit),
            value_wei_str,
            gas_price_wei 
        )
        
        tx_clean = tx_hash_str.replace('"', '').replace("'", "").strip()
        if "Error" in tx_clean:
             await log.error(f"Rust Swap Error: {tx_clean}")
             return b'\x00' * 32, None

        try:
            tx_bytes = bytes.fromhex(tx_clean.replace("0x", ""))
            return tx_bytes, expected_amount_out_wei
        except ValueError:
            return b'\x00' * 32, None