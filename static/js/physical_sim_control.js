/* Explicit, isolated hardware test. Operator secret lives only in this page. */
(function () {
  'use strict';
  const starts = [
    ['N33','동측 분기점'],['N10','동측 비상구 앞'],['N9','중앙복도 동측'],
    ['N34','중앙복도 중앙'],['N8','중앙복도 서측'],['N35','서측 분기점'],
    ['N7','서측 비상구 앞'],['N36','4관 내부'],['N37','5관 내부'],['N38','1관 내부'],
    ['N12','2관 내부'],['N13','4DX관 내부'],['N14','매표소 앞'],['N15','팝콘팩토리 앞'],
    ['N5','화장실 1'],['N6','화장실 2'],['N3','완강기'],['N19','팝콘 매장 내부'],
    ['N1','5관 앞 복도'],['N20','북서 복도'],['N11','1관 남측'],['N23','서측 상부 복도'],
    ['N2','5관 앞 분기점'],['N25','매점 앞'],['N4','4관 앞'],['N27','팝콘 매장 분기점'],
    ['N28','화장실 1 분기점'],['N29','화장실 2 분기점'],['N30','2관 분기점'],['N31','1관 분기점'],
  ];
  const fires = [['N20','FLM-01'],['N2','FLM-02'],['N3','FLM-03'],['N4','FLM-04'],
    ['N5','FLM-05'],['N6','FLM-06'],['N7','FLM-07'],['N8','FLM-08'],
    ['N9','FLM-09'],['N10','FLM-10'],['N11','FLM-11']];

  function init() {
    // Availability requires explicit server-side opt-in; never expose by default.
    if (document.documentElement.dataset.physicalSim !== 'enabled') return;
    const card = document.querySelector('.scenario-card');
    if (!card || document.getElementById('physicalSimPanel')) return;
    const panel = document.createElement('details');
    panel.id = 'physicalSimPanel';
    panel.className = 'scenario-lab';
    panel.style.marginTop = '16px';
    panel.innerHTML = '<summary><span><b>Pi 연결 및 LED 시험</b><small>Pi 실행 모드 확인</small></span></summary>' +
      '<div style="padding:14px;display:grid;gap:10px">' +
      '<p>Pi에서 실행 중인 프로그램에 따라 경로만 확인하거나 LED를 짧게 시험합니다.</p>' +
      '<label>운영자 키 <input id="physicalSimToken" type="password" autocomplete="off" spellcheck="false" style="display:block;width:100%;margin-top:4px" /></label>' +
      '<label>출발 노드 <select id="physicalSimStart" style="display:block;width:100%;margin-top:4px"></select></label>' +
      '<label>모의 화재 <select id="physicalSimFire" style="display:block;width:100%;margin-top:4px"></select></label>' +
      '<div style="display:flex;gap:8px;flex-wrap:wrap"><button type="button" class="btn primary" id="physicalSimSend">연결 점검 요청</button>' +
      '<button type="button" class="btn secondary" id="physicalSimFromScreen">현재 화면 조건으로 점검</button>' +
      '<button type="button" class="btn secondary" id="physicalSimRefresh">결과 확인</button></div>' +
      '<p id="physicalSimStatus" role="status" aria-live="polite">연결 점검 요청 전</p>' +
      '<p style="font-size:12px">Uno 응답과 LED의 실제 발광은 별도로 확인하세요.</p></div>';
    card.appendChild(panel);
    const token = panel.querySelector('#physicalSimToken');
    const start = panel.querySelector('#physicalSimStart');
    const fire = panel.querySelector('#physicalSimFire');
    const send = panel.querySelector('#physicalSimSend');
    const fromScreen = panel.querySelector('#physicalSimFromScreen');
    const refresh = panel.querySelector('#physicalSimRefresh');
    const status = panel.querySelector('#physicalSimStatus');
    function option(select, value, label) {
      const el = document.createElement('option');
      el.value = value; el.textContent = label; select.appendChild(el);
    }
    starts.forEach(([id, name]) => option(start, id, `${id} · ${name}`));
    fires.forEach(([node, sensor]) => option(fire, node, `${node} · ${sensor}`));
    let pending = false;
    async function request(url, body) {
      if (pending) return null;
      if (!token.value) { status.textContent = '운영자 키를 입력하세요.'; return null; }
      pending = true; send.disabled = true; fromScreen.disabled = true; refresh.disabled = true;
      try {
        const headers = {Authorization: `Bearer ${token.value}`};
        if (body) headers['Content-Type'] = 'application/json';
        const response = await fetch(url, {method:body ? 'POST':'GET', headers, cache:'no-store',
          ...(body ? {body:JSON.stringify(body)} : {})});
        const data = await response.json().catch(() => ({}));
        if (!response.ok || data.ok === false) throw new Error(data.error || `HTTP ${response.status}`);
        return data;
      } catch (error) {
        status.textContent = `요청 실패 · ${error.message || '연결을 확인하세요.'}`;
        return null;
      } finally { pending = false; send.disabled = false; fromScreen.disabled = false; refresh.disabled = false; }
    }
    function show(data) {
      const command = data.command || data;
      if (!command || (!command.status && !command.result)) { status.textContent = '시험 결과가 없습니다.'; return; }
      const states = {pending:'요청 대기', queued:'요청 대기', claimed:'Pi 처리 중', applied:'Pi 처리 완료',
        completed:'Pi 처리 완료', failed:'시험 실패', rejected:'요청 거부', expired:'요청 만료'};
      const result = command.result || {};
      const route = Array.isArray(result.routeNodes) && result.routeNodes.length ? result.routeNodes.join(' → ') : '경로 보고 없음';
      const led = result.ledCommandAck === true
        ? `Uno 점등 명령 응답 확인 · ${result.stopCommandAck === true ? 'STOP 응답 확인' : 'STOP 응답 미확인'} · 실제 발광 미확인`
        : 'LED 점등 명령 응답 없음';
      status.textContent = `${states[command.status] || command.status || '상태 확인 중'} · ${led} · ${route}` +
        (result.message ? ` · ${result.message}` : command.error ? ` · ${command.error}` : '');
    }
    send.addEventListener('click', async () => {
      status.textContent = '시험 요청 중';
      const data = await request('/api/sim-control/commands', {startNode:start.value, fireNode:fire.value});
      if (data) show(data);
    });
    fromScreen.addEventListener('click', async () => {
      if (pending) return;
      if (!token.value) { status.textContent = '운영자 키를 입력하세요.'; return; }
      if (!document.getElementById('simModeBtn')?.classList.contains('active')) {
        status.textContent = 'SIMULATION 화면에서만 점검할 수 있습니다.'; return;
      }
      let saved, history;
      try { saved = sessionStorage.getItem('fireguard-simulation-history'); history = saved ? JSON.parse(saved) : []; }
      catch (_) { status.textContent = '시뮬레이션 상태를 읽을 수 없습니다.'; return; }
      if (!Array.isArray(history)) { status.textContent = '시뮬레이션 상태를 읽을 수 없습니다.'; return; }
      pending = true; send.disabled = true; fromScreen.disabled = true; refresh.disabled = true;
      status.textContent = '현재 화면 조건 확인 중';
      let response, result;
      try {
        response = await fetch('/api/cloud/simulation', {method:'POST', headers:{'Content-Type':'application/json'},
          cache:'no-store', body:JSON.stringify({history})});
        result = await response.json();
        if (!response.ok || !result.ok) throw new Error(result.error || '화면 조건을 확인할 수 없습니다.');
        if (!document.getElementById('simModeBtn')?.classList.contains('active') ||
            sessionStorage.getItem('fireguard-simulation-history') !== saved) {
          throw new Error('화면 조건이 변경됐습니다. 다시 시도하세요.');
        }
        const state = result.state, sensors = result.floorplan?.sensors;
        if (state?.operationMode !== 'simulation' || !Array.isArray(sensors) || !state.flameSensors) {
          throw new Error('시뮬레이션 상태를 확인할 수 없습니다.');
        }
        const active = sensors.filter(s => s.type === 'flame' && state.flameSensors[s.id]?.active);
        if (active.length !== 1) throw new Error('모의 화재 센서 하나를 선택하세요.');
        const fireNode = active[0].node, startNode = state.startNode;
        if (!starts.some(([id]) => id === startNode) || !fires.some(([id]) => id === fireNode)) {
          throw new Error('Pi에 없는 노드입니다. Pi에 등록된 노드를 선택하세요.');
        }
        if ((state.blockedEdges || []).length || (state.manualBlockedEdges || []).length ||
            Object.keys(state.edgeWeightOverrides || {}).length ||
            Object.values(state.shutters || {}).some(s => s.closed || !s.connected) ||
            Object.values(state.flameSensors).some(s => !s.connected) ||
            (state.blockedNodes || []).some(id => id !== fireNode) ||
            !state.connections?.pi || !state.connections?.server) {
          throw new Error('이 점검은 출발점과 센서 화재 한 건만 지원합니다. 다른 장애 조건을 해제하세요.');
        }
        start.value = startNode; fire.value = fireNode;
      } catch (error) {
        status.textContent = `요청 실패 · ${error.message || '연결을 확인하세요.'}`;
        pending = false; send.disabled = false; fromScreen.disabled = false; refresh.disabled = false;
        return;
      }
      pending = false;
      const data = await request('/api/sim-control/commands', {startNode:start.value, fireNode:fire.value});
      if (data) show(data);
    });
    refresh.addEventListener('click', async () => {
      status.textContent = '시험 결과 확인 중';
      const data = await request('/api/sim-control/latest');
      if (data) show(data);
    });
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init);
  else init();
}());
