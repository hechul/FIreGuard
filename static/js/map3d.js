/**
 * FireGuard Map3D — Three.js 3D Map Engine
 * Reads the same floorplan + state objects as the 2D renderer.
 * Call sequence:
 *   Map3D.init(floorplan, container)  — once on load
 *   Map3D.update(state)              — on every state:update
 *   Map3D.dispose()                  — on teardown
 */
'use strict';

const Map3D = (() => {
  /* ------------------------------------------------------------------ */
  /* Constants & Config                                                   */
  /* ------------------------------------------------------------------ */
  // SVG viewBox is 0 0 584 858 — centre at (292, 429)
  const VW = 584;
  const VH = 858;

  // Y is UP in Three.js; blueprint X → 3D X, blueprint Y → 3D -Z
  function bx(x) { return x - VW / 2; }
  function bz(y) { return -(y - VH / 2); }

  const FLOOR_Y   = 0;
  const WALL_H    = 48;
  const WALL_T    = 4.8;
  const NODE_R    = 8;
  const EXIT_W    = 18;
  const LED_H     = 2;

  const COLORS = {
    bg:        0x111418,
    floor:     0xF1F5F9,
    wall:      0xE2E8F0,
    edge:      0x94A3B8,
    edgeBlock: 0xEF4444,
    node:      0x3182F6,
    nodeStart: 0x059669,
    nodeDanger:0xDC2626,
    nodeWarn:  0xF59E0B,
    nodeFallbk:0xA855F7,
    exit:      0x10B981,
    exitBlock: 0x9CA3AF,
    route:     0x3182F6,
    ledSafe:   0x00E676,
    ledDanger: 0xFF4444,
    flameSafe: 0x10B981,
    flameFire: 0xEF4444,
  };

  /* ------------------------------------------------------------------ */
  /* State                                                                */
  /* ------------------------------------------------------------------ */
  let _scene, _camera, _renderer, _controls, _dynamicGroup;
  let _floorplan = null;
  let _container = null;
  let _animId    = null;

  // Named object pools for update-in-place
  const pool = {
    nodes:   {},   // nodeId → Mesh (sphere)
    exits:   {},   // exitId → Mesh (box)
    edges:   {},   // edgeId → Line
    route:   [],   // Array of Line
    sensors: {},   // sensorId → Mesh
    leds:    [],   // Array of Mesh (LED strips from floorplan.ledSegments)
  };

  /* ------------------------------------------------------------------ */
  /* Initialise Scene                                                     */
  /* ------------------------------------------------------------------ */
  function init(floorplan, container) {
    _floorplan = floorplan;
    _container = container;

    // Renderer
    _renderer = new THREE.WebGLRenderer({ antialias: true, alpha: false });
    _renderer.setPixelRatio(window.devicePixelRatio);
    _renderer.shadowMap.enabled = true;
    _renderer.shadowMap.type = THREE.PCFSoftShadowMap;
    _renderer.setClearColor(COLORS.bg);
    container.appendChild(_renderer.domElement);
    _resize();

    // Camera
    _camera = new THREE.PerspectiveCamera(42, container.clientWidth / container.clientHeight, 1, 4000);
    _camera.position.set(0, 550, 480);

    // Controls (OrbitControls from CDN)
    _controls = new THREE.OrbitControls(_camera, _renderer.domElement);
    _controls.enableDamping  = true;
    _controls.dampingFactor  = 0.07;
    _controls.minDistance    = 100;
    _controls.maxDistance    = 1200;
    _controls.maxPolarAngle  = Math.PI / 2 + 0.15;

    // Scene
    _scene = new THREE.Scene();
    _scene.background = new THREE.Color(COLORS.bg);
    _scene.fog = new THREE.FogExp2(COLORS.bg, 0.00055);

    // Lights
    const amb = new THREE.AmbientLight(0xffffff, 0.7);
    _scene.add(amb);

    const dir = new THREE.DirectionalLight(0xffffff, 0.9);
    dir.position.set(200, 500, 300);
    dir.castShadow = true;
    dir.shadow.camera.near  = 10;
    dir.shadow.camera.far   = 1500;
    dir.shadow.camera.left  = -500;
    dir.shadow.camera.right =  500;
    dir.shadow.camera.top   =  500;
    dir.shadow.camera.bottom= -500;
    dir.shadow.mapSize.set(1024, 1024);
    _scene.add(dir);

    const fill = new THREE.DirectionalLight(0x93C5FD, 0.35);
    fill.position.set(-300, -200, -200);
    _scene.add(fill);

    // Dynamic Group for nodes, edges, exits, route, and sensors
    _dynamicGroup = new THREE.Group();
    _scene.add(_dynamicGroup);

    // Static geometry (floor + walls)
    _buildFloor();
    _buildRooms();

    // Exit markers
    _buildExits();

    // Edges
    _buildEdges();

    // Nodes
    _buildNodes();

    // Sensors
    _buildSensors();

    // LED strips (static geometry; colour updated via update())
    _buildLedStrips();

    // Resize observer
    const ro = new ResizeObserver(_resize);
    ro.observe(container);
    _renderer._resizeObs = ro;

    // Raycaster for 3D node selection
    const raycaster = new THREE.Raycaster();
    const mouse = new THREE.Vector2();
    let downTime = 0;
    let downX = 0, downY = 0;

    _renderer.domElement.addEventListener('pointerdown', (e) => {
      downTime = performance.now();
      downX = e.clientX;
      downY = e.clientY;
    });

    _renderer.domElement.addEventListener('pointerup', (e) => {
      const dist = Math.hypot(e.clientX - downX, e.clientY - downY);
      const elapsed = performance.now() - downTime;
      if (dist < 6 && elapsed < 350) {
        const rect = _renderer.domElement.getBoundingClientRect();
        mouse.x = ((e.clientX - rect.left) / rect.width) * 2 - 1;
        mouse.y = -((e.clientY - rect.top) / rect.height) * 2 + 1;
        raycaster.setFromCamera(mouse, _camera);

        const nodeMeshes = Object.values(pool.nodes);
        const hits = raycaster.intersectObjects(nodeMeshes, false);
        if (hits.length > 0) {
          const hitMesh = hits[0].object;
          const nid = Object.keys(pool.nodes).find(k => pool.nodes[k] === hitMesh);
          if (nid && typeof window.__onSelectNode3D === 'function') {
            window.__onSelectNode3D(nid);
          }
        }
      }
    });

    // Start loop
    _loop();
  }

  /* ------------------------------------------------------------------ */
  /* Static Builders                                                      */
  /* ------------------------------------------------------------------ */
  function _buildFloor() {
    // Thin floor slab
    const geo = new THREE.BoxGeometry(VW, 5, VH);
    const mat = new THREE.MeshStandardMaterial({ color: COLORS.floor, roughness: 0.8, metalness: 0.0 });
    const mesh = new THREE.Mesh(geo, mat);
    mesh.position.set(0, -2.5, 0);
    mesh.receiveShadow = true;
    _scene.add(mesh);

    // Grid
    const grid = new THREE.GridHelper(Math.max(VW, VH), 30, 0xCBD5E1, 0xE2E8F0);
    grid.position.set(0, 0.2, 0);
    _scene.add(grid);
  }

  function _buildRooms() {
    if (!_floorplan.rooms) return;
    const wallMat = new THREE.MeshStandardMaterial({
      color: COLORS.wall, roughness: 0.55, metalness: 0.05,
      transparent: true, opacity: 0.88,
    });

    _floorplan.rooms.forEach(room => {
      const { x, y, width, height, doors = [] } = room;
      const t = room.wallThickness || WALL_T;

      // Build 4 walls with door gaps
      // Each wall: { axis: H|V, x1, z1, x2, z2, doors: [] }
      const walls = [
        { side: 'top',    x0: x,        z0: y,          len: width,  horiz: true  },
        { side: 'bottom', x0: x,        z0: y + height, len: width,  horiz: true  },
        { side: 'left',   x0: x,        z0: y,          len: height, horiz: false },
        { side: 'right',  x0: x + width,z0: y,          len: height, horiz: false },
      ];

      walls.forEach(w => {
        const wallDoors = doors.filter(d => {
          const s = d.side;
          if (w.side === 'top'    && s === 'top')    return true;
          if (w.side === 'bottom' && s === 'bottom')  return true;
          if (w.side === 'left'   && s === 'left')    return true;
          if (w.side === 'right'  && s === 'right')   return true;
          return false;
        });
        _addWallSegment(w, wallDoors, t, wallMat);
      });
    });
  }

  function _addWallSegment(w, doors, thickness, mat) {
    const DH = 36; // door open height
    const segments = _splitByDoors(w.len, doors);
    segments.forEach(seg => {
      const cx = w.horiz
        ? w.x0 + seg.start + seg.len / 2
        : w.x0;
      const cz = w.horiz
        ? w.z0
        : w.z0 + seg.start + seg.len / 2;

      if (seg.isDoor) {
        // Only lintel above door
        const lH = WALL_H - DH;
        const geo = w.horiz
          ? new THREE.BoxGeometry(seg.len, lH, thickness)
          : new THREE.BoxGeometry(thickness, lH, seg.len);
        const mesh = new THREE.Mesh(geo, mat);
        mesh.position.set(bx(cx), DH + lH / 2, bz(cz));
        mesh.castShadow = true;
        _scene.add(mesh);
      } else {
        const geo = w.horiz
          ? new THREE.BoxGeometry(seg.len, WALL_H, thickness)
          : new THREE.BoxGeometry(thickness, WALL_H, seg.len);
        const mesh = new THREE.Mesh(geo, mat);
        mesh.position.set(bx(cx), WALL_H / 2, bz(cz));
        mesh.castShadow = true;
        _scene.add(mesh);
      }
    });
  }

  function _splitByDoors(totalLen, doors) {
    const segs = [];
    let cursor = 0;
    const sorted = [...doors].sort((a, b) => a.offset - b.offset);
    sorted.forEach(d => {
      if (d.offset > cursor) segs.push({ start: cursor, len: d.offset - cursor, isDoor: false });
      segs.push({ start: d.offset, len: d.width, isDoor: true });
      cursor = d.offset + d.width;
    });
    if (cursor < totalLen) segs.push({ start: cursor, len: totalLen - cursor, isDoor: false });
    return segs;
  }

  function _buildExits() {
    const mat = new THREE.MeshStandardMaterial({ color: COLORS.exit, roughness: 0.4, emissive: COLORS.exit, emissiveIntensity: 0.3 });
    (_floorplan.exits || []).forEach(exit => {
      const geo = new THREE.BoxGeometry(EXIT_W, EXIT_W, EXIT_W);
      const mesh = new THREE.Mesh(geo, mat.clone());
      mesh.position.set(bx(exit.x), EXIT_W / 2, bz(exit.y));
      mesh.castShadow = true;
      _dynamicGroup.add(mesh);
      pool.exits[exit.id] = mesh;

      // Label sprite
      const sp = _makeTextSprite(exit.name || exit.id, '#10B981', 90);
      sp.position.set(bx(exit.x), EXIT_W + 14, bz(exit.y));
      _dynamicGroup.add(sp);
    });
  }

  function _buildEdges() {
    const ptMap = _allPoints();
    const mat = new THREE.LineBasicMaterial({ color: COLORS.edge, linewidth: 2 });
    (_floorplan.edges || []).forEach(edge => {
      const a = ptMap[edge.from]; const b = ptMap[edge.to];
      if (!a || !b) return;
      let waypoints = [a, b];
      if (typeof MapGeometry !== 'undefined' && MapGeometry.createRouter) {
        try {
          const r = MapGeometry.createRouter(_floorplan);
          const routed = r.route(a, b);
          if (routed && routed.length >= 2) waypoints = routed;
        } catch (_) {}
      }
      const pts = waypoints.map(p => new THREE.Vector3(bx(p.x), LED_H + 2, bz(p.y)));
      const line = new THREE.Line(
        new THREE.BufferGeometry().setFromPoints(pts),
        mat.clone()
      );
      _dynamicGroup.add(line);
      pool.edges[edge.id] = line;
    });
  }

  function _buildNodes() {
    const fallbackById = {};
    (_floorplan.fallbackDestinations || []).forEach(f => { fallbackById[f.id] = f; });

    (_floorplan.nodes || []).forEach(node => {
      const isFallback = Boolean(fallbackById[node.id]);
      const geo = new THREE.SphereGeometry(isFallback ? NODE_R * 1.3 : NODE_R, 18, 12);
      const mat = new THREE.MeshStandardMaterial({
        color: COLORS.node, roughness: 0.4, metalness: 0.1,
        emissive: COLORS.node, emissiveIntensity: 0.25,
      });
      const mesh = new THREE.Mesh(geo, mat);
      mesh.position.set(bx(node.x), NODE_R, bz(node.y));
      mesh.castShadow = true;
      _dynamicGroup.add(mesh);
      pool.nodes[node.id] = mesh;

      // ID label
      const sp = _makeTextSprite(node.id, '#3182F6', 60);
      sp.position.set(bx(node.x), NODE_R * 2 + 8, bz(node.y));
      _dynamicGroup.add(sp);
    });
  }

  function _buildSensors() {
    if (!_floorplan.sensors) return;
    const ptMap = _allPoints();

    _floorplan.sensors.filter(sensor => sensor.type === 'flame').forEach(sensor => {
      const pt = ptMap[sensor.node]; if (!pt) return;
      const geo = new THREE.ConeGeometry(5, 12, 8);
      const mat = new THREE.MeshStandardMaterial({
        color: COLORS.flameSafe,
        roughness: 0.4, metalness: 0.1,
        emissive: COLORS.flameSafe,
        emissiveIntensity: 0.2,
      });
      const mesh = new THREE.Mesh(geo, mat);
      const offset = 12;
      mesh.position.set(bx(pt.x) + offset, 10, bz(pt.y) + offset);
      _dynamicGroup.add(mesh);
      pool.sensors[sensor.id] = { mesh };
    });
  }

  // Shared physical LED geometry for the dashboard 2D and 3D views.
  const LED_SEGMENTS_BLUEPRINT = window.FireGuardLedPlan;

  function _buildLedStrips() {
    const mat = new THREE.MeshBasicMaterial({ color: COLORS.ledSafe });
    LED_SEGMENTS_BLUEPRINT.forEach(([p1, p2]) => {
      const x1 = bx(p1[0]), z1 = bz(p1[1]);
      const x2 = bx(p2[0]), z2 = bz(p2[1]);
      const dx = x2 - x1, dz = z2 - z1;
      const len = Math.hypot(dx, dz);
      const angle = Math.atan2(dx, dz);
      const geo = new THREE.BoxGeometry(6, LED_H, len);
      const mesh = new THREE.Mesh(geo, mat.clone());
      mesh.position.set((x1 + x2) / 2, LED_H / 2, (z1 + z2) / 2);
      mesh.rotation.y = angle;
      _scene.add(mesh);
      pool.leds.push(mesh);
    });
  }

  /* ------------------------------------------------------------------ */
  /* Reactive Update (called on every state:update)                      */
  /* ------------------------------------------------------------------ */
  function update(state) {
    if (!_scene || !_floorplan) return;

    const ptMap     = _allPoints();
    const edgeMap   = {};
    (_floorplan.edges || []).forEach(e => { edgeMap[e.id] = e; });
    const routeEdgeIds = new Set(state.route?.edges || []);

    // 1. Route lines (clear old, draw new)
    pool.route.forEach(l => _dynamicGroup.remove(l));
    pool.route.length = 0;
    if (state.route?.edges?.length) {
      const routeMat = new THREE.LineBasicMaterial({ color: COLORS.route, linewidth: 4 });
      state.route.edges.forEach(eid => {
        const edge = edgeMap[eid]; if (!edge) return;
        const a = ptMap[edge.from]; const b = ptMap[edge.to];
        if (!a || !b) return;
        let waypoints = [a, b];
        if (typeof MapGeometry !== 'undefined' && MapGeometry.createRouter) {
          try {
            const r = MapGeometry.createRouter(_floorplan);
            const routed = r.route(a, b);
            if (routed && routed.length >= 2) waypoints = routed;
          } catch (_) {}
        }
        const pts = waypoints.map(p => new THREE.Vector3(bx(p.x), LED_H + 5, bz(p.y)));
        const line = new THREE.Line(new THREE.BufferGeometry().setFromPoints(pts), routeMat);
        _dynamicGroup.add(line);
        pool.route.push(line);
      });
    }

    // 2. Edge colours (blocked vs normal)
    Object.entries(pool.edges).forEach(([eid, line]) => {
      const blocked = state.blockedEdges.includes(eid);
      line.material.color.set(blocked ? COLORS.edgeBlock : COLORS.edge);
    });

    // 3. Node colours
    const fallbackById = {};
    (_floorplan.fallbackDestinations || []).forEach(f => { fallbackById[f.id] = f; });

    Object.entries(pool.nodes).forEach(([nid, mesh]) => {
      const blocked = state.blockedNodes.includes(nid);
      const isStart = state.startNode === nid;
      const isFallback = Boolean(fallbackById[nid]);
      let c = COLORS.node;
      if (blocked)    c = COLORS.nodeDanger;
      else if (isStart) c = COLORS.nodeStart;
      else if (isFallback) c = COLORS.nodeFallbk;
      mesh.material.color.set(c);
      mesh.material.emissive.set(c);
      mesh.material.emissiveIntensity = blocked ? 0.5 : 0.2;
    });

    // 4. Exit colours
    (_floorplan.exits || []).forEach(exit => {
      const mesh = pool.exits[exit.id]; if (!mesh) return;
      const isTarget = state.route?.exitId === exit.id;
      const c = isTarget ? COLORS.route : COLORS.exit;
      mesh.material.color.set(c);
      mesh.material.emissive.set(c);
      mesh.material.emissiveIntensity = isTarget ? 0.6 : 0.3;
    });

    // 5. Sensor colours
    Object.entries(pool.sensors).forEach(([sid, { mesh }]) => {
      const active = Boolean(state.flameSensors?.[sid]?.active);
      const c = active ? COLORS.flameFire : COLORS.flameSafe;
      mesh.material.color.set(c);
      mesh.material.emissive.set(c);
    });

    // 6. LED strip colour: route-active → blue glow, else green
    pool.leds.forEach(led => {
      const c = state.overallStatus === 'fire' ? COLORS.ledDanger
              : state.overallStatus === 'warning' ? COLORS.ledSafe
              : COLORS.ledSafe;
      led.material.color.set(c);
    });
  }

  /* ------------------------------------------------------------------ */
  /* Camera View Presets                                                  */
  /* ------------------------------------------------------------------ */
  const VIEWS = {
    iso:  [0, 550, 480,   0, 30, 0],
    top:  [0, 800, 0.1,   0, 0, 0],
    side: [420, 300, 50,  0, 80, 0],
  };

  function setView(name) {
    const v = VIEWS[name]; if (!v) return;
    _animCam(new THREE.Vector3(v[0], v[1], v[2]), new THREE.Vector3(v[3], v[4], v[5]));
  }

  function _animCam(endPos, endTarget) {
    const startPos = _camera.position.clone();
    const startTgt = _controls.target.clone();
    let p = 0;
    function step() {
      p = Math.min(p + 0.05, 1);
      _camera.position.lerpVectors(startPos, endPos, p);
      _controls.target.lerpVectors(startTgt, endTarget, p);
      _controls.update();
      if (p < 1) requestAnimationFrame(step);
    }
    step();
  }

  /* ------------------------------------------------------------------ */
  /* Helpers                                                              */
  /* ------------------------------------------------------------------ */
  function _allPoints() {
    const map = {};
    (_floorplan.nodes || []).forEach(n => { map[n.id] = n; });
    (_floorplan.exits || []).forEach(n => { map[n.id] = n; });
    (_floorplan.fallbackDestinations || []).forEach(n => { map[n.id] = n; });
    return map;
  }

  function _makeTextSprite(text, colorHex, scaleW) {
    const c = document.createElement('canvas');
    c.width = 256; c.height = 80;
    const ctx = c.getContext('2d');
    ctx.fillStyle = colorHex;
    ctx.font = 'bold 32px Pretendard, Arial, sans-serif';
    ctx.textAlign = 'center';
    ctx.fillText(text, 128, 52);
    const tex = new THREE.CanvasTexture(c);
    const mat = new THREE.SpriteMaterial({ map: tex, transparent: true });
    const sp  = new THREE.Sprite(mat);
    sp.scale.set(scaleW, scaleW / 3.2, 1);
    return sp;
  }

  function _resize() {
    if (!_container || !_renderer) return;
    const w = _container.clientWidth;
    const h = _container.clientHeight;
    _renderer.setSize(w, h);
    if (_camera) {
      _camera.aspect = w / h;
      _camera.updateProjectionMatrix();
    }
  }

  /* ------------------------------------------------------------------ */
  /* Animation Loop                                                       */
  /* ------------------------------------------------------------------ */
  const _clock = new THREE.Clock();
  function _loop() {
    _animId = requestAnimationFrame(_loop);
    const t = _clock.getElapsedTime();

    // Pulse LED strips when active (colour cycling)
    pool.leds.forEach((led, i) => {
      const base = led.material.color.getHex();
      if (base === COLORS.ledSafe || base === COLORS.ledDanger) {
        const pulse = 0.65 + 0.35 * Math.sin(t * 3 + i * 0.4);
        const col = new THREE.Color(base);
        col.multiplyScalar(pulse);
        led.material.color.set(col);
      }
    });

    // Pulse active exit
    Object.values(pool.exits).forEach(mesh => {
      const pulse = 0.7 + 0.3 * Math.sin(t * 2);
      mesh.material.emissiveIntensity = mesh.material.color.getHex() === COLORS.route
        ? pulse * 0.6 : 0.3;
    });

    _controls.update();
    _renderer.render(_scene, _camera);
  }

  /* ------------------------------------------------------------------ */
  /* Rebuild (Dynamic nodes, edges, exits, sensors on floorplan change) */
  /* ------------------------------------------------------------------ */
  function rebuild(newFloorplan, state) {
    if (!_scene || !_dynamicGroup) return;
    _floorplan = newFloorplan;

    // Remove all dynamic objects from _dynamicGroup
    while (_dynamicGroup.children.length > 0) {
      const obj = _dynamicGroup.children[0];
      _dynamicGroup.remove(obj);
      if (obj.geometry) obj.geometry.dispose();
      if (obj.material) {
        if (Array.isArray(obj.material)) obj.material.forEach(m => m.dispose());
        else obj.material.dispose();
      }
    }

    pool.route.length = 0;
    Object.keys(pool.nodes).forEach(k => delete pool.nodes[k]);
    Object.keys(pool.exits).forEach(k => delete pool.exits[k]);
    Object.keys(pool.edges).forEach(k => delete pool.edges[k]);
    Object.keys(pool.sensors).forEach(k => delete pool.sensors[k]);

    _buildExits();
    _buildEdges();
    _buildNodes();
    _buildSensors();

    if (state) update(state);
  }

  /* ------------------------------------------------------------------ */
  /* Dispose                                                              */
  /* ------------------------------------------------------------------ */
  function dispose() {
    if (_animId) cancelAnimationFrame(_animId);
    if (_renderer) {
      _renderer.dispose();
      if (_renderer._resizeObs) _renderer._resizeObs.disconnect();
      if (_renderer.domElement.parentNode) _renderer.domElement.parentNode.removeChild(_renderer.domElement);
    }
    pool.route.length = 0;
    pool.leds.length  = 0;
    Object.keys(pool.nodes).forEach(k => delete pool.nodes[k]);
    Object.keys(pool.exits).forEach(k => delete pool.exits[k]);
    Object.keys(pool.edges).forEach(k => delete pool.edges[k]);
    Object.keys(pool.sensors).forEach(k => delete pool.sensors[k]);
    _scene = _camera = _renderer = _controls = _dynamicGroup = null;
  }

  return { init, update, setView, rebuild, dispose };
})();
