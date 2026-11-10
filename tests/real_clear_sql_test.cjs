// Isolated PGlite integration test; never touches the production Supabase DB.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const {PGlite} = require(process.env.FIREGUARD_PGLITE_MODULE || '@electric-sql/pglite');

(async () => {
  const db = new PGlite();
  try {
    await db.exec('create role anon; create role authenticated; create role service_role bypassrls; create publication supabase_realtime;');
    const base = fs.readFileSync('supabase/migrations/202610300001_cloud.sql','utf8');
    const migration = fs.readFileSync('supabase/migrations/202611100003_real_clear_queue.sql','utf8');
    await db.exec(base); await db.exec(migration); await db.exec(migration);
    const privileges = (await db.query(`select
      has_function_privilege('anon','public.real_clear_create(uuid,text,text[])','execute') as anon_create,
      has_function_privilege('authenticated','public.real_clear_claim(text)','execute') as auth_claim,
      has_function_privilege('service_role','public.real_clear_create(uuid,text,text[])','execute') as service_create,
      has_function_privilege('service_role','public.real_clear_claim(text)','execute') as service_claim,
      has_function_privilege('service_role','public.real_clear_complete(text,uuid,uuid,jsonb)','execute') as service_complete,
      has_table_privilege('anon','public.real_fire_clear_commands','select') as anon_select`)).rows[0];
    assert.deepEqual(privileges, {anon_create:false,auth_claim:false,service_create:true,service_claim:true,service_complete:true,anon_select:false});
    const id1='10000000-0000-4000-8000-000000000001';
    const id2='10000000-0000-4000-8000-000000000002';
    const id3='10000000-0000-4000-8000-000000000003';
    const id4='10000000-0000-4000-8000-000000000004';
    const fake='20000000-0000-4000-8000-000000000001';
    const create=async(id,sensors)=>(await db.query('select public.real_clear_create($1::uuid,$2::text,$3::text[]) r',[id,'pi-01',sensors])).rows[0].r;
    const claim=async()=>(await db.query('select public.real_clear_claim($1::text) r',['pi-01'])).rows[0].r;
    const complete=async(id,token,result)=>(await db.query('select public.real_clear_complete($1::text,$2::uuid,$3::uuid,$4::jsonb) r',['pi-01',id,token,JSON.stringify(result)])).rows[0].r;
    const latest=async()=>(await db.query('select public.real_clear_latest($1::text) r',['pi-01'])).rows[0].r;
    // Only legitimate unique installed sensors can be requested.
    for (const invalid of [[],['FLM-01','FLM-01'],['FLM-12'],['FLM-01',null]])
      await assert.rejects(()=>create(id1,invalid));
    assert.equal((await create(id1,['FLM-07','FLM-01'])).status,'pending');
    assert.equal((await create(id1,['FLM-01','FLM-07'])).id,id1);
    await assert.rejects(()=>create(id1,['FLM-01']));
    await assert.rejects(()=>create(id2,['FLM-02']));
    const taken=await claim();
    assert.equal(taken.id,id1);
    assert.deepEqual(taken.sensorIds,['FLM-01','FLM-07']);
    assert.equal(await claim(),null,'a claimed command must never be delivered twice');
    // The wrong claim token, sensors outside request and malformed results fail closed.
    const ok={status:'completed',message:'ok',clearedSensorIds:['FLM-01','FLM-07'],rejectedSensorIds:[]};
    await assert.rejects(()=>complete(id1,fake,ok));
    for (const bad of [
      {status:'completed',message:'bad',clearedSensorIds:['FLM-01'],rejectedSensorIds:[]},
      {status:'completed',message:'bad',clearedSensorIds:['FLM-01','FLM-08'],rejectedSensorIds:[]},
      {status:'rejected',message:'bad',clearedSensorIds:['FLM-01'],rejectedSensorIds:['FLM-07']},
      {status:'failed',message:'bad',clearedSensorIds:['FLM-01'],rejectedSensorIds:['FLM-01']},
    ]) await assert.rejects(()=>complete(id1,taken.claimToken,bad));
    assert.equal((await complete(id1,taken.claimToken,ok)).status,'completed');
    assert.equal((await complete(id1,taken.claimToken,ok)).status,'completed','same ACK must be idempotent');
    await assert.rejects(()=>complete(id1,taken.claimToken,{...ok,message:'different'}));
    assert.equal((await latest()).status,'completed');
    // Unclaimed expired work is not delivered and does not block a new request.
    assert.equal((await create(id2,['FLM-02'])).status,'pending');
    await db.query("update public.real_fire_clear_commands set expires_at=now()-interval '1 second' where id=$1::uuid",[id2]);
    assert.equal(await claim(),null);
    assert.equal((await latest()).status,'expired');
    assert.equal((await create(id3,['FLM-03'])).status,'pending');
    const expiredClaim=await claim();
    await db.query("update public.real_fire_clear_commands set expires_at=now()-interval '1 second' where id=$1::uuid",[id3]);
    assert.equal(await claim(),null,'an expired claimed command must not be redelivered');
    await assert.rejects(()=>create(id4,['FLM-04']),'unknown claimed work blocks new requests');
    const failure={status:'failed',message:'unknown; no retry',clearedSensorIds:[],rejectedSensorIds:[]};
    assert.equal((await complete(id3,expiredClaim.claimToken,failure)).status,'failed','late ACK settles existing claim');
    assert.equal((await complete(id3,expiredClaim.claimToken,failure)).status,'failed','late ACK retry is idempotent');
    assert.equal((await create(id4,['FLM-04'])).status,'pending');
    assert.equal((await db.query('select count(*)::int n from public.device_state')).rows[0].n,0,'queue never mutates fire telemetry');
    assert.equal((await db.query('select count(*)::int n from public.events')).rows[0].n,0,'queue never fabricates events');
    console.log('PASS: REAL clear SQL permissions, multi-sensor, claim, expiry, ACK and isolation');
  } finally { await db.close(); }
})().catch(error=>{console.error(error);process.exitCode=1});
