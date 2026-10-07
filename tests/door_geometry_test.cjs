const assert = require('node:assert/strict');
const floor = require('../static/data/floorplan.json');
const geometry = require('../static/js/map_geometry.js');
const router = geometry.createRouter(floor);
const nodes = Object.fromEntries([...floor.nodes, ...floor.exits].map(n => [n.id, n]));

// Check actual wall intersections independently of the routing search.
function verify(path) {
  assert(path && path.length >= 2, 'A physical path must exist');
  for (let i = 1; i < path.length; i++) {
    const a = path[i-1], b = path[i];
    assert(a.x === b.x || a.y === b.y, 'Segments must be orthogonal');
    for (const wall of router.walls) {
      const intersects = Math.max(a.x,b.x) >= wall.x && Math.min(a.x,b.x) <= wall.x+wall.width &&
        Math.max(a.y,b.y) >= wall.y && Math.min(a.y,b.y) <= wall.y+wall.height;
      assert(!intersects, `Wall crossed: ${JSON.stringify({a,b,wall})}`);
    }
  }
}
for (const edge of floor.edges) {
  const path = router.route(nodes[edge.from], nodes[edge.to]);
  verify(path);
  assert.equal(path[0].x, nodes[edge.from].x);
  assert.equal(path.at(-1).y, nodes[edge.to].y);
  assert.deepEqual(router.route(nodes[edge.to], nodes[edge.from]).map(p=>({x:p.x,y:p.y})), [...path].reverse().map(p=>({x:p.x,y:p.y})));
}

// Door sides and offsets transcribed from the source PDF (600 x 900 mm).
const expected = {cinema5:['bottom',80], cinema4:['right',65], cinema4dx:['top',45], cinema2:['top',45], cinema1:['top',45]};
for (const [id, [side,offset]] of Object.entries(expected)) {
  const room = floor.rooms.find(r => r.id === id);
  assert.equal(room.doors[0].side, side);
  const scale = side === 'right' ? 858/900 : 584/600;
  assert(Math.abs(room.doors[0].offset - offset*scale) < 0.001);
  // Every possible room-to-exit connection must use a wall opening.
  for (const exit of floor.exits) verify(router.route({x:room.x+room.width/2,y:room.y+room.height/2},exit));
}
const south = floor.rooms.find(r => r.id === 'cinema1');
assert(south.doors.some(d => d.side === 'bottom'));
const wall = router.walls[0];
assert.equal(router.validPoint({x:wall.x+wall.width/2,y:wall.y+wall.height/2}), false);
assert.equal(router.route({x:wall.x+wall.width/2,y:wall.y+wall.height/2}, nodes.N1), null);
console.log(`PASS: ${floor.edges.length} edges and 20 room-to-exit paths avoid walls and use PDF door openings`);

// Regression: all edges from an interior point share exactly the same stem,
// including the first vertex OUTSIDE the room. Test off-centre dragged nodes.
const within = (p,r) => p.x >= r.x && p.x <= r.x+r.width && p.y >= r.y && p.y <= r.y+r.height;
for (const room of floor.rooms) {
  for (const point of [
    {x: room.x+room.width*0.3,y: room.y+room.height*0.4},
    {x: room.x+room.width*0.65,y: room.y+room.height*0.6},
  ]) {
    let commonStem;
    for (const exit of floor.exits) {
      const path = router.route(point, exit);
      verify(path);
      const outsideIndex = path.findIndex(p => !within(p,room));
      assert(outsideIndex > 0);
      const stem = path.slice(0,outsideIndex+1);
      if (!commonStem) commonStem = stem;
      else assert.deepEqual(stem,commonStem,`${room.id}: route branched inside`);
      assert(path.slice(outsideIndex).every(p=>!within(p,room)),`${room.id}: route re-entered room`);
      assert.deepEqual(router.route(exit,point),[...path].reverse());
    }
  }
}
console.log('PASS: all 10 rooms share a common stem through the door before branching (including multi-door rooms and dragged nodes)');
