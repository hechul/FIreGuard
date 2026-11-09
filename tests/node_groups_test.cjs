const assert = require('node:assert/strict');
const groups = require('../static/js/node_groups.js');
for (const [rep, hidden] of [['N2','N1'],['N29','N8'],['N30','N34'],['N35','N28']]) {
 assert.equal(groups.displayId(rep), rep);
 assert.equal(groups.displayId(hidden), rep);
 assert.deepEqual(groups.members(hidden), [rep,hidden]);
 const state = {blockedNodes:[hidden], startNode:hidden};
 assert.deepEqual(groups.stateFor(rep,state), {blocked:true,start:true});
}
assert.deepEqual(groups.members('N5'),['N5']);
console.log('PASS grouped UI markers preserve hidden fire and origin state');
