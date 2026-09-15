// JARVIS dashboard — app.js (vanilla, nessun framework)

const WORKSPACES = ["jarvis", "aura", "whitesoul", "trading", "isabela", "vino"];
let currentWs = localStorage.getItem("jarvis_ws") || "jarvis";

const $ = (sel) => document.querySelector(sel);

async function api(action, body = {}) {
  const r = await fetch("/api/jarvis", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ action, ...body }),
  });
  const data = await r.json();
  if (!r.ok) throw new Error(data.error || "errore");
  return data;
}

// ── Finestre fluttuanti ────────────────────────────────────────────────

let topZ = 10;

function bringToFront(win) {
  topZ += 1;
  win.style.zIndex = topZ;
}

function dockBtnFor(id) {
  return document.querySelector(`.dock-btn[data-toggle="${id}"]`);
}

function openWindow(id) {
  const win = document.getElementById(id);
  if (!win || win.classList.contains("open")) return;
  win.classList.add("open");
  bringToFront(win);
  dockBtnFor(id)?.classList.add("open");
  if (id === "win-brain") startBrainGraph();
  if (id === "win-camera") startCamera();
}

function closeWindow(id) {
  const win = document.getElementById(id);
  if (!win || !win.classList.contains("open")) return;
  win.classList.remove("open");
  dockBtnFor(id)?.classList.remove("open");
  if (id === "win-brain") stopBrainGraph();
  if (id === "win-camera") stopCamera();
}

function toggleWindow(id) {
  const win = document.getElementById(id);
  if (!win) return;
  (win.classList.contains("open") ? closeWindow : openWindow)(id);
}

function makeDraggable(win) {
  const header = win.querySelector(".fw-header");
  if (!header) return;
  let dragging = false;
  let startX = 0, startY = 0, origX = 0, origY = 0;

  header.addEventListener("pointerdown", (e) => {
    if (e.target.closest(".fw-close")) return;
    dragging = true;
    bringToFront(win);
    startX = e.clientX;
    startY = e.clientY;
    origX = parseFloat(win.style.getPropertyValue("--x")) || 0;
    origY = parseFloat(win.style.getPropertyValue("--y")) || 0;
    header.setPointerCapture(e.pointerId);
  });
  header.addEventListener("pointermove", (e) => {
    if (!dragging) return;
    win.style.setProperty("--x", `${origX + (e.clientX - startX)}px`);
    win.style.setProperty("--y", `${origY + (e.clientY - startY)}px`);
  });
  const stopDrag = () => { dragging = false; };
  header.addEventListener("pointerup", stopDrag);
  header.addEventListener("pointercancel", stopDrag);
}

function setupWindows() {
  document.querySelectorAll(".floating-window").forEach((win) => {
    makeDraggable(win);
    bringToFront(win);
  });
  document.querySelectorAll(".dock-btn").forEach((btn) => {
    btn.addEventListener("click", () => toggleWindow(btn.dataset.toggle));
  });
  document.querySelectorAll(".fw-close").forEach((btn) => {
    btn.addEventListener("click", () => closeWindow(btn.dataset.close));
  });
}

// ── Login ────────────────────────────────────────────────────────────

$("#login-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  $("#login-error").textContent = "";
  try {
    await api("login", { password: $("#login-password").value });
    boot();
  } catch (err) {
    $("#login-error").textContent = err.message === "Password errata" ? "Password errata." : "Errore di accesso.";
  }
});

$("#logout-btn").addEventListener("click", () => {
  document.cookie = "jarvis_session=; Path=/; Max-Age=0";
  location.reload();
});

// ── Workspace pills ──────────────────────────────────────────────────

function renderPills() {
  const wrap = $("#ws-pills");
  wrap.innerHTML = "";
  for (const ws of WORKSPACES) {
    const btn = document.createElement("button");
    btn.className = "ws-pill" + (ws === currentWs ? " active" : "");
    btn.textContent = ws;
    btn.addEventListener("click", () => {
      currentWs = ws;
      localStorage.setItem("jarvis_ws", ws);
      renderPills();
      $("#hud-ws").textContent = currentWs;
    });
    wrap.appendChild(btn);
  }
  $("#hud-ws").textContent = currentWs;
}

// ── HUD strip: clock, session uptime, connection status ─────────────

