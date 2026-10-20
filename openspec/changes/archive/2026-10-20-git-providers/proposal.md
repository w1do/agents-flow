# Proposal: git-providers

> Репозиторий workspace на GitHub или GitLab: провайдер, адрес, проект и ключ задаются у каждого workspace.
> Решение владельца 2026-10-19 (D-60): «мы не должны быть привязаны только к gitlab: проект выбирает провайдера —
> GitHub или GitLab, по токену». Заменяет часть D-01 «только GitLab» для репозиториев workspace. Место в плане — 6e,
> до `mvp-07`: владелец хочет скоро запускать задачи worker на GitHub-репозитории `w1do/chistotyumen`.

## Open questions (нужен ответ владельца до реализации)

У каждого вопроса есть вариант по умолчанию, на нём написан design.md. Если владелец выбирает другой вариант,
design.md правится до начала реализации.

1. **Тип токена GitHub.** По умолчанию — fine-grained personal access token на один репозиторий (или на набор
   репозиториев workspace) с правами Repository: Contents — Read and write, Pull requests — Read and write,
   Metadata — Read (выставляется автоматически). Классический токен со scope `repo` тоже работает (git и REST
   принимают оба), но даёт доступ ко всем репозиториям владельца. GitHub App (токен установки на час) — позже,
   отдельным изменением. Вариант: классический токен.
2. **GitHub Enterprise Server.** По умолчанию не поддерживается в этом изменении: для `provider: github` адрес
   только `https://github.com`, иной `base_url` отклоняется конфигом с понятной ошибкой. Поддержка GHE (REST
   `<base_url>/api/v3`) — отдельное изменение, когда появится такой проект. Вариант: разрешить сейчас без live-проверки.
3. **Переход со старого конфига.** По умолчанию — чистый разрыв: секция `gitlab:` и поле `workspaces[].gitlab_project`
   больше не принимаются, конфиг отклоняется с сообщением, куда перенести поля (D-60). Владелец правит боевой
   `harness.yaml` до выката (один файл, шаги — в docs/deployment.md). Вариант: принимать старую форму с
   предупреждением ещё одну версию.
4. **ENV `GITLAB_TOKEN` и `GITLAB_URL`.** По умолчанию удаляются: ключ берётся только из vault по
   `workspaces[].repo.access_ref` (D-45). Один глобальный ключ в ENV не привязан к workspace и провайдеру, а
   GitHub-ключ в переменной с именем GitLab запутывает. Вариант: оставить `GITLAB_TOKEN` запасным ключом для
   workspace с `provider: gitlab` без `access_ref`.
5. **Слова в Telegram.** По умолчанию строка готовности зависит от провайдера workspace: «готова, MR создан» для
   GitLab и «готова, PR создан» для GitHub (`mvp-09`). Вариант: везде «MR».
6. **Правка `.env.example`** (удалить строки `GITLAB_URL`, `GITLAB_TOKEN`) — агентам запрещено читать `.env*`.
   По умолчанию пункт выполняется только по явной команде владельца, иначе пропускается и отмечается в отчёте.
7. **Остаточный риск R-1 (эскалация 1, D-62).** Агент работает в песочнице под тем же пользователем, с `sudo`, а
   каждая команда харнесса запускается login-shell (`bash -l -c`), который читает `~/.profile`. Поэтому агент,
   получивший выполнение кода (prompt injection), может перехватить ключ, попавший в песочницу после его работы, —
   в том числе главный ключ GitHub с доступом ко всем репозиториям. Это изменение закрывает подмену через файлы
   конфига git и ключи в env установок, но не эту границу. По умолчанию: риск принимается для 6e, в PLAN.md
   добавляется отдельное изменение (git с ключом вне песочницы или песочница на workspace) и переход на
   fine-grained ключ на репозиторий. Вариант: не запускать задачи на GitHub с главным ключом до этого изменения.
   Ответ владельца 2026-10-19: принять R-1, закрытие — отдельное изменение в PLAN.md.

## Why

Сейчас адрес Git-хостинга один на весь харнесс (`gitlab.base_url`), ключ один (`gitlab.access_ref` или ENV
`GITLAB_TOKEN`), а git в песочнице авторизуется только по схеме GitLab (`oauth2:<token>`, D-52). Проект на GitHub
можно склонировать только анонимно, а push и PR для него не спроектированы. Владелец хочет, чтобы workspace сам
выбирал провайдера, и первым запустить worker на GitHub-репозитории `w1do/chistotyumen`.

## What Changes

- **Конфиг (BREAKING):** у каждого workspace блок `repo`: `provider: github | gitlab`, `base_url` (только https;
  по умолчанию `https://github.com` и `https://gitlab.com`), `project` (`owner/name` или `group/subgroup/name`),
  `access_ref` (ссылка vault, необязательна для публичного репозитория в режиме только чтения). `default_branch`
  остаётся полем workspace. Секция `gitlab:` и поле `gitlab_project` удаляются, старая форма отклоняется с
  сообщением о переносе.
