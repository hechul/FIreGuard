/**
 * FireGuard Map3D — Three.js 3D Map Engine
 * Reads the same floorplan + state objects as the 2D renderer.
 * Call sequence:
 *   Map3D.init(floorplan, container)  — once on load
 *   Map3D.update(state, directedLines) — same directed corridor geometry as the 2D map
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

  // Y is UP in Three.js; map the 2D top to the far side of the 3D view.
  function bx(x) { return x - VW / 2; }
  function bz(y) { return y - VH / 2; }

  const FLOOR_Y   = 0;
  const WALL_H    = 24;
  const WALL_T    = 4.8;
  const NODE_R    = 6;
  const EXIT_W    = 18;
  const LED_H     = 2;

  const COLORS = {
    bg:        0x111f29,
    floor:     0xa5b3b8,
    wall:      0xE2E8F0,
    edge:      0x94A3B8,
    edgeBlock: 0xEF4444,
    node:      0x477186,
    nodeStart: 0x059669,
    nodeDanger:0xDC2626,
    nodeWarn:  0xF59E0B,
    nodeFallbk:0xA855F7,
    exit:      0x10B981,
    exitBlock: 0x9CA3AF,
    route:     0x21C880,
    ledSafe:   0x00E676,
    ledDanger: 0xFF4444,
    flameSafe: 0x10B981,
    flameFire: 0xEF4444,
  };

  /* ------------------------------------------------------------------ */
  /* State                                                                */
  /* ------------------------------------------------------------------ */
  let _scene, _camera, _renderer, _controls, _dynamicGroup;
  let _architecture;
  let eventMark = null;
  let eventKey = '';
  function clearEventMark() {
    if (eventMark) {
      eventMark.parent?.remove(eventMark);
      eventMark.traverse(obj => {
        obj.geometry?.dispose();
        obj.material?.dispose();
      });
    }
    eventMark = null;
    eventKey = '';
  }

  function focusEvent(nodeId, edgeIds = [], additionalNodeIds = []) {
    if (!_dynamicGroup) return;
    const nodes = [...new Set([nodeId, ...additionalNodeIds].filter(Boolean)
      .map(id => window.FireGuardNodeGroups?.displayId(id) || id))];
    const edges = [...new Set(edgeIds)];
    const key = nodes.length || edges.length ? JSON.stringify([nodes, edges]) : '';
    if (eventKey === key) return;
    clearEventMark();
    if (!key) return;
    const points = _allPoints();
    eventKey = key;
    eventMark = new THREE.Group();
    eventMark.name = 'selected-event';
    const color = 0x55d8ff;
    for (const id of nodes) {
      const point = points[id];
      if (!point) continue;
      const ring = new THREE.Mesh(
        new THREE.RingGeometry(12, 15, 48),
        new THREE.MeshBasicMaterial({ color, side: THREE.DoubleSide, depthWrite: false })
      );
      ring.rotation.x = -Math.PI / 2;
      ring.position.set(bx(point.x), LED_H + 5, bz(point.y));
      eventMark.add(ring);
    }
    for (const edgeId of edges) {
      const edge = pool.edges[edgeId];
      if (!edge) continue;
      const line = new THREE.Line(edge.geometry.clone(), new THREE.LineDashedMaterial({
        color, dashSize: 5, gapSize: 4
      }));
      line.position.y = 4;
      line.computeLineDistances();
      eventMark.add(line);
    }
    _dynamicGroup.add(eventMark);
  }

  let _floorplan = null;
  let _container = null;
  let _animId    = null;

  // Named object pools for update-in-place
  const pool = {
    nodes:   {},   // nodeId → Mesh (sphere)
    exits:   {},   // exitId → Mesh (box)
    edges:   {},   // edgeId → Line
    route:   null, // One floor ribbon for all calculated routes.
    sensors: {},   // sensorId → Mesh
    leds:    [],   // Array of Mesh (LED strips from floorplan.ledSegments)
    ledReports: [], // Approximate locations for commands acknowledged by the Pi.
  };

  /* ------------------------------------------------------------------ */
  /* Initialise Scene                                                     */
  /* ------------------------------------------------------------------ */
  function init(floorplan, container) {
    // A visual-only projection aligns the two branches at the prototype's
    // shared junction. Never mutate the routing or telemetry floorplan.
    _floorplan = window.FireGuardPrototypeProjection
      ? window.FireGuardPrototypeProjection.project(floorplan) : floorplan;
    _container = container;

    // Renderer
    _renderer = new THREE.WebGLRenderer({ antialias: true, alpha: false });
    _renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
    _renderer.shadowMap.enabled = true;
    _renderer.shadowMap.type = THREE.PCFSoftShadowMap;
    _renderer.setClearColor(COLORS.bg);
    container.appendChild(_renderer.domElement);
    _resize();

    // Camera
    _camera = new THREE.PerspectiveCamera(42, container.clientWidth / container.clientHeight, 1, 4000);
    _camera.position.copy(_fittedCamera('iso'));

    // Controls (OrbitControls from CDN)
    _controls = new THREE.OrbitControls(_camera, _renderer.domElement);
    _controls.enableDamping  = true;
    _controls.dampingFactor  = 0.07;
    _controls.minDistance    = 100;
    _controls.maxDistance    = Math.max(1800, _camera.position.length() * 1.3);
    _controls.maxPolarAngle  = Math.PI * 0.47;

    // Scene
    _scene = new THREE.Scene();
    _scene.background = new THREE.Color(COLORS.bg);
    _scene.fog = new THREE.FogExp2(COLORS.bg, 0.00017);

    // Lights
    const amb = new THREE.HemisphereLight(0xf5fbff, 0x89909b, 0.95);
    _scene.add(amb);

    const dir = new THREE.DirectionalLight(0xffeed7, 0.77);
    dir.position.set(-250, 600, 250);
    dir.shadow.normalBias = 0.55;
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
    fill.position.set(360, 270, -210);
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

    // Dark fascia defines the edge of the cutaway model.
    const base = new THREE.Mesh(new THREE.BoxGeometry(VW + 6, 9, VH + 6),
      new THREE.MeshStandardMaterial({color: 0x304652, roughness: 0.9}));
    base.position.y = -9;
    _scene.add(base);
  }

  function _buildRooms() {
    _architecture = new THREE.Group();
    _scene.add(_architecture);
    const boxes = [];
    function box(x, y, z, width, height, depth, color) {
      boxes.push({x: bx(x), y, z: bz(z), width, height, depth, color});
    }
    for (const room of _floorplan.rooms || []) {
      const {x, y, width, height, kind, doors = []} = room;
      const cx = x + width / 2, cz = y + height / 2;
      const t = room.wallThickness || WALL_T;
      const tile = kind === 'cinema' ? 0x77858e : kind === 'utility' ? 0xa7c3bd : 0xc4b19b;
      box(cx, 0.35, cz, width, 0.7, height, tile);

      for (const side of ['top', 'bottom', 'left', 'right']) {
        const across = side === 'top' || side === 'bottom';
        const span = across ? width : height;
        const wallHeight = side === 'bottom' ? WALL_H * 0.55 : WALL_H;
        for (const part of _splitByDoors(span, doors.filter(d => d.side === side))) {
          if (part.isDoor || part.len <= 0) continue;
          const mid = part.start + part.len / 2;
          const wx = across ? x + mid : side === 'left' ? x : x + width;
          const wz = across ? side === 'top' ? y : y + height : y + mid;
          const w = across ? part.len : t, d = across ? t : part.len;
          box(wx, wallHeight / 2, wz, w, wallHeight, d, 0xdde1df);
          box(wx, wallHeight + 0.45, wz, w + 0.4, 0.9, d + 0.4, 0x576873);
        }
      }
      if (kind === 'cinema') {
        // Four seat banks leave both principal aisles free for floor guidance.
        for (const fx of [0.18, 0.29, 0.71, 0.82]) {
          for (const fz of [0.22, 0.33, 0.69, 0.8]) {
            const seatX = x + width * fx, seatZ = y + height * fz;
            box(seatX, 2.6, seatZ, width * 0.076, 3.5, height * 0.052, 0x334b59);
            box(seatX, 5.3, seatZ + 2, width * 0.076, 4.2, 2.2, 0x496777);
          }
        }
      } else if (kind === 'shop' || kind === 'public') {
        // Side counters are outside the room's central route to the entrance.
        box(x + width * 0.8, 4.6, y + height * 0.25, width * 0.16, 8, height * 0.27, 0x80634e);
        box(x + width * 0.8, 9, y + height * 0.25, width * 0.18, 1.4, height * 0.29, 0xe0c6a5);
      }
      const labelWidth = Math.min(width * 0.86, Math.max(42, room.name.length * 10 + 18));
      const label = _makeTextSprite(room.name, '#f5f8f8', labelWidth);
      label.position.set(bx(cx), WALL_H + 7, bz(y + height * 0.26));
      _architecture.add(label);
    }
    if (!boxes.length) return;
    const mesh = new THREE.InstancedMesh(new THREE.BoxGeometry(1, 1, 1),
      new THREE.MeshStandardMaterial({roughness: 0.82}), boxes.length);
    const transform = new THREE.Object3D(), tint = new THREE.Color();
    boxes.forEach((part, i) => {
      transform.position.set(part.x, part.y, part.z);
      transform.scale.set(part.width, part.height, part.depth);
      transform.updateMatrix();
      mesh.setMatrixAt(i, transform.matrix);
      mesh.setColorAt(i, tint.setHex(part.color));
    });
    mesh.castShadow = mesh.receiveShadow = true;
    _architecture.add(mesh);
  }

  function _removeArchitecture() {
    if (!_architecture) return;
    _scene.remove(_architecture);
    _architecture.children.forEach(object => {
      if (object.isMesh) object.geometry.dispose();
      object.material.map?.dispose();
      object.material.dispose();
      object.dispose?.();
    });
    _architecture = null;
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
      const sp = _makeTextSprite(exit.name || exit.id, '#aaf7ce', 70);
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
      if (window.FireGuardNodeGroups && window.FireGuardNodeGroups.displayId(node.id) !== node.id) return;
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

      // Room labels give spatial context; the picked node ID appears in its action panel.
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
    LED_SEGMENTS_BLUEPRINT.forEach(([original1, original2]) => {
      let p1 = original1, p2 = original2;
      // The toilet-1 strip shares the 4DX junction in the prototype. This is
      // only a view projection; the Pi's LED indices remain unchanged.
      if (p1[0] === 214 && p1[1] === 567 && p2[0] === 214 && p2[1] === 510) {
        const junction = (_floorplan.nodes || []).find(node => node.id === 'N35');
        if (junction) { p1 = [junction.x, p1[1]]; p2 = [junction.x, p2[1]]; }
      }
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
  let _routeKey = null;
  let _ledReportKey = null;
  const reducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)');

  // Width is in floor-plan units. A ribbon remains visible on WebGL drivers
  // where native line width is fixed to one pixel. Its distance attribute
  // increases along the Pi's traversal, even when the stored edge is reversed.
  function _updateRoute(lines) {
    const key = JSON.stringify(lines);
    if (key === _routeKey) return;
    _routeKey = key;
    if (pool.route) {
      _dynamicGroup.remove(pool.route);
      pool.route.geometry.dispose();
      pool.route.material.dispose();
      pool.route = null;
    }
    const positions = [], distances = [], sides = [], indices = [];
    for (const line of lines) {
      let travelled = 0;
      const points = line.vertices.filter(([x,y], i, vertices) =>
        i === 0 || x !== vertices[i-1][0] || y !== vertices[i-1][1]);
      if (points.length < 2) continue;
      const normals = points.slice(1).map(([x,y],i) => {
        const dx = x - points[i][0], dy = y - points[i][1];
        const len = Math.hypot(dx,dy);
        return [-dy/len, dx/len, len];
      });
      const remaining = line.remaining ?? normals.reduce((sum,n) => sum + n[2], 0);
      const base = distances.length;
      points.forEach(([x,y],i) => {
        const prev = normals[Math.max(0,i-1)], next = normals[Math.min(i,normals.length-1)];
        const dot = prev[0]*next[0] + prev[1]*next[1];
        const dx = dot < -.95 ? next[0] : (prev[0]+next[0]) / Math.max(.6,1+dot);
        const dy = dot < -.95 ? next[1] : (prev[1]+next[1]) / Math.max(.6,1+dot);
        if (i) travelled += prev[2];
        for (const side of [-1,1]) {
          positions.push(bx(x + side*dx*2.8), FLOOR_Y+5, bz(y + side*dy*2.8));
          distances.push(travelled - remaining);
          sides.push(side);
        }
        if (i) {
          const j = base + 2*i;
          indices.push(j-2,j-1,j, j,j-1,j+1);
        }
      });
    }
    if (!positions.length) return;
    const geometry = new THREE.BufferGeometry();
    geometry.setAttribute('position',new THREE.Float32BufferAttribute(positions,3));
    geometry.setAttribute('distanceAlong',new THREE.Float32BufferAttribute(distances,1));
    geometry.setAttribute('side',new THREE.Float32BufferAttribute(sides,1));
    geometry.setIndex(indices);
    const material = new THREE.ShaderMaterial({
      uniforms: {phase: {value:0}},
      side: THREE.DoubleSide,
      vertexShader: `attribute float distanceAlong;
        attribute float side;
        varying float d; varying float across;
        void main() { d=distanceAlong; across=side;
          gl_Position=projectionMatrix*modelViewMatrix*vec4(position,1.0); }`,
      fragmentShader: `uniform float phase;
        varying float d; varying float across;
        void main() {
          float band = mod(d - phase + 2.4*abs(across), 21.0);
          float shine = smoothstep(4.0, 7.0, band)*(1.0-smoothstep(12.0,15.0,band));
          gl_FragColor=vec4(mix(vec3(.035,.43,.29),vec3(.46,1.0,.74),shine),1.0);
        }`,
    });
    pool.route = new THREE.Mesh(geometry,material);
    pool.route.name = 'calculated-route-flow';
    _dynamicGroup.add(pool.route);
  }

  function update(state, directedLines = []) {
    if (!_scene || !_floorplan) return;

    const cloud = state.cloud;
    const uncertain = cloud?.enabled && state.operationMode === 'real' &&
      (!cloud.hasTelemetry || cloud.stale || cloud.routeSource === 'pi_unverified');
    const lines = uncertain ? [] : directedLines;
    _updateRoute(lines);
    const destinations = new Set(lines.map(line => line.to));

    // 2. Edge colours (blocked vs normal)
    Object.entries(pool.edges).forEach(([eid, line]) => {
      const blocked = state.blockedEdges.includes(eid);
      line.material.color.set(blocked ? COLORS.edgeBlock : COLORS.edge);
    });

    // 3. Node colours
    const fallbackById = {};
    (_floorplan.fallbackDestinations || []).forEach(f => { fallbackById[f.id] = f; });

    Object.entries(pool.nodes).forEach(([nid, mesh]) => {
      const members = window.FireGuardNodeGroups?.members(nid) || [nid];
      const blocked = members.some(id => state.blockedNodes.includes(id));
      const isStart = members.includes(state.startNode);
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
      const isTarget = destinations.has(exit.id);
      const c = isTarget ? COLORS.route : COLORS.exit;
      mesh.material.color.set(c);
      mesh.material.emissive.set(c);
      mesh.material.emissiveIntensity = isTarget ? 0.6 : 0.3;
    });

    // 5. Sensor colours
    Object.entries(pool.sensors).forEach(([sid, { mesh }]) => {
      const active = Boolean(state.flameSensors?.[sid]?.active);
      const unconfirmed = state.cloud?.enabled && (!state.cloud.hasTelemetry || state.cloud.stale || !state.flameSensors?.[sid]?.connected);
      const c = active ? COLORS.flameFire : unconfirmed ? 0x64748B : COLORS.flameSafe;
      mesh.material.color.set(c);
      mesh.material.emissive.set(c);
    });

    // Neutral reference strips under the independent route ribbon and
    // acknowledged LED dots make it possible to distinguish all three layers.
    pool.leds.forEach(led => led.material.color.setHex(0x64748B));
    const report = window.FireGuardRealLedProjection && window.FireGuardPrototypeMap
      ? window.FireGuardRealLedProjection.projectFor3d(state, window.FireGuardPrototypeMap.sections) : null;
    const note = document.getElementById('realLed3dNote');
    if (note) {
      note.hidden = !report;
      note.textContent = report?.label || '';
    }
    const points = report?.points || [];
    const reportKey = JSON.stringify(points);
    if (reportKey === _ledReportKey) return;
    _ledReportKey = reportKey;
    for (const mesh of pool.ledReports) {
      _dynamicGroup.remove(mesh);
      mesh.geometry.dispose();
      mesh.material.dispose();
      mesh.dispose();
    }
    pool.ledReports.length = 0;
    if (points.length) {
      const mesh = new THREE.InstancedMesh(new THREE.SphereGeometry(2.5, 8, 6),
        new THREE.MeshBasicMaterial(), points.length);
      const transform = new THREE.Matrix4(), color = new THREE.Color();
      points.forEach((p,i) => {
        mesh.setMatrixAt(i,transform.makeTranslation(bx(p.x),LED_H+5,bz(p.y)));
        mesh.setColorAt(i,color.setHex(p.color === 'fire' ? COLORS.ledDanger : COLORS.ledSafe));
      });
      mesh.name = 'acknowledged-led-positions';
      _dynamicGroup.add(mesh);
      pool.ledReports.push(mesh);
    }
  }

  /* ------------------------------------------------------------------ */
  /* Camera View Presets                                                  */
  /* ------------------------------------------------------------------ */
  const VIEWS = {iso: [0.25, 1, 0.75], top: [0, 1, 0.001], side: [1, 0.5, 0.24]};

  function _fittedCamera(name) {
    // Fit all slab corners in the perspective frustum, including narrow displays.
    const direction = new THREE.Vector3(...VIEWS[name]).normalize();
    const right = new THREE.Vector3().crossVectors(new THREE.Vector3(0,1,0), direction).normalize();
    const up = new THREE.Vector3().crossVectors(direction, right);
    const tan = Math.tan(THREE.MathUtils.degToRad(_camera.fov / 2));
    let distance = 0;
    for (const x of [-VW/2,VW/2]) for (const z of [-VH/2,VH/2]) {
      const p = new THREE.Vector3(x, WALL_H, z);
      const margin = Math.max(Math.abs(p.dot(right))/(tan*_camera.aspect), Math.abs(p.dot(up))/tan);
      distance = Math.max(distance, p.dot(direction) + margin * 1.07);
    }
    return direction.multiplyScalar(distance);
  }

  function setView(name) {
    if (!VIEWS[name]) return;
    _animCam(_fittedCamera(name), new THREE.Vector3(0,0,0));
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
    // Fallback entries are destination metadata; their coordinates live on nodes.
    // Do not replace a positioned node with metadata lacking x/y (NaN geometry).
    (_floorplan.fallbackDestinations || []).forEach(n => {
      if (!map[n.id] && Number.isFinite(n.x) && Number.isFinite(n.y)) map[n.id] = n;
    });
    return map;
  }

  function _makeTextSprite(text, colorHex, scaleW) {
    const c = document.createElement('canvas');
    const ctx = c.getContext('2d');
    const font = '600 30px "Apple SD Gothic Neo", "Malgun Gothic", sans-serif';
    ctx.font = font;
    c.width = Math.ceil(ctx.measureText(text).width) + 28;
    c.height = 48;
    ctx.font = font;
    ctx.fillStyle = 'rgba(19,32,39,.94)';
    ctx.fillRect(0, 0, c.width, c.height);
    ctx.fillStyle = colorHex;
    ctx.textAlign = 'center';
    ctx.textBaseline = 'middle';
    ctx.fillText(text, c.width / 2, c.height / 2 + 1);
    const tex = new THREE.CanvasTexture(c);
    const mat = new THREE.SpriteMaterial({map: tex, transparent:true, depthWrite:false});
    const sp = new THREE.Sprite(mat);
    sp.scale.set(scaleW, scaleW * c.height / c.width, 1);
    return sp;
  }

  function _resize() {
    if (!_container || !_renderer) return;
    const w = _container.clientWidth;
    const h = _container.clientHeight;
    if (!w || !h) return;
    _renderer.setSize(w, h);
    if (_camera && w > 0 && h > 0) {
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
    if (!_container.clientWidth || !_container.clientHeight || document.hidden) return;
    const t = _clock.getElapsedTime();

    if (pool.route) {
      pool.route.material.uniforms.phase.value = reducedMotion.matches ? 0 : (performance.now() / 1000 % 1) * 21;
    }

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
  function rebuild(newFloorplan, state, directedLines = []) {
    if (!_scene || !_dynamicGroup) return;
    _floorplan = window.FireGuardPrototypeProjection
      ? window.FireGuardPrototypeProjection.project(newFloorplan) : newFloorplan;

    _removeArchitecture();
    _buildRooms();

    clearEventMark();
    // Remove all dynamic objects from _dynamicGroup
    while (_dynamicGroup.children.length > 0) {
      const obj = _dynamicGroup.children[0];
      _dynamicGroup.remove(obj);
      if (obj.isInstancedMesh) obj.dispose();
      if (!obj.isSprite && obj.geometry) obj.geometry.dispose();
      if (obj.material) {
        if (Array.isArray(obj.material)) obj.material.forEach(m => m.dispose());
        else {
          obj.material.map?.dispose();
          obj.material.dispose();
        }
      }
    }

    pool.route = null;
    _routeKey = _ledReportKey = null;
    pool.ledReports.length = 0;
    Object.keys(pool.nodes).forEach(k => delete pool.nodes[k]);
    Object.keys(pool.exits).forEach(k => delete pool.exits[k]);
    Object.keys(pool.edges).forEach(k => delete pool.edges[k]);
    Object.keys(pool.sensors).forEach(k => delete pool.sensors[k]);

    _buildExits();
    _buildEdges();
    _buildNodes();
    _buildSensors();

    if (state) update(state, directedLines);
  }

  /* ------------------------------------------------------------------ */
  /* Dispose                                                              */
  /* ------------------------------------------------------------------ */
  function dispose() {
    clearEventMark();
    _removeArchitecture();
    if (_animId) cancelAnimationFrame(_animId);
    if (_renderer) {
      _controls?.dispose();
      _scene?.traverse(obj => {
        if (obj.isInstancedMesh) obj.dispose();
        if (!obj.isSprite) obj.geometry?.dispose();
        for (const material of [].concat(obj.material || [])) {
          material.map?.dispose();
          material.dispose();
        }
      });
      _renderer.dispose();
      if (_renderer._resizeObs) _renderer._resizeObs.disconnect();
      if (_renderer.domElement.parentNode) _renderer.domElement.parentNode.removeChild(_renderer.domElement);
    }
    pool.route = null;
    _routeKey = _ledReportKey = null;
    pool.ledReports.length = 0;
    pool.leds.length  = 0;
    Object.keys(pool.nodes).forEach(k => delete pool.nodes[k]);
    Object.keys(pool.exits).forEach(k => delete pool.exits[k]);
    Object.keys(pool.edges).forEach(k => delete pool.edges[k]);
    Object.keys(pool.sensors).forEach(k => delete pool.sensors[k]);
    _scene = _camera = _renderer = _controls = _dynamicGroup = null;
  }

  return { init, update, setView, focusEvent, rebuild, dispose };
})();
