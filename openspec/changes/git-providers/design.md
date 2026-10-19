# Design: git-providers

> Решение D-60. Вопросы владельцу — в начале proposal.md; design написан на вариантах по умолчанию.

## Problem statement

Харнесс умеет работать с одним Git-хостингом на всю установку и только по схеме авторизации GitLab. Workspace на
GitHub (`w1do/chistotyumen`) клонируется только анонимно, ключа для него нет, а `mvp-09` планирует только MR в
GitLab. Нужно, чтобы провайдер, адрес, проект и ключ задавались у каждого workspace, git в песочнице авторизовался
ключом своего workspace, а доставка (`mvp-09`) работала с MR GitLab и PR GitHub через один протокол.

## Goals / Non-Goals

**Goals:**

- `workspaces[].repo` с `provider`, `base_url`, `project`, `access_ref`; разумные адреса по умолчанию.
- Клоны, fetch и (в `mvp-09`) push с заголовком, привязанным к адресу репозитория своего workspace.
- В одной песочнице — workspace разных провайдеров с разными ключами.
- Без ключа: bootstrap клонирует публичный репозиторий анонимно; задача не запускается, причина понятна.
- Redaction покрывает токены и заголовки обоих провайдеров.
- Контракт `GitProvider` для `mvp-09` с реализациями GitLab и GitHub.

**Non-Goals:** GitHub Enterprise Server, GitHub App, другие провайдеры, задачи только на чтение, сам push/MR
(это `mvp-09`), смена хостинга харнесса.

## Context: текущее состояние (ветка от `main` edb7be6)

- `config.py`: `HarnessConfig.gitlab: GitLabConfig(base_url, access_ref)`; `WorkspaceConfig.gitlab_project`,
  `default_branch`. `GitLabConfig.base_url` допускает `http://` и `https://`, отклоняет userinfo (D-26).
- `services/sandboxes.py`: `clone_url(config, ws)` = `gitlab.base_url + "/" + gitlab_project + ".git"`;
  `git_auth_header(token)` = `Authorization: Basic base64("oauth2:<token>")`; `git_auth_env(base_url, token)` —
  `GIT_CONFIG_COUNT=2`, `http.<base_url>/.extraHeader`, `http.followRedirects=false`, `GIT_TERMINAL_PROMPT=0`;
  `git_auth_secret_values(token)` — заголовок и его base64; `bootstrap(..., gitlab_token)` передаёт
  `--gitlab-url <base_url>` и env `GITLAB_TOKEN`; `activate(..., gitlab_token, gitlab_base_url)` — fetch с заголовком.
- `deploy/sandbox/bootstrap.sh`: `GITLAB_TOKEN` снимается из env в начале, `--gitlab-url` обязателен при клонах,
  заголовок собирается в скрипте, `run_git_auth` ставит `http.${gitlab_url}.extraHeader` на clone/fetch. Пары
  `<id>=<url>` по `PAIR_RE` (`https?://`).
- `worker/dispatcher.py`: `_run_reserved` берёт ключ `secret_refs.resolve(vault, config.gitlab.access_ref,
  fallback=ctx.gitlab_token)`, без ключа — `SandboxStepError("gitlab_token")`; токен и заголовок — в
  `runner.secrets`. `build_dispatch_context` требует ENV `GITLAB_TOKEN`, если нет `gitlab.access_ref`.
- `cli.py` `sandbox bootstrap`: тот же resolve, без ключа — выход 1 «нужен gitlab.access_ref или GITLAB_TOKEN».
- `settings.py`: `gitlab_url`, `gitlab_token` (`SecretStr`). `wiring.secret_values` собирает все `SecretStr`
  настроек для redaction.
- `security/redaction.py`: шаблоны Telegram, `glpat-`, `sk-ant-`, `aft_`, `Bearer`.
- `mvp-09-delivery-mr` (todo): `adapters/gitlab`, `GitProvider` (`find_open_mr`, `create_mr`), httpx REST v4.
  D-56: агент коммитит, push и MR делает харнесс после гейтов. D-58 (в `main`): базовые гейты, в том числе
  `branch_guard` (push только `task/<id>`). `task-rework` (D-57, в `main`) добавляет `get_mr_state`, `add_mr_note`.
  Обе ссылки на `adapters/gitlab` переведены этим изменением на `adapters/git`.

## Decisions

1. **Блок `repo` у workspace, а не глобальная секция.** Провайдер и ключ — свойства репозитория. Отвергнуто:
   глобальный список провайдеров со ссылкой из workspace — лишний уровень при одном-двух проектах.
2. **Чистый разрыв со старым конфигом (вопрос 3).** `gitlab:` и `gitlab_project` отклоняются с сообщением, куда
   перенести поля. Почему: боевой файл один и правится владельцем; совместимая форма удвоила бы проверки и тесты,
   а глобальный `gitlab.access_ref` рядом с `repo.access_ref` дал бы неоднозначность, какой ключ куда уходит.
   Без молчаливого маппинга ключ одного хоста не уйдёт на другой. Цена — правка `harness.yaml` до выката
   (docs/deployment.md, раздел «Переход на D-60»).
3. **Только https.** Заголовок с ключом по http уходит открытым текстом. Отвергнуто: оставить `http://` для
   локальных тестов — тестам хватает фейков и respx.
4. **Адрес по умолчанию по провайдеру:** `github` → `https://github.com`, `gitlab` → `https://gitlab.com`.
   Самостоятельный GitLab — любой https-адрес, в том числе с путём (`https://host/gitlab`). GitHub — только
   `https://github.com` (вопрос 2).
