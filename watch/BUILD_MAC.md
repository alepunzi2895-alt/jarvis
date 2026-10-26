# JARVIS Watch: build su Mac con Xcode 15.1

Setup: macOS Ventura 13.7.8, Xcode 15.1, watchOS 26 sul Watch.

## ATTENZIONE: blocco da leggere prima

Xcode 15.1 non può installare né fare il debug su un Watch con watchOS 26.
Il suo SDK arriva a watchOS 10.1. Su Ventura non si installa Xcode 26, che serve
per watchOS 26 (requisito riportato in
[Apple Developer Forums, thread 823233](https://developer.apple.com/forums/thread/823233)
e in [mjtsai.com](https://mjtsai.com/blog/?p=49363): Xcode 26 richiede macOS Sequoia 15.6 o superiore).
Per Xcode 26.4 il requisito è macOS Tahoe 26.2 o superiore
([fonte in cinese](https://developer.aliyun.com/article/1719435)).

Quindi con questa combinazione hai due strade:

- **Strada A (solo questa guida, nessun device):** Xcode 15.1 su Ventura, build e
  test nel simulatore Apple Watch con watchOS 10.1. Il Watch fisico con watchOS 26
  non lo vede.
- **Strada B (consigliata per il Watch vero):** aggiorna il Mac a Sonoma o Sequoia
  (verifica che il modello sia supportato da Apple), installa Xcode 26, poi segui
  `watch/README.md` su quella versione. Nessun cambio di codice: il progetto usa
  watchOS 10.0 come minimo, compatibile con entrambe.

Le sezioni sotto sono per la strada A. Per la B, ripeti i passi 3-9 con Xcode 26.

---

## 0. Prerequisiti

1. Apple ID registrato al Developer Program gratuito (serve per firmare il progetto).
2. Spazio libero: almeno 30 GB (Xcode 15.1 più il simulatore watchOS).
3. Sul PC Windows, JARVIS acceso e Tailscale attivo sul Mac (l'app chiama il ponte VPS
   su porta 9443).
4. Sul PC, leggi il token: `C:\Users\f45038c\Downloads\jarvis\.watch-token`
   (senza "Bearer"). Lo incolli nel passo 3.

## 1. Installa Xcode 15.1

1. Apri https://developer.apple.com/download/all/ e accedi.
2. Cerca **Xcode 15.1** e scarica il file `Xcode_15.1.xip`.
   Non usare l'App Store: installa l'ultima versione, non la 15.1.
3. Doppio clic sul `.xip`: Safari lo estrae in `Xcode.app`.
4. Sposta `Xcode.app` in `/Applications`. Se hai già altro Xcode, rinomina
   prima quello vecchio (es. `Xcode-26.app`), non cancellarlo.
5. Apri Terminale e seleziona la versione:
   ```sh
   sudo xcode-select -s /Applications/Xcode.app/Contents/Developer
   xcodebuild -version
   ```
   Output atteso: `Xcode 15.1` e `Build version 15C65`.
6. Apri Xcode, accetta la licenza, lascia installare i componenti aggiuntivi.

## 2. Installa il simulatore watchOS 10.1

1. Xcode → Settings → **Platforms** (o Components).
2. Clicca `+` → **watchOS 10.1 Simulator** → Get. Dimensione circa 5-8 GB.
3. Verifica nel menu di destinazione: "Apple Watch Ultra (49mm)" presente.

## 3. Clona il branch e prepara la configurazione

```sh
cd ~/Developer
git clone -b feature/watch-app https://github.com/alepunzi2895-alt/jarvis.git
cd jarvis/watch/JarvisWatch
cp Config.swift.example Config.swift
open -e Config.swift
```

In `Config.swift` incolla il token dentro `token` (il contenuto di `.watch-token`).
L'indirizzo `baseURL` è già corretto (ponte VPS, porta 9443). Salva.
`Config.swift` è in `.gitignore`: non committarlo.

## 4. Crea il progetto Xcode (fuori dal repo)

1. Xcode → File → New → Project.
2. Scheda **watchOS** → **App** → Next.
3. Product Name: `JarvisWatch`. Interface: **SwiftUI**. Language: **Swift**.
4. Spunta **Watch-only App** (in Xcode 15 è la voce "Supports Running Without iOS App
   Installation" o simile: attivala).
5. Salva in una cartella **fuori** da `jarvis/`, es. `~/Developer/JarvisWatchProject`.

## 5. Sostituisci i file del template

1. Nel navigatore a sinistra, nel gruppo `JarvisWatch Watch App`, seleziona
   `ContentView.swift` e `JarvisWatchApp.swift` (quello del template) → Move to Trash.
2. Trascina nel target **JarvisWatch Watch App** tutti questi file da
   `~/Developer/jarvis/watch/JarvisWatch/`:
   - `Config.swift`
   - `ContentView.swift`
   - `JarvisClient.swift`
   - `JarvisSession.swift`
   - `JarvisWatchApp.swift`
   - `LocationProvider.swift`
   - `OrbView.swift`

   Nella finestra di importazione: **Copy items if needed: SPENTO**. Spunta solo il
   target Watch App.
3. NON trascinare `Config.swift.example`.

## 6. Impostazioni del target

1. Seleziona il progetto → target **JarvisWatch Watch App**.
2. **General → Minimum Deployments**: watchOS **10.0**.
3. **Signing & Capabilities** → Team: il tuo Apple ID. Lascia "Automatically manage signing" attivo.
4. **Info** → aggiungi la chiave
   `Privacy - Location When In Use Usage Description`
   con valore: `Per il meteo di JARVIS da dove sei`.
5. **Build Settings** → cerca `Swift Language Version`: deve essere **Swift 5**.
   Se è 6, cambialo (Xcode 15.1 non supporta Swift 6).

## 7. Build e test nel simulatore

1. Destinazione in alto: **Apple Watch Ultra (49mm)** (watchOS 10.1).
2. Cmd+B. Se compila, Cmd+R.
3. Nel simulatore: tocca la sfera → detta o scrivi una domanda → Invio.
4. Al primo uso concedi microfono e posizione (opzionali).
5. Se appare "JARVIS non raggiungibile. Controlla iPhone e Tailscale.":
   Tailscale è acceso sul Mac? Il ponte risponde su `https://win-6gfp84o12pq.tail18e3c0.ts.net:9443`?
   Controlla dal Mac con `curl -sI https://win-6gfp84o12pq.tail18e3c0.ts.net:9443`.

## 8. Errori di compilazione

Copia l'errore completo (testo rosso, riga e file) e incollalo nella chat con JARVIS.
Non modificare altro: il codice è stato scritto su Windows senza compilazione, quindi
piccoli errori sono attesi.

## 9. Installazione sul Watch fisico (solo strada B)

Con Xcode 15.1 non è possibile. Con Xcode 26 su Sequoia:

1. Watch: Impostazioni → Privacy e sicurezza → Modalità sviluppatore → riavvio.
2. Watch e iPhone collegati al Mac, stessa rete.
3. Xcode → destinazione: il Watch → Cmd+R. La prima installazione è lenta.
4. Con Apple ID gratuito l'app scade dopo 7 giorni: basta un nuovo Cmd+R.

## 10. Aggiornare il codice

```sh
cd ~/Developer/jarvis && git pull
```
I file in `jarvis/` sono referenziati, quindi l'aggiornamento è automatico. Poi Cmd+R in Xcode.
