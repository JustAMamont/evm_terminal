from typing import Dict, Any, Callable, List, Union
from .schemas import APICommand, APIResponse
import inspect

class Route:
    def __init__(self, handler: Callable, validation_schema: Any = None):
        self.handler = handler
        self.validation_schema = validation_schema
        self.requires_cache = 'cache' in inspect.signature(handler).parameters


class APIRouter:
    def __init__(self):
        self.routes: Dict[str, Route] = {}
        self.middleware: List[Callable] = []


    def register_route(self, command_type: str, handler: Callable,
                      validation_schema: Any = None):
        self.routes[command_type] = Route(handler, validation_schema)


    def add_middleware(self, middleware_func: Callable):
        self.middleware.append(middleware_func)


    async def process_command(self, command: APICommand, cache) -> APIResponse:
        if command.type not in self.routes:
            return APIResponse(
                command_id=command.command_id,
                status="error",
                error=f"Route not found for: {command.type}"
            )
        route = self.routes[command.type]
        try:
            current_command: Union[APICommand, APIResponse] = command
            for middleware in self.middleware:
                result = await middleware(current_command, cache)
                if isinstance(result, APIResponse):
                    return result
                current_command = result
            if not isinstance(current_command, APICommand):
                return APIResponse(command_id=command.command_id, status="error", error="Middleware chain corrupted")

            command = current_command
            if route.validation_schema:
                try:
                    validated_data = route.validation_schema(**command.data)
                    command.data = validated_data.model_dump()
                except Exception as e:
                    return APIResponse(command_id=command.command_id, status="error", error=f"Validation error: {str(e)}")

            if route.requires_cache:
                result = await route.handler(command, cache)
            else:
                result = await route.handler(command)

            if isinstance(result, APIResponse):
                return result
            elif isinstance(result, dict):
                return APIResponse(command_id=command.command_id, status="success", data=result)
            else:
                return APIResponse(command_id=command.command_id, status="success", data={"result": result})

        except Exception as e:
            return APIResponse(command_id=command.command_id, status="error", error=f"Handler error: {str(e)}")