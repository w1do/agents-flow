"""Команды harness-server. Тонкий вход: проверяет ENV и конфиг, затем вызывает модули сервера."""

import asyncio
import logging
import os
from collections.abc import Awaitable, Callable
from pathlib import Path

import typer
import uvicorn
from alembic import command as alembic_command
from alembic.config import Config as AlembicConfig
from sqlalchemy.ext.asyncio import AsyncSession

from harness_server import wiring
from harness_server.adapters.sandbox import SandboxError, SandboxProvider
from harness_server.adapters.telegram import TelegramError
from harness_server.app import create_app
from harness_server.config import ConfigError, HarnessConfig, load_config
from harness_server.db.session import create_engine, create_session_factory
from harness_server.services import sandboxes
from harness_server.services.projects import list_workspaces
from harness_server.services.webhook import register_webhook, webhook_url
from harness_server.settings import Settings, SettingsError, load_settings
from harness_server.worker import serve_worker
from harness_server.worker.settings import load_worker_settings

# Корень приложения: uv ставит workspace editable, поэтому cli.py лежит в
# <root>/apps/server/src/harness_server/ и в репозитории, и в образе (/app). Путь не зависит от cwd:
# терминал Dokploy открывается в / (bootstrap-in-image, D-63).

app = typer.Typer(
    help="agents-flow harness: сервер, worker, миграции, проверка конфигурации.",
    no_args_is_help=True,
    add_completion=False,
)
telegram_app = typer.Typer(help="Telegram: регистрация webhook.", no_args_is_help=True)
app.add_typer(telegram_app, name="telegram")
sandbox_app = typer.Typer(
    help="Песочница: пауза, возобновление, статус; проект подключается agent init <project>.",
    no_args_is_help=True,
)
app.add_typer(sandbox_app, name="sandbox")


def _configure_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    # В URL запроса к Bot API — токен бота: на INFO httpx и httpcore записали бы его в лог.
    for name in ("httpx", "httpcore"):
        logging.getLogger(name).setLevel(logging.WARNING)


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
    """Запускает worker с ENV машины агента и HARNESS_CONFIG, без настроек сервера."""
    try:
        settings = load_worker_settings()
        config = load_config(settings.harness_config)
    except (SettingsError, ConfigError) as exc:
        typer.echo(f"Ошибка конфигурации: {exc}", err=True)
        raise typer.Exit(code=1) from None
    _configure_logging()
    asyncio.run(serve_worker(settings, config))


@app.command()
def migrate(alembic_config: Path = Path("alembic.ini")) -> None:
    """Применяет миграции Alembic до head. Нужна переменная DATABASE_URL."""
    # env.py читает DATABASE_URL напрямую; миграциям не нужны ENV HTTP-сервера и worker.
    if not os.environ.get("DATABASE_URL"):
        typer.echo("Ошибка конфигурации: DATABASE_URL: не задан", err=True)
        raise typer.Exit(code=1)
    _configure_logging()
    alembic_command.upgrade(AlembicConfig(str(alembic_config)), "head")


@app.command("check-config")
def check_config() -> None:
    """Проверяет ENV и harness.yaml и печатает активные проекты из каталога на сервере."""
    settings, _ = _load_or_exit()
    _configure_logging()
    workspaces = asyncio.run(_with_session(settings, list_workspaces))
    for workspace in workspaces:
        typer.echo(f"{workspace.id} — {workspace.name}")


async def _set_webhook(settings: Settings, url: str) -> None:
    """Регистрирует webhook через адаптер Telegram из общей сборки адаптеров."""
    async with wiring.build_http_client() as http:
        adapters = wiring.build_adapters(settings, http)
        await register_webhook(
            adapters.telegram, url, settings.telegram_webhook_secret.get_secret_value()
        )


