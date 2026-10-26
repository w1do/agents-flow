from pathlib import Path


def test_image_does_not_copy_removed_bootstrap() -> None:
    assert "deploy/sandbox" not in Path("Dockerfile").read_text()


def test_dockerfile_keeps_editable_workspace_install() -> None:
    assert "--no-editable" not in Path("Dockerfile").read_text()