5. **Заголовок привязан к адресу репозитория, а не хоста** (уточняет D-52): `http.<base_url>/<project>.git/.extraHeader`.
   git сопоставляет путь `http.<url>.*` по префиксу на границе `/` (git-config, `http.<url>.*`), а запросы
   smart HTTP идут на `<clone_url>/info/refs` и `<clone_url>/git-upload-pack|git-receive-pack`, поэтому
   заголовок получает только этот репозиторий. Два workspace на `github.com` с разными fine-grained токенами не
   пересекаются, а если агент сменит `origin` клона на чужой репозиторий того же хоста, ключ туда не уйдёт.
   Дополнительно активация возвращает `origin` на адрес из конфига перед fetch.
6. **Пользователь Basic по провайдеру:** GitLab `oauth2` (D-52, проверено live 6c), GitHub `x-access-token`.
   Документация GitHub: токен используется вместо пароля для Git по HTTPS, имя пользователя для аутентификации не
   используется (Managing your personal access tokens, «Using a personal access token on the command line»);
   для токена установки GitHub App документирован вид `https://x-access-token:TOKEN@github.com/owner/repo.git`
   (Authenticating as a GitHub App installation). Заголовок `Authorization: Basic base64("x-access-token:<token>")`
   через `http.https://github.com/.extraheader` — тот же способ, что у `actions/checkout`. Одно имя подходит для
   classic PAT, fine-grained PAT и (позже) токена App. Подтверждается live-тестом задачи 6.1 на
   `w1do/chistotyumen`.
7. **Заголовок для bootstrap собирает сервер**, скрипт получает готовое значение в env `GIT_AUTH_HEADER_<i>`, где
   `i` — номер пары `<id>=<url>` в argv (с 0). Почему: знание о провайдере (имя пользователя Basic) остаётся в
   Python в одном месте (`services/git_access.py`), скрипт не различает провайдеров. Имя переменной по номеру, а не
   по id workspace: id допускает `-`, недопустимый в имени переменной окружения. Значение — секрет того же уровня,
   что токен: только env одной команды, скрипт снимает его из env до любых установок. Отвергнуто: один bootstrap на
   workspace — повторяет установку пакетов и проверки на каждый репозиторий; токены в argv или файле — запрещено D-52.
8. **Ключ только из vault по `repo.access_ref` (вопрос 4).** ENV `GITLAB_TOKEN`/`GITLAB_URL` удаляются из
   `Settings`. Лишняя переменная в ENV Dokploy игнорируется (`extra="ignore"`), владелец удаляет её сам.
9. **Ключ записи обязателен для любой задачи.** Все пайплайны (`plan` в `mvp-08`, `implement` в `mvp-09`) пушат
   ветку `task/<id>`. Без `access_ref` задача сразу `error` с причиной `repo_access_ref: …`, до активации песочницы.
   Bootstrap без ключа клонирует анонимно (публичный репозиторий). Флаг «пайплайн без push» добавит `check-tasks`.
   Отвергнуто: пробовать fetch анонимно и падать на push — песочница и время агента тратятся впустую.
10. **`GitProvider` — в `mvp-09`, здесь только контракт.** До `mvp-09` у адаптера нет потребителя; код без вызовов
    не пишется. Контракт ниже фиксирует имена, чтобы `mvp-09`, `task-rework` и D-58 сошлись. Внутренний термин
    харнесса — «MR» (глоссарий, D-56): для GitHub это pull request; слово для владельца — по провайдеру
    (`change_request_label`).
11. **Redaction по шаблонам обоих провайдеров** плюс точные значения токена, заголовка и его base64 для
    каждого разрешённого ключа. Шаблон `Basic <base64>` закрывает заголовок, даже если точного значения нет.

## Файлы и символы

### Новые файлы

| Файл (от `apps/server/`) | Символы |
|---|---|
| `src/harness_server/services/git_access.py` | `GIT_BASIC_USERS`, `CHANGE_REQUEST_LABELS`, `clone_url`, `auth_url_prefix`, `git_auth_header`, `git_auth_env`, `anonymous_git_env`, `git_auth_secret_values`, `change_request_label` |
| `tests/test_git_access.py` | тесты модуля |

### Изменяемые файлы

| Файл | Что меняется |
|---|---|
| `apps/server/src/harness_server/config.py` | `GitProviderName`, `DEFAULT_REPO_BASE_URLS`, `GITHUB_BASE_URL`, `RepoConfig`; `WorkspaceConfig.repo` вместо `gitlab_project`; удаление `GitLabConfig` и `HarnessConfig.gitlab`; сообщения о старой форме; docstring модуля |
| `apps/server/src/harness_server/services/sandboxes.py` | удаление `clone_url`, `git_auth_header`, `git_auth_env`, `git_auth_secret_values`; `bootstrap(repo_tokens=…)`; `activate(repo=…, repo_token=…)`; `set-url` перед fetch |
| `apps/server/src/harness_server/worker/dispatcher.py` | ключ по workspace задачи, причина `repo_access_ref`, удаление `DispatchContext.gitlab_token` и проверки `GITLAB_TOKEN`; предупреждение о workspace без ключа |
| `apps/server/src/harness_server/cli.py` | `sandbox bootstrap`: ключи по workspace, без ключа — анонимно с предупреждением |
| `apps/server/src/harness_server/settings.py` | удаление `gitlab_url`, `gitlab_token` |
| `apps/server/src/harness_server/security/redaction.py` | новые шаблоны |
| `deploy/sandbox/bootstrap.sh` | `GIT_AUTH_HEADER_<i>`, удаление `--gitlab-url`, https-пары, заголовок на префикс пары |
| `apps/server/tests/{conftest.py, test_config.py, test_sandbox_service.py, test_sandbox_bootstrap.py, test_dispatcher.py, test_cli.py, test_redaction.py, test_routing_service.py, test_telegram_render.py, test_polza_live.py, test_agent_runtime_live.py, test_sandbox_profile_live.py}` | новые поля конфига и сигнатуры, тесты ниже |
| `config/harness.example.yaml`, `ARCHITECTURE.md`, `docs/deployment.md`, `docs/operating-without-ui.md`, `apps/server/README.md`, `docs/glossary.md`, `PLAN.md` | документация |

