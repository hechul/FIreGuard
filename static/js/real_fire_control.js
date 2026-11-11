/* Compact REAL monitoring and an opt-in, authenticated clear request.
   Simulation events never update or submit actual sensor state. */
(function (root, factory) {
  if (typeof module === 'object' && module.exports) module.exports = factory();
  else root.FireGuardRealFireControl = factory(root);
}(typeof globalThis !== 'undefined' ? globalThis : this, function (root) {
  'use strict';

  function confirmedByTelemetry(state, baselineObservedAt, sensorIds, command) {
    if (!state?.cloud?.enabled || !state.cloud.hasTelemetry || state.cloud.stale ||
        command?.status !== 'completed' || !Array.isArray(sensorIds) || !sensorIds.length) return false;
    const cleared = command.result?.clearedSensorIds;
    const rejected = command.result?.rejectedSensorIds;
    if (!Array.isArray(cleared) || !Array.isArray(rejected) || rejected.length ||
        cleared.length !== sensorIds.length || new Set(cleared).size !== sensorIds.length ||
        sensorIds.some(id => !cleared.includes(id))) return false;
    const before = Date.parse(baselineObservedAt || '');
    const after = Date.parse(state.cloud.observedAt || '');
    if (!Number.isFinite(before) || !Number.isFinite(after) || after <= before) return false;
    return sensorIds.every(id => state.flameSensors?.[id]?.active === false && state.flameSensors?.[id]?.connected === true);
  }

  function mount(doc, win) {
    if (!doc || !win || doc.documentElement.dataset.cloud !== 'true') return;
    const statusCard = doc.querySelector('.status-card');
    const sensorCard = doc.querySelector('.sensor-card');
    if (!statusCard || !sensorCard || doc.getElementById('realFireControl')) return;

    const ledStatus = doc.createElement('div');
    ledStatus.className = 'response-item';
    ledStatus.id = 'realLedSummary';
    ledStatus.style.marginTop = '12px';
    ledStatus.hidden = true;
    const ledLabel = doc.createElement('span'); ledLabel.textContent = '실제 LED';
    const ledText = doc.createElement('strong'); ledText.textContent = 'LED 상태 확인 대기';
    ledText.style.display = 'block'; ledText.setAttribute('aria-live', 'polite');
    ledStatus.append(ledLabel, ledText);
    statusCard.appendChild(ledStatus);

    const panel = doc.createElement('details');
    panel.id = 'realFireControl'; panel.className = 'scenario-lab';
    panel.style.marginTop = '16px'; panel.hidden = true;
    panel.innerHTML = '<summary><span><b>실제 화재 수동 해제</b><small>관리자 전용</small></span></summary>' +
      '<div style="padding:14px;display:grid;gap:10px">' +
      '<p>화재가 끝났고 센서가 정상인지 확인한 뒤 선택해 주세요.</p>' +
      '<label>관리자 키<input id="realFireOperatorKey" type="password" autocomplete="off" spellcheck="false" style="display:block;width:100%;margin-top:4px"></label>' +
      '<fieldset id="realFireSensorChoices" style="border:0;padding:0;margin:0"><legend>해제할 화재 센서</legend></fieldset>' +
      '<button id="realFireSubmit" class="btn secondary" type="button">선택한 화재 해제 요청</button>' +
      '<button id="realFireRetry" class="btn secondary" type="button" hidden>요청 결과 다시 확인</button>' +
      '<p id="realFireClearStatus" role="status" aria-live="polite">요청 전</p></div>';
    sensorCard.appendChild(panel);
    const key = panel.querySelector('#realFireOperatorKey');
    const choices = panel.querySelector('#realFireSensorChoices');
    const submit = panel.querySelector('#realFireSubmit');
    const retry = panel.querySelector('#realFireRetry');
    const status = panel.querySelector('#realFireClearStatus');
    let current = null, visible = false, pending = null, polling = false;

    function showChoices(ids) {
      const chosen = new Set([...choices.querySelectorAll('input:checked')].map(input => input.value));
      choices.replaceChildren();
      const legend = doc.createElement('legend'); legend.textContent = '해제할 화재 센서'; choices.appendChild(legend);
      for (const id of ids) {
        const label = doc.createElement('label'); label.style.display = 'block';
        const input = doc.createElement('input'); input.type = 'checkbox'; input.value = id;
        input.checked = chosen.has(id); input.disabled = Boolean(pending);
        label.append(input, doc.createTextNode(' ' + id)); choices.appendChild(label);
      }
    }
    function update(event) {
      const detail = event?.detail || {};
      current = detail.state || null;
      visible = detail.viewMode === 'real' && current?.cloud?.enabled === true;
      ledStatus.hidden = !visible;
      if (visible) ledText.textContent = win.FireGuardHardwareDisplay?.describeCompact(current.cloud) || 'LED 상태 확인 대기';
      const ids = Array.isArray(current?.realFireSensorIds) ? current.realFireSensorIds.filter(id => /^FLM-\d{2}$/.test(id)) : [];
      const enabled = doc.documentElement.dataset.realClear === 'enabled';
      panel.hidden = !visible || !enabled || (!ids.length && !pending);
      if (!visible) return;
      showChoices(ids);
      retry.hidden = !pending || !pending.id;
      retry.disabled = polling;
      submit.disabled = Boolean(pending) || !ids.length || !current.cloud.hasTelemetry || current.cloud.stale;
      if (!pending && current.cloud.stale) status.textContent = '실제 장비 상태를 확인한 뒤 해제할 수 있습니다.';
      if (pending && confirmedByTelemetry(current, pending.baseline, pending.sensorIds, pending.command)) {
        status.textContent = 'Pi 처리와 최신 센서 상태를 확인했습니다.';
        pending = null; submit.disabled = !ids.length;
        showChoices(ids);
      }
    }
    win.addEventListener('fireguard:real-state', update);
    // dashboard.js can initialize before this deferred module. Request its
    // latest snapshot rather than waiting for the next telemetry update.
    if (typeof win.CustomEvent === 'function')
      win.dispatchEvent(new win.CustomEvent('fireguard:request-real-state'));

    async function api(path, body) {
      const headers = {Authorization: `Bearer ${key.value}`};
      if (body) headers['Content-Type'] = 'application/json';
      const response = await win.fetch(path, {method:body ? 'POST' : 'GET', headers, cache:'no-store',
        ...(body ? {body:JSON.stringify(body)} : {})});
      const data = await response.json().catch(() => ({}));
      if (!response.ok || data.ok === false) {
        const error = new Error(data.error || `HTTP ${response.status}`);
        error.status = response.status;
        throw error;
      }
      return data;
    }
    async function poll() {
      if (polling || !pending) return;
      polling = true;
      retry.disabled = true;
      try {
        for (let attempt = 0; attempt < 60 && pending; attempt++) {
          await new Promise(resolve => win.setTimeout(resolve, 2000));
          if (!pending) break;
          const data = await api('/api/real-control/latest');
          if (!data.command || data.command.id !== pending.id) {
            status.textContent = '요청 결과를 확인할 수 없습니다. 상태를 확인해 주세요.';
            break;
          }
          pending.command = data.command;
          const code = data.command.status;
          if (code === 'rejected' || code === 'failed' || code === 'expired') {
            status.textContent = `해제되지 않았습니다 · ${data.command.result?.message || 'Pi 상태를 확인하세요.'}`;
            pending = null;
            if (current) update({detail:{state:current, viewMode:visible ? 'real' : 'simulation'}});
            break;
          }
          if (confirmedByTelemetry(current, pending.baseline, pending.sensorIds, pending.command)) {
            status.textContent = 'Pi 처리와 최신 센서 상태를 확인했습니다.';
            pending = null;
            if (current) update({detail:{state:current, viewMode:visible ? 'real' : 'simulation'}});
            break;
          }
          status.textContent = code === 'completed' ? 'Pi 응답 확인 · 최신 센서 상태를 기다리는 중' : 'Pi 처리 결과를 기다리는 중';
        }
        if (pending) status.textContent = '결과 확인 대기 중입니다. 실제 센서 상태가 확인될 때까지 화재를 유지합니다.';
      } catch (error) {
        status.textContent = error.status === 401
          ? '관리자 키를 확인하고 요청 결과를 다시 확인해 주세요.'
          : '연결이 끊겨 요청 결과를 확인할 수 없습니다. 화재 상태를 확인해 주세요.';
      } finally { polling = false; retry.disabled = false; retry.hidden = !pending?.id; }
    }
    retry.addEventListener('click', () => { if (pending?.id) void poll(); });
    submit.addEventListener('click', async () => {
      if (!visible || pending || !current?.cloud?.hasTelemetry || current.cloud.stale) return;
      if (!key.value) { status.textContent = '관리자 키를 입력해 주세요.'; return; }
      const ids = [...choices.querySelectorAll('input:checked')].map(input => input.value);
      if (!ids.length) { status.textContent = '해제할 센서를 선택해 주세요.'; return; }
      const actual = new Set(current.realFireSensorIds || []);
      if (ids.some(id => !actual.has(id) || current.flameSensors?.[id]?.connected !== true)) {
        status.textContent = '연결된 화재 센서의 상태를 다시 확인해 주세요.'; return;
      }
      const baseline = current.cloud.observedAt;
      if (!Number.isFinite(Date.parse(baseline || ''))) { status.textContent = '센서 관측 시각을 확인할 수 없습니다.'; return; }
      // A request in flight cannot be submitted again even if the view changes.
      pending = {id:null, sensorIds:ids, baseline, command:null}; submit.disabled = true;
      status.textContent = 'Pi에 해제를 요청하는 중';
      try {
        const result = await api('/api/real-control/clear', {sensorIds:ids});
        if (!pending || !result.command?.id) throw new Error('요청 결과를 확인할 수 없습니다.');
        pending.id = result.command.id;
        retry.hidden = false;
        status.textContent = 'Pi 처리 결과를 기다리는 중';
        void poll();
      } catch (error) {
        if (error.status === 400 || error.status === 401 || error.status === 405) {
          pending = null;
          submit.disabled = false;
          status.textContent = error.status === 401 ? '관리자 키가 올바르지 않습니다.' : '요청이 거부되었습니다. 센서 선택과 서버 설정을 확인해 주세요.';
          return;
        }
        // Network failure can occur after server accepted the request. Do not
        // send again or claim that state was cleared without explicit recovery.
        status.textContent = '요청 결과를 확인할 수 없습니다. 실제 센서 상태를 확인해 주세요.';
      }
    });
  }
  if (root?.document) {
    if (root.document.readyState === 'loading') root.document.addEventListener('DOMContentLoaded', () => mount(root.document, root));
    else mount(root.document, root);
  }
  return { confirmedByTelemetry, mount };
}));
