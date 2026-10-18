# Proposal: task-pause-resume

> Пауза и возобновление задачи. Волна 3 (после MVP), см. PLAN.md.

## Why

Задачу нужно уметь остановить без потери работы и продолжить с места остановки (ТЗ §5.1).

## What Changes

- `pause_task`: остановка агента, чекпоинт, WIP-коммит незакоммиченного в `task/<id>` и push, стирание кредов, статус `paused`, worktree остаётся
- `resume_task`: resume песочницы, `git fetch`, новые креды, агент продолжает с чекпоинта
- Переходы `active→paused`, `paused→active`

## Capabilities

### New Capabilities

Нет.

### Modified Capabilities

- `task-lifecycle`: добавляются требования (ADDED): Пауза без потери работы, Продолжение с чекпоинта.

## Impact

- Зависит от: `checkpoints`.
- Ссылки: ТЗ §5.1 (что значит пауза), §17 вопрос 11.
- Затрагивает ARCHITECTURE.md (разделы по теме) и, при новых инструментах, docs/mcp-agents-flow.md.

## Не входит

- Пауза всей песочницы с несколькими задачами (`sandbox-pool`)
