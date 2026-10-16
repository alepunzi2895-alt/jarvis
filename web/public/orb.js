/*
 * JARVIS — bolla centrale animata (canvas 3D, sfera di nodi/connessioni).
 *
 * Adattato da un riferimento HTML fornito da Alessandro (2026-09-15, "JARVIS
 * core") — stessa idea (sfera di punti proiettata in 3D, impulsi che
 * viaggiano lungo gli archi, stati con colore/energia diversi), ma senza il
 * suo websocket/mic/clock/scorciatoie da tastiera: qui gira DENTRO la
 * dashboard esistente, che ha gia' i propri segnali di stato (task in corso,
 * mic in ascolto, TTS in corso via Turso) — niente bisogno di un canale
 * separato. Confinato al contenitore #jarvis-orb (non piu' schermo intero)
 * cosi' convive con le finestre flottanti/dock gia' presenti.
 *
 * Stili (2026-10-16): "liscia" (default) e "globo" sono rotondi, con bordo e
 * alone circolari, gli stessi del quadrante Clockology; "originale" e' la
 * sfera di prima, rifiutata perche' "non sembra un cerchio perfetto" (raggio
 * dei nodi irregolare, bordo a poligono). Propagazione degli impulsi sotto
 * la soglia delle cascate: con 0,7 l'intera sfera si accende ogni ~1 s.
 */

const ORB_STYLES = {
  liscia:    { nodes: 170, jitter: false, wobble: 0.006, glow: 0.02, radius: 0.37, spread: 0.32, rim: true },
  globo:     { globe: true, jitter: false, wobble: 0.006, glow: 0.02, radius: 0.37, spread: 0.26, rim: true },
  originale: { nodes: 110, jitter: true,  wobble: 0.025, glow: 0.05, radius: 0.42, spread: 0.7,  rim: false },
};

const ORB_STATES = {
  idle:      { hue: 205, rot: 0.0018, fire: 0.012, speed: 0.014 },
  listening: { hue: 205, rot: 0.0035, fire: 0.03,  speed: 0.022 },
  thinking:  { hue: 38,  rot: 0.011,  fire: 0.22,  speed: 0.045 },
  speaking:  { hue: 150, rot: 0.005,  fire: 0.05,  speed: 0.03  },
  alert:     { hue: 356, rot: 0.007,  fire: 0.12,  speed: 0.04, jitter: 1 },
};

