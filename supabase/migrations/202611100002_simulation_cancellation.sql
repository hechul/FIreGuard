-- Invalidate an outstanding SIM command without touching REAL telemetry.
-- A claimed command remains claimed until the Pi reports that it has stopped;
-- this prevents a replacement from running concurrently on the same Uno.
begin;
alter table public.simulation_commands
    add column if not exists cancel_requested boolean not null default false;

create or replace function public.sim_command_cancel(p_device_id text, p_id uuid)
returns jsonb language plpgsql security definer set search_path = pg_catalog, public as $$
declare c public.simulation_commands%rowtype;
begin
  if p_device_id is null or p_device_id !~ '^[A-Za-z0-9_-]{1,64}$' or p_id is null then
    raise exception 'Invalid command' using errcode='22023';
  end if;
  select * into c from public.simulation_commands
    where device_id=p_device_id and id=p_id for update;
  if not found then
    return jsonb_build_object('id',p_id,'status','not_found','cancelRequested',false);
  end if;
  if c.status='pending' then
    update public.simulation_commands set status='rejected', cancel_requested=true,
      completed_at=now(), result=jsonb_build_object('status','rejected','message','운영자가 시험을 취소했습니다.',
                                                   'routeNodes','[]'::jsonb,'ledCommandAck',false)
      where id=c.id returning * into c;
  elsif c.status='claimed' then
    update public.simulation_commands set cancel_requested=true where id=c.id returning * into c;
  end if;
  return jsonb_build_object('id',c.id,'status',c.status,'cancelRequested',c.cancel_requested);
end $$;

-- The claim token prevents one device or stale worker from validating another
-- worker's lease. Missing, expired, or malformed commands always fail closed.
create or replace function public.sim_command_check(p_device_id text, p_id uuid, p_claim_token uuid)
returns jsonb language plpgsql security definer set search_path = pg_catalog, public as $$
declare c public.simulation_commands%rowtype;
begin
  if p_device_id is null or p_device_id !~ '^[A-Za-z0-9_-]{1,64}$' or p_id is null or p_claim_token is null then
    raise exception 'Invalid command' using errcode='22023';
  end if;
  select * into c from public.simulation_commands
    where device_id=p_device_id and id=p_id and claim_token=p_claim_token;
  if not found then return jsonb_build_object('active',false,'cancelRequested',true); end if;
  return jsonb_build_object('active',c.status='claimed' and not c.cancel_requested and c.expires_at > now(),
                            'cancelRequested',c.cancel_requested);
end $$;

-- Preserve the existing result contract, but never let a cancelled claimed
-- command be recorded as a successful completed command.
create or replace function public.sim_command_complete(p_device_id text, p_id uuid, p_claim_token uuid, p_result jsonb)
returns jsonb language plpgsql security definer set search_path = pg_catalog, public as $$
declare c public.simulation_commands%rowtype; s text;
begin
  if p_device_id is null or p_id is null or p_claim_token is null or jsonb_typeof(p_result) is distinct from 'object' or octet_length(p_result::text) > 16384 then
    raise exception 'Invalid result' using errcode='22023';
  end if;
  s := p_result->>'status';
  if s is null or s not in ('completed','rejected','failed') or jsonb_typeof(p_result->'message') is distinct from 'string' or jsonb_typeof(p_result->'routeNodes') is distinct from 'array' or jsonb_typeof(p_result->'ledCommandAck') is distinct from 'boolean' then
    raise exception 'Invalid result' using errcode='22023';
  end if;
  select * into c from public.simulation_commands where id=p_id and device_id=p_device_id for update;
  if not found or c.claim_token is distinct from p_claim_token then raise exception 'Invalid claim' using errcode='22023'; end if;
  if c.cancel_requested and s='completed' then
    s := 'failed';
    p_result := jsonb_set(p_result, '{status}', '"failed"'::jsonb);
    p_result := jsonb_set(p_result, '{message}', to_jsonb('시험 취소됨: ' || (p_result->>'message')));
  end if;
  if c.status in ('completed','rejected','failed') and c.result = p_result then
    return jsonb_build_object('id',c.id,'status',c.status);
  end if;
  if c.status <> 'claimed' or c.expires_at <= now() then raise exception 'Claim expired' using errcode='22023'; end if;
  update public.simulation_commands set status=s, result=p_result, completed_at=now() where id=p_id;
  return jsonb_build_object('id',p_id,'status',s);
end $$;
revoke all on function public.sim_command_cancel(text,uuid) from public, anon, authenticated;
revoke all on function public.sim_command_check(text,uuid,uuid) from public, anon, authenticated;
revoke all on function public.sim_command_complete(text,uuid,uuid,jsonb) from public, anon, authenticated;
grant execute on function public.sim_command_cancel(text,uuid) to service_role;
grant execute on function public.sim_command_check(text,uuid,uuid) to service_role;
grant execute on function public.sim_command_complete(text,uuid,uuid,jsonb) to service_role;
commit;
