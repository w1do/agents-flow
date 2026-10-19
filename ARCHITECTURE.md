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
| console | `apps/console` | React + shadcn/ui; в MVP — REST `/api/console/*` над теми же сервисами, MCP — после `operator-tokens` (D-39) | MVP (`mvp-10`) |
| shared-types | `packages/shared-types` | TS-типы для консоли, генерируются из `shared/` | MVP (`mvp-10`) |

## 2. Слои сервера

```
apps/server/src/harness_server/
├── app.py             # create_app(): FastAPI + смонтированный MCP, lifespan
├── cli.py             # harness-server: serve | worker | migrate | check-config | telegram set-webhook | sandbox status|pause|resume|bootstrap | reset-password
├── settings.py        # pydantic-settings: ENV, путь к config/harness.yaml
├── config.py          # загрузка и валидация config/harness.yaml (workspaces, sandbox, gitlab)
├── wiring.py          # композиционный корень бота: httpx-клиент, BotAdapters, BotContext (D-29)
├── api/               # HTTP-входы: tasks (POST /tasks, GET /tasks/{id}), telegram_webhook (POST /telegram/webhook), deps (сессия, admin-токен, секрет webhook), health. Без бизнес-логики
├── mcp/               # MCP agents-flow: auth (токен задачи), tools. Без бизнес-логики
├── telegram/          # parse.py (update → IncomingText / IncomingVoice / ButtonPress, dedup_key), render.py (тексты, карточка, callback_data, клавиатура); без I/O
├── services/          # ВСЯ бизнес-логика: tasks (mvp-03), intake (приём и восстановление апдейтов), notify (одно сообщение задачи), webhook (регистрация), context (BotContext); routing (классификация, уточнение, запись routings, mvp-05), status_report (ответ на запрос состояния, mvp-05), spec, sandboxes, delivery
├── domain/            # statuses.py (таблица переходов), errors.py (DomainError и коды), без I/O и sqlalchemy
├── db/                # base.py (Base, naming convention, enum-хелперы), ids.py (uuid7), session.py, models/ (9 таблиц)
├── adapters/          # внешние API за интерфейсами (Protocol) и фейки: telegram (httpx, mvp-04), stt (OpenAI-совместимый, mvp-04), polza (Router/PolzaRouter/FakeRouter, OpenAI-совместимый chat completions, mvp-05), novita, gitlab
├── worker/            # __init__.py (цикл worker, API не меняется), dispatcher.py (восстановление → reserve → activate → run → cleanup → pause), pipeline.py (контракт Pipeline; реестр PIPELINES пуст до mvp-08/09), gates (mvp-09)
└── security/          # redaction (фильтр секретов: шаблоны токенов и точные значения), task tokens
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
| `tasks` | id, kind (`plan`/`implement`/`check`), workspace_id, parent_id, text, status, priority, source (`telegram`/`spec`/`mcp`/`api`), spec_item_id, branch, mr_url, result, tests_state, created_at, updated_at | Задача и канбан (представление по статусам) |
| `task_events` | id, task_id, status, text, source (`telegram`/`agent`/`worker`/`api`), created_at | Лента этапов для Telegram и журнала |
| `routings` | id, task_id (NULL для status, unknown и ожидающего уточнения), command_class (`work`/`status`/`unknown`), decision (`auto`/`clarify`/`fallback`), options (JSON), chosen_workspace_id, raw_response, confidence, error (причина запасного пути), source_text (до нажатия «Сделать задачу», затем NULL), resolved_at | Решение Polza и выбор пользователя (mvp-05, D-32, миграция `0003`) |
| `spec_items` | id, workspace_id, plan_task_id, change_id, key, text, status, last_checkpoint_id; UNIQUE (workspace_id, change_id, key) | Зеркало пунктов OpenSpec |
| `sandboxes` | id, provider_id, agent_type, status (`paused`/`active`/`error`), current_task_id, profile_version, agent_started_at (время запуска агента, NULL — не запускался), agent_pid (pid группы агента, NULL — неизвестен) | Песочницы Novita; колонки агента — серверный учёт запуска, файлам песочницы не доверяем (D-41, миграция `0004`) |
| `checkpoints` | id, task_id, summary, files (JSON), diff_redacted, next_step, status, tokens | Чекпоинты (MVP: от сервера после агента) |
| `telegram_messages` | task_id, chat_id, message_id, lines (JSON) | Одно обновляемое сообщение на задачу |
| `telegram_updates` | kind (`update`/`callback`) + external_id (составной PK), received_at, processed_at, payload (JSONB NULL) | Идемпотентность входа (A4). `payload` — нормализованный апдейт владельца (текст, голос или нажатие кнопки, без имён и `from`) до обработки; после обработки обнуляется (D-27) |
| `task_tokens` | id, task_id, token_hash (только хеш), role (`planner`/`implementer`), expires_at, revoked_at | Токены задачи для MCP (A2) |

Схема создаётся миграцией `0001` (mvp-03, `db/migrations/versions/`); миграция `0002` (mvp-04) добавляет
аддитивную nullable-колонку `telegram_updates.payload`. Перечисления — `VARCHAR(16)` с именованным
CHECK `ck_<таблица>_<колонка>` (D-22); первичные ключи — UUIDv7 из `db/ids.py` (D-21).

Команда `harness-server sandbox resume` (design 8, mvp-06) действует по статусу строки `sandboxes`: закреплена задача
(`current_task_id`) — отказ `SandboxBusy` до любых вызовов провайдера; `paused` — без действий, провайдер не вызывается;
`error` или `active` без задачи — `connect`, затем `pause`, затем статус `paused` и сброс `agent_started_at`/`agent_pid`.
Ошибка провайдера не меняет строку.

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
   дедуп по `update_id`. Апдейт нормализуется и записывается в `telegram_updates.payload`, затем обработка идёт в фоне,
   ответ `200` не ждёт STT и Telegram. Голос скачивается через `getFile` (не больше `VOICE_MAX_BYTES`) и уходит в STT
   (OpenAI-совместимый `/audio/transcriptions`). Апдейт, принятый до рестарта, дообрабатывает worker при старте
   (`processed_at IS NULL` и старше 1 мин); недостающую карточку задачи worker досылает там же. Необработанные апдейты
   старше 24 ч списываются без обработки только при старте worker (периодической очистки нет).
2. **Классификация.** Polza (OpenAI-совместимый chat completions, JSON-ответ, Pydantic-валидация) возвращает
   класс (`work` / `status` / `unknown`) и до 3 workspace (D-31, D-33). `work` с уверенностью ниже
   `ROUTING_MIN_CONFIDENCE` (0.6) и любой класс с низкой уверенностью → вопрос «Сделать задачу / Показать статус»,
   задача не создаётся до нажатия. `status` → список открытых задач из БД без LLM и без песочниц (D-34);
   `unknown` → подсказка. Невалидный ответ, недоступность или отсутствие `POLZA_AI_KEY`/`POLZA_AI_MODEL` →
   запасной путь: задача `choosing` и кнопки со всеми workspace (D-13). Каждое решение пишется в `routings`.
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
  (`connect`, `exec`, `write_file`, `read_file`, `pause`, `extend_timeout`) скрывает Novita SDK
  (`adapters/novita`, нативный async `AsyncSandbox`, D-35). Песочница берёт одну задачу: резервирование
  `FOR UPDATE SKIP LOCKED` (`services/sandboxes.reserve`).
- Bootstrap (`deploy/sandbox/bootstrap.sh`, `sandbox-profile`): Node ≥ 22.13 (NodeSource, если нужно, через
  `sudo -n`), pinned `claude`, `git`, `openspec`, клон репозиториев, пустые `~/.claude/skills` и `~/.claude/agents`
  (D-48), `mcp.json` с `${AGENTS_FLOW_TOKEN}` (значение приходит в env exec-команды). Секретов в файле нет. Идемпотентен.
  С `--memory-ref`/`--memory-repo` (`sandbox.memory`, D-47, D-51): Docker Engine + Compose v2, memory-agent из GitHub
  на закреплённом коммите (клон по sha, `npm ci` по lockfile, сборка от пользователя песочницы, симлинк `/usr/local/bin/memory`, маркер `~/.harness/memory/installed-ref`),
  `memory service up`, `memory init --path ~/work/<id>` на клон каждого workspace; маркер `~/.harness/memory/<id>.ready`.
  Пакет `project-memory` из реестра npm не ставится (чужой пакет, D-51).
  Скрипт `~/.harness/bin/ensure-docker.sh` поднимает демон при активации (после паузы Novita). Ключ embeddings
  приходит только в env команды bootstrap; `EMBEDDING_API_KEY` в `.memory/.env` и конфиг memory не пишется.
- Токен GitLab уходит git заголовком `Authorization` только на префикс `gitlab.base_url` (`GIT_CONFIG_*` в env клона и fetch, D-52); askpass не используется.
- Ключи из vault (D-45, `adapters/vault`, MCP-клиент на официальном SDK): ссылка `vault:<project>/<service>/<name>`
  в `harness.yaml` (`gitlab.access_ref`, `sandbox.memory.embedding_ref`); значение берётся на каждую команду и
  передаётся только в env (bootstrap, активация, запуск агента). Без vault ссылка даёт `not_configured`; ключ
  GitLab без ссылки — ENV `GITLAB_TOKEN`. Сбой vault при активации — задача `error` с причиной `vault`.
- Память проекта (`sandbox-profile`, D-47): при активации `git checkout --detach origin/<default_branch>` клона
  workspace и `memory sync --path <клон>`; сбой не роняет задачу (предупреждение в лог). Агент получает
  `HARNESS_MEMORY_PROJECT=~/work/<id>`; индекс по worktree не строится.
- Креды (`CLAUDE_CODE_OAUTH_TOKEN`, `GITLAB_TOKEN`, токен задачи) передаются только в env конкретной exec-команды
  и не записываются на диск песочницы. Claude Code авторизуется подпиской через `CLAUDE_CODE_OAUTH_TOKEN`
  (D-18); `ANTHROPIC_API_KEY` в песочнице не задаётся: по документации Claude Code он перекрывает OAuth-токен (спайком не проверялось). `--bare` не используется. Риски токена подписки (экфильтрация, лимиты по окнам) — в `openspec/changes/mvp-06-sandbox-runtime/design.md`, Risks.
- Агент запускается в фоне, вывод `stream-json` пишется в `~/.harness/tasks/<id>/stream.jsonl`, итог — в
  `~/.harness/tasks/<id>/status.json`. Worker опрашивает файл статуса через exec.

## 8. Безопасность (MVP)

| Угроза | Мера |
|---|---|
| Чужие сообщения | Секрет webhook + `chat_id == TELEGRAM_CHAT_ID`, остальное отбрасывается без ответа |
| Дубли Telegram | Таблица `telegram_updates`, повторное нажатие не создаёт активацию (A4) |
| Утечка токена бота | Токен — часть URL Bot API: ошибки адаптера Telegram без URL и текста исключения httpx; логгеры `httpx` и `httpcore` на WARNING (D-29) |
| Утечка ключа STT | Ключ передаётся только заголовком `Authorization`; ошибки STT его не содержат |
| Утечка ключа Polza и текста владельца наружу | Ключ только в заголовке `Authorization`; в Polza уходит `redact(text)` не больше 2000 символов, транспорт только `https://`; ответ модели валидируется, путь выбирает сервер (D-31, D-33) |
| Персональные данные в очереди | В `payload` нет `from` и имён; `payload` обнуляется после обработки (D-27) |
| Агент вызывает управление | Токен задачи, роль и проверка принадлежности задачи на каждом вызове (A2) |
| Секреты в git/БД/Telegram | `security/redaction`: шаблоны + точные значения выданных кредов; блокирует коммит при находке (A3) |
| SQL-инъекции | Только SQLAlchemy ORM с параметрами, Pydantic на входе |
| Гонка за песочницу | `SELECT … FOR UPDATE SKIP LOCKED` на `sandboxes`, активация идемпотентна (A5) |
| Перехват | HTTPS через Traefik Dokploy; наружу порты не публикуются |

