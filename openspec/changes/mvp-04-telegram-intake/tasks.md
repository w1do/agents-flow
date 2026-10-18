# Tasks

## 1. Адаптеры

- [ ] 1.1 `adapters/telegram`: Protocol `TelegramClient`, httpx-реализация (5 методов + `download_file`), фейк; контрактные тесты respx — проверка: pytest
- [ ] 1.2 `adapters/stt`: Protocol `SpeechToText`, OpenAI-совместимая реализация (multipart, таймаут), фейк; тесты на успех, ошибку, пустой текст — проверка: pytest
- [ ] 1.3 `security/redaction.py` базовый: шаблоны токенов (Telegram, GitLab `glpat-`, Anthropic `sk-ant-`, общий `Bearer`), функция `redact(text, extra_values)`; тесты — проверка: pytest (дополняется в `mvp-09`)

## 2. Webhook и приём

- [ ] 2.1 `api/telegram_webhook.py`: секрет, chat_id, дедуп в `telegram_updates`, фоновая обработка, `200` — проверка: тесты сценариев «Неверный секрет», «Чужой чат», «Повторная доставка»
- [ ] 2.2 `telegram/parse.py`: разбор update в `IncomingText | IncomingVoice | ButtonPress` (Pydantic) — проверка: тесты на записанных JSON Telegram
- [ ] 2.3 Дообработка необработанных апдейтов при старте worker (`processed_at is null` и старше 1 мин) — проверка: pytest

## 3. Сервисы

- [ ] 3.1 `services/intake.py`: текст/голос → задача `plan` (`new` → `choosing`) + кнопки всех workspace из конфига; ошибка STT → ответ без задачи — проверка: тесты сервиса с фейками
- [ ] 3.2 `services/intake.choose_workspace`: кнопка → `planning`, повторное нажатие → подсказка — проверка: тесты сценариев «Выбор workspace» и «Повторное нажатие»
- [ ] 3.3 `services/notify.py` + `telegram/render.py`: одно сообщение, дописывание строк, обработка «not modified», redaction — проверка: тест сценария «Два этапа»

## 4. Команды и документация

- [ ] 4.1 `harness-server telegram set-webhook` (URL из `HARNESS_PUBLIC_URL`, секрет из ENV) — проверка: тест CLI с фейком
- [ ] 4.2 ARCHITECTURE.md §5, §9 (ENV STT), docs/deployment.md (шаг set-webhook), README сервера, PLAN.md — проверка: ревью
- [ ] 4.3 Ручная проверка `-m live`: текст и голос из реального чата создают задачу с кнопками — проверка: запись результата в PR

## 5. Память проекта

- [ ] 5.1 `memory_update` по изменённым путям, `memory_annotate` для каждого нового файла, `memory_status` без устаревших файлов

## 6. Хвосты ревью mvp-02

- [ ] 6.1 `settings.py::_check_webhook_secret_format`: минимальная длина `TELEGRAM_WEBHOOK_SECRET` ≥ 32 (как `HARNESS_SECRET_KEY`); Telegram допускает секрет 1–256 символов из `A-Za-z0-9_-` — проверка: тест, секрет из 1 символа отклоняется, секрет из 32 символов принимается
