# Архитектура

## Три компонента

```
Telegram: текст / голос
          │
          ▼
┌─────────────────────────────┐
│ server/ (Dokploy)           │
│ FastAPI ── PostgreSQL       │
│   ├── панель (React)        │
│   ├── транскрибация         │
│   ├── Telegram              │
│   └── MCP endpoint          │
└─────────────────────────────┘
          │ HTTPS API
          ▼
┌─────────────────────────────┐
│ harness/ (машина проекта)   │
│ Go: аренда, worktree,       │
│ этапы, решения, отчёты      │
└─────────────────────────────┘
          │ stdin JSON / stdout NDJSON
          ▼
┌─────────────────────────────┐
│ runner/ (машина проекта)    │
│ Python: один этап за запуск │
│   ├── planning              │
│   ├── implementation        │
│   ├── testing               │
│   └── publication           │
└─────────────────────────────┘
          │
     worktree task/<task_id>
          │ после решения publish
   Git push / Dokploy deploy
```

## Границы ответственности

| Компонент | Отвечает | Не отвечает |
|---|---|---|
| Сервер | состояние задач, решения, история, skills, токены, панель | выполнение работ в проекте |
| Harness | аренда задачи, worktree, этапы, ожидание решений, доставка отчётов | знания о стеке, деплое, git-хостинге; запуск модели |
| Runner | один этап: план, правки файлов, проверки, команды публикации | сервер, lease, выбор skills |
| Skills | как реализовать, проверить, запушить, задеплоить | права доступа и хранение секретов |
| Агент (stub/deepagents) | анализ, план, реализация, проверки, отчёт | смена статусов и приёмка |

Harness запускает runner отдельным процессом на каждый этап и передаёт ему
снимок задачи, skills и checkpoint. Между этапами состояние живёт в harness
и на сервере, процессов runner одновременно нет.

## Поток задачи

1. Telegram или панель → сервер создаёт задачу `new`.
2. Harness опрашивает сервер и атомарно арендует задачу → `choosing`.
3. Агент получает skills этапа планирования → `planning`.
4. План уходит на сервер → `backlog`, пользователь решает.
5. `approved` → `active`, агент реализует; `rework` → `planning`.
6. Проверки → `testing`, отчёт → `ready`.
7. `publish` → `merged` + этап publication; `rework` → `active`;
   `keep_ready` → результат остаётся в `ready`.

## Ключевые технические решения

- Аренда через PostgreSQL `FOR UPDATE SKIP LOCKED`, TTL 60 с, heartbeat.
- Идемпотентность через `Idempotency-Key` и таблицу `idempotency_keys`.
- MCP и REST используют один service layer.
- Skills — Markdown, версионируются, снимок фиксируется на задаче.
- Публикация — отдельный этап с отдельным набором skills.
- Runner — отдельный процесс с контрактом stdin/stdout, поэтому harness
  не знает о модели и фреймворке агента.
- За доверенным прокси следит `server/app/api/proxy.py`: адрес клиента и
  `X-Forwarded-Proto` берутся только от `TRUSTED_PROXY_IPS`, rate-limit
  считается по реальному клиенту.
- Панель собирается в `server/web/dist` и раздаётся тем же FastAPI;
  сборка необязательна, без неё работает только API.

## Чего нет и не будет в MVP

Собственный LangGraph, брокер очередей, WebSocket, отдельный движок
оркестрации, Redis/RabbitMQ/Kafka.

## Папки

```
agents-server/
├── server/          FastAPI, панель, MCP, Telegram
│   └── web/         React-панель (Vite, сборка в dist/)
├── harness/         Go-бинарник
├── runner/          Python runner этапов
├── deploy/          compose для Dokploy и БД
├── docs/            эта документация
└── openspec/        change agents-flow-mvp
```

`server/`, `harness/` и `runner/` развиваются независимо: общий контракт —
только API и формат skills, а между harness и runner — stdin/stdout JSON
(контракт в `harness/RUNNER.md`). Позже каждая папка может стать отдельным
репозиторием без изменения кода.
