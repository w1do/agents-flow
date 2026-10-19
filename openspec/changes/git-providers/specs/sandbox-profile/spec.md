## MODIFIED Requirements

### Requirement: Bootstrap без участия владельца

Bootstrap SHALL готовить песочницу одной командой: Node не ниже 22.13, `claude` и `openspec` закреплённых версий,
доступ к репозиторию каждого workspace по ключу этого workspace (GitHub или GitLab), клоны репозиториев workspace,
пустые каталоги `~/.claude/skills` и `~/.claude/agents`, а при включённой памяти — Docker Engine с Compose v2.
Workspace без ключа MUST клонироваться анонимно. Bootstrap MUST быть идемпотентным и MUST NOT ставить языки и стек
проектов.

#### Scenario: Повторный bootstrap с памятью

- **WHEN** bootstrap с включённой памятью запускается второй раз на подготовленной песочнице
- **THEN** скрипт завершается с кодом 0, Node, Docker и npm-пакеты не переустанавливаются, memory-agent с тем же
  sha не переустанавливается, репозитории не клонируются заново

#### Scenario: Автор коммитов

- **WHEN** агент запускается с автором из `sandbox.git_author` (по умолчанию `agents-flow`)
- **THEN** в env процесса агента заданы `GIT_AUTHOR_NAME`/`GIT_AUTHOR_EMAIL` и `GIT_COMMITTER_*`, а не глобальный git config

#### Scenario: Нет sudo и старый Node

- **WHEN** в песочнице Node ниже 22.13 и нет `sudo`
- **THEN** bootstrap завершается с кодом 1 и сообщением, что нужен Node 22.13 или sudo

#### Scenario: Публичный репозиторий без ключа

- **WHEN** у workspace нет `repo.access_ref`, а его репозиторий публичный
- **THEN** bootstrap клонирует его без заголовка авторизации, CLI выводит предупреждение с id workspace

### Requirement: Ключи из vault

Сервер SHALL получать ключи по ссылкам `vault:<project>/<service>/<name>` из настроек через MCP-адаптер vault без
участия владельца. Ключ репозитория MUST браться по ссылке `repo.access_ref` своего workspace; ENV `GITLAB_TOKEN`
MUST NOT использоваться. Ключи MUST передаваться в песочницу только в окружении команд и MUST NOT записываться в
файлы песочницы, включая конфигурацию memory-agent.

#### Scenario: Ключ embeddings не на диске

- **WHEN** bootstrap выполнил `memory init` с ключом embeddings из vault
- **THEN** поиск значения ключа в `~` и в каталогах репозиториев ничего не находит

#### Scenario: Vault недоступен при bootstrap

- **WHEN** vault не отвечает во время bootstrap
- **THEN** bootstrap завершается с кодом 1 и причиной `vault`, статус песочницы не меняется

#### Scenario: Ключ из ENV не используется

- **WHEN** в ENV задан `GITLAB_TOKEN`, а у workspace нет `repo.access_ref`
- **THEN** значение из ENV не уходит в песочницу, клон этого workspace анонимный

## ADDED Requirements

### Requirement: Авторизация git по workspace

Git в песочнице SHALL авторизоваться ключом workspace заголовком `Authorization: Basic` в окружении одной
git-команды, привязанным к префиксу адреса репозитория этого workspace (`<base_url>/<project>.git/`), с выключенными
редиректами. Имя пользователя Basic MUST быть `oauth2` для GitLab и `x-access-token` для GitHub. Ключ и заголовок
MUST NOT попадать в argv и файлы. Перед fetch задачи `origin` клона MUST возвращаться на адрес из конфига.

#### Scenario: Два провайдера в одной песочнице

- **WHEN** bootstrap клонирует workspace GitHub с ключом и workspace GitLab с другим ключом
- **THEN** клон GitHub получает заголовок с `x-access-token` только на префикс своего репозитория, клон GitLab —
  заголовок с `oauth2` только на префикс своего, ни один ключ не уходит в чужой репозиторий

#### Scenario: Агент сменил origin

- **WHEN** агент изменил адрес `origin` клона на другой репозиторий того же хоста
- **THEN** активация следующей задачи возвращает `origin` на адрес из конфига до fetch, ключ на другой адрес не уходит

### Requirement: Заголовки репозиториев в bootstrap

Bootstrap SHALL получать заголовок i-й пары `<id>=<url>` только в env `GIT_AUTH_HEADER_<i>` и снимать эти
переменные из env до любых установок. Неверное имя, номер без пары или значение не вида `Authorization: Basic`
MUST завершать скрипт с кодом 2 без вывода значения.

#### Scenario: Заголовок без пары

- **WHEN** bootstrap получает `GIT_AUTH_HEADER_3`, а пар в аргументах две
- **THEN** скрипт завершается с кодом 2 до любых установок, значение заголовка в выводе отсутствует

#### Scenario: Удалённый аргумент адреса GitLab

- **WHEN** bootstrap запускают с `--gitlab-url`
- **THEN** скрипт завершается с кодом 2 «неизвестный аргумент»
