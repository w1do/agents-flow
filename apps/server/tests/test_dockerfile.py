"""Образ харнесса содержит скрипт bootstrap песочницы (bootstrap-in-image, D-63)."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
DOCKERFILE = ROOT / "Dockerfile"
DOCKERIGNORE = ROOT / ".dockerignore"


def _builder_stage() -> list[str]:
    """Строки builder-стадии: от первого FROM до runtime-стадии (второй FROM)."""
    lines = DOCKERFILE.read_text(encoding="utf-8").splitlines()
    from_indexes = [i for i, line in enumerate(lines) if line.startswith("FROM ")]
    assert len(from_indexes) >= 2, "ожидаются builder и runtime стадии"
    return [line.strip() for line in lines[from_indexes[0] : from_indexes[1]]]


def test_builder_copies_bootstrap_script() -> None:
    builder = _builder_stage()
    assert "COPY deploy/sandbox ./deploy/sandbox" in builder

    runtime = DOCKERFILE.read_text(encoding="utf-8").splitlines()
    runtime_start = [i for i, line in enumerate(runtime) if line.startswith("FROM ")][1]
    assert "COPY --from=builder --chown=app:app /app /app" in [
        line.strip() for line in runtime[runtime_start:]
    ]


def test_dockerignore_keeps_bootstrap_script() -> None:
    excluded = {
        "deploy",
        "deploy/",
        "deploy/sandbox",
        "deploy/sandbox/",
        "deploy/*",
        "deploy/**",
        "**/deploy",
        "*.sh",
        "**/*.sh",
    }
    patterns = [
        line.strip()
        for line in DOCKERIGNORE.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]
    assert excluded.isdisjoint(patterns), sorted(excluded & set(patterns))


def test_dockerfile_installs_workspace_editable() -> None:
    # Путь к скрипту от корня приложения (D-63) опирается на editable-установку workspace:
    # без неё cli.py не лежит в /app/apps/server/src.
    assert "--no-editable" not in DOCKERFILE.read_text(encoding="utf-8")
