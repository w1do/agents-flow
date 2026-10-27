from app.models.task_event import TaskEvent
from app.repositories.base import Repository


class TaskEventRepository(Repository[TaskEvent]):
    model = TaskEvent
