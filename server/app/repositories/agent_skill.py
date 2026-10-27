from app.models.agent_skill import AgentSkill
from app.repositories.base import Repository


class AgentSkillRepository(Repository[AgentSkill]):
    model = AgentSkill
