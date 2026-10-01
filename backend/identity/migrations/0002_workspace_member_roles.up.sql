-- Membership roles for the client-profile API (additive, reversible).
--
-- A NULL role (every pre-existing membership) grants nothing: the application
-- fails closed on an unknown or missing role. Role ids reuse the TrustOS
-- client-workspace vocabulary (evaluation/trustos/client_workspace_isolation.py).
-- No new table is created, so no new row-level-security statement is needed;
-- 0001_identity_workspace_foundation.rls.sql already covers workspace_members.
ALTER TABLE workspace_members
    ADD COLUMN role TEXT CHECK (role IS NULL OR role IN ('client_viewer', 'internal_operator'));
