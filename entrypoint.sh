#!/bin/sh

# Create letsencrypt directory if it doesn't exist and set correct permissions
mkdir -p /app/letsencrypt
touch /app/letsencrypt/acme.json
chmod 600 /app/letsencrypt/acme.json

# Verify if database exists or run migrations
python manage.py migrate

# Collect static files
python manage.py collectstatic --noinput

# Exec the container's main command
exec "$@"
