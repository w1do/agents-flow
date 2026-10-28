from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, SecretStr, StringConstraints, field_validator
from urllib.parse import urlsplit


class HarnessInitRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    project_id: UUID
    init_code: SecretStr = Field(min_length=1)
    agent_name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
    repository_path_hint: str | None = None
    git_remote: str | None = None


class SkillFile(BaseModel):
    skill_id: UUID
    category: str
    name: str
    filename: str
    version: int
    content_hash: str
    content: str
    snapshot_content_missing: bool = False


class HarnessInitResponse(BaseModel):
    agent_id: UUID
    agent_token: str = Field(repr=False)
    server_url: str
    poll_interval_seconds: int = Field(default=5, gt=0)
    lease_ttl_seconds: int = Field(default=60, gt=0)
    skills: list[SkillFile]

    @field_validator("server_url")
    @classmethod
    def validate_server_url(cls, value: str) -> str:
        if value:
            try:
                parsed = urlsplit(value)
                parsed.port
            except ValueError as error:
                raise ValueError("server_url must be a valid HTTP or HTTPS URL") from error
            if parsed.scheme not in {"http", "https"} or not parsed.hostname:
                raise ValueError("server_url must be an HTTP or HTTPS URL")
        return value
