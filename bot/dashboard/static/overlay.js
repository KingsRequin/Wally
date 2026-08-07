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
  const bubble = document.getElementById("bubble");

  const RECONNECT_MS = 5000;

  // Ancrage à DROITE par défaut (posé dans le HTML, donc sans flash au chargement).
  // `?side=left` rétablit l'ancrage à gauche ; la mise en page est purement CSS
  // derrière `data-side`.
  if (new URLSearchParams(location.search).get("side") === "left") {
    document.body.dataset.side = "left";
  }

  // ── Avatar ───────────────────────────────────────────────────────────────
  // Les GIF par émotion ont été retirés : #avatar-slot attend son avatar Rive.
  // Tout ce qui y sera placé hérite de la taille du slot et de l'animation de
  // réaction (classe .reacting), sans rien changer ici.
  //
  // Le flux SSE des émotions n'est plus consommé : avec Rive, une émotion pilote
  // des ENTRÉES de machine à états, pas un choix de fichier — le rebranchement
  // se fera sur ce modèle, pas en restaurant celui-ci.

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

  // ── Widgets ──────────────────────────────────────────────────────────────
  // Rendus en CSS 3D plutôt qu'avec un moteur : plus léger, et composé par le
  // GPU du streamer — qui fait déjà tourner le jeu et l'encodage.
  const widgets = document.getElementById("widgets");
  let widgetTimer = null;

  const BUILDERS = {
    // Le résultat vient de Wally, pas du hasard du navigateur : c'est ce qui lui
    // permet de commenter — et de tricher.
    coinflip(p) {
      const heads = p.result !== "tails";
      const coin = el("div", "coin");
      // Demi-tours pairs → pile reste face à nous ; impairs → on voit l'autre.
      const halfTurns = (heads ? 6 : 7) * 180;
      coin.style.setProperty("--half-turns", `${halfTurns}deg`);
      coin.style.setProperty("--half-turns-mid", `${halfTurns / 2}deg`);
      coin.append(faceEl("face", "P"), faceEl("face tails", "F"));
      return coin;
    },

    dice(p) {
      // Un ou plusieurs dés : le serveur envoie `results`, `result` reste pour
      // la compatibilité d'un tirage unique.
      const values = Array.isArray(p.results) && p.results.length
        ? p.results : [p.result];
      if (values.length > 1) {
        const row = el("div", "dice-row");
        values.forEach((v) => row.appendChild(BUILDERS.dice({ result: v })));
        return row;
      }
      const value = Math.min(6, Math.max(1, parseInt(values[0], 10) || 1));
      const die = el("div", "die");
      // Rotation finale qui amène la face voulue vers la caméra.
      const FINAL = {
        1: "rotateX(0deg) rotateY(0deg)",
        2: "rotateY(-90deg)",
        3: "rotateY(180deg)",
        4: "rotateY(90deg)",
        5: "rotateX(-90deg)",
        6: "rotateX(90deg)",
      };
      die.style.setProperty("--final-rotation", FINAL[value]);
      for (let i = 1; i <= 6; i++) {
        const side = el("div", `side s${i}`);
        side.textContent = String(i);
        die.appendChild(side);
      }
      return die;
    },

    counter(p) {
      const node = el("div", "counter");
      node.textContent = String(p.text || "");
      return node;
    },

    // La roue s'arrête sur l'option choisie côté serveur : l'angle est calculé
    // pour amener ce secteur sous le curseur.
    wheel(p) {
      const options = Array.isArray(p.options) ? p.options.slice(0, 8) : [];
      if (!options.length) return el("div", "");
      const winner = Math.min(options.length - 1, Math.max(0, Number(p.index) || 0));
      const slice = 360 / options.length;

      const box = el("div", "wheel-box");
      const wheel = el("div", "wheel");
      const COLORS = ["#46c6ff", "#9d7bff", "#ff7ba8", "#ffcf5c",
                      "#6ee7a8", "#ff9f68", "#7fd1ff", "#c9a0ff"];
      const stops = options
        .map((_, i) => `${COLORS[i % COLORS.length]} ${i * slice}deg ${(i + 1) * slice}deg`)
        .join(", ");
      wheel.style.background = `conic-gradient(${stops})`;
      // Plusieurs tours pour l'effet, puis on aligne le milieu du secteur en haut.
      const angle = 360 * 4 + (360 - (winner * slice + slice / 2));
      wheel.style.setProperty("--final-angle", `${angle}deg`);

      const label = el("div", "label");
      label.textContent = String(options[winner]);
      box.append(wheel, el("div", "pin"), label);
      return box;
    },

    countdown(p) {
      const node = el("div", "countdown");
      let left = Math.min(600, Math.max(1, parseInt(p.seconds, 10) || 10));
      const render = () => {
        const m = Math.floor(left / 60);
        node.textContent = m > 0
          ? `${m}:${String(left % 60).padStart(2, "0")}`
          : String(left);
        node.classList.remove("tick");
        void node.offsetWidth;
        node.classList.add("tick");
      };
      render();
      const id = setInterval(() => {
        left -= 1;
        if (left <= 0) { clearInterval(id); node.textContent = String(p.done || "0"); return; }
        render();
      }, 1000);
      // Le widget peut être remplacé avant la fin : on coupe le timer avec lui.
      node.dataset.interval = String(id);
      return node;
    },

    gauge(p) {
      const box = el("div", "gauge");
      const cap = el("div", "cap");
      cap.textContent = String(p.label || "");
      const track = el("div", "track");
      const fill = el("div", "fill");
      const pct = Math.min(100, Math.max(0, Number(p.percent) || 0));
      track.appendChild(fill);
      box.append(cap, track);
      // Laisse le navigateur peindre à 0 avant d'animer vers la valeur.
      requestAnimationFrame(() => { fill.style.width = `${pct}%`; });
      return box;
    },

    // Le sondage se met à jour à chaque vote : on le reconstruit en place plutôt
    // que de le faire réapparaître, pour ne pas rejouer l'animation d'entrée.
    poll(p) {
      const options = Array.isArray(p.options) ? p.options : [];
      const box = el("div", "poll");

      const q = el("div", "q");
      const qText = el("span", "");
      qText.textContent = String(p.question || "");
      const left = el("span", "left");
      q.append(qText, left);
      box.appendChild(q);

      // Sablier : une seule animation linéaire posée à la création, donc fluide
      // en continu — le décompte en secondes, lui, saute d'un cran à la fois.
      const timer = el("div", "timer");
      const bar = document.createElement("span");
      if (p.seconds > 0) timer.style.setProperty("--dur", `${p.seconds}s`);
      timer.appendChild(bar);
      box.appendChild(timer);

      options.forEach((label, i) => {
        const opt = el("div", "opt");
        // Entrée en cascade : les options se posent l'une après l'autre.
        opt.style.setProperty("--i", String(i));
        const row = el("div", "row");
        const name = el("span", "");
        name.textContent = `${i + 1}. ${label}`;
        const count = el("span", "count");
        row.append(name, count);
        const track = el("div", "bar");
        track.appendChild(document.createElement("span"));
        opt.append(row, track);
        box.appendChild(opt);
      });
      updatePoll(box, p);
      return box;
    },

    bingo(p) {
      const cells = Array.isArray(p.cells) ? p.cells : [];
      const done = Array.isArray(p.done) ? p.done : [];
      const classesBox = ["bingo"];
      if (p.full) classesBox.push("full");
      if (cells.length <= 4) classesBox.push("few");   // 2 colonnes suffisent
      const box = el("div", classesBox.join(" "));
      const title = el("div", "bingo-title");
      title.textContent = p.full ? "BINGO !" : "Bingo du stream";
      box.appendChild(title);
      const grid = el("div", "grid");
      box.appendChild(grid);
      cells.forEach((label, i) => {
        // `just` met en avant la case qu'on vient de cocher : sans ça, on ne
        // sait pas ce qui a changé dans une grille déjà à moitié pleine.
        const classes = ["cell"];
        if (done[i]) classes.push("done");
        if (i === p.just) classes.push("just");
        const row = el("div", classes.join(" "));
        row.style.setProperty("--i", String(i));
        const mark = el("span", "mark");
        mark.textContent = done[i] ? "✓" : "";
        const text = el("span", "txt");
        text.textContent = String(label);
        row.append(mark, text);
        grid.appendChild(row);
      });
      return box;
    },

    stats(p) {
      const box = el("div", "stats");
      if (p.player) {
        const who = el("div", "who");
        who.textContent = String(p.player);
        box.appendChild(who);
      }
      (Array.isArray(p.lines) ? p.lines : []).forEach((line, i) => {
        const row = el("div", "line");
        row.style.setProperty("--i", String(i));
        // « Label : valeur » est séparé pour aligner les valeurs à droite ;
        // sans deux-points, la ligne reste affichée telle quelle.
        const cut = String(line).indexOf(":");
        if (cut > 0) {
          const k = el("span", "k"), v = el("span", "v");
          k.textContent = String(line).slice(0, cut).trim();
          v.textContent = String(line).slice(cut + 1).trim();
          row.append(k, v);
        } else {
          row.textContent = String(line);
        }
        box.appendChild(row);
      });
      return box;
    },

    versus(p) {
      const box = el("div", "versus");
      if (p.label) {
        const lbl = el("div", "vs-label");
        lbl.textContent = String(p.label);
        box.appendChild(lbl);
      }
      const left = Number(p.left_value) || 0;
      const right = Number(p.right_value) || 0;
      // Barres relatives au meilleur des deux : l'écart se lit d'un coup d'œil.
      const top = Math.max(left, right, 1);
      [[p.left_name, left], [p.right_name, right]].forEach(([name, value], i) => {
        const row = el("div", value >= Math.max(left, right) ? "vs-row lead" : "vs-row");
        row.style.setProperty("--i", String(i));
        const head = el("div", "row");
        const n = el("span", ""), v = el("span", "");
        n.textContent = String(name || "?");
        v.textContent = value.toLocaleString("fr-FR");
        head.append(n, v);
        const bar = el("div", "bar");
        const fill = document.createElement("span");
        bar.appendChild(fill);
        row.append(head, bar);
        box.appendChild(row);
        requestAnimationFrame(() => {
          fill.style.width = `${Math.round((value / top) * 100)}%`;
        });
      });
      return box;
    },

    pinned(p) {
      const box = el("div", "pinned");
      const who = el("div", "who");
      who.textContent = String(p.author || "");
      const msg = el("div", "msg");
      msg.textContent = String(p.text || "");
      box.append(who, msg);
      return box;
    },
  };

  function el(tag, className) {
    const n = document.createElement(tag);
    n.className = className;
    return n;
  }

  function faceEl(className, label) {
    const n = el("div", className);
    n.textContent = label;
    return n;
  }

  function updatePoll(box, p) {
    const tally = Array.isArray(p.tally) ? p.tally : [];
    const total = tally.reduce((a, b) => a + b, 0) || 0;
    const winner = Number.isInteger(p.winner) ? p.winner : -1;
    const left = box.querySelector(".q .left");
    if (left) left.textContent = p.seconds > 0 ? `${p.seconds}s` : "terminé";
    if (p.final) box.classList.add("final");

    box.querySelectorAll(".opt").forEach((opt, i) => {
      const votes = tally[i] || 0;
      const pct = total ? Math.round((votes / total) * 100) : 0;
      const count = opt.querySelector(".count");
      const next = total ? `${pct}% (${votes})` : (p.final ? "0" : "—");
      if (count && count.textContent !== next) {
        count.textContent = next;
        // Petit à-coup sur le chiffre qui change : on voit QUI vient de prendre
        // un vote, sans relire tout le tableau.
        count.classList.remove("bump");
        void count.offsetWidth;
        count.classList.add("bump");
      }
      // La largeur est animée par CSS : la barre glisse au lieu de sauter.
      const fill = opt.querySelector(".bar span");
      if (fill) requestAnimationFrame(() => { fill.style.width = `${pct}%`; });
      opt.classList.toggle("win", i === winner);
      opt.classList.toggle("lose", winner >= 0 && i !== winner);
    });
  }

  function clearWidgets() {
    // Un compte à rebours remplacé doit voir son timer coupé, sinon il continue
    // de tourner dans le vide pendant tout le live.
    widgets.querySelectorAll("[data-interval]").forEach((n) => {
      clearInterval(Number(n.dataset.interval));
    });
    widgets.replaceChildren();
    document.body.classList.remove("widget-on");
  }

  function showWidget(kind, params) {
    const build = BUILDERS[kind];
    if (!build) return;
    clearTimeout(widgetTimer);

    // Un sondage déjà affiché est mis à jour en place : le refaire apparaître à
    // chaque vote rejouerait l'animation d'entrée et clignoterait.
    const current = widgets.firstElementChild;
    const poll = current && current.dataset.kind === "poll"
      ? current.querySelector(".poll") : null;
    if (kind === "poll" && poll) {
      // Mutation en place : reconstruire relancerait la cascade d'entrée et
      // ferait repartir chaque barre de zéro à chaque vote.
      updatePoll(poll, params);
    } else {
      clearWidgets();
      const box = el("div", "widget");
      box.dataset.kind = kind;
      box.appendChild(build(params));
      widgets.replaceChildren(box);
      void box.offsetWidth;
      box.classList.add("visible");
    }
    const box = widgets.firstElementChild;
    // Après clearWidgets(), qui la retire : l'avatar s'efface, le widget prend
    // sa place.
    document.body.classList.add("widget-on");

    // Le serveur décide (animation + lecture) ; ce plafond n'est qu'un garde-fou.
    const seconds = Math.min(30, Math.max(2, Number(params.duration) || 12));
    widgetTimer = setTimeout(() => {
      box.classList.remove("visible");
      setTimeout(clearWidgets, 300);
    }, seconds * 1000);
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

  connect("/api/public/sse/overlay", (d) => {
    stage.classList.toggle("hidden", d.visible === false);
  });

  connect("/api/public/sse/overlay-feed", (event) => {
    switch (event.type) {
      case "bubble":   say(event.text, event.mode, event.duration); break;
      case "thinking": showThinking(event.active); break;
      case "react":    react(); break;
      case "widget":   showWidget(event.kind, event.params || {}); break;
    }
  });

  // ── Mise à jour automatique ──────────────────────────────────────────────
  // OBS garde sa page en mémoire des heures : sans ça, il faut penser à
  // rafraîchir la source à chaque changement. On compare une empreinte du
  // contenu servi et on recharge quand elle bouge. Basée sur le CONTENU, donc
  // un simple redémarrage du bot ne provoque aucun rechargement.
  const VERSION_POLL_MS = 30000;
  let knownVersion = null;

  async function checkVersion() {
    try {
      const r = await fetch("/api/public/overlay-version", { cache: "no-store" });
      if (!r.ok) return;
      const { version } = await r.json();
      if (!version) return;
      if (knownVersion && version !== knownVersion) location.reload();
      knownVersion = version;
    } catch { /* hors ligne : on retentera au prochain tour */ }
  }

  checkVersion();
  setInterval(checkVersion, VERSION_POLL_MS);

  // ── Instrumentation ──────────────────────────────────────────────────────
  // Impossible de lire l'usage GPU depuis une page (la Compute Pressure API ne
  // couvre que le CPU, et n'est pas disponible dans le CEF d'OBS). On mesure
  // donc ce qu'on peut : le coût de rendu de l'overlay lui-même. Sert de base de
  // comparaison AVANT l'ajout de l'avatar Rive.
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
