#!/bin/sh
# Подготовка перед стартом контейнера backend. В контейнере reminders — RUN_MIGRATIONS=0:
# миграции делает только backend, reminders стартует после его healthcheck.
set -e

if [ "${RUN_MIGRATIONS:-1}" = "1" ]; then
    # migrate также создаёт/обновляет администратора из ADMIN_USERNAME / ADMIN_PASSWORD.
    python manage.py migrate --noinput
    python manage.py collectstatic --noinput --verbosity 0
fi

if [ "${SEED_DEMO:-0}" = "1" ]; then
    # Без --reset: если платежи уже есть, команда ничего не меняет.
    python manage.py seed_demo
fi

exec "$@"
