// JARVIS dashboard — api/tradeflow.js
// Proxy read-only verso il gateway pubblico di tradeflow-ai (dati mt5 in sola lettura, non sensibili).

const TRADEFLOW_URL = "https://tradeflow-ai-delta.vercel.app/api/db";

export default async function handler(req, res) {
  if (req.method === "OPTIONS") return res.status(200).end();

  try {
    const ctrl = new AbortController();
    const timeout = setTimeout(() => ctrl.abort(), 8000);
    const r = await fetch(TRADEFLOW_URL, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ action: "mt5_get" }),
      signal: ctrl.signal,
    });
    clearTimeout(timeout);
    const data = await r.json();
    return res.status(200).json(data);
  } catch (e) {
    return res.status(502).json({ ok: false, error: "tradeflow unreachable: " + e.message });
  }
}
