# Proposal: mvp-04-telegram-intake

## Why

Telegram — единственный вход MVP (ТЗ §2 п.1, §5). Нужно принять текст и голос только от владельца, не создать
дублей при повторной доставке, создать задачу и дать выбрать проект кнопкой. Сообщение о задаче одно и
обновляется по этапам (ТЗ §6, вопрос 9).

## What Changes

- `POST /telegram/webhook`: проверка `X-Telegram-Bot-Api-Secret-Token`, фильтр `chat_id == TELEGRAM_CHAT_ID`,
  дедуп по `update_id` и `callback_query.id` (A4), быстрый ответ `200`.
- Адаптер `adapters/telegram` (httpx): `send_message`, `edit_message_text`, `answer_callback_query`, `get_file`,
  `download_file`, `set_webhook` + фейк.
- Адаптер `adapters/stt` (`SpeechToText`): OpenAI-совместимый `/audio/transcriptions`, URL/ключ/модель из ENV (D-05) + фейк.
- `services/intake.py`: текст или расшифровка голоса → задача `plan` в `new` → `choosing` + кнопки со **всеми**
  workspace (ранжирование Polza добавит `mvp-05`). Нажатие кнопки → `planning`.
- `services/notify.py` + `telegram/render.py`: одно сообщение на задачу, этапы дописываются строками
  `Задача [<название>] (<этап>)`; хранится в `telegram_messages`.
- CLI `harness-server telegram set-webhook`.

## Capabilities

### New Capabilities

- `telegram-bot`: приём сообщений владельца, кнопки выбора проекта, одно обновляемое сообщение задачи.
- `speech-to-text`: перевод голосового сообщения в текст.

### Modified Capabilities

Нет.

## Impact

- ENV: `TELEGRAM_*`, `STT_PROVIDER`, `STT_API_URL`, `STT_API_KEY`, `STT_MODEL` (ARCHITECTURE.md §9).
- Зависит от: `mvp-03-task-store`.
- Ссылки: ТЗ §5 шаги 1–4, §6 (MVP-часть), §7, §16.1 A4, C6 (только chat_id).

## Не входит

Классы команд и ранжирование (`mvp-05`), «Другой проект» (`telegram-other-project`), кнопки «Остановить/Повторить»
(`telegram-full-stages`), конвертация и длинные голосовые (`voice-robustness`).
