-- Fix mutable search_path warning on set_updated_at.
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

-- touch_conversation_on_message should only ever run as a trigger, not
-- be directly callable via the REST RPC endpoint by anon/authenticated.
revoke execute on function public.touch_conversation_on_message() from public, anon, authenticated;
