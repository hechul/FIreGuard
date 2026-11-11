'use strict';
const assert = require('node:assert/strict');
const {mount} = require('../static/js/real_fire_control.js');
const handlers = {}, fields = {}, calls = [];
function element() { return {style:{}, hidden:false, disabled:false, value:'', textContent:'',
  append(){}, appendChild(){}, replaceChildren(){}, setAttribute(){},
  addEventListener(name, cb){this[name] = cb;}, querySelectorAll(){return [];}}; }
for (const id of ['realFireOperatorKey','realFireSensorChoices','realFireSubmit','realFireRetry','realFireClearStatus']) fields['#'+id] = element();
fields['#realFireOperatorKey'].value = 'wrong';
const selected = {value:'FLM-01'};
fields['#realFireSensorChoices'].querySelectorAll = () => [selected];
const document = {documentElement:{dataset:{cloud:'true',realClear:'enabled'}},
  getElementById(){return null;}, querySelector(){return element();}, createTextNode(){return {};},
  createElement(){const e=element();e.querySelector=id=>fields[id];return e;}};
const win={addEventListener(name,cb){handlers[name]=cb;}, dispatchEvent(){},
  CustomEvent:class {}, fetch: async () => {calls.push(1);return {ok:false,status:401,json:async()=>({ok:false})};}};
mount(document,win);
handlers['fireguard:real-state']({detail:{viewMode:'real',state:{cloud:{enabled:true,hasTelemetry:true,stale:false,observedAt:'2026-11-10T00:00:00Z'},realFireSensorIds:['FLM-01'],flameSensors:{'FLM-01':{connected:true,active:true}}}}});
(async()=>{await fields['#realFireSubmit'].click();assert.equal(fields['#realFireSubmit'].disabled,false);assert.match(fields['#realFireClearStatus'].textContent,/키가 올바르지/);await fields['#realFireSubmit'].click();assert.equal(calls.length,2);
handlers['fireguard:real-state']({detail:{viewMode:'real',state:{cloud:{enabled:true,hasTelemetry:true,stale:true},realFireSensorIds:['FLM-01'],flameSensors:{'FLM-01':{connected:false,active:true}}}}});
assert.equal(fields['#realFireSubmit'].disabled,true,'offline state cannot request fire clearance');
await fields['#realFireSubmit'].click();assert.equal(calls.length,2,'offline click cannot send a command');
console.log('PASS: operator retry and offline clearance protection');})().catch(e=>{console.error(e);process.exitCode=1;});
