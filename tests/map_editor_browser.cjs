// Run against an isolated test server; this test saves a node and an edge.
const assert = require('node:assert/strict');
const {chromium} = require(process.env.PLAYWRIGHT_MODULE || 'playwright');

(async () => {
  const browser = await chromium.launch({channel: 'msedge', headless: true});
  try {
    const page = await browser.newPage({baseURL: process.env.FIREGUARD_TEST_URL || 'http://127.0.0.1:5051', viewport: {width: 1440, height: 1000}});
    const errors = [];
    page.on('pageerror', error => errors.push(error.message));
    await page.goto(process.env.FIREGUARD_TEST_URL || 'http://127.0.0.1:5051');
    await page.locator('#nodeLayer circle').first().waitFor();
    const original = await page.request.get('/api/floorplan').then(r => r.json());
    let nodeNumber = 1, edgeNumber = 1;
    while (original.nodes.some(n => n.id === `N${nodeNumber}`)) nodeNumber++;
    while (original.edges.some(e => e.id === `E${String(edgeNumber).padStart(2,'0')}`)) edgeNumber++;
    const addedNode = `#editorNodeLayer [data-node-id="N${nodeNumber}"]`;
    const addedEdge = `#editorEdgeLayer [data-edge-id="E${String(edgeNumber).padStart(2,'0')}"]`;
    const originalNode = page.locator('#nodeLayer circle').first();
    const box = await originalNode.boundingBox();
    await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2);
    await page.mouse.down();
    await page.mouse.move(box.x + 50, box.y + 40, {steps: 6});
    await page.mouse.up();
    assert.deepEqual(await page.request.get('/api/floorplan').then(r => r.json()), original);
    await page.locator('[data-page="mapEditor"]').click();
    const node = page.locator('#editorNodeLayer [data-node-id="N1"] circle');
    await node.waitFor();
    await page.locator('#editorSnapToggle').uncheck();
    const point = (x, y) => page.locator('#mapEditorSvg').evaluate((svg, p) => {
      const pt = svg.createSVGPoint(); pt.x = p.x; pt.y = p.y;
      const screen = pt.matrixTransform(svg.getScreenCTM());
      return {x: screen.x, y: screen.y};
    }, {x, y});
    const start = await point(original.nodes[0].x, original.nodes[0].y);
    const end = await point(410, 490);
    await page.mouse.move(start.x, start.y);
    await page.mouse.down();
    await page.mouse.move(end.x, end.y, {steps: 8});
    await page.mouse.up();
    assert.equal(Number(await node.getAttribute('cx')), 410);
    assert.equal(Number(await node.getAttribute('cy')), 490);
    assert.equal(await page.locator('#editorDirtyBadge').textContent(), '저장 전');
    await page.locator('[data-page="overview"]').click();
    await page.locator('[data-page="mapEditor"]').click();
    assert.equal(Number(await node.getAttribute('cx')), 410);
    await page.locator('#editorAddNodeBtn').click();
    const add = await point(470, 540);
    await page.mouse.click(add.x, add.y);
    await page.locator(addedNode).waitFor();
    await page.locator('#editorUndoBtn').click();
    assert.equal(await page.locator(addedNode).count(), 0);
    await page.mouse.click(add.x, add.y);
    await page.locator('#editorConnectBtn').click();
    await page.locator(`${addedNode} circle`).click();
    await page.locator('#editorNodeLayer [data-node-id="N1"] circle').click();
    assert.equal(await page.locator(addedEdge).count(), 1);
    await page.locator('#editorSaveBtn').click();
    await page.waitForFunction(() => document.querySelector('#editorDirtyBadge').textContent === '저장됨');
    const saved = await page.request.get('/api/floorplan').then(r => r.json());
    assert.equal(saved.nodes.length, original.nodes.length + 1);
    assert.equal(saved.edges.length, original.edges.length + 1);
    assert.equal(saved.nodes[0].x, 410);
    await page.reload();
    await page.locator('[data-page="mapEditor"]').click();
    await page.locator(addedNode).waitFor();
    // A narrow layout uses a different SVG scale and letterboxing.
    await page.setViewportSize({width: 800, height: 900});
    await page.locator('#mapEditorSvg').scrollIntoViewIfNeeded();
    const narrowStart = await point(410, 490);
    const narrowEnd = await point(430, 510);
    await page.mouse.move(narrowStart.x, narrowStart.y);
    await page.mouse.down();
    await page.mouse.move(narrowEnd.x, narrowEnd.y, {steps: 8});
    await page.mouse.up();
    assert.equal(Number(await node.getAttribute('cx')), 430);
    assert.equal(Number(await node.getAttribute('cy')), 510);
    assert.deepEqual(errors, []);
    console.log('PASS: default lock, drag at two sizes, draft preservation, add, undo, connect, save and reload');
  } finally {
    await browser.close();
  }
})().catch(error => { console.error(error); process.exit(1); });
