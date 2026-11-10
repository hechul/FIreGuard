/* Presentation-only geometry: graph IDs, costs and Pi mappings remain unchanged. */
(function (root, factory) {
  if (typeof module === 'object' && module.exports) module.exports = factory();
  else root.FireGuardPrototypeProjection = factory();
}(typeof globalThis !== 'undefined' ? globalThis : this, function () {
  'use strict';
  function project(floorplan) {
    const view = JSON.parse(JSON.stringify(floorplan));
    const byId = id => view.nodes.find(n => n.id === id);
    // Align the shop's interior node and entrance with the room's visual centre.
    const shop = (view.rooms || []).find(r => r.id === 'shop');
    const shopEntrance = byId('N25'), shopInterior = byId('N39');
    if (shop && shopEntrance && shopInterior) {
      shopEntrance.x = shopInterior.x = shop.x + shop.width / 2;
    }
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
    // The photographed prototype places the two toilets next to each other.
    // Shift the second room and its branch as a single presentation group;
    // keep all graph IDs, edge weights and device mapping untouched.
    const room2 = (view.rooms || []).find(r => r.id === 'toilet2');
    const toilet2 = byId('N6'), branch2 = byId('N29');
    if (room2 && toilet2 && branch2) {
      const oldBranchX = branch2.x;
      const shift = room.x + room.width + 22 - room2.x;
      room2.x += shift; toilet2.x += shift; branch2.x += shift;
      for (const guide of view.corridorGuides || []) {
        if (guide.length === 2 && guide.every(p => Math.abs(p.x - oldBranchX) < .1)) {
          guide.forEach(p => { p.x += shift; });
        }
      }
    }
    return view;
  }
  return { project };
}));
