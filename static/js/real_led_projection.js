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
      label: 'Pi 명령 위치 · 도면 기준 추정 · 실제 발광 미확인',
      points: [...seen].map(index => ({index, ...coords[index], color: fires.has(index) ? 'fire' : 'route'})),
    };
  }
  return { coordinates, project };
}));
