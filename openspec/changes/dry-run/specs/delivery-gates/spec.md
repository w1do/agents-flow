## ADDED Requirements

### Requirement: Dry-run обязателен

Workspace SHALL принимать задачи только после успешного dry-run; dry-run MUST NOT пушить в боевой репозиторий.

#### Scenario: Новый workspace

- **WHEN** workspace добавлен, dry-run не выполнялся
- **THEN** задачи для него не создаются, бот предлагает запустить dry-run
