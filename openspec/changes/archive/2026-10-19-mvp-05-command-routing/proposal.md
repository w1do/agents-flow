# Proposal: mvp-05-command-routing

## Why

Голос никогда не запускает разработку напрямую: сначала Polza определяет класс команды и предлагает проекты,
решение остаётся за человеком (ТЗ §2 п.2, §5.0). Для среза нужны классы «работа» и «запрос состояния» (ТЗ §16.0 п.2).
В `mvp-04` любой текст становится задачей `plan` с кнопками всех workspace; классификации нет.

## What Changes

- Адаптер `adapters/polza` (`Router`, `PolzaRouter`, `FakeRouter`): OpenAI-совместимый `POST {POLZA_AI_URL}/chat/completions`,
  `response_format: json_object`, жёсткий таймаут 10 с на попытку и не больше одной повторной попытки (D-31).
- `shared/harness_shared/routing.py`: `CommandClass` (`work`/`status`/`unknown`), `RoutingDecisionKind`
  (`auto`/`clarify`/`fallback`), `WorkspaceCandidate`, `RoutingDecision` — валидация JSON модели
  `{class, confidence, workspaces: [{id, score}], title}`.
- `services/routing.py` + промпт `services/prompts/routing.md`: один вызов модели; сервер отбрасывает неизвестные id,
  убирает дубли, сортирует по score и оставляет ≤ 3 кандидатов; каждое решение (класс, уверенность, варианты,
  сырой ответ после redaction, причина ошибки) пишется в `routings`.
- Миграция `0003`: `routings.task_id` становится nullable; новые колонки `decision`, `error`, `source_text`,
  `resolved_at`; CHECK для `command_class` и `decision` (D-32).
- Встраивание в `services/intake`: `work` → задача `plan` в `choosing` и кнопки кандидатов (первая — самая вероятная);
  `status` → отчёт об открытых задачах из `services.tasks.list_tasks` без LLM и без песочниц; `unknown` →
  «Не понял, вот что умею: …».
- Уверенность ниже `ROUTING_MIN_CONFIDENCE` (по умолчанию 0.6) для любого класса → кнопки «Сделать задачу» /
  «Показать статус» (`callback_data = rt:<routing.id.hex>:w|s`); задача не создаётся до нажатия (D-33).
- Polza не настроена, недоступна или ответ невалиден → задача в `choosing` с кнопками всех workspace (D-13).
- Нажатие кнопки проекта записывает `routings.chosen_workspace_id`.

## Capabilities

### New Capabilities

- `command-routing`: класс команды и кандидаты workspace, уточнение кнопкой, запасной путь, ответ на запрос состояния.

### Modified Capabilities

- `telegram-bot`: требование «Выбор проекта кнопкой» уточняется: задачу создаёт только текст класса `work`
  (или запасной путь), кнопок не больше трёх, самый вероятный проект первым.

## Impact

- ENV: `POLZA_AI_URL` (по умолчанию `https://polza.ai/api/v1`, только `https://`), `POLZA_AI_KEY` (секрет),
  `POLZA_AI_MODEL`, `ROUTING_MIN_CONFIDENCE` (по умолчанию 0.6; в коде mvp-02 было 0.7 — исправляется).
  Переменные уже есть в Compose и ARCHITECTURE §9.
- БД: миграция `0003` (таблица `routings`, данных до mvp-05 в ней нет).
- Внешний сервис: текст команды владельца (после redaction, ≤ 2000 символов) уходит в Polza.
- Зависит от: `mvp-04-telegram-intake`. Решения: D-13, D-17, D-31…D-34.
- Ссылки: ТЗ §5 шаг 2, §5.0, §16.0 п.2, §16.1 C4.

## Не входит

Классы `check` и `control` (`check-tasks`, `control-commands`), «Другой проект» (`telegram-other-project`),
«сколько потрачено» (`status-commands`), напоминания и пометка неуверенности по разнице score
(`routing-uncertainty`), повторная отправка потерянного сообщения уточнения.
