(() => {
  const origin = document.querySelector('main[data-node]').dataset.node;
  const id = name => document.getElementById(name);
  let lastReport = null;
  let lastMapKey = '';

  function stamp(value) {
    if (!value || Number.isNaN(Date.parse(value))) return '';
    return new Date(value).toLocaleString('ko-KR', {hour12:false});
  }

  function message(title, detail, tone) {
    id('statusTitle').textContent = title;
    id('statusDetail').textContent = detail;
    id('status').dataset.tone = tone;
  }

  function hideGuidance() {
    id('guidance').hidden = true;
    lastMapKey = '';
    id('mobileMap').replaceChildren();
    id('exit').textContent = id('next').textContent = id('route').textContent = '';
  }

  function routeFromReport(state) {
    if (!state.cloud?.enabled && state.operationMode === 'simulation') {
      if (Object.hasOwn(state.simulationZoneRoutes || {}, origin)) {
        return {known:true, route:state.simulationZoneRoutes[origin]};
      }
    }
    const summary = FireGuardRealLedProjection.allZoneSummary(state.cloud);
    if (!summary || summary.stale || summary.unverified) return {known:false};
    const forest = state.cloud.hardware.allZone;
    if (state.blockedNodes.includes(origin)) return {known:true, blocked:true};
    if (forest.unreachableNodes.includes(origin)) return {known:true, route:null};
    if (!forest.guidedNodes.includes(origin) && !forest.fallbackDestinations?.includes(origin)) return {known:false};
    const route = FireGuardZoneGuidance.realRoute(origin, forest);
    return {known:Boolean(route), route};
  }

  function draw(plan, points, route, blocked) {
    const map = id('mobileMap');
    const drawKey = JSON.stringify([plan, route.nodes, route.edges, blocked]);
    if (drawKey === lastMapKey) return;
    lastMapKey = drawKey;
    map.replaceChildren();
    const append = (tag, attrs, label) => {
      const element = document.createElementNS('http://www.w3.org/2000/svg', tag);
      for (const [key,value] of Object.entries(attrs)) element.setAttribute(key,value);
      if (label) element.textContent = label;
      map.appendChild(element);
    };
    const corners = [...points.values()];
    for (const room of plan.rooms || []) {
      append('rect', {class:'map-room',x:room.x,y:room.y,width:room.width,height:room.height,rx:3});
      corners.push(room,{x:room.x+room.width,y:room.y+room.height});
    }
    const pad = 28;
    const left = Math.min(...corners.map(p=>p.x))-pad, top = Math.min(...corners.map(p=>p.y))-pad;
    map.setAttribute('viewBox',[left,top,Math.max(...corners.map(p=>p.x))+pad-left,Math.max(...corners.map(p=>p.y))+pad-top].join(' '));
    const router = MapGeometry.createRouter(plan);
    const chosen = new Set(route.edges);
    for (const edge of [...plan.edges].sort((a,b)=>Number(chosen.has(a.id))-Number(chosen.has(b.id)))) {
      const a = points.get(edge.from), b = points.get(edge.to);
      if (!a || !b) continue;
      const geometry = router.route(a,b);
      if (geometry?.length) append('polyline',{class:chosen.has(edge.id)?'map-path':'map-edge',points:geometry.map(p=>p.x+','+p.y).join(' ')});
    }
    for (const node of blocked) {
      const point = points.get(node);
      if (point) append('circle',{class:'map-fire',cx:point.x,cy:point.y,r:7});
    }
    const markers = origin === route.destinationId ? [[origin,'현재 위치 · 도착']] : [[origin,'현재 위치'],[route.destinationId,'목적지']];
    for (const [node,label] of markers) {
      const p = points.get(node);
      append('circle',{class:node===origin?'map-origin':'map-destination',cx:p.x,cy:p.y,r:8});
      append('text',{x:p.x,y:p.y-13,'text-anchor':'middle'},label);
    }
  }

  function render(state, floor) {
    const cloud = state.cloud, sim = !cloud?.enabled && state.operationMode === 'simulation';
    const plan = FireGuardPrototypeProjection.project(FireGuardRealLedProjection.floorplanForReport(floor, cloud));
    const points = new Map([...plan.nodes, ...plan.exits].map(n=>[n.id,n]));
    const name = node => points.get(node)?.name?.replace(/^추가 노드 (N\d+)$/, '$1') || node;
    id('location').textContent = name(origin);
    id('mode').textContent = sim ? '시뮬레이션' : '실제 관제';
    lastReport = stamp(cloud?.observedAt || state.updatedAt) || lastReport;
    const reportText = lastReport ? '마지막 보고 · '+lastReport : '장비 보고 대기 중';
    const {known, route, blocked} = routeFromReport(state);
    if (!points.has(origin) || !known || blocked || !route || !route.nodes.every(node=>points.has(node))) {
      hideGuidance();
      if (!points.has(origin)) message('등록되지 않은 QR 위치', '설치된 QR의 위치를 확인하세요.', 'warning');
      else if (!known) message('현재 경로 확인 불가', reportText, 'warning');
      else if (blocked || state.blockedNodes.includes(origin)) message('이 위치에 화재 감지', '현재 출발 가능한 경로가 없습니다.', 'danger');
      else message('안내 가능한 경로 없음', reportText, 'danger');
      return;
    }
    const fallback = route.routeMode === 'fallback';
    const fire = state.blockedNodes.length > 0;
    message(fire ? (sim ? '모의 화재 감지' : '화재 경보') : '경로 안내 중', reportText, fire ? 'danger' : fallback ? 'warning' : 'normal');
    id('destinationLabel').textContent = fallback ? '보조 대피지점' : '안내 비상구';
    id('exit').textContent = name(route.destinationId);
    id('next').textContent = route.nodes[1] ? '다음 지점 · '+name(route.nodes[1]) : '현재 위치가 안내 목적지입니다.';
    id('route').textContent = route.nodes.map(name).join(' → ');
    draw(plan, points, route, state.blockedNodes);
    id('guidance').hidden = false;
  }

  async function refresh() {
    const controller = new AbortController();
    const deadline = setTimeout(()=>controller.abort(), 6000);
    try {
      const read = async path => {
        const response = await fetch(path,{cache:'no-store',signal:controller.signal});
        if (!response.ok) throw new Error('상태 조회 실패');
        return response.json();
      };
      const [state, floor] = await Promise.all([read('/api/state'),read('/api/floorplan')]);
      render(state, floor);
    } catch {
      hideGuidance();
      message('현재 경로 확인 불가', lastReport ? '마지막 보고 · '+lastReport : '관제 연결을 확인하세요.', 'warning');
    } finally {
      clearTimeout(deadline);
      setTimeout(refresh,2500);
    }
  }
  refresh();
})();
