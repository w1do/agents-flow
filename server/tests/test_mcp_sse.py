import asyncio

import pytest


async def run_stream(monkeypatch, chunks, status=200,
                     content_type="text/event-stream; charset=utf-8"):
    from app.mcp import transport

    monkeypatch.setattr(transport, "agent_identity", lambda _token: "agent")
    event_sent = asyncio.Event()
    allow_eof = asyncio.Event()
    messages = []

    async def sdk_app(scope, receive, send):
        await send({"type": "http.response.start", "status": status, "headers": [
            (b"content-type", content_type.encode()),
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


@pytest.mark.parametrize("separator", [b"\n\n", b"\r\n\r\n"])
async def test_get_mcp_delivers_heartbeat_before_eof(monkeypatch, separator):
    task, event_sent, allow_eof, messages = await run_stream(
        monkeypatch, [b": heartbeat" + separator]
    )
    try:
        await asyncio.wait_for(event_sent.wait(), timeout=1)
        assert any(item.get("body") == b": heartbeat" + separator for item in messages)
    finally:
        allow_eof.set()
        await task


@pytest.mark.parametrize("status", [201, 202, 301, 302, 307, 399])
@pytest.mark.parametrize("content_type", ["application/json", "text/event-stream"])
async def test_nonstandard_status_sanitizes_jsonrpc_errors(
    monkeypatch, status, content_type
):
    import json

    secret = "upstream-secret"
    original_message = f"private upstream message: {secret}"
    original_data = f"private upstream data: {secret}"
    rpc_error = {
        "jsonrpc": "2.0", "id": 7,
        "error": {"code": -32001, "message": original_message, "data": original_data},
    }
    payload = json.dumps(rpc_error).encode()
    if content_type == "text/event-stream":
        payload = b"data: " + payload + b"\r\n\r\n"
    chunks = [payload[:17], payload[17:]]
    task, _event_sent, allow_eof, messages = await run_stream(
        monkeypatch, chunks, status=status, content_type=content_type
    )
    try:
        allow_eof.set()
        await task
        body = b"".join(message.get("body", b"") for message in messages)
        assert secret not in body.decode()
        assert original_message.encode() not in body
        assert original_data.encode() not in body
        if content_type == "text/event-stream":
            data = next(line[6:] for line in body.splitlines() if line.startswith(b"data: "))
            result = json.loads(data)
        else:
            result = json.loads(body)
        assert result == {
            "jsonrpc": "2.0", "id": 7,
            "error": {"code": -32001, "message": "MCP request failed",
                      "data": "MCP request failed"},
        }
    finally:
        allow_eof.set()


async def test_get_mcp_delivers_crlf_split_between_chunks_before_eof(monkeypatch):
    task, event_sent, allow_eof, messages = await run_stream(
        monkeypatch, [b": heartbeat\r\n", b"\r\n"]
    )
    try:
        await asyncio.wait_for(event_sent.wait(), timeout=1)
        assert any(item.get("body") == b": heartbeat\r\n\r\n" for item in messages)
    finally:
        allow_eof.set()
        await task


@pytest.mark.parametrize("status", [201, 202, 301, 302, 307, 399])
async def test_multiline_sse_sanitizes_combined_jsonrpc_error(monkeypatch, status):
    import json

    secret = "upstream-secret"
    original_message = f"private upstream message: {secret}"
    original_data = f"private upstream data: {secret}"
    event = (
        b'data: {"jsonrpc":"2.0","id":7,\r\n'
        + f'data: "error":{{"code":-32001,"message":"{original_message}",'.encode()
        + f'"data":"{original_data}"}}}}\r\n\r\n'.encode()
    )
    task, _event_sent, allow_eof, messages = await run_stream(
        monkeypatch, [event[:23], event[23:]], status=status
    )
    try:
        allow_eof.set()
        await task
        body = b"".join(message.get("body", b"") for message in messages)
        assert secret.encode() not in body
        assert original_message.encode() not in body
        assert original_data.encode() not in body
        data = b"\n".join(
            line[5:].removeprefix(b" ")
            for line in body.splitlines() if line.startswith(b"data:")
        )
        assert json.loads(data) == {
            "jsonrpc": "2.0", "id": 7,
            "error": {"code": -32001, "message": "MCP request failed",
                      "data": "MCP request failed"},
        }
    finally:
        allow_eof.set()


async def test_successful_sse_preserves_data_field_bytes(monkeypatch):
    event = b'data:{"jsonrpc":"2.0","id":7,"result":{}}\n\n'
    task, _event_sent, allow_eof, messages = await run_stream(monkeypatch, [event])
    try:
        allow_eof.set()
        await task
        body = b"".join(message.get("body", b"") for message in messages)
        assert body == event
    finally:
        allow_eof.set()
