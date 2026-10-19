# Novita Agent Sandbox: результаты спайка mvp-01

Спайк проверяет поведение песочницы Novita до начала `mvp-06-sandbox-runtime`: exec, файлы, пауза
и возобновление, продление и истечение таймаута, установку Claude Code. Основание: решение
[D-16](decisions.md) и риск A1 ТЗ (`docs/tz/tz-v5.md`). Вопросы 5–7 ТЗ из
[open-questions.md](open-questions.md): цена паузы, кастомные образы, продление сессии при таймауте.
Результаты питают адаптер `SandboxProvider` (exec, write_file, read_file, pause, resume,
extend_timeout) в `mvp-06-sandbox-runtime`.

Статус: живые запуски выполнены 2026-10-18 (SDK `novita_sandbox==2.1.1`, шаблон по умолчанию,
`@anthropic-ai/claude-code@2.1.292`). Итоги и выводы ниже. Всё, что не подтверждено запуском, помечено
отдельно: в таблице возможностей и в разделе «Не проверено живьём». Финальный полный прогон после
исправлений — «Запуск 4».

## Как запускать спайк

```bash
export NOVITA_API_KEY=...            # обязательна; ключ читает SDK, скрипт его не печатает
export CLAUDE_CODE_OAUTH_TOKEN=...   # необязательна; токен подписки (claude setup-token)
export NOVITA_DOMAIN=...             # необязательна; по умолчанию us-phx-1.sandbox.novita.ai
export HARNESS_PUBLIC_URL=...        # необязательна; в выводе и отчёте только scheme://host[:port]

uv run tools/spikes/novita_check.py --report <путь>.json
```

Без uv: `python3 -m venv .venv && .venv/bin/pip install novita_sandbox==2.1.1`, затем
`.venv/bin/python tools/spikes/novita_check.py`.

Офлайн-проверки без ключа и без SDK: `python3 tools/spikes/novita_check.py --self-test` (печатает
`self-test: OK`). SDK импортируется только после разбора аргументов и проверки ключа.

Флаги:

- `--claude-version` — версия `@anthropic-ai/claude-code`, по умолчанию `2.1.292`.
- `--report PATH` — сохранить строки итогов и детали в JSON, права файла 0600. По умолчанию не пишется.
- `--only {expire,claude}` — повторяемый флаг. `expire` — только короткая песочница для истечения
  таймаута. `claude` — основная песочница, установка claude (2.1) и шаги 2.2. Без флага выполняются все шаги.
- `--skip-claude` — пропустить шаги Claude Code (2.1 и 2.2).
- `--skip-timeout` — пропустить шаги продления и истечения таймаута (1.4).
- `--short-timeout SEC` — таймаут короткой песочницы, по умолчанию 30 с.
- `--template` — шаблон песочницы, по умолчанию шаблон SDK.
- `--self-test` — офлайн-проверки маскировки, разбора stream-json и логики флагов.

Код возврата: 0 — без FAIL; 1 — есть хотя бы один FAIL; 2 — не задан `NOVITA_API_KEY`.
SIGTERM обрабатывается как завершение с `finally`, поэтому cleanup всё равно убирает созданные песочницы.

Порядок шагов: основная песочница (exec, пауза, продление, claude, HTTPS), затем её `kill`, и только потом
короткая песочница для истечения таймаута. Причина: квота vCPU команды общая (см. ограничения ниже).

## Вызовы SDK

Источник: интроспекция пакета `novita_sandbox==2.1.1`. Вызовы подтверждены запусками, кроме
помеченных в колонке примечаний.

