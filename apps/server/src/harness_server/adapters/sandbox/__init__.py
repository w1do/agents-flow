"""Общий контракт песочницы, ошибки и фейк для сервисных тестов."""

from harness_server.adapters.sandbox.errors import SandboxError, SandboxNotFound, SandboxUnavailable
from harness_server.adapters.sandbox.fake import FakeSandbox, JournalEntry
from harness_server.adapters.sandbox.protocol import ExecResult, SandboxProvider

__all__ = [
    "ExecResult",
    "FakeSandbox",
    "JournalEntry",
    "SandboxError",
    "SandboxNotFound",
    "SandboxProvider",
    "SandboxUnavailable",
]
