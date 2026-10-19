# Tasks

Порядок и детали — design.md («Detailed specification», «Ordered implementation steps»). Вопросы владельцу —
proposal.md; без ответа действует вариант по умолчанию.

## 0. Подготовка

- [ ] 0.1 Ответы владельца на вопросы 1–6 proposal.md записаны в D-60 (или design.md поправлен до реализации) — проверка: ревью

## 1. Конфиг

- [ ] 1.1 `RepoConfig`, `WorkspaceConfig.repo`, удаление `GitLabConfig`/`HarnessConfig.gitlab`, сообщения о старой
  форме (design 1) — проверка: тесты `test_repo_*`, `test_legacy_*` в `test_config.py`
- [ ] 1.2 `config/harness.example.yaml`: `repo` у `demo`, пример GitHub, без `gitlab:` — проверка: пример загружается тестом

## 2. Адрес и авторизация git

- [ ] 2.1 `services/git_access.py` (design 2) — проверка: `test_git_access.py`
- [ ] 2.2 `security/redaction.py`: шаблоны GitHub, GitLab, `Basic` (design 7) — проверка: `test_redaction.py`

## 3. Песочница

- [ ] 3.1 `sandboxes.bootstrap(repo_tokens)`, `GIT_AUTH_HEADER_<i>`, без `--gitlab-url` (design 3) — проверка:
  `test_bootstrap_passes_header_per_pair_in_env`, `test_bootstrap_rejects_tokens_for_unknown_workspace`
- [ ] 3.2 `sandboxes.activate(repo, repo_token)`, `set-url origin` перед fetch (design 3) — проверка:
  `test_activate_resets_origin_before_fetch`, `test_activate_github_fetch_uses_x_access_token_header`
- [ ] 3.3 `deploy/sandbox/bootstrap.sh` (design 8) — проверка: скриптовые тесты `test_sandbox_bootstrap.py`, shellcheck

## 4. Worker и CLI

- [ ] 4.1 `settings.py` без `gitlab_url`/`gitlab_token` (design 6) — проверка: `./tools/harness check`
- [ ] 4.2 `worker/dispatcher.py`: ключ workspace задачи, причина `repo_access_ref`, предупреждение (design 4) —
  проверка: `test_task_without_access_ref_goes_to_error_with_reason`, `test_dispatcher_fetch_is_bound_to_repo_prefix`
- [ ] 4.3 `cli.py sandbox bootstrap`: ключи по workspace, анонимно с предупреждением (design 5) — проверка:
  `test_sandbox_bootstrap_without_any_key_clones_anonymously_with_warning`
- [ ] 4.4 Остальные тесты и фабрики `WorkspaceConfig` (design «Test strategy») — проверка: `./tools/harness check` зелёный

## 5. Live-проверка (владелец)

- [ ] 5.1 Fine-grained токен на `w1do/chistotyumen` (Contents RW, Pull requests RW) в vault, `access_ref` в
  `harness.yaml` — проверка: подтверждение владельца
- [ ] 5.2 `test_github_private_clone_live` и `test_sandbox_profile_live` с `LIVE_REPO_PROVIDER=github` — проверка: вывод теста

## 6. Документация

- [ ] 6.1 ARCHITECTURE.md: §1 (адаптер `git`, «GitHub/GitLab API»), §5 (MR/PR), §7 (абзац про авторизацию git:
  заголовок на префикс репозитория, `oauth2`/`x-access-token`, `GIT_AUTH_HEADER_<i>`; ключи из `repo.access_ref`),
  §9 (`workspaces[].repo`, удалить строку `GITLAB_URL`, `GITLAB_TOKEN`; убрать заметку «план git-providers») — проверка: ревью диффа
- [ ] 6.2 docs/deployment.md: раздел «Переход на D-60» (порядок: правка `harness.yaml` → выкат; примеры GitHub и
  GitLab; удалить `GITLAB_TOKEN` из ENV Dokploy), абзацы про `gitlab.access_ref` → `repo.access_ref`;
  docs/operating-without-ui.md (предупреждение worker, bootstrap); `apps/server/README.md` — проверка: ревью диффа
- [ ] 6.3 docs/glossary.md: «MR» — merge request GitLab или pull request GitHub; «провайдер репозитория» — проверка: ревью
- [ ] 6.4 docs/decisions.md: ответы на вопросы в D-60, если отличаются от умолчаний; PLAN.md: статус `git-providers` — проверка: ревью
- [ ] 6.5 `docker-compose.yml` (если в нём есть `GITLAB_URL`/`GITLAB_TOKEN`) и `.env.example` — только по явной команде
  владельца, иначе пункт пропускается и отмечается в отчёте

## 7. Память проекта

- [ ] 7.1 `memory_update` по изменённым путям, `memory_annotate` для каждого нового и изменённого файла, `memory_status`
  без устаревших файлов
