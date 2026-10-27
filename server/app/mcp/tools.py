"""MCP protocol adapters; task behavior lives in the shared service layer."""
import json

from mcp.server import Server
from mcp_types import CallToolResult, ListToolsResult, TextContent, Tool
from starlette.concurrency import run_in_threadpool

from app.schemas.mcp import TOOL_SCHEMAS
from app.services.mcp_calls import invoke


async def list_tools(_context, _params):
    return ListToolsResult(tools=[
        Tool(name=name, description=name.removeprefix("agent_").replace("_", " "),
             input_schema=schema.model_json_schema())
        for name, schema in TOOL_SCHEMAS.items()
    ])


async def call_tool(context, params):
    result = await run_in_threadpool(
        invoke, context.request.state.mcp_agent_id, params.name, params.arguments or {},
    )
    return CallToolResult(
        content=[TextContent(type="text", text=json.dumps(result, ensure_ascii=False))],
        structured_content=result, is_error="error" in result,
    )


def create_server():
    # Low-level callbacks let us validate with REST schemas without SDK errors
    # reflecting raw argument values or logging exceptions with their contents.
    return Server("Agents Flow", version="0.1.0",
                  on_list_tools=list_tools, on_call_tool=call_tool)
