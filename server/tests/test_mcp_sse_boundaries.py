import asyncio
import json

import pytest


async def run_stream(monkeypatch, chunks, status):
    from app.mcp import transport

    monkeypatch.setattr(transport, "agent_identity", lambda _token: "agent")
    event_sent, allow_eof = asyncio.Event(), asyncio.Event()
    messages = []

    async def sdk_app(scope, receive, send):
        await send({"type": "http.response.start", "status": status, "headers": [
            (b"content-type", b"text/event-stream"),
        ]})
        for chunk in chunks:
            await send({"type": "http.response.body", "body": chunk, "more_body": True})
        event_sent.set()
        await allow_eof.wait()
        await send({"type": "http.response.body", "body": b"", "more_body": False})

    async def capture(message):
        messages.append(message)

    scope = {
        "type": "http", "method": "GET", "path": "/mcp", "root_path": "",
        "headers": [(b"authorization", b"Bearer valid")], "state": {},
    }
    task = asyncio.create_task(transport.AgentTokenMiddleware(sdk_app)(scope, None, capture))
    return task, event_sent, allow_eof, messages


def event_payloads(body):
    return [json.loads(line[6:]) for line in body.splitlines()
            if line.startswith(b"data: ")]


@pytest.mark.parametrize("ending", [b"\n\n", b"\r\n\r\n", b"\n\r\n",
                                    b"\r\r", b"\r\n\n"])
@pytest.mark.parametrize("status", [200, 201])
async def test_sse_line_endings_sanitize_error_and_keep_structure(
    monkeypatch, ending, status
):
    secret = b"SECRET"
    error = (b'data: {"jsonrpc":"2.0","id":7,"error":{"code":-32001,'
             b'"message":"SECRET","data":"SECRET"}}' + ending)
    task, _sent, allow_eof, messages = await run_stream(monkeypatch, [error], status)
    try:
        allow_eof.set()
        await task
        body = b"".join(message.get("body", b"") for message in messages)
        assert secret not in body
        assert event_payloads(body) == [{
            "jsonrpc": "2.0", "id": 7,
            "error": {"code": -32001, "message": "MCP request failed",
                      "data": "MCP request failed"},
        }]
    finally:
        allow_eof.set()


async def test_sse_lf_crlf_boundary_keeps_following_result_as_separate_event(monkeypatch):
    first = (b'data: {"jsonrpc":"2.0","id":7,"error":{"code":-32001,'
             b'"message":"SECRET","data":"SECRET"}}\n\r\n')
    second = b'data: {"jsonrpc":"2.0","id":8,"result":{}}\n\n'
    task, _sent, allow_eof, messages = await run_stream(
        monkeypatch, [first + second], 200
    )
    try:
        allow_eof.set()
        await task
        body = b"".join(message.get("body", b"") for message in messages)
        assert b"SECRET" not in body
        assert event_payloads(body) == [
            {"jsonrpc": "2.0", "id": 7,
             "error": {"code": -32001, "message": "MCP request failed",
                       "data": "MCP request failed"}},
            {"jsonrpc": "2.0", "id": 8, "result": {}},
        ]
    finally:
        allow_eof.set()


async def test_sse_boundary_split_between_chunks_is_retained(monkeypatch):
    first = b'data: {"jsonrpc":"2.0","id":7,"error":{"message":"SECRET"}}\n\r'
    second = b'\ndata: {"jsonrpc":"2.0","id":8,"result":{}}\n\n'
    task, _sent, allow_eof, messages = await run_stream(
        monkeypatch, [first, second], 200
    )
    try:
        allow_eof.set()
        await task
        body = b"".join(message.get("body", b"") for message in messages)
        assert b"SECRET" not in body
        assert [item["id"] for item in event_payloads(body)] == [7, 8]
    finally:
        allow_eof.set()
