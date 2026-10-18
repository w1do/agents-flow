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
