"""Proxy prefixes and sanitized exception logs."""
import pytest

from app.middleware.body_limit import BodyLimitMiddleware, MAX_BODY_BYTES
from app.middleware.security_headers import SecurityHeadersMiddleware


@pytest.mark.parametrize("prefixed", [True, False])
async def test_body_limit_with_root_path(prefixed):
    sent = []

    async def app(*args):
        pytest.fail("oversized report reached application")

    async def receive():
        return {"type": "http.request", "body": b"x" * (MAX_BODY_BYTES + 1)}

    async def send(message):
        sent.append(message)

    path = "/api/v1/tasks/fixture/events"
    scope = {"type": "http", "root_path": "/prefix", "headers": [],
             "path": "/prefix" + path if prefixed else path}
    await BodyLimitMiddleware(app)(scope, receive, send)
    assert sent[0]["status"] == 422


async def test_exception_log_sanitizes_secrets_and_paths(caplog, monkeypatch):
    from app.middleware.security_headers import logger

    # Earlier SDK lifespan tests can disable existing loggers process-wide.
    monkeypatch.setattr(logger, "disabled", False)
    caplog.set_level("ERROR", logger=logger.name)
    secret = "ghp_" + "A" * 36
    sent = []

    async def app(*args):
        raise ValueError("failed " + secret + " key.PEM?marker=42")

    async def send(message):
        sent.append(message)

    await SecurityHeadersMiddleware(app)({"type": "http"}, None, send)
    assert sent[0]["status"] == 500
    assert secret not in caplog.text
    assert "key.PEM" not in caplog.text and "marker=42" not in caplog.text
    assert "[REDACTED]" in caplog.text


async def test_extreme_json_depth_is_rejected_before_decoding():
    sent = []

    async def app(*args):
        pytest.fail("deep JSON reached decoder")

    async def receive():
        return {"type": "http.request", "body": b"[" * 2000 + b"0" + b"]" * 2000}

    async def send(message):
        sent.append(message)

    scope = {"type": "http", "path": "/api/v1/tasks/fixture/result", "headers": []}
    await BodyLimitMiddleware(app)(scope, receive, send)
    assert sent[0]["status"] == 422


async def test_json_depth_ignores_brackets_in_escaped_strings():
    from app.middleware.json_depth import excessive_depth
    import json

    assert excessive_depth(json.dumps({"text": '\"' + "[" * 2000}).encode()) is False
