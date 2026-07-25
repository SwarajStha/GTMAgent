<#
  Load the demo seed into the running Postgres container.
  Prereq: `docker compose up -d db` AND `alembic upgrade head` have already run
  (the seed loads DATA into the migrated schema — see scripts/seed/README.md).

  Usage:  .\scripts\seed\load_seed.ps1
#>
$ErrorActionPreference = "Stop"
$seed = Join-Path $PSScriptRoot "seed_demo.sql"
$repoRoot = Resolve-Path (Join-Path $PSScriptRoot "..\..")

# Resolve the container via the compose SERVICE name ("db"), not a guessed
# container name. Compose names containers after the project directory (e.g. a
# repo cloned as "GTMAgent" gets "gtmagent-db-1", but a checker cloning it into
# any other folder name gets a different name entirely) — hardcoding a name
# broke on any clone whose folder wasn't named exactly like the original repo.
# `docker compose ... db` resolves the current container regardless of its name,
# as long as we run from the repo root (where docker-compose.yml lives).
Push-Location $repoRoot
try {
    docker compose cp $seed db:/tmp/seed_demo.sql
    if ($LASTEXITCODE -ne 0) { throw "docker compose cp failed (exit code $LASTEXITCODE)" }

    docker compose exec db psql -U gtm -d gtm -v ON_ERROR_STOP=1 -f /tmp/seed_demo.sql
    if ($LASTEXITCODE -ne 0) { throw "psql seed load failed (exit code $LASTEXITCODE)" }
} finally {
    Pop-Location
}
Write-Host "OK - demo seed loaded (database gtm)."