const bootedAt = Date.now();

function tickClock() {
  const now = new Date().toLocaleTimeString("it-IT");
  $("#hud-clock").textContent = now;
  $("#header-clock").textContent = now;

  const elapsedS = Math.floor((Date.now() - bootedAt) / 1000);
  const h = String(Math.floor(elapsedS / 3600)).padStart(2, "0");
  const m = String(Math.floor((elapsedS % 3600) / 60)).padStart(2, "0");
  const s = String(elapsedS % 60).padStart(2, "0");
  $("#hud-uptime").textContent = `${h}:${m}:${s}`;
}

function setConn(state) {
  const map = {
    online: ["good", "online"],
    warning: ["warning", "instabile"],
    offline: ["critical", "offline"],
  };
  const [cls, label] = map[state];
  $("#hud-conn").innerHTML = `<span class="status-pill ${cls}"><span class="dot"></span>${label}</span>`;
}

// ── Console ──────────────────────────────────────────────────────────

function appendEntry(prompt) {
  const log = $("#console-log");
  const el = document.createElement("div");
  el.className = "entry pending";
  el.innerHTML = `<div class="prompt"></div><div class="result"></div><div class="meta"></div>`;
  el.querySelector(".prompt").textContent = prompt;
  log.appendChild(el);
  log.scrollTop = log.scrollHeight;
  return el;
}

function fillEntry(el, task) {
  el.classList.remove("pending");
  if (task.status === "error") el.classList.add("error");
  el.querySelector(".result").textContent = task.result || "(nessun output)";
  const meta = [];
  if (task.workspace) meta.push(task.workspace);
  if (task.cost_usd) meta.push(`$${Number(task.cost_usd).toFixed(3)}`);
  el.querySelector(".meta").textContent = meta.join(" · ");
  $("#console-log").scrollTop = $("#console-log").scrollHeight;
}

async function pollTask(taskId, el) {
  for (let i = 0; i < 200; i++) {
    await new Promise((r) => setTimeout(r, 1500));
    try {
      const { task } = await api("task_poll", { task_id: taskId });
      if (task.status === "done" || task.status === "error") {
        fillEntry(el, task);
        return;
      }
    } catch {
      fillEntry(el, { status: "error", result: "Connessione persa." });
      return;
    }
  }
  fillEntry(el, { status: "error", result: "Timeout: nessuna risposta dal bridge locale." });
}

async function submitTask(text, imageB64) {
  if (!text.trim()) return;
  openWindow("win-chat");
  const el = appendEntry(text);
  $("#console-text").value = "";
  try {
    const body = { workspace: currentWs, prompt: text };
    if (imageB64) body.image_b64 = imageB64;
    const { task_id } = await api("task_push", body);
    pollTask(task_id, el);
  } catch (err) {
    fillEntry(el, { status: "error", result: err.message });
  }
}

$("#console-form").addEventListener("submit", (e) => {
  e.preventDefault();
  submitTask($("#console-text").value);
});

async function loadHistory() {
  try {
    const { tasks } = await api("tasks_recent", { limit: 20 });
    $("#hud-taskcount").textContent = tasks.length;
    for (const t of tasks.reverse()) {
      const el = appendEntry(t.prompt);
      if (t.status === "done" || t.status === "error") fillEntry(el, t);
      else pollTask(t.id, el);
    }
  } catch {
    /* prima sessione, nessuno storico */
  }
}

