# CLAUDE.md — agents-flow harness

Правила для любого агента (Claude Code, Codex, субагенты), который работает в этом репозитории.
Что строим: [ARCHITECTURE.md](ARCHITECTURE.md). Что делаем сейчас: [PLAN.md](PLAN.md).
Требования: [docs/tz/tz-v5.md](docs/tz/tz-v5.md). Решения поверх ТЗ: [docs/decisions.md](docs/decisions.md).

## 1. Перед началом работы

1. `memory_status` → при устаревших файлах `memory sync`. Контекст берётся из project-memory
   (`memory_search`, `memory_get_context`), а не перечитыванием репозитория.
2. Найти своё OpenSpec-изменение в `openspec/changes/<id>/` и работать строго по его `tasks.md`.
   Работа без изменения OpenSpec не начинается. Новое поведение = новое изменение (`/opsx:propose`).
3. Изменения MVP выполняются по порядку из PLAN.md: следующее начинается, когда предыдущее принято.

## 2. Стек (не менять без записи в docs/decisions.md)

- Сервер: Python 3.12, FastAPI (async), SQLAlchemy 2 async + asyncpg, Pydantic v2, Alembic, uv.
- MCP: официальный MCP Python SDK, Streamable HTTP, смонтирован в FastAPI на `/mcp`.
- Внешние API: httpx (async). Telegram — тонкий собственный клиент на httpx.
- Тесты: pytest + pytest-asyncio, Postgres в testcontainers или сервисе CI. Линт: ruff, mypy `--strict`.
- Консоль (MVP, `mvp-10-operator-console`, D-39): React + shadcn/ui, ESLint + Prettier, типы из `packages/shared-types`.
- Git-хостинг: GitLab (MR, CI, Registry). Деплой: Dokploy.

## 3. Жёсткие правила

- **Бизнес-логика только в `services/`.** `api/`, `mcp/`, `telegram/`, `cli.py` — тонкие входы. Telegram-кнопка
  и MCP-инструмент вызывают одну и ту же функцию сервиса.
- **Внешний API — только через адаптер** в `adapters/<name>/` с `Protocol` и фейком для тестов.
  Сервисы не импортируют SDK Novita, httpx-клиенты Telegram/Polza/GitLab напрямую.
- **БД:** только SQLAlchemy ORM с параметрами, без raw SQL с конкатенацией. Схема меняется только миграцией
  Alembic в `db/migrations`. Вход валидируется Pydantic до ORM.
- **Статусы задачи** только из набора ТЗ v5: `new, choosing, planning, backlog, active, testing, ready, merged,
  error, stalled, paused, trash`. Переходы — только через `domain/statuses.py`.
- **Обработчики не блокируются:** webhook и MCP отвечают быстро; песочница, агент и гейты — в worker.
- **Секреты:** не в коде, YAML, логах, коммитах, Telegram и БД. Конфиг хранит ссылки, значения — в ENV Dokploy.
  Всё, что уходит в БД/Telegram/git из песочницы, проходит `security/redaction`. `.env*` не коммитится и не читается агентом.
- **Ядро без доменной логики:** поведение агентов задаётся промптами и skills, а не кодом под конкретный проект.
- **Каждая задача** — своя ветка `task/<task_id>` и worktree; в основную ветку только через MR.
- **Тесты не зелёные по умолчанию:** нет команды тестов → `no_tests`, а не «пройдено».
- **Гейты идемпотентны:** каждый шаг проверяет, не выполнен ли он уже (push, MR).

## 4. Код

- Типизация везде, mypy strict без `type: ignore` без комментария причины.
- Модули короткие и по одному назначению. Имена — по словарю [docs/glossary.md](docs/glossary.md).
- Pydantic-модели, которые видит внешний мир (MCP, API, консоль), живут в `shared/`. Дублировать типы нельзя.
- Ошибки домена — свои исключения в `domain/errors.py`; MCP и API переводят их в ответы.
- Логи структурированные, без секретов и без полного текста diff.
- Комментарии объясняют «почему», а не пересказывают код. Docstring у публичных функций сервисов и адаптеров.

## 5. Тесты и проверки

Каждое изменение кода коммитится вместе с тестами. Перед сдачей задачи:

```bash
./tools/harness check     # ruff check, ruff format --check, mypy, pytest
```

- Сервисы тестируются с фейковыми адаптерами и реальным Postgres.
- Адаптеры — контрактными тестами на записанных ответах (respx), без реальных ключей.
- Интеграция с Novita/Telegram/GitLab — отдельные тесты с маркером `live`, по умолчанию не запускаются.

## 6. Документация и память (обязательно в том же изменении)

- Новый эндпоинт, статус, таблица, ENV, сервис → ARCHITECTURE.md (+ Compose и `.env.example` для ENV/сервиса).
- Статус изменения OpenSpec → PLAN.md. Новое решение → docs/decisions.md (`D-NN`).
- Каталог MCP-инструментов → docs/mcp-agents-flow.md.
- У каждой части (`apps/server`, `apps/console`, `shared`, `db`) свой README: запуск, тесты, команды.
- После любого изменения файлов: `memory_update` по путям → `memory_annotate` для каждого нового/изменённого
  файла → `memory_status` без устаревших файлов. `.memory/` руками не править.

## 7. Команды

Единая точка входа — `./tools/harness <команда>` (появляется в `mvp-02-foundation`):

| Команда | Что делает |
|---|---|
| `./tools/harness check` | Линт, типы, тесты |
| `./tools/harness dev` | Локальный server + worker |
| `./tools/harness migrate` | `alembic upgrade head` |
| `./tools/harness sandbox pause\|resume` | Пауза/возобновление песочницы из конфига |
| `openspec list` / `openspec validate --all` | Состояние и проверка спецификаций |
