# Tasks

Порядок обязателен. Подробности, имена и строки — design.md. После каждой группы — `./tools/harness check`.

## 0. Подготовка

- [ ] 0.1 Ответы владельца на вопросы 1–8 `proposal.md` получены. При ответе не по умолчанию design.md исправлен до
  начала кода. Через project-memory сверены имена mvp-07/mvp-09: `AgentContext`, `@agent_tool`, инструмент «сдать
  работу», пайплайн `implement`, события гейтов `gate:<name>:<state>`, `GitProvider`. Расхождения в именах внесены в
  design.md. Расхождение в поведении → стоп и эскалация — проверка: запись в отчёте

## 1. Модель, статусы, миграция

- [ ] 1.1 `shared/.../dialog.py` (`DialogKind`, `DialogState`, `LinkKind`, `BoundVia`). В `shared/.../routing.py`:
  `CommandClass.FEEDBACK`, `RoutingDecisionKind.BOUND`, `TaskCandidate`, поля `tasks`/`actionable`,
  `FeedbackAssessment` — проверка: `test_routing_models.py` (старые ответы без новых полей валидны)
- [ ] 1.2 Переходы в `domain/statuses.py` (design §14) — проверка: тесты переходов из design «Test strategy»
- [ ] 1.3 `db/models/dialog.py`, колонки `tasks.followup_of_id`, `tasks.run_base_sha`, `routings.bound_via`,
  миграция с переносом карточек и `downgrade` — проверка: `test_migration_task_dialog.py`, `test_migrations.py`

## 2. Telegram: разбор, клиент, рендер

- [ ] 2.1 `reply_to_message_id` в `telegram/parse.py` — проверка: `test_parse_reply_to_message_id`,
  `test_load_incoming_without_reply_field`
- [ ] 2.2 `send_message(force_reply, reply_to_message_id)` в протоколе, клиенте и фейке — проверка: контрактный тест respx на тело запроса
- [ ] 2.3 Константы, callback-функции и клавиатуры в `telegram/render.py`, строка `#ref` в карточке — проверка:
  тесты render из design

## 3. Сервис диалога

- [ ] 3.1 `task_ref`, `extract_refs`, `find_tasks_by_ref`, `link_message`, `resolve_link`, `recent_tasks_for_routing`
  — проверка: `test_task_ref_uses_tail`, `test_find_tasks_by_ref_ambiguous`, `test_link_message_idempotent`
- [ ] 3.2 `ask_owner`, `open_question_count`, ветка «ответ» в `handle_owner_message` — проверка:
  `test_ask_owner_*`, `test_answer_*`
- [ ] 3.3 Оценка ясности, уточнение, подтверждение, `accept_feedback`, `create_followup_task`, предел — проверка:
  остальные тесты `test_task_dialog.py`
- [ ] 3.4 `consume_for_run`, `build_dialog_prompt`, `requeue_if_pending`, `deliver_owner_questions`, промпт
  `dialog.md` — проверка: `test_consume_for_run_sets_cycle`, `test_prompt_history_truncated_oldest_first`,
  `test_requeue_if_pending_after_ready`, `test_deliver_owner_questions_links_message`

## 4. Маршрутизация и приём

- [ ] 4.1 `routing.md` (дословно, design §3), `feedback.md`, `build_system_prompt(tasks)`, `rank_task_candidates`,
  `feedback_leader`, `assess_feedback`, `record_routing(bound_via)` — проверка: `test_routing_feedback.py`
- [ ] 4.2 `services/intake.py`: шаги привязки до `classify`, `_DialogPending`, кнопки `rw:`/`rf:`/`fb:`,
  `notify.*` из design §13, ссылка `card` в `send_task_card` — проверка: `test_intake_dialog.py`, тесты mvp-04/05 зелёные

## 5. MCP, worker, гейты

- [ ] 5.1 MCP-инструмент `ask_owner` и строка в промптах планировщика и исполнителя — проверка: `test_ask_owner_tool.py`
- [ ] 5.2 `GitProvider.get_mr_state`, `add_mr_note` в `adapters/git` (GitLab и GitHub, D-60) + фейк + respx — проверка: контрактные тесты адаптера
- [ ] 5.3 Активация на существующей ветке, `run_base_sha`, `consume_for_run` в пайплайнах `implement` и `plan`,
  `deliver_owner_questions` в `dispatch_once` — проверка: `test_rework_uses_existing_branch`, `test_followup_branch_from_default`
- [ ] 5.4 `pause_for_owner` (WIP-коммит → все базовые гейты D-58 из `CORE_GATES` → push `task/<id>` без force,
  без `tests` и MR; отказ гейта → `error`), гейты по прогону, push без force, заметка MR, строки этапов доработки,
  `send_rework_done`, `requeue_if_pending` — проверка: остальные тесты `test_rework_pipeline.py`
- [ ] 5.5 `settings.task_rework_max`, поля `BotContext` (`rework_max`, `git`), wiring — проверка: `test_settings.py`, `test_wiring_*`

## 6. Live-проверка (владелец)

- [ ] 6.1 Сквозной сценарий в боевом Telegram: задача → MR → reply «поменяй …» → новые коммиты в том же MR → «доработка 1: готова, MR обновлён» — проверка: подтверждение владельца
- [ ] 6.2 `test_polza_feedback_live`: 10 фраз mvp-05 + 4 фразы `feedback` на модели D-55 без регрессии — проверка: вывод теста, чекбокс закрывает владелец
- [ ] 6.3 Вопрос агента: `ask_owner` → сообщение в Telegram → ответ reply'ем → задача продолжается — проверка: подтверждение владельца

## 7. Документация

- [ ] 7.1 ARCHITECTURE.md: §3 (`task_dialog`, `telegram_message_links`, новые колонки), §4 (переходы), §5 (привязка
  до классификации, доработка, вопрос агента), §6 (`ask_owner`), §9 (`TASK_REWORK_MAX`) — проверка: ревью диффа
- [ ] 7.2 docs/decisions.md: решения 1–16 design.md → следующие свободные номера после D-58, ответы на вопросы proposal.md. docs/glossary.md:
  `DialogEntry`, `MessageLink`, `feedback`, «доработка», «задача-продолжение», `ref`. docs/mcp-agents-flow.md:
  `ask_owner` — проверка: ревью диффа
- [ ] 7.3 PLAN.md: статус `task-rework`. README `apps/server`: команды тестов — проверка: ревью диффа
- [ ] 7.4 Порядок отката (design «Rollback») — в docs/deployment.md или README сервера — проверка: ревью диффа
- [ ] 7.5 `docker-compose.yml` и `.env.example`: `TASK_REWORK_MAX` — только по явной команде владельца, иначе пункт
  пропускается и отмечается в отчёте

## 8. Память проекта

- [ ] 8.1 `memory_update` по изменённым путям, `memory_annotate` для каждого нового и изменённого файла, `memory_status` без устаревших файлов
