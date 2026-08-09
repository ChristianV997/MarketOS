# Supabase foundation

`schema.sql` is the deliberately small Postgres target for the MVP Island. It
creates workspace-scoped canonical events, public signals, advisory artifacts,
run envelopes, and source-readiness snapshots. It does not import existing
JSONL/DuckDB data, replace `JsonlEventRepository`, enable a browser client, or
create an Auth/RLS tenancy implementation.

Apply it only to an operator-owned project after reviewing it in the Supabase
SQL editor or your normal migration process. RLS is enabled with no public
policies, so a client does not gain data access merely because the tables
exist. Keep `SUPABASE_SERVICE_ROLE_KEY` server-side; it is never a Vite env
variable. The optional `backend.events.adapters.supabase.SupabaseEventRepository`
is constructed explicitly and is not the MarketOS default repository.

Before enabling a production adapter, define workspace ownership policies,
test them with a real Supabase project, and decide whether backend writes use a
server-only service role or a constrained database connection. Verify current
Supabase configuration and pricing before committing spend.
