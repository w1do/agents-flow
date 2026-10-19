# Proposal: mvp-10-operator-console

> Веб-панель оператора в MVP. Решение владельца 2026-10-19 (D-39): весь сквозной поток должен проверяться
> не только через Telegram, но и в браузере. Идёт после `mvp-09` (сквозной срез готов, панель его показывает).

## Why

Без интерфейса владелец видит задачи только в Telegram, а песочницу и логи агента — через CLI и БД. Для приёмки MVP
нужно видеть канбан, ленту событий, состояние песочницы и вывод агента, а также создавать задачу без голоса.
Это минимальная часть `console-auth` и `console-observability`, перенесённая в MVP.

## What Changes

- `apps/console`: React + TypeScript + Vite + shadcn/ui, ESLint + Prettier, README; сборка в статику.
- `packages/shared-types`: TS-типы, генерируемые из JSON Schema моделей `harness_shared` (без ручного дублирования).
- Вход администратора: `ADMIN_EMAIL` / `ADMIN_PASSWORD` при первом старте → таблица `admins` (хеш пароля),
  `harness-server reset-password`, серверные сессии в таблице `console_sessions` (cookie `HttpOnly`, `Secure`,
  `SameSite=Strict`), выход и отзыв сессий.
- API панели `/api/console/*` (FastAPI, тонкий вход, логика в `services/`): вход/выход, список задач (канбан),
  карточка задачи (события, ветка, MR, итог, решение маршрутизации), создание задачи (текст + проект), состояние
  песочницы, пауза/возобновление, хвост вывода агента после redaction.
- Экраны: «Вход», «Канбан», «Задача», «Новая задача», «Песочница».
- Compose: сервис `console` (nginx: статика + прокси `/api` на `server` внутри сети, один origin); GitLab CI —
  lint, typecheck, build консоли на стадии check.

## Capabilities

### New Capabilities

- `operator-console`: веб-панель оператора: вход, канбан, карточка и создание задачи, песочница и логи агента.

### Modified Capabilities

Нет.

## Impact

- Зависит от: `mvp-03-task-store`, `mvp-05-command-routing`, `mvp-06-sandbox-runtime`, `mvp-09-delivery-mr`.
- Новые таблицы: `admins`, `console_sessions` (миграция). ENV: `ADMIN_EMAIL`, `ADMIN_PASSWORD` (секрет),
  `CONSOLE_SESSION_TTL_HOURS` (по умолчанию 12).
- Критерий приёмки MVP дополняется: тот же сквозной поток виден в панели (PLAN.md).
- Затрагивает ARCHITECTURE.md (§1 части, §2, §4 таблицы, §9 ENV, Compose), CLAUDE.md §2, `.env.example`.
- Ссылки: ТЗ §8 (вход и наблюдаемость), §14.

## Не входит

- Настройки агентов, workspace и песочниц из панели (`console-settings`).
- Чекпоинты, процессы и расход токенов в карточке (`console-observability` после MVP).
- Работа панели через MCP с операторским токеном (`console-auth` после `operator-tokens`): в MVP панель ходит в
  REST `/api/console/*`, который вызывает те же функции сервисов, что Telegram и CLI.
- Правка и удаление задач, ручная смена статусов.
