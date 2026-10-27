(() => {
  'use strict';

  const byId = (id) => document.getElementById(id);
  const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

  let floorplan = null;
  let currentState = null;
  let socket = null;
  let selectedNodeId = null;
  let browserConnected = true;
  let pollTimer = null;
  let demoRunId = 0;

  // 2D / 3D map view state
  let mapViewMode = '2d'; // '2d' | '3d'
  let map3dReady   = false;

  // Map Editor state
  let editorMode = 'node';
  let editorPositions = {};
  let editorSavedPositions = {};
  let editorSelected = null;
  let editorDrag = null;
  let editorUndoStack = [];
  let editorDraft = null;
  let editorBase = null;
  let editorConnectFrom = null;
  let editorSaving = false;
  let geometryRouter = null;
  let geometrySignature = '';

  const copy = (value) => JSON.parse(JSON.stringify(value));
  const editorActive = () => byId('mapEditor').classList.contains('active') && !editorSaving;
  const editorDirty = () => editorDraft && (JSON.stringify(editorDraft) !== JSON.stringify(editorBase) || !editorPositionsEqual(editorPositions, editorSavedPositions));

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
    if (['SHUTTER', 'CONNECTION', 'CONGESTION', 'SENSOR'].includes(type)) return 'tone-warning';
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

  function router() {
    const signature = JSON.stringify([floorplan.rooms || [], floorplan.edges || []]);
    if (!geometryRouter || geometrySignature !== signature) {
      geometryRouter = MapGeometry.createRouter(floorplan);
      geometrySignature = signature;
    }
    return geometryRouter;
  }

  function buildEdgePath(a, b, className) {
    const path = document.createElementNS('http://www.w3.org/2000/svg', 'polyline');
    const points = router().route(a, b);
    path.setAttribute('points', points ? points.map(p => `${p.x},${p.y}`).join(' ') : '');
    path.setAttribute('class', className);
    path.setAttribute('fill', 'none');
    path.setAttribute('stroke-linejoin', 'round');
    return path;
  }

  function renderFloorplanBase() {
    const element = (tag, attrs, text) => {
      const el = document.createElementNS('http://www.w3.org/2000/svg', tag);
      Object.entries(attrs).forEach(([key, value]) => el.setAttribute(key, value));
      if (text) el.textContent = text;
      return el;
    };
    document.querySelectorAll('.schematic-base').forEach(svg => {
      svg.replaceChildren(element('rect', {class: 'plan-bg', x: 8, y: 8, width: 568, height: 842, rx: 10}));
      for (const guide of floorplan.corridorGuides || []) svg.appendChild(buildSvgLine(guide[0], guide[1], 'corridor-guide'));
      for (const room of floorplan.rooms || []) {
        svg.appendChild(element('rect', {class: `room ${room.kind} door-room`, x: room.x, y: room.y, width: room.width, height: room.height}));
        for (const wall of MapGeometry.wallRects(room)) svg.appendChild(element('rect', {...wall, class: 'room-wall'}));
        const cx = room.x + room.width/2, cy = room.y + room.height/2;
        const labelY = room.kind === 'utility' ? room.y + room.height - 12 : room.y > 580 ? cy + 35 : cy - 30;
        svg.appendChild(element('text', {class: `room-title ${room.kind === 'utility' ? 'tiny' : 'small'}`, x: cx, y: labelY}, room.name));
        for (const door of room.doors || []) {
          const horizontal = door.side === 'top' || door.side === 'bottom';
          const x = horizontal ? room.x + door.offset : door.side === 'left' ? room.x : room.x + room.width;
          const y = horizontal ? (door.side === 'top' ? room.y : room.y + room.height) : room.y + door.offset;
          const end = horizontal ? {x: x + door.width, y} : {x, y: y + door.width};
          const threshold = buildSvgLine({x,y}, end, 'door-threshold');
          threshold.appendChild(element('title', {}, `${room.name} 출입문`));
          svg.appendChild(threshold);
          svg.appendChild(element('text', {class: 'door-label', x: horizontal ? x+door.width/2 : x+7, y: horizontal ? y-7 : y+door.width/2-5, 'text-anchor': horizontal ? 'middle' : 'start'}, '문'));
        }
      }
      const descender = floorplan.nodes.find(n => n.id === 'N3');
      if (descender) svg.appendChild(element('text', {class: 'descender-label', x: descender.x, y: descender.y-18}, '완강기'));
      // Keep physical LEDs separate from editable nodes and evacuation edges.
      if (svg.closest('#mapStage')) {
        const leds = element('g', {class: 'physical-led-layer', 'pointer-events': 'none', 'aria-label': 'LED 유도등'});
        for (const [start, end] of window.FireGuardLedPlan) {
          const attrs = {x1: start[0], y1: start[1], x2: end[0], y2: end[1], 'stroke-linecap': 'round'};
          leds.appendChild(element('line', {...attrs, stroke: '#64748b', 'stroke-width': 5}));
          leds.appendChild(element('line', {...attrs, stroke: '#e2e8f0', 'stroke-width': 2, 'stroke-dasharray': '1 12'}));
        }
        svg.appendChild(leds);
      }
    });
  }


  function clamp(value, min, max) {
    return Math.max(min, Math.min(max, value));
  }

  function updateRouteVisualScale() {
    const stage = byId('mapStage');
    const svg = byId('floorSvg');
    const marker = byId('arrowGreen');
    if (!stage || !svg || !marker) return;

    const rect = stage.getBoundingClientRect();
    const scale = Math.min(rect.width / 584, rect.height / 858);
    const stroke = clamp(4.8 * scale, 2.6, 5.0);
    const arrow = clamp(8.2 * scale, 4.8, 8.2);

    svg.style.setProperty('--route-stroke', `${stroke.toFixed(2)}px`);
    stage.style.setProperty('--route-stroke', `${stroke.toFixed(2)}px`);
    stage.style.setProperty('--route-arrow-size', `${arrow.toFixed(2)}px`);

    marker.setAttribute('markerWidth', arrow.toFixed(2));
    marker.setAttribute('markerHeight', arrow.toFixed(2));
    marker.setAttribute('refX', (arrow * 0.82).toFixed(2));
    marker.setAttribute('refY', (arrow / 2).toFixed(2));
  }


  function editorPointMap() {
    const map = {};
    if (!floorplan) return map;
    [...editorDraft.nodes, ...editorDraft.exits].forEach((item) => {
      const current = editorPositions[item.id] || { x: Number(item.x), y: Number(item.y) };
      map[item.id] = { ...item, x: Number(current.x), y: Number(current.y) };
    });
    return map;
  }

  function cloneEditorPositions(source = editorPositions) {
    const copy = {};
    Object.entries(source).forEach(([id, p]) => {
      copy[id] = { x: Number(p.x), y: Number(p.y) };
    });
    return copy;
  }

  function initEditorPositions() {
    if (!floorplan) return;
    editorDraft = copy(floorplan);
    editorBase = copy(floorplan);
    editorConnectFrom = null;
    editorPositions = {};
    [...floorplan.nodes, ...floorplan.exits].forEach((item) => {
      editorPositions[item.id] = { x: Number(item.x), y: Number(item.y) };
    });
    editorSavedPositions = cloneEditorPositions();
    editorUndoStack = [];
    editorSelected = null;
    byId('editorUndoBtn').disabled = true;
    updateEditorDirtyState();
    renderMapEditor();
    updateEditorInspector();
  }

  function editorSnap(value) {
    const snap = byId('editorSnapToggle')?.checked;
    return snap ? Math.round(value / 5) * 5 : Math.round(value * 10) / 10;
  }

  function editorSvgPoint(event) {
    const svg = byId('mapEditorSvg');
    const point = svg.createSVGPoint();
    point.x = event.clientX;
    point.y = event.clientY;
    return point.matrixTransform(svg.getScreenCTM().inverse());
  }

  function clampEditorPoint(point) {
    return {
      x: Math.max(8, Math.min(576, editorSnap(point.x))),
      y: Math.max(8, Math.min(850, editorSnap(point.y))),
    };
  }

  function pushEditorUndo() {
    editorUndoStack.push({ positions: cloneEditorPositions(), draft: copy(editorDraft) });
    if (editorUndoStack.length > 40) editorUndoStack.shift();
    const button = byId('editorUndoBtn');
    if (button) button.disabled = editorUndoStack.length === 0;
  }

  function editorPositionsEqual(a, b) {
    const keys = Object.keys(a);
    if (keys.length !== Object.keys(b).length) return false;
    return keys.every((id) =>
      Math.abs(Number(a[id]?.x) - Number(b[id]?.x)) < 0.01 &&
      Math.abs(Number(a[id]?.y) - Number(b[id]?.y)) < 0.01
    );
  }

  function updateEditorDirtyState() {
    const badge = byId('editorDirtyBadge');
    if (!badge) return;
    const dirty = editorDirty();
    badge.textContent = dirty ? '저장 전' : '저장됨';
    badge.classList.toggle('dirty', dirty);
    badge.classList.toggle('clean', !dirty);
  }

  function setEditorMode(mode) {
    editorDrag = null;
    editorConnectFrom = null;
    editorMode = mode;
    byId('editorNodeModeBtn')?.classList.toggle('active', mode === 'node');
    byId('editorEdgeModeBtn')?.classList.toggle('active', mode === 'edge');
    byId('editorAddNodeBtn').classList.toggle('active', mode === 'add');
    byId('editorConnectBtn').classList.toggle('active', mode === 'connect');
    byId('editorModeHint').textContent = ({node: '노드 또는 출구를 드래그하세요.', edge: '간선을 드래그하면 양 끝 지점이 함께 이동합니다.', add: '지도에서 새 노드를 놓을 빈 위치를 클릭하세요.', connect: '연결할 첫 번째 지점과 두 번째 지점을 차례로 클릭하세요.'})[mode];
    const stage = byId('mapEditorStage');
    if (stage) stage.dataset.mode = mode;
    renderMapEditor();
  }

  function selectEditorItem(type, id) {
    editorSelected = { type, id };
    renderMapEditor();
    updateEditorInspector();
  }

  function renderMapEditor() {
    if (!editorDraft || !byId('mapEditorSvg')) return;

    const points = editorPointMap();
    const edgeLayer = byId('editorEdgeLayer');
    const nodeLayer = byId('editorNodeLayer');
    edgeLayer.innerHTML = '';
    nodeLayer.innerHTML = '';

    editorDraft.edges.forEach((edge) => {
      const a = points[edge.from];
      const b = points[edge.to];
      if (!a || !b) return;

      const group = document.createElementNS('http://www.w3.org/2000/svg', 'g');
      group.setAttribute('class', 'editor-edge-group');

      // 넓은 투명 hit area
      const hit = buildEdgePath(a, b, 'editor-edge-hit');
      hit.dataset.edgeId = edge.id;

      const visible = buildEdgePath(
        a,
        b,
        `editor-edge-line ${editorSelected?.type === 'edge' && editorSelected.id === edge.id ? 'selected' : ''}`
      );

      const middle = MapGeometry.midpoint(router().route(a, b)) || a;
      const midX = middle.x;
      const midY = middle.y;
      const label = document.createElementNS('http://www.w3.org/2000/svg', 'text');
      label.setAttribute('x', midX);
      label.setAttribute('y', midY - 5);
      label.setAttribute('class', 'editor-edge-label');
      label.setAttribute('text-anchor', 'middle');
      label.textContent = edge.id;

      hit.addEventListener('pointerdown', (event) => {
        if (!editorActive() || event.button !== 0) return;
        if (editorMode === 'add') return; // Let event bubble to SVG for node addition / edge splitting
        event.preventDefault();
        event.stopPropagation();
        if (editorMode === 'connect') return;
        byId('mapEditorSvg').setPointerCapture(event.pointerId);
        selectEditorItem('edge', edge.id);
        if (editorMode !== 'edge') return;

        pushEditorUndo();
        const start = editorSvgPoint(event);
        editorDrag = {
          kind: 'edge',
          id: edge.id,
          from: edge.from,
          to: edge.to,
          start,
          fromStart: { ...editorPositions[edge.from] },
          toStart: { ...editorPositions[edge.to] },
        };
        byId('mapEditorSvg').setPointerCapture?.(event.pointerId);
      });

      hit.addEventListener('click', (event) => {
        if (editorMode === 'add' || editorMode === 'connect') return;
        selectEditorItem('edge', edge.id);
      });
      group.append(visible, hit, label);
      edgeLayer.appendChild(group);
    });

    const fallbackIds = new Set((editorDraft.fallbackDestinations || []).map((item) => item.id));

    [...editorDraft.nodes, ...editorDraft.exits].forEach((point) => {
      const p = points[point.id];
      const isExit = floorplan.exits.some((exit) => exit.id === point.id);
      const selected = editorSelected?.type === 'node' && editorSelected.id === point.id;

      const group = document.createElementNS('http://www.w3.org/2000/svg', 'g');
      group.setAttribute('class', 'editor-node-group');
      group.dataset.nodeId = point.id;

      if (isExit) {
        const rect = document.createElementNS('http://www.w3.org/2000/svg', 'rect');
        rect.setAttribute('x', p.x - 11);
        rect.setAttribute('y', p.y - 9);
        rect.setAttribute('width', 22);
        rect.setAttribute('height', 18);
        rect.setAttribute('rx', 4);
        rect.setAttribute('class', `editor-exit ${selected ? 'selected' : ''}`);
        group.appendChild(rect);
      } else {
        const circle = document.createElementNS('http://www.w3.org/2000/svg', 'circle');
        circle.setAttribute('cx', p.x);
        circle.setAttribute('cy', p.y);
        circle.setAttribute('r', fallbackIds.has(point.id) ? 8.5 : 7);
        circle.setAttribute(
          'class',
          `editor-node ${fallbackIds.has(point.id) ? 'fallback' : ''} ${selected ? 'selected' : ''}`
        );
        group.appendChild(circle);
      }

      const label = document.createElementNS('http://www.w3.org/2000/svg', 'text');
      label.setAttribute('x', p.x);
      label.setAttribute('y', p.y - 12);
      label.setAttribute('text-anchor', 'middle');
      label.setAttribute('class', 'editor-node-label');
      label.textContent = point.id;
      group.appendChild(label);

      group.addEventListener('pointerdown', (event) => {
        if (!editorActive() || event.button !== 0) return;
        event.preventDefault();
        event.stopPropagation();
        if (editorMode === 'connect') { connectEditorPoint(point.id); return; }
        if (editorMode === 'add') return;
        byId('mapEditorSvg').setPointerCapture(event.pointerId);
        selectEditorItem('node', point.id);
        if (editorMode !== 'node') return;

        pushEditorUndo();
        editorDrag = {
          kind: 'node',
          id: point.id,
          start: editorSvgPoint(event),
          pointStart: { ...editorPositions[point.id] },
        };
        byId('mapEditorSvg').setPointerCapture?.(event.pointerId);
      });

      group.addEventListener('click', () => selectEditorItem('node', point.id));
      nodeLayer.appendChild(group);
    });
  }

  function onEditorPointerMove(event) {
    if (!editorDrag || !editorActive()) return;

    const current = editorSvgPoint(event);
    const dx = current.x - editorDrag.start.x;
    const dy = current.y - editorDrag.start.y;

    if (editorDrag.kind === 'node') {
      const point = clampEditorPoint({
        x: editorDrag.pointStart.x + dx,
        y: editorDrag.pointStart.y + dy,
      });
      if (router().validPoint(point)) editorPositions[editorDrag.id] = point;
    } else if (editorDrag.kind === 'edge') {
      const from = clampEditorPoint({
        x: editorDrag.fromStart.x + dx,
        y: editorDrag.fromStart.y + dy,
      });
      const to = clampEditorPoint({
        x: editorDrag.toStart.x + dx,
        y: editorDrag.toStart.y + dy,
      });
      if (router().validPoint(from) && router().validPoint(to)) {
        editorPositions[editorDrag.from] = from;
        editorPositions[editorDrag.to] = to;
      }
    }

    updateEditorDirtyState();
    renderMapEditor();
    updateEditorInspector();
  }

  function onEditorPointerUp(event) {
    editorDrag = null;
    const svg = byId('mapEditorSvg');
    if (event && svg.hasPointerCapture(event.pointerId)) svg.releasePointerCapture(event.pointerId);
  }

  function updateEditorInspector() {
    const empty = byId('editorInspectorEmpty');
    const body = byId('editorInspectorBody');
    const selectionLabel = byId('editorSelectionLabel');

    if (!editorSelected || !floorplan) {
      empty?.classList.remove('hidden');
      body?.classList.add('hidden');
      if (selectionLabel) selectionLabel.textContent = '선택 없음';
      return;
    }

    empty?.classList.add('hidden');
    body?.classList.remove('hidden');

    if (editorSelected.type === 'node') {
      const allPoints = [...editorDraft.nodes, ...editorDraft.exits];
      const item = allPoints.find((p) => p.id === editorSelected.id);
      const p = editorPositions[editorSelected.id];

      byId('editorItemType').textContent = floorplan.exits.some((e) => e.id === item.id) ? 'EXIT' : 'NODE';
      byId('editorItemId').textContent = item.id;
      byId('editorItemName').textContent = item.name || item.id;
      byId('editorXInput').value = Number(p.x).toFixed(1);
      byId('editorYInput').value = Number(p.y).toFixed(1);
      byId('editorNodeFields').classList.remove('hidden');
      byId('editorEdgeFields').classList.add('hidden');
      selectionLabel.textContent = `${item.id} · ${item.name || ''}`;
    } else {
      const edge = editorDraft.edges.find((e) => e.id === editorSelected.id);
      byId('editorItemType').textContent = 'EDGE';
      byId('editorItemId').textContent = edge.id;
      byId('editorItemName').textContent = `${edge.from} ↔ ${edge.to}`;
      byId('editorEdgeFrom').textContent = edge.from;
      byId('editorEdgeTo').textContent = edge.to;
      byId('editorNodeFields').classList.add('hidden');
      byId('editorEdgeFields').classList.remove('hidden');
      selectionLabel.textContent = `${edge.id} · ${edge.from} ↔ ${edge.to}`;
    }
  }

  function deleteEditorItem() {
    if (!editorActive() || !editorSelected) return;

    if (editorSelected.type === 'node') {
      if (floorplan.exits.some((e) => e.id === editorSelected.id)) {
        showToast('비상구(EXIT)는 삭제할 수 없습니다.', true);
        return;
      }
      const id = editorSelected.id;
      if (!window.confirm(`${id} 노드를 삭제하시겠습니까?\n연결된 간선도 함께 삭제됩니다.`)) return;
      pushEditorUndo();
      editorDraft.nodes = editorDraft.nodes.filter((n) => n.id !== id);
      editorDraft.edges = editorDraft.edges.filter((e) => e.from !== id && e.to !== id);
      delete editorPositions[id];
      editorSelected = null;
      editorConnectFrom = null;
      updateEditorDirtyState();
      renderMapEditor();
      updateEditorInspector();
      showToast(`${id} 노드 및 연결된 간선을 삭제했습니다.`);
    } else if (editorSelected.type === 'edge') {
      const id = editorSelected.id;
      if (!window.confirm(`${id} 간선을 삭제하시겠습니까?`)) return;
      pushEditorUndo();
      editorDraft.edges = editorDraft.edges.filter((e) => e.id !== id);
      editorSelected = null;
      updateEditorDirtyState();
      renderMapEditor();
      updateEditorInspector();
      showToast(`${id} 간선을 삭제했습니다.`);
    }
  }

  async function saveEditorLayout() {
    if (!editorActive() || !editorDirty()) return;
    editorSaving = true;
    byId('editorSaveBtn').disabled = true;
    try {
      const baseNodeIds = new Set(editorBase.nodes.map(n => n.id));
      const draftNodeIds = new Set(editorDraft.nodes.map(n => n.id));
      const deletedNodes = [...baseNodeIds].filter(id => !draftNodeIds.has(id));

      const baseEdgeIds = new Set(editorBase.edges.map(e => e.id));
      const draftEdgeIds = new Set(editorDraft.edges.map(e => e.id));
      const deletedEdges = [...baseEdgeIds].filter(id => !draftEdgeIds.has(id));

      const result = await api('/api/floorplan/layout', {
        positions: editorPositions,
        nodes: editorDraft.nodes.filter(n => !baseNodeIds.has(n.id)),
        edges: editorDraft.edges.filter(e => !baseEdgeIds.has(e.id)),
        deletedNodes,
        deletedEdges,
        baseFloorplan: editorBase,
      });
      floorplan = result.floorplan;
      initEditorPositions();

      // 기존 2D 대시보드 / 컨트롤 갱신
      buildControls();
      if (result.state) updateState(result.state);
      if (currentState) {
        renderMap(currentState);
        renderResponse(currentState);
        renderQr(currentState);
      }

      // 3D 대시보드도 즉시 동기화 리빌드
      if (map3dReady && typeof Map3D !== 'undefined') {
        Map3D.rebuild(floorplan, currentState);
      }
      showToast('지도 변경 사항을 저장하고 2D/3D 대시보드에 동기화했습니다.');
    } catch (error) {
      showToast(error.message || '맵 좌표 저장에 실패했습니다.', true);
    } finally {
      editorSaving = false;
      byId('editorSaveBtn').disabled = false;
    }
  }

  async function reloadEditorLayout() {
    if (editorSaving) return;
    if (editorDirty() && !window.confirm('저장하지 않은 수정 내용을 버리고 다시 불러올까요?')) return;
    try {
      floorplan = await api('/api/floorplan');
      initEditorPositions();
      buildControls();
      if (currentState) {
        renderMap(currentState);
        if (map3dReady && typeof Map3D !== 'undefined') {
          Map3D.rebuild(floorplan, currentState);
        }
      }
      showToast('저장된 좌표를 다시 불러왔습니다.');
    } catch (error) {
      showToast(error.message || '좌표를 다시 불러오지 못했습니다.', true);
    }
  }

  function undoEditorLayout() {
    if (!editorActive() || !editorUndoStack.length) return;
    const previous = editorUndoStack.pop();
    editorPositions = previous.positions;
    editorDraft = previous.draft;
    editorSelected = null;
    editorConnectFrom = null;
    byId('editorUndoBtn').disabled = editorUndoStack.length === 0;
    updateEditorDirtyState();
    renderMapEditor();
    updateEditorInspector();
  }

  function applyEditorCoordinates() {
    if (!editorActive() || !editorSelected || editorSelected.type !== 'node') return;
    const x = Number(byId('editorXInput').value);
    const y = Number(byId('editorYInput').value);
    if (!Number.isFinite(x) || !Number.isFinite(y)) return;
    const point = clampEditorPoint({x,y});
    if (!router().validPoint(point)) { showToast('벽과 떨어진 위치 또는 문 안쪽을 선택하세요.', true); return; }

    pushEditorUndo();
    editorPositions[editorSelected.id] = point;
    updateEditorDirtyState();
    renderMapEditor();
    updateEditorInspector();
  }

  function nextEditorId(prefix, items) {
    let n = 1;
    const ids = new Set(items.map(item => item.id));
    while (ids.has(prefix + (prefix === 'E' ? String(n).padStart(2, '0') : n))) n++;
    return prefix + (prefix === 'E' ? String(n).padStart(2, '0') : n);
  }

  function pointToSegmentDistance(px, py, x1, y1, x2, y2) {
    const dx = x2 - x1;
    const dy = y2 - y1;
    const l2 = dx * dx + dy * dy;
    if (l2 === 0) return Math.hypot(px - x1, py - y1);
    let t = ((px - x1) * dx + (py - y1) * dy) / l2;
    t = Math.max(0, Math.min(1, t));
    const projX = x1 + t * dx;
    const projY = y1 + t * dy;
    return Math.hypot(px - projX, py - projY);
  }

  function addEditorNode(event) {
    if (!editorActive() || editorMode !== 'add' || event.button !== 0) return;
    if (event.target.closest('.editor-node-group')) return;

    const rawPoint = editorSvgPoint(event);
    if (rawPoint.x < 8 || rawPoint.x > 576 || rawPoint.y < 8 || rawPoint.y > 850) return;
    const point = clampEditorPoint(rawPoint);
    if (!router().validPoint(point)) { showToast('벽 위에는 노드를 추가할 수 없습니다.', true); return; }

    pushEditorUndo();
    const id = nextEditorId('N', [...editorDraft.nodes, ...editorDraft.exits]);
    editorPositions[id] = point;
    editorDraft.nodes.push({ id, name: `추가 노드 ${id}`, ...point });

    // 1. 기존 간선 위 또는 부근에 생성된 경우: 해당 간선을 자동 분할하여 양 끝 노드와 연결
    const SPLIT_THRESHOLD = 36;
    let splitEdge = null;
    let minEdgeDist = Infinity;

    for (const edge of editorDraft.edges) {
      const pFrom = editorPositions[edge.from];
      const pTo   = editorPositions[edge.to];
      if (!pFrom || !pTo) continue;

      let waypoints = [pFrom, pTo];
      try {
        const routed = router().route(pFrom, pTo);
        if (routed && routed.length >= 2) waypoints = routed;
      } catch (_) {}

      for (let i = 0; i < waypoints.length - 1; i++) {
        const d = pointToSegmentDistance(point.x, point.y, waypoints[i].x, waypoints[i].y, waypoints[i+1].x, waypoints[i+1].y);
        if (d < minEdgeDist) {
          minEdgeDist = d;
          if (d <= SPLIT_THRESHOLD) {
            splitEdge = edge;
          }
        }
      }
    }

    const connected = [];

    if (splitEdge) {
      const fromNode = splitEdge.from;
      const toNode   = splitEdge.to;
      const origWeight = Number(splitEdge.weight) || 1.0;

      // 기존 간선 삭제
      editorDraft.edges = editorDraft.edges.filter(e => e.id !== splitEdge.id);

      // 분할된 두 간선 자동 생성 (from <-> new, new <-> to)
      const e1Id = nextEditorId('E', editorDraft.edges);
      const e1 = { id: e1Id, from: fromNode, to: id, weight: Math.max(0.5, Math.round((origWeight / 2) * 10) / 10) };
      editorDraft.edges.push(e1);

      const e2Id = nextEditorId('E', editorDraft.edges);
      const e2 = { id: e2Id, from: id, to: toNode, weight: Math.max(0.5, Math.round((origWeight / 2) * 10) / 10) };
      editorDraft.edges.push(e2);

      connected.push(fromNode, toNode);
    } else {
      // 2. 간선 위가 아닌 경우: 통행 가능한 가장 가까운 인접 노드 1~2개와 자동 연결
      const allOtherNodes = [...editorDraft.nodes.filter(n => n.id !== id), ...editorDraft.exits];
      const candidates = [];
      for (const target of allOtherNodes) {
        const targetPos = editorPositions[target.id];
        if (!targetPos) continue;
        const dist = Math.hypot(point.x - targetPos.x, point.y - targetPos.y);
        if (dist <= 180) {
          try {
            const routed = router().route(point, targetPos);
            if (routed && routed.length >= 2) {
              candidates.push({ id: target.id, dist });
            }
          } catch (_) {}
        }
      }
      candidates.sort((a, b) => a.dist - b.dist);
      const toConnect = candidates.slice(0, 2);
      for (const target of toConnect) {
        const edgeId = nextEditorId('E', editorDraft.edges);
        const weight = Math.max(0.5, Math.round((target.dist / 80) * 10) / 10);
        editorDraft.edges.push({ id: edgeId, from: target.id, to: id, weight });
        connected.push(target.id);
      }
    }

    selectEditorItem('node', id);
    updateEditorDirtyState();
    renderMapEditor();
    updateEditorInspector();

    if (connected.length > 0) {
      showToast(`${id} 생성 완료 · ${connected.join(', ')} 지점과 간선이 자동 연결되었습니다.`);
    } else {
      showToast(`${id} 추가 완료. 간선 연결 모드로 원하는 지점과 연결하세요.`);
    }
  }

  function connectEditorPoint(id) {
    if (!editorConnectFrom) {
      editorConnectFrom = id;
      selectEditorItem('node', id);
      byId('editorModeHint').textContent = `${id} 선택됨 · 연결할 두 번째 지점을 클릭하세요.`;
      return;
    }
    const from = editorConnectFrom;
    if (from === id) { showToast('다른 지점을 선택하세요.', true); return; }
    if (!router().route(editorPositions[from], editorPositions[id])) { showToast('문을 통과하는 연결을 찾을 수 없습니다.', true); return; }
    if (editorDraft.edges.some(e => (e.from === from && e.to === id) || (e.from === id && e.to === from))) {
      showToast('이미 연결된 지점입니다.', true); return;
    }
    const weight = Number(byId('editorNewEdgeWeight').value);
    if (!Number.isFinite(weight) || weight <= 0) { showToast('간선 비용을 0보다 크게 입력하세요.', true); return; }
    pushEditorUndo();
    const edgeId = nextEditorId('E', editorDraft.edges);
    editorDraft.edges.push({id: edgeId, from, to: id, weight});
    editorConnectFrom = null;
    selectEditorItem('edge', edgeId);
    updateEditorDirtyState();
    byId('editorModeHint').textContent = '연결 완료 · 다음 연결의 첫 번째 지점을 클릭하세요.';
  }

  // ------------------------------------------------------------------ //
  // 2D / 3D Map View Toggle                                             //
  // ------------------------------------------------------------------ //
  function setMapView(mode) {
    mapViewMode = mode;
    const stage2d = byId('mapStage');
    const stage3d = byId('mapStage3d');
    const legend  = byId('map2dLegend');
    const btn2d   = byId('mapView2dBtn');
    const btn3d   = byId('mapView3dBtn');

    if (mode === '3d') {
      stage2d.style.display = 'none';
      stage3d.style.display = 'block';
      if (legend) legend.style.display = 'none';
      btn2d.classList.remove('active');
      btn3d.classList.add('active');
      // Init 3D engine once (lazy)
      if (!map3dReady && typeof Map3D !== 'undefined' && floorplan) {
        Map3D.init(floorplan, stage3d);
        map3dReady = true;
      }
      if (map3dReady && currentState) Map3D.update(currentState);
    } else {
      stage2d.style.display = '';
      stage3d.style.display = 'none';
      if (legend) legend.style.display = '';
      btn2d.classList.add('active');
      btn3d.classList.remove('active');
    }
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

    const fallbackById = {};
    (floorplan.fallbackDestinations || []).forEach((item) => { fallbackById[item.id] = item; });

    floorplan.edges.forEach((edge) => {
      const a = points[edge.from]; const b = points[edge.to];
      if (!a || !b) return;
      const blocked = state.blockedEdges.includes(edge.id);
      const congested = Boolean(state.edgeWeightOverrides && state.edgeWeightOverrides[edge.id]);
      const classes = ['map-edge'];
      if (blocked) classes.push('blocked');
      else if (congested) classes.push('congested');
      const line = buildEdgePath(a, b, classes.join(' '));
      line.dataset.edgeId = edge.id;
      if (congested) {
        const title = document.createElementNS('http://www.w3.org/2000/svg', 'title');
        title.textContent = `${edge.id} 혼잡 가중치 ${state.edgeWeightOverrides[edge.id]}`;
        line.appendChild(title);
      }
      edgeLayer.appendChild(line);
    });

    if (state.route && state.route.nodes?.length > 1) {
      for (let i = 0; i < state.route.nodes.length - 1; i += 1) {
        const edge = edgesById[state.route.edges[i]];
        if (!edge) continue;
        const from = points[edge.from];
        const to = points[edge.to];
        if (!from || !to) continue;
        const path = buildEdgePath(from, to, 'route-edge');
        path.dataset.edgeId = edge.id;
        routeLayer.appendChild(path);
      }
    }

    floorplan.shutters.forEach((shutter) => {
      const edge = edgesById[shutter.edge];
      if (!edge) return;
      const a = points[edge.from]; const b = points[edge.to];
      const middle = MapGeometry.midpoint(router().route(a, b));
      if (!middle) return;
      const {x, y} = middle;
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
      const fallback = fallbackById[node.id];
      if (blocked) classes.push('blocked');
      if (state.startNode === node.id) classes.push('start');
      if (selectedNodeId === node.id) classes.push('selected');
      if (fallback) {
        classes.push('fallback-node', fallback.type === 'descender' ? 'descender' : 'toilet');
        if (state.route?.destinationId === node.id) classes.push('active-destination');
      }
      const circle = document.createElementNS('http://www.w3.org/2000/svg', 'circle');
      circle.setAttribute('cx', node.x); circle.setAttribute('cy', node.y); circle.setAttribute('r', fallback ? 8.5 : 6.4);
      circle.setAttribute('class', classes.join(' '));
      const label = document.createElementNS('http://www.w3.org/2000/svg', 'text');
      label.setAttribute('x', node.x); label.setAttribute('y', node.y - 11); label.setAttribute('text-anchor', 'middle');
      label.setAttribute('class', fallback ? 'fallback-node-label' : 'node-label');
      label.textContent = fallback ? `${node.id} · ${fallback.label}` : node.id;
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
    updateRouteVisualScale();

    // Sync 3D scene whenever state changes (if 3D is ready)
    if (map3dReady && typeof Map3D !== 'undefined') Map3D.update(state);
  }

  function renderHeader(state) {
    setChip('piChip', state.connections.pi);
    setChip('cloudChip', state.connections.server);
    setChip('flaskChip', browserConnected);

    const fireSwitch = byId('realFireSwitchBtn');
    const pendingRealFire = state.operationMode === 'simulation' && state.realFireDetected;
    fireSwitch.disabled = !pendingRealFire;
    fireSwitch.classList.toggle('fire-detected', Boolean(pendingRealFire));
    fireSwitch.textContent = pendingRealFire ? '실제 화재 발생 · REAL 전환' : state.realFireDetected ? '실제 화재 관제 중' : '실제 화재 감지 없음';
    fireSwitch.title = (state.realFireSensorIds || []).join(', ');
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
    const offlineSensors = state.sensorCounts?.offline || 0;
    if (!state.connections.pi && ['normal', 'warning'].includes(state.overallStatus)) {
      className = 'device-offline';
      title = 'EDGE CONTROLLER OFFLINE';
      icon = '×';
      description = 'Raspberry Pi 현장 제어기가 연결되지 않았습니다. 로컬 센서 수집과 물리 LED 출력 상태를 확인하세요.';
    } else if (state.fallbackActive) {
      className = 'fallback';
      title = 'EMERGENCY ROUTE';
      icon = '↪';
      description = `정규 비상구 경로가 모두 차단되어 ${state.selectedDestinationName || '보조 대피지점'}으로 안내합니다.`;
    } else if (state.failSafeActive && state.overallStatus === 'normal') {
      title = 'LOCAL FAIL-SAFE'; icon = '!'; description = '외부 서버 연결이 끊어졌습니다. Raspberry Pi 로컬 경로 계산과 LED 유도는 계속 유지됩니다.';
    } else if (offlineSensors > 0 && state.overallStatus === 'normal') {
      className = 'sensor-fault';
      title = 'SENSOR DEGRADED';
      icon = '!';
      description = `센서 ${offlineSensors}개가 통신 단절 상태입니다. 연결된 센서만으로 경로 판단을 계속합니다.`;
    } else if (state.congestionActive && state.overallStatus === 'normal') {
      className = 'congestion';
      title = 'CONGESTION REROUTE';
      icon = '↗';
      description = '인파 혼잡 구간의 Edge 가중치를 높여 덜 혼잡한 대피 경로로 우회했습니다.';
    }
    byId('systemIcon').textContent = icon;
    byId('systemTitle').textContent = title;
    byId('systemDescription').textContent = description;
    byId('updatedAt').textContent = fmtTime(state.updatedAt);
  }

  function renderResponse(state) {
    byId('selectedExitName').textContent = state.selectedDestinationName || state.selectedExitName || '경로 없음';
    byId('routeStatusText').textContent = state.route ? (state.fallbackActive ? '보조 대피 경로' : '경로 확보') : '대피 불가';
    byId('routeCostText').textContent = state.route ? `${state.fallbackActive ? 'FALLBACK · ' : ''}비용 ${state.route.cost.toFixed(1)}` : '경로를 확인하세요';
    const names = nodeMap();
    byId('routeNodeText').textContent = state.route ? state.route.nodes.map((id) => names[id]?.name || id).join(' → ') : '안전한 경로 없음';
    byId('failSafeNotice').classList.toggle('hidden', !state.failSafeActive);
    byId('fallbackNotice').classList.toggle('hidden', !state.fallbackActive);
    if (state.fallbackActive) {
      const typeLabel = state.selectedDestinationType === 'descender' ? '완강기' : '화장실';
      byId('fallbackNoticeText').textContent = `정규 비상구가 모두 차단되어 ${typeLabel} 보조 대피지점인 ${state.selectedDestinationName}으로 경로를 전환했습니다.`;
    }
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
    const sensorOffline = counts.offline || 0;
    byId('sensorSummary').innerHTML = `
      <div class="sensor-row"><span>불꽃 센서 정상</span><strong class="${counts.flameActive ? 'state-danger' : 'state-normal'}">${normalFlame}/${counts.flameTotal}</strong></div>
      <div class="sensor-row"><span>MQ-2 정상</span><strong class="${counts.mq2Danger ? 'state-danger' : counts.mq2Warning ? 'state-warning' : 'state-normal'}">${normalMq}/${counts.mq2Total}</strong></div>
      <div class="sensor-row"><span>MQ-2 주의 / 위험</span><strong class="${counts.mq2Danger ? 'state-danger' : counts.mq2Warning ? 'state-warning' : 'state-normal'}">${counts.mq2Warning} / ${counts.mq2Danger}</strong></div>
      <div class="sensor-row"><span>센서 통신 장애</span><strong class="${sensorOffline ? 'state-warning' : 'state-normal'}">${sensorOffline}</strong></div>
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
    byId('mobileExitPreview').textContent = state.selectedDestinationName || state.selectedExitName || '경로 없음';
    byId('mobileRoutePreview').textContent = state.route ? state.route.nodes.map((id) => names[id]?.name || id).join(' → ') : '안전한 경로를 찾을 수 없습니다.';
  }

  function updateState(state) {
    currentState = state;
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
    renderFloorplanBase();
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
  window.__onSelectNode3D = selectNode;

  function refreshNodeActionCard() {
    if (!floorplan || !selectedNodeId) return;
    const card = byId('nodeActionCard');
    const node = floorplan.nodes.find((n) => n.id === selectedNodeId);
    if (!node || !currentState || currentState.operationMode !== 'simulation') {
      card.classList.add('hidden'); return;
    }
    const sensors = floorplan.sensors.filter((s) => s.node === selectedNodeId);
    byId('selectedFireBtn').disabled = sensors.length === 0;
    byId('selectedClearBtn').disabled = sensors.length === 0;
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
    editorDrag = null;
    editorConnectFrom = null;
    document.querySelectorAll('.nav-item').forEach((b) => b.classList.toggle('active', b.dataset.page === pageId));
    document.querySelectorAll('.page').forEach((p) => p.classList.toggle('active', p.id === pageId));
    const titles = { overview: '실시간 화재 대피 통합 관제', equipment: '장비 관리', routing: '경로 및 수동 설정', events: '이벤트 기록', qr: 'QR 기반 모바일 대피 안내', mapEditor: '수정 모드 · 지도 편집' };
    if (pageId === 'mapEditor') setEditorMode('node');
    if (pageId === 'overview' && mapViewMode === '3d') setMapView('3d');
    byId('pageTitle').textContent = titles[pageId] || 'FireGuard';
    window.scrollTo({ top: 0, behavior: 'smooth' });
  }

  function bindActions() {
    document.querySelectorAll('.nav-item').forEach((button) => button.addEventListener('click', () => showPage(button.dataset.page)));
    document.querySelectorAll('.nav-shortcut').forEach((button) => button.addEventListener('click', () => showPage(button.dataset.targetPage)));
    document.querySelectorAll('[data-scenario]').forEach((button) => button.addEventListener('click', async () => {
      const explanation = byId('scenarioExplanation');
      if (explanation) {
        explanation.querySelector('span').textContent = `SCENARIO · ${button.dataset.scenario.toUpperCase()}`;
        explanation.querySelector('strong').textContent = button.dataset.note || '시나리오 실행 중';
      }
      await runScenario(button.dataset.scenario);
    }));

    byId('realFireSwitchBtn').addEventListener('click', () => {
      if (currentState?.operationMode !== 'simulation' || !currentState?.realFireDetected) return;
      if (window.confirm('실제 센서에서 화재가 감지되었습니다. REAL 모드로 전환하시겠습니까?')) setMode('real');
    });
    byId('realModeBtn').addEventListener('click', () => setMode('real'));
    byId('simModeBtn').addEventListener('click', () => setMode('simulation'));
    byId('autoDemoBtn').addEventListener('click', runAutoDemo);
    byId('stopDemoBtn').addEventListener('click', stopAutoDemo);
    byId('serverRestoreBtn').addEventListener('click', () => runScenario('server_on'));

    const btn2d = byId('mapView2dBtn');
    const btn3d = byId('mapView3dBtn');
    if (btn2d) btn2d.addEventListener('click', () => setMapView('2d'));
    if (btn3d) btn3d.addEventListener('click', () => setMapView('3d'));

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

    byId('editorNodeModeBtn').addEventListener('click', () => setEditorMode('node'));
    byId('editorEdgeModeBtn').addEventListener('click', () => setEditorMode('edge'));
    byId('editorAddNodeBtn').addEventListener('click', () => setEditorMode('add'));
    byId('editorConnectBtn').addEventListener('click', () => setEditorMode('connect'));
    byId('editorSaveBtn').addEventListener('click', saveEditorLayout);
    byId('editorReloadBtn').addEventListener('click', reloadEditorLayout);
    byId('editorUndoBtn').addEventListener('click', undoEditorLayout);
    byId('editorApplyCoordBtn').addEventListener('click', applyEditorCoordinates);
    byId('editorDeleteItemBtn')?.addEventListener('click', deleteEditorItem);
    byId('editorSnapToggle').addEventListener('change', renderMapEditor);

    const editorSvg = byId('mapEditorSvg');
    editorSvg.addEventListener('pointerdown', addEditorNode);
    editorSvg.addEventListener('pointermove', onEditorPointerMove);
    editorSvg.addEventListener('pointerup', onEditorPointerUp);
    editorSvg.addEventListener('pointercancel', onEditorPointerUp);
    editorSvg.addEventListener('lostpointercapture', () => { editorDrag = null; });
    window.addEventListener('beforeunload', event => {
      if (editorDirty()) { event.preventDefault(); event.returnValue = ''; }
    });
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
    socket.on('floorplan:update', (updatedFloorplan) => {
      floorplan = updatedFloorplan;
      if (!editorDrag && !editorDirty() && !editorSaving) initEditorPositions();
      buildControls();
      if (currentState) {
        renderMap(currentState);
        if (map3dReady && typeof Map3D !== 'undefined') {
          Map3D.rebuild(floorplan, currentState);
        }
      }
    });
    socket.on('connect_error', () => { setBrowserConnection(false); startPollingFallback(); });
  }

  async function init() {
    updateClock(); window.setInterval(updateClock, 1000);
    window.addEventListener('resize', updateRouteVisualScale);
    try {
      [floorplan, currentState] = await Promise.all([api('/api/floorplan'), api('/api/state')]);
      initEditorPositions();
      buildControls(); bindActions(); updateState(currentState); updateRouteVisualScale(); connectSocket();
    } catch (error) {
      showToast(`초기화 실패: ${error.message}`, true); setBrowserConnection(false); startPollingFallback();
    }
  }

  init();
})();
