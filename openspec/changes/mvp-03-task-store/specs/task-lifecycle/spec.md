## ADDED Requirements

### Requirement: Набор статусов задачи

Задача SHALL иметь kind из `plan`, `implement`, `check` и статус только из набора `new`, `choosing`, `planning`,
`backlog`, `active`, `testing`, `ready`, `merged`, `error`, `stalled`, `paused`, `trash`.
Система MUST отклонять запись любого другого значения.

#### Scenario: Неизвестный статус

- **WHEN** сервис пытается установить статус `completed`
- **THEN** операция отклоняется ошибкой валидации и задача не меняется

### Requirement: Допустимые переходы

Смена статуса SHALL выполняться только по таблице переходов своего kind. Для `plan`: `new→choosing`,
`choosing→planning`, `choosing→trash`, `planning→ready`, `planning→error`. Для `implement`: `backlog→active`,
`active→testing`, `active→error`, `testing→ready`, `testing→error`, `ready→merged`, `error→backlog` (повтор).
Недопустимый переход MUST отклоняться ошибкой `invalid_transition`.

#### Scenario: Пропуск этапа

- **WHEN** задачу `implement` в статусе `backlog` пытаются перевести в `ready`
- **THEN** возвращается `invalid_transition`, статус остаётся `backlog`

#### Scenario: Допустимый переход

- **WHEN** задачу `plan` в статусе `choosing` переводят в `planning`
- **THEN** статус меняется и появляется событие задачи со статусом `planning`

### Requirement: Лента событий

Каждая смена статуса и каждый отчёт агента SHALL создавать событие задачи с временем, статусом, текстом
и источником (`telegram`, `agent`, `worker`, `api`) в той же транзакции, что и изменение задачи.

#### Scenario: История задачи

- **WHEN** задача прошла `backlog → active → testing → ready`
- **THEN** у задачи 3 события в хронологическом порядке

### Requirement: Очередь задач без гонок

Выбор следующей задачи SHALL возвращать задачу с наибольшим приоритетом, а среди равных — самую раннюю,
и MUST гарантировать, что два конкурентных выбора не получат одну и ту же задачу.

#### Scenario: Два воркера

- **WHEN** два процесса одновременно запрашивают следующую задачу при одной задаче в `backlog`
- **THEN** задачу получает только один процесс, второй получает пустой результат

### Requirement: HTTP-доступ к задачам

Сервер SHALL предоставлять `POST /tasks` (создание задачи с текстом и необязательным workspace) и
`GET /tasks/{id}` (статус, результат, события). Оба эндпоинта MUST требовать операторский bearer-токен
и отвечать `401` без него, `404` для неизвестной задачи.

#### Scenario: Без токена

- **WHEN** запрос `GET /tasks/{id}` приходит без заголовка `Authorization`
- **THEN** сервер отвечает `401` и не раскрывает, существует ли задача
