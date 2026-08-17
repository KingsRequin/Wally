/* Spam de popups « virus » — le séquencement, sans DOM.
 *
 * Demande de l'owner : « popup de virus qui spam et qui se superpose, ça
 * commence doucement et ça accélère ». Deux gabarits mêlés — fausses alertes et
 * fenêtres à meme — qui s'empilent SANS JAMAIS disparaître : ici c'est
 * l'accumulation qui fait le gag, pas le mouvement. L'avalanche de memes, elle,
 * fait tomber ; les deux coexistent le temps que l'owner choisisse.
 *
 * Chargé APRÈS `overlay_avalanche.js`, dont il réutilise le mélange sans remise
 * (`WallyAvalanche.ordre`) : deux tirages maison auraient divergé au premier
 * correctif.
 */
(() => {
  "use strict";

  // Le rythme, d'un bout à l'autre. Une seconde entre deux fenêtres au départ,
  // un dixième à l'arrivée : en dessous de ce rapport, l'accélération ne se voit
  // pas, au-delà le début paraît en panne.
  const DEBUT_MS = 1000;
  const FIN_MS = 100;

  // Elles ne disparaissent jamais : chaque fenêtre reste un nœud vivant, avec
  // son image, sur la machine qui ENCODE le live. C'est ce qui borne le
  // spectacle, pas la durée.
  const PLAFOND = 80;

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
  ];

  /* Les instants d'ouverture, en millisecondes depuis le début du spam.
   *
   * L'intervalle décroît géométriquement de `DEBUT_MS` à `FIN_MS` sur toute la
   * fenêtre : chaque fenêtre arrive plus vite que la précédente, sans palier.
   */
  function rythme(dureeS) {
    const total = Math.max(0, (Number(dureeS) || 0) * 1000);
    const instants = [];
    let t = 0;
    let pas = DEBUT_MS;
    // Combien de crans pour aller de 1 s à 0,1 s : on l'ignore à l'avance
    // puisque la fenêtre commande. La raison est fixée sur une estimation du
    // nombre de fenêtres tenant dans la durée, puis appliquée telle quelle.
    const estimation = Math.max(2, Math.min(PLAFOND,
      Math.round(total / ((DEBUT_MS + FIN_MS) / 2))));
    const raison = Math.pow(FIN_MS / DEBUT_MS, 1 / (estimation - 1));
    while (t <= total && instants.length < PLAFOND) {
      instants.push(Math.round(t));
      t += pas;
      pas = Math.max(FIN_MS, pas * raison);
    }
    return instants;
  }

  /* Ce qui s'ouvre à chaque instant : une alerte ou un meme.
   *
   * Les memes sont tirés sans remise (`WallyAvalanche.ordre`) et le tirage
   * bascule sur les alertes dès que le stock est épuisé — ou vide dès le début,
   * auquel cas ce spectacle marche quand même, contrairement à l'avalanche.
   */
  function fenetres(instants, medias) {
    const stock = (window.WallyAvalanche
      ? window.WallyAvalanche.ordre(medias)
      : (Array.isArray(medias) ? medias.slice() : []));
    let prochainMeme = 0;
    let derniereAlerte = -1;
    return (instants || []).map((t, i) => {
      const veutMeme = Math.random() >= PART_ALERTES;
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

  /* Où s'ouvre une fenêtre, en pixels, entièrement dans le cadre.
   *
   * Le tirage tient compte de sa TAILLE : sans ça, une popup large sort par la
   * droite et ressemble à un bug de rendu — le piège déjà corrigé sur
   * l'avalanche. Plus grande que le cadre, elle part du coin plutôt que d'une
   * position négative tirée au hasard.
   */
  function place(largeur, hauteur, cadreL, cadreH) {
    const libreX = Math.max(0, (Number(cadreL) || 0) - (Number(largeur) || 0));
    const libreY = Math.max(0, (Number(cadreH) || 0) - (Number(hauteur) || 0));
    return { x: Math.round(Math.random() * libreX),
             y: Math.round(Math.random() * libreY) };
  }

  window.WallyVirus = { rythme, fenetres, place,
                        PLAFOND, PART_ALERTES, DEBUT_MS, FIN_MS };
})();
