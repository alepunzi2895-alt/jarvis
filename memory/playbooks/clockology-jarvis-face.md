# Quadrante JARVIS con Clockology (senza Mac)

Video della sfera: `watch/tools/render_orb_video.py` (venv JARVIS: playwright,
av, numpy). Usa `web/public/orb.js` con rotazioni modificate per un periodo
esatto di 3600 passi: loop di 60 s a 30 fps, giunzione con dissolvenza di 30
fotogrammi. Esce in due versioni: `jarvis_orb_<stile>.mp4` (solo sfera) e
`jarvis_orb_<stile>_label.mp4` (scritta JARVIS sopra il centro). Default
410x502 (Ultra/Ultra 2), argomenti `422 514` per Ultra 3.

Stili (`--stile`, default `liscia`):
- `liscia`: 170 nodi a raggio costante, bordo e alone circolari, raggio 0,37
  dello schermo. Circa 3,5 MB.
- `globo`: nodi su 12 paralleli, bordo e alone. Circa 2,6 MB.
- `originale`: la sfera irregolare di prima (rifiutata il 2026-10-16:
  "non sembra un cerchio perfetto", raggio irregolare e bordo a poligono).

Gli stili sono `ORB_STYLES` in `web/public/orb.js` (dal 2026-10-16 anche la
dashboard usa `liscia`): lo script passa `{ style }` a `createJarvisOrb` e
patcha solo le rotazioni per il loop esatto. Cambiare uno stile = cambiare
`orb.js`, dashboard e video restano allineati.

```
.venv/Scripts/python -I watch/tools/render_orb_video.py . .tmp/watch_face_v2 --stile liscia
```

Lampi: con la propagazione degli impulsi della dashboard (0,7) la rete entra
in cascata e l'intera sfera si accende ogni ~1 s (5-30% dei passi). Gli stili
rotondi usano 0,32 (liscia) e 0,26 (globo), scelti con una simulazione di
7200 passi: mai oltre il 30% dei nodi accesi insieme. Dopo ogni modifica
misura il video: differenza media tra fotogrammi consecutivi (scala di
grigi), la giunzione deve stare nel p5-p95 dei passi normali e il massimo
non deve superare ~3 volte il p95 (un lampo vale 20+).

Consegna sull'iPhone: `sendDocument` al bot owner (carica prima `.env` con
load_dotenv, altrimenti `core.telegram.TOKEN` è vuoto → 404).

In Clockology: layer video full screen con il file, layer ora digitale al
centro, layer testo "JARVIS" se si usa la versione senza scritta. Da
verificare sul suo iPhone: se l'editor c'è nell'app iPhone e se il layer
video richiede l'abbonamento Faces+. Clockology mostra solo il quadrante: per
le domande a JARVIS servono il comando rapido sul tasto Azione (playbook
apple-watch-comandi-rapidi.md) oppure l'app nativa.
