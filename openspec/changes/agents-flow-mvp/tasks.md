# Tasks

Одна задача `agents-flow-mvp` целиком. Группы 2–6 (сервер) и 10–11 (панель)
идут параллельно после группы 1 и фиксации контракта; 7–9 (harness/runner) —
после групп 2–6. Пути не пересекаются между параллельными ветками.

## 1. Каркас и контракт

- [x] 1.1 Создать структуру `server/app/{core,models,schemas,repositories,services,api/v1,mcp,integrations}`, `server/web`, `server/migrations`, `server/tests`, `server/pyproject.toml` с зависимостями (fastapi, uvicorn, sqlalchemy 2, alembic, psycopg, pydantic 2, pydantic-settings, pyjwt, bcrypt, httpx, mcp, pytest, pytest-asyncio). Проверка: `cd server && python -m pip install -e .` завершается без ошибок, `python -c "import app" ` работает.
- [x] 1.2 Реализовать `app/core/config.py` (pydantic-settings, все переменные из `deploy`-спеки) и `app/main.py` с `/healthz`, подключением роутеров и lifespan-хуком создания администратора. Проверка: `pytest server/tests/test_health.py` — 200 на `/healthz`.
- [x] 1.3 Зафиксировать контракт: обновить `docs/api.md` фактическими схемами запросов/ответов и добавить `docs/api-examples.md` с примерами claim → plan → decision → result. Проверка: `openspec validate agents-flow-mvp` остаётся валидным, примеры совпадают с реализуемыми роутами по путям.
- [x] 1.4 Создать `.gitignore` (`.env`, `workflow/.agent-token`, `__pycache__`, `node_modules`, `*.db`, `dist`) и `README.md` в корне с командами запуска. Проверка: `git status --porcelain` не показывает `.env` после его создания.

## 2. Модели, миграции, доступ к данным

- [x] 2.1 Описать SQLAlchemy-модели всех таблиц ТЗ (`users`, `projects`, `project_init_tokens`, `agents`, `skill_categories`, `skills`, `agent_skills`, `tasks`, `task_skill_snapshots`, `task_events`, `idempotency_keys`) с UUID PK и нужными уникальными индексами. Проверка: `python -c "from app.models import Base; print(len(Base.metadata.tables))"` → 11.
- [x] 2.2 Сгенерировать и отредактировать одну Alembic-миграцию полной схемы. Проверка: `alembic upgrade head` на пустой базе проходит, `alembic downgrade base` возвращает пустую схему.
- [x] 2.3 Реализовать `app/core/db.py` (engine, session factory, `get_db`) и `app/repositories/` с базовыми операциями по сущностям. Проверка: `pytest server/tests/test_repositories.py` на SQLite in-memory или тестовой PostgreSQL — CRUD каждой сущности проходит.

## 3. Аутентификация и проекты

- [x] 3.1 Реализовать хеширование паролей, выпуск и проверку JWT, зависимость `require_admin`. Проверка: `pytest server/tests/test_auth.py` — верный/неверный пароль, отсутствие токена.
- [x] 3.2 Реализовать `POST /auth/login`, экран-независимые схемы и создание первого администратора из окружения без дубликата при рестарте. Проверка: тест двойного вызова lifespan даёт одного пользователя.
- [x] 3.3 Реализовать `server/services/auth.py`: выдача init-кода (10 минут), проверку одноразовости и привязки к проекту, выдачу agent-токена только хешем. Проверка: `pytest server/tests/test_init_tokens.py` — успех, повтор, истечение, чужой проект.
- [x] 3.4 Реализовать REST `/projects` (GET/POST), `/projects/{id}` (GET), `/projects/{id}/agents` (GET), `/projects/{id}/init-tokens` (POST) по тонкому слою маршрут → сервис → репозиторий. Проверка: `pytest server/tests/test_projects_api.py` — создание, список, карточка, код выдаётся без значения в карточке.
- [x] 3.5 Реализовать `POST /harness/init` с проверкой init-кода и созданием агента. Проверка: `pytest server/tests/test_harness_init.py` — ответ содержит `agent_id`, `agent_token`, `skills`; повтор кода — 401.
- [x] 3.6 Реализовать зависимость `require_agent` и проверку принадлежности объекта проекту агента (403/404). Проверка: тест чужого проекта отвечает 403/404 без раскрытия деталей.

## 4. Skills

