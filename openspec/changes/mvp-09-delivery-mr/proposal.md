# Proposal: mvp-09-delivery-mr

> Критерий приёмки владельца (D-56, 2026-10-19): после реализации агент коммитит сам и вызывает «сдать работу»;
> push ветки `task/<id>`, MR и сообщение в Telegram делает харнесс после гейтов. Ключ записи агенту не выдаётся.


## Why

Критерий готовности среза: агент делает одну задачу из `backlog`, создан MR, в Telegram «готова, MR создан»
(ТЗ §16.0 п.4–5, «Критерий готовности»). Гейты проверяет харнесс, а не агент (ТЗ §2 п.8); тесты не зелёные
по умолчанию (B1), каждый шаг идемпотентен (B2).

## What Changes

- Пайплайн `implement` в worker: `backlog` → `active` (активация с базой `origin/task/<plan_id>`, D-10; строка
  «начата») → исполнитель → `testing` → гейты → `ready` (строка «готова, MR создан» со ссылкой) → очистка → пауза.
- Промпт исполнителя `services/prompts/implementer.md`: пункт спецификации, путь к изменению OpenSpec, правила
  репозитория (CLAUDE.md/AGENTS.md workspace), `report_task`, коммит в `task/<id>`.
- Гейты сервера: `commit_check` (есть коммиты относительно базы, рабочее дерево чистое; незакоммиченное
  коммитится сервером одним коммитом), `secret_scan`, `tests` (команда workspace; нет команды → `no_tests`),
  `push`, `merge_request` (поиск открытого MR по source branch, иначе создание).
- Адаптер `adapters/gitlab` (`GitProvider`): `find_open_mr`, `create_mr` + фейк.
- Упавший гейт → `error` с причиной в сообщении задачи. Мердж — руками.

## Capabilities

### New Capabilities

- `delivery-gates`: механические проверки результата агента и создание MR.

### Modified Capabilities

Нет.

## Impact

- ENV: `GITLAB_URL`, `GITLAB_TOKEN`. Конфиг: `workspace.gitlab_project`, `workspace.test_command`.
- Зависит от: `mvp-08-spec-planning`.
- Ссылки: ТЗ §6 (MVP-этапы), §10, §16.0 п.4–5, §16.1 A3, B1, B2.

## Не входит

Этапы «тестирование» и «влита MR» в Telegram, кнопки (`telegram-full-stages`), деплой-гейт и тесты как отдельный
процесс с отчётом (`gates-tests-deploy`), авто-мердж и staging (`staging-auto-merge`), очередь на репозиторий (`repo-queue`).
