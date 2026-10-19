# Proposal: mvp-07-agents-flow-mcp

> Критерий приёмки владельца (D-56, 2026-10-19): после реализации агент коммитит сам и вызывает «сдать работу»;
> push ветки `task/<id>`, MR и сообщение в Telegram делает харнесс после гейтов. Ключ записи агенту не выдаётся.


## Why

Агент в песочнице отчитывается и создаёт задачи только через MCP `agents-flow` (ТЗ §2 п.5, §11). Для среза нужны
`report_task`, `sync_spec`, `create_task` и токен задачи (ТЗ §16.0 п.6, п.8; риск A2). Без этого планировщик не может
передать работу исполнителю, а сервер — узнать этапы.

## What Changes

- MCP-сервер `agents-flow` на официальном Python SDK, Streamable HTTP, смонтирован в FastAPI на `/mcp` (D-09).
- Авторизация `Authorization: Bearer <токен задачи>`: поиск по хешу, проверка срока и отзыва, контекст
  `{task_id, workspace_id, role}` для инструмента.
- Инструменты: `report_task`, `sync_spec` (planner), `create_task` (planner, только `implement` в `backlog` своего
  workspace), `list_tasks` (чтение своего workspace). Логика — в `services/` (`tasks`, `spec`).
- `services/spec.py`: upsert `spec_items` по (`workspace_id`, `change_id`, `key`).
- Единый формат ошибок MCP: `unauthorized`, `forbidden`, `invalid_input`, `invalid_transition`.
- Каждый вызов пишет `task_events` с `source=agent`; тексты проходят redaction.

## Capabilities

### New Capabilities

- `agents-flow-mcp`: MCP-интерфейс агента, токены задачи, права ролей.

### Modified Capabilities

Нет.

## Impact

- Зависимости: `mcp` (официальный SDK).
- Зависит от: `mvp-03-task-store`, `mvp-06-sandbox-runtime` (выдача токена).
- Публичный HTTPS `/mcp` через Dokploy, доступный из Novita (A2, проверено в `mvp-01`).
- Ссылки: ТЗ §11 (MVP-часть), §14, §16.1 A2.

## Не входит

Операторский токен и скоупы (`operator-tokens`), остальные инструменты (`mcp-operator-tools`, `checkpoints`, …),
журнал вызовов с источником для внешних клиентов.