## Proposed architecture

```
harness.yaml workspaces[i].repo {provider, base_url, project, access_ref}
        │ load_config (RepoConfig: https, проект по провайдеру, ref vault)
        ▼
services/git_access ── clone_url / auth_url_prefix / git_auth_header(provider, token) / git_auth_env(repo, token)
        │                                   ▲
        ├── cli sandbox bootstrap ──► sandboxes.bootstrap(repo_tokens) ──► bootstrap.sh
        │        env GIT_AUTH_HEADER_<i> (по паре), argv: <id>=<clone_url> без секретов
        └── worker dispatcher ──► resolve(repo.access_ref) ──► sandboxes.activate(repo, repo_token)
                 нет ключа → error repo_access_ref           set-url origin → fetch с заголовком
                                                              (mvp-09: push тем же env; adapters/git для MR/PR)
```

## Detailed specification

### 1. `config.py`

Константы и типы (рядом с существующими шаблонами):

```python
GitProviderName = Literal["github", "gitlab"]
GITHUB_BASE_URL: Final = "https://github.com"
DEFAULT_REPO_BASE_URLS: Final[Mapping[str, str]] = {"github": GITHUB_BASE_URL, "gitlab": "https://gitlab.com"}
# Только https: заголовок с ключом не уходит открытым текстом (D-60). Тот же вид, что у прежнего --gitlab-url.
_REPO_BASE_URL_PATTERN = r"^https://[A-Za-z0-9.-]+(:[0-9]{1,5})?(/[A-Za-z0-9._~-]+)*/?$"
# group/subgroup/.../name: сегменты как у GitHub, минимум два.
_GITLAB_PROJECT_PATTERN = rf"^{_GITHUB_REPO_SEGMENT}(/{_GITHUB_REPO_SEGMENT})+$"
```

`Final`, `Literal`, `Mapping` импортируются (`typing`, `collections.abc`).

```python
class RepoConfig(BaseModel):
    """Репозиторий workspace (D-60): провайдер, адрес, проект и ссылка vault на ключ."""

    model_config = ConfigDict(extra="forbid")

    provider: GitProviderName
    base_url: str
    project: str = Field(min_length=1, max_length=255)
    # Ключ записи из vault (D-45). Без него — только анонимный клон публичного репозитория.
    access_ref: str | None = None
```

Валидаторы `RepoConfig` по порядку:

- `@model_validator(mode="before")` `_default_base_url(cls, data: Any) -> Any`: если `data` — dict, `data.get("base_url")
  is None` и `data.get("provider")` есть в `DEFAULT_REPO_BASE_URLS` → вернуть `{**data, "base_url": DEFAULT_REPO_BASE_URLS[provider]}`;
  иначе `data` без изменений.
- `@field_validator("base_url")` `_check_base_url`: если `"@" in value` → `ValueError("адрес не должен содержать
  учётные данные перед символом @; ключ задаётся ссылкой repo.access_ref")`; если не `re.fullmatch(_REPO_BASE_URL_PATTERN,
  value)` → `ValueError("адрес репозитория — https://хост[:порт][/путь] без учётных данных, query и fragment")`;
  вернуть `value.rstrip("/")`.
- `@field_validator("access_ref")` `_check_access_ref` → `_check_vault_ref(value, "access_ref")`.
- `@model_validator(mode="after")` `_check_provider_rules(self) -> Self`:
  - `self.project.lower().endswith(".git")` → `ValueError("project указывается без .git")`;
  - `provider == "github"`: `base_url != GITHUB_BASE_URL` → `ValueError("GitHub Enterprise пока не поддерживается:
    для github base_url — https://github.com")`; проект не `re.fullmatch(_GITHUB_REPO_PATTERN, …)` →
    `ValueError("project для github — owner/name")`;
  - `provider == "gitlab"`: проект не `re.fullmatch(_GITLAB_PROJECT_PATTERN, …)` → `ValueError("project для gitlab —
    group[/subgroup]/name")`.

`WorkspaceConfig`:

- поле `gitlab_project` удаляется, добавляется `repo: RepoConfig` (сразу после `voice_aliases`); `default_branch`,
  остальные поля без изменений; docstring: «Проект, с которым работает харнесс: репозиторий GitHub или GitLab и
  команда тестов.»
- `@model_validator(mode="before")` `_reject_legacy_fields`: dict с ключом `gitlab_project` → `ValueError("gitlab_project
  удалён (D-60): задайте repo: provider, project, access_ref")`.

`HarnessConfig`:

- поле `gitlab` удаляется, класс `GitLabConfig` удаляется целиком.
- `@model_validator(mode="before")` `_reject_legacy_gitlab_section`: dict с ключом `gitlab` → `ValueError("секция gitlab
  удалена (D-60): адрес, проект и ключ задаются в workspaces[].repo")`.

Docstring модуля: «…несекретные настройки workspace (в том числе репозиторий), sandbox.» и пример поля
`workspaces[0].repo.token` вместо `workspaces[0].gitlab_token`. Сообщения ошибок не содержат значений: их
выводит `_format_errors` без `input`.

### 2. `services/git_access.py` (новый)

