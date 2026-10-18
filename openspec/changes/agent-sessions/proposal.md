# Proposal: agent-sessions

> Сессии агента, пороги контекста и handoff. Волна 3 (после MVP), см. PLAN.md.

## Why

Длинные задачи не помещаются в одну сессию. ТЗ §10.1 задаёт отрезки, пороги 120k/150k и handoff (D-15).

## What Changes

- Запуск отрезками `claude -p --max-turns` с `--resume`
- Контекст последнего ответа = input + cache read + cache creation, по `message.id`
- Порог 120k — смена сессии на границе отрезка; 150k — немедленная остановка
- Handoff: детерминированная часть из git + summary агента; `save_handoff`, `list_sessions`, `force_handoff`
- Состояния сессии `running → handoff_pending → closed`

## Capabilities

### New Capabilities

- `agent-sessions`: сессии агента, пороги контекста и handoff.

### Modified Capabilities

Нет.

## Impact

- Зависит от: `checkpoints`, `budget-usage`.
- Ссылки: ТЗ §10.1.
- Затрагивает ARCHITECTURE.md (разделы по теме) и, при новых инструментах, docs/mcp-agents-flow.md.

## Не входит

- Параллельные сессии одной задачи (запрещены)
