from ..schemas import APICommand, APIResponse
from typing import Union
from web3 import Web3


async def validate_wallet_address(command: APICommand, cache) -> Union[APICommand, APIResponse]:
    """
    Middleware для валидации адресов кошельков.
    """
    return command


async def validate_token_address(command: APICommand, cache) -> Union[APICommand, APIResponse]:
    """
    Middleware для надежной валидации адресов токенов с использованием Web3.
    """
    if 'token_address' in command.data:
        token_address = command.data['token_address']
        if not Web3.is_address(token_address):
            return APIResponse(
                command_id=command.command_id,
                status="error",
                error=f"Неверный формат адреса токена: {token_address}"
            )
    
    # Дополнительная проверка для трейдинга, где адрес токена находится глубже
    if command.type == 'trading' and 'trade' in command.data and 'token_address' in command.data['trade']:
        token_address = command.data['trade']['token_address']
        if not Web3.is_address(token_address):
             return APIResponse(
                command_id=command.command_id,
                status="error",
                error=f"Неверный формат адреса токена в запросе на трейд: {token_address}"
            )

    return command


async def validate_trade_amount(command: APICommand, cache) -> Union[APICommand, APIResponse]:
    """Middleware для валидации суммы торговли"""
    if command.type == 'trading' and 'trade' in command.data:
        trade_data = command.data['trade']
        if 'amount' in trade_data:
            try:
                amount = float(trade_data['amount'])
                if amount <= 0:
                    return APIResponse(
                        command_id=command.command_id,
                        status="error",
                        error="Сумма для трейда должна быть положительным числом."
                    )
            except (ValueError, TypeError):
                 return APIResponse(
                    command_id=command.command_id,
                    status="error",
                    error="Неверный формат суммы для трейда."
                )
    return command