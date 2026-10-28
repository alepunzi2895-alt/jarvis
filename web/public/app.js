// JARVIS dashboard — app.js (vanilla, nessun framework)

const $ = (sel) => document.querySelector(sel);
const compactLayout = window.matchMedia("(max-width: 860px)");
const touchDevice = window.matchMedia("(pointer: coarse)").matches;

function setupViewport() {
  const resize = () => {
    const viewport = window.visualViewport;
    document.body.classList.toggle("short-viewport", compactLayout.matches && (viewport?.height || window.innerHeight) < 640);
    // Non contrastare lo zoom di accessibilita'. La tastiera iOS riduce
    // visualViewport, ma non necessariamente 100vh.
    if (!viewport || viewport.scale === 1) {
      document.documentElement.style.setProperty("--app-height", `${viewport?.height || window.innerHeight}px`);
    }
    fitWeatherWindow();
  };
  resize();
  window.visualViewport?.addEventListener("resize", resize);
  window.addEventListener("resize", resize);
  const syncAnimation = () => {
    if (document.hidden) window.JarvisOrb?.stop();
    else window.JarvisOrb?.start();
  };
  compactLayout.addEventListener("change", syncAnimation);
  document.addEventListener("visibilitychange", syncAnimation);
}

async function api(action, body = {}) {
  let r;
  try {
    r = await fetch("/api/jarvis", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ action, ...body }),
    });
  } catch (error) {
    if (!window.JarvisDirect) setConn("offline");
    throw error;
  }
  // In privato conta il WebSocket, non il successo di un widget HTTP.
  if (!window.JarvisDirect) setConn(r.ok ? "online" : "warning");
  const data = await r.json();
  if (!r.ok) throw new Error(data.error || "errore");
  return data;
}

// ── Finestre fluttuanti ────────────────────────────────────────────────

