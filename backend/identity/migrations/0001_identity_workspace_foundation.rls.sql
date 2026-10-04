-- Postgres-only. Apply after 0001 up, matching deploy/supabase/schema.sql: enable
-- row-level security and create NO anon/authenticated policies, so these tables
-- are not readable through a public data API. Server-side access is an operator
-- deployment responsibility; never expose a service-role or database credential
-- to the frontend. Not executed by the SQLite-based tests.
ALTER TABLE workspace_identity ENABLE ROW LEVEL SECURITY;
ALTER TABLE workspace_members ENABLE ROW LEVEL SECURITY;
ALTER TABLE owner_portfolio_items ENABLE ROW LEVEL SECURITY;
ALTER TABLE client_profiles ENABLE ROW LEVEL SECURITY;
ALTER TABLE client_profile_entries ENABLE ROW LEVEL SECURITY;
