# Agents Flow

Сервер на FastAPI и SQLAlchemy предоставляет login, проекты, init-коды и Harness init.
`GET /healthz` доступен без авторизации. Маршруты этапа 5 описаны в контракте, но
ещё не подключены.

## Установка и запуск

Сейчас приложение запускается локально. Compose и Dockerfile появятся на этапе 11.

Python ≥ 3.11 и PostgreSQL. Все команды выполняются в этом worktree.

```bash
cd server
python -m venv .venv
. .venv/bin/activate
python -m pip install -e .
```

Если в системе нет команды `python`, для создания venv используй `python3`.
Задай `DATABASE_URL` и `JWT_SECRET` через окружение либо `server/.env`.
Обязательные значения не имеют значений по умолчанию. Пример ввода в Bash:

```bash
read -rs -p 'DATABASE_URL: ' DATABASE_URL; printf '\n'
export DATABASE_URL
export JWT_SECRET="$(python -c 'import secrets; print(secrets.token_urlsafe(48))')"
read -r -p 'Admin email: ' ADMIN_EMAIL
read -rs -p 'Admin password: ' ADMIN_PASSWORD; printf '\n'
export ADMIN_EMAIL ADMIN_PASSWORD
alembic upgrade head
uvicorn app.main:app --host 127.0.0.1 --port 8000
```

При прямом доступе запускайте Uvicorn без `--proxy-headers`. За обратным
прокси включайте их только с `--forwarded-allow-ips=<доверенный адрес>`.
Прокси обязан перезаписывать `X-Forwarded-For`, а не дописывать входящее
значение. Приложение доверяет адресу соединения (`request.client.host`) и не
разбирает `X-Forwarded-For` самостоятельно.

В другом терминале: `curl --fail http://127.0.0.1:8000/healthz`.
Пароль в URL PostgreSQL должен быть закодирован как часть URL.

## Настройки

Имена переменных регистронезависимы; окружение имеет приоритет над `server/.env`.
Необязательные секреты отсутствуют (`None`), предустановленных ключей нет.

| Переменная | Назначение / значение без настройки |
|---|---|
| `DATABASE_URL` | обязательный SQLAlchemy URL, для PostgreSQL `postgresql+psycopg://…` |
| `JWT_SECRET` | обязательный случайный секрет длиной не менее 32 байт; создавай командой выше |
| `ADMIN_EMAIL`, `ADMIN_PASSWORD` | вместе создают первого администратора при старте; если не заданы, login недоступен до ручного создания пользователя |
| `TELEGRAM_BOT_TOKEN` | пустая строка, Telegram отключён |
| `TELEGRAM_WEBHOOK_SECRET` | отсутствует |
| `TRANSCRIPTION_PROVIDER` | `stub` |
| `TRANSCRIPTION_API_KEY` | отсутствует |
| `PUBLIC_BASE_URL` | `http://localhost:8000` |
| `OPENAI_API_KEY`, `OPENAI_BASE_URL` | отсутствуют |
| `AGENT_PROVIDER` | `stub` |
| `AGENT_MODEL` | отсутствует |

## Проверки

Из `server/` с активированным venv:

```bash
python -c "import app"
python -c "from app.models import Base; print(len(Base.metadata.tables))"
python -m pytest tests/test_health.py tests/test_repositories.py -q
python -m pytest -q
```

Тесты создают схему SQLAlchemy на SQLite in-memory с включёнными FK.
`TEST_DATABASE_URL` переключает их на отдельную тестовую PostgreSQL:
таблицы там создаются и удаляются фикстурами, нужна пустая тестовая база.
Тест миграции отдельно проверяет upgrade/downgrade и соответствие моделей на SQLite.

Из корня worktree после установки пакета:
`server/.venv/bin/python -m pytest server/tests/test_health.py`.

## Миграции

Из `server/`, с настройками и активированным venv:

```bash
alembic upgrade head
alembic current
alembic check
```

Проверка отката на пустой временной базе: `alembic downgrade base`.
Она удаляет все 11 таблиц приложения; служебная `alembic_version` остаётся.
Изменения схемы далее: `alembic revision --autogenerate -m 'описание'`,
проверить созданную миграцию, затем `alembic upgrade head`.

Репозитории вызывают `flush`, а границы commit/rollback задаёт сервис.
Блокировка аренды `FOR UPDATE SKIP LOCKED` появится на этапе 5.3.

Контракт и текущая доступность маршрутов: [docs/api.md](docs/api.md).
Примеры подключения Harness: [docs/api-examples.md](docs/api-examples.md).