## 9. Конфигурация и ENV

`config/harness.yaml` (путь в `HARNESS_CONFIG`, без секретов, пример — `config/harness.example.yaml`):
workspaces (id, name, voice_aliases, gitlab_project, default_branch, test_command, agent), sandbox (provider_id,
версии, опционально `git_author` (`name`, `email`: автор коммитов агента, по умолчанию `agents-flow`), опционально `memory`: `repo` (по умолчанию `w1do/memory-agent`), `ref` (полный sha коммита), `embedding_ref`), gitlab (base_url, опционально `access_ref` — ссылка
`vault:…` на главный ключ GitLab). Ключи с сегментами `token`/`tokens`, `key`, `password`/`passwd`/`pwd`, `secret`/`secrets`, `apikey`,
`credential`/`credentials` сервер отклоняет на любом уровне. `gitlab.base_url` с учётными данными (`user@host`) тоже
отклоняется (D-26); токен GitLab задаётся только в ENV.

Обязательные ENV (решение D-20): `DATABASE_URL`, `HARNESS_CONFIG`, `HARNESS_SECRET_KEY`, `TELEGRAM_BOT_TOKEN`,
`TELEGRAM_CHAT_ID`, `TELEGRAM_WEBHOOK_SECRET`. Сервер и worker не стартуют, если их нет или они пустые.
Остальные опциональны, пока их не использует свой этап («с этапа» — в `.env.example`).
Секреты в таблице помечены «секрет»; в коде это `SecretStr`.

