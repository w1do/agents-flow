# syntax=docker/dockerfile:1
# Один образ для migrate, server и worker: различаются только команды в docker-compose.yml.

# --- builder: зависимости и код в .venv ---
FROM python:3.12-slim-bookworm AS builder

COPY --from=ghcr.io/astral-sh/uv:0.13.1 /uv /uvx /bin/

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=0 \
    UV_NO_DEV=1

WORKDIR /app

# Слой зависимостей идёт до копирования кода: код меняется часто, зависимости редко.
# Монтируются только файлы, которые нужны uv для разрешения workspace.
RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    --mount=type=bind,source=.python-version,target=.python-version \
    --mount=type=bind,source=apps/server/pyproject.toml,target=apps/server/pyproject.toml \
    --mount=type=bind,source=shared/pyproject.toml,target=shared/pyproject.toml \
    uv sync --frozen --no-install-workspace --package harness-server

COPY pyproject.toml uv.lock .python-version ./
COPY apps ./apps
COPY shared ./shared
COPY db ./db
COPY alembic.ini ./
# Скрипт bootstrap песочницы: CLI читает его из образа (bootstrap-in-image, D-63).
COPY deploy/sandbox ./deploy/sandbox

RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --package harness-server

# --- runtime: только интерпретатор, .venv и код; без uv и исходников тестов ---
FROM python:3.12-slim-bookworm

# Непривилегированный пользователь с фиксированным uid: так работают тома и политики Dokploy.
RUN groupadd --system --gid 10001 app \
    && useradd --system --uid 10001 --gid app --home-dir /app --shell /usr/sbin/nologin app

ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1

WORKDIR /app
COPY --from=builder --chown=app:app /app /app

USER app

EXPOSE 8000

CMD ["harness-server", "serve", "--host", "0.0.0.0", "--port", "8000"]
