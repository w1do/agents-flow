"""SPA routing regressions; run from server/ alongside the backend suite."""

from secrets import token_urlsafe
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def application(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", f"sqlite+pysqlite:///{tmp_path / 'spa.db'}")
    monkeypatch.setenv("JWT_SECRET", token_urlsafe(32))
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "")
    from app.core.config import Settings, get_settings

    # Tests use explicit process configuration and never consult dotenv files.
    monkeypatch.setitem(Settings.model_config, "env_file", None)
    get_settings.cache_clear()
    from app.core import db
    from app.main import create_app
    from app.models import Base
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    engine = create_engine(get_settings().database_url, connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    monkeypatch.setattr(db, "SessionLocal", sessionmaker(bind=engine))
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "index.html").write_text("<!doctype html><html><body>Panel</body></html>")
    (dist / "assets").mkdir()
    (dist / "assets" / "panel.js").write_text("console.info('panel')")
    yield create_app, dist
    engine.dispose()
    get_settings.cache_clear()


def test_spa_and_reserved_routes(application):
    create_app, dist = application
    app = create_app(web_dist=dist)

    @app.get("/test/late-route")
    def late_route():
        return {"late": True}

    with TestClient(app) as client:
        for path in ["/", "/login", "/projects", f"/tasks/{uuid4()}", "/skills"]:
            response = client.get(path, headers={"Accept": "text/html"})
            assert response.status_code == 200
            assert response.headers["content-type"].startswith("text/html")
            assert response.headers["cache-control"] == "no-cache"
        assert "javascript" in client.get("/assets/panel.js").headers["content-type"]
        direct_index = client.get("/index.html")
        assert direct_index.headers["cache-control"] == "no-cache"
        assert client.get("/assets/missing.js").status_code == 404
        assert client.get("/healthz").json() == {"status": "ok"}
        assert client.get("/openapi.json").json()["info"]["title"] == "Agents Flow"
        assert client.get("/api/v1/projects").status_code == 401
        assert client.get("/test/late-route").json() == {"late": True}
        assert client.get("/test/missing").status_code == 404
        json_route = client.get(f"/projects/{uuid4()}", headers={"Accept": "application/json"})
        assert json_route.status_code == 404
        assert json_route.headers["content-type"].startswith("application/json")
        html_route = client.get(f"/projects/{uuid4()}", headers={"Accept": "text/html;q=0.5"})
        assert html_route.status_code == 200 and html_route.text.endswith("Panel</body></html>")
        rejected_html = client.get(f"/projects/{uuid4()}", headers={"Accept": "text/html;q=0"})
        assert rejected_html.status_code == 404
        assert client.post("/projects", headers={"Accept": "text/html"}).status_code == 404
        assert client.post("/api/v1/telegram/webhook", json={}).status_code == 404
        for path in ["/api/v1/openapi.json", "/api/v1", "/api/v1/missing", "/mcp/missing", "/healthz/missing"]:
            response = client.get(path)
            assert response.status_code == 404
            assert "text/html" not in response.headers["content-type"]
        response = client.get("/mcp")
        assert response.status_code == 401
        assert "text/html" not in response.headers["content-type"]


def test_no_build_keeps_api_available(application, tmp_path):
    create_app, _ = application
    with TestClient(create_app(web_dist=tmp_path / "absent")) as client:
        assert client.get("/healthz").status_code == 200
        assert client.get(f"/tasks/{uuid4()}").status_code == 404
        assert client.get("/api/v1/projects").status_code == 401


def test_static_cannot_escape_dist(application, tmp_path):
    create_app, dist = application
    secret = tmp_path / "outside.txt"
    secret.write_text("not public")
    (dist / "escape.txt").symlink_to(secret)
    with TestClient(create_app(web_dist=dist)) as client:
        assert client.get("/escape.txt").status_code == 404
        assert client.get("/assets/%2e%2e/%2e%2e/outside.txt").status_code == 404
