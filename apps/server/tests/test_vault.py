"""Vault (sandbox-profile, D-45): ссылки, разбор ответа, ошибки адаптера, resolve и build_vault.

Сеть не используется: ответы MCP собираются вручную, сбои моделируются подменой _call. Значения
секретов в тестах — заведомо фиктивные.
"""

import asyncio
import json
from typing import Any

import httpx2
import mcp.types as types
import pytest
from harness_server import wiring
from harness_server.adapters.vault import FakeVault, McpSecretVault, VaultError
from harness_server.services import secrets
from harness_server.settings import load_settings
from harness_server.vault_ref import VaultRef, is_vault_ref, parse_vault_ref
from mcp import MCPError
from pydantic import SecretStr
from pytest import MonkeyPatch

REF = VaultRef(project="demo", service="gitlab", name="main")
SECRET = "vault-test-value-0123456789abcdef"
VAULT_URL = "https://vault.example/mcp"
VAULT_TOKEN = "vault-token-test-0123456789abcdef"


@pytest.mark.parametrize(
    "text",
    [
        "vault:demo/gitlab/main",
        "vault:Проект/сервис/имя с пробелом",
        "vault:a-b_c/d.e/f:g",
    ],
)
def test_valid_vault_refs_parse_and_round_trip(text: str) -> None:
    ref = parse_vault_ref(text)

    assert ref is not None
    assert str(ref) == text
    assert parse_vault_ref(str(ref)) == ref
    assert is_vault_ref(text)


@pytest.mark.parametrize(
    "text",
    [
        "demo/gitlab/main",  # без префикса
        "vault:demo/gitlab",  # две части
        "vault:demo/gitlab/main/extra",  # четыре части
        "vault:demo//main",  # пустая часть
        "vault:/gitlab/main",
        "vault:demo/gitlab/ main",  # пробел в начале части
        "vault:demo/gitlab/main ",  # пробел в конце части
        "vault:demo/gitlab/main\nx",  # перевод строки
        "",
    ],
)
def test_invalid_vault_refs_return_none(text: str) -> None:
    assert parse_vault_ref(text) is None
    assert not is_vault_ref(text)


def test_parse_credential_reads_structured_content() -> None:
    from harness_server.adapters.vault.mcp_client import parse_credential

    result = types.CallToolResult(content=[], structured_content={"secret": SECRET})

    assert parse_credential(result, "gitlab/main").get_secret_value() == SECRET


def test_parse_credential_reads_json_text_block() -> None:
    from harness_server.adapters.vault.mcp_client import parse_credential

    text = types.TextContent(type="text", text=f'{{"secret": "{SECRET}"}}')
    result = types.CallToolResult(content=[text])

    assert parse_credential(result, "gitlab/main").get_secret_value() == SECRET


@pytest.mark.parametrize(
    "result",
    [
        types.CallToolResult(content=[], structured_content={"other": SECRET}),
        types.CallToolResult(content=[types.TextContent(type="text", text="не json")]),
        types.CallToolResult(content=[types.TextContent(type="text", text='{"x": 1}')]),
        types.CallToolResult(content=[]),
    ],
)
def test_parse_credential_without_secret_is_invalid_response(
    result: types.CallToolResult,
) -> None:
    from harness_server.adapters.vault.mcp_client import parse_credential

    with pytest.raises(VaultError) as info:
        parse_credential(result, "gitlab/main")

    assert info.value.reason == "invalid_response"


class _StubVault(McpSecretVault):
    """McpSecretVault с подменённым вызовом: ответ или исключение задаёт тест."""

    def __init__(self, behaviour: Any, *, timeout_s: float = 30) -> None:
        super().__init__(VAULT_URL, SecretStr(VAULT_TOKEN), timeout_s=timeout_s)
        self._behaviour = behaviour

    async def _call(self, ref: VaultRef) -> Any:
        return await self._behaviour(ref)


async def test_is_error_maps_to_tool_error() -> None:
    async def call(_ref: VaultRef) -> types.CallToolResult:
        return types.CallToolResult(content=[], is_error=True)

    with pytest.raises(VaultError) as info:
        await _StubVault(call).get(REF)

    assert info.value.reason == "tool_error"


async def test_deadline_maps_to_timeout() -> None:
    async def call(_ref: VaultRef) -> types.CallToolResult:
        await asyncio.sleep(10)
        return types.CallToolResult(content=[])

    with pytest.raises(VaultError) as info:
        await _StubVault(call, timeout_s=0.01).get(REF)

    assert info.value.reason == "timeout"


async def test_transport_failure_maps_to_unavailable_without_url_or_token() -> None:
    async def call(_ref: VaultRef) -> types.CallToolResult:
        raise OSError(f"connect {VAULT_URL} {VAULT_TOKEN}")

    with pytest.raises(VaultError) as info:
        await _StubVault(call).get(REF)

    assert info.value.reason == "unavailable"
    text = str(info.value)
    assert VAULT_URL not in text
    assert VAULT_TOKEN not in text
    assert "gitlab/main" in text


async def test_exception_group_from_transport_is_unwrapped() -> None:
    async def call(_ref: VaultRef) -> types.CallToolResult:
        raise BaseExceptionGroup("group", [TimeoutError()])

    with pytest.raises(VaultError) as info:
        await _StubVault(call).get(REF)

    assert info.value.reason == "timeout"


