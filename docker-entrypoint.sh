#!/bin/bash
set -e

echo "Running database migrations..."
# For existing deployments with tables but no migration history, run:
#   flask db stamp head
# before the first upgrade.
flask db upgrade
echo "Migrations complete."

exec "$@"
