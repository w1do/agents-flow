# Runner, панель, деплой и приёмка: группы 9–12 change `agents-flow-mvp`

Дата: 2026-10-28. Основная ветка `main` @ `a43dc36`.

| Группа | Коммит реализации | Merge в `main` |
|---|---|---|
| 9 — runner | `d2f1ff8` | `a43dc36` |
| 10 — панель | `fc277e7` | `db9dcb0` |
| 11 — деплой | `8b02e7b` | `6c1d825` |

Все три ветки влиты в `main`; `main` содержит коммиты реализации
(`git merge-base --is-ancestor` подтверждает).

## Запрос

Закрыть группы 9–12 по `openspec/changes/agents-flow-mvp/tasks.md`:
агентский runner, панель управления, деплой и сквозная приёмка MVP.

## Группа 9 — runner

**Что сделано.** Отдельный процесс `runner/` на Python: один запуск
обслуживает один этап — planning, implementation, testing, publication.
Вход — один JSON на stdin (задача, stage, path/worktree, branch, read_only,
checkpoint, снимки skills, при необходимости plan_text, feedback,
result_data), выход — NDJSON: `plan`, `progress`, `test_result`, `result`,
`failure`. Публикация запускается только после решения `publish`.

**Решения.**

1. **Контракт stdin/stdout, а не библиотека.** Harness запускает процесс и
   не знает о модели и SDK. Источник контракта — `harness/RUNNER.md`.
2. **Три провайдера.** `stub` (без API, детерминированный), `deepagents`
   (Deep Agents SDK) и `openai-compatible` (тонкий адаптер). Ключ и endpoint
   читаются из явного окружения или файла `runner.env` с правами не шире
   `0600`; в YAML и аргументах ключа нет.
3. **Команды skills — только в bubblewrap.** Корень read-only, worktree —
   приватная копия, `/tmp` и `/home` — отдельные tmpfs, IPC и PID namespace
   изолированы, capabilities сброшены, сеть закрыта seccomp. Без bwrap команда
   не запускается (`sandbox_unavailable`), а не выполняется «как-нибудь».
4. **Публикация откатываема.** До записи результата создаётся копия видимых
   файлов; ошибка запускает восстановление, неудачный откат оставляет копию
   `.env.runner-recovery-*` с правами `0700`.
5. **Секреты не наследуются командами** и маскируются в событиях, истории SDK,
   именах и содержимом артефактов.

**Проверки.** 59 файлов, 23 модуля, 31 тестовый файл; `pytest -q` ×3 —
255 passed, 0 skipped, exit 0. `python -m runner --help` — exit 0.
Smoke `AGENT_PROVIDER=stub examples/smoke.py` — exit 0, основная копия
репозитория не изменена. Ревью Astra — APPROVED; Astra-Sec подтвердил
закрытие CRITICAL/HIGH (fd, IPC, seccomp, backup публикации, коллизии имён).
Финальный гейт Opus — `FINAL: APPROVED`.

**Ограничение.** Собственного шага `git commit` в коде runner нет:
git-команды приходят из skills публикации и выполняются в копии worktree без
`.git`, поэтому для реального коммита нужен runner, который коммитит до
отчёта, либо команда git вне такой копии. Записано в `docs/harness.md` и
`runner/README.md`; вопрос открыт.

## Группа 10 — панель

**Что сделано.** SPA на Vite/React/TypeScript/Tailwind в `server/web/`,
собирается в `server/web/dist` и раздаётся тем же FastAPI. Прямые переходы на
маршруты панели работают через SPA-fallback: только GET, только не
зарезервированные префиксы (`api`, `mcp`, `healthz`, `docs`, `redoc`,
`openapi.json`) и только для HTML-запросов. Если сборки нет, сервер
продолжает обслуживать API.

**Решения.**

1. **Один origin.** Браузер получает HttpOnly-cookie `session` с
   `SameSite=Strict`; JWT в JavaScript не попадает. Для CLI и harness
   остаётся `/auth/token`.
2. **CSRF-заголовок на изменяющие запросы**, отдельные security headers и
   лимит размера skill.
3. **Опрос вместо WebSocket** — обновление раз в 15 секунд и кнопкой
   «Обновить», с поколениями запросов, чтобы поздний ответ не затирал свежий.
4. **Сборка необязательна.** `server/web` — статика, а не новый сервис;
   отдельного контейнера нет.

**Проверки.** `server/web/tests/test_spa.py` (TestClient + временная SQLite),
`npm test` (vitest), плюс правки `server/tests/test_auth.py`,
`test_security.py`, `test_skills_api.py` в коммите `fc277e7`.