| Задача | Вызов | Примечания |
|---|---|---|
| Импорт | `from novita_sandbox.core import Sandbox, SandboxQuery, SandboxState, CommandExitException` | Импорт ленивый, внутри функций. `Sandbox` — класс песочницы. `CodeInterpreterSandbox` и `DesktopSandbox` — другие классы, не нужны |
| Ключ и домен | ENV `NOVITA_API_KEY`, `NOVITA_DOMAIN` | Читаются SDK. По умолчанию `us-phx-1.sandbox.novita.ai` |
| Создание | `Sandbox.create(template=None, timeout=..., metadata={...}, envs=..., lifecycle=...)` | `timeout` в секундах, по умолчанию 300 (по docstring). `template=None` — шаблон SDK (node и npm есть) |
| Exec переднего плана | `sbx.commands.run(cmd, envs=..., timeout=60)` → `CommandResult` | Поля `stdout`, `stderr`, `exit_code`, `error`. `timeout` — таймаут соединения в секундах, `0` без лимита |
| Ненулевой код | исключение `CommandExitException` | Подтверждено: `exit_code=3`, `stderr` заполнен. Подкласс `SandboxException`, это исключение, а не возврат кода |
| Фоновый процесс | `sbx.commands.run("nohup ... &  echo $! > pid")` | Подтверждено. `background=True` возвращает `CommandHandle` с `pid`, но handle теряется при рестарте worker, поэтому mvp-06 пишет pid-файл (D-35) |
| Запись файла | `sbx.files.write(path, data)` → `WriteInfo` | Подтверждено: файл читается обратно после resume |
| Чтение файла | `sbx.files.read(path)` → `str` | Подтверждено. Нет файла → исключение, поэтому чтение в проверках обёрнуто |
| Пауза | `sbx.pause()` → `None` | Подтверждено. `beta_pause()` — устаревший алиас. Docstring врёт про «возвращает Sandbox ID» |
| Возобновление | `Sandbox.connect(sandbox_id, timeout=...)` | Подтверждено: `resume_s=0.2`. Автоматически возобновляет paused |
| Продление | `sbx.set_timeout(seconds)` | Подтверждено: `end_at` стал `now + seconds`, отсчёт от момента вызова (запуск 1). Уменьшение и лимиты по docstring SDK, живьём не проверено |
| Информация | `sbx.get_info()` → `SandboxInfo` | Подтверждено: поле `end_at` (datetime), `state`, `metadata` |
| Удаление | `Sandbox.kill(sandbox_id)` → `bool` | Подтверждено: cleanup возвращает `remaining=0` |
| Список | `Sandbox.list(query=SandboxQuery(metadata=..., state=[...]))` | Подтверждено. Пагинация: `while p.has_next: p.next_items()` |
| Поведение по таймауту | `create(lifecycle={"on_timeout": "kill" \| "pause", "auto_resume": bool})` | `kill` по умолчанию подтверждён запуском 2. Вариант `pause` не проверен живьём |
| Жива ли | `sbx.is_running()` → `bool` | Не проверено живьём: в спайке не используется |

Расхождения с отчётом researcher: имена и сигнатуры совпали. Добавлены `lifecycle` как рекомендуемый
способ задать поведение по таймауту и устаревший `beta_pause`.

## Результаты запуска

Все строки ниже получены 2026-10-18 с SDK `novita_sandbox==2.1.1`, шаблоном по умолчанию и
`claude 2.1.292`. Конкретные id песочниц в документе не приводятся. Запуски 1–3 сделаны на скрипте
до исправлений: в запуске 1 шаг `timeout expire` шёл до `kill` основной песочницы.

**Запуск 1 (полный, порядок до исправлений: expire до kill основной)**

```text
exec: OK
exec nonzero: raises CommandExitException exit_code=3 stderr=OK
pause/resume: files=OK process=OK pause_s=0.4 resume_s=0.2
timeout extend: OK EXTENDED end_at=2026-10-18 08:20:11 -> 2026-10-18 08:25:11 requested=1200s
timeout expire: FAIL RateLimitException: 429 ... exceed your team's total vCPU limit (10) ...
claude: version=2.1.292 max-turns=no bare=yes output-format=yes
stream-json: SKIPPED (no CLAUDE_CODE_OAUTH_TOKEN)
https: url=https://example.com code=200
cleanup: OK remaining=0
```

Причина 429: квота команды 10 vCPU. Рабочая песочница оркестратора занимала 8 vCPU, спайковая основная
песочница 2 vCPU, короткая не создалась. После этого скрипт переупорядочен: основная песочница убивается
до создания короткой.

**Запуск 2 (`--only expire`, `--short-timeout 30`, ожидание 45 с)**