// ── Voce dal microfono (ascolto a mani libere, registrazione locale) ──
// La Web Speech API del browser (riconoscimento cloud di Google) si è
// rivelata irraggiungibile su questa rete — verificato dal vivo il
// 2026-09-14: nessun onstart/onerror, il motore non parte mai, solo
// onend immediato. Il microfono registra soltanto (MediaRecorder,
// funzionante) e manda l'audio al bridge locale, che lo trascrive con lo
// stesso motore (faster-whisper) già usato dal daemon vocale nativo —
// sola andata, nessuna dipendenza da servizi esterni.
//
// Un click arma il microfono e resta acceso finché non lo spegni tu (un
// secondo click) — non serve più cliccare per ogni singolo comando. Dentro
// l'ascolto, ogni "segmento" parte da solo quando rileva voce e si ferma
// da solo dopo una pausa di silenzio (stessa soglia/logica di
// core/voice/stt.py, SILENCE_HANG_MS) o dopo un tetto massimo.
//
// Richiede la parola d'attivazione "Jarvis" nella frase (filtrata lato
// server, core/web_bridge.py::_strip_wake_word): senza, un ascolto sempre
// acceso capterebbe qualunque rumore ambientale (TV, conversazioni) come
// task reale — stesso problema già capitato una volta con l'ascolto
// continuo del vecchio riconoscimento cloud del browser (2026-07-14: ~230
// task spuri, ~1.33$ di chiamate Claude vere prima che esistesse un filtro
// equivalente). I segmenti senza "Jarvis" tornano dal bridge con
// status "ignored" e spariscono dalla console senza lasciare traccia.
//
// Limite noto: il segmento inizia a registrare solo DOPO che il volume
// supera la soglia (nessun pre-buffer) — la primissima sillaba di "Jarvis"
// può risultare tagliata. Non verificato dal vivo quanto pesi in pratica.

// Intercetta i comandi che aprono/chiudono le finestre PRIMA di sottoporli
// a Claude — istantaneo, nessuna chiamata task per queste azioni di UI.
function handleVoiceUiCommand(text) {
  const t = text.toLowerCase();
  const wants = (re) => re.test(t);
  const verb = /\b(apri|accendi|attiva|mostra)\b/;
  const closeVerb = /\b(chiudi|nascondi|spegni)\b/;

  if (wants(/\b(webcam|camera|cam|telecamera|fotocamera)\b/)) {
    if (wants(verb)) { openWindow("win-camera"); return true; }
    if (wants(closeVerb)) { closeWindow("win-camera"); return true; }
  }
  if (wants(/\b(chat|console)\b/)) {
    if (wants(verb)) { openWindow("win-chat"); return true; }
    if (wants(closeVerb)) { closeWindow("win-chat"); return true; }
  }
  if (wants(/\b(second brain|cervello|memoria)\b/)) {
    if (wants(verb)) { openWindow("win-brain"); return true; }
    if (wants(closeVerb)) { closeWindow("win-brain"); return true; }
  }
  if (wants(/\b(tradeflow|trading)\b/)) {
    if (wants(verb)) { openWindow("win-tradeflow"); return true; }
    if (wants(closeVerb)) { closeWindow("win-tradeflow"); return true; }
  }
  return false;
}

const MIC_SILENCE_RMS = 12; // scala 0-255 (AnalyserNode su dati Uint8 centrati a 128)
const MIC_SILENCE_HANG_MS = 1200; // stessa soglia di core/voice/stt.py::SILENCE_HANG_MS
const MIC_MAX_RECORD_MS = 15000;

