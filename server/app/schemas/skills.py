from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.schemas.common import Input, Patch, Text


MAX_SKILL_CONTENT_BYTES = 256 * 1024


def validate_skill_content_size(content: str) -> str:
    if len(content.encode("utf-8")) > MAX_SKILL_CONTENT_BYTES:
        raise ValueError("Markdown не должен превышать 256 КиБ в UTF-8")
    return content


class CategoryCreate(Input):
    name: Text
    description: str
    sort_order: int = Field(0, ge=0)


class CategoryPatch(Patch):
    name: Text | None = None
    description: str | None = None
    sort_order: int | None = Field(None, ge=0)


class CategoryResponse(CategoryCreate):
    model_config = ConfigDict(from_attributes=True)
    id: UUID


class SkillCreate(Input):
    category_id: UUID
    name: Text
    description: str
    content: str = Field(min_length=1, repr=False)

    @field_validator("content")
    @classmethod
    def content_size(cls, content: str) -> str:
        return validate_skill_content_size(content)


class SkillPatch(Patch):
    category_id: UUID | None = None
    name: Text | None = None
    description: str | None = None
    content: str | None = Field(None, min_length=1, repr=False)
    is_active: bool | None = None

    @field_validator("content")
    @classmethod
    def content_size(cls, content: str | None) -> str | None:
        return None if content is None else validate_skill_content_size(content)


class SkillResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    category_id: UUID
    name: str
    description: str
    content: str = Field(repr=False)
    version: int
    content_hash: str
    is_active: bool
    created_at: datetime
    updated_at: datetime
    warnings: list[str] = Field(default_factory=list)
    assigned_agents: list[UUID] = Field(default_factory=list)
    enabled: bool | None = None
    assigned_at: datetime | None = None


class AgentSkillsReplace(Input):
    skill_ids: list[UUID]
    disabled_skill_ids: list[UUID] = Field(default_factory=list)

    @model_validator(mode="after")
    def unique_skills(self):
        if len(set(self.skill_ids)) != len(self.skill_ids):
            raise ValueError("skill_ids должны быть уникальными")
        if not set(self.disabled_skill_ids) <= set(self.skill_ids):
            raise ValueError("Отключать можно только назначенные skills")
        return self