```text
timeout expire: killed exec=TimeoutException: The sandbox was not found ... likely due to sandbox timeout list_state=absent connect=SandboxNotFoundException
```

Вывод: по умолчанию (`lifecycle on_timeout=kill`) песочница по таймауту уничтожается. Её нет ни в exec,
ни в `connect`, ни в `Sandbox.list`. Запуск сделан до правила «killed только при absent или list=error».
Здесь list отвечал `absent`, поэтому вывод остаётся тем же.

**Запуск 3 (`--only claude`, авторизация подпиской через `CLAUDE_CODE_OAUTH_TOKEN` в envs команды,
без `ANTHROPIC_API_KEY`, без `--bare`)**

```text
exec: OK
claude: version=2.1.292 max-turns=no(hidden in --help) bare=yes output-format=yes
stream-json: events=4 messages=1 result=yes reconcile=OK input_sum=16289 result_input=16289 output_result=4 output_sum=4 max_turns_accepted=yes exit=0
stream-json no-verbose: FAILS exit_code=1 stderr_mentions_verbose=yes
main sandbox: kill=OK
```

Node и npm в шаблоне по умолчанию есть, `npm install -g @anthropic-ai/claude-code@2.1.292` прошёл.
`max_turns_accepted=yes` в этом запуске означает только то, что флаг не отвергнут и ход завершился с
`result`. Соблюдение лимита ходов (`error_max_turns`) не проверялось.

Примеры строк `stream-json` (санитизированы скриптом, текст ответа и служебные поля убраны):

```json
{"type":"system","subtype":"init","model":"claude-sonnet-5-5"}
{"type":"assistant","message":{"id":"msg_011Cg9MxFsgiNDZXWYv35wrf","model":"claude-sonnet-5-5","usage":{"input_tokens":2,"cache_creation_input_tokens":5413,"cache_read_input_tokens":10874,"output_tokens":4,"service_tier":"standard"},"stop_reason":null}}
{"type":"rate_limit_event"}
{"type":"result","subtype":"success","is_error":false,"num_turns":1,"total_cost_usd":0.0238708,"usage":{"input_tokens":2,"cache_creation_input_tokens":5413,"cache_read_input_tokens":10874,"output_tokens":4,"iterations":[{"type":"message","input_tokens":2,"output_tokens":4}]}}
```

Наблюдения по строкам: в `result` есть `usage.iterations` и `total_cost_usd`. Событие `rate_limit_event`
появилось в этом запуске. Его причина не установлена (см. «Не проверено живьём»). Модель по умолчанию
у подписки: `claude-sonnet-5-5`.

Сверка usage на одном ходе: `input_sum` = `input_tokens + cache_creation_input_tokens + cache_read_input_tokens`
по уникальным `message.id` = 2 + 5413 + 10874 = 16289, совпадает с `result`. Это один ход и одно сообщение,
поэтому дедупликация по `message.id` здесь не проверялась.

**Запуск 4 (финальный, полный порядок после исправлений)**

Полный прогон без `--only`, 2026-10-18 ~08:22 UTC, `CLAUDE_CODE_OAUTH_TOKEN` подписки, без `ANTHROPIC_API_KEY`.
Основная песочница удаляется до проверки expire, поэтому лимит 10 vCPU не мешает. Код выхода скрипта 0,
файл `--report` создан с правами `600`, значений секретов в нём нет.

```text
exec: OK
exec nonzero: raises CommandExitException exit_code=3 stderr=OK
pause/resume: files=OK process=OK pause_s=0.4 resume_s=0.2
timeout extend: OK EXTENDED end_at=08:37:31 -> 08:42:31 (UTC) requested=1200s
claude: version=2.1.292 max-turns=no(hidden in --help) bare=yes output-format=yes
stream-json: events=4 messages=1 result=yes result_subtype=success reconcile=OK input_sum=16289 result_input=16289 output_result=4 output_sum=4 max_turns_accepted=yes exit=0
stream-json no-verbose: FAILS exit_code=1 stderr_mentions_verbose=yes
https: url=https://example.com code=200
main sandbox: kill=OK
timeout expire: killed exec=TimeoutException (sandbox not found) list_state=absent short_timeout=30s waited=45s connect=SandboxNotFoundException
cleanup: OK remaining=0
```