function setupVoice() {
  const micBtn = $("#mic-btn");
  if (!navigator.mediaDevices || !window.MediaRecorder) {
    micBtn.disabled = true;
    micBtn.title = "Registrazione audio non supportata in questo browser";
    return;
  }

  const OFF_TITLE = 'Ascolto in pausa — clicca per riattivare (di\' "Jarvis" + comando)';
  const ON_TITLE = 'Ascolto a mani libere attivo — di\' "Jarvis" + comando — clicca per silenziare';
  micBtn.title = ON_TITLE;

  let armed = false;
  let stream = null;
  let audioCtx = null;
  let monitorInterval = null;
  let recorder = null;
  let recording = false;

  function stopSegment() {
    if (recorder && recorder.state !== "inactive") recorder.stop();
  }

  function startSegment() {
    recording = true;
    const chunks = [];
    recorder = new MediaRecorder(stream);
    recorder.ondataavailable = (e) => {
      if (e.data.size > 0) chunks.push(e.data);
    };
    recorder.onstop = () => {
      recording = false;
      const blob = new Blob(chunks, { type: recorder.mimeType || "audio/webm" });
      if (blob.size > 500) handleRecordedAudio(blob); // scarta segmenti vuoti/troppo brevi
    };
    recorder.start();
  }

  async function arm() {
    if (armed) return;
    try {
      stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    } catch {
      micBtn.title = "Microfono non autorizzato dal browser";
      return;
    }

    armed = true;
    micBtn.classList.add("listening");
    micBtn.title = ON_TITLE;

    // Rilevamento voce/silenzio lato browser (AnalyserNode), sempre attivo
    // finché armato — decide da solo quando iniziare e fermare ogni
    // segmento, stessa soglia/logica del daemon nativo.
    audioCtx = new (window.AudioContext || window.webkitAudioContext)();
    const source = audioCtx.createMediaStreamSource(stream);
    const analyser = audioCtx.createAnalyser();
    analyser.fftSize = 2048;
    source.connect(analyser);
    const data = new Uint8Array(analyser.fftSize);

    let silenceStartedAt = null;
    let segmentStartedAt = null;

    monitorInterval = setInterval(() => {
      analyser.getByteTimeDomainData(data);
      let sumSquares = 0;
      for (let i = 0; i < data.length; i++) {
        const v = data[i] - 128;
        sumSquares += v * v;
      }
      const rms = Math.sqrt(sumSquares / data.length);
      const speaking = rms > MIC_SILENCE_RMS;

      if (!recording) {
        if (speaking) {
          segmentStartedAt = Date.now();
          silenceStartedAt = null;
          startSegment();
        }
        return;
      }

      if (speaking) {
        silenceStartedAt = null;
      } else {
        if (silenceStartedAt === null) silenceStartedAt = Date.now();
        if (Date.now() - silenceStartedAt > MIC_SILENCE_HANG_MS) stopSegment();
      }
      if (Date.now() - segmentStartedAt > MIC_MAX_RECORD_MS) stopSegment();
    }, 100);
  }

  function disarm() {
    if (!armed) return;
    armed = false;
    clearInterval(monitorInterval);
    monitorInterval = null;
    stopSegment();
    stream.getTracks().forEach((t) => t.stop());
    audioCtx.close().catch(() => {});
    stream = null;
    audioCtx = null;
    micBtn.classList.remove("listening");
    micBtn.title = OFF_TITLE;
  }

  micBtn.addEventListener("click", () => {
    if (armed) disarm();
    else arm();
  });

  // Ascolto sempre attivo di default — niente click richiesto per iniziare
  // a parlare/mandare messaggi (richiesta esplicita di Alessandro): il
  // filtro "Jarvis" lato server (core/web_bridge.py::_strip_wake_word) e'
  // gia' quello che protegge da rumore ambientale, il click resta solo
  // come interruttore manuale per chi vuole silenziare il mic (es. per
  // privacy). La prima volta il browser mostra comunque il permesso
  // nativo del microfono — dopo, riparte da solo ad ogni apertura pagina.
  arm();
}

async function handleRecordedAudio(blob) {
  const reader = new FileReader();
  const audioB64 = await new Promise((resolve, reject) => {
    reader.onloadend = () => resolve(reader.result.split(",")[1]);
    reader.onerror = () => reject(reader.error);
    reader.readAsDataURL(blob);
  });
  submitTaskAudio(audioB64);
}

async function submitTaskAudio(audioB64) {
  openWindow("win-chat");
  const el = appendEntry("🎙️ (trascrizione in corso…)");
  try {
    const { task_id } = await api("task_push", { workspace: currentWs, audio_b64: audioB64 });
    pollTranscribedTask(task_id, el);
  } catch (err) {
    fillEntry(el, { status: "error", result: err.message });
  }
}

// Come pollTask, ma per un task nato da audio: appena il bridge locale ha
// trascritto (task.prompt si popola), se il testo e' un comando locale di
// finestra lo gestisce subito qui (stesso schema di handleVoiceUiCommand,
// prima riservato al riconoscimento vocale del browser) invece di aspettare
// che Claude gli risponda con del testo per un'azione che Claude non puo'
// comunque eseguire lui stesso. status="ignored" (dal filtro parola
// d'attivazione lato server) rimuove l'entry senza mostrarla: e' rumore
// ambientale captato dall'ascolto a mani libere, non un comando vero.
async function pollTranscribedTask(taskId, el) {
  let transcribed = false;
  for (let i = 0; i < 200; i++) {
    await new Promise((r) => setTimeout(r, 1000));
    let task;
    try {
      ({ task } = await api("task_poll", { task_id: taskId }));
    } catch {
      fillEntry(el, { status: "error", result: "Connessione persa." });
      return;
    }

    if (task.status === "ignored") {
      el.remove();
      return;
    }
    if (!transcribed && task.prompt) {
      transcribed = true;
      el.querySelector(".prompt").textContent = task.prompt;
      if (handleVoiceUiCommand(task.prompt)) {
        fillEntry(el, { status: "done", result: "Fatto." });
        return;
      }
    }
    if (task.status === "done" || task.status === "error") {
      fillEntry(el, task);
      return;
    }
  }
  fillEntry(el, { status: "error", result: "Timeout: nessuna risposta dal bridge locale." });
}

