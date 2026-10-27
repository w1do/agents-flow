from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import get_settings
from app.models import Base

url = make_url(get_settings().database_url)
connect_args = {}
if url.get_backend_name() == "postgresql":
    connect_args = {"connect_timeout": 5, "options": "-c statement_timeout=5000"}
engine = create_engine(url, pool_pre_ping=True, hide_parameters=True, connect_args=connect_args)
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)


def get_db() -> Generator[Session, None, None]:
    with SessionLocal() as session:
        yield session


__all__ = ["Base", "engine", "SessionLocal", "get_db"]
