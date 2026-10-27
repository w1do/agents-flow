from uuid import UUID, uuid4

import pytest
from sqlalchemy.exc import IntegrityError

from app import repositories as repos
from app.models import Base
from entity_factory import entity_values

ENTITIES = ["User", "Project", "ProjectInitToken", "Agent", "SkillCategory", "Skill",
            "AgentSkill", "Task", "TaskSkillSnapshot", "TaskEvent", "IdempotencyKey"]


@pytest.mark.parametrize("name", ENTITIES)
def test_crud(session, name):
    repository = getattr(repos, f"{name}Repository")(session)
    values, changes = entity_values(session, name)
    instance = repository.create(**values)
    entity_id = instance.id
    assert isinstance(entity_id, UUID)
    if hasattr(instance, "created_at"):
        assert instance.created_at is not None
    if hasattr(instance, "updated_at"):
        assert instance.updated_at is not None
    session.commit()
    session.expunge_all()
    instance = repository.get(entity_id)
    assert instance is not None
    for key, expected in values.items():
        actual = getattr(instance, key)
        if key == "expires_at":
            assert actual.replace(tzinfo=None) == expected.replace(tzinfo=None)
        else:
            assert actual == expected
    assert repository.get(uuid4()) is None
    assert [row.id for row in repository.list(id=entity_id)] == [entity_id]
    assert repository.list(offset=1) == []
    repository.update(instance, **changes)
    session.commit()
    session.expunge_all()
    instance = repository.get(entity_id)
    for key, expected in changes.items():
        assert getattr(instance, key) == expected
    repository.delete(instance)
    session.commit()
    assert repository.get(entity_id) is None
    assert repository.list() == []


@pytest.mark.parametrize("name", ["User", "Agent", "AgentSkill", "TaskSkillSnapshot", "IdempotencyKey"])
def test_unique_constraints(session, name):
    repository = getattr(repos, f"{name}Repository")(session)
    values, _ = entity_values(session, name)
    repository.create(**values)
    with pytest.raises(IntegrityError), session.begin_nested():
        repository.create(**values)


@pytest.mark.parametrize("name,field", [
    ("Agent", "status"), ("Task", "status"), ("Task", "source_type"), ("Task", "plan_decision"),
])
def test_enum_checks(session, name, field):
    repository = getattr(repos, f"{name}Repository")(session)
    values, _ = entity_values(session, name)
    with pytest.raises(IntegrityError), session.begin_nested():
        repository.create(**(values | {field: "invalid"}))


def test_event_id_is_unique_per_task_and_nullable(session):
    repository = repos.TaskEventRepository(session)
    values, _ = entity_values(session, "TaskEvent")
    repository.create(**values)
    with pytest.raises(IntegrityError), session.begin_nested():
        repository.create(**values)
    repository.create(**(values | {"event_id": None}))
    repository.create(**(values | {"event_id": None}))
    other, _ = entity_values(session, "TaskEvent")
    repository.create(**other)


def test_defaults(session):
    for name, expected in [
        ("Agent", {"status": "offline"}),
        ("Task", {"status": "new", "plan_decision": "pending", "plan_revision": 0}),
        ("Skill", {"version": 1, "is_active": True}),
        ("AgentSkill", {"enabled": True}),
    ]:
        values, _ = entity_values(session, name)
        instance = getattr(repos, f"{name}Repository")(session).create(**values)
        for field, value in expected.items():
            assert getattr(instance, field) == value


def test_foreign_keys(session):
    with pytest.raises(IntegrityError), session.begin_nested():
        repos.AgentSkillRepository(session).create(agent_id=uuid4(), skill_id=uuid4())


def test_repositories_leave_transaction_to_caller(session):
    project = repos.ProjectRepository(session).create(name="Temporary")
    entity_id = project.id
    session.rollback()
    assert repos.ProjectRepository(session).get(entity_id) is None


def test_all_primary_keys_are_uuid():
    assert len(Base.metadata.tables) == 11
    for table in Base.metadata.tables.values():
        assert [column.name for column in table.primary_key] == ["id"]
        assert table.c.id.type.python_type is UUID
