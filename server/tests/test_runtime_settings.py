from datetime import timedelta

import pytest
from pydantic import ValidationError

from app.core.config import Settings, get_settings
from app.services.init_tokens import issue_init_token


@pytest.mark.parametrize("remote", ["/repos/local.git", "../local.git", "repo.git", "./repo with spaces", "file:///repos/local.git"])
async def test_local_remotes(client, session, project, remote):
    code, _ = issue_init_token(session, project.id)
    session.commit()
    response = await client.post("/api/v1/harness/init", json={
        "project_id": str(project.id), "init_code": code, "agent_name": "Local", "git_remote": remote})
    assert response.status_code == 201


async def test_configured_intervals_used_in_init_and_leases(flow, monkeypatch, clock):
    monkeypatch.setenv("LEASE_TTL_SECONDS", "120")
    monkeypatch.setenv("POLL_INTERVAL_SECONDS", "9")
    get_settings.cache_clear()
    code, _ = issue_init_token(flow.session, flow.project.id)
    flow.session.commit()
    response = await flow.client.post("/api/v1/harness/init", json={
        "project_id": str(flow.project.id), "init_code": code, "agent_name": "Configured"})
    assert response.json()["lease_ttl_seconds"] == 120
    assert response.json()["poll_interval_seconds"] == 9
    task = flow.task()
    assert (await flow.claim()).status_code == 200
    from app.core.time import as_utc
    assert as_utc(task.lease_expires_at) == clock[0] + timedelta(seconds=120)


@pytest.mark.parametrize("field", ["lease_ttl_seconds", "poll_interval_seconds"])
@pytest.mark.parametrize("value", [0, -1])
def test_intervals_must_be_positive(field, value):
    with pytest.raises(ValidationError):
        Settings(_env_file=None, database_url="sqlite://", jwt_secret="x" * 32, **{field: value})


@pytest.mark.parametrize("remote", ["file://[", "file://remote-host/repo", "file:///repo?query", "--upload-pack=command"])
async def test_local_remote_rejects_invalid_syntax(client, session, project, remote):
    code, _ = issue_init_token(session, project.id)
    session.commit()
    response = await client.post("/api/v1/harness/init", json={
        "project_id": str(project.id), "init_code": code, "agent_name": "Local", "git_remote": remote})
    assert response.status_code == 422
