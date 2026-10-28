from hashlib import sha256
from uuid import uuid4

import pytest


async def test_category_skill_versions_and_card(flow):
    category = await flow.send("POST", "/skill-categories", {"name": "SEO", "description": "Search"})
    assert category.status_code == 201
    category_id = category.json()["id"]
    changed = await flow.send("PATCH", f"/skill-categories/{category_id}", {"name": "Разработка", "sort_order": 3})
    assert changed.json()["sort_order"] == 3
    created = await flow.send("POST", "/skills", dict(category_id=category_id, name="Build",
                                                     description="Compile", content="# Build"))
    assert created.status_code == 201
    skill = created.json()
    assert skill["version"] == 1
    assert skill["content_hash"] == sha256(b"# Build").hexdigest()
    path = f'/skills/{skill["id"]}'
    renamed = await flow.send("PATCH", path, {"description": "New", "name": "Build app"})
    assert renamed.json()["version"] == 1
    same = await flow.send("PATCH", path, {"content": "# Build"})
    assert same.json()["version"] == 1
    edited = await flow.send("PATCH", path, {"content": "# Test"})
    assert edited.json()["version"] == 2
    assert edited.json()["content_hash"] != skill["content_hash"]
    assert (await flow.send("GET", path)).json()["content"] == "# Test"
    listing = await flow.send("GET", f"/skills?category_id={category_id}&is_active=true&limit=1")
    assert len(listing.json()) == 1
    categories = await flow.send("GET", "/skill-categories")
    assert categories.json()[0]["name"] == "Разработка"


@pytest.mark.parametrize("content,pattern", [
    ("-----BEGIN RSA PRIVATE KEY-----\nexample\n-----END RSA PRIVATE KEY-----", "private_key"),
    ("ghp_" + "x" * 36, "github_token"), ("sk-" + "a" * 40, "api_token"),
    ("AKIA" + "A" * 16, "aws_key"),
])
async def test_secret_warning_preserves_skill_content(flow, caplog, content, pattern):
    existing = flow.skill()
    response = await flow.send("PATCH", f"/skills/{existing.id}", {"content": content})
    assert response.status_code == 200
    assert pattern in response.json()["warnings"]
    assert response.json()["content"] == content
    assert (await flow.send("GET", f"/skills/{existing.id}")).json()["content"] == content
    assert content not in caplog.text
    assert "Skill content matched" in caplog.text


async def test_secret_scanner_preserves_words_and_hashes(flow):
    from hashlib import sha256

    content = "Use task-status and task-reports; SHA256: " + "a" * 64
    created = await flow.send("POST", "/skill-categories", {"name": "Docs", "description": ""})
    skill = await flow.send("POST", "/skills", {"category_id": created.json()["id"],
                         "name": "Text", "description": "", "content": content})
    assert skill.json()["content"] == content and skill.json()["warnings"] == []
    assert skill.json()["content_hash"] == sha256(content.encode()).hexdigest()


@pytest.mark.parametrize("body", [{}, {"name": ""}, {"content": None}, {"unknown": True}])
async def test_patch_validation(flow, body):
    response = await flow.send("PATCH", f"/skills/{flow.skill().id}", body)
    assert response.status_code == 422


async def test_skill_markdown_is_limited_to_256_kib(flow):
    skill = flow.skill()
    path = f"/skills/{skill.id}"
    accepted = "x" * (256 * 1024)
    response = await flow.send("PATCH", path, {"content": accepted})
    assert response.status_code == 200
    assert len(response.json()["content"].encode("utf-8")) == 256 * 1024
    too_large = "я" * 200_000
    response = await flow.send("PATCH", path, {"content": too_large})
    assert response.status_code == 422


async def test_skill_permissions_and_missing_category(flow):
    assert (await flow.send("GET", "/skills", headers={})).status_code == 401
    assert (await flow.send("GET", "/skills", headers=flow.headers)).status_code == 403
    assert (await flow.send("GET", f"/skills/{uuid4()}")).status_code == 404
    invalid = dict(category_id=str(uuid4()), name="Name", description="", content="Text")
    assert (await flow.send("POST", "/skills", invalid)).status_code == 404
    assert (await flow.send("GET", "/skills?limit=201")).status_code == 422


async def test_categories_sort_and_validation(flow):
    for name, order in [("Later", 5), ("First", 0)]:
        assert (await flow.send("POST", "/skill-categories", dict(name=name, description="", sort_order=order))).status_code == 201
    assert [c["name"] for c in (await flow.send("GET", "/skill-categories")).json()] == ["First", "Later"]
    assert (await flow.send("PATCH", f"/skill-categories/{uuid4()}", {"name": "Other"})).status_code == 404
    assert (await flow.send("POST", "/skill-categories", {"name": " ", "description": ""})).status_code == 422
