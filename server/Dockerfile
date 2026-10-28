# Build context: repository root.
FROM node:22-alpine AS web
WORKDIR /web
COPY server/web/package.json server/web/package-lock.json ./
RUN npm ci
COPY server/web/ ./
RUN npm run build

FROM python:3.12-slim AS python-deps
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /app
# Install runtime requirements in a cacheable layer before application code.
COPY server/pyproject.toml ./
RUN python -c "import pathlib, subprocess, sys, tomllib; deps=tomllib.loads(pathlib.Path('pyproject.toml').read_text())['project']['dependencies']; subprocess.check_call([sys.executable, '-m', 'pip', 'install', '--no-cache-dir', *deps])"
COPY server/app/ ./app/
RUN python -m pip install --no-cache-dir --no-deps .

FROM python-deps AS lint
RUN python -m pip install --no-cache-dir ruff==0.14.2 \
    && ruff check --select E9,F63,F7,F82 app \
    && python -m pip check

FROM python-deps AS runtime
COPY server/alembic.ini ./
COPY server/migrations/ ./migrations/
COPY --from=web /web/dist/ ./web/dist/
USER 10001:10001
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--no-proxy-headers"]
