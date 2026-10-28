"""Size enforcement counts actual streamed bytes independently of headers."""
import pytest

from app.middleware.body_limit import BodyLimitMiddleware, MAX_BODY_BYTES


@pytest.mark.parametrize("length", [None, b"1", b"invalid", b"-1", str(MAX_BODY_BYTES + 1).encode()])
async def test_reject_stream_or_declared_body_before_application(length):
    called, sent = [], []

    async def application(*args):
        called.append(True)

    chunks = iter([{"type": "http.request", "body": b"x" * MAX_BODY_BYTES, "more_body": True},
                   {"type": "http.request", "body": b"x", "more_body": False}])

    async def receive():
        return next(chunks)

    async def send(message):
        sent.append(message)

    scope = {"type": "http", "path": "/api/v1/tasks/fixture/result",
             "headers": [] if length is None else [(b"content-length", length)]}
    await BodyLimitMiddleware(application)(scope, receive, send)
    assert not called
    assert sent[0]["status"] == 422


async def test_exact_body_limit_is_replayed_once():
    body = b"x" * MAX_BODY_BYTES
    chunks = iter([{"type": "http.request", "body": body, "more_body": False}])

    async def receive():
        return next(chunks)

    async def application(scope, replay, send):
        assert await replay() == {"type": "http.request", "body": body, "more_body": False}

    scope = {"type": "http", "path": "/api/v1/tasks/fixture/result", "headers": []}
    await BodyLimitMiddleware(application)(scope, receive, None)
