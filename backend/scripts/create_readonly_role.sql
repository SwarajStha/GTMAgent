-- Least-privilege READ-ONLY role for the agent's `query_db` tool (P2 structural fix).
--
-- The app connects to Postgres as `gtm`, which the pgvector docker image creates
-- as a SUPERUSER. That means a read-only SELECT routed through `query_db` could
-- still call pg_read_file(), read pg_authid password hashes, dblink out, etc. —
-- gated only by an application-layer keyword guard. This role removes that power
-- structurally: a NOSUPERUSER role with SELECT-only grants CANNOT invoke those
-- superuser-restricted functions, and Postgres — not our string matching —
-- enforces it.
--
-- Provision once, as a superuser, against the app database:
--     psql -U gtm -d gtm -f backend/scripts/create_readonly_role.sql
-- (Docker: `docker exec -i gtmagent-db-1 psql -U gtm -d gtm < backend/scripts/create_readonly_role.sql`)
--
-- Then point the app at it so `query_db` uses this role instead of the superuser
-- session (backend/.env):
--     DATABASE_URL_READONLY=postgresql+psycopg://gtm_ro:gtm_ro@localhost:6543/gtm
--
-- When DATABASE_URL_READONLY is unset, `query_db` falls back to the guarded
-- shared session (still safe via the keyword guard + statement_timeout, just
-- without the structural DB-level guarantee).

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'gtm_ro') THEN
        CREATE ROLE gtm_ro LOGIN PASSWORD 'gtm_ro'
            NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS;
    END IF;
END
$$;

-- Read-only + bounded by default, even if a caller forgets to set them per-txn.
ALTER ROLE gtm_ro SET default_transaction_read_only = on;
ALTER ROLE gtm_ro SET statement_timeout = '5000ms';

-- Minimal privileges: connect + read the app schema. No CREATE, no writes.
GRANT CONNECT ON DATABASE gtm TO gtm_ro;
GRANT USAGE ON SCHEMA public TO gtm_ro;
GRANT SELECT ON ALL TABLES IN SCHEMA public TO gtm_ro;

-- Future tables (new migrations) are readable too, without re-running grants.
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT ON TABLES TO gtm_ro;
