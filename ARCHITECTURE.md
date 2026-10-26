# ARCHITECTURE — agents-flow harness

Голосовой AI-харнесс: задача диктуется в Telegram, выполняется агентом (Claude Code) на локальной машине агента (D-64),
результат приходит как Merge Request в GitLab или Pull Request в GitHub (провайдер задаёт блок `repo` проекта, D-60, D-65), статус обновляется в том же чате.

Источник требований: [`docs/tz/tz-v5.md`](docs/tz/tz-v5.md). Принятые решения: [`docs/decisions.md`](docs/decisions.md).
План работ и статус: [`PLAN.md`](PLAN.md). Этот файл описывает **целевое** устройство системы и
обновляется тем же изменением, что и код (эндпоинт, статус, таблица, ENV, сервис).

## 1. Компоненты

```
 Telegram (голос/текст/кнопки)
        │ webhook (HTTPS, секрет)
        ▼
 ┌──────────────────────── server (FastAPI, async) ────────────────────────┐
 │ api/telegram ──► services ◄── mcp/agents-flow ◄─── агент на машине      │
 │                     │  ▲                         (токен задачи, HTTPS)  │
 │                     ▼  │                                                 │
 │              db (SQLAlchemy async) ──► Postgres (отдельный стек)         │
 │                     ▲                                                    │
 │ adapters: telegram, stt, polza, sandbox, local, gitlab, vault                           │
 └─────────────────────┼────────────────────────────────────────────────────┘
                       │ та же кодовая база, отдельный процесс
 ┌──────── worker (диспетчер, polling Postgres) ────────┐
 │ выбирает задачу → активирует машину → exec агента │──► локальная машина агента
 │ → гейты (секреты, коммит, тесты, push, MR)           │      └ claude, git, openspec
 └──────────────────────────────────────────────────────┘──► Git-провайдер: GitLab (MR) или GitHub (PR), адаптер `adapters/git`
```

| Компонент | Где | Назначение | Этап |
|---|---|---|---|
| server | `apps/server` | Webhook Telegram, MCP `agents-flow`, `GET /tasks/{id}`, health | MVP |
| worker | `apps/server` (команда `harness-server worker`), запускается на хосте как systemd user unit (D-64) | Диспетчер: polling очереди, песочница, агент, гейты | MVP |
| shared | `shared/` | Pydantic-модели и перечисления, общие для сервера и типов консоли | MVP |
| migrations | `db/migrations` | Alembic. Схема меняется только миграциями | MVP |
| agent | `apps/server/src/harness_server/agent_cli.py`, `services/machine.py` | Команда `agent init <project>` на машине агента: проверка prerequisites, каталоги, клон, память, маркер проекта (D-64) | MVP (`local-agent-machine`) |
| console | `apps/console` | React + shadcn/ui; в MVP — REST `/api/console/*` над теми же сервисами, MCP — после `operator-tokens` (D-39) | MVP (`mvp-10`) |
| shared-types | `packages/shared-types` | TS-типы для консоли, генерируются из `shared/` | MVP (`mvp-10`) |

## 2. Слои сервера

