'use strict';
const assert = require('node:assert/strict');
const {select} = require('../static/js/mobile_guidance.js');
const floor = {nodes:[{id:'A'},{id:'B'},{id:'C'},{id:'T'}],exits:[{id:'EXIT'}],edges:[
  {id:'AB',from:'A',to:'B'},{id:'BE',from:'B',to:'EXIT'},{id:'BT',from:'B',to:'T'}]};
const plan = {routingMode:'all_zones_to_exits',availableExits:['EXIT'],fallbackDestinations:[],
  directedEdges:[{edgeId:'AB',from:'A',to:'B',exitNode:'EXIT'},
                 {edgeId:'BE',from:'B',to:'EXIT',exitNode:'EXIT'}],ledExcludedEdges:[]};
const state = {realFireDetected:true,blockedNodes:['C'],blockedEdges:[],flameSensors:{one:{connected:true}},
  cloud:{enabled:true,hasTelemetry:true,stale:false,hardware:{operationMode:'real',allZone:plan}},
  route:{nodes:['A','C','EXIT'],edges:['wrong']}};
const clone = () => structuredClone(state);
assert.deepEqual(select(state,floor,'A').nodes,['A','B','EXIT'], 'Must use Pi plan, not server preview');
assert.deepEqual(select(state,floor,'B').nodes,['B','EXIT'], 'Independent QR start');
assert.equal(select(state,floor,'C').status,'no_route');
assert.equal(select(state,floor,'T').status,'no_route');
assert.equal(select(state,floor,'BAD').status,'unknown');
for (const change of [s=>s.cloud.stale=true,s=>s.cloud.hasTelemetry=false,
    s=>s.flameSensors.one.connected=false,s=>delete s.cloud.hardware.allZone,
    s=>s.blockedNodes.push('B'),s=>s.blockedEdges.push('AB'),
    s=>s.cloud.hardware.allZone.ledExcludedEdges.push('BE')]) {
  const s=clone();change(s);assert.equal(select(s,floor,'A').status,'unknown');
  assert.deepEqual(select(s,floor,'A').nodes,[]);
}
const fallback=clone();
fallback.cloud.hardware.allZone.availableExits=[];
fallback.cloud.hardware.allZone.fallbackDestinations=['T'];
fallback.cloud.hardware.allZone.directedEdges[1]={edgeId:'BT',from:'B',to:'T',exitNode:'T'};
assert.equal(select(fallback,floor,'A').status,'fallback');
assert.deepEqual(select(fallback,floor,'A').nodes,['A','B','T']);
const cycle=clone(); cycle.cloud.hardware.allZone.directedEdges[1]={edgeId:'AB',from:'B',to:'A',exitNode:'EXIT'};
assert.equal(select(cycle,floor,'A').status,'unknown');
const normal=clone();normal.realFireDetected=false;normal.route={nodes:['A','B','EXIT'],edges:['AB','BE']};
assert.equal(select(normal,floor,'A').status,'normal');
delete normal.cloud;assert.equal(select(normal,floor,'A').status,'simulation');
assert.deepEqual(state.route.nodes,['A','C','EXIT'], 'Read-only route selection');
console.log('PASS: mobile QR routes, Pi precedence, multiple starts, blocked/stale/offline/fallback states');
