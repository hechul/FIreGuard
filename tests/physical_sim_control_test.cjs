const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
class Element {
  constructor() { this.children=[]; this.handlers={}; this.value=''; this.disabled=false; this.textContent=''; this.style={}; }
  appendChild(child) { this.children.push(child); if (!this.value && child.value) this.value=child.value; }
  addEventListener(type, fn) { this.handlers[type]=fn; }
  setAttribute(name, value) { this[name] = value; }
  querySelector(id) { return elements[id]; }
}
const elements = {};
for (const id of ['#physicalSimToken','#physicalSimStart','#physicalSimFire','#physicalSimSend','#physicalSimFromScreen','#physicalSimRefresh','#physicalSimStatus','#physicalSimAuto']) elements[id]=new Element();
const card = new Element();
let simActive = true;
const simButton = {classList:{contains:()=>simActive}};
const document = {readyState:'complete', documentElement:{dataset:{physicalSim:'enabled'}},
  querySelector:()=>card, getElementById:id=>id==='simModeBtn'?simButton:null,
  createElement:()=>new Element()};
let history='[]';
const sessionStorage = {getItem:()=>history};
let requests=[];
let simulation = {ok:true,state:{operationMode:'simulation',startNode:'N4',blockedNodes:['N10'],blockedEdges:[],manualBlockedEdges:[],edgeWeightOverrides:{},shutters:{},flameSensors:{'FLM-15':{active:true,connected:true}},connections:{pi:true,server:true}},floorplan:{sensors:[{id:'FLM-15',type:'flame',node:'N10'}]}};
const fetch = async (url, options) => { requests.push({url,body:JSON.parse(options.body || '{}')});
  return {ok:true,json:async()=> url==='/api/cloud/simulation'?simulation:{ok:true,command:{status:'pending'}}}; };
vm.runInNewContext(fs.readFileSync('static/js/physical_sim_control.js','utf8'), {document,sessionStorage,fetch,JSON,Object,Array,Error});
elements['#physicalSimToken'].value='test-operator-key';
(async()=>{
  await elements['#physicalSimFromScreen'].handlers.click();
  assert.equal(requests.length,2);
  assert.equal(requests[1].url,'/api/sim-control/commands');
  assert.deepEqual(requests[1].body,{startNode:'N4',fireNodes:['N10']});
  requests=[];
  simulation.floorplan.sensors.push({id:'FLM-14',type:'flame',node:'N7'});
  simulation.state.flameSensors['FLM-14']={active:true,connected:true};
  simulation.state.blockedNodes=['N10','N7'];
  await elements['#physicalSimFromScreen'].handlers.click();
  assert.deepEqual(requests[1].body,{startNode:'N4',fireNodes:['N10','N7']},'all active fire nodes must be sent');
  requests=[];
  elements['#physicalSimStart'].value='N4'; elements['#physicalSimFire'].value='N10';
  await elements['#physicalSimSend'].handlers.click();
  assert.deepEqual(requests[0].body,{startNode:'N4',fireNode:'N10'},'manual single-fire command remains compatible');
  requests=[]; simulation.state.startNode='N40';
  await elements['#physicalSimFromScreen'].handlers.click();
  assert.equal(requests.length,1,'unsupported node must never reach Pi command API');
  simulation.state.startNode='N4'; simulation.state.blockedEdges=['E02']; requests=[];
  await elements['#physicalSimFromScreen'].handlers.click();
  assert.equal(requests.length,1,'unrepresentable edge blocks must never reach Pi command API');
  simActive=false; requests=[];
  await elements['#physicalSimFromScreen'].handlers.click();
  assert.equal(requests.length,0,'REAL mode must never send a simulation');
  console.log('PASS: current SIM selection sends all fires; manual single-fire stays compatible');
})().catch(e=>{console.error(e); process.exitCode=1;});
