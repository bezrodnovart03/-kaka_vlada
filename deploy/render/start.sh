#!/usr/bin/env bash
# Старт контейнера deploy/render: миграции, затем gunicorn, бот (run_reminders) и nginx.
# Если любой из трёх процессов завершится, контейнер выходит и Render его перезапускает.
set -euo pipefail

# Render сам сообщает публичный адрес сервиса — из него хосты, CSRF и ссылка в напоминаниях.
host="${RENDER_EXTERNAL_HOSTNAME:-localhost}"
url="${RENDER_EXTERNAL_URL:-http://localhost:${PORT}}"
if [ -z "${ALLOWED_HOSTS:-}" ]; then
    export ALLOWED_HOSTS="[\"${host}\",\"localhost\",\"127.0.0.1\"]"
fi
if [ -z "${CSRF_TRUSTED_ORIGINS:-}" ]; then
    export CSRF_TRUSTED_ORIGINS="[\"${url}\"]"
fi
export PANEL_URL="${PANEL_URL:-$url}"

# migrate также создаёт/обновляет администратора из ADMIN_USERNAME / ADMIN_PASSWORD.
python manage.py migrate --noinput
if [ "${SEED_DEMO:-0}" = "1" ]; then
    # Без --reset: если платежи уже есть, команда ничего не меняет.
    python manage.py seed_demo
fi

sed "s/__PORT__/${PORT}/" /app/deploy/nginx.conf > /tmp/nginx.conf

gunicorn config.wsgi:application --bind 127.0.0.1:8000 \
    --workers "${GUNICORN_WORKERS:-1}" --threads 4 --timeout 60 --access-logfile - &
python manage.py run_reminders &
nginx -c /tmp/nginx.conf -g "daemon off;" &

wait -n
exit 1
