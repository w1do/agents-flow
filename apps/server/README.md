# apps/server — сервер и worker

Пакет `harness_server`: FastAPI-приложение, worker и CLI `harness-server`. Бизнес-логики пока нет:
она появится в `services/` с изменением `mvp-03-task-store`.

## Команды CLI

| Команда | Что делает |
|---|---|
| `harness-server --help` | Справка по командам |
| `harness-server check-config` | Проверяет ENV и `harness.yaml`, печатает список workspace |
| `harness-server serve --host 127.0.0.1 --port 8000` | HTTP-сервер: `GET /health`, `GET /health/ready`. По умолчанию слушает localhost; в контейнере `--host 0.0.0.0` |
| `harness-server worker` | Цикл опроса очереди (пока без задач), остановка по SIGTERM |
| `harness-server migrate` | `alembic upgrade head`, нужен `DATABASE_URL` |

`serve`, `worker` и `check-config` перед стартом проверяют ENV и `harness.yaml`. При ошибке они
печатают имя переменной или путь к полю без значений и выходят с кодом 1, например:

```
Ошибка конфигурации: некорректные ENV: TELEGRAM_BOT_TOKEN: Field required
```

## Конфигурация

- ENV: обязательные и опциональные переменные описаны в [ARCHITECTURE.md §9](../../ARCHITECTURE.md)
  и в `.env.example`. Секреты читаются как `SecretStr`.
- `harness.yaml`: пример в `config/harness.example.yaml`. Файл с настройками workspace; ключи
  вида `token`, `key`, `password`, `secret`, `apikey` сервер отклоняет.

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
├── worker.py       # цикл worker и обработка SIGTERM
└── cli.py          # команды harness-server (typer)
```

Модели ответов, видимые снаружи, лежат в `shared/` (пакет `harness_shared`).
