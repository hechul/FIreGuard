-- REAL clear requests are private commands, not fire-state writes. Only the Pi
-- can decide whether a sensor's latch is safe to clear and report the result.
-- A claimed request is NEVER re-delivered or automatically expired: if the Pi
-- crashes before ACK, an operator must reconcile its durable execution ledger.
begin;
create table if not exists public.real_fire_clear_commands (
  id uuid primary key,
  device_id text not null check (device_id ~ '^[A-Za-z0-9_-]{1,64}$'),
  sensor_ids text[] not null,
  created_at timestamptz not null default now(),
  expires_at timestamptz not null,
  status text not null default 'pending' check (status in ('pending','claimed','completed','rejected','failed','expired')),
  claim_token uuid,
  claimed_at timestamptz,
  completed_at timestamptz,
  result jsonb
);
alter table public.real_fire_clear_commands enable row level security;
revoke all on public.real_fire_clear_commands from public, anon, authenticated;
create index if not exists real_clear_device_time_idx on public.real_fire_clear_commands(device_id, created_at desc);

create or replace function public.real_clear_create(p_id uuid, p_device_id text, p_sensor_ids text[])
returns jsonb language plpgsql security definer set search_path = pg_catalog, public as $$
declare c public.real_fire_clear_commands%rowtype; v_sensors text[];
begin
  if p_id is null or p_device_id is null or p_device_id !~ '^[A-Za-z0-9_-]{1,64}$'
     or p_sensor_ids is null or cardinality(p_sensor_ids) not between 1 and 11
     or exists(select 1 from unnest(p_sensor_ids) s where s is null or s !~ '^FLM-(0[1-9]|1[01])$')
     or (select count(distinct s) from unnest(p_sensor_ids) s) <> cardinality(p_sensor_ids) then
    raise exception 'Invalid clear command' using errcode='22023';
  end if;
  select array_agg(s order by s) into v_sensors from unnest(p_sensor_ids) s;
  perform pg_advisory_xact_lock(hashtextextended('real-clear:' || p_device_id, 0));
  select * into c from public.real_fire_clear_commands where id=p_id;
  if found then
    if c.device_id <> p_device_id or c.sensor_ids <> v_sensors then
      raise exception 'Conflicting command ID' using errcode='22023';
    end if;
  else
    update public.real_fire_clear_commands set status='expired'
      where device_id=p_device_id and status='pending' and expires_at <= now();
    if exists(select 1 from public.real_fire_clear_commands where device_id=p_device_id and status in ('pending','claimed')) then
      raise exception 'Unresolved clear request' using errcode='55000';
    end if;
    insert into public.real_fire_clear_commands(id,device_id,sensor_ids,expires_at)
      values(p_id,p_device_id,v_sensors,now()+interval '60 seconds') returning * into c;
  end if;
  return jsonb_build_object('id',c.id,'status',case when c.status='pending' and c.expires_at <= now() then 'expired' else c.status end,'expiresAt',c.expires_at);
end $$;

create or replace function public.real_clear_claim(p_device_id text)
returns jsonb language plpgsql security definer set search_path = pg_catalog, public as $$
declare c public.real_fire_clear_commands%rowtype;
begin
  if p_device_id is null or p_device_id !~ '^[A-Za-z0-9_-]{1,64}$' then raise exception 'Invalid device' using errcode='22023'; end if;
  perform pg_advisory_xact_lock(hashtextextended('real-clear:' || p_device_id, 0));
  update public.real_fire_clear_commands set status='expired'
    where device_id=p_device_id and status='pending' and expires_at <= now();
  -- No new command while a previously claimed command has an unknown outcome.
  if exists(select 1 from public.real_fire_clear_commands where device_id=p_device_id and status='claimed') then return null; end if;
  select * into c from public.real_fire_clear_commands
    where device_id=p_device_id and status='pending' and expires_at > now()
    order by created_at limit 1 for update;
  if not found then return null; end if;
  update public.real_fire_clear_commands set status='claimed', claim_token=gen_random_uuid(), claimed_at=now()
    where id=c.id returning * into c;
  return jsonb_build_object('id',c.id,'sensorIds',c.sensor_ids,'expiresAt',c.expires_at,'claimToken',c.claim_token);
end $$;

