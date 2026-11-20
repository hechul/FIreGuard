(() => {
  const id = name => document.getElementById(name);
  const ns = 'http://www.w3.org/2000/svg';
  function svg(tag, attrs) {
    const element = document.createElementNS(ns, tag);
    for (const [key, value] of Object.entries(attrs)) element.setAttribute(key, value);
    return element;
  }
  function ledReadout(state) {
    const c = state.cloud, h = c?.hardware;
    if (state.operationMode === 'simulation') return ['info', '시뮬레이션', '화면에 표시한 모의 경로입니다. 실물 시험 결과는 시험 패널에서 확인하세요.'];
    if (!c?.hasTelemetry || c.stale !== false) return ['muted', '현재 응답 미확인', c?.hasTelemetry ? '마지막 장비 보고 이후 새 응답을 기다립니다.' : '장비 보고 대기 중'];
    if (!h) return ['muted', '명령 응답 미확인', 'Arduino 응답이 포함된 장비 보고를 기다립니다.'];
    if (['disconnected','error'].includes(h.ledStatus)) return ['danger', 'LED 제어 오류', h.ledError || 'Arduino 연결과 명령 응답을 확인하세요.'];
    if (h.ledCommandAck === true && h.ledStatus === 'off') return ['normal', '소등 명령 확인', 'Arduino가 소등 명령에 응답했습니다.'];
    if (h.ledCommandAck === true && h.ledStatus === 'active') return ['normal', '안내 명령 확인', 'Arduino 응답 수신 · 실물 발광은 현장에서 확인'];
    if (h.allZone || h.routeNodes?.length) return ['info', '경로 계산됨', '안내 명령에 대한 Arduino 응답은 미확인입니다.'];
    return ['muted', '안내 명령 대기', '현재 보고에 확인된 안내 명령이 없습니다.'];
  }
  function render(state, plan, points) {
    const incidents = plan.sensors.filter(s => state.flameSensors[s.id]?.active);
    const sim = state.operationMode === 'simulation';
    const outdated = !sim && state.cloud?.enabled && (!state.cloud.hasTelemetry || state.cloud.stale);
    const summary = id('incidentStatus');
    summary.textContent = incidents.length ? (outdated ? '마지막 보고' : sim ? '모의 화재' : '화재 경보') + ' · ' + incidents.length + '곳'
      : outdated ? '현재 상태 미확인' : '감지된 화재 없음';
    summary.dataset.tone = incidents.length ? 'danger' : outdated ? 'warning' : 'normal';
    const layer = id('incidentMapLayer'), list = id('incidentLocations');
    layer.replaceChildren(); list.replaceChildren();
    for (const s of incidents) {
      const p = points[s.node];
      const label = (p?.name || s.name) + ' · ' + s.node;
      const row = document.createElement('div');
      row.className = 'incident-location';
      const name = document.createElement('strong'), status = document.createElement('span');
      name.textContent = label;
      status.textContent = s.id + ' · ' + (outdated || !state.flameSensors[s.id].connected ? '마지막 감지 보고' : sim ? '모의 감지' : '경보 유지 중');
      row.append(name,status); list.append(row);
      if (!p) continue;
      const group = svg('g', {class:'incident-pin'});
      const right = p.x < 435;
      const text = svg('text', {x:p.x + (right ? 12 : -12), y:p.y + 18, 'text-anchor':right ? 'start' : 'end'});
      text.textContent = label;
      group.append(svg('circle',{cx:p.x,cy:p.y,r:11}),text); layer.append(group);
    }
    const [tone,title,detail] = ledReadout(state);
    id('ledCommandState').dataset.tone = tone;
    id('ledCommandState').textContent = title;
    id('ledCommandDetail').textContent = detail;
  }
  window.FireGuardIncidentDisplay = {render};
})();
