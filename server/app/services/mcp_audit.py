"""Audit safe call metadata on an agent-owned task, never request bodies."""
from uuid import UUID

from app.repositories.task import TaskRepository
from app.repositories.task_history import TaskHistory
from app.schemas.mcp import TOOL_SCHEMAS


def record(session, agent, name, arguments, code):
    repo = TaskRepository(session)
    try:
        task_id = UUID(str(arguments.get("task_id")))
    except (ValueError, TypeError, AttributeError):
        task_id = None
    task = repo.get(task_id) if task_id else None
    if task is None or task.project_id != agent.project_id or task.assigned_agent_id != agent.id:
        assigned = repo.leased(agent.id)
        task = assigned[0] if assigned else None
    if task is None or task.project_id != agent.project_id:
        return  # task_events has a mandatory task FK; no unrelated task may be used.
    suffix = name.removeprefix("agent_") if name in TOOL_SCHEMAS else "unknown_tool"
    TaskHistory(session).append(
        task.id, f"mcp_{suffix}", "MCP tool call", agent_id=agent.id,
        payload={"code": code},
    )
