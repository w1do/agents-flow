# Design: bootstrap-in-image

## Problem statement

В образе нет `deploy/sandbox/bootstrap.sh`, а путь по умолчанию в `sandbox bootstrap` зависит от cwd. В терминале
Dokploy (cwd `/`) команда завершается кодом 1: «не читается скрипт deploy/sandbox/bootstrap.sh».

## Goals / Non-Goals

Goals: `harness-server sandbox bootstrap` без флагов работает в контейнере `server` и `worker` из любого cwd;
локальный запуск из корня репо и `--script` не меняются; регресс ловится тестами без Docker.

Non-Goals: новая ENV, изменение `bootstrap.sh`, `sandboxes.bootstrap`, compose, `.env.example`.

## Context: текущее состояние

- `Dockerfile`: builder (`WORKDIR /app`, `COPY apps|shared|db|alembic.ini`, `uv sync --frozen --package
  harness-server` — workspace ставится uv в editable-режиме по умолчанию) → runtime
  `COPY --from=builder --chown=app:app /app /app`, `USER app`.
- `.dockerignore` исключает `openspec`, `docs`, `tools/spikes`, но не `deploy`.
- `cli.py:237` `sandbox_bootstrap(script: Path = Path("deploy/sandbox/bootstrap.sh"))`, чтение `script.read_text`.
- `tools/harness` делает `cd "$ROOT"`; тесты CLI всегда передают `--script <tmp>`.
- `test_compose.py` находит корень как `Path(__file__).resolve().parents[3]`.

## Decisions

1. **Путь от расположения пакета, без ENV.** `cli.py` лежит в `<root>/apps/server/src/harness_server/cli.py` и
   локально, и в образе: uv ставит workspace-пакет editable, `.pth` в `/app/.venv` указывает на
   `/app/apps/server/src`. Поэтому `Path(__file__).resolve().parents[4]` — корень (`/app` или корень репо).
   Отвергнуто: ENV `HARNESS_BOOTSTRAP_SCRIPT` — лишняя настройка (Settings, compose, ARCHITECTURE.md §9,
   `.env.example`, который агентам не трогать) ради одного пути; `importlib.resources` — перенос скрипта в пакет
   ломает `shellcheck deploy/sandbox/*.sh` и путь в документации. Условие решения (editable-установка) закрепляет
   тест `test_dockerfile_installs_workspace_editable`: в `Dockerfile` нет `--no-editable`.
2. **Скрипт копируется в builder** строкой `COPY deploy/sandbox ./deploy/sandbox` после `COPY alembic.ini ./`.
   Runtime уже копирует `/app` целиком с `--chown=app:app`: файл читается пользователем `app`. Исполняемый бит не
   нужен — CLI читает текст и отправляет его в песочницу.
3. Решение записывается как D-63 в `docs/decisions.md`.

## Файлы и символы

- `Dockerfile` — одна строка `COPY`.
- `apps/server/src/harness_server/cli.py` — новые модульные константы `_APP_ROOT`, `DEFAULT_BOOTSTRAP_SCRIPT`;
  `sandbox_bootstrap(script: Path = DEFAULT_BOOTSTRAP_SCRIPT)`.
- `apps/server/tests/test_cli.py` — два теста.
- `apps/server/tests/test_dockerfile.py` (новый) — три теста.
- Документы: `docs/deployment.md`, `apps/server/README.md`, `PLAN.md`, `docs/decisions.md`.

## Detailed specification

### 1. `cli.py`

После блока импортов, перед `app = typer.Typer(...)`, добавить (текст комментария — как ниже):

    # Корень приложения: uv ставит workspace editable, поэтому cli.py лежит в
    # <root>/apps/server/src/harness_server/ и в репозитории, и в образе (/app). Путь не зависит от cwd:
    # терминал Dokploy открывается в / (bootstrap-in-image, D-63).
    _APP_ROOT = Path(__file__).resolve().parents[4]
    DEFAULT_BOOTSTRAP_SCRIPT = _APP_ROOT / "deploy" / "sandbox" / "bootstrap.sh"

Сигнатура: `def sandbox_bootstrap(script: Path = DEFAULT_BOOTSTRAP_SCRIPT) -> None:`. Остальное тело без изменений;
сообщение об ошибке чтения остаётся `f"Ошибка: не читается скрипт {script}"` (теперь печатает абсолютный путь).

### 2. `Dockerfile`

После строки `COPY alembic.ini ./` в builder добавить:

    # Скрипт bootstrap песочницы: CLI читает его из образа (bootstrap-in-image, D-63).
    COPY deploy/sandbox ./deploy/sandbox

### 3. Тесты

`apps/server/tests/test_cli.py`:

- `test_default_bootstrap_script_is_repo_file()` — `from harness_server.cli import DEFAULT_BOOTSTRAP_SCRIPT,
  sandbox_bootstrap`; ожидаемый путь `Path(__file__).resolve().parents[3] / "deploy" / "sandbox" / "bootstrap.sh"`;
  assert `DEFAULT_BOOTSTRAP_SCRIPT == expected`, `DEFAULT_BOOTSTRAP_SCRIPT.is_absolute()`,
  `DEFAULT_BOOTSTRAP_SCRIPT.is_file()`, `inspect.signature(sandbox_bootstrap).parameters["script"].default ==
  DEFAULT_BOOTSTRAP_SCRIPT`.
- `test_sandbox_bootstrap_default_script_does_not_depend_on_cwd(valid_env, monkeypatch, migrated_database_url,
  tmp_path)` — подготовка как в `test_sandbox_bootstrap_takes_keys_from_vault_into_env` (DATABASE_URL,
  `delenv GITLAB_TOKEN`, `HARNESS_CONFIG` = `_write_vault_config(tmp_path, valid_env, memory=False)`, FakeSandbox с
  `fake.respond('printf %s "$HOME"', stdout="/home/sbx")`, FakeVault с `VaultRef("demo", "gitlab", "main"):
  VAULT_GITLAB`, monkeypatch `wiring.build_sandbox_provider` и `wiring.build_vault`). Перед вызовом
  `cwd = tmp_path / "elsewhere"; cwd.mkdir(); monkeypatch.chdir(cwd)`. Вызов `runner.invoke(app, ["sandbox",
  "bootstrap"])` без `--script`. Assert: `result.exit_code == 0, result.output`; `"не читается скрипт" not in
  result.output`; `"bootstrap выполнен" in result.output`. Путь `HARNESS_CONFIG` из `_write_vault_config` абсолютный.
  Если `valid_env` содержит относительные пути и тест падает из-за cwd — привести их к абсолютным через
  `str(Path(...).resolve())` до `chdir`; другие правки фикстур запрещены.

`apps/server/tests/test_dockerfile.py` (новый; docstring модуля — «Образ харнесса содержит скрипт bootstrap
песочницы (bootstrap-in-image, D-63)»). Корень `ROOT = Path(__file__).resolve().parents[3]`, файлы читаются как текст:

- `test_builder_copies_bootstrap_script()` — в тексте `Dockerfile` до второй строки, начинающейся с `FROM `
  (runtime-стадия), есть строка, равная после `strip()` `COPY deploy/sandbox ./deploy/sandbox`; в runtime-части
  есть строка `COPY --from=builder --chown=app:app /app /app`.
- `test_dockerignore_keeps_bootstrap_script()` — ни одна строка `.dockerignore` (после `strip()`, без пустых и
  `#`-комментариев) не равна `deploy`, `deploy/`, `deploy/sandbox`, `deploy/sandbox/`, `deploy/*`, `deploy/**`,
  `**/deploy`, `*.sh`, `**/*.sh`.
- `test_dockerfile_installs_workspace_editable()` — `"--no-editable" not in` текст `Dockerfile` (условие решения 1).

### 4. Документация

- `docs/deployment.md`, «Первый запуск», шаг 3: после фразы про загрузку `deploy/sandbox/bootstrap.sh` добавить
  предложение: «Команда запускается в терминале Dokploy контейнера `server` или `worker` (из любого каталога):
  `harness-server sandbox bootstrap`; скрипт лежит в образе — `/app/deploy/sandbox/bootstrap.sh`, другой путь —
  `--script <путь>` (D-63).»
- `apps/server/README.md`, строка таблицы `sandbox bootstrap`: `[--script deploy/sandbox/bootstrap.sh]` →
  `[--script PATH]`; в описание добавить «по умолчанию `deploy/sandbox/bootstrap.sh` от корня приложения
  (`/app` в образе), не от cwd»; устаревшее «`GITLAB_TOKEN`» заменить на «ключи из vault по `repo.access_ref`» (D-60).
- `PLAN.md`: строка таблицы сразу после строки 6e:
  `| 6f | [`bootstrap-in-image`](openspec/changes/bootstrap-in-image/) | Скрипт bootstrap в образе, путь по умолчанию от корня приложения, не от cwd (D-63): bootstrap из терминала Dokploy | sandbox-profile | sandbox-profile | todo |`.
  Implementer по завершении ставит `review`.
- `docs/decisions.md`: строка D-63 в конце таблицы:
  `| D-63 | 2026-10-20 | Скрипт bootstrap песочницы входит в образ (`COPY deploy/sandbox`); путь по умолчанию в `sandbox bootstrap` — от корня приложения (`Path(__file__).parents[4]`, workspace ставится editable), без ENV; `--script` для другого пути | В терминале Dokploy cwd `/`, а `deploy/` в образ не копировался: bootstrap на проде падал. ENV ради одного пути — лишняя настройка в Settings, compose и `.env.example` | bootstrap-in-image, 2026-10-20 |`

## Rollback

Revert коммита изменения. Данные, БД и песочница не затрагиваются.