```python
"""Адрес и авторизация git для репозитория workspace (D-60, уточняет D-52).

Ключ уходит git только заголовком Authorization в env одной команды, на префикс адреса этого репозитория.
Значения ключей и заголовков в логи и исключения не попадают.
"""

GIT_BASIC_USERS: Final[Mapping[GitProviderName, str]] = {"gitlab": "oauth2", "github": "x-access-token"}
# Слово для владельца: у GitLab merge request, у GitHub pull request. Внутри харнесса термин — «MR».
CHANGE_REQUEST_LABELS: Final[Mapping[GitProviderName, str]] = {"gitlab": "MR", "github": "PR"}


def clone_url(repo: RepoConfig) -> str:
    """Адрес клона: base_url + проект + .git. Учётных данных в адресе нет."""
    return f"{repo.base_url}/{repo.project}.git"


def auth_url_prefix(repo: RepoConfig) -> str:
    """Префикс http.<url>.* для заголовка: только этот репозиторий (граница «/»)."""
    return f"{clone_url(repo)}/"


def git_auth_header(provider: GitProviderName, token: str) -> str:
    """Authorization: Basic base64("<user>:<token>"), user по провайдеру. Значение — секрет."""
    basic = base64.b64encode(f"{GIT_BASIC_USERS[provider]}:{token}".encode()).decode("ascii")
    return f"Authorization: Basic {basic}"


def git_auth_env(repo: RepoConfig, token: str) -> dict[str, str]:
    """env git-команды с заголовком на префикс репозитория; редиректы выключены. git >= 2.31."""
    return {
        "GIT_CONFIG_COUNT": "2",
        "GIT_CONFIG_KEY_0": f"http.{auth_url_prefix(repo)}.extraHeader",
        "GIT_CONFIG_VALUE_0": git_auth_header(repo.provider, token),
        "GIT_CONFIG_KEY_1": "http.followRedirects",
        "GIT_CONFIG_VALUE_1": "false",
        "GIT_TERMINAL_PROMPT": "0",
    }


def anonymous_git_env() -> dict[str, str]:
    """env git-команды без ключа: публичный репозиторий, без запроса пароля."""
    return {"GIT_TERMINAL_PROMPT": "0"}


def git_auth_secret_values(provider: GitProviderName, token: str) -> tuple[str, str]:
    """Секреты заголовка для redaction: полная строка и bare base64."""
    header = git_auth_header(provider, token)
    return header, header.removeprefix("Authorization: Basic ")


def change_request_label(provider: GitProviderName) -> str:
    """«MR» или «PR» для текстов владельцу (mvp-09)."""
    return CHANGE_REQUEST_LABELS[provider]
```

Импорты: `base64`, `Final`, `Mapping`, `GitProviderName`, `RepoConfig` из `harness_server.config`.

### 3. `services/sandboxes.py`

- Удалить `clone_url`, `git_auth_header`, `git_auth_env`, `git_auth_secret_values` (переехали в `git_access`).
  `git_author_env` остаётся. Импорт `base64` удалить, если больше не используется. Docstring модуля: «GITLAB_TOKEN»
  → «ключей репозиториев».
- `bootstrap`: параметр `gitlab_token: SecretStr | None` заменяется на `repo_tokens: Mapping[str, SecretStr]`
  (ключ — id workspace). Порядок:
  1. Проверка `memory_ref`/`memory_repo` как сейчас.
  2. `unknown = set(repo_tokens) - {ws.id for ws in config.workspaces}`; непусто → `ValueError("repo_tokens: ключ
     для неизвестного workspace")` до вызова провайдера.
  3. `args` без `--gitlab-url`; пары `f"{ws.id}={git_access.clone_url(ws.repo)}"` в порядке `config.workspaces`.
  4. `envs = {"GIT_TERMINAL_PROMPT": "0", "HARNESS_SANDBOX_BOOTSTRAP": "1"}`; для `index, ws in
     enumerate(config.workspaces)`: если `ws.id in repo_tokens` → `envs[f"GIT_AUTH_HEADER_{index}"] =
     git_access.git_auth_header(ws.repo.provider, repo_tokens[ws.id].get_secret_value())`. `EMBEDDING_API_KEY` как
     сейчас. Переменной `GITLAB_TOKEN` больше нет.
  5. Остальное (запись, запуск, удаление скрипта, таймауты) без изменений. Docstring: ключи репозиториев — в env
     `GIT_AUTH_HEADER_<i>` по номеру пары.
- `activate`: параметры `gitlab_token`, `gitlab_base_url` заменяются на `repo: RepoConfig`, `repo_token: SecretStr | None`
  (оба keyword-only; `repo` обязателен, без значения по умолчанию; ставятся на место прежних). Проверка
  `ValueError("gitlab_token задан без gitlab_base_url…")` удаляется. После `extend_timeout` и `home_dir`:
  1. `git_envs = git_access.git_auth_env(repo, repo_token.get_secret_value())` при `repo_token is not None`, иначе
     `git_access.anonymous_git_env()`.
  2. Новый шаг до fetch: `_exec_ok(provider, provider_id, f"git -C {q(repo_dir)} remote set-url origin
     {q(git_access.clone_url(repo))}", reason="remote", timeout_s=SHORT_TIMEOUT_SEC)` без env авторизации.
     Локальная переменная каталога клона переименовывается из `repo` в `repo_dir` (имя `repo` теперь параметр).
  3. fetch как сейчас с `envs=git_envs`. Остальное без изменений.

### 4. `worker/dispatcher.py`

- `DispatchContext.gitlab_token` удаляется вместе с комментарием.
- Константа модуля: `REPO_ACCESS_REF_REASON: Final = "repo_access_ref: у workspace {workspace_id} нет repo.access_ref —
  задаче нужен ключ записи (push)"`.
- `_run_reserved`, внутри `try` вместо блока GitLab:

```python
workspace = sandboxes.workspace_for(ctx.config, task)
repo_token = await secret_refs.resolve(ctx.vault, workspace.repo.access_ref, fallback=None)
if repo_token is None:
    raise SandboxStepError(REPO_ACCESS_REF_REASON.format(workspace_id=workspace.id))
# Токен и заголовок Basic (base64 от него) — секреты для redaction (D-52, D-60).
header, bare_b64 = git_access.git_auth_secret_values(workspace.repo.provider, repo_token.get_secret_value())
runner.secrets = (*runner.secrets, repo_token.get_secret_value(), header, bare_b64)
```

  вызов `activate(..., repo=workspace.repo, repo_token=repo_token, default_branch=workspace.default_branch, ...)`.
  `UnknownWorkspace` по-прежнему уходит в общий `except Exception` («исключение: UnknownWorkspace»).
