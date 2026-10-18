## ADDED Requirements

### Requirement: Гейты задаются workspace

Набор и порядок гейтов SHALL браться из настроек workspace; гейт `secrets` MUST быть всегда, даже если не указан.

#### Scenario: Workspace текстов

- **WHEN** у workspace гейты `commit` и `mr`
- **THEN** тесты и деплой не запускаются, проверка секретов выполняется

### Requirement: Гейт деплоя

Гейт `deploy` SHALL выполнять команду деплоя в staging и считаться пройденным только по нулевому коду.

#### Scenario: Деплой упал

- **WHEN** команда деплоя вернула ошибку
- **THEN** задача в `error` с причиной, MR не помечается готовым
