# AURA Ibiza

## Cos'è
Brand concierge di lusso a Ibiza — **brand principale** di Alessandro tra
i suoi progetti imprenditoriali. Opera a Ibiza e Formentera.
Dominio: auraibiza.com (Aruba).

## Modello di business
Tre linee: **B2C** (servizi diretti ai clienti finali), **B2B** (toolkit
SaaS/agenti IA rivenduti ad altri concierge), **B2P** (gestione ville a
revenue share per i proprietari).

## Servizi
Ville, yacht/barche, supercar, tavoli VIP ed eventi, ristoranti,
esperienze curate, transfer. Contatto diretto: +34 645 265 430.

## Regola assoluta
**Il brand è solo "AURA Ibiza".** Mai citare brand precedenti/dismessi:
LuXy Experience, Guaca/GuacaTravel/GuacaConcierge/GuacaBrain, Easy Life
Ibiza, Casa Porto — non esistono più, non nominarli nemmeno per errore.

## Identità
- Posizionamento: insider, minimale, spirituale — "conoscere" Ibiza, non
  promuoverla.
- Palette attuale: sabbia #F1E8D7, turchese #3FB6B2, teal scuro #2A8B87,
  ink #20423E. **Nota**: esiste anche una versione precedente
  verde-petrolio/oro — verificare con lui quale sia quella davvero attiva
  prima di usarla in un nuovo asset.
- Font: Playfair Display Medium (wordmark/titoli), Jost con spaziatura
  larga ~+250 (label/CTA).
- Elemento firma: cornice bianca interna ("cornice-firma").
- Motto: non ancora definitivo — direzione voluta: 2-3 parole evocative
  (es. "Live the unseen", "Ibiza, revealed").

## Contenuti/social
- Copy sempre **trilingue IT/EN/ES**, registro lusso-minimale — mai copy
  da agenzia generica.
- Caption: due righe evocative. Hashtag: #AuraIbiza #Ibiza #Formentera
  #IbizaVIP #IbizaNightlife.
- Strategia: "mostrare l'invisibile" + post product-forward (ville, auto,
  yacht — questi performano meglio dei post più concettuali).
- Griglia Instagram a terzine; 3 post guida fissati (City/Island, Beach,
  Party) — coerente con la griglia a temi già nota da JARVIS.
- Reel/Stories: template Canva pronti (PNG 1080×1920).
- **Gap aperto**: zero Reel sull'account — prossima leva di reach non
  ancora sfruttata.
- Nota qualità: post con l'auto ripresa in garage è il contenuto più
  debole pubblicato finora — da rifare all'aperto se richiesto di nuovo.

## Outreach e ads
- `aura_outreach.py` (Google Places API): 4 categorie (ristoranti/beach
  club, ville, auto, barche) × 10 zone di Ibiza → messaggi trilingue
  personalizzati con link `wa.me` e `mailto`, output Excel/CSV.
- Tono outreach: non insistente, CTA via email, mai chiedere chiamate
  dirette.
- Canale preferito: **WhatsApp** solo per link click-through — **mai**
  invii massivi automatici (violano i ToS di WhatsApp Business).
- Meta Ads: pubblico "On Island" (Ibiza/Formentera) + "Feeder Cities"
  (Londra, Parigi, Milano, Zurigo, Ginevra, Amsterdam, Dubai).

## Asset e contatti
- **Kevin** — gestisce il portafoglio ville; cartella PDF su Google
  Drive, ID `1QXHvMqvwW_5vKQg-tvOJ2RcnX6gPJNoo`.
- Ville: estrazione foto da PDF con PyMuPDF (22 ville già elaborate).
- Catalogo auto: 10 veicoli, targhe sfocate. Catalogo yacht: modifica
  prezzi con overlay PyMuPDF.

## Stack piattaforma
Next.js, Supabase, Claude API, Twilio, Stripe, Vercel.

## Lezioni sugli strumenti (da non riscoprire)
- Canva `generate-design` interpreta liberamente, non replica un layout
  al pixel — metodo affidabile: PNG trasparenti caricati come overlay
  bloccati + testo editabile sopra.
- Google Places restituisce telefono e sito ma **non** l'email — serve
  scraping del sito per quella.
- Connettore Google Drive: ricerca/creazione cartelle/copia OK; download
  contenuti no (limite noto del connettore, non un bug suo).

## Prossimi passi noti
- Integrare l'outreach in un CRM vero su Next.js/Supabase + Twilio
  (oggi è uno script standalone che produce un CSV).
- Estendere l'outreach a wellness, chef privati, sicurezza (oltre alle 4
  categorie attuali).

## Collegamento con AP Systems
AURA compare come case study nel portfolio AP Systems (vedi
`memory/projects/ap-systems.md`) insieme a ConciergeFlow.
