import asyncio

import pytest


async def run_stream(monkeypatch, chunks):
    from app.mcp import transport

    monkeypatch.setattr(transport, "agent_identity", lambda _token: "agent")
    event_sent = asyncio.Event()
    allow_eof = asyncio.Event()
    messages = []

    async def sdk_app(scope, receive, send):
        await send({"type": "http.response.start", "status": 200, "headers": [
            (b"content-type", b"text/event-stream; charset=utf-8"),
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
