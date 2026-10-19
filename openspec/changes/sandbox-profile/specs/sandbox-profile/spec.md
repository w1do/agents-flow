## ADDED Requirements

### Requirement: Bootstrap без участия владельца

Bootstrap SHALL готовить песочницу одной командой: Node не ниже 22.13, `claude` и `openspec` закреплённых версий,
доступ к GitLab по ключу, клоны репозиториев workspace, пустые каталоги `~/.claude/skills` и `~/.claude/agents`, а при
включённой памяти — Docker Engine с Compose v2. Bootstrap MUST быть идемпотентным и MUST NOT ставить языки и стек
проектов.

#### Scenario: Повторный bootstrap с памятью

- **WHEN** bootstrap с включённой памятью запускается второй раз на подготовленной песочнице
- **THEN** скрипт завершается с кодом 0, Node, Docker и npm-пакеты не переустанавливаются, memory-agent с тем же
  sha не переустанавливается, репозитории не клонируются заново

#### Scenario: Нет sudo и старый Node

- **WHEN** в песочнице Node ниже 22.13 и нет `sudo`
- **THEN** bootstrap завершается с кодом 1 и сообщением, что нужен Node 22.13 или sudo

### Requirement: Установка memory-agent

Когда память включена, bootstrap SHALL собирать memory-agent из GitHub-репозитория по полному sha коммита от имени
пользователя песочницы (зависимости по lockfile) и делать его команду `memory` доступной через симлинк. memory-agent
MUST NOT ставиться по имени из реестра npm, а ссылка на него MUST быть полным sha из 40 шестнадцатеричных символов
(не тег, не ветка).

#### Scenario: Смена коммита memory-agent

- **WHEN** в настройках памяти указан другой sha коммита и bootstrap запускается снова
- **THEN** memory-agent переустанавливается из GitHub на этот коммит

#### Scenario: Ссылка на memory-agent не sha

- **WHEN** в настройках памяти или в аргументах bootstrap ссылка на memory-agent — тег, ветка или короткий sha
- **THEN** конфигурация не загружается, а скрипт bootstrap завершается с кодом 2 до любых установок

### Requirement: Ключи из vault

Сервер SHALL получать ключи по ссылкам `vault:<project>/<service>/<name>` из настроек через MCP-адаптер vault без
участия владельца. Ключи MUST передаваться в песочницу только в окружении команд и MUST NOT записываться в файлы
песочницы, включая конфигурацию memory-agent. Без ссылки на ключ GitLab сервер MUST использовать ENV `GITLAB_TOKEN`.

#### Scenario: Ключ embeddings не на диске

- **WHEN** bootstrap выполнил `memory init` с ключом embeddings из vault
- **THEN** поиск значения ключа в `~` и в каталогах репозиториев ничего не находит

#### Scenario: Vault недоступен при bootstrap

- **WHEN** vault не отвечает во время bootstrap
- **THEN** bootstrap завершается с кодом 1 и причиной `vault`, статус песочницы не меняется

### Requirement: Память проекта в песочнице

Когда память включена, система SHALL индексировать клон каждого workspace при bootstrap и инкрементально обновлять
индекс при активации задачи. Сбой обновления памяти при активации MUST NOT переводить задачу в `error`.

#### Scenario: Сбой обновления памяти

- **WHEN** `memory sync` при активации завершается с ошибкой
- **THEN** в лог пишется предупреждение, агент запускается

#### Scenario: Память работает

- **WHEN** bootstrap с памятью завершён
- **THEN** `memory status` для клона workspace показывает работающие Qdrant и Typesense
