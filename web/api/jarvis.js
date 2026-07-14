// JARVIS dashboard — api/jarvis.js
// Gateway Turso unico (login, coda task browser<->bridge locale), stile tradeflow-ai/api/db.js.

import { createClient } from "@libsql/client";
import jwt from "jsonwebtoken";

const JWT_SECRET = process.env.DASHBOARD_JWT_SECRET;
const DASHBOARD_PASSWORD = process.env.DASHBOARD_PASSWORD;
const BOT_SECRET = process.env.JARVIS_BOT_SECRET;
const COOKIE_NAME = "jarvis_session";

function getDb() {
  let url = process.env.TURSO_JARVIS_DB_URL;
  const token = process.env.TURSO_JARVIS_AUTH_TOKEN;
  if (!url || !token) throw new Error("TURSO_JARVIS_DB_URL o TURSO_JARVIS_AUTH_TOKEN mancanti");
  if (url.startsWith("libsql://")) url = url.replace("libsql://", "https://");
  return createClient({ url, authToken: token });
}

function uuid() {
  return "xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx".replace(/[xy]/g, (c) => {
    const r = (Math.random() * 16) | 0;
    return (c === "x" ? r : (r & 0x3) | 0x8).toString(16);
  });
}

function parseCookies(req) {
  const header = req.headers.cookie || "";
  return Object.fromEntries(
    header.split(";").filter(Boolean).map((p) => {
      const i = p.indexOf("=");
      return [p.slice(0, i).trim(), decodeURIComponent(p.slice(i + 1).trim())];
    })
  );
}

function requireBrowserAuth(req) {
  const cookies = parseCookies(req);
  const token = cookies[COOKIE_NAME];
  if (!token) throw new Error("Unauthorized");
  try {
    jwt.verify(token, JWT_SECRET);
  } catch {
    throw new Error("Unauthorized");
  }
}

function requireBotAuth(body) {
  if (!BOT_SECRET || body.secret !== BOT_SECRET) throw new Error("Unauthorized");
}

// ── ACTION HANDLERS ──────────────────────────────────────────────────────────

async function initSchema(db) {
  await db.execute(`CREATE TABLE IF NOT EXISTS tasks (
    id TEXT PRIMARY KEY, channel TEXT, workspace TEXT, prompt TEXT,
    status TEXT NOT NULL DEFAULT 'pending',
    result TEXT, session_id TEXT, cost_usd REAL, image_b64 TEXT,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
  )`);
  await db.execute(`ALTER TABLE tasks ADD COLUMN image_b64 TEXT`).catch(() => {});
  await db.execute(`CREATE TABLE IF NOT EXISTS approvals (
    id TEXT PRIMARY KEY, kind TEXT, payload TEXT, status TEXT NOT NULL DEFAULT 'pending',
    requested_by TEXT,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    decided_at DATETIME
  )`);
  // Second brain — schema identico a quello creato lato Python in core/brain.py
  // (entrambi CREATE TABLE IF NOT EXISTS: chi arriva prima vince, devono restare
  // in sync se lo schema cambia).
  await db.execute(`CREATE TABLE IF NOT EXISTS brain_nodes (
    id TEXT PRIMARY KEY,
    label TEXT NOT NULL,
    label_key TEXT NOT NULL UNIQUE,
    summary TEXT,
    workspace TEXT,
    tags TEXT,
    hits INTEGER NOT NULL DEFAULT 1,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
  )`);
  await db.execute(`CREATE TABLE IF NOT EXISTS brain_edges (
    id TEXT PRIMARY KEY,
    source_id TEXT NOT NULL,
    target_id TEXT NOT NULL,
    relation TEXT NOT NULL DEFAULT '',
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(source_id, target_id, relation)
  )`);
  return { ok: true };
}

function login(req, res, body) {
  if (!DASHBOARD_PASSWORD || body.password !== DASHBOARD_PASSWORD) {
    throw new Error("Password errata");
  }
  const token = jwt.sign({ sub: "alessandro" }, JWT_SECRET, { expiresIn: "30d" });
  res.setHeader(
    "Set-Cookie",
    `${COOKIE_NAME}=${token}; Path=/; HttpOnly; Secure; SameSite=Strict; Max-Age=${60 * 60 * 24 * 30}`
  );
  return { ok: true };
}

