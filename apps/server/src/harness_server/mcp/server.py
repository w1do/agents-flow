"""Streamable HTTP MCP; авторизация каждого запроса и тонкий вызов сервисов."""

import json
from collections.abc import Callable
from typing import Any

import mcp.types as types
from harness_shared.planning import AgentListIn, AgentReportIn, AgentTaskIn, SpecSyncIn
from mcp.server import Server
from mcp.server.context import ServerRequestContext
from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
from pydantic import BaseModel, ValidationError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.types import Receive, Scope, Send

from harness_server.domain.errors import DomainError, WorkerUnauthorized
from harness_server.security.redaction import redact
from harness_server.services.agent_access import agent_task
from harness_server.services.agent_tools import invoke

_MODELS: dict[str, type[BaseModel]] = {
    "sync_spec": SpecSyncIn,
    "create_task": AgentTaskIn,
    "report_task": AgentReportIn,
    "list_tasks": AgentListIn,
}
Factory = async_sessionmaker[AsyncSession]


def bearer(request: Request) -> str:
    """Значение используется только для проверки, никогда не включается в ошибки."""
    scheme, _, token = request.headers.get("authorization", "").partition(" ")
    if scheme.lower() != "bearer" or not token or len(token) > 512:
        raise WorkerUnauthorized()
    return token


class PlannerMCP:
    """Stateless исключает перенос контекста одного токена в сессию другого."""

    def __init__(
        self,
        factory: Callable[[], Factory],
        secret_key: str,
        secrets: tuple[str, ...],
    ) -> None:
        self.factory = factory
        self.secret_key = secret_key
        self.secrets = secrets
        self.server: Server[dict[str, Any]] = Server(
            "agents-flow",
            on_list_tools=self.list_tools,
            on_call_tool=self.call_tool,
        )
        self.manager = StreamableHTTPSessionManager(
            self.server,
            stateless=True,
            json_response=True,
        )

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            return
        try:
            token = bearer(Request(scope))
            async with self.factory()() as session:
                await agent_task(session, token, self.secret_key)
        except WorkerUnauthorized:
            response = JSONResponse(
                {"detail": "unauthorized"},
                status_code=401,
                headers={"WWW-Authenticate": "Bearer"},
            )
            await response(scope, receive, send)
            return
        await self.manager.handle_request(scope, receive, send)

    async def list_tools(
        self,
        ctx: ServerRequestContext[dict[str, Any], Any],
        params: types.PaginatedRequestParams | None,
    ) -> types.ListToolsResult:
        return types.ListToolsResult(
            tools=[
                types.Tool(name=name, input_schema=model.model_json_schema())
                for name, model in _MODELS.items()
            ]
        )

    async def call_tool(
        self,
        ctx: ServerRequestContext[dict[str, Any], Any],
        params: types.CallToolRequestParams,
    ) -> types.CallToolResult:
        try:
            model = _MODELS.get(params.name)
            if model is None:
                return self.error("invalid_input")
            body = model.model_validate(params.arguments or {})
            if not isinstance(ctx.request, Request):
                raise WorkerUnauthorized()
            token = bearer(ctx.request)
            async with self.factory()() as session:
                value = await invoke(
                    session,
                    token,
                    self.secret_key,
                    params.name,
                    body,
                    self.secrets,
                )
            data: object
            if isinstance(value, list):
                data = [item.model_dump(mode="json") for item in value]
            elif isinstance(value, BaseModel):
                data = value.model_dump(mode="json")
            else:
                return self.error("invalid_result")
            return types.CallToolResult(
                content=[
                    types.TextContent(
                        type="text",
                        text=redact(
                            json.dumps(data, ensure_ascii=False),
                            (*self.secrets, token),
                        ),
                    ),
                ]
            )
        except ValidationError:
            return self.error("invalid_input")
        except DomainError as exc:
            return self.error("unauthorized" if isinstance(exc, WorkerUnauthorized) else exc.code)

    @staticmethod
    def error(code: str) -> types.CallToolResult:
        return types.CallToolResult(
            is_error=True,
            content=[types.TextContent(type="text", text=code)],
        )
