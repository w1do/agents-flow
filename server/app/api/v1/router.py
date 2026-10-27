from fastapi import APIRouter

from app.api.v1 import (
    agent_skills, auth, harness, leases, projects, skill_categories, skills,
    task_decisions, task_reports, tasks,
)

router = APIRouter()
for module in (auth, projects, harness, skill_categories, skills, agent_skills, tasks,
               leases, task_reports, task_decisions):
    router.include_router(module.router)
