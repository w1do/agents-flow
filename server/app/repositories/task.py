from app.models.task import Task
from app.repositories.base import Repository


class TaskRepository(Repository[Task]):
    model = Task
