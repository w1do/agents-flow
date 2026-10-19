# Proposal: skills-library

> Библиотека skills и агентов Claude через MCP. Волна 5 (после MVP), см. PLAN.md. Агенты — решение владельца
> 2026-10-19 (D-49).

## Why

Skills должны обновляться у всех агентов без переустановки; источник правды — Postgres (ТЗ §12). Владелец также
создаёт на платформе своих агентов Claude (субагенты: имя, описание задач, prompt, модель, инструменты); они
синхронизируются тем же механизмом.

## What Changes

- Таблица `skills` с версиями и хешами, привязка к workspace; колонка `kind` (`skill` | `agent`, VARCHAR(16) + CHECK,
  D-22). Тело записи — полный текст файла: для `skill` — `SKILL.md`, для `agent` — `<name>.md` (frontmatter `name`,
  `description`, необязательные `model`, `tools`, затем prompt). Сервер проверяет frontmatter при записи: `name`
  совпадает с именем записи, `description` не пуст
- `skills_manifest`, `get_skill` для агента возвращают записи обоих видов с полем `kind`; `list_skills(kind?)`,
  `upsert_skill(kind=…)`, `attach_skill`, `delete_skill(confirm)` для оператора. Отдельных инструментов для агентов нет:
  имена `list_agents`/`update_agent` в ТЗ §11 заняты ролями планировщика и исполнителя
- Агент сверяет манифест при старте и на каждом `report_task`; файлы кладёт в `~/.claude/skills/<name>/SKILL.md`
  (`skill`) и `~/.claude/agents/<name>.md` (`agent`) — каталоги готовит `sandbox-profile`
- Новая версия применяется со следующего этапа
- Уведомление в Telegram о затронутых workspace

## Capabilities

### New Capabilities

- `skills-library`: библиотека skills и агентов Claude через MCP.

### Modified Capabilities

Нет.

## Impact

- Зависит от: `sandbox-profile`, `mvp-07-agents-flow-mcp`.
- Ссылки: ТЗ §12, §17 вопросы 13–14; D-48, D-49.
- Затрагивает ARCHITECTURE.md (разделы по теме) и, при новых инструментах, docs/mcp-agents-flow.md.

## Не входит

- Редактор skills (`console-settings`)
