# JARVIS per Apple Watch

App watchOS a schermo intero: la sfera animata della dashboard
(`web/public/orb.js` portato in SwiftUI), la scritta JARVIS e l'ora digitale al
centro. Un tocco apre la dettatura; la domanda va a `POST /watch/ask` su
LiveBridge (`core/live_server.py`) e la risposta compare sotto la sfera e viene
letta a voce. Colore della sfera: blu a riposo, ambra mentre elabora, verde
mentre parla, rosso in caso di errore.

Apple non permette quadranti di terze parti: l'app fa da quadrante restando in
primo piano (vedi "Sul Watch").

## Build (Mac con Xcode 15 o successivo)

1. Clona il branch:
   `git clone -b feature/watch-app https://github.com/alepunzi2895-alt/jarvis.git`
2. `cp watch/JarvisWatch/Config.swift.example watch/JarvisWatch/Config.swift`
   e inserisci l'indirizzo della dashboard privata e il contenuto di
   `.watch-token` (sul PC). `Config.swift` non va su Git.
3. Xcode → File → New → Project → watchOS → App. Nome `JarvisWatch`,
   interfaccia SwiftUI, "Watch-only App". Salvalo fuori dal repo.
4. Nel target Watch elimina `ContentView.swift` e `JarvisWatchApp.swift` del
   modello (Move to Trash).
5. Trascina nel target i file `.swift` di `watch/JarvisWatch/`
   (`Config.swift.example` escluso), con "Copy items if needed" **spento**:
   così un `git pull` aggiorna direttamente il progetto.
6. Target → General → Minimum Deployments: watchOS 10.0.
   Signing & Capabilities → Team: il tuo Apple ID.
7. Prova prima nel simulatore "Apple Watch Ultra" (il Mac deve avere Tailscale
   acceso per raggiungere il PC).
8. Sul Watch vero: Impostazioni → Privacy e sicurezza → Modalità sviluppatore.
   Scegli il Watch come destinazione in Xcode e premi Run. La prima
   installazione è lenta.

Con l'Apple ID gratuito l'app scade dopo 7 giorni (basta un nuovo Run). Con
l'Apple Developer Program resta installata.

## Sul Watch

- Impostazioni → Generali → Ritorna al quadrante: "Dopo 1 ora". Abbassando il
  polso JARVIS resta al posto del quadrante.
- Con l'Always On la sfera si ferma e si attenua, l'ora resta visibile.
- L'animazione a 30 fps consuma batteria solo con il polso alzato.

## Limiti noti

- Codice scritto su Windows senza compilarlo: il primo build può chiedere
  piccole correzioni.
- Il tocco apre l'inserimento di watchOS: tocca il microfono per dettare.
- Non è verificato che il Watch raggiunga la tailnet passando dall'iPhone.
  Se nel simulatore funziona e sul Watch compare "PC non raggiungibile",
  serve l'endpoint pubblico sulla VPS.
- Voce di sistema italiana di Apple, non ancora la voce JARVIS del PC.