create or replace function public.real_clear_complete(p_device_id text, p_id uuid, p_claim_token uuid, p_result jsonb)
returns jsonb language plpgsql security definer set search_path = pg_catalog, public as $$
declare c public.real_fire_clear_commands%rowtype; s text;
begin
  if p_device_id is null or p_id is null or p_claim_token is null
     or jsonb_typeof(p_result) is distinct from 'object' or octet_length(p_result::text) > 8192 then
    raise exception 'Invalid result' using errcode='22023';
  end if;
  s := p_result->>'status';
  if s is null or s not in ('completed','rejected','failed')
     or jsonb_typeof(p_result->'message') is distinct from 'string'
     or jsonb_typeof(p_result->'clearedSensorIds') is distinct from 'array'
     or jsonb_typeof(p_result->'rejectedSensorIds') is distinct from 'array' then
    raise exception 'Invalid result' using errcode='22023';
  end if;
  select * into c from public.real_fire_clear_commands where id=p_id and device_id=p_device_id for update;
  if not found or c.claim_token is distinct from p_claim_token then raise exception 'Invalid claim' using errcode='22023'; end if;
  if exists(select 1 from jsonb_array_elements(p_result->'clearedSensorIds') v where jsonb_typeof(v) <> 'string' or not ((v #>> '{}') = any(c.sensor_ids)))
     or exists(select 1 from jsonb_array_elements(p_result->'rejectedSensorIds') v where jsonb_typeof(v) <> 'string' or not ((v #>> '{}') = any(c.sensor_ids))) then
    raise exception 'Unexpected sensor in result' using errcode='22023';
  end if;
  if (select count(*) from (select jsonb_array_elements_text(p_result->'clearedSensorIds') as sensor
                             union all select jsonb_array_elements_text(p_result->'rejectedSensorIds')) x)
     <> (select count(distinct sensor) from (select jsonb_array_elements_text(p_result->'clearedSensorIds') as sensor
                                              union all select jsonb_array_elements_text(p_result->'rejectedSensorIds')) x)
     or (s='completed' and (jsonb_array_length(p_result->'clearedSensorIds') <> cardinality(c.sensor_ids)
                            or jsonb_array_length(p_result->'rejectedSensorIds') <> 0))
     or (s='rejected' and (jsonb_array_length(p_result->'clearedSensorIds') <> 0
                           or jsonb_array_length(p_result->'rejectedSensorIds') <> cardinality(c.sensor_ids))) then
    raise exception 'Inconsistent clear result' using errcode='22023';
  end if;
  if c.status in ('completed','rejected','failed') and c.result = p_result then
    return jsonb_build_object('id',c.id,'status',c.status);
  end if;
  if c.status <> 'claimed' then raise exception 'Invalid command state' using errcode='22023'; end if;
  -- ACK can arrive after the execute deadline: unknown is safer than replay.
  update public.real_fire_clear_commands set status=s, result=p_result, completed_at=now() where id=p_id;
  return jsonb_build_object('id',p_id,'status',s);
end $$;

create or replace function public.real_clear_latest(p_device_id text)
returns jsonb language plpgsql security definer set search_path = pg_catalog, public as $$
declare c public.real_fire_clear_commands%rowtype;
begin
  if p_device_id is null or p_device_id !~ '^[A-Za-z0-9_-]{1,64}$' then raise exception 'Invalid device' using errcode='22023'; end if;
  select * into c from public.real_fire_clear_commands where device_id=p_device_id order by created_at desc limit 1;
  if not found then return null; end if;
  return jsonb_build_object('id',c.id,'sensorIds',c.sensor_ids,'expiresAt',c.expires_at,
    'status',case when c.status='pending' and c.expires_at <= now() then 'expired' else c.status end,'result',c.result);
end $$;
revoke all on function public.real_clear_create(uuid,text,text[]) from public, anon, authenticated;
revoke all on function public.real_clear_claim(text) from public, anon, authenticated;
revoke all on function public.real_clear_complete(text,uuid,uuid,jsonb) from public, anon, authenticated;
revoke all on function public.real_clear_latest(text) from public, anon, authenticated;
grant execute on function public.real_clear_create(uuid,text,text[]) to service_role;
grant execute on function public.real_clear_claim(text) to service_role;
grant execute on function public.real_clear_complete(text,uuid,uuid,jsonb) to service_role;
grant execute on function public.real_clear_latest(text) to service_role;
commit;