let topZ = 10;
const dataEscape = (value) => String(value ?? "").replace(/[&<>"']/g, ch => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[ch]));
const dataNumber = (value, digits = 2) => typeof value === "number" && Number.isFinite(value) ? value.toLocaleString("it-IT", {maximumFractionDigits:digits}) : "N/A";
const dataDate = value => value && Number.isFinite(Date.parse(value)) ? new Date(value).toLocaleString("it-IT") : "N/A";

async function refreshMemories() {
  if (!window.JarvisDirect) return;
  const target = $("#memory-items");
  try {
    const {memories = []} = await api("memories_list");
    target.replaceChildren();
    if (!memories.length) { target.textContent = "Nessuna memoria appresa. Puoi dire: ricorda che…"; return; }
    for (const item of memories) {
      const row = document.createElement("article"); row.className = "memory-item";
      const text = document.createElement("p"); text.textContent = item.kind === "avoid_mention" ? `Argomento escluso: ${item.topic}` : item.content;
      const source = document.createElement("small"); source.textContent = `${item.source} · ${dataDate(item.updated_at)}`;
      const button = document.createElement("button"); button.type = "button"; button.textContent = "Dimentica";
      button.onclick = async () => {
        button.disabled = true;
        try { await api("memory_forget", {id:item.id}); await refreshMemories(); }
        catch { button.disabled = false; source.textContent = "Operazione non riuscita. Riprova."; }
      };
      row.append(text, source, button); target.append(row);
    }
  } catch { target.textContent = "Memoria non disponibile. Riprova."; }
}

function equityGraph(points) {
  const rows = (points || []).filter(p => Number.isFinite(p.equity) && Number.isFinite(Date.parse(p.at)));
  if (rows.length < 2) return '<p class="panel-footnote">Il grafico apparirà dopo due campioni reali. Nessuno storico ricostruito.</p>';
  const low = Math.min(...rows.map(p=>p.equity)), high = Math.max(...rows.map(p=>p.equity));
  const start = Date.parse(rows[0].at), span = Math.max(1, Date.parse(rows.at(-1).at) - start);
  const coords = rows.map(p => `${(10 + (Date.parse(p.at)-start)/span*480).toFixed(1)},${(130-(p.equity-low)/(high-low||1)*110).toFixed(1)}`).join(" ");
  return `<svg class="equity-chart" viewBox="0 0 500 150" role="img" aria-label="Equity osservata del conto, asse orizzontale tempo"><polyline points="${coords}" fill="none" stroke="currentColor" stroke-width="2"/></svg><p class="panel-footnote">Min ${dataNumber(low)} · max ${dataNumber(high)} · ${rows.length} campioni<br>${dataDate(rows[0].at)} → ${dataDate(rows.at(-1).at)}</p>`;
}

// ── TradePilot (finestra dedicata): dashboard, dati, esperimenti ─────────
function tradePilotMetric(label, value) {
  return `<div><small>${label}</small><strong>${value}</strong></div>`;
}

function renderTradePilot(data) {
  const dash = $("#tp-dashboard"), table = $("#tp-data"), lab = $("#tp-experiments");
  if (!data.connected) {
    const message = dataEscape(data.error || "TradePilot non raggiungibile. I dati del conto non sono disponibili.");
    for (const target of [dash, table, lab]) target.innerHTML = `<p class="panel-footnote">${message}</p>`;
    return;
  }
  const account = data.account || {}, research = data.research || {}, factory = data.factory || {};
  const healthy = account.status === "ok";
  const money = value => healthy ? `${dataNumber(value)} ${dataEscape(account.currency)}` : "N/A";
  const pct = value => typeof value === "number" ? `${dataNumber(value)}%` : "N/A";
  const counts = data.strategy_counts || {};
  const last = factory.last_batch || {};
  $("#tp-hint").textContent = `${account.mode || "?"} · sola lettura`;
  const link = data.dashboard_url ? `<a class="panel-link" href="${dataEscape(data.dashboard_url)}" target="_blank" rel="noopener noreferrer">Apri dashboard TradePilot ↗</a>` : "";
  dash.innerHTML = `<p class="panel-footnote">VPS · ${dataDate(data.observed_at)}${healthy ? "" : " · conto non disponibile"}</p>
    <div class="data-metrics">${tradePilotMetric("Equity", money(account.equity))}${tradePilotMetric("Saldo", money(account.balance))}${tradePilotMetric("Giorno", pct(account.guard?.day_pct))}${tradePilotMetric("Settimana", pct(account.guard?.week_pct))}${tradePilotMetric("Drawdown dal picco", pct(account.guard?.drawdown_pct))}${tradePilotMetric("Strategie eligible", dataNumber(research.eligible_strategies, 0))}</div>
    ${equityGraph(data.curve)}<p class="panel-footnote">${dataEscape(data.curve_note)}</p>
    <p class="panel-subheading">Strategie</p>
    <p class="panel-footnote">${Object.entries(counts).map(([k, v]) => `${dataEscape(k)} ${v}`).join(" · ") || "Nessuna strategia"}</p>
    <p class="panel-subheading">Factory</p>
    <div class="data-metrics">${tradePilotMetric("Tentativi", dataNumber(factory.n_trials, 0))}${tradePilotMetric("Batch", dataNumber(factory.batches, 0))}${tradePilotMetric("Sopravvissute", dataNumber(factory.survivors, 0))}${tradePilotMetric("Ultimo batch", last.at ? `${dataDate(last.at)} · ${dataEscape(last.experiment)}` : "N/A")}</div>
    ${link}<p class="panel-footnote">${dataEscape(data.notice)}${Object.keys(data.errors || {}).length ? " Fonti parziali: " + dataEscape(Object.keys(data.errors).join(", ")) : ""}</p>`;
  const stats = [...(data.strategy_stats || [])].sort((a, b) => String(a.mode).localeCompare(String(b.mode)) || (b.trades || 0) - (a.trades || 0));
  table.innerHTML = `<p class="panel-footnote">Statistiche per modalità, mai sommate tra demo, shadow e counterfactual. R = rischio iniziale; N = operazioni.</p>
    <div class="data-table"><table><thead><tr><th>Strategia / modalità</th><th>N</th><th>Win %</th><th>PF</th><th>Media R</th><th>Tot R</th></tr></thead><tbody>${stats.map(s => `<tr><td>${dataEscape(s.strategy_id)}<br><b>${dataEscape(s.mode)}</b></td><td>${dataNumber(s.trades, 0)}</td><td>${dataNumber(typeof s.win_rate === "number" ? s.win_rate * 100 : null, 1)}</td><td>${dataNumber(s.profit_factor)}</td><td>${dataNumber(s.expectancy_r, 3)}</td><td>${dataNumber(s.total_r, 2)}</td></tr>`).join("")}</tbody></table></div>
    <p class="panel-subheading">Stato strategie</p>
    ${(data.strategies || []).map(s => `<article class="data-note"><strong>${dataEscape(s.id)} · ${dataEscape(s.status)}</strong><p>${dataEscape(s.evidence || "")}${s.suspension ? " · sospesa: " + dataEscape(s.suspension) : ""}</p></article>`).join("")}`;
  const experiments = [...(data.experiments || [])].reverse();
  lab.innerHTML = `<div class="data-metrics">${tradePilotMetric("Esperimenti", experiments.length)}${tradePilotMetric("Tentativi totali", dataNumber(research.total_trials, 0))}</div>
    <p class="panel-footnote">Registro VPS aggiornato: ${dataEscape(research.updated || "N/A")}. Può differire dal lavoro ancora sul PC.</p>
    ${experiments.map(e => `<article class="data-note"><strong>${dataEscape(e.id)} · ${dataEscape(e.date)} · ${dataEscape(e.verdict)}</strong><p>${dataEscape(e.title)}</p><p class="panel-footnote">${dataEscape(e.headline)}${e.trials ? ` · ${e.trials} tentativi` : ""}</p></article>`).join("")}`;
}

let tradePilotBusy = false;
async function refreshTradePilot() {
  if (!window.JarvisDirect || tradePilotBusy) return;
  tradePilotBusy = true;
  try { renderTradePilot(await api("tradepilot_data")); }
  catch { $("#tp-dashboard").textContent = "TradePilot non disponibile. Riprova."; }
  finally { tradePilotBusy = false; }
}

// ── IVECO: recap per il daily, job Databricks/deploy, IVGAgent, ticket ───
// App di lavoro aperte da "Apri tutte" e dalla voce ("collega tutte le app").
const WORK_APPS = ["teams", "outlook", "databricks_qas", "devops", "servicenow"];
let recapPoll = null;
async function refreshIvecoRecap() {
  const body = $("#iveco-recap-body"), button = $("#iveco-recap-btn");
  try {
    const {recap, running, schedule} = await api("iveco_recap");
    button.disabled = running;
    button.textContent = running ? "Generazione in corso (2-4 min)…" : "Genera ora";
    body.replaceChildren();
    if (!recap) { body.textContent = `Nessun recap ancora. Arriva da solo ${schedule}, anche su Telegram.`; }
    else {
      const meta = document.createElement("p"); meta.className = "panel-footnote";
      meta.textContent = `Generato ${recap.generated_at} · dal ${recap.since} · automatico ${schedule}`;
      const text = document.createElement("pre"); text.className = "recap-text"; text.textContent = recap.text;
      const missing = Object.entries(recap.sources || {}).filter(([, v]) => v !== "ok").map(([k, v]) => `${k}: ${v}`);
      body.append(meta, text);
      if (missing.length) { const note = document.createElement("p"); note.className = "panel-footnote"; note.textContent = "Fonti mancanti — " + missing.join(" · "); body.append(note); }
    }
    clearTimeout(recapPoll);
    if (running) recapPoll = setTimeout(refreshIvecoRecap, 10000);
  } catch { body.textContent = "Recap non disponibile. Riprova."; }
}

async function refreshIvecoJobs() {
  const target = $("#iveco-jobs-body");
  try {
    const data = await api("iveco_jobs");
    target.replaceChildren();
    for (const env of ["prd", "qas"]) {
      const row = data[env] || {};
      const head = document.createElement("p"); head.className = "panel-subheading";
      head.textContent = `Databricks ${env.toUpperCase()} · ultime 24 ore`;
      target.append(head);
      const note = document.createElement("p"); note.className = "panel-footnote";
      const o = row.overall || {};
      note.textContent = row.error || `${o.sample_runs ?? 0} run · ${o.succeeded ?? 0} riuscite · ${o.failed ?? 0} fallite · ${o.canceled ?? 0} annullate${row.complete === false ? " · copertura parziale" : ""}`;
      target.append(note);
      for (const job of row.failing_jobs || []) {
        const item = document.createElement("article"); item.className = "data-note";
        const title = document.createElement("strong"); title.textContent = `${job.job} · ${job.failed}/${job.runs} fallite`;
        const error = document.createElement("p"); error.textContent = job.last_error || "Nessun messaggio di errore.";
        item.append(title, error); target.append(item);
      }
    }
  } catch { target.textContent = "Job Databricks non disponibili. Riprova."; }
  api("devops_data").then(renderDevOps).catch(() => { $("#devops-data").textContent = "Azure DevOps non disponibile."; });
}

let agentPoll = null;
function renderIvgAgent(tasks) {
  const target = $("#ivgagent-tasks");
  target.replaceChildren();
  const labels = {running: "in corso", done: "risposta pronta", blocked: "risposta con azioni negate", error: "errore", interrupted: "interrotto"};
  for (const task of tasks) {
    const item = document.createElement("article"); item.className = "data-note";
    const title = document.createElement("strong"); title.textContent = `${labels[task.status] || task.status} · ${dataDate(task.created_at)}`;
    const prompt = document.createElement("p"); prompt.className = "panel-footnote"; prompt.textContent = task.prompt;
    const result = document.createElement("pre"); result.className = "recap-text"; result.textContent = task.result || "IVGAgent sta lavorando…";
    item.append(title, prompt, result); target.append(item);
  }
  if (!tasks.length) target.textContent = "Nessuna richiesta a IVGAgent.";
  clearTimeout(agentPoll);
  if (tasks.some(t => t.status === "running")) agentPoll = setTimeout(refreshIvgAgent, 8000);
}

async function refreshIvgAgent() {
  try { renderIvgAgent((await api("ivgagent_tasks")).tasks || []); }
  catch { $("#ivgagent-tasks").textContent = "Elenco IVGAgent non disponibile."; }
}

let ticketPoll = null;
async function refreshIvecoTickets() {
  const body = $("#iveco-tickets-body"), button = $("#iveco-tickets-btn");
  try {
    const {report, running, error} = await api("iveco_tickets");
    button.disabled = running;
    button.textContent = running ? "Analisi in corso (1-2 min)…" : "Aggiorna e analizza";
    body.replaceChildren();
    if (error) { const note = document.createElement("p"); note.className = "panel-footnote"; note.textContent = error; body.append(note); }
    if (!report) { body.append("Nessuna analisi ancora. Serve ServiceNow aperto almeno una volta nel browser JARVIS (Collegamenti)."); }
    else {
      const s = report.stats, m = s.last_30_days;
      const meta = document.createElement("p"); meta.className = "panel-footnote";
      meta.textContent = `${s.group} · letto ${s.observed_at}`;
      const head = document.createElement("p"); head.className = "panel-subheading";
      head.textContent = `${s.open} aperti · ${s.work_in_progress} in Work in Progress (${s.wip_without_development} senza sviluppo visibile) · ${s.stale} fermi da oltre 30 giorni`;
      const flow = document.createElement("p"); flow.className = "panel-footnote";
      flow.textContent = `Ultimi 30 giorni: ${m.opened} aperti, ${m.closed} chiusi (${m.cancelled} annullati)` +
        (s.median_days_to_close != null ? ` · chiusura mediana ${s.median_days_to_close} giorni` : "") +
        " · per persona: " + Object.entries(s.by_person).map(([k, v]) => `${k} ${v}`).join(", ");
      body.append(meta, head, flow);
      for (const t of s.tickets) {
        const item = document.createElement("article"); item.className = "data-note";
        const title = document.createElement("strong");
        title.textContent = `${t.number} · ${t.state} · ${t.assigned_to}${t.stale ? " · fermo" : ""}`;
        const info = document.createElement("p");
        info.textContent = `Aperto da ${t.age_days} giorni · ultima nota ${t.last_note || "nessuna"}` +
          (t.last_note_by ? ` (${t.last_note_by})` : "") + " · sviluppo: " +
          (t.linked_development.length ? t.linked_development.join(", ") : "nessuna citazione");
        item.append(title, info); body.append(item);
      }
      const text = document.createElement("pre"); text.className = "recap-text"; text.textContent = report.analysis;
      body.append(text);
    }
    clearTimeout(ticketPoll);
    if (running) ticketPoll = setTimeout(refreshIvecoTickets, 8000);
  } catch { body.textContent = "Ticket non disponibili. Riprova."; }
}

function refreshIveco() {
  refreshIvecoRecap();
  refreshIvecoJobs();
  refreshIvgAgent();
  refreshIvecoTickets();
}

function setupIveco() {
  $("#iveco-tickets-btn").addEventListener("click", async () => {
    $("#iveco-tickets-btn").disabled = true;
    try { await api("iveco_tickets_run"); } finally { refreshIvecoTickets(); }
  });
  $("#iveco-recap-btn").addEventListener("click", async () => {
    $("#iveco-recap-btn").disabled = true;
    try { await api("iveco_recap_run"); } finally { refreshIvecoRecap(); }
  });
  $("#ivgagent-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    const field = $("#ivgagent-text"), prompt = field.value.trim();
    if (!prompt) return;
    const button = event.submitter; if (button) button.disabled = true;
    try { renderIvgAgent((await api("ivgagent_ask", {prompt})).tasks || []); field.value = ""; }
    catch (error) { $("#ivgagent-tasks").textContent = error.message || "Invio non riuscito."; }
    finally { if (button) button.disabled = false; }
  });
}

// Schede dei pannelli: un solo pannello visibile per finestra.
function setupPanelTabs() {
  document.querySelectorAll(".panel-tabs").forEach((bar) => {
    const tabs = [...bar.querySelectorAll('[role="tab"]')];
    tabs.forEach((tab) => tab.addEventListener("click", () => {
      for (const other of tabs) {
        const selected = other === tab;
        other.setAttribute("aria-selected", String(selected));
        document.getElementById(other.getAttribute("aria-controls")).hidden = !selected;
      }
    }));
  });
}

let connectedDataBusy = false;
async function refreshConnectedData() {
  if (!window.JarvisDirect || connectedDataBusy) return;
  connectedDataBusy = true;
  try {
    await Promise.all([
      api("coding_tasks").then(data => {
        const target = $("#coding-jobs"); target.replaceChildren();
        if (!data.jobs?.length && !data.sessions?.length) target.textContent = "Nessun lavoro. Chiedi a JARVIS di inviare un prompt a Codex o Claude Code.";
        for (const job of data.jobs || []) {
          const row = document.createElement("article"); row.className = "data-note";
          const status = ({running:"in corso",done:"risposta disponibile",blocked:"serve attenzione",error:"errore",interrupted:"interrotto"})[job.status] || job.status;
          const title = document.createElement("strong"); title.textContent = `${job.provider} · ${job.project} · ${status}`;
          const result = document.createElement("p"); result.textContent = job.result || job.prompt;
          row.append(title, result); target.append(row);
        }
        // Sessioni aperte da Alessandro in VS Code/terminale/Codex, non avviate da JARVIS.
        for (const session of data.sessions || []) {
          const row = document.createElement("article"); row.className = "data-note";
          const title = document.createElement("strong");
          title.textContent = `${session.provider} · ${session.project || "?"} · ${session.state} · ${session.minutes_ago} min fa`;
          const result = document.createElement("p"); result.textContent = session.title || session.last_prompt;
          row.append(title, result); target.append(row);
        }
      }).catch(() => { $("#coding-jobs").textContent = "Stato lavori non disponibile."; })
    ]);
  } finally { connectedDataBusy = false; }
}

function renderDevOps(data) {
  const target = $("#devops-data");
  target.replaceChildren();
  const title = document.createElement("p"); title.className = "panel-subheading"; title.textContent = "Iveco · Deploy Azure DevOps";
  target.append(title);
  const note = document.createElement("p"); note.className = "panel-footnote";
  note.textContent = data.error || `Controllato: ${dataDate(data.observed_at)}. ${data.notice || ""}${data.partial ? " Copertura parziale." : ""}${Object.keys(data.errors || {}).length ? " Fonti non disponibili: " + Object.keys(data.errors).join(", ") : ""}`;
  target.append(note);
  for (const row of data.stages || []) {
    const item = document.createElement("article"); item.className = "data-note";
    const status = ({succeeded:"riuscita", skipped:"non eseguita", failed:"fallita", canceled:"annullata", inProgress:"in corso", pending:"in attesa", succeededWithIssues:"riuscita con problemi"})[row.status] || row.status;
    item.textContent = `Fase: ${row.name} · ${status} · ${dataDate(row.at)} · run ${row.build_number}`;
    target.append(item);
  }
  for (const row of data.job_attention || []) {
    const item = document.createElement("p"); item.className = "panel-footnote";
    item.textContent = `Da verificare: job ${row.name}, run ${row.build_number} · ${row.errors} errori · ${row.warnings} avvisi`;
    target.append(item);
  }
  if (data.connected && !(data.stages || []).length && !(data.deployments || []).length) {
    const empty = document.createElement("p"); empty.className = "panel-footnote";
    empty.textContent = "Nessun record di deploy o fase disponibile nelle fonti consultate."; target.append(empty);
  }
  for (const row of data.deployments || []) {
    const item = document.createElement("article"); item.className = "data-note";
    item.textContent = `${row.name} · ${row.environment || "ambiente non dichiarato"} · ${row.status} · ${dataDate(row.at)}`;
    target.append(item);
  }
  if ((data.builds || []).length) {
    const detail = document.createElement("details"), heading = document.createElement("summary");
    heading.textContent = "Build recenti (non equivalgono a deploy)"; detail.append(heading);
    for (const row of data.builds) { const p = document.createElement("p"); p.textContent = `${row.name} · ${row.branch} · ${row.result || row.status} · ${dataDate(row.at)}`; detail.append(p); }
    target.append(detail);
  }
}

function bringToFront(win) {
  topZ += 1;
  win.style.zIndex = topZ;
}

function dockBtnFor(id) {
  return document.querySelector(`.dock-btn[data-toggle="${id}"]`);
}

function openWindow(id) {
  const win = document.getElementById(id);
  if (!win) return;
  if (compactLayout.matches) {
    document.querySelectorAll(".floating-window.open, .chat-overlay.open").forEach((other) => {
      if (other !== win) closeWindow(other.id);
    });
  }
  if (win.classList.contains("open")) return;
  win.classList.add("open");
  // La conversazione non e' una finestra: resta sotto ai pannelli e non si sposta per la sfera.
  const floating = win.classList.contains("floating-window");
  if (floating) bringToFront(win);
  dockBtnFor(id)?.classList.add("open");
  dockBtnFor(id)?.setAttribute("aria-pressed", "true");
  if (id === "win-brain") { startBrainGraph(); refreshMemories(); }
  if (id === "win-projects") refreshConnectedData();
  if (id === "win-tradepilot") refreshTradePilot();
  if (id === "win-iveco") refreshIveco();
  if (id === "win-camera") startCamera();
  if (id === "win-weather") {
    fitWeatherWindow();
    refreshWeatherForecast();
  }
  if (floating) clearOrb(win);
}

// Le finestre non coprono mai la sfera (Alessandro, 2026-10-27). Desktop: una
// finestra che la tocca si sposta di lato, sopra o sotto, del minimo
// necessario; se e' troppo larga si stringe; senza spazio la sfera passa
// davanti. Su mobile la sfera ha gia' il suo spazio sopra il pannello.
const ORB_GAP = 12;
const WINDOW_MIN_WIDTH = 280; // min-width di .floating-window

function orbCircle() {
  const box = $("#jarvis-orb").getBoundingClientRect();
  return { x: box.left + box.width / 2, y: box.top + box.height / 2, r: box.width / 2 + ORB_GAP };
}

function stageLimits() {
  const stage = $("#hud-stage").getBoundingClientRect();
  return {
    stage,
    left: stage.left + 8,
    right: stage.right - 8,
    top: Math.max(stage.top, $("#app > header").getBoundingClientRect().bottom) + 8,
    bottom: Math.min(stage.bottom, $(".dock").getBoundingClientRect().top) - 8,
  };
}

// Posizione finale dalla regola CSS (centro scena + --x/--y), non dal
// rettangolo a schermo: durante l'animazione di apertura quello e' scalato.
function windowBox(win, stage) {
  const w = win.offsetWidth, h = win.offsetHeight;
  const x = parseFloat(win.style.getPropertyValue("--x")) || 0;
  const y = parseFloat(win.style.getPropertyValue("--y")) || 0;
  const anchor = stage.left + parseFloat(getComputedStyle(win).left);
  const left = (win.id === "win-chat" ? anchor : anchor - w / 2) + x; // la console e' ancorata a sinistra
  const top = stage.top + stage.height / 2 - h / 2 + y;
  return { left, top, right: left + w, bottom: top + h };
}

function coversOrb(box, orb) {
  const dx = Math.max(box.left - orb.x, 0, orb.x - box.right);
  const dy = Math.max(box.top - orb.y, 0, orb.y - box.bottom);
  return dx * dx + dy * dy < orb.r * orb.r;
}

function shiftWindow(win, dx, dy) {
  win.style.setProperty("--x", `${(parseFloat(win.style.getPropertyValue("--x")) || 0) + dx}px`);
  win.style.setProperty("--y", `${(parseFloat(win.style.getPropertyValue("--y")) || 0) + dy}px`);
}

function keepOrbClear(win) {
  if (compactLayout.matches || !win.classList.contains("open")) return;
  const limits = stageLimits(), orb = orbCircle();
  if (!limits.stage.width) return; // dashboard non ancora visibile (login)
  let box = windowBox(win, limits.stage);
  if (!coversOrb(box, orb)) return;
  const moves = [
    { dx: orb.x + orb.r - box.left, dy: 0 },
    { dx: orb.x - orb.r - box.right, dy: 0 },
    { dx: 0, dy: orb.y - orb.r - box.bottom },
    { dx: 0, dy: orb.y + orb.r - box.top },
  ].filter(({ dx, dy }) => (dx
    ? box.left + dx >= limits.left && box.right + dx <= limits.right
    : box.top + dy >= limits.top && box.bottom + dy <= limits.bottom));
  if (moves.length) {
    const best = moves.reduce((a, b) => (Math.abs(a.dx + a.dy) <= Math.abs(b.dx + b.dy) ? a : b));
    shiftWindow(win, best.dx, best.dy);
    return;
  }
  // Troppo larga per stare di lato: si stringe sul lato con piu' spazio.
  const rightRoom = limits.right - (orb.x + orb.r), leftRoom = orb.x - orb.r - limits.left;
  const toRight = win.id !== "win-chat" && rightRoom >= leftRoom;
  const room = Math.floor(toRight ? rightRoom : leftRoom);
  if (room < WINDOW_MIN_WIDTH) return;
  win.style.width = `${room}px`;
  box = windowBox(win, limits.stage); // piu' stretta = piu' alta: resta tra intestazione e dock
  const dy = box.top < limits.top ? limits.top - box.top : Math.max(limits.top - box.top, Math.min(0, limits.bottom - box.bottom));
  shiftWindow(win, toRight ? orb.x + orb.r - box.left : orb.x - orb.r - box.right, dy);
}

function updateOrbLayer() {
  const stage = $("#hud-stage").getBoundingClientRect(), orb = orbCircle();
  const covered = !compactLayout.matches && stage.width > 0 && [...document.querySelectorAll(".floating-window.open")]
    .some((win) => coversOrb(windowBox(win, stage), orb));
  $("#jarvis-orb").classList.toggle("orb-front", covered);
}

function clearOrb(win) {
  keepOrbClear(win);
  updateOrbLayer();
}

function fitWeatherWindow() {
  const win = $("#win-weather");
  if (compactLayout.matches || !win?.classList.contains("open")) return;
  const stage = $("#hud-stage").getBoundingClientRect();
  const top = $("#app > header").getBoundingClientRect().bottom + 12;
  const bottom = $(".dock").getBoundingClientRect().top - 12;
  const height = win.offsetHeight;
  const center = stage.top + stage.height / 2;
  const current = center + (parseFloat(win.style.getPropertyValue("--y")) || 0);
  const y = Math.max(top + height / 2, Math.min(current, bottom - height / 2));
  win.style.setProperty("--y", `${y - center}px`);
}

function closeWindow(id) {
  const win = document.getElementById(id);
  if (!win || !win.classList.contains("open")) return;
  win.classList.remove("open");
  dockBtnFor(id)?.classList.remove("open");
  dockBtnFor(id)?.setAttribute("aria-pressed", "false");
  if (id === "win-brain") stopBrainGraph();
  if (id === "win-camera") stopCamera();
  updateOrbLayer();
}

// Ologramma accanto alla console: un solo passaggio al caricamento della pagina,
// poi scompare. Video locale /media/online.mp4 (senza audio).
function playHologramIntro() {
  const holo = document.getElementById("hologram");
  const video = holo?.querySelector("video");
  if (!holo || !video) return;
  const done = () => holo.classList.remove("open");
  video.addEventListener("ended", done, { once: true });
  video.addEventListener("error", done, { once: true });
  if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) { done(); return; }
  video.play().catch(done);
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
    if (compactLayout.matches) return;
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
  const stopDrag = () => {
    if (dragging) clearOrb(win); // lasciata sopra la sfera: scivola di lato
    dragging = false;
  };
  header.addEventListener("pointerup", stopDrag);
  header.addEventListener("pointercancel", stopDrag);
}

