from ..base import BaseEndpoint
from ..schemas import APICommand, APIResponse, TradeRequest

class TradingEndpoint(BaseEndpoint):
    def __init__(self, cache, bot_service):
        super().__init__(cache)
        self.bot_service = bot_service
    

    async def execute(self, command: APICommand) -> APIResponse:
        action = command.data.get('action')
        
        if action == 'execute_trade':
            return await self._execute_trade(command)
        elif action == 'pre_approve':
            return await self._pre_approve(command)
        elif action == 'prefetch_decimals':
            return await self._prefetch_decimals(command)
        elif action == 'list_recent_tokens':
            return await self._list_recent_tokens(command)
        else:
            return self.create_response(command, status="error", error=f"Unknown trading action: {action}")
    

    async def _execute_trade(self, command: APICommand) -> APIResponse:
        try:
            trade_request = TradeRequest(**command.data['trade'])
            result = await self.bot_service.schedule_trades(trade_request)
            return self.create_response(command, data=result)
        except Exception as e:
            return self.create_response(command, status="error", error=str(e))


    async def _prefetch_decimals(self, command: APICommand) -> APIResponse:
        try:
            token_address = command.data['token_address']
            await self.bot_service.prefetch_token_decimals(token_address)
            return self.create_response(command, data={'status': 'Prefetch task for decimals scheduled'})
        except Exception as e:
            return self.create_response(command, status="error", error=str(e))


    async def _pre_approve(self, command: APICommand) -> APIResponse:
        """Запускает фоновый pre-approve для токена."""
        try:
            token_address = command.data['token_address']
            wallets = command.data['wallets']
            await self.bot_service.schedule_pre_approve(token_address, wallets)
            return self.create_response(command, data={'status': 'Pre-approve tasks scheduled'})
        except Exception as e:
            return self.create_response(command, status="error", error=str(e))


    async def _list_recent_tokens(self, command: APICommand) -> APIResponse:
        try:
            limit = command.data.get('limit', 10)
            tokens = await self.cache.db.get_recent_tokens(limit)
            return self.create_response(command, data={'tokens': tokens})
        except Exception as e:
            return self.create_response(command, status="error", error=str(e))