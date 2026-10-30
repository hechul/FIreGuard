-- FireGuard: public read-only capstone monitoring, server-only ingestion.
-- Telemetry contains operational data intended for the public dashboard.
-- NEVER include device tokens or other secrets in telemetry/events.
begin;

create table if not exists public.sensors (
    mapping_version text not null,
    id text not null,
    node_id text not null,
    bcm integer not null check (bcm between 0 and 27),
    physical integer not null check (physical between 1 and 40),
    name text not null,
    primary key (mapping_version, id),
    unique (mapping_version, bcm),
    unique (mapping_version, physical)
);

create table if not exists public.device_state (
    device_id text primary key check (device_id ~ '^[A-Za-z0-9_-]{1,64}$'),
    boot_id uuid not null,
    sequence bigint not null check (sequence >= 0),
    observed_at timestamptz not null,
    received_at timestamptz not null default now(),
    mapping_version text not null,
    telemetry jsonb not null check (jsonb_typeof(telemetry) = 'object')
);

create table if not exists public.events (
    id bigint generated always as identity primary key,
    device_id text not null references public.device_state(device_id),
    boot_id uuid not null,
    sequence bigint not null check (sequence >= 0),
    type text not null check (type in ('FIRE', 'CLEAR', 'LED')),
    observed_at timestamptz not null,
    received_at timestamptz not null default now(),
    payload jsonb not null
);
create index if not exists events_device_id_id_idx on public.events (device_id, id desc);

insert into public.sensors (mapping_version, id, node_id, bcm, physical, name) values
('flame-20261030-v1','FLM-01','N20',23,16,'추가 노드 N20 불꽃센서'),
('flame-20261030-v1','FLM-02','N2',27,13,'5관 앞 공통 복도 분기점 불꽃센서'),
('flame-20261030-v1','FLM-03','N3',22,15,'4관 좌측 완강기 불꽃센서'),
('flame-20261030-v1','FLM-04','N4',5,29,'4관 출입구 복도 분기점 불꽃센서'),
('flame-20261030-v1','FLM-05','N5',6,31,'화장실 1 임시 대피지점 불꽃센서'),
('flame-20261030-v1','FLM-06','N6',13,33,'화장실 2 임시 대피지점 불꽃센서'),
('flame-20261030-v1','FLM-07','N7',19,35,'서측 비상구 앞 불꽃센서'),
('flame-20261030-v1','FLM-08','N8',12,32,'중앙복도 서측 불꽃센서'),
('flame-20261030-v1','FLM-09','N9',16,36,'중앙복도 동측 불꽃센서'),
('flame-20261030-v1','FLM-10','N10',20,38,'동측 비상구 앞 불꽃센서'),
('flame-20261030-v1','FLM-11','N11',21,40,'추가 노드 N11 불꽃센서')
on conflict (mapping_version, id) do nothing;

alter table public.sensors enable row level security;
alter table public.device_state enable row level security;
alter table public.events enable row level security;
-- Read-only public monitoring. Change these policies before storing private data.
drop policy if exists sensors_public_read on public.sensors;
create policy sensors_public_read on public.sensors for select to anon, authenticated using (true);
drop policy if exists state_public_read on public.device_state;
create policy state_public_read on public.device_state for select to anon, authenticated using (true);
drop policy if exists events_public_read on public.events;
create policy events_public_read on public.events for select to anon, authenticated using (true);
revoke all on public.sensors, public.device_state, public.events from anon, authenticated;
grant select on public.sensors, public.device_state, public.events to anon, authenticated;
grant all on public.sensors, public.device_state, public.events to service_role;
grant usage, select on sequence public.events_id_seq to service_role;

create or replace function public.ingest_telemetry(p_telemetry jsonb)
returns jsonb
language plpgsql
security definer
set search_path = public, pg_temp
as $$
declare
    v_device text := p_telemetry->>'deviceId';
    v_boot uuid := (p_telemetry->>'bootId')::uuid;
    v_sequence bigint := (p_telemetry->>'sequence')::bigint;
    v_observed timestamptz := (p_telemetry->>'observedAt')::timestamptz;
    v_version text := p_telemetry->>'mappingVersion';
    v_received timestamptz := clock_timestamp();
    v_previous public.device_state%rowtype;
    v_found boolean;
    v_sensor record;
    v_led jsonb;
    v_old_led jsonb;
