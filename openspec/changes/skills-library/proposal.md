# Proposal: skills-library

> Библиотека skills через MCP. Волна 5 (после MVP), см. PLAN.md.

## Why

Skills должны обновляться у всех агентов без переустановки; источник правды — Postgres (ТЗ §12).

## What Changes

- Таблица `skills` с версиями и хешами, привязка к workspace
- `skills_manifest`, `get_skill` для агента; `list_skills`, `upsert_skill`, `attach_skill`, `delete_skill(confirm)` для оператора
- Агент сверяет манифест при старте и на каждом `report_task`
- Новая версия применяется со следующего этапа
- Уведомление в Telegram о затронутых workspace

## Capabilities

### New Capabilities

- `skills-library`: библиотека skills через mcp.

### Modified Capabilities

Нет.

## Impact

- Зависит от: `sandbox-profile`.
- Ссылки: ТЗ §12, §17 вопросы 13–14.
- Затрагивает ARCHITECTURE.md (разделы по теме) и, при новых инструментах, docs/mcp-agents-flow.md.

## Не входит

- Редактор skills (`console-settings`)
