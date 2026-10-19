## MODIFIED Requirements

### Requirement: Допустимые переходы

Смена статуса SHALL выполняться только по таблице переходов своего kind в `domain/statuses.py`. Для `plan`:
`new→choosing`, `choosing→planning`, `choosing→trash`, `planning→ready`, `planning→error`, `planning→paused`
(ждёт ответа владельца), `paused→planning` (ответ получен). Для `implement`:
`backlog→active`, `active→testing`, `active→error`, `active→paused` (ждёт ответа владельца), `testing→ready`,
`testing→error`, `ready→merged`, `ready→backlog` (доработка по замечанию владельца), `error→backlog` (повтор),
`paused→backlog` (ответ получен). Новые статусы вне набора ТЗ v5 MUST NOT вводиться. Недопустимый переход MUST
отклоняться ошибкой `invalid_transition`.

#### Scenario: Пропуск этапа

- **WHEN** задачу `implement` в статусе `backlog` пытаются перевести в `ready`
- **THEN** возвращается `invalid_transition`, статус остаётся `backlog`, событие не создаётся

#### Scenario: Допустимый переход

- **WHEN** задачу `plan` в статусе `choosing` переводят в `planning`
- **THEN** статус меняется и появляется событие задачи со статусом `planning`

#### Scenario: Повтор после ошибки

- **WHEN** задачу `implement` в статусе `error` переводят в `backlog`
- **THEN** переход выполняется и задача снова доступна очереди

#### Scenario: Доработка готовой задачи

- **WHEN** задачу `implement` в статусе `ready` переводят в `backlog`
- **THEN** переход выполняется, задача снова доступна очереди с той же веткой

#### Scenario: Влитая задача не возвращается

- **WHEN** задачу `implement` в статусе `merged` пытаются перевести в `backlog`
- **THEN** возвращается `invalid_transition`
