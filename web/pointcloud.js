import * as THREE from './vendor/three.module.min.js';

/*
 * Turning point-cloud objects for the result page.
 *
 * Files are made by tools/convert_ply.py (scans) and tools/make_objects.py
 * (procedural objects), format in tools/pointfile.py. Points are shuffled,
 * so taking the first N is a uniform subsample.
 *
 * show(i) assembles object i from scattered points; if another object is on
 * screen, its points fly apart first. show(-1) just scatters the current one.
 */

const MAX_POINTS = 320000; // per object; lower this if the iPad struggles

const REVEAL_MS = 3200;   // points fly in and assemble
const SCATTER_MS = 900;   // points fly apart before the next object
const SPIN_SPEED = 0.55;  // rad / s

// debug: ?still=<seconds> freezes objects fully assembled at that rotation
const STILL_PARAM = new URLSearchParams(location.search).get('still');
const STILL = STILL_PARAM === null ? null : Number(STILL_PARAM) || 0;

const CACHE_SIZE = 8; // point clouds kept in memory (archive browsing + current visitor)

/**
 * show(url, tilt) assembles the point cloud at `url` (tilt = forward lean, radians);
 * if another object is on screen, its points fly apart first. show(null) just
 * scatters the current one. preload(url) fetches ahead of time.
 */
export function createPointCloud(canvas) {
  const renderer = new THREE.WebGLRenderer({ canvas, alpha: true, antialias: false });
  renderer.setClearColor(0x000000, 0);

  const scene = new THREE.Scene();
  const camera = new THREE.PerspectiveCamera(30, 1, 0.1, 100);
  camera.position.set(0, 0, 8.4);

  // a turntable: `tiltG` leans the plate towards the camera (per object: flat things
  // are seen from above), `spin` turns the object on it
  const pivot = new THREE.Group();
  pivot.position.y = 0.55; // sit above the text, like the mockup
  scene.add(pivot);
  const tiltG = new THREE.Group();
  pivot.add(tiltG);
  const spin = new THREE.Group();
  tiltG.add(spin);

  const uniforms = {
    uTime: { value: 0 },
    uReveal: { value: 0 },
    uSize: { value: 1.6 },
    uPR: { value: 1 },
  };
  const material = makeMaterial(uniforms);

  // url -> { group, loaded, used }
  const slots = new Map();
  function slot(url) {
    let s = slots.get(url);
    if (s && s.failed && url !== current) {
      // a download that failed (network hiccup, file being replaced): try again
      spin.remove(s.group);
      slots.delete(url);
      s = null;
    }
    if (!s) {
      const group = new THREE.Group();
      group.visible = url === current; // (re)created while on screen: show it once loaded
      spin.add(group);
      const created = { group, loaded: false, failed: false, used: 0 };
      s = created;
      slots.set(url, s);
      loadPoints(url, MAX_POINTS).then((geometry) => {
        if (slots.get(url) !== created) return geometry.dispose(); // evicted meanwhile
        group.add(new THREE.Points(geometry, material));
        created.loaded = true;
      }, (err) => {
        console.error(`Point cloud ${url} failed to load`, err);
        created.failed = true;
      });
    }
    s.used = performance.now();
    evict(url); // after `used` is set, or the newest slot looks the oldest and evicts itself
    return s;
  }
  function evict(keep) {
    if (slots.size <= CACHE_SIZE) return;
    const old = [...slots.entries()]
      .filter(([u]) => u !== current && u !== next && u !== keep)
      .sort((a, b) => a[1].used - b[1].used);
    for (const [u, s] of old.slice(0, slots.size - CACHE_SIZE)) {
      s.group.traverse((o) => o.geometry && o.geometry.dispose());
      spin.remove(s.group);
      slots.delete(u);
    }
  }

  let current = null;    // url on screen (null = nothing)
  let next = null;       // url waiting while the current one scatters
  let nextTilt = 0.12;
  let phase = 'in';      // 'in' (assembling / assembled) | 'out' (scattering)
  let phaseT0 = null;
  let spinT0 = null;
  let outFrom = 1;

  function setCurrent(url, tilt) {
    for (const [u, s] of slots) s.group.visible = u === url;
    current = url;
    tiltG.rotation.x = tilt;
    phase = 'in';
    phaseT0 = null; // starts on the first frame where the object is loaded
  }

  function clear() {
    current = next = null;
    for (const s of slots.values()) s.group.visible = false;
    renderer.clear();
  }

  return {
    resize(stageScale, size) {
      const pr = Math.min(3, (window.devicePixelRatio || 1) * stageScale);
      renderer.setPixelRatio(pr);
      renderer.setSize(size, size, false);
      uniforms.uPR.value = pr;
    },
    preload(url) {
      if (url) slot(url);
    },
    // true once the object at url has failed to download
    failed(url) {
      return !!(slots.get(url) || {}).failed;
    },
    show(url, tilt = 0.12) {
      if (url) slot(url);
      if (current === null) {
        if (url) { spinT0 = null; setCurrent(url, tilt); }
      } else if (url !== current || phase === 'out') {
        next = url;
        nextTilt = tilt;
        if (phase !== 'out') {
          phase = 'out';
          phaseT0 = performance.now();
          outFrom = uniforms.uReveal.value;
        }
      }
    },
    stop: clear,
    update(now) {
      if (current === null) return;
      if (spinT0 === null) spinT0 = now;
      const t = (now - spinT0) / 1000;
      uniforms.uTime.value = t;
      spin.rotation.y = -0.9 + t * SPIN_SPEED;

      if (phase === 'out') {
        const k = Math.min(1, (now - phaseT0) / SCATTER_MS);
        uniforms.uReveal.value = outFrom * (1 - k * k);
        if (k >= 1) {
          if (next === null) return clear();
          setCurrent(next, nextTilt);
        }
      } else {
        if (!slot(current).loaded) return;
        if (phaseT0 === null) phaseT0 = now;
        uniforms.uReveal.value = STILL !== null ? 1 : Math.min(1, (now - phaseT0) / REVEAL_MS);
      }
      if (STILL !== null) spin.rotation.y = -0.9 + STILL * SPIN_SPEED;

      renderer.render(scene, camera);
    },
  };
}

