const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const source=fs.readFileSync('static/js/physical_sim_control.js','utf8');
class Element {
  constructor(){this.children=[];this.handlers={};this.value='';this.style={};this.textContent='';this.disabled=false;}
  appendChild(c){this.children.push(c);if(!this.value&&c.value)this.value=c.value;}
  addEventListener(k,f){this.handlers[k]=f;}
  setAttribute(k,v){this[k]=v;}
  querySelector(k){return this.elements[k];}
}
async function testInterruption(kind) {
  const elements={};
  for(const id of ['#physicalSimToken','#physicalSimStart','#physicalSimFire','#physicalSimSend','#physicalSimFromScreen','#physicalSimRefresh','#physicalSimStatus','#physicalSimAuto'])elements[id]=new Element();
  const handlers={},events=[]; let resolveFetch;
  const window={addEventListener:(key,fn)=>handlers[key]=fn,dispatchEvent:event=>events.push(event.type)};
  class CustomEvent{constructor(type){this.type=type;}}
  const panel=new Element();panel.elements=elements;
  const document={readyState:'complete',documentElement:{dataset:{physicalSim:'enabled'}},
    querySelector:()=>new Element(),getElementById:id=>id==='simModeBtn'?{classList:{contains:()=>true}}:null,
    createElement:tag=>tag==='details'?panel:new Element()};
  const fetch=()=>new Promise(resolve=>{resolveFetch=resolve;});
  vm.runInNewContext(source,{document,window,CustomEvent,fetch,setTimeout,clearTimeout,JSON,Object,Array,Error});
  const token=elements['#physicalSimToken'],button=elements['#physicalSimAuto'];
  token.value='first'; const pending=button.handlers.click();
  assert.equal(button.disabled,true);
  if(kind==='real')handlers['fireguard:simulation-ended']();
  else {token.value='changed';token.handlers.input();}
  resolveFetch({ok:true,json:async()=>({ok:true,command:null})});
  await pending;
  assert.notEqual(button['aria-pressed'],'true',kind+' must invalidate an in-flight authentication');
  assert.deepEqual(events,[],kind+' must not send a simulation-state request');
}
(async()=>{await testInterruption('real');await testInterruption('token');console.log('PASS: REAL transition and key edits invalidate pending operator authentication');})().catch(e=>{console.error(e);process.exitCode=1;});
