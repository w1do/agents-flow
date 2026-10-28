"""A failed response closes in Uvicorn without exposing its original exception."""
import logging
import traceback
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from uvicorn.protocols.http.h11_impl import RequestResponseCycle

from app.middleware.security_headers import SecurityHeadersMiddleware, logger


@pytest.mark.parametrize("completed", [False, True])
async def test_started_response_error_is_safe_for_uvicorn(caplog, monkeypatch, completed):
    uvicorn_logger = logging.getLogger("uvicorn.error")
    for log in (logger, uvicorn_logger):
        monkeypatch.setattr(log, "disabled", False)
        caplog.set_level(logging.ERROR, logger=log.name)
    synthetic_token = "ghp_" + "B" * 36
    sent, captured = [], []
    cycle = SimpleNamespace(scope={"type": "http"}, transport=Mock(), logger=uvicorn_logger,
                            response_started=False, response_complete=False, disconnected=False)

    async def send(message):
        sent.append(message)
        if message["type"] == "http.response.start":
            cycle.response_started = True
        if message["type"] == "http.response.body":
            cycle.response_complete = not message.get("more_body", False)

    cycle.send = send
    cycle.receive = Mock()

    async def app(scope, receive, send):
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"partial", "more_body": not completed})
        raise ValueError(synthetic_token + " key.PEM?marker=42")

    async def capture(scope, receive, send):
        try:
            await SecurityHeadersMiddleware(app)(scope, receive, send)
        except Exception as error:
            captured.append(error)
            raise

    await RequestResponseCycle.run_asgi(cycle, capture)
    cycle.transport.close.assert_called_once_with()
    assert len(sent) == 2 and sent[0]["status"] == 200
    assert len(captured) == 1 and type(captured[0]) is RuntimeError
    assert captured[0].__context__ is None and captured[0].__cause__ is None
    rendered = "".join(traceback.format_exception(captured[0]))
    assert "Response stream interrupted" in caplog.text
    assert "[REDACTED]" in caplog.text
    for output in (caplog.text, rendered, str(captured[0])):
        assert synthetic_token not in output
        assert "key.PEM" not in output and "marker=42" not in output
