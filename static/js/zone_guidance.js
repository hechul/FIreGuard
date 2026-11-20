(() => {
  let selected = null;
  let previousMode;
  let activeView;
  // Interior room origins and their order on the operator's floor plan.
  const origins = ['N37','N39','N19','N36','N40','N5','N6','N13','N12','N38','N3'];
  const id = name => document.getElementById(name);
  function realRoute(origin, forest) {
    if (!forest || forest.unreachableNodes.includes(origin)) return null;
    const next = new Map(forest.directedEdges.map(edge => [edge.from, edge]));
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
  function paint() {
    const {state, plan, allZone, realCloud} = activeView;
    const sim = state.operationMode === 'simulation';
    const forest = realCloud && allZone && !allZone.stale && !allZone.unverified ? state.cloud.hardware.allZone : null;
    const names = new Map([...plan.nodes, ...plan.exits].map(p => [p.id,p.name]));
    if (names.get('N19') === '추가 노드 N19') names.set('N19', '팝콘 매장 내부');
    const list = id('zoneGuidanceList'), layer = id('zoneFocusLayer');
    const detail = id('zoneGuidanceDetail');
    layer.replaceChildren();
    let focusRoute;
    const validOrigins = origins.filter(key => names.has(key));
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
      const target = known && !blocked && route ? names.get(route.destinationId) || route.destinationId : '';
      const status = !known ? '미확인' : blocked ? '화재 차단' : !route ? '경로 없음' :
        route.routeMode === 'fallback' ? '보조 · ' + target : target;
      button.dataset.status = !known ? 'unknown' : blocked || !route ? 'blocked' : route.routeMode;
      button.firstChild.textContent = names.get(key);
      button.lastChild.textContent = status;
      button.setAttribute('aria-pressed',String(selected === key));
      if (selected === key) {
        focusRoute = known && !blocked ? route : null;
        detail.textContent = names.get(key) + ' · ' + (focusRoute ? focusRoute.nodes.join(' → ') : status);
      }
    }
    for (const button of [...list.children]) if (!validOrigins.includes(button.dataset.zone)) button.remove();
    if (!selected) detail.textContent = sim ? '시뮬레이션 계산 · 구역을 선택하면 지도에 경로가 표시됩니다.' :
      forest ? 'Pi 계산 경로 · 구역을 선택해 확인하세요.' : '확인 가능한 Pi 전체 구역 보고를 기다립니다.';
    id('routeLayer').classList.toggle('zone-focus-muted',Boolean(focusRoute));
    if (!focusRoute) return;
    for (const [i,edgeId] of focusRoute.edges.entries()) {
      const edge = plan.edges.find(e => e.id === edgeId);
      const source = document.querySelector('#edgeLayer [data-edge-id="'+CSS.escape(edgeId)+'"]');
      if (!source || !edge) continue;
      const vertices = source.getAttribute('points').trim().split(/\s+/);
      if (edge.from !== focusRoute.nodes[i]) vertices.reverse();
      const path = document.createElementNS('http://www.w3.org/2000/svg','polyline');
      path.setAttribute('class','zone-focus-edge');
      path.setAttribute('points',vertices.join(' '));
      path.setAttribute('marker-end','url(#zoneArrow)');
      layer.append(path);
    }
  }
  window.FireGuardZoneGuidance = {render(view) {
    if (previousMode !== view.state.operationMode) selected = null;
    previousMode = view.state.operationMode;
    activeView = view;
    paint();
  }};
})();