async function taskPush(db, req, body) {
  requireBrowserAuth(req);
  const { workspace, prompt, image_b64 } = body;
  if (!prompt) throw new Error("prompt required");
  const id = uuid();
  await db.execute({
    sql: `INSERT INTO tasks (id, channel, workspace, prompt, status, image_b64) VALUES (?, 'web', ?, ?, 'pending', ?)`,
    args: [id, workspace || "jarvis", prompt, image_b64 || null],
  });
  return { ok: true, task_id: id };
}

async function taskPoll(db, req, body) {
  requireBrowserAuth(req);
  const { task_id } = body;
  const r = await db.execute({ sql: "SELECT * FROM tasks WHERE id=?", args: [task_id] });
  if (!r.rows.length) throw new Error("task non trovato");
  return { ok: true, task: r.rows[0] };
}

async function tasksRecent(db, req, body) {
  requireBrowserAuth(req);
  const limit = body.limit || 30;
  const r = await db.execute({ sql: "SELECT * FROM tasks ORDER BY created_at DESC LIMIT ?", args: [limit] });
  return { ok: true, tasks: r.rows };
}

async function taskGet(db, body) {
  requireBotAuth(body);
  const pending = await db.execute({
    sql: "SELECT id, workspace, prompt, image_b64 FROM tasks WHERE status='pending' ORDER BY created_at ASC LIMIT 1",
    args: [],
  });
  if (!pending.rows.length) return { ok: true, task: null };
  const task = pending.rows[0];
  await db.execute({
    sql: "UPDATE tasks SET status='running', updated_at=CURRENT_TIMESTAMP WHERE id=?",
    args: [task.id],
  });
  return { ok: true, task };
}

async function taskResultPush(db, body) {
  requireBotAuth(body);
  const { task_id, status, result, session_id, cost_usd } = body;
  if (!task_id) throw new Error("task_id required");
  await db.execute({
    sql: `UPDATE tasks SET status=?, result=?, session_id=?, cost_usd=?, updated_at=CURRENT_TIMESTAMP WHERE id=?`,
    args: [status || "done", result || null, session_id || null, cost_usd || 0, task_id],
  });
  return { ok: true };
}

async function brainGraph(db, req) {
  requireBrowserAuth(req);
  const nodes = await db.execute(
    "SELECT id, label, summary, workspace, tags, hits FROM brain_nodes ORDER BY updated_at DESC"
  );
  const edges = await db.execute("SELECT id, source_id, target_id, relation FROM brain_edges");
  return { ok: true, nodes: nodes.rows, edges: edges.rows };
}

async function brainNodeDelete(db, req, body) {
  requireBrowserAuth(req);
  const { id } = body;
  if (!id) throw new Error("id required");
  await db.execute({ sql: "DELETE FROM brain_edges WHERE source_id=? OR target_id=?", args: [id, id] });
  await db.execute({ sql: "DELETE FROM brain_nodes WHERE id=?", args: [id] });
  return { ok: true };
}

const ACTIONS = {
  login: (db, req, res, body) => login(req, res, body),
  init_schema: (db) => initSchema(db),
  task_push: (db, req, res, body) => taskPush(db, req, body),
  task_poll: (db, req, res, body) => taskPoll(db, req, body),
  tasks_recent: (db, req, res, body) => tasksRecent(db, req, body),
  task_get: (db, req, res, body) => taskGet(db, body),
  task_result_push: (db, req, res, body) => taskResultPush(db, body),
  brain_graph: (db, req, res, body) => brainGraph(db, req),
  brain_node_delete: (db, req, res, body) => brainNodeDelete(db, req, body),
};

export default async function handler(req, res) {
  if (req.method === "OPTIONS") return res.status(200).end();
  if (req.method === "GET") return res.status(200).json({ ok: true, service: "JARVIS Gateway" });

  let body = req.body;
  if (typeof body === "string") body = JSON.parse(body || "{}");
  body = body || {};

  const { action } = body;
  const fn = ACTIONS[action];
  if (!fn) return res.status(400).json({ error: "invalid action" });

  try {
    const db = getDb();
    const result = await fn(db, req, res, body);
    return res.status(200).json(result);
  } catch (e) {
    const code = e.message === "Unauthorized" ? 401 : 500;
    return res.status(code).json({ error: e.message });
  }
}
