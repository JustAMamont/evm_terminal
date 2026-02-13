import asyncio
import psutil
import os
from ..base import BaseEndpoint
from ..schemas import APICommand, APIResponse
from web3 import AsyncWeb3  


class SystemEndpoint(BaseEndpoint):
    """Эндпоинт для системной информации"""
    
    async def execute(self, command: APICommand) -> APIResponse:
        action = command.data.get('action')
        
        if action == 'status':
            return await self._get_status(command)
        elif action == 'metrics':
            return await self._get_metrics(command)
        elif action == 'health':
            return await self._health_check(command)
        else:
            return self.create_response(
                command, 
                status="error", 
                error=f"Unknown system action: {action}"
            )
    

    async def _get_status(self, command: APICommand) -> APIResponse:
        """Получить статус системы"""
        status_data = {
            'bot_running': True, # Если API отвечает, значит бот запущен
            'wallets_loaded': len(self.cache.get_all_wallets()),
            'enabled_wallets': len(self.cache.get_all_wallets(enabled_only=True)),
            'config': self.cache.get_config()
        }
        
        return self.create_response(command, data={'status': status_data})
    

    async def _get_metrics(self, command: APICommand) -> APIResponse:
        """Получить системные метрики"""
        process = psutil.Process(os.getpid())
        
        metrics = {
            'cpu_percent': process.cpu_percent(),
            'memory_mb': round(process.memory_info().rss / 1024 / 1024, 2),
            'threads_count': process.num_threads(),
            'active_tasks': len([t for t in asyncio.all_tasks() if not t.done()])
        }
        
        return self.create_response(command, data={'metrics': metrics})
    

    async def _health_check(self, command: APICommand) -> APIResponse:
        """Проверка здоровья системы"""
        db_ok = False
        try:
            if self.cache.db.conn:
                await self.cache.db.conn.execute("SELECT 1")
                db_ok = True
        except Exception:
            db_ok = False
            
        rpc_ok = False
        try:
            config = self.cache.get_config()
            # Пытаемся взять URL из настроек в БД, если нет - берем дефолтный для текущей сети
            rpc_url = config.get('rpc_url')
            if not rpc_url:
                # Этого кейса быть не должно, но для надежности
                return self.create_response(command, status="error", error="RPC URL не найден в конфигурации")

            w3 = AsyncWeb3(AsyncWeb3.AsyncHTTPProvider(rpc_url))
            if await w3.is_connected():
                rpc_ok = True
        except Exception:
            rpc_ok = False

        health_data = {
            'database': db_ok,
            'rpc_connection': rpc_ok,
            'wallets_exist': len(self.cache.get_all_wallets()) > 0
        }
        
        all_healthy = all(health_data.values())
        
        return self.create_response(command, data={
            'healthy': all_healthy,
            'components': health_data
        })