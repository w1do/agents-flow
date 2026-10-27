# MCP

Второй способ агенту отчитываться о работе. Тот же service layer и та же
PostgreSQL, что у REST. Отдельных статусов нет.

## Endpoint

```
https://flow.example.com/mcp
transport: Streamable HTTP over HTTPS
```

## Инструменты MVP

| Инструмент | Назначение |
|---|---|
| `agent_get_assigned_task` | текущая задача, lease, checkpoint, решения |
| `agent_heartbeat` | продлить аренду |
| `agent_report_plan` | передать план |
| `agent_get_plan_decision` | узнать решение по плану |
| `agent_report_progress` | передать прогресс |
| `agent_save_checkpoint` | сохранить checkpoint |
| `agent_report_test_result` | результаты тестов |
| `agent_report_result` | итог реализации |
| `agent_get_result_decision` | узнать решение по результату |
| `agent_report_publication_result` | итог push/deploy |
| `agent_report_failure` | ошибка |

## Правила

- Каждый отчёт несёт `event_id`; повтор не создаёт дубликат.
- Инструмент работает только со своей арендованной задачей и своим проектом.
- Обязателен актуальный `lease_id`; иначе `409`.

## Что агенту нельзя

- читать задачи других проектов;
- подтверждать собственный план;
- принимать собственный результат;
- запускать публикацию без решения пользователя;
- ставить `merged`.

## Реализация

- Один модуль инструментов поверх общих сервисов.
- Валидация аргументов — Pydantic-схемы, те же, что у REST.
- Авторизация — тот же agent token.
- Ответ — компактный JSON без внутренних деталей и секретов.
- Все вызовы пишут `task_events` с типом `mcp_*`.
