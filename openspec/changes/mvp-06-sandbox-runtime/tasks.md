# Tasks

## 1. Адаптер песочницы

- [ ] 1.1 `adapters/novita`: Protocol `SandboxProvider` (`exec`, `write_file`, `read_file`, `pause`, `resume`, `extend_timeout`) по фактам `docs/novita.md`; синхронный SDK — через `asyncio.to_thread` — проверка: mypy
- [ ] 1.2 Фейк `FakeSandbox` (файлы в памяти, журнал команд, программируемые ответы) — проверка: используется в тестах ниже
- [ ] 1.3 Live-тест `-m live`: exec, write/read, pause/resume на реальной песочнице — проверка: проходит вручную

## 2. Bootstrap

- [ ] 2.1 `deploy/sandbox/bootstrap.sh`: pinned `claude`, `openspec`, `git`, каталоги `~/.harness`, клон репозиториев (токен через `GIT_ASKPASS` из env), `mcp.json` с `${AGENTS_FLOW_URL}`/`${AGENTS_FLOW_TOKEN}`; `set -euo pipefail`, идемпотентность — проверка: shellcheck; двойной запуск в песочнице без ошибок
- [ ] 2.2 `harness-server sandbox bootstrap` — копирует скрипт в песочницу и выполняет — проверка: тест с фейком (команды в журнале)

## 3. Сервис песочниц

- [ ] 3.1 `services/sandboxes.activate`: блокировка строки, resume, выдача токена задачи (`security/tokens.py`: генерация, хеш, отзыв), `git fetch`, worktree `task/<id>` от базы; идемпотентность — проверка: тесты «Песочница занята», «Повторная активация»
- [ ] 3.2 `run_agent`: запись `run.sh`/`prompt.md`, фоновый запуск с env-кредами, pid — проверка: тест с фейком; в записанных файлах нет значений кредов (сценарий «Проверка диска»)
- [ ] 3.3 `poll`: чтение `status.json`, таймаут `AGENT_RUN_TIMEOUT_MIN` с kill и `error` — проверка: тесты «Агент завершился», «Превышено время»
- [ ] 3.4 `cleanup` + `pause` после успеха; `error` при неудаче — проверка: тест «Очистка не удалась»

## 4. Worker и CLI

- [ ] 4.1 Каркас пайплайна в `worker/dispatcher.py`: claim → activate → run → poll → (этапы kind) → cleanup → pause; регистрация пайплайнов по `kind` — проверка: тест с фейковым пайплайном
- [ ] 4.2 `harness-server sandbox pause|resume|status` с отказом при активной задаче — проверка: тест «Пауза занятой песочницы»
- [ ] 4.3 ARCHITECTURE.md §7, §9 (`ANTHROPIC_API_KEY`, `AGENT_RUN_TIMEOUT_MIN`), docs/deployment.md, PLAN.md — проверка: ревью

## 5. Память проекта

- [ ] 5.1 `memory_update` по изменённым путям, `memory_annotate` для каждого нового файла, `memory_status` без устаревших файлов
