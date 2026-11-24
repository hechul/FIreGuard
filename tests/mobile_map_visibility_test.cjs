// Exercise the actual browser controller with failed/stale/live fetch results.
const assert=require('node:assert/strict'),fs=require('fs'),vm=require('vm');
const floor=require('../static/data/floorplan.json');
class Element {
 constructor(){this.children=[];this.attrs={};this.dataset={};this.textContent='';this.hidden=false;this.disabled=false;}
 append(...items){this.children.push(...items)} appendChild(item){this.children.push(item)}
 replaceChildren(...items){this.children=items} setAttribute(k,v){this.attrs[k]=v}
 hasAttribute(k){return Object.hasOwn(this.attrs,k)}
 removeAttribute(k){delete this.attrs[k]}
 toggleAttribute(k,force){const present=force===undefined?!this.hasAttribute(k):Boolean(force);if(present)this.setAttribute(k,'');else this.removeAttribute(k);return present;}
 addEventListener(){}
}
async function check(mode){
 const elements=new Map();const get=id=>{if(!elements.has(id))elements.set(id,new Element());return elements.get(id)};
 // SVGElement has no HTMLElement.hidden reflection. Assigning .hidden=false
 // leaves the actual attribute (and the CSS [hidden] rule) untouched.
 get('map').setAttribute('hidden','');
 get('referenceFloorplan').textContent=JSON.stringify(floor);
 const state={cloud:{enabled:true,hasTelemetry:true,stale:mode==='stale'},flameSensors:{},blockedNodes:[],route:{nodes:['N37','N1'],edges:['E25']}};
 const listeners={};
 const context={document:{hidden:false,body:{dataset:{node:'N37',location:'5관'}},getElementById:get,
   createElementNS:()=>new Element(),createElement:()=>new Element(),addEventListener(){}},
  navigator:{onLine:true},AbortController,Date,JSON,Promise,Map,Set,setTimeout,clearTimeout,setInterval(){},
  fetch:async url=>{if(mode==='failed'||(mode==='state-failed'&&url.includes('/api/state')))throw Error('offline');
    return {ok:true,json:async()=>url.includes('/api/state')?state:floor}},
  window:{FireGuardPrototypeProjection:require('../static/js/prototype_projection.js'),
    FireGuardRealLedProjection:require('../static/js/real_led_projection.js'),
    FireGuardMobileGuidance:require('../static/js/mobile_guidance.js'),addEventListener:(e,fn)=>listeners[e]=fn}};
 vm.runInNewContext(fs.readFileSync(require.resolve('../static/js/mobile.js'),'utf8'),context);
 await new Promise(resolve=>setImmediate(resolve));
 assert.equal(get('map').hasAttribute('hidden'),false,mode+': SVG hidden attribute must be removed');
 assert(get('map').children.some(c=>c.textContent==='현재 위치'));
 const arrows=()=>get('map').children.filter(c=>c.attrs['marker-end']).length;
 if(mode==='live'){
  assert.equal(arrows(),1);
  listeners.offline();
  assert.equal(get('map').hasAttribute('hidden'),false);assert.equal(arrows(),0,'old guidance removed on disconnect');
 }else{
  assert.equal(arrows(),0);assert.equal(get('steps').children.length,0);
  assert.equal(get('mapEmpty').hidden,false);
 }
}
(async()=>{for(const mode of ['failed','state-failed','stale','live'])await check(mode);
 console.log('PASS: full map survives API failure, stale telemetry and disconnect; obsolete arrows removed');
})().catch(e=>{console.error(e);process.exit(1)});
