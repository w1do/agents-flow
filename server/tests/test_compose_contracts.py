from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_console_receives_jwt_secret_required_by_database_settings():
    compose = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")
    console = compose.split("  console:\n", 1)[1].split("\nsecrets:\n", 1)[0]
    assert "secrets: [database_url, jwt_secret, admin_password]" in console


def test_postgres_services_run_as_image_user_without_added_capabilities():
    for path in (ROOT / "docker-compose.local.yml", ROOT / "deploy/db/docker-compose.yml"):
        compose = path.read_text(encoding="utf-8")
        database = compose.split("  db:\n", 1)[1].split("\n  migrate:", 1)[0] if "\n  migrate:" in compose else compose.split("  db:\n", 1)[1].split("\nsecrets:", 1)[0]
        assert 'user: "70:70"' in database
        assert 'group_add: ["${SECRETS_GID:-1000}"]' in database
        assert "cap_add:" not in database
        assert "cap_drop: [ALL]" in database
        assert "no-new-privileges:true" in database
        assert "read_only: true" in database


def test_postgres_secret_group_requirement_is_documented():
    readme = (ROOT / "deploy/README.md").read_text(encoding="utf-8")
    assert "PostgreSQL runs as UID/GID 70" in readme
    assert "joins the same group" in readme
    assert 'sudo chmod 0440 .secrets/postgres_password' in readme
