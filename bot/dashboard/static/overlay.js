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
  const RECONNECT_MAX_MS = 60000;   // plafond du backoff de reconnexion

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

  let reactTimer = null;
  function react() {
    // Le timer du premier `react` retirait la classe du second en plein vol.
    clearTimeout(reactTimer);
    slot.classList.remove("reacting");
    void slot.offsetWidth;
    slot.classList.add("reacting");
    reactTimer = setTimeout(() => slot.classList.remove("reacting"), 1000);
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

    // Compte à rebours en anneau segmenté : les tirets s'éteignent un à un
    // dans le sens horaire, le temps reste lisible au centre. Un simple chiffre
    // ne disait pas d'un coup d'œil s'il restait beaucoup ou presque rien.
    countdown(p) {
      const SEGMENTS = 60;
      const total = Math.min(600, Math.max(1, parseInt(p.seconds, 10) || 10));
      const node = el("div", "countdown");

      const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
      svg.setAttribute("viewBox", "0 0 140 140");
      svg.setAttribute("class", "cd-ring");

      // Couleur figée à la construction : elle ne dépend que de la POSITION du
      // tiret, pas du temps. Les recalculer à chaque tick ferait 60 écritures
      // de style dix fois par seconde, sur la machine qui encode le live.
      const segs = [];
      for (let i = 0; i < SEGMENTS; i++) {
        const angle = (i / SEGMENTS) * 2 * Math.PI - Math.PI / 2;  // départ en haut
        const seg = document.createElementNS("http://www.w3.org/2000/svg", "line");
        seg.setAttribute("x1", (70 + Math.cos(angle) * 50).toFixed(2));
        seg.setAttribute("y1", (70 + Math.sin(angle) * 50).toFixed(2));
        seg.setAttribute("x2", (70 + Math.cos(angle) * 62).toFixed(2));
        seg.setAttribute("y2", (70 + Math.sin(angle) * 62).toFixed(2));
        seg.setAttribute("class", "cd-seg");
        // Ambre → rouge le long de l'anneau : la fin de course se voit venir.
        const t = i / (SEGMENTS - 1);
        seg.style.setProperty(
          "--on",
          `rgb(${Math.round(245 + (239 - 245) * t)}, ${Math.round(158 + (68 - 158) * t)}, ${Math.round(11 + (68 - 11) * t)})`,
        );
        svg.appendChild(seg);
        segs.push(seg);
      }
      node.appendChild(svg);

      const time = el("div", "cd-time");
      node.appendChild(time);

      // Temps calculé depuis l'origine plutôt que décrémenté : un onglet
      // ralenti ou une frame sautée ferait dériver un compteur qui se
      // soustrait, et le zéro n'arriverait jamais au bon moment.
      const startedAt = performance.now();
      let shownSecond = -1;

      const render = () => {
        const left = Math.max(0, total - (performance.now() - startedAt) / 1000);
        const lit = Math.ceil((left / total) * SEGMENTS);
        segs.forEach((seg, i) => seg.classList.toggle("on", i < lit));
        const whole = Math.ceil(left);
        if (whole !== shownSecond) {
          shownSecond = whole;
          const m = Math.floor(whole / 60);
          time.textContent = `${String(m).padStart(2, "0")}:${String(whole % 60).padStart(2, "0")}`;
          time.classList.remove("tick");
          void time.offsetWidth;
          time.classList.add("tick");
        }
        return left;
      };
      render();

      // 10 Hz : l'anneau s'éteint tiret par tiret au lieu de sauter de six
      // d'un coup à chaque seconde. Seules des classes changent.
      const id = setInterval(() => {
        if (render() > 0) return;
        clearInterval(id);
        segs.forEach((seg) => seg.classList.remove("on"));
        time.textContent = String(p.done || "0");
        node.classList.add("done");
      }, 100);
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

    talkers(p) {
      const box = el("div", "talkers");
      const title = el("div", "talkers-title");
      title.textContent = "Les plus bavards";
      box.appendChild(title);
      (Array.isArray(p.rows) ? p.rows : []).forEach((r, i) => {
        const row = el("div", `talker rank${i + 1}`);
        row.style.setProperty("--i", String(i));
        const pos = el("span", "pos");
        pos.textContent = ["🥇", "🥈", "🥉"][i] || `${i + 1}.`;
        const name = el("span", "who");
        name.textContent = String(r.name || "");
        const n = el("span", "n");
        n.textContent = String(r.count || 0);
        row.append(pos, name, n);
        box.appendChild(row);
      });
      return box;
    },

    clip(p) {
      const box = el("div", "clip");

      // Avec une URL d'embed, on JOUE le clip ; sinon on retombe sur la carte.
      // Le repli n'est pas décoratif : Twitch exige que `parent` corresponde au
      // domaine hôte, donc l'iframe est refusée si l'overlay est ouvert par une
      // IP locale. Mieux vaut la carte que la vidéo noire.
      //
      // `parent` vient de `location.hostname` et non d'une constante : c'est le
      // navigateur qui sait sur quel domaine il tourne, et heywally.fr comme
      // localhost marchent alors sans rien configurer.
      // 1. Le fichier vidéo : le SEUL mode qui démarre tout seul. Une balise
      //    <video muted autoplay> n'est jamais bloquée, alors que le player
      //    Twitch en iframe refuse l'autoplay dans un overlay.
      const video = String(p.video || "");
      if (/^https:\/\/[^/]+\.(cloudfront\.net|twitch\.tv|twitchcdn\.net)\//.test(video)) {
        box.classList.add("playing");
        const v = document.createElement("video");
        v.src = video;
        v.className = "clip-video";
        v.muted = true;          // propriété ET attribut : Safari/CEF exigent
        v.setAttribute("muted", "");
        v.autoplay = true;
        v.playsInline = true;
        // Une lecture refusée ne doit pas laisser un cadre noir muet.
        v.addEventListener("error", () => box.classList.add("clip-failed"));
        const who = el("div", "clip-credit");
        who.textContent = `✂ ${p.title || "un clip"} — ${p.author || "quelqu'un"}`;
        box.append(v, who);
        // `play()` explicite en plus de l'attribut : dans le CEF d'OBS, la
        // lecture automatique par attribut seul est parfois ignorée.
        v.play?.().catch(() => { /* muet : ne devrait pas arriver */ });
        return box;
      }

      // 2. Le player officiel. Il s'affiche mais attend un clic — filet si
      //    l'URL du fichier n'a pas pu être obtenue.
      //
      // Twitch REFUSE un `parent` qui n'est pas un nom de domaine (une IP est
      // rejetée, `localhost` est accepté). On le vérifie AVANT de monter
      // l'iframe : sinon le viewer voit la page d'erreur de Twitch en plein
      // live, là où la carte aurait fait le travail.
      const host = location.hostname;
      const hostOk = host === "localhost"
        || (host.includes(".") && !/^[\d.]+$/.test(host));

      const embed = String(p.embed || "");
      if (hostOk && embed.startsWith("https://clips.twitch.tv/embed?")) {
        box.classList.add("playing");
        const slot = el("div", "clip-frame");     // réserve la place, 16:9
        const who = el("div", "clip-credit");
        who.textContent = `✂ ${p.title || "un clip"} — ${p.author || "quelqu'un"}`;
        box.append(slot, who);

        // L'iframe n'est montée QU'APRÈS l'apparition du widget. Les widgets
        // entrent en fondu (`.widget { opacity: 0 }`), et Twitch refuse
        // l'autoplay quand le lecteur n'est pas visible au chargement :
        //   « Autoplay disabled. The following minimum requirements for
        //     autoplay were not met: style visibility. »
        // Créée trop tôt, la vidéo restait donc figée sur sa première image.
        setTimeout(() => {
          if (!slot.isConnected) return;          // widget déjà retiré
          // Le `transform` du widget parent (translateY + scale, posé pour
          // l'animation d'entrée) fait échouer la détection de visibilité de
          // Twitch, qui refuse alors l'autoplay — un faux positif connu, cf.
          // twitchdev/issues#1127. On le retire une fois l'entrée jouée : le
          // clip reste animé à l'apparition, et il démarre.
          const holder = slot.closest(".widget");
          if (holder) holder.style.transform = "none";
          const frame = document.createElement("iframe");
          // muted=true : c'est le choix produit (pas de doublon audio sur le
          // stream), et accessoirement la seule façon dont l'autoplay est
          // accepté sans interaction de l'utilisateur.
          frame.src = `${embed}&parent=${encodeURIComponent(location.hostname)}`
            + "&autoplay=true&muted=true";
          frame.allow = "autoplay";
          frame.setAttribute("scrolling", "no");
          frame.setAttribute("frameborder", "0");
          slot.replaceChildren(frame);
        }, 400);                                   // > la transition de .28 s
        return box;
      }

      const head = el("div", "clip-head");
      head.textContent = "✂ nouveau clip";
      const title = el("div", "clip-title");
      title.textContent = String(p.title || "");
      const who = el("div", "clip-author");
      who.textContent = `par ${p.author || "quelqu'un"}`;
      box.append(head, title, who);
      return box;
    },

    raid(p) {
      // Le moment le plus fort d'un live : des inconnus débarquent d'un coup.
      // Le NOM domine la carte — c'est quelqu'un qu'on remercie, pas un compteur.
      const box = el("div", "raid");
      const tag = el("div", "raid-tag");
      tag.textContent = "RAID";
      const nom = el("div", "raid-name");
      const raider = String(p.raider || "").trim();
      nom.textContent = raider ? `Merci ${raider} !` : "On se fait raid !";
      box.append(tag, nom);

      // Twitch peut annoncer un raid sans compte fiable : plutôt rien qu'un
      // « 0 spectateur » qui sonne comme un échec.
      const n = Number(p.viewers) || 0;
      if (n > 0) {
        const compte = el("div", "raid-count");
        compte.textContent = n > 1
          ? `${n} personnes débarquent` : "une personne débarque";
        box.appendChild(compte);
      }
      return box;
    },

    wave(p) {
      // Le chat spamme : l'emote arrive en grand, une fois. Pas de compteur —
      // le nombre n'ajoute rien, c'est le déferlement qu'on montre.
      const box = el("div", "wave");
      const big = el("div", "wave-emote");
      big.textContent = String(p.emote || "");
      const label = el("div", "wave-label");
      label.textContent = "le chat s'emballe";
      box.append(big, label);
      return box;
    },

    quote(p) {
      const box = el("div", "quote");
      const mark = el("div", "quote-mark");
      mark.textContent = "\u201C";      // guillemet ouvrant, purement décoratif
      const text = el("div", "quote-text");
      text.textContent = String(p.text || "");
      const who = el("div", "quote-author");
      who.textContent = p.age ? `— ${p.author}, ${p.age}` : `— ${p.author}`;
      box.append(mark, text, who);
      return box;
    },

    hangman(p) {
      const box = el("div", `hangman${p.won ? " won" : p.lost ? " lost" : ""}`);

      // Potence + pendu : les six membres apparaissent un par un, dessinés en
      // SVG. Chaque trait ajouté se trace (stroke-dashoffset) au lieu de
      // surgir — c'est ce qui rend la faute lisible sans texte.
      const misses = Math.max(0, Math.min(6, Number(p.misses) || 0));
      const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
      svg.setAttribute("viewBox", "0 0 120 130");
      svg.setAttribute("class", "gallows");
      const line = (x1, y1, x2, y2, cls) => {
        const l = document.createElementNS("http://www.w3.org/2000/svg", "line");
        l.setAttribute("x1", x1); l.setAttribute("y1", y1);
        l.setAttribute("x2", x2); l.setAttribute("y2", y2);
        if (cls) l.setAttribute("class", cls);
        return l;
      };
      // La potence est toujours là : c'est le décor, pas une faute.
      [[10,125,70,125],[30,125,30,10],[30,10,85,10],[85,10,85,26]]
        .forEach(([a,b,c,d]) => svg.appendChild(line(a,b,c,d,"post")));
      const parts = [];
      const head = document.createElementNS("http://www.w3.org/2000/svg", "circle");
      head.setAttribute("cx", 85); head.setAttribute("cy", 38);
      head.setAttribute("r", 12); head.setAttribute("class", "part");
      parts.push(head);
      parts.push(line(85, 50, 85, 85, "part"));    // corps
      parts.push(line(85, 58, 68, 74, "part"));    // bras gauche
      parts.push(line(85, 58, 102, 74, "part"));   // bras droit
      parts.push(line(85, 85, 70, 108, "part"));   // jambe gauche
      parts.push(line(85, 85, 100, 108, "part"));  // jambe droite
      parts.slice(0, misses).forEach((n, i) => {
        n.style.setProperty("--i", String(i));
        svg.appendChild(n);
      });
      box.appendChild(svg);

      const right = el("div", "hangman-side");
      if (p.hint) {
        const hint = el("div", "hangman-hint");
        hint.textContent = String(p.hint);
        right.appendChild(hint);
      }
      const word = el("div", "hangman-word");
      (Array.isArray(p.mask) ? p.mask : []).forEach((c, i) => {
        const slot = el("span", c ? "slot filled" : "slot");
        slot.textContent = c || "";
        slot.style.setProperty("--i", String(i));
        word.appendChild(slot);
      });
      right.appendChild(word);

      const missed = Array.isArray(p.missed) ? p.missed : [];
      if (missed.length) {
        const bad = el("div", "hangman-missed");
        bad.textContent = missed.join(" ").toUpperCase();
        right.appendChild(bad);
      }
      if (p.won || p.lost) {
        const verdict = el("div", "hangman-verdict");
        verdict.textContent = p.won ? "trouvé !" : `raté — c'était « ${p.word} »`;
        right.appendChild(verdict);
      } else {
        const help = el("div", "hangman-help");
        help.textContent = "proposez une lettre dans le chat";
        right.appendChild(help);
      }
      box.appendChild(right);
      return box;
    },

    rps(p) {
      // Un duel, tranché d'un coup : plus de phase de vote. Le serveur envoie
      // les deux coups déjà tirés — le navigateur ne fait que les jouer.
      const HANDS = { pierre: "✊", feuille: "✋", ciseaux: "✌️" };
      const box = el("div", "rps");

      const title = el("div", "rps-title");
      title.textContent = "Chifoumi";
      box.appendChild(title);

      const duel = el("div", "rps-duel");
      // Les deux mains « secouent » puis se figent sur le coup joué : c'est le
      // geste du vrai jeu, sans lui le résultat tombe sans suspense.
      const side = (who, move, label) => {
        const c = el("div", `rps-side ${who}`);
        const hand = el("div", "rps-hand");
        hand.textContent = HANDS[move] || "✊";
        const name = el("div", "rps-name");
        name.textContent = label;
        c.append(hand, name);
        return c;
      };
      const adversaire = String(p.opponent || "le chat");
      duel.append(side("opponent", p.theirs, adversaire),
                  el("div", "rps-vs"),
                  side("wally", p.mine, "Wally"));
      duel.querySelector(".rps-vs").textContent = "VS";
      box.appendChild(duel);

      const verdict = el("div", "rps-verdict");
      verdict.textContent =
        p.outcome === "draw" ? "égalité"
        : p.outcome === "opponent" ? `${adversaire} gagne`
        : "Wally gagne";
      box.classList.add(p.outcome || "draw");
      box.appendChild(verdict);
      return box;
    },

    meme(p) {
      const box = el("div", "meme");
      const img = document.createElement("img");
      img.src = String(p.src || "");
      img.alt = "";
      box.appendChild(img);
      if (p.caption) {
        const cap = el("div", "meme-cap");
        cap.textContent = String(p.caption);
        box.appendChild(cap);
      }
      return box;
    },

    prediction(p) {
      const done = p.outcome === "right" || p.outcome === "wrong";
      const box = el("div", done ? `prediction ${p.outcome}` : "prediction");
      const head = el("div", "pred-head");
      head.textContent = done
        ? (p.outcome === "right" ? "Wally avait raison" : "Wally s'est planté")
        : "Wally parie";
      const bet = el("div", "pred-bet");
      bet.textContent = String(p.bet || "");
      box.append(head, bet);
      // Le score cumulé fait tout l'intérêt : un pari isolé n'amuse personne.
      if (Number(p.total) > 0) {
        const score = el("div", "pred-score");
        score.textContent = `${p.right} / ${p.total}`;
        box.appendChild(score);
      }
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
      // Égalité parfaite : personne ne mène. `value >= Math.max(...)` marquait
      // les DEUX camps gagnants, ce qui ne veut rien dire à l'écran.
      const lead = left === right ? null : (left > right ? 0 : 1);
      [[p.left_name, left], [p.right_name, right]].forEach(([name, value], i) => {
        const row = el("div", i === lead ? "vs-row lead" : "vs-row");
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

    // Podium des clips les plus vus. Pas de vidéo : c'est un tableau qu'on lit,
    // et enchaîner cinq clips monopoliserait l'écran plusieurs minutes.
    clip_top(p) {
      const box = el("div", "stats cliptop");
      const who = el("div", "who");
      who.textContent = "Clips les plus vus";
      box.appendChild(who);
      (p.rows || []).forEach((row, i) => {
        const line = el("div", "line");
        line.style.setProperty("--i", String(i));
        const k = el("span", "k");
        k.textContent = `${i + 1}. ${row.title}`;
        const v = el("span", "v");
        v.textContent = `${Number(row.views || 0).toLocaleString("fr-FR")} vues`;
        line.append(k, v);
        const by = el("div", "cliptop-by");
        by.textContent = `par ${row.author}`;
        const wrap = el("div", "cliptop-row");
        wrap.append(line, by);
        box.appendChild(wrap);
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

  // Les panneaux Apex vivent dans `overlay_apex.js`, chargé AVANT ce fichier.
  // Dans l'autre ordre la fusion lirait `undefined` en silence, et « wally
  // affiche mon rang » ne montrerait rien sans la moindre erreur en console.
  Object.assign(BUILDERS, window.APEX_BUILDERS || {});

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

  // File d'attente : deux demandes rapprochées se remplaçaient, la seconde
  // n'était jamais vue. Elles se jouent maintenant l'une après l'autre.
  const pending = [];
  const QUEUE_MAX = 5;          // au-delà, on abandonne les plus anciennes
  const QUEUE_STALE_MS = 60000; // un dé lancé il y a une minute n'intéresse plus

  function showWidget(kind, params) {
    const build = BUILDERS[kind];
    if (!build) return;

    const current = widgets.firstElementChild;
    // Même nature que le widget affiché : c'est une MISE À JOUR (un vote de
    // sondage, une case de bingo, le verdict d'un pari), pas une nouvelle
    // demande — l'empiler la ferait arriver après coup, sur un widget disparu.
    const isUpdate = current && current.dataset.kind === kind;
    if (current && !isUpdate) {
      if (pending.length >= QUEUE_MAX) pending.shift();
      pending.push({ kind, params, at: Date.now() });
      return;
    }
    renderWidget(kind, params, build);
  }

  function playNext() {
    const now = Date.now();
    while (pending.length) {
      const next = pending.shift();
      if (now - next.at > QUEUE_STALE_MS) continue;   // périmée : on passe
      renderWidget(next.kind, next.params, BUILDERS[next.kind]);
      return;
    }
  }

  // Tout retirer de l'écran, sur ordre du serveur (`cancel_overlay`).
  //
  // Déclarée APRÈS `pending` à dessein : la lire avant sa déclaration lèverait
  // une TDZ, que `node --check` ne détecte pas (cf. l'incident buildSections).
  //
  // La file d'attente est vidée AUSSI : sans ça, la demande qui patientait
  // derrière surgissait 300 ms après l'annulation — on annulait un meme et le
  // dé qui attendait son tour prenait sa place. La bulle part avec le reste :
  // « enlève ce qui est affiché » vise ce qu'on lit, pas seulement le widget.
  function clearAll() {
    pending.length = 0;
    clearTimeout(widgetTimer);
    hideBubble();
    showThinking(false);
    const box = widgets.firstElementChild;
    if (!box) { clearWidgets(); return; }
    box.classList.remove("visible");
    widgetTimer = setTimeout(clearWidgets, 300);   // le temps de la sortie animée
  }

  // Les couleurs de l'overlay, pas celles de la fête foraine : le violet des
  // accents et le cyan, plus un or qui accroche l'œil sur une image de jeu.
  const CONFETTI_COLORS = ["#b79cff", "#06b6d4", "#ffd166", "#ffffff"];

  function burstConfetti(viewers) {
    // Absente si le fichier n'a pas été servi : un overlay sans confettis reste
    // un overlay, alors qu'une exception ici tuerait tout le rendu du widget.
    if (typeof window.confetti !== "function") return;

    // Un raid de 5 et un raid de 300, ce n'est pas le même moment — mais le
    // plafond compte autant : l'overlay tourne à côté du jeu et de l'encodage.
    const n = Math.max(0, Number(viewers) || 0);
    const count = Math.round(60 + Math.min(n, 200) * 0.7);   // 60 → 200

    // Deux canons depuis les bas-côtés : les particules montent en croisant
    // l'écran. Tirer du centre les ferait retomber sur la carte et la masquer.
    for (const x of [0.1, 0.9]) {
      window.confetti({
        particleCount: Math.round(count / 2),
        angle: x < 0.5 ? 60 : 120,
        spread: 62,
        startVelocity: 48,
        origin: { x, y: 0.95 },
        colors: CONFETTI_COLORS,
        disableForReducedMotion: false,
        scalar: 0.9,
        ticks: 220,          // ~3,5 s de vol : la carte en reste 10
      });
    }
  }

  function renderWidget(kind, params, build) {
    clearTimeout(widgetTimer);

    // Un sondage déjà affiché est mis à jour en place : le refaire apparaître à
    // chaque vote rejouerait l'animation d'entrée et clignoterait.
    const current = widgets.firstElementChild;
    const poll = current && current.dataset.kind === "poll"
      ? current.querySelector(".poll") : null;
    // Les widgets qui se RAFRAÎCHISSENT (un vote, une lettre, une case cochée)
    // rejouaient leur animation d'entrée à chaque mise à jour. Faute d'une
    // mutation en place pour chacun, on se contente de ne pas les faire
    // clignoter : on reconstruit sans relancer la cascade d'apparition.
    // Pas `rps` : un chifoumi est un affichage unique, deux duels de suite sont
    // deux animations. Le retenir ici privait le second de sa cascade d'entrée.
    const refresh = current && current.dataset.kind === kind
      && (kind === "bingo" || kind === "hangman");
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
      if (refresh) {
        box.classList.add("visible");   // déjà à l'écran : pas de réapparition
      } else {
        void box.offsetWidth;
        box.classList.add("visible");
      }
    }
    const box = widgets.firstElementChild;
    // Après clearWidgets(), qui la retire : l'avatar s'efface, le widget prend
    // sa place.
    document.body.classList.add("widget-on");

    // Les confettis vivent HORS du builder : ils ne sont pas un élément du
    // widget mais un effet plein écran, et ils doivent partir au moment exact
    // où la carte apparaît — pas à sa construction.
    if (kind === "raid" && !refresh) burstConfetti(params.viewers);

    // Une partie en cours ne s'efface pas toute seule : le pendu doit rester
    // sous les yeux du chat tant qu'on y joue. Un booléen plutôt qu'une durée
    // nulle — `Number(0) || 12` vaut 12, le piège serait invisible.
    if (params.sticky === true) return;

    // Le serveur décide (animation + lecture) ; ce plafond n'est qu'un garde-fou.
    // 180 s et non 30 : le serveur émet jusqu'à 124 s (sondage de 120 s + 4),
    // et un sondage de 60 s disparaissait de l'écran à mi-parcours, les viewers
    // n'ayant plus la question sous les yeux pour voter.
    const seconds = Math.min(180, Math.max(2, Number(params.duration) || 12));
    widgetTimer = setTimeout(() => {
      box.classList.remove("visible");
      // Suivi lui aussi : ce timer interne n'était annulé nulle part. Un vote
      // arrivant pendant les 300 ms de sortie reconstruisait le widget, puis le
      // nettoyage orphelin l'effaçait — et `playNext()` pouvait enchaîner sur
      // autre chose. Vaut pour bingo, hangman et poll.
      widgetTimer = setTimeout(() => {
        clearWidgets();
        playNext();       // la suivante prend le relais, si elle a tenu
      }, 300);
    }, seconds * 1000);
  }

  // ── Mise à jour automatique ──────────────────────────────────────────────
  // OBS garde sa page en mémoire des heures : sans ça, il faut penser à
  // rafraîchir la source à chaque changement. On compare une empreinte du
  // contenu servi et on recharge quand elle bouge. Basée sur le CONTENU, donc
  // un simple redémarrage du bot ne provoque aucun rechargement.
  //
  // Déclaré AVANT `connect()`, qui appelle `checkVersion()` : `knownVersion`
  // est un `let`, le lire plus haut lèverait une TDZ (cf. buildSections).
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

  // ── Flux SSE ─────────────────────────────────────────────────────────────
  function connect(url, onMessage) {
    let source;
    let delay = RECONNECT_MS;
    const open = () => {
      source = new EventSource(url);
      source.onmessage = (e) => {
        try { onMessage(JSON.parse(e.data)); } catch { /* keepalive ou bruit */ }
      };
      // Backoff : à intervalle fixe, un bot arrêté prenait 720 requêtes/heure et
      // par flux. Remis à zéro dès qu'un message arrive (donc que ça remarche).
      //
      // Et on vérifie la version TOUT DE SUITE : une reconnexion veut dire que
      // le serveur vient de revenir, donc le plus souvent qu'il a été
      // redéployé. Le sondage seul faisait attendre jusqu'à 30 s de plus après
      // une coupure d'une minute — on testait entre-temps, l'overlay tournait
      // encore sur l'ancien code, et il fallait le rafraîchir à la main.
      source.onopen = () => { delay = RECONNECT_MS; checkVersion(); };
      source.onerror = () => {
        source.close();
        setTimeout(open, delay);
        delay = Math.min(delay * 2, RECONNECT_MAX_MS);
      };
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
      case "clear":    clearAll(); break;
    }
  });


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

  // Lu UNE fois : le nom du GPU ne change jamais, et un contexte WebGL neuf
  // toutes les 10 s (~360 par live) finit par évincer les contextes vivants du
  // navigateur — Chrome en garde une quinzaine. Dans le CEF d'OBS, sur une
  // machine qui encode déjà, c'est du churn GPU gratuit.
  const GPU_NAME = (function () {
    try {
      const gl = document.createElement("canvas").getContext("webgl");
      if (!gl) return "inconnu";
      const ext = gl.getExtension("WEBGL_debug_renderer_info");
      const name = ext ? gl.getParameter(ext.UNMASKED_RENDERER_WEBGL) : "inconnu";
      // Rendre le contexte tout de suite : il ne resservira pas.
      gl.getExtension("WEBGL_lose_context")?.loseContext();
      return name;
    } catch { return "inconnu"; }
  })();

  setInterval(() => {
    const fps = perf.frames / 10;
    fetch("/api/public/overlay-health", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        fps: Math.round(fps),
        worst_frame_ms: Math.round(perf.worstFrame),
        gpu: GPU_NAME,
      }),
      keepalive: true,
    }).catch(() => { /* le diagnostic ne doit jamais gêner l'affichage */ });
    perf.frames = 0;
    perf.worstFrame = 0;
  }, 10000);
})();
