import asyncio
import time
from typing import Dict, Any, List, Optional, Tuple
from bot.core.db_manager import DatabaseManager
from utils.aiologger import log

class GlobalCache:
    def __init__(self, db_manager: DatabaseManager):
        self._wallets: Dict[str, Dict[str, Any]] = {}
        self.config: Dict[str, Any] = {}
        self.db = db_manager
        self._lock = asyncio.Lock()
        
        self._market_gas_price_wei: Optional[int] = None
        self._token_decimals: Dict[str, int] = {} 
        self._balances: Dict[str, Dict[str, float]] = {}
        
        # ОСНОВНОЙ КЭШ БАЛАНСОВ В WEI - работает мгновенно из памяти
        self._exact_balances_wei: Dict[str, Dict[str, int]] = {}
        
        # --- НОВЫЙ КЭШ ПОЗИЦИЙ (Cost) В ПАМЯТИ ---
        # Key: "wallet_addr:token_addr" -> {'cost': int, 'amount': int}
        self._positions: Dict[str, Dict[str, int]] = {}
        
        self._active_trade_token: Optional[str] = None
        
        self._expected_amounts_out: Dict[str, Dict[str, Any]] = {} 
        self._active_trade_amount_for_quote: Optional[float] = None
        
        # --- КЭШ ДЛЯ ПУЛОВ ---
        self._best_pools: Dict[str, Dict[str, Any]] = {} 
        # ---------------------------

        # Локи для каждого кошелька
        self._wallet_locks: Dict[str, asyncio.Lock] = {}

        self._quote_prices_usd: Dict[str, float] = {"USDT": 1.0, "USDC": 1.0, "USD1": 1.0}
        
        # Флаг для отложенного дампа в БД
        self._pending_db_dump: bool = False

    async def initialize(self):
        async with self._lock:
            self.config = await self.db.get_config()
            wallets_from_db = await self.db.get_all_wallets()
            for wallet_info in wallets_from_db:
                address = wallet_info['address']
                full_wallet_data = await self.db.get_wallet_with_pk(address)
                if full_wallet_data:
                    self._wallets[address] = full_wallet_data
                    self._wallet_locks[address.lower()] = asyncio.Lock()
            
            # --- ВОССТАНОВЛЕНИЕ БАЛАНСОВ ИЗ БД ---
            cached_bals = await self.db.get_all_cached_balances()
            restored_count = 0
            for row in cached_bals:
                w_addr = row['wallet_address']
                t_addr = row['token_address']
                wei_str = row['balance_wei']
                decimals = row['decimals']
                
                try:
                    wei = int(wei_str)
                    if wei > 0:
                        if w_addr not in self._exact_balances_wei:
                            self._exact_balances_wei[w_addr] = {}
                        self._exact_balances_wei[w_addr][t_addr] = wei
                        
                        self._token_decimals[t_addr] = decimals
                        
                        if w_addr not in self._balances:
                            self._balances[w_addr] = {}
                        self._balances[w_addr][t_addr] = wei / (10 ** decimals)
                        restored_count += 1
                except ValueError:
                    continue
            
            # --- ВОССТАНОВЛЕНИЕ ПОЗИЦИЙ ИЗ БД В ПАМЯТЬ ---
            all_positions = await self.db.get_all_positions()
            pos_count = 0
            
            for row in all_positions:
                w = row.get('wallet_address', '').lower()
                t = row.get('token_address', '').lower()
                key = f"{w}:{t}"
                
                c_wei = row.get('total_cost_wei') or '0'
                a_wei = row.get('total_amount_wei') or '0'
                
                cost_val = int(c_wei) if c_wei and c_wei != '0' else 0
                amount_val = int(a_wei) if a_wei and a_wei != '0' else 0
                
                self._positions[key] = {
                    'cost': cost_val,
                    'amount': amount_val
                }
                pos_count += 1
                
                await log.debug(f"[RESTORE POS] key={key[:30]}... | cost={cost_val} | amount={amount_val}")
            
            # DEBUG: Итоговое состояние позиций в памяти
            if self._positions:
                for k, v in self._positions.items():
                    await log.debug(f"[MEMORY POS] {k[:30]}... | cost={v['cost']} | amount={v['amount']}")
            
            if restored_count > 0 or pos_count > 0:
                await log.info(f"Восстановлено {restored_count} балансов и {pos_count} позиций из БД.")

        await log.info(f"Кэш инициализирован. Загружено конфигов: {len(self.config)}, кошельков: {len(self._wallets)}")

    # --- БЫСТРЫЕ МЕТОДЫ БАЛАНСОВ (из памяти) ---
    
    def set_exact_balance_wei(self, wallet_address: str, token_address: str, balance_wei: int):
        """Установить баланс (из WebSocket события) - мгновенно"""
        wallet_addr_lower = wallet_address.lower()
        token_addr_lower = token_address.lower()
        if wallet_addr_lower not in self._exact_balances_wei:
            self._exact_balances_wei[wallet_addr_lower] = {}
        self._exact_balances_wei[wallet_addr_lower][token_addr_lower] = balance_wei

    def get_exact_balance_wei(self, wallet_address: str, token_address: str) -> Optional[int]:
        """Получить баланс из кэша - мгновенно"""
        return self._exact_balances_wei.get(wallet_address.lower(), {}).get(token_address.lower())

    def add_token_balance(self, wallet_address: str, token_address: str, amount_wei: int, decimals: int = 18, save_to_db: bool = True) -> int:
        wallet_addr_lower = wallet_address.lower()
        token_addr_lower = token_address.lower()
        
        if wallet_addr_lower not in self._exact_balances_wei:
            self._exact_balances_wei[wallet_addr_lower] = {}
        
        current = self._exact_balances_wei[wallet_addr_lower].get(token_addr_lower, 0)
        new_balance = current + amount_wei
        
        self._exact_balances_wei[wallet_addr_lower][token_addr_lower] = new_balance
        
        if wallet_addr_lower not in self._balances:
            self._balances[wallet_addr_lower] = {}
        self._balances[wallet_addr_lower][token_addr_lower] = new_balance / (10 ** decimals)
        
        self._token_decimals[token_addr_lower] = decimals
        
        if save_to_db and new_balance > 0:
            asyncio.create_task(self._save_balance_to_db(wallet_addr_lower, token_addr_lower, new_balance, decimals))
        
        return new_balance

    def subtract_token_balance(self, wallet_address: str, token_address: str, amount_wei: int, decimals: int = 18, save_to_db: bool = True) -> int:
        wallet_addr_lower = wallet_address.lower()
        token_addr_lower = token_address.lower()
        
        current = self._exact_balances_wei.get(wallet_addr_lower, {}).get(token_addr_lower, 0)
        new_balance = max(0, current - amount_wei)
        
        if wallet_addr_lower not in self._exact_balances_wei:
            self._exact_balances_wei[wallet_addr_lower] = {}
        
        self._exact_balances_wei[wallet_addr_lower][token_addr_lower] = new_balance
        
        if wallet_addr_lower not in self._balances:
            self._balances[wallet_addr_lower] = {}
        self._balances[wallet_addr_lower][token_addr_lower] = new_balance / (10 ** decimals)
        
        if save_to_db:
            if new_balance > 0:
                asyncio.create_task(self._save_balance_to_db(wallet_addr_lower, token_addr_lower, new_balance, decimals))
            else:
                asyncio.create_task(self._delete_balance_from_db(wallet_addr_lower, token_addr_lower))
        
        return new_balance

    async def _save_balance_to_db(self, wallet: str, token: str, balance_wei: int, decimals: int):
        try: await self.db.save_cached_balance(wallet, token, balance_wei, decimals)
        except Exception: pass

    async def _delete_balance_from_db(self, wallet: str, token: str):
        try: await self.db.delete_cached_balance(wallet, token)
        except Exception: pass

    async def get_or_load_balance_wei(self, wallet_address: str, token_address: str) -> int:
        wallet_addr_lower = wallet_address.lower()
        token_addr_lower = token_address.lower()
        
        cached = self._exact_balances_wei.get(wallet_addr_lower, {}).get(token_addr_lower)
        if cached is not None and cached > 0:
            return cached
        
        # Если в кэше нет, пробуем восстановить из позиции в памяти (если есть)
        pos = self.get_position_memory(wallet_address, token_address)
        if pos and pos['amount'] > 0:
            # Восстанавливаем в кэш балансов
            self.set_exact_balance_wei(wallet_address, token_address, pos['amount'])
            return pos['amount']
            
        return 0

    # --- УПРАВЛЕНИЕ ПОЗИЦИЯМИ (RAM + Async DB) ---

    def update_position_memory(self, wallet: str, token: str, added_cost: int, added_amount: int):
        """Обновляет позицию в памяти и БД"""
        w = wallet.lower()
        t = token.lower()
        key = f"{w}:{t}"
        
        # Инициализируем если нет
        if key not in self._positions:
            self._positions[key] = {'cost': 0, 'amount': 0}
        
        # Обновляем память
        self._positions[key]['cost'] += added_cost
        self._positions[key]['amount'] += added_amount
        
        new_cost = self._positions[key]['cost']
        new_amount = self._positions[key]['amount']
        
        asyncio.create_task(log.debug(f"[POSITION] {w[:8]}... | cost={new_cost} | amount={new_amount}"))
        
        # Отправляем ПОЛНЫЕ значения в БД (не дельту!)
        asyncio.create_task(self.db.set_position(wallet, token, new_cost, new_amount))


    def close_position_memory(self, wallet: str, token: str):
        """Полностью закрывает позицию"""
        key = f"{wallet.lower()}:{token.lower()}"
        
        if key in self._positions:
            old_pos = self._positions[key]
            asyncio.create_task(log.debug(
                f"[POSITION CLOSE] {wallet[:8]}... | REMOVED cost={old_pos['cost']}, amount={old_pos['amount']}"
            ))
            del self._positions[key]
        else:
            asyncio.create_task(log.debug(f"[POSITION CLOSE] {wallet[:8]}... | KEY NOT FOUND in memory!"))
        
        asyncio.create_task(self.db.close_position(wallet, token))


    def get_position_memory(self, wallet: str, token: str) -> Dict[str, int]:
        """Мгновенное получение позиции из памяти"""
        key = f"{wallet.lower()}:{token.lower()}"
        return self._positions.get(key, {'cost': 0, 'amount': 0})

    def get_open_positions_tokens(self) -> List[Tuple[str, str]]:
        """Возвращает список (wallet, token) для открытых позиций с amount > 0"""
        result = []
        for key, pos in self._positions.items():
            if pos.get('amount', 0) > 0:
                parts = key.split(':')
                if len(parts) == 2:
                    result.append((parts[0], parts[1]))
        return result

    # --- Получение списка всех токенов, которые есть на балансе ---
    def get_all_tracked_token_addresses(self) -> List[str]:
        tokens = set()
        for balances in self._exact_balances_wei.values():
            for t_addr, amount in balances.items():
                if amount > 0:
                    tokens.add(t_addr)
        return list(tokens)

    # --- МЕТОДЫ ДЛЯ РАБОТЫ С ПУЛАМИ ---
    def set_best_pool(self, token_address: str, quote_address: str, pool_info: Dict[str, Any]):
        key = f"{token_address.lower()}_{quote_address.lower()}"
        self._best_pools[key] = pool_info
        asyncio.create_task(self.db.save_cached_pool(token_address, quote_address, pool_info))

    def get_best_pool(self, token_address: str, quote_address: str) -> Optional[Dict[str, Any]]:
        key = f"{token_address.lower()}_{quote_address.lower()}"
        return self._best_pools.get(key)
    
    async def clear_pool_cache(self, token_address: str, quote_address: str):
        key = f"{token_address.lower()}_{quote_address.lower()}"
        if key in self._best_pools:
            del self._best_pools[key]
        await self.db.delete_cached_pool(token_address, quote_address)
    # ---------------------------------------------

    def get_wallet_lock(self, wallet_address: str) -> asyncio.Lock:
        wallet_addr_lower = wallet_address.lower()
        if wallet_addr_lower not in self._wallet_locks:
            self._wallet_locks[wallet_addr_lower] = asyncio.Lock()
        return self._wallet_locks[wallet_addr_lower]

    def set_active_trade_token(self, token_address: Optional[str]):
        self._active_trade_token = token_address.lower() if token_address else None

    def get_active_trade_token(self) -> Optional[str]:
        return self._active_trade_token

    def set_active_trade_amount_for_quote(self, amount: Optional[float]):
        self._active_trade_amount_for_quote = amount

    def get_active_trade_amount_for_quote(self) -> Optional[float]:
        return self._active_trade_amount_for_quote

    def set_token_decimals(self, token_address: str, decimals: int):
        self._token_decimals[token_address.lower()] = decimals

    def get_token_decimals(self, token_address: str) -> Optional[int]:
        return self._token_decimals.get(token_address.lower())

    def set_wallet_balance(self, wallet_address: str, token_address: str, balance: float):
        wallet_addr_lower = wallet_address.lower()
        if wallet_addr_lower not in self._balances:
            self._balances[wallet_addr_lower] = {}
        self._balances[wallet_addr_lower][token_address.lower()] = balance

    def get_wallet_balances(self, wallet_address: str) -> Dict[str, float]:
        return self._balances.get(wallet_address.lower(), {})
    
    def set_quote_price(self, symbol: str, price: float):
        self._quote_prices_usd[symbol] = price

    def get_quote_price(self, symbol: str) -> float:
        key = symbol[1:] if symbol.startswith('W') else symbol
        return self._quote_prices_usd.get(key, 0.0)

    def set_market_gas_price(self, gas_price_wei: int):
        self._market_gas_price_wei = gas_price_wei

    def get_market_gas_price(self) -> Optional[int]:
        return self._market_gas_price_wei

    async def add_wallet(self, address: str, private_key: str, name: str, enabled: bool = True):
        async with self._lock:
            await self.db.add_wallet(address, private_key, name, enabled)
            self._wallets[address] = {"address": address, "private_key": private_key, "name": name, "enabled": enabled}
            self._wallet_locks[address.lower()] = asyncio.Lock()
        return self._wallets[address]

    def get_wallet_by_address(self, address: str) -> Optional[Dict[str, Any]]:
        return self._wallets.get(address)
    
    def get_all_wallets(self, enabled_only: bool = False) -> List[Dict[str, Any]]:
        wallets_list = []
        for addr, data in self._wallets.items():
            if enabled_only and not data.get('enabled', False):
                continue
            safe_data = data.copy()
            safe_data.pop('private_key', None)
            wallets_list.append(safe_data)
        return wallets_list

    async def update_wallet(self, address: str, update_data: Dict[str, Any]):
        async with self._lock:
            await self.db.update_wallet(address, update_data)
            if address in self._wallets:
                self._wallets[address].update(update_data)
        return self._wallets.get(address)

    async def delete_wallet(self, address: str):
        async with self._lock:
            await self.db.delete_wallet(address)
            if address in self._wallets:
                del self._wallets[address]
                if address.lower() in self._wallet_locks: 
                    del self._wallet_locks[address.lower()]
        return {"status": "deleted"}

    def get_config(self) -> Dict[str, Any]:
        return self.config

    async def update_config(self, config_updates: Dict[str, Any]):
        async with self._lock:
            await self.db.update_config(config_updates)
            self.config.update(config_updates)
        return self.config

    def set_expected_amount_out(self, token_in: str, token_out: str, amount_in: float, expected_amount_out_wei: int):
        key = f"{token_in.lower()}_{token_out.lower()}_{amount_in}"
        self._expected_amounts_out[key] = {"amount_out_wei": expected_amount_out_wei, "timestamp": time.time()}

    def get_expected_amount_out(self, token_in: str, token_out: str, amount_in: float, max_age_seconds: int = 5) -> Optional[int]:
        key = f"{token_in.lower()}_{token_out.lower()}_{amount_in}"
        data = self._expected_amounts_out.get(key)
        if data and (time.time() - data["timestamp"] < max_age_seconds):
            return data["amount_out_wei"]
        return None

    async def dump_state_to_db(self):
        """Сохраняет текущие известные балансы в базу данных перед выходом."""
        async with self._lock:
            count = 0
            for w_addr, tokens_map in self._exact_balances_wei.items():
                for t_addr, wei in tokens_map.items(): 
                    if wei > 0: 
                        decimals = self.get_token_decimals(t_addr)
                        if decimals is None: decimals = 18
                        await self.db.save_cached_balance(w_addr, t_addr, wei, decimals)
                        count += 1
            if count > 0:
                await log.info(f"Сохранено {count} записей балансов в БД перед выходом.")