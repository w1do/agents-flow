"""Статические контракты артефактов host-worker deployment без запуска сервисов."""

from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[3]


def _yaml(path: Path) -> dict[str, Any]:
    content = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert isinstance(content, dict)
    return content


def test_dokploy_compose_has_no_worker_service() -> None:
    services = _yaml(ROOT / "docker-compose.yml")["services"]
    assert isinstance(services, dict)
    assert set(services) == {"migrate", "server"}


def test_db_publishes_postgres_only_on_loopback() -> None:
    service = _yaml(ROOT / "deploy" / "db" / "docker-compose.yml")["services"]["postgres"]
    assert service["ports"] == ["127.0.0.1:5432:5432"]


def test_worker_unit_preserves_detached_agents_and_uses_host_environment() -> None:
    unit = (ROOT / "deploy" / "worker" / "agents-flow-worker.service").read_text()
    assert "EnvironmentFile=%h/.config/agents-flow/worker.env" in unit
    assert "ExecStart=/usr/bin/env harness-server worker" in unit
    assert "Restart=on-failure" in unit
    assert "KillMode=process" in unit
    assert "/app/" not in unit
    assert "sudo" not in unit


def test_docker_context_excludes_agent_worktrees_and_secret_containers() -> None:
    ignored = set((ROOT / ".dockerignore").read_text().splitlines())
    assert {".worktrees", "**/.env", "**/.env.*", "**/.memory", "config/harness.yaml"} <= ignored
