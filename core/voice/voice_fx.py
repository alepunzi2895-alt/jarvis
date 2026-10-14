"""
JARVIS — effetti voce "stile JARVIS film" applicati all'audio edge-tts.

Scelta di Alessandro (2026-10-14) tra i campioni in `.tmp/voci_jarvis/`:
`8_andrew_film` = en-US-AndrewMultilingualNeural che parla italiano, rate
-2%, pitch -4Hz, piu' questa catena tipo post-produzione: passa-alto,
EQ (meno fango, presenza, de-ess, aria), compressione, chorus modulato,
stanza piccola, limiter. Nessun clone di voci reali: solo ambiente e patina.

Lavora su mono float64 a qualsiasi sample rate. Costo misurato: pochi ms
per frase, trascurabile rispetto alla sintesi di rete.
"""

import numpy as np
from scipy import signal

# Coda per non troncare la stanza a fine frase.
_TAIL_SEC = 0.12


def _peak(f0: float, db: float, q: float, sr: int):
    a = 10 ** (db / 40)
    w = 2 * np.pi * f0 / sr
    al = np.sin(w) / (2 * q)
    b = np.array([1 + al * a, -2 * np.cos(w), 1 - al * a])
    d = np.array([1 + al / a, -2 * np.cos(w), 1 - al / a])
    return b / d[0], d / d[0]


def _shelf_hi(f0: float, db: float, sr: int):
    a = 10 ** (db / 40)
    w = 2 * np.pi * f0 / sr
    c = np.cos(w)
    s = 2 * np.sqrt(a) * np.sin(w) / 2 * np.sqrt(2)
    b = np.array([a * ((a + 1) + (a - 1) * c + s), -2 * a * ((a - 1) + (a + 1) * c), a * ((a + 1) + (a - 1) * c - s)])
    d = np.array([(a + 1) - (a - 1) * c + s, 2 * ((a - 1) - (a + 1) * c), (a + 1) - (a - 1) * c - s])
    return b / d[0], d / d[0]


def _eq(x: np.ndarray, sr: int) -> np.ndarray:
    b, a = signal.butter(2, 140, "highpass", fs=sr)
    y = signal.lfilter(b, a, x)
    for f0, db, q in [(300, -2.5, 1.0), (3000, 3.0, 0.8), (6500, -1.5, 2.0)]:
        b, a = _peak(f0, db, q, sr)
        y = signal.lfilter(b, a, y)
    if sr > 2 * 9500:
        b, a = _shelf_hi(9500, 2.5, sr)
        y = signal.lfilter(b, a, y)
    return y


def _compress(x: np.ndarray, sr: int, thr_db: float, ratio: float, att: float, rel: float) -> np.ndarray:
    env = np.abs(x)
    ga, gr = np.exp(-1 / (att * sr)), np.exp(-1 / (rel * sr))
    up = signal.lfilter([1 - ga], [1, -ga], env)
    down = signal.lfilter([1 - gr], [1, -gr], env)
    e = np.maximum(up, down) + 1e-9
    level = 20 * np.log10(e / np.max(e))
    gain_db = np.where(level > thr_db, (thr_db - level) * (1 - 1 / ratio), 0.0)
    return x * 10 ** (gain_db / 20)


def _chorus(x: np.ndarray, sr: int) -> np.ndarray:
    n = np.arange(len(x))
    y = x.copy()
    for base_ms, depth_ms, hz, mix in [(11.0, 1.6, 0.31, 0.16), (17.0, 2.2, 0.47, 0.12)]:
        delay = (base_ms + depth_ms * np.sin(2 * np.pi * hz * n / sr)) * sr / 1000
        y += mix * np.interp(n - delay, n, x, left=0.0)
    return y


def _feedback(x: np.ndarray, k: int, g: float) -> np.ndarray:
    """y[n] = x[n] + g*y[n-k], a blocchi di k campioni: lfilter con un
    denominatore lungo k costava ~0,8 s per frase (O(n*k))."""
    y = x.copy()
    for start in range(k, len(y), k):
        end = min(start + k, len(y))
        y[start:end] += g * y[start - k:end - k]
    return y


def _allpass(x: np.ndarray, k: int, g: float) -> np.ndarray:
    # y[n] = -g*x[n] + x[n-k] + g*y[n-k]
    v = -g * x
    v[k:] += x[:-k]
    return _feedback(v, k, g)


def _room(x: np.ndarray, sr: int, wet: float = 0.08) -> np.ndarray:
    out = np.zeros_like(x)
    for ms, g in [(19.3, 0.55), (23.9, 0.52), (27.7, 0.5), (31.1, 0.48)]:
        out += _feedback(x, int(sr * ms / 1000), g)
    out /= 4
    for ms, g in [(4.1, 0.6), (1.3, 0.6)]:
        out = _allpass(out, int(sr * ms / 1000), g)
    b, a = signal.butter(2, 400, "highpass", fs=sr)
    return (1 - wet) * x + wet * signal.lfilter(b, a, out)


def film(x: np.ndarray, sr: int) -> np.ndarray:
    """Catena del campione `8_andrew_film`. Ingresso/uscita mono float."""
    if x.size == 0 or not np.any(x):
        return x
    x = np.pad(x.astype(np.float64), (0, int(sr * _TAIL_SEC)))
    y = _compress(_eq(x, sr), sr, thr_db=-30, ratio=4.0, att=0.003, rel=0.06)
    y = _compress(_room(_chorus(y, sr), sr), sr, thr_db=-9, ratio=12.0, att=0.0005, rel=0.05)
    return y / (np.max(np.abs(y)) + 1e-9) * 0.89