async def test_httpx_timeout_maps_to_timeout() -> None:
    async def call(_ref: VaultRef) -> types.CallToolResult:
        raise httpx2.ReadTimeout("slow")

    with pytest.raises(VaultError) as info:
        await _StubVault(call).get(REF)

    assert info.value.reason == "timeout"


async def test_mcp_error_maps_to_unavailable_not_tool_error() -> None:
    """HTTP 401 или 5xx приходят как MCPError: это недоступность сервера, а не ответ инструмента."""

    async def call(_ref: VaultRef) -> types.CallToolResult:
        raise MCPError(-32603, "Unauthorized")

    with pytest.raises(VaultError) as info:
        await _StubVault(call).get(REF)

    assert info.value.reason == "unavailable"


async def test_fatal_exception_group_propagates_unchanged() -> None:
    """Отмена внутри группы не должна стать VaultError: пробрасываем исходное исключение."""

    async def call(_ref: VaultRef) -> types.CallToolResult:
        raise BaseExceptionGroup("x", [asyncio.CancelledError()])

    with pytest.raises(BaseExceptionGroup) as info:
        await _StubVault(call).get(REF)

    assert not isinstance(info.value, VaultError)
    assert info.value.message == "x"


async def test_successful_call_returns_secret() -> None:
    async def call(_ref: VaultRef) -> types.CallToolResult:
        return types.CallToolResult(content=[], structured_content={"secret": SECRET})

    value = await _StubVault(call).get(REF)

    assert value.get_secret_value() == SECRET
    assert SECRET not in repr(value)


async def test_fake_vault_records_requests_and_fails_on_demand() -> None:
    vault = FakeVault({REF: SECRET})

    assert (await vault.get(REF)).get_secret_value() == SECRET
    assert vault.requested == [REF]
    with pytest.raises(VaultError):
        await FakeVault(fail=VaultError("timeout")).get(REF)


async def test_resolve_without_ref_returns_fallback() -> None:
    fallback = SecretStr("env-value")

    assert await secrets.resolve(None, None, fallback=fallback) is fallback
    assert await secrets.resolve(None, None, fallback=None) is None


async def test_resolve_ref_without_vault_is_not_configured() -> None:
    with pytest.raises(VaultError) as info:
        await secrets.resolve(None, "vault:demo/gitlab/main", fallback=SecretStr("env"))

    assert info.value.reason == "not_configured"


async def test_resolve_ref_reads_vault_and_ignores_fallback() -> None:
    vault = FakeVault({REF: SECRET})

    value = await secrets.resolve(vault, "vault:demo/gitlab/main", fallback=SecretStr("env"))

    assert value is not None
    assert value.get_secret_value() == SECRET
    assert vault.requested == [REF]


def test_build_vault_needs_url_and_token(
    valid_env: dict[str, str], monkeypatch: MonkeyPatch
) -> None:
    monkeypatch.setenv("VAULT_MCP_URL", VAULT_URL)
    assert wiring.build_vault(load_settings()) is None  # токен не задан

    monkeypatch.setenv("VAULT_MCP_TOKEN", VAULT_TOKEN)
    assert isinstance(wiring.build_vault(load_settings()), McpSecretVault)


REAL_SHAPE_SECRET = "cred-test-value-0123456789abcdef"


def test_parse_credential_reads_nested_credential_in_text_block() -> None:
    """Форма project-vault 1.0.0: текстовый блок с объектом credential (проверено 2026-10-19)."""
    from harness_server.adapters.vault.mcp_client import parse_credential

    payload = {
        "credential": {
            "id": "c-1",
            "projectId": "p-1",
            "projectName": "demo",
            "service": "gitlab",
            "name": "main",
            "status": "active",
            "createdAt": "2026-10-01T00:00:00Z",
            "updatedAt": "2026-10-02T00:00:00Z",
            "secret": REAL_SHAPE_SECRET,
        }
    }
    result = types.CallToolResult(
        content=[types.TextContent(type="text", text=json.dumps(payload))],
        structured_content=None,
    )

    assert parse_credential(result, "gitlab/main").get_secret_value() == REAL_SHAPE_SECRET


def test_parse_credential_reads_nested_credential_in_structured_content() -> None:
    from harness_server.adapters.vault.mcp_client import parse_credential

    result = types.CallToolResult(
        content=[], structured_content={"credential": {"secret": REAL_SHAPE_SECRET}}
    )

    assert parse_credential(result, "gitlab/main").get_secret_value() == REAL_SHAPE_SECRET


@pytest.mark.parametrize(
    "payload",
    [
        {"credential": "cred-test-plain-0123456789"},  # credential не объект
        {"credential": ["cred-test-plain-0123456789"]},
        {"credential": {"name": "main"}},  # credential без secret
        {"credential": {"secret": ""}},  # пустой secret
        {"credential": {"secret": 42}},  # secret не строка
    ],
)
def test_parse_credential_invalid_nested_shapes_are_invalid_response(
    payload: dict[str, Any],
) -> None:
    from harness_server.adapters.vault.mcp_client import parse_credential

    text_result = types.CallToolResult(
        content=[types.TextContent(type="text", text=json.dumps(payload))]
    )
    structured_result = types.CallToolResult(content=[], structured_content=payload)

    for result in (text_result, structured_result):
        with pytest.raises(VaultError) as info:
            parse_credential(result, "gitlab/main")
        assert info.value.reason == "invalid_response"
        assert "cred-test-plain" not in str(info.value)
