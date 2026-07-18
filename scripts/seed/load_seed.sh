#!/usr/bin/env bash
# Load the demo seed into the running Postgres container.
# Prereq: `docker compose up -d db` AND `alembic upgrade head` have already run
# (the seed loads DATA into the migrated schema — see scripts/seed/README.md).
#
# Usage:  ./scripts/seed/load_seed.sh [container_name]   (default: gtmagent-db-1)
set -euo pipefail
CONTAINER="${1:-gtmagent-db-1}"
DIR="$(cd "$(dirname "$0")" && pwd)"

# Pipe the file to psql over stdin — bash streams the bytes verbatim (no
# re-encoding of the multilingual DE/CZ/PL/… text, and no MSYS path munging of
# a container-side -f argument under Git Bash on Windows).
docker exec -i "$CONTAINER" psql -U gtm -d gtm -v ON_ERROR_STOP=1 < "$DIR/seed_demo.sql"
echo "✓ Demo seed loaded into '$CONTAINER' (database gtm)."
