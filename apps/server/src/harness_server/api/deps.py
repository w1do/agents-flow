"""Зависимости FastAPI: сессия БД, конфиг и проверка временного HARNESS_ADMIN_TOKEN (D-23)."""

import hashlib
import hmac
from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import SecretStr
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from harness_server.config import HarnessConfig

# auto_error=False: собственная проверка даёт один и тот же 401 для любого отказа, а не 403 от
# FastAPI.
_bearer = HTTPBearer(auto_error=False)


def _unauthorized() -> HTTPException:
    """401 без подробностей: клиент не должен отличать «нет токена» от «токен не настроен»."""
    return HTTPException(
        status_code=401, detail="unauthorized", headers={"WWW-Authenticate": "Bearer"}
    )


async def require_admin_token(
    request: Request,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
) -> None:
    """Временный операторский доступ (D-23). Fail-closed: без настроенного токена — 401.

    Токен и заголовок Authorization не логируются и не попадают в текст ошибки.
    """
    expected: SecretStr | None = request.app.state.settings.harness_admin_token
    if expected is None or credentials is None or credentials.scheme.lower() != "bearer":
        raise _unauthorized()
    # Сравниваем фиксированные по длине sha256-дайджесты: время не зависит от длины токена.
    given_digest = hashlib.sha256(credentials.credentials.encode()).digest()
    expected_digest = hashlib.sha256(expected.get_secret_value().encode()).digest()
    if not hmac.compare_digest(given_digest, expected_digest):
        raise _unauthorized()


async def get_session(request: Request) -> AsyncIterator[AsyncSession]:
    """Сессия на запрос. Коммит делает сервис; сессия закрывается после ответа."""
    factory: async_sessionmaker[AsyncSession] = request.app.state.session_factory
    async with factory() as session:
        yield session


def get_config(request: Request) -> HarnessConfig:
    """Конфиг harness.yaml, загруженный при старте приложения."""
    config: HarnessConfig = request.app.state.config
    return config


SessionDep = Annotated[AsyncSession, Depends(get_session)]
ConfigDep = Annotated[HarnessConfig, Depends(get_config)]
