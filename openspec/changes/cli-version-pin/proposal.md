# Proposal: cli-version-pin

> Закрепление версий CLI агентов. Волна 5 (после MVP), см. PLAN.md.

## Why

Неожиданное обновление `claude` или `codex` ломает формат вывода и флаги (C8).

## What Changes

- Версии CLI в профиле
- Обновление версии — отдельная задача с live-тестом формата `stream-json`

## Capabilities

### New Capabilities

Нет.

### Modified Capabilities

- `sandbox-profile`: добавляются требования (ADDED): Закреплённые версии.

## Impact

- Зависит от: `sandbox-profile`.
- Ссылки: ТЗ §16.1 C8.
- Затрагивает ARCHITECTURE.md (разделы по теме) и, при новых инструментах, docs/mcp-agents-flow.md.

## Не входит

- Автообновление
