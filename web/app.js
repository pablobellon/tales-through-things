import { createPointCloud } from './pointcloud.js';
import { createDustText } from './dusttext.js';
import {
  createWave, initMic, resumeAudio, micStatus, startRecording, stopRecording,
} from './wave.js';

/*
 * Tales Through Things: the iPad side.
 *
 *   intro → browse 3 memories → "would you like to turn one into an object?"
 *     not yet → 3 more memories → ask again
 *     yes     → theme questions (hold to answer) → generating → object + haiku
 *             → "add it to the archive?" → back to intro
 *
 * One button (space bar): a press moves on, holding records a spoken answer.
 * The Mac (server/main.py) does the AI work; this page only shows and records.
 */

/* ------------------------------------------------------------------ */
/*  Config                                                             */
/* ------------------------------------------------------------------ */

const COLORS = { orange: '#E3963E', blue: '#5F5DFF' };

const WIPE_MS = 1100;          // orange <-> blue circular wipe from the disc
const RECORD_FILL_MS = 10000;  // while recording, blue keeps growing (log curve) until this
const MIN_RECORD_MS = 250;     // shorter is an accidental tap: "hold the button" hint right away
                               // (otherwise the Mac checks whether anything was actually said)
const TAIL_MS = 250;           // keep listening a moment after release (end of a quick "yes")
const RETRY_MS = 3500;         // how long that hint (and the blue flashes) stay
const ERROR_FLASHES = 5;
const PRESS_LOCK_MS = 1200;    // ignore presses right after something new appears
const MEMORY_LOCK_MS = 2500;   // ...a bit longer for a memory (let it assemble)
const BROWSE_COUNT = 3;        // memories shown before the invitation
const IDLE_RESET_MS = 120000;  // nobody touches anything for 2 min → back to intro
const GENERATE_TIMEOUT_MS = 240000;
const GENERATING_LINE_MS = 14000; // next "generating" line after this long

const LINES = {                // overwritten by server/script.json at boot
  intro: ['I collect memories and turn them into objects.', 'Have a look at a few of them.'],
  invite: 'What about one of your memories? Would you like to turn it into an object?',
  unclear: 'Sorry, I didn’t catch that. Would you like to turn one of your memories into an object?',
  thanks: ['Thank you! I think I have enough to remember.', 'Let me turn your memory into an object.'],
  generating: ['Your memory is taking shape…', 'Gathering the light, the sounds, the textures…', 'Almost there…'],
  archive: 'Would you like to add your memory to the archive?',
  archived: 'Your memory has joined the collection.',
  not_archived: 'We’ll keep this one out of the archive.',
  retry: 'Hold the button while you speak to record.',
  error: 'Something went wrong. Let’s start again.',
};

// Disc geometry from the CSS variables (index.html)
const rootStyle = getComputedStyle(document.documentElement);
const DISC_R = parseFloat(rootStyle.getPropertyValue('--disc')) / 2;
const DISC_Y = parseFloat(rootStyle.getPropertyValue('--disc-y'));

/* ------------------------------------------------------------------ */
/*  DOM + stage scaling                                                */
/* ------------------------------------------------------------------ */

const bgEl = document.getElementById('bg');
const arcEl = document.getElementById('ring-arc');
arcEl.setAttribute('cy', DISC_Y);
arcEl.setAttribute('transform', `rotate(-126 417 ${DISC_Y})`);
const gbCanvas = document.getElementById('gb');
const waveCanvas = document.getElementById('wave');
const sayEls = [document.getElementById('say-a'), document.getElementById('say-b')];
const haikuEl = document.getElementById('haiku');
const dustCanvas = document.getElementById('dust');
const hud = document.getElementById('hud');

let stageScale = 1;
function fitStage() {
  stageScale = Math.min(innerWidth / 834, innerHeight / 1194);
  document.documentElement.style.setProperty('--k', stageScale);
  objects.resize(stageScale, DISC_R * 2);
  wave.resize(stageScale);
  dust.resize(stageScale);
}

/* ------------------------------------------------------------------ */
/*  Background wipe: colour grows out from behind the disc             */
/* ------------------------------------------------------------------ */

let bgTarget = 'orange';
let activeWipe = null;

const LOG_K = 2; // recording curve steepness
const logCurve = (t, T) => Math.log(1 + LOG_K * t) / Math.log(1 + LOG_K * T);
const logCurveInverse = (p, T) => (Math.exp(p * Math.log(1 + LOG_K * T)) - 1) / LOG_K;

