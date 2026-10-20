# Tasks

Порядок и детали — design.md («Detailed specification», «Ordered implementation steps»). Вопросы владельцу —
proposal.md; без ответа действует вариант по умолчанию.

## 0. Подготовка

- [x] 0.1 Ответы владельца на вопросы 1–6 proposal.md записаны в D-60 (или design.md поправлен до реализации) — проверка: ревью

## 1. Конфиг

- [x] 1.1 `RepoConfig`, `WorkspaceConfig.repo`, удаление `GitLabConfig`/`HarnessConfig.gitlab`, сообщения о старой
  форме (design 1) — проверка: тесты `test_repo_*`, `test_legacy_*` в `test_config.py`
- [x] 1.2 `config/harness.example.yaml`: `repo` у `demo`, пример GitHub, без `gitlab:` — проверка: пример загружается тестом

## 2. Адрес и авторизация git

- [x] 2.1 `services/git_access.py` (design 2) — проверка: `test_git_access.py`
- [x] 2.2 `security/redaction.py`: шаблоны GitHub, GitLab, `Basic` (design 7) — проверка: `test_redaction.py`

## 3. Песочница

- [x] 3.1 `sandboxes.bootstrap(repo_tokens)`, `GIT_AUTH_HEADER_<i>`, без `--gitlab-url` (design 3) — проверка:
  `test_bootstrap_passes_header_per_pair_in_env`, `test_bootstrap_rejects_tokens_for_unknown_workspace`
- [x] 3.2 `sandboxes.activate(repo, repo_token)`, `set-url origin` перед fetch (design 3) — проверка:
  `test_activate_resets_origin_before_fetch`, `test_activate_github_fetch_uses_x_access_token_header`
- [x] 3.3 `deploy/sandbox/bootstrap.sh` (design 8) — проверка: скриптовые тесты `test_sandbox_bootstrap.py`, shellcheck

## 4. Worker и CLI

- [x] 4.1 `settings.py` без `gitlab_url`/`gitlab_token` (design 6) — проверка: `./tools/harness check`
- [x] 4.2 `worker/dispatcher.py`: ключ workspace задачи, причина `repo_access_ref`, предупреждение (design 4) —
  проверка: `test_task_without_access_ref_goes_to_error_with_reason`, `test_dispatcher_fetch_is_bound_to_repo_prefix`
- [x] 4.3 `cli.py sandbox bootstrap`: ключи по workspace, анонимно с предупреждением (design 5) — проверка:
  `test_sandbox_bootstrap_without_any_key_clones_anonymously_with_warning`
- [x] 4.4 Остальные тесты и фабрики `WorkspaceConfig` (design «Test strategy») — проверка: `./tools/harness check` зелёный

## 5. Live-проверка (владелец)

- [x] 5.1 Главный ключ GitHub `vault:Repository/Github/админский` в `repo.access_ref` у `w1do/chistotyumen` в `harness.yaml` (fine-grained — позже) — проверка: главный ключ GitHub в repo.access_ref боевого harness.yaml (2026-10-20, подтверждено владельцем)
- [x] 5.2 `test_github_private_clone_live` и `test_sandbox_profile_live` с `LIVE_REPO_PROVIDER=github` — проверка: вместо live-тестов pytest — прод-прогон `harness-server sandbox bootstrap` владельцем 2026-10-20, exit_code=0 (fetch w1do/chistotyumen с ключом GitHub); live-тесты pytest не запускались

## 6. Документация

- [x] 6.1 ARCHITECTURE.md: §1 (адаптер `git`, «GitHub/GitLab API»), §5 (MR/PR), §7 (абзац про авторизацию git:
  заголовок на префикс репозитория, `oauth2`/`x-access-token`, `GIT_AUTH_HEADER_<i>`; ключи из `repo.access_ref`),
  §9 (`workspaces[].repo`, удалить строку `GITLAB_URL`, `GITLAB_TOKEN`; убрать заметку «план git-providers») — проверка: ревью диффа
- [x] 6.2 docs/deployment.md: раздел «Переход на D-60» (порядок: правка `harness.yaml` → выкат; примеры GitHub и
  GitLab; удалить `GITLAB_TOKEN` из ENV Dokploy), абзацы про `gitlab.access_ref` → `repo.access_ref`;
  docs/operating-without-ui.md (предупреждение worker, bootstrap); `apps/server/README.md` — проверка: ревью диффа
- [x] 6.3 docs/glossary.md: «MR» — merge request GitLab или pull request GitHub; «провайдер репозитория» — проверка: ревью
- [x] 6.4 docs/decisions.md: ответы на вопросы в D-60, если отличаются от умолчаний; PLAN.md: статус `git-providers` — проверка: ревью
- [ ] 6.5 `docker-compose.yml` — сделано (строки ENV `GITLAB_URL`, `GITLAB_TOKEN` удалены по решению владельца); `.env.example` — пропущено по решению владельца (агентам `.env*` не читать и не править)

## 7. Память проекта

- [x] 7.1 `memory_update` по изменённым путям, `memory_annotate` для каждого нового и изменённого файла, `memory_status`
  без устаревших файлов — проверка: memory_sync 2026-10-20 (added 11, changed 4, renamed 9, removed 11, errors 0); аннотации PLAN.md и трёх main spec сохранены; memory_status stale_files 0, qdrant 3672 = typesense 3672

## 8. Исправления security-ревью (эскалация 1, D-62; design «Эскалация 1»)

- [x] 8.1 `config.py`: метки хоста и сегменты пути `base_url` (design Э.5) — проверка: `test_repo_base_url_rejects_dot_and_dash_segments`, `test_repo_base_url_accepts_ip_port_and_path`
- [x] 8.2 `services/git_access.py` целиком (design Э.2): перекрытия конфига, `clone_command`, `set_origin_command`, `fetch_command`, три секрета — проверка: `test_git_auth_env_overrides_clone_config`, `test_auth_env_disables_planted_hooks`, `test_auth_env_overrides_planted_http_config`, `test_auth_env_resets_planted_credential_helper`
- [x] 8.3 `security/redaction.py` (design Э.5) — проверка: `test_redacts_basic_auth_header_any_case`, `test_basic_before_long_word_is_kept`, `test_redacts_git_tokens_after_underscore`, `test_redacts_password_in_url`
- [x] 8.4 `services/sandboxes.py`: bootstrap в три шага, `_sync_clone`, fetch по адресу из конфига в `activate` (design Э.3) — проверка: `test_bootstrap_runs_setup_phase_without_secrets`, `test_bootstrap_clones_each_workspace_with_its_own_key`, `test_activate_fetches_config_url_not_origin`
- [x] 8.5 `deploy/sandbox/bootstrap.sh`: `--phase setup|memory`, без клонов и `GIT_AUTH_HEADER_<i>` (design Э.6) — проверка: скриптовые тесты Э.8, `shellcheck`
- [x] 8.6 `worker/dispatcher.py`, `cli.py`: секреты redaction, `SandboxStepError` в CLI, тексты docstring (design Э.4) — проверка: `test_dispatcher_fetch_is_bound_to_repo_prefix`, `test_sandbox_bootstrap_reports_step_error_reason`
- [x] 8.7 Документация (design Э.7): ARCHITECTURE.md §7, `apps/server/README.md` (`repo.access_ref`), упоминания `GIT_AUTH_HEADER` — проверка: ревью диффа; `./tools/harness check` зелёный
- [x] 8.8 Владелец ответил на вопрос 7 proposal.md (остаточный риск R-1) — проверка: запись в D-62 (ответ владельца записан в D-62)
