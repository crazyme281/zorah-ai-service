-- Knowledge the learned model picks up from chat (see backend/learned/).
-- One row per remembered standalone question + the vetted answer. Kept here
-- instead of on Render's disk so it survives every deploy.
--
-- Privacy: no user ids and no raw sessions - `sessions` holds short one-way
-- hashes only. Service role only: RLS is on with no policies, so the app's
-- own (anon / signed-in) keys can neither read nor write this table.

create table if not exists public.learned_chat_entries (
    id text primary key,
    questions jsonb not null default '[]'::jsonb,
    answer text not null,
    provider text,
    source text not null default 'provider_generated',
    sessions jsonb not null default '[]'::jsonb,
    status text not null default 'pending'
        check (status in ('pending', 'queued', 'active', 'rejected')),
    reason text,
    first_seen bigint,
    last_seen bigint,
    updated_at timestamptz not null default now()
);

create index if not exists learned_chat_entries_status_idx
    on public.learned_chat_entries (status);

alter table public.learned_chat_entries enable row level security;