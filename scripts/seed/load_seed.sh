#!/usr/bin/env bash
# Load the demo seed into the running Postgres container.
# Prereq: `docker compose up -d db` AND `alembic upgrade head` have already run
# (the seed loads DATA into the migrated schema — see scripts/seed/README.md).
#
# Usage:  ./scripts/seed/load_seed.sh
set -euo pipefail
DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$DIR/../.." && pwd)"

# Resolve the container via the compose SERVICE name ("db"), not a guessed
# container name. Compose names containers after the project directory (e.g. a
# repo cloned as "GTMAgent" gets "gtmagent-db-1", but a checker cloning it into
# any other folder name gets a different name entirely) — hardcoding a name
# broke on any clone whose folder wasn't named exactly like the original repo.
# Must run from the repo root so `docker compose` can find docker-compose.yml.
cd "$REPO_ROOT"
docker compose exec -T db psql -U gtm -d gtm -v ON_ERROR_STOP=1 < "$DIR/seed_demo.sql"
echo "✓ Demo seed loaded (database gtm)."
