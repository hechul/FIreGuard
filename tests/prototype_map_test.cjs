const assert = require('node:assert/strict');
const ref = require('../static/js/prototype_map.js');
assert.equal(ref.sections.length, 15);
assert.equal(ref.sections.reduce((n, s) => n + s.count, 0), 162);
assert.deepEqual(ref.sections.find(s => s.id === 'S3').line, [[45, 567], [535, 567]]);
assert.deepEqual(ref.sharedAnchor([{id:'N28',x:214,y:567},{id:'N35',x:165,y:567}]), {x:189.5,y:567});
assert.equal(ref.sharedAnchor([{id:'N28',x:214,y:567}]), null);
console.log('prototype reference overlay tests passed');