function wipeTo(name, slow = false) {
  if (name === bgTarget) return;
  const from = bgTarget;
  bgTarget = name;
  const now = performance.now();
  if (from === 'blue' && name === 'orange') return retract(now);

  if (activeWipe && activeWipe.mode === 'retract' && activeWipe.color === COLORS[name]) {
    const p0 = activeWipe.p;
    activeWipe.mode = slow ? 'log' : 'grow';
    activeWipe.t0 = slow ? now - logCurveInverse(p0, RECORD_FILL_MS / 1000) * 1000 : now;
    activeWipe.p0 = p0;
    return;
  }
  const el = document.createElement('div');
  el.className = 'wipe';
  bgEl.appendChild(el);
  activeWipe = { el, color: COLORS[name], mode: slow ? 'log' : 'grow', t0: now, p0: 0, p: 0 };
  updateWipe(now);
}

function retract(now) {
  let el, p0;
  if (activeWipe && activeWipe.color === COLORS.blue) {
    ({ el, p: p0 } = activeWipe);
  } else {
    el = document.createElement('div');
    el.className = 'wipe';
    bgEl.appendChild(el);
    p0 = 1;
  }
  setBase(COLORS.orange);
  for (const w of [...bgEl.children]) if (w !== el) w.remove();
  activeWipe = { el, color: COLORS.blue, mode: 'retract', t0: now, p0, p: p0 };
  updateWipe(now);
}

function updateWipe(now) {
  if (!activeWipe) return;
  const w = activeWipe;
  const t = (now - w.t0) / 1000;
  let done;
  if (w.mode === 'log') {
    w.p = Math.min(1, logCurve(t, RECORD_FILL_MS / 1000));
    done = w.p >= 1;
  } else {
    const k = Math.min(1, (t * 1000) / WIPE_MS);
    const e = easeInOutCubic(k);
    w.p = w.mode === 'grow' ? w.p0 + (1 - w.p0) * e : w.p0 * (1 - e);
    done = k >= 1;
  }
  drawWipe(w.el, w.color, w.p);
  if (done) {
    w.el.remove();
    for (const el of [...bgEl.children]) el.remove();
    if (w.mode !== 'retract') setBase(w.color);
    activeWipe = null;
  }
}

function setBase(color) {
  bgEl.style.background = color;
  document.documentElement.style.background = color;
  document.body.style.background = color;
}

function drawWipe(el, color, p) {
  const cx = innerWidth / 2;
  const cy = innerHeight / 2 + (DISC_Y - 597) * stageScale;
  const box = bgEl.getBoundingClientRect();
  const discR = DISC_R * stageScale;
  const far = Math.hypot(Math.max(cx, innerWidth - cx), Math.max(cy, innerHeight - cy));
  const band = 0.35 * far;
  const r = discR - band + (far - discR + band) * p;
  const c0 = hexA(color, 0), c55 = hexA(color, 0.55);
  el.style.background = `radial-gradient(circle at ${cx - box.left}px ${cy - box.top}px,
    ${color} 0px, ${color} ${Math.max(0, r)}px,
    ${c55} ${Math.max(0, r + band * 0.5)}px, ${c0} ${Math.max(0, r + band)}px)`;
}

function hexA(hex, a) {
  const n = parseInt(hex.slice(1), 16);
  return `rgba(${(n >> 16) & 255}, ${(n >> 8) & 255}, ${n & 255}, ${a})`;
}

/* ------------------------------------------------------------------ */
/*  Ring around the disc                                               */
/*   - question progress arc  - thinking (thin full ring, breathing)   */
/*   - generating (thick breathing ring)  - error flashes              */
/* ------------------------------------------------------------------ */

// A ring of a given thickness, with its inner edge tucked just under the disc
const ringR = (width) => DISC_R - 2 + width / 2;
const RING_Q = 56; // progress arc thickness

const ring = { frac: 0, sw: RING_Q, opacity: 1 };
let ringTween = null;
let breath = null;     // { a, b, period, t0 }: thickness oscillates between a and b
let errorAnim = null;  // { t0, restore }

function tweenRing(to, ms, ease = easeInOutCubic) {
  ringTween = { from: { ...ring }, to, t0: performance.now(), ms, ease };
}

function breathe(a, b, period) {
  breath = a === null ? null : { a, b, period, t0: performance.now() };
}

