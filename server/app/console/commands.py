from argparse import Namespace
from getpass import GetPassWarning, getpass
import sys
import warnings

from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.security import hash_password
from app.repositories.user import UserRepository
from app.schemas.auth import LoginRequest
from app.schemas.projects import ProjectCreate
from app.schemas.skills import CategoryCreate
from app.services.projects import create_project
from app.services.auth import validate_admin_password
from app.services.skills import category_save
from app.console.starter import seed_skills


def create_admin(session: Session, email: str | None) -> str:
    settings = get_settings()
    email = (email or settings.admin_email or "").strip()
    if not email:
        raise ValueError("Provide --email or ADMIN_EMAIL with a valid email address.")
    users = UserRepository(session)
    existing = users.by_email(email)
    if existing:
        return f"Administrator already exists: {existing.id}"
    if settings.admin_password and settings.admin_password.get_secret_value():
        password = settings.admin_password.get_secret_value()
    else:
        if not sys.stdin.isatty() or not sys.stderr.isatty():
            raise ValueError("Set ADMIN_PASSWORD or run this command from an interactive terminal.")
        with warnings.catch_warnings():
            warnings.simplefilter("error", GetPassWarning)
            try:
                password = getpass("Administrator password: ")
            except GetPassWarning as error:
                raise ValueError("Hidden password input is unavailable; set ADMIN_PASSWORD instead.") from error
    validate_admin_password(password)
    credentials = LoginRequest(email=email, password=password)
    user = users.create(email=credentials.email, password_hash=hash_password(password))
    return f"Administrator created: {user.id}"


def execute(session: Session, args: Namespace) -> str:
    if args.command == "create-admin":
        return create_admin(session, args.email)
    if args.command == "create-project":
        project = create_project(session, ProjectCreate(
            name=args.name, description=args.description, telegram_chat_id=args.telegram_chat_id,
        ))
        return f"Project created: {project.id}"
    if args.command == "create-category":
        category = category_save(session, CategoryCreate(
            name=args.name, description=args.description, sort_order=args.sort_order,
        ))
        return f"Category created: {category.id}"
    return seed_skills(session)
