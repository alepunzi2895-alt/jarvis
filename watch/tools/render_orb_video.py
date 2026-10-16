"""Renderizza la sfera di web/public/orb.js in un video MP4 a loop perfetto
(60 s, 30 fps) per un quadrante Clockology.

Uso: python watch/tools/render_orb_video.py <repo> <out_dir> [larghezza altezza] [--stile liscia|globo|originale]
Default 410x502 (Apple Watch Ultra/Ultra 2); Ultra 3: 422 514.
Stili: quelli di orb.js (ORB_STYLES). "liscia" (default, anche in dashboard)
sfera di nodi senza irregolarita' del raggio, con bordo e alone circolari;
"globo" nodi su paralleli con bordo e alone; "originale" la sfera irregolare
di prima.
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

assert style in ("liscia", "globo", "originale"), style

repo, out_dir = Path(args[0]), Path(args[1])
out_dir.mkdir(parents=True, exist_ok=True)
source = (repo / "web/public/orb.js").read_text(encoding="utf-8")
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
window.orb = createJarvisOrb(document.getElementById('orb'), { style: '__STYLE__' });
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
""".replace("__STYLE__", style)


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
