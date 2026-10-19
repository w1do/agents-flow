"""Адаптер vault: Protocol SecretVault, ошибки, фейк для тестов и MCP-клиент (D-45)."""

from harness_server.adapters.vault.errors import VaultError, VaultErrorReason
from harness_server.adapters.vault.fake import FakeVault
from harness_server.adapters.vault.mcp_client import McpSecretVault
from harness_server.adapters.vault.protocol import SecretVault

__all__ = [
    "FakeVault",
    "McpSecretVault",
    "SecretVault",
    "VaultError",
    "VaultErrorReason",
]