function setupWindows() {
  const fitPanels = () => {
    if (!compactLayout.matches) return;
    const panels = [...document.querySelectorAll(".floating-window.open")];
    panels.sort((a, b) => Number(b.style.zIndex) - Number(a.style.zIndex));
    if (panels[0]) openWindow(panels[0].id);
  };
  compactLayout.addEventListener("change", fitPanels);
  // Contenuti che crescono, ridimensionamento a mano, finestra del browser
  // cambiata o dashboard che appare dopo il login: la sfera resta libera.
  const sizes = new ResizeObserver((entries) => entries.forEach(({ target }) => {
    if (target.id === "hud-stage") document.querySelectorAll(".floating-window.open").forEach(clearOrb);
    else clearOrb(target);
  }));
  sizes.observe($("#hud-stage"));
  document.querySelectorAll(".floating-window").forEach((win) => {
    makeDraggable(win);
    bringToFront(win);
    sizes.observe(win);
  });
  document.querySelectorAll(".dock-btn").forEach((btn) => {
    btn.setAttribute("aria-label", btn.title);
    btn.setAttribute("aria-controls", btn.dataset.toggle);
    btn.setAttribute("aria-pressed", String(btn.classList.contains("open")));
    btn.addEventListener("click", () => {
      const id = btn.dataset.toggle;
      const wasOpen = document.getElementById(id)?.classList.contains("open");
      toggleWindow(id);
      // "quando vedo le percentuali dei progetti... mi facesse un'analisi
      // vocale" (2026-09-15): apre il pannello E sottopone la stessa
      // domanda che risponderebbe a voce/testo - passa dall'intent rapido
      // gia' esistente (core/intents.py::_PROJECT_STATUS_RE), che
      // web_bridge.py fa gia' parlare in automatico per ogni task da
      // dashboard. Solo sull'APERTURA manuale (non alla chiusura, e non
      // quando l'apertura e' gia' un effetto collaterale di una domanda
      // vocale completa - vedi handleVoiceUiCommand, che non passa da qui).
      if (id === "win-projects" && !wasOpen) {
        submitTask("come vanno i progetti?", undefined, { openConsole: !compactLayout.matches });
      }
    });
  });
  document.querySelectorAll(".fw-close").forEach((btn) => {
    btn.setAttribute("aria-label", "Chiudi pannello");
    btn.addEventListener("click", () => closeWindow(btn.dataset.close));
  });
  document.querySelectorAll("[data-connect-app]").forEach((button) => {
    button.addEventListener("click", () => {
      const app = button.dataset.connectApp;
      connectApps(app === "all" ? WORK_APPS : [app]);
    });
  });
  fitPanels();
  playHologramIntro();
}