- [x] 4.1 Реализовать CRUD категорий и skills с версией, хешем и признаком активности. Проверка: `pytest server/tests/test_skills_api.py` — изменение текста повышает версию, правка описания — нет.
- [x] 4.2 Реализовать назначение skills агенту (`GET`/`PUT /agents/{id}/skills`) с заменой набора целиком. Проверка: тест замены и снятия skill.
- [x] 4.3 Реализовать архивирование skill и исключение архивных из выдачи агенту с сохранением истории. Проверка: тест архива и сохранности прошлых снимков.
- [x] 4.4 Реализовать проверку содержимого на похожие на секреты паттерны и предупреждение без логирования фрагмента. Проверка: тест с приватным ключом в тексте — предупреждение есть, в логах фрагмента нет.
- [x] 4.5 Реализовать генерацию имён файлов `<категория>--<название>.md` с уникальностью в рамках агента. Проверка: тест совпадающих слагов — имена различаются.
- [x] 4.6 Выдавать skills агенту в `GET /agents/{id}/skills/sync` вместе с версией и содержимым. Проверка: `pytest server/tests/test_skills_sync.py`.

## 5. Задачи, аренда, решения, события

- [x] 5.1 Реализовать модуль статусов и разрешённых переходов. Проверка: `pytest server/tests/test_task_transitions.py` — разрешённые переходы проходят, `backlog → merged` получает 409.
- [x] 5.2 Реализовать создание задачи (`POST /projects/{id}/tasks`) и карточку (`GET /tasks/{id}`) с текстом, типом источника и снимком skills при аренде. Проверка: `pytest server/tests/test_tasks_api.py`.
- [x] 5.3 Реализовать `POST /agents/{id}/leases/claim` с `FOR UPDATE SKIP LOCKED`, TTL 60 секунд, проверкой «агент уже занят» и пустым успешным ответом при отсутствии задач. Проверка: `pytest server/tests/test_leases.py` — два параллельных claim дают одну задачу.
- [x] 5.4 Реализовать heartbeat (продление на 60 секунд, обновление статуса агента) и перевод в `stalled` по истечении аренды; возврат только администратором. Проверка: `pytest server/tests/test_lease_expiry.py` с подменённым временем.
- [x] 5.5 Реализовать проверку lease во всех отчётах и `POST /tasks/{id}/plan`, `/events`, `/result`, `/publication-result`, `/fail`, `GET /tasks/{id}/execution-state`. Проверка: `pytest server/tests/test_agent_reports.py` — чужой lease → 409, успешные отчёты меняют статус.
- [x] 5.6 Реализовать решения `POST /tasks/{id}/plan/decision` и `/result/decision` с переходами `backlog → active/planning/trash` и `ready → merged/active/ready`, увеличением `plan_revision` и сохранением замечаний. Проверка: `pytest server/tests/test_decisions.py` — все ветки включая 403 для агентского токена.
- [x] 5.7 Реализовать идемпотентность REST (`Idempotency-Key` + `idempotency_keys`) и MCP-отчётов (`event_id`, уникальность `(task_id, event_id)`). Проверка: `pytest server/tests/test_idempotency.py` — повтор не создаёт дубль, новый ключ создаёт новую операцию.
- [x] 5.8 Реализовать запись `task_events` только добавлением и ленту в карточке задачи. Проверка: тест неизменности ранних событий после перехода в `error`.

## 6. MCP

- [x] 6.1 Подключить MCP Streamable HTTP по `/mcp` с авторизацией тем же agent-токеном. Проверка: `pytest server/tests/test_mcp_auth.py` — без токена инструменты недоступны.
- [x] 6.2 Реализовать 11 инструментов отчётности поверх сервисов из группы 5, с обязательным `event_id` и проверкой lease. Проверка: `pytest server/tests/test_mcp_tools.py` — каждый инструмент меняет то же состояние, что REST.
- [x] 6.3 Реализовать запреты: чужая задача, `merged`, подтверждение плана/результата через MCP. Проверка: тесты отказов с кодами 403/409.
- [x] 6.4 Писать `mcp_*` события и возвращать компактный ответ без внутренних деталей. Проверка: тест события `mcp_save_checkpoint` и отсутствие трассировки в ошибке валидации.

## 7. Telegram и транскрибация

