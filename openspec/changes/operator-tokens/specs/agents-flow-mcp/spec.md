## ADDED Requirements

### Requirement: Скоупы операторского токена

Операторский токен SHALL иметь набор скоупов `read`, `operate`, `admin`, и инструмент MUST отклонять вызов без нужного скоупа ошибкой `forbidden`. Отозванный токен MUST отклоняться с `unauthorized`.

#### Scenario: Только чтение

- **WHEN** токен со скоупом `read` вызывает `pause_task`
- **THEN** вызов отклонён с `forbidden`

#### Scenario: Отзыв

- **WHEN** токен отозван командой `token revoke`
- **THEN** следующий вызов отклонён с `unauthorized`

### Requirement: Журнал вызовов

Каждый вызов инструмента MCP SHALL записываться в журнал с источником (`agent`, `telegram`, `console`, `external`), субъектом и результатом, без значений секретов.

#### Scenario: Внешний клиент

- **WHEN** внешний MCP-клиент вызывает `list_tasks`
- **THEN** в журнале запись с источником `external` и результатом `ok`
