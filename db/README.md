# db — миграции и Postgres

Схема меняется только миграциями Alembic в `db/migrations`. Метаданные — `Base.metadata`
(`harness_server.db.base`); `env.py` импортирует пакет моделей, поэтому autogenerate и `alembic check`
видят все таблицы.

## Миграции

| Что | Где |
|---|---|
| Окружение Alembic (async engine, URL из `DATABASE_URL`) | `db/migrations/env.py` |
| Шаблон ревизии | `db/migrations/script.py.mako` |
| Ревизии | `db/migrations/versions/`: `0001_initial` (9 таблиц MVP), `0002` (`telegram_updates.payload`) |
| Конфиг | `alembic.ini` в корне |

Применить миграции до head:

```bash
./tools/harness migrate               # то же: uv run harness-server migrate
```

Команда требует `DATABASE_URL`. `./tools/harness` загружает его из `.env`.

Проверка расхождения ORM и БД (после `upgrade head` не должно быть вывода о различиях):

```bash
uv run alembic check
```

## Ревизия 0001 (mvp-03)

Миграция написана вручную, без импорта кода приложения: значения CHECK записаны литералами.
Таблицы: `tasks`, `task_events`, `routings`, `checkpoints`, `spec_items`, `sandboxes`, `task_tokens`,
`telegram_messages`, `telegram_updates`. FK `tasks.spec_item_id → spec_items` создаётся последним
(цикл таблиц). Откат удаляет все таблицы MVP: `uv run alembic downgrade base`.

Перечисления хранятся как `VARCHAR(16)` с CHECK `ck_<таблица>_<колонка>` (D-22); нативный `ENUM`
Postgres не используется. Тесты БД (`apps/server/tests/conftest.py`) поднимают Postgres через
testcontainers или берут `TEST_DATABASE_URL` и применяют миграции до head один раз за сессию.

## Ревизия 0002 (mvp-04)

Миграция `20261018_0002_telegram_update_payload.py`, ручная, без импорта кода приложения. Добавляет nullable-колонку
`telegram_updates.payload` (JSONB): нормализованный апдейт владельца до обработки. После обработки значение
обнуляется, строка получает `processed_at` (D-27). Откат: `uv run alembic downgrade 0001` удаляет колонку и
тела необработанных апдейтов, поэтому перед откатом дождитесь `processed_at` у всех строк.

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