- `build_dispatch_context`: строка `("GITLAB_TOKEN", …)` и `gitlab_required` удаляются, `gitlab_token=` в
  конструкторе удаляется. После проверки `missing`: `without_key = [ws.id for ws in config.workspaces if
  ws.repo.access_ref is None]`; непусто → `logger.warning("workspace без repo.access_ref, задачи по ним уходят в
  error: %s", ", ".join(without_key))`. Контекст создаётся в любом случае.

### 5. `cli.py` `sandbox bootstrap`

- Docstring: «Ключи репозиториев workspace и embeddings берутся из vault по ссылкам harness.yaml…».
- В блоке `try … except VaultError`:

```python
repo_tokens: dict[str, SecretStr] = {}
for workspace in config.workspaces:
    token = asyncio.run(secret_refs.resolve(vault, workspace.repo.access_ref, fallback=None))
    if token is not None:
        repo_tokens[workspace.id] = token
```

- Проверка «нужен gitlab.access_ref или GITLAB_TOKEN» удаляется. Для каждого workspace без ключа:
  `typer.echo(f"workspace {ws.id}: нет repo.access_ref, клон анонимный (только публичный репозиторий)", err=True)`.
- `vault_values`: значения всех `repo_tokens`, embedding, плюс `git_access.git_auth_secret_values(ws.repo.provider,
  token)` для каждого workspace с ключом. Вызов `bootstrap(..., repo_tokens=repo_tokens, ...)`.

### 6. `settings.py`

Поля `gitlab_url` и `gitlab_token` удаляются. Остальное без изменений.

### 7. `security/redaction.py`

В `_PATTERNS` строка `glpat-` заменяется, добавляются строки (порядок: после Telegram):

```python
# GitLab: PAT, deploy, runner, OAuth и прочие токены с префиксом gl…- (D-60).
(re.compile(r"\bgl(?:pat|dt|rt|cbt|oas|ptt|ft|imt|agent|soat)-[A-Za-z0-9_.-]{20,}"), REDACTED),
# GitHub: classic PAT, OAuth, user-to-server, server-to-server, refresh (D-60).
(re.compile(r"\bgh[pousr]_[A-Za-z0-9]{36,}"), REDACTED),
# GitHub fine-grained PAT (D-60).
(re.compile(r"\bgithub_pat_[A-Za-z0-9_]{22,}"), REDACTED),
```

и после строки `bearer`:

```python
# Заголовок Basic git (oauth2:/x-access-token:<token> в base64): схема остаётся, значение заменяется.
(re.compile(r"(?i)\b(basic)\s+[A-Za-z0-9+/]{16,}={0,2}"), rf"\1 {REDACTED}"),
```

### 8. `deploy/sandbox/bootstrap.sh`

- Комментарий в шапке: пример без `--gitlab-url`; «Ключ репозитория уходит git только заголовком Authorization на
  префикс адреса своей пары (`GIT_CONFIG_*` в env одной команды); заголовок i-й пары приходит в env
  `GIT_AUTH_HEADER_<i>` (D-60)».
- Вместо `gitlab_token="${GITLAB_TOKEN:-}"` и `unset GITLAB_TOKEN EMBEDDING_API_KEY`:

```bash
# Заголовки git по парам (D-60): GIT_AUTH_HEADER_<i> — для i-й пары <id>=<url>, i с 0. Значения забираются
# в массив оболочки и снимаются из env до любых установок; имя с неверным номером — ошибка ниже.
declare -A git_auth_headers=()
bad_header_name=""
while IFS= read -r name; do
  case "$name" in
    GIT_AUTH_HEADER_*)
      if [[ "$name" =~ ^GIT_AUTH_HEADER_(0|[1-9][0-9]*)$ ]]; then
        git_auth_headers[${BASH_REMATCH[1]}]="${!name}"
      else
        bad_header_name="$name"
      fi
      unset "$name"
      ;;
  esac
done < <(compgen -e)
embedding_key="${EMBEDDING_API_KEY:-}"
# GITLAB_TOKEN сервер больше не передаёт (D-60); снимается на случай старого вызова.
unset GITLAB_TOKEN EMBEDDING_API_KEY
```

- `usage`: строка про `GITLAB_TOKEN`/`--gitlab-url` заменяется на «Ключ репозитория — заголовок в env
  GIT_AUTH_HEADER_<i> для i-й пары (с 0); без него клон анонимный.»
- Удалить `GITLAB_URL_RE`, переменную `gitlab_url`, ветку `--gitlab-url` в разборе аргументов (флаг теперь
  попадает в «неизвестный аргумент», код 2), проверки `--gitlab-url` и нормализацию `gitlab_url`.
- `PAIR_RE='^[A-Za-z0-9_-]{1,28}=https://[^[:space:]@?#]+$'`.
- После цикла проверки пар:

```bash
if [ -n "$bad_header_name" ]; then
  echo "$bad_header_name: ожидается GIT_AUTH_HEADER_<номер пары>" >&2
  exit 2
fi
HEADER_RE='^Authorization: Basic [A-Za-z0-9+/]+={0,2}$'
for index in "${!git_auth_headers[@]}"; do
  if [ "$index" -ge "${#repos[@]}" ]; then
    echo "GIT_AUTH_HEADER_$index без пары <workspace_id>=<clone_url>" >&2
    exit 2
  fi
  if ! [[ "${git_auth_headers[$index]}" =~ $HEADER_RE ]]; then
    echo "GIT_AUTH_HEADER_$index — не заголовок Authorization: Basic" >&2
    exit 2
  fi
done
```

  Значения заголовков в сообщения не попадают.
