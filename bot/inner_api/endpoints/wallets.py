from ..base import BaseEndpoint
from ..schemas import APICommand, APIResponse, WalletCreate, WalletUpdate
from web3 import Web3

class WalletsEndpoint(BaseEndpoint):
    """Эндпоинт для работы с кошельками"""
    
    async def execute(self, command: APICommand) -> APIResponse:
        action = command.data.get('action')
        if action == 'list': return await self._list_wallets(command)
        elif action == 'add': return await self._add_wallet(command)
        elif action == 'update': return await self._update_wallet(command)
        elif action == 'delete': return await self._delete_wallet(command)
        else: return self.create_response(command, status="error", error=f"Unknown wallet action: {action}")
    

    async def _add_wallet(self, command: APICommand) -> APIResponse:
        """Добавить кошелек по приватному ключу."""
        try:
            wallet_data = WalletCreate(**command.data['wallet'])
            private_key_str = wallet_data.private_key.strip()

            config = self.cache.get_config()
            rpc_url = config.get('rpc_url')
            if not rpc_url:
                return self.create_response(command, status="error", error="RPC URL не настроен. Проверьте настройки.")
            
            w3 = Web3(Web3.HTTPProvider(rpc_url))
            
            account = w3.eth.account.from_key(private_key_str)
            derived_address = account.address

            if self.cache.get_wallet_by_address(derived_address):
                return self.create_response(command, status="error", error=f"Кошелек с адресом {derived_address} уже существует.")

            result = await self.cache.add_wallet(
                address=derived_address,
                private_key=private_key_str,
                name=wallet_data.name,
                enabled=wallet_data.enabled
            )
            safe_result = result.copy(); safe_result.pop('private_key', None)
            return self.create_response(command, data=safe_result)
        except Exception as e:
            return self.create_response(command, status="error", error=f"Ошибка обработки ключа: {e}")
    

    async def _list_wallets(self, command: APICommand) -> APIResponse:
        wallets_data = self.cache.get_all_wallets(enabled_only=command.data.get('enabled_only', False))
        return self.create_response(command, data={'wallets': wallets_data})


    async def _update_wallet(self, command: APICommand) -> APIResponse:
        try:
            address = command.data['address']
            update_data = WalletUpdate(**command.data['update']).model_dump(exclude_unset=True)
            if not update_data: return self.create_response(command, status="error", error="Нет полей для обновления")
            result = await self.cache.update_wallet(address, update_data)
            safe_result = result.copy(); safe_result.pop('private_key', None)
            return self.create_response(command, data=safe_result)
        except Exception as e: 
            return self.create_response(command, status="error", error=str(e))
    
    
    async def _delete_wallet(self, command: APICommand) -> APIResponse:
        try:
            address = command.data['address']
            result = await self.cache.delete_wallet(address)
            return self.create_response(command, data=result)
        except Exception as e: return self.create_response(command, status="error", error=str(e))