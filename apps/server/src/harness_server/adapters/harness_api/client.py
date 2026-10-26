"""Клиент API сервера для `agent init`: запрос настроек проекта (project-catalog, D-65).

Единственный модуль машины агента, который ходит на сервер по сети. Токен оператора уходит только
в заголовке Authorization и нигде не печатается. Текст ошибок — только причина, без адреса, тела
ответа и токена: сеть и сервер могут вернуть что угодно.
"""

from typing import Final
from urllib.parse import urlsplit

import httpx
from harness_shared.projects import ProjectSettings
from pydantic import ValidationError

# Настройки — короткий JSON; дольше 15 секунд сервер не должен отвечать на запрос к каталогу.
SETTINGS_TIMEOUT_SEC: Final = 15.0
_LOOPBACK_HOSTS: Final = frozenset({"localhost", "127.0.0.1", "::1"})


class HarnessApiError(Exception):
    """Отказ сервера или сети. code — машинный код для CLI, reason — текст без значений."""

    def __init__(self, code: str, reason: str) -> None:
        self.code = code
        self.reason = reason
        super().__init__(reason)


def check_server_url(base_url: str) -> str:
    """Адрес сервера: https, а для локальной разработки — http только на loopback.

    Токен оператора идёт в заголовке, поэтому открытый http на внешний адрес недопустим.
    """
    parts = urlsplit(base_url)
    if parts.scheme == "https" and parts.hostname:
        return base_url.rstrip("/")
    if parts.scheme == "http" and parts.hostname in _LOOPBACK_HOSTS:
        return base_url.rstrip("/")
    raise HarnessApiError(
        "bad_url", "HARNESS_PUBLIC_URL должен быть https-адресом сервера (http — только localhost)"
    )


async def fetch_project_settings(
    base_url: str,
    token: str,
    project_id: str,
    *,
    transport: httpx.AsyncBaseTransport | None = None,
) -> ProjectSettings:
    """Настройки активного проекта с сервера. Отказы переводятся в HarnessApiError с кодом.

    transport — подмена сети в тестах (respx); в проде не задаётся.
    """
    url = f"{check_server_url(base_url)}/api/projects/{project_id}/settings"
    try:
        async with httpx.AsyncClient(transport=transport, timeout=SETTINGS_TIMEOUT_SEC) as client:
            response = await client.get(url, headers={"Authorization": f"Bearer {token}"})
    except httpx.HTTPError:
        # Текст исключения может содержать адрес: в сообщение уходит только причина.
        raise HarnessApiError(
            "unreachable", "сервер недоступен: проверьте HARNESS_PUBLIC_URL и сеть"
        ) from None

    if response.status_code == 200:
        try:
            return ProjectSettings.model_validate(response.json())
        except (ValidationError, ValueError):
            raise HarnessApiError(
                "bad_response", "ответ сервера не похож на настройки проекта"
            ) from None
    if response.status_code == 401:
        raise HarnessApiError(
            "unauthorized", "сервер отклонил токен оператора: проверьте HARNESS_ADMIN_TOKEN"
        )
    if response.status_code == 404:
        raise HarnessApiError("not_found", f"проект не найден на сервере: {project_id}")
    if response.status_code == 409:
        raise HarnessApiError(
            "project_disabled", "проект отключён на сервере: локальная инициализация отказана"
        )
    raise HarnessApiError("http_error", f"сервер ответил кодом {response.status_code}")
