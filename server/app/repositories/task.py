from sqlalchemy import select

from app.models.task import Task
from app.repositories.base import Repository
from app.core.task_states import WORKING


class TaskRepository(Repository[Task]):
    model = Task

    def lock(self, task_id):
        return self.session.scalar(select(Task).where(Task.id == task_id).with_for_update()
                                   .execution_options(populate_existing=True))

    def next_new(self, project_id):
        return self.session.scalar(select(Task).where(
            Task.project_id == project_id, Task.status == "new",
        ).order_by(Task.created_at, Task.id).limit(1).with_for_update(skip_locked=True)
          .execution_options(populate_existing=True))

    def leased(self, agent_id):
        return list(self.session.scalars(select(Task).where(
            Task.assigned_agent_id == agent_id, Task.lease_id.is_not(None),
            Task.status.in_(WORKING | {"merged"}), Task.completed_at.is_(None),
        )))

    def expired(self, now, project_id=None):
        query = select(Task).where(Task.lease_expires_at <= now,
                                   Task.status.in_(WORKING | {"merged"}),
                                   Task.completed_at.is_(None))
        if project_id:
            query = query.where(Task.project_id == project_id)
        return list(self.session.scalars(query.order_by(Task.id).with_for_update(skip_locked=True)
                                         .execution_options(populate_existing=True)))

    def for_project(self, project_id, status=None, offset=0, limit=50):
        query = select(Task).where(Task.project_id == project_id)
        if status:
            query = query.where(Task.status == status)
        return list(self.session.scalars(query.order_by(Task.created_at, Task.id)
                                         .offset(offset).limit(limit)))
