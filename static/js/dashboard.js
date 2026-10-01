(() => {
  'use strict';

  const byId = (id) => document.getElementById(id);
  const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

  let floorplan = null;
  let currentState = null;
  let reliabilityChart = null;
  const MAX_CHART_POINTS = 30;
  const chartData = { labels: [], flame: [], smoke: [], currentEmaSmoke: 0, currentEmaFlame: 0 };
  let socket = null;
  let selectedNodeId = null;
  let browserConnected = true;
  let pollTimer = null;
  let demoRunId = 0;

  const STATUS_COPY = {
    normal: { icon: '✓', title: 'SAFE', description: '현재 화재 상황이 없습니다. 모든 경로를 정상 감시 중입니다.' },
    warning: { icon: '!', title: 'WARNING', description: '일부 센서에서 주의 수준이 감지되었습니다. 상태를 확인하세요.' },
    fire: { icon: '🔥', title: 'FIRE DETECTED', description: '화재 또는 위험 수준의 연기가 감지되었습니다. 안전 경로를 재계산합니다.' },
    no_route: { icon: '×', title: 'NO SAFE ROUTE', description: '현재 시작 위치에서 사용 가능한 안전 대피 경로를 찾을 수 없습니다.' },
  };

  function showToast(message, isError = false) {
    const toast = byId('toast');
    toast.textContent = message;
    toast.classList.remove('hidden', 'error');
    if (isError) toast.classList.add('error');
    window.clearTimeout(showToast.timer);
    showToast.timer = window.setTimeout(() => toast.classList.add('hidden'), 2600);
  }

  function fmtTime(iso) {
    if (!iso) return '-';
    try {
      const d = new Date(iso);
      return d.toLocaleTimeString('ko-KR', { hour12: false, hour: '2-digit', minute: '2-digit', second: '2-digit' });
    } catch (_) {
      return String(iso).slice(11, 19);
    }
  }

  function updateClock() {
    const d = new Date();
    byId('currentDate').textContent = d.toLocaleDateString('ko-KR', { year: 'numeric', month: '2-digit', day: '2-digit', weekday: 'short' });
    byId('currentTime').textContent = d.toLocaleTimeString('ko-KR', { hour12: false });
  }

  async function api(path, body = undefined, options = {}) {
    const init = { headers: {} };
    if (body !== undefined) {
      init.method = options.method || 'POST';
      init.headers['Content-Type'] = 'application/json';
      init.body = JSON.stringify(body);
    }
    const response = await fetch(path, init);
    const data = await response.json().catch(() => ({}));
    if (!response.ok || data.ok === false) throw new Error(data.error || `HTTP ${response.status}`);
    return data;
  }

  async function safeApi(path, body) {
    try {
      const result = await api(path, body);
      if (result.state) updateState(result.state);
      return result;
    } catch (error) {
      showToast(error.message || '요청 처리에 실패했습니다.', true);
      return null;
    }
  }

  function nodeMap() {
    const map = {};
    if (!floorplan) return map;
    [...floorplan.nodes, ...floorplan.exits].forEach((item) => { map[item.id] = item; });
    return map;
  }

  function edgeMap() {
    const map = {};
    if (!floorplan) return map;
    floorplan.edges.forEach((item) => { map[item.id] = item; });
    return map;
  }

  function stateClass(status) {
    if (status === 'danger') return 'danger';
    if (status === 'warning') return 'warning';
    if (status === 'offline') return 'offline';
    return 'normal';
  }

  function eventTone(type) {
    if (['FIRE', 'CLEAR'].includes(type)) return 'tone-danger';
    if (['SHUTTER', 'CONNECTION'].includes(type)) return 'tone-warning';
    if (['ROUTE', 'START', 'MODE'].includes(type)) return 'tone-info';
    return 'tone-safe';
  }

  function setChip(id, online, label) {
    const chip = byId(id);
    chip.classList.toggle('off', !online);
    const em = chip.querySelector('em');
    if (em) em.textContent = online ? 'ONLINE' : label || 'OFFLINE';
  }

  function buildSvgLine(a, b, className, attrs = {}) {
    const line = document.createElementNS('http://www.w3.org/2000/svg', 'line');
    line.setAttribute('x1', a.x); line.setAttribute('y1', a.y);
    line.setAttribute('x2', b.x); line.setAttribute('y2', b.y);
    line.setAttribute('class', className);
    Object.entries(attrs).forEach(([key, value]) => line.setAttribute(key, value));
    return line;
  }

  function renderMap(state) {
    if (!floorplan) return;
    const points = nodeMap();
    const edgesById = edgeMap();
    const edgeLayer = byId('edgeLayer');
    const routeLayer = byId('routeLayer');
    const shutterLayer = byId('shutterLayer');
    const sensorLayer = byId('sensorLayer');
    const nodeLayer = byId('nodeLayer');
    const exitLayer = byId('exitLayer');
    [edgeLayer, routeLayer, shutterLayer, sensorLayer, nodeLayer, exitLayer].forEach((g) => { g.innerHTML = ''; });

    floorplan.edges.forEach((edge) => {
      const a = points[edge.from]; const b = points[edge.to];
      if (!a || !b) return;
      const blocked = state.blockedEdges.includes(edge.id);
      const line = buildSvgLine(a, b, blocked ? 'map-edge blocked' : 'map-edge');
      edgeLayer.appendChild(line);
    });

    if (state.route && state.route.nodes?.length > 1) {
      for (let i = 0; i < state.route.nodes.length - 1; i += 1) {
        const from = points[state.route.nodes[i]];
        const to = points[state.route.nodes[i + 1]];
        if (!from || !to) continue;
        routeLayer.appendChild(buildSvgLine(from, to, 'route-edge', { 'marker-end': 'url(#arrowGreen)' }));
      }
    }

    floorplan.shutters.forEach((shutter) => {
      const edge = edgesById[shutter.edge];
      if (!edge) return;
      const a = points[edge.from]; const b = points[edge.to];
      const x = (a.x + b.x) / 2; const y = (a.y + b.y) / 2;
      const rect = document.createElementNS('http://www.w3.org/2000/svg', 'rect');
      rect.setAttribute('x', x - 8); rect.setAttribute('y', y - 4);
      rect.setAttribute('width', 16); rect.setAttribute('height', 8); rect.setAttribute('rx', 1.5);
      rect.setAttribute('class', `shutter-mark ${state.shutters[shutter.id]?.closed ? 'closed' : ''}`);
      const title = document.createElementNS('http://www.w3.org/2000/svg', 'title');
      title.textContent = `${shutter.id} · ${shutter.name}`;
      rect.appendChild(title); shutterLayer.appendChild(rect);
    });

    floorplan.sensors.filter((s) => s.type === 'flame').forEach((sensor, index) => {
      const p = points[sensor.node]; if (!p) return;
      const active = Boolean(state.flameSensors[sensor.id]?.active);
      const dot = document.createElementNS('http://www.w3.org/2000/svg', 'circle');
      const offset = (index % 3) * 3;
      dot.setAttribute('cx', p.x + 10 + offset); dot.setAttribute('cy', p.y - 10);
      dot.setAttribute('r', 3.4); dot.setAttribute('class', `sensor-dot flame ${active ? 'danger' : ''}`);
      const title = document.createElementNS('http://www.w3.org/2000/svg', 'title');
      title.textContent = `${sensor.id} · ${sensor.name} · ${active ? '화재 감지' : '정상'}`;
      dot.appendChild(title); sensorLayer.appendChild(dot);
    });

    floorplan.sensors.filter((s) => s.type === 'mq2').forEach((sensor, index) => {
      const p = points[sensor.node]; if (!p) return;
      const mq = state.mq2Sensors[sensor.id];
      const rect = document.createElementNS('http://www.w3.org/2000/svg', 'rect');
      rect.setAttribute('x', p.x - 15 - (index % 2) * 2); rect.setAttribute('y', p.y - 15);
      rect.setAttribute('width', 6.8); rect.setAttribute('height', 6.8); rect.setAttribute('rx', 2);
      rect.setAttribute('class', `sensor-dot mq2 ${mq?.status || 'normal'}`);
      const title = document.createElementNS('http://www.w3.org/2000/svg', 'title');
      title.textContent = `${sensor.id} · ${sensor.name} · ${mq?.value ?? 0}`;
      rect.appendChild(title); sensorLayer.appendChild(rect);
    });

    floorplan.nodes.forEach((node) => {
      const group = document.createElementNS('http://www.w3.org/2000/svg', 'g');
      group.setAttribute('role', 'button'); group.setAttribute('tabindex', '0');
      const blocked = state.blockedNodes.includes(node.id);
      const classes = ['map-node'];
      if (blocked) classes.push('blocked');
      if (state.startNode === node.id) classes.push('start');
      if (selectedNodeId === node.id) classes.push('selected');
      const circle = document.createElementNS('http://www.w3.org/2000/svg', 'circle');
      circle.setAttribute('cx', node.x); circle.setAttribute('cy', node.y); circle.setAttribute('r', 6.4);
      circle.setAttribute('class', classes.join(' '));
      const label = document.createElementNS('http://www.w3.org/2000/svg', 'text');
      label.setAttribute('x', node.x); label.setAttribute('y', node.y - 10); label.setAttribute('text-anchor', 'middle');
      label.setAttribute('class', 'node-label'); label.textContent = node.id;
      const title = document.createElementNS('http://www.w3.org/2000/svg', 'title'); title.textContent = `${node.id} · ${node.name}`;
      group.append(circle, label, title);
      group.addEventListener('click', () => selectNode(node.id));
      group.addEventListener('keydown', (e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); selectNode(node.id); } });
      nodeLayer.appendChild(group);
    });

    floorplan.exits.forEach((exit) => {
      const group = document.createElementNS('http://www.w3.org/2000/svg', 'g');
      const rect = document.createElementNS('http://www.w3.org/2000/svg', 'rect');
      rect.setAttribute('x', exit.x - 10); rect.setAttribute('y', exit.y - 9); rect.setAttribute('width', 20); rect.setAttribute('height', 18); rect.setAttribute('rx', 3); rect.setAttribute('class', 'exit-box');
      const label = document.createElementNS('http://www.w3.org/2000/svg', 'text');
      label.setAttribute('x', exit.x); label.setAttribute('y', exit.y + 3); label.setAttribute('text-anchor', 'middle'); label.setAttribute('class', 'exit-label'); label.textContent = 'EXIT';
      const title = document.createElementNS('http://www.w3.org/2000/svg', 'title'); title.textContent = exit.name;
      group.append(rect, label, title); exitLayer.appendChild(group);
    });

    byId('startNodeLabel').textContent = state.startNode;
    byId('exitLabel').textContent = state.selectedExitName || '없음';
    byId('costLabel').textContent = state.route ? state.route.cost.toFixed(1) : '-';
    byId('blockedLabel').textContent = `${state.blockedNodes.length + state.blockedEdges.length} 구간`;
  }

  function renderHeader(state) {
    setChip('piChip', state.connections.pi);
    setChip('cloudChip', state.connections.server);
    setChip('flaskChip', browserConnected);

    const realBtn = byId('realModeBtn');
    const simBtn = byId('simModeBtn');
    realBtn.classList.toggle('active', state.operationMode === 'real');
    simBtn.classList.toggle('active', state.operationMode === 'simulation');
    document.querySelectorAll('.simulation-only').forEach((el) => { el.disabled = state.operationMode !== 'simulation'; });
    byId('realModeNotice').classList.toggle('hidden', state.operationMode !== 'real');
    byId('operationModeLabel').textContent = state.operationMode.toUpperCase();
  }

  function renderSystemBanner(state) {
    const copy = STATUS_COPY[state.overallStatus] || STATUS_COPY.normal;
    const banner = byId('systemBanner');
    let className = state.overallStatus === 'no_route' ? 'no-route' : state.overallStatus;
    if (state.failSafeActive && state.overallStatus === 'normal') className = 'failsafe';
    banner.className = `system-banner ${className}`;

    let title = copy.title;
    let description = copy.description;
    let icon = copy.icon;
    if (state.failSafeActive && state.overallStatus === 'normal') {
      title = 'LOCAL FAIL-SAFE'; icon = '!'; description = '외부 서버 연결이 끊어졌습니다. Raspberry Pi 로컬 경로 계산과 LED 유도는 계속 유지됩니다.';
    }
    byId('systemIcon').textContent = icon;
    byId('systemTitle').textContent = title;
    byId('systemDescription').textContent = description;
    byId('updatedAt').textContent = fmtTime(state.updatedAt);
  }

  function renderResponse(state) {
    byId('selectedExitName').textContent = state.selectedExitName || '경로 없음';
    byId('routeStatusText').textContent = state.route ? '경로 확보' : '대피 불가';
    byId('routeCostText').textContent = state.route ? `비용 ${state.route.cost.toFixed(1)}` : '경로를 확인하세요';
    const names = nodeMap();
    byId('routeNodeText').textContent = state.route ? state.route.nodes.map((id) => names[id]?.name || id).join(' → ') : '안전한 경로 없음';
    byId('failSafeNotice').classList.toggle('hidden', !state.failSafeActive);
    byId('noRouteNotice').classList.toggle('hidden', Boolean(state.route));
  }

  function renderSensors(state) {
    const counts = state.sensorCounts;
    byId('flameCount').textContent = `${counts.flameActive} / ${counts.flameTotal}`;
    byId('mq2Count').textContent = `${counts.mq2Danger} / ${counts.mq2Total}`;
    byId('flameStateText').textContent = counts.flameActive ? '화재 감지' : '정상 (화재 감지 없음)';
    byId('mq2StateText').textContent = counts.mq2Danger ? '위험 감지' : counts.mq2Warning ? '주의 감지' : '정상 (연기/가스 감지 없음)';

    const flameBox = byId('flameCount').closest('.sensor-metric');
    const mqBox = byId('mq2Count').closest('.sensor-metric');
    flameBox.classList.toggle('has-danger', counts.flameActive > 0);
    mqBox.classList.toggle('has-danger', counts.mq2Danger > 0);
    mqBox.classList.toggle('has-warning', counts.mq2Danger === 0 && counts.mq2Warning > 0);

    const normalFlame = Object.values(state.flameSensors).filter((v) => v.connected && !v.active).length;
    const normalMq = Object.values(state.mq2Sensors).filter((v) => v.connected && v.status === 'normal').length;
    const disconnected = state.equipment.filter((e) => e.status === 'offline').length;
    byId('sensorSummary').innerHTML = `
      <div class="sensor-row"><span>불꽃 센서 정상</span><strong class="${counts.flameActive ? 'state-danger' : 'state-normal'}">${normalFlame}/${counts.flameTotal}</strong></div>
      <div class="sensor-row"><span>MQ-2 정상</span><strong class="${counts.mq2Danger ? 'state-danger' : counts.mq2Warning ? 'state-warning' : 'state-normal'}">${normalMq}/${counts.mq2Total}</strong></div>
      <div class="sensor-row"><span>MQ-2 주의 / 위험</span><strong class="${counts.mq2Danger ? 'state-danger' : counts.mq2Warning ? 'state-warning' : 'state-normal'}">${counts.mq2Warning} / ${counts.mq2Danger}</strong></div>
      <div class="sensor-row"><span>연결 끊김 장비</span><strong class="${disconnected ? 'state-warning' : 'state-normal'}">${disconnected}</strong></div>`;
  }

  function renderEquipment(state) {
    const q = (byId('equipmentSearch').value || '').trim().toLowerCase();
    const filter = byId('equipmentFilter').value;
    const rows = state.equipment.filter((e) => {
      const matchesFilter = filter === 'all' || e.status === filter;
      const haystack = `${e.id} ${e.category} ${e.name} ${e.location}`.toLowerCase();
      return matchesFilter && haystack.includes(q);
    });
    byId('equipmentRows').innerHTML = rows.map((e) => `
      <tr><td>${e.id}</td><td>${e.category}</td><td>${e.name}</td><td>${e.location}</td><td>${e.value ?? '-'}</td><td><span class="status-chip ${stateClass(e.status)}">${e.stateLabel}</span></td><td>${fmtTime(e.lastSeen)}</td></tr>`).join('') || '<tr><td colspan="7">조건에 맞는 장비가 없습니다.</td></tr>';
  }

  function renderEvents(state) {
    byId('eventCount').textContent = `${state.events.length} EVENTS`;
    byId('eventList').innerHTML = state.events.map((e) => `
      <div class="event-row">
        <div class="event-time">${e.timestamp.replace('T', ' ').slice(0, 19)}</div>
        <div class="event-type ${eventTone(e.type)}">${e.type}</div>
        <div class="event-location">${e.location}</div>
        <div class="event-detail"><strong>${e.change}</strong><br><span>${e.result}</span></div>
      </div>`).join('') || '<div class="event-row"><div class="event-detail">이벤트 기록 없음</div></div>';

    const recent = state.events.slice(0, 5);
    byId('miniEventList').innerHTML = recent.map((e) => {
      const tone = ['FIRE', 'CLEAR'].includes(e.type) ? 'danger' : ['SHUTTER', 'CONNECTION'].includes(e.type) ? 'warning' : '';
      return `<div class="mini-event ${tone}"><i></i><span><strong>${fmtTime(e.timestamp)} · ${e.type}</strong><br>${e.change}</span></div>`;
    }).join('') || '<div class="mini-event"><i></i><span>이벤트 기록 없음</span></div>';
  }

  function renderRouting(state) {
    byId('manualBlockedList').innerHTML = state.manualBlockedEdges.length
      ? state.manualBlockedEdges.map((id) => `<div class="blocked-item"><span>${id}</span><strong>BLOCKED</strong></div>`).join('')
      : '<div class="sensor-row"><span>관리자 수동 차단 없음</span><strong class="state-normal">OPEN</strong></div>';
  }

  function renderQr(state) {
    const names = nodeMap();
    byId('mobileExitPreview').textContent = state.selectedExitName || '경로 없음';
    byId('mobileRoutePreview').textContent = state.route ? state.route.nodes.map((id) => names[id]?.name || id).join(' → ') : '안전한 경로를 찾을 수 없습니다.';
  }

  function initChart() {
    const ctx = document.getElementById('reliabilityChart');
    if (!ctx) return;
    reliabilityChart = new Chart(ctx, {
      type: 'line',
      data: {
        labels: chartData.labels,
        datasets: [
          {
            label: '불꽃 신뢰도',
            data: chartData.flame,
            borderColor: '#F04452',
            backgroundColor: 'rgba(240, 68, 82, 0.1)',
            borderWidth: 2,
            pointRadius: 2,
            fill: true,
            tension: 0.4
          },
          {
            label: '연기 신뢰도',
            data: chartData.smoke,
            borderColor: '#8B95A1',
            backgroundColor: 'rgba(139, 149, 161, 0.1)',
            borderWidth: 2,
            pointRadius: 2,
            fill: true,
            tension: 0.4
          }
        ]
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        animation: { duration: 0 },
        scales: {
          x: { display: true, ticks: { maxTicksLimit: 8, font: {size: 10} }, grid: { display: false } },
          y: { display: true, min: 0, max: 100, ticks: { stepSize: 20, font: {size: 10} } }
        },
        plugins: {
          legend: { display: true, position: 'top', align: 'end', labels: { font: {size: 11, weight: 'bold'}, boxWidth: 12 } }
        }
      }
    });
  }

  function updateChart(state) {
    if (!reliabilityChart) return;
    
    const now = new Date();
    const timeStr = `${now.getHours().toString().padStart(2,'0')}:${now.getMinutes().toString().padStart(2,'0')}:${now.getSeconds().toString().padStart(2,'0')}`;
    
    let maxMq2 = 0;
    for (const key in state.mq2Sensors) {
      if (state.mq2Sensors[key].value > maxMq2) {
        maxMq2 = state.mq2Sensors[key].value;
      }
    }
    // Assume 800 is a very high value representing 100%
    let currentSmoke = Math.min((maxMq2 / 800) * 100, 100);
    // If flame active > 0, set to 100%
    let currentFlame = state.sensorCounts.flameActive > 0 ? 100 : 0;

    // Exponential Moving Average to simulate the "few seconds margin" reliability
    chartData.currentEmaSmoke = (chartData.currentEmaSmoke * 0.7) + (currentSmoke * 0.3);
    chartData.currentEmaFlame = (chartData.currentEmaFlame * 0.6) + (currentFlame * 0.4);

    chartData.labels.push(timeStr);
    chartData.smoke.push(chartData.currentEmaSmoke);
    chartData.flame.push(chartData.currentEmaFlame);
    
    if (chartData.labels.length > MAX_CHART_POINTS) {
      chartData.labels.shift();
      chartData.smoke.shift();
      chartData.flame.shift();
    }
    
    reliabilityChart.update();
  }

  function updateState(state) {
    currentState = state;
    updateChart(state);
    renderHeader(state);
    renderSystemBanner(state);
    renderMap(state);
    renderResponse(state);
    renderSensors(state);
    renderEquipment(state);
    renderEvents(state);
    renderRouting(state);
    renderQr(state);
    refreshNodeActionCard();
  }

  function buildControls() {
    byId('startNodeSelect').innerHTML = floorplan.nodes.map((n) => `<option value="${n.id}">${n.id} · ${n.name}</option>`).join('');
    byId('flameSelect').innerHTML = floorplan.sensors.filter((s) => s.type === 'flame').map((s) => `<option value="${s.id}">${s.id} · ${s.name}</option>`).join('');
    byId('mq2Select').innerHTML = floorplan.sensors.filter((s) => s.type === 'mq2').map((s) => `<option value="${s.id}">${s.id} · ${s.name}</option>`).join('');
    byId('manualEdgeSelect').innerHTML = floorplan.edges.map((e) => `<option value="${e.id}">${e.id} · ${e.from} ↔ ${e.to} · W=${e.weight}</option>`).join('');
    byId('shutterControls').innerHTML = floorplan.shutters.map((s) => `
      <div class="shutter-item"><strong>${s.name}</strong><p>${s.id} · ${s.edge}</p><div class="inline-control"><button type="button" class="btn warning simulation-only" data-shutter="${s.id}" data-closed="true">닫기</button><button type="button" class="btn secondary simulation-only" data-shutter="${s.id}" data-closed="false">열기</button></div></div>`).join('');
    byId('shutterControls').querySelectorAll('[data-shutter]').forEach((button) => {
      button.addEventListener('click', () => safeApi('/api/simulation/shutter', { shutterId: button.dataset.shutter, closed: button.dataset.closed === 'true' }));
    });
  }

  function selectNode(nodeId) {
    if (!currentState || currentState.operationMode !== 'simulation') return;
    selectedNodeId = nodeId;
    refreshNodeActionCard();
    renderMap(currentState);
  }

  function refreshNodeActionCard() {
    if (!floorplan || !selectedNodeId) return;
    const card = byId('nodeActionCard');
    const node = floorplan.nodes.find((n) => n.id === selectedNodeId);
    if (!node || !currentState || currentState.operationMode !== 'simulation') {
      card.classList.add('hidden'); return;
    }
    const sensors = floorplan.sensors.filter((s) => s.node === selectedNodeId);
    byId('selectedNodeTitle').textContent = `${node.id} · ${node.name}`;
    byId('selectedNodeSensors').textContent = sensors.length ? `연결 센서: ${sensors.map((s) => `${s.id}(${s.type === 'mq2' ? 'MQ-2' : 'Flame'})`).join(', ')}` : '연결된 센서 없음';
    card.classList.remove('hidden');
  }

  function closeNodeActionCard() {
    selectedNodeId = null;
    byId('nodeActionCard').classList.add('hidden');
    if (currentState) renderMap(currentState);
  }

  async function setMode(mode) {
    const result = await safeApi('/api/mode', { mode });
    if (result?.state && mode === 'real') closeNodeActionCard();
  }

  async function runScenario(scenarioId) {
    if (!currentState || currentState.operationMode !== 'simulation') {
      showToast('SIMULATION 모드에서만 사용할 수 있습니다.', true); return;
    }
    return safeApi('/api/simulation/scenario', { scenarioId });
  }

  async function runAutoDemo() {
    if (!currentState || currentState.operationMode !== 'simulation') return;
    const runId = ++demoRunId;
    byId('autoDemoBtn').disabled = true;
    byId('stopDemoBtn').disabled = false;
    const steps = [
      ['STEP 1 · NORMAL', 'normal', 1800],
      ['STEP 2 · EAST EXIT FIRE', 'east_exit_fire', 2600],
      ['STEP 3 · SERVER LOST / FAIL-SAFE', 'server_off', 2600],
      ['STEP 4 · SERVER RECOVERY', 'server_on', 1800],
    ];
    for (const [label, scenario, wait] of steps) {
      if (runId !== demoRunId) break;
      byId('demoStep').textContent = label;
      await runScenario(scenario);
      await sleep(wait);
    }
    if (runId === demoRunId) byId('demoStep').textContent = 'DEMO COMPLETE';
    byId('autoDemoBtn').disabled = currentState?.operationMode !== 'simulation';
    byId('stopDemoBtn').disabled = true;
  }

  function stopAutoDemo() {
    demoRunId += 1;
    byId('demoStep').textContent = 'STOPPED';
    byId('autoDemoBtn').disabled = currentState?.operationMode !== 'simulation';
    byId('stopDemoBtn').disabled = true;
  }

  function showPage(pageId) {
    document.querySelectorAll('.nav-item').forEach((b) => b.classList.toggle('active', b.dataset.page === pageId));
    document.querySelectorAll('.page').forEach((p) => p.classList.toggle('active', p.id === pageId));
    const titles = { overview: '실시간 화재 대피 통합 관제', equipment: '장비 관리', routing: '경로 및 수동 설정', events: '이벤트 기록', qr: 'QR 기반 모바일 대피 안내' };
    byId('pageTitle').textContent = titles[pageId] || 'FireGuard';
    window.scrollTo({ top: 0, behavior: 'smooth' });
  }

  function bindActions() {
    document.querySelectorAll('.nav-item').forEach((button) => button.addEventListener('click', () => showPage(button.dataset.page)));
    document.querySelectorAll('.nav-shortcut').forEach((button) => button.addEventListener('click', () => showPage(button.dataset.targetPage)));
    document.querySelectorAll('[data-scenario]').forEach((button) => button.addEventListener('click', () => runScenario(button.dataset.scenario)));

    byId('realModeBtn').addEventListener('click', () => setMode('real'));
    byId('simModeBtn').addEventListener('click', () => setMode('simulation'));
    byId('autoDemoBtn').addEventListener('click', runAutoDemo);
    byId('stopDemoBtn').addEventListener('click', stopAutoDemo);
    byId('serverRestoreBtn').addEventListener('click', () => runScenario('server_on'));

    byId('nodeActionClose').addEventListener('click', closeNodeActionCard);
    byId('selectedFireBtn').addEventListener('click', () => selectedNodeId && safeApi('/api/simulation/node-fire', { nodeId: selectedNodeId, active: true }));
    byId('selectedClearBtn').addEventListener('click', () => selectedNodeId && safeApi('/api/simulation/node-fire', { nodeId: selectedNodeId, active: false }));
    byId('selectedStartBtn').addEventListener('click', () => selectedNodeId && safeApi('/api/simulation/start-node', { nodeId: selectedNodeId }));

    byId('equipmentSearch').addEventListener('input', () => currentState && renderEquipment(currentState));
    byId('equipmentFilter').addEventListener('change', () => currentState && renderEquipment(currentState));
    byId('startApplyBtn').addEventListener('click', () => safeApi('/api/simulation/start-node', { nodeId: byId('startNodeSelect').value }));
    byId('flameOnBtn').addEventListener('click', () => safeApi('/api/simulation/flame', { sensorId: byId('flameSelect').value, active: true }));
    byId('flameOffBtn').addEventListener('click', () => safeApi('/api/simulation/flame', { sensorId: byId('flameSelect').value, active: false }));
    byId('mq2Range').addEventListener('input', () => { byId('mq2Value').textContent = byId('mq2Range').value; });
    byId('mq2ApplyBtn').addEventListener('click', () => safeApi('/api/simulation/mq2', { sensorId: byId('mq2Select').value, value: Number(byId('mq2Range').value) }));
    byId('edgeBlockBtn').addEventListener('click', () => safeApi('/api/simulation/manual-edge', { edgeId: byId('manualEdgeSelect').value, blocked: true }));
    byId('edgeOpenBtn').addEventListener('click', () => safeApi('/api/simulation/manual-edge', { edgeId: byId('manualEdgeSelect').value, blocked: false }));
  }

  function setBrowserConnection(connected) {
    browserConnected = connected;
    byId('browserOfflineBanner').classList.toggle('hidden', connected);
    if (currentState) renderHeader(currentState);
  }

  function startPollingFallback() {
    if (pollTimer) return;
    pollTimer = window.setInterval(async () => {
      try {
        const s = await api('/api/state');
        setBrowserConnection(true);
        updateState(s);
      } catch (_) {
        setBrowserConnection(false);
      }
    }, 1000);
  }

  function stopPollingFallback() {
    if (!pollTimer) return;
    window.clearInterval(pollTimer); pollTimer = null;
  }

  function connectSocket() {
    if (typeof window.io !== 'function') {
      setBrowserConnection(false); startPollingFallback(); return;
    }
    socket = window.io({ reconnection: true, reconnectionDelay: 700, reconnectionDelayMax: 2500 });
    socket.on('connect', () => { setBrowserConnection(true); stopPollingFallback(); });
    socket.on('disconnect', () => { setBrowserConnection(false); startPollingFallback(); });
    socket.on('state:update', (state) => { setBrowserConnection(true); updateState(state); });
    socket.on('connect_error', () => { setBrowserConnection(false); startPollingFallback(); });
  }

  async function init() {
    updateClock(); window.setInterval(updateClock, 1000);
    try {
      [floorplan, currentState] = await Promise.all([api('/api/floorplan'), api('/api/state')]);
      buildControls(); bindActions(); initChart(); updateState(currentState); connectSocket();
    } catch (error) {
      showToast(`초기화 실패: ${error.message}`, true); setBrowserConnection(false); startPollingFallback();
    }
  }

  init();
})();
