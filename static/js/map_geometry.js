/* Door-aware orthogonal edge geometry. Logical graph IDs/weights stay unchanged. */
((root) => {
  'use strict';
  const EPS = 0.00001;
  const inside = (p, r) => p.x > r.x - EPS && p.x < r.x + r.width + EPS && p.y > r.y - EPS && p.y < r.y + r.height + EPS;

  function wallRects(room) {
    const t = room.wallThickness || 4.8;
    const result = [];
    for (const side of ['top', 'bottom', 'left', 'right']) {
      const horizontal = side === 'top' || side === 'bottom';
      const length = horizontal ? room.width : room.height;
      const doors = (room.doors || []).filter(d => d.side === side).sort((a, b) => a.offset - b.offset);
      let cursor = 0;
      for (const door of [...doors, {offset: length, width: 0}]) {
        if (door.offset > cursor) {
          result.push(horizontal
            ? {x: room.x + cursor, y: side === 'top' ? room.y : room.y + room.height - t, width: door.offset - cursor, height: t}
            : {x: side === 'left' ? room.x : room.x + room.width - t, y: room.y + cursor, width: t, height: door.offset - cursor});
        }
        cursor = door.offset + door.width;
      }
    }
    return result;
  }

  function segmentClear(a, b, obstacles) {
    if (Math.abs(a.x - b.x) > EPS && Math.abs(a.y - b.y) > EPS) return false;
    const x0 = Math.min(a.x, b.x), x1 = Math.max(a.x, b.x);
    const y0 = Math.min(a.y, b.y), y1 = Math.max(a.y, b.y);
    return !obstacles.some(r => x1 >= r.x - EPS && x0 <= r.x + r.width + EPS && y1 >= r.y - EPS && y0 <= r.y + r.height + EPS);
  }

  // Small binary heap keeps dragging responsive even on a large screen.
  class Heap {
    constructor() { this.items = []; }
    push(value) {
      const a = this.items; let i = a.length; a.push(value);
      while (i > 0) { const p = (i - 1) >> 1; if (a[p].score <= value.score) break; a[i] = a[p]; i = p; }
      a[i] = value;
    }
    pop() {
      const a = this.items, first = a[0], last = a.pop();
      if (a.length) {
        let i = 0;
        while (i * 2 + 1 < a.length) {
          let child = i * 2 + 1;
          if (child + 1 < a.length && a[child + 1].score < a[child].score) child++;
          if (a[child].score >= last.score) break;
          a[i] = a[child]; i = child;
        }
        a[i] = last;
      }
      return first;
    }
  }

  function createRouter(floorplan) {
    const walls = (floorplan.rooms || []).flatMap(wallRects);
    const clearance = 6;
    const obstacles = walls.map(r => ({x: r.x - clearance, y: r.y - clearance, width: r.width + clearance * 2, height: r.height + clearance * 2}));
    const rooms = floorplan.rooms || [];
    // Between door portals, stay outside every room (including alternate doors).
    const exteriorObstacles = rooms.map(r => ({x: r.x - clearance, y: r.y - clearance, width: r.width + clearance * 2, height: r.height + clearance * 2}));
    const cache = new Map();
    const maxX = floorplan.viewBox.width - 8, maxY = floorplan.viewBox.height - 8;
    const xs = [8, maxX], ys = [8, maxY];
    for (const r of obstacles) {
      xs.push(r.x - 0.1, r.x + r.width + 0.1);
      ys.push(r.y - 0.1, r.y + r.height + 0.1);
    }
    for (const room of floorplan.rooms || []) {
      xs.push(room.x + room.width / 2); ys.push(room.y + room.height / 2);
      for (const door of room.doors || []) {
        if (door.side === 'top' || door.side === 'bottom') xs.push(room.x + door.offset + door.width / 2);
        else ys.push(room.y + door.offset + door.width / 2);
      }
    }
    const rounded = n => Number(n.toFixed(6));
    const unique = (values, max) => [...new Set(values.map(rounded).filter(n => n >= 8 && n <= max))].sort((a,b) => a-b);
    const validPoint = p => Number.isFinite(p.x) && Number.isFinite(p.y) && p.x >= 8 && p.x <= maxX && p.y >= 8 && p.y <= maxY && !obstacles.some(r => inside(p, r));

    function findRoute(a, b, exterior = false) {
      a = {x: rounded(a.x), y: rounded(a.y)};
      b = {x: rounded(b.x), y: rounded(b.y)};
      const key = `${exterior}:${a.x},${a.y}:${b.x},${b.y}`;
      if (cache.has(key)) return cache.get(key);
      if (!validPoint(a) || !validPoint(b)) return null;
      const barriers = exterior ? exteriorObstacles : obstacles;
      if (segmentClear(a, b, barriers)) return [a, b];
      const xx = unique([...xs, a.x, b.x], maxX), yy = unique([...ys, a.y, b.y], maxY);
      const width = xx.length;
      const start = yy.indexOf(a.y) * width + xx.indexOf(a.x);
      const end = yy.indexOf(b.y) * width + xx.indexOf(b.x);
      const points = yy.flatMap(y => xx.map(x => ({x, y})));
      // Remember incoming direction to favor readable routes with fewer bends.
      const distances = new Float64Array(points.length * 3).fill(Infinity);
      const previous = new Int32Array(points.length * 3).fill(-1);
      const queue = new Heap();
      distances[start * 3] = 0; queue.push({id: start * 3, cost: 0, score: 0});
      let goal = -1;
      while (queue.items.length) {
        const {id: state, cost} = queue.pop();
        if (cost !== distances[state]) continue;
        const id = Math.floor(state / 3), direction = state % 3;
        if (id === end) { goal = state; break; }
        const col = id % width, row = Math.floor(id / width);
        const neighbors = [];
        if (col > 0) neighbors.push(id - 1);
        if (col < width - 1) neighbors.push(id + 1);
        if (row > 0) neighbors.push(id - width);
        if (row < yy.length - 1) neighbors.push(id + width);
        for (const next of neighbors) {
          if (!segmentClear(points[id], points[next], barriers)) continue;
          const p = points[next];
          const nextDirection = p.x === points[id].x ? 2 : 1;
          const nextState = next * 3 + nextDirection;
          const turn = direction && direction !== nextDirection ? 8 : 0;
          const candidate = cost + Math.abs(p.x - points[id].x) + Math.abs(p.y - points[id].y) + turn;
          if (candidate >= distances[nextState]) continue;
          distances[nextState] = candidate; previous[nextState] = state;
          queue.push({id: nextState, cost: candidate, score: candidate + Math.abs(p.x-b.x) + Math.abs(p.y-b.y)});
        }
      }
      let result = null;
      if (goal !== -1) {
        const path = [];
        for (let state = goal; state !== -1; state = previous[state]) path.push(points[Math.floor(state / 3)]);
        path.reverse();
        result = path.filter((p, i) => i === 0 || i === path.length-1 || !(
          (path[i-1].x === p.x && path[i+1].x === p.x) ||
          (path[i-1].y === p.y && path[i+1].y === p.y)));
      }
      if (cache.size > 500) cache.clear();
      cache.set(key, result);
      cache.set(`${exterior}:${b.x},${b.y}:${a.x},${a.y}`, result && [...result].reverse());
      return result;
    }

    function roomFor(point) { return rooms.find(room => inside(point, room)); }

    function roomStem(point, room) {
      if (!room) return [point];
      // The primary door is stable, independent of which edge/destination is drawn.
      // PDF door order lists the normal corridor entrance before auxiliary exits.
      const door = room.doors?.[room.routingDoor ?? 0];
      if (!door) return null;
      const horizontal = door.side === 'top' || door.side === 'bottom';
      const gap = clearance + 6;
      const portal = horizontal
        ? {x: room.x + door.offset + door.width / 2, y: door.side === 'top' ? room.y - gap : room.y + room.height + gap}
        : {x: door.side === 'left' ? room.x - gap : room.x + room.width + gap, y: room.y + door.offset + door.width / 2};
      portal.x = rounded(portal.x); portal.y = rounded(portal.y);
      const bend = horizontal ? {x: portal.x, y: point.y} : {x: point.x, y: portal.y};
      const stem = [point, bend, portal].filter((p, i, list) => i === 0 || p.x !== list[i-1].x || p.y !== list[i-1].y);
      return stem.every((p, i) => validPoint(p) && (i === 0 || segmentClear(stem[i-1], p, obstacles))) ? stem : null;
    }

    function route(a, b) {
      a = {x: rounded(a.x), y: rounded(a.y)};
      b = {x: rounded(b.x), y: rounded(b.y)};
      if (!validPoint(a) || !validPoint(b)) return null;
      const roomA = roomFor(a), roomB = roomFor(b);
      if (roomA && roomA === roomB) return findRoute(a, b);
      const start = roomStem(a, roomA), end = roomStem(b, roomB);
      if (!start || !end) return null;
      const middle = findRoute(start.at(-1), end.at(-1), true);
      if (!middle) return null;
      // Keep portal vertices explicit so every incident edge shares the entire stem.
      return [...start, ...middle.slice(1), ...end.slice(0, -1).reverse()];
    }
    return {route, validPoint, walls};
  }

  function midpoint(points) {
    if (!points?.length) return null;
    let length = 0;
    const lengths = points.slice(1).map((p,i) => {const n = Math.hypot(p.x-points[i].x, p.y-points[i].y); length += n; return n;});
    let remaining = length / 2;
    for (let i = 0; i < lengths.length; i++) {
      if (remaining <= lengths[i]) {const t = lengths[i] ? remaining / lengths[i] : 0; return {x: points[i].x+(points[i+1].x-points[i].x)*t, y: points[i].y+(points[i+1].y-points[i].y)*t};}
      remaining -= lengths[i];
    }
    return points[0];
  }
  const api = {wallRects, segmentClear, createRouter, midpoint};
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  else root.MapGeometry = api;
})(typeof window !== 'undefined' ? window : globalThis);
