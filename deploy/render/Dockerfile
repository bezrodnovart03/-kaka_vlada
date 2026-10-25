# syntax=docker/dockerfile:1
# Один контейнер для бесплатного Render (render.yaml): nginx + React-панель + gunicorn + бот.
# Для своего сервера удобнее compose.yaml (+ compose.prod.yaml), здесь — то же в одном образе.
# Контекст сборки — корень репозитория.

# ── SPA ───────────────────────────────────────────────────
FROM node:22-alpine AS frontend
WORKDIR /app
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ .
RUN npm run build

# ── зависимости backend через uv ──────────────────────────
FROM ghcr.io/astral-sh/uv:0.10.4 AS uv

FROM python:3.14-slim AS backend
COPY --from=uv /uv /uvx /bin/
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    UV_PROJECT_ENVIRONMENT=/app/backend/.venv
WORKDIR /app/backend
COPY backend/uv.lock backend/pyproject.toml ./
RUN uv sync --locked --no-dev --no-install-project
COPY backend/ .
# Статика админки собирается при сборке: settings требуют эти переменные, БД не нужна.
RUN SECRET_KEY=build-only ADMIN_USERNAME=build ADMIN_PASSWORD=build \
    .venv/bin/python manage.py collectstatic --noinput --verbosity 0

# ── рантайм ───────────────────────────────────────────────
FROM python:3.14-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends nginx-light \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --create-home --uid 10001 app

ENV PATH=/app/backend/.venv/bin:$PATH \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PORT=10000

WORKDIR /app/backend
COPY --from=backend --chown=app:app /app/backend /app/backend
COPY --from=frontend /app/dist /app/frontend
COPY deploy/render/nginx.conf deploy/render/start.sh /app/deploy/
RUN mkdir -p /app/backend/media && chown app:app /app/backend/media \
    && chmod +x /app/deploy/start.sh

USER app
EXPOSE 10000
CMD ["/app/deploy/start.sh"]
