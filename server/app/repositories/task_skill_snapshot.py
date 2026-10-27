from app.models.task_skill_snapshot import TaskSkillSnapshot
from app.repositories.base import Repository


class TaskSkillSnapshotRepository(Repository[TaskSkillSnapshot]):
    model = TaskSkillSnapshot
