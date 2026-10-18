# ARCHITECTURE — agents-flow harness

Голосовой AI-харнесс: задача диктуется в Telegram, выполняется агентом (Claude Code) в песочнице
Novita, результат приходит как Merge Request в GitLab, статус обновляется в том же чате.

Источник требований: [`docs/tz/tz-v5.md`](docs/tz/tz-v5.md). Принятые решения: [`docs/decisions.md`](docs/decisions.md).
План работ и статус: [`PLAN.md`](PLAN.md). Этот файл описывает **целевое** устройство системы и
обновляется тем же изменением, что и код (эндпоинт, статус, таблица, ENV, сервис).

## 1. Компоненты

```
 Telegram (голос/текст/кнопки)
        │ webhook (HTTPS, секрет)
        ▼
 ┌──────────────────────── server (FastAPI, async) ────────────────────────┐
 │ api/telegram ──► services ◄── mcp/agents-flow ◄─── агент в песочнице     │
 │                     │  ▲                         (токен задачи, HTTPS)  │
 │                     ▼  │                                                 │
 │              db (SQLAlchemy async) ──► Postgres (отдельный стек)         │
 │                     ▲                                                    │
 │ adapters: telegram, stt, polza, novita, gitlab                           │
 └─────────────────────┼────────────────────────────────────────────────────┘
                       │ та же кодовая база, отдельный процесс
 ┌──────── worker (диспетчер, polling Postgres) ────────┐
 │ выбирает задачу → активирует песочницу → exec агента │──► Novita Sandbox
 │ → гейты (секреты, коммит, тесты, push, MR)           │      └ claude, git, openspec
 └──────────────────────────────────────────────────────┘──► GitLab API (MR)
```

| Компонент | Где | Назначение | Этап |
|---|---|---|---|
| server | `apps/server` | Webhook Telegram, MCP `agents-flow`, `GET /tasks/{id}`, health | MVP |
| worker | `apps/server` (команда `harness-server worker`) | Диспетчер: polling очереди, песочница, агент, гейты | MVP |
| shared | `shared/` | Pydantic-модели и перечисления, общие для сервера и типов консоли | MVP |
| migrations | `db/migrations` | Alembic. Схема меняется только миграциями | MVP |
| bootstrap | `deploy/sandbox/bootstrap.sh` | Идемпотентная подготовка песочницы без секретов | MVP |
| console | `apps/console` | React + shadcn/ui, вызывает те же инструменты MCP | позже |
| shared-types | `packages/shared-types` | TS-типы для консоли, генерируются из `shared/` | позже |

## 2. Слои сервера

```
apps/server/src/harness_server/
├── main.py            # create_app(): FastAPI + смонтированный MCP, lifespan
├── cli.py             # harness-server: serve | worker | migrate | sandbox pause|resume | reset-password
├── settings.py        # pydantic-settings: ENV, путь к config/harness.yaml
├── config.py          # загрузка и валидация config/harness.yaml (workspaces, sandbox, gitlab)
├── api/               # HTTP-входы: telegram_webhook, tasks, health. Без бизнес-логики
├── mcp/               # MCP agents-flow: auth (токен задачи), tools. Без бизнес-логики
├── telegram/          # разбор update, рендер сообщений и кнопок, idempotency
├── services/          # ВСЯ бизнес-логика: tasks, routing, spec, sandboxes, delivery, notify
├── domain/            # статусы, допустимые переходы, ошибки домена (без I/O)
├── db/                # engine, session, ORM-модели, репозитории
├── adapters/          # внешние API за интерфейсами (Protocol): telegram, stt, polza, novita, gitlab
├── worker/            # dispatcher loop, pipelines plan/implement, gates
└── security/          # redaction (фильтр секретов), task tokens
```

Правила зависимостей (проверяются ревью и import-linter позже):

1. `api`, `mcp`, `telegram`, `cli` вызывают только `services`. Прямых запросов к БД в них нет.
2. `services` используют `db`, `domain`, `adapters` через интерфейсы. Это единственное место бизнес-логики:
   Telegram-кнопка, MCP-инструмент и консоль вызывают одну и ту же функцию сервиса.
3. `adapters` не знают про БД и домен задач; каждый внешний API — отдельный модуль с Protocol и фейком для тестов.
4. `domain` не делает I/O.
5. Обработчики HTTP не ждут агентов: долгие операции выполняет worker (не блокирующие обработчики).

## 3. Модель данных (MVP)

