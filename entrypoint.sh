#!/bin/sh

# Verify if database exists or run migrations
python manage.py migrate

# Collect static files
python manage.py collectstatic --noinput

# Exec the container's main command
exec "$@"
