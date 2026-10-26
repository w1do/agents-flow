# Proposal: integrations-mcp-config

> **Уточнение после `local-agent-machine`:** базовый `~/.harness/mcp.json` живёт на постоянной
> машине и создаётся `agent init`, а не bootstrap. Реестр, vault-ссылки, плейсхолдеры, CLI и
> генерация конфигурации при запуске агента остаются будущим объёмом этого изменения; динамическая
> генерация не отменена.

> Раздел MCP на платформе и генерация MCP-конфига агента. Решение владельца 2026-10-19: делается сразу после
> `sandbox-profile`, до `mvp-07-agents-flow-mcp` (D-43, D-46). Интеграции CRM из ТЗ §12 сюда не входят.

## Open questions (нужен ответ владельца)

1. **Публичный адрес MCP preferences** (сейчас на localhost владельца, из песочницы недоступен) и его авторизация. Пока
   адреса нет, сервер preferences в раздел MCP не добавляется.
2. **Адрес vault MCP для агента** и ссылка на ключ агента в vault (заголовок `Authorization` строки `vault` раздела MCP).
   Адрес и авторизация vault для сервера — открытый вопрос `sandbox-profile`.

## Why

Агенту нужны MCP-серверы владельца (vault, preferences и другие), а ключи к ним лежат в vault (ТЗ §11, §12). Раздел
MCP должен жить на платформе (Postgres), а не в файлах песочницы, и попадать к агенту при каждом запуске без
переустановки.

## What Changes

- Таблица `mcp_servers` (миграция `0005`): `name` (уникально), `description`, `transport` (`http` | `sse` | `stdio`),
  `url` или `command` + `args`, `env` и `headers` (JSON). Значение в `env`/`headers` — обычный текст или ссылка
  `vault:<project>/<service>/<name>` (допускается текстовый префикс через пробел: `Bearer vault:…`). Секреты в БД не
  хранятся. Раздел глобальный, без привязки к workspace.
- `services/mcp_servers.py`: добавление, список, просмотр, удаление; сборка конфига агента: ссылки разворачиваются
  через vault, значения уходят в env агента, в конфиге — плейсхолдеры `${HARNESS_MCP_<i>_<j>}`.
- Адаптер формата `McpConfigFormat` (Protocol) с реализацией для Claude Code; Codex и Junie — только интерфейс.
- Рантайм (изменение `sandbox-runtime`): `run_agent` при каждом запуске пишет `~/.harness/mcp.json` из раздела MCP,
  встроенного `project-memory` (если память включена) и `agents-flow`; флаги `claude -p` прежние, изоляция сохранена.
- CLI до консоли: `harness-server mcp add|list|show|remove` (тонкий вход, логика в `services/`).

## Capabilities

### New Capabilities

- `integrations`: раздел MCP-серверов платформы и конфиг MCP агента.

### Modified Capabilities

- `sandbox-runtime`: MCP-конфигурация харнесса генерируется сервером при каждом запуске агента.

## Impact

- Зависит от: `sandbox-profile` (vault-адаптер, `services/secrets.py`, `extra_envs`, `HARNESS_MEMORY_PROJECT`).
  Архивировать после `mvp-06` и `sandbox-profile`.
- Миграция `0005` (новая таблица, без изменения существующих).
- Документация: ARCHITECTURE.md (§3 таблица, §7, §9), docs/decisions.md (D-46), docs/deployment.md, PLAN.md.

## Не входит

- Интеграции CRM (таблица `integrations`, `upsert_integration`) — отдельное изменение при необходимости.
- MCP-инструменты `get_mcp_config`, `list_mcp`, `set_mcp_value`, `delete_mcp_value`: им нужен MCP-сервер (`mvp-07`) и
  операторские токены (`operator-tokens`). Агент получает конфиг файлом при запуске, оператор — через CLI.
- Привязка MCP к workspace: добавляется таблицей `workspace_mcp_servers` без изменения `mcp_servers`, когда понадобится.
- Страница раздела MCP — `mvp-10-operator-console` / консоль.
- Реализация форматов Codex и Junie.