## Группа 11 — деплой и эксплуатация

**Что сделано.** Три Compose-файла: корневой `docker-compose.yml`
(`migrate`, `server`, `console`), `docker-compose.local.yml` (локальная
PostgreSQL и переопределения) и `deploy/db/docker-compose.yml` (стек БД для
Dokploy). Добавлены `server/Dockerfile`, `.dockerignore`, `.env.example`.

**Решения.**

1. **Секреты только файлами.** Compose secrets монтируются в `/run/secrets`,
   приложение читает каталог через `secrets_dir`; PostgreSQL получает пароль
   через `POSTGRES_PASSWORD_FILE`. Значения не передаются через `environment`.
   `.secrets/` — `0750`, файлы `0440`, доступ через `group_add` с
   `SECRETS_GID`.
2. **Жёсткая изоляция контейнеров.** `cap_drop: ALL`,
   `no-new-privileges: true`, корень `read_only` с tmpfs, приложение —
   `USER 10001:10001`, PostgreSQL — `user: "70:70"`, порт БД не публикуется,
   сеть БД `internal: true`.
3. **Администратор — командой, а не при старте.** Автобутстрап админа удалён;
   `python -m app.console create-admin` берёт пароль из
   `.secrets/admin_password` или скрытого ввода, email — из `--email` или
   `ADMIN_EMAIL`. Пароль: ≥12 символов и ≤72 байт UTF-8. Другие команды:
   `create-project`, `create-category`, `seed-skills`.
4. **Доверенный прокси — отдельный слой.** `server/app/api/proxy.py` верит
   `X-Forwarded-For` и `X-Forwarded-Proto` только адресам из
   `TRUSTED_PROXY_IPS` (список IP/CIDR, `*` запрещён), нормализует
   IPv4-mapped IPv6 в обе стороны, а rate-limit считает по реальному клиенту.

**Проверки.** `docker compose config` для трёх файлов — exit 0;
`server/tests/test_compose_contracts.py`; полный `pytest` — 688 passed,
1 skipped, exit 0.

## Группа 12 — сквозная приёмка

| Пункт | Статус | Факт |
|---|---|---|
| 12.1 сквозной сценарий | закрыт | реальный harness с честным stub-runner на локальном `origin`: `backlog → ready → merged`, в ветке `task/39490e06-…` появился коммит `8fe74f4`, `main` не изменён; `FINAL: merged approved` |
| 12.2 отказы | открыт | `server/tests/test_security.py` существует и проходит, но отдельная проверка полного списка отказов (чужой lease, `merged` агентом, решение по плану агентом, публикация без `publish`, повтор init-кода) в задачах не отмечена |
| 12.3 потеря аренды | закрыт | `server/tests/test_lease_expiry.py` — 8 тестов с фикстурой часов; после TTL карточка показывает `stalled`, checkpoint и история сохраняются |
| 12.4 секреты вне Git | закрыт | `git ls-files` отслеживает только `.env.example`; реальных ключей в репозитории нет, тесты используют синтетические фикстуры |
| 12.5 документация | в работе | по этой правке обновлены `architecture.md`, `deployment.md`, `data-model.md`, `harness.md`, `criteria.md`, `runner/README.md`; `docs/api.md` в этом изменении не пересматривался |

## Воркеры

| Роль | Что делала |
|---|---|
| sol (GPT-6.1) | runner, панель, деплой |
| terra (GPT-5.6) | прогоны проверок |
| luna (GPT-6) | правки по ревью |
| astra / astra-sec (GPT-6) | ревью и ревью безопасности |
| final-gate-opus (Opus) | финальная приёмка |
| documenter (Haiku) | эта запись и правка `docs/` |

## Последствия

- `docs/architecture.md` описывает три компонента: сервер, harness, runner.
- `docs/deployment.md` описывает три Compose-файла, file-backed secrets,
  `create-admin` и проверку `docker compose config`.
- `docs/harness.md` и `runner/README.md` фиксируют контракт коммита: коммитит
  runner, harness git-работу не делает; `changed_paths` — заявленные пути.
- `docs/data-model.md` приведён к фактическому состоянию: аренда с
  `SKIP LOCKED` реализована, события только добавляются, админ создаётся
  командой.

## Открытые вопросы

1. Нет собственного шага коммита в runner; публикация полагается на skills и
   внешний runner из прогона 12.1.
2. Сервер не сверяет `changed_paths` с Git — достоверность зависит от skills.
3. Пункт 12.2 не закрыт отдельной проверкой отказов.
4. Конкурентная аренда на PostgreSQL проверяется только при заданном
   `TEST_DATABASE_URL`; в CI без PostgreSQL тест пропускается.
