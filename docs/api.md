# API

`GET /healthz`, login, проекты, init-токены, `/harness/init`, skills, задачи,
аренды, отчёты и решения реализованы.
FastAPI публикует `/docs`, `/redoc`, `/openapi.json`; примеры: [api-examples.md](api-examples.md).

## Формат и схемы

Все тела — `application/json`, UUID — строки UUID, время — RFC 3339 с часовым поясом.
Login принимает email с `@` и доменной точкой. `ProjectCreate.name` и
`HarnessInitRequest.agent_name` обрезаются по краям и должны содержать 1–200 символов.
Полные JSON Schema Draft 2020-12 находятся в `$defs` следующих файлов:

- [common.json](api-schemas/common.json): health, ошибки, статусы, источники.
- [identity.json](api-schemas/identity.json): вход, проекты, агенты, init-коды.
- [skills.json](api-schemas/skills.json): категории, skills, назначения.
- [tasks.json](api-schemas/tasks.json): задачи, события, снимки, решения, состояние исполнения.
- [harness.json](api-schemas/harness.json): init, heartbeat, claim, файлы skills.
- [reports.json](api-schemas/reports.json): отчёты агента.

Имя в таблице означает `$defs.<Имя>`; `[]` означает массив объектов этой схемы.
`—` означает отсутствие тела запроса. Пустая очередь claim возвращает 204 без тела.
Схемы указывают поля, null, enum и вложенные структуры; неизвестные поля запрещены,
кроме свободных JSON-полей.
`payload`, `checkpoint`, `result_data` — JSON-объекты с произвольными ключами.
Пропущенные необязательные `description`, `telegram_chat_id`, `feedback` дают `null`;
`sort_order` при создании категории — 0. PATCH меняет только переданные поля.
`warnings` в SkillResponse — массив предупреждений, пустой при их отсутствии.

## Авторизация и идемпотентность

| Обозначение | Заголовок Authorization |
|---|---|
| Admin | `Bearer <jwt>` |
| Agent | `Bearer <agent_token>` |
| Init | `init_code` в теле запроса `/harness/init` |
| Public | не нужен |

`Idempotency-Key` обязателен для новых POST, PATCH и PUT skills, задач, аренд и отчётов.
Login, создание проектов, init-токенов и `/harness/init` сохраняют прежний контракт без ключа.
Область ключа — субъект авторизации, метод и путь; повтор с тем же телом возвращает
сохранённый код и ответ, с другим телом — 409. Неуспешные операции ключ не занимают.
Отчёты агента дополнительно требуют `event_id` и актуальный `lease_id`:
повтор `(task_id, event_id)` не добавляет событие. Init-код действует 10 минут,
привязан к проекту и используется один раз; agent_token возвращается при init.
Коды и токены не включаются в карточки, списки, ошибки и логи.
Реализованные GET-списки проектов и агентов принимают `offset` (по умолчанию 0)
и `limit` (по умолчанию 50, диапазон 1–200). Списки skills, категорий и задач используют тот же предел.
`{id}` в каждом пути — UUID соответствующей сущности.

## Панель и проекты

