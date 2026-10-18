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
check  (каждый MR и main): ruff, mypy, pytest, alembic check, openspec validate --all
build  (main):             docker build с --cache-from registry → :$CI_COMMIT_SHORT_SHA и :main
deploy (main):             curl -X POST "$DOKPLOY_WEBHOOK_URL"
```

В переменных GitLab только `DOKPLOY_WEBHOOK_URL` и встроенные `CI_REGISTRY_*`. Цель — push → выкат до 10 минут.

## Первый запуск

1. Задеплоить стек БД, затем стек харнесса с ENV из ARCHITECTURE.md §9.
2. `harness-server telegram set-webhook` — регистрирует `${HARNESS_PUBLIC_URL}/telegram/webhook` с секретом.
3. Создать песочницу в Novita вручную, выполнить в ней `deploy/sandbox/bootstrap.sh`, записать id в `harness.yaml`.
4. `harness-server sandbox pause` — песочница уходит в простой до первой задачи.
