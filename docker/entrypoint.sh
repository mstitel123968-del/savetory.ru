#!/bin/sh
set -e

if [ "${SKIP_DB_WAIT}" = "1" ]; then
  exec "$@"
fi

host="${POSTGRES_HOST:-localhost}"
port="${POSTGRES_PORT:-5432}"

if [ -n "$host" ]; then
  echo "Waiting for PostgreSQL at ${host}:${port}..."
  python - <<'PY'
import os
import time
import psycopg2
from psycopg2 import OperationalError

host = os.environ.get('POSTGRES_HOST', 'localhost')
port = int(os.environ.get('POSTGRES_PORT', '5432'))
db = os.environ.get('POSTGRES_DB', 'trezo')
user = os.environ.get('POSTGRES_USER', 'trezo')
password = os.environ.get('POSTGRES_PASSWORD', 'trezo')

deadline = time.time() + 120
while True:
    try:
        conn = psycopg2.connect(host=host, port=port, dbname=db, user=user, password=password)
    except OperationalError as exc:
        if time.time() > deadline:
            raise SystemExit(f"Timed out waiting for PostgreSQL: {exc}")
        time.sleep(2)
    else:
        conn.close()
        break
PY
  echo "PostgreSQL is available."
fi

if [ "${SKIP_MIGRATIONS}" != "1" ]; then
  echo "Applying database migrations..."
  python manage.py migrate --noinput
fi

# Clean up any legacy Django user that used the reserved editor login.
echo "Cleaning reserved administrator user..."
python manage.py ensure_superuser

if [ "${SKIP_COLLECTSTATIC}" != "1" ]; then
  echo "Collecting static files..."
  python manage.py collectstatic --noinput --clear
fi

exec "$@"
