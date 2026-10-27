from sqlalchemy import select

from app.models.skill import Skill
from app.models.skill_category import SkillCategory
from app.repositories.base import Repository


class SkillRepository(Repository[Skill]):
    model = Skill

    def active_with_categories(self) -> list[tuple[Skill, str]]:
        statement = select(Skill, SkillCategory.name).join(
            SkillCategory, Skill.category_id == SkillCategory.id,
        ).where(Skill.is_active.is_(True)).order_by(Skill.id)
        return [(skill, category) for skill, category in self.session.execute(statement)]

    def lock(self, skill_id):
        return self.session.scalar(select(Skill).where(Skill.id == skill_id).with_for_update()
                                   .execution_options(populate_existing=True))
