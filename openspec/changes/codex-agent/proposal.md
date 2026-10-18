# Proposal: codex-agent

> Второй тип агента: Codex. Волна 5 (после MVP), см. PLAN.md.

## Why

ТЗ предусматривает второй агент; Codex по-другому находит skills и конфиг (вопрос 13).

## What Changes

- Тип агента `codex` в конфиге, команда запуска и разбор вывода
- `AGENTS.md` и `config.toml` в bootstrap
- Skills для Codex через `get_skill`, если он не подгружает их сам

## Capabilities

### New Capabilities

Нет.

### Modified Capabilities

- `sandbox-runtime`: добавляются требования (ADDED): Запуск агента по типу.

## Impact

- Зависит от: `sandbox-pool`, `skills-library`.
- Ссылки: ТЗ §16 п.9, §17 вопрос 13.
- Затрагивает ARCHITECTURE.md (разделы по теме) и, при новых инструментах, docs/mcp-agents-flow.md.

## Не входит

- Кастомные агенты