| Таблица | Ключевые поля | Назначение |
|---|---|---|
| `tasks` | id, kind (`plan`/`implement`/`check`), workspace_id, parent_id, text, status, priority, source (`telegram`/`spec`/`mcp`), spec_item_id, branch, mr_url, result, tests_state, created_at, updated_at | Задача и канбан (представление по статусам) |
| `task_events` | id, task_id, status, text, source, created_at | Лента этапов для Telegram и журнала |
| `routings` | id, task_id, command_class, options (JSON), chosen_workspace_id, raw_response, confidence | Решение Polza и выбор пользователя |
| `spec_items` | id, workspace_id, plan_task_id, change_id, key, text, status, last_checkpoint_id | Зеркало пунктов OpenSpec |
| `sandboxes` | id, provider_id, agent_type, status (`paused`/`active`/`error`), current_task_id, profile_version | Песочницы Novita |
| `checkpoints` | id, task_id, summary, files (JSON), diff_redacted, next_step, status, tokens | Чекпоинты (MVP: от сервера после агента) |
| `telegram_messages` | task_id, chat_id, message_id, lines (JSON) | Одно обновляемое сообщение на задачу |
| `telegram_updates` | update_id / callback_id (PK), received_at | Идемпотентность входа (A4) |
| `task_tokens` | id, task_id, token_hash, role (`planner`/`implementer`), expires_at, revoked_at | Токены задачи для MCP (A2) |

Workspace и агенты в MVP берутся из `config/harness.yaml`; таблицы `workspaces`, `agents`, `skills`,
`integrations`, `mcp_servers`, `sandbox_profiles`, `processes`, `sessions`, `operator_tokens`,
`audit_log` появляются в изменениях после MVP (см. PLAN.md).

## 4. Статусы задачи

Единый набор (ТЗ v5): `new`, `choosing`, `planning`, `backlog`, `active`, `testing`, `ready`,
`merged`, `error`, `stalled`, `paused`, `trash`. Новые статусы не вводятся без правки этого раздела,
`shared/` и миграции. Переходы задаются в `domain/statuses.py` и покрыты тестами.

```
plan:       new → choosing → planning → ready ("спецификация готова")
                     │            └──► error
                     └──► trash (отмена)
implement:  backlog → active → testing → ready (MR создан) → merged (позже: авто/вебхук)
                        │         │
                        └─────────┴──► error | stalled | paused   (paused/stalled — после MVP)
```

Класс «запрос состояния» задачу не создаёт: ответ собирается из `services.tasks` и отправляется сразу.

## 5. Сквозной поток MVP

1. **Вход.** `POST /telegram/webhook`: проверка `X-Telegram-Bot-Api-Secret-Token` и `chat_id == TELEGRAM_CHAT_ID`,
   дедуп по `update_id`. Голос скачивается через `getFile` и уходит в STT (OpenAI-совместимый `/audio/transcriptions`).
2. **Классификация.** Polza (OpenAI-совместимый chat completions, JSON-ответ, Pydantic-валидация) возвращает
   класс (`work` / `status` / `unknown`) и до 3 workspace. Невалидный ответ или недоступность → кнопки со всеми workspace.
3. **Выбор проекта.** Задача `plan` в `choosing`, бот присылает кнопки. Нажатие (дедуп по `callback_query.id`)
   → `planning`. Сообщение задачи одно, этапы дописываются через `editMessageText`.
4. **Планировщик.** Worker берёт задачу (`FOR UPDATE SKIP LOCKED`), блокирует строку песочницы, возобновляет её,
   выдаёт токен задачи, делает `git fetch` и worktree на `task/<plan_id>` от `origin/<default_branch>`, запускает
   `claude -p` с промптом планировщика. Планировщик пишет OpenSpec-изменение, коммитит, вызывает
   `sync_spec` и `create_task(kind=implement)` → задачи в `backlog`. Сервер пушит ветку плана, задача `plan` → `ready`.
5. **Исполнитель.** Worker берёт задачу из `backlog` по приоритету, worktree на `task/<id>` от
   `origin/task/<plan_id>` (в ней есть спецификация), агент реализует пункт и вызывает `report_task`.
6. **Гейты (сервер, exec, идемпотентно).** Фильтр секретов по `git diff` → коммит → тесты (команда из workspace;
   нет команды → `tests_state = no_tests`, не «зелёные») → push → MR в GitLab (сначала поиск существующего по
   source branch) → `ready`, сообщение «готова, MR создан». Мердж — руками.
7. **Очистка.** Удаление worktree и локальной ветки, отзыв токена задачи; успех очистки разрешает паузу песочницы.

## 6. MCP `agents-flow`

Смонтирован в FastAPI по пути `/mcp` (Streamable HTTP, официальный MCP Python SDK; host-приложение
запускает `session_manager.run()` в своём lifespan). Каталог инструментов: [`docs/mcp-agents-flow.md`](docs/mcp-agents-flow.md).

- **Токен задачи** (`Authorization: Bearer`): выдаётся при активации, хранится хешем, действует до конца задачи.
  Даёт доступ только к инструментам своей роли и своей задаче/workspace.
- **MVP-инструменты:** `report_task`, `sync_spec`, `create_task` (только планировщик, только `implement`/`backlog`,
  только свой workspace), `list_tasks` (чтение своего workspace).