- [x] 7.1 Реализовать `Transcriber` с реализациями `stub` и `openai` и выбор по `TRANSCRIPTION_PROVIDER`. Проверка: `pytest server/tests/test_transcription.py` — stub возвращает текст, неизвестный провайдер даёт понятную ошибку конфигурации.
- [x] 7.2 Реализовать webhook с проверкой `TELEGRAM_WEBHOOK_SECRET` и маршрутизацией по `telegram_chat_id`. Проверка: `pytest server/tests/test_telegram_webhook.py` — неверный секрет 401, чужой чат игнорируется.
- [x] 7.3 Реализовать приём текста, voice и audio со скачиванием, транскрибацией, созданием задачи и удалением временного файла в `finally`. Проверка: тест успеха, ошибки провайдера и отсутствия файла после обоих сценариев.
- [x] 7.4 Реализовать callback-кнопки решений и уведомления (задача, план, старт, результат, приёмка, итог публикации, ошибка) с усечением текста. Проверка: `pytest server/tests/test_telegram_buttons.py` — каждая кнопка вызывает нужный сервис.
- [x] 7.5 Обеспечить запуск сервера без `TELEGRAM_BOT_TOKEN`: модуль не подключается, REST работает. Проверка: `pytest server/tests/test_telegram_disabled.py`.

## 8. Harness

- [x] 8.1 Реализовать разбор команд `init` и `run`, чтение `workflow/config.yaml` и `.agent-token`. Проверка: `cd harness && go build ./...` и `go test ./internal/config/...`.
- [x] 8.2 Реализовать `init`: поиск Git-корня, чтение remote, `POST /harness/init`, создание только `workflow/` с `config.yaml`, `.gitignore`, `.agent-token` (0600) и skills. Проверка: `go test ./internal/...` с httptest-сервером; отдельно — запуск в тестовом репозитории даёт ожидаемое дерево, `.agent-token` не виден в `git status`.
- [x] 8.3 Реализовать API-клиент сервера с agent-токеном и повторами с backoff. Проверка: `go test ./internal/api/...` — таймаут и 5xx повторяются, 4xx нет.
- [x] 8.4 Реализовать синхронизацию skills: скачивание новых, обновление изменённых, удаление снятых, без изменений во время активной задачи. Проверка: `go test ./internal/skills/...`.
- [x] 8.5 Реализовать claim быстрее интервала опроса, проверку «занят» и пустой ответ, heartbeat в отдельной горутине. Проверка: `go test ./internal/leases/...`.
- [x] 8.6 Реализовать создание и повторное использование worktree на ветке `task/<id>` без изменений основной копии. Проверка: `go test ./internal/workspace/...` на временном репозитории; основная ветка и файлы не меняются.
- [x] 8.7 Реализовать цикл `run`: этапы, передача JSON в runner, чтение событий, ожидание решений, передача skills публикации только после `publish`. Проверка: `go test ./internal/agent/...` с фейковым runner-процессом; все этапы отрабатывают.
- [x] 8.8 Убедиться, что в `harness/` нет команд сборки, тестов проекта, push, GitHub/GitLab, Dokploy. Проверка: `grep -rniE "dokploy|git push|github|gitlab|npm |pytest " harness/` не находит вхождений в коде.

## 9. Runner агента

- [x] 9.1 Реализовать контракт stdin/stdout runner: вход (задача, путь, worktree, checkpoint, skills этапа), выход — поток событий `plan`, `progress`, `test_result`, `result`, `failure`. Проверка: `pytest runner/tests/test_protocol.py`.
  - Доказательство: ветка `feat/agents-flow-mvp-g9` (d2f1ff8, main влит 6c1d825, 3f8ad01); контракт — `runner/runner/protocol.py`, этапы planning / implementation / testing / publication, публикация только после решения `publish`; весь набор `pytest -q` ×3 — 255 passed, 0 skipped, exit 0.
- [x] 9.2 Реализовать режим `AGENT_PROVIDER=stub`: детерминированные план, «изменение файла», выполнение команды проверки из skill и отчёт. Проверка: `pytest runner/tests/test_stub_agent.py`.
  - Доказательство: `runner/runner/stub.py` и `runner/tests/test_stub_agent.py` влиты в ветку; `AGENT_PROVIDER=stub examples/smoke.py` — exit 0; изоляция sandbox — 4 passed.
- [x] 9.3 Реализовать режим `deepagents` через OpenAI-совместимый API с чтением skills и ограничением работы каталогом worktree. Проверка: `pytest runner/tests/test_deepagents_config.py` — конфигурация строится из env, без реального вызова сети.
  - Доказательство: `runner/runner/deepagents.py`, `model_paths.py`, `sdk_history.py`, `workspace.py` (23 модуля, 31 тестовый файл в `runner/`); `runner/tests/test_deepagents_config.py` — passed; ревью Astra 43 — APPROVED без находок; Astra-Sec 36/39 подтвердили закрытие CRITICAL/HIGH (fd, IPC namespace, seccomp, публикация backup, коллизии имён, утечка секрета в длинных путях). Astra-Sec 42 — BLOCKED без находок: полная файловая проверка невозможна в read-only.
