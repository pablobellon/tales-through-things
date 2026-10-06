/*
 * Microphone: the voice feedback drawn inside the black disc during recording
 * ("dust waves": orbiting dots, each syllable sends a wave through them),
 * and the recording itself (16 kHz mono WAV, sent to the Mac for transcription).
 *
 * If the mic is unavailable (no permission, not HTTPS...), a gentle simulated
 * voice keeps it moving so the sequence still works.
 */

const GAIN = 3.2;      // base mic gain
const SENSITIVITY = 2.5; // overall multiplier: raise for a more reactive wave
const CURVE = 0.6;     // < 1 boosts quiet sounds more than loud ones (1 = linear)

let ctx = null;
let analyser = null;
let timeData, freqData;
let micState = 'idle'; // idle | pending | on | off
let recorder = null;   // ScriptProcessorNode tapping the mic
let chunks = null;     // Float32Array[] while recording, null otherwise
let preRoll = [];      // the last ~0.5 s before the press (people start talking as they press)
const PRE_ROLL_S = 0.5;

export async function initMic() {
  if (micState !== 'idle') return;
  micState = 'pending';
  try {
    const stream = await navigator.mediaDevices.getUserMedia({
      audio: { echoCancellation: false, noiseSuppression: false, autoGainControl: false },
    });
    ctx = new (window.AudioContext || window.webkitAudioContext)();
    analyser = ctx.createAnalyser();
    analyser.fftSize = 1024;
    analyser.smoothingTimeConstant = 0.5;
    const source = ctx.createMediaStreamSource(stream);
    source.connect(analyser);
    // raw samples for the recording (outputs silence, but must reach the destination to run)
    recorder = ctx.createScriptProcessor(4096, 1, 1);
    recorder.onaudioprocess = (e) => {
      const block = new Float32Array(e.inputBuffer.getChannelData(0));
      if (chunks) {
        chunks.push(block);
      } else {
        preRoll.push(block);
        while (preRoll.length > 1 && (preRoll.length - 1) * block.length > PRE_ROLL_S * ctx.sampleRate) {
          preRoll.shift();
        }
      }
    };
    source.connect(recorder);
    recorder.connect(ctx.destination);
    timeData = new Float32Array(analyser.fftSize);
    freqData = new Uint8Array(analyser.frequencyBinCount);
    micState = 'on';
  } catch (err) {
    console.warn('Microphone unavailable, using simulated wave:', err);
    micState = 'off';
  }
}

// Audio can only start after a user gesture: call this from key / touch handlers.
export function resumeAudio() {
  if (ctx && ctx.state !== 'running') ctx.resume().catch(() => {});
}

export function micStatus() {
  return micState;
}

export function startRecording() {
  chunks = preRoll;
  preRoll = [];
}

// Stop and return the recording as a WAV Blob (16 kHz mono, 16-bit).
// Without a mic, returns a short silent WAV so the flow still works (mock AI).
export function stopRecording() {
  const parts = chunks || [];
  chunks = null;
  const rate = ctx ? ctx.sampleRate : 16000;
  const total = parts.reduce((n, c) => n + c.length, 0);
  const merged = new Float32Array(total || 1600);
  let o = 0;
  for (const c of parts) { merged.set(c, o); o += c.length; }
  return encodeWav(downsample(merged, rate, 16000), 16000);
}

function downsample(data, from, to) {
  if (from === to) return data;
  const ratio = from / to;
  const out = new Float32Array(Math.floor(data.length / ratio));
  for (let i = 0; i < out.length; i++) {
    // average the source samples that fall into this output sample
    const a = Math.floor(i * ratio), b = Math.min(data.length, Math.floor((i + 1) * ratio));
    let sum = 0;
    for (let k = a; k < b; k++) sum += data[k];
    out[i] = sum / Math.max(1, b - a);
  }
  return out;
}

function encodeWav(samples, rate) {
  const buf = new ArrayBuffer(44 + samples.length * 2);
  const v = new DataView(buf);
  const str = (o, s) => { for (let i = 0; i < s.length; i++) v.setUint8(o + i, s.charCodeAt(i)); };
  str(0, 'RIFF'); v.setUint32(4, 36 + samples.length * 2, true); str(8, 'WAVE');
  str(12, 'fmt '); v.setUint32(16, 16, true); v.setUint16(20, 1, true); v.setUint16(22, 1, true);
  v.setUint32(24, rate, true); v.setUint32(28, rate * 2, true); v.setUint16(32, 2, true); v.setUint16(34, 16, true);
  str(36, 'data'); v.setUint32(40, samples.length * 2, true);
  for (let i = 0; i < samples.length; i++) {
    const x = Math.max(-1, Math.min(1, samples[i]));
    v.setInt16(44 + i * 2, x < 0 ? x * 0x8000 : x * 0x7fff, true);
  }
  return new Blob([buf], { type: 'audio/wav' });
}

