<#
  Load the demo seed into the running Postgres container.
  Prereq: `docker compose up -d db` AND `alembic upgrade head` have already run
  (the seed loads DATA into the migrated schema — see scripts/seed/README.md).

  Usage:  .\scripts\seed\load_seed.ps1 [-Container gtmagent-db-1]
#>
param([string]$Container = "gtmagent-db-1")
$ErrorActionPreference = "Stop"
$seed = Join-Path $PSScriptRoot "seed_demo.sql"

# Copy into the container and run it there — avoids PowerShell stdin re-encoding
# the multilingual (DE/CZ/PL/…) company & tender text.
docker cp $seed "${Container}:/tmp/seed_demo.sql"
docker exec $Container psql -U gtm -d gtm -v ON_ERROR_STOP=1 -f /tmp/seed_demo.sql
Write-Host "OK - demo seed loaded into '$Container' (database gtm)."