- **Авторизация git по workspace:** заголовок `Authorization: Basic base64("<user>:<token>")` привязан к префиксу
  адреса клона этого workspace (`<base_url>/<project>.git/`), а не ко всему хосту. Пользователь Basic: `oauth2`
  для GitLab, `x-access-token` для GitHub. Редиректы выключены, токен не попадает в argv и файлы (как D-52).
- **Bootstrap (уточнено эскалацией 1, D-62):** аргумент `--gitlab-url` удаляется. Скрипт больше не клонирует:
  `bootstrap.sh --phase setup` ставит пакеты без ключей в env, затем сервер клонирует или обновляет репозиторий
  каждого workspace отдельной git-командой с ключом только этого workspace, затем `bootstrap.sh --phase memory`
  индексирует клоны с ключом embeddings. Workspace без ключа — анонимно. Команда git с ключом перекрывает настройки
  `.git/config` клона, `~/.gitconfig` и `/etc/gitconfig` (прокси, TLS, хуки, помощники учётных данных) и идёт по
  адресу из конфига, а не по `origin`.
- **Активация и задачи:** fetch задачи идёт с ключом её workspace; перед fetch сервер возвращает `origin` клона на
  адрес из конфига. Worker требует ключ workspace для каждой задачи (все пайплайны пушат ветку): без
  `repo.access_ref` задача уходит в `error` с понятной причиной до активации песочницы (нет fetch и worktree).
- **Redaction:** шаблоны токенов GitHub (`ghp_`, `gho_`, `ghu_`, `ghs_`, `ghr_`, `github_pat_`), расширенные
  префиксы GitLab и заголовок `Basic …`; точные значения токена и заголовка каждого workspace.
- **`mvp-09-delivery-mr`:** адаптер `adapters/git` с протоколом `GitProvider` и реализациями `gitlab` (MR, REST v4)
  и `github` (PR, REST), фейк, контрактные тесты respx. Внутренний термин харнесса остаётся «MR» (D-56, глоссарий),
  для GitHub это pull request.
- **PLAN.md:** строка 6e `git-providers` перед `mvp-07`, `mvp-09` зависит от `git-providers`.

## Capabilities

### New Capabilities

Нет.

### Modified Capabilities

- `platform-config`: MODIFIED — Описание workspace в конфиге, Секреты и учётные данные в конфигурации; ADDED —
  Репозиторий workspace, Адрес репозитория только https.
- `sandbox-profile`: MODIFIED — Bootstrap без участия владельца, Ключи из vault; ADDED — Авторизация git по
  workspace, Заголовки репозиториев в bootstrap.
- `sandbox-runtime`: ADDED — Ключ записи репозитория перед задачей, Токены git-провайдеров в redaction.

## Impact

- Код: `config.py`, новый `services/git_access.py`, `services/sandboxes.py` (`bootstrap`, `activate`, удаление
  `clone_url`/`git_auth_*`), `worker/dispatcher.py`, `cli.py`, `settings.py`, `security/redaction.py`,
  `deploy/sandbox/bootstrap.sh`, тесты.
- Конфиг: боевой `harness.yaml` правится владельцем до выката (BREAKING). ENV `GITLAB_URL`, `GITLAB_TOKEN`
  больше не читаются.
- Документация: ARCHITECTURE.md §1, §5, §7, §9; docs/deployment.md, docs/operating-without-ui.md,
  `apps/server/README.md`, `config/harness.example.yaml`, docs/decisions.md (D-60, пометки D-01 и D-52), PLAN.md.
- Нумерация решений: D-57…D-59 и D-61 уже в `main` (`task-rework`, гейты D-58, деплой Dokploy D-59,
  `TELEGRAM_API_URL` D-61). Решение этого изменения — D-60.
- `task-rework` (D-57) и гейты D-58 в `mvp-09` описывали `adapters/gitlab`. Это изменение переводит их на
  `adapters/git`: в `mvp-09` — порядок гейтов D-58 сохранён, `push`/`merge_request` работают для GitLab (MR) и
  GitHub (PR); в `task-rework` — путь модуля, тип `MergeRequestState` вместо `MrState`, `add_mr_note(project,
  number, body)`, провайдер workspace через `BotContext.git_for`, текст «ветка расходится с удалённым репозиторием».
- Зависит от: `sandbox-profile` (done). `mvp-09-delivery-mr` начинает зависеть от `git-providers`.
- Ссылки: D-01, D-45, D-52, D-56; ТЗ §16.0 п.4–5.

## Не входит

- GitHub Enterprise Server и GitHub App (вопросы 1–2).
- Другие провайдеры (Bitbucket, Gitea) — протокол `GitProvider` позволяет добавить их позже.
- Хостинг самого харнесса, CI и Registry (D-01 в этой части не меняется; сборка из GitHub — D-59).
- Задачи только на чтение (`check-tasks`): флаг пайплайна «без push» появится там.
- Push, MR/PR и гейты — `mvp-09-delivery-mr`.