```
apps/server/src/harness_server/
├── app.py             # create_app(): FastAPI + смонтированный MCP, lifespan
├── cli.py             # harness-server: serve | worker | migrate | check-config | telegram set-webhook | sandbox status|pause|resume | reset-password
├── agent_cli.py       # agent init <project>: вход на машине агента (D-64), без БД и Telegram
├── settings.py        # pydantic-settings: ENV, путь к config/harness.yaml
├── config.py          # загрузка и валидация config/harness.yaml (sandbox; проекты — в каталоге сервера, D-65)
├── wiring.py          # композиционный корень бота: httpx-клиент, BotAdapters, BotContext (D-29)
├── api/               # HTTP-входы: tasks (POST /tasks, GET /tasks/{id}), telegram_webhook (POST /telegram/webhook), deps (сессия, admin-токен, секрет webhook), health. Без бизнес-логики
├── mcp/               # MCP agents-flow: auth (токен задачи), tools. Без бизнес-логики
├── telegram/          # parse.py (update → IncomingText / IncomingVoice / ButtonPress, dedup_key), render.py (тексты, карточка, callback_data, клавиатура); без I/O
├── services/          # ВСЯ бизнес-логика: tasks (mvp-03), intake (приём и восстановление апдейтов), notify (одно сообщение задачи), webhook (регистрация), context (BotContext); routing (классификация, уточнение, запись routings, mvp-05), status_report (ответ на запрос состояния, mvp-05), spec, sandboxes, delivery, machine (D-64: проверки prerequisites, каталоги, клон, память, маркер проекта)
├── domain/            # statuses.py (таблица переходов), errors.py (DomainError и коды), без I/O и sqlalchemy
├── db/                # base.py (Base, naming convention, enum-хелперы), ids.py (uuid7), session.py, models/ (9 таблиц)
├── adapters/          # внешние API за интерфейсами (Protocol) и фейки: telegram (httpx, mvp-04), stt (OpenAI-совместимый, mvp-04), polza (Router/PolzaRouter/FakeRouter, OpenAI-совместимый chat completions, mvp-05), sandbox (D-64), local (`LocalSandboxProvider`, D-64), gitlab
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
| `projects` | id (до 28 символов, D-28), name, voice_aliases, repo_provider, repo_base_url, repo_project, access_ref (ссылка vault или NULL — анонимный клон), default_branch, test_command, agent, agent_max_turns, status (`active`/`disabled`) | Каталог проектов (D-65): заводит оператор через консоль или API, ключ хранится только ссылкой |
| `tasks` | id, kind (`plan`/`implement`/`check`), workspace_id, parent_id, text, status, priority, source (`telegram`/`spec`/`mcp`/`api`), spec_item_id, branch, mr_url, result, tests_state, created_at, updated_at | Задача и канбан (представление по статусам) |
| `task_events` | id, task_id, status, text, source (`telegram`/`agent`/`worker`/`api`), created_at | Лента этапов для Telegram и журнала |
| `routings` | id, task_id (NULL для status, unknown и ожидающего уточнения), command_class (`work`/`status`/`unknown`), decision (`auto`/`clarify`/`fallback`), options (JSON), chosen_workspace_id, raw_response, confidence, error (причина запасного пути), source_text (до нажатия «Сделать задачу», затем NULL), resolved_at | Решение Polza и выбор пользователя (mvp-05, D-32, миграция `0003`) |
| `spec_items` | id, workspace_id, plan_task_id, change_id, key, text, status, last_checkpoint_id; UNIQUE (workspace_id, change_id, key) | Зеркало пунктов OpenSpec |
| `sandboxes` | id, provider_id, agent_type, status (`paused`/`active`/`error`), current_task_id, profile_version, agent_started_at (время запуска агента, NULL — не запускался), agent_pid (pid группы агента, NULL — неизвестен) | Локальная машина агента (`provider_id` из harness.yaml), подготовленная через `agent init`; колонки агента — серверный учёт запуска, файлам рабочей копии не доверяем (D-41, D-64, миграция `0004`) |
| `checkpoints` | id, task_id, summary, files (JSON), diff_redacted, next_step, status, tokens | Чекпоинты (MVP: от сервера после агента) |
| `telegram_messages` | task_id, chat_id, message_id, lines (JSON) | Одно обновляемое сообщение на задачу |
| `telegram_updates` | kind (`update`/`callback`) + external_id (составной PK), received_at, processed_at, payload (JSONB NULL) | Идемпотентность входа (A4). `payload` — нормализованный апдейт владельца (текст, голос или нажатие кнопки, без имён и `from`) до обработки; после обработки обнуляется (D-27) |
| `task_tokens` | id, task_id, token_hash (только хеш), role (`planner`/`implementer`), expires_at, revoked_at | Токены задачи для MCP (A2) |

Схема создаётся миграцией `0001` (mvp-03, `db/migrations/versions/`); миграция `0002` (mvp-04) добавляет
аддитивную nullable-колонку `telegram_updates.payload`. Перечисления — `VARCHAR(16)` с именованным
CHECK `ck_<таблица>_<колонка>` (D-22); первичные ключи — UUIDv7 из `db/ids.py` (D-21).

Строка `sandboxes` блокирует параллельные задачи на одной машине: если `current_task_id` задан, новую задачу
не резервируют. `LocalSandboxProvider.pause` — пустая операция; статус `paused` не означает остановку процессов
или освобождение ресурсов ОС. Подробности об управлении CLI — в [apps/server/README.md](apps/server/README.md).

Проекты (workspace) хранятся в таблице `projects` (D-65), а не в `config/harness.yaml`. Таблицы `agents`, `skills`,
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
4. **Планировщик.** Worker берёт задачу (`FOR UPDATE SKIP LOCKED`), блокирует строку локальной машины,
   выдаёт токен задачи, делает `git fetch` и worktree на `task/<plan_id>` от `origin/<default_branch>`, запускает
   `claude -p` с промптом планировщика. До активации worker проверяет маркер `projects/<id>.ready`: без него задача не запускается, причина `project_not_initialized` (выполнить `agent init <id>`, D-64). Планировщик пишет OpenSpec-изменение, коммитит, вызывает
   `sync_spec` и `create_task(kind=implement)` → задачи в `backlog`. Сервер пушит ветку плана, задача `plan` → `ready`.
5. **Исполнитель.** Worker берёт задачу из `backlog` по приоритету, worktree на `task/<id>` от
   `origin/task/<plan_id>` (в ней есть спецификация), агент реализует пункт и вызывает `report_task`.
6. **Гейты (сервер, exec, идемпотентно, три уровня — D-58).** Уровень 1 — базовые гейты безопасности в коде,
   всегда и без настроек: коммит, фильтр секретов по `git diff` (шаблоны + значения кредов и vault), запрещённые
   пути, лимиты diff и бинарных файлов, push только в `task/<id>`, идемпотентные push и MR (сначала поиск
   существующего по source branch). Уровень 2 — гейты проекта из `workspaces[].gates` (`preset` `code`/`none` +
   `test`): `code` запускает тесты (нет команды → `tests_state = no_tests`, не «зелёные»), `none` проверок качества
   не запускает. Без тестов задача получает `ready` с кнопкой «Принять» — решает владелец. Уровень 3 (гейты задачи,
   только добавляют) и остальные пресеты — `gates-tests-deploy`. Отчёт агента на результат не влияет. Итог —
   `ready`, сообщение «готова, MR создан» (для GitHub — «готова, PR создан», D-60). Мердж — руками.
7. **Очистка.** Удаление worktree и локальной ветки, отзыв токена задачи; после успешной очистки блокировка машины освобождается.

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

- Рабочая среда агента — локальная машина агента (D-64), одна на workspace, её id — `sandbox.provider_id` в
  `config/harness.yaml`. Протокол `SandboxProvider` (`adapters/sandbox/`: `connect`, `exec`, `write_file`,
  `read_file`, `pause`) реализует `LocalSandboxProvider` (`adapters/local/provider.py`). Метод `extend_timeout`
  из протокола удалён. Песочница берёт одну задачу: резервирование `FOR UPDATE SKIP LOCKED` (`services/sandboxes.reserve`).
- `LocalSandboxProvider`: `connect` проверяет, что id совпадает с `provider_id`, и выполняет пробную команду `true`;
  `pause` — пустая операция; `exec` запускает команду в отдельной группе процессов (`start_new_session`), ограничивает
  вывод и по таймауту убивает всю группу (`killpg`); работать от root (uid 0) отказывается.
- Окружение подпроцессов очищено: белый список `PATH`, `HOME`, `USER`, `LOGNAME`, `LANG`, `LC_*`, `TERM` плюс явные
  `envs` (имена проверяются, NUL в значениях запрещён). Секреты worker (`DATABASE_URL`, `TELEGRAM_BOT_TOKEN`) в
  подпроцессах не видны; значения не попадают в argv.
- Файлы песочницы: `write_file` атомарный, права 0600 у файлов и 0700 у каталогов; `read_file` при отсутствии файла
  возвращает `None`.
- **История перехода (D-64 заменило Novita и bootstrap локальной машиной агента).** Приёмка пунктов `local-agent-machine`
  остаётся за владельцем; статус выполнения и незавершённые проверки ведутся в `openspec/changes/local-agent-machine/tasks.md`.
- Подготовка машины — команда `agent init <project>` (`agent_cli.py`, `services/machine.py`, D-64). Запускается от
  непривилегированного пользователя, без `sudo`:
  1. Проверка prerequisites (`check_prerequisites`): `git`, `node` ≥ 22.13, `npm`, клиент агента (`AGENT_CLIENT_COMMAND`,
     TODO: статус как ENV не подтверждён), `openspec`; при памяти — `memory` и `docker compose version`. Один отчёт, код 3.
     Инструменты ставит оператор, харнесс их не ставит.
  2. Каталоги `~/.harness/{bin,tasks,worktrees,projects,memory}` и `~/work` (0700); `mcp.json` с плейсхолдерами (0600).
     Значения секретов в файлах не пишутся.
  3. Клон и fetch репозитория workspace (`sync_clone`): ключ только в env git-команды; без ключа клон анонимный, с предупреждением.
  4. Память, если задан `sandbox.memory`: `.memory/` добавляется в `.git/info/exclude`, `memory init` получает
     `EMBEDDING_API_KEY` только в env команды, маркер `memory/<id>.ready`. Без блока `sandbox.memory` шаг пропускается.
  5. Маркер `projects/<id>.ready` ставится в конце и снимается в начале повторного запуска (задача 4.5, не принята).
- Инструменты и зависимости проекта устанавливает оператор на машине агента; `agent init` проверяет prerequisites и
  подключает проект. `ensure-docker.sh` и установка memory-agent харнессом не используются (D-44, D-47, D-51, D-63 заменены D-64).
- Ключ репозитория workspace уходит git заголовком `Authorization: Basic` только на префикс адреса его репозитория
  `<base_url>/<project>.git/` (`GIT_CONFIG_*` в env клона и fetch, D-52, D-60). Пользователь Basic: `oauth2` для GitLab,
  `x-access-token` для GitHub. Редиректы выключены. Клон и fetch делает `agent init` (`sync_clone`) отдельной
  git-командой на workspace; команда с ключом перекрывает настройки `.git/config`, `~/.gitconfig` и `/etc/gitconfig`
  (прокси, TLS, хуки, помощники учётных данных) и идёт по адресу из конфига, а не по `origin` (D-62). Workspace без ключа клонируется анонимно. Остаточный риск: агент с
  выполнением кода на машине агента может перехватить ключ через профиль оболочки или `sudo` (D-62, R-1).
  Задача без `repo.access_ref` уходит в `error` с причиной `repo_access_ref` до активации песочницы.
- Ключи из vault (D-45, `adapters/vault`, MCP-клиент на официальном SDK): ссылка `vault:<project>/<service>/<name>`
  в `harness.yaml` (`workspaces[].repo.access_ref`, `sandbox.memory.embedding_ref`); значение берётся на каждую команду и
  передаётся только в env (`agent init`, активация, запуск агента). Без vault ссылка даёт `not_configured`. ENV
  `GITLAB_TOKEN`/`GITLAB_URL` больше не читаются (D-60). Сбой vault при активации — задача `error` с причиной `vault`.
- Память проекта (`sandbox-profile`, D-47): при активации `git checkout --detach origin/<default_branch>` клона
  workspace и `memory sync --path <клон>`; сбой не роняет задачу (предупреждение в лог). Агент получает
  `HARNESS_MEMORY_PROJECT=~/work/<id>`; индекс по worktree не строится.
- Креды (`CLAUDE_CODE_OAUTH_TOKEN`, ключи репозиториев, токен задачи) передаются только в env конкретной exec-команды
  и не записываются на диск песочницы. Claude Code авторизуется подпиской через `CLAUDE_CODE_OAUTH_TOKEN`
  (D-18); `ANTHROPIC_API_KEY` в песочнице не задаётся: по документации Claude Code он перекрывает OAuth-токен (спайком не проверялось). `--bare` не используется. Риски токена подписки (экфильтрация, лимиты по окнам) — в `openspec/changes/archive/2026-10-19-mvp-06-sandbox-runtime/design.md`, Risks.
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
| Агент ослабляет проверки | Базовые гейты в коде, не настраиваются; гейты задачи только добавляют; файл гейтов — из основной ветки; `.harness/**`, `.env*` в diff запрещены (D-58) |
| SQL-инъекции | Только SQLAlchemy ORM с параметрами, Pydantic на входе |
| Гонка за песочницу | `SELECT … FOR UPDATE SKIP LOCKED` на `sandboxes`, активация идемпотентна (A5) |
| Секреты worker в подпроцессах агента | Очищенное окружение (белый список), значения секретов не в argv (`adapters/local`, D-64) |
| Перехват | HTTPS через Traefik Dokploy; наружу порты не публикуются |

## 9. Конфигурация и ENV

Каталог проектов (D-65): источник проектов — сервер. Проект заводится в консоли (`apps/console`, этап `mvp-10`) или через API `/api/console/projects` (`POST`, `GET`, `GET /{id}`, `PATCH /{id}`, `POST /{id}/disable`) под `HARNESS_ADMIN_TOKEN`. Ответ `GET /api/projects/{id}/settings` содержит поля локального конфига без значений ключей. Отключённый проект не принимает новые задачи и не выдаётся машине агента; задачи в работе доходят до своего статуса. `harness.yaml` с блоком `workspaces` или секцией `gitlab` сервер не загружает. `id` проекта: латиница, цифры и дефисы, не длиннее 28 символов.

`config/harness.yaml` (путь в `HARNESS_CONFIG`, без секретов, пример — `config/harness.example.yaml`):
sandbox (provider_id,
опционально `git_author` (`name`, `email`: автор коммитов агента, передаётся агенту env `GIT_AUTHOR_*`/`GIT_COMMITTER_*`, по умолчанию `agents-flow`), опционально `memory`: `embedding_ref` (поля `repo` и `ref` сняты, D-64)). Блок `repo` проекта (D-60): `provider` (`github` | `gitlab`), `base_url`
(только https; по умолчанию `https://github.com` / `https://gitlab.com`), `project` (`owner/name` для GitHub,
`group[/subgroup]/name` для GitLab), опционально `access_ref` — ссылка `vault:…` на ключ записи репозитория. Ключи с сегментами `token`/`tokens`, `key`, `password`/`passwd`/`pwd`, `secret`/`secrets`, `apikey`,
`credential`/`credentials` сервер отклоняет на любом уровне. `repo.base_url` с учётными данными (`user@host`) тоже
отклоняется (D-26); ключ репозитория задаётся только ссылкой vault. Секция `gitlab:` и поле `gitlab_project` удалены
(D-60): конфиг с ними не загружается, сообщение называет поля для переноса (`docs/deployment.md`, «Переход на D-60»).

Обязательные ENV (решение D-20): `DATABASE_URL`, `HARNESS_CONFIG`, `HARNESS_SECRET_KEY`, `TELEGRAM_BOT_TOKEN`,
`TELEGRAM_CHAT_ID`, `TELEGRAM_WEBHOOK_SECRET`. Сервер и worker не стартуют, если их нет или они пустые.
Остальные опциональны, пока их не использует свой этап («с этапа» — в `.env.example`).
Секреты в таблице помечены «секрет»; в коде это `SecretStr`.

| ENV | Назначение |
|---|---|
| `DATABASE_URL` | **Обязательная.** Postgres (asyncpg). Секрет: содержит пароль |
| `HARNESS_CONFIG` | **Обязательная.** Путь к `harness.yaml` |
| `HARNESS_SECRET_KEY` | **Обязательная.** Соль/ключ для хешей токенов. Секрет |
| `HARNESS_PUBLIC_URL` | Публичный HTTPS-адрес сервера: им пользуется MCP-конфиг агента и `harness-server telegram set-webhook` (адрес webhook = этот адрес + `/telegram/webhook`); только `https://`, без query и fragment |
| `HARNESS_ADMIN_TOKEN` | Временный операторский bearer для `POST /tasks`, `GET /tasks/{id}` (до `operator-tokens`). Если задан, должен быть не короче 32 символов (`openssl rand -hex 32`), иначе сервер не стартует. Не задан — `/tasks` отвечает 401 (fail-closed, D-23). Секрет |
| `TELEGRAM_BOT_TOKEN` | **Обязательная.** Токен бота. Секрет |
| `TELEGRAM_CHAT_ID` | **Обязательная.** Владелец бота: положительное целое число, id личного чата. Групповые чаты не поддерживаются (D-30) |
| `TELEGRAM_WEBHOOK_SECRET` | **Обязательная.** Секрет webhook: от 32 до 256 символов `A-Za-z0-9_-` (`openssl rand -hex 32`), иначе сервер не стартует. Секрет |
| `TELEGRAM_API_URL` | Адрес Bot API. Необязательная, по умолчанию `https://api.telegram.org`; пустое значение = по умолчанию. Прокси владельца (Cloudflare Worker) для сервера в РФ: только `https://`, без учётных данных, query и fragment; слеш в конце убирается. Адрес используется всеми вызовами Bot API, включая скачивание файлов и `set-webhook` (D-61) |
| `TELEGRAM_WEBHOOK_URL` | Адрес, на который Telegram шлёт апдейты. Необязательная; пусто = `HARNESS_PUBLIC_URL` + `/telegram/webhook`. Для сервера в РФ — маршрут Worker `/tg-webhook`, который пересылает POST на `HARNESS_PUBLIC_URL/telegram/webhook`. Правила как у `TELEGRAM_API_URL` (https, без учётных данных, query и fragment). Учитывает `harness-server telegram set-webhook` (D-61) |
| `POLZA_AI_URL`, `POLZA_AI_KEY`, `POLZA_AI_MODEL`, `ROUTING_MIN_CONFIDENCE` | Классификация и порог уверенности (mvp-05). `POLZA_AI_URL` по умолчанию `https://polza.ai/api/v1`, только `https://`; `POLZA_AI_KEY` — секрет; без ключа или модели маршрутизатор выключен (запасной путь); `ROUTING_MIN_CONFIDENCE` по умолчанию 0.6 (D-33) |
| `STT_PROVIDER`, `STT_API_URL`, `STT_API_KEY`, `STT_MODEL` | Распознавание речи. `STT_PROVIDER` — только `openai` (OpenAI-совместимый протокол) или не задан; без `STT_API_URL`, `STT_API_KEY` и `STT_MODEL` голос не распознаётся, бот отвечает «пришлите текстом». Whisper через Polza по умолчанию; `STT_API_KEY` — секрет |
| `VOICE_MAX_BYTES` | Лимит размера голосового файла в байтах: по умолчанию и максимум 20 МиБ (20971520), это лимит `getFile` Telegram. Больший файл не скачивается |
| `VAULT_MCP_URL`, `VAULT_MCP_TOKEN` | Vault с ключами владельца (D-45): адрес MCP-сервера и Bearer-токен. Нужны `agent init`; токен — секрет |
| `CLAUDE_CODE_OAUTH_TOKEN` | Токен подписки Claude для Claude Code на машине агента (`claude setup-token`; передаётся только процессу агента, D-18). Секрет |
| `AGENT_RUN_TIMEOUT_MIN`, `TESTS_TIMEOUT_MIN` | Лимит времени агента и гейта тестов (по умолчанию 60 и 15) |
| `AGENT_POLL_INTERVAL_SEC` | Пауза между опросами итога агента в worker, секунды, > 0 (по умолчанию 15; D-38) |
| `WORKER_POLL_INTERVAL_SEC` | Интервал опроса очереди worker, в секундах (по умолчанию 5) |
| `ADMIN_EMAIL`, `ADMIN_PASSWORD` | Консоль, `mvp-10` (`ADMIN_PASSWORD` — секрет) |

Команда `agent init <workspace>` (D-64, D-65) читает `HARNESS_CONFIG`, `VAULT_MCP_URL`, `VAULT_MCP_TOKEN`, `HARNESS_PUBLIC_URL` и
`HARNESS_ADMIN_TOKEN`: настройки проекта запрашивает у сервера по `GET /api/projects/{id}/settings` (адрес https, http — только localhost), локальный конфиг пишет в `~/.harness/projects/<id>.yaml` с правами 0600 и пометкой «сгенерирован, не править». `DATABASE_URL` и Telegram ей не нужны. Значения секретов в документах не указываются.
TODO: `AGENT_CLIENT_COMMAND` встречается в проверке prerequisites (задача 4.1), но как ENV не подтверждён, в таблицу не внесён.

Новая переменная или сервис добавляется одним изменением в Compose, `.env.example` и эту таблицу.

## 10. Деплой

Dokploy, два Compose-стека:

- `deploy/db/docker-compose.yml` — Postgres отдельно; редеплой харнесса не трогает данные.
- `docker-compose.yml` — `migrate` (одноразовый, `alembic upgrade head`) → `server`; `console` — `mvp-10` (D-39).
- Worker работает на хосте как systemd user unit рядом с локальной машиной агента; Compose БД публикует порт 5432 только на loopback хоста (`127.0.0.1`), сохраняя внешнюю сеть и volume. Контейнерный server подключается через Docker-сеть, worker — через loopback. См. [инструкцию деплоя](docs/deployment.md) и [настройку worker](deploy/worker/README.md).

Compose-сервисы используют внешнюю сеть `dokploy-network`; Postgres additionally binds only to host loopback. Домен и HTTPS — в Dokploy.
CI: `.gitlab-ci.yml`, стадии `check → build → deploy`; образы в GitLab Registry с тегами
`:$CI_COMMIT_SHORT_SHA` и `:main`; деплой — `curl` на webhook Dokploy. Цель — до 10 минут.
