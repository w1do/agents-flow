# Proposal: integrations-mcp-config

> Интеграции и MCP-серверы. Волна 5 (после MVP), см. PLAN.md.

## Why

Workspace подключают внешние системы (CRM и др.) и свои MCP-серверы; ключи только ссылками (ТЗ §12).

## What Changes

- Таблицы `integrations` (имя, API URL, `key_ref`, инструкция, actions) и `mcp_servers` (ключ → значение, секреты ссылками)
- `get_mcp_config` для агента; `list_integrations`, `upsert_integration`, `list_mcp`, `set_mcp_value`, `delete_mcp_value`
- Подстановка значений секретов только в env при активации

## Capabilities

### New Capabilities

- `integrations`: интеграции и mcp-серверы.

### Modified Capabilities

Нет.

## Impact

- Зависит от: `skills-library`.
- Ссылки: ТЗ §12 (интеграции), §11 (интеграции и MCP).
- Затрагивает ARCHITECTURE.md (разделы по теме) и, при новых инструментах, docs/mcp-agents-flow.md.

## Не входит

- Внешнее хранилище секретов (Vault) — отдельное решение
