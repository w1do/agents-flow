from functools import lru_cache
from threading import Lock
from uuid import UUID

from jwt import InvalidTokenError
from sqlalchemy.exc import IntegrityError
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.core.errors import unauthorized
from app.core.security import create_access_token, decode_token, hash_password, verify_password
from app.models.user import User
from app.repositories.user import UserRepository

_bootstrap_lock = Lock()


def validate_admin_password(password: str) -> str:
    if len(password) < 12 or not password.strip() or len(password.encode("utf-8")) > 72:
        raise ValueError("Administrator password must contain at least 12 characters and at most 72 UTF-8 bytes.")
    return password


def ensure_initial_admin(session: Session, settings: Settings | None = None) -> None:
    settings = settings or get_settings()
    with _bootstrap_lock:
        dialect = session.get_bind().dialect.name
        if dialect == "sqlite":
            connection = session.connection()
            raw_connection = connection.connection.driver_connection
            if not raw_connection.in_transaction:
                connection.exec_driver_sql("BEGIN IMMEDIATE")
        elif dialect == "postgresql":
            session.execute(text("SELECT pg_advisory_xact_lock(7319042281)"))
        users = UserRepository(session)
        password = settings.admin_password.get_secret_value() if settings.admin_password else ""
        if users.has_users() or not settings.admin_email or not password:
            return
        validate_admin_password(password)
        try:
            with session.begin_nested():
                users.create(email=settings.admin_email, password_hash=hash_password(password))
        except IntegrityError:
            session.expire_all()
            if not UserRepository(session).has_users():
                raise


@lru_cache(maxsize=1)
def _dummy_password_hash() -> str:
    return hash_password("invalid credentials")


def login(session: Session, email: str, password: str) -> str:
    user = UserRepository(session).by_email(email)
    hashed = user.password_hash if user else _dummy_password_hash()
    if not verify_password(password, hashed) or user is None:
        raise unauthorized()
    return create_access_token(str(user.id))


def authenticate_admin(session: Session, token: str) -> User | None:
    try:
        subject = UUID(decode_token(token)["sub"])
    except (InvalidTokenError, ValueError, TypeError, KeyError):
        return None
    return UserRepository(session).get(subject)