function createJarvisOrb(canvas, { style = "liscia" } = {}) {
  const S = ORB_STYLES[style] || ORB_STYLES.liscia;
  const cx = canvas.getContext("2d");
  const mobile = matchMedia("(max-width: 860px)");
  const reducedMotion = matchMedia("(prefers-reduced-motion: reduce)");
  let W = 0, H = 0, dpr = Math.min(window.devicePixelRatio || 1, 2);
  let state = "idle", P = { ...ORB_STATES.idle };
  let hue = ORB_STATES.idle.hue;
  let level = 0, targetLevel = 0, lastLevelAt = 0;
  let rotY = 0, rotX = 0.35, t = 0;
  let running = false;
  let frame = 0, lastDraw = 0;

  const K = 3;
  const nodes = [];
  const edges = [];
  const pulses = [];

  function resize() {
    dpr = Math.min(window.devicePixelRatio || 1, mobile.matches ? 1.5 : 2);
    const rect = canvas.parentElement.getBoundingClientRect();
    W = rect.width; H = rect.height;
    canvas.width = W * dpr; canvas.height = H * dpr;
    canvas.style.width = W + "px"; canvas.style.height = H + "px";
    cx.setTransform(dpr, 0, 0, dpr, 0, 0);
    if (nodes.length && reducedMotion.matches) draw();
  }

  function addNode(x, y, z) {
    nodes.push({ x, y, z, e: 0, ref: 0, h: hue, sx: 0, sy: 0, sz: 0, ph: Math.random() * 6.28 });
  }

  function buildSphere() {
    if (S.globe) buildGlobe(); else buildKnnSphere();
    nodes.forEach((n, i) => { n.nb = edges.filter((e) => e[0] === i || e[1] === i).map((e) => (e[0] === i ? e[1] : e[0])); });
  }

  // Nodi su 12 paralleli, archi lungo i paralleli e verso il nodo piu' vicino
  // del parallelo successivo.
  function buildGlobe() {
    const rows = [], LAT = 12;
    for (let a = 0; a < LAT; a++) {
      const phi = -Math.PI / 2 + Math.PI * (a + 0.5) / LAT, r = Math.cos(phi), y = Math.sin(phi);
      const M = Math.max(6, Math.round(22 * r)), row = [];
      for (let b = 0; b < M; b++) {
        const th = (2 * Math.PI * b) / M + a * 0.26;
        row.push(nodes.length);
        addNode(Math.cos(th) * r, y, Math.sin(th) * r);
      }
      rows.push(row);
    }
    rows.forEach((row) => row.forEach((i, b) => edges.push([i, row[(b + 1) % row.length]])));
    for (let a = 0; a + 1 < rows.length; a++) rows[a].forEach((i) => {
      const n = nodes[i];
      let best = -1, bd = 9;
      rows[a + 1].forEach((j) => { const m = nodes[j], d = (n.x - m.x) ** 2 + (n.z - m.z) ** 2; if (d < bd) { bd = d; best = j; } });
      edges.push([i, best]);
    });
  }

  function buildKnnSphere() {
    const N = S.nodes, ga = Math.PI * (3 - Math.sqrt(5));
    for (let i = 0; i < N; i++) {
      const y = 1 - (i / (N - 1)) * 2, r = Math.sqrt(1 - y * y), th = ga * i;
      const j = S.jitter ? 0.88 + Math.random() * 0.2 : 1;
      addNode(Math.cos(th) * r * j, y * j, Math.sin(th) * r * j);
    }
    const seen = new Set();
    nodes.forEach((a, i) => {
      nodes
        .map((b, j) => [j, (a.x - b.x) ** 2 + (a.y - b.y) ** 2 + (a.z - b.z) ** 2])
        .filter(([j]) => j !== i)
        .sort((p, q) => p[1] - q[1])
        .slice(0, K)
        .forEach(([j]) => {
          const key = i < j ? i + "-" + j : j + "-" + i;
          if (!seen.has(key)) { seen.add(key); edges.push([i, j]); }
        });
    });
  }

  function fire(i, h) {
    const n = nodes[i];
    if (!n || n.ref > 0) return;
    n.e = 1; n.ref = 30; n.h = h;
    n.nb.forEach((j) => { if (Math.random() < S.spread) pulses.push({ a: i, b: j, p: 0, h }); });
  }

  function project() {
    const R = Math.min(W, H) * S.radius * (1 + level * 0.18);
    const cy = Math.cos(rotY), sy = Math.sin(rotY), cxr = Math.cos(rotX), sxr = Math.sin(rotX);
    const f = R * 3.2;
    nodes.forEach((n) => {
      const wob = 1 + Math.sin(t * 0.02 + n.ph) * S.wobble + n.e * S.glow;
      const x = n.x * wob, y = n.y * wob, z = n.z * wob;
      const x1 = x * cy - z * sy, z1 = x * sy + z * cy;
      const y1 = y * cxr - z1 * sxr, z2 = y * sxr + z1 * cxr;
      const s = f / (f - z2 * R);
      n.sx = W / 2 + x1 * R * s;
      n.sy = H / 2 + y1 * R * s;
      n.sz = z2;
    });
    return R;
  }

  function angLerp(a, b, k) {
    const d = ((b - a + 540) % 360) - 180;
    return (a + d * k + 360) % 360;
  }

  function step() {
    t++;
    const T = ORB_STATES[state];
    for (const k of ["rot", "fire", "speed"]) P[k] += (T[k] - P[k]) * 0.04;
    hue = angLerp(hue, T.hue, 0.05);

    // In assenza di un livello reale (parlato: nessun dato dal TTS del
    // processo Python separato), auto-pulsa in modo plausibile — stesso
    // trucco del riferimento originale.
    if (state === "speaking" && performance.now() - lastLevelAt > 250) {
      targetLevel = 0.35 + Math.abs(Math.sin(t * 0.21) * Math.sin(t * 0.053)) * 0.6;
    }
    if (state !== "speaking" && state !== "listening" && performance.now() - lastLevelAt > 250) {
      targetLevel = 0;
    }
    level += (targetLevel - level) * 0.25;

    rotY += P.rot * (1 + level * 2);
    rotX = 0.35 + Math.sin(t * 0.003) * 0.12;

    const rate = P.fire * (1 + level * 4);
    if (Math.random() < rate) fire(Math.floor(Math.random() * nodes.length), (hue + (Math.random() - 0.5) * 30 + 360) % 360);
    if (level > 0.5 && Math.random() < level * 0.3) fire(Math.floor(Math.random() * nodes.length), hue);

    nodes.forEach((n) => { n.e *= 0.955; if (n.ref > 0) n.ref--; n.h = angLerp(n.h, hue, 0.01); });
    for (let k = pulses.length - 1; k >= 0; k--) {
      const p = pulses[k];
      p.p += P.speed;
      if (p.p >= 1) { pulses.splice(k, 1); fire(p.b, p.h); }
    }
    if (pulses.length > 300) pulses.splice(0, pulses.length - 300);
  }

  function draw() {
    cx.globalCompositeOperation = "source-over";
    cx.clearRect(0, 0, W, H);
    const R = project();
    const flick = ORB_STATES[state].jitter && Math.random() < 0.08 ? 0.4 : 1;

    cx.globalCompositeOperation = "lighter";

    const core = cx.createRadialGradient(W / 2, H / 2, 0, W / 2, H / 2, R * (0.55 + level * 0.5));
    core.addColorStop(0, `hsla(${hue},100%,70%,${(0.22 + level * 0.35) * flick})`);
    core.addColorStop(1, `hsla(${hue},100%,50%,0)`);
    cx.fillStyle = core;
    cx.beginPath(); cx.arc(W / 2, H / 2, R * 1.1, 0, 6.28); cx.fill();

    edges.forEach(([i, j]) => {
      const a = nodes[i], b = nodes[j];
      const depth = ((a.sz + b.sz) / 2 + 1) / 2;
      const e = Math.max(a.e, b.e);
      cx.strokeStyle = `hsla(${a.h},80%,${35 + e * 35}%,${(0.06 + depth * 0.18 + e * 0.45) * flick})`;
      cx.lineWidth = 0.5 + e * 1.2;
      cx.beginPath(); cx.moveTo(a.sx, a.sy); cx.lineTo(b.sx, b.sy); cx.stroke();
    });

    pulses.forEach((p) => {
      const a = nodes[p.a], b = nodes[p.b];
      const x = a.sx + (b.sx - a.sx) * p.p, y = a.sy + (b.sy - a.sy) * p.p;
      cx.fillStyle = `hsla(${p.h},100%,65%,.22)`;
      cx.beginPath(); cx.arc(x, y, 4, 0, 6.28); cx.fill();
      cx.fillStyle = `hsla(${p.h},100%,88%,.95)`;
      cx.beginPath(); cx.arc(x, y, 1.3, 0, 6.28); cx.fill();
    });

    nodes.forEach((n) => {
      const depth = (n.sz + 1) / 2, r = 0.8 + depth * 1.5 + n.e * 2.2;
      if (n.e > 0.08) {
        cx.fillStyle = `hsla(${n.h},100%,60%,${n.e * 0.2})`;
        cx.beginPath(); cx.arc(n.sx, n.sy, r * 4, 0, 6.28); cx.fill();
      }
      cx.fillStyle = `hsla(${n.h},${50 + n.e * 50}%,${40 + depth * 20 + n.e * 30}%,${(0.35 + depth * 0.65) * flick})`;
      cx.beginPath(); cx.arc(n.sx, n.sy, r, 0, 6.28); cx.fill();
    });

    if (S.rim) {
      const halo = cx.createRadialGradient(W / 2, H / 2, R * 0.94, W / 2, H / 2, R * 1.22);
      halo.addColorStop(0, `hsla(${hue},100%,60%,0)`);
      halo.addColorStop(0.35, `hsla(${hue},100%,62%,0.20)`);
      halo.addColorStop(1, `hsla(${hue},100%,50%,0)`);
      cx.fillStyle = halo;
      cx.beginPath(); cx.arc(W / 2, H / 2, R * 1.22, 0, 6.28); cx.fill();
    }
    cx.globalCompositeOperation = "source-over";
    cx.lineWidth = 1;
    if (S.rim) {
      cx.strokeStyle = `hsla(${hue},90%,70%,0.55)`;
      cx.beginPath(); cx.arc(W / 2, H / 2, R * 1.04, 0, 6.28); cx.stroke();
    }
    const rings = [[1.1, 0.0025, 0.9, 0.3], [1.16, -0.004, 0.35, 0.18]];
    rings.forEach(([k, sp, len, al], idx) => {
      const a0 = t * sp * (1 + level * 3) + idx;
      cx.strokeStyle = `hsla(${hue},90%,65%,${al + level * 0.3})`;
      for (let s = 0; s < 3; s++) {
        cx.beginPath();
        cx.arc(W / 2, H / 2, R * k, a0 + s * 2.094, a0 + s * 2.094 + len);
        cx.stroke();
      }
    });
  }

  function loop(now = performance.now()) {
    if (!running) return;
    const interval = mobile.matches ? 1000 / 30 : 0;
    if (!lastDraw || now - lastDraw >= interval) {
      step(); draw();
      lastDraw = now - ((now - lastDraw) % (interval || 1));
    }
    if (!reducedMotion.matches) frame = requestAnimationFrame(loop);
  }

  function setState(name) {
    if (!ORB_STATES[name]) return;
    state = name;
    if (running && reducedMotion.matches) { hue = ORB_STATES[name].hue; draw(); }
  }

  function setLevel(v) {
    targetLevel = Math.max(0, Math.min(1, +v || 0));
    lastLevelAt = performance.now();
  }

  function start() {
    if (running) return;
    running = true;
    lastDraw = 0;
    resize();
    if (!nodes.length) buildSphere();
    loop();
  }

  function stop() {
    running = false;
    cancelAnimationFrame(frame);
  }

  new ResizeObserver(() => { if (running) resize(); }).observe(canvas.parentElement);
  reducedMotion.addEventListener("change", () => { if (running) { stop(); start(); } });

  return { start, stop, setState, setLevel };
}

window.JarvisOrb = null; // popolato da app.js dopo aver trovato il canvas nel DOM
window.createJarvisOrb = createJarvisOrb;
