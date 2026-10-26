"""Машина worker загружается без серверных ENV; секреты не попадают в диагностику."""

import ast
from pathlib import Path

import pytest
from harness_server.settings import SettingsError
from harness_server.worker.settings import load_worker_settings


def test_worker_needs_no_database_telegram_or_server_secret(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("HARNESS_CONFIG", "/tmp/harness.yaml")
    monkeypatch.setenv("HARNESS_PUBLIC_URL", "http://127.0.0.1:8000")
    monkeypatch.setenv("WORKER_API_TOKEN", "test-worker-token-0123456789abcdef01")
    settings = load_worker_settings()
    assert settings.harness_config == Path("/tmp/harness.yaml")
    assert not hasattr(settings, "database_url") and not hasattr(settings, "harness_secret_key")


@pytest.mark.parametrize(
    "url",
    ["http://remote.test", "https://user:pass@remote.test", "https://remote.test?secret=value"],
)
def test_worker_rejects_unsafe_server_urls(monkeypatch: pytest.MonkeyPatch, url: str) -> None:
    monkeypatch.setenv("HARNESS_CONFIG", "/tmp/harness.yaml")
    monkeypatch.setenv("HARNESS_PUBLIC_URL", url)
    monkeypatch.setenv("WORKER_API_TOKEN", "secret-too-short")
    with pytest.raises(SettingsError) as caught:
        load_worker_settings()
    assert url not in str(caught.value) and "secret-too-short" not in str(caught.value)


def test_worker_modules_do_not_import_database() -> None:
    from harness_server import worker

    assert worker.__file__ is not None
    for path in Path(worker.__file__).parent.glob("*.py"):
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            modules = []
            if isinstance(node, ast.ImportFrom):
                modules = [node.module or ""]
            elif isinstance(node, ast.Import):
                modules = [alias.name for alias in node.names]
            assert not any(
                module.startswith(("harness_server.db", "sqlalchemy")) for module in modules
            ), path
