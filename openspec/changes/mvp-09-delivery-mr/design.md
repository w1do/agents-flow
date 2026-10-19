# Design: mvp-09-delivery-mr

## Context

Гейты выполняются сервером exec-командами в worktree задачи (D-03). Провайдер репозитория — у workspace: GitHub
или GitLab (D-60, изменение `git-providers`; заменяет «только GitLab» из D-01). Ветка реализации растёт от ветки
плана (D-10).

## Goals / Non-Goals

**Goals:** обрыв посреди гейтов продолжается с того же шага; ни один секрет не уходит в удалённый репозиторий;
«готова» означает проверенный результат; базовые гейты нельзя отключить конфигом, задачей или агентом (D-58).

**Non-Goals:** авто-мердж, деплой, параллельные задачи.

## Decisions

- **Гейты — упорядоченный список шагов** с состоянием в `task_events` (`gate:<name>:passed|failed|skipped`).
  Повторный запуск пайплайна пропускает шаги с `passed`, кроме `secret_scan` и `tests`, если после них появились
  новые коммиты. Альтернатива — отдельная таблица шагов: избыточно для MVP.
- **Коммит незакоммиченного делает сервер** (`git add -A && git commit -m "<task>: <title>"`) — агент мог забыть;
  если изменений нет совсем — `error` «нет изменений».
- **Тесты:** `gates.test` (или `test_command`) из конфига в worktree, таймаут из настроек. Нет команды → `tests_state=no_tests` и
  пометка «без тестов» в сообщении; задача всё равно может стать `ready` (мердж руками страхует, ТЗ §16.0).
  Ненулевой код → `tests_state=failed`, задача `error`, хвост вывода (redacted, 30 строк) в причине.
- **MR:** `find_open_mr(project, source_branch)` → если есть, используем; иначе `create_mr(source=task/<id>,
  target=<default_branch>, title, description)` с ссылкой на изменение OpenSpec и пункт. URL сохраняется в задаче.
- **Адаптер `adapters/git`** (контракт — design.md `git-providers`, раздел 9): `protocol.py` (`GitProvider`,
  `MergeRequestRef(number, url)`, `MergeRequestState`, `GitProviderError(reason)`), `gitlab.py` (`GitLabProvider`),
  `github.py` (`GitHubProvider`), `fake.py` (`FakeGitProvider`), `factory.py` (`build_git_provider(provider,
  base_url, token, client)`). httpx async, без python-gitlab и PyGithub (минимум зависимостей). Ключ — из vault по
  `repo.access_ref` workspace (D-60), только в заголовке запроса. `follow_redirects=False`, таймаут 30 с. Ошибки:
  сеть → `GitProviderError("network")`, не 2xx → `GitProviderError(f"http_{status}")`, неожиданный JSON →
  `GitProviderError("bad_response")`; тело ответа и ключ в текст ошибки не попадают.
  - **GitLab** (`<base_url>/api/v4`, заголовок `Authorization: Bearer <token>`, проект — `quote(project, safe="")`):
    `find_open_mr` — `GET /projects/:id/merge_requests?state=opened&source_branch=<b>` → первый `iid`, `web_url`;
    `create_mr` — `POST /projects/:id/merge_requests` `{source_branch, target_branch, title, description}`, ответ 409
    (MR уже есть) → повторный `find_open_mr`.
  - **GitHub** (`https://api.github.com`, заголовки `Authorization: Bearer <token>`, `Accept:
    application/vnd.github+json`, `X-GitHub-Api-Version: 2022-11-28`, проект `owner/name`): `find_open_mr` —
    `GET /repos/{owner}/{name}/pulls?state=open&head={owner}:{branch}` → первый `number`, `html_url`; `create_mr` —
    `POST /repos/{owner}/{name}/pulls` `{title, head: <branch>, base: <target>, body}`, ответ 422 (PR уже есть) →
    повторный `find_open_mr`.
  - `get_mr_state` и `add_mr_note` (`task-rework`): GitLab — `GET …/merge_requests?source_branch=<b>&order_by=created_at&sort=desc`
    (`opened`/`locked` → `open`, `merged`, `closed`; пусто → `none`) и `POST …/merge_requests/:iid/notes {body}`;
    GitHub — `GET …/pulls?state=all&head={owner}:{branch}&sort=created&direction=desc` (`merged_at` не null →
    `merged`, `state=open` → `open`, иначе `closed`; пусто → `none`) и `POST /repos/{owner}/{name}/issues/{number}/comments {body}`.
- **Слова для владельца:** строка этапа «готова, {label} создан», где `label = git_access.change_request_label(provider)`
  («MR» для GitLab, «PR» для GitHub).

### Гейты в три уровня (D-58)

