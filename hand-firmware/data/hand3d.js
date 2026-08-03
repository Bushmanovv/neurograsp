/* 3D hand for the InMoov app.
 *
 * Default: a procedural InMoov hand + forearm built to the real assembly's
 * proportions (hand ~187x146x71mm, 4x three-segment fingers, 2-segment thumb,
 * flat palm plate, tapered forearm shell). It ARTICULATES with the app state
 * (setPose drives finger curl + wrist).  Drag to orbit.
 *
 * Optional: load a static realistic model instead with `?glb=models/<file>`
 * (auto-stood-up, auto-fit, studio-lit). `?lite` skips shadows/env for testing.
 */
window.Hand3D = function (container, opts) {
  opts = opts || {};
  const T = window.THREE;
  const w = () => container.clientWidth || 1;
  const h = () => container.clientHeight || 1;

  const scene = new T.Scene();
  const camera = new T.PerspectiveCamera(30, w() / h(), 0.1, 100);
  camera.position.set(0, 0.1, 16);
  camera.lookAt(0, 0, 0);

  const renderer = new T.WebGLRenderer({ antialias: true, alpha: true });
  renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
  renderer.setSize(w(), h());
  const LITE = new URLSearchParams(location.search).has("lite");
  renderer.shadowMap.enabled = !LITE;
  renderer.shadowMap.type = T.PCFSoftShadowMap;
  if (T.sRGBEncoding) renderer.outputEncoding = T.sRGBEncoding;
  container.appendChild(renderer.domElement);

  if (!LITE) (function setEnv() {
    const c = document.createElement("canvas"); c.width = 32; c.height = 96;
    const g = c.getContext("2d");
    const grd = g.createLinearGradient(0, 0, 0, 96);
    grd.addColorStop(0, "#eef2f7"); grd.addColorStop(0.45, "#dbe1ea");
    grd.addColorStop(0.7, "#b8c0cd"); grd.addColorStop(1, "#8d96a4");
    g.fillStyle = grd; g.fillRect(0, 0, 32, 96);
    g.fillStyle = "rgba(255,255,255,0.5)"; g.fillRect(0, 6, 32, 14);
    const tex = new T.CanvasTexture(c); tex.mapping = T.EquirectangularReflectionMapping;
    const pmrem = new T.PMREMGenerator(renderer);
    scene.environment = pmrem.fromEquirectangular(tex).texture;
    tex.dispose(); pmrem.dispose();
  })();

  scene.add(new T.HemisphereLight(0xffffff, 0xa6b1c4, 0.3));
  const key = new T.DirectionalLight(0xffffff, 0.85);
  key.position.set(4, 9, 7); key.castShadow = !LITE;
  key.shadow.mapSize.set(2048, 2048);
  Object.assign(key.shadow.camera, { near: 1, far: 40, left: -8, right: 8, top: 9, bottom: -9 });
  key.shadow.bias = -0.0005; scene.add(key);
  const rimL = new T.DirectionalLight(0xcfe0ff, 0.45); rimL.position.set(-6, 4, -5); scene.add(rimL);
  const fillL = new T.DirectionalLight(0xffffff, 0.2); fillL.position.set(0, -2, 6); scene.add(fillL);

  let groundY = -4;
  const ground = new T.Mesh(new T.CircleGeometry(9, 48), new T.ShadowMaterial({ opacity: 0.15 }));
  ground.rotation.x = -Math.PI / 2; ground.position.y = groundY; ground.receiveShadow = true; scene.add(ground);

  const root = new T.Group(); scene.add(root);

  // materials: matte white printed PLA + dark mechanical joints + metal
  const white = new T.MeshStandardMaterial({ color: 0xaab3c2, roughness: 0.62, metalness: 0.05, envMapIntensity: 0.6 });
  const darkJ = new T.MeshStandardMaterial({ color: 0x262a30, roughness: 0.45, metalness: 0.5, envMapIntensity: 1.0 });
  const metal = new T.MeshStandardMaterial({ color: 0xc3c8d0, roughness: 0.25, metalness: 1.0, envMapIntensity: 1.2 });

  // ---- shared geometry helpers ----
  function roundedRect(wd, ht, r) {
    const s = new T.Shape(); const x = -wd / 2, y = -ht / 2;
    s.moveTo(x + r, y);
    s.lineTo(x + wd - r, y); s.quadraticCurveTo(x + wd, y, x + wd, y + r);
    s.lineTo(x + wd, y + ht - r); s.quadraticCurveTo(x + wd, y + ht, x + wd - r, y + ht);
    s.lineTo(x + r, y + ht); s.quadraticCurveTo(x, y + ht, x, y + ht - r);
    s.lineTo(x, y + r); s.quadraticCurveTo(x, y, x + r, y);
    return s;
  }
  function shellBar(wd, ht, dp, r, mat) {
    const geo = new T.ExtrudeGeometry(roundedRect(wd, ht, Math.min(r, wd / 2, ht / 2)),
      { depth: dp, bevelEnabled: true, bevelThickness: dp * 0.16, bevelSize: r * 0.4, bevelSegments: 2, steps: 1, curveSegments: 8 });
    geo.center(); geo.computeVertexNormals();
    const m = new T.Mesh(geo, mat || white); m.castShadow = true; m.receiveShadow = true; return m;
  }
  function pin(radius, len, mat) {
    const m = new T.Mesh(new T.CylinderGeometry(radius, radius, len, 16), mat || darkJ);
    m.rotation.z = Math.PI / 2; m.castShadow = true; return m;
  }
  // palm plate: the +x (pinky/ulnar) side is ONE continuous smooth curve from the
  // bottom edge up to the knuckle corner — leaves the bottom horizontally and meets
  // the top corner vertically (tangent-matched, so no kink), narrow near the wrist
  // and full width at the knuckles. `taper` sets how much it draws in toward the wrist.
  function palmShell(wd, ht, dp, r, taper, mat) {
    r = Math.min(r, wd / 2, ht / 2);
    const x = -wd / 2, y = -ht / 2;
    const s = new T.Shape();
    s.moveTo(x + r, y);
    s.lineTo(x + wd - r - taper, y);                                       // bottom edge (ends early on the pinky side)
    s.bezierCurveTo(x + wd - taper * 0.35, y,                              // leave the bottom horizontally,
                    x + wd, y + ht * 0.5,                                  //  sweep out and up,
                    x + wd, y + ht - r);                                   //  arrive vertically at the knuckle corner
    s.quadraticCurveTo(x + wd, y + ht, x + wd - r, y + ht);
    s.lineTo(x + r, y + ht); s.quadraticCurveTo(x, y + ht, x, y + ht - r);
    s.lineTo(x, y + r); s.quadraticCurveTo(x, y, x + r, y);
    const geo = new T.ExtrudeGeometry(s,
      { depth: dp, bevelEnabled: true, bevelThickness: dp * 0.16, bevelSize: r * 0.4, bevelSegments: 2, steps: 1, curveSegments: 12 });
    geo.computeBoundingBox(); const b = geo.boundingBox;
    geo.translate(0, -(b.min.y + b.max.y) / 2, -(b.min.z + b.max.z) / 2);  // centre y & z, keep x so palm stays aligned with the fingers
    geo.computeVertexNormals();
    const m = new T.Mesh(geo, mat || white); m.castShadow = true; m.receiveShadow = true; return m;
  }

  // ---- pose / wave state ----
  let poser = null, waveNode = root;
  let cur = [12, 14, 12, 12, 16, 90], tgt = cur.slice();

  // scale + center any built node to a target height and seat it on the ground.
  // biasY (fraction of targetH) nudges the model down so a long forearm reads as
  // "entering from below" and the hand sits at the optical centre, not the wrist.
  // onAxis: keep the model's structural centreline (x=z=0) at screen centre instead
  // of the bounding-box centre — otherwise a protruding thumb skews the hand sideways.
  function frame(node, targetH, biasY, onAxis) {
    node.updateMatrixWorld(true);
    let box = new T.Box3().setFromObject(node);
    const size = new T.Vector3(); box.getSize(size);
    node.scale.multiplyScalar(targetH / Math.max(size.x, size.y, size.z));
    node.updateMatrixWorld(true);
    box = new T.Box3().setFromObject(node);
    const c = new T.Vector3(); box.getCenter(c); node.position.sub(c);
    if (onAxis) { node.position.x = 0; node.position.z = 0; }
    if (biasY) node.position.y += biasY * targetH;
    node.updateMatrixWorld(true);
    box = new T.Box3().setFromObject(node);
    groundY = box.min.y - 0.2; ground.position.y = groundY;
    root.add(node); waveNode = node;
  }

  // crisp silhouette: add a slightly inflated, back-faced dark copy of every mesh
  // (inverted-hull outline). Added as a CHILD of each mesh so it tracks pose for free.
  const outlineMat = new T.MeshBasicMaterial({ color: 0x39414f, side: T.BackSide });
  function addOutline(node, t) {
    const meshes = [];
    node.traverse((o) => { if (o.isMesh && !o.userData.outline && o.geometry && o.geometry.attributes.normal) meshes.push(o); });
    meshes.forEach((o) => {
      const g = o.geometry.clone();
      const p = g.attributes.position, n = g.attributes.normal;
      for (let i = 0; i < p.count; i++)
        p.setXYZ(i, p.getX(i) + n.getX(i) * t, p.getY(i) + n.getY(i) * t, p.getZ(i) + n.getZ(i) * t);
      p.needsUpdate = true;
      const ol = new T.Mesh(g, outlineMat);
      ol.userData.outline = true; ol.castShadow = false; ol.receiveShadow = false;
      o.add(ol);
    });
  }

  // ============================ optional GLB ============================
  function loadGLB(url) {
    new T.GLTFLoader().load(url, (g) => {
      const obj = g.scene; obj.traverse((o) => { if (o.isMesh) { o.castShadow = o.receiveShadow = true; if (o.material && "envMapIntensity" in o.material) o.material.envMapIntensity = 1; } });
      const holder = new T.Group(); holder.add(obj);
      const AX = { x: new T.Vector3(1, 0, 0), y: new T.Vector3(0, 1, 0), z: new T.Vector3(0, 0, 1) };
      holder.rotateOnWorldAxis(AX.z, Math.PI / 2); holder.rotateOnWorldAxis(AX.y, Math.PI / 2);
      const q = new URLSearchParams(location.search);
      [["mrx", AX.x], ["mry", AX.y], ["mrz", AX.z]].forEach(([k, ax]) => { const v = +(q.get(k) || 0); if (v) holder.rotateOnWorldAxis(ax, v); });
      frame(holder, 7.5);
    }, undefined, () => buildInMoov());
  }

  // ===================== procedural InMoov hand =======================
  // proportions in ~mm/30 units (hand≈187mm long). fingers: middle>ring>index>pinky
  function buildInMoov() {
    const model = new T.Group();

    // ---------- forearm shell (tapered, not bulbous) ----------
    const P = (x, y) => new T.Vector2(x, y);
    const forearm = new T.Mesh(new T.LatheGeometry([
      P(0.0, -6.9), P(0.52, -6.7), P(0.82, -5.95), P(1.0, -4.8),
      P(1.08, -3.5), P(1.06, -2.25), P(0.96, -1.15), P(0.86, -0.5), P(0.82, -0.1)], 56), white);
    forearm.castShadow = true; model.add(forearm);
    const elbow = new T.Mesh(new T.TorusGeometry(0.54, 0.16, 16, 36), metal);
    elbow.rotation.x = Math.PI / 2; elbow.position.y = -6.75; model.add(elbow);

    // ---------- dark wrist (servo bed) ----------
    const wmesh = new T.Mesh(new T.CylinderGeometry(0.76, 0.82, 0.74, 28), darkJ);
    wmesh.position.y = 0.25; wmesh.castShadow = true; model.add(wmesh);
    [0.08, 0.42].forEach((y) => { const r = new T.Mesh(new T.TorusGeometry(0.78, 0.05, 10, 30), darkJ); r.rotation.x = Math.PI / 2; r.position.y = y; model.add(r); });

    // ---------- hand (articulated) ----------
    const hand = new T.Group(); hand.position.y = 0.6; hand.rotation.x = -0.12; model.add(hand);
    const wrist = new T.Group(); hand.add(wrist);

    // palm plate (flat cover), top edge a touch wider
    const PHW = 1.3, PHH = 1.62, PHD = 0.34;   // half width / half length / half thick
    const palm = palmShell(PHW * 2, PHH * 2, PHD * 2, 0.78, 0.35, white);
    palm.position.y = PHH; wrist.add(palm);
    // subtle knuckle ridge across the top of the palm
    const knuck = shellBar(PHW * 1.9, 0.5, PHD * 1.7, 0.24, white);
    knuck.position.set(0, PHH * 2 - 0.1, 0.05); wrist.add(knuck);

    // a finger = tapering shell segments with dark hinge pins (visible joints)
    function makeFinger(segs, baseW, baseT) {
      const rootG = new T.Group(); const joints = []; let parent = rootG, wd = baseW, th = baseT;
      segs.forEach((len, i) => {
        const hingeR = wd * 0.52;
        const joint = new T.Group(); parent.add(joint); joints.push(joint);
        joint.add(pin(hingeR, wd * 1.1, darkJ));
        const ph = shellBar(wd, len, th, Math.min(th, wd) * 0.46, white); ph.position.y = len / 2 + hingeR * 0.6; joint.add(ph);
        if (i === segs.length - 1) { const tip = shellBar(wd * 0.86, len * 0.5, th * 0.9, th * 0.4, white); tip.position.y = len + hingeR * 0.3; joint.add(tip); }
        const next = new T.Group(); next.position.y = len + hingeR * 1.0; joint.add(next);
        parent = next; wd *= 0.9; th *= 0.92;
      });
      return { root: rootG, joints };
    }

    const CURL = -1, JMAX = [1.3, 1.5, 1.1], REST = [0.05, 0.08, 0.1];
    const TOP = PHH * 2;
    // [x, y, z, baseW, baseT, segLens, fanZ]  — real finger ratios
    const FDEF = [
      [-0.92, TOP - 0.18, 0.18, 0.42, 0.34, [1.3, 0.83, 0.67], 0.12],   // index
      [-0.31, TOP - 0.02, 0.2, 0.46, 0.37, [1.5, 0.93, 0.73], 0.02],    // middle (tallest)
      [0.31, TOP - 0.1, 0.19, 0.44, 0.36, [1.4, 0.87, 0.7], -0.05],     // ring
      [0.88, TOP - 0.34, 0.15, 0.37, 0.31, [1.05, 0.66, 0.58], -0.16],  // pinky (shortest)
    ];
    const fingers = FDEF.map(([x, y, z, bw, bt, segs, fz]) => {
      const f = makeFinger(segs, bw, bt);
      f.root.position.set(x, y, z); f.root.rotation.z = fz; f.root.rotation.x = -0.04; wrist.add(f.root); return f;
    });

    // thumb: dark mount on the lower side, angled out, 2 segments
    const tm = new T.Mesh(new T.CylinderGeometry(0.34, 0.34, 0.6, 20), darkJ);
    tm.rotation.set(0, 0, 0.95); tm.position.set(-1.32, 0.0, 0.12); tm.castShadow = true; wrist.add(tm);
    const thumb = makeFinger([1.3, 1.0], 0.42, 0.36);
    thumb.root.position.set(-1.44, -0.05, 0.14); thumb.root.rotation.set(0.45, -0.5, 1.05); wrist.add(thumb.root);

    const setCurl = (f, t, m) => f.joints.forEach((j, i) => { j.rotation.x = CURL * ((REST[i] || 0.1) + (m[i] || 1.2) * t); });
    waveNode = hand;
    poser = {
      apply(p) {
        for (let i = 0; i < 4; i++) setCurl(fingers[i], p[i + 1] / 180, JMAX);
        setCurl(thumb, p[0] / 180, [1.0, 0.9]);
        // wrist servo rotates the whole hand about the forearm (wrist) axis —
        // pronation/supination — NOT a side-to-side tilt.
        wrist.rotation.y = ((p[5] - 90) / 90) * 1.4;
      },
    };
    addOutline(model, 0.07);
    frame(model, 6.0, -0.1, true);
  }

  // dispatch: ?glb=<file> loads a static model; otherwise the InMoov hand
  const glbParam = new URLSearchParams(location.search).get("glb") || opts.url;
  if (glbParam && T.GLTFLoader) loadGLB(glbParam); else buildInMoov();

  // ============================ orbit ============================
  const _ry = new URLSearchParams(location.search).get("ry");
  let rotY = _ry !== null ? +_ry : Math.PI - 0.16, rotX = -0.03, tgtRotY = rotY, tgtRotX = rotX;
  let dragging = false, userActive = false, lastX = 0, lastY = 0;
  const el = renderer.domElement;
  el.style.touchAction = "none"; el.style.cursor = "grab";
  el.addEventListener("pointerdown", (e) => { dragging = true; userActive = true; el.style.cursor = "grabbing"; lastX = e.clientX; lastY = e.clientY; el.setPointerCapture && el.setPointerCapture(e.pointerId); });
  el.addEventListener("pointermove", (e) => { if (!dragging) return; tgtRotY += (e.clientX - lastX) * 0.01; tgtRotX += (e.clientY - lastY) * 0.01; tgtRotX = Math.max(-0.9, Math.min(0.9, tgtRotX)); lastX = e.clientX; lastY = e.clientY; });
  const endDrag = () => { dragging = false; el.style.cursor = "grab"; };
  el.addEventListener("pointerup", endDrag); el.addEventListener("pointercancel", endDrag);

  // ============================ loop ============================
  let waveT = 0, raf = null, alive = true;
  function loop() {
    if (!alive) return;
    raf = requestAnimationFrame(loop);
    for (let i = 0; i < 6; i++) cur[i] += (tgt[i] - cur[i]) * 0.15;
    if (poser) poser.apply(cur);
    if (!userActive) tgtRotY += 0.0030;
    rotY += (tgtRotY - rotY) * 0.12; rotX += (tgtRotX - rotX) * 0.12;
    root.rotation.y = rotY; root.rotation.x = rotX;
    if (waveNode) { if (waveT > 0) { waveT -= 0.016; waveNode.rotation.z = Math.sin((1.5 - waveT) * 11) * 0.26 * Math.min(1, waveT * 1.6); } else waveNode.rotation.z += (0 - waveNode.rotation.z) * 0.08; }
    renderer.render(scene, camera);
  }
  loop();

  const ro = new ResizeObserver(() => { camera.aspect = w() / h(); camera.updateProjectionMatrix(); renderer.setSize(w(), h()); });
  ro.observe(container);

  return {
    setPose(a) { if (a) tgt = a.slice(); },
    wave() { waveT = 1.5; },
    // mirror across X so a right-hand model reads as a left hand (matches the
    // user's physical prosthetic). Orbit still tracks the same drag direction.
    setMirror(on) { root.scale.x = on ? -1 : 1; },
    dispose() { alive = false; cancelAnimationFrame(raf); ro.disconnect(); renderer.dispose(); container.innerHTML = ""; },
  };
};