// ── TradeFlow widget ─────────────────────────────────────────────────

function statusPill(bot_status) {
  if (!bot_status) return `<span class="status-pill warning"><span class="dot"></span>sconosciuto</span>`;
  if (bot_status.running) {
    const mode = bot_status.dry_run ? "demo" : "live";
    return `<span class="status-pill good"><span class="dot"></span>attivo · ${mode}</span>`;
  }
  return `<span class="status-pill critical"><span class="dot"></span>fermo</span>`;
}

function timeAgo(iso) {
  if (!iso) return "mai";
  const s = Math.floor((Date.now() - new Date(iso).getTime()) / 1000);
  if (s < 60) return `${s}s fa`;
  if (s < 3600) return `${Math.floor(s / 60)}m fa`;
  return `${Math.floor(s / 3600)}h fa`;
}

async function refreshTradeflow() {
  try {
    const res = await fetch("/api/tradeflow", { method: "POST" });
    const json = await res.json();
    const data = json.data;
    const stats = $("#tradeflow-stats");
    if (!data) {
      stats.innerHTML = `<div class="stat-tile"><div class="label">Equity</div><div class="value">—</div></div>
        <div class="stat-tile"><div class="label">Posizioni</div><div class="value">—</div></div>`;
      $("#tradeflow-status").innerHTML = "";
      $("#tradeflow-sync").textContent = "Bot non ancora connesso.";
      setConn("online");
      return;
    }
    const eq = data.account?.equity;
    const cur = data.account?.currency || "";
    stats.innerHTML = `
      <div class="stat-tile"><div class="label">Equity</div><div class="value">${eq != null ? eq.toFixed(2) + " " + cur : "—"}</div></div>
      <div class="stat-tile"><div class="label">Posizioni</div><div class="value">${data.positions?.length ?? 0}</div></div>`;
    $("#tradeflow-status").innerHTML = statusPill(data.bot_status);
    $("#tradeflow-sync").textContent = "Ultimo sync: " + timeAgo(json.updated_at || data.synced_at);
    setConn("online");
  } catch {
    $("#tradeflow-sync").textContent = "Errore di connessione.";
    setConn("warning");
  }
}

// ── Second brain — grafo animato (canvas, nessuna libreria) ──────────
// Colori per workspace: stesso ordine/palette categorica della skill dataviz
// (slot 1-6 del tema dark), cosi' l'ordine resta fisso indipendentemente
// dall'ordine con cui i workspace compaiono nei dati.
const WORKSPACE_COLORS = {
  jarvis: "#3987e5",
  aura: "#199e70",
  whitesoul: "#c98500",
  trading: "#008300",
  isabela: "#9085e9",
  vino: "#e66767",
};
const BRAIN_DEFAULT_COLOR = "#898781";

let brainNodes = [];
let brainEdges = [];
const brainPositions = new Map();
let brainCanvas = null;
let brainCtx = null;
let brainFont = "11px sans-serif";
let brainRunning = false;
let brainAnimHandle = null;
let brainPollTimer = null;
let hoveredNode = null;
let focusedNode = null;
let brainScale = 1; // ricalcolato ad ogni frame per far stare l'intero grafo nel canvas

function hexToRgba(hex, alpha) {
  const r = parseInt(hex.slice(1, 3), 16);
  const g = parseInt(hex.slice(3, 5), 16);
  const b = parseInt(hex.slice(5, 7), 16);
  return `rgba(${r},${g},${b},${alpha})`;
}

function brainIsConnected(node, focus) {
  return brainEdges.some(
    (e) => (e.source === focus && e.target === node) || (e.target === focus && e.source === node)
  );
}

