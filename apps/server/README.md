# apps/server — сервер и worker

Пакет `harness_server`: FastAPI-приложение, worker и CLI `harness-server`. Бизнес-логика задач —
в `services/tasks.py` (mvp-03); входы (`api/`, позже `mcp/`, `telegram/`, CLI) только вызывают её.

## Команды CLI

| Команда | Что делает |
|---|---|
| `harness-server --help` | Справка по командам |
| `harness-server check-config` | Проверяет ENV и `harness.yaml`, печатает список workspace |
| `harness-server serve --host 127.0.0.1 --port 8000` | HTTP-сервер: `GET /health`, `GET /health/ready`. По умолчанию слушает localhost; в контейнере `--host 0.0.0.0` |
| `harness-server worker` | Цикл опроса очереди (пока без задач), остановка по SIGTERM |
| `harness-server migrate` | `alembic upgrade head`, нужен `DATABASE_URL` |

## HTTP-эндпоинты задач

| Метод и путь | Что делает | Ответ |
|---|---|---|
| `POST /tasks` | Создаёт задачу `plan` в статусе `new`, источник `api`. Тело: `text` (1–20 000 символов), необязательный `workspace_id` | `201` с задачей; `422` при `unknown_workspace` или пустом тексте |
| `GET /tasks/{id}` | Задача и лента событий в хронологическом порядке | `200`; `404`, если задачи нет |

Оба требуют заголовок `Authorization: Bearer <HARNESS_ADMIN_TOKEN>` (временный доступ, D-23). Без заголовка,
с другой схемой, неверным токеном или когда `HARNESS_ADMIN_TOKEN` не задан — `401` с `WWW-Authenticate: Bearer`
и телом `{"detail": "unauthorized"}`, без проверки существования задачи. `HARNESS_ADMIN_TOKEN`, если задан,
должен быть не короче 32 символов без пробелов по краям: короткий токен роняет запуск сервера целиком,
пустой считается не заданным, и `/tasks` тогда всегда отвечает 401.

`serve`, `worker` и `check-config` перед стартом проверяют ENV и `harness.yaml`. При ошибке они
печатают имя переменной или путь к полю без значений и выходят с кодом 1, например:

```
Ошибка конфигурации: некорректные ENV: TELEGRAM_BOT_TOKEN: Field required
```

## Конфигурация

- ENV: обязательные и опциональные переменные описаны в [ARCHITECTURE.md §9](../../ARCHITECTURE.md)
  и в `.env.example`. Секреты читаются как `SecretStr`.
- `harness.yaml`: пример в `config/harness.example.yaml`. Файл с настройками workspace; ключи
  вида `token`, `key`, `password`, `secret`, `apikey`, `credential` (и их варианты во множественном числе,
  `passwd`, `pwd`) сервер отклоняет; `gitlab.base_url` с учётными данными тоже.

## Запуск

Из корня репозитория:

```bash
uv sync
cp .env.example .env                  # заполнить секреты
cp config/harness.example.yaml config/harness.yaml
./tools/harness dev                   # server на :8000 и worker
```

`/health` отвечает без Postgres. `/health/ready` без доступной БД отвечает 503.

## Тесты

```bash
./tools/harness check                 # ruff, ruff format, mypy strict, pytest
uv run pytest                         # только тесты
```

Тесты с БД используют `TEST_DATABASE_URL`, если он задан (так в CI), иначе поднимают Postgres
через testcontainers (нужен Docker). Тесты с маркером `live` (реальные внешние сервисы) по
умолчанию не запускаются.

## Структура

```
src/harness_server/
├── settings.py     # Settings: ENV, секреты как SecretStr
├── config.py       # HarnessConfig: harness.yaml, запрет секретов в файле
├── app.py          # create_app(settings, config): FastAPI и lifespan с engine БД
├── api/health.py   # /health и /health/ready
├── api/tasks.py    # POST /tasks, GET /tasks/{id}
├── api/deps.py     # сессия БД, конфиг, проверка HARNESS_ADMIN_TOKEN
├── services/tasks.py  # создание, смена статуса, лента, очередь claim_next_task
├── domain/         # statuses.py (таблица переходов), errors.py (DomainError)
├── db/             # base, ids (uuid7), session, models/ (ORM 9 таблиц)
├── worker.py       # цикл worker и обработка SIGTERM
└── cli.py          # команды harness-server (typer)
```

Модели ответов, видимые снаружи, лежат в `shared/` (пакет `harness_shared`).
