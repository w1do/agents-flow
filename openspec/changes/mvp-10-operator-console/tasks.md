# Tasks

Решения — `design.md` и D-39 (`docs/decisions.md`). Начинается после принятия `mvp-09` (PLAN.md).

## 1. Сервер: администратор и сессии

- [ ] 1.1 Миграция: таблицы `admins`, `console_sessions`; `TaskSource.CONSOLE` в `harness_shared` и CHECK — проверка: `test_migrations.py`
- [ ] 1.2 `security/passwords.py` (scrypt, формат, `compare_digest`), `ADMIN_PASSWORD` ≥ 12 и `CONSOLE_SESSION_TTL_HOURS` в `settings.py` — проверка: `test_passwords.py`, `test_settings.py`
- [ ] 1.3 `services/admins.py`: создание при первом старте (lifespan server и CLI), вход, сессии, CSRF, лимит попыток, отзыв — проверка: тесты «Первый старт», «Неверный пароль», «Перебор пароля», «Запрос без сессии», «Запрос без CSRF-заголовка»
- [ ] 1.4 `harness-server reset-password --email` (пароль через prompt без эха) — проверка: тест «Сброс пароля»

## 2. Сервер: API панели

- [ ] 2.1 `harness_shared/console.py`: модели ответов; `python -m harness_shared.schema` — JSON Schema — проверка: mypy, тест схемы
- [ ] 2.2 `api/console/` (auth, tasks, sandbox, logs) — тонкие входы над `services/` — проверка: тесты «Канбан», «Карточка задачи»
- [ ] 2.3 `services/tasks.create_from_console` (текст через `redact`, `select_workspace` → `planning`) — проверка: тесты «Новая задача», «Неизвестный проект»
- [ ] 2.4 Песочница и лог агента через `services/sandboxes` (mvp-06) — проверка: тесты «Пауза занятой песочницы из панели», «Секрет в логе агента», «Лог чужой задачи» с `FakeSandbox`

## 3. Консоль

- [ ] 3.1 `apps/console`: Vite + React + TS strict + shadcn/ui + TanStack Query + React Router, ESLint + Prettier, pnpm, README — проверка: `pnpm lint`, `pnpm typecheck`, `pnpm build`
- [ ] 3.2 `packages/shared-types`: генерация TS из JSON Schema, файл в git — проверка: генерация в CI без diff
- [ ] 3.3 Экраны «Вход», «Канбан», «Задача», «Новая задача», «Песочница» (опрос 5 с, CSRF-заголовок) — проверка: Vitest + Testing Library
- [ ] 3.4 Playwright smoke: вход → канбан → новая задача → карточка, против server с фейковыми адаптерами — проверка: проходит в CI

## 4. Деплой и документация

- [ ] 4.1 `deploy/console/` (Dockerfile, nginx.conf с прокси `/api`, CSP и заголовками), сервис `console` в `docker-compose.yml` (expose, `dokploy-network`), GitLab CI: check и build консоли — проверка: `docker compose config`, CI ≤ 10 минут
- [ ] 4.2 `./tools/harness check` запускает проверки консоли — проверка: локальный прогон
- [ ] 4.3 ARCHITECTURE.md (§1, §2, §4, §9, Compose), `.env.example`, `docs/deployment.md` (домен консоли), PLAN.md, CLAUDE.md §2 — проверка: ревью
- [ ] 4.4 Ручная проверка владельцем: голосом «создай X» → задача видна в канбане → лог агента в «Песочнице» → MR в карточке — проверка: закрывает владелец

## 5. Память проекта

- [ ] 5.1 `memory_update` по изменённым путям, `memory_annotate` для каждого нового и изменённого файла, `memory_status` без устаревших файлов