function updateRing(now) {
  if (ringTween) {
    const { from, to, t0, ms, ease } = ringTween;
    const p = Math.min(1, (now - t0) / ms);
    for (const k in to) ring[k] = from[k] + (to[k] - from[k]) * ease(p);
    if (p >= 1) ringTween = null;
  }
  if (breath) {
    const t = (now - breath.t0) / breath.period;
    const p = 0.5 - 0.5 * Math.cos(t * Math.PI * 2);
    ring.sw = breath.a + (breath.b - breath.a) * p;
  }
  if (errorAnim) {
    const t = (now - errorAnim.t0) / RETRY_MS;
    if (t < 1) {
      Object.assign(ring, { frac: 1, opacity: 1, sw: 44 * Math.abs(Math.sin(t * Math.PI * ERROR_FLASHES)) });
    } else {
      Object.assign(ring, { frac: errorAnim.restore.frac, sw: 0 });
      tweenRing(errorAnim.restore, 500, easeOutCubic);
      errorAnim = null;
    }
  }
  const r = ringR(Math.max(0, ring.sw));
  const C = 2 * Math.PI * r;
  arcEl.setAttribute('r', r.toFixed(2));
  arcEl.setAttribute('stroke-width', Math.max(0, ring.sw).toFixed(2));
  arcEl.setAttribute('stroke-dasharray', `${(C * ring.frac).toFixed(2)} ${C.toFixed(2)}`);
  arcEl.setAttribute('opacity', Math.max(0, ring.opacity).toFixed(3));
}

// the ring's resting state (what it goes back to after thinking / errors)
let ringRest = { frac: 0, sw: RING_Q, opacity: 0 };
function restRing(state, ms = 900) {
  ringRest = { frac: 0, sw: RING_Q, opacity: 1, ...state };
  breathe(null);
  if (!errorAnim) tweenRing(ringRest, ms);
}

// while the Mac works (transcribing, choosing the next question): a thin breathing ring
let thinkingOn = false;
function thinking(on) {
  thinkingOn = on;
  if (on) {
    breathe(null);
    tweenRing({ frac: 1, opacity: 0.9, sw: 15 }, 500);
    setTimeout(() => { if (thinkingOn) breathe(8, 22, 1100); }, 500);
  } else {
    restRing(ringRest, 500);
  }
}

function generatingRing(on) {
  thinkingOn = false;
  if (on) {
    tweenRing({ frac: 1, opacity: 1, sw: 36 }, 900);
    setTimeout(() => breathe(36, 130, 1250), 900);
  } else {
    breathe(null);
    tweenRing({ sw: 0, opacity: 0 }, 900, easeOutCubic);
    ringRest = { frac: 0, sw: RING_Q, opacity: 0 };
  }
}

function errorFlash() {
  ringTween = null;
  breath = null;
  errorAnim = { t0: performance.now(), restore: ringRest };
}

const easeInOutCubic = (t) => (t < 0.5 ? 4 * t * t * t : 1 - Math.pow(-2 * t + 2, 3) / 2);
const easeOutCubic = (t) => 1 - Math.pow(1 - t, 3);

/* ------------------------------------------------------------------ */
/*  Text in the disc                                                   */
/* ------------------------------------------------------------------ */

let sayIndex = 0;
let sayText = '';
const SAY_MAX = 47, SAY_MIN = 24;

// Show a line in the disc (crossfade). Font size shrinks until it fits.
// a text leaves: its letters scatter as dust
function hideText(el) {
  if (!el.classList.contains('on')) return;
  dust.disappear(el);
  el.style.transition = 'opacity 250ms ease';
  el.classList.remove('on');
}

// a text arrives: dust gathers into its letters, then the crisp text takes over
function revealText(el, delayMs = 0) {
  const at = dust.appear(el, delayMs);
  el.style.transition = `opacity 600ms ease ${at}ms`;
  el.classList.add('on');
}

function say(text) {
  sayText = text || '';
  const out = sayEls[sayIndex];
  sayIndex = 1 - sayIndex;
  const el = sayEls[sayIndex];
  hideText(out);
  if (!text) return;
  el.textContent = '';
  const span = document.createElement('span');
  span.textContent = text;
  el.appendChild(span);
  const maxH = DISC_R * 2 * 0.62;
  let size = SAY_MAX;
  el.style.fontSize = size + 'px';
  while (size > SAY_MIN && (span.offsetHeight > maxH || span.offsetWidth > el.clientWidth)) {
    size -= 2;
    el.style.fontSize = size + 'px';
  }
  revealText(el, 200); // just after the previous text has scattered
  waveCanvas.classList.remove('on');
}

