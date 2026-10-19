# Tasks

Порядок и детали — design.md («Ordered implementation steps», разделы §1–§15). Имена тестов обязательны.

## 1. Контракт Polza, модели и схема

- [x] 1.1 Проверить по документации Polza формат chat completions, `response_format`, список моделей; записать в `docs/decisions.md` (обновить D-17, D-31) — проверка: ссылки на документацию в записи (выполнено Architect)
- [x] 1.2 `shared/src/harness_shared/routing.py`: `CommandClass`, `RoutingDecisionKind`, `WorkspaceCandidate`, `RoutingDecision` (design §1) — проверка: `test_routing_models.py` (невалидный класс и confidence, лишние поля игнорируются, title нормализован)
- [x] 1.3 `domain/errors.py::AlreadyResolved` (design §14) — проверка: используется тестом `test_claim_twice_raises_already_resolved`
- [x] 1.4 `db/models/planning.py::Routing` и миграция `20261018_0003_routing_decision.py` (design §15) — проверка: `test_routings_schema_after_0003`, `test_downgrade_and_upgrade_roundtrip` (`alembic check` чистый)

## 2. Адаптер Polza и внедрение

- [x] 2.1 `adapters/polza`: `Router`, `RouterReply`, `RouterError`, `PolzaRouter` (жёсткий таймаут 10 с, одна повторная попытка по правилам D-31, повтор без `response_format` после 400), `FakeRouter` (design §2–§4) — проверка: `test_polza_client.py` (respx)
- [x] 2.2 `settings.py` (`ROUTING_MIN_CONFIDENCE` = 0.6, `POLZA_AI_URL` только https), `services/context.py` (`router`, `routing_min_confidence`), `wiring.py` (`BotAdapters.router`, `PolzaRouter` при ключе и модели), `conftest.py` (`make_bot_context`, `routing_content`) (design §11–§13) — проверка: `test_settings.py`, `test_wiring_routing.py`

## 3. Сервис маршрутизации и Telegram

- [x] 3.1 `services/prompts/__init__.py`, `services/prompts/routing.md` (дословно design §5) и `services/routing.py` (design §6): сборка промпта, извлечение JSON, фильтр id, ≤ 3 кандидата, `classify`, запись `routings`, уточнение — проверка: `test_routing_service.py` (сценарий «Модель вернула несуществующий проект» — `test_rank_drops_unknown_workspace`)
- [x] 3.2 `telegram/render.py`: тексты, `rt:<hex>:w|s`, клавиатура уточнения, `render_status_report` (design §8) — проверка: дописанный `test_telegram_render.py`
- [x] 3.3 `services/status_report.py` (design §7) — проверка: `test_status_report.py`
- [x] 3.4 `services/notify.py` (`send_task_card(..., workspaces=)`, `send_clarify`, `close_prompt`) и `services/intake.py` (`_route_text`, `_send_followup`, `handle_button`, `resolve_clarification`, `record_choice` в `choose_workspace`) (design §9–§10) — проверка: `test_intake_routing.py` (сценарии «Команда на работу», «Ранжирование кнопок», «Непонятная команда», «Низкая уверенность», «Уточнение: сделать задачу», «Уточнение: показать статус», «Повторное нажатие уточнения», «Polza недоступна», «Невалидный ответ модели», «Что по задачам», «Секрет в команде», «Выбор записывается в решение маршрутизации»); тесты mvp-04 проходят без правок

## 4. Проверки

- [x] 4.1 `test_polza_live.py` (маркер `live`, по умолчанию не запускается) — проверка: `pytest -m live` с ключом владельца пропускается без ENV
- [x] 4.2 `uv run ruff format .`, `./tools/harness check` — проверка: зелёный
- [x] 4.3 `routing.md` входит в wheel (команда из design «Commands») — проверка: `grep` находит путь
- [x] 4.4 `openspec validate mvp-05-command-routing --strict` и `openspec validate --all` — проверка: без ошибок

## 5. Документация и ручная проверка

- [x] 5.1 ARCHITECTURE.md (§2, §3 `routings`, §5 п.2, §8 Polza, §9 `POLZA_*`/`ROUTING_MIN_CONFIDENCE`), `db/README.md` (ревизия 0003), `apps/server/README.md`, `shared/README.md`, PLAN.md (статус mvp-05), `.env.example` (только по разрешению владельца, design Open questions п.3) — проверка: ревью
- [x] 5.2 Ручная проверка `-m live` и через бота на 10 реальных фразах (5 работа, 3 статус, 2 мусор), часть голосом; модель выбирает владелец (Open questions п.1); результат — таблица «фраза → класс, confidence, кандидаты» в MR — проверка: таблица фраз и классов
  Результат 2026-10-19 (принято владельцем, D-55): модель `anthropic/claude-haiku-5.5`, по 2 прогона на фразу, `-m live`.
  Проверка через бота голосом отложена до первого деплоя.

  | Ожидается | Фраза | Класс, confidence, кандидаты (оба прогона) |
  |---|---|---|
  | работа | сделай авторизацию по email в магазине | work 0.95, shop 0.95 |
  | работа | добавь в демо-проект страницу с ценами | work 0.95, demo 0.95 |
  | работа | почини баг с корзиной, товары пропадают | work 0.93 / 0.85, shop 0.85 / 0.70 |
  | работа | нужен экспорт заказов в эксель | work 0.80 / 0.85, shop 0.60 / 0.70 |
  | работа | перепиши readme в демо проекте | work 0.95, demo 0.95 |
  | статус | какие задачи открыты | status 0.95 |
  | статус | что с задачами по магазину | status 0.90 |
  | статус | как там авторизация, готово? | status 0.90 |
  | мусор | эээ ну короче | unknown 0.90 |
  | мусор | привет как дела | unknown 0.95 |

  Сравнение: `mistralai/mistral-nemo` — 7/10 (пропуск `confidence`, «как там авторизация» → work), `openai/gpt-4.1-mini` — 10/10.

## 6. Память проекта

- [x] 6.1 `memory_update` по изменённым путям, `memory_annotate` для каждого нового и изменённого файла, `memory_status` без устаревших файлов
