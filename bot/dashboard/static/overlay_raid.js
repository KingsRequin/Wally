/* La fête d'un raid — la seconde la plus forte d'un live.
 *
 * Des inconnus débarquent d'un coup, et quelqu'un mérite d'être remercié par
 * son nom. Jusqu'ici l'overlay répondait par deux canons de confettis ; l'owner
 * a demandé le 2026-08-21 « plus de confettis, des lights, des effets ».
 *
 * Ce qui est ici, c'est la PRISE D'ÉCRAN : une couche plein cadre qui vit 4,2 s
 * — flash, faisceaux de projecteurs, vignette dorée, trois vagues de confettis
 * et des serpentins — puis disparaît du DOM. La carte, elle, reste ses 10 s.
 *
 * La secousse porte sur `#stage`, donc sur l'HABILLAGE. L'image du jeu ne bouge
 * pas : la source navigateur d'OBS ne dessine que cette page. Le streamer ne
 * voit rien de tout ça pendant qu'il joue — l'overlay s'adresse aux viewers.
 *
 * Le module ne connaît PAS la palette : `overlay.js` la lui passe (`token()`).
 * La recopier ici en ferait une seconde source de vérité, qui divergerait au
 * premier ajustement de couleur.
 */
(() => {
  "use strict";

  // Ce que dure la couche d'effets. Au-delà, la fête mange le jeu ; en deçà,
  // elle passe avant que le viewer ait tourné les yeux vers le nom.
  const DUREE_MS = 4200;

  // La secousse est courte par nature : c'est un impact, pas un tremblement.
  const SECOUSSE_MS = 420;

  // Le compte ne dépend PLUS du nombre de raiders. Arbitrage de l'owner le
  // 2026-08-21, contre trois paliers et contre une montée continue : « toujours
  // à fond ». Un raid de 3 mérite la même fête qu'un raid de 300.
  //
  // Aucune salve ne part du CENTRE : les particules retomberaient sur la carte
  // et masqueraient le nom, qui est tout l'objet du widget. Les canons tirent
  // des bas-côtés vers le haut, et du plafond vers le bas.
  //
  // `t` est le retard de la salve. Toutes sont tirées AVANT la fin de la
  // couche : une salve lâchée après coup ferait pleuvoir des confettis sur un
  // écran redevenu calme.
  const SALVES = [
    // ── Vague 1, à l'instant du flash : les quatre coins d'un coup.
    { t: 0, particleCount: 95, angle: 62, spread: 68, startVelocity: 58,
      origin: { x: 0.06, y: 0.96 }, scalar: 0.95, ticks: 260 },
    { t: 0, particleCount: 95, angle: 118, spread: 68, startVelocity: 58,
      origin: { x: 0.94, y: 0.96 }, scalar: 0.95, ticks: 260 },
    { t: 0, particleCount: 60, angle: 250, spread: 80, startVelocity: 38,
      origin: { x: 0.22, y: -0.08 }, scalar: 0.9, ticks: 240 },
    { t: 0, particleCount: 60, angle: 290, spread: 80, startVelocity: 38,
      origin: { x: 0.78, y: -0.08 }, scalar: 0.9, ticks: 240 },

    // ── Serpentins : ils FLOTTENT au lieu de retomber. Gravité basse,
    //    décroissance haute, dérive latérale, gros `scalar` — ce sont des
    //    rubans, et ils restent en l'air bien après les confettis.
    { t: 60, particleCount: 22, angle: 60, spread: 55, startVelocity: 34,
      origin: { x: 0.12, y: 0.72 }, scalar: 2.2, ticks: 420,
      gravity: 0.32, decay: 0.93, drift: 0.9 },
    { t: 60, particleCount: 22, angle: 120, spread: 55, startVelocity: 34,
      origin: { x: 0.88, y: 0.72 }, scalar: 2.2, ticks: 420,
      gravity: 0.32, decay: 0.93, drift: -0.9 },

    // ── Vague 2 : la relance, pendant que la première retombe.
    { t: 700, particleCount: 80, angle: 68, spread: 78, startVelocity: 52,
      origin: { x: 0.14, y: 0.98 }, scalar: 1, ticks: 240 },
    { t: 700, particleCount: 80, angle: 112, spread: 78, startVelocity: 52,
      origin: { x: 0.86, y: 0.98 }, scalar: 1, ticks: 240 },

    // ── Vague 3 : la dernière, plus haute et plus large — elle couvre l'écran
    //    au moment où la vignette repulse.
    { t: 1500, particleCount: 65, angle: 75, spread: 100, startVelocity: 46,
      origin: { x: 0.2, y: 1.0 }, scalar: 1.05, ticks: 220 },
    { t: 1500, particleCount: 65, angle: 105, spread: 100, startVelocity: 46,
      origin: { x: 0.8, y: 1.0 }, scalar: 1.05, ticks: 220 },
    { t: 1500, particleCount: 45, angle: 270, spread: 120, startVelocity: 30,
      origin: { x: 0.5, y: -0.1 }, scalar: 0.85, ticks: 260 },
  ];

  // Les trois couches de lumière. L'ordre est celui du document : la vignette
  // est écrite en dernier, elle passe donc par-dessus les faisceaux.
  const COUCHES = ["raid-flash", "raid-faisceaux", "raid-vignette"];

  // La couche en place, s'il y en a une, et les minuteurs qu'elle a armés.
  let couche = null;
  let secoue = null;
  const minuteurs = [];

  /* Coupe la fête en cours et remet la page comme avant.
   *
   * Appelée aussi bien par le minuteur de fin que par un SECOND raid arrivé
   * dans la foulée. Les minuteurs en attente sont annulés : sans ça, un raid
   * coupé continuerait de cracher ses vagues de confettis sur un écran calme,
   * et le nettoyage du premier retirerait la couche du second.
   */
  function arreter() {
    for (const id of minuteurs) clearTimeout(id);
    minuteurs.length = 0;
    if (couche && couche.parentNode) couche.parentNode.removeChild(couche);
    couche = null;
    if (secoue) {
      secoue.classList.remove("raid-secousse");
      secoue = null;
    }
  }

  function creerCouche() {
    const fx = document.createElement("div");
    fx.id = "raid-fx";
    // Rien à annoncer : c'est de la lumière, pas de l'information.
    fx.setAttribute("aria-hidden", "true");
    for (const nom of COUCHES) {
      const n = document.createElement("div");
      n.className = nom;
      fx.appendChild(n);
    }
    return fx;
  }

  /* L'habillage encaisse le choc. */
  function secouer(cible) {
    cible.classList.remove("raid-secousse");
    // Sans ce reflow, un second raid dans la même seconde ne secouerait rien :
    // la classe n'aurait jamais quitté le nœud, donc l'animation ne repartirait
    // pas. Même patron que le hochement de l'avatar.
    void cible.offsetWidth;
    cible.classList.add("raid-secousse");
    secoue = cible;
    // Retirée par MINUTEUR et jamais sur `animationend` : une animation
    // relancée émet `animationcancel`, et l'événement de fin n'arrive alors
    // jamais — piège déjà payé sur les classes `animate__`.
    minuteurs.push(setTimeout(() => {
      cible.classList.remove("raid-secousse");
      secoue = null;
    }, SECOUSSE_MS));
  }

  function tirerConfettis(couleurs) {
    // Absente si le fichier n'a pas été servi : un overlay sans confettis reste
    // un overlay, alors qu'une exception ici emporterait toute la fête.
    const tir = typeof window !== "undefined" ? window.confetti : null;
    if (typeof tir !== "function") return;
    const teintes = Array.isArray(couleurs) && couleurs.length ? couleurs : null;
    for (const salve of SALVES) {
      const params = Object.assign({}, salve, { disableForReducedMotion: false });
      delete params.t;
      // Sans teintes, canvas-confetti garde les siennes : mieux qu'une palette
      // recopiée ici, qui vieillirait sans que personne ne le voie.
      if (teintes) params.colors = teintes;
      // La première vague part SYNCHRONE, avec le flash. Passée par un
      // `setTimeout(0)`, elle serait décalée d'une frame — et un flash qui
      // précède ses confettis se lit comme deux événements, pas comme un.
      if (!salve.t) tir(params);
      else minuteurs.push(setTimeout(() => tir(params), salve.t));
    }
  }

  function sonner() {
    const sons = typeof window !== "undefined" ? window.WallySons : null;
    if (!sons) return;
    // Relu à chaque raid, comme pour le spam : l'owner dépose ses fichiers
    // pendant le live. Ce chargement-là sert au raid SUIVANT — celui-ci joue ce
    // qui est déjà décodé, et se tait si le dossier est encore vide.
    if (typeof sons.charger === "function") sons.charger();
    if (typeof sons.raid === "function") sons.raid();
  }

  /* Lance la fête. `hote` est `#stage` : la couche vit DEDANS, jamais sur
   * `<body>`. `#stage` ne porte aucun `transform` hors secousse — donc pas le
   * piège du bloc conteneur payé sur `.meme` et `.virus-popup` — et il hérite
   * de `#stage.hidden` : overlay masqué, pas de fête fantôme.
   */
  function celebrer(hote, couleurs) {
    const cible = hote
      || (typeof document !== "undefined" && document.getElementById("stage"));
    if (!cible) return false;
    arreter();
    couche = creerCouche();
    cible.appendChild(couche);
    secouer(cible);
    tirerConfettis(couleurs);
    sonner();
    minuteurs.push(setTimeout(arreter, DUREE_MS));
    return true;
  }

  window.WallyRaid = { celebrer, arreter, SALVES, COUCHES,
                       DUREE_MS, SECOUSSE_MS };
})();
