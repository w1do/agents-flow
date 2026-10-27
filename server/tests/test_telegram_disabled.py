from app.integrations.telegram import client as bot_client


async def test_no_token_disables_module_and_rest_lifespan_works(client, app, monkeypatch, flow):
    def forbidden(settings):
        raise AssertionError("Telegram adapter must not be constructed without token")

    monkeypatch.setattr(bot_client, "create_client", forbidden)
    from app.main import create_app

    disabled = create_app()
    assert not hasattr(disabled.state, "telegram")
    assert "/api/v1/telegram/webhook" not in disabled.openapi()["paths"]
    assert not hasattr(app.state, "telegram")
    assert (await client.get("/healthz")).status_code == 200
    assert (await client.post("/api/v1/telegram/webhook", json={})).status_code == 404
    response = await flow.send("POST", f"/projects/{flow.project.id}/tasks", {
        "title": "REST works", "description": "No Telegram", "source_type": "api", "source_text": "Text",
    })
    assert response.status_code == 201 and response.json()["status"] == "new"
