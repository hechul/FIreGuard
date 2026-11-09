const assert = require('node:assert/strict');
const source = require('../static/data/floorplan.json');
const projection = require('../static/js/prototype_projection.js');
const geometry = require('../static/js/map_geometry.js');
const before = JSON.stringify(source);
const view = projection.project(source);
const p = Object.fromEntries([...view.nodes, ...view.exits].map(n => [n.id, n]));
assert.equal(p.N28.x, p.N35.x);
assert.equal(p.N5.x, p.N35.x);
assert.equal(p.N13.x, p.N35.x);
assert.equal(p.N28.y, p.N35.y);
assert.equal(JSON.stringify(source), before, 'display projection must not mutate canonical data');
const room = view.rooms.find(r => r.id === 'toilet1');
assert(p.N5.x > room.x && p.N5.x < room.x + room.width);
const route = geometry.createRouter(view);
for (const [a,b] of [['N13','N35'], ['N28','N5']]) {
 const points = route.route(p[a],p[b]);
 assert(points && points.length >= 2, `projected ${a}-${b} route should reach its door`);
 assert(points.every(q => Math.abs(q.x - p.N35.x) < 0.01), `${a}-${b} should follow the shared straight corridor`);
}
assert.equal(view.edges.find(e=>e.id==='E30').weight,source.edges.find(e=>e.id==='E30').weight);
console.log('PASS: prototype projection aligns both branches without changing graph data');
