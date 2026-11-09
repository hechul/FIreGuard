// Executes both migrations against an isolated PGlite instance; never Supabase.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const { PGlite } = require(process.env.FIREGUARD_PGLITE_MODULE || '@electric-sql/pglite');
(async () => {
 const db = new PGlite();
 try {
  await db.exec('create role anon; create role authenticated; create role service_role bypassrls; create publication supabase_realtime;');
  await db.exec(fs.readFileSync('supabase/migrations/202610300001_cloud.sql','utf8'));
  const migration=fs.readFileSync('supabase/migrations/202611090001_arduino_telemetry.sql','utf8');
  await db.exec(migration); await db.exec(migration);
  const sensors=Array.from({length:11},(_,i)=>`FLM-${String(i+1).padStart(2,'0')}`);
  const data={deviceId:'pi-01', bootId:'88888888-8888-4888-8888-888888888888', sequence:1, observedAt:'2026-11-09T01:00:01Z',mappingVersion:'flame-20261030-v1',flame:Object.fromEntries(sensors.map(s=>[s,s==='FLM-07'])),hardware:{flame:Object.fromEntries(sensors.map(s=>[s,{active:s==='FLM-07',connected:true}]))}};
  const ingest=async d=>(await db.query('select public.ingest_telemetry_v2($1::jsonb) as r',[JSON.stringify(d)])).rows[0].r;
  assert.equal((await ingest(data)).accepted,true);
  data.sequence=2;data.observedAt='2026-11-09T01:00:02Z';data.flame['FLM-07']=false;data.hardware.flame['FLM-07']={active:false,connected:false};
  assert.equal((await ingest(data)).accepted,true);
  let row=(await db.query('select telemetry from public.device_state')).rows[0].telemetry;
  assert.equal(row.flame['FLM-07'],true);assert.equal(row.hardware.flame['FLM-07'].connected,false);
  let events=(await db.query('select type from public.events order by id')).rows.map(x=>x.type);
  assert.deepEqual(events,['FIRE']);
  assert.equal((await ingest(data)).accepted,false);
  data.sequence=3;data.observedAt='2026-11-09T01:00:03Z';data.hardware.flame['FLM-07'].connected=true;
  assert.equal((await ingest(data)).accepted,true);
  row=(await db.query('select telemetry from public.device_state')).rows[0].telemetry;
  assert.equal(row.flame['FLM-07'],false);
  events=(await db.query('select type from public.events order by id')).rows.map(x=>x.type);
  assert.deepEqual(events,['FIRE','CLEAR']);
  console.log('PASS: v2 migration preserves fire on disconnect and clears only on confirmed sensor recovery');
 } finally {await db.close();}
})().catch(e=>{console.error(e);process.exitCode=1});
