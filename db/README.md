# db — миграции и Postgres

Схема меняется только миграциями Alembic в `db/migrations`. Моделей пока нет: они появятся в
`mvp-03-task-store`, тогда в `env.py` подключается `target_metadata`.

## Миграции

| Что | Где |
|---|---|
| Окружение Alembic (async engine, URL из `DATABASE_URL`) | `db/migrations/env.py` |
| Шаблон ревизии | `db/migrations/script.py.mako` |
| Ревизии | `db/migrations/versions/` (пока пусто) |
| Конфиг | `alembic.ini` в корне |

Применить миграции до head:

```bash
./tools/harness migrate               # то же: uv run harness-server migrate
```

Команда требует `DATABASE_URL`. `./tools/harness` загружает его из `.env`.

## Локальный Postgres

Для разработки на хосте:

```bash
docker run -d --name harness-pg -p 127.0.0.1:5432:5432 -e POSTGRES_DB=harness -e POSTGRES_USER=harness -e POSTGRES_PASSWORD=CHANGE_ME postgres:16-alpine
```

`DATABASE_URL` и `POSTGRES_PASSWORD` в `.env` (из `.env.example`) уже совпадают с этой командой.
Порт опубликован только на `127.0.0.1`. Удалить: `docker rm -f harness-pg`.

## Postgres: стек `deploy/db` (Dokploy)

Postgres — отдельный стек Compose (`deploy/db/docker-compose.yml`), в Dokploy его деплоят отдельно,
чтобы редеплой харнесса не трогал данные. Все сервисы работают во внешней сети `dokploy-network`,
порты наружу не публикуются (`expose: 5432`). Сервис называется `postgres`: из контейнеров в
`dokploy-network` он доступен по этому имени. Стек с хоста не используется.
