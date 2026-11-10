-- Isolated, short-lived SIM commands. Never writes device_state or events.
begin;
create table if not exists public.simulation_commands (
    id uuid primary key,
    device_id text not null check (device_id ~ '^[A-Za-z0-9_-]{1,64}$'),
    start_node text not null check (start_node ~ '^N[0-9]{1,3}$'),
    fire_node text not null check (fire_node ~ '^N[0-9]{1,3}$'),
    created_at timestamptz not null default now(),
    expires_at timestamptz not null,
    status text not null default 'pending' check (status in ('pending', 'claimed', 'completed', 'rejected', 'failed', 'expired')),
    claim_token uuid,
    claimed_at timestamptz,
    completed_at timestamptz,
    result jsonb
);
alter table public.simulation_commands enable row level security;
revoke all on public.simulation_commands from public, anon, authenticated;
create index if not exists sim_commands_device_time_idx on public.simulation_commands(device_id, created_at desc);

create or replace function public.sim_command_create(p_id uuid, p_device_id text, p_start_node text, p_fire_node text)
returns jsonb language plpgsql security definer set search_path = pg_catalog, public as $$
declare c public.simulation_commands%rowtype;
begin
  if p_id is null or p_device_id !~ '^[A-Za-z0-9_-]{1,64}$' or p_start_node !~ '^N[0-9]{1,3}$' or p_fire_node !~ '^N[0-9]{1,3}$' then
    raise exception 'Invalid command' using errcode='22023';
  end if;
  perform pg_advisory_xact_lock(hashtextextended('sim:' || p_device_id, 0));
  select * into c from public.simulation_commands where id=p_id;
  if found then
    if c.device_id <> p_device_id or c.start_node <> p_start_node or c.fire_node <> p_fire_node then
      raise exception 'Conflicting command ID' using errcode='22023';
    end if;
  else
    update public.simulation_commands set status='expired' where device_id=p_device_id and status in ('pending','claimed') and expires_at <= now();
    if exists(select 1 from public.simulation_commands where device_id=p_device_id and status in ('pending','claimed')) then
      raise exception 'A command is already in progress' using errcode='55000';
    end if;
    insert into public.simulation_commands(id,device_id,start_node,fire_node,expires_at)
      values(p_id,p_device_id,p_start_node,p_fire_node,now()+interval '30 seconds') returning * into c;
  end if;
  return jsonb_build_object('id',c.id,'status',case when c.status in ('pending','claimed') and c.expires_at <= now() then 'expired' else c.status end,'expiresAt',c.expires_at);
end $$;

create or replace function public.sim_command_claim(p_device_id text)
returns jsonb language plpgsql security definer set search_path = pg_catalog, public as $$
declare c public.simulation_commands%rowtype;
begin
  if p_device_id is null or p_device_id !~ '^[A-Za-z0-9_-]{1,64}$' then raise exception 'Invalid device' using errcode='22023'; end if;
  perform pg_advisory_xact_lock(hashtextextended('sim:' || p_device_id, 0));
  update public.simulation_commands set status='expired' where device_id=p_device_id and status in ('pending','claimed') and expires_at <= now();
  select * into c from public.simulation_commands where device_id=p_device_id and status='pending' and expires_at > now() order by created_at limit 1 for update;
  if not found then return null; end if;
  update public.simulation_commands set status='claimed', claim_token=gen_random_uuid(), claimed_at=now() where id=c.id returning * into c;
  return jsonb_build_object('id',c.id,'startNode',c.start_node,'fireNode',c.fire_node,'expiresAt',c.expires_at,'claimToken',c.claim_token);
end $$;

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
  if c.status in ('completed','rejected','failed') and c.result = p_result then
    return jsonb_build_object('id',c.id,'status',c.status);
  end if;
  if c.status <> 'claimed' or c.expires_at <= now() then raise exception 'Claim expired' using errcode='22023'; end if;
  update public.simulation_commands set status=s, result=p_result, completed_at=now() where id=p_id;
  return jsonb_build_object('id',p_id,'status',s);
end $$;

create or replace function public.sim_command_latest(p_device_id text)
returns jsonb language plpgsql security definer set search_path = pg_catalog, public as $$
declare c public.simulation_commands%rowtype;
begin
  if p_device_id is null or p_device_id !~ '^[A-Za-z0-9_-]{1,64}$' then raise exception 'Invalid device' using errcode='22023'; end if;
  select * into c from public.simulation_commands where device_id=p_device_id order by created_at desc limit 1;
  if not found then return null; end if;
  return jsonb_build_object('id',c.id,'startNode',c.start_node,'fireNode',c.fire_node,'expiresAt',c.expires_at,
      'status',case when c.status in ('pending','claimed') and c.expires_at <= now() then 'expired' else c.status end,'result',c.result);
end $$;
revoke all on function public.sim_command_create(uuid,text,text,text) from public, anon, authenticated;
revoke all on function public.sim_command_claim(text) from public, anon, authenticated;
revoke all on function public.sim_command_complete(text,uuid,uuid,jsonb) from public, anon, authenticated;
revoke all on function public.sim_command_latest(text) from public, anon, authenticated;
grant execute on function public.sim_command_create(uuid,text,text,text) to service_role;
grant execute on function public.sim_command_claim(text) to service_role;
grant execute on function public.sim_command_complete(text,uuid,uuid,jsonb) to service_role;
grant execute on function public.sim_command_latest(text) to service_role;
commit;
