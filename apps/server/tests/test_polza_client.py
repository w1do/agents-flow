"""Контрактные тесты PolzaRouter (respx): запрос, повторы по D-31, ошибки без утечек."""

import asyncio
import json
from typing import Any

import httpx
import pytest
import respx
from harness_server.adapters.polza import PolzaRouter, RouterError

pytestmark = pytest.mark.asyncio

API_URL = "https://polza.test/api/v1/"
ENDPOINT = "https://polza.test/api/v1/chat/completions"
KEY = "test-polza-key-0123456789"
MODEL = "test/model"
SYSTEM = "системный промпт"
USER = "сделай авторизацию"


def _ok(content: str = '{"class": "work"}') -> httpx.Response:
    return httpx.Response(
        200,
        json={"model": MODEL, "choices": [{"message": {"role": "assistant", "content": content}}]},
    )


def _router(http: httpx.AsyncClient, delays: list[float], **kwargs: Any) -> PolzaRouter:
    async def fake_sleep(seconds: float) -> None:
        delays.append(seconds)

    return PolzaRouter(API_URL, KEY, MODEL, http, sleep=fake_sleep, **kwargs)


@respx.mock
async def test_complete_posts_chat_completion() -> None:
    route = respx.post(ENDPOINT).mock(return_value=_ok())

    async with httpx.AsyncClient() as http:
        await _router(http, []).complete(system_prompt=SYSTEM, user_text=USER)

    request = route.calls.last.request
    assert request.headers["Authorization"] == f"Bearer {KEY}"
    body = json.loads(request.content)
    assert body["model"] == MODEL
    assert body["messages"] == [
        {"role": "system", "content": SYSTEM},
        {"role": "user", "content": USER},
    ]
    assert body["temperature"] == 0
    assert body["max_tokens"] == 300
    assert body["response_format"] == {"type": "json_object"}


@respx.mock
async def test_complete_returns_content_and_model() -> None:
    respx.post(ENDPOINT).mock(return_value=_ok('{"class": "status"}'))

    async with httpx.AsyncClient() as http:
        reply = await _router(http, []).complete(system_prompt=SYSTEM, user_text=USER)

    assert reply.content == '{"class": "status"}'
    assert reply.model == MODEL


@respx.mock
async def test_retry_after_timeout_then_success() -> None:
    route = respx.post(ENDPOINT).mock(side_effect=[httpx.ReadTimeout("t"), _ok()])
    delays: list[float] = []

    async with httpx.AsyncClient() as http:
        reply = await _router(http, delays).complete(system_prompt=SYSTEM, user_text=USER)

    assert route.call_count == 2
    assert delays == [1.0]
    assert reply.content == '{"class": "work"}'


@respx.mock
@pytest.mark.parametrize("status", [408, 429, 500, 502, 503, 504])
async def test_retry_on_transient_status(status: int) -> None:
    route = respx.post(ENDPOINT).mock(side_effect=[httpx.Response(status), _ok()])

    async with httpx.AsyncClient() as http:
        await _router(http, []).complete(system_prompt=SYSTEM, user_text=USER)

    assert route.call_count == 2


@respx.mock
async def test_retry_after_header_used() -> None:
    route = respx.post(ENDPOINT).mock(
        side_effect=[httpx.Response(429, headers={"Retry-After": "2"}), _ok()]
    )
    delays: list[float] = []

    async with httpx.AsyncClient() as http:
        await _router(http, delays).complete(system_prompt=SYSTEM, user_text=USER)

    assert route.call_count == 2
    assert delays == [2.0]


@respx.mock
async def test_retry_after_header_capped() -> None:
    respx.post(ENDPOINT).mock(
        side_effect=[httpx.Response(429, headers={"Retry-After": "60"}), _ok()]
    )
    delays: list[float] = []

    async with httpx.AsyncClient() as http:
        await _router(http, delays).complete(system_prompt=SYSTEM, user_text=USER)

    assert delays == [5.0]


