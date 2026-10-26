"""Отдельная авторизация worker: одинаковые отказы, секреты не эхоятся."""

import httpx
import pytest
from asgi_lifespan import LifespanManager
from harness_server.app import create_app
from harness_server.config import load_config
from harness_server.settings import SettingsError, load_settings

ADMIN = "test-admin-token-0123456789abcdef01"
WORKER = "test-worker-token-0123456789abcdef01"


@pytest.mark.parametrize("token", [None, ADMIN, "wrong", "токен"])
async def test_worker_rejects_invalid_auth(
    valid_env: dict[str, str], monkeypatch: pytest.MonkeyPatch, token: str | None
) -> None:
    monkeypatch.setenv("HARNESS_ADMIN_TOKEN", ADMIN)
    monkeypatch.setenv("WORKER_API_TOKEN", WORKER)
    settings = load_settings()
    app = create_app(settings, load_config(settings.harness_config))
    headers = {} if token is None else {"Authorization": f"Bearer {token}"}
    # HTTPX accepts ASCII headers only; malformed bytes still reach the ASGI auth dependency.
    raw_headers = {key.encode(): value.encode() for key, value in headers.items()}
    async with (
        LifespanManager(app),
        httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client,
    ):
        response = await client.post("/worker/tasks/claim", headers=raw_headers)
    assert response.status_code == 401
    assert response.json() == {"detail": "unauthorized"}


@pytest.mark.parametrize("token", ["short", " " * 32, ADMIN])
def test_worker_token_configuration_is_validated(
    valid_env: dict[str, str], monkeypatch: pytest.MonkeyPatch, token: str
) -> None:
    monkeypatch.setenv("HARNESS_ADMIN_TOKEN", ADMIN)
    monkeypatch.setenv("WORKER_API_TOKEN", token)
    with pytest.raises(SettingsError) as error:
        load_settings()
    assert token not in str(error.value)


async def test_worker_auth_is_fail_closed_without_configured_token(
    valid_env: dict[str, str],
) -> None:
    settings = load_settings()
    app = create_app(settings, load_config(settings.harness_config))
    async with (
        LifespanManager(app),
        httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client,
    ):
        response = await client.post(
            "/worker/tasks/claim", headers={"Authorization": f"Bearer {WORKER}"}
        )
    assert response.status_code == 401
