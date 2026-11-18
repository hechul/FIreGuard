'use strict';
const assert = require('node:assert/strict');
const {project, projectFor3d, coordinates, allZoneSummary, markConnectionUnknown} = require('../static/js/real_led_projection.js');
const {sections} = require('../static/js/prototype_map.js');
const coords = coordinates(sections);
assert.equal(coords.length, 162);
// S2 is bottom-to-top and S3 right-to-left despite drawing order.
assert(coords[4].y > coords[35].y);
assert(coords[36].x > coords[65].x);
const h = {operationMode:'real', ledStatus:'active', ledCommandAck:true,
 ledMappingVersion:'led162-usb163-shift20-da2de217fd',
 ledLogicalIndices:[0,20,61], ledIndices:[0,21,62],
 fireLedLogicalIndices:[61,80], fireLedIndices:[62,81]};
const cloud = {enabled:true,hasTelemetry:true,stale:false,routeSource:'pi',hardware:h};
const result = project(cloud,sections);
const room5 = project({...cloud, hardware:{...h, ledMappingVersion:'led162-usb163-shift20-ca3ff6b9c6',
 ledLogicalIndices:[158,161],ledIndices:[159,162],fireLedLogicalIndices:[],fireLedIndices:[]}}, sections);
assert.equal(room5.points[0].x,240);
assert(room5.points[0].y > room5.points[1].y, '159 is corridor side, 162 inside room 5');
const s2mapping = project({...cloud,hardware:{...h,ledMappingVersion:'led162-usb163-shift20-4a635eec44',
 ledLogicalIndices:[4,5,6,7,158,161],ledIndices:[4,5,6,7,159,162],fireLedLogicalIndices:[],fireLedIndices:[]}},sections);
assert.equal(s2mapping.points.length,6);
assert.equal(s2mapping.points[4].x,240,'new mapping retains room 5 location');
assert(s2mapping.points[0].y > s2mapping.points[3].y,'S2 points toward lower end');
const floor = require('../static/data/floorplan.json');
assert.equal(floor.exits.filter(e=>e.id==='EXIT_S2').length,1);
assert.deepEqual(floor.edges.find(e=>e.id==='E39'),{id:'E39',from:'N7',to:'EXIT_S2',weight:0.5});
const liveState = {cloud, connections:{pi:true,server:true}, flameSensors:{'FLM-01':{active:true,connected:true}}, sensorCounts:{offline:0}, equipment:[{id:'FLM-01',status:'danger'}]};
const unavailable = markConnectionUnknown(liveState);
assert.equal(unavailable.cloud.stale,true);
assert.equal(unavailable.connections.pi,false);
assert.equal(unavailable.flameSensors['FLM-01'].active,true,'disconnect retains reported fire');
assert.equal(unavailable.flameSensors['FLM-01'].connected,false);
assert.equal(unavailable.equipment[0].status,'offline');
assert.equal(project(unavailable.cloud,sections),null,'do not show LED commands as current after browser disconnect');
assert.equal(liveState.cloud.stale,false,'do not mutate the original report');
assert.deepEqual(projectFor3d({operationMode:'real',cloud},sections),result);
assert.equal(projectFor3d({operationMode:'simulation',cloud},sections),null);
assert.equal(projectFor3d({operationMode:'real',cloud:{...cloud,stale:true}},sections),null);
assert.match(result.label,/추정.*발광 미확인/);
assert.deepEqual(result.points.map(p=>[p.index,p.color]),[[0,'route'],[20,'route'],[61,'fire'],[80,'fire']]);
assert.equal(project({...cloud,stale:true},sections),null);
assert.equal(project({...cloud,routeSource:'server_preview'},sections),null);
assert.equal(project({...cloud,hardware:{...h,ledCommandAck:false}},sections),null);
assert.equal(project({...cloud,hardware:{...h,ledStatus:'off'}},sections),null);
assert.equal(project({...cloud,hardware:{...h,operationMode:'simulation'}},sections),null);
assert.equal(project({...cloud,hardware:{...h,ledMappingVersion:'unknown'}},sections),null);
assert.equal(project({...cloud,hardware:{...h,ledIndices:[0,20,62]}},sections),null);
assert.equal(project({...cloud,hardware:{...h,ledLogicalIndices:[999],ledIndices:[1000]}},sections),null);
assert.equal(project(cloud,sections.slice(0,-1)),null);
const forest = {routingMode:'all_zones_to_exits', routeStatus:'partial',
 availableExits:['EXIT_NW'], guidedNodes:['N4','N27'], unreachableNodes:['N12'],
 directedEdges:[{edgeId:'E26',from:'N4',to:'N27',exitNode:'EXIT_NW'}], ledExcludedEdges:['E02']};
