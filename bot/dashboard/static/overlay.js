/* Overlay de stream — bulles, avatar, instrumentation.
 *
 * Rappel de conception : cet overlay s'adresse aux VIEWERS. Le streamer ne le
 * voit pas pendant qu'il joue.
 *
 * Le rendu se fait sur SA machine, à côté du jeu et de l'encodage : on reste
 * sur des animations transform/opacity, composées par le GPU sans repaint.
 */
(() => {
  "use strict";

  const stage  = document.getElementById("stage");
  const slot   = document.getElementById("avatar-slot");
  const avatar = document.getElementById("avatar");
  const bubble = document.getElementById("bubble");

  const RECONNECT_MS = 5000;

  // ── Avatar émotionnel ────────────────────────────────────────────────────
  // Conservé tel quel de la version précédente : Rive le remplacera en phase 3.
  function updateAvatar(emotions) {
    let dominant = "neutral", maxVal = 0.2;
    for (const [emotion, value] of Object.entries(emotions || {})) {
      if (value > maxVal) { dominant = emotion; maxVal = value; }
    }
    let tier = "idle";
    if (dominant !== "neutral") {
      tier = maxVal >= 0.7 ? "high" : maxVal >= 0.4 ? "mid" : "low";
    }
    const base = dominant === "neutral"
      ? "/static/avatar/emotions/neutral/idle"
      : `/static/avatar/emotions/${dominant}/${tier}`;

    // Certaines émotions n'ont qu'un PNG : on teste le GIF avant de l'appliquer.
    const probe = new Image();
    probe.onload  = () => { avatar.src = base + ".gif"; };
    probe.onerror = () => { avatar.src = base + ".png"; };
    probe.src = base + ".gif";
  }

  // ── Bulle ────────────────────────────────────────────────────────────────
  let hideTimer = null;

  function showBubble(node, mode) {
    clearTimeout(hideTimer);
    bubble.className = mode === "thought" ? "thought" : "speech";
    bubble.replaceChildren(node);
    // Force un reflow pour que la transition reparte même sur deux bulles
    // consécutives.
    void bubble.offsetWidth;
    bubble.classList.add("visible");
  }

  function hideBubble() {
    bubble.classList.remove("visible");
  }

  function say(text, mode, durationSeconds) {
    // textContent via createTextNode : le texte vient du LLM, jamais interprété
    // comme du HTML.
    showBubble(document.createTextNode(text), mode);
    hideTimer = setTimeout(hideBubble, Math.max(1, durationSeconds || 3) * 1000);
  }

  function makeDots() {
    const dots = document.createElement("span");
    dots.className = "dots";
    for (let i = 0; i < 3; i++) dots.appendChild(document.createElement("span"));
    return dots;
  }

  function showThinking(active) {
    clearTimeout(hideTimer);
    if (!active) { hideBubble(); return; }
    showBubble(makeDots(), "speech");
    // Filet de sécurité : si la génération échoue sans jamais rien renvoyer,
    // les points ne doivent pas rester à l'écran indéfiniment.
    hideTimer = setTimeout(hideBubble, 15000);
  }

  function react() {
    slot.classList.remove("reacting");
    void slot.offsetWidth;
    slot.classList.add("reacting");
    setTimeout(() => slot.classList.remove("reacting"), 1000);
  }

  // ── Flux SSE ─────────────────────────────────────────────────────────────
  function connect(url, onMessage) {
    let source;
    const open = () => {
      source = new EventSource(url);
      source.onmessage = (e) => {
        try { onMessage(JSON.parse(e.data)); } catch { /* keepalive ou bruit */ }
      };
      source.onerror = () => { source.close(); setTimeout(open, RECONNECT_MS); };
    };
    open();
  }

  connect("/api/public/sse/emotions", updateAvatar);

  connect("/api/public/sse/overlay", (d) => {
    stage.classList.toggle("hidden", d.visible === false);
  });

  connect("/api/public/sse/overlay-feed", (event) => {
    switch (event.type) {
      case "bubble":   say(event.text, event.mode, event.duration); break;
      case "thinking": showThinking(event.active); break;
      case "react":    react(); break;
      case "widget":   /* phase 1b */ break;
    }
  });

  // ── Instrumentation ──────────────────────────────────────────────────────
  // Impossible de lire l'usage GPU depuis une page (la Compute Pressure API ne
  // couvre que le CPU, et n'est pas disponible dans le CEF d'OBS). On mesure
  // donc ce qu'on peut : le coût de rendu de l'overlay lui-même. Sert de base de
  // comparaison AVANT l'ajout de l'avatar animé.
  const perf = { frames: 0, worstFrame: 0, last: performance.now() };

  function tick(now) {
    const delta = now - perf.last;
    perf.last = now;
    perf.frames++;
    if (delta > perf.worstFrame) perf.worstFrame = delta;
    requestAnimationFrame(tick);
  }
  requestAnimationFrame(tick);

  function gpuName() {
    try {
      const gl = document.createElement("canvas").getContext("webgl");
      const ext = gl && gl.getExtension("WEBGL_debug_renderer_info");
      return ext ? gl.getParameter(ext.UNMASKED_RENDERER_WEBGL) : "inconnu";
    } catch { return "inconnu"; }
  }

  setInterval(() => {
    const fps = perf.frames / 10;
    fetch("/api/public/overlay-health", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        fps: Math.round(fps),
        worst_frame_ms: Math.round(perf.worstFrame),
        gpu: gpuName(),
      }),
      keepalive: true,
    }).catch(() => { /* le diagnostic ne doit jamais gêner l'affichage */ });
    perf.frames = 0;
    perf.worstFrame = 0;
  }, 10000);
})();
