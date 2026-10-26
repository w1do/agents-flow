# Design: mvp-10-operator-console

## Context

К `mvp-10` есть: задачи, события и очередь (`mvp-03`), Telegram и маршрутизация (`mvp-04`, `mvp-05`), песочница и
запуск агента (`mvp-06`), MCP (`mvp-07`), планирование и доставка MR (`mvp-08`, `mvp-09`). Интерфейс — только
Telegram, CLI и `POST/GET /tasks` с временным `HARNESS_ADMIN_TOKEN` (D-23). Операторских токенов (`operator-tokens`)
в MVP нет, поэтому панель не может ходить в MCP как оператор. Каталог проектов уже есть на сервере (D-65):
`/api/console/projects` работает под тем же `HARNESS_ADMIN_TOKEN`.

## Goals / Non-Goals

**Goals:** владелец входит в браузере, видит канбан и ленту задачи, создаёт задачу, видит песочницу и вывод агента,
ставит песочницу на паузу, ведёт настройки проектов (список, создание, редактирование, отключение); ни один секрет не
попадает в браузер; панель не содержит бизнес-логики.

**Non-Goals:** настройки песочниц и профилей агента вне полей проекта (`console-settings`), несколько пользователей и
роли, серверные сессии и вход по паролю на этом этапе (см. «Исключение этапа»), MCP-доступ панели, realtime через
WebSocket.

## Исключение этапа: вход токеном

Решение владельца для этого этапа: оператор вводит `HARNESS_ADMIN_TOKEN` на экране «Вход», токен держится только в
памяти вкладки. Серверных сессий на этом этапе нет. Решения 3 и 4 ниже сохранены как целевая схема и отложены.

Что это меняет:

- Не создаются таблицы `admins` и `console_sessions`; не нужны `ADMIN_EMAIL`, `ADMIN_PASSWORD`,
  `CONSOLE_SESSION_TTL_HOURS` и команда `reset-password`.
- Нет `POST /api/console/login`, `POST /api/console/logout`, `GET /api/console/session`, cookie `harness_session`,
  заголовка `X-Harness-CSRF` и лимита попыток входа.
- Все эндпоинты панели принимают `Authorization: Bearer <HARNESS_ADMIN_TOKEN>` тем же способом, что `/tasks` (D-23) и
  `/api/console/projects` (D-65). Отсутствующий, неверный или не настроенный токен — 401 без подробностей.
- Токен не записывается в `localStorage`, `sessionStorage`, cookie и URL. После перезагрузки вкладки его вводят заново.

Причина: оператор один; токен уже проверяется на сервере и защищает `/tasks` и каталог проектов. Сессия с паролем —
отдельный объём работ (таблицы, хеш, сброс, CSRF), который не нужен, чтобы проверить сквозной поток и настройки в
браузере. Браузер не прикладывает заголовок `Authorization` сам, поэтому CSRF-заголовок и `SameSite` для этого способа
не нужны.

Цена: токен живёт в памяти страницы и доступен её скриптам, поэтому XSS опаснее, чем при `HttpOnly` cookie. Защита —
CSP `default-src 'self'` (решение 9) и отсутствие внешних скриптов. Серверные сессии (решения 3–4) возвращаются
отдельным изменением вместе с `console-auth`.

## Decisions

1. **REST для панели в MVP (D-39).** `api/console/*` — тонкий вход: проверка доступа → функция `services/*` →
   Pydantic-модель ответа из `harness_shared.console`. Те же функции вызывают Telegram и CLI (CLAUDE.md §3).
   Эндпоинты проектов уже живут в `apps/server/src/harness_server/api/projects.py` (префикс `/api/console/projects`)
   и не переносятся (см. решение 10). После `operator-tokens` панель переходит на MCP (`console-auth`), REST остаётся до
   этой миграции.
2. **Один origin.** Сервис `console` — nginx: SPA-статика и `location /api/ { proxy_pass http://server:8000; }`
   внутри `dokploy-network`. Наружу — только домен консоли в Dokploy (HTTPS), порты не публикуются. CORS не нужен.
   Cookie `SameSite=Strict` — для отложенных сессий (см. «Исключение этапа»).
3. **(отложено) Администратор.** Таблица `admins` (`id`, `email` UNIQUE, `password_hash`, `created_at`,
   `password_changed_at`). При старте `server` (lifespan) и в CLI: если строк нет и заданы `ADMIN_EMAIL`/`ADMIN_PASSWORD` —
   создать; если строка есть — ENV пароль не перезаписывает. Хеш — `hashlib.scrypt` (n=2^15, r=8, p=1, соль 16 байт) в
   формате `scrypt$n$r$p$salt$hash` (stdlib, без новой зависимости), сравнение `hmac.compare_digest`.
   `ADMIN_PASSWORD` ≥ 12 символов (проверка в `settings.py`). `harness-server reset-password --email` спрашивает
   пароль интерактивно (не аргументом — не попадает в историю shell), меняет хеш и отзывает все сессии.
