## ADDED Requirements

### Requirement: Подключение проекта командой agent init

Оператор SHALL подключать проект на машине с агентом командой `agent init {project}`, где `{project}` — id workspace
из `harness.yaml`. Команда MUST создать каталоги харнесса, клон `~/work/{project}`, `~/.harness/mcp.json` и по успеху
поставить маркер готовности проекта. Неизвестный id MUST давать код 2 без побочных эффектов. Команда MUST NOT
требовать `DATABASE_URL` и настроек Telegram.

#### Scenario: Первое подключение проекта

- **WHEN** оператор запускает `agent init demo` на машине с установленными инструментами, а `demo` есть в конфиге
- **THEN** репозиторий склонирован в `~/work/demo`, `~/.harness/mcp.json` записан, маркер `~/.harness/projects/demo.ready` поставлен, код выхода 0

#### Scenario: Неизвестный проект

- **WHEN** оператор запускает `agent init unknown`
- **THEN** код выхода 2, сообщение «неизвестный проект» со списком id workspace, каталоги и клоны не создаются

#### Scenario: Запуск без базы и Telegram

- **WHEN** в окружении есть `HARNESS_CONFIG` и ссылки vault, но нет `DATABASE_URL` и `TELEGRAM_*`
- **THEN** `agent init demo` выполняется без ошибки конфигурации

### Requirement: Идемпотентность agent init

Повторный `agent init {project}` SHALL завершаться кодом 0 без повторного клонирования и без потери данных: клон не
пересоздаётся, `origin` возвращается на адрес из конфига, выполняется fetch, маркер остаётся. Каталог
`~/work/{project}`, который существует и не является git-репозиторием, MUST давать код 1 без изменений в нём.

#### Scenario: Повторный запуск

- **WHEN** `agent init demo` запускается второй раз на подключённом проекте
- **THEN** код выхода 0, клон не пересоздан, выполнены только возврат `origin` и fetch

#### Scenario: Каталог не репозиторий

- **WHEN** `~/work/demo` существует и в нём нет `.git`
- **THEN** код выхода 1 с сообщением, что каталог не является git-репозиторием, содержимое каталога не изменено

### Requirement: Предпосылки проверяются и не устанавливаются

`agent init` SHALL проверять наличие `git`, `node` не ниже 22.13, `npm`, клиента агента, `openspec`, а при включённой
памяти — `memory` и работающего Docker Engine с Compose v2, и печатать найденные версии. Команда MUST NOT
устанавливать инструменты, обращаться к `sudo`, менять пакеты системы и скачивать установочные скрипты. Недостающая
предпосылка MUST давать код выхода 3 и сообщение «нет <программа>» со всеми отсутствующими программами сразу, до
любых изменений в файловой системе.

#### Scenario: Нет Node

- **WHEN** на машине нет `node` или версия ниже 22.13
- **THEN** код выхода 3, сообщение называет `node`, клон и каталоги не создаются, `sudo` не вызывается

#### Scenario: Несколько отсутствующих программ

- **WHEN** нет `openspec` и `git`
- **THEN** одно сообщение перечисляет обе программы

#### Scenario: Память включена, Docker не работает

- **WHEN** в конфиге есть блок `sandbox.memory`, а `docker compose version` завершается ошибкой
- **THEN** код выхода 3, сообщение называет Docker Compose, `memory init` не запускается

### Requirement: Клон с ключом только этого workspace

`agent init` SHALL клонировать и обновлять репозиторий workspace отдельной git-командой с ключом, полученным по
`repo.access_ref` этого workspace из vault. Ключ MUST передаваться только в env команды, MUST NOT попадать в argv,
файлы и вывод, а вывод MUST проходить redaction. Workspace без `repo.access_ref` MUST клонироваться анонимно с
предупреждением. Ошибка vault MUST давать код 1 и причину `vault` до любых изменений.

#### Scenario: Ключ не на диске

- **WHEN** `agent init demo` выполнен для workspace с ключом из vault
- **THEN** поиск значения ключа в `~`, `~/work/demo` и `~/.harness` ничего не находит

#### Scenario: Workspace без ключа

- **WHEN** у workspace нет `repo.access_ref`
- **THEN** клон анонимный, в stderr предупреждение с id workspace, код выхода 0 при публичном репозитории

#### Scenario: Vault недоступен

- **WHEN** vault не отвечает во время `agent init`
- **THEN** код выхода 1 и причина `vault`, клон и маркер не создаются

### Requirement: MCP-конфигурация без секретов

`agent init` SHALL записывать `~/.harness/mcp.json` с литеральными плейсхолдерами адреса и токена `agents-flow`, права
файла 0600. Значения токена и адреса MUST NOT записываться: они приходят в env команды запуска агента.

