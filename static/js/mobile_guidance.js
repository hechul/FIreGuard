/* Read-only QR routing: use the Pi forest during a real fire. */
(function (root, factory) {
  if (typeof module === 'object' && module.exports) module.exports = factory();
  else root.FireGuardMobileGuidance = factory();
}(typeof globalThis !== 'undefined' ? globalThis : this, function () {
  'use strict';
  function select(state, floor, start) {
    const unknown = message => ({status:'unknown', message, nodes:[], edges:[]});
    const noRoute = message => ({status:'no_route', message, nodes:[], edges:[]});
    const nodes = new Map([...floor.nodes, ...floor.exits].map(n => [n.id, n]));
    if (!nodes.has(start)) return unknown('등록되지 않은 위치입니다.');
    const cloud = state.cloud;
    if (cloud?.enabled && (!cloud.hasTelemetry || cloud.stale !== false))
      return unknown('장비의 최신 상태를 확인할 수 없습니다. 현장 안내를 확인하세요.');
    if (cloud?.enabled && Object.values(state.flameSensors || {}).some(s => !s.connected))
      return unknown('일부 화재 센서의 연결이 끊겼습니다. 현장 안내를 확인하세요.');
    const blocked = new Set([...(state.blockedNodes || []), ...(cloud?.hardware?.blockedNodes || [])]);
    if (blocked.has(start)) return noRoute('현재 위치에서 화재가 감지되었습니다. 즉시 현장 안내를 확인하세요.');
    const h = cloud?.hardware;
    if (cloud?.enabled && state.realFireDetected) {
      const plan = h?.allZone;
      if (h?.operationMode !== 'real' || !plan || plan.routingMode !== 'all_zones_to_exits')
        return unknown('이 위치의 Pi 대피경로 보고를 기다리고 있습니다.');
      const successors = new Map();
      for (const edge of plan.directedEdges || []) {
        if (successors.has(edge.from)) return unknown('경로 정보를 확인할 수 없습니다.');
        successors.set(edge.from, edge);
      }
      const exits = new Set(plan.availableExits || []), fallback = new Set(plan.fallbackDestinations || []);
      const routeNodes = [start], routeEdges = [], seen = new Set();
      const closed = new Set([...(state.blockedEdges || []), ...(h.blockedEdges || []), ...(plan.ledExcludedEdges || [])]);
      const edges = new Map(floor.edges.map(e => [e.id, e]));
      let at = start;
      while (!exits.has(at) && !fallback.has(at)) {
        if (seen.has(at)) return unknown('경로 정보를 확인할 수 없습니다.');
        seen.add(at);
        const next = successors.get(at);
        if (!next) return noRoute('현재 위치에서 연결된 대피경로가 없습니다. 현장 안내를 확인하세요.');
        const edge = edges.get(next.edgeId);
        if (!edge || !nodes.has(next.to) || blocked.has(next.to) || closed.has(edge.id) ||
            !((edge.from === at && edge.to === next.to) || (edge.to === at && edge.from === next.to)))
          return unknown('현재 화재 상태와 경로가 일치하지 않습니다.');
        routeEdges.push(edge.id); routeNodes.push(next.to); at = next.to;
      }
      return {status:fallback.has(at) ? 'fallback' : 'fire', nodes:routeNodes, edges:routeEdges,
        destination:at, message:fallback.has(at) ? '정규 비상구 대신 지정된 보조 대피지점입니다.' : '현재 화재를 반영한 Pi 대피경로입니다.'};
    }
    const route = !cloud?.enabled && Object.hasOwn(state.simulationZoneRoutes || {}, start)
      ? state.simulationZoneRoutes[start] : state.route;
    if (!route || route.nodes?.[0] !== start || route.nodes.some(n => !nodes.has(n) || blocked.has(n)))
      return noRoute('현재 위치에서 연결된 경로를 찾을 수 없습니다.');
    if (route.routeMode === 'fallback')
      return {status:'fallback',nodes:route.nodes,edges:route.edges,destination:route.nodes.at(-1),
        message:(cloud?.enabled ? '' : '시뮬레이션 · ')+'정규 비상구 대신 지정된 보조 대피지점입니다.'};
    return {status:cloud?.enabled ? 'normal' : 'simulation', nodes:route.nodes, edges:route.edges,
      destination:route.nodes[route.nodes.length - 1],
      message:cloud?.enabled ? '평상시 출구 위치 안내입니다. 화재 발생 시 경로가 갱신됩니다.' : '시뮬레이션 경로입니다. 실제 장비 상태가 아닙니다.'};
  }
  return {select};
}));
