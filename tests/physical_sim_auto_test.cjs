const assert = require('node:assert/strict');
const fs = require('node:fs'), vm = require('node:vm');
class Element {
  constructor(){this.children=[];this.handlers={};this.value='';this.style={};this.textContent='';this.disabled=false;}
  appendChild(c){this.children.push(c);if(!this.value&&c.value)this.value=c.value;}
  addEventListener(k,f){this.handlers[k]=f;}
  setAttribute(k,v){this[k]=v;}
  querySelector(k){return elements[k];}
}
const elements={};
for(const id of ['#physicalSimToken','#physicalSimStart','#physicalSimFire','#physicalSimSend','#physicalSimFromScreen','#physicalSimRefresh','#physicalSimStatus','#physicalSimAuto'])elements[id]=new Element();
const handlers={}, timers=new Map();let timerId=0, requests=[], rejectAuth=false;
const window={addEventListener:(key,fn)=>handlers[key]=fn,
  dispatchEvent:event=>{if(event.type==='fireguard:request-simulation-state')send();}};
class CustomEvent { constructor(type,options={}) {this.type=type;this.detail=options.detail;} }
const document={readyState:'complete',documentElement:{dataset:{physicalSim:'enabled'}},querySelector:()=>new Element(),getElementById:id=>id==='simModeBtn'?{classList:{contains:()=>true}}:null,createElement:()=>new Element()};
const fetch=async(url,options)=>{requests.push({url,body:JSON.parse(options.body||'{}')});
 if(url==='/api/sim-control/latest' && rejectAuth)return {ok:false,status:401,json:async()=>({ok:false,error:'시험 연결 인증이 필요합니다.'})};
 return {ok:true,json:async()=>({ok:true,command:{id:'cmd1',status:'pending'}})}};
const setTimeout=(fn,delay)=>{let id=++timerId;timers.set(id,{fn,delay});return id;};
const clearTimeout=id=>timers.delete(id);
vm.runInNewContext(fs.readFileSync('static/js/physical_sim_control.js','utf8'),{document,window,CustomEvent,sessionStorage:{getItem:()=>null},fetch,setTimeout,clearTimeout,JSON,Object,Array,Error});
const state={operationMode:'simulation',startNode:'N4',blockedNodes:['N10'],blockedEdges:[],manualBlockedEdges:[],edgeWeightOverrides:{},shutters:{},flameSensors:{'FLM-15':{active:true,connected:true}},connections:{pi:true,server:true}};
const floorplan={sensors:[{id:'FLM-15',type:'flame',node:'N10'}]};
const send=()=>handlers['fireguard:simulation-action']({detail:{state,floorplan}});
const tick=async(delay)=>{const t=[...timers].find(([,v])=>v.delay===delay); assert(t,'timer missing');timers.delete(t[0]);t[1].fn();for(let i=0;i<10;i++)await Promise.resolve();};
(async()=>{
 send(); assert.equal(timers.size,0,'must not arm automatically');
 elements['#physicalSimToken'].value='test-token';rejectAuth=true;
 await elements['#physicalSimAuto'].handlers.click();
 assert.notEqual(elements['#physicalSimAuto']['aria-pressed'],'true','invalid token must not arm');
 assert.match(elements['#physicalSimStatus'].textContent,/인증이 필요/);
 assert.equal(timers.size,0,'invalid token must not trigger any command');
 rejectAuth=false; requests=[];
 await elements['#physicalSimAuto'].handlers.click();
 assert.equal(requests[0].url,'/api/sim-control/latest','auth must be checked before arming');
 assert.equal(elements['#physicalSimAuto']['aria-pressed'],'true');
 await tick(500);
 assert.equal(requests[1].url,'/api/sim-control/commands');assert.deepEqual(requests[1].body,{startNode:'N4',fireNode:'N10'});
 state.flameSensors['FLM-15'].active=false; state.blockedNodes=[]; send();
 for(let i=0;i<10;i++)await Promise.resolve();
 assert.equal(requests[2].url,'/api/sim-control/cancel');assert.deepEqual(requests[2].body,{id:'cmd1'});
 handlers['fireguard:simulation-ended']();
 assert.equal(elements['#physicalSimAuto']['aria-pressed'],'false');
 console.log('PASS: automatic LED commands require arming and fire clearing cancels prior request');
})().catch(e=>{console.error(e);process.exitCode=1});
