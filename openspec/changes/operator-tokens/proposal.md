# Proposal: operator-tokens

> Операторские токены и журнал вызовов. Волна 2 (после MVP), см. PLAN.md.

## Why

Telegram, консоль и внешние MCP-клиенты должны работать через MCP с отзываемыми токенами и скоупами, а все вызовы — попадать в журнал с источником (ТЗ §11, §14).

## What Changes

- Таблица `operator_tokens` (хеш, скоупы `read`/`operate`/`admin`, источник, отзыв)
- Таблица `audit_log`: инструмент, источник, субъект, результат, время
- CLI `harness-server token create|revoke|list`
- Замена временного `HARNESS_ADMIN_TOKEN`

## Capabilities

### New Capabilities

Нет.

### Modified Capabilities

- `agents-flow-mcp`: добавляются требования (ADDED): Скоупы операторского токена, Журнал вызовов.

## Impact

- Зависит от: `mvp-07-agents-flow-mcp`.
- Ссылки: ТЗ §11 (два вида доступа), §14.
- Затрагивает ARCHITECTURE.md (разделы по теме) и, при новых инструментах, docs/mcp-agents-flow.md.

## Не входит

- UI выдачи токенов (`console-settings`)