async function loadBrainGraph() {
  try {
    const { nodes, edges } = await api("brain_graph");
    for (const n of brainNodes) brainPositions.set(n.id, { x: n.x, y: n.y, vx: n.vx, vy: n.vy });

    brainNodes = nodes.map((n) => {
      const prev = brainPositions.get(n.id);
      return {
        id: n.id,
        label: n.label,
        summary: n.summary,
        workspace: n.workspace,
        hits: n.hits || 1,
        x: prev ? prev.x : (Math.random() - 0.5) * 300,
        y: prev ? prev.y : (Math.random() - 0.5) * 300,
        vx: prev ? prev.vx : 0,
        vy: prev ? prev.vy : 0,
      };
    });
    const byId = new Map(brainNodes.map((n) => [n.id, n]));
    brainEdges = edges
      .map((e) => ({ source: byId.get(e.source_id), target: byId.get(e.target_id), relation: e.relation }))
      .filter((e) => e.source && e.target);

    hoveredNode = null;
    focusedNode = null;
    $("#brain-hint").textContent = `${brainNodes.length} nodi · ${brainEdges.length} collegamenti`;
  } catch {
    $("#brain-hint").textContent = "Errore di caricamento.";
  }
}

function brainFindNear(x, y) {
  let best = null;
  let bestDist = 20 * 20;
  for (const n of brainNodes) {
    const d = (n.x - x) ** 2 + (n.y - y) ** 2;
    if (d < bestDist) {
      bestDist = d;
      best = n;
    }
  }
  return best;
}

function setupBrainCanvas() {
  brainCanvas = $("#brain-canvas");
  brainCtx = brainCanvas.getContext("2d");
  brainFont = getComputedStyle(document.body).fontFamily;

  function resize() {
    const rect = brainCanvas.getBoundingClientRect();
    const dpr = window.devicePixelRatio || 1;
    brainCanvas.width = rect.width * dpr;
    brainCanvas.height = rect.height * dpr;
    brainCtx.setTransform(dpr, 0, 0, dpr, 0, 0);
  }
  window.addEventListener("resize", resize);
  // window.resize non scatta quando l'utente ridimensiona la finestra
  // fluttuante trascinando l'angolo (CSS resize) — serve un observer
  // dedicato sul canvas stesso per aggiornare la risoluzione interna.
  new ResizeObserver(resize).observe(brainCanvas);
  resize();

  // Le coordinate del mouse sono in pixel schermo; le posizioni dei nodi sono
  // in "spazio mondo" e vengono disegnate scalate (zoom-to-fit, vedi
  // brainRender) — va applicata la stessa scala in senso inverso per far
  // corrispondere hover/click al nodo giusto.
  brainCanvas.addEventListener("mousemove", (e) => {
    const rect = brainCanvas.getBoundingClientRect();
    const mx = (e.clientX - rect.left - rect.width / 2) / brainScale;
    const my = (e.clientY - rect.top - rect.height / 2) / brainScale;
    hoveredNode = brainFindNear(mx, my);
    brainCanvas.style.cursor = hoveredNode ? "pointer" : "grab";
  });

  brainCanvas.addEventListener("click", (e) => {
    const rect = brainCanvas.getBoundingClientRect();
    const mx = (e.clientX - rect.left - rect.width / 2) / brainScale;
    const my = (e.clientY - rect.top - rect.height / 2) / brainScale;
    const n = brainFindNear(mx, my);
    focusedNode = focusedNode === n ? null : n;
  });

  brainCanvas.addEventListener("dblclick", async (e) => {
    const rect = brainCanvas.getBoundingClientRect();
    const mx = (e.clientX - rect.left - rect.width / 2) / brainScale;
    const my = (e.clientY - rect.top - rect.height / 2) / brainScale;
    const n = brainFindNear(mx, my);
    if (!n) return;
    if (!confirm(`Eliminare il nodo "${n.label}"?`)) return;
    try {
      await api("brain_node_delete", { id: n.id });
      await loadBrainGraph();
    } catch {
      $("#brain-hint").textContent = "Errore durante l'eliminazione.";
    }
  });
}

