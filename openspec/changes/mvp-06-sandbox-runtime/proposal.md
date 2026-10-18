# Proposal: mvp-06-sandbox-runtime

## Why

Задачи выполняются только в песочницах (ТЗ §2 п.3), клиента в песочнице нет (п.4): сервер сам возобновляет
песочницу, готовит worktree, запускает агента exec-командой и следит за ним. Это общий механизм для
планировщика (`mvp-08`) и исполнителя (`mvp-09`). Опирается на факты из `mvp-01-novita-spike`.

## What Changes

- Адаптер `adapters/novita` (`SandboxProvider`): `exec` (с env, таймаутом, фоном), `write_file`, `read_file`,
  `pause`, `resume`, `extend_timeout` + фейк (in-memory файловая система и журнал команд).
- `deploy/sandbox/bootstrap.sh`: pinned `claude` и `openspec`, `git`, клон репозиториев workspace,
  `~/.harness/`, `.mcp.json` с `${AGENTS_FLOW_URL}` и `${AGENTS_FLOW_TOKEN}`. Без секретов, идемпотентен.
- `services/sandboxes.py`: `activate(task)` (блокировка строки песочницы `SKIP LOCKED`, resume, токен задачи,
  `git fetch`, worktree на `task/<id>` от заданной базы), `run_agent(task, prompt)` (фоновый `claude -p`,
  вывод в `~/.harness/tasks/<id>/stream.jsonl`, итог в `status.json`), `poll(task)`, `cleanup(task)`
  (worktree, локальная ветка, отзыв токена), `pause()` только после успешной очистки.
- Worker: цикл выбирает задачу, активирует песочницу и ведёт её через этапы (каркас пайплайна; содержимое
  этапов plan/implement — в `mvp-08`/`mvp-09`).
- CLI: `harness-server sandbox pause|resume|status|bootstrap`.

## Capabilities

### New Capabilities

- `sandbox-runtime`: жизненный цикл песочницы и запуск агента по задаче.

### Modified Capabilities

Нет.

## Impact

- ENV: `NOVITA_API_KEY`, `NOVITA_DOMAIN`, `CLAUDE_CODE_OAUTH_TOKEN` (токен подписки, D-18), `AGENT_RUN_TIMEOUT_MIN` (по умолчанию 60).
- Конфиг: `sandbox.provider_id`, `workspace.agent` (команда и pinned-версия).
- Зависит от: `mvp-01-novita-spike` (факты API), `mvp-03-task-store`.
- Ссылки: ТЗ §9, §10, §16.0 п.4 и 7, §16.1 A5.

## Не входит

Пул и создание песочниц (`sandbox-pool`), продление сессии и ретраи каждые 10 минут (`sandbox-timeout-extend`),
heartbeat (`agent-heartbeat`), сессии и handoff (`agent-sessions`), снимки (`harness-snap`).