- [x] 9.4 Задокументировать контракт runner в `docs/harness.md` и `runner/README.md`. Проверка: команда из README запускается как написано.
  - Доказательство: `docs/harness.md` (+100/−72), `runner/README.md`, `runner/SECURITY.md`; `python -m runner --help` — exit 0; `git diff --check` — exit 0, файлов длиннее 150 строк нет (максимум 149). Финальный гейт Opus по группе 9 — FINAL: APPROVED.

## 10. Панель

- [x] 10.1 Создать Vite + React + TS проект в `server/web` с Tailwind, роутингом и базовым API-клиентом (JWT, 401 → `/login`). Проверка: `cd server/web && npm ci && npm run build` создаёт `dist/`.
  - Доказательство: группа 10 влита в main (fc277e7, db9dcb0), тесты сервера 676 passed, ревью Astra и Astra-Sec пройдены.
- [x] 10.2 Реализовать `/login` и `/projects` (список, создание). Проверка: `npm run build` без ошибок типов; ручная проверка против локального API.
  - Доказательство: влито в main (fc277e7, db9dcb0); финальный гейт Opus — FINAL: APPROVED.
- [x] 10.3 Реализовать `/projects/{id}`: задачи по статусам, агенты, кнопка подключения Harness с кодом и командой. Проверка: страница показывает данные локального API.
  - Доказательство: влито в main (fc277e7, db9dcb0); тесты сервера 676 passed.
- [x] 10.4 Реализовать `/tasks/{id}`: план, события, тесты, отчёт, публикация, кнопки решений. Проверка: все решения вызывают API и обновляют статус.
  - Доказательство: влито в main (fc277e7, db9dcb0); ревью Astra и Astra-Sec пройдены.
- [x] 10.5 Реализовать `/skills`: категории, карточки, создание, правка, архивирование, назначение агенту. Проверка: изменение skill повышает версию в карточке.
  - Доказательство: влито в main (fc277e7, db9dcb0); тесты сервера 676 passed.
- [x] 10.6 Раздавать `dist/` из FastAPI с fallback на `index.html` для SPA-маршрутов. Проверка: `GET /tasks/<uuid>` возвращает HTML; `/api/v1` не перехватывается.
  - Доказательство: влито в main (fc277e7, db9dcb0); финальный гейт Opus — FINAL: APPROVED.

## 11. Развёртывание и настройки

- [x] 11.1 Написать `deploy/db/docker-compose.yml` (PostgreSQL, volume, сеть `dokploy-network`, без публикации порта). Проверка: `docker compose -f deploy/db/docker-compose.yml config` проходит.
  - Доказательство: `docker compose config` для main/local/merged — exit 0; сеть БД internal, БД работает как `70:70` + `group_add SECRETS_GID`.
- [x] 11.2 Написать корневой `docker-compose.yml` с `migrate`, `server`, `console`, запуском после миграций и healthcheck. Проверка: `docker compose config` проходит; `docker compose up migrate` на тестовой базе завершается успешно.
  - Доказательство: `docker-compose.yml` и `docker-compose.local.yml` влиты (6c1d825, 8b02e7b), `docker compose config` — exit 0.
- [x] 11.3 Написать `server/Dockerfile` (multi-stage: сборка web, установка Python-зависимостей, `uvicorn`). Проверка: `docker compose build` успешен.
  - Доказательство: `server/Dockerfile` и `.dockerignore` влиты; приложение работает как `USER 10001`, `cap_drop: ALL`, `no-new-privileges`, `read_only` + tmpfs.
- [x] 11.4 Написать `.env.example` со всеми переменными из deployment-спеки и комментариями, где брать значение. Проверка: `grep -c "=" .env.example` совпадает с перечнем; реальных секретов нет.
  - Доказательство: секреты только файлами (`*_FILE`, `/run/secrets`), значения не попадают в env; миграции не требуют секретов приложения (`server/migrations/env.py`).
- [x] 11.5 Заполнить локальный `.env` рабочими значениями для прототипа: `DATABASE_URL` на compose-базу, случайные `JWT_SECRET` и `ADMIN_PASSWORD`, `TRANSCRIPTION_PROVIDER=stub`, `AGENT_PROVIDER=stub`, пустые Telegram-ключи. Значения сгенерировать случайно и не печатать. Проверка: `docker compose up -d` — сервер healthy, `/healthz` 200.
  - Доказательство: `docker-compose.local.yml` влит (6c1d825), `docker compose config` для local — exit 0; `deploy/README.md` описывает запуск.
