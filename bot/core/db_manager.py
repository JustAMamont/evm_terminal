import aiosqlite
from typing import List, Dict, Any, Optional
from pathlib import Path
from utils.security import SecurityManager

SENSITIVE_KEYS = {'rpc_url'}

class DatabaseManager:
    def __init__(self, db_path: str, global_db_path: str = "data/global.db"):
        self.db_path = Path(db_path)
        self.global_db_path = Path(global_db_path)
        
        self.conn: Optional[aiosqlite.Connection] = None
        self.global_conn: Optional[aiosqlite.Connection] = None

        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.global_db_path.parent.mkdir(parents=True, exist_ok=True)
        
        self.security = SecurityManager()

    async def connect(self):
        if not self.conn or not self.conn.is_alive():
            self.conn = await aiosqlite.connect(self.db_path)
            self.conn.row_factory = aiosqlite.Row
            await self.conn.execute("PRAGMA journal_mode=WAL;")

        if not self.global_conn or not self.global_conn.is_alive():
            self.global_conn = await aiosqlite.connect(self.global_db_path)
            self.global_conn.row_factory = aiosqlite.Row
            await self.global_conn.execute("PRAGMA journal_mode=WAL;")
        
        await self._create_tables()

    async def close(self):
        if self.conn: await self.conn.close(); self.conn = None
        if self.global_conn: await self.global_conn.close(); self.global_conn = None

    async def _create_tables(self):
        async with self.conn.cursor() as cursor: # type: ignore
            await cursor.execute('''
                CREATE TABLE IF NOT EXISTS wallets (
                    address TEXT PRIMARY KEY, private_key TEXT NOT NULL,
                    name TEXT NOT NULL, enabled BOOLEAN NOT NULL DEFAULT 1
                )''')
            await cursor.execute('''
                CREATE TABLE IF NOT EXISTS recent_tokens (
                    token_address TEXT PRIMARY KEY, name TEXT, symbol TEXT,
                    last_traded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )''')
            await cursor.execute('''
                CREATE TABLE IF NOT EXISTS config (
                    key TEXT PRIMARY KEY, value TEXT
                )''')
            await cursor.execute('''
                CREATE TABLE IF NOT EXISTS pending_trade_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    payload TEXT NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            # Таблица кэша балансов
            await cursor.execute('''
                CREATE TABLE IF NOT EXISTS cached_balances (
                    wallet_address TEXT,
                    token_address TEXT,
                    balance_wei TEXT,
                    decimals INTEGER,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (wallet_address, token_address)
                )
            ''')
            # Таблица кэша пулов
            await cursor.execute('''
                CREATE TABLE IF NOT EXISTS cached_pools (
                    token_address TEXT,
                    quote_address TEXT,
                    pool_data_json TEXT,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (token_address, quote_address)
                )
            ''')
            # --- Активные позиции (для PnL и DCA) ---
            await cursor.execute('''
                CREATE TABLE IF NOT EXISTS active_positions (
                    wallet_address TEXT,
                    token_address TEXT,
                    total_cost_wei TEXT, -- Сколько всего потрачено (quote token)
                    total_amount_wei TEXT, -- Сколько всего куплено (base token)
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (wallet_address, token_address)
                )
            ''')
        await self.conn.commit() # type: ignore

        async with self.global_conn.cursor() as cursor: # type: ignore
            await cursor.execute('''
                CREATE TABLE IF NOT EXISTS security (
                    key_name TEXT PRIMARY KEY, salt BLOB, verifier TEXT
                )''')
            await cursor.execute('''
                CREATE TABLE IF NOT EXISTS global_settings (
                    key TEXT PRIMARY KEY, value TEXT
                )''')
        await self.global_conn.commit() # type: ignore

    async def is_encrypted(self) -> bool:
        async with self.global_conn.cursor() as cursor: # type: ignore
            await cursor.execute("SELECT 1 FROM security WHERE key_name = 'main'")
            return await cursor.fetchone() is not None

    async def set_password(self, password: str):
        salt = self.security.generate_salt()
        self.security.unlock(password, salt)
        verifier = self.security.encrypt("VERIFICATION_SUCCESS")
        
        async with self.global_conn.cursor() as cursor: # type: ignore
            await cursor.execute("INSERT OR REPLACE INTO security (key_name, salt, verifier) VALUES ('main', ?, ?)", (salt, verifier))
        await self.global_conn.commit() # type: ignore
        
        await self._migrate_plain_data()

    async def unlock_db(self, password: str) -> bool:
        async with self.global_conn.cursor() as cursor: # type: ignore
            await cursor.execute("SELECT salt, verifier FROM security WHERE key_name = 'main'")
            row = await cursor.fetchone()
            
        if not row: return False
        self.security.unlock(password, row['salt'])
        try:
            return self.security.decrypt(row['verifier']) == "VERIFICATION_SUCCESS"
        except Exception:
            return False

    async def _migrate_plain_data(self):
        wallets = await self.get_all_wallets_raw()
        for w in wallets:
            pk = w['private_key']
            if pk and not pk.startswith("UklGR"): 
                encrypted_pk = self.security.encrypt(pk)
                async with self.conn.cursor() as cursor: # type: ignore
                    await cursor.execute("UPDATE wallets SET private_key = ? WHERE address = ?", (encrypted_pk, w['address']))
        
        config = await self.get_config(raw=True)
        for key in SENSITIVE_KEYS:
            if key in config:
                val = str(config[key])
                try:
                    self.security.decrypt(val) 
                except Exception: 
                    encrypted_val = self.security.encrypt(val)
                    async with self.conn.cursor() as cursor: # type: ignore
                        await cursor.execute("UPDATE config SET value = ? WHERE key = ?", (encrypted_val, key))
        await self.conn.commit() # type: ignore

    # --- Методы для кошельков ---
    async def add_wallet(self, address: str, private_key: str, name: str, enabled: bool):
        encrypted_pk = self.security.encrypt(private_key)
        async with self.conn.cursor() as cursor: # type: ignore
            await cursor.execute("INSERT INTO wallets (address, private_key, name, enabled) VALUES (?, ?, ?, ?)",(address, encrypted_pk, name, enabled))
        await self.conn.commit() # type: ignore

    async def get_wallet_with_pk(self, address: str) -> Optional[Dict[str, Any]]:
        async with self.conn.cursor() as cursor: # type: ignore
            await cursor.execute("SELECT * FROM wallets WHERE address = ?", (address,))
            row = await cursor.fetchone()
        if row:
            data = dict(row)
            try: data['private_key'] = self.security.decrypt(data['private_key'])
            except: pass 
            return data
        return None

    async def get_all_wallets_raw(self) -> List[Dict[str, Any]]:
        async with self.conn.cursor() as cursor: # type: ignore
            await cursor.execute("SELECT * FROM wallets")
            rows = await cursor.fetchall()
        return [dict(row) for row in rows]

    async def get_all_wallets(self, enabled_only: bool = False) -> List[Dict[str, Any]]:
        query = "SELECT address, name, enabled FROM wallets"
        if enabled_only: query += " WHERE enabled = 1"
        async with self.conn.cursor() as cursor: # type: ignore
            await cursor.execute(query)
            rows = await cursor.fetchall()
        return [dict(row) for row in rows]

    async def update_wallet(self, address: str, update_data: Dict[str, Any]):
        fields = ', '.join([f"{key} = ?" for key in update_data.keys()])
        values = list(update_data.values()) + [address]
        async with self.conn.cursor() as cursor: # type: ignore
            await cursor.execute(f"UPDATE wallets SET {fields} WHERE address = ?", values)
        await self.conn.commit() # type: ignore

    async def delete_wallet(self, address: str):
        async with self.conn.cursor() as cursor: # type: ignore
            await cursor.execute("DELETE FROM wallets WHERE address = ?", (address,))
        await self.conn.commit() # type: ignore

    # --- Методы Config ---
    async def get_config(self, raw: bool = False) -> Dict[str, Any]:
        config = {}
        async with self.conn.cursor() as cursor:  # type: ignore
            await cursor.execute("SELECT key, value FROM config")
            rows = await cursor.fetchall()
        for row in rows:
            key, value = row['key'], row['value']
            if value is None:
                config[key] = None; continue
            if not raw and key in SENSITIVE_KEYS and self.security.is_active():
                try: value = self.security.decrypt(value)
                except Exception: pass
            
            # --- Корректный парсинг Boolean и чисел ---
            if isinstance(value, str):
                if value.lower() == 'true':
                    config[key] = True
                    continue
                elif value.lower() == 'false':
                    config[key] = False
                    continue
            
            try:
                float_val = float(value)
                config[key] = int(float_val) if float_val.is_integer() else float_val
            except (ValueError, TypeError):
                config[key] = value
        
        async with self.global_conn.cursor() as cursor: # type: ignore
            await cursor.execute("SELECT key, value FROM global_settings")
            rows = await cursor.fetchall()
        for row in rows:
            config[row['key']] = row['value']
            
        return config

    async def update_config(self, config_data: Dict[str, Any]):
        # --- Добавляем 'user_agreement_accepted' в список глобальных ключей ---
        global_keys = ['last_network', 'system_tag', 'user_agreement_accepted']
        network_updates = {k: v for k, v in config_data.items() if k not in global_keys}
        global_updates = {k: v for k, v in config_data.items() if k in global_keys}
        
        if network_updates:
            async with self.conn.cursor() as cursor: # type: ignore
                for key, value in network_updates.items():
                    str_val = str(value)
                    if key in SENSITIVE_KEYS and self.security.is_active():
                        str_val = self.security.encrypt(str_val)
                    await cursor.execute("INSERT OR REPLACE INTO config (key, value) VALUES (?, ?)", (key, str_val))
            await self.conn.commit() # type: ignore

        if global_updates:
            async with self.global_conn.cursor() as cursor: # type: ignore
                for key, value in global_updates.items():
                    await cursor.execute("INSERT OR REPLACE INTO global_settings (key, value) VALUES (?, ?)", (key, str(value)))
            await self.global_conn.commit() # type: ignore
            
    # --- Методы Tokens ---
    async def add_or_update_recent_token(self, token_address: str, name: Optional[str] = None, symbol: Optional[str] = None):
        token_address = token_address.lower()
        async with self.conn.cursor() as cursor: # type: ignore
            await cursor.execute("SELECT name, symbol FROM recent_tokens WHERE token_address = ?", (token_address,))
            row = await cursor.fetchone()
            if row:
                if name is None: name = row['name']
                if symbol is None: symbol = row['symbol']
            await cursor.execute("""INSERT OR REPLACE INTO recent_tokens (token_address, name, symbol, last_traded_at) 
                   VALUES (?, ?, ?, CURRENT_TIMESTAMP)""", (token_address, name, symbol))
            await cursor.execute("""DELETE FROM recent_tokens WHERE token_address NOT IN (
                    SELECT token_address FROM recent_tokens ORDER BY last_traded_at DESC LIMIT 20)""")
        await self.conn.commit() # type: ignore
    
    async def get_recent_tokens(self, limit: int = 20) -> List[Dict[str, Any]]:
        async with self.conn.cursor() as cursor: # type: ignore
            await cursor.execute("SELECT token_address, name, symbol, last_traded_at FROM recent_tokens ORDER BY last_traded_at DESC LIMIT ?", (limit,))
            rows = await cursor.fetchall()
        return [dict(row) for row in rows]

    async def get_token_metadata(self, token_address: str) -> Optional[Dict[str, Any]]:
        async with self.conn.cursor() as cursor: # type: ignore
            await cursor.execute("SELECT name, symbol FROM recent_tokens WHERE token_address = ?", (token_address.lower(),))
            row = await cursor.fetchone()
        return dict(row) if row else None

    # --- Методы Events ---
    async def save_pending_event(self, payload: Dict[str, Any]):
        import json
        try:
            json_str = json.dumps(payload)
            async with self.conn.cursor() as cursor: # type: ignore
                await cursor.execute("INSERT INTO pending_trade_events (payload) VALUES (?)", (json_str,))
            await self.conn.commit() # type: ignore
        except Exception as e:
            print(f"DB Error save_pending_event: {e}")

    async def get_pending_events(self, limit: int = 50) -> List[Dict[str, Any]]:
        import json
        results = []
        try:
            async with self.conn.cursor() as cursor: # type: ignore
                await cursor.execute("SELECT id, payload FROM pending_trade_events ORDER BY created_at ASC LIMIT ?", (limit,))
                rows = await cursor.fetchall()
                for row in rows:
                    try:
                        data = json.loads(row['payload'])
                        results.append({'id': row['id'], 'data': data})
                    except: pass
        except Exception: pass
        return results

    async def delete_pending_events(self, ids: List[int]):
        if not ids: return
        try:
            placeholders = ','.join('?' for _ in ids)
            async with self.conn.cursor() as cursor: # type: ignore
                await cursor.execute(f"DELETE FROM pending_trade_events WHERE id IN ({placeholders})", tuple(ids))
            await self.conn.commit() # type: ignore
        except Exception as e:
            print(f"DB Error delete_pending_events: {e}")

    # --- МЕТОДЫ ДЛЯ БАЛАНСОВ (PERSISTENCE) ---
    async def save_cached_balance(self, wallet_address: str, token_address: str, balance_wei: int, decimals: int):
        async with self.conn.cursor() as cursor: # type: ignore
            await cursor.execute("""
                INSERT OR REPLACE INTO cached_balances (wallet_address, token_address, balance_wei, decimals, updated_at)
                VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
            """, (wallet_address.lower(), token_address.lower(), str(balance_wei), decimals))
        await self.conn.commit() # type: ignore

    async def get_all_cached_balances(self) -> List[Dict[str, Any]]:
        async with self.conn.cursor() as cursor: # type: ignore
            await cursor.execute("SELECT wallet_address, token_address, balance_wei, decimals FROM cached_balances")
            rows = await cursor.fetchall()
        return [dict(row) for row in rows]

    async def delete_cached_balance(self, wallet_address: str, token_address: str):
        async with self.conn.cursor() as cursor: # type: ignore
            await cursor.execute("""
                DELETE FROM cached_balances 
                WHERE wallet_address = ? AND token_address = ?
            """, (wallet_address.lower(), token_address.lower()))
        await self.conn.commit() # type: ignore

    # --- МЕТОДЫ ДЛЯ КЭША ПУЛОВ ---
    async def save_cached_pool(self, token_address: str, quote_address: str, pool_data: dict):
        import json
        pool_data_json = json.dumps(pool_data)
        async with self.conn.cursor() as cursor: # type: ignore
            await cursor.execute("""
                INSERT OR REPLACE INTO cached_pools (token_address, quote_address, pool_data_json, updated_at)
                VALUES (?, ?, ?, CURRENT_TIMESTAMP)
            """, (token_address.lower(), quote_address.lower(), pool_data_json))
        await self.conn.commit() # type: ignore

    async def get_all_cached_pools(self) -> List[Dict[str, Any]]:
        import json
        results = []
        async with self.conn.cursor() as cursor: # type: ignore
            await cursor.execute("SELECT token_address, quote_address, pool_data_json FROM cached_pools")
            rows = await cursor.fetchall()
            for row in rows:
                try:
                    results.append({
                        "token_address": row["token_address"],
                        "quote_address": row["quote_address"],
                        "pool_data": json.loads(row["pool_data_json"])
                    })
                except: continue
        return results

    async def delete_cached_pool(self, token_address: str, quote_address: str):
        async with self.conn.cursor() as cursor: # type: ignore
            await cursor.execute("""
                DELETE FROM cached_pools 
                WHERE token_address = ? AND quote_address = ?
            """, (token_address.lower(), quote_address.lower()))
        await self.conn.commit() # type: ignore

    # --- НОВЫЕ МЕТОДЫ: PnL / Positions ---
    async def update_position(self, wallet: str, token: str, cost_added_wei: int, amount_added_wei: int = 0):
        """Обновляет позицию (DCA) - добавляет затраты к существующим."""
        w = wallet.lower()
        t = token.lower()
        async with self.conn.cursor() as cursor: # type: ignore
            # 1. Получаем текущую позицию
            await cursor.execute("SELECT total_cost_wei, total_amount_wei FROM active_positions WHERE wallet_address=? AND token_address=?", (w, t))
            row = await cursor.fetchone()
            
            current_cost = int(row['total_cost_wei']) if row else 0
            current_amount = int(row['total_amount_wei']) if row and row['total_amount_wei'] else 0
            
            new_cost = current_cost + cost_added_wei
            new_amount = current_amount + amount_added_wei
            
            await cursor.execute("""
                INSERT INTO active_positions (wallet_address, token_address, total_cost_wei, total_amount_wei)
                VALUES (?, ?, ?, ?) 
                ON CONFLICT(wallet_address, token_address) 
                DO UPDATE SET total_cost_wei = ?, total_amount_wei = ?, updated_at = CURRENT_TIMESTAMP
            """, (w, t, str(new_cost), str(new_amount), str(new_cost), str(new_amount)))
        await self.conn.commit() # type: ignore

    async def get_position(self, wallet: str, token: str) -> Dict[str, int]:
        """Возвращает total_cost и total_amount для кошелька."""
        async with self.conn.cursor() as cursor: # type: ignore
            await cursor.execute("SELECT total_cost_wei, total_amount_wei FROM active_positions WHERE wallet_address=? AND token_address=?", (wallet.lower(), token.lower()))
            row = await cursor.fetchone()
            if row:
                return {
                    'total_cost': int(row['total_cost_wei']),
                    'total_amount': int(row['total_amount_wei'] or 0)
                }
            return {'total_cost': 0, 'total_amount': 0}

    async def close_position(self, wallet: str, token: str):
        """Закрывает позицию (удаляет запись) при полной продаже."""
        async with self.conn.cursor() as cursor: # type: ignore
            await cursor.execute("DELETE FROM active_positions WHERE wallet_address=? AND token_address=?", (wallet.lower(), token.lower()))
        await self.conn.commit() # type: ignore