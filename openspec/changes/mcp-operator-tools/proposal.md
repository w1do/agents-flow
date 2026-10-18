# Proposal: mcp-operator-tools

> Операторские инструменты задач и спецификации. Волна 2 (после MVP), см. PLAN.md.

## Why

Всё, что можно сделать с задачей, должно быть инструментом MCP (ТЗ §2 п.5). Telegram и консоль используют их вместо собственных путей.

## What Changes

- `create_task`, `get_task`, `choose_workspace`, `retry_task`, `set_task_priority`, `task_history`, `agent_status`
- `stop_task` с `confirm=true`
- `list_spec`, `sync_spec` для оператора
- Telegram-обработчики переходят на эти инструменты через сервисы

## Capabilities

### New Capabilities

Нет.

### Modified Capabilities

- `agents-flow-mcp`: добавляются требования (ADDED): Опасные инструменты требуют подтверждения, Управление задачами оператором.

## Impact

- Зависит от: `operator-tokens`.
- Ссылки: ТЗ §11 (операторские инструменты: задачи, спецификация).
- Затрагивает ARCHITECTURE.md (разделы по теме) и, при новых инструментах, docs/mcp-agents-flow.md.

## Не входит

- Инструменты песочниц (`sandbox-pool`), skills, интеграций, профиля