function brainStep() {
  const n = brainNodes.length;
  if (!n) return;

  for (let i = 0; i < n; i++) {
    const a = brainNodes[i];
    for (let j = i + 1; j < n; j++) {
      const b = brainNodes[j];
      const dx = a.x - b.x;
      const dy = a.y - b.y;
      const distSq = dx * dx + dy * dy || 0.01;
      const force = 700 / distSq;
      const dist = Math.sqrt(distSq);
      const fx = (dx / dist) * force;
      const fy = (dy / dist) * force;
      a.vx += fx;
      a.vy += fy;
      b.vx -= fx;
      b.vy -= fy;
    }
  }

  for (const e of brainEdges) {
    const dx = e.target.x - e.source.x;
    const dy = e.target.y - e.source.y;
    const dist = Math.sqrt(dx * dx + dy * dy) || 0.01;
    const force = (dist - 90) * 0.02;
    const fx = (dx / dist) * force;
    const fy = (dy / dist) * force;
    e.source.vx += fx;
    e.source.vy += fy;
    e.target.vx -= fx;
    e.target.vy -= fy;
  }

  for (const node of brainNodes) {
    node.vx += -node.x * 0.001;
    node.vy += -node.y * 0.001;
    node.vx += (Math.random() - 0.5) * 0.6; // jitter continuo: il grafo non si ferma mai
    node.vy += (Math.random() - 0.5) * 0.6;
    node.vx *= 0.85;
    node.vy *= 0.85;
    node.x += node.vx;
    node.y += node.vy;
  }
}

function brainNodeStyle(node) {
  const base = WORKSPACE_COLORS[node.workspace] || BRAIN_DEFAULT_COLOR;
  if (focusedNode) {
    const on = node === focusedNode || brainIsConnected(node, focusedNode);
    return on ? { fill: base, glow: 8 } : { fill: "rgba(255,255,255,0.07)", glow: 0 };
  }
  const onWs = node.workspace === currentWs;
  return onWs ? { fill: base, glow: 7 } : { fill: hexToRgba(base, 0.35), glow: 0 };
}

function brainRender() {
  const rect = brainCanvas.getBoundingClientRect();
  const w = rect.width;
  const h = rect.height;
  brainCtx.clearRect(0, 0, w, h);

  // Zoom-to-fit: senza questo, un grafo con molti nodi (il layout a forze li
  // spinge ben oltre i confini del canvas) mostrava solo il cluster centrale
  // — il resto restava fuori schermo. Si ricalcola ogni frame sul bounding
  // box corrente dei nodi, cosi' segue anche l'animazione/jitter continuo.
  brainScale = 1;
  if (brainNodes.length > 1) {
    let minX = Infinity, maxX = -Infinity, minY = Infinity, maxY = -Infinity;
    for (const n of brainNodes) {
      if (n.x < minX) minX = n.x;
      if (n.x > maxX) maxX = n.x;
      if (n.y < minY) minY = n.y;
      if (n.y > maxY) maxY = n.y;
    }
    const contentW = Math.max(maxX - minX, 1);
    const contentH = Math.max(maxY - minY, 1);
    const padding = 0.8; // margine cosi' i nodi ai bordi non toccano la cornice
    brainScale = Math.min(1, (w * padding) / contentW, (h * padding) / contentH);
  }

  brainCtx.save();
  brainCtx.translate(w / 2, h / 2);
  brainCtx.scale(brainScale, brainScale);

  brainCtx.lineWidth = 1 / brainScale;
  for (const e of brainEdges) {
    const dim = focusedNode && e.source !== focusedNode && e.target !== focusedNode;
    brainCtx.strokeStyle = dim ? "rgba(255,255,255,0.04)" : "rgba(57,135,229,0.25)";
    brainCtx.beginPath();
    brainCtx.moveTo(e.source.x, e.source.y);
    brainCtx.lineTo(e.target.x, e.target.y);
    brainCtx.stroke();
  }

  brainCtx.textAlign = "center";
  brainCtx.font = `11px ${brainFont}`;
  for (const node of brainNodes) {
    const { fill, glow } = brainNodeStyle(node);
    const r = 4 + Math.min(node.hits, 12);

    brainCtx.beginPath();
    brainCtx.arc(node.x, node.y, r, 0, Math.PI * 2);
    brainCtx.fillStyle = fill;
    brainCtx.shadowColor = glow ? fill : "transparent";
    brainCtx.shadowBlur = glow;
    brainCtx.fill();
    brainCtx.shadowBlur = 0;

    if (node === hoveredNode || node === focusedNode || node.hits >= 4) {
      brainCtx.fillStyle = glow ? "#ffffff" : "rgba(255,255,255,0.3)";
      brainCtx.fillText(node.label, node.x, node.y - r - 6);
    }
  }
  brainCtx.restore();

  if (hoveredNode) {
    $("#brain-hint").textContent = hoveredNode.summary
      ? `${hoveredNode.label} — ${hoveredNode.summary}`
      : hoveredNode.label;
  } else {
    $("#brain-hint").textContent = `${brainNodes.length} nodi · ${brainEdges.length} collegamenti`;
  }
}

