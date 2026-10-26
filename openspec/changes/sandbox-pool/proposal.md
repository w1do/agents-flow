# Proposal: sandbox-pool

> Пул песочниц. Волна 5 (после MVP), см. PLAN.md.

## Why

Одной песочницы мало для параллельной работы; ТЗ §9 описывает общий пул по типу агента.

## What Changes

- Несколько песочниц в `sandboxes`, выбор свободной нужного типа агента с `SKIP LOCKED`
- `create_sandbox(agent_type)`, `list_sandboxes`, `pause_sandbox(es)`, `resume_sandbox(es)`, `delete_sandbox(confirm)`
- Выбор и API пула остаются будущим объёмом. Создание через Novita API, bootstrap и создание
  локального провайдера отменены `local-agent-machine`; пул сейчас не реализуется.

## Capabilities

### New Capabilities

Нет.

### Modified Capabilities

- `sandbox-runtime`: добавляются требования (ADDED): Выбор песочницы по типу агента, Удаление с подтверждением.

## Impact

- Зависит от: `mvp-06-sandbox-runtime`, `operator-tokens`.
- Ссылки: ТЗ §9 (модель), §17 вопрос 2.
- Затрагивает ARCHITECTURE.md (разделы по теме) и, при новых инструментах, docs/mcp-agents-flow.md.

## Не входит

- Автомасштабирование
