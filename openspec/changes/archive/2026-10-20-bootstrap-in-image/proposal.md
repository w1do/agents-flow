# Proposal: bootstrap-in-image

> `harness-server sandbox bootstrap` в контейнере `server`/`worker` на проде (Dokploy) падает с
> «Ошибка: не читается скрипт deploy/sandbox/bootstrap.sh» (2026-10-20). Изменение кладёт скрипт в образ и делает
> путь по умолчанию независимым от текущего каталога. Место в плане — 6f, после 6e.

## Why

1. `Dockerfile` копирует в образ только `pyproject.toml`, `uv.lock`, `.python-version`, `apps`, `shared`, `db`,
   `alembic.ini`. Каталога `deploy/` в образе нет (`.dockerignore` его не исключает, его просто не копируют).
2. `cli.py` `sandbox_bootstrap(script: Path = Path("deploy/sandbox/bootstrap.sh"))` — путь относительно cwd.
   Терминал Dokploy открывается в `/`, поэтому даже при наличии файла в `/app` путь не находится.

Ошибка существует с `sandbox-profile` (6c): тогда bootstrap запускали локально из корня репозитория. Worker
bootstrap не вызывает (только `activate`), задачи не затронуты.

## What Changes

- `Dockerfile`: каталог `deploy/sandbox` копируется в образ (`/app/deploy/sandbox`, владелец `app`).
- `cli.py`: путь по умолчанию — константа `DEFAULT_BOOTSTRAP_SCRIPT`, вычисленная от расположения пакета
  (`Path(__file__).resolve().parents[4] / "deploy/sandbox/bootstrap.sh"`): `/app/...` в образе и `<репо>/...`
  локально. Новой ENV нет. Флаг `--script` сохраняется.
- Тесты: CLI находит скрипт при cwd вне репозитория; текстовая проверка `Dockerfile` и `.dockerignore`.
- Документация: `docs/deployment.md` (запуск bootstrap в терминале Dokploy), `apps/server/README.md`,
  `PLAN.md` (строка 6f), `docs/decisions.md` (D-63).

## Capabilities

### New Capabilities

Нет.

### Modified Capabilities

- `sandbox-profile`: добавлено требование «Скрипт bootstrap в образе сервера».

## Impact

- Код: `Dockerfile`, `apps/server/src/harness_server/cli.py` (одна константа и значение по умолчанию).
- Тесты: `apps/server/tests/test_cli.py`, новый `apps/server/tests/test_dockerfile.py`.
- ENV, БД, миграции, API, MCP, Telegram: без изменений. `docker-compose.yml`, `.env.example`, ARCHITECTURE.md §9 не
  меняются.
- Совместимость: явный `--script <путь>` работает как раньше. Локально из корня репо поведение то же.
- Откат: revert коммита; образ без `deploy/` возвращает прежнюю ошибку, данных не касается.

## Не входит

- Запуск bootstrap из worker автоматически, расписание, Telegram-команда bootstrap.
- Упаковка скрипта как package data (`importlib.resources`) — см. design.md, решение 1.
