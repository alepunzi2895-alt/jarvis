// Chat per progetto: una sessione Claude Code per progetto, letta e comandata dalla dashboard.
(() => {
  const el = (id) => document.getElementById(id);
  const state = { project: null, lastId: 0, busy: false, timer: null, editable: false };

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

  function setStatus(text) { el("status").textContent = text || ""; }

  async function loadProjects() {
    const { projects } = await api("project_chats");
    const box = el("projects");
    box.textContent = "";
    for (const p of projects) {
      const b = document.createElement("button");
      b.className = "proj" + (p.key === state.project ? " on" : "");
      const name = document.createElement("span");
      name.textContent = (p.busy ? "● " : "") + p.label;
      const sub = document.createElement("small");
      sub.textContent = p.editable ? "modifica attiva" : "sola lettura";
      b.append(name, sub);
      b.addEventListener("click", () => openProject(p));
      box.append(b);
    }
  }

  function render(items) {
    const log = el("log");
    if (!state.lastId) log.textContent = "";
    for (const item of items) {
      state.lastId = Math.max(state.lastId, item.id);
      if (item.kind === "session") continue;
      const m = document.createElement("div");
      m.className = `m ${item.kind}` + (item.status === "error" ? " error" : "");
      const when = (item.at || "").slice(11, 16);
      m.textContent = item.kind === "user" || item.kind === "text" || item.kind === "result"
        ? item.text
        : item.kind === "tool" ? `› ${item.text}`
        : item.text || item.kind;
      if (item.kind === "result") m.title = when;
      log.append(m);
    }
    if (items.length) log.scrollTop = log.scrollHeight;
    if (!log.children.length) log.innerHTML = '<div class="hint">Nessun messaggio ancora.</div>';
  }

  async function poll() {
    if (!state.project) return;
    try {
      const data = await api("project_chat_history", { project: state.project, after: state.lastId });
      render(data.events);
      state.busy = data.busy;
      setStatus(data.busy ? "Claude Code al lavoro…" : data.live ? "sessione in corso (altrove)…" : "pronto");
      updateControls();
    } catch (error) {
      setStatus(error.message);
    }
  }

  // Sessioni Claude Code del progetto (VS Code o terminale): si puo' collegare una diversa.
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
    } catch (error) {
      select.hidden = true;
    }
  }

  el("session").addEventListener("change", async (event) => {
    if (!state.project || !event.target.value) return;
    try {
      await api("project_chat_attach", { project: state.project, session_id: event.target.value });
      state.lastId = 0;
      el("log").textContent = "";
      await poll();
    } catch (error) {
      setStatus(error.message);
    }
  });

  function updateControls() {
    const enabled = state.editable && !state.busy;
    el("input").disabled = !state.editable;
    el("send").disabled = !enabled;
    el("stop").disabled = !state.busy;
  }

  async function openProject(p) {
    state.project = p.key;
    state.editable = p.editable;
    state.lastId = 0;
    el("title").textContent = p.label;
    el("log").textContent = "";
    await loadSessions();
    if (state.timer) clearInterval(state.timer);
    state.timer = setInterval(poll, 2000);
    await loadProjects();
    if (!p.editable) setStatus("cartella in sola lettura: chat disattivata");
    await poll();
  }

  el("form").addEventListener("submit", async (event) => {
    event.preventDefault();
    const text = el("input").value.trim();
    if (!text || !state.project) return;
    try {
      el("input").value = "";
      await api("project_chat_send", { project: state.project, text });
      await poll();
    } catch (error) {
      setStatus(error.message);
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
      await poll();
    } catch (error) {
      setStatus(error.message);
    }
  });

  // Dettatura: il microfono del browser trascrive e invia il prompt a Claude Code.
  const Rec = window.SpeechRecognition || window.webkitSpeechRecognition;
  if (Rec) {
    const rec = new Rec();
    rec.lang = "it-IT";
    rec.interimResults = false;
    el("mic").hidden = false;
    el("mic").addEventListener("click", () => {
      if (!state.project || !state.editable) return;
      rec.start();
      setStatus("ascolto…");
    });
    rec.onresult = (event) => {
      el("input").value = event.results[0][0].transcript;
      el("form").requestSubmit();
    };
    rec.onerror = (event) => setStatus(`microfono: ${event.error}`);
    rec.onend = () => { if (el("status").textContent === "ascolto…") setStatus(""); };
  }

  loadProjects().catch((error) => setStatus(error.message));
})();
