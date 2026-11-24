(function () {
  'use strict';
  const start = document.body.dataset.node;
  const el = id => document.getElementById(id);
  let focused = false, lastDrawing = null, previousRoute = null, changedUntil = 0;
  let referenceFloor = JSON.parse(el('referenceFloorplan').textContent);
  function showReferenceMap() {
    lastDrawing = [window.FireGuardPrototypeProjection.project(referenceFloor), {nodes:[],edges:[]}, {blockedNodes:[]}];
    draw(...lastDrawing);
    // SVGElement.hidden is not reflected to the HTML hidden attribute.
    // Remove the actual attribute so [hidden] CSS cannot hide a drawn map.
    el('map').removeAttribute('hidden');
    el('mapEmpty').hidden = false;
    el('mapEmpty').textContent = '전체 지도와 QR 위치입니다. 현재 대피경로는 확인되지 않았습니다.';
    el('mapToggle').disabled = true;
  }
  function shape(tag, attrs, text) {
    const item = document.createElementNS('http://www.w3.org/2000/svg', tag);
    for (const [key, value] of Object.entries(attrs)) item.setAttribute(key, value);
    if (text !== undefined) item.textContent = text;
    return item;
  }
  function draw(floor, view, state) {
    const map = el('map'); map.replaceChildren();
    const positions = new Map([...floor.nodes,...floor.exits].map(n => [n.id,n]));
    const selected = view.nodes.map(id => positions.get(id)).filter(Boolean);
    if (focused && selected.length > 1) {
      const x = Math.max(0,Math.min(...selected.map(n=>n.x))-55), y = Math.max(0,Math.min(...selected.map(n=>n.y))-55);
      const right = Math.min(floor.viewBox.width,Math.max(...selected.map(n=>n.x))+55);
      const bottom = Math.min(floor.viewBox.height,Math.max(...selected.map(n=>n.y))+55);
      map.setAttribute('viewBox',`${x} ${y} ${Math.max(120,right-x)} ${Math.max(160,bottom-y)}`);
    } else map.setAttribute('viewBox', `0 0 ${floor.viewBox.width} ${floor.viewBox.height}`);
    const defs = shape('defs', {}), marker = shape('marker', {id:'direction', viewBox:'0 0 10 10', refX:8, refY:5, markerWidth:4, markerHeight:4, orient:'auto'});
    marker.append(shape('path', {d:'M 0 0 L 10 5 L 0 10 z', fill:'#81cfed'})); defs.append(marker); map.append(defs);
    for (const room of floor.rooms || []) {
      map.append(shape('rect', {x:room.x,y:room.y,width:room.width,height:room.height,rx:5,fill:'#1b3041',stroke:'#506579'}));
      map.append(shape('text', {x:room.x+room.width/2,y:room.y+room.height/2,'text-anchor':'middle','font-size':13,fill:'#c8dce9'},room.name || room.label || ''));
    }
    const points = new Map([...floor.nodes,...floor.exits].map(n => [n.id,n]));
    for (const edge of floor.edges) {
      const a = points.get(edge.from), b = points.get(edge.to);
      if (a && b) map.append(shape('line',{x1:a.x,y1:a.y,x2:b.x,y2:b.y,stroke:'#4b6174','stroke-width':4}));
    }
    for (let i = 1; i < view.nodes.length; i++) {
      const a = points.get(view.nodes[i-1]), b = points.get(view.nodes[i]);
      map.append(shape('line',{x1:a.x,y1:a.y,x2:b.x,y2:b.y,stroke:'#81cfed','stroke-width':6,'marker-end':'url(#direction)'}));
    }
    for (const exit of floor.exits) {
      map.append(shape('circle',{cx:exit.x,cy:exit.y,r:8,fill:'#138364'}));
      map.append(shape('text',{x:Math.max(35,Math.min(floor.viewBox.width-40,exit.x)),y:exit.y-14,'text-anchor':'middle','font-size':13,fill:'#9fe1bd'},exit.name));
    }
    for (const id of state.blockedNodes || []) {
      const point = points.get(id);
      if (point) map.append(shape('circle',{cx:point.x,cy:point.y,r:10,fill:'#d83449'}));
    }
    const origin = points.get(start);
    if (origin) {
      map.append(shape('circle',{cx:origin.x,cy:origin.y,r:12,fill:'#ffba42',stroke:'#593900','stroke-width':2}));
      map.append(shape('text',{x:origin.x,y:origin.y-19,'text-anchor':'middle','font-size':16,'font-weight':'bold',fill:'#ffd278'},'현재 위치'));
    }
  }
  function clear(message) {
    lastDrawing = null; previousRoute = null; changedUntil = 0;
    el('status').dataset.status = 'unknown';
    el('nextStop').textContent = '현장 안내 확인';
    el('routeChange').hidden = true;
    el('status').textContent = '최신 안내 확인 불가';
    el('message').textContent = message;
    el('destination').textContent = '현장 안내를 확인하세요';
    el('steps').replaceChildren();
    showReferenceMap();
    el('stepsTitle').hidden = true;
    el('updated').textContent = '경로 표시를 중단했습니다.';
  }
  async function refresh() {
    if (document.hidden) { clear('화면을 다시 열면 최신 경로를 확인합니다.'); return; }
    const controller = new AbortController(), timeout = setTimeout(() => controller.abort(), 7000);
    try {
      const read = async url => {
        const response = await fetch(url,{cache:'no-store',signal:controller.signal});
        if (!response.ok) throw new Error('조회 실패');
        return response.json();
      };
      const [stateResult, floorResult] = await Promise.allSettled([read('/api/state?startNode='+encodeURIComponent(start)),read('/api/floorplan')]);
      if (floorResult.status === 'fulfilled') referenceFloor = floorResult.value;
      if (stateResult.status !== 'fulfilled' || floorResult.status !== 'fulfilled') {
        clear('최신 상태를 확인할 수 없어 대피경로를 숨겼습니다. 전체 지도는 참고용입니다.'); return;
      }
      const state = stateResult.value, raw = floorResult.value;
      if (document.hidden || !navigator.onLine) { clear('최신 경로를 다시 확인해야 합니다.'); return; }
      const floor = window.FireGuardRealLedProjection.floorplanForReport(raw,state.cloud);
      const view = window.FireGuardMobileGuidance.select(state,floor,start);
      const names = Object.fromEntries([...floor.nodes,...floor.exits].map(n => [n.id,n.name || n.id]));
      names[start] = document.body.dataset.location || names[start];
      el('location').textContent = names[start] || start;
      el('status').textContent = {unknown:'최신 안내 확인 불가',no_route:'연결된 경로 없음',fire:'화재 감지 · 대피경로',fallback:'보조 대피지점 안내',normal:'평상시 출구 안내',simulation:'시뮬레이션'}[view.status];
      el('status').dataset.status = view.status;
      el('message').textContent = view.message;
      el('destination').textContent = view.destination ? names[view.destination] : '현장 안내를 확인하세요';
      el('nextStop').textContent = view.nodes[1] ? names[view.nodes[1]] : view.destination === start ? '안내 목적지에 도착한 위치입니다' : '현장 안내 확인';
      const routeKey = view.nodes.length ? JSON.stringify(view.nodes) : null;
      if (previousRoute && routeKey && previousRoute !== routeKey) {
        changedUntil = Date.now()+12000;
        el('routeChange').textContent = '대피경로가 변경되었습니다. 새 목적지와 이동 순서를 확인하세요.';
      }
      previousRoute = routeKey;
      el('routeChange').hidden = !routeKey || Date.now() >= changedUntil;
      el('steps').replaceChildren();
      for (const id of view.nodes) {
        const li = document.createElement('li'); li.textContent = `${names[id]} (${id})`; el('steps').append(li);
      }
      lastDrawing = view.status === 'unknown' ? null : [window.FireGuardPrototypeProjection.project(floor),view,state];
      el('map').toggleAttribute('hidden', !lastDrawing); el('mapEmpty').hidden = !!lastDrawing;
      el('mapToggle').disabled = !lastDrawing;
      el('stepsTitle').hidden = view.nodes.length === 0;
      if (!lastDrawing) showReferenceMap(); else draw(...lastDrawing);
      const reported = state.cloud?.observedAt || state.updatedAt;
      const validTime = reported && !Number.isNaN(Date.parse(reported));
      el('updated').textContent = (validTime ? '상태 보고 '+new Date(reported).toLocaleTimeString('ko-KR') : '상태 보고 시각 미확인')+' · 2초마다 확인';
    } catch (error) { clear('통신이 끊겨 최신 경로를 확인할 수 없습니다. 현장 안내를 확인하세요.'); }
    finally { clearTimeout(timeout); }
  }
  let running = false;
  async function tick() { if (running) return; running = true; el('refresh').disabled = true; try { await refresh(); } finally { running = false; el('refresh').disabled = false; } }
  el('mapToggle').addEventListener('click',() => {
    focused = !focused; el('mapToggle').setAttribute('aria-pressed',String(focused));
    el('mapToggle').textContent = focused ? '전체 지도' : '경로 확대';
    if (lastDrawing) draw(...lastDrawing);
  });
  window.addEventListener('offline',() => clear('인터넷 연결을 확인하세요.'));
  document.addEventListener('visibilitychange',() => { clear('최신 경로를 확인하고 있습니다.'); if (!document.hidden) tick(); });
  el('refresh').addEventListener('click',tick);
  showReferenceMap(); tick(); setInterval(tick,2000);
}());
