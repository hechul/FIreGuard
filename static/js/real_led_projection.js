/* Project acknowledged Pi LED commands onto the dashboard reference drawing.
   This is an approximate map of commands, never evidence of physical light. */
(function (root, factory) {
  if (typeof module === 'object' && module.exports) module.exports = factory();
  else root.FireGuardRealLedProjection = factory();
}(typeof globalThis !== 'undefined' ? globalThis : this, function () {
  'use strict';
  const knownVersions = new Set([
    'led162-usb163-shift20-dfea4ba7d3',
    'led162-usb163-shift20-da2de217fd',
    'led162-usb163-shift20-c5a4392f78',
  ]);
  // Same S1-S15 counts and DIN-to-DOUT directions as Pi led_routes.py.
  const specs = [
    ['S1',4,'right'], ['S2',32,'up'], ['S3',30,'left'],
    ['S4',4,'up'], ['S5',4,'up'], ['S6',4,'down'], ['S7',4,'down'],
    ['S8',14,'down'], ['S9',23,'up'], ['S10',4,'right'], ['S11',5,'right'],
    ['S12',7,'right'], ['S13',5,'up'], ['S14',18,'right'], ['S15',4,'up'],
  ];
  function coordinates(sections) {
    if (!Array.isArray(sections) || sections.length !== specs.length) return null;
    const result = [];
    for (let i = 0; i < specs.length; i++) {
      const [id, count, direction] = specs[i], section = sections[i];
      if (!section || section.id !== id || section.count !== count ||
          !Array.isArray(section.line) || section.line.length !== 2 ||
          section.line.some(p => !Array.isArray(p) || p.length !== 2 || p.some(n => !Number.isFinite(n)))) return null;
      let [a,b] = section.line;
      if ((direction === 'right' && a[0] > b[0]) || (direction === 'left' && a[0] < b[0]) ||
          (direction === 'down' && a[1] > b[1]) || (direction === 'up' && a[1] < b[1])) [a,b] = [b,a];
      for (let n = 0; n < count; n++) {
        const t = (n + 0.5) / count;
        result.push({x: a[0] + (b[0] - a[0]) * t, y: a[1] + (b[1] - a[1]) * t});
      }
    }
    return result.length === 162 ? result : null;
  }
  function validIndices(values) {
    return Array.isArray(values) && values.every(n => Number.isInteger(n) && n >= 0 && n < 162) && new Set(values).size === values.length;
  }
  function consistent(logical, slots) {
    return Array.isArray(slots) && slots.length === logical.length &&
      logical.every((value, i) => slots[i] === value + (value >= 20 ? 1 : 0));
  }
  // Pi's directed forest is a calculation, independent of the Uno ACK.
  // Keep stale reports identifiable but never draw their edges as current.
  function allZoneSummary(cloud) {
    const h = cloud?.hardware, plan = h?.allZone;
    if (!cloud?.enabled || !cloud.hasTelemetry || !['pi', 'pi_unverified'].includes(cloud.routeSource) ||
        h?.operationMode !== 'real' || !plan || plan.routingMode !== 'all_zones_to_exits' ||
        !['ok', 'partial', 'no_route'].includes(plan.routeStatus)) return null;
    const identifiers = values => Array.isArray(values) && values.every(x => typeof x === 'string' && /^[A-Za-z0-9_-]{1,64}$/.test(x)) && new Set(values).size === values.length;
    const fallbackDestinations = plan.fallbackDestinations ?? [];
    if (!identifiers(plan.availableExits) || !identifiers(fallbackDestinations) || !identifiers(plan.guidedNodes) ||
        !identifiers(plan.unreachableNodes) || !identifiers(plan.ledExcludedEdges) ||
        !Array.isArray(plan.directedEdges) || plan.directedEdges.some(e => !e ||
          ![e.edgeId, e.from, e.to, e.exitNode].every(x => typeof x === 'string' && /^[A-Za-z0-9_-]{1,64}$/.test(x)) || e.from === e.to)) return null;
    const stale = cloud.stale !== false;
    const unverified = cloud.routeSource === 'pi_unverified';
    const statuses = {ok:'전체 구역 경로 계산', partial:'일부 구역 경로 없음', no_route:'전체 구역 경로 없음'};
    return {
      stale, unverified, status: stale ? '전체 구역 마지막 보고 · 현재 미확인' : unverified ? 'Pi 전체 경로 확인 필요' : statuses[plan.routeStatus],
      label: stale ? '마지막 Pi 보고 · 현재 상태 미확인' : unverified ? 'Pi 경로와 센서 상태를 확인해 주세요' : 'Pi 계산 경로 · LED 적용 및 실제 발광은 별도 확인',
      routeStatus: plan.routeStatus,
      guidedCount: plan.guidedNodes.length, unreachableCount: plan.unreachableNodes.length,
      availableExits: [...plan.availableExits],
      fallbackDestinations: [...fallbackDestinations],
      directedEdges: stale || unverified ? [] : plan.directedEdges.map(({edgeId,from,to,exitNode}) => ({edgeId,from,to,exitNode})),
      ledAcknowledged: !stale && !unverified && h.ledStatus === 'active' && h.ledCommandAck === true,
    };
  }
  function project(cloud, sections) {
    const h = cloud?.hardware;
    if (!cloud?.enabled || !cloud.hasTelemetry || cloud.stale !== false || cloud.routeSource !== 'pi' ||
        !h || h.operationMode !== 'real' || h.ledStatus !== 'active' || h.ledCommandAck !== true ||
        !knownVersions.has(h.ledMappingVersion) || !validIndices(h.ledLogicalIndices) ||
        !validIndices(h.fireLedLogicalIndices) || !consistent(h.ledLogicalIndices, h.ledIndices) ||
        !consistent(h.fireLedLogicalIndices, h.fireLedIndices)) return null;
    const coords = coordinates(sections);
    if (!coords) return null;
    const fires = new Set(h.fireLedLogicalIndices), seen = new Set([...h.ledLogicalIndices, ...fires]);
    return {
      label: allZoneSummary(cloud) ? 'Pi 전체 구역 LED 명령 위치 · 도면 기준 추정 · 실제 발광 미확인' : 'Pi 명령 위치 · 도면 기준 추정 · 실제 발광 미확인',
      points: [...seen].map(index => ({index, ...coords[index], color: fires.has(index) ? 'fire' : 'route'})),
    };
  }
  // The simulator must never draw physical REAL output as its own state.
  function projectFor3d(state, sections) {
    return state?.operationMode === 'real' ? project(state.cloud, sections) : null;
  }
  // A disconnected browser cannot continue to present an old server response
  // as live, even if the Pi was online when that response was generated.
  function markConnectionUnknown(state) {
    if (!state?.cloud?.enabled) return state;
    const flameSensors = Object.fromEntries(Object.entries(state.flameSensors || {}).map(
      ([id, sensor]) => [id, {...sensor, connected: false}]));
    return {...state, cloud: {...state.cloud, stale: true},
      connections: {...state.connections, pi: false}, flameSensors,
      sensorCounts: {...state.sensorCounts, offline: Object.keys(flameSensors).length},
      equipment: (state.equipment || []).map(item => ({...item, status:'offline',
        stateLabel:'서버 연결 끊김 · 현재 상태 미확인'}))};
  }
  return { coordinates, project, allZoneSummary, projectFor3d, markConnectionUnknown };
}));
