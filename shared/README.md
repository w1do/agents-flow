# shared — общие модели (`harness_shared`)

Pydantic-модели, которые видят внешние потребители: API, MCP, консоль. Сервер импортирует их
отсюда, дубли в `apps/server` не допускаются.

## Состав

| Модуль | Модели |
|---|---|
| `harness_shared/health.py` | `HealthResponse` (`status: "ok"`), `ReadyResponse` (`status: "ready" \| "unavailable"`, `database: bool`) |
| `harness_shared/tasks.py` | Перечисления `TaskKind`, `TaskStatus`, `TaskSource`, `TaskEventSource`, `TestsState`; DTO `TaskCreateIn`, `TaskOut`, `TaskEventOut`, `TaskDetailOut` |
| `harness_shared/sandboxes.py` | Перечисления `SandboxStatus`, `AgentRole` |

## Использование

Пакет подключён к workspace как зависимость `harness-shared` в `apps/server/pyproject.toml`.
Установка и проверка типов выполняются из корня:

```bash
uv sync
uv run mypy apps shared
```

Новая модель, которую видит внешний мир, добавляется сюда, а не в `apps/server`.
