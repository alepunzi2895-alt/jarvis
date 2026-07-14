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

async function submitTask(text) {
  if (!text.trim()) return;
  const el = appendEntry(text);
  $("#console-text").value = "";
  try {
    const { task_id } = await api("task_push", { workspace: currentWs, prompt: text });
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

// ── Push-to-talk (Web Speech API, nativa browser) ───────────────────

function setupVoice() {
  const Recognition = window.SpeechRecognition || window.webkitSpeechRecognition;
  const micBtn = $("#mic-btn");
  if (!Recognition) {
    micBtn.disabled = true;
    micBtn.title = "Riconoscimento vocale non supportato in questo browser";
    return;
  }

  const rec = new Recognition();
  rec.lang = "it-IT";
  rec.interimResults = false;
  rec.maxAlternatives = 1;

  rec.onresult = (e) => {
    const text = e.results[0][0].transcript;
    submitTask(text);
  };
  rec.onend = () => micBtn.classList.remove("listening");
  rec.onerror = () => micBtn.classList.remove("listening");

  const start = (e) => {
    e.preventDefault();
    micBtn.classList.add("listening");
    try { rec.start(); } catch { /* già in ascolto */ }
  };
  const stop = () => {
    try { rec.stop(); } catch { /* noop */ }
  };

  micBtn.addEventListener("mousedown", start);
  micBtn.addEventListener("touchstart", start);
  micBtn.addEventListener("mouseup", stop);
  micBtn.addEventListener("mouseleave", stop);
  micBtn.addEventListener("touchend", stop);
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

// ── Boot ─────────────────────────────────────────────────────────────

async function boot() {
  $("#login-screen").style.display = "none";
  $("#app").classList.add("visible");
  renderPills();
  setupVoice();
  tickClock();
  setInterval(tickClock, 1000);
  await loadHistory();
  refreshTradeflow();
  setInterval(refreshTradeflow, 5000);
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
