# Proposal: sandbox-profile

> Подготовка песочницы без участия владельца: bootstrap, ключи из vault, память проекта. Решение владельца
> 2026-10-19: делается сразу после `mvp-06-sandbox-runtime`, затем `integrations-mcp-config`, оба до
> `mvp-07-agents-flow-mcp` (D-43). Решения — D-43…D-45, D-47, D-48.

## Open questions (нужен ответ владельца)

Код пишется и тестируется с фейками без ответов. Ответы нужны для live-проверок (tasks, раздел 5) и боевого запуска.

1. **Адрес и авторизация vault MCP для сервера.** Заложено: ENV `VAULT_MCP_URL` (https) и `VAULT_MCP_TOKEN`, заголовок
   `Authorization: Bearer <token>`, транспорт Streamable HTTP. Если авторизация другая — меняется только
   `adapters/vault/mcp_client.py`. Имя поля с секретом в ответе `get_credential` (заложено `secret`).
2. **Ссылки на ключи в vault** (`<project>/<service>/<name>`): главный ключ GitLab, ключ embeddings Polza для memory-agent.
3. **Ресурсы.** Если live-проверка 5.3 («memory-agent + агент в 2 ГБ») не пройдёт — какой размер песочницы брать.

## Why

Песочница должна готовиться одной командой, без ручных шагов (ТЗ §9, §13). Агенту нужна память проекта
(memory-agent). Ключи лежат в vault владельца; сервер берёт их сам и не оставляет на диске песочницы.

## What Changes

- **Bootstrap расширяется** (тот же `deploy/sandbox/bootstrap.sh`, идемпотентно, через `sudo -n`): Node ≥ 22.13
  (NodeSource), глобальные npm-пакеты в системный префикс через sudo, пустые `~/.claude/skills` и `~/.claude/agents`;
  при включённой памяти — Docker Engine + Compose v2, memory-agent (`project-memory` точной версии,
  `memory service up`, `memory init` для каждого workspace). Шагов про MCP нет.
- **Vault-адаптер** `adapters/vault/` (Protocol `SecretVault`, фейк, MCP-клиент на официальном Python SDK,
  инструмент `get_credential`). Ссылка на секрет — `vault:<project>/<service>/<name>`. Доступ сервера — без подтверждения.
- **Настройки** `harness.yaml`: `gitlab.access_ref` (главный ключ GitLab из vault; без него — ENV `GITLAB_TOKEN`),
  `sandbox.memory` (`version` пакета `project-memory`, `embedding_ref`).
- **Рантайм (изменение `sandbox-runtime`)**: GitLab-ключ и ключ embeddings берутся из vault и передаются только в env
  команд; при активации — `memory sync` по клону workspace (сбой не роняет задачу); при запуске агента —
  `HARNESS_MEMORY_PROJECT`; redaction покрывает значения из vault.

## Capabilities

### New Capabilities

- `sandbox-profile`: подготовка песочницы bootstrap-скриптом, ключи из vault, память проекта.

### Modified Capabilities

- `sandbox-runtime`: секреты из vault в env команд и redaction по ним.

## Impact

- Зависит от: `mvp-06-sandbox-runtime`. Архивировать после `mvp-06`: delta `sandbox-runtime` (MODIFIED) опирается на
  его спеку в `openspec/specs/`. Если раньше влит `mvp-06b-vps-provider`, `SandboxProvider` импортируется оттуда же,
  откуда его импортирует `services/sandboxes.py`.
- Следующее изменение `integrations-mcp-config` использует vault-адаптер и генерирует MCP-конфиг агента.
- Новая зависимость: `mcp` (официальный Python SDK, точная версия; `mvp-07` использует ту же).
- Новые ENV: `VAULT_MCP_URL`, `VAULT_MCP_TOKEN`. Миграций БД нет.
- Документация: ARCHITECTURE.md (§7, §9), docs/decisions.md, docs/deployment.md, PLAN.md, docs/open-questions.md
  (вопросы 4 и 6).

## Не входит

- Отдельный репозиторий профиля, таблица версий профиля, одноразовая ссылка `GET /bootstrap/...`, инструменты
  `get_profile`/`update_profile`/`get_bootstrap_link`: настройки — в `harness.yaml` (позже в консоли), ссылка — `sandbox-pool`.
- Свой шаблон Novita: песочница одна и переиспользуется через паузу. Шаблон может появиться в `sandbox-pool`.
- Установка языков и стека проектов: это делает агент по предпочтениям владельца.
- MCP-серверы агента (`integrations-mcp-config`), наполнение skills и агентов Claude (`skills-library`).
- Автоматический повторный bootstrap при активации (`sandbox-pool`).
