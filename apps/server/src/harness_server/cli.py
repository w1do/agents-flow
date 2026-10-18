"""Команды harness-server. Тонкий вход: проверяет ENV и конфиг, затем вызывает модули сервера."""

import asyncio
import logging
import os
from pathlib import Path

import typer
import uvicorn
from alembic import command as alembic_command
from alembic.config import Config as AlembicConfig

from harness_server.app import create_app
from harness_server.config import ConfigError, HarnessConfig, load_config
from harness_server.settings import Settings, SettingsError, load_settings
from harness_server.worker import serve_worker

app = typer.Typer(
    help="agents-flow harness: сервер, worker, миграции, проверка конфигурации.",
    no_args_is_help=True,
    add_completion=False,
)


def _configure_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )


def _load_or_exit() -> tuple[Settings, HarnessConfig]:
    """Проверяет ENV и harness.yaml до старта. При ошибке печатает причину и выходит с кодом 1."""
    try:
        settings = load_settings()
        config = load_config(settings.harness_config)
    except (SettingsError, ConfigError) as exc:
        typer.echo(f"Ошибка конфигурации: {exc}", err=True)
        raise typer.Exit(code=1) from None
    return settings, config


@app.command()
def serve(host: str = "127.0.0.1", port: int = 8000) -> None:
    """Запускает HTTP-сервер (health и далее webhook, MCP) через uvicorn.

    По умолчанию слушает только localhost; в контейнере адрес задаётся явно: --host 0.0.0.0.
    """
    settings, config = _load_or_exit()
    _configure_logging()
    uvicorn.run(create_app(settings, config), host=host, port=port)


@app.command()
def worker() -> None:
    """Запускает worker: цикл опроса очереди, корректная остановка по SIGTERM."""
    settings, _ = _load_or_exit()
    _configure_logging()
    asyncio.run(serve_worker(settings.worker_poll_interval_sec))


@app.command()
def migrate(alembic_config: Path = Path("alembic.ini")) -> None:
    """Применяет миграции Alembic до head. Нужна переменная DATABASE_URL."""
    # env.py читает DATABASE_URL напрямую из окружения, поэтому проверяем её здесь,
    # чтобы не получить трассировку Alembic вместо понятного сообщения.
    if not os.environ.get("DATABASE_URL"):
        typer.echo("Ошибка конфигурации: DATABASE_URL: не задан", err=True)
        raise typer.Exit(code=1)
    _configure_logging()
    alembic_command.upgrade(AlembicConfig(str(alembic_config)), "head")


@app.command("check-config")
def check_config() -> None:
    """Проверяет ENV и harness.yaml и печатает список workspace."""
    _, config = _load_or_exit()
    for workspace in config.workspaces:
        typer.echo(f"{workspace.id} — {workspace.name}")
