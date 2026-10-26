## MODIFIED Requirements

### Requirement: Ключи из vault

Сервер и команда `agent init` SHALL получать ключи по ссылкам `vault:<project>/<service>/<name>` из настроек через
MCP-адаптер vault без участия владельца. Ключ репозитория MUST браться по ссылке `repo.access_ref` своего workspace;
ENV `GITLAB_TOKEN` MUST NOT использоваться. Ключи MUST передаваться на машину только в окружении команд и MUST NOT
записываться в файлы машины, включая конфигурацию memory-agent.

#### Scenario: Ключ embeddings не на диске

- **WHEN** `agent init` выполнил `memory init` с ключом embeddings из vault
- **THEN** поиск значения ключа в `~` и в каталогах репозиториев ничего не находит

#### Scenario: Vault недоступен при bootstrap

- **WHEN** vault не отвечает во время подготовки проекта командой `agent init` (сценарий сохраняет прежнее имя)
- **THEN** команда завершается с кодом 1 и причиной `vault`, клоны и маркеры не создаются

#### Scenario: Ключ из ENV не используется

- **WHEN** в ENV задан `GITLAB_TOKEN`, а у workspace нет `repo.access_ref`
- **THEN** значение из ENV не уходит на машину, клон этого workspace анонимный

### Requirement: Память проекта в песочнице

Когда память включена (задан блок `sandbox.memory`), система SHALL индексировать клон workspace при `agent init` и
инкрементально обновлять индекс при активации задачи. Установку memory-agent и запуск Docker выполняет владелец
машины: активация MUST NOT устанавливать memory-agent и MUST NOT запускать демон Docker. Сбой обновления памяти при
активации MUST NOT переводить задачу в `error`.

#### Scenario: Сбой обновления памяти

- **WHEN** `memory sync` при активации завершается с ошибкой
- **THEN** в лог пишется предупреждение, агент запускается

#### Scenario: Память работает

- **WHEN** `agent init` с памятью завершён
- **THEN** `memory status` для клона workspace показывает работающие Qdrant и Typesense

#### Scenario: Демон Docker остановлен

- **WHEN** при активации Docker не отвечает и `memory sync` завершается ошибкой
- **THEN** предупреждение в лог, демон не запускается харнессом, агент запускается

### Requirement: Авторизация git по workspace

Git на машине SHALL авторизоваться ключом workspace заголовком `Authorization: Basic` в окружении одной
git-команды, привязанным к префиксу адреса репозитория этого workspace (`<base_url>/<project>.git/`), с выключенными
редиректами. Имя пользователя Basic MUST быть `oauth2` для GitLab и `x-access-token` для GitHub. Ключ и заголовок
MUST NOT попадать в argv и файлы. Перед fetch задачи `origin` клона MUST возвращаться на адрес из конфига.

#### Scenario: Два провайдера в одной песочнице

- **WHEN** `agent init` клонирует workspace GitHub с ключом и workspace GitLab с другим ключом (двумя запусками)
- **THEN** клон GitHub получает заголовок с `x-access-token` только на префикс своего репозитория, клон GitLab —
  заголовок с `oauth2` только на префикс своего, ни один ключ не уходит в чужой репозиторий

#### Scenario: Агент сменил origin

- **WHEN** агент изменил адрес `origin` клона на другой репозиторий того же хоста
- **THEN** активация следующей задачи возвращает `origin` на адрес из конфига до fetch, ключ на другой адрес не уходит

## REMOVED Requirements

### Requirement: Bootstrap без участия владельца

**Reason**: Харнесс больше не готовит машину: Node, клиент агента, `openspec`, Docker и memory-agent ставит владелец
один раз. Автор коммитов агента перенесён в `agent-machine`, подключение проекта — в `agent init`.

**Migration**: Поставить инструменты на машину вручную; выполнить `agent init <project>` для каждого workspace.

### Requirement: Установка memory-agent

**Reason**: Установка memory-agent по sha коммита выполнялась bootstrap; теперь memory-agent ставится владельцем,
поля `sandbox.memory.repo` и `sandbox.memory.ref` удалены.

**Migration**: Собрать и установить memory-agent на машине вручную, убрать `repo` и `ref` из `sandbox.memory`,
оставив при необходимости `embedding_ref`.

### Requirement: Bootstrap без ключей в установках

**Reason**: Скрипт bootstrap и его фазы `setup` и `memory` удалены; установок харнесс не выполняет, поэтому защита
фазы установок от ключей в env не нужна.

**Migration**: Нет. Ключ передаётся только в env команды `agent init` (клон, `memory init`).

### Requirement: Клоны bootstrap делает сервер

**Reason**: Клоны и fetch при подключении проекта делает `agent init` (требование о ключе только своего workspace
перенесено в `agent-machine`); скрипта bootstrap, который не должен клонировать, больше нет.

**Migration**: Использовать `agent init <project>`; аргумент `--gitlab-url` и прочие аргументы bootstrap исчезли вместе со скриптом.

### Requirement: Скрипт bootstrap в образе сервера

**Reason**: `deploy/sandbox/bootstrap.sh` и команда `harness-server sandbox bootstrap` удалены, образ не содержит
`deploy/sandbox`.

**Migration**: Команда `agent` ставится вместе с пакетом `harness-server` на машине агента (`uv sync` или `uv tool install`).
