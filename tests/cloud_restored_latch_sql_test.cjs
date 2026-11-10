// Isolated PGlite regression for restoring a Pi latch while disconnected.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const {PGlite} = require(process.env.FIREGUARD_PGLITE_MODULE || '@electric-sql/pglite');
(async()=>{
 const db=new PGlite();
 try {
  await db.exec('create role anon; create role authenticated; create role service_role bypassrls; create publication supabase_realtime;');
  await db.exec(fs.readFileSync('supabase/migrations/202610300001_cloud.sql','utf8'));
  await db.exec(fs.readFileSync('supabase/migrations/202611090001_arduino_telemetry.sql','utf8'));
  const sql=fs.readFileSync('supabase/migrations/202611100005_v2_preserve_restored_latch.sql','utf8');
  await db.exec(sql); await db.exec(sql);
  const ids=Array.from({length:11},(_,i)=>`FLM-${String(i+1).padStart(2,'0')}`);
  const data={deviceId:'pi-01',bootId:'88888888-8888-4888-8888-888888888888', sequence:1,observedAt:'2026-11-09T01:00:01Z',mappingVersion:'flame-20261030-v1',flame:Object.fromEntries(ids.map(s=>[s,false])),hardware:{flame:Object.fromEntries(ids.map(s=>[s,{active:false,connected:true}]))}};
  const ingest=async d=>(await db.query('select public.ingest_telemetry_v2($1::jsonb) as r',[JSON.stringify(d)])).rows[0].r;
  const row=async ()=>(await db.query('select telemetry from public.device_state where device_id=$1',['pi-01'])).rows[0].telemetry;
  // First observation is a restored latched alarm while disconnected.
  data.flame['FLM-01']=true; data.hardware.flame['FLM-01']={active:true,connected:false};
  assert.equal((await ingest(data)).accepted,true);
  assert.equal((await row()).flame['FLM-01'],true);
  // Previous false, Pi reports newly restored true while disconnected.
  data.sequence=2; data.observedAt='2026-11-09T01:00:02Z';
  data.flame['FLM-07']=true; data.hardware.flame['FLM-07']={active:true,connected:false};
  assert.equal((await ingest(data)).accepted,true);
  let saved=await row(); assert.equal(saved.flame['FLM-01'],true);assert.equal(saved.flame['FLM-07'],true);
  assert.equal(saved.hardware.flame['FLM-07'].connected,false);
  // Neither disconnected sensor may be silently cleared by a false report.
  data.sequence=3; data.observedAt='2026-11-09T01:00:03Z';
  for(const id of ['FLM-01','FLM-07']) {data.flame[id]=false;data.hardware.flame[id].active=false;}
  assert.equal((await ingest(data)).accepted,true);
  saved=await row(); assert.equal(saved.flame['FLM-01'],true); assert.equal(saved.flame['FLM-07'],true);
  assert.equal((await ingest(data)).accepted,false);
  // An authenticated later connected report may clear only its own sensor;
  // the Pi must decide and persist the human-authorized clear beforehand.
  data.sequence=4; data.observedAt='2026-11-09T01:00:04Z'; data.hardware.flame['FLM-01'].connected=true;
  assert.equal((await ingest(data)).accepted,true);
  saved=await row(); assert.equal(saved.flame['FLM-01'],false); assert.equal(saved.flame['FLM-07'],true);
  const roles=await db.query("select has_function_privilege('anon','public.ingest_telemetry_v2(jsonb)','execute') as anon, has_function_privilege('authenticated','public.ingest_telemetry_v2(jsonb)','execute') as auth, has_function_privilege('service_role','public.ingest_telemetry_v2(jsonb)','execute') as service");
  assert.deepEqual(roles.rows[0],{anon:false,auth:false,service:true});
  console.log('PASS: disconnected restored latches, selective recovery, ordering and RPC permissions');
 } finally {await db.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});
