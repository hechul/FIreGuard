/* Transport-only tests: node tests/cloud_live_test.cjs */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync(require('node:path').join(__dirname, '../static/js/cloud_live.js'), 'utf8');
const flush = () => new Promise(resolve => setImmediate(resolve));

function fixture() {
  const settings = { enabled: true, deviceId: 'pi-01', supabaseUrl: 'https://test.supabase.co', supabaseAnonKey: 'public-key' };
  let failConfig = false, failState = false, fetches = 0, subscription, invalidation, filter, removed = false;
  const intervals = new Map(), timeouts = new Map(), listeners = {};
  let nextId = 0;
  const label = { textContent: '' };
  const channel = {
    on(event, options, callback) { filter = options; invalidation = callback; return this; },
    subscribe(callback) { subscription = callback; return this; },
  };
  const client = { channel: () => channel, removeChannel: () => { removed = true; } };
  const window = {
    supabase: { createClient: (url, key, options) => {
      assert.equal(key, 'public-key');
      assert.equal(options.auth.persistSession, false);
      return client;
    } },
    addEventListener: (event, callback) => { listeners[event] = callback; },
    removeEventListener: event => { delete listeners[event]; },
  };
  const context = {
    window,
    document: { getElementById: () => label },
    fetch: async (url, options) => {
      assert.equal(options.cache, 'no-store');
      if (url === '/api/cloud/config') {
        if (failConfig) throw new Error('offline');
        return { ok: true, json: async () => settings };
      }
      assert.equal(url, '/api/state'); fetches++;
      return { ok: !failState, json: async () => failState ? { ok: false } : { revision: fetches } };
    },
    setInterval: (callback, delay) => { assert.equal(delay, 5000); intervals.set(++nextId, callback); return nextId; },
    clearInterval: id => intervals.delete(id),
    setTimeout: callback => { timeouts.set(++nextId, callback); return nextId; },
    clearTimeout: id => timeouts.delete(id),
  };
  vm.runInNewContext(source, context);
  return {
    api: window.FireGuardCloud, settings, label, intervals, timeouts, listeners,
    get fetches() { return fetches; }, get filter() { return filter; }, get removed() { return removed; },
    set failConfig(value) { failConfig = value; }, set failState(value) { failState = value; },
    subscribe: state => subscription(state), invalidate: () => invalidation(),
    drain: () => { const pending = [...timeouts.values()]; timeouts.clear(); pending.forEach(callback => callback()); },
  };
}

(async () => {
  const retry = fixture();
  retry.failConfig = true;
  await assert.rejects(retry.api.config(), /offline/);
  retry.failConfig = false;
  assert.equal((await retry.api.config()).deviceId, 'pi-01', 'failed config requests must recover');

  const f = fixture(), states = [], connections = [];
  const live = await f.api.start(state => states.push(state), online => connections.push(online));
  await flush();
  assert.equal(states.length, 1);
  assert.equal(f.filter.table, 'device_state');
  assert.equal(f.filter.filter, 'device_id=eq.pi-01');
  f.subscribe('SUBSCRIBED');
  assert.match(f.label.textContent, /Realtime 연결됨/);
  f.invalidate(); f.invalidate();
  assert.equal(f.timeouts.size, 1, 'bursts coalesce into one invalidation');
  f.drain(); await flush();
  assert.equal(states.length, 2);
  f.subscribe('CHANNEL_ERROR');
  assert.match(f.label.textContent, /5초 주기 동기화/);
  f.failState = true;
  [...f.intervals.values()][0](); await flush();
  assert.equal(connections.at(-1), false);
  f.failState = false;
  [...f.intervals.values()][0](); await flush();
  assert.equal(connections.at(-1), true);
  f.listeners.pagehide({ persisted: true });
  assert.equal(f.intervals.size, 1, 'bfcache entry should resume its transport');
  live.stop();
  assert.equal(f.intervals.size, 0);
  assert.equal(f.removed, true);
  const count = f.fetches;
  await live.refresh();
  assert.equal(f.fetches, count, 'stopped subscriptions do not fetch');

  const local = fixture();
  assert.equal(await local.api.start(() => {}, () => {}, { enabled: false }), null);
  assert.equal(local.fetches, 0);
  console.log('cloud_live transport tests passed');
})().catch(error => { console.error(error); process.exitCode = 1; });
