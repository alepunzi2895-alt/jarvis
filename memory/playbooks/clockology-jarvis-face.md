# Quadrante JARVIS con Clockology (senza Mac)

Video della sfera: `watch/tools/render_orb_video.py` (venv JARVIS: playwright,
av, numpy). Usa `web/public/orb.js` con rotazioni modificate per un periodo
esatto di 3600 passi: loop di 60 s a 30 fps, giunzione con dissolvenza di 30
fotogrammi (salto misurato 3,7 contro 3,3-4,2 dei passi normali). Esce in due
versioni: `jarvis_orb.mp4` (solo sfera) e `jarvis_orb_label.mp4` (scritta
JARVIS sopra il centro). Default 410x502 (Ultra/Ultra 2), argomenti `422 514`
per Ultra 3. Con crf 25 pesa circa 8,5 MB.

```
.venv/Scripts/python -I watch/tools/render_orb_video.py . .tmp/watch_face
```

Consegna sull'iPhone: `sendDocument` al bot owner (carica prima `.env` con
load_dotenv, altrimenti `core.telegram.TOKEN` è vuoto → 404).

In Clockology: layer video full screen con il file, layer ora digitale al
centro, layer testo "JARVIS" se si usa la versione senza scritta. Da
verificare sul suo iPhone: se l'editor c'è nell'app iPhone e se il layer
video richiede l'abbonamento Faces+. Clockology mostra solo il quadrante: per
le domande a JARVIS servono il comando rapido sul tasto Azione (playbook
apple-watch-comandi-rapidi.md) oppure l'app nativa.