4. **(отложено) Сессии.** Таблица `console_sessions` (`id`, `admin_id`, `token_hash` UNIQUE (HMAC-SHA256 с
   `HARNESS_SECRET_KEY`, как токены задач), `created_at`, `expires_at`, `revoked_at`, `last_seen_at`). Cookie
   `harness_session` (`HttpOnly`, `Secure`, `SameSite=Strict`, `Path=/api`), TTL `CONSOLE_SESSION_TTL_HOURS` (12).
   Изменяющие запросы требуют заголовок `X-Harness-CSRF`, равный значению из ответа `/api/console/session`
   (double submit, привязан к сессии) — защита сверх SameSite. Вход: ограничение 5 неудачных попыток за 15 минут
   на email и IP (в памяти процесса; одного процесса server в MVP достаточно), ответ одинаковый для неверного email и
   пароля. Логи входа без пароля и без email целиком (маска).
5. **Эндпоинты.** Все эндпоинты панели принимают `Authorization: Bearer <HARNESS_ADMIN_TOKEN>` (см. «Исключение этапа»).
   Вход и сессии (`login`, `logout`, `session`) на этом этапе не вводятся.
   - `GET /api/console/workspaces` — id и названия активных проектов из каталога (D-65), без настроек. Блок `workspaces`
     в `harness.yaml` сервер отклоняет, поэтому список берётся не из файла.
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
   - Проекты (уже есть в `api/projects.py`, решение 10): `GET /api/console/projects` — все проекты, включая
     отключённые; `GET /api/console/projects/{id}`; `POST /api/console/projects` — тело `ProjectInput` с `id`, ответ 201;
     занятый id — 409, существующий проект не меняется; `PATCH /api/console/projects/{id}` — `ProjectUpdate`;
     `POST /api/console/projects/{id}/disable`. Эндпоинт `GET /api/projects/{id}/settings` — для `agent init`, панель
     его не использует.
6. **Обновление данных** — опрос каждые 5 с на открытом экране (TanStack Query `refetchInterval`); WebSocket — после MVP.
7. **Типы.** `harness_shared` экспортирует JSON Schema моделей ответа (`uv run python -m harness_shared.schema`),
   `packages/shared-types` генерирует TS (`json-schema-to-typescript`), сгенерированный файл коммитится; проверка в
   CI: генерация не даёт diff. Типы проектов (`harness_shared/projects.py`) попадают в ту же генерацию; ручных копий нет.
8. **Стек консоли:** Vite + React 18 + TypeScript strict, shadcn/ui (Tailwind), TanStack Query, React Router;
   тесты — Vitest + Testing Library (компоненты) и Playwright smoke (вход → канбан) против сервера с фейковыми
   адаптерами; ESLint + Prettier; `pnpm` с lock-файлом. `./tools/harness check` запускает и проверки консоли.
9. **Безопасность ответа:** заголовки nginx `Content-Security-Policy: default-src 'self'`, `X-Frame-Options: DENY`,
   `Referrer-Policy: no-referrer`; ответы API не содержат секретов, токенов задач, `token_hash`, `password_hash`.
10. **Настройки проектов в панели.** Экраны списка, создания и редактирования, отключение — по `ProjectRead`,
    `ProjectInput` и `ProjectUpdate` из `harness_shared/projects.py`. Правила:
    - `id` задаётся только при создании и не меняется; формат — `PROJECT_ID_PATTERN` (не длиннее 28 символов, D-28).
    - `PATCH` меняет только переданные поля, но блок `repo` заменяется целиком. Форма отправляет его полностью, включая
      `access_ref` из последнего чтения; иначе ссылка на ключ снимается (D-65).
    - Поле `test_command` — единственное необязательное, которое можно сбросить в `null`; остальные обязательные поля
      `null` не принимают.
    - Ключ репозитория в форму не вводится. Поле `access_ref` — только ссылка вида `vault:<project>/<service>/<name>`;
      значение ключа панель не получает (D-45, D-60).
    - Ошибка проверки 422 `invalid_project` приходит со списком `fields`: подсвечиваются только эти поля, значения в
      тексте не выводятся. Коды 404 `not_found`, 409 `project_conflict` и `project_disabled` показываются текстом по коду.
    - Клиентская проверка формы — подсказка до отправки. Главные правила у сервера; клиент не копирует их как типы.
    - Отключение — после подтверждения. Новые задачи по проекту и выдача его настроек прекращаются; задачи в работе
      не останавливаются (D-65).

## Risks / Trade-offs

- [REST дублирует будущие операторские MCP-инструменты] → один слой сервисов; при `operator-tokens` меняется только
  транспорт панели.
- [Токен в памяти вкладки доступен скриптам страницы (XSS)] → CSP `default-src 'self'`, без внешних скриптов, токен не
  сохраняется в хранилище браузера; полноценная защита — сессии после `console-auth`.
- [Лимит попыток входа в памяти сбрасывается при рестарте] → (отложено вместе с сессиями) принято для одного
  администратора в MVP; общий лимит — с `operator-tokens`.
- [Лог агента может содержать секрет, которого нет в списке redaction] → шаблоны токенов + точные значения;
  ограничение объёма; доступ только с токеном оператора.
- [Панель увеличивает поверхность атаки] → один origin, HTTPS через Dokploy, CSP, без публикации портов.
- [PATCH блока `repo` без `access_ref` снимает ссылку на ключ (D-65)] → форма отправляет весь блок `repo`; тест
  «Редактирование проекта» проверяет тело запроса.
