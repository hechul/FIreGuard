'use strict';
const assert = require('node:assert/strict');
const {confirmedByTelemetry, mount} = require('../static/js/real_fire_control.js');
const {describeCompact} = require('../static/js/cloud_hardware.js');
const before = '2026-11-10T05:00:00Z';
const state = {cloud:{enabled:true,hasTelemetry:true,stale:false,observedAt:'2026-11-10T05:00:01Z'},
  flameSensors:{'FLM-01':{active:false,connected:true},'FLM-02':{active:false,connected:true}}};
const ids = ['FLM-01','FLM-02'];
const cmd = {status:'completed',result:{clearedSensorIds:ids,rejectedSensorIds:[]}};
assert.equal(confirmedByTelemetry(state,before,ids,cmd),true);
assert.equal(confirmedByTelemetry({...state,cloud:{...state.cloud,stale:true}},before,ids,cmd),false);
assert.equal(confirmedByTelemetry(state,state.cloud.observedAt,ids,cmd),false);
assert.equal(confirmedByTelemetry(state,before,ids,{...cmd,status:'claimed'}),false);
assert.equal(confirmedByTelemetry(state,before,ids,{...cmd,result:{clearedSensorIds:['FLM-01'],rejectedSensorIds:[]}}),false);
assert.equal(confirmedByTelemetry({...state,flameSensors:{...state.flameSensors,'FLM-02':{active:false,connected:false}}},before,ids,cmd),false);
assert.match(describeCompact({enabled:true,hasTelemetry:true,stale:true,hardware:{ledCommandAck:true}}),/현재 상태 미확인/);
assert.match(describeCompact({enabled:true,hasTelemetry:true,stale:false,hardware:{ledStatus:'active',ledCommandAck:false}}),/응답 미확인/);
assert.match(describeCompact({enabled:true,hasTelemetry:true,stale:false,hardware:{ledStatus:'active',ledCommandAck:true,ledLogicalIndices:[1,2],fireLedLogicalIndices:[3]}}),/경로 2개.*화재 1개.*발광 미확인/);
const events = [], handlers = {};
const element = () => ({style:{}, append(){}, appendChild(){}, setAttribute(){}, addEventListener(){}, querySelectorAll(){return [];}});
const fields = Object.fromEntries(['#realFireOperatorKey','#realFireSensorChoices','#realFireSubmit','#realFireRetry','#realFireClearStatus'].map(id=>[id,element()]));
const document = {documentElement:{dataset:{cloud:'true'}}, getElementById(){return null;},
  querySelector(){return element();}, createElement(){const e=element();e.querySelector=id=>fields[id];return e;}};
const win = {addEventListener(name, cb){handlers[name]=cb;}, dispatchEvent(e){events.push(e.type);},
  CustomEvent:class {constructor(type){this.type=type;}}};
mount(document,win);
assert.equal(typeof handlers['fireguard:real-state'],'function');
assert.deepEqual(events,['fireguard:request-real-state']);
console.log('PASS: real clear needs matching Pi acknowledgement and newer fresh telemetry; LED reports distinguish acknowledgement');
