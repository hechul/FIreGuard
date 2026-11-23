(function () {
  'use strict';
  const start = document.body.dataset.node;
  const el = id => document.getElementById(id);
  function shape(tag, attrs, text) {
    const item = document.createElementNS('http://www.w3.org/2000/svg', tag);
    for (const [key, value] of Object.entries(attrs)) item.setAttribute(key, value);
    if (text !== undefined) item.textContent = text;
    return item;
  }
  function draw(floor, view, state) {
    const map = el('map'); map.replaceChildren();
    map.setAttribute('viewBox', `0 0 ${floor.viewBox.width} ${floor.viewBox.height}`);
    const defs = shape('defs', {}), marker = shape('marker', {id:'direction', viewBox:'0 0 10 10', refX:8, refY:5, markerWidth:4, markerHeight:4, orient:'auto'});
    marker.append(shape('path', {d:'M 0 0 L 10 5 L 0 10 z', fill:'#176bda'})); defs.append(marker); map.append(defs);
    for (const room of floor.rooms || []) {
      map.append(shape('rect', {x:room.x,y:room.y,width:room.width,height:room.height,rx:5,fill:'#edf2f6',stroke:'#d4dde6'}));
      map.append(shape('text', {x:room.x+room.width/2,y:room.y+room.height/2,'text-anchor':'middle','font-size':13,fill:'#536779'},room.name || room.label || ''));
    }
    const points = new Map([...floor.nodes,...floor.exits].map(n => [n.id,n]));
    for (const edge of floor.edges) {
      const a = points.get(edge.from), b = points.get(edge.to);
      if (a && b) map.append(shape('line',{x1:a.x,y1:a.y,x2:b.x,y2:b.y,stroke:'#ccd5de','stroke-width':4}));
    }
    for (let i = 1; i < view.nodes.length; i++) {
      const a = points.get(view.nodes[i-1]), b = points.get(view.nodes[i]);
      map.append(shape('line',{x1:a.x,y1:a.y,x2:b.x,y2:b.y,stroke:'#176bda','stroke-width':6,'marker-end':'url(#direction)'}));
    }
    for (const exit of floor.exits) {
      map.append(shape('circle',{cx:exit.x,cy:exit.y,r:8,fill:'#138364'}));
      map.append(shape('text',{x:Math.max(35,Math.min(floor.viewBox.width-40,exit.x)),y:exit.y-14,'text-anchor':'middle','font-size':13,fill:'#086747'},exit.name));
    }
    for (const id of state.blockedNodes || []) {
      const point = points.get(id);
      if (point) map.append(shape('circle',{cx:point.x,cy:point.y,r:10,fill:'#d83449'}));
    }
    const origin = points.get(start);
    if (origin) {
      map.append(shape('circle',{cx:origin.x,cy:origin.y,r:12,fill:'#ffba42',stroke:'#593900','stroke-width':2}));
      map.append(shape('text',{x:origin.x,y:origin.y-19,'text-anchor':'middle','font-size':16,'font-weight':'bold',fill:'#593900'},'현재 위치'));
    }
  }
  function clear(message) {
    el('status').textContent = '최신 안내 확인 불가';
    el('message').textContent = message;
    el('destination').textContent = '현장 안내를 확인하세요';
    el('steps').replaceChildren(); el('map').replaceChildren();
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
      const [state, raw] = await Promise.all([read('/api/state?startNode='+encodeURIComponent(start)),read('/api/floorplan')]);
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
      el('steps').replaceChildren();
      for (const id of view.nodes) {
        const li = document.createElement('li'); li.textContent = `${names[id]} (${id})`; el('steps').append(li);
      }
      if (view.status === 'unknown') el('map').replaceChildren();
      else draw(window.FireGuardPrototypeProjection.project(floor),view,state);
      el('updated').textContent = '화면 갱신 '+new Date().toLocaleTimeString('ko-KR')+' · 2초마다 확인';
    } catch (error) { clear('통신이 끊겨 최신 경로를 확인할 수 없습니다. 현장 안내를 확인하세요.'); }
    finally { clearTimeout(timeout); }
  }
  let running = false;
  async function tick() { if (running) return; running = true; try { await refresh(); } finally { running = false; } }
  window.addEventListener('offline',() => clear('인터넷 연결을 확인하세요.'));
  document.addEventListener('visibilitychange',() => { clear('최신 경로를 확인하고 있습니다.'); if (!document.hidden) tick(); });
  el('refresh').addEventListener('click',tick);
  tick(); setInterval(tick,2000);
}());
