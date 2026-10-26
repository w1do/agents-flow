# Tasks

STATUS: BLOCKED на проверках Postgres (доступ к Docker запрещён).

Отсутствующие MCP и worker API-контракты реализованы в 2.2–2.3 по решению оркестратора
от 2026-10-26; требования добавлены в specs/spec-planning/spec.md.
Код 2.2–2.3 и 3.1 написан; галочки оставлены открытыми до успешного прогона
test_planner_mcp.py, test_worker_plan_api.py и test_plan_dispatch_api.py с реальной Postgres.
Пайплайн с фейками, настоящий Git/OpenSpec, MCP-транспорт SDK и текст итога проверены без БД.

## 1. Гейты общего назначения

- [x] 1.1 `security/redaction.scan_diff(diff, extra_values)` → список находок без значений; тесты на шаблоны и точные значения — проверка: pytest
- [x] 1.2 `worker/gates.py`: `secret_scan`, `push` (идемпотентно через `ls-remote`), результат шага `GateResult` — проверка: тесты с фейковой песочницей (повторный push пропускается)

## 2. Планировщик

- [x] 2.1 `services/prompts/planner.md` (правила OpenSpec, декомпозиция, ключи пунктов, обязательные вызовы MCP, коммит) — проверка: снапшот-тест сборки промпта с данными задачи
- [ ] 2.2 Пайплайн `plan` в `worker/pipelines/plan.py`: activate (база `origin/<default_branch>`) → run_agent → poll → проверки → push → `ready` — проверка: тест с фейками, где «агент» пишет каталог изменения и вызывает сервисы
- [ ] 2.3 Проверки плана: новый каталог `openspec/changes/<id>/`, `openspec validate <id>` через exec, ≥1 задача `implement`; при отказе `error` + задачи в `trash` — проверка: тесты «Спецификация не проходит проверку», «Секрет в спецификации»
- [x] 2.4 Регрессия регистрации plan: SIGTERM/SIGINT отменяют текущий dispatch и ожидания HTTP до закрытия клиента; исходные SIGTERM-тесты и тесты зависших recover/claim и паузы опроса — 5 passed. Полный прогон test_worker.py/test_worker_plan_api.py вместе с регрессиями: 5 passed, 5 ошибок подготовки Postgres (Docker запрещён).

## 3. Итог

- [ ] 3.1 `notify`: строка «спецификация готова, задач: N» + список — проверка: тест «Три задачи»
- [x] 3.2 ARCHITECTURE.md §5 п.4, PLAN.md — проверка: ревью
- [ ] 3.3 За владельцем: live-проверка текстом «создай …» в Telegram получен план, ветка `task/<plan_id>` в GitLab, задачи в `backlog` (`list_tasks`) — проверка: скриншот/ссылки в PR

## 4. Память проекта

- [ ] 4.1 За оркестратором: `memory_update` по изменённым путям, `memory_annotate` для каждого нового файла, `memory_status` без устаревших файлов; локально не выполнять по решению оркестратора