- Блок «Заголовок git для клонов и fetch» заменяется:

```bash
# Один вызов git для клона и fetch: заголовок — префиксная переменная той же команды, не argv. Префикс —
# адрес пары с завершающим «/»: заголовок получает только этот репозиторий (D-60). Без заголовка — анонимно.
run_git_auth() {
  local header="$1" prefix="$2"
  shift 2
  if [ -n "$header" ]; then
    # Редиректы выключены, чтобы заголовок не ушёл на другой хост.
    GIT_CONFIG_COUNT=2 GIT_CONFIG_KEY_0="http.${prefix}.extraHeader" \
      GIT_CONFIG_VALUE_0="$header" GIT_CONFIG_KEY_1=http.followRedirects \
      GIT_CONFIG_VALUE_1=false GIT_TERMINAL_PROMPT=0 git "$@"
  else
    GIT_TERMINAL_PROMPT=0 git "$@"
  fi
}
for index in "${!repos[@]}"; do
  pair="${repos[$index]}"
  workspace_id="${pair%%=*}"
  url="${pair#*=}"
  dir="$HOME/work/$workspace_id"
  header="${git_auth_headers[$index]:-}"
  if [ ! -e "$dir" ]; then
    echo "клонирую $workspace_id"
    run_git_auth "$header" "${url}/" clone --quiet -- "$url" "$dir"
  else
    if [ ! -d "$dir/.git" ]; then
      echo "$dir существует и не является git-репозиторием" >&2
      exit 1
    fi
    echo "обновляю $workspace_id"
    git -C "$dir" remote set-url origin "$url"
    run_git_auth "$header" "${url}/" -C "$dir" fetch --quiet --prune origin
  fi
done
```

- Остальное (память, guard `HARNESS_SANDBOX_BOOTSTRAP`, удаление askpass) без изменений. `shellcheck` проходит.

### 9. Контракт `GitProvider` (реализуется в `mvp-09`)

`adapters/git/protocol.py`:

```python
MergeRequestState = Literal["open", "merged", "closed", "none"]

@dataclass(frozen=True, slots=True)
class MergeRequestRef:
    number: int  # GitLab iid, GitHub номер PR
    url: str     # web_url / html_url

class GitProviderError(Exception):
    def __init__(self, reason: str) -> None: ...  # reason: "network" | "http_<status>" | "bad_response"; без тела ответа и ключа

class GitProvider(Protocol):
    async def find_open_mr(self, project: str, source_branch: str) -> MergeRequestRef | None: ...
    async def create_mr(self, project: str, *, source_branch: str, target_branch: str, title: str, description: str) -> MergeRequestRef: ...
    async def get_mr_state(self, project: str, source_branch: str) -> MergeRequestState: ...   # task-rework
    async def add_mr_note(self, project: str, number: int, body: str) -> None: ...            # task-rework
```

Фабрика `adapters/git/factory.py`: `build_git_provider(provider: GitProviderName, base_url: str, token: SecretStr,
client: httpx.AsyncClient) -> GitProvider`. REST-детали обеих реализаций — в design.md `mvp-09-delivery-mr`.
Push — git в песочнице с `git_access.git_auth_env(repo, token)` (D-56), не REST.

## Data flow / control flow

- **Загрузка конфига:** YAML → `_reject_secret_fields` → `HarnessConfig` (before: нет `gitlab`) → `WorkspaceConfig`
  (before: нет `gitlab_project`) → `RepoConfig` (before: адрес по умолчанию → проверка адреса → ref → правила
  провайдера). Любая ошибка → `ConfigError` с путём поля, без значения; сервер и worker не стартуют.
- **Bootstrap (CLI):** конфиг → для каждого workspace resolve `access_ref` (VaultError → выход 1 «Ошибка vault») →
  `bootstrap(repo_tokens)` → env `GIT_AUTH_HEADER_<i>` → скрипт снимает env → проверка пар и заголовков → клон/fetch
  каждой пары своим заголовком или анонимно → вывод через redaction (токены, заголовки, base64).
- **Задача (worker):** reserve → `_run_reserved` → workspace задачи → resolve ключа → нет → `error`
  `repo_access_ref: …` (песочница не активируется, cleanup как при любой ошибке) → есть → секреты в redaction →
  `activate` → `set-url origin` → fetch с заголовком на префикс репозитория → пайплайн.

## Validation and error handling

| Ситуация | Результат |
|---|---|
| `gitlab:` в корне | `ConfigError`: «секция gitlab удалена (D-60)…» |
| `gitlab_project` у workspace | `ConfigError` `workspaces[i]`: «gitlab_project удалён (D-60)…» |
| нет `repo` у workspace | `ConfigError` `workspaces[i].repo: Field required` |
| `provider` не github/gitlab | `ConfigError` `workspaces[i].repo.provider` |
| `base_url` http, с `@`, query, fragment | `ConfigError` `workspaces[i].repo.base_url`, значения нет |
| github + иной `base_url` | `ConfigError` «GitHub Enterprise пока не поддерживается…» |
| github + `group/sub/name` | `ConfigError` «project для github — owner/name» |
| gitlab + `name` (один сегмент) или `…/.git` | `ConfigError` |
| `access_ref` не `vault:…` | `ConfigError` `access_ref: ожидается ссылка vault:…` |
| `repo.token: …` в YAML | `ConfigError` «поле похоже на секрет» (как раньше) |
| задача, workspace без `access_ref` | задача `error`, причина `repo_access_ref: у workspace <id> нет repo.access_ref — задаче нужен ключ записи (push)` |
| vault недоступен при задаче | `error` `vault` (как раньше) |
| bootstrap: `--gitlab-url` | выход 2 «неизвестный аргумент» |
| bootstrap: `GIT_AUTH_HEADER_5` при 2 парах, `GIT_AUTH_HEADER_x`, неверный вид | выход 2 без значения |
| bootstrap: пара `http://…` | выход 2 «некорректная пара» |
| `repo_tokens` с неизвестным id | `ValueError` до вызова провайдера |

