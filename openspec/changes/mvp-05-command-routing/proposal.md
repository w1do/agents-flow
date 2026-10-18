# Proposal: mvp-05-command-routing

## Why

Голос никогда не запускает разработку напрямую: сначала Polza определяет класс команды и предлагает проекты,
решение остаётся за человеком (ТЗ §2 п.2, §5.0). Для среза нужны классы «работа» и «запрос состояния» (ТЗ §16.0 п.2).

## What Changes

- Адаптер `adapters/polza` (`Router`): OpenAI-совместимый chat completions, ответ — JSON по схеме
  `{class, confidence, workspaces: [{id, score}], title}`; фейк. Формат Polza подтверждается в задаче 1.1 (D-17).
- `services/routing.py`: промпт из списка workspace (id, name, voice_aliases), валидация ответа Pydantic,
  отбрасывание неизвестных id, не больше 3 кандидатов, запись `routings` (варианты, сырой ответ, выбор).
- Классы MVP: `work` → путь `mvp-04` с ранжированными кнопками (первая — самая вероятная) + короткое название задачи;
  `status` → ответ из `services.tasks.list_tasks` (открытые задачи по workspace) без песочниц; `unknown` →
  «не понял, вот что умею».
- Неуверенность (confidence ниже порога из настроек) → кнопки «Сделать задачу» / «Показать статус»; работа без нажатия не стартует.
- Polza недоступна или ответ невалиден → кнопки со всеми workspace (D-13).

## Capabilities

### New Capabilities

- `command-routing`: определение класса команды и кандидатов workspace, ответы на запрос состояния.

### Modified Capabilities

Нет (поведение `telegram-bot` не меняется: кнопки те же, меняется порядок и число).

## Impact

- ENV: `POLZA_AI_URL`, `POLZA_AI_KEY`, `POLZA_AI_MODEL`, `ROUTING_MIN_CONFIDENCE` (по умолчанию 0.6).
- Зависит от: `mvp-04-telegram-intake`.
- Ссылки: ТЗ §5 шаг 2, §5.0, §16.0 п.2, §16.1 C4.

## Не входит

Классы `check` и `control` (`check-tasks`, `control-commands`), «Другой проект» (`telegram-other-project`),
«сколько потрачено» (`status-commands`).
