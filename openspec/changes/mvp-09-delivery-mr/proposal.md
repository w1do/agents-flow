# Proposal: mvp-09-delivery-mr

> Критерий приёмки владельца (D-56, 2026-10-19): после реализации агент коммитит сам и вызывает «сдать работу»;
> push ветки `task/<id>`, MR и сообщение в Telegram делает харнесс после гейтов. Ключ записи агенту не выдаётся.
>
> Гейты в три уровня (D-58, 2026-10-19). В MVP входят базовые гейты безопасности (в коде, всегда, не настраиваются)
> и гейты качества проекта из `harness.yaml`: пресет `code` или `none` плюс одна команда тестов. Пресеты, гейты
> уровня задачи, файл гейтов в репозитории и гейт деплоя — в `gates-tests-deploy`.


## Why

Критерий готовности среза: агент делает одну задачу из `backlog`, создан MR, в Telegram «готова, MR создан»
(ТЗ §16.0 п.4–5, «Критерий готовности»). Гейты проверяет харнесс, а не агент (ТЗ §2 п.8); тесты не зелёные
по умолчанию (B1), каждый шаг идемпотентен (B2).

## What Changes

- Пайплайн `implement` в worker: `backlog` → `active` (активация с базой `origin/task/<plan_id>`, D-10; строка
  «начата») → исполнитель → `testing` → гейты → `ready` (строка «готова, MR создан», для GitHub «готова, PR создан», со ссылкой) → очистка → пауза.
- Промпт исполнителя `services/prompts/implementer.md`: пункт спецификации, путь к изменению OpenSpec, правила
  репозитория (CLAUDE.md/AGENTS.md workspace), `report_task`, коммит в `task/<id>`.
- **Базовые гейты безопасности** (D-58, уровень 1). Работают всегда, заданы в коде, конфиг и задача их не
  отключают: `commit_check` (есть коммиты относительно базы, рабочее дерево чистое; незакоммиченное сервер
  коммитит одним коммитом), `secret_scan` (шаблоны `security/redaction` + точные значения выданных кредов и
  ключей из vault), `path_policy` (запрещённые пути), `diff_limits` (размер diff и бинарные файлы),
  `branch_guard` (push только в `task/<id>`, никогда в основную ветку), идемпотентные `push` и `merge_request`
  (поиск открытого MR/PR по source branch, иначе создание).
- **Гейты качества проекта** (D-58, уровень 2) из `workspaces[].gates` в `harness.yaml`: `preset` (`code` по
  умолчанию или `none`) и переопределение `test` (команда тестов). `code`: гейт `tests`, нет команды → `no_tests`,
  решение за владельцем, «пройдено» не пишется никогда. `none`: автоматических проверок качества нет, готовую
  задачу принимает владелец кнопкой «Принять» в Telegram. Поле `test_command` остаётся синонимом `gates.test`.
- Адаптер `adapters/git` (`GitProvider`, контракт — design.md `git-providers`, D-60): реализации `gitlab` (merge
  request, REST v4) и `github` (pull request, REST), `find_open_mr`, `create_mr` + фейк; провайдер — из
  `workspaces[].repo.provider`. Внутренний термин харнесса — «MR»; владелец видит «MR» для GitLab и «PR» для GitHub.
- Push ветки — git в песочнице с заголовком ключа workspace (`git_access.git_auth_env`, D-60), без `--force`.
- Упавший гейт → `error` с причиной в сообщении задачи. Мердж — руками.

## Capabilities

### New Capabilities

- `delivery-gates`: механические проверки результата агента и создание MR.

### Modified Capabilities

Нет.

## Impact

- ENV: нет новых; ключ репозитория — `workspaces[].repo.access_ref` из vault (D-60, `GITLAB_TOKEN` не используется).
  Конфиг: `workspaces[].repo` (`provider`, `base_url`, `project`), `workspace.gates.preset`, `workspace.gates.test`
  (синоним — `workspace.test_command`).
- Зависит от: `mvp-08-spec-planning`, `git-providers` (6e, D-60).
- Ссылки: ТЗ §6 (MVP-этапы), §10, §16.0 п.4–5, §16.1 A3, B1, B2.

## Не входит

Этапы «тестирование» и «влита MR» в Telegram, кнопки, кроме «Принять» (`telegram-full-stages`); кнопка «Доработать»
(`task-rework`); пресеты кроме `code`/`none`, гейты уровня задачи, файл гейтов в репозитории, деплой-гейт и тесты как
отдельный процесс с отчётом (`gates-tests-deploy`), авто-мердж и staging (`staging-auto-merge`), очередь на репозиторий (`repo-queue`).