## Authorization and security

- Ключ — только ссылка vault в YAML; значение — env одной команды (bootstrap, fetch, в `mvp-09` push). В argv,
  файлы песочницы, логи и БД не попадает (D-20, D-52).
- Заголовок привязан к префиксу адреса репозитория; редиректы выключены; `origin` возвращается на адрес из
  конфига перед fetch. Ключ одного workspace не уходит в чужой репозиторий, в том числе на том же хосте.
- Только https.
- Минимальные права (вопрос 1): fine-grained токен на репозиторий, Contents RW и Pull requests RW. Ключ агенту не
  выдаётся (D-18, D-56): git в процессе агента запускается без заголовка.
- Redaction: шаблоны токенов GitHub и GitLab, `Basic …`, точные значения токена, заголовка и base64 для каждого
  ключа (CLI и worker).

## Backward compatibility

- **BREAKING для `harness.yaml`:** старая форма не загружается (решение 2). Порядок выката: владелец переносит
  `gitlab.base_url`/`gitlab.access_ref`/`gitlab_project` в `workspaces[].repo` и только потом выкатывает образ.
  Пример для GitLab: `repo: {provider: gitlab, base_url: https://gitlab.com, project: group/demo, access_ref:
  "vault:Repository/Gitlab/админский"}`; для GitHub: `repo: {provider: github, project: w1do/chistotyumen,
  access_ref: "vault:…"}`.
- ENV `GITLAB_TOKEN`/`GITLAB_URL` игнорируются; если ключ брался из ENV, владелец кладёт его в vault и задаёт
  `access_ref`.
- Подготовленная песочница: клоны уже есть, повторный bootstrap делает `set-url` и fetch с новым заголовком.
  Анонимные клоны публичных репозиториев не меняются.
- `mvp-08`/`mvp-09` ещё не реализованы, их пайплайны сразу пишутся на новых сигнатурах.

## Test strategy

Все команды — из корня репозитория. Новые и изменённые тесты (`apps/server/tests/`):

- `test_config.py` (заменить тесты `test_gitlab_*`):
  `test_repo_github_defaults_base_url`, `test_repo_gitlab_defaults_base_url`, `test_repo_gitlab_self_hosted_with_path`,
  `test_repo_base_url_trailing_slash_stripped`, `test_repo_base_url_http_rejected`,
  `test_repo_base_url_with_userinfo_rejected` (в сообщении нет пароля), `test_repo_base_url_forms_rejected`
  (parametrize: query, fragment, пробел, без схемы), `test_repo_github_enterprise_rejected`,
  `test_repo_github_project_must_be_owner_name`, `test_repo_gitlab_project_needs_group`,
  `test_repo_project_with_dot_git_rejected`, `test_repo_unknown_provider_rejected`,
  `test_repo_access_ref_accepts_vault_reference`, `test_repo_access_ref_must_be_vault_reference`,
  `test_repo_access_ref_optional`, `test_legacy_gitlab_section_rejected_with_hint`,
  `test_legacy_gitlab_project_rejected_with_hint`, `test_workspace_without_repo_rejected`,
  `test_workspaces_with_different_providers_accepted`; тесты, которые загружают `config/harness.example.yaml`,
  обновляются вместе с примером.
- `test_git_access.py`: `test_clone_url_github`, `test_clone_url_gitlab_subgroup`,
  `test_git_auth_header_uses_oauth2_for_gitlab`, `test_git_auth_header_uses_x_access_token_for_github`,
  `test_git_auth_env_is_scoped_to_repo_prefix` (ключ `http.https://github.com/w1do/chistotyumen.git/.extraHeader`,
  `followRedirects=false`), `test_git_auth_secret_values_cover_header_and_base64`, `test_change_request_label`.
- `test_sandbox_service.py`: заменить `test_activate_fetch_env_carries_url_scoped_auth_header`,
  `test_activate_token_without_base_url_raises_before_provider_call` (удалить), `test_git_auth_env_is_scoped_to_base_url_prefix`
  (перенести в `test_git_access.py`), `test_git_auth_header_is_redaction_secret_material` (перенести),
  `test_activate_without_token_fetches_anonymously`; добавить `test_activate_resets_origin_before_fetch`,
  `test_activate_github_fetch_uses_x_access_token_header`.
- `test_sandbox_bootstrap.py`: ожидаемые аргументы без `--gitlab-url`; `test_bootstrap_passes_header_per_pair_in_env`
  (два workspace: github с ключом → `GIT_AUTH_HEADER_0`, gitlab без ключа → нет `GIT_AUTH_HEADER_1`),
  `test_bootstrap_rejects_tokens_for_unknown_workspace`, `test_bootstrap_without_tokens_has_no_auth_env`
  (вместо `test_bootstrap_without_token_has_no_gitlab_env`); скриптовые: `test_script_rejects_removed_gitlab_url_flag`,
  `test_script_rejects_http_pair`, `test_script_rejects_header_without_pair`, `test_script_rejects_bad_header_name`,
  `test_script_rejects_malformed_header` (вывод не содержит значения), `test_script_unsets_auth_headers_before_any_install_step`,
  `test_script_binds_header_to_pair_prefix` (текст содержит `http.${prefix}.extraHeader` один раз и `"${url}/"` на
  clone и fetch), `test_script_allows_anonymous_clones_without_token` (обновить). Удалить
  `test_script_accepts_valid_gitlab_url`, `test_script_rejects_malformed_gitlab_url`,
  `test_script_requires_gitlab_url_when_clones_are_given`, `test_script_builds_header_from_token_via_builtins_and_stdin`;
  `test_script_unsets_token_and_does_not_export_it` → `test_script_does_not_export_auth_headers`.