function showHaiku(lines) {
  hideText(haikuEl);
  if (!lines) return;
  haikuEl.textContent = '';
  lines.forEach((l, i) => {
    if (i) haikuEl.appendChild(document.createElement('br'));
    haikuEl.appendChild(document.createTextNode(l));
  });
  // a little wrapper so the lines stay centred as a block
  const block = document.createElement('div');
  while (haikuEl.firstChild) block.appendChild(haikuEl.firstChild);
  haikuEl.appendChild(block);
  revealText(haikuEl, 1200); // once the object has started to assemble
}

/* ------------------------------------------------------------------ */
/*  Server                                                             */
/* ------------------------------------------------------------------ */

// Calls the Mac. Throws Reset if the experience was reset while waiting,
// so a late answer never leaks into the next visitor's flow.
async function api(path, { method = 'GET', body, timeout = 90000 } = {}) {
  const id = runId;
  const ctl = new AbortController();
  const timer = setTimeout(() => ctl.abort(), timeout);
  try {
    const res = await fetch(path, {
      method, body, signal: ctl.signal, cache: 'no-store',
      headers: body instanceof Blob ? { 'Content-Type': body.type } : { 'Content-Type': 'application/json' },
    });
    const data = await res.json();
    if (id !== runId) throw new Reset();
    if (!res.ok) throw new Error(data.error || `HTTP ${res.status}`);
    return data;
  } finally {
    clearTimeout(timer);
  }
}

/* ------------------------------------------------------------------ */
/*  Input: press to continue, hold to answer                           */
/* ------------------------------------------------------------------ */

class Reset extends Error {}

let runId = 0;          // bumps on every reset: stale waits throw Reset
let waiter = null;      // { kind: 'press' | 'record', lockUntil, resolve, reject, ... }
let lastInput = performance.now();
let state = 'boot';     // for the HUD and idle reset

// wait for a press of the button
function waitPress(lockMs = PRESS_LOCK_MS) {
  return new Promise((resolve, reject) => {
    waiter = { kind: 'press', lockUntil: performance.now() + lockMs, resolve, reject };
  });
}

// wait for a spoken answer: hold to record, release to send; returns a WAV Blob
function recordAnswer(lockMs = PRESS_LOCK_MS) {
  return new Promise((resolve, reject) => {
    waiter = { kind: 'record', lockUntil: performance.now() + lockMs, resolve, reject,
               recording: false, t0: 0, retryTimer: null };
  });
}

function sleep(ms) {
  const id = runId;
  return new Promise((resolve, reject) => setTimeout(() => (id === runId ? resolve() : reject(new Reset())), ms));
}

let spaceHeld = false;

function onPress() {
  resumeAudio();
  lastInput = performance.now();
  if (spaceHeld) return;
  spaceHeld = true;
  const w = waiter;
  if (!w || performance.now() < w.lockUntil) return;
  if (w.kind === 'press') {
    waiter = null;
    w.resolve();
  } else if (w.kind === 'record' && !w.recording) {
    clearTimeout(w.retryTimer);
    w.recording = true;
    w.t0 = performance.now();
    w.question = w.question ?? sayText;
    startRecording();
    errorAnim = null;
    wipeTo('blue', true);
    sayEls.forEach(hideText); // the question dissolves as the visitor speaks
    waveCanvas.classList.add('on');
    state = state.replace(/ \(recording\)$/, '') + ' (recording)';
  }
}

function onRelease() {
  lastInput = performance.now();
  if (!spaceHeld) return;
  spaceHeld = false;
  const w = waiter;
  if (!w || w.kind !== 'record' || !w.recording) return;
  w.recording = false;
  state = state.replace(/ \(recording\)$/, '');
  wipeTo('orange');
  waveCanvas.classList.remove('on');
  if (performance.now() - w.t0 < MIN_RECORD_MS) {
    // an accidental tap: hint + blue flashes, then the question again (or hold right away)
    stopRecording();
    say(LINES.retry);
    errorFlash();
    w.retryTimer = setTimeout(() => { if (waiter === w && !w.recording) say(w.question); }, RETRY_MS);
    return;
  }
  waiter = null;
  setTimeout(() => w.resolve(stopRecording()), TAIL_MS);
}

// nothing was heard in the recording (decided by the Mac): hint, then ask again
async function nothingHeard() {
  say(LINES.retry);
  errorFlash();
  await sleep(RETRY_MS);
}