export function createWave(canvas, size) {
  const g = canvas.getContext('2d');
  const levels = { low: 0, mid: 0, high: 0, all: 0 };
  let pr = 1;

  function readLevels(t) {
    let raw;
    if (micState === 'on' && ctx.state === 'running') {
      analyser.getFloatTimeDomainData(timeData);
      analyser.getByteFrequencyData(freqData);
      let sum = 0;
      for (let i = 0; i < timeData.length; i++) sum += timeData[i] * timeData[i];
      const band = (a, b) => {
        let s = 0;
        for (let i = a; i < b; i++) s += freqData[i];
        return s / ((b - a) * 255);
      };
      // ~47 Hz per bin at 48 kHz
      const boost = (x) => Math.pow(x * SENSITIVITY, CURVE);
      raw = {
        all: boost(Math.sqrt(sum / timeData.length) * GAIN),
        low: boost(band(2, 12) * 1.4),
        mid: boost(band(12, 60) * 1.8),
        high: boost(band(60, 200) * 2.4),
      };
    } else {
      // simulated "someone talking"
      const s = 0.18 + 0.14 * Math.sin(t * 2.3) * Math.sin(t * 0.7) + 0.08 * Math.sin(t * 7.1);
      raw = { all: s, low: s * 1.1, mid: s * 0.9, high: s * 0.6 };
    }
    for (const k in levels) {
      const v = Math.min(1, raw[k]);
      // fast attack, slower release
      levels[k] += (v - levels[k]) * (v > levels[k] ? 0.45 : 0.08);
    }
  }

  // ---- dust waves: points orbit the disc; each syllable sends a wave from the
  // centre that pushes the points it passes and lights them up (no ring drawn)
  const COLORS = ['#5F5DFF', '#A9A8FF', '#FFFFFF'];
  const sprites = COLORS.map((c) => {
    const s = document.createElement('canvas');
    s.width = s.height = 32;
    const sg = s.getContext('2d');
    const grad = sg.createRadialGradient(16, 16, 0, 16, 16, 16);
    grad.addColorStop(0, c); grad.addColorStop(0.55, c); grad.addColorStop(1, 'rgba(0,0,0,0)');
    sg.fillStyle = grad; sg.beginPath(); sg.arc(16, 16, 16, 0, Math.PI * 2); sg.fill();
    return s;
  });
  const DOTS = 900, LIFE = 2.6;
  const dots = Array.from({ length: DOTS }, () => ({
    r: 0.1 + Math.pow(Math.random(), 0.6) * 0.8, a: Math.random() * Math.PI * 2,
    sp: (0.08 + Math.random() * 0.25) * (Math.random() < 0.5 ? -1 : 1), z: Math.random(),
  }));
  let rings = [];
  let nextRing = 0, prevAll = 0, lastT = null;

  return {
    resize(stageScale) {
      pr = Math.min(3, (window.devicePixelRatio || 1) * stageScale);
      canvas.width = Math.round(size * pr);
      canvas.height = Math.round(size * pr);
    },
    draw(now) {
      const t = now / 1000;
      const dt = lastT === null ? 0.016 : Math.min(0.05, t - lastT);
      lastT = t;
      readLevels(t);
      const level = levels.all;

      // a syllable starts (sharp rise), or steady speech: a new wave
      const onset = level - prevAll > 0.08 && level > 0.2;
      prevAll = level;
      if ((onset || (level > 0.18 && t > nextRing)) && rings.length < 10) {
        rings.push({ born: t, power: 0.4 + level });
        nextRing = t + 0.38;
      }
      rings = rings.filter((r) => t - r.born < LIFE);
      const fronts = rings.map((r) => {
        const k = (t - r.born) / LIFE;
        return { rad: 0.06 + 0.88 * Math.sqrt(k), k, power: r.power };
      });

      const W = canvas.width;
      const R = (W / 2) * 0.92;
      const unit = W / 300; // dot sizes in a 300-unit disc
      g.setTransform(1, 0, 0, 1, 0, 0);
      g.clearRect(0, 0, W, W);
      g.translate(W / 2, W / 2);
      g.globalCompositeOperation = 'lighter';

      for (const d of dots) {
        d.a += d.sp * dt * (0.5 + level);
        let push = 0, glow = 0;
        for (const f of fronts) {
          const x = (d.r - f.rad) / 0.07;
          const w = Math.exp(-x * x) * f.power * (1 - f.k);
          push += w * 0.07;
          glow += w;
        }
        const r = R * Math.min(0.96, d.r + push + level * 0.015);
        const size = (1.3 + d.z * 1.6 + Math.min(2.6, glow * 2.3)) * unit;
        g.globalAlpha = Math.min(1, 0.3 + d.z * 0.25 + glow * 0.8);
        g.drawImage(sprites[glow > 0.5 ? 2 : d.z > 0.55 ? 1 : 0],
                    Math.cos(d.a) * r - size / 2, Math.sin(d.a) * r - size / 2, size, size);
      }
      // a small heart that beats with the voice
      g.globalCompositeOperation = 'source-over';
      g.globalAlpha = 0.9;
      g.drawImage(sprites[2], -R * (0.03 + 0.05 * level), -R * (0.03 + 0.05 * level),
                  R * (0.06 + 0.1 * level), R * (0.06 + 0.1 * level));
      g.globalAlpha = 1;
    },
  };
}