| Метод и полный путь | Доступ | Запрос | Успешный ответ | Ошибки |
|---|---|---|---|---|
| POST `/api/v1/auth/login` | Public | LoginRequest | 204, HttpOnly cookie `session` | 401, 422, 429 |
| POST `/api/v1/auth/token` | Public | LoginRequest | 200 TokenResponse (`access_token`) | 401, 422, 429 |
| GET `/api/v1/projects` | Admin | — | 200 ProjectResponse[] | 401, 422 |
| POST `/api/v1/projects` | Admin | ProjectCreate | 201 ProjectResponse | 401, 422 |
| GET `/api/v1/projects/{id}` | Admin | — | 200 ProjectResponse | 401, 404, 422 |
| POST `/api/v1/projects/{id}/init-tokens` | Admin | — | 201 InitTokenResponse (`code`) | 401, 404, 422 |
| GET `/api/v1/projects/{id}/agents` | Admin | — | 200 AgentResponse[] | 401, 404, 422 |
| GET `/api/v1/projects/{id}/tasks` | Admin | — | 200 TaskResponse[] | 401, 403, 404, 422 |
| POST `/api/v1/projects/{id}/tasks` | Admin | TaskCreate | 201 TaskResponse | 401, 403, 404, 409, 422 |
| GET `/api/v1/tasks/{id}` | Admin | — | 200 TaskResponse | 401, 403, 404, 422 |
| PATCH `/api/v1/tasks/{id}` | Admin | TaskPatch (`status`: new/paused/trash) | 200 TaskResponse | 401, 403, 404, 409, 422 |
| POST `/api/v1/tasks/{id}/plan/decision` | Admin | PlanDecisionRequest | 200 TaskResponse | 401, 403, 404, 409, 422 |
| POST `/api/v1/tasks/{id}/result/decision` | Admin | ResultDecisionRequest | 200 TaskResponse | 401, 403, 404, 409, 422 |

`active_task_count` считает choosing/planning/active/testing.
ProjectResponse для списка, карточки и создания содержит `active_task_count`, массив текущих `agents`,
`init_code_expires_at` (nullable, дата и время истечения активного init-кода),
`telegram_chat_id`, `created_at` и `updated_at`. AgentResponse содержит `project_id`,
`repository_path_hint`, `created_at` и `updated_at`. LoginResponse содержит `expires_in`
в секундах. TaskResponse — события по времени
создания и снимки skills. В списке задач допустим фильтр `status` из TaskStatus.
`approved` запускает реализацию, `rejected` возвращает план на улучшение;
для rejected нужен непустой feedback (иначе 422). `trash` снимает план с работы.
PATCH возвращает stalled в new; остальные переходы проверяются по матрице.
`publish` разрешает публикацию, `rework` возвращает в active и требует feedback,
`keep_ready` оставляет ready. `merged` выставляет только сервер по решению Admin.
Решение о публикации и замечания к результату сохраняются через события;
`result_feedback` и `publication_requested` в execution-state вычисляются из них.

## Skills

| Метод и полный путь | Доступ | Запрос | Успешный ответ | Ошибки |
|---|---|---|---|---|
| GET `/api/v1/skill-categories` | Admin | — | 200 CategoryResponse[] | 401, 403, 422 |
| POST `/api/v1/skill-categories` | Admin | CategoryCreate | 201 CategoryResponse | 401, 403, 409, 422 |
| PATCH `/api/v1/skill-categories/{id}` | Admin | CategoryPatch | 200 CategoryResponse | 401, 403, 404, 409, 422 |
| GET `/api/v1/skills` | Admin | — | 200 SkillResponse[] | 401, 403, 422 |
| POST `/api/v1/skills` | Admin | SkillCreate | 201 SkillResponse | 401, 403, 404, 409, 422 |
| GET `/api/v1/skills/{id}` | Admin | — | 200 SkillResponse | 401, 403, 404, 422 |
| PATCH `/api/v1/skills/{id}` | Admin | SkillPatch | 200 SkillResponse | 401, 403, 404, 409, 422 |
| POST `/api/v1/skills/{id}/archive` | Admin | — | 200 SkillResponse | 401, 403, 404, 409, 422 |
| GET `/api/v1/agents/{id}/skills` | Admin | — | 200 SkillResponse[] | 401, 403, 404, 422 |
| PUT `/api/v1/agents/{id}/skills` | Admin | AgentSkillsReplace | 200 SkillResponse[] | 401, 403, 404, 409, 422 |

Пустой `skill_ids` снимает назначения. Необязательный `disabled_skill_ids` —
подмножество назначений с enabled=false; остальные включаются. В ответах есть
`assigned_agents`, а для назначений — `enabled` и `assigned_at`. Архивирование сохраняет снимки.
`GET /api/v1/skills` дополнительно принимает `category_id: UUID`, `is_active: bool`.
Версия skill увеличивается только при изменении сохранённого content.
SkillPatch также принимает `is_active`. Подозрительное содержимое сохраняется без
изменений; `warnings` содержит имена совпавших типов секрета.

