(() => {
  let selected = null;
  let previousMode;
  let activeView;
  // Interior room origins and their order on the operator's floor plan.
  const origins = ['N37','N39','N19','N36','N40','N5','N6','N13','N12','N38','N3'];
  const id = name => document.getElementById(name);
  function realRoute(origin, forest) {
    if (!forest || forest.unreachableNodes.includes(origin)) return null;
    const next = new Map();
    // The Pi lists primary routes before supplementary corridor coverage.
    for (const edge of forest.directedEdges) if (!next.has(edge.from)) next.set(edge.from, edge);
    const targets = new Set([...forest.availableExits, ...(forest.fallbackDestinations || [])]);
    const nodes = [origin], edges = [];
    let cursor = origin;
    while (!targets.has(cursor)) {
      const edge = next.get(cursor);
      if (!edge || nodes.includes(edge.to)) return null;
      nodes.push(edge.to); edges.push(edge.edgeId); cursor = edge.to;
    }
    return {nodes, edges, destinationId:cursor, routeMode:forest.availableExits.includes(cursor) ? 'exit' : 'fallback'};
  }
  // Retain a short highlight across DOM rebuilds while flow animation continues.
  const emphasisMs = 5200;
  const previousRoutes = new Map();
  const latestChanges = new Map();
  const deadlines = new Map();
  let expiryTimer = null;

  const edgeKey = (id, from, to) => [id, from, to].join('/');
  function routeKeys(route) {
    return new Set((route?.edges || []).map((id, i) => edgeKey(id, route.nodes[i], route.nodes[i + 1])));
  }
  function trackRoute(origin, known, route, destination, label) {
    if (!known) {
      previousRoutes.delete(origin);
      latestChanges.delete(origin);
      deadlines.delete(origin);
      return;
    }
    const edges = route instanceof Set ? route : routeKeys(route);
    const previous = previousRoutes.get(origin);
    if (previous) {
      const until = performance.now() + emphasisMs;
      const expiry = deadlines.get(origin) || new Map();
      for (const edge of edges) if (!previous.edges.has(edge)) expiry.set(edge, until);
      for (const edge of expiry.keys()) if (!edges.has(edge)) expiry.delete(edge);
      if (expiry.size) deadlines.set(origin, expiry);
      if (origin !== 'overview' && previous.destination !== destination) {
        latestChanges.set(origin, previous.label + ' → ' + label);
      }
    }
    previousRoutes.set(origin, {edges, destination, label});
  }
  function applyEmphasis() {
    clearTimeout(expiryTimer);
    const now = performance.now();
    let nextExpiry = Infinity;
    for (const [origin, expiry] of deadlines) {
      for (const [edge, time] of expiry) {
        if (time <= now) expiry.delete(edge);
        else nextExpiry = Math.min(nextExpiry, time);
      }
      if (!expiry.size) deadlines.delete(origin);
    }
    for (const layer of [id('routeLayer'), id('zoneFocusLayer')]) {
      const changed = deadlines.get(layer.id === 'routeLayer' ? 'overview' : selected);
      for (const path of layer.querySelectorAll('polyline[data-edge-id]')) {
        const d = path.dataset;
        path.classList.toggle('route-reassigned', !!changed?.has(edgeKey(d.edgeId, d.fromNode, d.toNode)));
      }
    }
    if (nextExpiry < Infinity) expiryTimer = setTimeout(applyEmphasis, Math.ceil(nextExpiry - now));
  }
  function renderExitCounts(exits, totals, exceptions, reportAvailable) {
    const container = id('exitGuidanceCounts');
    if (!container) return;
    const fragment = document.createDocumentFragment();
    if (reportAvailable) {
      for (const exit of exits) {
        const row = document.createElement('div');
        row.className = 'exit-guidance-row';
        const name = document.createElement('span'), value = document.createElement('strong');
        name.textContent = exit.name || exit.id;
        value.textContent = (totals.get(exit.id) || 0) + '개 구역';
        row.append(name, value);
        fragment.append(row);
      }
    }
    const labels = {fallback: '보조 대피지점', blocked: '화재 차단', missing: '경로 없음', unknown: '미확인'};
    const note = document.createElement('p');
    note.className = 'exit-guidance-note';
    note.textContent = reportAvailable
      ? Object.entries(exceptions).filter(([, count]) => count > 0)
          .map(([kind, count]) => labels[kind] + ' ' + count + '개 구역').join(' · ')
      : '출구별 안내 구역 수 미확인';
    if (note.textContent) fragment.append(note);
    container.replaceChildren(fragment);
  }

  function paint() {
    const {state, plan, allZone, realCloud} = activeView;
    const sim = state.operationMode === 'simulation';
    const forest = realCloud && allZone && !allZone.stale && !allZone.unverified ? state.cloud.hardware.allZone : null;
    const names = new Map([...plan.nodes, ...plan.exits].map(p => [p.id,p.name]));
    if (names.get('N19') === '추가 노드 N19') names.set('N19', '팝콘 매장 내부');
    const list = id('zoneGuidanceList'), layer = id('zoneFocusLayer');
    const detail = id('zoneGuidanceDetail');
    const ready = sim ? !!state.simulationZoneRoutes : !!forest;
    const overview = sim ? state.route : new Set((allZone?.directedEdges || []).map(e => edgeKey(e.edgeId, e.from, e.to)));
    const source = sim ? state.startNode : 'pi';
    // A different starting position is a new query, not a reroute.
    if (previousRoutes.get('overview')?.destination !== source) {
      previousRoutes.delete('overview');
      deadlines.delete('overview');
    }
    trackRoute('overview', ready, overview, source, '');
    layer.replaceChildren();
    let focusRoute;
    const validOrigins = origins.filter(key => names.has(key));
    const totals = new Map(plan.exits.map(exit => [exit.id, 0]));
    const exceptions = {fallback: 0, blocked: 0, missing: 0, unknown: 0};
    if (!validOrigins.includes(selected)) selected = null;
    for (const key of validOrigins) {
      let button = list.querySelector('[data-zone="'+key+'"]');
      if (!button) {
        button = document.createElement('button');
        button.type = 'button'; button.dataset.zone = key; button.className = 'zone-row';
        button.append(document.createElement('strong'),document.createElement('span'));
        button.onclick = () => {
          selected = selected === key ? null : key;
          if (selected) activeView.onFocus();
          paint();
        };
        list.append(button);
      }
      const route = sim ? state.simulationZoneRoutes?.[key] : realRoute(key,forest);
      const known = sim ? Object.hasOwn(state.simulationZoneRoutes || {},key) :
        forest && (forest.guidedNodes.includes(key) || forest.unreachableNodes.includes(key) ||
          forest.fallbackDestinations?.includes(key) || state.blockedNodes.includes(key));
      const blocked = known && state.blockedNodes.includes(key);
      if (!known) exceptions.unknown++;
      else if (blocked) exceptions.blocked++;
      else if (!route) exceptions.missing++;
      else if (route.routeMode === 'fallback') exceptions.fallback++;
      else if (totals.has(route.destinationId)) totals.set(route.destinationId, totals.get(route.destinationId) + 1);
      else exceptions.unknown++;
      const target = known && !blocked && route ? names.get(route.destinationId) || route.destinationId : '';
      const status = !known ? '미확인' : blocked ? '화재 차단' : !route ? '경로 없음' :
        route.routeMode === 'fallback' ? '보조 · ' + target : target;
      button.dataset.status = !known ? 'unknown' : blocked || !route ? 'blocked' : route.routeMode;
      button.firstChild.textContent = names.get(key);
      button.children[1].textContent = status;
      trackRoute(key, known, blocked ? null : route, blocked ? 'blocked' : route?.destinationId || 'no_route', status);
      const changed = latestChanges.get(key);
      let note = button.querySelector('.zone-destination-change');
      if (changed) {
        if (!note) {
          note = document.createElement('small');
          note.className = 'zone-destination-change';
          button.append(note);
        }
        note.textContent = '최근 변경 · ' + changed;
      } else if (note) note.remove();
      button.setAttribute('aria-pressed',String(selected === key));
      if (selected === key) {
        focusRoute = known && !blocked ? route : null;
        detail.textContent = names.get(key) + ' · ' + (focusRoute ? focusRoute.nodes.join(' → ') : status);
      }
    }
    renderExitCounts(plan.exits, totals, exceptions, validOrigins.length > exceptions.unknown);
    for (const button of [...list.children]) if (!validOrigins.includes(button.dataset.zone)) button.remove();
    if (!selected) detail.textContent = sim ? '시뮬레이션 계산 · 구역을 선택하면 지도에 경로가 표시됩니다.' :
      forest ? 'Pi 계산 경로 · 구역을 선택해 확인하세요.' : '확인 가능한 Pi 전체 구역 보고를 기다립니다.';
    id('routeLayer').classList.toggle('zone-focus-muted',Boolean(focusRoute));
    if (!focusRoute) { applyEmphasis(); return; }
    for (const [i,edgeId] of focusRoute.edges.entries()) {
      const edge = plan.edges.find(e => e.id === edgeId);
      const source = document.querySelector('#edgeLayer [data-edge-id="'+CSS.escape(edgeId)+'"]');
      if (!source || !edge) continue;
      const vertices = source.getAttribute('points').trim().split(/\s+/);
      if (edge.from !== focusRoute.nodes[i]) vertices.reverse();
      const path = document.createElementNS('http://www.w3.org/2000/svg','polyline');
      path.setAttribute('class','zone-focus-edge');
      path.setAttribute('points',vertices.join(' '));
      path.dataset.edgeId = edgeId;
      path.dataset.fromNode = focusRoute.nodes[i];
      path.dataset.toNode = focusRoute.nodes[i+1];
      if (forest) {
        path.setAttribute('class','route-edge');
        const base = document.querySelector('#routeLayer [data-edge-id="'+CSS.escape(edgeId)+'"]');
        if (base) {
          path.style.animationDelay = base.style.animationDelay;
          path.setAttribute('points',base.getAttribute('points'));
        }
      } else path.setAttribute('marker-end','url(#zoneArrow)');
      layer.append(path);
    }
    applyEmphasis();
  }
  window.FireGuardZoneGuidance = {realRoute, render(view) {
    if (previousMode !== view.state.operationMode) {
      selected = null;
      deadlines.clear();
      previousRoutes.clear();
      latestChanges.clear();
    }
    previousMode = view.state.operationMode;
    activeView = view;
    paint();
  }};
})();
