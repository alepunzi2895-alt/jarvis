# JARVIS per Apple Watch

App watchOS a schermo intero: la sfera animata della dashboard
(`web/public/orb.js`, stile "liscia", portato in SwiftUI), la scritta JARVIS e
l'ora digitale al centro. Un tocco apre la dettatura; la domanda va a
`POST /watch/ask` sul ponte VPS (`core/relay.py`): con il PC acceso risponde il
PC con tutte le sue app, con il PC spento risponde la VPS. La risposta compare
sotto la sfera e viene letta a voce. Ogni domanda porta la posizione del Watch
(se concessa) per il meteo. Colore della sfera: blu a riposo, ambra mentre
elabora, verde mentre parla, rosso in caso di errore.

Apple non permette quadranti di terze parti: l'app fa da quadrante restando in
primo piano (vedi "Sul Watch").

## Build (Mac con Xcode 15 o successivo)

1. Clona il branch:
   `git clone -b feature/watch-app https://github.com/alepunzi2895-alt/jarvis.git`
2. `cp watch/JarvisWatch/Config.swift.example watch/JarvisWatch/Config.swift`
   e incolla in `token` il contenuto di `.watch-token` (sul PC, senza
   "Bearer"). L'indirizzo del ponte e' gia' giusto. `Config.swift` non va su Git.
3. Xcode → File → New → Project → watchOS → App. Nome `JarvisWatch`,
   interfaccia SwiftUI, "Watch-only App". Salvalo fuori dal repo.
4. Nel target Watch elimina `ContentView.swift` e `JarvisWatchApp.swift` del
   modello (Move to Trash).
5. Trascina nel target tutti i file `.swift` di `watch/JarvisWatch/`
   (anche `Config.swift` e `LocationProvider.swift`; non `Config.swift.example`),
   con "Copy items if needed" **spento**: un `git pull` aggiorna il progetto.
6. Target → Info → aggiungi la chiave
   "Privacy - Location When In Use Usage Description" con il testo
   "Per il meteo di JARVIS da dove sei".
7. Target → General → Minimum Deployments: watchOS 10.0.
   Signing & Capabilities → Team: il tuo Apple ID.
8. Prova nel simulatore "Apple Watch Ultra" (il Mac deve avere Tailscale
   acceso per raggiungere il ponte).
9. Sul Watch vero: Impostazioni → Privacy e sicurezza → Modalita' sviluppatore,
   poi riavvio del Watch. Watch e iPhone collegati al Mac (stessa rete Wi-Fi,
   iPhone via cavo la prima volta). In Xcode scegli il Watch come destinazione e
   premi Run. La prima installazione e' lenta.

Con l'Apple ID gratuito l'app scade dopo 7 giorni (basta un nuovo Run). Con
l'Apple Developer Program resta installata.

## Sul Watch

- Alla prima domanda concedi microfono/dettatura e posizione.
- Impostazioni → Generali → Ritorna al quadrante: "Dopo 1 ora". Abbassando il
  polso JARVIS resta al posto del quadrante.
- Con l'Always On la sfera si ferma e si attenua, l'ora resta visibile.
- L'animazione a 30 fps consuma batteria solo con il polso alzato.

## Limiti noti

- Codice scritto su Windows senza compilarlo: il primo build puo' chiedere
  piccole correzioni (incolla qui gli errori di Xcode).
- Il tocco apre l'inserimento di watchOS: tocca il microfono per dettare.
- Non e' verificato che il Watch raggiunga la tailnet passando dall'iPhone.
  Se nel simulatore funziona e sul Watch compare "JARVIS non raggiungibile",
  serve aprire `/watch/ask` del ponte con Tailscale Funnel.
- Voce di sistema italiana di Apple, non ancora la voce JARVIS del PC.
- La prima domanda dopo l'installazione parte senza posizione (richiesta del
  permesso); dalla seconda il meteo segue il Watch.
