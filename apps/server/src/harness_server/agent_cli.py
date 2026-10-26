"""Operator CLI for preparing a local agent machine: `agent init <workspace>` (D-65).

Настройки проекта берутся с сервера по id, локальный конфиг пишется в ~/.harness/projects/<id>.yaml
и только потом идёт подготовка клона. Адрес сервера и токен оператора — из ENV, не из файлов.
"""

import asyncio
import re

import typer
from harness_shared.projects import PROJECT_ID_PATTERN
from pydantic import ValidationError

from harness_server.adapters.harness_api import HarnessApiError, fetch_project_settings
from harness_server.adapters.vault import McpSecretVault
from harness_server.config import ConfigError, load_config
from harness_server.services.machine import (
    MachineError,
    RootUserError,
    init_project,
    require_non_root,
    write_project_config,
)
from harness_server.settings import AgentSettings

app = typer.Typer(
    help="agents-flow agent machine commands", no_args_is_help=True, add_completion=False
)

# Коды выхода: 1 — отказ сервера или подготовки, 2 — проект не найден на сервере (как неизвестный
# проект в MachineError), 3 — не хватает инструментов (MachineError из check_prerequisites).
_EXIT_NOT_FOUND = 2


def _safe_validation_error(exc: ValidationError) -> str:
    """Formats only field names and validator messages, never rejected ENV input values."""
    fields = ", ".join(
        ".".join(str(part) for part in error["loc"]).upper() for error in exc.errors()
    )
    return f"Ошибка конфигурации agent: проверьте ENV {fields}"


@app.callback()
def agent() -> None:
    """agents-flow commands for the owner-managed agent machine."""


@app.command()
def init(workspace: str) -> None:
    """Подключает проект WORKSPACE с сервера к этой машине агента."""
    if re.fullmatch(PROJECT_ID_PATTERN, workspace) is None:
        typer.echo("Ошибка: идентификатор проекта — латиница, цифры и дефисы", err=True)
        raise typer.Exit(code=1)
    try:
        settings = AgentSettings()  # type: ignore[call-arg]  # populated from process ENV by BaseSettings
        if settings.harness_public_url is None or settings.harness_admin_token is None:
            typer.echo(
                "Ошибка конфигурации agent: нужны ENV HARNESS_PUBLIC_URL и HARNESS_ADMIN_TOKEN",
                err=True,
            )
            raise typer.Exit(code=1)
        config = load_config(settings.harness_config)
        require_non_root()
        project = asyncio.run(
            fetch_project_settings(
                settings.harness_public_url,
                settings.harness_admin_token.get_secret_value(),
                workspace,
            )
        )
        write_project_config(project)
        vault = (
            McpSecretVault(settings.vault_mcp_url, settings.vault_mcp_token)
            if settings.vault_mcp_url and settings.vault_mcp_token
            else None
        )
        asyncio.run(init_project(config, project, vault))
    except ValidationError as exc:
        typer.echo(_safe_validation_error(exc), err=True)
        raise typer.Exit(code=1) from None
    except HarnessApiError as exc:
        typer.echo(f"Ошибка сервера: {exc.reason}", err=True)
        raise typer.Exit(code=_EXIT_NOT_FOUND if exc.code == "not_found" else 1) from None
    except RootUserError:
        typer.echo("Ошибка: нужен отдельный пользователь без root", err=True)
        raise typer.Exit(code=1) from None
    except (MachineError, ConfigError) as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=exc.code if isinstance(exc, MachineError) else 1) from None
