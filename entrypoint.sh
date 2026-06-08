#!/usr/bin/env bash
# Container entrypoint: wait for the database, migrate, collect static, then run.
set -e

echo "Waiting for the database to accept connections..."
until python -c "
import django, os
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()
from django.db import connection
connection.ensure_connection()
" 2>/dev/null; do
  echo "  ...database not ready yet, retrying in 2s"
  sleep 2
done
echo "Database is ready."

python manage.py migrate --noinput
python manage.py collectstatic --noinput

# Optional bootstrap helpers, toggled via environment variables.
if [ -n "${DJANGO_SUPERUSER_USERNAME:-}" ] && [ -n "${DJANGO_SUPERUSER_PASSWORD:-}" ]; then
  echo "Ensuring superuser '${DJANGO_SUPERUSER_USERNAME}' exists..."
  python manage.py createsuperuser --noinput || true
fi

if [ "${SEED_ON_START:-false}" = "true" ]; then
  echo "Seeding demo data..."
  python manage.py seed_data
fi

exec "$@"
