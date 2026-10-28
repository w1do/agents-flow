"""Uvicorn never sees secret-bearing groups or secondary exception contexts."""
import asyncio
import logging
import traceback
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from uvicorn.protocols.http.h11_impl import RequestResponseCycle

from app.middleware.security_headers import SecurityHeadersMiddleware, logger

SECRET = "ghp_" + "C" * 36
DETAIL = SECRET + " key.PEM?marker=42"


class BrokenTextError(Exception):
    def __str__(self):
        raise ValueError(DETAIL)


@pytest.mark.parametrize("phase", ["before_start", "after_start", "partial", "complete"])
@pytest.mark.parametrize("kind", ["group", "broken_str"])
async def test_groups_and_broken_text_do_not_escape_to_uvicorn(caplog, monkeypatch, phase, kind):
    async def app(scope, receive, send):
        if phase != "before_start":
            await send({"type": "http.response.start", "status": 200, "headers": []})
        if phase in {"partial", "complete"}:
            await send({"type": "http.response.body", "body": b"body", "more_body": phase == "partial"})
        if kind == "broken_str":
            raise BrokenTextError(DETAIL)
        raise BaseExceptionGroup("outer " + DETAIL, [asyncio.CancelledError(),
                                 ExceptionGroup("nested", [ValueError(DETAIL)])])

    sent, captured, cycle = await run_with_uvicorn(app, caplog, monkeypatch)
    if phase == "before_start":
        assert sent[0]["status"] == 500
        assert not captured
    else:
        assert sent[0]["status"] == 200
        assert len(captured) == 1
        cycle.transport.close.assert_called_once_with()
    if kind == "group":
        assert "[REDACTED]" in caplog.text
    assert_safe(caplog.text, captured)


@pytest.mark.parametrize("failure", ["cancel_start", "cancel_body", "error_body"])
async def test_failed_fallback_clears_original_context(caplog, monkeypatch, failure):
    async def app(*args):
        raise ValueError(DETAIL)

    sent, captured, cycle = await run_with_uvicorn(app, caplog, monkeypatch, failure)
    assert sent[0]["status"] == 500
    assert len(captured) == 1
    cycle.transport.close.assert_called_once_with()
    assert "[REDACTED]" in caplog.text
    assert_safe(caplog.text, captured)


async def run_with_uvicorn(app, caplog, monkeypatch, failure=None):
    uvicorn_logger = logging.getLogger("uvicorn.error")
    for log in (logger, uvicorn_logger):
        monkeypatch.setattr(log, "disabled", False)
        caplog.set_level(logging.ERROR, logger=log.name)
    sent, captured = [], []
    cycle = SimpleNamespace(scope={"type": "http"}, transport=Mock(), logger=uvicorn_logger,
                            response_started=False, response_complete=False, disconnected=False)

    async def send(message):
        sent.append(message)
        if failure == "cancel_start" and message["type"] == "http.response.start":
            cycle.response_started = True
            raise asyncio.CancelledError(DETAIL)
        if message["type"] == "http.response.start":
            cycle.response_started = True
        if message["type"] == "http.response.body":
            if failure == "cancel_body":
                raise asyncio.CancelledError(DETAIL)
            if failure == "error_body":
                raise ValueError(DETAIL)
            cycle.response_complete = not message.get("more_body", False)

    async def capture(scope, receive, send):
        try:
            await SecurityHeadersMiddleware(app)(scope, receive, send)
        except BaseException as error:
            captured.append(error)
            raise

    cycle.send, cycle.receive = send, Mock()
    cycle.send_500_response = lambda: RequestResponseCycle.send_500_response(cycle)
    await RequestResponseCycle.run_asgi(cycle, capture)
    return sent, captured, cycle


def assert_safe(logs, captured):
    for error in captured:
        assert type(error) is RuntimeError
        assert error.__context__ is None and error.__cause__ is None
    rendered = logs + "".join("".join(traceback.format_exception(error)) for error in captured)
    assert SECRET not in rendered
    assert "marker=42" not in rendered and "key.PEM" not in rendered