## Harness

| Метод и полный путь | Доступ | Запрос | Успешный ответ | Ошибки |
|---|---|---|---|---|
| POST `/api/v1/harness/init` | Init | HarnessInitRequest | 201 HarnessInitResponse | 401, 403, 404, 409, 422 |
| POST `/api/v1/agents/{id}/heartbeat` | Agent | HeartbeatRequest | 200 HeartbeatResponse | 401, 403, 404, 409, 422 |
| GET `/api/v1/agents/{id}/skills/sync` | Agent | — | 200 SkillSyncResponse | 401, 403, 404, 422 |
| POST `/api/v1/agents/{id}/leases/claim` | Agent | ClaimRequest | 200 ClaimResponse или 204 без тела | 401, 403, 404, 409, 422, 429 |
| GET `/api/v1/tasks/{id}/execution-state` | Agent | — | 200 ExecutionStateResponse | 401, 403, 404, 409, 422 |
| POST `/api/v1/tasks/{id}/plan` | Agent | PlanRequest | 200 ReportResponse | 401, 403, 404, 409, 422 |
| POST `/api/v1/tasks/{id}/events` | Agent | EventRequest | 200 ReportResponse | 401, 403, 404, 409, 422 |
| POST `/api/v1/tasks/{id}/result` | Agent | ResultRequest | 200 ReportResponse | 401, 403, 404, 409, 422 |
| POST `/api/v1/tasks/{id}/publication-result` | Agent | PublicationResultRequest | 200 ReportResponse | 401, 403, 404, 409, 422 |
| POST `/api/v1/tasks/{id}/fail` | Agent | FailRequest | 200 ReportResponse | 401, 403, 404, 409, 422 |

Claim без задач → 204 без тела. При успехе lease находится в task и в полях
`lease_id`, `lease_expires_at` ответа.
`/harness/init` принимает `init_code` в JSON теле и возвращает `skills: []` для нового
агента. Назначения выполняются администратором явно. URL `git_remote` с credentials
отклоняется с 422 в формате `ValidationErrorResponse`. `server_url` в ответе Harness
берётся из `PUBLIC_BASE_URL` и должен быть HTTP(S) URL. Чужие и отсутствующие объекты
одинаково отвечают 404.
Heartbeat без задачи → `{"task_id":null,"lease_id":null}`; оба поля либо null,
либо UUID, смешанная пара — 422. TTL аренды — 60 секунд, poll — 5 секунд.
Skills sync возвращает полный текущий набор включённых активных файлов с `name`;
отсутствующие удаляются. Истечение аренды проверяется при обращении и каждые 5 секунд.
Execution-state требует query `lease_id: UUID`, проверяемый как в отчётах.
Execution-state также возвращает `checkpoint`. Events с `event_type=planning|testing`
двигают этап; серверные типы событий и смена статуса через payload запрещены.
Publication-result записывает событие после publish, сохраняя merged даже при ошибке.
Fail и publication-result освобождают агента; ожидание решений сохраняет аренду.

## Ошибки

| Код | Значение | Схема |
|---|---|---|
| 401 | отсутствующий/неверный/истёкший токен; использованный init-код | ErrorResponse |
| 403 | роль не разрешена, другой проект/агент | ErrorResponse |
| 404 | объект отсутствует/скрыт, маршрут ещё не реализован | ErrorResponse |
| 405 | неверный HTTP-метод | ErrorResponse |
| 409 | чужой/истёкший lease, агент занят, переход или ключ конфликтует | ErrorResponse |
| 422 | тело, UUID, query или обязательный заголовок не прошли валидацию | ValidationErrorResponse с `detail: ValidationIssue[]` |
| 429 | превышена частота login или claim; заголовок Retry-After в секундах | ErrorResponse |

Ошибки не содержат внутренних исключений или секретов.
