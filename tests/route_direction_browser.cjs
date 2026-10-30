const assert = require('node:assert/strict');
const {chromium} = require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const base = process.env.FIREGUARD_TEST_URL || 'http://127.0.0.1:5054';
(async () => {
  const browser = await chromium.launch({channel:'msedge',headless:true});
  try {
    const page = await browser.newPage({viewport:{width:1600,height:1100}});
    const errors=[]; page.on('pageerror',e=>errors.push(e.message));
    await page.goto(base);
    await page.locator('#flameCount').waitFor();
    const floor=await page.request.get(base+'/api/floorplan').then(r=>r.json());
    const nodes=Object.fromEntries([...floor.nodes,...floor.exits].map(n=>[n.id,n]));
    let forward=0,backward=0;
    async function post(path,data) {
      const r=await page.request.post(base+path,{data}); assert.equal(r.status(),200);
      return (await r.json()).state;
    }
    async function verify(state) {
      const route=state.route; assert(route);
      await page.waitForFunction(route => {
        const lines=[...document.querySelectorAll('#routeLayer polyline')];
        return lines.length===route.edges.length && lines.every((line,i)=>
          line.dataset.edgeId===route.edges[i] && line.dataset.fromNode===route.nodes[i] && line.dataset.toNode===route.nodes[i+1]);
      },route);
      for(let i=0;i<route.edges.length;i++) {
        const edge=floor.edges.find(e=>e.id===route.edges[i]);
        const canonical=await page.locator(`#edgeLayer [data-edge-id="${edge.id}"]`).getAttribute('points');
        const actual=await page.locator(`#routeLayer [data-edge-id="${edge.id}"]`).getAttribute('points');
        const reverse=edge.from!==route.nodes[i];
        reverse ? backward++ : forward++;
        assert.equal(actual, reverse ? canonical.split(' ').reverse().join(' ') : canonical);
        const coords=actual.split(' ').map(p=>p.split(',').map(Number));
        for(const [p,id] of [[coords[0],route.nodes[i]],[coords.at(-1),route.nodes[i+1]]]) {
          assert(Math.hypot(p[0]-nodes[id].x,p[1]-nodes[id].y)<.02,`Route endpoint ${id}`);
        }
      }
      const phase=await page.locator('#routeLayer polyline').evaluateAll(lines=>lines.map(line=>({
        length:line.getTotalLength(),offset:parseFloat(getComputedStyle(line).strokeDashoffset),
        animation:getComputedStyle(line).animationName,
      })));
      for(let i=0;i<phase.length;i++) {
        assert.equal(phase[i].animation,'routeFlow');
        if(i) {
          const diff=phase[i-1].offset+phase[i-1].length-phase[i].offset;
          assert(Math.abs(diff-Math.round(diff/21)*21)<.3,'Dash flow must continue across junctions');
        }
      }
    }
    await post('/api/mode',{mode:'simulation'});
    await post('/api/simulation/reset',{});
    for(const start of ['N10','N7','N20','N11','N36','N33']) {
      await verify(await post('/api/simulation/start-node',{nodeId:start}));
    }
    await verify(await post('/api/simulation/scenario',{scenarioId:'east_exit_fire'}));
    await verify(await post('/api/simulation/scenario',{scenarioId:'fallback_toilet'}));
    assert(forward>0 && backward>0,'Must cover both stored edge directions');
    // Repeated state redraws must retain a progressing, rather than restarting, phase.
    const before=await page.locator('#routeLayer polyline').first().evaluate(e=>parseFloat(getComputedStyle(e).strokeDashoffset));
    await page.waitForTimeout(200);
    const state=await post('/api/simulation/start-node',{nodeId:'N33'});
    await verify(state);
    const after=await page.locator('#routeLayer polyline').first().evaluate(e=>parseFloat(getComputedStyle(e).strokeDashoffset));
    assert.notEqual(before,after);
    await page.screenshot({path:process.env.FIREGUARD_TEST_SCREENSHOT || 'tmp/route-direction.png'});
    assert.deepEqual(errors.filter(e=>e!=='THREE is not defined'),[]);
    console.log(`PASS: directed evacuation routes, unchanged corridor geometry, continuous dash phase (${forward} forward, ${backward} reversed edges)`);
  }finally {await browser.close()}
})().catch(e=>{console.error(e);process.exit(1)});
