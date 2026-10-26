"""Test-local environment boundary for owner-opt-in ``agent init`` live checks."""

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Final

import pytest

LOCAL_AGENT_LIVE: Final = "LOCAL_AGENT_LIVE"
LOCAL_AGENT_LIVE_HARNESS_CONFIG: Final = "LOCAL_AGENT_LIVE_HARNESS_CONFIG"
_OPTIONAL_AGENT_SETTINGS: Final = ("VAULT_MCP_URL", "VAULT_MCP_TOKEN", "HARNESS_PUBLIC_URL")
_SYSTEM_NAMES: Final = frozenset({"PATH", "HOME", "USER", "LOGNAME", "LANG", "TERM"})


@dataclass(frozen=True)
class LiveAgentEnvironment:
    """Session-captured operator inputs; values are never formatted into diagnostics."""

    config_path: Path
    optional_settings: dict[str, str]


def capture_live_agent_environment() -> LiveAgentEnvironment:
    """Capture the explicit owner opt-in inputs before function-scoped env cleaning."""
    if os.environ.get(LOCAL_AGENT_LIVE) != "1":
        pytest.skip("set LOCAL_AGENT_LIVE=1 for owner local-machine acceptance")
    configured_path = os.environ.get(LOCAL_AGENT_LIVE_HARNESS_CONFIG)
    if not configured_path:
        pytest.skip("set LOCAL_AGENT_LIVE_HARNESS_CONFIG to an explicit local config path")
    return LiveAgentEnvironment(
        config_path=Path(configured_path),
        optional_settings={
            name: value for name in _OPTIONAL_AGENT_SETTINGS if (value := os.environ.get(name))
        },
    )


def minimal_agent_init_environment(captured: LiveAgentEnvironment) -> dict[str, str]:
    """Build the only environment passed to the ``agent init`` child process."""
    environment = {
        name: value
        for name, value in os.environ.items()
        if name in _SYSTEM_NAMES or name.startswith("LC_")
    }
    environment["HARNESS_CONFIG"] = str(captured.config_path)
    environment.update(captured.optional_settings)
    return environment


def current_worktree_agent(repo_root: Path) -> Path:
    """Return the explicit worktree entry point, never resolving ``agent`` through PATH."""
    entry_point = repo_root / ".venv" / "bin" / "agent"
    if not entry_point.is_file() or not os.access(entry_point, os.X_OK):
        pytest.skip("current worktree .venv/bin/agent is unavailable")
    return entry_point


def run_agent_init(repo_root: Path, captured: LiveAgentEnvironment, workspace: str) -> None:
    """Run the explicit entry point without exposing child output or settings in failures."""
    import subprocess

    result = subprocess.run(
        [str(current_worktree_agent(repo_root)), "init", workspace],
        env=minimal_agent_init_environment(captured),
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        pytest.fail("agent init failed (output withheld)", pytrace=False)
