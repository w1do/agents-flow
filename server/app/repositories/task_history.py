from datetime import timedelta

from sqlalchemy import select

from app.models import TaskEvent, TaskSkillSnapshot
from app.repositories.task_event import TaskEventRepository
from app.repositories.task_skill_snapshot import TaskSkillSnapshotRepository


class TaskHistory:
    def __init__(self, session):
        self.session = session

    def events(self, task_id):
        return list(self.session.scalars(select(TaskEvent).where(TaskEvent.task_id == task_id)
                                         .order_by(TaskEvent.created_at, TaskEvent.id)))

    def snapshots(self, task_id):
        return list(self.session.scalars(select(TaskSkillSnapshot).where(
            TaskSkillSnapshot.task_id == task_id,
        ).order_by(TaskSkillSnapshot.id)))

    def was_claimed(self, task_id):
        return self.session.scalar(select(TaskEvent.id).where(
            TaskEvent.task_id == task_id, TaskEvent.event_type == "claimed",
        ).limit(1)) is not None

    def event(self, task_id, event_id):
        return self.session.scalar(select(TaskEvent).where(
            TaskEvent.task_id == task_id, TaskEvent.event_id == event_id,
        ))

    def append(self, task_id, event_type, message, *, agent_id=None, event_id=None, payload=None):
        from app.core import time

        previous = self.session.scalar(select(TaskEvent.created_at).where(
            TaskEvent.task_id == task_id,
        ).order_by(TaskEvent.created_at.desc()).limit(1))
        timestamp = time.now()
        if previous and time.as_utc(previous) >= timestamp:
            timestamp = time.as_utc(previous) + timedelta(microseconds=1)
        return TaskEventRepository(self.session).create(
            task_id=task_id, event_type=event_type, message=message, agent_id=agent_id,
            event_id=event_id, payload=payload, created_at=timestamp,
        )

    def snapshot(self, task_id, files):
        existing = {row.skill_id for row in self.snapshots(task_id)}
        claimed = self.session.scalar(select(TaskEvent.id).where(
            TaskEvent.task_id == task_id, TaskEvent.event_type == "claimed",
        ).limit(1))
        if existing or claimed:
            return
        for skill in files:
            if skill.skill_id not in existing:
                TaskSkillSnapshotRepository(self.session).create(
                    task_id=task_id, skill_id=skill.skill_id, skill_name=skill.name,
                    category=skill.category, skill_version=skill.version,
                    content_hash=skill.content_hash, content=skill.content, content_missing=False,
                    filename=skill.filename,
                )
