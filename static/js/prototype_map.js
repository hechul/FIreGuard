/* Prototype reference geometry only. Physical location and direction remain unverified. */
(function (root, factory) {
  if (typeof module === 'object' && module.exports) module.exports = factory();
  else root.FireGuardPrototypeMap = factory();
}(typeof globalThis !== 'undefined' ? globalThis : this, function () {
  'use strict';
  const sections = [{"id":"S1","line":[[45,140],[115,140]],"count":4},{"id":"S2","line":[[115,140],[115,567]],"count":32},{"id":"S3","line":[[45,567],[535,567]],"count":30},{"id":"S4","line":[[165,567],[165,645]],"count":4},{"id":"S5","line":[[165.47,567],[165.47,510]],"count":4},{"id":"S6","line":[[265.344,567],[265.344,510]],"count":4},{"id":"S7","line":[[307,567],[307,645]],"count":4},{"id":"S8","line":[[448,567],[448,820]],"count":14},{"id":"S9","line":[[375,567],[375,267]],"count":23},{"id":"S10","line":[[375,410],[435,410]],"count":4},{"id":"S11","line":[[375,362],[317,362]],"count":5},{"id":"S12","line":[[375,315],[477,315]],"count":7},{"id":"S13","line":[[477,315],[477,282]],"count":5},{"id":"S14","line":[[115,267],[385,267]],"count":18},{"id":"S15","line":[[385,267],[385,235]],"count":4}];
  function sharedAnchor(nodes) {
    const a = nodes.find(node => node.id === 'N28');
    const b = nodes.find(node => node.id === 'N35');
    if (!a || !b) return null;
    return {x: (a.x + b.x) / 2, y: (a.y + b.y) / 2};
  }
  return { sections, sharedAnchor };
}));
