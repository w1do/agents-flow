import re
import unicodedata
from urllib.parse import urlsplit

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.schemas.harness import HarnessInitRequest, HarnessInitResponse
from app.services.agent_auth import generate_agent_token
from app.services.init_tokens import consume_init_token

_REMOTE_URL = re.compile(r"^(https|ssh|git)://([^/?#\s]+)(/[^?#\s]+)$")
_SCP_REMOTE = re.compile(r"^[A-Za-z0-9._-]+@[A-Za-z0-9.-]+:.+$")
_AUTHORITY = re.compile(
    r"^(?:[^/@:?#]+(?::[^/@?#]*)?@)?(?:[A-Za-z0-9.-]+|\[[0-9a-fA-F:]+\])(?::[0-9]+)?$"
)


def _validate_git_remote(remote: str) -> None:
    if any(unicodedata.category(char)[0] == "C" for char in remote):
        _remote_error("git_remote contains invalid characters")
    try:
        remote.encode("utf-8")
    except UnicodeEncodeError:
        _remote_error("git_remote contains invalid characters")
    if re.match(r"^[A-Za-z][A-Za-z0-9+.-]*::", remote):
        _remote_error("git_remote must not use remote-helper syntax")
    if remote.startswith("file://"):
        try:
            parsed = urlsplit(remote)
        except ValueError:
            _remote_error("git_remote must be a valid local file URL")
        if (parsed.netloc not in {"", "localhost"} or not parsed.path.startswith("/")
                or parsed.path == "/" or parsed.query or parsed.fragment):
            _remote_error("git_remote must be a local file URL without parameters")
        return
    if remote.startswith(("/", "./", "../")) or (remote and ":" not in remote and not remote.startswith("-")):
        return
    if _SCP_REMOTE.fullmatch(remote):
        return
    match = _REMOTE_URL.fullmatch(remote)
    if not match:
        _remote_error("git_remote must be a valid URL")
    scheme, authority, path = match.groups()
    try:
        if not _AUTHORITY.fullmatch(authority):
            raise ValueError("invalid host")
        parsed = urlsplit(remote)
        if parsed.scheme != scheme or not parsed.hostname or not path.strip("/"):
            raise ValueError("invalid remote")
        if parsed.query or parsed.fragment or parsed.password is not None:
            raise ValueError("invalid remote credentials or parameters")
        if scheme == "https" and parsed.username is not None:
            raise ValueError("HTTPS userinfo is forbidden")
        if scheme == "ssh" and parsed.password is not None:
            raise ValueError("SSH passwords are forbidden")
        if parsed.port is not None and parsed.port > 65535:
            raise ValueError("invalid port")
    except ValueError as error:
        _remote_error("git_remote must be a valid URL without credentials or parameters")


def _remote_error(message: str) -> None:
    raise HTTPException(422, detail=[{
        "loc": ["body", "git_remote"], "msg": message, "type": "value_error",
    }])


def initialize_harness(session: Session, body: HarnessInitRequest) -> HarnessInitResponse:
    if body.git_remote:
        _validate_git_remote(body.git_remote)
    plain_token, token_hash = generate_agent_token()
    with session.begin_nested():
        agent = consume_init_token(
            session, body.init_code.get_secret_value(), body.project_id,
            agent_name=body.agent_name, agent_token_hash=token_hash,
            repository_path_hint=body.repository_path_hint or "", git_remote=body.git_remote or "",
        )
        skills = []
        response = HarnessInitResponse(
            agent_id=agent.id, agent_token=plain_token,
            server_url=get_settings().public_base_url,
            poll_interval_seconds=get_settings().poll_interval_seconds,
            lease_ttl_seconds=get_settings().lease_ttl_seconds,
            skills=skills,
        )
    session.commit()
    return response
