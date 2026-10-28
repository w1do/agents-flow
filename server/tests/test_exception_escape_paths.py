"""Cancellation and logger failures never export the original exception chain."""
import asyncio
import logging
import traceback

import pytest

from app.middleware.security_headers import logger
from test_round6_middleware import DETAIL, SECRET, run_with_uvicorn


@pytest.mark.parametrize("phase", ["before_start", "after_start", "partial", "complete"])
@pytest.mark.parametrize("path", ["cancellation", "logging_handler"])
async def test_exception_escape_paths_are_safe_for_uvicorn(caplog, monkeypatch, phase, path):
    async def app(scope, receive, send):
        if phase != "before_start":
            await send({"type": "http.response.start", "status": 200, "headers": []})
        if phase in {"partial", "complete"}:
            await send({"type": "http.response.body", "body": b"body", "more_body": phase == "partial"})
        try:
            raise ValueError(DETAIL)
        except ValueError as original:
            if path == "cancellation":
                raise asyncio.CancelledError(DETAIL) from original
            raise RuntimeError("Request failed") from original

    class BrokenHandler(logging.Handler):
        def emit(self, record):
            raise OSError(DETAIL)

    if path == "logging_handler":
        monkeypatch.setattr(logger, "handlers", [BrokenHandler()])
    sent, captured, cycle = await run_with_uvicorn(app, caplog, monkeypatch)
    assert len(captured) == 1
    error = captured[0]
    assert type(error) is (asyncio.CancelledError if path == "cancellation" else RuntimeError)
    assert error.__context__ is None and error.__cause__ is None
    rendered = caplog.text + "".join(traceback.format_exception(error))
    assert SECRET not in rendered and "key.PEM" not in rendered and "marker=42" not in rendered
    if phase == "before_start":
        assert sent[0]["status"] == 500
        assert cycle.response_complete is True
        cycle.transport.close.assert_not_called()
    else:
        cycle.transport.close.assert_called_once_with()
        assert sent[0]["status"] == 200
        assert len(sent) == (1 if phase == "after_start" else 2)
