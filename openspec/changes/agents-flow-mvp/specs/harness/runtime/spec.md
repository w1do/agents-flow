# Spec Delta

## Purpose

Ставится в произвольный Git-проект, получает задачу с сервера и ведёт её
по этапам, не зная ничего о конкретном стеке, хостинге и деплое.

## ADDED Requirements

### Requirement: Инициализация в Git-проекте
`harness init <project_id>` SHALL находить корень Git-репозитория, читать remote,
отправлять `POST /harness/init` с init-кодом и SHALL создавать только каталог
`workflow/` с конфигурацией, `.agent-token` и skills.

#### Scenario: Успешная инициализация
- **WHEN** команда запущена в корне Git-репозитория с действующим init-кодом
- **THEN** создан `workflow/` с `config.yaml`, `.gitignore`, `.agent-token` и файлами skills

#### Scenario: Неверный init-код
- **WHEN** сервер отклонил код
- **THEN** `workflow/` не создаётся, выводится понятная ошибка

#### Scenario: Вне Git-репозитория
- **WHEN** команда запущена не в Git-репозитории
- **THEN** команда завершается ошибкой до обращения к серверу

### Requirement: Хранение секрета
Harness SHALL хранить agent-токен только в `workflow/.agent-token` с правами 0600,
SHALL добавлять файл в `workflow/.gitignore` и SHALL не писать токен в YAML и логи.

#### Scenario: Токен не попадает в Git
- **WHEN** после init выполняется `git status`
- **THEN** `.agent-token` не виден как новый файл

#### Scenario: Права файла
- **WHEN** init завершён
- **THEN** у `.agent-token` права 0600

### Requirement: Рабочий цикл run
`harness run` SHALL синхронизировать skills, продлевать аренду heartbeat,
арендовать не более одной задачи и SHALL вести её по этапам до решения
пользователя.

#### Scenario: Нет задач
- **WHEN** сервер не выдал задачу
- **THEN** Harness ждёт `poll_interval_seconds` и повторяет запрос

#### Scenario: Задача получена
- **WHEN** аренда успешна
- **THEN** Harness создаёт worktree, передаёт задачу агенту и сообщает план на сервер

#### Scenario: Нет связи
- **WHEN** сервер недоступен
- **THEN** Harness повторяет с задержкой, не теряет состояние задачи и не завершает её сам

### Requirement: Изоляция работы в worktree
Harness SHALL создавать отдельный Git worktree на ветке `task/<task_id>` и SHALL
не изменять основную рабочую копию и основную ветку.

#### Scenario: Работа идёт
- **WHEN** агент реализует задачу
- **THEN** изменения находятся в worktree задачи, основная ветка не тронута

#### Scenario: Повторный запуск по той же задаче
- **WHEN** задача снова выдана после сбоя и worktree уже существует
- **THEN** Harness продолжает в существующем worktree, а не создаёт второй

### Requirement: Синхронизация skills перед задачей
Harness SHALL перед получением новой задачи загружать новые skills, обновлять
изменённые и удалять снятые, и SHALL не менять skills задачи, которая уже идёт.

#### Scenario: Skill изменён на сервере
- **WHEN** между задачами изменился skill
- **THEN** локальный файл обновлён до следующей задачи

#### Scenario: Skill снят с агента
- **WHEN** skill больше не назначен
- **THEN** его файл удалён из `workflow/skills/`

### Requirement: Этапы работы и наборы skills
Harness SHALL передавать агенту только skills текущего этапа: планирование,
реализация, проверки, публикация, и SHALL не передавать skills публикации
до решения `publish`.

#### Scenario: Планирование
- **WHEN** агент формирует план
- **THEN** ему не передаются skills Git и деплоя

#### Scenario: Публикация
- **WHEN** сервер подтвердил решение `publish`
- **THEN** агенту передаются skills Git и деплоя

#### Scenario: Нет skills публикации
- **WHEN** агенту не назначены skills Git и деплоя
- **THEN** он завершает работу на `ready`, push и deploy не выполняются

### Requirement: Отчёт о ходе работы
Harness SHALL передавать план, прогресс, checkpoint, результаты проверок,
итог реализации и итог публикации, и SHALL сохранять checkpoint при сбое.

#### Scenario: Сбой агента
- **WHEN** агент завершился ошибкой
- **THEN** Harness отправляет `fail` с человеческим описанием и сохраняет checkpoint

#### Scenario: Результат проверок
- **WHEN** агент выполнил проверки из skill
- **THEN** сервер получает список команд, exit code и краткую сводку

### Requirement: Отсутствие привязки к стеку
Harness SHALL не содержать команд сборки, тестов, Git push, GitHub/GitLab API,
Dokploy и имён фреймворков; эти действия SHALL выполняться агентом по skills.

#### Scenario: Проект на другом стеке
- **WHEN** Harness поставлен в проект на другом языке
- **THEN** поведение Harness не меняется, отличия приходят только из skills