- `test_dispatcher.py`: `test_repo_key_comes_from_workspace_access_ref` (вместо `test_gitlab_key_comes_from_vault_…`),
  `test_task_without_access_ref_goes_to_error_with_reason` (причина начинается с `repo_access_ref:`, в песочнице не
  было `git fetch` и `worktree add`), `test_dispatcher_fetch_is_bound_to_repo_prefix` (вместо `…_gitlab_base_url`),
  `test_auth_header_value_is_redacted_from_agent_output` (обновить на github), `test_build_context_ignores_gitlab_env`
  и `test_build_context_warns_about_workspace_without_key` (вместо трёх `test_build_context_*access_ref*`).
- `test_cli.py`: `test_sandbox_bootstrap_without_any_key_clones_anonymously_with_warning` (вместо
  `…_without_any_gitlab_key_exits_one`), `test_sandbox_bootstrap_redacts_auth_header_in_failure_output` (обновить).
- `test_redaction.py`: `test_redacts_github_classic_token`, `test_redacts_github_fine_grained_token`,
  `test_redacts_gitlab_token_prefixes` (parametrize `glpat-`, `gldt-`, `glrt-`), `test_redacts_basic_auth_header`
  (схема остаётся), `test_short_basic_word_is_kept` («basic idea» не меняется).
- Остальные файлы (`conftest.py`, `test_routing_service.py`, `test_telegram_render.py`, `test_polza_live.py`,
  `test_agent_runtime_live.py`, `test_sandbox_profile_live.py`): `gitlab_project="group/x"` →
  `repo=RepoConfig(provider="gitlab", project="group/x")`, `BASE_CONFIG.gitlab…` → поля `repo`. Live-тест профиля:
  `LIVE_GITLAB_ACCESS_REF` → `LIVE_REPO_ACCESS_REF`, плюс `LIVE_REPO_PROVIDER` (`github`|`gitlab`, по умолчанию
  `gitlab`) и `LIVE_REPO_PROJECT`.
- Live (`-m live`, владелец): `test_github_private_clone_live` — bootstrap с ключом `w1do/chistotyumen` клонирует
  приватный репозиторий; fetch активации проходит.

## Acceptance criteria

1. `harness.yaml` с workspace GitHub (`w1do/chistotyumen`) и workspace GitLab загружается; старая форма отклоняется
   с подсказкой.
2. Bootstrap в одной песочнице клонирует оба репозитория, каждый своим ключом; workspace без ключа — анонимно.
3. Задача на workspace GitHub активируется: fetch с `x-access-token`, заголовок только на префикс репозитория.
4. Задача на workspace без `access_ref` — `error` с причиной `repo_access_ref: …`, песочница не активировалась.
5. Ни токен, ни заголовок, ни его base64 не встречаются в выводе CLI, событиях задачи и логах (тесты redaction).
6. `./tools/harness check` зелёный; `openspec validate --all` без ошибок; live `test_github_private_clone_live` пройден.

## Rollback

Откат — revert коммитов изменения и возврат `harness.yaml` к форме с `gitlab:` (сохранить копию файла до правки).
Миграций БД нет. Песочницу трогать не нужно: клоны совместимы, следующий bootstrap старой версии вернёт
`origin`. ENV `GITLAB_TOKEN` вернуть, если ключ брался из ENV.

## Разрешённые для изменения файлы

Только файлы из таблиц «Новые файлы» и «Изменяемые файлы», `docs/decisions.md` (пометки, D-60 уже записано),
`docker-compose.yml` (удалить `GITLAB_URL`, `GITLAB_TOKEN`, если есть) и `.env.example` — только по явной команде
владельца (вопрос 6). Другие файлы не меняются.

## Commands

```bash
./tools/harness fmt
./tools/harness check        # ruff check, ruff format --check, mypy strict, shellcheck, pytest
openspec validate git-providers --strict
openspec validate --all
```

## Risks / Trade-offs

- [Выкат образа до правки `harness.yaml`] → сервер не стартует с понятной ошибкой; порядок выката в
  docs/deployment.md, откат — прежний образ.
- [GitHub изменит обработку Basic с `x-access-token`] → тот же способ использует `actions/checkout`; live-тест
  6.1 ловит регресс.
- [Префикс репозитория не совпал с URL запроса (регистр, `.git`)] → адрес клона собирается из конфига один раз
  (`clone_url`) и тот же адрес становится `origin`; GitHub не перенаправляет при выключенных редиректах, ошибка
  видна как сбой fetch.
- [Чистый разрыв ломает чужие копии `harness.yaml`] → пример и сообщение об ошибке указывают точную замену.

## Ordered implementation steps (Implementer)

1. `config.py` по разделу 1; обновить `config/harness.example.yaml` (у `demo`: `repo: {provider: gitlab, project:
   group/demo}` с комментарием про `base_url` и `access_ref`; секцию `gitlab:` удалить; закомментированный пример
   workspace GitHub `w1do/chistotyumen`). Тесты `test_config.py`. `./tools/harness check` по `test_config.py`.
2. `services/git_access.py` по разделу 2 и `tests/test_git_access.py`.
3. `security/redaction.py` по разделу 7 и `test_redaction.py`.
4. `services/sandboxes.py` по разделу 3; `test_sandbox_service.py`, серверная часть `test_sandbox_bootstrap.py`.
5. `deploy/sandbox/bootstrap.sh` по разделу 8; скриптовые тесты `test_sandbox_bootstrap.py`; shellcheck.
6. `settings.py` (раздел 6), `worker/dispatcher.py` (раздел 4), `cli.py` (раздел 5); `test_dispatcher.py`, `test_cli.py`.
7. Остальные тесты из «Test strategy» (фабрики `WorkspaceConfig`, live-тесты). `./tools/harness check` целиком.
8. Документация: задачи раздела 6 tasks.md.
9. Память проекта: задачи раздела 7 tasks.md.
