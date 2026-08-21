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
  // Le texte vit dans un enfant : c'est LUI qui porte le garde-fou
  // anti-débordement. Posé sur la bulle, il rognerait sa queue.
  const bubbleText = document.getElementById("bubble-text");

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
  // Déclarés ensemble et AVANT leurs lecteurs : un `let` lu avant sa ligne de
  // déclaration lève une TDZ, que `node --check` ne détecte pas.
  let hideTimer = null;
  let sayTimer = null;

  function showBubble(node, mode) {
    clearTimeout(hideTimer);
    clearTimeout(sayTimer);
    // Par `classList` et non par `className` : la bulle porte aussi
    // `sans-pointe`, posé par `overlay_layout.js` quand l'avatar est masqué
    // dans la scène. Une réaffectation entière l'effacerait à la première
    // réplique, et la pointe se remettrait à viser le vide.
    bubble.classList.remove("visible", "speech", "thought");
    bubble.classList.add(mode === "thought" ? "thought" : "speech");
    bubbleText.replaceChildren(node);
    // Force un reflow pour que la transition reparte même sur deux bulles
    // consécutives.
    void bubble.offsetWidth;
    bubble.classList.add("visible");
  }

  function hideBubble() {
    clearTimeout(sayTimer);
    bubble.classList.remove("visible");
  }

  // Sortie parasitée : la MÊME rafale que le rotateur de memes, qui s'affiche
  // sur le même stream. Cinq états à 30 ms — plus court que les sept du
  // rotateur : une bulle part toutes les quelques secondes, une transition de
  // meme toutes les quinze.
  const GLITCH = { etats: 5, saccade: 30, decalage: 14 };
  const GLITCH_MS = GLITCH.etats * GLITCH.saccade;

  // ── Les réglages de rythme de la scène ───────────────────────────────────
  //
  // Les widgets dont la sortie est décidée par leur PROPRE mécanique, et que la
  // durée réglée dans la scène ne doit donc pas piloter :
  //   · `clip` sort sur la fin de la vidéo (`video.duration + 5`) — une durée
  //     posée par-dessus couperait le clip au milieu ;
  //   · `virus_popup` reçoit sa durée en ENTRÉE d'un plan de fenêtres calculé
  //     (`WallyVirus.rythme` → `fenetres`) : elle y est déjà remplacée, plus
  //     bas, et un second minuteur ferait tomber l'écran bleu de nettoyage à
  //     côté de son plan.
  const DUREE_INTERNE = new Set(["clip", "virus_popup"]);

  /** Pose une animation d'`animate.css` sur un nœud.
   *
   *  Sa sœur `animDe()`, qui lit les réglages de la scène, est déclarée avec
   *  `estSolo`/`masqueWally` — les trois lisent `reglages`, et ce fichier les
   *  garde groupées sous sa déclaration.
   *
   *  `glitch` et `aucune` ne sont pas des classes : le premier est la rafale
   *  maison (jouée ailleurs), le second ne fait rien. Les traiter ici évite à
   *  chaque appelant de répéter la condition.
   */
  function animer(noeud, nom, ms, boucle) {
    if (!noeud || nom === "aucune" || nom === "glitch") return;
    noeud.style.setProperty("--animate-duration", (ms / 1000) + "s");
    noeud.classList.add("animate__animated", "animate__" + nom);
    if (boucle) noeud.classList.add("animate__infinite");
  }

  /** La bulle part en glitch.
   *
   *  `nettoyer` est indispensable : la rafale écrit les quatre propriétés EN
   *  LIGNE, où elles l'emportent sur la feuille de style. Sans ce ménage, la
   *  bulle suivante naîtrait décalée, filtrée, à moitié transparente.
   */
  function popBubble() {
    if (!bubble.classList.contains("visible")) return;
    WallyGlitch.rafale(bubble, GLITCH).then(() => {
      WallyGlitch.nettoyer(bubble);
      hideBubble();
    });
  }

  // Wally accuse le coup quand il parle. Sur `say` seulement, pas sur les trois
  // points : il hoche la tête en prenant la parole, pas en réfléchissant.
  let nodTimer = null;
  function nod() {
    // Un raid en cours l'emporte : on ne coupe pas une réaction ample pour un
    // hochement.
    if (slot.classList.contains("reacting")) return;
    clearTimeout(nodTimer);
    slot.classList.remove("speaking");
    void slot.offsetWidth;                      // relance l'animation
    slot.classList.add("speaking");
    nodTimer = setTimeout(() => slot.classList.remove("speaking"), 500);
  }

  function say(text, mode, durationSeconds) {
    // Wally bouge D'ABORD, la bulle suit 90 ms plus tard. Simultanés, les deux
    // ne sont qu'une coïncidence ; décalés, l'un devient la cause de l'autre.
    nod();
    clearTimeout(sayTimer);
    sayTimer = setTimeout(() => {
      // textContent via createTextNode : le texte vient du LLM, jamais
      // interprété comme du HTML.
      showBubble(document.createTextNode(text), mode);
      // Armé APRÈS `showBubble`, qui désarme `hideTimer` : posé avant, il
      // annulait le minuteur qu'on venait de poser et la bulle restait à
      // l'écran indéfiniment. Effet de bord du décalage de 90 ms.
      // La durée d'affichage part de l'apparition RÉELLE, ce qui est aussi
      // ce que le serveur a calculé.
      //
      // La durée réglée pour la bulle dans cette scène l'emporte sur celle-ci.
      // Zéro vaut « auto » : le repli de 3 s d'avant ce réglage, qui est la
      // valeur livrée — une bulle ne change donc de rythme que si on le lui
      // demande.
      const regleeBulle = Number((reglages.bubble || {}).duree) || 0;
      hideTimer = setTimeout(popBubble,
        (regleeBulle || Math.max(1, durationSeconds || 3)) * 1000);
    }, 90);
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

  // ── Palette ──────────────────────────────────────────────────────────────
  // Les couleurs vivent dans le `:root` du CSS, une seule fois. Les lire ici
  // plutôt que les redéclarer : la bague du compte à rebours interpolait entre
  // `rgb(245,158,11)` et `rgb(239,68,68)`, soit les deux mêmes couleurs que le
  // CSS, réécrites en chiffres — une retouche de palette en oubliait la moitié.
  const _tokens = {};
  function token(nom) {
    if (!(nom in _tokens)) {
      _tokens[nom] = getComputedStyle(document.documentElement)
        .getPropertyValue(`--${nom}`).trim();
    }
    return _tokens[nom];
  }
  /** Composantes d'un token, ou `null` s'il n'est pas un `#rrggbb`. */
  function tokenRGB(nom) {
    const m = /^#([0-9a-f]{6})$/i.exec(token(nom));
    return m ? [0, 2, 4].map((i) => parseInt(m[1].slice(i, i + 2), 16)) : null;
  }

  // ── Widgets ──────────────────────────────────────────────────────────────
  // Rendus en CSS 3D plutôt qu'avec un moteur : plus léger, et composé par le
  // GPU du streamer — qui fait déjà tourner le jeu et l'encodage.
  //
  // Chaque widget entre dans le conteneur de son `kind` (`[data-element]`), et
  // non plus dans un `#widgets` commun : c'est ce qui lui donne sa place, son
  // échelle et son empilement propres (`overlay_layout.js`). PLUSIEURS widgets
  // peuvent donc être à l'écran en même temps — c'est le sens du réglage `solo`
  // du modèle —, et les widgets en place se cherchent à travers tous les
  // conteneurs.
  const WIDGET_EN_PLACE = "[data-element] > .widget:not(.leaving)";
  const WIDGET_TOUS = "[data-element] > .widget";

  /** Le conteneur d'un `kind`, créé au besoin.
   *
   *  Un widget dont le conteneur manque ne s'afficherait NULLE PART, sans la
   *  moindre erreur — la panne la plus coûteuse de cet overlay. On en crée un
   *  plutôt que de perdre la carte en silence ; la console dit lequel manque au
   *  HTML, et un test Python le rattrape au dépôt.
   */
  function hoteWidget(kind) {
    let hote = document.querySelector(`[data-element="${kind}"]`);
    if (!hote) {
      console.error("overlay : aucun conteneur pour le widget", kind);
      hote = document.createElement("div");
      hote.dataset.element = kind;
      stage.appendChild(hote);
    }
    return hote;
  }

  // Un minuteur de disparition PAR `kind`, et non un minuteur unique : les
  // widgets cohabitent, ils partent donc chacun à leur heure. Avec un seul
  // minuteur, l'arrivée d'un widget annulait la sortie de celui d'à côté, qui
  // restait à l'écran pour tout le reste du live.
  const minuteurs = new Map();   // kind → id du minuteur de sortie
  // Ce qui ne vise aucun widget en particulier : le relais vers la demande
  // suivante, et le nettoyage différé d'une annulation.
  let relaisTimer = null;

  // Les valeurs publiées à l'apparition PRÉCÉDENTE du duel Apex, pour faire
  // tressaillir le seul chiffre qui vient de bouger (§11 de la spec du duel).
  //
  // Une mémoire de module, et non un rafraîchissement en place façon sondage :
  // le widget du duel n'est PAS `sticky`, il reparaît à chaque manche et le
  // cycle normal des widgets l'efface entre-temps. Au moment où le score
  // suivant arrive, il n'y a le plus souvent plus rien à l'écran à mettre à
  // jour — un rafraîchissement en place ne verrait donc jamais la différence,
  // là où cette mémoire la voit d'une manche à l'autre. Et c'est bien ce qu'on
  // veut : un duel dure une heure, ses apparitions doivent garder leur entrée.
  //
  // Déclaré AVANT `BUILDERS`, comme le reste des `let` du fichier : un `let`
  // lu avant sa ligne lève une TDZ, que `node --check` ne détecte pas.
  let duelPrecedent = null;

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
      // La coquille seulement : la roue est peinte dans un canvas par
      // spin-wheel, qui a besoin d'un conteneur DÉJÀ dans le DOM pour se
      // dimensionner. Le montage se fait donc dans `renderWidget`, une fois la
      // carte attachée — cf. `mountWheel`.
      const options = Array.isArray(p.options) ? p.options.slice(0, 8) : [];
      if (!options.length) return el("div", "");
      const box = el("div", "wheel-box");
      box.append(el("div", "wheel-canvas"), el("div", "pin"),
                 el("div", "label"));
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
        // Les deux bouts sortent de la palette ; si un token n'est pas un
        // `#rrggbb`, l'anneau reste d'une seule couleur plutôt que de virer au
        // gris — un dégradé raté doit se voir, pas se deviner.
        const t = i / (SEGMENTS - 1);
        const a = tokenRGB("wally"), b = tokenRGB("lose");
        seg.style.setProperty(
          "--on",
          a && b
            ? `rgb(${a.map((v, k) => Math.round(v + (b[k] - v) * t)).join(", ")})`
            : token("wally"),
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
      // `scaleX` et non `width` : composé par le GPU, pas de mise en page.
      requestAnimationFrame(() => { fill.style.transform = `scaleX(${pct / 100})`; });
      return box;
    },

    // Le sondage se met à jour à chaque vote : on le reconstruit en place plutôt
    // que de le faire réapparaître, pour ne pas rejouer l'animation d'entrée.
    poll(p) {
      const options = Array.isArray(p.options) ? p.options : [];
      const box = el("div", "poll");
      // Identité du sondage : `renderWidget` s'en sert pour distinguer une mise
      // à jour de votes d'un sondage entièrement nouveau.
      box.dataset.signature = JSON.stringify([String(p.question || ""), options]);

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
        // Les deux façons de jouer, dites à l'écran : le mot entier a été
        // ajouté le 2026-08-20, et une règle qu'on ne lit nulle part n'existe
        // pas pour le chat.
        help.textContent = "une lettre — ou le mot entier — dans le chat";
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
      // Les deux mains battent de haut en bas trois fois, ensemble, puis se
      // posent sur le coup joué : c'est le geste du vrai jeu, sans lui le
      // résultat tombe sans suspense. Le détail est dans `@keyframes rps-throw`.
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
      // L'image seule, sans légende : la description d'un meme sert à Wally
      // pour le commenter, elle n'est pas destinée aux spectateurs.
      const box = el("div", "meme");
      // La boîte vient de la table, jamais du CSS : c'est le chiffre que le
      // repère du panneau affiche, et il ne doit exister qu'à un endroit.
      const zone = window.WallyLayout && WallyLayout.taille("meme");
      if (zone) {
        box.style.setProperty("--meme-zone-l", zone[0] + "px");
        box.style.setProperty("--meme-zone-h", zone[1] + "px");
      }
      const img = document.createElement("img");
      img.src = String(p.src || "");
      img.alt = "";
      box.appendChild(img);
      return box;
    },

    planning(p) {
      // Une image fixe, sans légende : le planning se lit, il ne se commente
      // pas dans la carte — Wally a sa bulle pour ça.
      const box = el("div", "planning");
      const img = document.createElement("img");
      img.src = String(p.src || "");
      img.alt = "";
      box.appendChild(img);
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
      // `duel` marque une comparaison qui revient : le duel Apex se rejoue en
      // plusieurs apparitions. Une comparaison générique ne le passe pas et
      // garde exactement le rendu d'avant.
      const duel = p.duel === true;
      const final = duel && p.final === true;
      if (final) box.classList.add("final");
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
      const devant = left === right ? null : (left > right ? 0 : 1);
      // Tant que le duel COURT, personne n'est désigné vainqueur : c'est la
      // grammaire du sondage, dont aucune option n'est `win` avant la clôture.
      // Allumer la couleur de victoire dès la manche 1 la consomme pour toute
      // l'heure que dure le duel, et le verdict n'apporte plus rien à l'écran.
      // Hors duel, une comparaison est un instantané : son meneur reste coloré.
      const lead = (duel && !final) ? null : devant;
      const avant = duel ? duelPrecedent : null;
      if (duel) duelPrecedent = final ? null : [left, right];
      [[p.left_name, left], [p.right_name, right]].forEach(([name, value], i) => {
        const row = el("div", "vs-row");
        if (i === lead) row.classList.add("lead");
        else if (lead !== null) row.classList.add("lose");
        row.style.setProperty("--i", String(i));
        const head = el("div", "row");
        const n = el("span", ""), v = el("span", "count");
        n.textContent = String(name || "?");
        v.textContent = value.toLocaleString("fr-FR");
        // Le chiffre qui vient de bouger tressaille : on voit QUI vient de
        // faire un kill, sans relire les deux lignes. Uniquement à la hausse —
        // un score qui baisse est un duel qui recommence, pas un exploit.
        if (avant && value > avant[i]) v.classList.add("bump");
        head.append(n, v);
        row.appendChild(head);
        // Sous-titre optionnel (légende jouée, niveau du compte) — le duel s'en
        // sert, les appels génériques ne le passent pas et n'affichent rien.
        // Placé sous le nom/score, avant la barre : c'est une précision sur
        // le camp, pas une donnée qui doit peser sur la comparaison lue.
        const subs = [p.left_sub, p.right_sub];
        if (subs[i]) {
          const sub = el("div", "vs-sub");
          sub.textContent = String(subs[i]);
          row.appendChild(sub);
        }
        const bar = el("div", "bar");
        const fill = document.createElement("span");
        bar.appendChild(fill);
        row.appendChild(bar);
        box.appendChild(row);
        requestAnimationFrame(() => {
          fill.style.transform = `scaleX(${top ? value / top : 0})`;
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

    // Spam de popups « virus » — variante de l'avalanche, montée pour être
    // comparée à elle. Ici rien ne tombe : les fenêtres s'ouvrent de plus en
    // plus vite et RESTENT, jusqu'à l'écran bleu qui recouvre tout.
    //
    // Elles ne sont pas retirées une à une : au-delà du plafond, la PLUS
    // ANCIENNE se ferme — c'est le DOM qu'on borne, pas le spectacle, sinon le
    // dossier s'arrête au tiers.
    virus_popup(p) {
      const box = el("div", "virus-popup");
      // Stock relu avant de bâtir le plan : c'est lui qui décide combien de
      // fenêtres s'ouvrent, et le serveur a dimensionné la carte sur le dossier
      // tel qu'il est à cet instant.
      stockFrais((medias) => {
        if (!box.isConnected) return;
        // `p.seconds` porte DÉJÀ la durée réglée dans la scène quand il y en a
        // une : elle est posée en amont, dans `showWidget`, sur les deux champs
        // à la fois. Le builder n'a donc rien à savoir du modèle.
        const duree = Math.max(3, Math.min(300,
          Number(p.seconds) || window.WallyVirus.dureeSelonStock(medias.length)));
        lancerSpamVirus(box, medias, duree);
      });
      return box;
    },

    // Le morceau en cours, affiché quand quelqu'un demande dans le chat ce qui
    // passe. Il COHABITE : pas de `widget-on`, Wally reste à l'écran à côté.
    music_now(p) {
      const joue = !!p.playing;
      const box = el("div", "music-now" + (joue ? " joue" : ""));
      // Deux couches : `box` porte l'ombre, `pilule` porte le fond et la
      // découpe du déroulé. Sur un seul élément, le `clip-path` amputerait la
      // lueur colorée EN PERMANENCE (cf. le commentaire du style).
      const pilule = el("div", "music-pilule");

      // Le disque : la pochette montée sur un vinyle. Il tourne même sans
      // pochette — un morceau dont on n'a pas l'image reste un morceau, et un
      // vinyle nu vaut mieux qu'un trou dans la carte.
      const disque = el("div", "music-disque");
      const pochette = String(p.cover || "");
      if (pochette) {
        const img = el("img", "music-pochette");
        // `crossOrigin` posé AVANT `src`, et sur l'image AFFICHÉE plutôt que
        // sur une seconde copie : c'est elle qu'on relira au canvas pour en
        // tirer la couleur. Une image chargée en CORS et la même sans CORS sont
        // deux entrées de cache DISTINCTES — deux copies feraient télécharger
        // la pochette deux fois pour une seule à l'écran.
        img.crossOrigin = "anonymous";
        img.alt = "";
        img.addEventListener("load", () => teinterSelonPochette(box, img));
        // Une pochette qui ne charge pas ne laisse pas d'image cassée à
        // l'écran : le disque nu fait un vinyle très convenable.
        img.addEventListener("error", () => img.remove());
        img.src = pochette;
        disque.appendChild(img);
      }
      disque.append(el("div", "music-reflet"), el("div", "music-axe"));

      const texte = el("div", "music-texte");
      const etat = el("div", "music-etat");
      etat.textContent = joue ? "En lecture" : "En pause";
      const titre = el("div", "music-titre");
      titre.textContent = String(p.title || "");
      texte.append(etat, titre);
      // L'artiste SEULEMENT s'il y en a un : une ligne vide n'est pas neutre,
      // elle décale le titre vers le haut et creuse la carte sous lui.
      const nomArtiste = String(p.artist || "");
      if (nomArtiste) {
        const artiste = el("div", "music-artiste");
        artiste.textContent = nomArtiste;
        texte.appendChild(artiste);
      }

      // Cinq barres qui dansent : un équaliseur dit « ça joue » sans un mot, et
      // se fige quand c'est en pause — l'information est dans le mouvement.
      const note = el("div", "music-note");
      for (let i = 0; i < 5; i++) note.appendChild(el("i", ""));

      pilule.append(disque, texte, note);
      box.appendChild(pilule);
      return box;
    },

    // Bilan de fin de partie Apex : les kills de la game, et le cumul du live.
    // Il COHABITE — il s'installe le temps qu'on le lise pendant que la partie
    // suivante commence.
    apex_kills(p) {
      const box = el("div", "apex-kills");
      const chiffre = el("div", "ak-chiffre");
      chiffre.textContent = String(Number(p.kills) || 0);
      const droite = el("div", "ak-droite");
      const quoi = el("div", "ak-quoi");
      // Le pluriel se lit de loin : « 1 kill » et « 1 kills » n'ont pas le même
      // niveau de soin apparent, et c'est vu par tout le chat.
      quoi.textContent = (Number(p.kills) === 1 ? "kill" : "kills") + " cette game";
      const cumul = el("div", "ak-cumul");
      const parties = Number(p.games) || 0;
      cumul.textContent = `${Number(p.total) || 0} sur le live · ${parties} partie${parties > 1 ? "s" : ""}`;
      droite.append(quoi, cumul);
      box.append(chiffre, droite);
      // Les points de rang, SEULEMENT s'ils ont bougé : le serveur n'envoie
      // rien quand la partie n'était pas classée, et un « 0 RP » à l'écran
      // inventerait une partie classée blanche. Le signe porte la couleur —
      // vert on monte, rouge on descend, sans un mot de plus.
      const rp = Number(p.rp);
      if (Number.isFinite(rp) && rp !== 0) {
        const pastille = el("div", "ak-rp" + (rp > 0 ? " gagne" : " perd"));
        pastille.textContent = `${rp > 0 ? "+" : "−"}${Math.abs(rp)} RP`;
        box.append(pastille);
      }
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

  /* La couleur dominante d'une pochette, en `[r, v, b]`, ou `null`.
   *
   * Le tri se fait par TEINTE et non par couleur exacte : une pochette n'a
   * jamais deux fois le même pixel, mais elle a une famille de teintes, et
   * c'est celle-là qu'on cherche. Chaque pixel pèse sa saturation AU CARRÉ —
   * sans ça, le gris d'un fond, qui couvre les trois quarts d'une image, gagne
   * contre le rouge qui en fait l'identité. Les pixels presque noirs ou presque
   * blancs ne votent pas du tout : leur teinte n'est que du bruit d'arrondi.
   *
   * 48 × 48 : on cherche une ambiance, pas un détail. Lire la pochette en
   * pleine résolution coûterait cent fois plus pour la même réponse.
   */
  function couleurDominante(img) {
    const N = 48;
    const toile = document.createElement("canvas");
    toile.width = toile.height = N;
    const ctx = toile.getContext("2d", { willReadFrequently: true });
    if (!ctx) return null;
    ctx.drawImage(img, 0, 0, N, N);
    let pixels;
    try {
      pixels = ctx.getImageData(0, 0, N, N).data;
    } catch (e) {
      // Pochette servie sans en-tête CORS : la toile est « souillée » et sa
      // lecture lève. Ce n'est PAS une panne — c'est un hébergeur qui ne le
      // permet pas, et l'accent neutre de la carte prend le relais sans que
      // rien ne manque à l'écran.
      return null;
    }
    const paniers = new Map();       // teinte arrondie → poids cumulés
    for (let i = 0; i < pixels.length; i += 4) {
      const [t, sat, lum] = versTsl(pixels[i], pixels[i + 1], pixels[i + 2]);
      if (lum < 0.12 || lum > 0.94) continue;
      const cle = Math.round(t * 18);
      const poids = 0.25 + sat * sat * 2.2 * (1 - Math.abs(lum - 0.55));
      const panier = paniers.get(cle) || { p: 0, t: 0, s: 0, l: 0 };
      panier.p += poids;
      panier.t += t * poids;
      panier.s += sat * poids;
      panier.l += lum * poids;
      paniers.set(cle, panier);
    }
    let gagnant = null;
    paniers.forEach((panier) => {
      if (!gagnant || panier.p > gagnant.p) gagnant = panier;
    });
    if (!gagnant) return null;       // pochette entièrement noire ou blanche
    // Saturation et luminosité sont REMONTÉES dans une fourchette étroite : la
    // moyenne d'une pochette est toujours terne, et un accent terne sur du
    // gameplay ne se voit pas. La teinte, elle, n'est jamais touchée — c'est
    // elle qui fait reconnaître l'album.
    return versRvb(
      gagnant.t / gagnant.p,
      Math.max(0.62, Math.min(1, (gagnant.s / gagnant.p) * 1.35)),
      Math.max(0.5, Math.min(0.66, (gagnant.l / gagnant.p) * 1.15)),
    );
  }

  /* RVB (0–255) → TSL, chaque composante dans [0, 1]. */
  function versTsl(r, v, b) {
    r /= 255; v /= 255; b /= 255;
    const haut = Math.max(r, v, b), bas = Math.min(r, v, b);
    const lum = (haut + bas) / 2;
    if (haut === bas) return [0, 0, lum];   // gris : aucune teinte à lire
    const ecart = haut - bas;
    const sat = lum > 0.5 ? ecart / (2 - haut - bas) : ecart / (haut + bas);
    let t;
    if (haut === r) t = (v - b) / ecart + (v < b ? 6 : 0);
    else if (haut === v) t = (b - r) / ecart + 2;
    else t = (r - v) / ecart + 4;
    return [t / 6, sat, lum];
  }

  /* TSL → RVB (0–255). */
  function versRvb(t, s, l) {
    const a = s * Math.min(l, 1 - l);
    return [0, 8, 4].map((n) => {
      const k = (n + t * 12) % 12;
      return Math.round(255 * (l - a * Math.max(-1, Math.min(k - 3, 9 - k, 1))));
    });
  }

  /* Habille la carte aux couleurs du morceau, une fois sa pochette chargée.
   *
   * Les variables sont posées sur la CARTE et jamais sur `:root` : plusieurs
   * widgets peuvent être à l'écran en même temps, et une variable globale
   * survivrait au départ de celui-ci pour teinter le suivant.
   */
  function teinterSelonPochette(box, img) {
    const rgb = couleurDominante(img);
    if (!rgb) return;                // l'accent neutre de la carte reste en place
    const [r, v, b] = rgb;
    box.style.setProperty("--accent-morceau", `rgb(${r}, ${v}, ${b})`);
    // L'artiste prend la couleur en sourdine plutôt qu'un gris : c'est ce qui
    // fait tenir la carte ensemble au lieu d'un accent posé à un seul endroit.
    box.style.setProperty("--accent-doux", `rgba(${r}, ${v}, ${b}, .72)`);
    // La bordure prend la couleur elle aussi, mais très diluée : à pleine
    // opacité elle deviendrait un liseré fluo autour de la carte, alors que
    // c'en est le contour.
    box.style.setProperty("--bord-morceau", `rgba(${r}, ${v}, ${b}, .34)`);
    box.style.setProperty("--lueur-morceau", `rgba(${r}, ${v}, ${b}, .6)`);
  }

  /* Le dossier de memes, relu AVANT de lancer un spectacle qui le veut entier.
   *
   * « De nouveaux memes sont souvent ajoutés » (owner) : sans relecture, les
   * deux spectacles travaillent sur la liste chargée à l'ouverture de la page,
   * et un meme déposé pendant le live n'entre qu'au bout d'un cycle complet de
   * rotation. Le serveur, lui, relit le dossier à chaque déclenchement — c'est
   * son décompte qui fixe la durée, les deux doivent donc voir la même chose.
   *
   * Le rappel est TOUJOURS appelé, même si la relecture échoue : le réseau ne
   * doit pas décider s'il y a un spectacle ou non. On repart alors sur la
   * dernière liste connue.
   */
  function stockFrais(suite) {
    const rendre = () => suite((window.WallyRotationMedias || []).slice());
    const relire = window.WallyRotationRelire;
    if (typeof relire !== "function") { rendre(); return; }
    try {
      const p = relire();
      if (p && typeof p.then === "function") p.then(rendre, rendre);
      else rendre();
    } catch (e) { rendre(); }
  }

  /* Ouvre les fenêtres du spam sur la boîte reçue, de plus en plus vite, puis
   * l'écran bleu. Sortie du builder pour la même raison que l'avalanche : le
   * stock est relu avant de commencer. */
  function lancerSpamVirus(box, medias, duree) {
    const plan = window.WallyVirus.fenetres(window.WallyVirus.rythme(duree), medias);
    // Les sons sont relus ici pour la même raison que le stock de memes : le
    // dossier est bind-monté, l'owner y dépose un ding pendant le live, et la
    // page ne doit pas rester sur l'inventaire de son ouverture. Ce qui est
    // déjà décodé n'est pas retéléchargé — l'appel est donc sans frais.
    if (window.WallySons) window.WallySons.charger();
    // Un semeur par spectacle : il garde le fil des cellules déjà servies, et
    // c'est ce qui répartit les fenêtres sur tout l'écran au lieu du milieu.
    const semeur = window.WallyVirus.semeur(window.innerWidth || 1920,
                                            window.innerHeight || 1080);
    const timers = [];
    plan.forEach((f, i) => {
      timers.push(setTimeout(() => {
        if (!box.isConnected) return;
        box.appendChild(fenetreVirus(f, i, semeur));
        // Le ding accompagne l'OUVERTURE, pas la construction du nœud : c'est
        // ici qu'on sait que la fenêtre entre réellement à l'écran.
        if (window.WallySons) window.WallySons.popup();
        // Elles restent TOUTES : le plafond n'est plus qu'un filet, posé
        // au-dessus de ce que le dossier peut produire.
        const vivantes = box.querySelectorAll(".vwin");
        for (let k = 0; k < vivantes.length - window.WallyVirus.PLAFOND_VIVANTES; k++) {
          vivantes[k].remove();
        }
      }, f.t));
    });
    // L'écran bleu arrive à la fin du spam, pas à la fin de la carte : elle
    // reste ensuite le temps qu'on le lise.
    timers.push(setTimeout(() => {
      if (!box.isConnected) return;
      // Tout se tait d'un coup, un battement de silence, puis l'impact grave.
      // C'est la coupure qui fait la fin — un son de plus par-dessus le chaos
      // ne s'entendrait pas comme une fin.
      if (window.WallySons) window.WallySons.bsod();
      box.appendChild(ecranBleu());
    }, duree * 1000));
    // `disposeWidget` ne vide que `data-interval` : sans ce ménage, les
    // rendez-vous en attente continueraient d'ouvrir des fenêtres dans un nœud
    // détaché après le départ de la carte.
    box.dataset.timeouts = timers.join(",");
  }

  /* Une fenêtre du spam « virus » : barre de titre, corps, boutons.
   *
   * Le texte passe par `textContent` et jamais par `innerHTML` : les titres de
   * fenêtre à meme portent des NOMS DE FICHIERS venus du dossier de la
   * communauté, donc du texte qu'on ne contrôle pas.
   */
  function fenetreVirus(f, rang, semeur) {
    const win = el("div", "vwin" + (f.genre === "meme" ? " vwin-meme" : ""));
    const barre = el("div", "vwin-bar");
    const titre = el("span", "vwin-title");
    titre.textContent = f.titre || "";
    const boutons = el("span", "vwin-btns");
    boutons.textContent = "_ □ ✕";
    barre.append(titre, boutons);
    const corps = el("div", "vwin-body");
    if (f.genre === "meme") {
      const src = "/api/public/meme/" + encodeURIComponent(f.media.nom);
      if (f.media.genre === "video") {
        const v = document.createElement("video");
        v.src = src; v.muted = true; v.autoplay = true; v.loop = true;
        v.playsInline = true;
        corps.appendChild(v);
      } else {
        const i = document.createElement("img");
        i.src = src; i.alt = "";
        corps.appendChild(i);
      }
    } else {
      const ligne = el("div", "vwin-msg");
      const icone = el("span", "vwin-icon");
      icone.textContent = "⛔";
      const texte = el("span", "vwin-text");
      texte.textContent = f.message || "";
      ligne.append(icone, texte);
      const pied = el("div", "vwin-actions");
      ["OK", "Annuler"].forEach((mot) => {
        const b = el("span", "vwin-btn");
        b.textContent = mot;
        pied.appendChild(b);
      });
      corps.append(ligne, pied);
    }
    win.append(barre, corps);
    // Taille tirée ici, position ensuite : `place()` a besoin de la taille pour
    // garder la fenêtre ENTIÈREMENT dans le cadre.
    //
    // La hauteur est IMPOSÉE, pas estimée. Celle d'un meme dépend sinon de son
    // ratio — inconnu tant que l'image n'est pas chargée — et on ne peut alors
    // que majorer : les fenêtres s'arrêtaient donc plus haut que le calcul ne
    // le croyait, et le bas de l'écran restait dégarni (couverture mesurée à
    // 40 % en bas contre 94 % au centre). Fixée ici, elle est exacte, et
    // l'image s'y adapte (`object-fit: contain`).
    const cadreH = window.innerHeight || 1080;
    const largeur = (f.genre === "meme" ? 220 : 300) + Math.floor(Math.random() * 160);
    const hauteur = f.genre === "meme"
      ? Math.round(Math.min(largeur, cadreH * 0.30) + 46)
      : 210;                                    // titre + deux lignes + boutons
    win.style.width = largeur + "px";
    win.style.height = hauteur + "px";
    const p = semeur.place(largeur, hauteur);
    win.style.left = p.x + "px";
    win.style.top = p.y + "px";
    // Chaque nouvelle passe DEVANT les précédentes : c'est l'empilement qui
    // raconte la submersion.
    win.style.zIndex = String(10 + rang);
    return win;
  }

  /* L'écran bleu final. Il recouvre tout : c'est lui qui clôt le spectacle,
   * et il doit rester lisible quelques secondes avant le retrait de la carte. */
  function ecranBleu() {
    const mot = window.WallyVirus.bsod();
    const bsod = el("div", "virus-bsod");
    const smiley = el("div", "bsod-face");
    smiley.textContent = ":(";
    const texte = el("div", "bsod-text");
    texte.textContent = mot.titre;
    const sous = el("div", "bsod-sub");
    sous.textContent = mot.message;
    const code = el("div", "bsod-code");
    code.textContent = "Code d'arrêt : " + mot.code;
    bsod.append(smiley, texte, sous, code);
    return bsod;
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
      // Animée par CSS : la barre glisse au lieu de sauter.
      const fill = opt.querySelector(".bar span");
      if (fill) requestAnimationFrame(() => { fill.style.transform = `scaleX(${pct / 100})`; });
      opt.classList.toggle("win", i === winner);
      opt.classList.toggle("lose", winner >= 0 && i !== winner);
    });
  }

  // La roue en cours. spin-wheel garde une boucle d'animation vivante tant
  // qu'on ne l'a pas retirée : sortir son canvas du DOM ne suffit PAS, la
  // boucle continuerait de tourner dans le vide pour tout le reste du live.
  let activeWheel = null;
  // La carte qui possède la roue en cours. Avec le relais recouvrant, une roue
  // sortante se retire 300 ms APRÈS que la suivante a été montée : sans savoir
  // à qui appartient `activeWheel`, la sortante détruisait la nouvelle.
  let activeWheelBox = null;

  function disposeWheel() {
    if (!activeWheel) return;
    try {
      activeWheel.remove();
    } catch (e) {
      /* déjà retirée : rien à faire */
    }
    activeWheel = null;
    activeWheelBox = null;
  }

  /** Les widgets en place, en ignorant ceux qui finissent de sortir. */
  function widgetsEnPlace() {
    return document.querySelectorAll(WIDGET_EN_PLACE);
  }

  /** Le widget en place POUR CE `kind`, s'il y en a un.
   *
   *  Chaque `kind` a son conteneur : il ne peut donc pas y en avoir deux, et
   *  une nouvelle publication du même `kind` est une mise à jour (un vote de
   *  sondage, une case de bingo cochée), pas une seconde carte. */
  function widgetDe(kind) {
    return document.querySelector(`[data-element="${kind}"] > .widget:not(.leaving)`);
  }

  /** Le widget SOLO en place, s'il y en a un : celui qui tient toute la scène.
   *
   *  C'est LUI, et rien d'autre, qui fait patienter les suivants. L'effacement
   *  de l'avatar est une AUTRE question — voir `masqueurEnPlace()`. */
  function soloEnPlace() {
    const boites = widgetsEnPlace();
    for (let i = 0; i < boites.length; i++) {
      if (estSolo(boites[i].dataset.kind)) return boites[i];
    }
    return null;
  }

  /** Le widget en place qui EFFACE WALLY, s'il y en a un.
   *
   *  Distinct de `soloEnPlace()` : tenir toute la scène et effacer l'avatar
   *  sont deux questions différentes, réglées séparément (`wally_visible`). Un
   *  meme peut occuper seul la scène tout en gardant Wally à côté pour qu'il le
   *  commente. */
  function masqueurEnPlace() {
    const boites = widgetsEnPlace();
    for (let i = 0; i < boites.length; i++) {
      if (masqueWally(boites[i].dataset.kind)) return boites[i];
    }
    return null;
  }

  /** `widget-on` est un ÉTAT DÉRIVÉ, recalculé depuis ce qui est RÉELLEMENT à
   *  l'écran — jamais posé puis retiré au fil des événements.
   *
   *  C'est le seul endroit du fichier qui écrit cette classe, et c'est
   *  volontaire : elle efface l'avatar et la bulle. Posée à l'arrivée d'un
   *  widget et retirée « quand il n'y a plus rien nulle part », elle restait
   *  accrochée dès qu'une carte survivait à son tour de piste — un widget
   *  `sticky`, une sortie dont le minuteur avait été annulé par le voisin — et
   *  Wally disparaissait sans jamais revenir. Dérivée, aucune séquence
   *  d'événements ne peut la laisser en travers : il suffit qu'aucun widget
   *  masquant ne soit en place. */
  function majWidgetOn() {
    document.body.classList.toggle("widget-on", !!masqueurEnPlace());
  }

  /** La scène a-t-elle de la place pour ce widget MAINTENANT ?
   *
   *  Trois cas, et un seul fait attendre :
   *    - c'est le sien qui est déjà là → mise à jour, toujours acceptée ;
   *    - un widget solo tient la scène → tout le reste attend son départ ;
   *    - un widget solo veut entrer → il attend que la scène soit vide.
   *  Deux widgets `solo: false` s'affichent donc ensemble, chacun à sa place. */
  function placeLibre(kind) {
    if (widgetDe(kind)) return true;
    if (soloEnPlace()) return false;
    return !(estSolo(kind) && widgetsEnPlace().length > 0);
  }

  /** Retire UN widget et coupe ce qu'il faisait tourner. Un compte à rebours
   *  retiré sans ça continue de tourner dans le vide tout le live. */
  function disposeWidget(box) {
    if (!box) return;
    box.querySelectorAll("[data-interval]").forEach((n) => {
      clearInterval(Number(n.dataset.interval));
    });
    // Les rendez-vous en attente, eux, ne sont pas des intervalles : le spam de
    // popups en pose un par fenêtre à venir. Sans ce ménage, ils continueraient
    // d'ouvrir des fenêtres dans un nœud détaché après le départ de la carte.
    box.querySelectorAll("[data-timeouts]").forEach((n) => {
      String(n.dataset.timeouts).split(",").forEach((id) => {
        if (id) clearTimeout(Number(id));
      });
    });
    // Uniquement SA roue : une carte sortante ne doit pas emporter celle que la
    // suivante vient de monter pendant le recouvrement.
    if (activeWheelBox === box) disposeWheel();
    box.remove();
    // Une carte de moins : l'avatar et la bulle reviennent si plus aucun widget
    // solo ne tient la scène. Recalculé plutôt que retiré à la condition « plus
    // rien nulle part » — une carte qui traîne ailleurs n'a aucune raison de
    // garder l'avatar effacé si elle cohabite.
    majWidgetOn();
  }

  /** Retire les widgets EN PLACE.
   *
   *  Ceux qui finissent de sortir (`.leaving`) sont laissés : ils se retirent
   *  seuls, et c'est ce qui permet à la suivante d'entrer pendant qu'ils
   *  s'en vont. `tout` force le nettoyage complet, pour une annulation. */
  function clearWidgets(tout = false) {
    const cibles = document.querySelectorAll(tout ? WIDGET_TOUS : WIDGET_EN_PLACE);
    cibles.forEach((n) => disposeWidget(n));
    if (tout) {
      disposeWheel();
      // Les cartes seulement. `replaceChildren()` sur les conteneurs viderait
      // AUSSI l'avatar et la bulle, qui vivent dans les leurs.
      document.querySelectorAll(WIDGET_TOUS).forEach((n) => n.remove());
      majWidgetOn();
    }
  }

  // File d'attente : deux demandes rapprochées se remplaçaient, la seconde
  // n'était jamais vue. Elles se jouent maintenant l'une après l'autre.
  const pending = [];
  const QUEUE_MAX = 5;          // au-delà, on abandonne les plus anciennes
  const QUEUE_STALE_MS = 60000; // un dé lancé il y a une minute n'intéresse plus

  function showWidget(kind, params) {
    const build = BUILDERS[kind];
    if (!build) return;

    // Le délai réglé décale l'APPARITION, pas la sortie : le minuteur de durée
    // ne part qu'une fois la carte montée. Posé ici, avant la file d'attente,
    // pour que le délai reste un simple retard de l'événement — réserver la
    // place sans rien monter ferait patienter les autres devant du vide.
    //
    // Rangé dans `minuteurs` comme le reste, et pas dans une variable à part :
    // `clearAll()` vide cette table, et un widget qui surgit APRÈS un « enlève
    // tout » est un fantôme — ce fichier en a déjà payé plusieurs. La clé est
    // préfixée pour ne pas écraser le minuteur de SORTIE du même `kind`.
    //
    // `_delai_consomme` est ce qui empêche la boucle : le second passage porte
    // le drapeau et tombe droit dans le montage.
    // Le spam de popups est le seul dont la durée pilote DEUX choses : le plan
    // de fenêtres (`seconds`) et la sortie de la carte (`duration`), que le
    // serveur publie séparés — l'écran bleu de nettoyage vit dans leur écart.
    // Ne remplacer que le premier laisserait la carte partir avant la fin de
    // son propre plan : réglé à 60 s là où le serveur en annonce 30, l'écran
    // bleu ne serait JAMAIS vu. On les décale donc ensemble, en conservant
    // l'écart tel que le serveur l'a calculé — plutôt que de recopier ici la
    // durée du bleu, qui vit en Python et divergerait.
    if (kind === "virus_popup") {
      const reglee = Number((reglages.virus_popup || {}).duree) || 0;
      if (reglee > 0) {
        const ecart = Math.max(
          0, (Number(params.duration) || 0) - (Number(params.seconds) || 0));
        params = Object.assign({}, params,
                               { seconds: reglee, duration: reglee + ecart });
      }
    }

    const delai = Number((reglages[kind] || {}).delai) || 0;
    if (delai > 0 && !params._delai_consomme) {
      const cle = "delai:" + kind;
      clearTimeout(minuteurs.get(cle));
      minuteurs.set(cle, setTimeout(() => {
        minuteurs.delete(cle);
        showWidget(kind, Object.assign({}, params, { _delai_consomme: true }));
      }, delai * 1000));
      return;
    }

    // La file ne sert QU'À ceux qui n'ont pas de place. Elle valait autrefois
    // pour tout ce qui arrivait pendant qu'un widget était là, quel qu'il
    // soit : deux cartes qui ne se gênent pas se succédaient sur une minute au
    // lieu de s'afficher ensemble.
    if (!placeLibre(kind)) {
      if (pending.length >= QUEUE_MAX) pending.shift();
      pending.push({ kind, params, at: Date.now() });
      return;
    }
    renderWidget(kind, params, build);
  }

  function playNext() {
    const now = Date.now();
    while (pending.length) {
      const next = pending[0];
      // Périmée : un dé lancé il y a une minute n'intéresse plus personne.
      if (now - next.at > QUEUE_STALE_MS) { pending.shift(); continue; }
      // La scène n'est pas encore libre pour lui : il garde son tour. Le widget
      // qui la tient rappellera `playNext()` en partant.
      if (!placeLibre(next.kind)) return;
      pending.shift();
      renderWidget(next.kind, next.params, BUILDERS[next.kind]);
      // Un solo prend toute la scène : les suivants attendent son départ. Un
      // widget qui cohabite laisse la place — on enchaîne sur le suivant, qui
      // s'affichera à côté plutôt que dans une minute.
      if (estSolo(next.kind)) return;
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
    minuteurs.forEach((id) => clearTimeout(id));
    minuteurs.clear();
    clearTimeout(relaisTimer);
    hideBubble();
    showThinking(false);
    // Les repères partent avec le reste : « enlève ce qui est affiché » vise
    // tout ce qui est à l'écran, et un repère oublié survivrait 30 s de plus
    // sur une page qu'on vient de vider.
    retirerFantomes();
    // L'image de la galerie aussi : elle est à l'écran, et ce qui est à
    // l'écran s'en va. Le rotateur, lui, reste — il est le décor de la scène,
    // au même titre que l'avatar, pas un événement qu'on vient de montrer.
    IMAGE.cacher();
    const boites = widgetsEnPlace();
    if (!boites.length) { clearWidgets(true); playNext(); return; }
    boites.forEach((b) => b.classList.remove("visible"));
    // `true` : une annulation emporte AUSSI ce qui était en train de sortir.
    // `playNext()` derrière : une demande arrivée PENDANT ces 300 ms se met en
    // file (les cartes sont encore là), et plus rien ne l'en sortait — elle
    // patientait jusqu'au prochain widget, parfois tout le live.
    relaisTimer = setTimeout(() => { clearWidgets(true); playNext(); }, 300);
  }

  // ── Repères de placement ─────────────────────────────────────────────────
  //
  // Le « Tout afficher » du panneau de mise en scène : un rectangle nommé à la
  // place de chaque élément NON masqué, pour juger de leur cohabitation d'un
  // coup d'œil.
  //
  // Pourquoi des repères et pas les vrais widgets : ils sont `solo` pour la
  // plupart, donc ils passent l'un APRÈS l'autre par la file d'attente. Les
  // demander tous aurait pris cinq minutes en n'en montrant jamais qu'un.
  //
  // Chaque repère vit dans le conteneur de son élément : c'est donc la page
  // elle-même qui le place, avec l'ancrage, l'échelle et l'empilement réels.
  // Un rectangle calculé ailleurs mentirait sur ce qu'on est en train de régler.
  const FANTOMES_MS = 30000;
  // Déclaré AVANT les fonctions qui le lisent — un `let` lu avant sa ligne lève
  // une TDZ, que `node --check` ne détecte pas.
  let fantomeTimer = null;

  function retirerFantomes() {
    clearTimeout(fantomeTimer);
    fantomeTimer = null;
    document.querySelectorAll(".ghost").forEach((n) => n.remove());
  }

  function afficherFantomes(elements) {
    retirerFantomes();
    if (!elements || !window.WallyLayout) return;
    WallyLayout.ELEMENTS.forEach((cle) => {
      const reglage = elements[cle];
      if (!reglage || reglage.hidden) return;
      const hote = document.querySelector(`[data-element="${cle}"]`);
      if (!hote) return;
      const taille = WallyLayout.taille(cle);
      const box = el("div", "ghost");
      box.style.width = `${taille[0]}px`;
      box.style.height = `${taille[1]}px`;
      const nom = el("span", "ghost-nom");
      nom.textContent = cle;
      box.appendChild(nom);
      hote.appendChild(box);
    });
    fantomeTimer = setTimeout(retirerFantomes, FANTOMES_MS);
  }

  // ── Banc de mesure ────────────────────────────────────────────────────────
  //
  // Le panneau de mise en scène dessine un cadre par élément. Tant qu'un widget
  // n'a jamais paru, il n'a AUCUNE taille à lire : le cadre portait alors une
  // valeur de table, et ne devenait juste qu'au premier ▶ — « certaines box ne
  // se mettent à jour que au lancement de l'élément ».
  //
  // Le ▶ ne pouvait pas servir de mesure automatique : il passe par le serveur,
  // qui PUBLIE sur le bus. Mesurer les vingt-sept widgets à l'ouverture du
  // panneau les aurait fait défiler EN DIRECT devant les viewers dès qu'on
  // règle la scène du live. Ce banc, lui, ne parle à personne : il monte chaque
  // widget ici, lit sa boîte, et le retire dans la même tâche JavaScript — rien
  // d'autre ne s'exécute entre les deux, donc aucune carte de banc ne peut être
  // prise pour un widget en place.
  //
  // Trois précautions :
  //
  //   · dans le conteneur RÉEL du widget : le CSS qui le dimensionne y est
  //     contextuel (grille à une cellule, `width: max-content`, règles par
  //     `kind`). Mesuré dans un coin neutre, il n'a pas la même boîte.
  //   · sans la classe `visible`, et sous `visibility: hidden` : la carte est
  //     mise en page, donc mesurable, mais personne ne la voit — ni ici, ni sur
  //     la source OBS si cette page est celle du live.
  //   · `offsetWidth/offsetHeight`, jamais `getBoundingClientRect()`, qui porte
  //     déjà le `scale()` du placement : le panneau applique le sien, et le
  //     compter deux fois donnerait un repère au carré de l'échelle.
  //
  // Ce que le banc N'INCLUT PAS, et pourquoi :
  //
  //   · `meme`, `rotator`, `image` — leur boîte est IMPOSÉE, mesurée par le
  //     serveur sur le dossier. Le banc monterait UNE image et rendrait un
  //     cadre qui change à chaque rotation, ce qu'on a précisément supprimé.
  //   · `planning` — sa taille est celle de l'image qu'on lui donne.
  //   · `clip` — la table porte volontairement l'état LECTURE (540 × 363), le
  //     plus encombrant ; l'échantillon ne monte que la carte d'annonce
  //     (300 × 81), et un repère trop petit laisserait la vidéo recouvrir ses
  //     voisins. Son builder arme en plus une iframe Twitch en différé.
  //   · `apex_progress` — la courbe SE RETIRE quand elle n'a pas de relevés
  //     (`_HORS_WIDGET`, routes/overlay.py, le dit déjà pour le ▶). Mesuré à
  //     vide, le banc l'a relevé à 560 × 22 : un trait plat, alors qu'en live
  //     le panneau porte une courbe. Un cadre mesuré sur un widget qui se
  //     dérobe est plus faux que l'ordre de grandeur qu'il remplacerait.
  const BANC_HORS = {
    meme: true, rotator: true, image: true, planning: true, clip: true,
    apex_progress: true,
  };

  /** Retire une carte de banc, minuteurs compris.
   *
   *  Le compte à rebours arme un `setInterval` DÈS SA CONSTRUCTION
   *  (`node.dataset.interval`) : oublié ici, il tournerait dix fois par seconde
   *  jusqu'à la fin de la page, sur la machine qui encode le live.
   */
  function retirerBanc(box) {
    box.querySelectorAll("[data-interval]").forEach((n) => {
      clearInterval(Number(n.dataset.interval));
    });
    if (box.dataset.interval) clearInterval(Number(box.dataset.interval));
    box.remove();
  }

  /** Monte chaque widget hors vue et rend sa boîte, en pixels de mise en page.
   *
   *  `echantillons` vient du serveur (`_ECHANTILLONS`, routes/overlay.py) : les
   *  mêmes paramètres que le ▶. Un widget construit sans eux serait vide et ne
   *  dirait rien de son encombrement — un sondage sans option n'a pas la
   *  largeur d'un sondage.
   */
  function mesurerEchantillons(echantillons) {
    const ech = echantillons || {};
    const vues = {};
    Object.keys(BUILDERS).forEach((kind) => {
      if (BANC_HORS[kind]) return;
      let box = null;
      try {
        box = el("div", "widget banc");
        box.dataset.kind = kind;
        box.appendChild(BUILDERS[kind](Object.assign({}, ech[kind] || {})));
        hoteWidget(kind).appendChild(box);
        const l = box.offsetWidth, h = box.offsetHeight;
        // Un widget qui ne rend rien N'A PAS de taille : la clé reste absente
        // plutôt que de valoir zéro. « Je ne sais pas » ne s'écrit pas en
        // chiffres — c'est toute la règle de ce mécanisme.
        if (l > 0 && h > 0) vues[kind] = [l, h];
      } catch (e) {
        // Un builder qui refuse son échantillon ne doit pas emporter les
        // vingt-six autres : le panneau garde son estimation pour celui-là.
        console.warn("overlay : banc de mesure impossible pour", kind, e);
      } finally {
        if (box) retirerBanc(box);
      }
    });
    return vues;
  }

  // La seule chose que cette page expose au panneau de mise en scène, qui
  // l'ouvre en `iframe` de même origine.
  window.WallyBanc = { mesurer: mesurerEchantillons };

  // Les couleurs de l'overlay, pas celles de la fête foraine : les accents de
  // la palette, plus un blanc qui accroche l'œil sur une image de jeu.
  // Lus au premier raid, pas au chargement : le CSS est prêt bien avant.
  // Le cyan `#06b6d4` qui traînait ici venait du DASHBOARD — l'overlay, lui,
  // n'a jamais eu ce bleu.
  const confettiColors = () => [token("who"), token("info"), token("gold"), "#ffffff"];

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
        colors: confettiColors(),
        disableForReducedMotion: false,
        scalar: 0.9,
        ticks: 220,          // ~3,5 s de vol : la carte en reste 10
      });
    }
  }

  // Les couleurs des secteurs. Deux voisins ne doivent jamais se ressembler :
  // la roue tourne vite, c'est le contraste qui donne la sensation de vitesse.
  // Six teintes viennent de la palette, deux la complètent — une roue a besoin
  // de plus de teintes distinctes que le reste de l'overlay, mais elle n'a
  // aucune raison d'en inventer huit.
  const wheelColors = () => [
    token("info"), token("who-deep"), token("lose"), token("gold"),
    token("win"), token("wally"), "#7fd1ff", "#c9a0ff",
  ];
  const WHEEL_SPIN_MS = 4000;      // le widget reste 10 s : 6 s pour lire

  function mountWheel(host, params) {
    const options = Array.isArray(params.options) ? params.options.slice(0, 8) : [];
    if (!host || !options.length) return;

    const label = host.parentElement.querySelector(".label");
    const winner = Math.min(options.length - 1,
                            Math.max(0, Number(params.index) || 0));

    // Absente si le fichier n'a pas été servi. Le repli n'est pas décoratif :
    // sans lui, une roue muette laisserait le viewer sans réponse.
    if (!window.spinWheel || typeof window.spinWheel.Wheel !== "function") {
      if (label) {
        label.textContent = String(options[winner]);
        label.classList.add("visible");
      }
      return;
    }

    disposeWheel();
    activeWheelBox = host.closest(".widget");
    activeWheel = new window.spinWheel.Wheel(host, {
      items: options.map((o) => ({ label: String(o) })),
      itemBackgroundColors: wheelColors(),
      itemLabelColors: ["#141419"],
      // Les labels DANS les secteurs : c'est tout l'intérêt du changement. La
      // roue d'avant ne montrait que des couleurs, et le viewer découvrait les
      // options en même temps que le résultat — aucun suspense possible.
      itemLabelFontSizeMax: 22,
      itemLabelAlign: "right",
      itemLabelRadius: 0.92,
      itemLabelRadiusMax: 0.2,
      borderColor: "rgba(255,255,255,.85)",
      borderWidth: 3,
      lineColor: "rgba(20,20,25,.35)",
      lineWidth: 1,
      radius: 0.96,
      // OBS n'a pas de souris, et un drag accidentel fausserait le tirage —
      // qui est décidé côté serveur, pas ici.
      isInteractive: false,
      // Le pointeur est notre triangle CSS, en haut. spin-wheel n'en dessine
      // pas : il aligne juste l'item gagnant sur cet angle.
      pointerAngle: 0,
    });

    // Le résultat n'apparaît qu'à l'arrêt : l'afficher d'emblée vendrait la
    // mèche avant que la roue ait fini de tourner.
    activeWheel.onRest = () => {
      if (!label) return;
      label.textContent = String(options[winner]);
      label.classList.add("visible");
    };
    // `spinToItem(index, durée, centrer, tours, sens, easing)` — le gagnant
    // vient du serveur, la roue ne fait que l'atteindre.
    activeWheel.spinToItem(winner, WHEEL_SPIN_MS, true, 4, 1);
  }

  function renderWidget(kind, params, build) {
    // Le minuteur DE CE `kind` seulement : couper celui des voisins les
    // laisserait à l'écran indéfiniment.
    clearTimeout(minuteurs.get(kind));
    minuteurs.delete(kind);

    // Un sondage déjà affiché est mis à jour en place : le refaire apparaître à
    // chaque vote rejouerait l'animation d'entrée et clignoterait.
    // `widgetDe(kind)` et non « le widget affiché » : plusieurs cartes peuvent
    // être à l'écran, et c'est la SIENNE qu'on met à jour.
    const current = widgetDe(kind);
    let poll = kind === "poll" && current
      ? current.querySelector(".poll") : null;
    // …mais seulement s'il s'agit du MÊME sondage. `updatePoll` ne touche ni la
    // question ni les intitulés : un nouveau sondage lancé pendant que l'ancien
    // est encore à l'écran s'affichait avec la question et les options de
    // l'ancien, grisées « terminé », mais avec les votes du nouveau.
    if (poll) {
      const signature = JSON.stringify([params.question || "", params.options || []]);
      if (poll.dataset.signature !== signature) poll = null;
    }
    // Les widgets qui se RAFRAÎCHISSENT (un vote, une lettre, une case cochée)
    // rejouaient leur animation d'entrée à chaque mise à jour. Faute d'une
    // mutation en place pour chacun, on se contente de ne pas les faire
    // clignoter : on reconstruit sans relancer la cascade d'apparition.
    // Pas `rps` : un chifoumi est un affichage unique, deux duels de suite sont
    // deux animations. Le retenir ici privait le second de sa cascade d'entrée.
    const refresh = current && (kind === "bingo" || kind === "hangman");
    let box;
    if (kind === "poll" && poll) {
      // Mutation en place : reconstruire relancerait la cascade d'entrée et
      // ferait repartir chaque barre de zéro à chaque vote.
      updatePoll(poll, params);
      box = current;
    } else {
      // Un widget SOLO prend la scène : ce qui est en place lui cède la place.
      // Un widget qui cohabite ne retire QUE le sien — sans quoi il chasserait
      // des cartes qui ne le gênent pas, ce que le réglage `solo: false` du
      // modèle dit précisément de ne pas faire.
      if (estSolo(kind)) clearWidgets();
      else disposeWidget(current);
      box = el("div", "widget");
      box.dataset.kind = kind;
      box.appendChild(build(params));
      // Dans le conteneur de SON `kind` : c'est lui qui porte la place, la
      // taille et l'empilement réglés pour ce widget.
      hoteWidget(kind).appendChild(box);
      if (refresh) {
        box.classList.add("visible");   // déjà à l'écran : pas de réapparition
      } else {
        void box.offsetWidth;
        box.classList.add("visible");
      }
    }
    // `box` est la carte qu'on vient de monter, et non « la première carte
    // trouvée à l'écran » : avec plusieurs widgets en place, celle-ci pouvait
    // être une VOISINE, qui héritait alors du minuteur de sortie du nouveau
    // venu — et le nouveau venu ne partait plus jamais.
    // `widget-on` se recalcule : c'est le seul écrivain de cette classe.
    majWidgetOn();

    // Les confettis vivent HORS du builder : ils ne sont pas un élément du
    // widget mais un effet plein écran, et ils doivent partir au moment exact
    // où la carte apparaît — pas à sa construction.
    if (kind === "raid" && !refresh) burstConfetti(params.viewers);
    if (kind === "wheel" && !refresh) {
      mountWheel(box.querySelector(".wheel-canvas"), params);
    }

    // ── Les animations réglées pour ce widget dans cette scène ───────────
    //
    // `glitch` — le défaut — ne pose AUCUNE classe : la transition CSS de
    // `.visible` reste seule, c'est-à-dire l'entrée d'avant ce chantier.
    const anim = animDe(kind);
    if (!refresh) animer(box, anim.entree, anim.ms, false);
    // L'insistance se rejoue en boucle pendant tout l'affichage. Posée sur le
    // CONTENU et non sur la carte : deux `animation` sur un même nœud se
    // remplacent au lieu de se cumuler, et la carte porte déjà son entrée.
    if (!refresh && anim.insistance !== "aucune") {
      animer(box.firstElementChild, anim.insistance, anim.ms, true);
    }

    // Une partie en cours ne s'efface pas toute seule : le pendu doit rester
    // sous les yeux du chat tant qu'on y joue. Un booléen plutôt qu'une durée
    // nulle — `Number(0) || 12` vaut 12, le piège serait invisible.
    if (params.sticky === true) return;

    // La durée réglée pour CE widget dans CETTE scène l'emporte sur celle que
    // le serveur envoie : c'est le streamer qui décide de son habillage. Zéro
    // vaut « auto », c'est-à-dire le comportement d'avant ce réglage — et c'est
    // la valeur livrée, pour que rien ne change tant que personne n'y touche.
    // Un simple repli n'aurait quasiment jamais rien fait : tous les événements
    // portent déjà une durée.
    const dureeReglee = DUREE_INTERNE.has(kind)
      ? 0 : (Number((reglages[kind] || {}).duree) || 0);
    // Le serveur décide (animation + lecture) ; ce plafond n'est qu'un garde-fou.
    // 180 s et non 30 : le serveur émet jusqu'à 124 s (sondage de 120 s + 4),
    // et un sondage de 60 s disparaissait de l'écran à mi-parcours, les viewers
    // n'ayant plus la question sous les yeux pour voter.
    const seconds = dureeReglee > 0
      ? dureeReglee
      : Math.min(180, Math.max(2, Number(params.duration) || 12));
    minuteurs.set(kind, setTimeout(() => {
      minuteurs.delete(kind);
      // Le widget éclate comme la bulle, mais plus large : il apparaît quelques
      // fois par live là où une bulle part toutes les quelques secondes.
      // `leaving` cesse de le compter comme la carte EN PLACE : la suivante
      // peut commencer à entrer pendant qu'il finit de partir. Sans
      // recouvrement, deux widgets à la suite lisent comme deux événements ;
      // avec, comme un seul mouvement.
      // La superposition est portée par la grille du conteneur, pas par un
      // `position: absolute` : hors flux, la carte ne dimensionnait plus son
      // conteneur et se téléportait le temps de sa sortie.
      box.classList.add("leaving");
      // La rafale garde SA durée (5 × 30 ms), quoi qu'on règle : `anim_duree`
      // ne la pilote pas. Faire suivre le relais à une durée réglée ferait
      // attendre la carte suivante pour rien.
      const sortieMs = anim.sortie === "glitch" ? GLITCH_MS : anim.ms;
      if (anim.sortie === "glitch") {
        // Une carte est plus large qu'une bulle : elle encaisse un décalage
        // plus franc sans sortir du cadre.
        WallyGlitch.rafale(box, { ...GLITCH, decalage: 22 }).then(() => {
          WallyGlitch.nettoyer(box);
          box.classList.remove("visible");
        });
      } else {
        // Les classes d'ENTRÉE partent d'abord : deux `animation` sur un même
        // nœud se remplacent, et sans ce ménage la sortie ne se jouerait
        // jamais. Un minuteur et non `animationend` — une carte chassée pendant
        // sa sortie déclenche `animationcancel`, et si `animate.min.css`
        // n'était pas servi l'événement n'arriverait jamais. Piège déjà payé
        // sur l'image de la galerie, quelques centaines de lignes plus bas.
        box.classList.remove("animate__animated", "animate__" + anim.entree);
        animer(box, anim.sortie, sortieMs, false);
        setTimeout(() => box.classList.remove("visible"), sortieMs);
      }
      // Suivi lui aussi : ce timer interne n'était annulé nulle part. Un vote
      // arrivant pendant les 300 ms de sortie reconstruisait le widget, puis le
      // nettoyage orphelin l'effaçait — et `playNext()` pouvait enchaîner sur
      // autre chose. Vaut pour bingo, hangman et poll.
      // Appelée à la fin de la rafale : la suivante entre quand la précédente
      // a fini de se parasiter. Deux cartes pleines l'une sur l'autre seraient
      // illisibles.
      relaisTimer = setTimeout(playNext, sortieMs);
      setTimeout(() => disposeWidget(box), sortieMs + 260);
    }, seconds * 1000));
  }

  // ── Rotateur de memes ────────────────────────────────────────────────────
  //
  // Porté de `overlay_rotation.html`, qui tournait dans SA propre source OBS.
  // Trois choses changent en venant ici, et elles sont tout l'objet du portage :
  //
  //   1. le média est borné par la TAILLE DE LA ZONE (canvas 1920×1080), plus
  //      par le viewport : la zone a maintenant une place et une échelle ;
  //   2. le réglage `hidden` de la scène coupe la boucle POUR DE BON —
  //      téléchargements compris. Un rotateur masqué qui continue d'aspirer des
  //      memes serait une source de trafic invisible, donc jamais remarquée ;
  //   3. le gardien de figeage relance la BOUCLE au lieu de recharger la page :
  //      ici, un `location.reload()` emporterait les bulles, les widgets et
  //      l'avatar pour un rotateur coincé.
  //
  // Déclaré AVANT `chargerLayout()`, qui l'appelle : un `const` lu avant sa
  // ligne de déclaration lève une TDZ, que `node --check` ne détecte pas.
  const ROTATEUR = (() => {
    const cadre = document.getElementById("rotateur");
    const img = document.getElementById("rotateur-image");
    const video = document.getElementById("rotateur-video");

    const params = new URLSearchParams(location.search);
    /** Lit un réglage numérique de l'URL.
     *
     *  `params.has` d'abord, et non `Number(...)` seul : `Number(null)` vaut 0,
     *  donc un paramètre ABSENT passerait pour un zéro explicite dès qu'on
     *  autorise le zéro. Le minimum est donc porté par l'appelant, pas deviné.
     */
    const nombre = (cle, defaut, minimum) => {
      if (!params.has(cle)) return defaut;
      const v = Number(params.get(cle));
      return Number.isFinite(v) && v >= minimum ? v : defaut;
    };

    // La cadence NE VIENT PLUS DE L'URL : elle est un réglage de l'élément
    // `rotator` dans la scène (`bot/core/overlay_layout.py`), au même titre que
    // sa position. Deux sources pour une même valeur, c'est la valeur du
    // panneau qui écraserait celle de l'URL au premier chargement du layout —
    // un réglage qui ne tient pas vaut moins qu'un réglage absent.
    //
    // Bornes et défauts recopiés du modèle : le serveur tranche, on ne fait
    // qu'éviter d'afficher n'importe quoi si la clé manque (layout rangé avant
    // l'ajout du champ) ou arrive abîmée.
    const DUREE_MIN = 1, DUREE_MAX = 120, DUREE_DEFAUT = 9;
    // `pause = 0` est une valeur légitime : elle enchaîne les memes sans temps
    // mort, le glitch de sortie de l'un touchant celui d'entrée du suivant.
    const PAUSE_MIN = 0, PAUSE_MAX = 120, PAUSE_DEFAUT = 5;
    let DUREE = DUREE_DEFAUT * 1000;
    let PAUSE = PAUSE_DEFAUT * 1000;

    /** Un réglage de cadence, en millisecondes.
     *
     *  `typeof v === "number"` et pas `Number(v)` : `Number(null)` vaut 0, et
     *  une clé absente passerait alors pour une pause explicite de zéro.
     */
    const secondes = (v, mini, maxi, defaut) => {
      const n = (typeof v === "number" && Number.isFinite(v))
        ? Math.max(mini, Math.min(maxi, v)) : defaut;
      return n * 1000;
    };

    const ORDRE = params.get("ordre") === "dossier" ? "dossier" : "hasard";
    const SACCADE = nombre("saccade", 33, 1);   // ms par état de glitch
    const AGRANDIR = nombre("agrandir", 2, 1);  // facteur maximum d'agrandissement
    const ETATS = 7;                            // états par rafale

    // Le rayon doit suivre celui du CSS (`--r-lg`), sinon l'angle droit du
    // contenu réapparaît derrière les coins arrondis du cadre.
    const RAYON = "16px";
    const NET = WallyGlitch.net(RAYON);
    const ETEINT = WallyGlitch.eteint(RAYON);
    const appliquer = (etat) => WallyGlitch.appliquer(cadre, etat);
    const rafale = () => WallyGlitch.rafale(cadre, { etats: ETATS, saccade: SACCADE });

    // La boîte, puis la place du média DEDANS : la zone moins le passe-partout
    // (14 px de marge + 3 px de bordure, des deux côtés). Le cadre porte la
    // taille de la zone et ne bouge plus ; c'est le média qui s'y range.
    const CADRE_MARGE = 34;
    let MEDIA_L = 80, MEDIA_H = 80;

    /** Relit la boîte dans la table et la pose sur le cadre.
     *
     *  Rappelée quand le layout arrive : la boîte est MESURÉE par le serveur sur
     *  le dossier de memes, donc elle n'est pas connue au chargement du script.
     *  Figée à la construction, elle serait restée sur le repli de la table, et
     *  ajouter un meme d'un format inédit n'aurait plus rien changé.
     */
    function poserZone() {
      const zone = WallyLayout.taille("rotator");
      MEDIA_L = Math.max(80, zone[0] - CADRE_MARGE);
      MEDIA_H = Math.max(80, zone[1] - CADRE_MARGE);
      cadre.style.setProperty("--rotateur-zone-l", zone[0] + "px");
      cadre.style.setProperty("--rotateur-zone-h", zone[1] + "px");
    }
    poserZone();

    let medias = [];
    let dernier = null;
    let rang = 0;
    let depuisRelecture = 0;
    let echecsDaffilee = 0;
    // Le numéro de la boucle en cours. Arrêter ou relancer l'incrémente : la
    // chaîne précédente le voit à son prochain point de contrôle et se retire.
    // Sans ce compteur, un masquage puis un démarrage feraient tourner DEUX
    // chaînes en parallèle, et les memes se chasseraient l'un l'autre.
    let generation = 0;
    let enMarche = false;
    let minuteur = null;
    let derniereVie = Date.now();
    let aDejaAffiche = false;

    function planifier(gen, ms) {
      clearTimeout(minuteur);
      minuteur = setTimeout(() => tour(gen), ms);
    }

    async function charger() {
      // Une liste vide n'écrase jamais une liste qui marchait : le bot peut
      // être en train de redémarrer, la source doit continuer de tourner.
      try {
        const r = await fetch("/api/public/rotation", { cache: "no-store" });
        const data = await r.json();
        if (Array.isArray(data.medias) && data.medias.length) {
          medias = data.medias;
          // Partagée avec l'avalanche de memes, qui puise dans le MÊME stock.
          // Une seconde source aurait divergé au premier meme ajouté — et
          // l'avalanche est justement l'endroit où l'on veut tout le dossier.
          window.WallyRotationMedias = medias;
        }
      } catch (e) { /* on garde la liste précédente */ }
    }

    // Relecture À LA DEMANDE, pour les deux spectacles qui veulent le dossier
    // ENTIER (avalanche, spam de popups). Sans elle, ils travaillaient sur la
    // liste chargée à l'ouverture de la page : un meme déposé pendant le live
    // n'entrait qu'au bout d'un cycle complet de rotation — or « de nouveaux
    // memes sont souvent ajoutés » (owner), et c'est la durée même du
    // spectacle qui en dépend.
    window.WallyRotationRelire = charger;

    function tirer() {
      if (ORDRE === "dossier") {
        const m = medias[rang % medias.length];
        rang += 1;
        return m;
      }
      // Deux fois le même d'affilée passerait pour un bug d'affichage.
      const pool = medias.filter((m) => m.nom !== dernier);
      const choix = pool.length ? pool : medias;
      return choix[Math.floor(Math.random() * choix.length)];
    }

    const url = (media) => "/api/public/meme/" + encodeURIComponent(media.nom);

    /** Charge le média et attend ses dimensions AVANT de l'afficher.
     *  Sans ça, le cadre naîtrait à la taille de l'ancien média puis grandirait
     *  d'un coup quand le nouveau arrive : le saut de format serait visible. */
    function precharger(media) {
      return new Promise((resolve, reject) => {
        if (media.genre === "video") {
          video.onloadedmetadata = () => resolve({ l: video.videoWidth, h: video.videoHeight });
          video.onerror = () => reject(new Error("vidéo illisible : " + media.nom));
          video.src = url(media);
          video.load();
          return;
        }
        const test = new Image();
        test.onload = () => resolve({ l: test.naturalWidth, h: test.naturalHeight });
        test.onerror = () => reject(new Error("média illisible : " + media.nom));
        test.src = url(media);
      });
    }

    /** Donne au média la place qu'il mérite dans la zone.
     *
     *  Les memes du dossier vont de 260 à 2100 px de côté. Sans agrandissement,
     *  un petit occupe un tiers de ce qu'occupe un grand et paraît perdu ; à
     *  remplir la zone coûte que coûte, il baverait (près de 3×). D'où le
     *  plafond : on agrandit jusqu'à `AGRANDIR` fois, pas au-delà.
     *
     *  La réduction, elle, reste au CSS (`max-width` / `max-height`).
     */
    function dimensionner(element, naturel) {
      element.style.width = "";
      element.style.height = "";
      if (!naturel || !naturel.l || !naturel.h) return;
      const facteur = Math.min(MEDIA_L / naturel.l, MEDIA_H / naturel.h, AGRANDIR);
      if (facteur > 1) {
        element.style.width = Math.round(naturel.l * facteur) + "px";
        element.style.height = "auto";
      }
    }

    /** Joue la vidéo et rend la main à la fin.
     *
     *  Trois façons de ne jamais rendre la main, trois parades :
     *  - le navigateur refuse la lecture audio automatique → seconde tentative
     *    en muet, puis abandon ;
     *  - le fichier est tronqué et `ended` n'arrive jamais → minuteur de secours ;
     *  - la lecture cale → le même minuteur.
     *  Sans elles, la zone resterait figée sur cette vidéo pour tout le live.
     */
    function jouerVideo() {
      return new Promise((fini) => {
        let rendu = false;
        const rendreLaMain = () => {
          if (rendu) return;
          rendu = true;
          clearTimeout(secours);
          video.onended = null;
          fini();
        };
        const limite = Number.isFinite(video.duration) && video.duration > 0
          ? (video.duration + 5) * 1000
          : 60000;
        const secours = setTimeout(rendreLaMain, limite);
        video.onended = rendreLaMain;
        video.muted = false;
        video.currentTime = 0;
        video.play().catch(() => {
          // Chrome bloque la lecture audio automatique tant qu'OBS n'a pas
          // autorisé la source. Muet vaut mieux que rien.
          video.muted = true;
          video.play().catch(rendreLaMain);
        });
      });
    }

    async function tour(gen) {
      // Le contrôle est repris après CHAQUE attente : entre deux, la scène a pu
      // masquer le rotateur, et une chaîne périmée qui continue afficherait un
      // meme dans une zone que le propriétaire vient d'éteindre.
      if (gen !== generation) return;
      // Le bloc est éteint AVANT de changer de média : le cadre se
      // redimensionne pendant qu'il est invisible, sinon on le verrait sauter
      // d'un format à l'autre.
      appliquer(ETEINT);

      if (!medias.length) {
        await charger();
        if (gen !== generation) return;
        planifier(gen, medias.length ? 0 : 10000);
        return;
      }

      const media = tirer();
      dernier = media.nom;

      // Tous les N affichages, où N est la taille de la liste : un meme déposé
      // pendant le live entre dans la rotation sans toucher à OBS.
      depuisRelecture += 1;
      if (depuisRelecture >= medias.length) { depuisRelecture = 0; charger(); }

      let naturel;
      try {
        naturel = await precharger(media);
        echecsDaffilee = 0;
      } catch (e) {
        echecsDaffilee += 1;
        if (gen !== generation) return;
        // Trois échecs de suite ne désignent plus des fichiers fautifs : c'est
        // le serveur qui ne répond plus — un rebuild du bot dure une quinzaine
        // de secondes. Continuer à écarter viderait la bibliothèque entière en
        // quelques secondes et la zone perdrait l'autonomie qui fait tout son
        // intérêt. On patiente, la liste reste intacte.
        if (echecsDaffilee < 3) {
          medias = medias.filter((m) => m.nom !== media.nom);
          planifier(gen, 0);
        } else {
          planifier(gen, 5000);
        }
        return;
      }
      if (gen !== generation) return;

      const estVideo = media.genre === "video";
      img.classList.toggle("absent", estVideo);
      video.classList.toggle("absent", !estVideo);
      if (!estVideo) img.src = url(media);
      dimensionner(estVideo ? video : img, naturel);

      await rafale();
      if (gen !== generation) return;
      appliquer(NET);
      signeDeVie();

      const sortir = async () => {
        if (gen !== generation) return;
        await rafale();
        if (gen !== generation) return;
        appliquer(ETEINT);
        if (estVideo) video.pause();
        planifier(gen, PAUSE);
      };

      // Une vidéo dure ce qu'elle dure ; une image, le temps réglé.
      // Le minuteur de sortie passe par la MÊME variable que celui du tour
      // suivant : il n'y en a jamais qu'un en vol, donc un seul à annuler
      // quand la zone se masque.
      if (estVideo) {
        await jouerVideo();
        sortir();
      } else {
        clearTimeout(minuteur);
        minuteur = setTimeout(sortir, DUREE);
      }
    }

    function signeDeVie() { derniereVie = Date.now(); aDejaAffiche = true; }

    // Une vidéo longue est un signe de vie par ses `timeupdate` : sans cette
    // condition, le gardien couperait un média de deux minutes en plein milieu.
    video.addEventListener("timeupdate", signeDeVie);

    function demarrer() {
      if (enMarche) return;
      enMarche = true;
      generation += 1;
      const gen = generation;
      aDejaAffiche = false;
      derniereVie = Date.now();
      charger().then(() => { if (gen === generation) tour(gen); });
    }

    /** Coupe la boucle et rend la zone muette — y compris le réseau.
     *
     *  Les `src` sont RETIRÉS, pas vidés : `src = ""` fait redemander la page
     *  elle-même au serveur dans plusieurs navigateurs. Une vidéo en cours de
     *  mise en tampon continue sinon de tirer sur la connexion pendant tout le
     *  live, pour une zone que personne ne voit.
     */
    function arreter() {
      generation += 1;
      enMarche = false;
      clearTimeout(minuteur);
      minuteur = null;
      video.pause();
      video.removeAttribute("src");
      video.load();
      img.removeAttribute("src");
      appliquer(ETEINT);
    }

    /** Le réglage de la scène : c'est LUI qui allume ou éteint la zone, et qui
     *  porte sa cadence.
     *
     *  Rappelée à chaque publication du panneau (`case "layout"`), donc la
     *  cadence suit SANS rechargement. Le cycle en cours va au bout avec
     *  l'ancienne valeur — son minuteur est déjà armé —, le suivant prend la
     *  nouvelle. Couper le média affiché pour appliquer un réglage plus tôt
     *  ferait sauter un meme à l'antenne à chaque publication, y compris quand
     *  on ne touche qu'à la position d'un autre élément.
     *
     *  `el` absent (layout indisponible) : on garde la cadence précédente
     *  plutôt que de revenir aux défauts sur un simple aléa réseau.
     */
    function appliquerReglage(el) {
      // La boîte d'abord : elle vient d'être mesurée par le serveur, et le
      // média affiché doit se ranger dans la nouvelle avant le tour suivant.
      poserZone();
      if (el) {
        DUREE = secondes(el.duree, DUREE_MIN, DUREE_MAX, DUREE_DEFAUT);
        PAUSE = secondes(el.pause, PAUSE_MIN, PAUSE_MAX, PAUSE_DEFAUT);
      }
      if (el && !el.hidden) demarrer();
      else {
        arreter();
        // La zone est éteinte, mais l'AVALANCHE puise dans la même liste et
        // peut être achetée à tout moment. Sans ce chargement, un rotateur
        // masqué la laissait sans un seul meme à faire tomber.
        if (!(window.WallyRotationMedias || []).length) charger();
      }
    }

    /** Passe au média suivant tout de suite (le ▶ du panneau de mise en scène).
     *  Rend `false` si la zone est éteinte : il n'y a rien à relancer, et
     *  répondre « c'est parti » sur une zone masquée est un mensonge. */
    function relancer() {
      if (!enMarche) return false;
      generation += 1;
      const gen = generation;
      clearTimeout(minuteur);
      tour(gen);
      return true;
    }

    // Une source de live qui se fige ne le dit à personne : on ne s'en aperçoit
    // qu'en revoyant le VOD. `aDejaAffiche` borne le gardien à ce qu'il sait
    // guérir : si le bot est arrêté quand OBS ouvre la page, il n'y a jamais eu
    // de signe de vie, et la boucle est déjà en train de réessayer toute seule.
    // Les dix secondes de marge couvrent les cadences très courtes, où trois
    // cycles ne font qu'une poignée de secondes.
    setInterval(() => {
      if (enMarche && aDejaAffiche && medias.length
          && Date.now() - derniereVie > 3 * (DUREE + PAUSE) + 10000) {
        relancer();
      }
    }, 5000);

    return { appliquerReglage, relancer, charger };
  })();

  // ── Image de la galerie ──────────────────────────────────────────────────
  //
  // Portée de `overlay_image.html`. Le bot la pousse par son propre flux SSE
  // (`!image` sur Twitch), branché plus bas avec les autres.
  const IMAGE = (() => {
    const boite = document.getElementById("image-galerie");
    const img = document.getElementById("image-galerie-img");
    const credit = document.getElementById("image-galerie-credit");

    const zone = WallyLayout.taille("image");
    boite.style.setProperty("--image-l", zone[0] + "px");
    boite.style.setProperty("--image-h", zone[1] + "px");

    // Une zone masquée ne télécharge rien : sur la scène de jeu, l'image de la
    // galerie est souvent éteinte, et poser son `src` ferait tirer un fichier
    // de plusieurs mégaoctets que personne ne verra.
    let masque = false;
    let minuteurSortie = null;
    let minuteurFin = null;

    function cacher() {
      clearTimeout(minuteurSortie);
      clearTimeout(minuteurFin);
      minuteurSortie = null;
      minuteurFin = null;
      boite.style.display = "none";
      boite.className = "image-galerie";
      img.removeAttribute("src");
      credit.replaceChildren();
    }

    function montrer(data) {
      if (masque || !data || !data.image_url) return;
      // Les quatre réglages viennent désormais de la SCÈNE et non de
      // `config.yaml` : la galerie se règle comme tous les autres widgets, et
      // PAR SCÈNE. `data.*` reste en repli — la graine qui recopie les valeurs
      // du fichier dans le layout arrive en phase 5, et une page ouverte
      // entre-temps ne doit pas perdre le réglage de l'owner.
      //
      // `glitch` est écarté ici : c'est le défaut commun des menus, mais la
      // galerie n'a jamais eu de rafale — elle entre en fondu depuis toujours.
      // Le laisser passer ferait disparaître son animation.
      const reg = reglages.image || {};
      const animIn = (reg.anim_entree && reg.anim_entree !== "glitch")
        ? reg.anim_entree : (data.animation_in || "fadeIn");
      const animOut = (reg.anim_sortie && reg.anim_sortie !== "glitch")
        ? reg.anim_sortie : (data.animation_out || "fadeOut");
      const duree = ((Number(reg.duree) || 0)
        || Number(data.display_duration) || 15) * 1000;
      const animS = Number(reg.anim_duree) > 0
        ? Number(reg.anim_duree) : (Number(data.animation_duration) || 1);

      clearTimeout(minuteurSortie);
      clearTimeout(minuteurFin);

      img.src = data.image_url;
      credit.replaceChildren();
      if (data.username) {
        const label = document.createElement("span");
        label.className = "credit-label";
        label.textContent = "par";
        const nom = document.createElement("span");
        nom.className = "credit-nom";
        // `textContent` : le pseudo vient du chat, il n'est pas du HTML.
        nom.textContent = data.username;
        credit.append(label, nom);
      }
      boite.style.display = "block";
      boite.style.setProperty("--animate-duration", animS + "s");
      boite.className = "image-galerie animate__animated animate__" + animIn;

      minuteurSortie = setTimeout(() => {
        boite.className = "image-galerie animate__animated animate__" + animOut;
        // Un MINUTEUR, et non l'événement `animationend` de la page d'origine.
        // Deux pièges d'un coup : une image chassée pendant sa sortie déclenche
        // `animationcancel` et non `animationend`, si bien que le gestionnaire
        // survivait et effaçait la SUIVANTE ; et si `animate.min.css` n'était
        // pas servi, aucune animation ne se joue — `animationend` n'arriverait
        // jamais et l'image resterait à l'écran pour le reste du live.
        minuteurFin = setTimeout(cacher, animS * 1000 + 100);
      }, duree);
    }

    /** Le réglage de la scène. Une image déjà à l'écran quand la zone se masque
     *  s'en va : elle est posée dans un conteneur devenu invisible. */
    function appliquerReglage(el) {
      masque = !el || !!el.hidden;
      if (masque) cacher();
    }

    return { montrer, cacher, appliquerReglage };
  })();

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

  // ── Layout des scènes ────────────────────────────────────────────────────
  // Le layout est chargé par un GET, pas attendu du bus : une page ouverte
  // alors que le bus est muet doit quand même se placer.
  const sceneSlug = document.body.dataset.sceneSlug || "";
  // Le modèle est la source : un widget dont on ignore le réglage est traité
  // comme solo, l'ancien comportement — jamais deux widgets superposés par
  // accident.
  let reglages = {};
  function estSolo(kind) {
    const el = reglages[kind];
    if (!el) return true;
    // Un élément MASQUÉ dans la scène n'occupe rien : il ne peut pas prétendre
    // à la scène entière. Sans ça, tester un élément masqué effaçait l'avatar
    // pour ne rien montrer à la place — l'écran perdait Wally et ne gagnait
    // rien, le temps de la durée d'affichage.
    if (el.hidden) return false;
    return el.solo !== false;
  }
  /** Ce widget efface-t-il l'avatar et la bulle pendant son passage ?
   *
   *  Question SÉPARÉE de `estSolo()` depuis qu'un élément peut tenir seul la
   *  scène tout en gardant Wally à côté. Deux replis, tous deux sur l'ancien
   *  comportement : un `kind` inconnu efface (prudence), et un réglage servi
   *  SANS le champ — un layout rangé avant l'ajout de ce champ — retombe sur
   *  `solo`, qui décidait à lui seul de l'effacement. */
  function masqueWally(kind) {
    const el = reglages[kind];
    if (!el) return true;
    // Masqué dans la scène : il n'occupe rien, donc il n'efface rien. Sans ça,
    // tester un élément masqué faisait perdre Wally sans rien montrer.
    if (el.hidden) return false;
    if (el.wally_visible === undefined || el.wally_visible === null) {
      return el.solo !== false;
    }
    return !el.wally_visible;
  }
  /** Les réglages d'animation de CE widget dans CETTE scène, avec leurs replis.
   *
   *  Troisième lectrice de `reglages`, déclarée avec les deux autres. Les
   *  replis reproduisent le comportement d'avant ce réglage : la rafale de
   *  glitch, et sa durée. Un layout rangé avant ce chantier ne porte aucun de
   *  ces champs — il doit rendre exactement ce qu'il rendait.
   */
  function animDe(kind) {
    const r = reglages[kind] || {};
    const s = Number(r.anim_duree);
    return {
      entree: r.anim_entree || "glitch",
      sortie: r.anim_sortie || "glitch",
      insistance: r.anim_insistance || "aucune",
      ms: (s > 0 ? s : GLITCH_MS / 1000) * 1000,
    };
  }

  async function chargerLayout() {
    try {
      const r = await fetch(
        "/api/public/overlay-layout?scene=" + encodeURIComponent(sceneSlug),
        { cache: "no-store" });
      const data = await r.json();
      // `|| {}` : une scène sans `elements` laisserait `reglages` indéfini et
      // ferait mourir tout le rendu des widgets à la première lecture.
      reglages = data.scene.elements || {};
      // AVANT `appliquer` : les boîtes mesurées sur le dossier de memes doivent
      // être en place quand les zones se placent, sinon la première frame se
      // dessine sur le repli de la table et saute ensuite.
      WallyLayout.poserTailles(data.tailles);
      WallyLayout.appliquer(data.scene.slug, data.scene);
      // Les deux zones qui portent leur propre boucle : `display: none` sur le
      // conteneur les cacherait, mais le rotateur continuerait de télécharger
      // des memes pour personne. C'est le réglage qui les allume ou les éteint.
      ROTATEUR.appliquerReglage(reglages.rotator);
      IMAGE.appliquerReglage(reglages.image);
      // Course avec l'EventSource : `feed.recent()` peut réafficher un widget
      // AVANT que ce fetch (lecture SQLite) ne réponde. Tant que `reglages`
      // valait `{}`, ce widget a été classé solo par défaut et `widget-on` a
      // effacé l'avatar. On réévalue maintenant — sans ça, rien ne la
      // retouchait avant le widget SUIVANT. `majWidgetOn()` relit TOUT ce qui
      // est à l'écran : le réglage a pu changer pour plusieurs cartes à la
      // fois, et c'est aussi ce qui rend l'avatar quand la scène n'a plus
      // aucun widget solo.
      majWidgetOn();
    } catch (e) {
      // Les défauts du CSS restent en place : mal placé vaut mieux que vide.
      console.warn("layout indisponible", e);
    }
  }
  chargerLayout();
  // La source peut être redimensionnée dans OBS après coup : le facteur de
  // canvas change, les échelles doivent suivre.
  window.addEventListener("resize", chargerLayout);

  // ── Flux SSE ─────────────────────────────────────────────────────────────
  // `evenement` : le nom de l'événement SSE à écouter, quand le flux en nomme
  // un (`event: show_image`). Sans lui, `onmessage` ne voit que les messages
  // anonymes — un flux nommé arriverait sans que rien ne le signale.
  function connect(url, onMessage, evenement) {
    let source;
    let delay = RECONNECT_MS;
    const open = () => {
      source = new EventSource(url);
      const recevoir = (e) => {
        try { onMessage(JSON.parse(e.data)); } catch { /* keepalive ou bruit */ }
      };
      if (evenement) source.addEventListener(evenement, recevoir);
      else source.onmessage = recevoir;
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
    // Un événement qui porte un slug ne concerne QUE la page de cette scène.
    // Sans ce filtre, régler la scène de fin depuis le panneau ferait surgir un
    // dé d'essai en plein live sur celle du jeu — c'est exactement ce que le
    // champ `scene` existe pour empêcher. Un événement sans slug (tout ce que
    // Wally publie de lui-même) vise tout le monde, comme avant.
    if (event.scene && event.scene !== sceneSlug) return;
    switch (event.type) {
      case "bubble":   say(event.text, event.mode, event.duration); break;
      case "thinking": showThinking(event.active); break;
      case "react":    react(); break;
      case "widget":   showWidget(event.kind, event.params || {}); break;
      case "clear":    clearAll(); break;
      // L'événement est un simple SIGNAL : le layout n'y voyage pas, sans quoi
      // il occuperait le tampon de rejeu au détriment des bulles. On refait le
      // GET, qui reste la seule source de vérité.
      case "layout":   chargerLayout(); break;
      case "ghosts":   afficherFantomes(event.elements); break;
      // Le ▶ du rotateur : il tourne déjà tout seul, alors la seule chose utile
      // à faire est de passer au média suivant SANS attendre le tour d'après —
      // on règle sa place en le regardant.
      case "rotator":  ROTATEUR.relancer(); break;
    }
  });

  // L'image de la galerie a son PROPRE flux : c'est le bot qui la pousse
  // (`!image` sur Twitch), et l'ancienne source OBS `/overlay-image` l'écoute
  // toujours. Le nom d'événement est le troisième argument.
  //
  // `onerror` d'un `EventSource` retombe à CHAQUE reconnexion, y compris
  // normale : ce n'est pas une panne. La page d'origine armait un
  // `location.reload()` de 30 s qu'elle devait désamorcer à `onopen` sous peine
  // d'empiler les rechargements ; ici c'est `connect()` qui rouvre, avec son
  // backoff — rien à désamorcer.
  connect("/api/public/sse/overlay-image", (data) => {
    // Un `scene` sur la charge utile vient d'un essai depuis le panneau : il ne
    // concerne QUE la page de cette scène. Ce que Wally pousse en direct n'en
    // porte pas et s'affiche partout, comme avant.
    if (data.scene && data.scene !== sceneSlug) return;
    IMAGE.montrer(data);
  }, "show_image");

  // Aperçu local (`?preview=1`) : rendre un widget SANS passer par le flux.
  // Le flux part vers tous les clients connectés — donc vers l'OBS du streamer :
  // régler une couleur ou une animation ne doit pas s'afficher en plein live.
  // Le crochet n'existe que sous ce paramètre, et n'émet rien.
  if (new URLSearchParams(location.search).has("preview")) {
    window.__overlayPreview = {
      showWidget, say, showThinking, react,
      // Les deux zones qui ne passent pas par un builder : sans elles, l'aperçu
      // local ne pouvait rien montrer de la moitié de la page.
      rotateur: ROTATEUR, image: IMAGE,
      kinds: () => Object.keys(BUILDERS),
    };
  }


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
