/*
 * Dust text: texts in the disc gather from drifting dots into their letters
 * (like the objects' point clouds), then the crisp text takes over; when a text
 * leaves, its dots scatter outwards and fade.
 *
 * appear(el, delayMs)  → ms after which the crisp text should be visible
 * disappear(el)        → scatter the dots of a text that is being removed
 */

const MAX_DOTS = 3500;
const FLY_S = 1.0;      // one dot's flight
const SPREAD_S = 0.6;   // dots leave one after the other over this time
const SWAP_S = 0.15;    // when the dots land, the crisp text replaces them this fast
const OUT_S = 0.8;      // scattering when a text leaves

export function createDustText(canvas, discEl, size) {
  const g = canvas.getContext('2d');
  let pr = 1;
  let groups = []; // { dots, t0, mode: 'in' | 'out' }

  const sprites = ['#FFFFFF', '#A9A8FF', '#5F5DFF'].map((c) => {
    const s = document.createElement('canvas');
    s.width = s.height = 24;
    const sg = s.getContext('2d');
    const grad = sg.createRadialGradient(12, 12, 0, 12, 12, 12);
    grad.addColorStop(0, c); grad.addColorStop(0.5, c); grad.addColorStop(1, 'rgba(0,0,0,0)');
    sg.fillStyle = grad; sg.beginPath(); sg.arc(12, 12, 12, 0, Math.PI * 2); sg.fill();
    return s;
  });

  // where each word of `el` sits, in disc coordinates (CSS px of the 834×1194 stage)
  function wordBoxes(el) {
    const disc = discEl.getBoundingClientRect();
    const k = disc.width / size;
    const boxes = [];
    const walker = document.createTreeWalker(el, NodeFilter.SHOW_TEXT);
    for (let node = walker.nextNode(); node; node = walker.nextNode()) {
      const re = /\S+/g;
      for (let m = re.exec(node.textContent); m; m = re.exec(node.textContent)) {
        const range = document.createRange();
        range.setStart(node, m.index);
        range.setEnd(node, m.index + m[0].length);
        const r = range.getClientRects()[0];
        if (r) boxes.push({ word: m[0], x: (r.left - disc.left) / k, y: (r.top - disc.top) / k, h: r.height / k });
      }
    }
    return boxes;
  }

  // the letters as dots: draw the words off screen and sample their pixels
  function textDots(el) {
    const boxes = wordBoxes(el);
    if (!boxes.length) return [];
    const cs = getComputedStyle(el);
    const off = document.createElement('canvas');
    off.width = off.height = Math.ceil(size);
    const og = off.getContext('2d', { willReadFrequently: true });
    og.font = `${cs.fontWeight} ${cs.fontSize} ${cs.fontFamily}`;
    og.fillStyle = '#fff';
    og.textBaseline = 'middle';
    for (const b of boxes) og.fillText(b.word, b.x, b.y + b.h / 2 + parseFloat(cs.fontSize) * 0.06);
    const data = og.getImageData(0, 0, off.width, off.height).data;
    let pts = [];
    const step = parseFloat(cs.fontSize) > 30 ? 2 : 1.5;
    for (let y = 0; y < off.height; y += step) {
      for (let x = 0; x < off.width; x += step) {
        if (data[(Math.floor(y) * off.width + Math.floor(x)) * 4 + 3] > 110) pts.push([x, y]);
      }
    }
    if (pts.length > MAX_DOTS) pts = pts.sort(() => Math.random() - 0.5).slice(0, MAX_DOTS);
    let minX = Infinity, maxX = -Infinity;
    for (const [x] of pts) { minX = Math.min(minX, x); maxX = Math.max(maxX, x); }
    const R = size / 2;
    return pts.map(([x, y]) => {
      // start somewhere in the disc, drifting in from a random direction
      const a = Math.random() * Math.PI * 2, r = R * (0.35 + Math.random() * 0.6);
      return {
        tx: x, ty: y,
        sx: R + Math.cos(a) * r, sy: R + Math.sin(a) * r,
        // reveal roughly left to right, with some randomness
        delay: SPREAD_S * (0.6 * (x - minX) / Math.max(1, maxX - minX) + 0.4 * Math.random()),
        c: Math.random() < 0.7 ? 0 : Math.random() < 0.6 ? 1 : 2,
        s: 0.9 + Math.random() * 0.9,
      };
    });
  }

  const ease = (t) => (t < 0.5 ? 4 * t * t * t : 1 - Math.pow(-2 * t + 2, 3) / 2);

  return {
    resize(stageScale) {
      pr = Math.min(3, (window.devicePixelRatio || 1) * stageScale);
      canvas.width = canvas.height = Math.round(size * pr);
    },
    appear(el, delayMs = 0) {
      const dots = textDots(el);
      if (!dots.length) return 0;
      groups.push({ dots, t0: performance.now() / 1000 + delayMs / 1000, mode: 'in' });
      return delayMs + (SPREAD_S + FLY_S) * 1000; // the crisp text appears as the last dots land
    },
    disappear(el) {
      const dots = textDots(el);
      if (!dots.length) return;
      const R = size / 2;
      for (const d of dots) {
        // fly outwards from the letter, a little away from the centre
        const dx = d.tx - R, dy = d.ty - R, len = Math.hypot(dx, dy) || 1;
        const push = 40 + Math.random() * 90;
        d.sx = d.tx; d.sy = d.ty;
        d.ex = d.tx + (dx / len) * push + (Math.random() - 0.5) * 60;
        d.ey = d.ty + (dy / len) * push + (Math.random() - 0.5) * 60;
        d.delay = Math.random() * 0.15;
      }
      groups.push({ dots, t0: performance.now() / 1000, mode: 'out' });
    },
    clear() {
      groups = [];
      g.clearRect(0, 0, canvas.width, canvas.height);
    },
    draw(now) {
      const t = now / 1000;
      if (!groups.length) return;
      g.setTransform(1, 0, 0, 1, 0, 0);
      g.clearRect(0, 0, canvas.width, canvas.height);
      g.scale(pr, pr);
      g.globalCompositeOperation = 'lighter';
      groups = groups.filter((grp) => {
        const age = t - grp.t0;
        if (grp.mode === 'in') {
          const landed = SPREAD_S + FLY_S;
          if (age > landed + SWAP_S) return false;
          const fade = age > landed ? 1 - (age - landed) / SWAP_S : 1;
          for (const d of grp.dots) {
            const k = Math.min(1, Math.max(0, (age - d.delay) / FLY_S));
            if (k <= 0) continue;
            const e = ease(k);
            // a slight curve on the way in
            const wob = (1 - e) * 18 * Math.sin(d.delay * 40 + age * 3);
            const x = d.sx + (d.tx - d.sx) * e + wob, y = d.sy + (d.ty - d.sy) * e - wob * 0.5;
            const s = d.s * (1.6 - 0.6 * e);
            g.globalAlpha = Math.min(1, k * 2) * fade * (0.55 + 0.45 * e);
            g.drawImage(sprites[e > 0.95 ? 0 : d.c], x - s, y - s, s * 2, s * 2);
          }
        } else {
          if (age > OUT_S + 0.15) return false;
          for (const d of grp.dots) {
            const k = Math.min(1, Math.max(0, (age - d.delay) / OUT_S));
            const e = k * k;
            const x = d.sx + (d.ex - d.sx) * e, y = d.sy + (d.ey - d.sy) * e;
            const s = d.s * (1 + 0.5 * e);
            g.globalAlpha = (1 - k) * 0.9;
            g.drawImage(sprites[k < 0.3 ? 0 : d.c], x - s, y - s, s * 2, s * 2);
          }
        }
        return true;
      });
      if (!groups.length) g.clearRect(0, 0, canvas.width, canvas.height);
      g.globalAlpha = 1;
      g.globalCompositeOperation = 'source-over';
    },
  };
}