Результаты запусков 1–3 повторились, сирот (`cleanup: WARN orphan`) нет.

## Таблица возможностей

| Возможность | Подтверждено | Как вызывать | Ограничения |
|---|---|---|---|
| Создание песочницы | да | `Sandbox.create(timeout=900, metadata={...})` | Квота команды 10 vCPU, см. ниже. Шаблон по умолчанию 2 vCPU |
| exec и код возврата | да | `sbx.commands.run(cmd, timeout=60)` | `echo` → `exit_code=0`, `stdout` ок |
| Ненулевой код | да | ловить `CommandExitException` | `exit_code=3`, `stderr` заполнен. Исключение, не возврат |
| Фоновый процесс | да | `nohup cmd >/dev/null 2>&1 & echo $! > pid` через обычный `run` | Вывод должен быть перенаправлен, иначе `run` ждёт |
| Запись и чтение файла | да | `sbx.files.write(path, data)`, `sbx.files.read(path)` | Чтение несуществующего файла бросает исключение |
| Пауза | да | `sbx.pause()` | `pause_s≈0.4` на маленькой песочнице, один цикл. Не `beta_pause`, он устарел |
| Возобновление | да | `Sandbox.connect(sandbox_id, timeout=...)` | `resume_s≈0.2`, один цикл |
| Сохранение файлов при паузе | да | по записи и чтению после connect | Проверено в запуске 1 (один короткий цикл). Длительное хранение не проверено |
| Сохранение фонового процесса при паузе | да | pid-файл и `kill -0` после connect | `process=OK` в запуске 1 (один короткий цикл). Противоречие overview и legacy-persistence закрыто в пользу legacy-persistence |
| Продление `set_timeout` | да | `sbx.set_timeout(1200)` | `end_at = now + seconds`, отсчёт от вызова (запуски 1 и 4: песочница создана с `timeout=900`, `set_timeout(1200)` вызван сразу после создания, поэтому `end_at` сдвинулся на 1200 − 900 = 300 с). Уменьшение, максимум 86 400 с (Pro) и 3 600 с (Hobby) по docstring SDK, живьём не проверено |
| Истечение таймаута по умолчанию | да | `create(timeout=N)` без lifecycle | Песочница уничтожается: exec, connect и list её не видят (запуск 2). Данные теряются |
| `lifecycle on_timeout=pause` | нет | `create(lifecycle={"on_timeout": "pause", "auto_resume": ...})` | По SDK и документации. Живьём не проверено |
| `kill` | да | `Sandbox.kill(sandbox_id)` | Возвращает `remaining=0` в cleanup |
| `Sandbox.list` с фильтром | да | `SandboxQuery(metadata=..., state=[...])` | Фильтр по metadata работает. Нужен для отделения своих песочниц от чужих |
| Исходящий HTTPS из песочницы | да | `curl` внутри песочницы | `example.com` → 200. Проверен только example.com, `HARNESS_PUBLIC_URL` не задавался |
| node и npm в шаблоне по умолчанию | да | `node -v`, `npm -v` | Установка claude через npm прошла без кастомного образа |
| Лимит vCPU команды | да | ошибка 429 при create | Квота команды 10 vCPU. Занято рабочей песочницей оркестратора 8 vCPU, спайковой 2 vCPU. Для задач свободно примерно 2 vCPU |
| Установка claude | да | `npm install -g @anthropic-ai/claude-code@2.1.292` | Прошла в запуске 3 |
| `--max-turns` | частично | `claude -p ... --max-turns 1` | Не виден в `claude --help` (2.1.292 и 2.1.302 локально), но задокументирован в cli-reference («Exits with an error when the limit is reached») и принимается: `max_turns_accepted=yes`, exit 0. Соблюдение лимита (`error_max_turns`) живьём не проверено |
| `--bare` | частично | флаг виден в `--help` | По документации `--bare` не читает OAuth-токен. Живьём с токеном не проверено. Спайк запускает без `--bare` |
| `stream-json` | частично | `claude -p ... --output-format stream-json --verbose` | Один ход: событий 4, сообщений 1, `result=yes`. Многоходовой вывод не проверен |
| `stream-json` без `--verbose` | да, падает | `--output-format stream-json` без `--verbose` | `exit_code=1`, stderr упоминает `verbose`. `--verbose` обязателен |
| Сверка usage | частично | сумма input по уникальным `message.id`, сверка с `result.usage` | Один ход: `reconcile=OK`, 16289 = 16289. Дедупликация на нескольких сообщениях не проверена |
| Авторизация подпиской | да | `CLAUDE_CODE_OAUTH_TOKEN` в envs команды | Работает, ключ `ANTHROPIC_API_KEY` в env не задавался. Модель по умолчанию у подписки `claude-sonnet-5-5` |
| Цена паузы (вопрос 5) | частично | по документации | CPU и RAM на паузе не тарифицируются, тарифицируется хранение. Ставка не найдена. Не проверено |
| Кастомные образы (вопрос 6) | нет | по документации: `novita-sandbox-cli template create --dockerfile`, SDK `template.build` | Живьём не собирали |
| Продление сессии (вопрос 7) | да | `set_timeout` | Закрыт: см. D-19 |

