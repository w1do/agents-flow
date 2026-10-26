# syntax=docker/dockerfile:1
# Образ консоли: статика Vite за nginx. Контекст сборки — корень репозитория:
# apps/console подключает packages/shared-types через `link:` в package.json.

# --- build: зависимости pnpm и vite build ---
FROM node:22-alpine AS build

RUN corepack enable && corepack prepare pnpm@9.12.3 --activate

WORKDIR /repo/apps/console

# Слой зависимостей идёт до копирования исходников: код меняется чаще lockfile.
# shared-types копируется первым, иначе `link:` в pnpm не найдёт целевой каталог.
COPY packages/shared-types /repo/packages/shared-types
COPY apps/console/package.json apps/console/pnpm-lock.yaml ./
RUN pnpm install --frozen-lockfile

COPY apps/console/ ./
RUN pnpm build

# --- runtime: только статика и конфиг nginx ---
FROM nginx:alpine

# nginx.conf заменяет default.conf: единственный server-блок, отдаёт SPA и проксирует API.
COPY apps/console/nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /repo/apps/console/dist /usr/share/nginx/html

EXPOSE 80
