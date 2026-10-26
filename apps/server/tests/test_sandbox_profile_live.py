"""Owner opt-in local-machine profile and secret-boundary checks."""

import os
import shutil
import subprocess
from pathlib import Path

import pytest
from harness_server.test_support.secret_scan import ScanIncomplete, contains_secret
from live_agent_env import LiveAgentEnvironment, run_agent_init

pytestmark = pytest.mark.live


REPO_ROOT = Path(__file__).resolve().parents[3]


def _workspace() -> str:
    if os.environ.get("LOCAL_AGENT_LIVE") != "1":
        pytest.skip("set LOCAL_AGENT_LIVE=1 for the owner-managed local-machine check")
    workspace = os.environ.get("LOCAL_AGENT_LIVE_WORKSPACE")
    if not workspace or os.getuid() == 0:
        pytest.skip("requires workspace and dedicated non-root user")
    return workspace


def test_agent_init_writes_private_placeholder_profile(
    live_agent_environment: LiveAgentEnvironment,
) -> None:
    workspace = _workspace()
    run_agent_init(REPO_ROOT, live_agent_environment, workspace)

    mcp = Path.home() / ".harness" / "mcp.json"
    text = mcp.read_text(encoding="utf-8")
    assert "${AGENTS_FLOW_URL}" in text
    assert "${AGENTS_FLOW_TOKEN}" in text
    assert mcp.stat().st_mode & 0o777 == 0o600

    # The worker-only variables must not be needed by init and must not appear
    # in its generated profile.  Values are never included in assertion output.
    for name in ("DATABASE_URL", "TELEGRAM_BOT_TOKEN", "VAULT_MCP_TOKEN"):
        value = os.environ.get(name)
        if value:
            assert value not in text


def test_live_memory_status_runs_when_memory_is_enabled(
    live_agent_environment: LiveAgentEnvironment,
) -> None:
    workspace = _workspace()
    if os.environ.get("LOCAL_AGENT_LIVE_MEMORY") != "1":
        pytest.skip("requires LOCAL_AGENT_LIVE_MEMORY=1 and installed memory")
    run_agent_init(REPO_ROOT, live_agent_environment, workspace)
    memory = shutil.which("memory")
    if memory is None:
        pytest.skip("requires installed memory")
    result = subprocess.run(
        [memory, "status"],
        cwd=Path.home() / "work" / workspace,
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        pytest.fail("memory status failed (output withheld)", pytrace=False)


def test_live_workspace_isolation_and_secret_search() -> None:
    workspace = _workspace()
    repo = Path.home() / "work" / workspace
    assert not (repo / ".memory" / ".env").exists()
    assert not (repo / ".git" / "config").read_text(encoding="utf-8").count("AGENTS_FLOW_TOKEN")
    needle = os.environ.get("LOCAL_AGENT_LIVE_SECRET_TO_CHECK")
    if not needle:
        pytest.skip("set LOCAL_AGENT_LIVE_SECRET_TO_CHECK for the complete disk-secret check")
    try:
        found = contains_secret(Path.home(), needle)
    except ScanIncomplete:
        pytest.fail("secret scan incomplete")
    assert not found, "secret scan found a value"