const whole = {...cloud,hardware:{...h,allZone:forest}};
const view = allZoneSummary(whole);
assert.deepEqual(view.fallbackDestinations, [], 'legacy all-zone reports remain compatible');
assert.deepEqual(allZoneSummary({...whole,hardware:{...h,allZone:{...forest,fallbackDestinations:['N5']}}}).fallbackDestinations, ['N5']);
assert.equal(allZoneSummary({...whole,hardware:{...h,allZone:{...forest,fallbackDestinations:[42]}}}), null);
assert.equal(view.status,'일부 구역 경로 없음');
assert.equal(view.guidedCount,2);
assert.equal(view.unreachableCount,1);
assert.deepEqual(view.directedEdges,forest.directedEdges);
const coverage = [{edgeId:'E01',from:'N23',to:'N20',exitNode:'EXIT_NW'}];
const extended = {...whole,hardware:{...h,allZone:{...forest,coverageEdges:coverage}}};
assert.deepEqual(allZoneSummary(extended).directedEdges,[...forest.directedEdges,...coverage]);
assert.deepEqual(allZoneSummary({...extended,stale:true}).directedEdges,[]);
assert.equal(allZoneSummary({...extended,hardware:{...h,allZone:{...forest,coverageEdges:'invalid'}}}),null);
const partial = {...whole,hardware:{...h,allZone:{...forest,partialEdges:[{
 edgeId:'E10',towardNode:'N3',exitNode:'EXIT_NW',ledLogicalIndices:Array.from({length:12},(_,i)=>i+10)}]}}};
assert.equal(allZoneSummary(partial).partialGuidanceCount,1);
assert.deepEqual(allZoneSummary(partial).directedEdges,forest.directedEdges,'no full E10 arrow across fire');
assert.equal(allZoneSummary({...partial,stale:true}).partialGuidanceCount,0);
assert.equal(allZoneSummary({...partial,hardware:{...h,allZone:{...forest,partialEdges:[{}]}}}),null);
assert.equal(view.ledAcknowledged,true);
assert.match(view.label,/계산 경로.*별도 확인/);
assert.match(project(whole,sections).label,/전체 구역.*발광 미확인/);
const unacknowledged = allZoneSummary({...whole,hardware:{...h,allZone:forest,ledCommandAck:false}});
assert.equal(unacknowledged.ledAcknowledged,false);
assert.equal(unacknowledged.directedEdges.length,1,'계산 경로는 LED ACK와 독립적');
const staleView = allZoneSummary({...whole,stale:true});
assert.match(staleView.status,/현재 미확인/);
assert.equal(staleView.directedEdges.length,0,'오래된 경로를 현재 경로로 그리지 않음');
const unverifiedView = allZoneSummary({...whole,routeSource:'pi_unverified'});
assert.match(unverifiedView.status,/확인 필요/);
assert.equal(unverifiedView.directedEdges.length,0,'미검증 Pi 경로는 그리지 않음');
assert.equal(unverifiedView.ledAcknowledged,false);
assert.equal(allZoneSummary({...whole,routeSource:'server_preview'}),null);
assert.equal(allZoneSummary({...whole,hardware:{...h,operationMode:'simulation',allZone:forest}}),null);
assert.equal(allZoneSummary({...whole,hardware:{...h,allZone:{...forest,directedEdges:[{edgeId:'E1',from:'N1',to:'N1',exitNode:'EXIT_NW'}]}}}),null);
console.log('PASS: projected LED commands require fresh REAL acknowledgement and known mapping');
