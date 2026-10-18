# Proposal: console-settings

> Консоль: настройки агентов, workspace и песочниц. Волна 6 (после MVP), см. PLAN.md.

## Why

Настройки из `harness.yaml` переезжают в базу и редактируются в консоли (ТЗ §8, D-11).

## What Changes

- Таблицы `workspaces`, `agents`; импорт из `harness.yaml` при первом запуске
- Экраны: агенты, workspace, skills, интеграции, мои MCP, песочницы, профиль
- `list_workspaces`, `get_workspace`, `update_workspace`, `list_agents`, `update_agent`

## Capabilities

### New Capabilities

Нет.

### Modified Capabilities

- `operator-console`: добавляются требования (ADDED): Настройки в базе.

## Impact

- Зависит от: `console-auth`, `sandbox-profile`, `skills-library`, `integrations-mcp-config`.
- Ссылки: ТЗ §8.
- Затрагивает ARCHITECTURE.md (разделы по теме) и, при новых инструментах, docs/mcp-agents-flow.md.

## Не входит

- Мультипользовательский доступ
