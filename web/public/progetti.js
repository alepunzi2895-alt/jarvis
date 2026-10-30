// Chat Claude Code per progetto: sessione collegata, trascrizione in tempo reale, prompt scritti e vocali.
(() => {
  const el = (id) => document.getElementById(id);
  const state = { project: null, editable: false, lastId: 0, busy: false, live: false, listening: false };
  let pollTimer = null;
  let orb = null;

  async function api(action, body = {}) {
    const r = await fetch("/api/jarvis", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ action, ...body }),
    });
    const data = await r.json().catch(() => ({}));
    if (!r.ok) throw new Error(data.error || `HTTP ${r.status}`);
    return data;
  }

  // ── sfera: stato da chat e microfono ───────────────────────────
  function setOrb(name, label) {
    if (orb && orb.setState) orb.setState(name);
    el("orb-state").textContent = label;
  }

  function refreshOrb() {
    if (state.listening) setOrb("listening", "ascolto");
    else if (state.busy) setOrb("thinking", "elaborazione");
    else if (state.live) setOrb("speaking", "sessione attiva");
    else setOrb("idle", "standby");
  }

  function setChip(kind, text) {
    const chip = el("status");
    chip.className = "chip" + (kind ? " " + kind : "");
    chip.textContent = text;
  }

  // ── progetti ───────────────────────────────────────────────────
  async function loadProjects() {
    const { projects } = await api("project_chats");
    const box = el("projects");
    box.textContent = "";
    for (const p of projects) {
      const b = document.createElement("button");
      b.type = "button";
      b.className = "proj" + (p.key === state.project ? " on" : "");
      const text = document.createElement("span");
      text.textContent = p.label;
      const sub = document.createElement("small");
      sub.textContent = p.editable ? "modifica attiva" : "sola lettura";
      text.append(sub);
      b.append(text);
      if (p.busy) {
        const mark = document.createElement("span");
        mark.className = "busy";
        mark.textContent = "●";
        b.append(mark);
      }
      b.addEventListener("click", () => openProject(p));
      box.append(b);
    }
  }

  async function openProject(p) {
    state.project = p.key;
    state.editable = p.editable;
    state.lastId = 0;
    el("title").textContent = p.label.toUpperCase();
    el("log").textContent = "";
    el("stop").disabled = true;
    history.replaceState(null, "", `?project=${encodeURIComponent(p.key)}`);
    await loadProjects();
    await loadSessions();
    el("input").disabled = !state.editable;
    if (!p.editable) setChip("", "sola lettura");
    schedulePoll(0);
  }

  // ── cronologia: strumenti raggruppati, rumore nascosto ─────────
  function appendTools(log, tools) {
    const details = document.createElement("details");
    details.className = "tools";
    const summary = document.createElement("summary");
    summary.textContent = `⚙ ${tools.length} strumenti`;
    const body = document.createElement("div");
    body.textContent = tools.map((t) => `› ${t.text}`).join("\n");
    details.append(summary, body);
    log.append(details);
  }

  function render(items) {
    const log = el("log");
    if (!state.lastId) log.textContent = "";
    let tools = [];
    const flush = () => { if (tools.length) { appendTools(log, tools); tools = []; } };
    for (const item of items) {
      state.lastId = Math.max(state.lastId, item.id);
      if (item.kind === "tool") { tools.push(item); continue; }
      flush();
      if (item.kind === "session" || item.kind === "status") continue;
      const m = document.createElement("div");
      m.className = `m ${item.kind}`;
      if (item.kind === "error") m.textContent = `! ${item.text}`;
      else m.textContent = item.text || "";
      if (item.kind === "result" && item.status === "error") m.classList.add("error");
      log.append(m);
    }
    flush();
    if (items.length) log.scrollTop = log.scrollHeight;
    if (!log.children.length) log.innerHTML = '<div class="hint">&gt; nessun messaggio ancora_</div>';
  }

  async function poll() {
    if (!state.project) return;
    try {
      const data = await api("project_chat_history", { project: state.project, after: state.lastId });
      render(data.events);
      state.busy = data.busy;
      state.live = data.live;
      el("stop").disabled = !state.busy;
      el("send").disabled = !state.editable || state.busy;
      if (state.busy) setChip("busy", "lavoro in corso");
      else if (state.live) setChip("live", "sessione attiva");
      else setChip("ok", "pronto");
      refreshOrb();
      schedulePoll(state.busy || state.live ? 2000 : 8000);
    } catch (error) {
      setChip("", error.message);
      schedulePoll(8000);
    }
  }

  function schedulePoll(ms) {
    clearTimeout(pollTimer);
    pollTimer = setTimeout(poll, ms);
  }

  async function loadSessions() {
    const select = el("session");
    try {
      const { sessions, current } = await api("project_chat_sessions", { project: state.project });
      select.textContent = "";
      for (const s of sessions) {
        const option = document.createElement("option");
        option.value = s.session_id;
        option.textContent = `${s.active ? "● " : ""}${s.modified} · ${s.session_id.slice(0, 8)}`;
        option.selected = s.session_id === current;
        select.append(option);
      }
      select.hidden = !sessions.length;
    } catch {
      select.hidden = true;
    }
  }

  el("session").addEventListener("change", async (event) => {
    if (!state.project || !event.target.value) return;
    try {
      await api("project_chat_attach", { project: state.project, session_id: event.target.value });
      state.lastId = 0;
      el("log").textContent = "";
      schedulePoll(0);
    } catch (error) {
      setChip("", error.message);
    }
  });

  // ── invio, stop, dettatura ─────────────────────────────────────
  el("form").addEventListener("submit", async (event) => {
    event.preventDefault();
    const text = el("input").value.trim();
    if (!text || !state.project) return;
    try {
      el("input").value = "";
      await api("project_chat_send", { project: state.project, text });
      schedulePoll(0);
    } catch (error) {
      setChip("", error.message);
      el("input").value = text;
    }
  });

  el("input").addEventListener("keydown", (event) => {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      el("form").requestSubmit();
    }
  });

  el("stop").addEventListener("click", async () => {
    if (!state.project) return;
    try {
      await api("project_chat_stop", { project: state.project });
      schedulePoll(0);
    } catch (error) {
      setChip("", error.message);
    }
  });

  const Rec = window.SpeechRecognition || window.webkitSpeechRecognition;
  if (Rec) {
    const rec = new Rec();
    rec.lang = "it-IT";
    rec.interimResults = false;
    el("mic").hidden = false;
    el("mic").addEventListener("click", () => {
      if (!state.project || !state.editable || state.busy) return;
      rec.start();
    });
    rec.onstart = () => { state.listening = true; el("mic").classList.add("listening"); refreshOrb(); };
    rec.onend = () => { state.listening = false; el("mic").classList.remove("listening"); refreshOrb(); };
    rec.onresult = (event) => {
      el("input").value = event.results[0][0].transcript;
      el("form").requestSubmit();
    };
    rec.onerror = (event) => setChip("", `microfono: ${event.error}`);
  }

  // ── limiti Claude Code (stima locale) ──────────────────────────
  function fmt(n) {
    if (n >= 1e6) return `${(n / 1e6).toFixed(2)} M`;
    if (n >= 1e3) return `${(n / 1e3).toFixed(1)} k`;
    return String(n);
  }

  async function loadUsage() {
    try {
      const { windows } = await api("project_chat_usage");
      el("u5").textContent = `${fmt(windows["5h"].output)} out · ${windows["5h"].messages} msg`;
      el("u7").textContent = `${fmt(windows["7d"].output)} out · ${windows["7d"].messages} msg`;
      // scala relativa al massimo osservato: solo per leggere l'andamento, non un limite
      const max = Math.max(windows["7d"].output, windows["5h"].output, 1);
      el("b5").style.width = `${Math.round((windows["5h"].output / max) * 100)}%`;
      el("b7").style.width = `${Math.round((windows["7d"].output / max) * 100)}%`;
    } catch {
      el("u5").textContent = "non disponibile";
      el("u7").textContent = "—";
    }
  }

  // ── avvio ──────────────────────────────────────────────────────
  if (window.createJarvisOrb && el("orb-canvas")) {
    orb = window.createJarvisOrb(el("orb-canvas"), { style: "liscia" });
    if (orb && orb.start) orb.start();
  }
  setOrb("idle", "standby");
  loadUsage();
  setInterval(loadUsage, 30000);

  const wanted = new URLSearchParams(location.search).get("project");
  loadProjects()
    .then(async () => {
      if (!wanted) return;
      const { projects } = await api("project_chats");
      const match = projects.find((p) => p.key === wanted);
      if (match) await openProject(match);
    })
    .catch((error) => setChip("", error.message));
})();
