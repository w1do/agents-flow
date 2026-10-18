## ADDED Requirements

### Requirement: Запуск агента по типу

Пайплайны SHALL запускать агента по типу из настроек workspace одинаковым контрактом: файл потока, файл статуса, отчёты через MCP.

#### Scenario: Workspace на Codex

- **WHEN** у workspace агент `codex`
- **THEN** задача выполняется Codex на песочнице типа `codex`, этапы и гейты те же
