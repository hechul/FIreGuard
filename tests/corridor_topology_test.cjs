const assert = require('node:assert/strict');
const floor = require('../static/data/floorplan.json');
const router = require('../static/js/map_geometry.js').createRouter(floor);
const nodes = Object.fromEntries([...floor.nodes, ...floor.exits].map(n => [n.id, n]));
const segments = [];
for (const edge of floor.edges) {
  const path = router.route(nodes[edge.from], nodes[edge.to]);
  assert(path, `Missing physical route: ${edge.id}`);
  for (let i = 1; i < path.length; i++) segments.push({id: edge.id, a: path[i-1], b: path[i]});
}
// Ignore sub-0.01 coordinate rounding at door centres, not shared corridors.
for (let i = 0; i < segments.length; i++) {
  for (const t of segments.slice(i+1)) {
    const s = segments[i];
    if (s.id === t.id) continue;
    for (const [axis, other] of [['x','y'], ['y','x']]) {
      if (Math.abs(s.a[axis]-s.b[axis]) > 1e-6 || Math.abs(t.a[axis]-t.b[axis]) > 1e-6 || Math.abs(s.a[axis]-t.a[axis]) > 1e-6) continue;
      const overlap = Math.min(Math.max(s.a[other],s.b[other]), Math.max(t.a[other],t.b[other])) - Math.max(Math.min(s.a[other],s.b[other]), Math.min(t.a[other],t.b[other]));
      assert(overlap <= 0.01, `${s.id} and ${t.id} duplicate ${overlap} units of corridor`);
    }
  }
}
const protectedNodes = {
  N10:[525.6,567.23], N7:[107.07,567.23], N8:[253.07,567.23], N9:[374.73,567.23],
  N14:[374.73,409.93], N20:[105,140], N11:[450,790], N1:[240,243],
  N5:[214.13,488.58], N6:[296.87,488.58], N3:[107.07,362.27],
};
assert.deepEqual(floor.sensors.filter(s=>s.type==='flame').map(s=>s.node).sort(), Object.keys(protectedNodes).sort());
for (const [id, xy] of Object.entries(protectedNodes)) assert.deepEqual([nodes[id].x,nodes[id].y], xy, `Protected sensor moved: ${id}`);
assert(!nodes.N21 && !nodes.N32, 'Unused northwest nodes must be removed');
assert(floor.edges.some(e => [e.from,e.to].includes('N20') && [e.from,e.to].includes('N23')), 'N20 must connect directly to N23');
console.log('PASS: no duplicate corridor segments; 11 flame sensors at approved positions; northwest corridor simplified');