const isSpace = (e) => e.code === 'Space' || e.key === ' ' || e.key === 'Spacebar';

addEventListener('keydown', (e) => {
  if (isSpace(e)) {
    e.preventDefault();
    if (!e.repeat) onPress();
    return;
  }
  const k = e.key.toLowerCase();
  if (k === 'r' || k === 'escape') reset();
  else if (k === 'h') hud.classList.toggle('on');
  else if (k === 'f') goFullscreen();
});
addEventListener('keyup', (e) => {
  if (isSpace(e)) { e.preventDefault(); onRelease(); }
});
addEventListener('blur', onRelease);
addEventListener('pointerdown', (e) => { e.preventDefault(); goFullscreen(); onPress(); });
addEventListener('pointerup', onRelease);
addEventListener('pointercancel', onRelease);
addEventListener('contextmenu', (e) => e.preventDefault());
// The page is a bit taller than the screen on purpose (#extend): never let it scroll.
addEventListener('scroll', () => { if (scrollX || scrollY) scrollTo(0, 0); }, { passive: true });

function goFullscreen() {
  const el = document.documentElement;
  if (document.fullscreenElement || document.webkitFullscreenElement) return;
  const req = el.requestFullscreen || el.webkitRequestFullscreen;
  if (req) { try { req.call(el)?.catch?.(() => {}); } catch {} }
}

/* ------------------------------------------------------------------ */
/*  The experience                                                     */
/* ------------------------------------------------------------------ */

let session = null; // current visitor's session id (to discard it on reset)
let seen = new Set();

async function intro() {
  state = 'intro';
  objects.show(null);
  showHaiku(null);
  restRing({ frac: 0, opacity: 0 });
  say(LINES.intro[0]);
  await sleep(3500);
  say(LINES.intro[1]);
  await waitPress();
}

function shuffle(items) {
  const a = [...items];
  for (let i = a.length - 1; i > 0; i--) {
    const j = Math.floor(Math.random() * (i + 1));
    [a[i], a[j]] = [a[j], a[i]];
  }
  return a;
}

async function browse() {
  state = 'browse';
  let list = [];
  try { list = await api('/api/collection'); } catch (e) { console.warn(e); }
  if (!list.length) return;
  // 3 memories at random among those not seen yet in this visit (every memory gets its turn)
  let pool = list.filter((m) => !seen.has(m.id));
  if (pool.length < BROWSE_COUNT) { seen = new Set(); pool = list; }
  pool = shuffle(pool).slice(0, BROWSE_COUNT);
  pool.forEach((m) => objects.preload(m.points));

  say('');
  for (let i = 0; i < pool.length; i++) {
    const m = pool[i];
    seen.add(m.id);
    state = `browse ${i + 1}/${pool.length}`;
    gbCanvas.classList.add('on');
    objects.show(m.points, m.tilt);
    showHaiku(m.haiku);
    await waitPress(MEMORY_LOCK_MS);
  }
  objects.show(null);
  showHaiku(null);
}

// ask a yes/no question by voice; returns 'yes' or 'no'
async function askYesNo(key) {
  let text = LINES[key];
  for (;;) {
    state = `ask ${key}`;
    say(text);
    const wav = await recordAnswer();
    say('');
    thinking(true);
    const res = await api(`/api/yesno?q=${key}`, { method: 'POST', body: wav });
    thinking(false);
    if (res.answer === 'yes' || res.answer === 'no') return res.answer;
    if (res.answer === 'empty') { await nothingHeard(); continue; }
    text = key === 'invite' ? LINES.unclear : LINES[key];
  }
}

