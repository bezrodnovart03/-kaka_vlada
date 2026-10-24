# syntax=docker/dockerfile:1

# ── сборка зависимостей через uv ──────────────────────────
FROM ghcr.io/astral-sh/uv:0.10.4 AS uv

FROM python:3.14-slim AS build
COPY --from=uv /uv /uvx /bin/
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    UV_PROJECT_ENVIRONMENT=/app/.venv
WORKDIR /app

# Сначала только зависимости: слой кэшируется, пока не меняется uv.lock.
RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    uv sync --locked --no-dev --no-install-project

COPY . .

# ── рантайм: без uv и компиляторов, от непривилегированного пользователя ──
FROM python:3.14-slim

ENV PATH=/app/.venv/bin:$PATH \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

RUN useradd --create-home --uid 10001 app
WORKDIR /app
COPY --from=build --chown=app:app /app /app
# Каталоги томов создаются заранее с владельцем app: именованный том наследует права.
RUN mkdir -p /app/media /app/staticfiles /app/logs \
    && chown app:app /app/media /app/staticfiles /app/logs \
    && chmod +x /app/docker-entrypoint.sh

USER app
EXPOSE 8000

ENTRYPOINT ["/app/docker-entrypoint.sh"]
CMD ["sh", "-c", "exec gunicorn config.wsgi:application --bind 0.0.0.0:8000 --workers ${GUNICORN_WORKERS:-2} --timeout 60 --access-logfile -"]
