/* Cloud transport: Supabase invalidations + periodic REST state resync.
 * Only the public project key is sent to the browser. Device credentials stay
 * on the Pi/server. REST snapshots remain authoritative after reconnects.
 */
(() => {
  'use strict';
  let configPromise;
  const config = () => configPromise ||= fetch('/api/cloud/config', { cache: 'no-store' })
    .then(async response => {
      if (!response.ok) throw new Error('클라우드 설정을 불러오지 못했습니다.');
      return response.json();
    }).catch(error => { configPromise = null; throw error; });

  function loadClient() {
    if (window.supabase?.createClient) return Promise.resolve();
    return new Promise((resolve, reject) => {
      const script = document.createElement('script');
      script.src = 'https://cdn.jsdelivr.net/npm/@supabase/supabase-js@2.49.8/dist/umd/supabase.js';
      script.onload = () => window.supabase?.createClient ? resolve() : reject(new Error('Realtime client unavailable'));
      script.onerror = reject;
      document.head.appendChild(script);
    });
  }

  async function start(onState, onConnection = () => {}, suppliedConfig) {
    const settings = suppliedConfig || await config();
    if (!settings.enabled) return null;
    let stopped = false;
    let inflight = false;
    let pending = false;
    let client;
    let channel;
    let debounce;
    const transport = text => {
      const element = document.getElementById('cloudTransport');
      if (element) element.textContent = text;
    };
    async function refresh() {
      if (stopped) return;
      if (inflight) { pending = true; return; }
      inflight = true;
      try {
        const response = await fetch('/api/state', { cache: 'no-store' });
        const snapshot = await response.json();
        if (!response.ok || snapshot.ok === false) throw new Error('상태 조회 실패');
        if (!stopped) { onState(snapshot); onConnection(true); }
      } catch (_) {
        if (!stopped) onConnection(false);
      } finally {
        inflight = false;
        if (pending && !stopped) { pending = false; refresh(); }
      }
    }
    const invalidate = () => {
      clearTimeout(debounce);
      debounce = setTimeout(refresh, 100);
    };
    transport('5초 주기 동기화 · Realtime 연결 중');
    const timer = setInterval(refresh, 5000);
    window.addEventListener('online', invalidate);
    await refresh();
    // Realtime is an acceleration path. Failed CDN/subscription never prevents
    // the periodic fetch from recovering or detecting stale device telemetry.
    loadClient().then(() => {
      if (stopped) return;
      if (!settings.supabaseUrl || !settings.supabaseAnonKey) { transport('Realtime 설정 없음 · 5초 주기 동기화'); return; }
      client = window.supabase.createClient(settings.supabaseUrl, settings.supabaseAnonKey, {
        auth: { persistSession: false, autoRefreshToken: false, detectSessionInUrl: false },
      });
      channel = client.channel(`fireguard-${settings.deviceId}`)
        .on('postgres_changes', {
          event: '*', schema: 'public', table: 'device_state',
          filter: `device_id=eq.${settings.deviceId}`,
        }, invalidate)
        .subscribe(status => {
          if (stopped) return;
          transport(status === 'SUBSCRIBED' ? 'Realtime 연결됨 · 5초 주기 재확인' : 'Realtime 재연결 중 · 5초 주기 동기화');
          if (status === 'SUBSCRIBED') invalidate();
        });
    }).catch(() => transport('Realtime 연결 불가 · 5초 주기 동기화'));
    const stop = () => {
      stopped = true;
      clearInterval(timer); clearTimeout(debounce);
      window.removeEventListener('online', invalidate);
      if (channel) client.removeChannel(channel);
    };
    window.addEventListener('pagehide', event => { if (!event.persisted) stop(); });
    return { refresh, stop };
  }

  window.FireGuardCloud = { config, start };
})();