@telegram_app.command("set-webhook")
def set_webhook() -> None:
    """Регистрирует webhook: адрес из HARNESS_PUBLIC_URL, секрет из TELEGRAM_WEBHOOK_SECRET."""
    settings, _ = _load_or_exit()
    _configure_logging()
    # TELEGRAM_WEBHOOK_URL — адрес прокси владельца (D-61); без него берём HARNESS_PUBLIC_URL.
    if settings.telegram_webhook_url is not None:
        url = settings.telegram_webhook_url
    else:
        try:
            url = webhook_url(settings.harness_public_url)
        except ValueError as exc:
            typer.echo(f"Ошибка конфигурации: HARNESS_PUBLIC_URL: {exc}", err=True)
            raise typer.Exit(code=1) from None
    try:
        asyncio.run(_set_webhook(settings, url))
    except TelegramError as exc:
        # В сообщении TelegramError нет URL и токена; секрет webhook сюда не попадает.
        typer.echo(f"Ошибка Telegram: {exc}", err=True)
        raise typer.Exit(code=1) from None
    typer.echo(f"webhook установлен: {url}")


async def _with_session[T](settings: Settings, action: Callable[[AsyncSession], Awaitable[T]]) -> T:
    """Одна сессия БД на команду; engine закрывается при выходе."""
    engine = create_engine(settings.database_url.get_secret_value())
    try:
        async with create_session_factory(engine)() as session:
            return await action(session)
    finally:
        await engine.dispose()


def _run_sandbox_action(
    settings: Settings,
    config: HarnessConfig,
    action: Callable[[AsyncSession, SandboxProvider], Awaitable[None]],
    *,
    done: str,
) -> None:
    """Выполняет действие над песочницей и печатает итог. Отказы сервиса — код выхода 1."""
    provider = wiring.build_sandbox_provider(settings, config.sandbox.provider_id)

    async def run(session: AsyncSession) -> None:
        # Строка песочницы может отсутствовать, если worker ещё не стартовал (design 8).
        await sandboxes.ensure_sandbox(session, config)
        await action(session, provider)

    try:
        asyncio.run(_with_session(settings, run))
    except sandboxes.SandboxBusy as exc:
        typer.echo(f"Ошибка: песочница занята задачей {exc.task_id}", err=True)
        raise typer.Exit(code=1) from None
    except (SandboxError, sandboxes.SandboxStepError) as exc:
        # Текст исключений провайдера не печатаем: в нём может быть вывод песочницы.
        reason = exc.reason if isinstance(exc, sandboxes.SandboxStepError) else type(exc).__name__
        typer.echo(f"Ошибка песочницы: {reason}", err=True)
        raise typer.Exit(code=1) from None
    typer.echo(done)


@sandbox_app.command("status")
def sandbox_status_command() -> None:
    """Строка песочницы из конфига: статус и закреплённая задача."""
    settings, config = _load_or_exit()
    _configure_logging()
    provider_id = config.sandbox.provider_id
    row = asyncio.run(_with_session(settings, lambda s: sandboxes.sandbox_status(s, provider_id)))
    if row is None:
        typer.echo(f"{provider_id}: строки нет, worker создаст её при старте")
        return
    task = "-" if row.current_task_id is None else str(row.current_task_id)
    typer.echo(f"{provider_id}: статус={row.status} задача={task}")


@sandbox_app.command("pause")
def sandbox_pause() -> None:
    """Пауза песочницы. Отказывает, если за ней закреплена задача."""
    settings, config = _load_or_exit()
    _configure_logging()
    provider_id = config.sandbox.provider_id
    _run_sandbox_action(
        settings,
        config,
        lambda s, p: sandboxes.pause_sandbox(s, p, provider_id),
        done="песочница на паузе",
    )


@sandbox_app.command("resume")
def sandbox_resume() -> None:
    """Возобновление песочницы; после успешного connect статус error сбрасывается в paused."""
    settings, config = _load_or_exit()
    _configure_logging()
    provider_id = config.sandbox.provider_id
    _run_sandbox_action(
        settings,
        config,
        lambda s, p: sandboxes.resume_sandbox(s, p, provider_id),
        done="песочница возобновлена",
    )
