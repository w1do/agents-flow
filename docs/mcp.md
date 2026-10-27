# MCP

Второй способ агенту отчитываться о работе. Тот же service layer и та же
PostgreSQL, что у REST. Отдельных статусов нет.

## Endpoint

```
https://flow.example.com/mcp
transport: Streamable HTTP over HTTPS
Authorization: Bearer <agent_token>
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

- Каждый вызов несёт `event_id`; повтор отчёта не создаёт дубликат отчёта.
- Инструмент работает только со своей арендованной задачей и своим проектом.
- Обязателен актуальный `lease_id`; иначе `409`.

## Аргументы и ответы

- Каждый инструмент принимает `task_id`, `lease_id`, `event_id`.
  Только `agent_get_assigned_task` может опустить `task_id`: сервер находит
  текущую задачу, затем проверяет переданный lease. Новую задачу он не арендует.
- Поля отчётов совпадают с REST. `agent_report_progress` принимает `event_type`,
  `message`, необязательные `payload` и `checkpoint`.
- `agent_save_checkpoint` принимает объект `checkpoint` и необязательный `message`;
  вызывает сервис событий с `event_type=checkpoint`.
- `agent_report_test_result` принимает `message` и необязательный `payload`;
  вызывает сервис событий с `event_type=test_result` без смены статуса.
- `agent_get_assigned_task` возвращает `task` (включая снимки skills) и
  `execution_state`; оба инструмента чтения решений возвращают `execution_state`.
- Ошибки инструментов: `isError=true`, JSON `error` с `code` и `message`.
  HTTP-коды отказов REST передаются в `error.code`; отсутствие токена даёт HTTP 401.
- Вызов с доступной своей задачей оставляет отдельное событие `mcp_*`, в том числе
  при ошибке или повторе отчёта. В аудите только код исхода; тела запроса нет.
  Если своей задачи нет, событие не создаётся: `task_events` требует `task_id`.

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
