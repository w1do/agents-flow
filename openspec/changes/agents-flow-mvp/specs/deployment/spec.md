# Spec Delta

## Purpose

Описывает, как сервер и база разворачиваются в Dokploy и какие переменные
окружения нужны, чтобы прототип запускался одной командой.

## ADDED Requirements

### Requirement: Compose-стек базы
Система SHALL разворачивать PostgreSQL отдельным Compose-стеком с постоянным
volume, без публикации порта наружу и в сети `dokploy-network`.

#### Scenario: Пересборка сервера
- **WHEN** сервер пересобирается и перезапускается
- **THEN** данные PostgreSQL сохраняются

#### Scenario: Доступ снаружи
- **WHEN** выполнена попытка подключиться к PostgreSQL извне сети
- **THEN** соединение недоступно

### Requirement: Compose-стек приложения
Система SHALL запускать `migrate`, `server` и `console` так, чтобы миграции
завершались до старта сервера.

#### Scenario: Первый запуск
- **WHEN** стек поднимается на пустой базе
- **THEN** миграции применяются, сервер стартует и отвечает на healthcheck

#### Scenario: Миграция упала
- **WHEN** `migrate` завершился ошибкой
- **THEN** сервер не стартует

### Requirement: Локальный запуск прототипа
Система SHALL позволять поднять сервер локально одной командой
`docker compose up` с заполненным `.env`.

#### Scenario: Локальный старт
- **WHEN** разработчик выполнил `docker compose up` при наличии `.env`
- **THEN** база, миграции и сервер поднимаются, панель доступна по локальному адресу

### Requirement: Переменные окружения
Система SHALL читать конфигурацию из переменных окружения и SHALL предоставлять
`.env.example` со всеми обязательными именами без реальных значений.

#### Scenario: Полный перечень
- **WHEN** разработчик открывает `.env.example`
- **THEN** в нём есть `DATABASE_URL`, `JWT_SECRET`, `ADMIN_EMAIL`, `ADMIN_PASSWORD`,
  `TELEGRAM_BOT_TOKEN`, `TELEGRAM_WEBHOOK_SECRET`, `TRANSCRIPTION_PROVIDER`,
  `TRANSCRIPTION_API_KEY`, `PUBLIC_BASE_URL`, `OPENAI_API_KEY` и `OPENAI_BASE_URL`

#### Scenario: Работа без внешних сервисов
- **WHEN** Telegram и провайдер транскрибации не настроены
- **THEN** сервер стартует и REST, панель и MCP доступны, а Telegram-функции отключены

### Requirement: Отсутствие секретов в репозитории
Система SHALL игнорировать `.env`, `workflow/.agent-token` и локальные данные
и SHALL не требовать секретов в Git.

#### Scenario: Коммит после настройки
- **WHEN** разработчик закоммитил изменения после заполнения `.env`
- **THEN** `.env` отсутствует в коммите
