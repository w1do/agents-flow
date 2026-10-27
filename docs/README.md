# Документация Agents Flow

Один файл — одна тема. Корневые документы (`GOAL.md`, `MVP.md`, `CLAUDE.md`)
лежат в корне, всё техническое — здесь.

| Файл | Тема |
|---|---|
| [architecture.md](architecture.md) | Компоненты, потоки, границы ответственности |
| [data-model.md](data-model.md) | Таблицы PostgreSQL и связи |
| [api.md](api.md) | REST-контракты `/api/v1` |
| [task-lifecycle.md](task-lifecycle.md) | Статусы, переходы, аренда, идемпотентность |
| [skills.md](skills.md) | Модель skills, версии, назначение, ограничения |
| [harness.md](harness.md) | Устройство Go-бинарника, init, run, синхронизация |
| [deep-agents.md](deep-agents.md) | Что получает агент на каждом этапе |
| [telegram.md](telegram.md) | Голос, текст, кнопки решений, уведомления |
| [mcp.md](mcp.md) | MCP-инструменты и их ограничения |
| [security.md](security.md) | Токены, права, запреты |
| [deployment.md](deployment.md) | Dokploy, compose, переменные окружения |
| [criteria.md](criteria.md) | Приёмочные и качественные критерии |
| [roadmap.md](roadmap.md) | Порядок реализации MVP |

## Журнал решений

`docs/decisions/YYYY-MM-DD-<id>.md` — по одному файлу на значимое решение:
контекст, варианты, выбор, последствия.

## Правило

Документ описывает то, как система работает, а не то, какой код хотелось бы
написать. Источник требований — [../PLAN.md](../PLAN.md); при расхождении
побеждает PLAN.md, документ исправляется.
