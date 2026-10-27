"""Real MCP SDK client over an in-process Streamable HTTP connection."""
import asyncio
from contextlib import asynccontextmanager
from uuid import uuid4

import httpx2
import pytest
from mcp import Client
from mcp.client.streamable_http import streamable_http_client

CALLS = [
    ("agent_get_assigned_task", "active", {}),
    ("agent_heartbeat", "active", {}),
    ("agent_report_plan", "planning", {"plan_text": "Implement"}),
    ("agent_get_plan_decision", "backlog", {}),
    ("agent_report_progress", "active", {"event_type": "progress", "message": "Step"}),
    ("agent_save_checkpoint", "active", {"checkpoint": {"step": 1}}),
    ("agent_report_test_result", "testing", {"message": "Tests passed", "payload": {"passed": 5}}),
    ("agent_report_result", "testing", {"result_summary": "Done", "result_data": {"tests": "passed"}}),
    ("agent_get_result_decision", "ready", {}),
    ("agent_report_publication_result", "merged", {"success": True, "message": "Pushed"}),
    ("agent_report_failure", "active", {"message": "Failed"}),
]


@asynccontextmanager
async def background_context(context):
    """Keep AnyIO context entry/exit in one task across pytest fixture yields."""
    ready = asyncio.get_running_loop().create_future()
    stop = asyncio.Event()

    async def run():
        try:
            async with context as value:
                ready.set_result(value)
                await stop.wait()
        except BaseException as exception:
            if not ready.done():
                ready.set_exception(exception)
            else:
                raise

    task = asyncio.create_task(run())
    try:
        yield await ready
    finally:
        stop.set()
        await task


class MCPClient:
    def __init__(self, sdk, session):
        self.sdk, self.session = sdk, session

    async def raw(self, name, arguments):
        result = await self.sdk.call_tool(name, arguments)
        assert result.structured_content is not None
        # MCP uses its own transaction; discard the REST fixture's identity cache.
        self.session.expire_all()
        return result

    async def call(self, name, task, fields=None, *, event_id=None):
        arguments = {"task_id": str(task.id), "lease_id": str(task.lease_id),
                     "event_id": event_id or str(uuid4())} | (fields or {})
        result = await self.raw(name, arguments)
        return result.structured_content


@pytest.fixture
def mcp_factory(flow, app):
    @asynccontextmanager
    async def connect(headers=None, mode="legacy"):
        async with httpx2.AsyncClient(transport=httpx2.ASGITransport(app=app),
                                     headers=flow.headers if headers is None else headers) as http:
            transport = streamable_http_client("http://test/mcp", http_client=http)
            async with background_context(Client(transport, mode=mode, read_timeout_seconds=5)) as sdk:
                yield MCPClient(sdk, flow.session)
    return connect


@pytest.fixture
async def mcp(mcp_factory):
    async with mcp_factory() as client:
        yield client
