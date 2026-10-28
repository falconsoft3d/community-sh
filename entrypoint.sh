#!/bin/sh

# Create letsencrypt directory if it doesn't exist and set correct permissions
mkdir -p /app/letsencrypt
touch /app/letsencrypt/acme.json
chmod 600 /app/letsencrypt/acme.json

# Only the app service prepares the database; cron and others set RUN_MIGRATIONS=false
if [ "${RUN_MIGRATIONS:-true}" = "true" ]; then
    python manage.py migrate --noinput
    python manage.py createcachetable
    # One-time copy of db.sqlite3 into Postgres for installs that predate DATABASE_URL support
    python manage.py migrate_from_sqlite
    python manage.py collectstatic --noinput
    # Traefik routes (and Let's Encrypt certificates) for MAIN_DOMAIN and every instance
    python manage.py configure_domain || echo "configure_domain failed; the panel stays reachable on port 8000"
fi

# Exec the container's main command
exec "$@"
