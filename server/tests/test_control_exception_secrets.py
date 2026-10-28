"""Control exceptions keep their type without exporting messages or chains."""
import logging
import traceback

import pytest

from app.middleware.security_headers import logger
from test_round6_middleware import DETAIL, SECRET, run_with_uvicorn


@pytest.mark.parametrize("phase", ["before_start", "after_start", "partial", "complete"])
@pytest.mark.parametrize("error_type", [SystemExit, KeyboardInterrupt])
@pytest.mark.parametrize("source", ["app", "logger"])
async def test_control_exception_copies_are_safe_for_uvicorn(
        caplog, monkeypatch, phase, error_type, source):
    originals = []

    def interrupt():
        error = error_type(DETAIL)
        error.add_note(DETAIL)
        originals.append(error)
        raise error from ValueError(DETAIL)

    async def app(scope, receive, send):
        if phase != "before_start":
            await send({"type": "http.response.start", "status": 200, "headers": []})
        if phase in {"partial", "complete"}:
            await send({"type": "http.response.body", "body": b"body", "more_body": phase == "partial"})
        if source == "app":
            interrupt()
        raise ValueError(DETAIL)

    class InterruptingHandler(logging.Handler):
        def emit(self, record):
            interrupt()

    if source == "logger":
        monkeypatch.setattr(logger, "handlers", [InterruptingHandler()])
    sent, captured, cycle = await run_with_uvicorn(app, caplog, monkeypatch)
    assert len(captured) == 1 and len(originals) == 1
    error = captured[0]
    assert type(error) is error_type and error is not originals[0]
    assert error.args == () and not getattr(error, "__notes__", [])
    assert error.__context__ is None and error.__cause__ is None
    assert originals[0].args == (DETAIL,) and originals[0].__cause__ is not None
    rendered = caplog.text + "".join(traceback.format_exception(error))
    assert SECRET not in rendered and "key.PEM" not in rendered and "marker=42" not in rendered
    if phase == "before_start":
        assert sent[0]["status"] == 500
    else:
        assert sent[0]["status"] == 200
        cycle.transport.close.assert_called_once_with()
