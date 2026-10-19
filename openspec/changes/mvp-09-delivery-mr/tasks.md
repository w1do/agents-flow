# Tasks

## 1. GitLab

- [ ] 1.1 `adapters/gitlab`: Protocol `GitProvider` (`find_open_mr`, `create_mr`), httpx REST v4, фейк; контрактные тесты respx — проверка: pytest
- [ ] 1.2 Live-тест `-m live`: создание и поиск MR в тестовом проекте — проверка: проходит вручную

## 2. Гейты

- [ ] 2.1 `commit_check`: коммит незакоммиченного сервером, `error` «нет изменений» — проверка: тест «Пустой результат»
- [ ] 2.2 `tests`: команда workspace, таймаут `TESTS_TIMEOUT_MIN`, `no_tests`/`passed`/`failed`, хвост вывода через redaction — проверка: тесты «Нет команды тестов», «Тесты упали»
- [ ] 2.3 `merge_request`: поиск существующего, создание, сохранение URL — проверка: тест «MR уже существует»
- [ ] 2.4 Состояние шагов в событиях и пропуск выполненных при повторе — проверка: тест «Обрыв после push»
- [ ] 2.5 `secret_scan` на diff реализации с кредами задачи и ключами из vault (D-58) — проверка: тест «Ключ в коде»
- [ ] 2.6 Базовые гейты D-58 в `services/gates/core.py` (`CORE_GATES`, `CORE_DENY_PATHS`, лимиты diff): `path_policy`,
  `diff_limits`, `branch_guard` — проверка: тесты «Агент изменил .env», «Большой бинарный файл», «Попытка в основную
  ветку», «Пресет без проверок»
- [ ] 2.7 `WorkspaceGates` (`preset` `code`/`none`, `test`) в `config.py`, синоним `test_command`, `PRESETS` в
  `services/gates/presets.py`; `config/harness.example.yaml` — проверка: тесты «Оба поля команды тестов», «Пресет по умолчанию»
- [ ] 2.8 Пометка «без автоматических проверок — нужно решение владельца», кнопка «Принять» (`ac:<task hex>`),
  событие `approval:accepted` — проверка: тесты «Workspace без проверок», «Агент сообщил о тестах»

## 3. Исполнитель

- [ ] 3.1 `services/prompts/implementer.md` (пункт спецификации, путь изменения, правила репо, `report_task`, коммит) — проверка: снапшот-тест
- [ ] 3.2 Пайплайн `implement` в `worker/pipelines/implement.py`: claim из `backlog` → `active` («начата») → агент → `testing` → гейты → `ready` («готова, MR создан») → очистка → пауза — проверка: тест «Успешная задача» с фейками

## 4. Сквозная проверка среза

- [ ] 4.1 Live: голосом «создай X» → план → задачи в `backlog` → одна задача → MR → сообщение в Telegram (критерий ТЗ §16.0) — проверка: ссылки на MR и скриншот чата в PR
- [ ] 4.2 ARCHITECTURE.md §5 п.5–7, §9 (`GITLAB_*`, `TESTS_TIMEOUT_MIN`, `workspaces[].gates`), §5 п.6 и §8 (гейты D-58), docs/deployment.md, PLAN.md (MVP принят) — проверка: ревью

## 5. Память проекта

- [ ] 5.1 `memory_update` по изменённым путям, `memory_annotate` для каждого нового файла, `memory_status` без устаревших файлов
