const fs = require('fs'), vm = require('vm'), assert=require('node:assert/strict');
function init(width, denied=false){
 const media={}; const listeners=(e)=>{e.listeners={};e.addEventListener=(name,f)=>(e.listeners[name] ||= []).push(f);e.emit=(name,arg={})=>(e.listeners[name]||[]).forEach(f=>f(arg));return e;};
 const node=()=>{let attrs={},classes=new Set();let e=listeners({dataset:{},children:[],classList:{toggle(k,v){v?classes.add(k):classes.delete(k)},contains:k=>classes.has(k)},setAttribute(k,v){attrs[k]=v},getAttribute:k=>attrs[k],insertBefore(c,b){this.children.push(c)},appendChild(c){this.children.push(c)},focus(){this.focused=true},querySelector(){return null}});return e;};
 const side=node(),title=node(),body=node(),nav=node(),navItem=node(),label=node();label.childNodes=[{textContent:'대시보드'}];navItem.querySelector=()=>label;side.querySelector=(s)=>s==='.nav-list'?nav:null;side.querySelectorAll=()=>[navItem];
 const d=listeners({readyState:'complete',body,createElement:node,querySelector:s=>s==='.sidebar'?side:s==='.topbar-title'?title:null});
 let storage={};let ls={getItem:k=>{if(denied)throw Error('denied');return storage[k]??null},setItem:(k,v)=>{if(denied)throw Error('denied');storage[k]=v}};
 let win={matchMedia:s=>media[s] ||= listeners({matches:width<=Number(s.match(/\d+/)[0])}),dispatchEvent:()=>{}};
 vm.runInNewContext(fs.readFileSync('static/js/sidebar.js','utf8'),{document:d,window:win,localStorage:ls,Event:class{}});
 return {side,title,body,nav,navItem,desktop:side.children[0],group:side.children[1],mobile:title.children[0],backdrop:body.children[0],d,storage};
}
let a=init(1400);assert.equal(a.desktop.getAttribute('aria-expanded'),'true');a.desktop.emit('click');assert(a.body.classList.contains('sidebar-collapsed'));assert.equal(a.desktop.getAttribute('aria-expanded'),'false');assert.equal(a.storage['fireguard-sidebar-collapsed'],'true');assert.equal(a.navItem.getAttribute('aria-label'),'대시보드');a.desktop.emit('click');assert(!a.body.classList.contains('sidebar-collapsed'));
assert.equal(a.group.getAttribute('aria-expanded'),'true');a.group.emit('click');assert.equal(a.nav.hidden,true);assert.equal(a.group.getAttribute('aria-expanded'),'false');a.desktop.emit('click');assert.equal(a.group.hidden,true);assert.equal(a.nav.hidden,false);a.desktop.emit('click');assert.equal(a.nav.hidden,true);assert.equal(a.group.getAttribute('aria-expanded'),'false');a.group.emit('click');assert.equal(a.nav.hidden,false);
let b=init(500,true);assert.equal(b.side.getAttribute('aria-hidden'),'true');b.mobile.emit('click');assert(b.body.classList.contains('sidebar-mobile-open'));assert.equal(b.mobile.getAttribute('aria-expanded'),'true');b.d.emit('keydown',{key:'Escape'});assert(!b.body.classList.contains('sidebar-mobile-open'));assert.equal(b.mobile.focused,true);b.mobile.emit('click');b.navItem.emit('click');assert(!b.body.classList.contains('sidebar-mobile-open'));
let c=init(900);assert(c.body.classList.contains('sidebar-collapsed'));c.desktop.emit('click');assert(!c.body.classList.contains('sidebar-collapsed'));
console.log('PASS: sidebar and menu group toggles, compact icons, mobile navigation, denied storage');
