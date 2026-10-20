# Tasks

Детали — design.md («Detailed specification»). Порядок обязателен.

## 1. Код

- [x] 1.1 `apps/server/src/harness_server/cli.py`: константы `_APP_ROOT`, `DEFAULT_BOOTSTRAP_SCRIPT`, значение по
  умолчанию `sandbox_bootstrap(script: Path = DEFAULT_BOOTSTRAP_SCRIPT)` (design 1) — проверка:
  `test_default_bootstrap_script_is_repo_file`
- [x] 1.2 `Dockerfile`: `COPY deploy/sandbox ./deploy/sandbox` в builder после `COPY alembic.ini ./` (design 2) —
  проверка: `test_builder_copies_bootstrap_script`

## 2. Тесты

- [x] 2.1 `apps/server/tests/test_cli.py`: `test_default_bootstrap_script_is_repo_file`,
  `test_sandbox_bootstrap_default_script_does_not_depend_on_cwd` (design 3)
- [x] 2.2 `apps/server/tests/test_dockerfile.py`: `test_builder_copies_bootstrap_script`,
  `test_dockerignore_keeps_bootstrap_script`, `test_dockerfile_installs_workspace_editable` (design 3)

## 3. Документация

- [x] 3.1 `docs/deployment.md` шаг 3 «Первый запуск», `apps/server/README.md` строка `sandbox bootstrap` (design 4)
- [x] 3.2 `docs/decisions.md` D-63; `PLAN.md` строка 6f, статус `review` после зелёных проверок (design 4)

## 4. Проверки

- [x] 4.1 `./tools/harness check` (известное исключение: `ruff format --check` на двух старых openspec `design.md`,
  PLAN.md) и `openspec validate bootstrap-in-image --strict`
- [ ] 4.2 Если доступен Docker: `docker build -t agents-flow:bootstrap-check .` и
  `docker run --rm -w / --entrypoint sh agents-flow:bootstrap-check -c 'test -r /app/deploy/sandbox/bootstrap.sh && python -c "from harness_server.cli import DEFAULT_BOOTSTRAP_SCRIPT as p; assert p.is_file(), p; print(p)"'`
  печатает `/app/deploy/sandbox/bootstrap.sh`. Без Docker — отметить «не выполнено» в отчёте, не «пройдено».
- [ ] 4.3 Живая проверка владельца: в Dokploy-терминале `worker` `harness-server sandbox bootstrap` → «bootstrap выполнен»
