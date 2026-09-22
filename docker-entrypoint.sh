#!/usr/bin/env bash
# Bring the schema up to date, then hand over to the real command.
#
# `set -e` matters here: without it a failed migration would be logged and the
# API would start anyway, serving traffic against a schema it does not match.
set -euo pipefail

echo "Running database migrations..."
alembic upgrade head

exec "$@"