async function createMemory() {
  state = 'starting';
  thinking(true);
  let r = await api('/api/session', { method: 'POST' });
  session = r.session;
  thinking(false);

  // questions
  for (;;) {
    state = `question ${r.index}/${r.total}`;
    restRing({ frac: (r.index - 1) / r.total });
    say(r.question);
    const wav = await recordAnswer();
    say('');
    restRing({ frac: r.index / r.total }, 600);
    thinking(true);
    const next = await api(`/api/session/${session}/answer`, { method: 'POST', body: wav });
    thinking(false);
    if (next.done) break;
    if (next.empty) await nothingHeard(); // then the same question again
    r = next;
  }

  // thanks, then generating (the server is already working on it)
  state = 'thanks';
  restRing({ frac: 1 });
  say(LINES.thanks[0]);
  await sleep(3200);
  say(LINES.thanks[1]);
  await sleep(2800);
  state = 'generating';
  generatingRing(true);
  say(LINES.generating[0]);
  const t0 = performance.now();
  let line = 0;
  let memory = null;
  while (!memory) {
    await sleep(1500);
    // a new line now and then, so a long wait never looks stuck (the last one stays)
    const due = Math.min(LINES.generating.length - 1, Math.floor((performance.now() - t0) / GENERATING_LINE_MS));
    if (due > line) say(LINES.generating[(line = due)]);
    const s = await api(`/api/session/${session}`);
    state = `generating (${s.stage || '…'})`;
    if (s.status === 'ready') memory = s.memory;
    else if (s.status === 'error') throw new Error('generation failed');
    if (performance.now() - t0 > GENERATE_TIMEOUT_MS) throw new Error('generation timed out');
  }

  // the memory object
  state = 'result';
  objects.preload(memory.points);
  say('');
  generatingRing(false);
  gbCanvas.classList.add('on');
  objects.show(memory.points, memory.tilt);
  showHaiku(memory.haiku);
  await waitPress(MEMORY_LOCK_MS + 1500);

  // archive?
  objects.show(null);
  showHaiku(null);
  const keep = (await askYesNo('archive')) === 'yes';
  await api(`/api/session/${session}/finish`, { method: 'POST', body: JSON.stringify({ keep }) });
  session = null;
  if (keep) seen = new Set(); // let it show up in the collection right away
  state = 'archived';
  say(keep ? LINES.archived : LINES.not_archived);
  await sleep(4500);
}

async function experience() {
  const id = runId;
  try {
    for (;;) {
      await intro();
      for (;;) {
        await browse();
        if ((await askYesNo('invite')) === 'yes') break;
      }
      await createMemory();
    }
  } catch (err) {
    if (err instanceof Reset || id !== runId) return; // a reset already restarted things
    console.error(err);
    state = 'error';
    discardSession();
    thinking(false);
    generatingRing(false);
    objects.show(null);
    showHaiku(null);
    say(LINES.error);
    setTimeout(() => { if (id === runId) reset(); }, 4000);
  }
}

function discardSession() {
  if (!session) return;
  fetch(`/api/session/${session}/finish`, { method: 'POST', body: '{"keep":false}' }).catch(() => {});
  session = null;
}

// back to the intro, from anywhere
function reset() {
  runId++;
  if (waiter) {
    clearTimeout(waiter.retryTimer);
    if (waiter.recording) stopRecording();
    waiter.reject(new Reset());
    waiter = null;
  }
  discardSession();
  seen = new Set();
  errorAnim = null;
  breathe(null);
  waveCanvas.classList.remove('on');
  wipeTo('orange');
  experience();
}

/* ------------------------------------------------------------------ */
/*  HUD (press H) + idle reset                                         */
/* ------------------------------------------------------------------ */

setInterval(() => {
  hud.textContent = `${state}\nmic: ${micStatus()}${session ? `\nsession: ${session}` : ''}\n` +
    '[space] press/hold · [R] reset · [F] fullscreen · [H] hide';
  const waitingForVisitor = waiter && !waiter.recording && !state.startsWith('intro');
  if (waitingForVisitor && performance.now() - lastInput > IDLE_RESET_MS) reset();
}, 1000);

/* ------------------------------------------------------------------ */
/*  Boot                                                               */
/* ------------------------------------------------------------------ */

const objects = createPointCloud(gbCanvas);
const wave = createWave(waveCanvas, DISC_R * 2);
const dust = createDustText(dustCanvas, document.getElementById('disc'), DISC_R * 2);
initMic();
addEventListener('resize', fitStage);
fitStage();

let waveUntil = 0;
function frame(now) {
  updateRing(now);
  updateWipe(now);
  objects.update(now);
  dust.draw(now);
  if (waiter && waiter.recording) waveUntil = now + 800;
  if (now < waveUntil) wave.draw(now);
  requestAnimationFrame(frame);
}
requestAnimationFrame(frame);

// Review: ?memory=<id> shows one archived memory (press R to leave)
const reviewId = new URLSearchParams(location.search).get('memory');
async function review(id) {
  state = 'review';
  const m = (await api('/api/collection')).find((x) => x.id === id);
  if (!m) return say(`No memory "${id}"`);
  gbCanvas.classList.add('on');
  objects.show(m.points, m.tilt);
  showHaiku(m.haiku);
}

api('/api/script').then((lines) => Object.assign(LINES, lines)).catch(() => {})
  .finally(() => (reviewId ? review(reviewId) : experience()));