function brainTick() {
  brainStep();
  brainRender();
  if (brainRunning) brainAnimHandle = requestAnimationFrame(brainTick);
}

function startBrainGraph() {
  if (!brainCanvas) setupBrainCanvas();
  loadBrainGraph();
  brainRunning = true;
  brainTick();
  brainPollTimer = setInterval(loadBrainGraph, 60000);
}

function stopBrainGraph() {
  brainRunning = false;
  if (brainAnimHandle) cancelAnimationFrame(brainAnimHandle);
  if (brainPollTimer) clearInterval(brainPollTimer);
}

// ── Camera ("che Jarvis mi veda") ────────────────────────────────────
// Attivata solo su richiesta esplicita (click o voce), mai in background.
// Lo stream si ferma sempre quando la finestra si chiude.

let cameraStream = null;

async function startCamera() {
  const video = $("#camera-video");
  const hint = $("#camera-hint");
  try {
    cameraStream = await navigator.mediaDevices.getUserMedia({ video: true });
    video.srcObject = cameraStream;
    hint.textContent = "Camera attiva.";
  } catch {
    hint.textContent = "Permesso camera negato o non disponibile.";
  }
}

function stopCamera() {
  if (cameraStream) {
    cameraStream.getTracks().forEach((t) => t.stop());
    cameraStream = null;
  }
  $("#camera-video").srcObject = null;
  $("#camera-ask-form").hidden = true;
  $("#camera-hint").textContent = "Camera non attiva.";
}

function setupCamera() {
  $("#camera-ask-btn").addEventListener("click", () => {
    if (!cameraStream) return;
    const video = $("#camera-video");
    const canvas = $("#camera-canvas");
    canvas.width = video.videoWidth;
    canvas.height = video.videoHeight;
    canvas.getContext("2d").drawImage(video, 0, 0);
    $("#camera-ask-form").hidden = false;
    $("#camera-ask-text").focus();
  });

  $("#camera-ask-form").addEventListener("submit", (e) => {
    e.preventDefault();
    const canvas = $("#camera-canvas");
    const imageB64 = canvas.toDataURL("image/jpeg", 0.85);
    const question = $("#camera-ask-text").value.trim() || "Cosa vedi?";
    $("#camera-ask-form").hidden = true;
    submitTask(question, imageB64);
  });
}

// ── Stato "sta parlando" (bolla centrale) ───────────────────────────────
// L'audio esce dagli altoparlanti del PC via un processo Python separato
// (core/voice/tts.py), non nel browser — l'unico modo per far reagire la
// bolla e' chiedere periodicamente a Turso se JARVIS sta parlando in
// questo momento, qualunque canale (Telegram/voce/dashboard) l'abbia
// innescato.
const ORB_SPEAKING_POLL_MS = 700;

async function pollSpeakingStatus() {
  const orb = $("#jarvis-orb");
  try {
    const { speaking } = await api("runtime_status");
    orb.classList.toggle("orb-speaking", !!speaking);
  } catch {
    // rete assente/blip transitorio: non toccare lo stato attuale della bolla
  }
}

// ── Boot ─────────────────────────────────────────────────────────────

async function boot() {
  $("#login-screen").style.display = "none";
  $("#app").classList.add("visible");
  renderPills();
  setupVoice();
  setupWindows();
  setupCamera();
  tickClock();
  setInterval(tickClock, 1000);
  await loadHistory();
  refreshTradeflow();
  setInterval(refreshTradeflow, 5000);
  pollSpeakingStatus();
  setInterval(pollSpeakingStatus, ORB_SPEAKING_POLL_MS);
}

// Se il cookie di sessione è già valido, salta il login
(async () => {
  try {
    await api("tasks_recent", { limit: 1 });
    boot();
  } catch {
    // resta sulla schermata di login
  }
})();
