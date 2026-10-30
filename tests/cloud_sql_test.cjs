/*
 * Execute the production migration against embedded PostgreSQL (PGlite).
 * Dependencies stay outside this Python repository:
 *   npm install --prefix /tmp/fireguard-pglite @electric-sql/pglite
 *   FIREGUARD_PGLITE_MODULE=/tmp/fireguard-pglite/node_modules/@electric-sql/pglite node tests/cloud_sql_test.cjs
 * This does not connect to Supabase. PGlite has one database connection, so
 * Promise.all tests queued duplicate submissions, not multi-session contention.
 */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { PGlite } = require(process.env.FIREGUARD_PGLITE_MODULE || '@electric-sql/pglite');

async function main() {
  const db = new PGlite();
  let passed = 0;
  async function test(name, action) {
    await action();
    passed += 1;
    console.log(`ok ${passed} - ${name}`);
  }
  async function asRole(role, action) {
    await db.exec(`set role ${role}`);
    try { return await action(); }
    finally { await db.exec('reset role'); }
  }
  const countEvents = async () => Number((await db.query('select count(*) as n from public.events')).rows[0].n);
  const snapshot = (sequence, changes = {}) => ({
    deviceId: 'pi-01', bootId: '88888888-8888-4888-8888-888888888888',
    sequence, observedAt: `2026-10-30T03:00:${String(sequence).padStart(2, '0')}Z`,
    mappingVersion: 'flame-20261030-v1',
    flame: Object.fromEntries(Array.from({ length: 11 }, (_, i) => [`FLM-${String(i + 1).padStart(2, '0')}`, false])),
    ...changes,
  });
  const ingest = async (value) => (await db.query('select public.ingest_telemetry($1::jsonb) as result', [JSON.stringify(value)])).rows[0].result;
  const migration = fs.readFileSync(path.join(__dirname, '../supabase/migrations/202610300001_cloud.sql'), 'utf8');
  try {
    await db.exec('create role anon; create role authenticated; create role service_role bypassrls; create publication supabase_realtime;');
    await test('production migration executes and can be rerun', async () => {
      await db.exec(migration);
      await db.exec(migration);
      assert.equal(Number((await db.query('select count(*) as n from sensors')).rows[0].n), 11);
      const published = (await db.query("select tablename from pg_publication_tables where pubname='supabase_realtime' order by tablename")).rows.map(r => r.tablename);
      assert.deepEqual(published, ['device_state', 'events']);
    });
    await test('initial healthy snapshot creates state without event noise', async () => {
      const result = await asRole('service_role', () => ingest(snapshot(1)));
      assert.equal(result.accepted, true);
      assert.equal(await countEvents(), 0);
    });
    await test('fire, unchanged heartbeat and clear create exactly two events', async () => {
      const fire = { ...snapshot(2).flame, 'FLM-08': true };
      await ingest(snapshot(2, { flame: fire }));
      await ingest(snapshot(3, { flame: fire }));
      assert.equal(await countEvents(), 1);
      await ingest(snapshot(4));
      const events = (await db.query('select type,payload from events order by id')).rows;
      assert.deepEqual(events.map(e => e.type), ['FIRE', 'CLEAR']);
      assert.equal(events[0].payload.sensorId, 'FLM-08');
      assert.equal(events[0].payload.nodeId, 'N8');
      assert.equal(events[1].payload.active, false);
    });
    await test('LED changes are recorded but timestamp-only changes are not', async () => {
      const led = { status: 'applied', routeId: 'route-1', segments: [{ id: 'S1', color: '#00ff00', on: true }] };
      await ingest(snapshot(5, { led }));
      await ingest(snapshot(6, { led: { ...led, reportedAt: '2026-10-30T03:00:06Z' } }));
      assert.equal(await countEvents(), 3);
      await ingest(snapshot(7, { led: { ...led, status: 'error', error: 'output failed' } }));
      assert.equal(await countEvents(), 4);
    });
    await test('concurrent duplicate submissions accept once and emit one event', async () => {
      const flame = { ...snapshot(8).flame, 'FLM-01': true };
      const value = snapshot(8, { flame });
      const results = await Promise.all(Array.from({ length: 12 }, () => ingest(value)));
      assert.equal(results.filter(r => r.accepted).length, 1);
      assert.equal(await countEvents(), 5);
      const state = (await db.query('select sequence,telemetry from device_state')).rows[0];
      assert.equal(Number(state.sequence), 8);
      assert.equal(state.telemetry.flame['FLM-01'], true);
    });
    await test('old sequence and old boot observations cannot replace current state', async () => {
      assert.equal((await ingest(snapshot(7))).accepted, false);
      assert.equal((await ingest(snapshot(9, { observedAt: '2026-10-30T03:00:01Z' }))).accepted, false);
      assert.equal((await ingest(snapshot(0, { bootId: '99999999-9999-4999-8999-999999999999', observedAt: '2026-10-30T03:00:01Z' }))).accepted, false);
      assert.equal(Number((await db.query('select sequence from device_state')).rows[0].sequence), 8);
      assert.equal(await countEvents(), 5);
    });
    await test('newer boot may restart its sequence', async () => {
      assert.equal((await ingest(snapshot(0, { bootId: '99999999-9999-4999-8999-999999999999', observedAt: '2026-10-30T03:00:09Z' }))).accepted, true);
      assert.equal(Number((await db.query('select sequence from device_state')).rows[0].sequence), 0);
    });
    await test('invalid snapshots fail atomically', async () => {
      const before = await countEvents();
      for (const changes of [{ flame: { 'FLM-08': true } }, { flame: { ...snapshot(10).flame, 'FLM-08': 'true' } }, { mappingVersion: 'unknown' }]) {
        await assert.rejects(() => ingest(snapshot(10, changes)), error => error.code === '22023');
      }
      assert.equal(await countEvents(), before);
      assert.equal(Number((await db.query('select sequence from device_state')).rows[0].sequence), 0);
    });
    await test('anon can read public dashboard tables', async () => {
      await asRole('anon', async () => {
        assert.equal((await db.query('select * from sensors')).rows.length, 11);
        assert.equal((await db.query('select * from device_state')).rows.length, 1);
        assert.ok((await db.query('select * from events')).rows.length > 0);
      });
    });
    await test('anon and authenticated cannot write or call ingestion RPC', async () => {
      for (const role of ['anon', 'authenticated']) {
        await asRole(role, async () => {
          await assert.rejects(() => db.query("update device_state set sequence=999 where device_id='pi-01'"), error => error.code === '42501');
          await assert.rejects(() => db.query("delete from events"), error => error.code === '42501');
          await assert.rejects(() => db.query("update sensors set node_id='N9'"), error => error.code === '42501');
          await assert.rejects(() => ingest(snapshot(11)), error => error.code === '42501');
        });
      }
    });
    console.log(`PASS: ${passed} embedded PostgreSQL tests; no live Supabase connection.`);
  } finally {
    await db.close();
  }
}
main().catch(error => { console.error(error); process.exitCode = 1; });
