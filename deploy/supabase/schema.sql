-- MarketOS MVP Island schema. Apply deliberately in a Supabase SQL editor or
-- migration workflow after reviewing the deployment model. This does not
-- migrate any JSONL, DuckDB, workflow, or legacy Supabase state table.

create table if not exists public.workspaces (
    workspace_id text primary key,
    name text not null default 'MarketOS workspace',
    created_at timestamptz not null default now(),
    metadata jsonb not null default '{}'::jsonb
);

-- Mirrors backend.contracts.events.Event. event_id is supplied by MarketOS,
-- preserving canonical replay identity across JSONL and future Postgres reads.
create table if not exists public.canonical_events (
    event_id text primary key,
    workspace_id text null references public.workspaces(workspace_id) on delete set null,
    aggregate_type text not null,
    aggregate_id text not null,
    event_type text not null,
    schema_version integer not null check (schema_version >= 1),
    occurred_at double precision not null,
    causation_id text null,
    correlation_id text null,
    experiment_id text null,
    actor text null,
    source text not null,
    payload jsonb not null default '{}'::jsonb,
    metadata jsonb not null default '{}'::jsonb,
    created_at timestamptz not null default now()
);
create index if not exists canonical_events_workspace_occurred_idx on public.canonical_events (workspace_id, occurred_at, event_id);
create index if not exists canonical_events_event_type_idx on public.canonical_events (event_type);
create index if not exists canonical_events_aggregate_idx on public.canonical_events (aggregate_type, aggregate_id);
create index if not exists canonical_events_correlation_idx on public.canonical_events (correlation_id) where correlation_id is not null;

-- Cached normalized public observations; each row may be linked to a canonical
-- event but must never be interpreted as demand, profit, or launch authority.
create table if not exists public.public_signals (
    signal_id text primary key,
    workspace_id text null references public.workspaces(workspace_id) on delete set null,
    event_id text null references public.canonical_events(event_id) on delete set null,
    source text not null,
    source_url text not null,
    observed_at double precision not null,
    query text not null,
    title text not null,
    description text not null default '',
    score double precision null,
    rank integer null,
    evidence_url text null,
    attribution jsonb not null default '{}'::jsonb,
    quality jsonb not null default '{}'::jsonb,
    payload jsonb not null default '{}'::jsonb,
    created_at timestamptz not null default now()
);
create index if not exists public_signals_workspace_observed_idx on public.public_signals (workspace_id, observed_at desc);
create index if not exists public_signals_source_query_idx on public.public_signals (source, query);

-- Advisory artifacts/reports stay separate from events for read views. They do
-- not grant launch, spend, publishing, order, payment, or provider authority.
create table if not exists public.artifacts (
    artifact_id text primary key,
    workspace_id text null references public.workspaces(workspace_id) on delete set null,
    artifact_type text not null,
    title text not null default '',
    status text not null default 'advisory',
    source_event_id text null references public.canonical_events(event_id) on delete set null,
    payload jsonb not null default '{}'::jsonb,
    metadata jsonb not null default '{}'::jsonb,
    created_at timestamptz not null default now()
);
create index if not exists artifacts_workspace_type_idx on public.artifacts (workspace_id, artifact_type, created_at desc);

create table if not exists public.run_envelopes (
    run_id text primary key,
    workspace_id text null references public.workspaces(workspace_id) on delete set null,
    run_type text not null,
    status text not null,
    correlation_id text null,
    payload jsonb not null default '{}'::jsonb,
    metadata jsonb not null default '{}'::jsonb,
    created_at timestamptz not null default now()
);
create index if not exists run_envelopes_workspace_created_idx on public.run_envelopes (workspace_id, created_at desc);

create table if not exists public.source_readiness (
    readiness_id text primary key,
    workspace_id text null references public.workspaces(workspace_id) on delete set null,
    source text not null,
    status text not null,
    requires_credentials boolean not null default false,
    network_required boolean not null default false,
    report jsonb not null default '{}'::jsonb,
    observed_at timestamptz not null default now()
);
create index if not exists source_readiness_workspace_source_idx on public.source_readiness (workspace_id, source, observed_at desc);

-- MVP data should not be exposed anonymously by accident. RLS is enabled now;
-- workspace/user policies belong to the later Auth/RLS promotion after an
-- authenticated workspace model is implemented and tested.
alter table public.workspaces enable row level security;
alter table public.canonical_events enable row level security;
alter table public.public_signals enable row level security;
alter table public.artifacts enable row level security;
alter table public.run_envelopes enable row level security;
alter table public.source_readiness enable row level security;

-- No anon/authenticated policies are created in this foundation. Server-side
-- service-role access is an operator deployment responsibility; never expose a
-- service-role key to Vercel/frontend environment variables.
