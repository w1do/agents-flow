"""Общие зависимости и безопасные HTTP-ошибки канала worker."""

from collections.abc import Callable, Coroutine
from typing import Annotated, Any

from fastapi import Header, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute

from harness_server.domain.errors import InvalidTransition, WorkerConflict, WorkerUnauthorized

TaskTokenDep = Annotated[str, Header(alias="X-Task-Token", max_length=512)]


class WorkerRoute(APIRoute):
    """Секреты из невалидного тела и исключений не возвращаются в ответ."""

    def get_route_handler(self) -> Callable[[Request], Coroutine[Any, Any, Response]]:
        handler = super().get_route_handler()

        async def safe_handler(request: Request) -> Response:
            try:
                return await handler(request)
            except WorkerUnauthorized:
                return JSONResponse({"detail": "unauthorized"}, status_code=401)
            except (InvalidTransition, WorkerConflict):
                return JSONResponse({"detail": "conflict"}, status_code=409)
            except RequestValidationError:
                return JSONResponse({"detail": "invalid_request"}, status_code=422)

        return safe_handler
