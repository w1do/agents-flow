# Spec Delta

## Purpose

Даёт агенту второй способ вести задачу — через MCP-инструменты поверх того же
состояния и тех же правил, что REST, без собственных статусов.

## ADDED Requirements

### Requirement: Набор инструментов агента
Система SHALL предоставлять MCP-инструменты `agent_get_assigned_task`,
`agent_heartbeat`, `agent_report_plan`, `agent_get_plan_decision`,
`agent_report_progress`, `agent_save_checkpoint`, `agent_report_test_result`,
`agent_report_result`, `agent_get_result_decision`,
`agent_report_publication_result`, `agent_report_failure`.

#### Scenario: Получение своей задачи
- **WHEN** агент вызывает `agent_get_assigned_task`
- **THEN** возвращаются задача, lease, checkpoint и последнее решение пользователя

#### Scenario: Отчёт о плане через MCP
- **WHEN** агент вызывает `agent_report_plan`
- **THEN** задача переходит в `backlog` так же, как через REST

### Requirement: Единое состояние с REST
Система SHALL использовать общий service layer и одну базу для MCP и REST
и SHALL не заводить отдельные статусы или обходы ограничений.

#### Scenario: Смена через MCP видна в панели
- **WHEN** агент отчитался через MCP
- **THEN** изменение сразу видно в REST-карточке задачи

#### Scenario: Ограничения те же
- **WHEN** MCP-вызов пытается поставить `merged`
- **THEN** сервер отказывает так же, как в REST

### Requirement: Ограничение доступа к своей арендованной задаче
Система SHALL позволять MCP-инструментам работать только со своей арендованной
задачей и своим проектом.

#### Scenario: Чужая задача
- **WHEN** агент передаёт `task_id` другого проекта
- **THEN** возвращается отказ, данные задачи не раскрываются

#### Scenario: Задача без текущей аренды
- **WHEN** агент вызывает отчёт по задаче, которая ему не выдана
- **THEN** возвращается отказ 409 или 403

### Requirement: Обязательный event_id в отчётах
Система SHALL требовать `event_id` в каждом MCP-отчёте и SHALL игнорировать
повтор с уже известным `event_id`.

#### Scenario: Повторный отчёт
- **WHEN** агент повторяет `agent_report_progress` с тем же `event_id`
- **THEN** дубликат не создаётся и ответ успешен

### Requirement: Журналирование MCP-вызовов
Система SHALL записывать каждый MCP-вызов в `task_events` с типом `mcp_*`
и SHALL не включать в событие секреты и полные тела запросов.

#### Scenario: Вызов сохранения checkpoint
- **WHEN** агент вызывает `agent_save_checkpoint`
- **THEN** в ленте появляется событие `mcp_save_checkpoint`

### Requirement: Компактный безопасный ответ
Система SHALL отвечать компактным JSON без внутренних деталей, стектрейсов
и секретов, с понятной ошибкой.

#### Scenario: Неверный аргумент
- **WHEN** инструмент вызван с невалидным аргументом
- **THEN** возвращается ошибка валидации без внутренних путей и трассировки
