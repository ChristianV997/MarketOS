-- Identity / workspace / durable-state foundation (additive).
--
-- Prerequisite: the existing `workspaces` table from deploy/supabase/schema.sql
-- (workspace_id TEXT PRIMARY KEY, name TEXT NOT NULL, ...). This migration never
-- creates, alters, or drops it, so there is one workspace catalog, not two.
--
-- Portable subset (TEXT ids/timestamps, CHECK, FK, UNIQUE) so the constraints can
-- be exercised in tests. Postgres-only row-level security lives in the matching
-- .rls.sql file. Foreign keys deliberately have no ON DELETE CASCADE.
--
-- SECURITY: on any database that exposes a public data API (e.g. Supabase's
-- `public` schema), apply 0001_identity_workspace_foundation.rls.sql immediately
-- after this file. Without it these tables, including workspace_members, are
-- readable through that API.
--
-- workspace_type reuses backend.workspaces.client_workspace.WORKSPACE_TYPES:
--   'internal'       -> the owner's own portfolio workspace
--   'client_service' -> one consulting client, operator-managed

CREATE TABLE IF NOT EXISTS workspace_identity (
    workspace_id   TEXT PRIMARY KEY REFERENCES workspaces (workspace_id),
    workspace_type TEXT NOT NULL CHECK (workspace_type IN ('internal', 'client_service')),
    created_at     TEXT NOT NULL,
    UNIQUE (workspace_id, workspace_type)
);

CREATE TABLE IF NOT EXISTS workspace_members (
    issuer       TEXT NOT NULL CHECK (length(issuer) > 0),
    subject      TEXT NOT NULL CHECK (length(subject) > 0),
    workspace_id TEXT NOT NULL REFERENCES workspace_identity (workspace_id),
    created_at   TEXT NOT NULL,
    PRIMARY KEY (issuer, subject, workspace_id)
);

CREATE INDEX IF NOT EXISTS idx_workspace_members_workspace ON workspace_members (workspace_id);

-- evidence_label intentionally has no live/measured value: nothing in this
-- foundation can establish measured or live evidence.
CREATE TABLE IF NOT EXISTS owner_portfolio_items (
    item_id        TEXT PRIMARY KEY,
    workspace_id   TEXT NOT NULL,
    workspace_type TEXT NOT NULL DEFAULT 'internal' CHECK (workspace_type = 'internal'),
    name           TEXT NOT NULL CHECK (length(name) > 0),
    category       TEXT,
    segment        TEXT,
    evidence_label TEXT NOT NULL CHECK (evidence_label IN ('fixture', 'manual', 'assumption', 'derived', 'unavailable')),
    created_at     TEXT NOT NULL,
    updated_at     TEXT NOT NULL,
    UNIQUE (workspace_id, name),
    FOREIGN KEY (workspace_id, workspace_type) REFERENCES workspace_identity (workspace_id, workspace_type)
);

CREATE TABLE IF NOT EXISTS client_profiles (
    workspace_id   TEXT PRIMARY KEY,
    workspace_type TEXT NOT NULL DEFAULT 'client_service' CHECK (workspace_type = 'client_service'),
    company_name   TEXT NOT NULL CHECK (length(company_name) > 0),
    business_type  TEXT NOT NULL CHECK (business_type IN ('service_b2c', 'service_b2b', 'product', 'other')),
    created_at     TEXT NOT NULL,
    updated_at     TEXT NOT NULL,
    FOREIGN KEY (workspace_id, workspace_type) REFERENCES workspace_identity (workspace_id, workspace_type)
);

-- Segments, target markets, offerings/inventory, and social accounts. A social
-- account is a recorded handle only: connection_state can only be 'record_only'.
CREATE TABLE IF NOT EXISTS client_profile_entries (
    entry_id         TEXT PRIMARY KEY,
    workspace_id     TEXT NOT NULL REFERENCES client_profiles (workspace_id),
    kind             TEXT NOT NULL CHECK (kind IN ('segment', 'target_market', 'offering', 'social_account')),
    label            TEXT NOT NULL CHECK (length(label) > 0),
    platform         TEXT NOT NULL DEFAULT '',
    connection_state TEXT NOT NULL DEFAULT 'record_only' CHECK (connection_state = 'record_only'),
    created_at       TEXT NOT NULL,
    CHECK ((kind = 'social_account') = (length(platform) > 0)),
    UNIQUE (workspace_id, kind, label, platform)
);