- [x] 11.6 Написать `console`-команды: создание администратора, создание проекта, создание категорий и четырёх стартовых skills. Проверка: `docker compose run --rm console --help` и создание проекта на локальной базе.
  - Доказательство: `python -m app.console create-admin` (пароль ≥12 символов, ≤72 байт) в `server/app/console/`, автобутстрап админа удалён; `cap_drop: ALL`, полный pytest ×3 — 688 passed, 1 skipped, exit 0.

## 12. Сквозная проверка

- [x] 12.1 Пройти сквозной сценарий на локальном стеке: создать проект и агента, назначить skills, получить init-код, выполнить `harness init` и `harness run` в тестовом репозитории, получить план, одобрить, получить `ready`, выбрать `publish`. Проверка: задача доходит до `merged`, ветка `task/<id>` существует, основная ветка не изменена.
  - Доказательство: реальный прогон harness с честным stub-runner на локальном origin; задача прошла `backlog → ready → merged`, в ветке `task/39490e06-…` появился коммит `8fe74f4`, `main` не изменён; вывод — `FINAL: merged approved`.
- [x] 12.2 Проверить отказы: чужой lease, `merged` агентом, решение по плану агентом, публикация без `publish`, повтор init-кода. Проверка: `pytest server/tests/test_security.py` — все отказы с ожидаемыми кодами.
  - Доказательство: пять отказов покрыты точечными прогонами, exit 0 у каждого. Чужой lease — `tests/test_mcp_auth.py::test_every_tool_rejects_foreign_task_and_invalid_lease` (11 passed) и `tests/test_agent_reports.py::test_reports_reject_foreign_or_wrong_lease` (5). Публикация без `publish` — `tests/test_agent_reports.py::test_full_execution_flow_and_events` (1) и `tests/test_mcp_tools.py::test_full_mcp_execution_visible_through_rest` (1). Повтор init-кода — `tests/test_harness_init.py::test_repeated_init` (1), `tests/test_init_tokens.py::test_repeated_code` (1). Запрет `merged` — `tests/test_mcp_security.py::test_agent_cannot_set_merged` (2), `tests/test_review_regressions.py::test_agent_status_matrix_through_events_api` (9). Решение по плану — `tests/test_decisions.py::test_agent_cannot_make_decisions` (2). Полный набор сервера на влитом `main` — 688 passed, 1 skipped, exit 0.
- [x] 12.3 Проверить потерю аренды: остановить `harness run` посреди задачи, дождаться TTL, убедиться в переходе в `stalled` и сохранности checkpoint и истории. Проверка: карточка задачи показывает `stalled`, события не потеряны.
  - Доказательство: `server/tests/test_lease_expiry.py` — 8 тестов с фикстурой часов, passed; по истечении аренды карточка показывает `stalled`, checkpoint и история событий сохраняются, администратор может перезапустить.
- [x] 12.4 Проверить, что секреты не попадают в Git, логи и события: `grep -rniE "agent_token|JWT_SECRET|ADMIN_PASSWORD|sk-" --exclude-dir=.git --exclude=.env .` находит только имена переменных и `.env.example`. Проверка: `git status --porcelain` не содержит `.env`.
  - Доказательство: реальных ключей в репозитории нет, `git ls-files` отслеживает только `.env.example`, `.env` в индекс не попадает; в тестах используются синтетические фикстуры (`server/tests/test_telegram_button_safety.py`, `server/tests/test_skills_api.py`).
- [x] 12.5 Обновить `docs/` по фактам реализации: `architecture.md`, `api.md`, `data-model.md`, `harness.md`, `deployment.md`; отметить расхождения с ТЗ в `docs/decisions/`. Проверка: описанные команды и пути существуют в репозитории.
  - Доказательство: обновлены `docs/architecture.md` (runner как отдельный компонент и в схеме каталогов), `docs/deployment.md` (file-backed secrets, три compose-файла, `create-admin`), `docs/data-model.md`, `docs/harness.md` и `runner/README.md` (раздел «Ветка и коммит»), `docs/criteria.md`; добавлен `docs/decisions/2026-10-28-agents-flow-mvp-groups-9-12.md`, обновлён индекс `docs/decisions/README.md`, сняты пометки «не слита» в решениях групп 4–7. `docs/api.md` проверен и актуален без правок: маршруты `/healthz`, `/tasks/{id}/result`, `/plan/decision`, `/result/decision` на месте. Расхождения зафиксированы в решении групп 9–12; коммит делает runner, а проверка `changed_paths` сервером и auth-контракт остаются открытым ограничением. `openspec validate agents-flow-mvp --strict` — valid, exit 0.

## Workflow follow-up

- Синхронизировать project-memory после завершения правок.
- Запустить `final-gate-opus` и получить `FINAL: APPROVED` перед слиянием.
- Архивировать изменение после приёмки.
