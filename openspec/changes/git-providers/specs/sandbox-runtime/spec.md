## ADDED Requirements

### Requirement: Ключ записи репозитория перед задачей

Перед активацией песочницы под задачу worker SHALL получить ключ репозитория workspace задачи по `repo.access_ref`.
Если ссылки нет, задача MUST перейти в `error` с причиной, которая начинается с `repo_access_ref:` и называет
workspace, а песочница MUST NOT активироваться. Fetch при активации MUST идти с ключом workspace задачи.

#### Scenario: Workspace без ключа

- **WHEN** в очереди задача workspace без `repo.access_ref`
- **THEN** задача в `error` с причиной `repo_access_ref: у workspace <id> нет repo.access_ref — задаче нужен ключ
  записи (push)`, fetch и worktree в песочнице не выполнялись

#### Scenario: Задача на GitHub

- **WHEN** задача workspace `provider: github` с ключом активируется
- **THEN** fetch выполняется с заголовком `x-access-token` на префикс `https://github.com/<owner>/<name>.git/`

### Requirement: Токены git-провайдеров в redaction

Redaction SHALL заменять токены GitHub (`ghp_`, `gho_`, `ghu_`, `ghs_`, `ghr_`, `github_pat_`), токены GitLab с
префиксами `glpat-`, `gldt-`, `glrt-` и другими `gl…-`, в том числе сразу после `_`, значение заголовка `Basic` в
любом регистре по шаблону, даже без точного значения, и пароль в адресе `https://user:pass@host`. Точные значения
ключа репозитория, его заголовка, base64 и base64 в URL-кодировке MUST добавляться в redaction для каждого
разрешённого ключа.

#### Scenario: Токен GitHub в выводе агента

- **WHEN** вывод агента или bootstrap содержит `github_pat_…` или `ghp_…`
- **THEN** в лог и БД уходит текст с `[REDACTED]` вместо значения

#### Scenario: Заголовок Basic в ошибке git

- **WHEN** текст ошибки содержит `Authorization: Basic <base64>`
- **THEN** текст сохраняется как `Authorization: Basic [REDACTED]`

#### Scenario: Пароль в адресе git

- **WHEN** текст ошибки содержит `https://oauth2:<token>@gitlab.com/group/demo.git`
- **THEN** текст сохраняется как `https://oauth2:[REDACTED]@gitlab.com/group/demo.git`

#### Scenario: Слово basic в тексте

- **WHEN** текст содержит `basic internationalization`
- **THEN** текст не меняется