- **Операторский токен** со скоупами `read`/`operate`/`admin`, журнал вызовов с источником — после MVP.
- Агент не пишет в Telegram: сообщения формирует сервер по `task_events`.

## 7. Песочница

- MVP: одна песочница, созданная вручную, её id в `config/harness.yaml`. Адаптер `SandboxProvider`
  (`exec`, `write_file`, `read_file`, `pause`, `resume`, `extend_timeout`) скрывает Novita SDK.
- Bootstrap (`deploy/sandbox/bootstrap.sh`): pinned `claude`, `git`, `openspec`, клон репозиториев,
  `.mcp.json` с `${AGENTS_FLOW_TOKEN}` (значение приходит в env exec-команды). Секретов в файле нет. Идемпотентен.
- Креды (`ANTHROPIC_API_KEY`, `GITLAB_TOKEN`, токен задачи) передаются только в env конкретной exec-команды
  и не записываются на диск песочницы.
- Агент запускается в фоне, вывод `stream-json` пишется в `~/.harness/tasks/<id>/stream.jsonl`, итог — в
  `~/.harness/tasks/<id>/status.json`. Worker опрашивает файл статуса через exec.

## 8. Безопасность (MVP)

| Угроза | Мера |
|---|---|
| Чужие сообщения | Секрет webhook + `chat_id == TELEGRAM_CHAT_ID`, остальное отбрасывается без ответа |
| Дубли Telegram | Таблица `telegram_updates`, повторное нажатие не создаёт активацию (A4) |
| Агент вызывает управление | Токен задачи, роль и проверка принадлежности задачи на каждом вызове (A2) |
| Секреты в git/БД/Telegram | `security/redaction`: шаблоны + точные значения выданных кредов; блокирует коммит при находке (A3) |
| SQL-инъекции | Только SQLAlchemy ORM с параметрами, Pydantic на входе |
| Гонка за песочницу | `SELECT … FOR UPDATE SKIP LOCKED` на `sandboxes`, активация идемпотентна (A5) |
| Перехват | HTTPS через Traefik Dokploy; наружу порты не публикуются |

## 9. Конфигурация и ENV

`config/harness.yaml` (путь в `HARNESS_CONFIG`, без секретов, пример — `config/harness.example.yaml`):
workspaces (id, name, voice_aliases, gitlab_project, default_branch, test_command, agent), sandbox (provider_id),
gitlab (base_url).

| ENV | Назначение |
|---|---|
| `DATABASE_URL` | Postgres (asyncpg) |
| `HARNESS_PUBLIC_URL` | Публичный HTTPS-адрес сервера, им пользуется MCP-конфиг песочницы |
| `HARNESS_CONFIG` | Путь к `harness.yaml` |
| `HARNESS_SECRET_KEY` | Соль/ключ для хешей токенов |
| `HARNESS_ADMIN_TOKEN` | Временный операторский bearer для `POST /tasks`, `GET /tasks/{id}` (до `operator-tokens`) |
| `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`, `TELEGRAM_WEBHOOK_SECRET` | Бот и владелец |
| `POLZA_AI_URL`, `POLZA_AI_KEY`, `POLZA_AI_MODEL`, `ROUTING_MIN_CONFIDENCE` | Классификация и порог уверенности |
| `STT_PROVIDER`, `STT_API_URL`, `STT_API_KEY`, `STT_MODEL` | Распознавание речи (по умолчанию Whisper через Polza) |
| `NOVITA_API_KEY`, `NOVITA_DOMAIN` | Песочницы |
| `GITLAB_URL`, `GITLAB_TOKEN` | Push и MR |
| `ANTHROPIC_API_KEY` | Claude Code в песочнице (передаётся только в exec) |
| `AGENT_RUN_TIMEOUT_MIN`, `TESTS_TIMEOUT_MIN` | Лимит времени агента и гейта тестов |
| `ADMIN_EMAIL`, `ADMIN_PASSWORD` | Консоль, после MVP |

Новая переменная или сервис добавляется одним изменением в Compose, `.env.example` и эту таблицу.

## 10. Деплой

Dokploy, два Compose-стека:

- `deploy/db/docker-compose.yml` — Postgres отдельно; редеплой харнесса не трогает данные.
- `docker-compose.yml` — `migrate` (одноразовый, `alembic upgrade head`) → `server` и `worker`
  (`depends_on: service_completed_successfully`); `console` — после MVP.

Все сервисы в внешней сети `dokploy-network`, наружу только `expose`, домен и HTTPS — в Dokploy.
CI: `.gitlab-ci.yml`, стадии `check → build → deploy`; образы в GitLab Registry с тегами
`:$CI_COMMIT_SHORT_SHA` и `:main`; деплой — `curl` на webhook Dokploy. Цель — до 10 минут.
