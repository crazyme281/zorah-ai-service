-- Projects: an optional grouping/folder for chats.
create table public.projects (
    id uuid primary key default gen_random_uuid(),
    user_id uuid not null default auth.uid() references auth.users(id) on delete cascade,
    name text not null default 'New Project',
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

-- Conversations: one row per chat shown in the sidebar. project_id is
-- nullable so a chat can exist standalone, outside any project.
create table public.conversations (
    id uuid primary key default gen_random_uuid(),
    user_id uuid not null default auth.uid() references auth.users(id) on delete cascade,
    project_id uuid references public.projects(id) on delete set null,
    title text not null default 'New Chat',
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    last_message_at timestamptz
);

-- Messages: individual turns within a conversation. user_id is
-- denormalized here (rather than joining through conversations) so the
-- RLS check on every message row is a cheap direct comparison.
create table public.messages (
    id uuid primary key default gen_random_uuid(),
    conversation_id uuid not null references public.conversations(id) on delete cascade,
    user_id uuid not null default auth.uid() references auth.users(id) on delete cascade,
    role text not null check (role in ('user', 'assistant', 'system')),
    content text not null,
    provider text,   -- internal routing info (which AI provider answered) - not for display
    intent text,     -- internal routing info (classified intent) - not for display
    created_at timestamptz not null default now()
);

-- Indexes for the sidebar's main queries: list a user's chats ordered
-- by recency, list a project's chats, load a conversation's messages.
create index conversations_user_recency_idx
    on public.conversations (user_id, coalesce(last_message_at, updated_at) desc);
create index conversations_project_idx
    on public.conversations (project_id);
create index messages_conversation_idx
    on public.messages (conversation_id, created_at);

-- Keep updated_at current on edit.
create or replace function public.set_updated_at()
returns trigger
language plpgsql
set search_path = public
as $$
begin
    new.updated_at = now();
    return new;
end;
$$;

create trigger projects_set_updated_at
    before update on public.projects
    for each row execute function public.set_updated_at();

create trigger conversations_set_updated_at
    before update on public.conversations
    for each row execute function public.set_updated_at();

-- Bump the parent conversation's timestamps whenever a new message
-- lands, so the sidebar's recency ordering stays correct without the
-- frontend having to do it manually. security definer + fixed
-- search_path so this runs reliably regardless of caller RLS.
create or replace function public.touch_conversation_on_message()
returns trigger
language plpgsql
security definer
set search_path = public
as $$
begin
    update public.conversations
    set last_message_at = new.created_at,
        updated_at = now()
    where id = new.conversation_id;
    return new;
end;
$$;

create trigger messages_touch_conversation
    after insert on public.messages
    for each row execute function public.touch_conversation_on_message();

-- Row Level Security: every table restricted to auth.uid() = user_id.
alter table public.projects enable row level security;
alter table public.conversations enable row level security;
alter table public.messages enable row level security;

create policy "select own projects" on public.projects
    for select using (user_id = auth.uid());
create policy "insert own projects" on public.projects
    for insert with check (user_id = auth.uid());
create policy "update own projects" on public.projects
    for update using (user_id = auth.uid()) with check (user_id = auth.uid());
create policy "delete own projects" on public.projects
    for delete using (user_id = auth.uid());

create policy "select own conversations" on public.conversations
    for select using (user_id = auth.uid());
create policy "insert own conversations" on public.conversations
    for insert with check (user_id = auth.uid());
create policy "update own conversations" on public.conversations
    for update using (user_id = auth.uid()) with check (user_id = auth.uid());
create policy "delete own conversations" on public.conversations
    for delete using (user_id = auth.uid());

create policy "select own messages" on public.messages
    for select using (user_id = auth.uid());
create policy "insert own messages" on public.messages
    for insert with check (user_id = auth.uid());
create policy "update own messages" on public.messages
    for update using (user_id = auth.uid()) with check (user_id = auth.uid());
create policy "delete own messages" on public.messages
    for delete using (user_id = auth.uid());