@respx.mock
async def test_two_transient_failures_raise() -> None:
    route = respx.post(ENDPOINT).mock(side_effect=[httpx.Response(503), httpx.Response(503)])

    async with httpx.AsyncClient() as http:
        with pytest.raises(RouterError) as info:
            await _router(http, []).complete(system_prompt=SYSTEM, user_text=USER)

    assert info.value.reason == "http_503"
    assert route.call_count == 2


@respx.mock
@pytest.mark.parametrize("code", [401, 402, 403, 404, 413, 422])
async def test_no_retry_on_client_errors(code: int) -> None:
    route = respx.post(ENDPOINT).mock(return_value=httpx.Response(code))

    async with httpx.AsyncClient() as http:
        with pytest.raises(RouterError) as info:
            await _router(http, []).complete(system_prompt=SYSTEM, user_text=USER)

    assert info.value.reason == f"http_{code}"
    assert route.call_count == 1


@respx.mock
async def test_400_retries_without_response_format() -> None:
    route = respx.post(ENDPOINT).mock(side_effect=[httpx.Response(400), _ok()])
    delays: list[float] = []

    async with httpx.AsyncClient() as http:
        await _router(http, delays).complete(system_prompt=SYSTEM, user_text=USER)

    assert route.call_count == 2
    first = json.loads(route.calls[0].request.content)
    second = json.loads(route.calls[1].request.content)
    assert "response_format" in first
    assert "response_format" not in second
    assert delays == []


@respx.mock
async def test_400_twice_raises() -> None:
    route = respx.post(ENDPOINT).mock(side_effect=[httpx.Response(400), httpx.Response(400)])

    async with httpx.AsyncClient() as http:
        with pytest.raises(RouterError) as info:
            await _router(http, []).complete(system_prompt=SYSTEM, user_text=USER)

    assert info.value.reason == "http_400"
    assert route.call_count == 2


@respx.mock
async def test_invalid_json_body_raises_without_retry() -> None:
    route = respx.post(ENDPOINT).mock(return_value=httpx.Response(200, content="не json".encode()))

    async with httpx.AsyncClient() as http:
        with pytest.raises(RouterError) as info:
            await _router(http, []).complete(system_prompt=SYSTEM, user_text=USER)

    assert info.value.reason == "invalid_response"
    assert route.call_count == 1


@respx.mock
@pytest.mark.parametrize(
    "body",
    [
        {},
        {"choices": []},
        {"choices": [{"message": {}}]},
        {"choices": [{"message": {"content": "  "}}]},
        [],
    ],
)
async def test_bad_shape_raises_invalid_response(body: Any) -> None:
    respx.post(ENDPOINT).mock(return_value=httpx.Response(200, json=body))

    async with httpx.AsyncClient() as http:
        with pytest.raises(RouterError) as info:
            await _router(http, []).complete(system_prompt=SYSTEM, user_text=USER)

    assert info.value.reason == "invalid_response"


@respx.mock
async def test_slow_response_hits_deadline() -> None:
    # respx записывает вызов только после ответа, а отменённый дедлайном запрос до него не доходит,
    # поэтому попытки считаются внутри обработчика.
    attempts: list[int] = []

    async def slow(request: httpx.Request) -> httpx.Response:
        attempts.append(1)
        await asyncio.sleep(1)
        return _ok()

    respx.post(ENDPOINT).mock(side_effect=slow)

    async with httpx.AsyncClient() as http:
        with pytest.raises(RouterError) as info:
            await _router(http, [], timeout_sec=0.05).complete(system_prompt=SYSTEM, user_text=USER)

    assert info.value.reason == "timeout"
    assert len(attempts) == 2


@respx.mock
async def test_errors_do_not_leak_key() -> None:
    respx.post(ENDPOINT).mock(side_effect=httpx.ConnectError("сеть недоступна"))

    async with httpx.AsyncClient() as http:
        router = _router(http, [])
        with pytest.raises(RouterError) as info:
            await router.complete(system_prompt=SYSTEM, user_text=USER)

    assert KEY not in str(info.value)
    assert KEY not in repr(info.value)
    assert KEY not in repr(router)