async function loadPoints(url, maxPoints) {
  const res = await fetch(url);
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  const buf = await res.arrayBuffer();
  const view = new DataView(buf);
  const total = view.getUint32(0, true);
  const scale = view.getFloat32(4, true);
  const n = Math.min(total, maxPoints);

  const q = new Int16Array(buf, 8, total * 4);
  const c = new Uint8Array(buf, 8 + total * 8, total * 4);

  const pos = new Float32Array(n * 3);
  const col = new Float32Array(n * 4);
  const start = new Float32Array(n * 3);
  const rand = new Float32Array(n);

  for (let i = 0; i < n; i++) {
    pos[i * 3] = q[i * 4] * scale;
    pos[i * 3 + 1] = q[i * 4 + 1] * scale;
    pos[i * 3 + 2] = q[i * 4 + 2] * scale;
    for (let k = 0; k < 4; k++) col[i * 4 + k] = c[i * 4 + k] / 255;

    // scattered start positions on a loose sphere shell
    const u = Math.random() * 2 - 1;
    const th = Math.random() * Math.PI * 2;
    const r = 1.5 + Math.random() * 1.2;
    const s = Math.sqrt(1 - u * u);
    start[i * 3] = r * s * Math.cos(th);
    start[i * 3 + 1] = r * u;
    start[i * 3 + 2] = r * s * Math.sin(th);
    rand[i] = Math.random();
  }

  const g = new THREE.BufferGeometry();
  g.setAttribute('position', new THREE.BufferAttribute(pos, 3));
  g.setAttribute('aColor', new THREE.BufferAttribute(col, 4));
  g.setAttribute('aStart', new THREE.BufferAttribute(start, 3));
  g.setAttribute('aRand', new THREE.BufferAttribute(rand, 1));
  return g;
}

/* ------------------------------------------------------------------ */
/*  Shader                                                             */
/* ------------------------------------------------------------------ */

function makeMaterial(uniforms) {
  return new THREE.ShaderMaterial({
    uniforms,
    vertexShader: /* glsl */ `
      attribute vec3 aStart;
      attribute vec4 aColor;
      attribute float aRand;
      uniform float uTime, uReveal, uSize, uPR;
      varying vec4 vColor;
      varying float vFade;

      void main() {
        // assemble bottom-to-top with some randomness
        float h = clamp((position.y + 1.0) * 0.5, 0.0, 1.0);
        float delay = 0.45 * h + 0.25 * aRand;
        float t = clamp(uReveal * 1.7 - delay, 0.0, 1.0);
        t = t * t * (3.0 - 2.0 * t);

        vec3 p = mix(aStart, position, t);
        // gentle shimmer while flying
        p += 0.02 * vec3(
          sin(uTime * 1.7 + aRand * 61.0),
          sin(uTime * 1.3 + aRand * 37.0),
          sin(uTime * 1.1 + aRand * 83.0)) * (1.0 - t);

        vec4 mv = modelViewMatrix * vec4(p, 1.0);
        gl_Position = projectionMatrix * mv;
        gl_PointSize = uSize * uPR * (0.7 + 0.6 * aRand) * (8.4 / -mv.z);

        vColor = aColor;
        vFade = 0.25 + 0.75 * t;
      }
    `,
    fragmentShader: /* glsl */ `
      varying vec4 vColor;
      varying float vFade;
      void main() {
        float d = length(gl_PointCoord - 0.5);
        if (d > 0.5) discard;
        float a = smoothstep(0.5, 0.2, d) * vColor.a * vFade * 0.75;
        // lift the colours a little so the cloud glows like the reference
        // real colours, with the darkest lifted a little so they still show on the black disc
        vec3 rgb = 0.16 + vColor.rgb * 1.05;
        gl_FragColor = vec4(min(rgb, 1.0), a);
      }
    `,
    transparent: true,
    // no depth: points blend over each other, so the inside shows through (x-ray look)
    depthWrite: false,
    depthTest: false,
    blending: THREE.NormalBlending,
  });
}
