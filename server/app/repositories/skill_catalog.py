from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.models import AgentSkill, Skill, SkillCategory


class SkillCatalog:
    def __init__(self, session: Session):
        self.session = session

    def categories(self, offset=0, limit=50):
        return list(self.session.scalars(select(SkillCategory).order_by(
            SkillCategory.sort_order, SkillCategory.id,
        ).offset(offset).limit(limit)))

    def skills(self, category_id=None, is_active=None, offset=0, limit=50):
        query = select(Skill)
        if category_id is not None:
            query = query.where(Skill.category_id == category_id)
        if is_active is not None:
            query = query.where(Skill.is_active == is_active)
        return list(self.session.scalars(query.order_by(Skill.id).offset(offset).limit(limit)))

    def assignments(self, agent_id: UUID, active_only=False):
        query = select(AgentSkill, Skill, SkillCategory).join(
            Skill, AgentSkill.skill_id == Skill.id,
        ).join(SkillCategory, Skill.category_id == SkillCategory.id).where(
            AgentSkill.agent_id == agent_id,
        ).order_by(AgentSkill.assigned_at, AgentSkill.id)
        if active_only:
            query = query.where(AgentSkill.enabled.is_(True), Skill.is_active.is_(True))
        return self.session.execute(query).all()

    def assigned_agents(self, skill_id):
        return list(self.session.scalars(select(AgentSkill.agent_id).where(
            AgentSkill.skill_id == skill_id,
        ).order_by(AgentSkill.agent_id)))

    def remove_missing(self, agent_id, skill_ids):
        self.session.execute(delete(AgentSkill).where(
            AgentSkill.agent_id == agent_id, AgentSkill.skill_id.not_in(skill_ids),
        ))
