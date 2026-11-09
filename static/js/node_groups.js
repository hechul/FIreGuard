/* Display-only groupings. Never modify graph nodes, routes or hardware mappings. */
(function (root, factory) {
  if (typeof module === 'object' && module.exports) module.exports = factory();
  else root.FireGuardNodeGroups = factory();
}(typeof globalThis !== 'undefined' ? globalThis : this, function () {
  'use strict';
  const groups = Object.freeze({N2: ['N2', 'N1'], N29: ['N29', 'N8'], N30: ['N30', 'N34'], N35: ['N35', 'N28']});
  const representative = Object.fromEntries(Object.entries(groups).flatMap(([rep, ids]) => ids.map(id => [id, rep])));
  const members = id => groups[representative[id]] || [id];
  const displayId = id => representative[id] || id;
  const stateFor = (id, state) => {
    const ids = members(id);
    return {blocked: ids.some(n => state.blockedNodes.includes(n)), start: ids.includes(state.startNode)};
  };
  return {groups, members, displayId, stateFor};
}));