// ── Login ────────────────────────────────────────────────────────────

if (window.JARVIS_TAILNET_AUTH) $("#logout-btn").hidden = true;

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

$("#logout-btn").addEventListener("click", async () => {
  if (window.JarvisDirect) {
    window.JarvisDirect.cancel();
    await api("logout");
  }
  document.cookie = "jarvis_session=; Path=/; Max-Age=0";
  location.reload();
});

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
    connecting: ["warning", "collegamento"],
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
  // Progetto rilevato automaticamente dal testo (non piu' scelto a mano
  // dalla dashboard) — l'HUD mostra l'ultimo, solo a scopo informativo.
  if (task.workspace) $("#hud-ws").textContent = task.workspace;
  $("#console-log").scrollTop = $("#console-log").scrollHeight;
  // La bolla torna a idle quando la risposta arriva (se JARVIS deve anche
  // parlarla, pollSpeakingStatus() la porta a "speaking" al prossimo giro di
  // polling) — su errore lampeggia rosso per un attimo invece di sparire subito.
  if (task.status === "error") setOrbAlert();
  else if (orbState === "thinking") setOrbState("idle");
}

async function pollTask(taskId, el) {
  for (let i = 0; i < 200; i++) {
    await new Promise((r) => setTimeout(r, 1500));
    try {
      const { task } = await api("task_poll", { task_id: taskId });
      // "superseded" (2026-09-16): una domanda piu' recente ha sostituito
      // questa prima che partisse — non e' un errore/timeout, dillo chiaro
      // invece di lasciar scadere i 200 tentativi con un falso "Timeout".
      if (task.status === "superseded") {
        fillEntry(el, { status: "done", result: "Sostituita da una domanda più recente." });
        return;
      }
      // Rumore scartato dal filtro "Jarvis": prima non era gestito qui e
      // dopo 200 tentativi mostrava un falso "Timeout" (es. "Alla prossima!").
      if (task.status === "ignored") {
        el.remove();
        return;
      }
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

async function submitTask(text, imageB64, options = {}) {
  if (!text.trim()) return;
  if (options.openConsole !== false) openWindow("win-chat");
  const el = appendEntry(text);
  $("#console-text").value = "";
  if (window.JarvisDirect) {
    return window.JarvisDirect.submit({ type: "text", prompt: text, image_b64: imageB64 }, el);
  }
  try {
    // Niente piu' "workspace" dal client — il bridge locale lo rileva da
    // solo dal testo (core/claude_bridge.py::detect_workspace).
    const body = { prompt: text };
    if (imageB64) body.image_b64 = imageB64;
    const { task_id } = await api("task_push", body);
    setOrbState("thinking");
    pollTask(task_id, el);
  } catch (err) {
    fillEntry(el, { status: "error", result: err.message });
  }
}

$("#console-form").addEventListener("submit", (e) => {
  e.preventDefault();
  submitTask($("#console-text").value);
});

// Messaggi scambiati fuori da questa chat (Telegram, voce sul PC, avvisi):
// stessa console, con l'origine nella riga meta.
const FEED_SOURCES = { telegram: "Telegram", telegram_in: "da Telegram", voce: "voce PC" };

function appendFeed(item) {
  const el = appendEntry(item.prompt || "");
  el.classList.remove("pending");
  el.classList.add("feed");
  if (!item.prompt) el.querySelector(".prompt").remove();
  if (item.text) el.querySelector(".result").textContent = item.text;
  else el.querySelector(".result").remove();
  el.querySelector(".meta").textContent = `${FEED_SOURCES[item.source] || item.source} · ${(item.at || "").slice(11, 16)}`;
  $("#console-log").scrollTop = $("#console-log").scrollHeight;
}
window.appendFeed = appendFeed;

async function loadHistory() {
  try {
    const { tasks } = await api("tasks_recent", { limit: 20 });
    $("#hud-taskcount").textContent = tasks.length;
    for (const t of tasks.reverse()) {
      if (t.kind === "feed") {
        appendFeed({ ...t, text: t.result });
        continue;
      }
      if (t.status === "ignored" || t.status === "superseded") continue; // rumore/superate: non sono storia
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
// 2026-09-15, secondo giro: segnalato dal vivo che spesso la trascrizione
// tornava vuota ("non ho capito niente dall'audio") anche per frasi vere e
// intere. Causa quasi certa: la primissima versione catturava ogni
// segmento con un MediaRecorder NUOVO creato solo dopo aver rilevato voce
// (nessun pre-buffer, vedi nota sotto) — probabile che tagliasse via più
// della sola prima sillaba. Riscritto per catturare PCM grezzo in
// continuo con AudioContext/ScriptProcessorNode (invece di MediaRecorder):
// un buffer circolare tiene sempre gli ultimi ~PREROLL_MS di audio, cosi'
// quando si rileva voce il segmento include gia' l'attimo prima
// dell'attivazione — mai più un inizio tagliato. Il segmento raccolto
// viene incapsulato in un WAV al volo (nessuna libreria, ~20 righe) invece
// di un file webm/opus — stessa cosa che core/voice/stt.py sa gia'
// decodificare, un formato in meno di cui fidarsi.

// Intercetta i comandi che aprono/chiudono le finestre PRIMA di sottoporli
// a Claude — istantaneo, nessuna chiamata task per queste azioni di UI.
function handleVoiceUiCommand(text) {
  const t = text.toLowerCase();
  const wants = (re) => re.test(t);
  const verb = /\b(apri|accendi|attiva|mostra)\b/;
  const closeVerb = /\b(chiudi|nascondi|spegni)\b/;

  if (wants(/\b(collega|connessioni|autentica)\b/) && wants(/\b(teams|outlook|databricks|devops|azure|servicenow|ticket|app|servizi)\b/)) {
    openWindow("win-connections");
    const selected = wants(/\b(tutti|tutte|tutto|app|servizi)\b/)
      ? WORK_APPS
      : [
          ...(wants(/\bteams\b/) ? ["teams"] : []),
          ...(wants(/\boutlook\b/) ? ["outlook"] : []),
          ...(wants(/\bdatabricks\b/) ? ["databricks_qas"] : []),
          ...(wants(/\b(devops|azure)\b/) ? ["devops"] : []),
          ...(wants(/\b(servicenow|ticket)\b/) ? ["servicenow"] : []),
        ];
    if (selected.length) connectApps(selected);
    return true;
  }

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
    if (wants(verb)) { openWindow("win-projects"); return true; }
    if (wants(closeVerb)) { closeWindow("win-projects"); return true; }
  }
  if (wants(/\btrade\s*pilot\b/) && window.JarvisDirect) {
    if (wants(verb)) { openWindow("win-tradepilot"); return true; }
    if (wants(closeVerb)) { closeWindow("win-tradepilot"); return true; }
  }
  if (wants(/\b(iveco|ivg\s*agent)\b/) && window.JarvisDirect) {
    if (wants(verb)) { openWindow("win-iveco"); return true; }
    if (wants(closeVerb)) { closeWindow("win-iveco"); return true; }
  }
  // Meteo/progetti: si aprono anche solo chiedendo ("che tempo fa", "come
  // siamo messi con i progetti") senza dover dire esplicitamente "apri" —
  // e SENZA return true, perche' la domanda deve comunque proseguire verso
  // l'intent rapido che da' la risposta vera (qui si apre solo il pannello
  // visivo come effetto collaterale).
  if (wants(/\bmeteo\b/) || wants(/\btempo\s+fa\b/)) {
    if (wants(closeVerb)) { closeWindow("win-weather"); return true; }
    openWindow("win-weather");
  }
  if (wants(/\bprogett[oi]\b/)) {
    if (wants(closeVerb)) { closeWindow("win-projects"); return true; }
    openWindow("win-projects");
  }
  return false;
}

async function connectApps(apps) {
  const status = $("#connections-status");
  if (!status) return;
  status.textContent = "Apro le app nella sessione JARVIS…";
  try {
    const data = await api("connect_apps", { apps });
    status.textContent = data.results.map((result) => result.message).join(" ");
  } catch (error) {
    status.textContent = error.message || "Collegamento non riuscito.";
  }
}

// 2026-09-15, terzo giro: verificato dal vivo (logs/bot.log) che 0.02 era
// troppo basso — scattava su rumore di fondo/ventola, restava "in
// ascolto" per l'intero tetto di 15s ripetutamente, e whisper allucinava
// testo plausibile su quell'audio quasi silenzioso (frasi tipo "Sottotitoli
// a cura di QTSS" — artefatto notissimo di whisper su input silenzioso/
// rumoroso, non un bug di decodifica). Alzata la soglia + richiesto che il
// suono resti sopra soglia per un tratto minimo continuo (non un singolo
// blip) prima di considerarlo davvero l'inizio di una frase.
// Il privato filtra comunque Jarvis lato server. 0.06 scartava voce normale
// di volume basso; 0.012 e' vicino alla soglia del microfono nativo (300/32768).
const MIC_SILENCE_RMS = window.JARVIS_LOCAL ? 0.012 : 0.06;
const MIC_ONSET_SUSTAIN_MS = 200; // il suono deve restare sopra soglia per questo tratto continuo prima di far scattare la registrazione
const MIC_SILENCE_HANG_MS = 800; // allineato al default del daemon locale
const MIC_MAX_RECORD_MS = 15000;
const MIC_PREROLL_MS = 400; // audio tenuto PRIMA del rilevamento voce, cosi' l'inizio non si taglia mai
const MIC_MIN_SEGMENT_MS = 300; // sotto questa durata e' rumore/click, scartato
// Soglia usata SOLO mentre JARVIS sta parlando (barge-in): molto piu' alta
// della normale MIC_SILENCE_RMS apposta — l'audio di JARVIS stesso esce
// dagli altoparlanti del PC e rientra nel mic (stesso problema di eco gia'
// risolto silenziando del tutto durante il parlato), quindi durante il
// parlato si registra SOLO se qualcuno interrompe parlando chiaramente piu'
// forte/vicino di quel rientro — non su qualunque suono. Sotto questa soglia
// resta muto come prima (nessuna regressione sul problema di eco).
const MIC_INTERRUPT_RMS = 0.22;
const MIC_INTERRUPT_ONSET_SUSTAIN_MS = 300; // piu' lungo del normale: un picco isolato dell'eco non deve bastare

function _pcmRms(data) {
  let sum = 0;
  for (let i = 0; i < data.length; i++) sum += data[i] * data[i];
  return Math.sqrt(sum / data.length);
}

function _concatFloat32(chunks) {
  const total = chunks.reduce((s, c) => s + c.length, 0);
  const out = new Float32Array(total);
  let offset = 0;
  for (const c of chunks) {
    out.set(c, offset);
    offset += c.length;
  }
  return out;
}

// WAV mono 16-bit PCM al volo — nessuna libreria, cosi' il server (faster-whisper
// via PyAV) decodifica un formato semplice e senza ambiguita' invece di webm/opus.
function _encodeWav(samples, sampleRate) {
  const buffer = new ArrayBuffer(44 + samples.length * 2);
  const view = new DataView(buffer);
  const writeString = (offset, str) => {
    for (let i = 0; i < str.length; i++) view.setUint8(offset + i, str.charCodeAt(i));
  };
  writeString(0, "RIFF");
  view.setUint32(4, 36 + samples.length * 2, true);
  writeString(8, "WAVE");
  writeString(12, "fmt ");
  view.setUint32(16, 16, true);
  view.setUint16(20, 1, true); // PCM
  view.setUint16(22, 1, true); // mono
  view.setUint32(24, sampleRate, true);
  view.setUint32(28, sampleRate * 2, true); // byte rate (16 bit mono)
  view.setUint16(32, 2, true); // block align
  view.setUint16(34, 16, true); // bit depth
  writeString(36, "data");
  view.setUint32(40, samples.length * 2, true);
  let offset = 44;
  for (let i = 0; i < samples.length; i++, offset += 2) {
    const s = Math.max(-1, Math.min(1, samples[i]));
    view.setInt16(offset, s < 0 ? s * 0x8000 : s * 0x7fff, true);
  }
  return new Blob([buffer], { type: "audio/wav" });
}

function setupVoice() {
  const micBtn = $("#mic-btn");
  function showMicStatus(message) {
    micBtn.title = message;
    micBtn.setAttribute("aria-label", message);
    $("#voice-status").textContent = message;
  }
  if (!navigator.mediaDevices || !(window.AudioContext || window.webkitAudioContext)) {
    micBtn.disabled = true;
    showMicStatus("Microfono non disponibile: apri JARVIS in HTTPS su Safari o Chrome");
    return;
  }

  const OFF_TITLE = 'Tocca il microfono, poi di’ “Jarvis” e il comando';
  const ON_TITLE = 'Ti ascolto · di’ “Jarvis” e il comando';
  showMicStatus(OFF_TITLE);

  let armed = false;
  let stream = null;
  let audioCtx = null;
  let processor = null;
  let silentSink = null;

  // Stato del rilevamento voce/silenzio — un buffer circolare di "preroll"
  // mentre si aspetta l'inizio del parlato, poi il segmento vero e proprio.
  let recording = false;
  let prerollChunks = [];
  let prerollMs = 0;
  let segmentChunks = [];
  let segmentMs = 0;
  let silenceMs = 0;
  let onsetCandidateMs = 0; // quanto suono continuo sopra soglia si e' visto finora, PRIMA di committare la registrazione
  let hitMaxDuration = false;

  function _chunkMs(chunk) {
    return (chunk.length / audioCtx.sampleRate) * 1000;
  }

  function finalizeSegment() {
    recording = false;
    if (orbState === "listening") setOrbState("idle"); // "thinking" arriva solo se il segmento va sottoposto davvero
    const samples = _concatFloat32(segmentChunks);
    segmentChunks = [];
    const durationMs = (samples.length / audioCtx.sampleRate) * 1000;
    const wasMaxDuration = hitMaxDuration;
    segmentMs = 0;
    silenceMs = 0;
    hitMaxDuration = false;
    if (durationMs < MIC_MIN_SEGMENT_MS) return; // troppo corto: rumore/click, non voce vera
    if (wasMaxDuration) return; // mai una pausa vera per 15s intere: quasi certamente rumore di fondo, non un comando
    handleRecordedAudio(_encodeWav(samples, audioCtx.sampleRate));
  }

  // Non accodare un'attivazione: su iOS perderebbe il gesto utente,
  // e potrebbe accendere il mic molto dopo il tap che l'ha richiesta.
  let arming = false;
  let attempt = 0;
  let releaseMicLock = null;

  function acquireMicLock(token) {
    if (!navigator.locks) return Promise.resolve(true);
    return new Promise((resolve, reject) => {
      navigator.locks.request("jarvis-mic", { ifAvailable: true }, (lock) => {
        if (!lock || token !== attempt) { resolve(false); return; }
        resolve(true);
        return new Promise((release) => { releaseMicLock = release; });
      }).catch(reject);
    });
  }

  function freeMicLock() {
    releaseMicLock?.();
    releaseMicLock = null;
  }

  async function arm() {
    window.JarvisDirect?.unlock();
    if (armed || arming) return;
    const token = ++attempt;
    arming = true;
    showMicStatus("Attivazione microfono… Tocca di nuovo per annullare");
    try {
      // Creazione e resume devono iniziare NEL gesto utente, prima dei
      // permessi asincroni. Safari altrimenti lascia il contesto sospeso.
      const ctx = new (window.AudioContext || window.webkitAudioContext)();
      audioCtx = ctx;
      ctx.resume().catch(() => {});
      const acquired = await acquireMicLock(token);
      if (token !== attempt) return;
      if (!acquired) {
        disarm(false, "Microfono attivo in un’altra scheda. Chiudila e riprova.");
        return;
      }
      const requestedStream = await navigator.mediaDevices.getUserMedia({
        audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true, autoGainControl: true },
      });
      if (token !== attempt) {
        requestedStream.getTracks().forEach((track) => track.stop());
        return;
      }
      stream = requestedStream;
      if (ctx.state !== "running") {
        disarm(false, "Tocca il microfono per riattivare l’audio");
        return;
      }
      arming = false;

      armed = true;
      window.JarvisDirect?.setMicEnabled(true);
      micBtn.classList.add("listening");
      micBtn.setAttribute("aria-pressed", "true");
      showMicStatus(ON_TITLE);
      prerollChunks = [];
      prerollMs = 0;
      segmentChunks = [];
      segmentMs = 0;
      silenceMs = 0;
      onsetCandidateMs = 0;
      hitMaxDuration = false;
      recording = false;

      const source = audioCtx.createMediaStreamSource(stream);
      // ScriptProcessorNode e' deprecato ma universalmente supportato — per un
      // singolo tool interno non serve il carico in piu' di un AudioWorklet
      // (un file JS separato solo per questo). Va comunque collegato a una
      // destinazione per essere eseguito in alcuni browser: un GainNode a
      // volume zero lo tiene "vivo" senza mandare l'audio agli altoparlanti
      // (altrimenti si sentirebbe un eco del proprio microfono).
      processor = audioCtx.createScriptProcessor(4096, 1, 1);
      silentSink = audioCtx.createGain();
      silentSink.gain.value = 0;
      source.connect(processor);
      processor.connect(silentSink);
      silentSink.connect(audioCtx.destination);
      ctx.onstatechange = () => {
        if (armed && ctx.state !== "running") disarm(false, "Audio interrotto · tocca il microfono per riprendere");
      };
      stream.getAudioTracks().forEach((track) => {
        track.onended = () => disarm(false, "Microfono scollegato · tocca per riprovare");
      });

      processor.onaudioprocess = (e) => {
        if (!armed) return;
        const data = e.inputBuffer.getChannelData(0).slice(); // copia: il buffer sorgente viene riusato dal browser
        const chunkMs = _chunkMs(data);
        const rms = _pcmRms(data);

        // JARVIS sta parlando dagli altoparlanti del PC (processo Python
        // separato, non nel browser) — il mic normalmente tace del tutto per
        // non risentirsi da solo, MA con una soglia molto piu' alta (e un
        // debounce piu' lungo) resta possibile interromperlo dicendo "hey
        // jarvis" chiaramente sopra l'eco del proprio parlato (barge-in,
        // 2026-09-15). Niente pre-buffer in questa modalita': prima della
        // soglia c'e' solo l'eco di JARVIS, non ha senso includerlo.
        const silenceThreshold = botSpeaking ? MIC_INTERRUPT_RMS : MIC_SILENCE_RMS;
        const onsetSustainNeeded = botSpeaking ? MIC_INTERRUPT_ONSET_SUSTAIN_MS : MIC_ONSET_SUSTAIN_MS;
        const speaking = rms > silenceThreshold;

        if (!recording) {
          if (!botSpeaking) {
            prerollChunks.push(data);
            prerollMs += chunkMs;
            while (prerollChunks.length > 1 && prerollMs - _chunkMs(prerollChunks[0]) >= MIC_PREROLL_MS) {
              prerollMs -= _chunkMs(prerollChunks.shift());
            }
          } else if (prerollChunks.length) {
            // Non usato in questa modalita': tenerlo svuotato evita che audio
            // "vecchio" (da prima che JARVIS iniziasse a parlare) venga
            // riesumato come pre-buffer quando torna in ascolto normale.
            prerollChunks = [];
            prerollMs = 0;
          }
          // Debounce: un singolo blip sopra soglia (click, colpo di tosse breve,
          // spike isolato dell'eco) non deve far scattare una registrazione
          // intera — deve restare sopra soglia con continuita' per il tratto
          // minimo richiesto in questa modalita'.
          onsetCandidateMs = speaking ? onsetCandidateMs + chunkMs : 0;
          if (onsetCandidateMs >= onsetSustainNeeded) {
            recording = true;
            segmentChunks = botSpeaking ? [data] : prerollChunks; // pre-buffer solo a mic normale
            segmentMs = botSpeaking ? chunkMs : prerollMs;
            silenceMs = 0;
            onsetCandidateMs = 0;
            prerollChunks = [];
            prerollMs = 0;
            setOrbState("listening");
          }
          return;
        }

        segmentChunks.push(data);
        segmentMs += chunkMs;
        window.JarvisOrb?.setLevel(rms * 2.5); // reagisce al volume vero mentre registra
        if (speaking) {
          silenceMs = 0;
        } else {
          silenceMs += chunkMs;
        }
        if (silenceMs >= MIC_SILENCE_HANG_MS) {
          finalizeSegment();
        } else if (segmentMs >= MIC_MAX_RECORD_MS) {
          hitMaxDuration = true;
          finalizeSegment();
        }
      };
    } catch (error) {
      if (token !== attempt) return;
      const message = error.name === "NotAllowedError"
        ? "Consenti il microfono nelle impostazioni del sito, poi riprova"
        : "Microfono non disponibile · tocca per riprovare";
      disarm(false, message);
    }
  }

  function disarm(submit = true, message = OFF_TITLE) {
    ++attempt; // invalida anche una richiesta permessi ancora in corso
    if (submit && armed && recording) finalizeSegment();
    armed = false;
    window.JarvisDirect?.setMicEnabled(false);
    arming = false;
    recording = false;
    segmentChunks = [];
    prerollChunks = [];
    if (processor) { processor.onaudioprocess = null; processor.disconnect(); }
    silentSink?.disconnect();
    stream?.getTracks().forEach((t) => { t.onended = null; t.stop(); });
    if (audioCtx) { audioCtx.onstatechange = null; audioCtx.close().catch(() => {}); }
    stream = null;
    audioCtx = null;
    processor = null;
    silentSink = null;
    freeMicLock();
    micBtn.classList.remove("listening");
    micBtn.setAttribute("aria-pressed", "false");
    if (orbState === "listening") setOrbState("idle");
    showMicStatus(message);
  }

  micBtn.addEventListener("click", () => {
    if (armed || arming) disarm();
    else arm();
  });

  document.addEventListener("visibilitychange", () => {
    if (touchDevice && document.hidden) disarm(false, "Ascolto in pausa · tocca il microfono per riprendere");
  });
  window.addEventListener("pagehide", () => disarm(false));
  // Il microfono resta spento finché l'utente non lo attiva dal pulsante.
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
  if (window.JarvisDirect) {
    return window.JarvisDirect.submit({ type: "audio", data: audioB64 }, el);
  }
  try {
    const { task_id } = await api("task_push", { audio_b64: audioB64 });
    setOrbState("thinking");
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
      if (orbState === "thinking") setOrbState("idle");
      return;
    }
    if (task.status === "superseded") {
      // Come "ignored": una domanda vocale piu' recente l'ha gia'
      // sostituita, rimossa in silenzio invece di mostrare un "Timeout".
      el.remove();
      if (orbState === "thinking") setOrbState("idle");
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

// ── Meteo settimanale animato ("come il vero JARVIS di Iron Man") ──────
// Dati scritti da bot.py::weather_forecast_loop() su Turso (il browser non
// puo' chiamare Open-Meteo con la posizione configurata in .env — quella
// vive solo lato Python). Icone animate per categoria WMO: i raggi del sole
// ruotano, gocce/fiocchi scendono, il fulmine lampeggia — vedi CSS
// .weather-icon. SVG inline invece delle emoji (2026-10-14): su Windows/Edge
// la nebbia 🌫️ diventava un quadrato bianco e le nuvole erano minuscole e
// poco contrastate. Tracciati delle nuvole in stile Feather Icons (MIT).
function _wxRays(cx, cy, r1, r2, angles) {
  const f = (n) => n.toFixed(2);
  return angles.map((deg) => {
    const a = (deg * Math.PI) / 180;
    return `<line x1="${f(cx + r1 * Math.cos(a))}" y1="${f(cy + r1 * Math.sin(a))}" x2="${f(cx + r2 * Math.cos(a))}" y2="${f(cy + r2 * Math.sin(a))}"/>`;
  }).join("");
}
const WX_CLOUD = '<path class="wx-cloud-shape" d="M18 10h-1.26A8 8 0 1 0 9 20h9a5 5 0 0 0 0-10z"/>';
const WX_SVG = {
  sun: `<circle class="wx-sun-core" cx="12" cy="12" r="4"/><g class="wx-rays">${_wxRays(12, 12, 6.8, 9.3, [0, 45, 90, 135, 180, 225, 270, 315])}</g>`,
  partly: `<circle class="wx-sun-core" cx="8" cy="8" r="3.2"/><g class="wx-rays">${_wxRays(8, 8, 5, 6.8, [0, 135, 180, 225, 270, 315])}</g>`
    + `<g transform="translate(5 6) scale(.75)" stroke-width="2.13">${WX_CLOUD}</g>`,
  cloud: WX_CLOUD,
  fog: `<g transform="translate(3 0) scale(.75)" stroke-width="2.13">${WX_CLOUD}</g><path class="wx-fog-lines" d="M4 18.5h16M7 22h10"/>`,
  drizzle: '<path d="M20 16.58A5 5 0 0 0 18 7h-1.26A8 8 0 1 0 4 15.25"/>'
    + '<g class="wx-drops"><path d="M8 13v2M8 19v2M12 15v2M12 21v2M16 13v2M16 19v2"/></g>',
  rain: '<path d="M20 16.58A5 5 0 0 0 18 7h-1.26A8 8 0 1 0 4 15.25"/>'
    + '<g class="wx-drops"><path d="M8 13v8M12 15v8M16 13v8"/></g>',
  snow: '<path d="M20 17.58A5 5 0 0 0 18 8h-1.26A8 8 0 1 0 4 16.25"/>'
    + '<g class="wx-flakes"><path d="M8 16h.01M8 20h.01M12 18h.01M12 22h.01M16 16h.01M16 20h.01"/></g>',
  storm: '<path d="M19 16.9A5 5 0 0 0 18 7h-1.26a8 8 0 1 0-11.62 9"/><polyline class="wx-bolt" points="13 11 9 17 15 17 11 23"/>',
};
const WX_KIND = {
  0: "sun", 1: "sun", 2: "partly", 3: "cloud", 45: "fog", 48: "fog",
  51: "drizzle", 53: "drizzle", 55: "drizzle", 56: "drizzle", 57: "drizzle",
  61: "rain", 63: "rain", 65: "rain", 66: "rain", 67: "rain", 80: "rain", 81: "rain", 82: "rain",
  71: "snow", 73: "snow", 75: "snow", 77: "snow", 85: "snow", 86: "snow",
  95: "storm", 96: "storm", 99: "storm",
};
const WX_LABEL = {
  sun: "Sereno", partly: "Parzialmente nuvoloso", cloud: "Nuvoloso", fog: "Nebbia",
  drizzle: "Pioviggine", rain: "Pioggia", snow: "Neve", storm: "Temporale",
};

function weatherIcon(code) {
  const kind = WX_KIND[code] || "cloud";
  return `<svg class="weather-icon wx-${kind}" viewBox="0 0 24 24" role="img" aria-label="${WX_LABEL[kind]}"><title>${WX_LABEL[kind]}</title>${WX_SVG[kind]}</svg>`;
}
const GIORNI_BREVI = ["Lun", "Mar", "Mer", "Gio", "Ven", "Sab", "Dom"];

function _dayShortName(dateStr) {
  const dow = new Date(dateStr + "T00:00:00Z").getUTCDay(); // 0=Dom..6=Sab
  return GIORNI_BREVI[(dow + 6) % 7];
}

async function refreshWeatherForecast() {
  try {
    const { forecast } = await api("weather_forecast");
    const container = $("#weather-days");
    if (!forecast || !forecast.days || !forecast.days.length) {
      container.innerHTML = `<p class="panel-footnote">In attesa che il bridge locale pubblichi le previsioni…</p>`;
      return;
    }
    $("#weather-place").textContent = forecast.place;
    container.innerHTML = forecast.days
      .map((d) => {
        return `
          <div class="weather-day">
            <div class="wx-day-name">${_dayShortName(d.date)}</div>
            ${weatherIcon(d.code)}
            <div class="wx-temps"><span class="wx-high">${d.high ?? "—"}°</span><span class="wx-low">${d.low ?? "—"}°</span></div>
          </div>`;
      })
      .join("");
    fitWeatherWindow();
  } catch {
    // rete assente/blip transitorio: lascia il pannello com'era
  }
}

// ── Stato progetti (segnali git reali, niente percentuali) ─────────────
// Dati scritti da bot.py::project_status_loop() su Turso — git status/log
// gira solo in locale (SystemExecutor), il browser non puo' farlo da solo.
// Niente punteggio/percentuale "salute" (rimosso 2026-09-16, richiesta
// esplicita di Alessandro: GitHub/Vercel coprono gia' lo stato reale dei
// progetti, un numero derivato in piu' qui era ridondante).
function _lastCommitShort(text) {
  if (!text) return "—";
  const m = text.match(/\(([^)]+)\)\s*$/); // "%h %s (%cr)" -> solo il "%cr" finale
  return m ? m[1] : text;
}

async function refreshProjectStatus() {
  try {
    const { projects, insights = {} } = await api("project_status_data");
    const container = $("#project-cards");
    if (!projects || !projects.length) {
      container.innerHTML = `<p class="panel-footnote">In attesa che il bridge locale pubblichi lo stato progetti…</p>`;
      return;
    }
    // Prossimi step e consigli ricavati dalle conversazioni (core/project_insights.py).
    const advice = (p) => {
      const item = insights[p.key];
      if (!item) return "";
      const list = (rows) => rows.length ? `<ul>${rows.map((r) => `<li>${_escHtml(r)}</li>`).join("")}</ul>` : "<p class=\"panel-footnote\">Nessuno.</p>";
      return `<details class="project-insights" open><summary>Prossimi step e consigli · ${_escHtml(item.updated_at)}</summary>
        ${item.summary ? `<p class="panel-footnote">${_escHtml(item.summary)}</p>` : ""}
        <p class="project-card-label">Prossimi step</p>${list(item.next_steps || [])}
        <p class="project-card-label">Consigli</p>${list(item.advice || [])}</details>`;
    };
    // Prima i progetti con prossimi step, poi gli altri nell'ordine di sempre.
    const ordered = [...projects].sort((a, b) => Boolean(insights[b.key]) - Boolean(insights[a.key]));
    container.innerHTML = ordered
      .map((p) => card(p).replace(/<\/div>\s*$/, advice(p) + "</div>"))
      .join("");
  } catch {
    // rete assente/blip transitorio: lascia il pannello com'era
  }
}

// Card di un progetto: stato Git o motivo per cui manca.
function card(p) {
  if (!p.configured) {
    return `<div class="project-card disabled">
      <div class="project-card-title">${_escHtml(p.label)}</div>
      <p class="panel-footnote">Disponibile in memoria o nel registro; percorso locale non configurato.</p>
    </div>`;
  }
  if (p.error) {
    return `<div class="project-card">
      <div class="project-card-title">${_escHtml(p.label)}</div>
      <p class="panel-footnote">Errore git: ${_escHtml(p.error.slice(0, 80))}</p>
    </div>`;
  }
  if (!p.branch) return `<div class="project-card"><div class="project-card-title">${_escHtml(p.label)}</div><p class="panel-footnote">Cartella locale senza Git.</p></div>`;
  return `
    <div class="project-card">
      <div class="project-card-title">${_escHtml(p.label)} <span class="project-branch">${_escHtml(p.branch || "")}</span></div>
      <div class="project-card-row"><span>Modifiche in sospeso</span><strong>${p.dirty_files}</strong></div>
      <div class="project-card-row"><span>Ultimo commit</span><strong>${_escHtml(_lastCommitShort(p.last_commit))}</strong></div>
    </div>`;
}

// ── GitHub / Vercel reali (core/remote_status.py) ───────────────────
// A differenza delle card sopra (solo i 3 workspace con path locale
// configurato), qui arrivano TUTTI i repository posseduti su GitHub —
// richiesta esplicita di Alessandro (2026-09-15): "andrebbe integrato il
// mio GitHub e il mio vercel per vedere tutti i progetti e gli status".
// Testo che arriva da fuori (descrizione repo, messaggio di commit): a
// differenza delle altre card qui sopra (dati locali/propri), puo' essere
// stato scritto da chiunque abbia scritto su quel repo — escaping esplicito
// invece di fidarsi come per il resto del pannello.
function _escHtml(s) {
  if (s == null) return "";
  return String(s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

const VERCEL_STATE_COLOR = {
  READY: "var(--good)",
  BUILDING: "var(--warning)",
  QUEUED: "var(--warning)",
  ERROR: "var(--critical)",
  CANCELED: "var(--text-muted)",
};

function _timeAgo(iso) {
  if (!iso) return "—";
  const ms = typeof iso === "number" ? iso : Date.parse(iso);
  if (!Number.isFinite(ms)) return "—";
  const days = Math.floor((Date.now() - ms) / 86400000);
  if (days <= 0) return "oggi";
  if (days === 1) return "ieri";
  if (days < 30) return `${days}g fa`;
  const months = Math.floor(days / 30);
  return months === 1 ? "1 mese fa" : `${months} mesi fa`;
}

async function refreshRemoteStatus() {
  try {
    const { remote } = await api("remote_status_data");
    const container = $("#remote-cards");
    if (!container) return;
    const entries = remote?.entries;
    if (!entries || !entries.length) {
      container.innerHTML = `<p class="panel-footnote">In attesa che il bridge locale pubblichi GitHub/Vercel…</p>`;
      return;
    }
    container.innerHTML = entries
      .map(({ github, vercel }) => {
        const name = _escHtml(github?.name || vercel?.name || "?");
        const url = github?.url || vercel?.url || "#";
        const privateTag = github?.private ? `<span class="project-branch">privato</span>` : "";
        const commitLine = github?.last_commit
          ? `${_escHtml(github.last_commit.message)} · ${_timeAgo(github.last_commit.date)}`
          : "—";
        const vercelRow = vercel
          ? `<div class="project-card-row"><span>Vercel</span><strong style="color:${VERCEL_STATE_COLOR[vercel.state] || "var(--text-muted)"}">${_escHtml(vercel.state || "?")}</strong></div>`
          : "";
        return `
          <div class="project-card">
            <div class="project-card-title"><a href="${url}" target="_blank" rel="noopener">${name}</a> ${privateTag}</div>
            <div class="project-card-row"><span>Ultimo commit</span><strong>${commitLine}</strong></div>
            ${vercelRow}
          </div>`;
      })
      .join("");
  } catch {
    // rete assente/blip transitorio: lascia il pannello com'era
  }
}

// ── Trading (Myfxbook), core/myfxbook.py — dashboard finanziaria, "solo
// trading per ora" (richiesta esplicita di Alessandro, 2026-09-16): unica
// fonte dati realmente strutturata oggi, AURA/WhiteSoul/AP Systems restano
// fuori finche' non hanno un posto strutturato da cui prendere i numeri.
// Pannello nascosto del tutto se Myfxbook non e' configurato lato bridge
// (nessuna riga mai scritta su Turso, non solo vuota).
async function refreshTradingStatus() {
  try {
    const { trading } = await api("trading_status_data");
    const heading = $("#trading-subheading");
    const container = $("#trading-cards");
    if (!container || !heading) return;
    if (!trading || !trading.length) {
      heading.hidden = true;
      container.hidden = true;
      return;
    }
    heading.hidden = false;
    container.hidden = false;
    container.innerHTML = trading
      .map((a) => {
        const total = (a.won_trades || 0) + (a.lost_trades || 0);
        const winrate = total ? `${Math.round((a.won_trades / total) * 100)}%` : "n/d";
        const gainColor = a.gain >= 0 ? "var(--good)" : "var(--critical)";
        return `
          <div class="project-card">
            <div class="project-card-title">${_escHtml(a.name)}</div>
            <div class="project-card-row"><span>Equity</span><strong>${Number(a.equity).toFixed(2)}</strong></div>
            <div class="project-card-row"><span>Gain</span><strong style="color:${gainColor}">${Number(a.gain).toFixed(2)}%</strong></div>
            <div class="project-card-row"><span>Drawdown</span><strong>${Number(a.drawdown).toFixed(2)}%</strong></div>
            <div class="project-card-row"><span>Winrate</span><strong>${winrate} (${total} trade)</strong></div>
          </div>`;
      })
      .join("");
  } catch {
    // rete assente/blip transitorio: lascia il pannello com'era
  }
}

// ── Second brain — grafo animato (canvas, nessuna libreria) ──────────
// Un solo brain, senza piu' distinzione per progetto (richiesta esplicita
// di Alessandro, 2026-09-16: "non mi piace avere tutti quei contesti
// sopra... mettere tutto insieme nel brain"). Un colore unico per tutti i
// nodi, stesso accent fisso della dashboard.
const BRAIN_NODE_COLOR = "#3987e5";

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
  if (focusedNode) {
    const on = node === focusedNode || brainIsConnected(node, focusedNode);
    return on ? { fill: BRAIN_NODE_COLOR, glow: 8 } : { fill: "rgba(255,255,255,0.07)", glow: 0 };
  }
  return { fill: BRAIN_NODE_COLOR, glow: 4 };
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
let cameraAttempt = 0;

async function startCamera() {
  const token = ++cameraAttempt;
  const video = $("#camera-video");
  const hint = $("#camera-hint");
  try {
    const stream = await navigator.mediaDevices.getUserMedia({ video: true });
    if (token !== cameraAttempt) {
      stream.getTracks().forEach((track) => track.stop());
      return;
    }
    cameraStream = stream;
    video.srcObject = cameraStream;
    hint.textContent = "Camera attiva.";
  } catch {
    if (token === cameraAttempt) hint.textContent = "Permesso camera negato o non disponibile.";
  }
}

function stopCamera() {
  ++cameraAttempt;
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

// ── Stato "sta parlando" (bolla centrale + muting del mic) ──────────────
// L'audio esce dagli altoparlanti del PC via un processo Python separato
// (core/voice/tts.py), non nel browser — l'unico modo per far reagire la
// bolla (e per il mic di sapere di doversi zittire, vedi sotto) e'
// chiedere periodicamente a Turso se JARVIS sta parlando in questo
// momento, qualunque canale (Telegram/voce/dashboard) l'abbia innescato.
const ORB_SPEAKING_POLL_MS = 700;

// Trovato dal vivo (2026-09-15): con l'ascolto sempre attivo di stamattina
// E le risposte lette ad alta voce dagli altoparlanti del PC, il
// microfono si risentiva DA SOLO — ritrascriveva le proprie risposte
// come se fossero un nuovo comando (visto nei log: le cifre di un codice
// errore lette ad alta voce, ricatturate e ritrascritte). L'echo
// cancellation del browser non lo previene: cancella solo l'audio che IL
// BROWSER STESSO sta riproducendo (WebRTC/<audio>), non un processo di
// sistema separato che scrive sugli altoparlanti. `botSpeaking` (letto da
// setupVoice()) fa tacere completamente il mic mentre JARVIS parla.
let botSpeaking = false;

// ── Bolla animata (orb.js) — stato/energia riflettono cosa sta facendo
// davvero JARVIS in questo momento (idle/listening/thinking/speaking/alert).
// orbState e' la fonte di verita' lato client: pollSpeakingStatus() legge
// solo "sta parlando adesso?" da Turso ogni 700ms, quindi non deve MAI
// sovrascrivere alla cieca uno stato piu' specifico (es. "listening" appena
// scattato) impostato nel frattempo da un altro punto del codice.
let orbState = "idle";
let orbStateGen = 0;

// Avanzamento dei comandi lunghi (eventi "progress" da LiveBridge): anello attorno
// alla sfera che si riempie, percentuale, passo attuale e ultimi passi completati.
function showProgress(label, percent) {
  const box = $("#task-progress");
  if (!box) return;
  box.hidden = false;
  const value = Number.isFinite(percent) ? percent : null;
  $("#task-percent").textContent = value == null ? "…" : `${value}%`;
  $("#task-ring-fill").style.strokeDasharray = `${value ?? 3} 100`;
  const current = $("#task-label");
  const steps = $("#task-steps");
  if (label && current.textContent !== label) {
    if (current.textContent && current.textContent !== "al lavoro") {
      const done = document.createElement("li");
      done.textContent = current.textContent;
      steps.append(done);
      while (steps.children.length > 3) steps.firstChild.remove();
    }
    current.textContent = label;
  }
}

function hideProgress() {
  const box = $("#task-progress");
  if (!box || box.hidden) return;
  box.hidden = true;
  $("#task-steps").replaceChildren();
  $("#task-label").textContent = "al lavoro";
  $("#task-ring-fill").style.strokeDasharray = "0 100";
}
window.showProgress = showProgress;
window.hideProgress = hideProgress;

function setOrbState(name) {
  orbState = name;
  window.JarvisOrb?.setState(name);
}

function setOrbAlert(durationMs = 2500) {
  const gen = ++orbStateGen;
  setOrbState("alert");
  setTimeout(() => {
    if (orbStateGen === gen) setOrbState("idle");
  }, durationMs);
}

async function pollSpeakingStatus() {
  if (window.JarvisDirect) {
    botSpeaking = window.JarvisDirect.speaking;
    return;
  }
  // Tab nascosta: la bolla non si vede e senza mic attivo il flag non serve.
  // Ogni chiamata a 700 ms consuma Fast Origin Transfer Vercel (10 GB/mese
  // condivisi fra tutti i progetti), quindi si interroga solo se serve.
  if (document.hidden && !$("#mic-btn")?.classList.contains("listening")) return;
  try {
    const { speaking } = await api("runtime_status");
    botSpeaking = !!speaking;
    if (botSpeaking && orbState !== "speaking") setOrbState("speaking");
    else if (!botSpeaking && orbState === "speaking") setOrbState("idle");
  } catch {
    // rete assente/blip transitorio: non toccare lo stato attuale della bolla/mic
  }
}

// ── Boot ─────────────────────────────────────────────────────────────

// Ogni passo e' isolato nel proprio try/catch: boot() non e' mai atteso da
// chi lo chiama (vedi sotto, "boot()" senza await dentro un try/catch che
// quindi non lo protegge affatto), quindi un'eccezione in UN SOLO pezzo
// (es. la bolla animata su un browser/GPU che si comporta in modo
// imprevisto) fermava silenziosamente TUTTO cio' che veniva dopo nella
// funzione — mic, dock, meteo, progetti inclusi. Bug reale osservato dal
// vivo (2026-09-15) subito dopo l'introduzione della bolla animata.
function _bootStep(label, fn) {
  try {
    fn();
  } catch (e) {
    console.error(`boot: "${label}" fallito (ignorato, il resto della dashboard deve continuare)`, e);
  }
}

async function boot() {
  $("#login-screen").style.display = "none";
  $("#app").classList.add("visible");
  _bootStep("viewport", setupViewport);
  _bootStep("direct-voice", () => window.JarvisDirect?.start());
  _bootStep("orb", () => {
    // ?orb=globo|originale per confrontare gli stili; default "liscia".
    const style = new URLSearchParams(location.search).get("orb") || undefined;
    window.JarvisOrb = window.createJarvisOrb($("#orb-canvas"), { style });
    if (!document.hidden) window.JarvisOrb.start();
  });
  _bootStep("voice", setupVoice);
  _bootStep("windows", setupWindows);
  _bootStep("connected-data", () => {
    if (!window.JarvisDirect) return;
    $("#connected-data").hidden = false;
    $("#learned-memory").hidden = false;
    // TradePilot e IVECO leggono dati privati del PC: solo dalla dashboard locale.
    document.querySelectorAll('[data-toggle="win-tradepilot"], [data-toggle="win-iveco"], [data-toggle="win-connections"]').forEach((b) => { b.hidden = false; });
    $("#refresh-data-btn").onclick = refreshConnectedData;
    setupPanelTabs();
    setupIveco();
    const isOpen = (id) => !document.hidden && $("#" + id).classList.contains("open");
    setInterval(() => {
      if (isOpen("win-projects")) refreshConnectedData();
      if (isOpen("win-tradepilot")) refreshTradePilot();
      if (isOpen("win-iveco")) refreshIvecoJobs();
    }, 60000);
  });
  _bootStep("camera", setupCamera);
  _bootStep("clock", () => {
    tickClock();
    setInterval(tickClock, 1000);
  });
  try {
    await loadHistory();
  } catch (e) {
    console.error('boot: "history" fallito (ignorato)', e);
  }
  _bootStep("weather", () => {
    refreshWeatherForecast();
    setInterval(refreshWeatherForecast, 5 * 60 * 1000); // il bridge locale pubblica ogni 30min, basta controllare ogni 5
  });
  _bootStep("project-status", () => {
    refreshProjectStatus();
    setInterval(refreshProjectStatus, 2 * 60 * 1000); // il bridge locale pubblica ogni 10min
  });
  _bootStep("remote-status", () => {
    refreshRemoteStatus();
    setInterval(refreshRemoteStatus, 3 * 60 * 1000); // il bridge locale pubblica ogni 15min
  });
  _bootStep("trading-status", () => {
    refreshTradingStatus();
    setInterval(refreshTradingStatus, 3 * 60 * 1000); // il bridge locale pubblica ogni 15min
  });
  _bootStep("speaking-poll", () => {
    pollSpeakingStatus();
    setInterval(pollSpeakingStatus, ORB_SPEAKING_POLL_MS);
  });
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

// Stessi messaggi nella conversazione unica, anche su iPhone.
document.querySelectorAll("[data-prompt]").forEach(button => {
  button.addEventListener("click", () => submitTask(button.dataset.prompt));
});