## Выводы для mvp-06

- **Пауза сохраняет файлы и фоновый процесс.** Проверено в одном коротком цикле `pause` → `connect` (запуск 1,
  секунды паузы). Длительное хранение паузы не проверено. Изменений архитектуры песочницы по итогам спайка не
  требуется. Задача 3.3 выполнена: устаревший риск «пауза не сохраняет процессы» и креды с `ANTHROPIC_API_KEY`
  исправлены в [`openspec/changes/archive/2026-10-19-mvp-06-sandbox-runtime/design.md`](../openspec/changes/archive/2026-10-19-mvp-06-sandbox-runtime/design.md)
  (Decisions, Risks / Trade-offs).
- **Таймаут по умолчанию уничтожает песочницу.** Адаптер обязан либо продлевать `set_timeout` до истечения
  (отсчёт от вызова), либо задавать `lifecycle on_timeout=pause`. Вариант `pause` ещё не проверен живьём.
- **Ненулевой код возврата — исключение.** Адаптер ловит `CommandExitException` и берёт `exit_code` и `stderr`
  из исключения.
- **Лимит vCPU команды.** Квота 10 vCPU общая. Рабочая песочница оркестратора занимает 8, остаётся ~2
  на задачи, пока она работает. Шаблон по умолчанию = 2 vCPU. `sandbox-pool` должен учитывать квоту.
  Id рабочей песочницы сюда не записывается.
- **Claude Code.** Запускать `claude -p` без `--bare`, если авторизация подпиской через OAuth-токен.
  `ANTHROPIC_API_KEY` в песочнице не задавать: по документации Claude Code он имеет приоритет над токеном
  (порядок приоритета в authentication). Спайком это не проверялось. Токен передавать только в envs команды.
- **stream-json.** Нужен `--verbose` (подтверждено). Output токены брать из `result.usage` (правило по
  документации, на одном ходе совпало). Дедупликация по `message.id` и плейсхолдер в assistant-событиях
  не проверены на многоходовом выводе. Эту проверку переносим в live-тест `mvp-06`: многоходовой запуск с tool-use.

## Claude Code в песочнице

- **Версия.** `@anthropic-ai/claude-code@2.1.292` (stable), `npm install -g`. Node и npm в шаблоне есть.
- **Авторизация.** Подписка через `CLAUDE_CODE_OAUTH_TOKEN`. Токен передаётся только в env конкретной команды
  песочницы и в файлы не пишется.
- **Получение токена (практическая заметка для bootstrap).** `claude setup-token` открывает браузер и показывает
  код вида `<код>#<state>`. Это не токен. Код вставляется обратно в терминал, после чего setup-token выводит
  токен с префиксом `sk-ant-oat01-`. Срок действия около года (по документации, не проверено спайком).
- **Ограничение `--bare`.** По документации Claude Code (`code.claude.com/docs/en/authentication`) `--bare`
  не читает OAuth-токен. Поэтому запуск без `--bare`. Живьём с токеном `--bare` не проверяли.
