from ..base import BaseEndpoint
from ..schemas import APICommand, APIResponse, ConfigUpdate

class ConfigEndpoint(BaseEndpoint):
    """Эндпоинт для работы с конфигурацией"""
    

    async def execute(self, command: APICommand) -> APIResponse:
        action = command.data.get('action')
        
        if action == 'get':
            return await self._get_config(command)
        elif action == 'update':
            return await self._update_config(command)
        else:
            return self.create_response(
                command, 
                status="error", 
                error=f"Unknown config action: {action}"
            )
    

    async def _get_config(self, command: APICommand) -> APIResponse:
        """Получить текущую конфигурацию"""
        config = self.cache.get_config()
        return self.create_response(command, data={'config': config})
    
    
    async def _update_config(self, command: APICommand) -> APIResponse:
        """Обновить конфигурацию"""
        try:
            update_data = ConfigUpdate(**command.data['config'])
            config_updates = update_data.model_dump(exclude_unset=True)
            
            if not config_updates:
                 return self.create_response(command, status="error", error="No fields to update")

            result = await self.cache.update_config(config_updates)
            return self.create_response(command, data={'config': result})
        except Exception as e:
            return self.create_response(command, status="error", error=str(e))