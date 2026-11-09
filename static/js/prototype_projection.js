/* Presentation-only geometry: graph IDs, costs and Pi mappings remain unchanged. */
(function (root, factory) {
  if (typeof module === 'object' && module.exports) module.exports = factory();
  else root.FireGuardPrototypeProjection = factory();
}(typeof globalThis !== 'undefined' ? globalThis : this, function () {
  'use strict';
  function project(floorplan) {
    const view = JSON.parse(JSON.stringify(floorplan));
    const byId = id => view.nodes.find(n => n.id === id);
    const junction = byId('N35'), branch = byId('N28'), toilet = byId('N5');
    const room = (view.rooms || []).find(r => r.id === 'toilet1');
    if (!junction || !branch || !toilet || !room) return view;
    const oldX = branch.x;
    const dx = junction.x - oldX;
    branch.x += dx; toilet.x += dx; room.x += dx;
    // Existing reference guide belonging to toilet 1 follows its branch.
    for (const guide of view.corridorGuides || []) {
      if (guide.length === 2 && guide.every(p => Math.abs(p.x - oldX) < .1)) {
        guide.forEach(p => { p.x += dx; });
      }
    }
    return view;
  }
  return { project };
}));
