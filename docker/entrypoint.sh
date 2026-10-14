#!/bin/sh
# Container entrypoint: migrate, optionally bootstrap dev data, then exec the server.
set -eu

if [ "${SBH_RUN_MIGRATIONS:-true}" = "true" ]; then
  echo "[entrypoint] applying database migrations (alembic upgrade head)"
  alembic upgrade head
fi

if [ "${SBH_DEV_BOOTSTRAP:-false}" = "true" ]; then
  echo "[entrypoint] DEV bootstrap: throw-away admin/token and SYNTHETIC data"
  python -m app.cli dev-bootstrap
  python -m app.cli seed --if-empty --days "${SBH_SEED_DAYS:-30}"
fi

exec "$@"