| ENV | Назначение |
|---|---|
| `DATABASE_URL` | **Обязательная.** Postgres (asyncpg). Секрет: содержит пароль |
| `HARNESS_CONFIG` | **Обязательная.** Путь к `harness.yaml` |
| `HARNESS_SECRET_KEY` | **Обязательная.** Соль/ключ для хешей токенов. Секрет |
| `HARNESS_PUBLIC_URL` | Публичный HTTPS-адрес сервера: им пользуется MCP-конфиг песочницы и `harness-server telegram set-webhook` (адрес webhook = этот адрес + `/telegram/webhook`); только `https://`, без query и fragment |
| `HARNESS_ADMIN_TOKEN` | Временный операторский bearer для `POST /tasks`, `GET /tasks/{id}` (до `operator-tokens`). Если задан, должен быть не короче 32 символов (`openssl rand -hex 32`), иначе сервер не стартует. Не задан — `/tasks` отвечает 401 (fail-closed, D-23). Секрет |
| `TELEGRAM_BOT_TOKEN` | **Обязательная.** Токен бота. Секрет |
| `TELEGRAM_CHAT_ID` | **Обязательная.** Владелец бота: положительное целое число, id личного чата. Групповые чаты не поддерживаются (D-30) |
| `TELEGRAM_WEBHOOK_SECRET` | **Обязательная.** Секрет webhook: от 32 до 256 символов `A-Za-z0-9_-` (`openssl rand -hex 32`), иначе сервер не стартует. Секрет |
| `POLZA_AI_URL`, `POLZA_AI_KEY`, `POLZA_AI_MODEL`, `ROUTING_MIN_CONFIDENCE` | Классификация и порог уверенности (mvp-05). `POLZA_AI_URL` по умолчанию `https://polza.ai/api/v1`, только `https://`; `POLZA_AI_KEY` — секрет; без ключа или модели маршрутизатор выключен (запасной путь); `ROUTING_MIN_CONFIDENCE` по умолчанию 0.6 (D-33) |
| `STT_PROVIDER`, `STT_API_URL`, `STT_API_KEY`, `STT_MODEL` | Распознавание речи. `STT_PROVIDER` — только `openai` (OpenAI-совместимый протокол) или не задан; без `STT_API_URL`, `STT_API_KEY` и `STT_MODEL` голос не распознаётся, бот отвечает «пришлите текстом». Whisper через Polza по умолчанию; `STT_API_KEY` — секрет |
| `VOICE_MAX_BYTES` | Лимит размера голосового файла в байтах: по умолчанию и максимум 20 МиБ (20971520), это лимит `getFile` Telegram. Больший файл не скачивается |
| `NOVITA_API_KEY`, `NOVITA_DOMAIN` | Песочницы (`NOVITA_API_KEY` — секрет) |
| `GITLAB_URL`, `GITLAB_TOKEN` | Push и MR (`GITLAB_TOKEN` — секрет; не нужен, если задан `gitlab.access_ref`) |
| `VAULT_MCP_URL`, `VAULT_MCP_TOKEN` | Vault с ключами владельца (D-45, `sandbox-profile`): адрес MCP-сервера, только `https://`, и Bearer-токен (секрет). Без них ссылки `vault:…` не разрешаются |
| `CLAUDE_CODE_OAUTH_TOKEN` | Токен подписки Claude для Claude Code в песочнице (`claude setup-token`, срок ~1 год; передаётся только в exec, D-18). Секрет |
| `AGENT_RUN_TIMEOUT_MIN`, `TESTS_TIMEOUT_MIN` | Лимит времени агента и гейта тестов (по умолчанию 60 и 15) |
| `AGENT_POLL_INTERVAL_SEC` | Пауза между опросами итога агента в worker, секунды, > 0 (по умолчанию 15; D-38) |
| `WORKER_POLL_INTERVAL_SEC` | Интервал опроса очереди worker, в секундах (по умолчанию 5) |
| `ADMIN_EMAIL`, `ADMIN_PASSWORD` | Консоль, `mvp-10` (`ADMIN_PASSWORD` — секрет) |

Новая переменная или сервис добавляется одним изменением в Compose, `.env.example` и эту таблицу.

## 10. Деплой

Dokploy, два Compose-стека:

- `deploy/db/docker-compose.yml` — Postgres отдельно; редеплой харнесса не трогает данные.
- `docker-compose.yml` — `migrate` (одноразовый, `alembic upgrade head`) → `server` и `worker`
  (`depends_on: service_completed_successfully`); `console` — `mvp-10` (D-39).

Все сервисы в внешней сети `dokploy-network`, наружу только `expose`, домен и HTTPS — в Dokploy.
CI: `.gitlab-ci.yml`, стадии `check → build → deploy`; образы в GitLab Registry с тегами
`:$CI_COMMIT_SHORT_SHA` и `:main`; деплой — `curl` на webhook Dokploy. Цель — до 10 минут.
