import asyncio
from uuid import uuid4

from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select
from sqlalchemy.orm import sessionmaker

from app.models import Task


async def test_parallel_same_idempotency_key_returns_same_task(flow, app):
    from app.core import db

    factory = sessionmaker(bind=flow.session.bind, expire_on_commit=False)

    def get_db():
        with factory() as session:
            yield session

    app.dependency_overrides[db.get_db] = get_db
    transport = ASGITransport(app=app)
    key = str(uuid4())
    body = {"title": "Concurrent", "description": "", "source_type": "api",
            "source_text": "Once"}
    path = f"/api/v1/projects/{flow.project.id}/tasks"
    headers = flow.admin | {"Idempotency-Key": key}
    sqlite_lock = asyncio.Lock()

    async def send():
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            if flow.session.bind.dialect.name == "sqlite":
                async with sqlite_lock:
                    return await client.post(path, json=body, headers=headers)
            return await client.post(path, json=body, headers=headers)

    first, second = await asyncio.gather(send(), send())
    assert first.status_code == second.status_code == 201
    assert first.content == second.content
    assert flow.session.scalar(select(func.count()).select_from(Task)) == 1
