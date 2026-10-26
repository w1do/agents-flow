"""Зависимости FastAPI: сессия БД, конфиг и проверка временного HARNESS_ADMIN_TOKEN (D-23)."""

import hashlib
import hmac
from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import Depends, Header, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import SecretStr
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from harness_server.services.context import BotContext

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


async def require_webhook_secret(
    request: Request,
    x_telegram_bot_api_secret_token: Annotated[str | None, Header()] = None,
) -> None:
    """Проверка секрета webhook: 401 без заголовка или при несовпадении (D-29).

    Сравнение sha256-дайджестов через compare_digest: время не зависит от длины секрета.
    Ответ один и тот же для любого отказа; секрет и заголовок в тексте ошибки не появляются.
    """
    expected: SecretStr = request.app.state.settings.telegram_webhook_secret
    if x_telegram_bot_api_secret_token is None:
        raise HTTPException(status_code=401, detail="unauthorized")
    given_digest = hashlib.sha256(x_telegram_bot_api_secret_token.encode()).digest()
    expected_digest = hashlib.sha256(expected.get_secret_value().encode()).digest()
    if not hmac.compare_digest(given_digest, expected_digest):
        raise HTTPException(status_code=401, detail="unauthorized")


def get_bot_context(request: Request) -> BotContext:
    """Контекст бота, собранный в lifespan приложения (wiring.py)."""
    bot: BotContext = request.app.state.bot
    return bot


SessionDep = Annotated[AsyncSession, Depends(get_session)]
BotContextDep = Annotated[BotContext, Depends(get_bot_context)]
