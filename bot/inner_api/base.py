from abc import ABC, abstractmethod
from typing import Dict, Any, Optional
from .schemas import APICommand, APIResponse

class BaseEndpoint(ABC):
    def __init__(self, cache):
        self.cache = cache

    @abstractmethod
    async def execute(self, command: APICommand) -> APIResponse:
        pass


    def create_response(self, command: APICommand, status: str = "success",
                       data: Optional[Dict[str, Any]] = None,
                       error: Optional[str] = None) -> APIResponse:
        return APIResponse(
            command_id=command.command_id,
            status=status,
            data=data or {},
            error=error
        )