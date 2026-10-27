from uuid import UUID

from app.core.errors import not_found
from app.core.time import as_utc
from app.repositories.agent import AgentRepository
from app.repositories.agent_skill import AgentSkillRepository
from app.repositories.skill import SkillRepository
from app.repositories.skill_catalog import SkillCatalog
from app.repositories.skill_category import SkillCategoryRepository
from app.schemas.harness import SkillFile
from app.schemas.skills import CategoryResponse, SkillResponse
from app.services.skill_content import content_values, slug, warn


def get_category(session, category_id):
    category = SkillCategoryRepository(session).get(category_id)
    if category is None:
        raise not_found()
    return category


def get_skill(session, skill_id):
    skill = SkillRepository(session).get(skill_id)
    if skill is None:
        raise not_found()
    return skill


def get_agent(session, agent_id):
    agent = AgentRepository(session).get(agent_id)
    if agent is None:
        raise not_found()
    return agent


def category_save(session, body, category_id=None):
    repo = SkillCategoryRepository(session)
    values = body.model_dump(exclude_unset=True)
    category = repo.update(get_category(session, category_id), **values) if category_id else repo.create(**values)
    return CategoryResponse.model_validate(category)


def skill_response(session, skill, warnings=None, assignment=None):
    response = SkillResponse.model_validate(skill)
    response.content = skill.content
    response.created_at, response.updated_at = as_utc(skill.created_at), as_utc(skill.updated_at)
    response.warnings = warnings or []
    response.assigned_agents = SkillCatalog(session).assigned_agents(skill.id)
    if assignment:
        response.enabled = assignment.enabled
        response.assigned_at = as_utc(assignment.assigned_at)
    return response


def skill_save(session, body, skill_id=None):
    repo = SkillRepository(session)
    skill = repo.lock(skill_id) if skill_id else None
    if skill_id and skill is None:
        raise not_found()
    values = body.model_dump(exclude_unset=True)
    if "category_id" in values:
        get_category(session, values["category_id"])
    warnings = []
    if "content" in values:
        warnings = warn(values["content"])
        values.update(content_values(values["content"]))
        if skill is None or values["content"] != skill.content:
            values["version"] = skill.version + 1 if skill else 1
    skill = repo.update(skill, **values) if skill else repo.create(**values)
    return skill_response(session, skill, warnings)


def archive(session, skill_id):
    skill = SkillRepository(session).lock(skill_id)
    if skill is None:
        raise not_found()
    SkillRepository(session).update(skill, is_active=False)
    return skill_response(session, skill)


def assigned(session, agent_id):
    get_agent(session, agent_id)
    return [skill_response(session, skill, assignment=link)
            for link, skill, _ in SkillCatalog(session).assignments(agent_id)]


def replace(session, agent_id, body):
    AgentRepository(session).lock(agent_id)
    get_agent(session, agent_id)
    for skill_id in body.skill_ids:
        get_skill(session, skill_id)
    catalog = SkillCatalog(session)
    existing = {link.skill_id: link for link, _, _ in catalog.assignments(agent_id)}
    catalog.remove_missing(agent_id, body.skill_ids)
    repo = AgentSkillRepository(session)
    for skill_id in body.skill_ids:
        enabled = skill_id not in body.disabled_skill_ids
        if skill_id in existing:
            repo.update(existing[skill_id], enabled=enabled)
        else:
            repo.create(agent_id=agent_id, skill_id=skill_id, enabled=enabled)
    return assigned(session, agent_id)


def sync(session, agent_id: UUID):
    files, used = [], set()
    for _, skill, category in SkillCatalog(session).assignments(agent_id, active_only=True):
        base = f"{slug(category.name)}--{slug(skill.name)}"
        filename, suffix = f"{base}.md", 2
        while filename in used:
            filename, suffix = f"{base}-{suffix}.md", suffix + 1
        used.add(filename)
        files.append(SkillFile(skill_id=skill.id, name=skill.name, filename=filename,
                               category=category.name,
                               version=skill.version, content_hash=skill.content_hash,
                               content=skill.content))
    return {"skills": files}


def list_categories(session, offset, limit):
    return SkillCatalog(session).categories(offset, limit)


def list_skills(session, category_id, is_active, offset, limit):
    return [skill_response(session, skill) for skill in
            SkillCatalog(session).skills(category_id, is_active, offset, limit)]