- **Приоритет `ANTHROPIC_API_KEY`.** По документации Claude Code этот ключ имеет приоритет над OAuth-токеном.
  Поэтому в песочнице он не задаётся. Спайком не проверялось.
- **stream-json.** Предположение спайка: одно сообщение может дать несколько событий `assistant` с одним
  `message.id`, поэтому дедуплицировать по `message.id` и брать последнее вхождение. Исследование mvp-06: в Python SDK
  `message_id` описан как общий для всех сообщений одного хода, поэтому итог берётся из `result.usage` (D-37), а
  поведение `message.id` фиксирует live-тест mvp-06. Сумма input по уникальным id
  сверяется с `usage` события `result`. Подтверждено на одном ходе, многоходовой вывод не проверен.
- **Флаги.** `--output-format stream-json` требует `--verbose` (подтверждено). `--max-turns` не виден в
  `--help`, но задокументирован в cli-reference; соблюдение лимита не проверено.
- **Изоляция.** Без `--bare` режим `-p` выполняет hooks из `.claude/settings.json` и подключает `.mcp.json` рабочего
  каталога без диалога доверия (документация headless). Запуск — с `--setting-sources user` и `--strict-mcp-config` (D-36).
- **Приоритет auth** (документация authentication): облачный провайдер, `ANTHROPIC_AUTH_TOKEN`, `ANTHROPIC_API_KEY`,
  `apiKeyHelper`, `CLAUDE_CODE_OAUTH_TOKEN`. `run.sh` делает `unset` первых двух (D-37).
- **Исходящий трафик.** Novita поддерживает `network={allow_out, deny_out}` при создании и `set_network` (IP и CIDR;
  доменные имена в core SDK не подтверждены). Рекомендация — в `docs/deployment.md` (D-38).

## Не проверено живьём

- Цена паузы: ставка хранения не найдена, данные только по документации.
- Кастомные образы: сборка шаблонов не запускалась.
- Длительное хранение паузы и поведение при паузе дольше одного короткого цикла.
- Максимум и уменьшение `set_timeout`: по docstring SDK.
- `lifecycle on_timeout=pause` и `auto_resume`.
- `--bare` с OAuth-токеном.
- Приоритет `ANTHROPIC_API_KEY` над `CLAUDE_CODE_OAUTH_TOKEN`: по документации Claude Code.
- Срок действия токена `setup-token` (около года): по документации.
- Причина события `rate_limit_event` в stream-json. Гипотеза: лимиты подписки. По документации у API-ключа
  такого события нет. Не проверено.
- Соблюдение `--max-turns` (ошибка `error_max_turns`).
- Многоходовой stream-json с tool-use: дедупликация по `message.id`, плейсхолдер `output_tokens` в assistant.
  Перенесено в live-тест `mvp-06`.
- Доступ по `HARNESS_PUBLIC_URL` (проверен только `example.com`).

## Источники

Ссылки перенесены из отчёта researcher. В этом спайке страницы не открывались, поэтому утверждения,
которые от них зависят, помечены как «по документации», если их не подтвердил запуск.

- https://docs.novita.ai/guides/sandbox-overview
- https://docs.novita.ai/guides/sandbox-lifecycle
- https://docs.novita.ai/guides/sandbox-commands-background
- https://docs.novita.ai/guides/sandbox-legacy-persistence
- https://docs.novita.ai/guides/sandbox-your-first-agent-sandbox
- https://novita.ai/docs/guides/sandbox-template-build-operations
- https://novita.ai/docs/guides/sandbox-auto-resume
- https://novita.ai/docs/guides/sandbox-idle-timeout
- https://pypi.org/project/novita-sandbox/
- https://code.claude.com/docs/en/authentication
- https://code.claude.com/docs/en/headless
- https://code.claude.com/docs/en/cli-reference
- https://code.claude.com/docs/en/agent-sdk/cost-tracking
- https://www.npmjs.com/package/@anthropic-ai/claude-code

**Противоречие источников о паузе** (overview и legacy-persistence по-разному описывают процессы при паузе)
закрыто запуском 1 в одном коротком цикле: процессы сохранились. Вывод совпадает с legacy-persistence.
Длительное хранение остаётся непроверенным.
