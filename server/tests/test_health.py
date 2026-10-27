async def test_healthz(client):
    response = await client.get("/healthz")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


async def test_healthz_has_no_api_prefix(client):
    assert (await client.get("/api/v1/healthz")).status_code == 404
