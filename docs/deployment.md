# Развёртывание

## Три Compose-файла

| Файл | Что запускает |
|---|---|
| `docker-compose.yml` | стек приложения в Dokploy: `migrate`, `server`, `console` |
| `docker-compose.local.yml` | локальный запуск: `db` (PostgreSQL), переопределения для `migrate` и `console` |
| `deploy/db/docker-compose.yml` | отдельный стек PostgreSQL для Dokploy |

Проверка синтаксиса и подстановки без запуска:

```bash
docker compose config
docker compose -f docker-compose.yml -f docker-compose.local.yml config
docker compose -p agents-flow-db -f deploy/db/docker-compose.yml config
```

Корневой стек не содержит PostgreSQL и не может поднять вторую базу.
`migrate` завершается успешно до старта `server` и `console`
(`depends_on: service_completed_successfully`). `console` входит в профиль
`tools` и не стартует вместе с сервером.

## База

`deploy/db/docker-compose.yml` — PostgreSQL с постоянным volume.

- работает как `user: "70:70"`, без root;
- порт наружу не публикуется;
- единственная сеть — `agents-flow-database-private` с `internal: true`,
  то есть без выхода во внешний мир;
- пароль приходит файлом: `POSTGRES_PASSWORD_FILE: /run/secrets/postgres_password`.

Приложение (`server`, `migrate`, `console`) подключается к двум сетям:
`dokploy-network` и `database-private`. Приватная сеть создаётся стеком БД.

## Приложение

| Сервис | Роль |
|---|---|
| `migrate` | Alembic, `alembic upgrade head`, до `server` |
| `server` | FastAPI + панель + MCP + Telegram |
| `console` | админ-команды: `python -m app.console` |

Все три сервиса запускаются одинаково жёстко:

- `cap_drop: [ALL]` и `security_opt: [no-new-privileges:true]`;
- корневая ФС `read_only: true`, запись только в `tmpfs` (`/tmp`,
  у `server` — 64 МиБ, у `migrate` и `console` — 16 МиБ);
- приложение работает как `USER 10001:10001` (см. `server/Dockerfile`);
- `group_add: ["${SECRETS_GID:-1000}"]` — дополнительная группа только для
  чтения файлов секретов.

`server` проверяет себя через `GET /healthz` и слушает
`${SERVER_BIND_ADDRESS:-127.0.0.1}:${SERVER_PORT:-8000}`. Наружу его
публикует Dokploy/Traefik по HTTPS.

## Секреты

Значения секретов **не** передаются через Dokploy Environment и не попадают
в переменные окружения контейнера. Все они — file-backed Compose secrets:
монтируются в `/run/secrets/<имя>`, а приложение читает каталог `/run/secrets`
через `secrets_dir` в `server/app/core/config.py`.

| Файл в `.secrets/` | Кто использует |
|---|---|
| `database_url` | `migrate`, `server`, `console` |
| `jwt_secret` | `server`, `console` |
| `admin_password` | `server`, `console` |
| `telegram_bot_token`, `telegram_webhook_secret` | `server` |
| `transcription_api_key`, `openai_api_key` | `server` |
| `postgres_password` | только PostgreSQL |

Каталог `.secrets/` — права `0750`, каждый файл — `0440`, владелец — группа
`SECRETS_GID` (по умолчанию `1000`). Каталог задаётся `SECRETS_DIR`, по
умолчанию `./.secrets` от корня репозитория. Файлы необязательных
провайдеров могут быть пустыми.

`jwt_secret` — не короче 32 байт. Пароль администратора — не короче 12
символов и не длиннее 72 байт UTF-8 (ограничение bcrypt).

## Создание администратора

Автоматического создания администратора при старте сервера нет. Первого
пользователя создаёт консольная команда:

```bash
docker compose --profile tools run --rm console create-admin
```

Пароль берётся из `ADMIN_PASSWORD` (файл `.secrets/admin_password`) либо
запрашивается скрытым вводом в интерактивном терминале. Email берётся из
`--email` или `ADMIN_EMAIL`. Повторный вызов с существующим email ничего не
меняет и сообщает id пользователя.

Другие команды консоли: `create-project`, `create-category`, `seed-skills`
(идемпотентно создаёт категории и стартовые skills).

## Переменные окружения

В `docker-compose.yml` через `environment` передаются только несекретные
значения:

```text
ADMIN_EMAIL
TRANSCRIPTION_PROVIDER
TRANSCRIPTION_MODEL
PUBLIC_BASE_URL
OPENAI_BASE_URL
AGENT_PROVIDER
AGENT_MODEL
TRUSTED_PROXY_IPS
```

`TRUSTED_PROXY_IPS` — JSON-список IP/CIDR прокси. `*` запрещён. Только
адресам из этого списка сервер верит в `X-Forwarded-For` и
`X-Forwarded-Proto`; rate-limit считается по реальному клиенту.

## Локальный запуск

```bash
docker compose -f docker-compose.yml -f docker-compose.local.yml up -d
```

Панель и API — на `http://localhost:8000`, проверка — `/healthz`.
Локальная сеть приложения имеет выход наружу, сеть БД — нет.
Остановка с удалением данных:

```bash
docker compose -f docker-compose.yml -f docker-compose.local.yml down -v
```

## Dokploy

1. Создать внешнюю сеть `dokploy-network`.
2. Развернуть стек БД: `agents-flow-db` из `deploy/db/docker-compose.yml`.
3. Развернуть корневой `docker-compose.yml` как стек приложения.
4. Создать администратора через `docker compose --profile tools run --rm console create-admin`.
5. Направить трафик на порт `server`; HTTPS завершает Traefik.

Harness и runner в серверный Compose не входят.

## Harness и runner

Ставятся на машине с Git-проектом.

Требования:

- Linux с Git и доступным `/proc`;
- Python >=3.11 и bubblewrap для runner;
- Deep Agents SDK — только для `AGENT_PROVIDER=deepagents`;
- HTTPS до сервера;
- проектные инструменты, только если нужны назначенным skills.

```bash
harness init <project_id>
harness run
```

## Обновление

1. Собрать новый образ сервера.
2. `migrate` прогоняется автоматически.
3. Панель и API перезапускаются.
4. Harness и runner совместимы по API и по контракту stdin/stdout:
   изменения контракта — только с обратной совместимостью или новой
   версией endpoint.

## Откат

- Образ сервера — предыдущий тег.
- Миграции — только вперёд; откат данных — из бэкапа.
- Бэкап PostgreSQL — регулярный, проверяется восстановлением.
