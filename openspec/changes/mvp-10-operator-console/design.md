# Design: mvp-10-operator-console

## Context

К `mvp-10` есть: задачи, события и очередь (`mvp-03`), Telegram и маршрутизация (`mvp-04`, `mvp-05`), песочница и
запуск агента (`mvp-06`), MCP (`mvp-07`), планирование и доставка MR (`mvp-08`, `mvp-09`). Интерфейс — только
Telegram, CLI и `POST/GET /tasks` с временным `HARNESS_ADMIN_TOKEN` (D-23). Операторских токенов (`operator-tokens`)
в MVP нет, поэтому панель не может ходить в MCP как оператор.

## Goals / Non-Goals

**Goals:** владелец входит в браузере, видит канбан и ленту задачи, создаёт задачу, видит песочницу и вывод агента,
ставит песочницу на паузу; ни один секрет не попадает в браузер; панель не содержит бизнес-логики.

**Non-Goals:** настройки, несколько пользователей и роли, MCP-доступ панели, realtime через WebSocket.

## Decisions

1. **REST для панели в MVP (D-39).** `api/console/*` — тонкий вход: проверка сессии → функция `services/*` →
   Pydantic-модель ответа из `harness_shared.console`. Те же функции вызывают Telegram и CLI (CLAUDE.md §3).
   После `operator-tokens` панель переходит на MCP (`console-auth`), REST остаётся до этой миграции.
2. **Один origin.** Сервис `console` — nginx: SPA-статика и `location /api/ { proxy_pass http://server:8000; }`
   внутри `dokploy-network`. Наружу — только домен консоли в Dokploy (HTTPS), порты не публикуются. CORS не нужен,
   cookie `SameSite=Strict`.
3. **Администратор.** Таблица `admins` (`id`, `email` UNIQUE, `password_hash`, `created_at`, `password_changed_at`).
   При старте `server` (lifespan) и в CLI: если строк нет и заданы `ADMIN_EMAIL`/`ADMIN_PASSWORD` — создать; если
   строка есть — ENV пароль не перезаписывает. Хеш — `hashlib.scrypt` (n=2^15, r=8, p=1, соль 16 байт) в формате
   `scrypt$n$r$p$salt$hash` (stdlib, без новой зависимости), сравнение `hmac.compare_digest`.
   `ADMIN_PASSWORD` ≥ 12 символов (проверка в `settings.py`). `harness-server reset-password --email` спрашивает
   пароль интерактивно (не аргументом — не попадает в историю shell), меняет хеш и отзывает все сессии.
4. **Сессии.** Таблица `console_sessions` (`id`, `admin_id`, `token_hash` UNIQUE (HMAC-SHA256 с
   `HARNESS_SECRET_KEY`, как токены задач), `created_at`, `expires_at`, `revoked_at`, `last_seen_at`). Cookie
   `harness_session` (`HttpOnly`, `Secure`, `SameSite=Strict`, `Path=/api`), TTL `CONSOLE_SESSION_TTL_HOURS` (12).
   Изменяющие запросы требуют заголовок `X-Harness-CSRF`, равный значению из ответа `/api/console/session`
   (double submit, привязан к сессии) — защита сверх SameSite. Вход: ограничение 5 неудачных попыток за 15 минут
   на email и IP (в памяти процесса; одного процесса server в MVP достаточно), ответ одинаковый для неверного email и
   пароля. Логи входа без пароля и без email целиком (маска).
5. **Эндпоинты** (все, кроме входа, требуют сессию):
   - `POST /api/console/login`, `POST /api/console/logout`, `GET /api/console/session`.
   - `GET /api/console/workspaces` — id и имена из `harness.yaml` (без настроек).
   - `GET /api/console/tasks?workspace=&status=` — карточки канбана (до 200, новые сверху), сгруппирует клиент.
   - `GET /api/console/tasks/{id}` — задача, события (`task_events`), последняя `routings`, ветка, MR, итог,
     `tests_state`.
   - `POST /api/console/tasks` — `{text, workspace_id}`: задача `plan` с источником `console` (новое значение
     `TaskSource.CONSOLE`, миграция CHECK), сразу `select_workspace` → `planning`, без Polza (проект выбран
     человеком). Текст ≤ 4000 символов, проходит `redact` до записи, как в Telegram.
   - `GET /api/console/sandbox` — статус, `current_task_id`, `profile_version`, причина ошибки.
   - `POST /api/console/sandbox/pause|resume` — те же функции `services/sandboxes`, что CLI (отказ при активной задаче).
   - `GET /api/console/tasks/{id}/agent-log?lines=200` — хвост `stream.jsonl` и `stderr.log` из песочницы
     (≤ 500 строк, ≤ 64 КиБ) после `redact` с точными значениями всех секретов; задача должна быть закреплена за
     песочницей, иначе 404. Только чтение файлов `~/.harness/tasks/<id>/`, путь строится из UUID, не из ввода.
6. **Обновление данных** — опрос каждые 5 с на открытом экране (TanStack Query `refetchInterval`); WebSocket — после MVP.
7. **Типы.** `harness_shared` экспортирует JSON Schema моделей ответа (`uv run python -m harness_shared.schema`),
   `packages/shared-types` генерирует TS (`json-schema-to-typescript`), сгенерированный файл коммитится; проверка в
   CI: генерация не даёт diff.
8. **Стек консоли:** Vite + React 18 + TypeScript strict, shadcn/ui (Tailwind), TanStack Query, React Router;
   тесты — Vitest + Testing Library (компоненты) и Playwright smoke (вход → канбан) против сервера с фейковыми
   адаптерами; ESLint + Prettier; `pnpm` с lock-файлом. `./tools/harness check` запускает и проверки консоли.
9. **Безопасность ответа:** заголовки nginx `Content-Security-Policy: default-src 'self'`, `X-Frame-Options: DENY`,
   `Referrer-Policy: no-referrer`; ответы API не содержат секретов, токенов задач, `token_hash`, `password_hash`.

## Risks / Trade-offs

- [REST дублирует будущие операторские MCP-инструменты] → один слой сервисов; при `operator-tokens` меняется только
  транспорт панели.
- [Лимит попыток входа в памяти сбрасывается при рестарте] → принято для одного администратора в MVP; общий лимит —
  с `operator-tokens`.
- [Лог агента может содержать секрет, которого нет в списке redaction] → шаблоны токенов + точные значения;
  ограничение объёма; доступ только после входа.
- [Панель увеличивает поверхность атаки] → один origin, HTTPS через Dokploy, CSRF, `HttpOnly` cookie, CSP, без
  публикации портов.
