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
      '<button type="button" class="btn secondary" id="physicalSimAuto" aria-pressed="false">지도와 LED 자동 연동 켜기</button>' +
      '<p>모형 시연 전용 · 실제 센서를 감시하지 않습니다. 화재 해제 시 이미 전송된 LED 명령은 즉시 취소되지 않을 수 있습니다.</p>' +
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
    const autoButton = panel.querySelector('#physicalSimAuto');
    const status = panel.querySelector('#physicalSimStatus');
    function option(select, value, label) {
      const el = document.createElement('option');
      el.value = value; el.textContent = label; select.appendChild(el);
    }
    starts.forEach(([id, name]) => option(start, id, `${id} · ${name}`));
    fires.forEach(([node, sensor]) => option(fire, node, `${node} · ${sensor}`));
    let pending = false;
    let autoArmed = false, autoAuthenticating = false, autoTimer = null, autoVersion = 0, latestSelection = null, autoInFlight = false;
    let activeCommand = null;

    function cancelActive() {
      const command = activeCommand;
      if (!command || command.cancelling) return;
      command.cancelling = true;
      fetch('/api/sim-control/cancel', {
        method:'POST', headers:{'Content-Type':'application/json', Authorization:`Bearer ${command.token}`},
        cache:'no-store', body:JSON.stringify({id:command.id}),
      }).then(response => {
        if (!response.ok) throw new Error('취소 요청 실패');
      }).catch(() => {
        autoArmed = false; latestSelection = null; autoVersion++;
        autoButton.setAttribute('aria-pressed', 'false');
        autoButton.textContent = '지도와 LED 자동 연동 켜기';
        status.textContent = 'Pi 요청 취소를 확인하지 못했습니다. 모형 LED 상태를 직접 확인하세요.';
      });
    }

    function selectionFrom(state, floorplan) {
      const sensors = floorplan?.sensors;
      if (state?.operationMode !== 'simulation' || !Array.isArray(sensors) || !state.flameSensors)
        throw new Error('시뮬레이션 상태를 확인할 수 없습니다.');
      const active = sensors.filter(s => s.type === 'flame' && state.flameSensors[s.id]?.active);
      if (!active.length) return null;
      // Graph node IDs are the shared contract: SIM and Pi sensor IDs differ.
      const fireNodes = [...new Set(active.map(sensor => sensor.node))].sort();
      const startNode = state.startNode;
      if (!starts.some(([id]) => id === startNode) ||
          fireNodes.some(node => !fires.some(([id]) => id === node)))
        throw new Error('Pi에 없는 노드입니다.');
      const blockedNodes = new Set(state.blockedNodes || []);
      if ((state.blockedEdges || []).length || (state.manualBlockedEdges || []).length ||
          Object.keys(state.edgeWeightOverrides || {}).length ||
          Object.values(state.shutters || {}).some(s => s.closed || !s.connected) ||
          Object.values(state.flameSensors).some(s => !s.connected) ||
          blockedNodes.size !== fireNodes.length || fireNodes.some(id => !blockedNodes.has(id)) ||
          !state.connections?.pi || !state.connections?.server)
        throw new Error('출발점과 모의 화재 외의 장애 조건은 지원하지 않습니다.');
      return {startNode, fireNodes};
    }

    function setAuto(armed, message) {
      if (!armed) cancelActive();
      autoArmed = armed; autoVersion++; latestSelection = null;
      if (autoTimer !== null) clearTimeout(autoTimer);
      autoTimer = null;
      autoButton.setAttribute('aria-pressed', armed ? 'true' : 'false');
      autoButton.textContent = armed ? '지도와 LED 자동 연동 끄기' : '지도와 LED 자동 연동 켜기';
      if (message) status.textContent = message;
    }
    token.addEventListener('input', () => {
      if (autoArmed || autoAuthenticating) setAuto(false, '운영자 키가 변경되어 자동 연동을 껐습니다.');
    });
    autoButton.addEventListener('click', async () => {
      if (autoArmed) { setAuto(false, '자동 연동 꺼짐 · 이미 전송된 요청은 취소되지 않을 수 있습니다.'); return; }
      if (!token.value) { status.textContent = '운영자 키를 입력하세요.'; return; }
      if (!document.getElementById('simModeBtn')?.classList.contains('active')) {
        status.textContent = 'SIMULATION 화면에서만 자동 연동할 수 있습니다.'; return;
      }
      if (pending || autoAuthenticating) return;
      const checkedToken = token.value, checkedVersion = autoVersion;
      autoAuthenticating = true; autoButton.disabled = true;
      status.textContent = '운영자 키 확인 중';
      const verified = await request('/api/sim-control/latest');
      autoAuthenticating = false; autoButton.disabled = false;
      if (!verified) return; // Preserve the authentication or network error shown by request().
      if (token.value !== checkedToken || autoVersion !== checkedVersion ||
          !document.getElementById('simModeBtn')?.classList.contains('active')) {
        status.textContent = '화면 또는 운영자 키가 변경됐습니다. 다시 시도하세요.'; return;
      }
      setAuto(true, '자동 연동 켜짐 · 지도에서 출발점과 화재를 선택하세요. 실제 센서 감시는 하지 않습니다.');
      if (typeof window !== 'undefined') window.dispatchEvent(new CustomEvent('fireguard:request-simulation-state'));
    });

    async function autoSend(version) {
      if (!autoArmed || version !== autoVersion || !latestSelection || autoInFlight) return;
      if (pending) { autoTimer = setTimeout(() => autoSend(version), 500); return; }
      const chosen = latestSelection;
      latestSelection = null;
      autoInFlight = true;
      const sentToken = token.value;
      status.textContent = 'Pi로 모형 시연 요청 중';
      const result = await request('/api/sim-control/commands', chosen);
      if (!result || !result.command?.id) {
        autoInFlight = false;
        setAuto(false, '요청 결과를 확인할 수 없어 자동 연동을 껐습니다. Pi 상태를 확인하세요.');
        return;
      }
      show(result);
      const id = result.command.id;
      activeCommand = {id, token:sentToken, cancelling:false};
      if (!autoArmed || version !== autoVersion) cancelActive();
      // Wait for this exact command to finish before forwarding a newer state.
      for (let i = 0; i < 35; i++) {
        await new Promise(resolve => setTimeout(resolve, 1000));
        if (!autoArmed) { autoInFlight = false; return; }
        const latest = await request('/api/sim-control/latest');
        if (!latest || latest.command?.id !== id) {
          autoInFlight = false; setAuto(false, 'Pi 요청 상태를 확인할 수 없어 자동 연동을 껐습니다.'); return;
        }
        show(latest);
        if (['completed', 'failed', 'rejected', 'expired', 'cancelled', 'not_found'].includes(latest.command.status)) {
          autoInFlight = false;
          const intentionalCancel = activeCommand?.cancelling === true;
          activeCommand = null;
          if (!['completed', 'cancelled'].includes(latest.command.status) &&
              !(intentionalCancel && ['rejected', 'failed'].includes(latest.command.status))) {
            const message = status.textContent;
            setAuto(false, `${message} · 자동 연동 꺼짐`); return;
          }
          if (latestSelection && autoArmed) autoTimer = setTimeout(() => autoSend(autoVersion), 500);
          return;
        }
      }
      autoInFlight = false; setAuto(false, 'Pi 응답 시간이 초과되어 자동 연동을 껐습니다.');
    }
    if (typeof window !== 'undefined') {
      window.addEventListener('fireguard:simulation-ended', () => {
        if (autoArmed || autoAuthenticating) setAuto(false, 'REAL 모드 전환 · 자동 연동 꺼짐');
      });
      window.addEventListener('fireguard:simulation-action', event => {
        if (!autoArmed) return;
        try {
          latestSelection = selectionFrom(event.detail?.state, event.detail?.floorplan);
          autoVersion++;
          cancelActive();
          if (autoTimer !== null) clearTimeout(autoTimer);
          if (!latestSelection) {
            status.textContent = '모의 화재 없음 · 이미 전송된 LED 명령은 즉시 취소되지 않을 수 있습니다.';
            return;
          }
          if (!autoInFlight) autoTimer = setTimeout(() => autoSend(autoVersion), 500);
          else status.textContent = '현재 LED 시험 종료 후 마지막 선택을 전송합니다.';
        } catch (error) { setAuto(false, `${error.message} · 자동 연동 꺼짐`); }
      });
    }
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
      const mode = result.safetyMode === 'simulation_only' ? '모형 시연 · 실제 센서 감시 아님 · ' : '';
      status.textContent = `${states[command.status] || command.status || '상태 확인 중'} · ${mode}${led} · ${route}` +
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
      let response, result, chosen;
      try {
        response = await fetch('/api/cloud/simulation', {method:'POST', headers:{'Content-Type':'application/json'},
          cache:'no-store', body:JSON.stringify({history})});
        result = await response.json();
        if (!response.ok || !result.ok) throw new Error(result.error || '화면 조건을 확인할 수 없습니다.');
        if (!document.getElementById('simModeBtn')?.classList.contains('active') ||
            sessionStorage.getItem('fireguard-simulation-history') !== saved) {
          throw new Error('화면 조건이 변경됐습니다. 다시 시도하세요.');
        }
        chosen = selectionFrom(result.state, result.floorplan);
        if (!chosen) throw new Error('모의 화재 센서를 하나 이상 선택하세요.');
        start.value = chosen.startNode;
        if (chosen.fireNodes.length === 1) fire.value = chosen.fireNodes[0];
      } catch (error) {
        status.textContent = `요청 실패 · ${error.message || '연결을 확인하세요.'}`;
        pending = false; send.disabled = false; fromScreen.disabled = false; refresh.disabled = false;
        return;
      }
      pending = false;
      const data = await request('/api/sim-control/commands', chosen);
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
