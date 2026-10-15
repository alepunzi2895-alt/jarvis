"""Renderizza la sfera di web/public/orb.js in un video MP4 a loop perfetto
(60 s, 30 fps) per un quadrante Clockology.

Uso: python watch/tools/render_orb_video.py <repo> <out_dir> [larghezza altezza] [--stile liscia|globo|originale]
Default 410x502 (Apple Watch Ultra/Ultra 2); Ultra 3: 422 514.
Stili: "liscia" (default) sfera di nodi senza irregolarita' del raggio, con
bordo e alone circolari; "globo" nodi su paralleli con bordo e alone;
"originale" la sfera della dashboard cosi' com'e'.
Richiede il venv di JARVIS (playwright, av, numpy)."""
import io
import math
import sys
from pathlib import Path

import av
import numpy as np
from playwright.sync_api import sync_playwright

args = sys.argv[1:]
style = "liscia"
if "--stile" in args:
    k = args.index("--stile")
    style = args[k + 1]
    del args[k:k + 2]
W, H = (int(args[2]), int(args[3])) if len(args) > 3 else (410, 502)
FPS, PERIOD_STEPS, FADE = 30, 3600, 30
FRAMES = PERIOD_STEPS // 2  # 2 passi da 1/60 s per fotogramma

# Sfera rotonda: raggio dei nodi costante, oscillazione minima, raggio ridotto
# perche' alone e bordo restino dentro lo schermo.
SMOOTH = {
    "const j = 0.88 + Math.random() * 0.2;": "const j = 1;",
    "Math.sin(t * 0.02 + n.ph) * 0.025 + n.e * 0.05": "Math.sin(t * 0.02 + n.ph) * 0.006 + n.e * 0.02",
    "Math.min(W, H) * 0.42": "Math.min(W, H) * 0.37",
}
RIM = {
    '    cx.globalCompositeOperation = "source-over";\n    cx.lineWidth = 1;': """\
    const halo = cx.createRadialGradient(W / 2, H / 2, R * 0.94, W / 2, H / 2, R * 1.22);
    halo.addColorStop(0, `hsla(${hue},100%,60%,0)`);
    halo.addColorStop(0.35, `hsla(${hue},100%,62%,0.20)`);
    halo.addColorStop(1, `hsla(${hue},100%,50%,0)`);
    cx.fillStyle = halo;
    cx.beginPath(); cx.arc(W / 2, H / 2, R * 1.22, 0, 6.28); cx.fill();
    cx.globalCompositeOperation = "source-over";
    cx.lineWidth = 1;
    cx.strokeStyle = `hsla(${hue},90%,70%,0.55)`;
    cx.beginPath(); cx.arc(W / 2, H / 2, R * 1.04, 0, 6.28); cx.stroke();""",
}
# Nodi su 12 paralleli, archi lungo i paralleli e verso il nodo piu' vicino del
# parallelo successivo.
GLOBE = {
    "const N = 110, K = 3;": "let N = 110, K = 3;",
    "  function buildSphere() {": """\
  function buildSphere() { return buildGlobe(); }
  function buildGlobe() {
    const rows = [], LAT = 12;
    for (let a = 0; a < LAT; a++) {
      const phi = -Math.PI / 2 + Math.PI * (a + 0.5) / LAT, r = Math.cos(phi), y = Math.sin(phi);
      const M = Math.max(6, Math.round(22 * r)), row = [];
      for (let b = 0; b < M; b++) {
        const th = (2 * Math.PI * b) / M + a * 0.26;
        row.push(nodes.length);
        nodes.push({ x: Math.cos(th) * r, y, z: Math.sin(th) * r, e: 0, ref: 0, h: hue, sx: 0, sy: 0, sz: 0, ph: Math.random() * 6.28 });
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
    N = nodes.length;
    nodes.forEach((n, i) => { n.nb = edges.filter((e) => e[0] === i || e[1] === i).map((e) => (e[0] === i ? e[1] : e[0])); });
  }
  function buildKnnSphere() {""",
}
# Con la propagazione della dashboard (0.7) le cascate di impulsi diventano
# lampi dell'intera sfera ogni ~1 s; sotto la soglia l'attivita' resta sparsa
# (simulazione su 7200 passi, 3 prove: liscia a 0.32 e globo a 0.26 mai oltre
# il 30% dei nodi accesi insieme; liscia 0.34 e globo 0.3 lampeggiano ancora).
def propagation(p):
    return {"if (Math.random() < 0.7) pulses.push": f"if (Math.random() < {p}) pulses.push"}


STYLES = {
    "originale": {},
    "liscia": {**SMOOTH, **RIM, "const N = 110, K = 3;": "const N = 170, K = 3;", **propagation(0.32)},
    "globo": {**SMOOTH, **RIM, **GLOBE, **propagation(0.26)},
}

repo, out_dir = Path(args[0]), Path(args[1])
out_dir.mkdir(parents=True, exist_ok=True)
source = (repo / "web/public/orb.js").read_text(encoding="utf-8")
for old, new in STYLES[style].items():
    assert source.count(old) == 1, old
    source = source.replace(old, new)
