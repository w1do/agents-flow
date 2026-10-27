from app.models.skill_category import SkillCategory
from app.repositories.base import Repository


class SkillCategoryRepository(Repository[SkillCategory]):
    model = SkillCategory
