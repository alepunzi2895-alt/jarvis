// Attivo solo sulla dashboard servita dal PC. Mai ripiegare sulla coda cloud.
(() => {
  if (!window.JARVIS_LOCAL) return;
  let socket, connecting, current = null;
  let playback = Promise.resolve();
  const entries = new Map(), superseded = new Set(), partials = new Map();
  // Risposte vocali su un elemento <audio> (blob mp3), non su Web Audio: su Safari iOS il
  // contesto Web Audio resta sospeso o muto (interruttore silenzioso) senza un gesto
  // dell'utente, mentre l'elemento audio sbloccato una volta suona anche dopo.
  const player = new Audio();
  player.preload = "auto";
  let playerUnlocked = false, playingNow = false, finishPlayback = null;
  let status;
  let sttReady = false;
  let micEnabled = false;
  let partialEnabled = false; // testo parziale: solo se il PC lo ha attivato (JARVIS_LIVE_PARTIAL=1)
  // PC (puntatore fine): la console aperta abilita la wake word del daemon vocale.
  const coarse = window.matchMedia("(pointer: coarse)").matches;

  function setStatus(text) { if (status) status.textContent = text; }

  // Da chiamare dentro un gesto dell'utente (tocco, tasto, microfono): sblocca l'elemento
  // audio per tutte le risposte successive.
  function unlock() {
    if (playerUnlocked) return;
    player.src = "data:audio/wav;base64,UklGRiQAAABXQVZFZm10IBAAAAABAAEARKwAAIhYAQACABAAZGF0YQAAAAA=";
    player.play().then(() => { playerUnlocked = true; player.pause(); }).catch(() => setStatus("Tocca lo schermo per ascoltare."));
  }

  function silence() {
    current = null;
    player.pause();
    playingNow = false;
    finishPlayback?.();
    botSpeaking = false;
  }

  function finish(id, error) {
    const entry = entries.get(id);
    if (!entry) return;
    if (error && entry.classList.contains("pending")) fillEntry(entry, { status: "error", result: error });
    entries.delete(id);
    superseded.delete(id);
  }

  function cancel() {
    silence();
    if (socket?.readyState === WebSocket.OPEN) socket.send(JSON.stringify({ type: "cancel" }));
    for (const id of entries.keys()) finish(id, "Interrotto.");
    setStatus("Interrotto. Puoi fare una nuova domanda.");
  }

  function play(id, data) {
    if (id !== current) return Promise.resolve();
    return new Promise((resolve) => {
      const url = URL.createObjectURL(new Blob([Uint8Array.from(atob(data), c => c.charCodeAt(0))], { type: "audio/mpeg" }));
      const done = () => {
        player.onended = player.onerror = null;
        URL.revokeObjectURL(url);
        if (finishPlayback === done) finishPlayback = null;
        playingNow = false;
        botSpeaking = false;
        if (orbState === "speaking") setOrbState("idle");
        resolve();
      };
      finishPlayback = done;
      player.onended = done;
      player.onerror = done;
      player.src = url;
      playingNow = true;
      botSpeaking = true;
      setOrbState("speaking");
      player.play().catch(() => {
        setStatus("Tocca lo schermo per ascoltare la risposta.");
        done();
      });
    });
  }

  // Richieste fatte da un'altra superficie (telefono) mostrate anche in chat sul PC.
  const mirrored = new Map();
  function mirrorMessage(data) {
    if (!window.appendEntry || !window.fillEntry) return;
    let el = mirrored.get(data.id);
    if (!el) {
      el = window.appendEntry(data.prompt || "");
      el.classList.add("remote");
      mirrored.set(data.id, el);
      window.openWindow?.("win-chat"); // il comando arrivato dal telefono si vede subito sul PC
    }
    if (data.kind === "result") {
      window.fillEntry(el, { status: "done", result: data.text || "" });
      mirrored.delete(data.id);
    }
  }

  function message(event) {
    const data = JSON.parse(event.data);
    if (data.type === "mirror") { mirrorMessage(data); return; }
    if (data.type === "partial") {
      const onText = partials.get(data.id);
      partials.delete(data.id);
      onText?.(data.text || "");
      return;
    }
    if (data.type === "ready") {
      partialEnabled = Boolean(data.partial);
      if (!sttReady) setStatus(data.stt_ready ? `Voce locale pronta · ${data.device}` : `Preparazione voce locale · ${data.device}`);
      sttReady = data.stt_ready;
      return;
    }
    if (data.type === "feed") {
      window.appendFeed?.(data.item);
      return;
    }
    const entry = entries.get(data.id);
    if (!entry) return;
    switch (data.type) {
      case "accepted":
        silence();
        // Il server annulla il comando precedente: dirlo invece di un generico "Interrotto".
        for (const id of entries.keys()) if (id !== data.id) superseded.add(id);
        current = data.id;
        entry.querySelector(".prompt").textContent = data.prompt;
        if (!entry.dataset.image && handleVoiceUiCommand(data.prompt)) {
          if (socket?.readyState === WebSocket.OPEN) socket.send(JSON.stringify({ type: "cancel" }));
          silence();
          fillEntry(entry, { status: "done", result: "Azione avviata." });
          finish(data.id);
          setOrbState("idle");
          setStatus("Azione avviata.");
          break;
        }
        setOrbState("thinking");
        setStatus("Risposta in arrivo…");
        break;
      case "sentence":
        entry.querySelector(".result").textContent += data.text + " ";
        break;
      case "audio":
        playback = playback.then(() => play(data.id, data.data)).catch(() => setStatus("Audio non disponibile. La risposta è nella console."));
        break;
      case "progress":
        window.showProgress?.(data.label, data.percent);
        break;
      case "result":
        window.hideProgress?.();
        fillEntry(entry, { ...data, status: "done" });
        break;
      case "done": {
        const t = data.timings;
        entry.querySelector(".meta").textContent += ` · STT ${t.stt_ms} ms · testo ${t.first_text_ms ?? "—"} ms · audio ${t.first_audio_ms ?? "—"} ms`;
        setStatus(playerUnlocked ? "Pronto. Di’ Jarvis e la tua domanda." : "Tocca lo schermo per ascoltare.");
        finish(data.id);
        break;
      }
      case "ignored": entry.remove(); finish(data.id); setStatus("Audio ricevuto. Di’ Jarvis e poi il comando."); break;
      case "cancelled":
        window.hideProgress?.();
        if (current === data.id) silence();
        finish(data.id, superseded.has(data.id) ? "Sostituito dal comando successivo." : "Interrotto."); break;
      case "error": window.hideProgress?.(); finish(data.id, data.message); setStatus(data.message); break;
      case "notice": setStatus(data.message); break;
    }
  }

  function connect() {
    if (socket?.readyState === WebSocket.OPEN) return Promise.resolve(socket);
    if (connecting) return connecting;
    setConn("connecting");
    connecting = new Promise((resolve, reject) => {
      const ws = socket = new WebSocket(`${location.protocol === "https:" ? "wss:" : "ws:"}//${location.host}/live/ws${coarse ? "" : "?pc=1"}`);
      const timer = setTimeout(() => ws.close(), 8000);
      ws.onopen = () => {
        if (ws !== socket) return;
        clearTimeout(timer);
        setConn("online");
        if (!coarse) ws.send(JSON.stringify({ type: "mic_state", enabled: micEnabled }));
        resolve(ws);
      };
      ws.onmessage = event => { if (ws === socket) message(event); };
      ws.onerror = () => {
        if (ws !== socket) return;
        setConn("offline");
        reject(new Error("PC non raggiungibile. Controlla Tailscale e riprova."));
      };
      ws.onclose = () => {
        clearTimeout(timer);
        if (ws !== socket) return;
        setConn("offline");
        connecting = null;
        sttReady = false;
        silence();
        for (const id of entries.keys()) finish(id, "Connessione al PC interrotta. Reinvia la domanda.");
        setStatus("PC scollegato. Il prossimo invio riprova la connessione.");
        reject(new Error("PC scollegato. Controlla Tailscale."));
      };
    }).finally(() => { connecting = null; });
    return connecting;
  }

  // Il dispositivo che scrive: il server usa la webcam di quel dispositivo, mai quella del PC dal telefono.
  const DEVICE = /Android|iPhone|iPad|iPod|Mobile/i.test(navigator.userAgent) ? "mobile" : "pc";
  async function submit(payload, entry) {
    if (payload.type === "text") unlock();
    const id = crypto.randomUUID();
    entries.set(id, entry);
    try {
      const ws = await connect();
      if (!entries.has(id)) return;
      ws.send(JSON.stringify({ ...payload, id, device: DEVICE }));
    } catch (error) { finish(id, error.message); }
  }

  // Testo provvisorio mentre si parla: nessuna connessione nuova, solo se il
  // socket e' gia' aperto. Restituisce false se il passo non e' partito.
  function partial(base64Wav, onText) {
    if (!partialEnabled || socket?.readyState !== WebSocket.OPEN) return false;
    const id = "p" + crypto.randomUUID().slice(0, 12);
    partials.set(id, onText);
    socket.send(JSON.stringify({ type: "partial", id, data: base64Wav }));
    return true;
  }

  function start() {
    const bar = document.createElement("div");
    bar.className = "live-controls";
    // Niente pulsanti nella conversazione (2026-10-28): l'audio si sblocca al
    // primo clic o tasto, Esc interrompe la risposta in corso.
    bar.innerHTML = '<span role="status" aria-live="polite">Collegamento al PC…</span>';
    document.querySelector(".fw-body--console").prepend(bar);
    status = bar.querySelector("span");
    const firstGesture = () => {
      unlock();
      document.removeEventListener("pointerdown", firstGesture, true);
      document.removeEventListener("keydown", firstGesture, true);
    };
    document.addEventListener("pointerdown", firstGesture, true);
    document.addEventListener("keydown", firstGesture, true);
    document.addEventListener("keydown", (event) => { if (event.key === "Escape" && current) cancel(); });
    connect().catch(error => setStatus(error.message));
    setInterval(() => {
      if (!sttReady && !document.hidden && socket?.readyState === WebSocket.OPEN) socket.send(JSON.stringify({ type: "status" }));
      // Sul PC si ricollega da solo (es. dopo un riavvio di LiveBridge):
      // senza, la console resta aperta ma la wake word spenta.
      if (!coarse && !connecting && (!socket || socket.readyState === WebSocket.CLOSED)) connect().catch(() => {});
    }, 10000);
    // Pagina nascosta (altra scheda, finestra coperta: Chrome/Edge su Windows
    // la marcano hidden): il comando continua sul PC, annullare resta compito
    // di Stop. 2026-10-14: "Analizza i job"/"Organizza oggi" finivano in
    // "Interrotto." cosi'. Solo su telefono si zittisce: sul desktop la voce
    // deve arrivare anche con la finestra coperta, come dalle casse del PC.
    document.addEventListener("visibilitychange", () => { if (document.hidden && coarse) silence(); });
    // Dopo un reload il browser tiene l'audio sospeso fino al primo gesto:
    // qualunque clic o tasto lo riattiva, anche senza pulsanti.
    window.addEventListener("pagehide", () => { cancel(); socket?.close(); });
  }
  function setMicEnabled(enabled) {
    micEnabled = Boolean(enabled);
    if (!coarse && socket?.readyState === WebSocket.OPEN) {
      socket.send(JSON.stringify({ type: "mic_state", enabled: micEnabled }));
    }
  }

  window.JarvisDirect = { start, submit, partial, get partialEnabled() { return partialEnabled; }, get audioState() { return playerUnlocked ? 'unlocked' : 'locked'; }, unlock, cancel, setMicEnabled, get speaking() { return playingNow; } };
})();
