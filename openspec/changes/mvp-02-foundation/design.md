# Design: mvp-02-foundation

## Context

Репозиторий пуст, кроме документации и OpenSpec. Решения D-07 (uv, Python 3.12), D-08 (отдельный worker),
D-11 (конфиг в YAML) задают рамки.

## Goals / Non-Goals

**Goals:** один образ для `migrate`, `server`, `worker`; конфиг проверяется при старте; CI проходит за минуты.

**Non-Goals:** бизнес-логика, таблицы домена, консоль.

## Decisions

- **uv workspace** вместо отдельных проектов: один `uv.lock`, `shared` подключается как workspace-зависимость.
  Альтернатива — Poetry: медленнее в CI, отвергнута на брифинге.
- **Два слоя конфигурации.** ENV — секреты и адреса (`Settings`). YAML — несекретные настройки workspace
  (`HarnessConfig`). Поля YAML, похожие на секрет (`token`, `key`, `password`), запрещены валидатором.
  Альтернатива — всё в ENV: неудобно описывать списки workspace.
- **`create_app(settings, config)`** — фабрика без глобального состояния, чтобы тесты создавали приложение с фейками.
- **`./tools/harness`** — bash-обёртка над `uv run`; единая точка команд (preferences). Альтернатива — Makefile:
  отвергнута ради одного стиля с `harness-server`.
- **Compose:** `migrate` одноразовый; `server` и `worker` ждут `service_completed_successfully`. Сеть
  `dokploy-network` external, только `expose`. Postgres — отдельный стек.
- **CI-образ** собирается с `--cache-from type=registry`; зависимости ставятся слоем до копирования кода.

## Risks / Trade-offs

- [Dokploy не видит сеть БД] → оба стека в `dokploy-network`, адрес БД по имени сервиса из стека БД.
- [Длинный CI из-за testcontainers] → в CI Postgres как `services:` GitLab, testcontainers только локально.
- [Пайплайн GitLab на MR не запускался: remote репозитория — GitHub] → YAML и команды job `check:python` проверены локально; подтвердить на первом MR в GitLab.
- [`alembic check` не работает при `target_metadata=None`] → убран из CI, включается в mvp-03 вместе с моделями.
- [Postgres и харнесс в общей `dokploy-network`, порт 5432 виден другим стекам сети] → защита паролем; отдельная internal-сеть невозможна между двумя стеками Dokploy, пересмотреть при hardening.
- [Образы `docker:27`, `python:3.12-slim-bookworm` закреплены тегом, без digest] → принято для MVP.
- [Нет проверки плейсхолдера `CHANGE_ME`, нет `cap_drop`/`read_only` у контейнеров] → hardening после MVP.
- [Разбор `.env` в `tools/harness` без автотеста; CRLF оставляет `\r` в значениях] → проверено вручную на спецсимволах; `.env` в LF.
- [Сервис `migrate` монтирует `harness.yaml`, который ему не нужен] → безвредно, убрать при следующей правке compose.
- [Локальная разработка: Postgres через `docker run -p 127.0.0.1:5432:5432`, стек `deploy/db` без `ports`] → описано в docs/development.md и db/README.md.
