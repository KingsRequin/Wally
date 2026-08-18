/* Spam de popups « virus » — le séquencement, sans DOM.
 *
 * Demande de l'owner : « popup de virus qui spam et qui se superpose, ça
 * commence doucement et ça accélère ». Deux gabarits mêlés — fausses alertes et
 * fenêtres à meme — qui s'empilent SANS JAMAIS disparaître : ici c'est
 * l'accumulation qui fait le gag, pas le mouvement. L'avalanche de memes, elle,
 * fait tomber ; les deux coexistent le temps que l'owner choisisse.
 *
 * L'avalanche de memes, sa rivale, a été retirée le 2026-08-18 : l'owner a
 * tranché entre les deux après les avoir vues tourner. Le mélange sans remise
 * qu'elle portait vit désormais ici.
 */
(() => {
  "use strict";

  // Le rythme, d'un bout à l'autre. Une seconde entre deux fenêtres au départ,
  // un dixième à l'arrivée : en dessous de ce rapport, l'accélération ne se voit
  // pas, au-delà le début paraît en panne.
  const DEBUT_MS = 1000;
  const FIN_MS = 100;

  // Combien de fenêtres restent OUVERTES en même temps. Au-delà, le rendu ferme
  // la plus ancienne.
  //
  // « Elles doivent toutes s'empiler » (owner) : à 80, les deux tiers se
  // refermaient en cours de route — un arbitrage de perf pris sans lui, chaque
  // fenêtre étant un nœud vivant avec son image sur la machine qui ENCODE le
  // live. Le filet est donc remonté AU-DESSUS de ce que le dossier produit :
  // 134 memes ouvrent 224 fenêtres, il en faudrait plus de 240 dans le dossier
  // pour qu'une seule se referme. À rearbitrer si le dossier double.
  const PLAFOND_VIVANTES = 420;

  // Garde-fou de boucle, pas un réglage : `rythme()` n'est plus borné que par
  // le temps, et une durée délirante ne doit pas figer la page du live.
  const GARDE_FOU = 2000;

  // Part de fausses alertes dans le mélange. Le reste va aux memes — et bascule
  // entièrement sur les alertes quand le dossier est vide.
  const PART_ALERTES = 0.4;

  /* Les gabarits d'alerte. Du gag assumé, écrit en dur : ce n'est pas du
   * comportement, et le faire produire par un modèle coûterait un appel LLM
   * pour des libellés qu'on veut stables d'un achat à l'autre.
   */
  const ALERTES = [
    ["⚠ Alerte de sécurité", "WALLY.EXE a détecté {n} virus sur ce PC."],
    ["Erreur système", "Impossible de localiser le sang-froid d'Azraël."],
    ["⚠ Attention", "Votre inscription à Apex a expiré il y a {n} jours."],
    ["Analyse antivirus", "{n} fichiers infectés. Formatage dans 3 secondes."],
    ["Erreur fatale", "meme.exe a cessé de fonctionner."],
    ["⚠ Avertissement", "Une pièce de votre matériel est un grille-pain."],
    ["Mise à jour requise", "Wally 2.0 disponible. Redémarrage dans {n} s."],
    ["Erreur critique", "Le dossier « aim » est introuvable."],
    ["⚠ Alerte réseau", "{n} spectateurs tentent d'accéder à vos memes."],
    ["Défragmentation", "Réorganisation de {n} % de votre dignité…"],
    ["Erreur 0x{n}", "Opération impossible : le chat rigole trop fort."],
    ["⚠ Disque plein", "Il ne reste plus que {n} Ko pour vos clips."],
    ["Pilote manquant", "Aucun pilote trouvé pour « viser correctement »."],
    ["⚠ Surchauffe", "Votre carte graphique demande {n} jours de congés."],
    ["Assistant Wally", "On dirait que tu essaies de gagner. Besoin d'aide ?"],
    ["Erreur de lecture", "Secteur défectueux : votre dernier fight."],
    ["⚠ Sauvegarde", "Impossible de sauvegarder. Ce moment restera gênant."],
    ["Licence expirée", "Votre droit de râler expire dans {n} secondes."],
    ["⚠ Alerte mémoire", "Trop de memes ouverts. Fermez l'un d'eux. Ou pas."],
    ["Erreur d'exécution", "L'objet « stratégie » n'a pas été initialisé."],
    ["Nettoyage de disque", "{n} Go de clips ratés peuvent être supprimés."],
    ["⚠ Périphérique", "Souris déconnectée. Ça expliquerait beaucoup."],
    ["Analyse terminée", "Aucune menace détectée. Le danger, c'est toi."],
    ["Erreur 404", "Loot introuvable. Vérifiez le sol, encore."],
    ["⚠ Batterie faible", "Motivation à {n} %. Branchez un café."],
    ["Rapport d'erreurs", "Envoyer ce fight à Respawn ? [Oui] [Oui]"],
    ["⚠ Conflit logiciel", "wally.exe et silence.exe ne peuvent coexister."],
    ["Installation", "Installation de la patience… {n} % — annulée."],
    ["⚠ Fichier corrompu", "highlight_{n}.mp4 est illisible. Comme la partie."],
    ["Pare-feu", "{n} tentatives de tir bloquées. Toutes les vôtres."],
    ["Erreur de synchro", "Votre ping et vos réflexes ne sont pas d'accord."],
    ["⚠ Espace mémoire", "Souvenir de la victoire introuvable dans le cache."],
  ];

  /* L'écran bleu de fin. Autant de finals que d'humeurs : figé, on le revoit au
   * troisième achat et il ne fait plus rire. Le code d'erreur en majuscules est
   * le détail qui le fait RECONNAÎTRE comme un BSOD.
   */
  const BSODS = [
    ["Ton PC a rencontré un problème et doit redémarrer.",
     "Il en a surtout marre de tes memes.", "MEME_OVERFLOW"],
    ["Ton PC a abandonné.",
     "Il a vu le dernier fight et il préfère s'éteindre.", "CRITICAL_CRINGE"],
    ["Une erreur est survenue.",
     "Nous cherchons encore laquelle. Ça peut prendre un moment.",
     "UNKNOWN_SKILL_ISSUE"],
    ["Arrêt d'urgence.",
     "Trop de fenêtres ouvertes, pas assez de neurones libres.",
     "TOO_MANY_POPUPS"],
    ["Ton PC a rencontré Wally et doit redémarrer.",
     "Ce n'est pas un bug, c'est une opinion.", "WALLY_WAS_HERE"],
    ["Redémarrage nécessaire.",
     "Le grille-pain a pris le contrôle. Tout va bien.", "TOASTER_TAKEOVER"],
    ["Erreur irrécupérable.",
     "Le module « viser » n'a jamais été installé.", "AIM_NOT_FOUND"],
    ["Ton PC fait une pause.",
     "Le chat rigolait trop fort, il n'entendait plus rien.",
     "CHAT_DENIAL_OF_SERVICE"],
  ];

  /* Les instants d'ouverture, en millisecondes depuis le début du spam.
   *
   * L'intervalle décroît géométriquement de `DEBUT_MS` à `FIN_MS` sur toute la
   * fenêtre : chaque fenêtre arrive plus vite que la précédente, sans palier.
   */
  // Combien d'ouvertures pour passer de `DEBUT_MS` à `FIN_MS`. La montée en
  // régime dure toujours autant ; ce qui s'allonge avec le stock, c'est le
  // plateau qui suit.
  const CRANS = 24;
  const RAISON = Math.pow(FIN_MS / DEBUT_MS, 1 / (CRANS - 1));

  function rythme(dureeS) {
    const total = Math.max(0, (Number(dureeS) || 0) * 1000);
    const instants = [];
    let t = 0;
    let pas = DEBUT_MS;
    while (t <= total && instants.length < GARDE_FOU) {
      instants.push(Math.round(t));
      t += pas;
      pas = Math.max(FIN_MS, pas * RAISON);
    }
    return instants;
  }

  /* La durée qu'il faut pour ouvrir `combien` fenêtres.
   *
   * L'inverse exact de `rythme()` : la montée en régime, puis le plateau. Le
   * serveur tient la même règle de son côté (`_duree_virus`) pour dimensionner
   * la carte — deux écritures d'un même calcul, dont l'accord est tenu par un
   * test plutôt que par la discipline.
   */
  function dureePour(combien) {
    const n = Math.max(1, Number(combien) || 0);
    let t = 0;
    let pas = DEBUT_MS;
    for (let i = 1; i < n; i++) {
      t += pas;
      pas = Math.max(FIN_MS, pas * RAISON);
    }
    return Math.ceil(t / 1000);
  }

  /* Le stock dans un ordre mêlé, en entier, une fois chacun.
   *
   * Copie d'abord : la liste vient du rotateur (`window.WallyRotationMedias`),
   * qui s'en sert pour son propre défilé. La mélanger en place mêlerait aussi
   * le sien. Et un tirage AVEC remise n'épuise pas un stock — sur 134 médias,
   * il en laisse environ 40 % au vestiaire pendant que d'autres repassent trois
   * fois. Un stock se PARCOURT.
   */
  function ordre(medias) {
    const stock = Array.isArray(medias) ? medias.slice() : [];
    for (let i = stock.length - 1; i > 0; i--) {          // Fisher-Yates
      const j = Math.floor(Math.random() * (i + 1));
      const t = stock[i]; stock[i] = stock[j]; stock[j] = t;
    }
    return stock;
  }

  /* Ce qui s'ouvre à chaque instant : une alerte ou un meme.
   *
   * Les memes sont tirés sans remise et le tirage bascule sur les alertes dès
   * que le stock est épuisé — ou vide dès le début, auquel cas ce spectacle
   * marche quand même : les fausses alertes se suffisent.
   */
  function fenetres(instants, medias) {
    const stock = ordre(medias);
    const plan = instants || [];
    let prochainMeme = 0;
    let derniereAlerte = -1;
    return plan.map((t, i) => {
      const restantes = plan.length - i;
      const memesRestants = stock.length - prochainMeme;
      // Un tirage à pile ou face ne garantit RIEN : sur 224 ouvertures à 60 %,
      // le nombre de memes varie d'une dizaine autour de 134 — une fois sur
      // deux, le dossier n'était pas épuisé. Dès qu'il reste juste assez de
      // place pour les memes qui attendent, on cesse de tirer au sort.
      const veutMeme = memesRestants >= restantes || Math.random() >= PART_ALERTES;
      if (veutMeme && prochainMeme < stock.length) {
        return { t, genre: "meme", media: stock[prochainMeme++],
                 titre: nomCourt(stock[prochainMeme - 1]), message: "" };
      }
      // Jamais deux fois le même texte à la suite : deux alertes identiques
      // l'une sous l'autre cassent l'illusion du spam.
      let k = Math.floor(Math.random() * ALERTES.length);
      if (k === derniereAlerte) k = (k + 1) % ALERTES.length;
      derniereAlerte = k;
      const n = 1 + Math.floor(Math.random() * 999);
      return { t, genre: "alerte", titre: ALERTES[k][0],
               message: ALERTES[k][1].replace("{n}", String(n)) };
    });
  }

  /* Le nom du fichier, en guise de titre de fenêtre. C'est ce qui fait lire la
   * vignette comme une pièce jointe piégée plutôt que comme une image posée. */
  function nomCourt(media) {
    const nom = String((media && media.nom) || "meme");
    return nom.length > 28 ? nom.slice(0, 27) + "…" : nom;
  }

  // La grille du semeur. Assez fine pour que l'écran se remplisse par petites
  // touches, assez grossière pour qu'une popup tienne dans sa cellule.
  const COLONNES = 5;
  const LIGNES = 4;

  /* Un semeur pour un spectacle : il répartit les fenêtres sur TOUT l'écran.
   *
   * « Elles se stackent beaucoup vers le centre on dirait » (owner) — et c'est
   * géométrique, pas une impression. Un coin tiré uniformément dans
   * `[0, cadre - taille]` met le CENTRE de la fenêtre dans un rectangle rétréci
   * de sa demi-taille : une popup de 370 px de haut sur un écran de 1080 ne
   * peut jamais avoir son centre au-dessus de 185 px ni sous 895. Les bords se
   * dégarnissent, le milieu double.
   *
   * On parcourt donc une grille de cellules dans un ordre mêlé, remêlé à chaque
   * tour : chaque zone reçoit sa fenêtre avant qu'aucune n'en reçoive deux, et
   * deux popups de suite ne se collent plus l'une sur l'autre.
   */
  function semeur(cadreL, cadreH) {
    const L = Number(cadreL) || 1920;
    const H = Number(cadreH) || 1080;
    let cellules = [];
    let rang = 0;

    function remelanger() {
      cellules = [];
      for (let c = 0; c < COLONNES; c++) {
        for (let l = 0; l < LIGNES; l++) cellules.push([c, l]);
      }
      for (let i = cellules.length - 1; i > 0; i--) {
        const j = Math.floor(Math.random() * (i + 1));
        const t = cellules[i]; cellules[i] = cellules[j]; cellules[j] = t;
      }
      rang = 0;
    }

    return {
      place(largeur, hauteur) {
        if (rang >= cellules.length) remelanger();
        const [c, l] = cellules[rang++];
        // La grille découpe l'espace des positions ADMISSIBLES, pas l'écran :
        // le coin d'une fenêtre haute ne peut pas descendre plus bas que
        // `H - hauteur`. Découper l'écran et rabattre ensuite ce qui dépasse
        // entassait les grandes fenêtres vers le haut — mesuré, 16 % des
        // centres dans le tiers haut contre 6 % dans le tiers bas. Ici il n'y a
        // plus rien à rabattre : chaque cellule est atteignable telle quelle.
        const libreX = Math.max(0, L - (Number(largeur) || 0));
        const libreY = Math.max(0, H - (Number(hauteur) || 0));
        return { x: Math.round((c + Math.random()) * libreX / COLONNES),
                 y: Math.round((l + Math.random()) * libreY / LIGNES) };
      },
    };
  }

  /* La durée qu'il faut pour montrer `nbMemes` memes, alertes comprises.
   *
   * Sert au ▶ du panneau, qui n'annonce aucune durée : ces deux spectacles
   * prennent l'écran entier, un essai n'y règle donc aucune position — il ne
   * sert qu'à JUGER l'effet, et il doit pour cela le montrer en entier. Un
   * essai plus court affichait 58 memes sur 135 et faisait conclure, à tort,
   * que le dossier ne passait pas.
   */
  function dureeSelonStock(nbMemes) {
    const memes = Math.max(0, Number(nbMemes) || 0);
    return dureePour(Math.ceil(memes / (1 - PART_ALERTES)) || 1);
  }

  /* Le final, tiré au sort. */
  function bsod() {
    const b = BSODS[Math.floor(Math.random() * BSODS.length)];
    return { titre: b[0], message: b[1], code: b[2] };
  }

  window.WallyVirus = { rythme, dureePour, dureeSelonStock, fenetres, ordre,
                        semeur, bsod,
                        PLAFOND_VIVANTES, GARDE_FOU, PART_ALERTES,
                        DEBUT_MS, FIN_MS, NB_ALERTES: ALERTES.length };
})();
