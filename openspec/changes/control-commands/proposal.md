# Proposal: control-commands

> Голосовые команды управления. Волна 3 (после MVP), см. PLAN.md.

## Why

Пауза, возобновление и остановка голосом (ТЗ §5.1). Модель только определяет намерение из закрытого списка, исполняет сервер.

## What Changes

- Класс `control`: действие из закрытого списка (`pause_sandboxes`, `resume_sandboxes`, `pause_tasks`, `resume_tasks`, `stop_task`, `status`), цель, фильтр, уверенность
- Проверка применимости и неоднозначности целей (кнопки выбора)
- Пауза — сразу; возобновление и остановка — кнопка «Подтвердить»
- Итог: сколько остановлено и что сохранено

## Capabilities

### New Capabilities

Нет.

### Modified Capabilities

- `command-routing`: добавляются требования (ADDED): Закрытый список действий, Подтверждение по риску, Неоднозначная цель.

## Impact

- Зависит от: `mcp-operator-tools`, `task-pause-resume`.
- Ссылки: ТЗ §5.1.
- Затрагивает ARCHITECTURE.md (разделы по теме) и, при новых инструментах, docs/mcp-agents-flow.md.

## Не входит

- Второй фактор (`confirm-second-factor`)