begin
    if jsonb_typeof(p_telemetry) is distinct from 'object'
       or v_device is null or v_device !~ '^[A-Za-z0-9_-]{1,64}$'
       or v_boot is null or v_sequence is null or v_sequence < 0
       or v_observed is null or not isfinite(v_observed)
       or v_version is null then
        raise exception 'Invalid telemetry envelope' using errcode = '22023';
    end if;
    if jsonb_typeof(p_telemetry->'flame') is distinct from 'object'
       or not exists (select 1 from public.sensors where mapping_version = v_version) then
        raise exception 'Invalid sensor mapping or flame snapshot' using errcode = '22023';
    end if;
    -- Full snapshots avoid treating omitted/unread sensors as healthy.
    if (select count(*) from jsonb_object_keys(p_telemetry->'flame')) <>
       (select count(*) from public.sensors where mapping_version = v_version)
       or exists (
           select 1 from public.sensors s where s.mapping_version = v_version
           and jsonb_typeof(p_telemetry->'flame'->s.id) is distinct from 'boolean'
       ) then
        raise exception 'A full boolean snapshot of the configured sensors is required' using errcode = '22023';
    end if;
    -- Lock even before the first row exists; concurrent invocations serialize per Pi.
    perform pg_advisory_xact_lock(hashtextextended(v_device, 0));
    select * into v_previous from public.device_state where device_id = v_device for update;
    v_found := found;
    if v_found then
        if v_boot = v_previous.boot_id and v_sequence <= v_previous.sequence then
            return jsonb_build_object('accepted',false,'reason','duplicate','deviceId',v_device,'sequence',v_previous.sequence);
        end if;
        if v_observed < v_previous.observed_at
           or (v_boot <> v_previous.boot_id and v_observed <= v_previous.observed_at) then
            return jsonb_build_object('accepted',false,'reason','stale','deviceId',v_device,'sequence',v_previous.sequence);
        end if;
    end if;

    insert into public.device_state (device_id, boot_id, sequence, observed_at, received_at, mapping_version, telemetry)
    values (v_device, v_boot, v_sequence, v_observed, v_received, v_version, p_telemetry)
    on conflict (device_id) do update set
        boot_id=excluded.boot_id, sequence=excluded.sequence, observed_at=excluded.observed_at,
        received_at=excluded.received_at, mapping_version=excluded.mapping_version, telemetry=excluded.telemetry;

    for v_sensor in select id, node_id from public.sensors where mapping_version=v_version loop
        if (not v_found and p_telemetry->'flame'->v_sensor.id = 'true'::jsonb)
           or (v_found and p_telemetry->'flame'->v_sensor.id is distinct from v_previous.telemetry->'flame'->v_sensor.id) then
            insert into public.events (device_id,boot_id,sequence,type,observed_at,received_at,payload)
            values (v_device,v_boot,v_sequence,
                    case when p_telemetry->'flame'->v_sensor.id='true'::jsonb then 'FIRE' else 'CLEAR' end,
                    v_observed,v_received,jsonb_build_object('sensorId',v_sensor.id,'nodeId',v_sensor.node_id,
                    'active',p_telemetry->'flame'->v_sensor.id,'mappingVersion',v_version));
        end if;
    end loop;

    -- Timestamps alone do not create repeated LED events.
    if jsonb_typeof(p_telemetry->'led') = 'object' then
        v_led := jsonb_build_object('status',p_telemetry->'led'->'status',
                 'segments',p_telemetry->'led'->'segments','routeId',p_telemetry->'led'->'routeId',
                 'error',p_telemetry->'led'->'error');
        v_old_led := jsonb_build_object('status',v_previous.telemetry->'led'->'status',
                     'segments',v_previous.telemetry->'led'->'segments','routeId',v_previous.telemetry->'led'->'routeId',
                     'error',v_previous.telemetry->'led'->'error');
        if v_led is distinct from v_old_led then
            insert into public.events (device_id,boot_id,sequence,type,observed_at,received_at,payload)
            values (v_device,v_boot,v_sequence,'LED',v_observed,v_received,v_led);
        end if;
    end if;
    return jsonb_build_object('accepted',true,'deviceId',v_device,'sequence',v_sequence);
end;
$$;
revoke all on function public.ingest_telemetry(jsonb) from public, anon, authenticated;
grant execute on function public.ingest_telemetry(jsonb) to service_role;

-- Supabase already creates supabase_realtime; guard additions for SQL-editor reruns.
do $$
begin
    if exists (select 1 from pg_publication where pubname='supabase_realtime') then
        if not exists (select 1 from pg_publication_tables where pubname='supabase_realtime' and schemaname='public' and tablename='device_state') then
            alter publication supabase_realtime add table public.device_state;
        end if;
        if not exists (select 1 from pg_publication_tables where pubname='supabase_realtime' and schemaname='public' and tablename='events') then
            alter publication supabase_realtime add table public.events;
        end if;
    end if;
end;
$$;
commit;