#### Scenario: Содержимое mcp.json

- **WHEN** `agent init demo` завершён
- **THEN** `~/.harness/mcp.json` содержит `${AGENTS_FLOW_URL}` и `${AGENTS_FLOW_TOKEN}`, а не значения, и доступен только владельцу

### Requirement: Память проекта при инициализации

Когда в конфиге есть блок `sandbox.memory`, `agent init` SHALL добавлять `.memory/` в `.git/info/exclude` клона и
индексировать клон командой `memory init` с ключом embeddings из vault только в env этой команды, затем ставить
маркер `~/.harness/memory/{project}.ready`. Повторный запуск MUST NOT переиндексировать неизменённые файлы. Ключ
embeddings MUST NOT попадать в `.memory/.env` и конфигурацию memory-agent.

#### Scenario: Память подключена

- **WHEN** `agent init demo` выполнен при включённой памяти
- **THEN** маркер `~/.harness/memory/demo.ready` поставлен, `memory status` для клона показывает работающие сервисы

#### Scenario: Память выключена

- **WHEN** блока `sandbox.memory` нет
- **THEN** Docker не проверяется, `memory init` не вызывается, маркера памяти нет

#### Scenario: Ключ embeddings не на диске

- **WHEN** `memory init` выполнен с ключом embeddings из vault
- **THEN** поиск значения ключа в `~` и в каталогах репозиториев ничего не находит

### Requirement: Автор коммитов агента

Агент SHALL запускаться с автором коммитов из `sandbox.git_author` (по умолчанию `agents-flow`) через переменные
окружения процесса, а не через глобальный git config машины.

#### Scenario: Автор коммитов

- **WHEN** агент запускается с настройками по умолчанию
- **THEN** в env процесса агента заданы `GIT_AUTHOR_NAME`, `GIT_AUTHOR_EMAIL` и `GIT_COMMITTER_*`, `git config --global` машины не изменён

### Requirement: Запуск не от root

`agent init` и worker SHALL отказываться работать от имени root (uid 0): код выхода 1 и сообщение «нужен отдельный
пользователь без root» до любых изменений. Домашний каталог пользователя MUST быть единственным местом записи
`agent init`.

#### Scenario: Запуск от root

- **WHEN** `agent init demo` запускается с uid 0
- **THEN** код выхода 1, ничего не создано

### Requirement: Локальное исполнение команд с очищенным окружением

Команды worker на машине агента SHALL выполняться подпроцессами оболочки в окружении, собранном из минимального
набора (`PATH`, `HOME`, `USER`, `LANG`, `LC_*`, `TERM`) и явно переданных переменных команды. Остальные переменные
процесса worker (в том числе `DATABASE_URL`, `HARNESS_SECRET_KEY`, `TELEGRAM_*`, `VAULT_MCP_TOKEN`) MUST NOT попадать
в процессы агента, git и гейтов. Таймаут команды MUST завершать всю группу её процессов.

#### Scenario: Секреты worker не видны агенту

- **WHEN** worker запускает команду `env`, а в env worker заданы `DATABASE_URL` и `TELEGRAM_BOT_TOKEN`
- **THEN** вывод не содержит этих переменных, но содержит переданные команде `AGENTS_FLOW_TOKEN` и `GIT_AUTHOR_NAME`

#### Scenario: Таймаут команды

- **WHEN** команда превышает `timeout_s`
- **THEN** группа процессов команды остановлена, вызов завершается ошибкой `timeout`, процессы не остаются

#### Scenario: Секрет не в списке процессов

- **WHEN** команда запускается со значением секрета в переданных переменных
- **THEN** значение не встречается в аргументах процесса

### Requirement: Удалённые настройки Novita и установки отклоняются

Конфиг и ENV SHALL отклонять удалённые настройки с понятным сообщением, а не игнорировать их молча: поля
`sandbox.claude_code_version`, `sandbox.openspec_version`, `sandbox.memory.repo`, `sandbox.memory.ref` в `harness.yaml`
MUST давать ошибку загрузки конфигурации, называющую поле и причину («версии и установка — на машине владельца»).
Переменные `NOVITA_API_KEY` и `NOVITA_DOMAIN` MUST NOT читаться; их наличие в ENV не влияет на работу.

#### Scenario: Старый конфиг

- **WHEN** `harness.yaml` содержит `sandbox.claude_code_version`
- **THEN** сервер и `agent init` не стартуют, сообщение называет `sandbox.claude_code_version`

#### Scenario: Лишняя ENV

- **WHEN** в окружении worker остался `NOVITA_API_KEY`
- **THEN** значение не читается и не попадает в лог, worker работает с локальной машиной
