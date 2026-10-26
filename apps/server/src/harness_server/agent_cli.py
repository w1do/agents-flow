"""Operator CLI for preparing a local agent machine."""

import asyncio

import typer
from pydantic import ValidationError

from harness_server.adapters.vault import McpSecretVault
from harness_server.config import ConfigError, load_config
from harness_server.services.machine import MachineError, init_project
from harness_server.settings import AgentSettings

app = typer.Typer(
    help="agents-flow agent machine commands", no_args_is_help=True, add_completion=False
)


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
def init(project: str) -> None:
    """Connect PROJECT to this already prepared agents-flow machine."""
    try:
        settings = AgentSettings()  # type: ignore[call-arg]  # populated from process ENV by BaseSettings
        config = load_config(settings.harness_config)
        vault = (
            McpSecretVault(settings.vault_mcp_url, settings.vault_mcp_token)
            if settings.vault_mcp_url and settings.vault_mcp_token
            else None
        )
        asyncio.run(init_project(config, project, vault))
    except ValidationError as exc:
        typer.echo(_safe_validation_error(exc), err=True)
        raise typer.Exit(code=1) from None
    except (MachineError, ConfigError) as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=exc.code if isinstance(exc, MachineError) else 1) from None
