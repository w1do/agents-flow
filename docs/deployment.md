# Деплой (Dokploy + GitLab CI)

## Стеки

| Стек | Файл | Сервисы | Заметки |
|---|---|---|---|
| БД | `deploy/db/docker-compose.yml` | `postgres` | Отдельный Compose-сервис Dokploy, volume, без `ports` |
| Харнесс | `docker-compose.yml` | `migrate` → `server`, `worker`; `console` после MVP | Один образ для migrate/server/worker |

- Все сервисы в внешней сети `dokploy-network`; наружу только `expose`.
- Домен и HTTPS — в Dokploy на `server` (и `console` позже). Песочницам Novita нужен публичный HTTPS `/mcp` (A2).
- `migrate` — одноразовый (`alembic upgrade head`); `server` и `worker` стартуют через
  `depends_on: { migrate: { condition: service_completed_successfully } }`.
- Секреты приложения — только в Environment Dokploy. `config/harness.yaml` — File Mount Dokploy.

## CI (`.gitlab-ci.yml`)

```
check:python    (MR и main): uv sync --frozen, ruff check, ruff format --check, mypy, pytest;
                             Postgres — сервис postgres:16-alpine, TEST_DATABASE_URL задан в job
check:openspec  (MR и main): openspec validate --all
build:image     (main):      buildx build --push, cache из registry (:buildcache)
                             → :$CI_COMMIT_SHORT_SHA и :main
deploy:dokploy  (main):      curl -fsS -X POST "$DOKPLOY_WEBHOOK_URL"
```

В переменных GitLab только `DOKPLOY_WEBHOOK_URL` и встроенные `CI_REGISTRY_*`. Цель — push → выкат до 10 минут.

`alembic check` в CI пока не запускается: без моделей `target_metadata` пустой, и команда падает.
Шаг добавляется в `check:python` вместе с моделями (mvp-03).

Пайплайн GitLab не проверен на MR: remote репозитория — GitHub. Проверены структура YAML и
команды job `check:python` локально.

## Первый запуск

1. Задеплоить стек БД, затем стек харнесса с ENV из ARCHITECTURE.md §9.
2. `harness-server telegram set-webhook` — регистрирует `${HARNESS_PUBLIC_URL}/telegram/webhook` с секретом.
3. Создать песочницу в Novita вручную, выполнить в ней `deploy/sandbox/bootstrap.sh`, записать id в `harness.yaml`.
4. `harness-server sandbox pause` — песочница уходит в простой до первой задачи.
