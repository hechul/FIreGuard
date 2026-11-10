-- Separate v2 RPC allows safe rollout: until this migration is applied, new
-- senders fail rather than silently using the old boolean-only event logic.
begin;

create or replace function public.ingest_telemetry_v2(p_telemetry jsonb)
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
    -- New payloads must include validated per-sensor connectivity. Unknown sensors
    -- cannot be treated as clear merely because their current read is unavailable.
    if jsonb_typeof(p_telemetry->'hardware'->'flame') is distinct from 'object'
       or exists (
           select 1 from public.sensors s where s.mapping_version=v_version
           and (jsonb_typeof(p_telemetry->'hardware'->'flame'->s.id->'connected') is distinct from 'boolean'
             or jsonb_typeof(p_telemetry->'hardware'->'flame'->s.id->'active') is distinct from 'boolean')
       ) then
        raise exception 'Per-sensor status required' using errcode = '22023';
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

    -- Preserve both a previously known fire and a restored Pi latch under the
    -- same lock when a sensor disconnects; connectivity remains false.
    for v_sensor in select id from public.sensors where mapping_version=v_version loop
        if p_telemetry->'hardware'->'flame'->v_sensor.id->'connected' = 'false'::jsonb then
            p_telemetry := jsonb_set(p_telemetry, array['flame', v_sensor.id],
                to_jsonb(coalesce((v_previous.telemetry->'flame'->>v_sensor.id)::boolean, false)
                         or (p_telemetry->'flame'->>v_sensor.id)::boolean));
        end if;
    end loop;

    insert into public.device_state (device_id, boot_id, sequence, observed_at, received_at, mapping_version, telemetry)
    values (v_device, v_boot, v_sequence, v_observed, v_received, v_version, p_telemetry)
    on conflict (device_id) do update set
        boot_id=excluded.boot_id, sequence=excluded.sequence, observed_at=excluded.observed_at,
        received_at=excluded.received_at, mapping_version=excluded.mapping_version, telemetry=excluded.telemetry;

    for v_sensor in select id, node_id from public.sensors where mapping_version=v_version loop
        if p_telemetry->'hardware'->'flame'->v_sensor.id->'connected' = 'true'::jsonb
           and ((not v_found and p_telemetry->'flame'->v_sensor.id = 'true'::jsonb)
           or (v_found and p_telemetry->'flame'->v_sensor.id is distinct from v_previous.telemetry->'flame'->v_sensor.id)) then
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
revoke all on function public.ingest_telemetry_v2(jsonb) from public, anon, authenticated;
grant execute on function public.ingest_telemetry_v2(jsonb) to service_role;

commit;
