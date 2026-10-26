# Spec Delta

## MODIFIED Requirements

### Requirement: Описание workspace в конфиге

Список workspaces SHALL храниться на сервере как проекты (см. `project-catalog`), а не в `harness.yaml`.
Конфиг SHALL описывать только глобальные настройки сервера и песочницы. Блок `workspaces` в `harness.yaml`
MUST отклоняться с сообщением, куда перенести проект (в консоль или API `project-catalog`). Секция `gitlab` и
поле `gitlab_project` MUST отклоняться с сообщением, куда перенести настройки. Идентификаторы проектов MUST
быть уникальны.

#### Scenario: Повтор идентификатора
- **WHEN** два проекта на сервере получили одинаковый `id`
- **THEN** второе создание отклоняется, существующий проект не меняется

#### Scenario: Старая форма конфига
- **WHEN** в `harness.yaml` есть блок `workspaces` или секция `gitlab`
- **THEN** сервер не запускается и называет блок, который нужно перенести

### Requirement: Секреты и учётные данные в конфигурации

Проверка `harness.yaml` SHALL отклонять ключи с сегментами `token`, `tokens`, `key`, `password`, `passwd`, `pwd`,
`secret`, `secrets`, `apikey`, `credential`, `credentials` на любом уровне вложенности. Переменная
`HARNESS_ADMIN_TOKEN`, если задана, MUST быть не короче 32 символов. Сообщения об ошибках MUST называть поле или
переменную без значения.

#### Scenario: Пароль в адресе GitLab
- **WHEN** в адресе репозитория проекта указаны учётные данные (`user:pass@host`)
- **THEN** проект отклоняется, а адрес в сообщении не выводится

#### Scenario: Новый сегмент секрета
- **WHEN** в `harness.yaml` появляется ключ с сегментом `token` на любом уровне
- **THEN** конфиг отклоняется с именем поля без значения

#### Scenario: Короткий операторский токен
- **WHEN** `HARNESS_ADMIN_TOKEN` задан короче 32 символов
- **THEN** сервер не запускается с понятным сообщением без значения токена

### Requirement: Репозиторий workspace

Блок `repo` проекта SHALL задавать провайдера (`github` или `gitlab`), адрес `base_url`, проект `project` и
необязательную ссылку `access_ref` на ключ в vault (`vault:<project>/<service>/<name>`). Без `base_url` адрес MUST
быть `https://github.com` для GitHub и `https://gitlab.com` для GitLab. Проект GitHub MUST иметь вид `owner/name`,
проект GitLab — `group[/subgroup]/name`, без `.git`. Проверка выполняется при создании и изменении проекта на
сервере.

#### Scenario: Workspace на GitHub по умолчанию
- **WHEN** проект создан с провайдером `github` и без `base_url`
- **THEN** адрес репозитория MUST быть `https://github.com`

#### Scenario: Свой GitLab с подгруппой
- **WHEN** проект создан с провайдером `gitlab`, проектом `group/subgroup/name` и своим адресом
- **THEN** сервер принимает проект и использует указанный адрес

#### Scenario: Разные провайдеры в одном конфиге
- **WHEN** на сервере есть проекты на GitHub и на GitLab одновременно
- **THEN** каждый проект использует свой провайдер, без общего значения по умолчанию
