"""Validate Git assertions without granting them server verification authority."""
from pathlib import PurePosixPath
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, TypeAdapter, field_validator

from app.schemas.payload_limits import bounded_payload
from app.services.protected_paths import redact_paths, sensitive

Sha = Annotated[str, StringConstraints(strict=True, pattern=r"^[0-9a-fA-F]{40}$")]
Path = Annotated[str, StringConstraints(strict=True, min_length=1, max_length=4096)]
sha_adapter = TypeAdapter(Sha | None)


def relative_path(value):
    parts = PurePosixPath(value).parts
    if (not parts or value.startswith("/") or "\\" in value or ":" in value or "\0" in value
            or ".." in parts or any(sensitive(p) for p in parts)):
        raise ValueError("Forbidden Git claim path")
    return value


class ClaimModel(BaseModel):
    model_config = ConfigDict(extra="ignore", strict=True)


class CommitClaim(ClaimModel):
    sha: Sha
    subject: Annotated[str, StringConstraints(max_length=200)] | None = None

    @field_validator("subject")
    @classmethod
    def safe_subject(cls, value):
        return redact_paths(value)[:200] if value is not None else None


class StatusClaim(ClaimModel):
    code: Annotated[str, StringConstraints(pattern=r"^[ MADRCUT?!]{1,2}$")]
    path: Path
    ignored: bool = False

    _path = field_validator("path")(relative_path)


class GitClaims(ClaimModel):
    source: Literal["agent_reported"] = "agent_reported"
    base_sha: Sha | None = None
    head_sha: Sha | None = None
    commits: Annotated[list[Sha | CommitClaim], Field(max_length=100)] = []
    status: Annotated[list[StatusClaim], Field(max_length=10000)] = []
    diff_name_only: Annotated[list[Path], Field(max_length=10000)] = []
    worktree_clean: bool | None = None
    index_conflict: bool | None = None
    stale_index: bool | None = None
    cleanup_failed: bool | None = None

    @field_validator("diff_name_only")
    @classmethod
    def paths(cls, values):
        return [relative_path(value) for value in values]


def git_claims(data):
    """Keep application result fields; whitelist every field inside Git claims."""
    if data is None:
        return None
    bounded_payload(data)
    data = dict(data)
    if "commit_sha" in data:
        data["commit_sha"] = sha_adapter.validate_python(data["commit_sha"])
    if "changed_paths" in data:
        paths = TypeAdapter(Annotated[list[Path], Field(max_length=1000)]).validate_python(
            data["changed_paths"], strict=True)
        data["changed_paths"] = [relative_path(path) for path in paths]
    if "commit_subject" in data:
        subject = TypeAdapter(Annotated[str, StringConstraints(strict=True, max_length=200)] | None)
        value = subject.validate_python(data["commit_subject"])
        data["commit_subject"] = redact_paths(value)[:200] if value is not None else None
    verification = data.pop("verification", None)
    claims = data.pop("claims", None)
    if verification is not None or claims is not None:
        value = verification if verification is not None else claims
        # Caller-provided provenance never changes the trust boundary.
        if isinstance(value, dict):
            value = dict(value, source="agent_reported")
        parsed = GitClaims.model_validate(value)
        data["claims"] = parsed.model_dump(exclude_unset=True) | {"source": "agent_reported"}
    return data