- **Порядок гейтов:** `commit_check` → `secret_scan` → `path_policy` → `diff_limits` → гейты качества проекта
  (`tests` для `code`) → `branch_guard` → `push` → `merge_request` (MR в GitLab, PR в GitHub через `GitProvider`
  workspace, D-60) → запрос приёмки владельца (если нужен). Базовые
  гейты (уровень 1) — список в коде (`services/gates/core.py`, константа `CORE_GATES`), конфиг его не читает.
  Альтернатива — общий список гейтов в конфиге с обязательным `secrets` (прежний план `gates-tests-deploy`):
  конфиг или ошибка в нём могли бы отключить проверку безопасности.
- **`secret_scan`:** `git diff <base>..HEAD` проверяется шаблонами `security/redaction` и точными значениями всех
  секретов задачи (выданные креды, ключи, разрешённые из vault, `ctx.secret_values`). Находка → `error`, в причине
  файл и строка, значения нет. Альтернатива — проверка skill'ом агента: skill — совет агенту, а не принуждение.
- **`path_policy`:** изменённые пути (`git diff --name-only --no-renames <base>..HEAD` плюс исходные пути
  переименований) сверяются с `CORE_DENY_PATHS` в коде: `.env`, `.env.*` (кроме `.env.example`), `*.pem`, `*.key`,
  `id_rsa*`, `id_ed25519*`, `.harness/**`, `.git/**`, `.claude/settings*.json`, `.mcp.json`. Совпадение
  (fnmatch по POSIX-пути от корня репозитория) → `error` «запрещённый путь: <путь>». Альтернатива — allowlist по
  workspace: в MVP нет данных, какие пути нужны проектам. Allowlist workspace может только сузить набор
  (`gates-tests-deploy`).
- **`diff_limits`:** константы в коде `DIFF_MAX_FILES = 300`, `DIFF_MAX_LINES = 20000` (сумма добавленных и удалённых
  строк по `git diff --numstat`), бинарный файл (`-	-` в numstat) больше `BINARY_MAX_BYTES = 1 MiB` или сумма
  бинарных больше `BINARY_TOTAL_MAX_BYTES = 5 MiB` → `error` с числами без содержимого. Альтернатива — лимиты в
  конфиге: агент или ошибка конфига ослабили бы их. Лимиты меняются только правкой кода с записью в decisions.md.
- **`branch_guard`:** push только явным refspec `HEAD:refs/heads/task/<task_id>`, без `--force`. Имя ветки
  собирается сервером из id задачи, а не берётся из worktree. Целевая ветка, равная `default_branch` workspace или
  не начинающаяся с `task/`, → `error` до push. MR создаётся только из `task/<id>` в `default_branch`.
- **Гейты качества проекта:** `WorkspaceConfig.gates: WorkspaceGates` (`preset: Literal["code", "none"] = "code"`,
  `test: str | None = None`, `extra="forbid"`). Пресет — шаблон набора гейтов уровня 2, отдельного механизма нет:
  `PRESETS = {"code": ("tests",), "none": ()}` в `services/gates/presets.py`. Переопределение `test` задаёт
  команду. Старое поле `test_command` — синоним `gates.test`: если заданы оба, конфиг отклоняется («задайте только
  gates.test»). Альтернатива — убрать `test_command` сразу: сломался бы рабочий `harness.yaml` владельца.
- **Решение за владельцем.** `code` без команды → `tests_state = no_tests`. `none` → гейт `tests` отмечается
  `skipped`, `tests_state = not_run`. В обоих случаях после MR задача получает `ready` с пометкой «без
  автоматических проверок — нужно решение владельца» и кнопкой «Принять» (`ac:<task hex>`). Нажатие пишет событие
  `approval:accepted` с источником `telegram` и строку «принята владельцем». Статус задачи не меняется, мердж
  по-прежнему руками. «Пройдено» в сообщении появляется только при `tests_state = passed`. Кнопку «Доработать»
  рядом добавляет `task-rework`. Альтернатива — новый статус «ждёт приёмки»: вне набора ТЗ v5.
- **Уровень задачи** (только добавлять проверки или требовать приёмку) в MVP не реализуется. Контракт для
  `gates-tests-deploy`: итоговый набор = базовые ∪ проектные ∪ задачные, удаление невозможно по построению
  (объединение множеств).
- **Агент не оценивает себя.** Отчёт агента («тесты прошли») на гейты не влияет: гейты запускает сервер
  exec-командами в worktree и смотрит только на коды возврата. Skills учат агента проходить проверки.

## Risks / Trade-offs

- [`path_policy` блокирует законную правку `.claude/settings.json` проекта] → правка руками владельца; список
  меняется решением.
- [Лимиты diff малы для генерации кода или ассетов] → константы правятся с записью в decisions.md.

- [В MR попадают коммиты плана] → ожидаемо по D-10; после мерджа первого MR остальные MR показывают только свой код.
- [Тесты workspace долгие] → таймаут `TESTS_TIMEOUT_MIN`; полноценный учёт процессов — `processes`.