# Rotazioni con periodo esatto di 3600 passi: il fotogramma 1800 coincide col primo.
replacements = {
    "rotY += P.rot * (1 + level * 2);": "rotY = t * (2 * Math.PI / 3600);",
    "rotX = 0.35 + Math.sin(t * 0.003) * 0.12;": "rotX = 0.35 + Math.sin(t * (2 * Math.PI / 1800)) * 0.12;",
    "Math.sin(t * 0.02 + n.ph)": "Math.sin(t * (2 * Math.PI * 11 / 3600) + n.ph)",
    "[[1.1, 0.0025, 0.9, 0.3], [1.16, -0.004, 0.35, 0.18]]":
        "[[1.1, 2 * Math.PI * 4 / 3 / 3600, 0.9, 0.3], [1.16, -2 * Math.PI * 7 / 3 / 3600, 0.35, 0.18]]",
    "return { start, stop, setState, setLevel };":
        "return { start, stop, setState, setLevel, step, draw, init() { resize(); if (!nodes.length) buildSphere(); } };",
}
for old, new in replacements.items():
    assert source.count(old) == 1, old
    source = source.replace(old, new)

page_html = f"""<!doctype html><html><body style="margin:0;background:#000">
<div id="box" style="width:{W}px;height:{H}px;position:relative"><canvas id="orb"></canvas></div>
<canvas id="plain" width="{W}" height="{H}"></canvas><canvas id="label" width="{W}" height="{H}"></canvas>
</body></html>"""

harness = """
window.orb = createJarvisOrb(document.getElementById('orb'));
orb.init();
for (let i = 0; i < 3600; i++) orb.step();
window.grab = (count) => {
  const src = document.getElementById('orb');
  const out = [];
  for (let k = 0; k < count; k++) {
    orb.step(); orb.step(); orb.draw();
    const pair = [];
    for (const id of ['plain', 'label']) {
      const c = document.getElementById(id), g = c.getContext('2d');
      g.fillStyle = '#000'; g.fillRect(0, 0, c.width, c.height);
      g.drawImage(src, 0, 0, c.width, c.height);
      if (id === 'label') {
        g.font = '600 24px "Segoe UI", sans-serif';
        g.letterSpacing = '9px';
        g.textAlign = 'center';
        g.shadowColor = 'rgba(57,135,229,.9)'; g.shadowBlur = 12;
        g.fillStyle = '#3987e5';
        g.fillText('JARVIS', c.width / 2 + 4, c.height / 2 - 52);
        g.shadowBlur = 0;
      }
      pair.push(c.toDataURL('image/png'));
    }
    out.push(pair);
  }
  return out;
};
"""


def decode(data_url):
    import base64
    raw = base64.b64decode(data_url.split(",", 1)[1])
    with av.open(io.BytesIO(raw), format="png_pipe") as container:
        frame = next(container.decode(video=0))
        return frame.to_ndarray(format="rgb24")


def writer(path):
    container = av.open(str(path), "w")
    stream = container.add_stream("libx264", rate=FPS)
    stream.width, stream.height, stream.pix_fmt = W, H, "yuv420p"
    stream.options = {"crf": "25", "preset": "slow", "movflags": "+faststart"}
    return container, stream


def put(container, stream, array):
    for packet in stream.encode(av.VideoFrame.from_ndarray(array, format="rgb24")):
        container.mux(packet)


outputs = {name: writer(out_dir / f"jarvis_orb_{style}{suffix}.mp4") for name, suffix in (("plain", ""), ("label", "_label"))}
head = {"plain": [], "label": []}
with sync_playwright() as p:
    browser = p.chromium.launch()
    page = browser.new_page(viewport={"width": W, "height": H * 3}, device_scale_factor=1)
    page.set_content(page_html)
    page.add_script_tag(content=source)
    page.evaluate(harness)
    index = 0
    while index < FRAMES + FADE:
        batch = page.evaluate(f"grab({min(10, FRAMES + FADE - index)})")
        for pair in batch:
            for name, data in zip(("plain", "label"), pair):
                array = decode(data)
                container, stream = outputs[name]
                if index < FADE:
                    head[name].append(array)
                    if name == "plain" and index == 0:
                        (out_dir / f"{style}_first_frame.png").write_bytes(__import__("base64").b64decode(data.split(",", 1)[1]))
                elif index < FRAMES:
                    put(container, stream, array)
                else:
                    i = index - FRAMES
                    a = (i + 1) / FADE
                    blended = (array.astype(np.float32) * (1 - a) + head[name][i].astype(np.float32) * a)
                    put(container, stream, blended.round().astype(np.uint8))
            if index == 0:
                (out_dir / f"{style}_label_frame.png").write_bytes(__import__("base64").b64decode(pair[1].split(",", 1)[1]))
            index += 1
        if index % 300 < 10:
            print("fotogrammi", index, flush=True)
    browser.close()
for container, stream in outputs.values():
    for packet in stream.encode():
        container.mux(packet)
    container.close()
print("ok")
