const assert = require('node:assert/strict');
const {chromium} = require(process.env.PLAYWRIGHT_MODULE || 'playwright');
(async () => {
  const browser = await chromium.launch({channel:'msedge', headless:true});
  try {
    const page = await browser.newPage({baseURL:'http://127.0.0.1:5051', viewport:{width:1600,height:1100}});
    const errors = [];
    page.on('pageerror', e => errors.push(e.message));
    await page.goto('/');
    await page.locator('#edgeLayer polyline').first().waitFor();
    const floor = await page.request.get('/api/floorplan').then(r=>r.json());
    assert.equal(await page.locator('#edgeLayer polyline').count(),floor.edges.length);
    assert.equal(await page.locator('#mapStage .door-threshold').count(),11);
    await page.request.post('/api/simulation/start-node',{data:{nodeId:'N36'}});
    await page.waitForFunction(() => document.querySelector('#startNodeLabel').textContent.includes('N36'));
    const paths = await page.locator('#routeLayer polyline').evaluateAll(elements => elements.map(e=>({id:e.dataset.edgeId,points:e.getAttribute('points')})));
    assert(paths.length > 0);
    for (const path of paths) assert.equal(path.points, await page.locator(`#edgeLayer [data-edge-id="${path.id}"]`).getAttribute('points'));
    await page.locator('#mapStage').screenshot({path:'tmp/pdfs/dashboard-doors.png'});
    await page.locator('[data-page="mapEditor"]').click();
    await page.locator('#editorEdgeLayer polyline').first().waitFor();
    for (const edge of floor.edges) assert.equal(
      await page.locator(`#editorEdgeLayer [data-edge-id="${edge.id}"]`).getAttribute('points'),
      await page.locator(`#edgeLayer [data-edge-id="${edge.id}"]`).getAttribute('points'));
    // Reproduce the screenshot: N37 moved to the left inside Cinema 5.
    await page.locator('#editorNodeLayer [data-node-id="N37"] circle').click();
    await page.locator('#editorXInput').fill('180');
    await page.locator('#editorYInput').fill('150');
    await page.locator('#editorApplyCoordBtn').click();
    const room = floor.rooms.find(r=>r.id==='cinema5');
    let stem;
    for (const edge of floor.edges.filter(e=>e.from==='N37'||e.to==='N37')) {
      const text = await page.locator(`#editorEdgeLayer [data-edge-id="${edge.id}"]`).getAttribute('points');
      const path = text.split(' ').map(p=>p.split(',').map(Number));
      if (edge.to==='N37') path.reverse();
      assert.deepEqual(path[0],[180,150]);
      const firstOutside = path.findIndex(([x,y])=>x<room.x||x>room.x+room.width||y<room.y||y>room.y+room.height);
      assert(firstOutside>0);
      const prefix = path.slice(0,firstOutside+1);
      if (!stem) stem=prefix;
      else assert.deepEqual(prefix,stem,'Cinema 5 must branch only outside the door');
    }
    await page.locator('#mapEditorStage').screenshot({path:'tmp/pdfs/editor-doors.png'});
    assert.deepEqual(errors,[]);
    console.log('PASS: shared geometry in all views; off-centre N37 branches only outside Cinema 5');
  } finally {await browser.close();}
})().catch(e=>{console.error(e);process.exit(1);});
