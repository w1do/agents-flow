# Модель данных

PostgreSQL, SQLAlchemy, миграции только через Alembic. Все секреты — хеши.
Схема — из PLAN.md раздел 11.

## Связи

```
users

projects ──┬── project_init_tokens
           ├── agents ── agent_skills ── skills ── skill_categories
           └── tasks ──┬── task_events
                       ├── task_skill_snapshots
                       └── (assigned_agent_id → agents)

idempotency_keys
```

## users

| Поле | Тип | Примечание |
|---|---|---|
| id | UUID | PK |
| email | text | unique |
| password_hash | text | bcrypt/argon2 |
| created_at | timestamptz | |

Первый администратор создаётся из `ADMIN_EMAIL` / `ADMIN_PASSWORD` при старте.

## projects

| Поле | Тип | Примечание |
|---|---|---|
| id | UUID | PK |
| name | text | |
| description | text | nullable |
| telegram_chat_id | text | nullable |
| project_token_hash | text | nullable |
| created_at / updated_at | timestamptz | |

## project_init_tokens

| Поле | Тип | Примечание |
|---|---|---|
| id | UUID | PK |
| project_id | UUID | FK → projects |
| token_hash | text | единственное хранение кода |
| expires_at | timestamptz | +10 минут |
| used_at | timestamptz | nullable, одноразовость |
| created_at | timestamptz | |

## agents

| Поле | Тип | Примечание |
|---|---|---|
| id | UUID | PK |
| project_id | UUID | FK → projects |
| name | text | unique в проекте |
| agent_token_hash | text | |
| repository_path_hint | text | подсказка, не доверенные данные |
| git_remote | text | например `origin` |
| status | enum | `online`, `busy`, `offline` |
| last_heartbeat_at | timestamptz | |
| created_at / updated_at | timestamptz | |

## skill_categories

`id` UUID, `name`, `description`, `sort_order`.

## skills

| Поле | Тип | Примечание |
|---|---|---|
| id | UUID | PK |
| category_id | UUID | FK |
| name | text | |
| description | text | |
| content | text | Markdown |
| version | int | +1 при изменении текста |
| content_hash | text | sha256 содержимого |
| is_active | bool | |
| created_at / updated_at | timestamptz | |

## agent_skills

`agent_id`, `skill_id`, `enabled`, `assigned_at`. Уникальность `agent_id + skill_id`.

## tasks

| Поле | Тип | Примечание |
|---|---|---|
| id | UUID | PK |
| project_id | UUID | FK |
| title | text | |
| description | text | |
| source_type | enum | `web`, `telegram_text`, `telegram_voice`, `api` |
| source_text | text | исходный текст или расшифровка |
| status | enum | 12 статусов из task-lifecycle.md |
| assigned_agent_id | UUID | nullable |
| lease_id | UUID | nullable |
| lease_expires_at | timestamptz | nullable |
| plan_text | text | nullable |
| plan_revision | int | счётчик улучшений |
| plan_decision | enum | `pending`, `approved`, `rejected` |
| plan_feedback | text | nullable |
| result_summary | text | nullable |
| result_data | jsonb | файлы, тесты, commit SHA |
| checkpoint | jsonb | состояние работы агента |
| created_at / updated_at / completed_at | timestamptz | |

## task_skill_snapshots

`task_id`, `skill_id`, `skill_name`, `skill_version`, `content_hash`.
Фиксируется при аренде задачи — гарантирует, что правка skill не меняет
текущую задачу.

## task_events

`id` UUID, `task_id`, `agent_id` nullable, `event_type`, `message`,
`payload` jsonb, `created_at`. Только добавление, без обновлений.

## idempotency_keys

`id` UUID, `scope`, `idempotency_key`, `request_hash`, `response_code`,
`response_body` jsonb, `created_at`. Уникальность `scope + idempotency_key`.

## Индексы

- `tasks (project_id, status)` — выборка задач для панели и аренды.
- `tasks (status, created_at)` — очередь аренды.
- `task_events (task_id, created_at)` — лента событий.
- `agent_skills (agent_id)` — синхронизация skills.
