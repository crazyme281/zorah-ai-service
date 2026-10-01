-- Zorah Training: one row per course a learner starts. The whole
-- generated path and the learner's progress live in jsonb so a course can
-- be resumed exactly where it was left (cached lesson / task / quiz
-- content included) without regenerating anything.

create table public.training_courses (
    id uuid primary key default gen_random_uuid(),
    user_id uuid not null default auth.uid() references auth.users(id) on delete cascade,
    subject text not null check (char_length(subject) between 1 and 200),
    is_coding boolean not null default false,
    language text,                                   -- coding courses only
    level text,                                      -- what the learner picked at the start
    stage text not null default 'basic'
        check (stage in ('basic', 'intermediate', 'advanced', 'pro')),
    title text not null,
    curriculum jsonb not null,                       -- current stage's modules / lessons (+ roadmap)
    progress jsonb not null default '{"lessons": {}, "history": []}'::jsonb,
    current_lesson_id text,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

create index training_courses_user_recent_idx
    on public.training_courses (user_id, updated_at desc);

alter table public.training_courses enable row level security;

-- Go and Pro only. SECURITY DEFINER so the check works whatever RLS
-- policies profiles itself has; plpgsql so the table isn't resolved until
-- the function is called. Mirrors backend/access/tiers.py
-- (can_use_teaching). The backend re-checks the live tier (including
-- subscription expiry) before generating anything, so this is the second
-- layer, not the only one.
create or replace function public.has_training_access()
returns boolean
language plpgsql
stable
security definer
set search_path = public
as $$
begin
    return exists (
        select 1 from public.profiles p
        where p.user_id = auth.uid() and p.tier in ('GO', 'PRO')
    );
end;
$$;

revoke all on function public.has_training_access() from public;
grant execute on function public.has_training_access() to authenticated;

-- Learners can always see and delete their own courses (even after a plan
-- lapses); creating and updating needs an active Go/Pro plan.
create policy "training_courses_select_own" on public.training_courses
    for select to authenticated using (user_id = auth.uid());

create policy "training_courses_insert_paid" on public.training_courses
    for insert to authenticated
    with check (user_id = auth.uid() and public.has_training_access());

create policy "training_courses_update_paid" on public.training_courses
    for update to authenticated
    using (user_id = auth.uid() and public.has_training_access())
    with check (user_id = auth.uid() and public.has_training_access());

create policy "training_courses_delete_own" on public.training_courses
    for delete to authenticated using (user_id = auth.uid());

create or replace function public.training_courses_touch()
returns trigger
language plpgsql
set search_path = public
as $$
begin
    new.updated_at = now();
    return new;
end;
$$;

create trigger training_courses_touch_updated_at
    before update on public.training_courses
    for each row execute function public.training_courses_touch();
