-- Multiple simulated fires, isolated from REAL telemetry. Requires migration 002.
-- A legacy Pi can ONLY claim a single-fire command. Multi-fire commands require
-- the v2 claim RPC; deploy an explicitly versioned claim endpoint and Pi together.
begin;
alter table public.simulation_commands add column if not exists fire_nodes text[];

create or replace function public.sim_command_create_v2(p_id uuid, p_device_id text, p_start_node text, p_fire_nodes text[])
returns jsonb language plpgsql security definer set search_path = pg_catalog, public as $$
declare c public.simulation_commands%rowtype; nodes text[];
begin
  if p_id is null or p_device_id is null or p_device_id !~ '^[A-Za-z0-9_-]{1,64}$'
     or p_start_node is null or p_start_node !~ '^N[0-9]{1,3}$'
     or p_fire_nodes is null or cardinality(p_fire_nodes) not between 1 and 11
     or array_ndims(p_fire_nodes) is distinct from 1
     or exists (select 1 from unnest(p_fire_nodes) n where n is null or n <> all(array['N20','N2','N3','N4','N5','N6','N7','N8','N9','N10','N11']))
     or cardinality(p_fire_nodes) <> (select count(distinct n) from unnest(p_fire_nodes) n) then
    raise exception 'Invalid command' using errcode='22023';
  end if;
  -- Stable ordering makes retrying an identical set of fires idempotent.
  select array_agg(n order by n) into nodes from unnest(p_fire_nodes) n;
  perform pg_advisory_xact_lock(hashtextextended('sim:' || p_device_id, 0));
  select * into c from public.simulation_commands where id=p_id;
  if found then
    if c.device_id <> p_device_id or c.start_node <> p_start_node
       or coalesce(c.fire_nodes, array[c.fire_node]) <> nodes then
      raise exception 'Conflicting command ID' using errcode='22023';
    end if;
  else
    update public.simulation_commands set status='expired'
      where device_id=p_device_id and status in ('pending','claimed') and expires_at <= now();
    if exists(select 1 from public.simulation_commands where device_id=p_device_id and status in ('pending','claimed')) then
      raise exception 'A command is already in progress' using errcode='55000';
    end if;
    insert into public.simulation_commands(id,device_id,start_node,fire_node,fire_nodes,expires_at)
      values(p_id,p_device_id,p_start_node,nodes[1],nodes,now()+interval '30 seconds') returning * into c;
  end if;
  return jsonb_build_object('id',c.id,'status',case when c.status in ('pending','claimed') and c.expires_at <= now() then 'expired' else c.status end,'expiresAt',c.expires_at);
end $$;

-- Preserve the old RPC but never deliver a multi-fire command to an old Pi.
create or replace function public.sim_command_claim(p_device_id text)
returns jsonb language plpgsql security definer set search_path = pg_catalog, public as $$
declare c public.simulation_commands%rowtype;
begin
  if p_device_id is null or p_device_id !~ '^[A-Za-z0-9_-]{1,64}$' then raise exception 'Invalid device' using errcode='22023'; end if;
  perform pg_advisory_xact_lock(hashtextextended('sim:' || p_device_id, 0));
  update public.simulation_commands set status='expired' where device_id=p_device_id and status in ('pending','claimed') and expires_at <= now();
  select * into c from public.simulation_commands where device_id=p_device_id and status='pending' and expires_at > now()
    and cardinality(coalesce(fire_nodes, array[fire_node])) = 1 order by created_at limit 1 for update;
  if not found then return null; end if;
  update public.simulation_commands set status='claimed',claim_token=gen_random_uuid(),claimed_at=now() where id=c.id returning * into c;
  return jsonb_build_object('id',c.id,'startNode',c.start_node,'fireNode',c.fire_node,'expiresAt',c.expires_at,'claimToken',c.claim_token);
end $$;

create or replace function public.sim_command_claim_v2(p_device_id text)
returns jsonb language plpgsql security definer set search_path = pg_catalog, public as $$
declare c public.simulation_commands%rowtype;
begin
  if p_device_id is null or p_device_id !~ '^[A-Za-z0-9_-]{1,64}$' then raise exception 'Invalid device' using errcode='22023'; end if;
  perform pg_advisory_xact_lock(hashtextextended('sim:' || p_device_id, 0));
  update public.simulation_commands set status='expired' where device_id=p_device_id and status in ('pending','claimed') and expires_at <= now();
  select * into c from public.simulation_commands where device_id=p_device_id and status='pending' and expires_at > now() order by created_at limit 1 for update;
  if not found then return null; end if;
  update public.simulation_commands set status='claimed',claim_token=gen_random_uuid(),claimed_at=now() where id=c.id returning * into c;
  return jsonb_build_object('id',c.id,'startNode',c.start_node,
      'fireNode',case when cardinality(coalesce(c.fire_nodes,array[c.fire_node])) > 1 then '__MULTI__' else c.fire_node end,
      'fireNodes',coalesce(c.fire_nodes,array[c.fire_node]),'expiresAt',c.expires_at,'claimToken',c.claim_token);
end $$;

create or replace function public.sim_command_latest(p_device_id text)
returns jsonb language plpgsql security definer set search_path = pg_catalog, public as $$
declare c public.simulation_commands%rowtype;
begin
  if p_device_id is null or p_device_id !~ '^[A-Za-z0-9_-]{1,64}$' then raise exception 'Invalid device' using errcode='22023'; end if;
  select * into c from public.simulation_commands where device_id=p_device_id order by created_at desc limit 1;
  if not found then return null; end if;
  return jsonb_build_object('id',c.id,'startNode',c.start_node,'fireNode',c.fire_node,
      'fireNodes',coalesce(c.fire_nodes,array[c.fire_node]),'expiresAt',c.expires_at,
      'status',case when c.status in ('pending','claimed') and c.expires_at <= now() then 'expired' else c.status end,'result',c.result);
end $$;
revoke all on function public.sim_command_create_v2(uuid,text,text,text[]) from public, anon, authenticated;
revoke all on function public.sim_command_claim(text) from public, anon, authenticated;
revoke all on function public.sim_command_claim_v2(text) from public, anon, authenticated;
revoke all on function public.sim_command_latest(text) from public, anon, authenticated;
grant execute on function public.sim_command_create_v2(uuid,text,text,text[]) to service_role;
grant execute on function public.sim_command_claim(text) to service_role;
grant execute on function public.sim_command_claim_v2(text) to service_role;
grant execute on function public.sim_command_latest(text) to service_role;
commit;
