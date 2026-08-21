// bot/dashboard/static/overlay_admin.js
//
// Le panneau de mise en scène de l'overlay : la liste des scènes, la liste des
// éléments, et la surface où on les place.
//
// Écrit hors d'`app.js` — qui pèse déjà 5679 lignes — parce que ce seul panneau
// en vaut plusieurs centaines. `app.js` n'en connaît que trois lignes : le
// conteneur qu'il nous passe.
//
// Deux principes gouvernent le fichier :
//
//   1. **Rien ne part tout seul.** Une modification reste dans le navigateur
//      jusqu'à « Mettre à jour ». On règle la scène de fin pendant que le live
//      tourne sans que l'écran bouge d'un pixel. La case « Publier au fil de
//      l'eau » lève cette règle, et elle est DÉCOCHÉE par défaut : le cas
//      dangereux ne doit jamais être celui qu'on obtient sans rien faire.
//   2. **Aucune exception ne sort d'ici.** Un `throw` dans un montage casse
//      toutes les sections suivantes du panneau — c'est un incident déjà payé
//      ici (`buildSections`). `monter()` est synchrone et enveloppé ; le
//      chargement réseau vit dans sa propre promesse.
window.OverlayAdmin = (function () {
  "use strict";

  const URL_LAYOUT = "/api/admin/overlay/layout";
  const URL_APERCU = "/api/admin/overlay/preview";
  const CANVAS_W = 1920;
  // La hauteur logique de la page d'overlay. Elle ne sert qu'à l'AFFICHER dans
  // le badge : la surface, elle, tient son 16/9 du CSS (`aspect-ratio`).
  const CANVAS_H = 1080;
  // Au-delà, on considère que l'aperçu ne viendra pas et on reste sur les
  // rectangles nommés. Un aperçu absent ne doit jamais empêcher de placer.
  const APERCU_DELAI_MS = 8000;

  // Les slugs que les routes existantes occupent déjà (`/overlay-image`,
  // `/overlay-rotation`, `/api/.../version`, `/health`). Une scène qui en
  // prendrait un masquerait la route. Miroir de `SLUGS_RESERVES`
  // (bot/core/overlay_layout.py) — le serveur tranche, on évite juste de lui
  // proposer l'impossible.
  const SLUGS_RESERVES = ["image", "rotation", "version", "health"];

  // Les libellés lisibles NE SONT PAS écrits ici : ils viennent du serveur, avec
  // le layout (`bot/core/overlay_elements.py`, joint à la réponse du GET). Une
  // seconde table ici aurait dérivé de la première au premier widget ajouté, et
  // c'est justement le reproche auquel ce panneau répond — « apex prédateur ??
  // ». Une clé sans libellé s'affiche telle quelle plutôt que de disparaître.

  // L'encombrement supposé de chaque élément vit dans `WallyLayout` : la page
  // d'overlay s'en sert AUSSI (les repères de « Tout afficher »), et deux
  // tables auraient divergé au premier widget ajouté. Le repli couvre le cas où
  // `overlay_layout.js` n'aurait pas été servi.
  const TAILLE_REPLI = [400, 260];

  function tailleElement(cle) {
    const W = window.WallyLayout;
    return (W && typeof W.taille === "function" && W.taille(cle)) || TAILLE_REPLI;
  }

  /** L'encombrement d'un élément, MESURÉ quand c'est possible.
   *
   *  La table de `WallyLayout` n'était qu'une supposition, et elle se voyait :
   *  le repère du meme occupait 570 × 430 px de la surface pour un meme qui en
   *  faisait 200 × 220. Un repère qui ment sur la taille ment sur TOUT ce qui
   *  en découle — l'alignement colle la mauvaise boîte au bord, la répartition
   *  calcule de faux espaces, le détecteur de débordement se trompe.
   *
   *  L'aperçu est la vraie page d'overlay, de même origine : on y lit donc la
   *  taille réelle (`mesures`, alimentée par `mesurerTout()`). Le repli reste la
   *  table — un aperçu absent, ou un widget qui n'affiche rien, n'a pas de
   *  taille à lire. `reelle` dit LAQUELLE des deux on rend : le repère le
   *  montre (traits pointillés) plutôt que de faire croire à une mesure qu'on
   *  n'a pas.
   */
  function tailleRendue(cle) {
    const m = mesures[cle];
    if (m && m[0] > 0 && m[1] > 0) return { taille: m, reelle: true };
    // Les widgets à média (`meme`, `rotator`, `image`) ne sont mesurables QUE
    // par le serveur, sur le dossier : le navigateur n'y a pas accès. Leur
    // boîte est donc une vraie mesure, et l'annoncer en pointillés comme une
    // supposition faisait mentir le repère dans l'autre sens.
    const W = window.WallyLayout;
    const servie = !!(W && typeof W.estMesuree === "function" && W.estMesuree(cle));
    return { taille: tailleElement(cle), reelle: servie };
  }

  // La grille de neuf cases, dans l'ordre où elle s'affiche.
  const ANCRAGES = [
    "top-left", "top-center", "top-right",
    "middle-left", "center", "middle-right",
    "bottom-left", "bottom-center", "bottom-right",
  ];

  // Le même ancrage en français, et sa flèche. Les clés du modèle sont en
  // anglais et le resteront — elles voyagent jusqu'à la page d'overlay —, mais
  // « ancrage bottom-left → top-left » dans un journal de modifications ne se
  // lit pas. La flèche sert la grille 3 × 3 des réglages, qui n'affichait
  // jusqu'ici que des carrés muets.
  const LIBELLES_ANCRAGE = {
    "top-left": ["haut-gauche", "\u2196"],
    "top-center": ["haut-centre", "\u2191"],
    "top-right": ["haut-droite", "\u2197"],
    "middle-left": ["milieu-gauche", "\u2190"],
    "center": ["centre", "\u00b7"],
    "middle-right": ["milieu-droite", "\u2192"],
    "bottom-left": ["bas-gauche", "\u2199"],
    "bottom-center": ["bas-centre", "\u2193"],
    "bottom-right": ["bas-droite", "\u2198"],
  };

  function nomAncrage(cle) {
    return (LIBELLES_ANCRAGE[cle] || [cle])[0];
  }

  function flecheAncrage(cle) {
    return (LIBELLES_ANCRAGE[cle] || [null, "\u00b7"])[1];
  }

  // ── Les bornes et les pas de la manipulation ────────────────────────────
  //
  // Les mêmes bornes que le modèle (`bot/core/overlay_layout.py`). Elles sont
  // appliquées À LA SAISIE et pas seulement à l'enregistrement : sinon le
  // repère continue de suivre le pointeur hors du cadre, puis revient en
  // arrière au relâchement — on ne sait plus ce qu'on a posé.
  const POS_MIN = 0, POS_MAX = 100;
  const ECHELLE_MIN = 0.2, ECHELLE_MAX = 2.0;

  // Ce que le SERVEUR ne peut pas dire : comment un réglage se NOMME et se
  // manipule à l'écran. Les bornes, les choix, les défauts et surtout les
  // PORTÉES — qui porte quoi — viennent du GET (`portees`, `animations`), et
  // restent l'unique autorité. Une seconde table de bornes en JavaScript
  // divergeait au premier ajustement : le panneau laissait alors saisir une
  // valeur que le serveur ramène en silence, on croyait avoir réglé, rien ne
  // bougeait, et rien ne le disait.
  //
  // `nature` : "nombre" par défaut · "booleen" · "choix" (avec `menu`, le
  // catalogue d'animations dont il tire ses options).
  // `auto` : le libellé du zéro, quand zéro ne veut pas dire zéro. Sans lui, le
  // streamer lit « durée : 0 » et comprend « ne s'affiche pas ».
  const CHAMPS = {
    opacite: { label: "Opacité", pas: 0.05,
      aide: "La transparence de l'élément. 1 = parfaitement opaque." },
    rotation: { label: "Inclinaison", pas: 1, unite: "°",
      aide: "L'élément s'incline autour de son centre : il ne se déplace pas." },
    miroir: { label: "Miroir", nature: "booleen",
      aide: "Retourne l'élément de gauche à droite." },
    largeur_max: { label: "Largeur max", pas: 10, unite: " px", auto: "Auto",
      aide: "En pixels du canvas 1920, à l'échelle de l'élément. Auto = la "
          + "largeur de son contenu, plafonnée à 92 % de l'écran." },
    duree: { label: "Durée", pas: 0.5, unite: " s", auto: "Auto",
      aide: "Combien de temps l'élément reste à l'écran. Auto = c'est Wally "
          + "qui décide, comme avant. Une partie en cours n'est jamais coupée." },
    pause: { label: "Pause", pas: 0.5, unite: " s",
      aide: "Combien de temps la zone reste vide entre deux memes. 0 les "
          + "enchaîne." },
    delai: { label: "Délai", pas: 0.5, unite: " s",
      aide: "Combien de temps on attend avant de le faire apparaître." },
    anim_duree: { label: "Durée d'anim.", pas: 0.05, unite: " s",
      aide: "La durée de l'entrée et de la sortie. La carte suivante attend la "
          + "fin de la sortie pour entrer." },
    anim_entree: { label: "Entrée", nature: "choix", menu: "entree",
      aide: "Comment l'élément apparaît." },
    anim_sortie: { label: "Sortie", nature: "choix", menu: "sortie",
      aide: "Comment l'élément s'en va." },
    anim_insistance: { label: "Insistance", nature: "choix", menu: "insistance",
      aide: "Un effet rejoué en boucle pendant tout l'affichage." },
  };

  // Les champs que TOUT élément porte par construction, hors du système de
  // portées : ils vivent dans `_el()` et non dans les tables de validation.
  const PLACEMENT = ["x", "y", "scale", "anchor"];

  /** Les réglages que CET élément porte, et comment chacun se valide.
   *
   *  Rend `{ champ: {mini, maxi, auto} | {choix: [...]} | null }`. Les quatre
   *  universels y sont toujours ; les autres seulement si l'élément les porte.
   *  Tout vient du serveur : le panneau ne devine rien.
   */
  function portesDe(cle) {
    const p = etat.portees || {};
    const out = Object.assign({}, p.universels || {});
    Object.keys((p.champs_propres || {})[cle] || {}).forEach(function (nom) {
      out[nom] = p.champs_propres[cle][nom];
    });
    Object.keys((p.champs_choix || {})[cle] || {}).forEach(function (nom) {
      out[nom] = { choix: p.champs_choix[cle][nom] };
    });
    return out;
  }
  // Une flèche vaut 0,1 % — environ deux pixels sur 1920. Avec Maj, 1 %.
  const PAS_FIN = 0.1, PAS_GROS = 1;
  // Le pas de la grille d'aimantation, en pourcentage, et sa portée en PIXELS
  // d'écran : exprimée en pourcentage, elle accrocherait deux fois plus fort
  // sur une surface deux fois plus petite.
  const GRILLE = 10, AIMANT_PX = 8;
  // Les graduations des deux règles, en pourcentage. Cinq repères : au-delà,
  // les chiffres se touchent sur une règle de 18 px de haut.
  const GRADUATIONS = [0, 25, 50, 75, 100];
  const COINS = ["nw", "ne", "sw", "se"];
  const TOUCHES = {
    ArrowLeft: [-1, 0], ArrowRight: [1, 0], ArrowUp: [0, -1], ArrowDown: [0, 1],
  };

  /** L'état du panneau.
   *
   *  `brouillon` est un COMPTEUR : le nombre de modifications non publiées.
   *  Zéro vaut « rien en attente ». `direct` porte la case « Publier au fil de
   *  l'eau » ; toujours faux au chargement, et JAMAIS retenu d'une visite à
   *  l'autre — une préférence qui survit ferait qu'on ouvre le panneau en plein
   *  live avec la publication immédiate déjà armée, sans l'avoir demandé.
   *
   *  `publie` est le modèle À L'ANTENNE, sérialisé, tel que le serveur nous l'a
   *  rendu au dernier aller-retour. Il sert deux fois : à repérer qu'un autre
   *  onglet a publié entre-temps, et à garder un cran d'annulation.
   *  `precedent` est ce même modèle d'AVANT la dernière publication.
   */
  const etat = {
    layout: null,
    libelles: {},   // clé → {nom, description}, servi par le GET du layout
    // Qui porte quel réglage, avec quelles bornes, et le catalogue des
    // animations. Servis par le même GET, jamais recopiés ici.
    portees: {},
    animations: {},
    // La mise en scène D'ORIGINE, servie par le même GET (`?defauts=1`) et mise
    // en cache pour la visite. JAMAIS écrite ici : `ELEMENTS` bouge à chaque
    // widget ajouté, et une seconde table dans le navigateur aurait divergé de
    // la première — « Réinitialiser » aurait alors rendu une position d'origine
    // qui n'en est plus une. `null` tant qu'on n'a pas eu besoin d'elle.
    defauts: null,
    // Les paramètres d'essai de chaque widget (`_ECHANTILLONS`, côté serveur),
    // servis par le même GET. Ils alimentent le banc de mesure, qui monte
    // chaque widget dans l'aperçu pour en lire la taille sans le déclencher.
    echantillons: null,
    slugCourant: null,
    // `elementCourant` est le PRINCIPAL de la sélection : celui dont la barre de
    // réglages montre les valeurs, celui qui porte les poignées, et celui qu'on
    // suit du pointeur quand on déplace un bloc. Il est TOUJOURS dans
    // `selection` tant qu'il n'est pas nul — les deux se posent ensemble
    // (`poserPrincipal`, `selectionner`), jamais l'un sans l'autre.
    elementCourant: null,
    selection: [],       // les clés retenues, l'élément principal compris
    ancreSelection: null,  // le point de départ d'un Maj+clic
    presse: null,          // les réglages copiés par C, collés par V
    // Les en-têtes de groupe repliés, par `slug/id`. DANS LE NAVIGATEUR ET PAS
    // DANS LE MODÈLE : plier une liste est un confort de lecture, pas une
    // décision de mise en scène. Rangé dans le modèle, ce serait une
    // modification de plus au compteur — donc quelque chose à publier — et un
    // pli fait ici changerait l'antenne. La contrepartie assumée : un F5
    // rouvre tous les groupes.
    replies: {},
    brouillon: 0,
    direct: false,
    publie: null,
    precedent: null,
    // Quand ce qui est à l'antenne y est parti, en ISO local, tel que le
    // serveur le range (`overlay:layout:maj`). `null` vaut « on ne sait pas » —
    // jamais publié depuis que la date est suivie, ou base muette — et le pied
    // de publication le dit ainsi plutôt que d'inventer une heure.
    majAntenne: null,
  };

  const noeuds = {};      // les nœuds du squelette, posés une fois
  const reperes = {};     // les rectangles de la surface, par clé d'élément
  let menuOuvert = null;  // le menu ⋮ déployé, s'il y en a un
  let menuHote = null;    // le bouton qui l'a ouvert — il le referme lui-même
  let manip = null;       // la manipulation en cours sur la surface, ou null
  let observateur = null; // ResizeObserver de la surface
  let glisse = null;      // la clé de l'élément en cours de glisser dans la liste
  let infobulle = null;   // l'unique bulle d'aide, posée sur <body>
  let apercuSlug = null;      // la scène actuellement chargée dans l'iframe
  let apercuMinuteur = null;  // le délai au bout duquel on bascule sur le repli
  let survole = null;         // la clé de l'élément survolé, liste OU surface
  let survoleOrigine = null;  // « liste » ou « surface » — le survol est à SENS
  let survoleMarques = [];    // les nœuds portant la marque, pour la retirer
                              // UNIQUE : la liste éclaire l'aperçu, pas l'inverse
  let raccourcisPoses = false;  // l'écouteur clavier du document, posé une fois

  /** Ce que la surface MONTRE. Dans le navigateur et pas dans le modèle : c'est
   *  un confort de lecture, pas une décision de mise en scène. Rangé dans le
   *  modèle, changer de vue serait une modification à publier.
   *
   *  `vue` : « les-deux » (le défaut), « apercu », « cadres ». `aides` : les
   *  repères posés SUR la surface, indépendants les uns des autres.
   */
  let vue = "les-deux";
  const aides = { grille: true, zoneSure: false, capture: true };
  // L'aperçu a-t-il chargé une VRAIE page d'overlay ? Distinct de la vue : on
  // peut vouloir cacher un aperçu qui marche, et il ne faut pas confondre les
  // deux — c'est ce qui décide du style des repères.
  let apercuPret = false;
  let outilsOuverts = false;    // le panneau d'outils de la sélection
  let derniereAnalyse = null;   // le dernier calcul de chevauchements

  /** Ce que la LISTE montre. Dans le navigateur, comme la vue : chercher un
   *  élément n'est pas une décision de mise en scène, et rangé dans le modèle
   *  ce serait une modification de plus à publier.
   *
   *  `texte` cherche dans le nom lisible ET dans la clé technique : on connaît
   *  l'un ou l'autre selon qu'on vient du panneau ou d'un log.
   */
  const filtre = { texte: "", masques: false, modifies: false };

  function filtreActif() {
    return !!filtre.texte || filtre.masques || filtre.modifies;
  }

  /** Cet élément passe-t-il le filtre ? `modifie` : l'élément diffère-t-il de
   *  ce qui est à l'antenne (calculé une fois par rendu, pas une fois par
   *  ligne). */
  function passeFiltre(cle, element, modifie) {
    if (filtre.masques && !element.hidden) return false;
    if (filtre.modifies && !modifie) return false;
    if (!filtre.texte) return true;
    const t = filtre.texte;
    return cle.toLowerCase().indexOf(t) >= 0
      || libelle(cle).toLowerCase().indexOf(t) >= 0;
  }

  /** Les clés modifiées depuis l'antenne, dans la scène affichée. Un objet et
   *  non un tableau : la liste le consulte une fois par ligne. */
  function clesModifiees() {
    const scene = sceneCourante();
    if (!scene) return {};
    const change = diffAntenne().parScene[scene.slug];
    return (change && change.cles) || {};
  }

  /** Les tailles LUES dans l'aperçu : clé → [largeur, hauteur] en pixels du
   *  canvas 1920. Une clé absente vaut « pas mesurable » — le widget n'affiche
   *  rien —, et le repère retombe alors sur l'estimation.
   *
   *  Déclaré ICI, avec le reste de l'état, et pas dans la section qui le
   *  remplit : `geometrie()` le lit trois cents lignes plus haut, et un `const`
   *  lu avant sa ligne lève une TDZ que `node --check` ne détecte pas.
   */
  const mesures = {};
  let mesureRO = null;        // ResizeObserver posé dans l'aperçu
  let mesureMO = null;        // MutationObserver posé dans l'aperçu
  let mesureDoc = null;       // le document écouté, pour retirer les écouteurs
  let mesureMinuteur = null;  // le regroupement d'une rafale de mutations
  let mesureAccalmie = null;  // la re-mesure après la DERNIÈRE mutation
  let mesureDerniere = 0;     // quand la dernière passe est partie
  let mesureEnRetard = false; // une mesure demandée pendant un geste

  // Une passe de mesure lit `offsetWidth` et `getComputedStyle` sur tous les
  // enfants des trente-sept conteneurs de l'aperçu : un recalcul de style et un
  // reflow forcés dans l'iframe, sur le thread de la page admin. Branchée telle
  // quelle sur un `MutationObserver` et un `ResizeObserver`, elle s'exécutait à
  // LA CADENCE DES ANIMATIONS de l'overlay — soixante fois par seconde tant
  // qu'un widget vivait à l'écran, chacune pouvant reconstruire les
  // trente-sept repères. C'est la cause première du panneau à une image par
  // seconde, et elle ne se voit nulle part : rien ne clignote, tout rame.
  //
  // Mesuré avant correction, avec UN SEUL widget factice qui mutait à chaque
  // frame dans un aperçu par ailleurs vide : 180 appels à `getComputedStyle`
  // par seconde. En direct, l'aperçu porte des dizaines de widgets animés.
  const MESURE_PERIODE_MS = 250;
  // La passe de rattrapage, après la DERNIÈRE mutation. Elle remplace les trois
  // relances (150, 500 et 1200 ms) reprogrammées à CHAQUE rafale : ce qu'elles
  // rattrapaient — une transition qui s'achève, une image qui se décode — se
  // produit à l'accalmie, jamais au milieu du flot.
  const MESURE_ACCALMIE_MS = 600;

  // La scène qu'on éditait, d'une visite à l'autre. Sans elle, un F5 ramène sur
  // la scène par défaut : le réglage qu'on venait de publier sur une AUTRE
  // scène a alors l'air d'avoir disparu — l'élément est bien à sa place, mais
  // on regarde une autre scène. C'est exactement ce qu'on lit comme « ça ne
  // persiste pas ».
  const CLE_SCENE = "wally.overlay.scene";

  /** Le stockage local peut lever (mode privé, stockage refusé, quota) : une
   *  préférence d'affichage ne doit jamais empêcher le panneau de s'ouvrir. */
  function sceneRetenue() {
    try {
      return window.localStorage.getItem(CLE_SCENE);
    } catch (e) {
      return null;
    }
  }

  function retenirScene(slug) {
    if (!slug) return;
    try {
      window.localStorage.setItem(CLE_SCENE, slug);
    } catch (e) {
      // Stockage refusé : on perd la mémoire de la scène, rien d'autre.
    }
  }

  // Le brouillon en attente, d'une visite à l'autre. Dans le NAVIGATEUR et
  // jamais en base : rangé côté serveur, il serait servi aux pages d'overlay au
  // prochain redémarrage du bot — donc publié à l'antenne sans avoir jamais été
  // validé. C'est exactement ce que le brouillon existe pour empêcher.
  const CLE_BROUILLON = "wally.overlay.brouillon";

  function rangerBrouillon() {
    if (!etat.layout) return;
    try {
      window.localStorage.setItem(CLE_BROUILLON, JSON.stringify({
        quand: Date.now(),
        n: etat.brouillon,
        base: etat.publie,      // ce qui était à l'antenne quand on l'a écrit
        scene: etat.slugCourant,
        layout: etat.layout,
      }));
    } catch (e) {
      // Stockage refusé ou plein : le brouillon reste valable à l'écran, il ne
      // survivra simplement pas au rechargement.
    }
  }

  function oublierBrouillon() {
    try {
      window.localStorage.removeItem(CLE_BROUILLON);
    } catch (e) {
      // Rien à défaire.
    }
  }

  // ── La capture de stream en fond ────────────────────────────────────────
  //
  // On place par rapport au décor RÉEL — le cadre du chat, la zone de jeu —
  // plutôt que dans le vide. C'est une aide au travail : elle vit dans le
  // NAVIGATEUR, ne va pas en base, et ne part JAMAIS vers l'overlay. Elle ne
  // touche pas au modèle, donc elle ne compte pas comme une modification.
  //
  // Elle est réduite et recompressée avant d'être rangée, et c'est une GARDE,
  // pas une optimisation : le brouillon non publié vit dans le même
  // `localStorage` — cinq mégaoctets en tout —, et une capture 1920 × 1080 en
  // PNG en pèse plusieurs à elle seule. Perdre un travail en cours au profit
  // d'une image de décor serait le pire échange possible. Si le quota se ferme
  // quand même, c'est le FOND qu'on abandonne, et on le dit.
  const CLE_FOND = "wally:overlay:fond";
  // La surface ne dépasse jamais cette largeur à l'écran : ranger du 1920 ne
  // donnerait pas un pixel de plus à voir, pour cinq fois le poids.
  const FOND_LARGEUR_MAX = 960;
  const FOND_QUALITE = 0.72;
  // En dessous, le fond est invisible et le curseur passe pour cassé.
  const FOND_OPACITE_MIN = 20;
  const FOND_OPACITE_DEFAUT = 55;

  function bornerOpaciteFond(valeur) {
    const n = Number(valeur);
    if (!isFinite(n)) return FOND_OPACITE_DEFAUT;
    return Math.max(FOND_OPACITE_MIN, Math.min(100, Math.round(n)));
  }

  /** Ce qu'on accepte de poser en `src`. Une dataURL d'image RASTER, produite
   *  par notre propre canvas — rien d'autre. Le SVG est écarté avec le reste :
   *  ses scripts ne s'exécutent pas dans une `<img>`, mais la reconnaissance ne
   *  s'appuie pas sur cette subtilité, elle liste ce qu'elle sait sûr. */
  function estImageRangeable(valeur) {
    return typeof valeur === "string"
      && /^data:image\/(png|jpeg|webp|gif);base64,[A-Za-z0-9+/=]+$/.test(valeur);
  }

  /** Range le fond. Rend `false` si le stockage a refusé — un fond qui ne
   *  survit pas au rechargement sans que rien ne l'annonce se lit comme un bug
   *  du bouton. */
  function rangerFond(image, opacite) {
    if (!estImageRangeable(image)) return false;
    try {
      window.localStorage.setItem(CLE_FOND, JSON.stringify({
        image: image,
        opacite: bornerOpaciteFond(opacite),
      }));
      return true;
    } catch (e) {
      // Quota plein, stockage refusé. On ne touche à RIEN d'autre : le
      // brouillon déjà rangé doit survivre à l'échec de cette image.
      return false;
    }
  }

  /** Le fond rangé, ou `null`. Tout ce qui n'est pas une image reconnue est
   *  jeté sans bruit : le panneau se règle en plein live, une préférence
   *  d'affichage illisible ne doit jamais l'empêcher de s'ouvrir. */
  function lireFond() {
    let brut = null;
    try {
      brut = window.localStorage.getItem(CLE_FOND);
    } catch (e) {
      return null;
    }
    if (!brut) return null;
    let d = null;
    try {
      d = JSON.parse(brut);
    } catch (e) {
      return null;
    }
    if (!d || !estImageRangeable(d.image)) return null;
    return { image: d.image, opacite: bornerOpaciteFond(d.opacite) };
  }

  function oublierFond() {
    try {
      window.localStorage.removeItem(CLE_FOND);
    } catch (e) {
      // Rien à défaire.
    }
  }

  /** Le brouillon rangé, ou `null`. Un contenu tordu (quota tronqué, version
   *  d'avant) ne doit pas empêcher le panneau de s'ouvrir : on le jette. */
  function lireBrouillon() {
    let brut = null;
    try {
      brut = window.localStorage.getItem(CLE_BROUILLON);
    } catch (e) {
      return null;
    }
    if (!brut) return null;
    let d = null;
    try {
      d = JSON.parse(brut);
    } catch (e) {
      return null;
    }
    if (!d || !d.n || !d.layout || !d.layout.scenes || !d.layout.scenes.length) {
      return null;
    }
    return d;
  }

  /** L'âge du brouillon, en clair. « Il y a deux heures » dit tout de suite
   *  s'il s'agit du travail d'avant le F5 ou d'un oubli d'avant-hier. */
  function depuis(quand) {
    const s = Math.max(0, Math.round((Date.now() - Number(quand || 0)) / 1000));
    if (!isFinite(s) || s < 90) return "il y a moins d'une minute";
    const m = Math.round(s / 60);
    if (m < 90) return "il y a " + m + " minutes";
    const h = Math.round(m / 60);
    if (h < 36) return "il y a " + h + " heure" + (h > 1 ? "s" : "");
    return "il y a " + Math.round(h / 24) + " jours";
  }

  // ── Petits outils ───────────────────────────────────────────────────────

  function creer(tag, cls, texte) {
    const n = document.createElement(tag);
    if (cls) n.className = cls;
    if (texte !== undefined && texte !== null) n.textContent = texte;
    return n;
  }

  /** L'icône « copier », en SVG comme celles de la barre latérale.
   *
   *  Ni emoji ni glyphe Unicode : 📋 sort en carré vide dans un navigateur sans
   *  police emoji couleur — constaté à l'écran ici même —, et ⧉ manque à
   *  presque toutes les polices système. Un tracé ne dépend d'aucune police.
   *  `createElementNS` est obligatoire — `createElement("svg")` fabrique un
   *  élément HTML inconnu, qui ne dessine rien. */
  function iconeCopie() {
    const NS = "http://www.w3.org/2000/svg";
    const svg = document.createElementNS(NS, "svg");
    svg.setAttribute("viewBox", "0 0 24 24");
    svg.setAttribute("width", "13");
    svg.setAttribute("height", "13");
    svg.setAttribute("fill", "none");
    svg.setAttribute("stroke", "currentColor");
    svg.setAttribute("stroke-width", "2");
    svg.setAttribute("stroke-linecap", "round");
    svg.setAttribute("stroke-linejoin", "round");
    svg.setAttribute("aria-hidden", "true");
    [
      "M9 9h10v12H9z",                       // la feuille de devant
      "M15 5H5v12h2",                        // celle de derrière
    ].forEach(function (d) {
      const p = document.createElementNS(NS, "path");
      p.setAttribute("d", d);
      svg.appendChild(p);
    });
    return svg;
  }

  function notifier(msg, type) {
    if (typeof window.toast === "function") window.toast(msg, type || "success");
  }

  function libelle(cle) {
    const l = etat.libelles[cle];
    return (l && l.nom) || cle;
  }

  function description(cle) {
    const l = etat.libelles[cle];
    return (l && l.description) || "";
  }

  /** L'adresse à coller dans OBS. Le domaine se DÉDUIT de la page courante :
   *  écrit en dur, il aurait renvoyé sur heywally.fr un dashboard ouvert par
   *  son IP locale — donc une source OBS pointée hors du réseau. */
  function urlScene(slug) {
    return window.location.origin + "/overlay-" + slug;
  }

  /** Copie, y compris hors contexte sécurisé. `navigator.clipboard` est
   *  INDÉFINI en http sur une IP locale : y appeler `.writeText` lève une
   *  TypeError synchrone qu'aucun `.catch()` n'attrape — d'où le test avant. */
  function copier(texte) {
    if (navigator.clipboard && window.isSecureContext) {
      navigator.clipboard.writeText(texte)
        .then(function () { notifier("Adresse copiée"); })
        .catch(function () { copierAncienneMethode(texte); });
      return;
    }
    copierAncienneMethode(texte);
  }

  function copierAncienneMethode(texte) {
    const zone = document.createElement("textarea");
    zone.value = texte;
    zone.setAttribute("readonly", "");
    zone.style.position = "fixed";
    zone.style.opacity = "0";
    document.body.appendChild(zone);
    zone.select();
    let ok = false;
    try { ok = document.execCommand("copy"); } catch (e) { ok = false; }
    document.body.removeChild(zone);
    notifier(ok ? "Adresse copiée" : "Copie refusée — sélectionnez l'adresse à la main",
             ok ? "success" : "error");
  }

  // ── L'infobulle ─────────────────────────────────────────────────────────

  /** Une vraie bulle, pas l'attribut `title` : celui-ci met deux secondes à
   *  venir et s'affiche en noir sur blanc système, illisible sur ce fond.
   *
   *  Posée sur `<body>` en `position: fixed` : la liste des éléments est en
   *  `overflow-y: auto`, une bulle placée dedans y serait rognée. */
  function poserInfobulle(hote, texte) {
    // Le texte vit SUR le nœud et les écouteurs le relisent à chaque survol.
    // Capturé dans une closure comme avant, le mettre à jour imposait de
    // rebrancher un couple d'écouteurs — donc de jeter le nœud et d'en refaire
    // un. C'est en partie ce qui obligeait la surface à se reconstruire en
    // entier au moindre changement.
    hote._bulle = texte || "";
    if (hote._bulleBranchee) return;
    hote._bulleBranchee = true;
    hote.addEventListener("mouseenter", function () {
      if (hote._bulle) montrerInfobulle(hote, hote._bulle);
    });
    hote.addEventListener("mouseleave", masquerInfobulle);
  }

  function montrerInfobulle(hote, texte) {
    if (!infobulle) {
      infobulle = creer("div", "ovl-infobulle");
      infobulle.setAttribute("role", "tooltip");
      document.body.appendChild(infobulle);
      // En CAPTURE : `scroll` ne remonte pas, et il y a trois conteneurs qui
      // défilent ici (la page, la liste des éléments, la colonne). Un seul
      // écouteur les couvre tous. Sinon la bulle, posée en `fixed`, reste
      // accrochée là où elle est née pendant que sa cible s'en va.
      document.addEventListener("scroll", masquerInfobulle, true);
    }
    infobulle.textContent = texte;
    infobulle.classList.add("visible");
    // Mesurée APRÈS avoir reçu son texte, sinon la bulle se place sur la
    // largeur de la précédente et déborde de l'écran une fois sur deux.
    const cible = hote.getBoundingClientRect();
    const bulle = infobulle.getBoundingClientRect();
    let gauche = cible.right + 10;
    if (gauche + bulle.width > window.innerWidth - 8) {
      gauche = Math.max(8, cible.left - bulle.width - 10);
    }
    let haut = cible.top + cible.height / 2 - bulle.height / 2;
    haut = Math.max(8, Math.min(haut, window.innerHeight - bulle.height - 8));
    infobulle.style.left = gauche + "px";
    infobulle.style.top = haut + "px";
  }

  function masquerInfobulle() {
    if (infobulle) infobulle.classList.remove("visible");
  }

  function sceneCourante() {
    if (!etat.layout) return null;
    const scenes = etat.layout.scenes || [];
    for (let i = 0; i < scenes.length; i++) {
      if (scenes[i].slug === etat.slugCourant) return scenes[i];
    }
    return scenes[0] || null;
  }

  // ── Les groupes ─────────────────────────────────────────────────────────
  //
  // Le modèle est côté serveur (`bot/core/overlay_layout.py`, section « Les
  // groupes d'éléments ») et c'est lui qui tranche. Ici on tient les mêmes
  // règles AVANT l'envoi, pour ne jamais afficher un état que le serveur
  // rangerait autrement :
  //
  //   - un élément n'appartient qu'à UN groupe (`retirerDesGroupes` passe avant
  //     toute adhésion) ;
  //   - un groupe vidé de son dernier membre disparaît — il n'y a plus rien à
  //     manipuler dessous ;
  //   - les membres d'un groupe se suivent dans l'empilement (`ordreGroupe`),
  //     parce que l'ordre de la liste EST l'empilement et qu'une liste qui les
  //     montre l'un sous l'autre pendant que trois widgets s'intercalent
  //     mentirait sur la seule chose qu'elle raconte.
  //
  // SÉLECTIONNER UN GROUPE, C'EST SÉLECTIONNER SES MEMBRES. Rien d'autre. Tout
  // ce qui existait déjà — glisser, flèches, aligner, répartir, coller des
  // réglages, décalage commun borné — s'applique alors sans une ligne de plus,
  // et le cadenas continue de retenir individuellement ce qu'il retenait.

  function groupesScene() {
    const scene = sceneCourante();
    return (scene && Array.isArray(scene.groupes)) ? scene.groupes : [];
  }

  /** Le groupe qui contient `cle`, ou `null`. */
  function groupeDe(cle) {
    const groupes = groupesScene();
    for (let i = 0; i < groupes.length; i++) {
      if ((groupes[i].membres || []).indexOf(cle) >= 0) return groupes[i];
    }
    return null;
  }

  /** Les membres qui existent VRAIMENT dans la scène, dans l'ordre de celle-ci.
   *  Une clé fantôme — modèle d'une version d'avant, widget retiré du code —
   *  ne doit ni s'afficher ni compter dans « 3 éléments ». */
  function membresPresents(groupe) {
    const scene = sceneCourante();
    if (!scene) return [];
    const membres = groupe.membres || [];
    return (scene.ordre || []).filter(function (cle) {
      return membres.indexOf(cle) >= 0 && !!scene.elements[cle];
    });
  }

  /** Les membres d'un groupe rendus CONTIGUS, à la place du premier d'entre
   *  eux. Miroir exact de `_ordre_avec_groupes()` (Python) : les deux se lisent
   *  ensemble, et c'est le serveur qui fait foi. Pure, donc testée. */
  function ordreGroupe(ordre, groupes) {
    if (!groupes || !groupes.length) return (ordre || []).slice();
    const parCle = {};
    groupes.forEach(function (g) {
      (g.membres || []).forEach(function (cle) { parCle[cle] = g.id; });
    });
    const sortie = [], faits = {};
    (ordre || []).forEach(function (cle) {
      const gid = parCle[cle];
      if (gid === undefined) { sortie.push(cle); return; }
      if (faits[gid]) return;
      faits[gid] = true;
      (ordre || []).forEach(function (c) {
        if (parCle[c] === gid) sortie.push(c);
      });
    });
    return sortie;
  }

  /** Range l'empilement de la scène après un changement de groupe. Rend `true`
   *  s'il a bougé — l'appelant compte UNE modification pour toute l'opération,
   *  jamais une par effet de bord. */
  function normaliserOrdre(scene) {
    const avant = scene.ordre || [];
    const apres = ordreGroupe(avant, scene.groupes || []);
    const identique = apres.length === avant.length
      && apres.every(function (c, i) { return avant[i] === c; });
    if (identique) return false;
    scene.ordre = apres;
    return true;
  }

  /** Sort ces clés de tous les groupes — c'est LA garde de l'exclusivité, et
   *  elle est au point d'écriture : toute adhésion passe par ici d'abord.
   *  Un groupe vidé de son dernier membre s'en va avec.
   *
   *  Rend les noms des groupes dissous, pour qu'on le dise. */
  function retirerDesGroupes(scene, cles) {
    const perdus = [];
    scene.groupes = (scene.groupes || []).filter(function (g) {
      g.membres = (g.membres || []).filter(function (c) {
        return cles.indexOf(c) < 0;
      });
      if (g.membres.length) return true;
      perdus.push(g.nom);
      return false;
    });
    return perdus;
  }

  /** Un identifiant stable, lisible dans le JSON, unique DANS LA SCÈNE. Le nom
   *  ne peut pas servir de clé : on le renomme, et deux groupes ont le droit de
   *  porter le même mot. */
  function idGroupeUnique(scene, nom) {
    const base = slugDepuisNom(nom);
    const pris = {};
    (scene.groupes || []).forEach(function (g) { pris[g.id] = true; });
    if (!pris[base]) return base;
    let n = 2;
    while (pris[base + "-" + n]) n += 1;
    return base + "-" + n;
  }

  function cleRepli(id) {
    return etat.slugCourant + "/" + id;
  }

  function estReplie(id) {
    return !!etat.replies[cleRepli(id)];
  }

  function basculerRepli(id) {
    const cle = cleRepli(id);
    if (etat.replies[cle]) delete etat.replies[cle];
    else etat.replies[cle] = true;
    rendreElements();
  }

  // ── Ce qu'on fait à un groupe ───────────────────────────────────────────

  /** Le groupe naît de la SÉLECTION : c'est le geste qu'on vient de faire, et
   *  il n'y a pas d'autre façon de désigner sept widgets d'un coup.
   *
   *  Deux membres au minimum : un groupe d'un seul élément est un élément, avec
   *  un en-tête en plus et rien à manipuler ensemble. */
  function creerGroupe() {
    const scene = sceneCourante();
    const cles = selection();
    if (!scene) return;
    if (cles.length < 2) {
      notifier("Choisissez au moins deux éléments — Ctrl+clic, ou un glisser "
        + "sur le fond de la surface — puis regroupez-les.", "error");
      return;
    }
    const nom = window.prompt(
      "Nom du groupe (" + cles.length + " éléments) :\n\n"
      + cles.map(libelle).join(", "), "Nouveau groupe");
    if (nom === null) return;
    const propre = nom.trim();
    if (!propre) { notifier("Un nom vide n'a rien à afficher.", "error"); return; }
    const perdus = retirerDesGroupes(scene, cles);
    scene.groupes.push({
      id: idGroupeUnique(scene, propre),
      nom: propre,
      membres: cles.slice(),
    });
    normaliserOrdre(scene);
    marquerModifie();
    rendreTout();
    notifier("Groupe « " + propre + " » créé : " + cles.length + " éléments."
      + (perdus.length ? " Dissous au passage : " + perdus.join(", ") + "." : "")
      + " Rien n'est parti à l'antenne.");
  }

  function renommerGroupe(groupe) {
    const nom = window.prompt("Nouveau nom du groupe :", groupe.nom);
    if (nom === null) return;
    const propre = nom.trim();
    if (!propre) { notifier("Un nom vide n'a rien à afficher.", "error"); return; }
    if (propre === groupe.nom) return;
    groupe.nom = propre;
    marquerModifie();
    rendreElements();
    rendreSurface();
  }

  /** Dissoudre ne touche à RIEN d'autre : les éléments gardent leur place, leur
   *  masquage et leur verrou. On défait l'en-tête, pas le travail. */
  function dissoudreGroupe(groupe) {
    const scene = sceneCourante();
    if (!scene) return;
    scene.groupes = (scene.groupes || []).filter(function (g) {
      return g !== groupe;
    });
    marquerModifie();
    rendreTout();
    notifier("Groupe « " + groupe.nom + " » dissous — les éléments n'ont pas bougé.");
  }

  function ajouterAuGroupe(groupe) {
    const scene = sceneCourante();
    const cles = selection().filter(function (c) {
      return (groupe.membres || []).indexOf(c) < 0;
    });
    if (!scene) return;
    if (!cles.length) {
      notifier("Sélectionnez d'abord les éléments à ajouter — ceux qui sont "
        + "déjà dans « " + groupe.nom + " » ne comptent pas.", "error");
      return;
    }
    const perdus = retirerDesGroupes(scene, cles);
    // `retirerDesGroupes` a pu faire disparaître CE groupe-ci s'il ne contenait
    // que des éléments qu'on lui reprend — impossible ici, puisqu'on a écarté
    // ses propres membres, mais la garde coûte une ligne et évite de ressusciter
    // un groupe dissous.
    if ((scene.groupes || []).indexOf(groupe) < 0) scene.groupes.push(groupe);
    groupe.membres = (groupe.membres || []).concat(cles);
    normaliserOrdre(scene);
    marquerModifie();
    rendreTout();
    notifier(cles.length + " élément(s) ajouté(s) à « " + groupe.nom + " »."
      + (perdus.length ? " Dissous au passage : " + perdus.join(", ") + "." : ""));
  }

  function retirerDuGroupe(cle) {
    const scene = sceneCourante();
    const groupe = groupeDe(cle);
    if (!scene || !groupe) return;
    const nom = groupe.nom;
    const perdus = retirerDesGroupes(scene, [cle]);
    marquerModifie();
    rendreTout();
    notifier(libelle(cle) + " ne fait plus partie de « " + nom + " »."
      + (perdus.length ? " Le groupe, vidé, a été dissous." : ""));
  }

  /** Dissout TOUS les groupes que la sélection touche. Le pendant de
   *  « Grouper » : après un clic sur un en-tête, la sélection est justement le
   *  groupe entier. */
  function degrouperSelection() {
    const scene = sceneCourante();
    const cles = selection();
    if (!scene) return;
    const vises = [];
    cles.forEach(function (cle) {
      const g = groupeDe(cle);
      if (g && vises.indexOf(g) < 0) vises.push(g);
    });
    if (!vises.length) {
      notifier(cles.length
        ? "La sélection n'appartient à aucun groupe."
        : "Aucun élément sélectionné.", "error");
      return;
    }
    scene.groupes = (scene.groupes || []).filter(function (g) {
      return vises.indexOf(g) < 0;
    });
    marquerModifie();
    rendreTout();
    notifier(vises.length + " groupe(s) dissous : "
      + vises.map(function (g) { return g.nom; }).join(", ")
      + " — les éléments n'ont pas bougé.");
  }

  /** Un clic sur l'en-tête : la sélection devient exactement les membres.
   *  Le principal est le DERNIER, comme après un rectangle de sélection — c'est
   *  lui dont la barre montre les réglages. */
  function selectionnerGroupe(groupe) {
    const membres = membresPresents(groupe);
    if (!membres.length) return;
    etat.selection = membres.slice();
    etat.elementCourant = membres[membres.length - 1];
    etat.ancreSelection = etat.elementCourant;
    rendreSelection();
  }

  // ── La sélection ────────────────────────────────────────────────────────
  //
  // Trente-quatre éléments sur trois scènes, réglés un par un : le panneau
  // demandait un aller-retour liste → surface → réglages par élément. La
  // sélection multiple est le socle de tout ce qui suit (aligner, répartir,
  // coller des réglages) — sans elle, chaque outil ne saurait agir que sur un.
  //
  // L'ORDRE DE LA SÉLECTION EST CELUI DE LA SCÈNE, jamais celui des clics :
  // un alignement ou une répartition doit rendre le même résultat quel que soit
  // l'ordre dans lequel on a composé la sélection.

  function estSelectionne(cle) {
    return etat.selection.indexOf(cle) >= 0;
  }

  /** Les clés retenues qui existent vraiment dans la scène affichée. */
  function selection() {
    const scene = sceneCourante();
    if (!scene) return [];
    return (scene.ordre || []).filter(function (cle) {
      return estSelectionne(cle) && !!scene.elements[cle];
    });
  }

  /** Écarte ce qui n'existe plus et rétablit l'invariant : le principal est
   *  toujours dans la sélection, et une sélection vide n'a pas de principal.
   *  Sans ce ménage, une clé fantôme (scène rechargée, brouillon d'une version
   *  d'avant) resterait dans les outils, qui agiraient sur un élément absent
   *  de l'écran. */
  function nettoyerSelection() {
    const scene = sceneCourante();
    const elements = (scene && scene.elements) || {};
    etat.selection = etat.selection.filter(function (cle) { return !!elements[cle]; });
    if (etat.elementCourant && !elements[etat.elementCourant]) etat.elementCourant = null;
    if (!etat.elementCourant) {
      etat.selection = [];
    } else if (!estSelectionne(etat.elementCourant)) {
      etat.selection.push(etat.elementCourant);
    }
    if (etat.ancreSelection && !elements[etat.ancreSelection]) {
      etat.ancreSelection = etat.elementCourant;
    }
  }

  /** Fait de `cle` le principal SANS défaire la sélection s'il en fait déjà
   *  partie : cliquer un membre du bloc pour l'attraper ne doit pas dissoudre
   *  le bloc qu'on vient de composer. */
  function poserPrincipal(cle) {
    etat.elementCourant = cle || null;
    if (!cle) { etat.selection = []; etat.ancreSelection = null; return; }
    if (!estSelectionne(cle)) {
      etat.selection = [cle];
      etat.ancreSelection = cle;
    }
  }

  function rendreSelection() {
    rendreElements();
    rendreSurface();
    rendreReglages();
  }

  /** Ctrl+clic : entrer ou sortir de la sélection. */
  function basculerSelection(cle) {
    const i = etat.selection.indexOf(cle);
    if (i >= 0) {
      etat.selection.splice(i, 1);
      if (etat.elementCourant === cle) {
        etat.elementCourant = etat.selection[etat.selection.length - 1] || null;
      }
    } else {
      etat.selection.push(cle);
      etat.elementCourant = cle;
    }
    etat.ancreSelection = cle;
    rendreSelection();
  }

  /** Maj+clic : la plage entre l'ancre et la ligne cliquée, dans l'ordre de la
   *  liste. L'ancre NE BOUGE PAS — deux Maj+clic successifs élargissent depuis
   *  le même point de départ, au lieu de ramper d'un cran. */
  function etendreSelection(cle) {
    const scene = sceneCourante();
    const ordre = (scene && scene.ordre) || [];
    const fin = ordre.indexOf(cle);
    if (fin < 0) return;
    const depart = ordre.indexOf(etat.ancreSelection);
    if (depart < 0) { selectionner(cle); return; }
    etat.selection = ordre.slice(Math.min(depart, fin), Math.max(depart, fin) + 1);
    etat.elementCourant = cle;
    rendreSelection();
  }

  /** Ctrl+A : tout ce qui est visible ET libre. Prendre les masqués et les
   *  verrouillés remplirait la sélection d'éléments qu'aucun outil ne peut
   *  bouger — le compteur annoncerait trente-quatre pour six déplacements. */
  function toutSelectionner() {
    const scene = sceneCourante();
    if (!scene) return;
    etat.selection = (scene.ordre || []).filter(function (cle) {
      const el = scene.elements[cle];
      return !!el && !el.hidden && !el.locked;
    });
    etat.elementCourant = etat.selection[etat.selection.length - 1] || null;
    etat.ancreSelection = etat.elementCourant;
    rendreSelection();
    notifier(etat.selection.length + " élément(s) sélectionné(s).");
  }

  function viderSelection() {
    if (!etat.selection.length && !etat.elementCourant) return;
    etat.selection = [];
    etat.elementCourant = null;
    etat.ancreSelection = null;
    rendreSelection();
  }

  /** La sélection triée en deux : ce qu'un outil peut déplacer, et ce que le
   *  cadenas retient. Les verrouillés sont RENDUS, pas jetés — un élément qui
   *  ne suit pas doit être NOMMÉ, sinon on croit l'outil cassé. */
  function selectionDeplacable() {
    const scene = sceneCourante();
    const membres = [];
    const bloques = [];
    if (!scene) return { membres: membres, bloques: bloques };
    selection().forEach(function (cle) {
      const el = scene.elements[cle];
      if (!el) return;
      if (el.locked) { bloques.push(cle); return; }
      membres.push({ cle: cle, element: el, depart: { x: el.x, y: el.y } });
    });
    return { membres: membres, bloques: bloques };
  }

  /** Dit ce que le cadenas a retenu. Le silence était l'autre option : elle
   *  laisse croire que l'outil n'a rien fait. */
  function direLesBloques(bloques) {
    if (!bloques || !bloques.length) return;
    notifier(bloques.length + " élément(s) verrouillé(s) n'ont pas bougé : "
      + bloques.map(libelle).join(", ")
      + " — le cadenas de la liste les libère.", "error");
  }

  function borner(valeur, mini, maxi, defaut) {
    const n = Number(valeur);
    if (!isFinite(n)) return defaut;
    return Math.max(mini, Math.min(maxi, n));
  }

  /** Le slug d'URL d'un nom, miroir de `slug_depuis_nom()` (Python).
   *
   *  Le Python ne garantit PAS l'unicité contre les scènes existantes : deux
   *  scènes du même slug, et le serveur n'en garde qu'une (`fusionner()` jette
   *  les doublons). L'unicité se joue donc ici, avant l'envoi.
   */
  function slugDepuisNom(nom) {
    let s = String(nom || "");
    if (typeof s.normalize === "function") s = s.normalize("NFKD");
    s = s.replace(/[\u0300-\u036f]/g, "")  // les diacritiques décomposés
         .toLowerCase()
         .replace(/[^a-z0-9]+/g, "-")
         .replace(/^-+|-+$/g, "");
    if (!s) s = "scene";
    if (SLUGS_RESERVES.indexOf(s) >= 0) s = s + "-2";
    return s;
  }

  function slugUnique(base) {
    const pris = {};
    (etat.layout.scenes || []).forEach(function (s) { pris[s.slug] = true; });
    if (!pris[base]) return base;
    let n = 2;
    while (pris[base + "-" + n]) n += 1;
    return base + "-" + n;
  }

  // ── Réseau ──────────────────────────────────────────────────────────────

  /** L'appel admin d'`app.js` : c'est lui qui pose le Bearer et gère le 401.
   *  Refaire un `fetch` nu ici enverrait la requête sans jeton. */
  function appeler(url, options) {
    if (typeof window.apiFetch !== "function") {
      return Promise.reject(new Error("apiFetch absent"));
    }
    return window.apiFetch(url, options);
  }

  /** Ce que le GET ajoute AUTOUR du modèle, et que le PUT ne rend pas.
   *
   *  Une seule liste, parce qu'il en fallait DEUX pour que ça marche — celle du
   *  chargement (qui les retire du modèle) et celle de la comparaison de
   *  concurrence (qui doit les ignorer) — et qu'elles ont divergé : `tailles`
   *  n'a jamais été ajoutée à la seconde. Résultat, le modèle servi ne pouvait
   *  plus JAMAIS être égal au nôtre, et chaque publication ouvrait un
   *  « la mise en scène a changé, continuer ? » qui n'avait aucun fondement.
   *  En publication au fil de l'eau, c'est un dialogue par modification : le
   *  navigateur propose alors de bloquer les boîtes de dialogue de la page, et
   *  l'éditeur devient inutilisable en direct. Un test Python confronte cette
   *  liste à ce que la route ajoute réellement.
   */
  const HORS_MODELE = ["libelles", "tailles", "echantillons", "maj",
                       "animations", "portees"];

  /** Le modèle SEUL, sans ce que le GET lui a joint. Modifie l'objet reçu. */
  function retirerHorsModele(objet) {
    if (!objet) return objet;
    HORS_MODELE.forEach(function (cle) { delete objet[cle]; });
    return objet;
  }

  function charger() {
    return appeler(URL_LAYOUT)
      .then(function (r) { return r && r.ok ? r.json() : null; })
      .then(function (layout) {
        if (!layout || !layout.scenes || !layout.scenes.length) {
          echouer("Mise en scène illisible");
          return;
        }
        // Trois tables voyagent AVEC le modèle, sans en faire partie : les
        // libellés lisibles des éléments, les boîtes des widgets à média
        // (mesurées par le serveur sur le dossier — le navigateur n'y a pas
        // accès) et les échantillons du ▶, dont le banc de mesure se sert.
        // Chacune est ici plutôt que recopiée en JavaScript, pour la même
        // raison : deux tables divergent au premier widget ajouté.
        if (layout.libelles) etat.libelles = layout.libelles;
        if (layout.tailles && window.WallyLayout) {
          WallyLayout.poserTailles(layout.tailles);
        }
        if (layout.echantillons) etat.echantillons = layout.echantillons;
        // Le catalogue d'animations et les portées : qui porte quel réglage, et
        // avec quelles bornes. Servis plutôt que recopiés ici — une seconde
        // table aurait divergé du modèle au premier champ ajouté, et le panneau
        // aurait alors laissé saisir une valeur que le serveur ramène en
        // silence : on croit avoir réglé, rien ne bouge, et rien ne le dit.
        if (layout.animations) etat.animations = layout.animations;
        if (layout.portees) etat.portees = layout.portees;
        // Quand ce qui est à l'antenne y est parti. Lue AVANT le retrait :
        // `retirerHorsModele` l'efface avec le reste de ce qui voyage.
        etat.majAntenne = layout.maj || null;
        // Elles sortent du modèle avant tout le reste : `publier()` renvoie
        // `etat.layout` tel quel au serveur, et le PUT ne les rend pas. Les y
        // laisser les enverrait à l'antenne comme un réglage de scène.
        adopter(retirerHorsModele(layout));
        // L'aperçu peut avoir fini de charger AVANT cette réponse : il a alors
        // sauté son banc faute d'échantillons. On repasse.
        lancerBanc();
      })
      .catch(function (e) {
        echouer("Mise en scène : " + (e && e.message ? e.message : "erreur"));
      });
  }

  /** Prend un layout du serveur pour vérité et redessine tout. */
  function adopter(layout) {
    etat.layout = layout;
    etat.brouillon = 0;
    etat.publie = JSON.stringify(layout);
    // Plus rien en attente : un brouillon qui survivrait ici serait proposé au
    // prochain chargement alors qu'il est déjà à l'antenne.
    oublierBrouillon();
    const scenes = layout.scenes || [];
    const existe = scenes.some(function (s) { return s.slug === etat.slugCourant; });
    if (!existe) etat.slugCourant = layout.defaut || scenes[0].slug;
    retenirScene(etat.slugCourant);
    const scene = sceneCourante();
    const ordre = (scene && scene.ordre) || [];
    if (!scene || !scene.elements[etat.elementCourant]) {
      etat.elementCourant = ordre[0] || null;
    }
    nettoyerSelection();
    // La pile repart d'ici : ce qu'on vient d'adopter EST ce qui est à
    // l'antenne, et « annuler » vers un état d'avant n'aurait plus de sens.
    reinitialiserHistoire();
    rendreTout();
  }

  function echouer(message) {
    if (noeuds.cadre) noeuds.cadre.innerHTML = "";
    if (noeuds.listeScenes) {
      noeuds.listeScenes.innerHTML = "";
      noeuds.listeScenes.appendChild(creer("li", "ovl-vide", message));
    }
    notifier(message, "error");
  }

  /** Le modèle servi a-t-il bougé depuis notre dernier aller-retour ?
   *
   *  Deux onglets du panneau renvoient chacun le MODÈLE ENTIER tel qu'il l'a
   *  chargé : le second efface le travail du premier sans que rien ne le dise.
   *  Le serveur ne porte pas de numéro de révision — on relit donc juste avant
   *  d'écrire. Une lecture qui échoue NE BLOQUE PAS la publication : on est en
   *  direct, et un réseau capricieux ne doit pas coincer le streamer. */
  function verifierConcurrence() {
    if (!etat.publie) return Promise.resolve(true);
    return appeler(URL_LAYOUT)
      .then(function (r) { return r && r.ok ? r.json() : null; })
      .then(function (servi) {
        if (!servi || !servi.scenes) return true;
        // Ce que le GET joint au modèle ne fait pas partie de la comparaison :
        // `etat.publie` ne le porte pas, et l'y laisser rendait les deux
        // TOUJOURS différents — donc la question TOUJOURS posée.
        if (JSON.stringify(retirerHorsModele(servi)) === etat.publie) return true;
        return window.confirm(
          "La mise en scène à l'antenne a changé depuis votre chargement — "
          + "un autre onglet du panneau, sans doute.\n\nPublier maintenant "
          + "écrasera ces changements.\n\nContinuer ?");
      })
      .catch(function () { return true; });
  }

  /** Envoie un modèle. Le serveur renvoie ce qu'il a RANGÉ — on adopte sa
   *  réponse, pas ce qu'on lui a envoyé : les valeurs bornées apparaissent donc
   *  immédiatement à l'écran.
   *
   *  `message` remplace l'annonce générique : une opération de scène dit ce
   *  qu'elle a fait, et elle ne le dit qu'une fois le serveur d'accord. Un
   *  échec laisse le compteur en attente — la modification n'est pas perdue,
   *  « Mettre à jour » la renverra. */
  function publierModele(modele, message) {
    if (!modele) return Promise.resolve();
    // Une publication demandée à la main solde le fil de l'eau en attente :
    // sinon le minuteur repartirait derrière pour renvoyer la même chose.
    annulerPublicationDifferee();
    return verifierConcurrence().then(function (feuVert) {
      if (!feuVert) return undefined;
      // Ce qui est à l'antenne AVANT cet envoi : le cran d'annulation.
      const avant = etat.publie;
      return appeler(URL_LAYOUT, {
        method: "PUT",
        body: JSON.stringify(modele),
      })
        .then(function (r) {
          if (!r || !r.ok) throw new Error("le serveur a refusé");
          return r.json();
        })
        .then(function (layout) {
          // La date de publication voyage AVEC la réponse sans faire partie du
          // modèle. Retirée avant toute comparaison : `etat.publie` ne la porte
          // pas, et l'y laisser rendrait `verifierConcurrence()` toujours
          // différente — donc la question toujours posée.
          etat.majAntenne = layout.maj || null;
          retirerHorsModele(layout);
          // Un envoi qui ne change rien à l'écran ne doit pas consommer le
          // cran : on garderait un « annuler » qui ne fait rien.
          if (avant && avant !== JSON.stringify(layout)) etat.precedent = avant;
          if (manip) {
            // Un glisser a COMMENCÉ pendant l'aller-retour. `adopter()`
            // remplacerait `etat.layout` par la réponse du serveur, et
            // `manip.element` désignerait alors un objet détaché : le
            // mouvement en cours partirait dans le vide et sauterait en
            // arrière au relâchement. On note ce qui est parti, on laisse le
            // modèle sous les doigts — le geste comptera dans le brouillon
            // suivant, et ses valeurs bornées reviendront à la publication
            // d'après.
            etat.publie = JSON.stringify(layout);
            rendreBarrePublication();
            notifier(message || "Mise en scène publiée");
            return;
          }
          adopter(layout);
          notifier(message || "Mise en scène publiée");
        })
        .catch(function (e) {
          notifier("Publication impossible : " + (e && e.message ? e.message : "erreur"),
                   "error");
        });
    });
  }

  function publier(message) {
    return publierModele(etat.layout, message);
  }

  /** Le filet : republier ce qui était à l'antenne avant la dernière
   *  publication. UN SEUL cran — c'est de quoi ne pas rester coincé en plein
   *  live, pas un historique. Comme `publierModele()` garde à son tour l'état
   *  qu'on vient de remplacer, un second clic refait le chemin inverse. */
  function annulerPublication() {
    if (!etat.precedent) return Promise.resolve();
    let modele = null;
    try {
      modele = JSON.parse(etat.precedent);
    } catch (e) {
      etat.precedent = null;
      rendreBarrePublication();
      return Promise.resolve();
    }
    const perte = etat.brouillon > 0
      ? "\n\nATTENTION : vos " + etat.brouillon
        + " modification(s) en attente seront perdues."
      : "";
    if (!window.confirm(
        "Republier la mise en scène d'avant la dernière publication ?" + perte)) {
      return Promise.resolve();
    }
    return publierModele(modele, "Publication précédente rétablie.");
  }

  /** Jette le brouillon et reprend ce qui est réellement à l'antenne. */
  function abandonner() {
    if (etat.brouillon > 0 &&
        !window.confirm(etat.brouillon + " modification(s) seront perdues. Continuer ?")) {
      return Promise.resolve();
    }
    annulerPublicationDifferee();
    oublierBrouillon();
    return charger();
  }

  // ── Le fil de l'eau ─────────────────────────────────────────────────────

  // Le repos au bout duquel une modification part, case cochée. Un glisser ne
  // compte qu'une fois (`finirManip`), mais une frappe dans un champ ou une
  // flèche maintenue en produit une par événement : sans ce délai, un PUT par
  // caractère tapé.
  const DIRECT_DELAI_MS = 250;
  let directMinuteur = null;

  function annulerPublicationDifferee() {
    if (directMinuteur) {
      clearTimeout(directMinuteur);
      directMinuteur = null;
    }
  }

  function programmerPublicationDirecte() {
    annulerPublicationDifferee();
    directMinuteur = setTimeout(function () {
      directMinuteur = null;
      // Rien PENDANT le geste : `adopter()` remplace `etat.layout`, et
      // `manip.element` pointerait alors sur un objet détaché — le glisser en
      // cours se poursuivrait dans le vide. On attend le relâchement.
      if (manip) { programmerPublicationDirecte(); return; }
      if (etat.brouillon > 0) publier();
    }, DIRECT_DELAI_MS);
  }

  // ── Annuler et refaire les gestes d'édition ─────────────────────────────
  //
  // À NE PAS CONFONDRE avec « Annuler la publication », juste en dessous : ce
  // cran-là porte sur ce qui est à l'ANTENNE et repasse par le serveur.
  // Celui-ci défait des gestes du BROUILLON, sans rien envoyer.
  //
  // CHAQUE PAS GARDE LE MODÈLE ENTIER. Ce n'est pas un éditeur de texte : un
  // seul geste touche ici des dizaines d'éléments à la fois (aligner, répartir,
  // grouper, coller), et un journal de deltas coûterait plus cher à tenir juste
  // qu'une copie de quelques kilo-octets. D'où la borne — vingt pas, au-delà le
  // plus ancien sort par le haut.
  const HISTOIRE_PAS = 20;
  // Deux appels de MÊME SOURCE à moins d'une demi-seconde sont un seul geste :
  // taper « 12.5 » dans un champ émet quatre `input`, et quatre pas videraient
  // le cinquième de l'historique sur une seule frappe.
  const HISTOIRE_FUSION_MS = 500;

  const histoire = {
    pile: [],      // les instantanés, du plus ancien au plus récent
    index: 0,      // celui qui est à l'écran
    source: null,  // ce qui a produit le dernier pas, pour fusionner une frappe
    quand: 0,
    // Les modifications déjà comptées quand la pile a commencé. Un brouillon
    // repris en porte, et un pas sorti par le haut de la pile reste une
    // modification non publiée même s'il n'est plus annulable : sans ce report,
    // le compteur retomberait à vingt après soixante gestes.
    base: 0,
  };

  function instantane() {
    return etat.layout ? JSON.parse(JSON.stringify(etat.layout)) : null;
  }

  /** Repart d'une pile neuve sur ce qui est à l'écran — ce que font `adopter()`
   *  et la reprise d'un brouillon. Annuler vers un modèle sans rapport avec ce
   *  qui est à l'antenne serait pire que de ne pas pouvoir annuler du tout. */
  function reinitialiserHistoire() {
    const debut = instantane();
    histoire.pile = debut ? [debut] : [];
    histoire.index = 0;
    histoire.source = null;
    histoire.quand = 0;
    histoire.base = etat.brouillon;
    majBoutonsHistoire();
  }

  /** Un pas de plus — ou la suite du précédent, si c'est la même frappe. */
  function pousserHistoire(source) {
    const courant = instantane();
    // Pas de modèle, ou pile jamais posée : il n'y a pas de point de départ vers
    // lequel revenir. Le compteur retombe alors sur son propre incrément.
    if (!courant || !histoire.pile.length) return;
    const maintenant = Date.now();
    const fusionne = source != null && source === histoire.source
      && histoire.index > 0
      && maintenant - histoire.quand < HISTOIRE_FUSION_MS;
    histoire.source = source;
    histoire.quand = maintenant;
    if (fusionne) { histoire.pile[histoire.index] = courant; return; }
    // Repartir dans une autre direction après une annulation efface ce qui était
    // refaisable : la règle de tous les éditeurs. Sans elle, un Ctrl+Y mènerait
    // vers un état qui n'a jamais suivi celui-ci.
    histoire.pile.length = histoire.index + 1;
    histoire.pile.push(courant);
    histoire.index += 1;
    while (histoire.pile.length > HISTOIRE_PAS + 1) {
      histoire.pile.shift();
      histoire.index -= 1;
      histoire.base += 1;
    }
  }

  /** Le compteur DÉRIVE de l'historique : sans ça, dix annulations ramèneraient
   *  la disposition de départ en affichant « 10 modifications non publiées ». */
  function compterModifications() {
    return histoire.pile.length ? histoire.base + histoire.index
                                : etat.brouillon + 1;
  }

  function appliquerHistoire() {
    const pas = histoire.pile[histoire.index];
    if (!pas) return;
    etat.layout = JSON.parse(JSON.stringify(pas));
    // La scène ou l'élément regardés peuvent ne plus exister dans le pas repris
    // — une scène supprimée, un groupe dissous. Même résolution que `adopter()`,
    // sans quoi la liste resterait sur une ligne active sans modèle derrière.
    const scenes = etat.layout.scenes || [];
    const existe = scenes.some(function (s) { return s.slug === etat.slugCourant; });
    if (!existe) {
      etat.slugCourant = etat.layout.defaut || (scenes[0] || {}).slug || null;
    }
    const scene = sceneCourante();
    if (!scene || !scene.elements[etat.elementCourant]) {
      etat.elementCourant = (scene && scene.ordre && scene.ordre[0]) || null;
    }
    nettoyerSelection();
    etat.brouillon = histoire.base + histoire.index;
    // Le geste suivant ne fusionne pas avec celui d'avant l'annulation : ils
    // sont séparés par un aller-retour dans l'historique.
    histoire.source = null;
    rangerBrouillon();
    rendreTout();
  }

  function annulerHistoire() {
    if (histoire.index <= 0) return false;
    histoire.index -= 1;
    appliquerHistoire();
    return true;
  }

  function refaireHistoire() {
    if (histoire.index >= histoire.pile.length - 1) return false;
    histoire.index += 1;
    appliquerHistoire();
    return true;
  }

  /** Ce qui reste de part et d'autre. Dit à chaque fois : un historique dont on
   *  ne voit pas le fond se tape à l'aveugle, et on finit par appuyer trois fois
   *  de trop « au cas où ». */
  function croquisHistoire() {
    return histoire.index + " à annuler, "
      + Math.max(0, histoire.pile.length - 1 - histoire.index) + " à refaire.";
  }

  /** Un raccourci qui ne répond RIEN quand il n'y a plus rien à faire se lit
   *  comme un panneau figé — on retape, plus fort. */
  function direDefait(fait) {
    notifier(fait ? "Geste annulé. " + croquisHistoire()
                  : "Rien de plus à annuler : on est au début du brouillon.");
  }

  function direRefait(fait) {
    notifier(fait ? "Geste refait. " + croquisHistoire()
                  : "Rien à refaire : on est au dernier geste.");
  }

  function majBoutonsHistoire() {
    if (noeuds.defaire) noeuds.defaire.disabled = histoire.index <= 0;
    if (noeuds.refaire) {
      noeuds.refaire.disabled = histoire.index >= histoire.pile.length - 1;
    }
  }

  /** À appeler après CHAQUE mutation locale du modèle.
   *
   *  `source` nomme le geste, pour l'historique : deux appels rapprochés de même
   *  source ne comptent que pour un pas. Les appelants qui ne la passent pas
   *  valent chacun un pas — c'est le bon défaut, un geste anonyme est un geste
   *  distinct.
   */
  function marquerModifie(source) {
    pousserHistoire(source);
    etat.brouillon = compterModifications();
    rangerBrouillon();
    rendreBarrePublication();
    if (etat.direct) programmerPublicationDirecte();
  }

  // ── Exporter et importer la mise en scène ──────────────────────────────
  //
  // LE FORMAT D'ÉCHANGE EST LE MODÈLE : ce que rend le GET, ce qu'accepte le
  // PUT. Un format à part aurait dérivé au premier champ ajouté, et un fichier
  // de la semaine dernière serait revenu amputé sans que rien ne le dise.
  //
  // LE PIÈGE EST CÔTÉ SERVEUR, ET IL NE LÈVE RIEN. `fusionner()` rend la
  // livraison par défaut sur toute entrée qui n'a pas de `scenes` exploitable
  // (bot/core/overlay_layout.py). C'est le bon comportement pour lui — un JSON
  // tronqué en base ne doit jamais donner un overlay vide en plein live —, mais
  // il veut dire qu'un fichier tordu envoyé d'ici écraserait TOUTE la mise en
  // scène par les défauts, en silence et à l'antenne. D'où le refus AVANT
  // l'envoi : ce n'est pas une revalidation du serveur, c'est la garde contre
  // son repli.

  /** `null` si c'est une mise en scène, la raison du refus sinon. */
  function refusImport(donnees) {
    if (!donnees || typeof donnees !== "object" || Array.isArray(donnees)) {
      return "ce fichier ne décrit pas une mise en scène.";
    }
    const scenes = donnees.scenes;
    if (!Array.isArray(scenes) || !scenes.length) {
      return "aucune scène là-dedans.";
    }
    const muettes = scenes.filter(function (s) {
      return !s || typeof s !== "object" || typeof s.slug !== "string"
        || !s.slug.trim();
    }).length;
    if (muettes) {
      return muettes + " scène(s) sans identifiant — fichier tronqué, ou "
        + "produit par autre chose que ce panneau.";
    }
    return null;
  }

  /** « Celui d'avant le live de samedi » : sans date, deux exports ne se
   *  distinguent pas. Deux chiffres partout — un `2026-8-3` ne se trie pas. */
  function nomExport() {
    const d = new Date();
    const deux = function (n) { return (n < 10 ? "0" : "") + n; };
    return "wally-mise-en-scene-" + d.getFullYear() + "-"
      + deux(d.getMonth() + 1) + "-" + deux(d.getDate()) + ".json";
  }

  /** Le fichier part du NAVIGATEUR et non du serveur : c'est ce qu'on a SOUS
   *  LES YEUX qu'on veut garder, brouillon compris. Passer par un GET
   *  exporterait l'antenne — l'inverse de ce qu'on demande quand on exporte
   *  avant de tenter quelque chose. */
  function exporter() {
    if (!etat.layout) {
      notifier("Rien à exporter : la mise en scène n'est pas chargée.", "error");
      return;
    }
    let url = null;
    try {
      url = URL.createObjectURL(new Blob(
        [JSON.stringify(etat.layout, null, 2)], { type: "application/json" }));
      const lien = document.createElement("a");
      lien.href = url;
      lien.download = nomExport();
      document.body.appendChild(lien);
      lien.click();
      document.body.removeChild(lien);
    } catch (e) {
      notifier("Export impossible : " + e.message, "error");
      return;
    }
    // Révoquée plus tard : tout de suite, certains navigateurs coupent le
    // téléchargement qu'ils viennent à peine de commencer.
    if (url) window.setTimeout(function () { URL.revokeObjectURL(url); }, 10000);
    notifier(etat.brouillon > 0
      ? "Exporté tel qu'à l'écran — les " + etat.brouillon
        + " modification(s) non publiée(s) sont dedans."
      : "Mise en scène exportée.");
  }

  /** Ce qu'un fichier ne garantit pas, et dont le panneau a besoin pour se
   *  dessiner sans exception : trois champs par scène. Le serveur borne et
   *  complète le reste à la publication — mais il ne le fera qu'à ce
   *  moment-là, et d'ici là c'est nous qui rendons la scène. */
  function normaliserImport(donnees) {
    (donnees.scenes || []).forEach(function (s) {
      if (!s.elements || typeof s.elements !== "object") s.elements = {};
      if (!Array.isArray(s.ordre)) s.ordre = Object.keys(s.elements);
      if (!Array.isArray(s.groupes)) s.groupes = [];
      if (typeof s.nom !== "string" || !s.nom) s.nom = s.slug;
    });
    return donnees;
  }

  function importer(fichier) {
    if (!fichier) return;
    const lecteur = new FileReader();
    lecteur.onerror = function () {
      notifier("Fichier illisible.", "error");
    };
    lecteur.onload = function () {
      let donnees = null;
      try {
        donnees = JSON.parse(String(lecteur.result));
      } catch (e) {
        notifier("Import refusé : ce n'est pas du JSON valide.", "error");
        return;
      }
      const refus = refusImport(donnees);
      if (refus) { notifier("Import refusé : " + refus, "error"); return; }
      const n = donnees.scenes.length;
      if (!window.confirm(
            "Remplacer la mise en scène par « " + fichier.name + " » ?\n\n"
            + n + " scène(s) y sont décrites.\n\nRien ne part à l'antenne : "
            + "comme tout le reste ici, l'import passe par le brouillon, et "
            + "Ctrl+Z le défait.")) {
        return;
      }
      etat.layout = normaliserImport(donnees);
      // Même résolution que `adopter()` : la scène regardée n'existe
      // probablement plus dans le fichier qui arrive.
      const scenes = etat.layout.scenes;
      const existe = scenes.some(function (s) { return s.slug === etat.slugCourant; });
      if (!existe) etat.slugCourant = etat.layout.defaut || scenes[0].slug;
      const scene = sceneCourante();
      if (!scene || !scene.elements[etat.elementCourant]) {
        etat.elementCourant = (scene && scene.ordre && scene.ordre[0]) || null;
      }
      retenirScene(etat.slugCourant);
      nettoyerSelection();
      // Un pas d'historique à lui : un import se défait comme un geste, et
      // c'est bien le moins pour l'opération qui remplace TOUT.
      marquerModifie("import");
      rendreTout();
      notifier(n + " scène(s) importée(s) — « Mettre à jour » pour les envoyer "
        + "à l'antenne.");
    };
    lecteur.readAsText(fichier);
  }

  /** Le feu vert avant une opération de STRUCTURE (renommer, dupliquer,
   *  supprimer, définir par défaut). Ces quatre-là partent tout de suite, à la
   *  différence d'un placement : leur résultat est une ADRESSE qu'on colle dans
   *  OBS, et une adresse qui n'existe qu'en brouillon est un mensonge — elle
   *  disparaît au premier F5, ce qu'on découvrait sans le moindre message.
   *
   *  Mais `publier()` envoie le MODÈLE ENTIER : un placement en attente
   *  partirait à l'antenne avec l'opération. On le dit AVANT plutôt que de le
   *  laisser découvrir en plein live. Sans brouillon — le cas courant —, aucune
   *  question n'est posée.
   */
  function accordPourPublier() {
    if (etat.brouillon === 0) return true;
    return window.confirm(
      etat.brouillon + " modification(s) de placement non publiée(s) partiront "
      + "AUSSI à l'antenne avec cette opération.\n\nContinuer ?");
  }

  // ── Ce qui a changé depuis l'antenne ────────────────────────────────────
  //
  // Le compteur du brouillon compte des GESTES ; le pied de publication doit
  // dire ce qui PART. Ce n'est pas la même chose : déplacer un élément puis le
  // ramener fait deux gestes et zéro changement. Et « 6 modifications en
  // attente » sans dire lesquelles est précisément ce qu'on ne peut pas
  // vérifier avant de cliquer, en plein live.
  //
  // La liste se calcule donc en COMPARANT le modèle affiché à `etat.publie` —
  // ce qui est réellement à l'antenne —, jamais en comptant les clics.

  let antenneSrc;              // la chaîne dont `antenneModele` a été tiré
  let antenneModele = null;

  /** Le modèle à l'antenne, désérialisé UNE FOIS par publication.
   *
   *  `JSON.parse` sur trois scènes de trente-quatre éléments à chaque rendu se
   *  paierait pendant le glisser ; la chaîne, elle, ne change qu'au retour du
   *  serveur.
   */
  function modeleAntenne() {
    if (antenneSrc === etat.publie) return antenneModele;
    antenneSrc = etat.publie;
    antenneModele = null;
    if (etat.publie) {
      try {
        antenneModele = JSON.parse(etat.publie);
      } catch (e) {
        // Ne peut arriver que si `etat.publie` n'est pas ce qu'on y a mis. Dit
        // et pas avalé : sans référence, le pied n'affiche plus aucun détail,
        // et c'est le genre de vide qu'on met des semaines à expliquer.
        if (window.console) console.error("Mise en scène — modèle à l'antenne :", e);
      }
    }
    return antenneModele;
  }

  function unPourcent(v) { return (Math.round(Number(v) * 10) / 10).toFixed(1); }
  function uneEchelle(v) { return (Math.round(Number(v) * 100) / 100).toFixed(2); }
  function uneSeconde(v) { return String(Math.round(Number(v) * 10) / 10); }

  /** Ce qui distingue deux versions d'un même élément, en français. Un tableau
   *  vide vaut « identique ».
   *
   *  Les champs sont énumérés à la main plutôt que balayés par `Object.keys` :
   *  chacun se DIT autrement — un booléen n'a pas de « avant → après » lisible,
   *  et « solo: false → true » ne veut rien dire pour qui règle un habillage.
   */
  // Ce qui se dit « libellé avant → après ». Les champs qui se disent AUTREMENT
  // — masqué, verrouillé, solo, Wally visible, ancrage, miroir — restent écrits
  // à la main juste au-dessus : « solo: false → true » ne veut rien dire pour
  // qui règle un habillage.
  //
  // `auto` s'écrit « auto » et non « 0 » : le zéro y signifie « c'est Wally qui
  // décide », et l'annoncer comme un chiffre ferait lire « durée : 0 », donc
  // « ne s'affiche plus ».
  const DITS = [
    ["opacite", "opacité", uneEchelle],
    ["rotation", "inclinaison", function (v) { return uneSeconde(v) + "°"; }],
    ["largeur_max", "largeur max", function (v) {
      return Number(v) > 0 ? Math.round(Number(v)) + " px" : "auto"; }],
    ["duree", "durée", function (v) {
      return Number(v) > 0 ? uneSeconde(v) + " s" : "auto"; }],
    ["pause", "pause", function (v) { return uneSeconde(v) + " s"; }],
    ["delai", "délai", function (v) { return uneSeconde(v) + " s"; }],
    ["anim_duree", "durée d'anim.", function (v) { return uneSeconde(v) + " s"; }],
    ["anim_entree", "entrée", function (v) { return nomAnimation(v); }],
    ["anim_sortie", "sortie", function (v) { return nomAnimation(v); }],
    ["anim_insistance", "insistance", function (v) { return nomAnimation(v); }],
  ];

  function decrireElement(avant, apres) {
    const d = [];
    if (avant.x !== apres.x) {
      d.push("x " + unPourcent(avant.x) + " → " + unPourcent(apres.x) + " %");
    }
    if (avant.y !== apres.y) {
      d.push("y " + unPourcent(avant.y) + " → " + unPourcent(apres.y) + " %");
    }
    if (avant.scale !== apres.scale) {
      d.push("taille " + uneEchelle(avant.scale) + " → " + uneEchelle(apres.scale));
    }
    if (avant.anchor !== apres.anchor) {
      d.push("ancrage " + nomAncrage(avant.anchor) + " → " + nomAncrage(apres.anchor));
    }
    if (!avant.hidden !== !apres.hidden) d.push(apres.hidden ? "masqué" : "affiché");
    if (!avant.locked !== !apres.locked) {
      d.push(apres.locked ? "verrouillé" : "déverrouillé");
    }
    if (!avant.solo !== !apres.solo) {
      d.push(apres.solo ? "prend la scène seul" : "cohabite avec les autres");
    }
    if (gardeWally(avant) !== gardeWally(apres)) {
      d.push(gardeWally(apres) ? "Wally reste visible" : "Wally s'efface");
    }
    if (!avant.miroir !== !apres.miroir) {
      d.push(apres.miroir ? "en miroir" : "sens normal");
    }
    // Les onze qui se disent tous de la même façon : « libellé avant → après ».
    // En table et non en `if` empilés — ils étaient deux, ils sont onze, et la
    // liste grandira encore.
    //
    // La règle qui compte est CONSERVÉE : un champ absent DES DEUX CÔTÉS ne
    // produit aucune ligne. Un modèle rangé avant l'ajout d'un champ ne le
    // porte pas, et « durée undefined → 9 s » annoncerait une modification que
    // personne n'a faite.
    DITS.forEach(function (dit) {
      const a = avant[dit[0]], b = apres[dit[0]];
      if (a === undefined || b === undefined || a === b) return;
      d.push(dit[1] + " " + dit[2](a) + " → " + dit[2](b));
    });
    return d;
  }

  /** Ce qui sépare une scène affichée de sa version à l'antenne : une ligne par
   *  élément touché, plus les changements qui portent sur la scène elle-même.
   *  `cle` vaut `null` sur ces derniers — c'est ce qui les distingue. */
  function diffScene(avant, apres) {
    if (!avant) return [{ cle: null, nom: apres.nom, d: "scène ajoutée" }];
    const lignes = [];
    if (avant.nom !== apres.nom) {
      lignes.push({ cle: null, nom: apres.nom,
                    d: "renommée « " + avant.nom + " » — l'adresse ne bouge pas" });
    }
    const rangAvant = {}, rangApres = {};
    (avant.ordre || []).forEach(function (c, i) { rangAvant[c] = i; });
    (apres.ordre || []).forEach(function (c, i) { rangApres[c] = i; });
    (apres.ordre || []).forEach(function (cle) {
      const el = (apres.elements || {})[cle];
      if (!el) return;
      const vieux = (avant.elements || {})[cle];
      if (!vieux) {
        lignes.push({ cle: cle, nom: libelle(cle), d: "ajouté à la scène" });
        return;
      }
      const d = decrireElement(vieux, el);
      if (rangAvant[cle] !== undefined && rangAvant[cle] !== rangApres[cle]) {
        d.push("rang " + (rangAvant[cle] + 1) + " → " + (rangApres[cle] + 1));
      }
      if (d.length) lignes.push({ cle: cle, nom: libelle(cle), d: d.join(" · ") });
    });
    Object.keys(avant.elements || {}).forEach(function (cle) {
      if (!(apres.elements || {})[cle]) {
        lignes.push({ cle: cle, nom: libelle(cle), d: "retiré de la scène" });
      }
    });
    // Les groupes se comparent en bloc : leur composition, leur ordre et leurs
    // noms tiennent en un objet, et détailler « Alice sortie du groupe 2 »
    // demanderait une seconde grammaire pour un cas qu'on règle rarement.
    if (JSON.stringify(avant.groupes || []) !== JSON.stringify(apres.groupes || [])) {
      lignes.push({ cle: null, nom: apres.nom, d: "groupes modifiés" });
    }
    return lignes;
  }

  function nomDeScene(slug) {
    const scenes = (etat.layout && etat.layout.scenes) || [];
    for (let i = 0; i < scenes.length; i++) {
      if (scenes[i].slug === slug) return scenes[i].nom;
    }
    return slug;
  }

  /** Tout ce qui partira à la prochaine publication.
   *
   *  `parScene[slug]` sert les onglets — `n` allume la pastille ambre,
   *  `elements` écrit « 5 modifiés ». `liste` sert le détail du pied.
   */
  function diffAntenne() {
    const resultat = { total: 0, parScene: {}, liste: [] };
    const antenne = modeleAntenne();
    if (!antenne || !etat.layout) return resultat;
    const parSlug = {};
    (antenne.scenes || []).forEach(function (s) { parSlug[s.slug] = s; });
    (etat.layout.scenes || []).forEach(function (scene) {
      const lignes = diffScene(parSlug[scene.slug], scene);
      let elements = 0;
      // Les clés touchées, pour la pastille ambre de chaque ligne de la liste.
      // Rendues ici plutôt que recalculées là-bas : c'est le même parcours, et
      // deux calculs du « modifié » auraient divergé au premier champ ajouté.
      const cles = {};
      lignes.forEach(function (l) {
        if (l.cle) { elements += 1; cles[l.cle] = true; }
        resultat.liste.push({ slug: scene.slug, scene: scene.nom, cle: l.cle,
                              nom: l.nom, d: l.d });
      });
      resultat.parScene[scene.slug] = { n: lignes.length, elements: elements,
                                        cles: cles };
      delete parSlug[scene.slug];
    });
    // Ce qui n'existe plus n'a plus d'onglet — et sa disparition est justement
    // ce qu'il faut avoir lu avant de publier.
    Object.keys(parSlug).forEach(function (slug) {
      resultat.liste.push({ slug: slug, scene: parSlug[slug].nom, cle: null,
                            nom: parSlug[slug].nom, d: "scène supprimée" });
    });
    if (antenne.defaut !== etat.layout.defaut) {
      const nom = nomDeScene(etat.layout.defaut);
      resultat.liste.push({ slug: etat.layout.defaut, scene: nom, cle: null,
                            nom: nom, d: "devient la scène par défaut" });
    }
    resultat.total = resultat.liste.length;
    return resultat;
  }

  // ── La liste des scènes ─────────────────────────────────────────────────

  /** Les scènes en ONGLETS, en tête du panneau.
   *
   *  Elles occupaient une colonne de 280 px à gauche, en face de la surface —
   *  280 px pris à la seule chose qu'on regarde vraiment, pour trois lignes qui
   *  ne changent jamais. En onglets, elles disent en plus ce que la colonne ne
   *  pouvait pas dire : combien d'éléments la scène montre, et combien y
   *  attendent d'être publiés.
   */
  function rendreScenes() {
    const liste = noeuds.listeScenes;
    if (!liste || !etat.layout) return;
    fermerMenu();
    // Même raison que dans `rendreElements()` : le nœud survolé disparaît, son
    // `mouseleave` ne partira jamais.
    masquerInfobulle();
    liste.innerHTML = "";
    const diff = diffAntenne();
    (etat.layout.scenes || []).forEach(function (scene) {
      const item = creer("li", "ovl-scene");
      if (scene.slug === etat.slugCourant) item.classList.add("actif");
      // Un <button> et non un <div> : c'est le geste principal de la barre, il
      // doit se prendre au clavier comme les onglets de la barre latérale.
      const corps = creer("button", "ovl-scene-corps");
      corps.type = "button";
      const haut = creer("div", "ovl-scene-haut");
      haut.appendChild(creer("span", "ovl-scene-nom", scene.nom));
      if (scene.slug === etat.layout.defaut) {
        haut.appendChild(creer("span", "ovl-badge", "défaut"));
      }
      const change = diff.parScene[scene.slug] || { n: 0, elements: 0 };
      if (change.n) {
        // La pastille ambre porte la même information que le pied, sur
        // l'onglet : sans elle, on publie sans savoir qu'une AUTRE scène part
        // aussi — et `publier()` pousse le modèle entier.
        const point = creer("span", "ovl-point");
        point.title = change.n + " modification" + (change.n > 1 ? "s" : "")
          + " en attente sur cette scène.";
        haut.appendChild(point);
      }
      corps.appendChild(haut);
      const visibles = (scene.ordre || []).filter(function (c) {
        const el = (scene.elements || {})[c];
        return el && !el.hidden;
      }).length;
      corps.appendChild(creer("div", "ovl-scene-sous",
        visibles + " visible" + (visibles > 1 ? "s" : "")
        + (change.elements
           ? " · " + change.elements + " modifié" + (change.elements > 1 ? "s" : "")
           : "")));
      corps.addEventListener("click", function () { choisirScene(scene.slug); });
      item.appendChild(corps);

      const bouton = creer("button", "ovl-menu-btn", "⋮");
      bouton.title = "Renommer, dupliquer, supprimer…";
      bouton.setAttribute("aria-label", "Actions sur la scène « " + scene.nom + " »");
      bouton.addEventListener("click", function (evt) {
        evt.stopPropagation();
        if (menuOuvert && menuOuvert.parentNode === item) { fermerMenu(); return; }
        ouvrirMenu(item, scene, bouton);
      });
      item.appendChild(bouton);

      liste.appendChild(item);
    });
    rendreSource();
  }

  /** L'adresse de la scène AFFICHÉE, à droite de la barre d'onglets.
   *
   *  Une seule adresse au lieu d'une par ligne : c'est celle de la scène qu'on
   *  règle qu'on va coller dans OBS, et trois adresses empilées prenaient la
   *  place sans qu'on lise jamais les deux autres. Elle reste ENTIÈRE — la
   *  déduire de tête est ce qu'on reprochait au panneau d'avant.
   */
  function rendreSource() {
    if (!noeuds.sourceUrl) return;
    const scene = sceneCourante();
    const adresse = scene ? urlScene(scene.slug) : "";
    noeuds.sourceUrl.textContent = adresse;
    noeuds.sourceCopie.disabled = !adresse;
    noeuds.sourceCopie.setAttribute("aria-label", scene
      ? "Copier l'adresse de « " + scene.nom + " »" : "Aucune scène");
    poserInfobulle(noeuds.sourceUrl, adresse);
  }

  /** Une scène neuve, partie de la mise en scène D'ORIGINE.
   *
   *  Des défauts du serveur et pas d'une copie de la scène courante : « + Scène »
   *  doit donner une page propre, et « Dupliquer » existe pour l'autre besoin.
   *  Les valeurs viennent de `?defauts=1`, jamais d'une table écrite ici.
   */
  function nouvelleScene() {
    if (!etat.layout) return;
    if (!accordPourPublier()) return;
    const nom = window.prompt("Nom de la nouvelle scène :", "Nouvelle scène");
    if (nom === null) return;
    const propre = nom.trim();
    if (!propre) { notifier("Un nom vide n'a rien à afficher.", "error"); return; }
    const slug = slugUnique(slugDepuisNom(propre));
    chargerDefauts().then(function (defauts) {
      if (!defauts) {
        notifier("Valeurs d'origine indisponibles : le serveur n'a pas répondu. "
          + "Aucune scène créée.", "error");
        return;
      }
      const origine = elementsDefaut(defauts, slug);
      const structure = defautsStructure(defauts, slug);
      const elements = {};
      // Copie PROFONDE : les défauts sont gardés en cache pour toute la visite,
      // et une référence partagée ferait bouger la livraison au premier réglage.
      Object.keys(origine).forEach(function (cle) {
        elements[cle] = Object.assign({}, origine[cle]);
      });
      etat.layout.scenes.push({
        slug: slug,
        nom: propre,
        ordre: structure.ordre.slice(),
        elements: elements,
        groupes: JSON.parse(JSON.stringify(structure.groupes)),
      });
      etat.slugCourant = slug;
      retenirScene(slug);
      etat.elementCourant = structure.ordre[0] || null;
      nettoyerSelection();
      marquerModifie();
      rendreTout();
      // L'adresse annoncée doit EXISTER : elle part dans OBS dans la minute qui
      // suit. Elle n'est donc dite qu'une fois la scène enregistrée.
      publier("Scène « " + propre + " » créée · " + urlScene(slug));
    });
  }

  function choisirScene(slug) {
    if (etat.slugCourant === slug) return;
    etat.slugCourant = slug;
    retenirScene(slug);
    const scene = sceneCourante();
    if (scene && !scene.elements[etat.elementCourant]) {
      etat.elementCourant = (scene.ordre || [])[0] || null;
    }
    nettoyerSelection();
    rendreTout();
  }

  function fermerMenu() {
    if (menuOuvert && menuOuvert.parentNode) menuOuvert.parentNode.removeChild(menuOuvert);
    menuOuvert = null;
    menuHote = null;
    document.removeEventListener("pointerdown", fermerAuClicDehors, true);
    // Posé par le menu FLOTTANT d'un groupe seulement (`ouvrirMenuGroupe`), mais
    // retiré ici sans condition : un écouteur de défilement en capture qui
    // survit à son menu ferme celui du voisin au premier coup de molette.
    document.removeEventListener("scroll", fermerMenu, true);
  }

  function fermerAuClicDehors(evt) {
    if (menuOuvert && menuOuvert.contains(evt.target)) return;
    // Le bouton qui a OUVERT le menu ne le referme pas ici : son propre `click`
    // s'en charge, et il bascule. Sans cette exception, le `pointerdown`
    // fermait d'abord — le `click` retrouvait alors `menuOuvert` à `null` et
    // rouvrait aussitôt. Le menu ne se refermait jamais par son bouton.
    if (menuHote && menuHote.contains(evt.target)) return;
    fermerMenu();
  }

  function actionMenu(menu, texte, actif, action) {
    const b = creer("button", "ovl-menu-item", texte);
    if (!actif) b.classList.add("inactif");
    b.addEventListener("click", function (evt) {
      evt.stopPropagation();
      fermerMenu();
      action();
    });
    menu.appendChild(b);
    return b;
  }

  /** `hote` : le bouton ⋮ qui ouvre ce menu. Passé plutôt que relu — le nom
   *  `bouton` désigne ICI la fabrique de boutons du module, pas le nœud. */
  function ouvrirMenu(item, scene, hote) {
    fermerMenu();
    const menu = creer("div", "ovl-menu");
    const seule = (etat.layout.scenes || []).length <= 1;

    actionMenu(menu, "Renommer", true, function () { renommer(scene); });
    actionMenu(menu, "Dupliquer", true, function () { dupliquer(scene); });
    actionMenu(menu, "Supprimer", !seule, function () {
      if (seule) {
        notifier("Il faut au moins une scène : celle-ci ne peut pas partir.", "error");
        return;
      }
      supprimer(scene);
    });
    actionMenu(menu, "Définir par défaut", scene.slug !== etat.layout.defaut, function () {
      definirDefaut(scene);
    });
    // L'avertissement vit dans l'interface, pas seulement dans le code : c'est
    // le streamer qui pointe ses sources OBS, et il découvrirait une URL morte
    // en plein direct, écran noir.
    menu.appendChild(creer("div", "ovl-menu-note",
      "Renommer ne touche jamais à l'adresse " + urlScene(scene.slug) + " : "
      + "la source OBS continue de fonctionner."));

    item.appendChild(menu);
    menuOuvert = menu;
    menuHote = hote;
    // En phase de capture, et posé au tour suivant : sinon le clic qui vient
    // d'ouvrir le menu le referme aussitôt.
    setTimeout(function () {
      document.addEventListener("pointerdown", fermerAuClicDehors, true);
    }, 0);
  }

  function renommer(scene) {
    if (!accordPourPublier()) return;
    const nom = window.prompt(
      "Nouveau nom de la scène.\n\nL'adresse ne change PAS :\n"
      + urlScene(scene.slug)
      + "\n\nC'est voulu — vos sources OBS restent valables.", scene.nom);
    if (nom === null) return;
    const propre = nom.trim();
    if (!propre) { notifier("Un nom vide n'a rien à afficher.", "error"); return; }
    scene.nom = propre;
    marquerModifie();
    rendreScenes();
    // Redit APRÈS coup : l'avertissement du `prompt` est lu en diagonale, et
    // l'adresse figée est précisément ce qui surprend. Annoncé par `publier()`,
    // donc seulement une fois le serveur d'accord : l'annoncer ici l'aurait dit
    // aussi quand l'enregistrement échoue.
    publier("Renommée « " + propre + " ». L'adresse reste " + urlScene(scene.slug) + ".");
  }

  function dupliquer(scene) {
    if (!accordPourPublier()) return;
    const nom = window.prompt("Nom de la copie :", scene.nom + " (copie)");
    if (nom === null) return;
    const propre = nom.trim();
    if (!propre) { notifier("Un nom vide n'a rien à afficher.", "error"); return; }
    const slug = slugUnique(slugDepuisNom(propre));
    // Copie PROFONDE des éléments : un dictionnaire partagé ferait bouger les
    // deux scènes ensemble au premier réglage, ce qui est exactement le
    // contraire de ce qu'on duplique.
    const elements = {};
    Object.keys(scene.elements || {}).forEach(function (cle) {
      elements[cle] = Object.assign({}, scene.elements[cle]);
    });
    const copie = {
      slug: slug,
      nom: propre,
      ordre: (scene.ordre || []).slice(),
      elements: elements,
    };
    const scenes = etat.layout.scenes;
    scenes.splice(scenes.indexOf(scene) + 1, 0, copie);
    etat.slugCourant = slug;
    marquerModifie();
    rendreTout();
    // L'adresse annoncée doit EXISTER : elle part dans OBS dans la minute qui
    // suit. Elle n'est donc dite qu'une fois la scène enregistrée.
    publier("Scène « " + propre + " » créée · " + urlScene(slug));
  }

  function supprimer(scene) {
    if (!accordPourPublier()) return;
    if (!window.confirm("Supprimer « " + scene.nom + " » ? "
        + "Une source OBS pointée sur " + urlScene(scene.slug)
        + " affichera alors la scène par défaut.")) return;
    const scenes = etat.layout.scenes;
    scenes.splice(scenes.indexOf(scene), 1);
    if (etat.layout.defaut === scene.slug) etat.layout.defaut = scenes[0].slug;
    if (etat.slugCourant === scene.slug) etat.slugCourant = scenes[0].slug;
    marquerModifie();
    rendreTout();
    publier("Scène « " + scene.nom + " » supprimée.");
  }

  function definirDefaut(scene) {
    if (!accordPourPublier()) return;
    etat.layout.defaut = scene.slug;
    marquerModifie();
    rendreScenes();
    publier("« " + scene.nom + " » est la scène par défaut.");
  }

  // ── Le survol, dans UN SEUL sens ────────────────────────────────────────

  /** Quels côtés portent la marque, selon d'où vient le survol.
   *
   *  SENS UNIQUE, et c'est la correction : la liste éclaire l'aperçu, l'aperçu
   *  n'éclaire pas la liste.
   *
   *  Le lien était symétrique. Trente-quatre éléments, dont vingt-six partent
   *  au même endroit : une ligne ne dit pas LEQUEL des repères empilés elle
   *  désigne, et cette question-là se pose vraiment — c'est le sens qu'on
   *  garde. L'autre répondait à une question que le repère pose déjà lui-même,
   *  puisqu'il porte son nom au survol : il éclairait la ligne ET faisait
   *  défiler la liste jusqu'à elle. La liste sautait donc à chaque va-et-vient
   *  du pointeur au-dessus de la scène, ce qui se lit comme une sélection qu'on
   *  n'a pas demandée. Reproche de l'owner, mot pour mot : « survoler un
   *  élément dans la visualisation le sélectionne dans la liste ».
   *
   *  Une origine inconnue vaut « liste » : le repli est le comportement
   *  complet, jamais celui qui efface la marque sans le dire.
   */
  function cotesDuSurvol(origine, calque, liste) {
    return origine === "surface" ? [calque] : [calque, liste];
  }

  function survoler(cle, origine) {
    survole = cle;
    survoleOrigine = cle ? origine : null;
    appliquerSurvol();
  }

  /** Repose la marque après coup. Les repères ET les lignes sont reconstruits à
   *  chaque rendu — au moindre appui sur une flèche, par exemple : sans ce
   *  rappel, la marque disparaîtrait sous un pointeur qui n'a pas bougé, et le
   *  `mouseleave` du nœud détruit ne viendrait jamais la retirer de l'autre
   *  côté.
   *
   *  DEUX classes et non une : `survole` marque, `survole-liste` REMONTE le
   *  repère au-dessus des autres. Le rang n'a de sens que pour un survol venu
   *  de la LISTE — retrouver du regard, au milieu de vingt-six repères empilés,
   *  celui que désigne la ligne. Venu de la SURFACE, il se retournait contre
   *  celui qui le posait : le repère traversé passait devant celui qu'on venait
   *  de choisir dans la liste, le pointeur ne le quittait donc plus (il est
   *  maintenant dessus), et l'élément visé devenait impossible à attraper.
   *  Sur la surface, le repère qui reçoit le pointeur est DÉJÀ celui du dessus :
   *  il n'a rien à gagner à monter.
   */
  function appliquerSurvol() {
    // Les nœuds marqués sont GARDÉS, plutôt que rebalayés : cette fonction est
    // sur le chemin du pointeur (chaque entrée et chaque sortie de repère), et
    // deux `querySelectorAll` sur la liste ET la surface à chaque mouvement,
    // c'est un balayage complet du panneau par déplacement de souris.
    survoleMarques.forEach(function (n) {
      n.classList.remove("survole");
      n.classList.remove("survole-liste");
    });
    survoleMarques = [];
    if (!survole) return;
    cotesDuSurvol(survoleOrigine, noeuds.calque, noeuds.listeElements)
      .forEach(function (hote) {
        if (!hote || !hote.querySelector) return;
        const n = hote.querySelector('[data-cle="' + survole + '"]');
        if (!n) return;
        n.classList.add("survole");
        if (survoleOrigine !== "surface") n.classList.add("survole-liste");
        survoleMarques.push(n);
      });
  }

  // ── La liste des éléments ───────────────────────────────────────────────

  // La signature de tout ce que la LISTE montre — la sélection exceptée.
  //
  // `rendreElements()` repartait d'un `innerHTML = ""` : trente-sept lignes,
  // leurs quatre boutons, leurs infobulles et leur glisser jetés et refaits —
  // environ quatre cents nœuds et deux cent cinquante écouteurs — à chaque
  // clic, alors que dans l'immense majorité des cas seule la SÉLECTION avait
  // bougé, c'est-à-dire deux classes par ligne. La signature départage les deux.
  //
  // Elle doit couvrir TOUT ce que la liste affiche, sans quoi un changement
  // passerait inaperçu : un œil qui ne se ferme pas, un groupe qui garde son
  // ancien nom. D'où le détail — c'est le prix de la garde, et il est payé une
  // fois par rendu, pas quatre cents.
  let listeSignature = null;

  function signatureListe(scene) {
    const parCle = {};
    const groupes = groupesScene();
    groupes.forEach(function (g) {
      (g.membres || []).forEach(function (cle) { parCle[cle] = g.id; });
    });
    // Le « modifié » de chaque ligne EN FAIT PARTIE : sans lui, la pastille
    // ambre n'apparaîtrait qu'au prochain changement de nom ou de visibilité —
    // c'est-à-dire jamais, puisque déplacer un élément ne touche ni l'un ni
    // l'autre. Calculé une fois ici, pas une fois par ligne.
    const modifiees = clesModifiees();
    const els = (scene.ordre || []).map(function (cle) {
      const el = scene.elements[cle];
      if (!el) return cle + "\u0001absent";
      return [cle, libelle(cle), description(cle), el.hidden ? 1 : 0,
              el.locked ? 1 : 0, parCle[cle] || "",
              modifiees[cle] ? 1 : 0].join("\u0001");
    });
    const gs = groupes.map(function (g) {
      return [g.id, g.nom, estReplie(g.id) ? 1 : 0,
              membresPresents(g).join(",")].join("\u0001");
    });
    // Et le filtre : il décide de QUI est affiché. Oublié ici, taper dans la
    // recherche ne redessinerait rien — la liste se croirait à jour.
    return scene.slug + "\u0002" + els.join("\u0002")
      + "\u0003" + gs.join("\u0002")
      + "\u0003" + filtre.texte
      + (filtre.masques ? "M" : "") + (filtre.modifies ? "D" : "");
  }

  /** La sélection posée sur les lignes DÉJÀ là : deux classes par élément, une
   *  par en-tête de groupe. Le seul chemin quand la liste n'a pas changé. */
  function appliquerSelectionListe() {
    const liste = noeuds.listeElements;
    if (!liste || !liste.querySelectorAll) return;
    liste.querySelectorAll(".ovl-el[data-cle]").forEach(function (n) {
      const cle = n.dataset.cle;
      n.classList.toggle("actif", cle === etat.elementCourant);
      n.classList.toggle("selectionne", estSelectionne(cle));
    });
    const parId = {};
    groupesScene().forEach(function (g) { parId[g.id] = g; });
    liste.querySelectorAll(".ovl-groupe[data-groupe]").forEach(function (n) {
      const g = parId[n.dataset.groupe];
      const membres = g ? membresPresents(g) : [];
      // Tous membres sélectionnés, jamais une partie : même règle qu'à la
      // construction (`itemGroupe`), et pour la même raison.
      n.classList.toggle("selectionne",
        membres.length > 0 && membres.every(estSelectionne));
    });
  }

  function rendreElements() {
    const liste = noeuds.listeElements;
    const scene = sceneCourante();
    if (!liste || !scene) return;
    const sig = signatureListe(scene);
    if (sig === listeSignature && liste.firstChild) {
      appliquerSelectionListe();
      appliquerSurvol();
      return;
    }
    listeSignature = sig;
    // Le nœud survolé va disparaître : son `mouseleave` ne partira jamais, et
    // la bulle resterait plantée à l'écran.
    masquerInfobulle();
    liste.innerHTML = "";
    const modifiees = clesModifiees();
    const cherche = filtreActif();

    // Un groupe s'affiche à la place de son PREMIER membre, et emporte les
    // autres avec lui — même règle que l'empilement (`ordreGroupe`), qui est
    // normalisé à chaque changement de groupe. Cette forme-ci reste juste même
    // si l'ordre ne l'était pas encore : la liste ne montre jamais deux
    // en-têtes du même nom.
    const parCle = {};
    groupesScene().forEach(function (g) {
      (g.membres || []).forEach(function (cle) { parCle[cle] = g; });
    });
    const faits = {};
    let groupes = 0, affiches = 0;
    (scene.ordre || []).forEach(function (cle) {
      const element = scene.elements[cle];
      if (!element) return;   // une clé d'ordre sans élément : on l'ignore
      // FILTRÉ : la liste passe À PLAT, sans en-têtes de groupe. Chercher, ce
      // n'est pas parcourir une structure — c'est trouver un élément, et un
      // en-tête « Bloc Apex (1 sur 5) » ne dit rien d'utile pendant ce
      // geste-là. Cela évite aussi d'offrir un œil de groupe qui agirait sur
      // quatre membres invisibles.
      if (cherche) {
        if (!passeFiltre(cle, element, modifiees[cle])) return;
        affiches += 1;
        liste.appendChild(itemElement(cle, element, modifiees[cle]));
        return;
      }
      const groupe = parCle[cle];
      if (!groupe) {
        affiches += 1;
        liste.appendChild(itemElement(cle, element, modifiees[cle]));
        return;
      }
      if (faits[groupe.id]) return;
      faits[groupe.id] = true;
      groupes += 1;
      liste.appendChild(itemGroupe(groupe, modifiees));
    });

    if (cherche && !affiches) {
      liste.appendChild(creer("li", "ovl-vide",
        "Aucun élément ne correspond. Vider le filtre les remontre tous."));
    }
    rendreCompteListe(scene, groupes, cherche ? affiches : -1);
    if (noeuds.aideListe) {
      noeuds.aideListe.textContent = cherche
        ? "Liste filtrée : le glisser est suspendu — il déplacerait un élément "
          + "par-dessus ceux qui sont cachés. « Derrière » et « Devant » de la "
          + "bande d'inspection règlent le rang sans vider le filtre."
        : "Glisser pour changer le rang : ce qui est en haut passe devant. "
          + "Le point ambre marque un élément modifié depuis l'antenne.";
    }
    appliquerSurvol();
  }

  /** L'en-tête de la liste : ce que la scène montre, et ce qu'elle cache.
   *
   *  « 37 éléments » ne disait rien : les trente-sept sont TOUJOURS là, dans
   *  toutes les scènes — c'est `hidden` qui les distingue, et c'est lui qu'on
   *  vient régler.
   */
  function rendreCompteListe(scene, groupes, affiches) {
    if (!noeuds.compteElements) return;
    const cles = (scene.ordre || []).filter(function (c) {
      return !!scene.elements[c];
    });
    let visibles = 0;
    cles.forEach(function (c) { if (!scene.elements[c].hidden) visibles += 1; });
    const masques = cles.length - visibles;
    noeuds.compteElements.textContent = affiches >= 0
      ? affiches + " sur " + cles.length + " affichés"
      : visibles + " visible" + (visibles > 1 ? "s" : "")
        + " · " + masques + " masqué" + (masques > 1 ? "s" : "")
        + (groupes ? " · " + groupes + " groupe" + (groupes > 1 ? "s" : "") : "");
    if (noeuds.reveler) {
      noeuds.reveler.style.display = masques ? "" : "none";
      noeuds.reveler.textContent = "+ Rendre visible un des " + masques
        + " éléments masqués";
    }
  }

  // ── Le sélecteur d'animation ────────────────────────────────────────────
  //
  // Quatre-vingt-dix-sept animations réparties en dix familles : ni un
  // `<select>` natif — on n'y montre ni recherche ni aperçu — ni une liste à
  // plat, où « celle qui glisse depuis la droite » se cherche à l'œil.
  //
  // Le catalogue vient du serveur (`etat.animations`), jamais recopié ici :
  // deux listes divergent à la première mise à jour d'animate.css.

  // Ce que la clé technique ne dit pas en français. Le RESTE se DÉRIVE
  // (famille + direction) plutôt que de s'écrire : quatre-vingt-dix-sept
  // traductions à la main auraient divergé du catalogue au premier ajout, et
  // c'est exactement ce que ce chantier passe son temps à éviter.
  const NOMS_ANIM = {
    glitch: "Glitch (maison)", aucune: "Aucune",
    jackInTheBox: "Boîte à surprise", hinge: "Gond qui lâche",
    rollIn: "Roulé", rollOut: "Roulé",
    bounce: "Sautillement", flash: "Flash", pulse: "Pulsation",
    rubberBand: "Élastique", shakeX: "Secousse horizontale",
    shakeY: "Secousse verticale", headShake: "Non de la tête",
    swing: "Balancement", tada: "Ta-daa", wobble: "Vacillement",
    jello: "Gelée", heartBeat: "Battement de cœur", flip: "Retournement",
  };

  // Les suffixes de direction, du plus long au plus court : « DownBig » doit
  // être reconnu avant « Down », sinon on annonce « vers le bas » pour un
  // mouvement ample.
  const DIRECTIONS_ANIM = [
    ["DownBig", "vers le bas, ample"], ["UpBig", "vers le haut, ample"],
    ["LeftBig", "vers la gauche, ample"], ["RightBig", "vers la droite, ample"],
    ["TopLeft", "coin haut-gauche"], ["TopRight", "coin haut-droit"],
    ["BottomLeft", "coin bas-gauche"], ["BottomRight", "coin bas-droit"],
    ["DownLeft", "bas-gauche"], ["DownRight", "bas-droit"],
    ["UpLeft", "haut-gauche"], ["UpRight", "haut-droit"],
    ["Down", "vers le bas"], ["Up", "vers le haut"],
    ["Left", "vers la gauche"], ["Right", "vers la droite"],
    ["X", "axe horizontal"], ["Y", "axe vertical"],
  ];

  /** La famille d'une animation, telle que le serveur l'a rangée. */
  function familleAnimation(nom) {
    const cat = etat.animations || {};
    for (const menu of Object.keys(cat)) {
      for (const famille of Object.keys(cat[menu])) {
        if ((cat[menu][famille] || []).indexOf(nom) >= 0) return famille;
      }
    }
    return "";
  }

  /** Le nom lisible d'une animation. « fadeInUpBig » ne dit rien à qui règle
   *  un habillage ; « Fondu · vers le haut, ample » se comprend. */
  function nomAnimation(nom) {
    if (!nom) return "—";
    if (NOMS_ANIM[nom]) return NOMS_ANIM[nom];
    const famille = familleAnimation(nom);
    for (const [suffixe, dit] of DIRECTIONS_ANIM) {
      if (nom.endsWith(suffixe)) {
        return (famille || nom) + " · " + dit;
      }
    }
    return famille || nom;
  }

  /** Ouvre le catalogue sous un bouton de champ.
   *
   *  Monté sur `<body>` en `position: fixed`, comme les autres menus de ce
   *  panneau : l'inspecteur est en `overflow` et rognerait une liste qui monte.
   *  Le côté et le sens se choisissent à l'OUVERTURE — la barre passe à la
   *  ligne selon la largeur, et un ancrage figé se trompe une fois sur deux.
   */
  function ouvrirSelecteurAnim(hote, menu, courante, onChoix) {
    if (menuOuvert && menuOuvert.dataset.anim === menu
        && menuHote === hote) { fermerMenu(); return; }
    fermerMenu();
    const catalogue = (etat.animations || {})[menu];
    if (!catalogue) {
      notifier("Catalogue d'animations indisponible — rechargez le panneau.");
      return;
    }
    // `ovl-menu-flottant` est indispensable : sans elle, `.ovl-menu` reste en
    // `position: absolute; top: 100%; right: 6px` et le `left`/`top` en pixels
    // qu'on calcule plus bas ne vise plus rien.
    const boite = creer("div", "ovl-menu ovl-menu-flottant ovl-menu-anim");
    boite.dataset.anim = menu;

    const recherche = document.createElement("input");
    recherche.type = "search";
    recherche.className = "ovl-anim-recherche";
    recherche.placeholder = "Chercher une animation…";
    recherche.setAttribute("aria-label", "Chercher une animation");
    // Échap referme sans choisir, et rend le focus au bouton : sans ça, on
    // sort du menu au clavier sans savoir où l'on est revenu.
    recherche.addEventListener("keydown", function (e) {
      if (e.key !== "Escape") return;
      e.stopPropagation();
      fermerMenu();
      hote.focus();
    });
    boite.appendChild(recherche);

    const liste = creer("div", "ovl-anim-liste");
    boite.appendChild(liste);

    // La vignette d'aperçu : elle rejoue l'animation choisie au survol. Un nom
    // ne dit pas ce que fait « backInUp », et l'essayer en publiant sur
    // l'antenne n'est pas une option en plein live.
    const apercu = creer("div", "ovl-anim-apercu");
    const pastille = creer("div", "ovl-anim-pastille", "Aa");
    apercu.appendChild(pastille);
    boite.appendChild(apercu);

    let nettoyage = null;
    function jouer(nom) {
      // On retire AVANT de reposer : une classe déjà présente ne relance pas
      // l'animation, et survoler deux fois la même entrée ne montrerait rien.
      clearTimeout(nettoyage);
      pastille.className = "ovl-anim-pastille";
      if (!nom || nom === "aucune" || nom === "glitch") return;
      // Le navigateur doit voir le retrait avant l'ajout.
      void pastille.offsetWidth;
      pastille.classList.add("animate__animated", "animate__" + nom);
      // Un MINUTEUR et non `animationend` : une vignette relancée pendant son
      // animation déclenche `animationcancel`, et si `animate.min.css` n'était
      // pas servi l'événement n'arriverait jamais. Piège déjà payé sur la page.
      nettoyage = setTimeout(function () {
        pastille.className = "ovl-anim-pastille";
      }, 1400);
    }

    const entrees = [];
    Object.keys(catalogue).forEach(function (famille) {
      const titre = creer("div", "ovl-anim-famille", famille);
      liste.appendChild(titre);
      const groupe = { titre: titre, boutons: [] };
      (catalogue[famille] || []).forEach(function (nom) {
        const b = creer("button", "ovl-anim-item", nomAnimation(nom));
        b.type = "button";
        // La clé technique en second, en petit : c'est elle qui apparaît dans
        // le modèle et dans un log, et on la cherche parfois par ce nom-là.
        b.appendChild(creer("span", "ovl-anim-cle", nom));
        if (nom === courante) b.classList.add("actif");
        b.addEventListener("mouseenter", function () { jouer(nom); });
        b.addEventListener("focus", function () { jouer(nom); });
        b.addEventListener("click", function () {
          fermerMenu();
          onChoix(nom);
        });
        groupe.boutons.push({ noeud: b, nom: nom,
                              texte: (nomAnimation(nom) + " " + nom + " "
                                      + famille).toLowerCase() });
        liste.appendChild(b);
      });
      entrees.push(groupe);
    });

    // La recherche porte sur le nom FRANÇAIS, sur la clé technique ET sur la
    // famille : on connaît l'un ou l'autre selon qu'on cherche « fondu »,
    // « fadeInUp » ou « glissement ». Même parti pris que le filtre de la liste
    // des éléments.
    recherche.addEventListener("input", function () {
      const q = recherche.value.trim().toLowerCase();
      entrees.forEach(function (groupe) {
        let vus = 0;
        groupe.boutons.forEach(function (item) {
          const vu = !q || item.texte.indexOf(q) >= 0;
          item.noeud.hidden = !vu;
          if (vu) vus += 1;
        });
        // Un en-tête de famille sans membre visible n'a plus rien à annoncer.
        groupe.titre.hidden = vus === 0;
      });
    });

    document.body.appendChild(boite);
    menuOuvert = boite;
    menuHote = hote;
    const r = hote.getBoundingClientRect();
    const m = boite.getBoundingClientRect();
    const gauche = Math.max(8, Math.min(r.left, window.innerWidth - m.width - 8));
    let haut = r.bottom + 4;
    if (haut + m.height > window.innerHeight - 8) {
      haut = Math.max(8, r.top - m.height - 4);
    }
    boite.style.left = gauche + "px";
    boite.style.top = haut + "px";
    recherche.focus();
    setTimeout(function () {
      document.addEventListener("pointerdown", fermerAuClicDehors, true);
      document.addEventListener("scroll", fermerMenu, true);
    }, 0);
  }

  /** Le menu du « + » : les éléments masqués de la scène, un clic les remontre.
   *
   *  Posé sur `<body>` en `position: fixed`, comme le menu des groupes : la
   *  liste est en `overflow-y: auto` et le rognerait.
   */
  function ouvrirMenuMasques(hote) {
    if (menuOuvert && menuOuvert.dataset.reveler === "1") { fermerMenu(); return; }
    fermerMenu();
    const scene = sceneCourante();
    if (!scene) return;
    const masques = (scene.ordre || []).filter(function (c) {
      const el = scene.elements[c];
      return el && el.hidden;
    });
    if (!masques.length) {
      notifier("Tout est déjà visible dans cette scène.");
      return;
    }
    const menu = creer("div", "ovl-menu ovl-menu-flottant ovl-menu-liste");
    menu.dataset.reveler = "1";
    masques.forEach(function (cle) {
      const el = scene.elements[cle];
      const b = actionMenu(menu, libelle(cle) + " · " + cle, !el.locked,
        function () {
          if (el.locked) {
            notifier("« " + libelle(cle) + " » est verrouillé : le cadenas de "
              + "sa ligne le libère.", "error");
            return;
          }
          el.hidden = false;
          apresBascule(cle);
        });
      // Un verrouillé reste LISTÉ et grisé : absent, on le chercherait dans la
      // liste sans comprendre pourquoi il n'est pas là.
      if (el.locked) b.title = "Verrouillé : ni déplacé, ni masqué, ni remontré.";
    });
    document.body.appendChild(menu);
    menuOuvert = menu;
    menuHote = hote;
    const r = hote.getBoundingClientRect();
    const m = menu.getBoundingClientRect();
    let gauche = Math.max(8, Math.min(r.left, window.innerWidth - m.width - 8));
    let haut = r.bottom + 4;
    if (haut + m.height > window.innerHeight - 8) {
      haut = Math.max(8, r.top - m.height - 4);
    }
    menu.style.left = gauche + "px";
    menu.style.top = haut + "px";
    setTimeout(function () {
      document.addEventListener("pointerdown", fermerAuClicDehors, true);
      document.addEventListener("scroll", fermerMenu, true);
    }, 0);
  }

  /** Une ligne de groupe : l'en-tête pliable, puis les membres.
   *
   *  Les membres restent DANS LE DOCUMENT quand l'en-tête est replié — c'est le
   *  CSS qui les cache. Les retirer les ferait disparaître de
   *  `appliquerOrdreDepuisDom()`, qui lit la liste pour en tirer l'empilement :
   *  un seul glisser, et les membres de tous les groupes repliés seraient
   *  repoussés à la fin de la scène.
   */
  function itemGroupe(groupe, modifiees) {
    const scene = sceneCourante();
    const membres = membresPresents(groupe);
    const touche = membres.some(function (c) { return (modifiees || {})[c]; });
    const item = creer("li", "ovl-groupe");
    item.dataset.groupe = groupe.id;
    item.draggable = true;
    const replie = estReplie(groupe.id);
    if (replie) item.classList.add("replie");
    // Tous membres sélectionnés = le groupe est « celui qu'on manipule ». Une
    // sélection partielle ne le dit pas : ce serait la promesse d'un geste qui
    // ne toucherait qu'une partie du bloc.
    const entier = membres.length > 0 && membres.every(estSelectionne);
    if (entier) item.classList.add("selectionne");

    const entete = creer("div", "ovl-groupe-entete");
    const chevron = bouton(replie ? "▸" : "▾",
      replie ? "Déplier — montrer les " + membres.length + " membres"
             : "Replier — l'en-tête reste, les membres se cachent",
      "", function () { basculerRepli(groupe.id); });
    chevron.classList.add("ovl-groupe-chevron");
    chevron.setAttribute("aria-expanded", replie ? "false" : "true");
    entete.appendChild(chevron);

    const corps = creer("div", "ovl-groupe-corps");
    corps.appendChild(creer("span", "ovl-groupe-nom", groupe.nom));
    // La pastille du groupe : un membre replié qui a bougé ne se voit nulle
    // part, et c'est précisément ce qu'on publie sans l'avoir vu.
    if (touche) {
      const point = creer("span", "ovl-point");
      point.title = "Au moins un membre a bougé depuis l'antenne.";
      corps.appendChild(point);
    }
    corps.addEventListener("click", function () { selectionnerGroupe(groupe); });
    poserInfobulle(corps, "Sélectionner le groupe entier — c'est-à-dire ses "
      + membres.length + " membres : " + membres.map(libelle).join(", ")
      + ". Tout ce qui vaut pour une sélection vaut alors pour eux — les "
      + "déplacer d'un bloc, les aligner, les répartir.");
    entete.appendChild(corps);

    // L'œil et le cadenas du groupe agissent sur les MEMBRES : un groupe n'a pas
    // d'état à lui. Ils montrent l'état d'ensemble — masqué quand tous le sont.
    const cles = membres.slice();
    const tousMasques = membres.length > 0 && membres.every(function (c) {
      return scene.elements[c].hidden;
    });
    const tousVerrous = membres.length > 0 && membres.every(function (c) {
      return scene.elements[c].locked;
    });
    // Le compte voyage avec les boutons, sur le second rang de l'en-tête : le
    // NOM garde alors toute la largeur de la colonne. « Tableau de bord Apex »
    // sortait en « TABLEAU… », et un groupe qu'on ne peut pas lire ne se
    // reconnaît pas.
    const actions = creer("div", "ovl-el-actions ovl-groupe-actions");
    actions.appendChild(creer("span", "ovl-groupe-compte",
      membres.length + " élément" + (membres.length > 1 ? "s" : "")));
    actions.appendChild(bouton(tousMasques ? "🚫" : "👁",
      tousMasques ? "Tous masqués — cliquer pour tout remontrer"
                  : "Masquer tout le groupe dans cette scène. Un membre "
                    + "verrouillé ne bougera pas, et ce sera dit.",
      tousMasques ? "actif" : "",
      function () {
        basculerChamp("hidden", "masqués", "remontrés", cles);
      }));
    actions.appendChild(bouton(tousVerrous ? "🔒" : "🔓",
      tousVerrous ? "Tous verrouillés — cliquer pour tout libérer"
                  : "Verrouiller tout le groupe : ni déplacé, ni "
                    + "redimensionné, ni masqué.",
      tousVerrous ? "actif" : "",
      function () {
        basculerChamp("locked", "verrouillés", "libérés", cles);
      }));
    // `boutonMenu` se cite lui-même : la fonction n'est appelée qu'au clic,
    // longtemps après l'affectation du `const`.
    const boutonMenu = bouton("⋮", "Renommer, ajouter la sélection, dissoudre…",
      "", function () { ouvrirMenuGroupe(boutonMenu, groupe); });
    actions.appendChild(boutonMenu);
    entete.appendChild(actions);
    item.appendChild(entete);

    const liste = creer("ul", "ovl-groupe-membres");
    membres.forEach(function (cle) {
      liste.appendChild(itemElement(cle, scene.elements[cle],
                                    (modifiees || {})[cle]));
    });
    item.appendChild(liste);
    brancherGlisser(item, groupe.id);
    return item;
  }

  /** Le menu d'un groupe, posé sur `<body>` en `position: fixed`.
   *
   *  Pas dans la liste : celle-ci est en `overflow-y: auto` sur 420 px, et un
   *  menu né dedans y serait rogné — c'est exactement pour ça que l'infobulle
   *  vit déjà sur `<body>`. Il se ferme au défilement plutôt que de suivre : un
   *  menu accroché à un bouton parti ailleurs est pire qu'un menu fermé.
   */
  function ouvrirMenuGroupe(hote, groupe) {
    if (menuOuvert && menuOuvert.dataset.groupe === groupe.id) { fermerMenu(); return; }
    fermerMenu();
    const menu = creer("div", "ovl-menu ovl-menu-flottant");
    menu.dataset.groupe = groupe.id;
    const membres = membresPresents(groupe);
    const aAjouter = selection().filter(function (c) {
      return (groupe.membres || []).indexOf(c) < 0;
    }).length;

    actionMenu(menu, "Sélectionner les " + membres.length + " membres", true,
      function () { selectionnerGroupe(groupe); });
    actionMenu(menu, "Renommer", true, function () { renommerGroupe(groupe); });
    actionMenu(menu, aAjouter
      ? "Ajouter la sélection (" + aAjouter + ")"
      : "Ajouter la sélection", aAjouter > 0, function () {
        if (!aAjouter) {
          notifier("Sélectionnez d'abord des éléments hors de « "
            + groupe.nom + " ».", "error");
          return;
        }
        ajouterAuGroupe(groupe);
      });
    actionMenu(menu, "Dissoudre le groupe", true, function () {
      dissoudreGroupe(groupe);
    });
    menu.appendChild(creer("div", "ovl-menu-note",
      "Dissoudre ne déplace rien et n'efface rien : les éléments gardent leur "
      + "place, leur masquage et leur cadenas."));

    document.body.appendChild(menu);
    menuOuvert = menu;
    menuHote = hote;
    const r = hote.getBoundingClientRect();
    const m = menu.getBoundingClientRect();
    let gauche = r.right - m.width;
    gauche = Math.max(8, Math.min(gauche, window.innerWidth - m.width - 8));
    let haut = r.bottom + 4;
    if (haut + m.height > window.innerHeight - 8) {
      haut = Math.max(8, r.top - m.height - 4);
    }
    menu.style.left = gauche + "px";
    menu.style.top = haut + "px";
    setTimeout(function () {
      document.addEventListener("pointerdown", fermerAuClicDehors, true);
      document.addEventListener("scroll", fermerMenu, true);
    }, 0);
  }

  function itemElement(cle, element, modifie) {
    const item = creer("li", "ovl-el");
    item.dataset.cle = cle;
    // Une liste FILTRÉE ne se réordonne pas : `appliquerOrdreDepuisDom()` lit
    // la liste pour en tirer l'empilement, et il n'y verrait qu'une partie des
    // clés — les autres seraient repoussées à la fin de la scène au premier
    // glisser. Le rang se règle alors par « Derrière » / « Devant ».
    item.draggable = !filtreActif();
    if (cle === etat.elementCourant) item.classList.add("actif");
    if (estSelectionne(cle)) item.classList.add("selectionne");
    if (element.hidden) item.classList.add("masque");
    if (element.locked) item.classList.add("verrouille");

    item.appendChild(creer("span", "ovl-el-poignee", "⠿"));
    const corps = creer("div", "ovl-el-corps");
    // Le nom lisible passe devant ; la clé technique reste sous les yeux, en
    // petit — c'est elle qui apparaît dans les logs et dans le JSON exporté.
    corps.appendChild(creer("span", "ovl-el-nom", libelle(cle)));
    corps.appendChild(creer("span", "ovl-el-cle", cle));
    if (modifie) {
      const point = creer("span", "ovl-point");
      point.title = "Modifié depuis l'antenne — le détail est dans le pied.";
      corps.appendChild(point);
    }
    item.appendChild(corps);
    poserInfobulle(corps, description(cle));

    const actions = creer("div", "ovl-el-actions");
    // L'œil est GRISÉ sous cadenas, comme les champs de la barre de réglages :
    // le verrou bloque la visibilité au même titre que la position et la
    // taille. Grisé plutôt qu'absent — un bouton qui disparaît fait douter de
    // ce qu'on a sous les yeux.
    const oeil = bouton(
      element.hidden ? "🚫" : "👁",
      element.locked
        ? "Verrouillé : ni déplacé, ni redimensionné, ni masqué. Le cadenas "
          + "ci-contre le libère."
        : (element.hidden ? "Masqué dans cette scène — cliquer pour montrer"
                          : "Visible — cliquer pour masquer dans cette scène"),
      element.hidden ? "actif" : "",
      function () { element.hidden = !element.hidden; apresBascule(cle); });
    oeil.disabled = !!element.locked;
    actions.appendChild(oeil);
    actions.appendChild(bouton(
      element.locked ? "🔒" : "🔓",
      element.locked ? "Verrouillé — il ne bougera pas au glisser"
                     : "Libre — cliquer pour le verrouiller",
      element.locked ? "actif" : "",
      function () { element.locked = !element.locked; apresBascule(cle); }));
    actions.appendChild(bouton("▶",
      "Afficher cet élément avec un contenu d'exemple, dans l'aperçu de CETTE "
      + "scène — jamais sur celle qui est à l'antenne.", "",
      function () { tester(cle); }));
    // Le retrait n'apparaît QUE sur un membre : un quatrième bouton sur les
    // trente-quatre lignes, dont vingt n'en ont que faire, encombrerait une
    // colonne de 280 px pour rien.
    const sien = groupeDe(cle);
    if (sien) {
      actions.appendChild(bouton("⊖",
        "Retirer de « " + sien.nom + " » — l'élément ne bouge pas, il cesse "
        + "seulement de suivre le groupe.", "",
        function () { retirerDuGroupe(cle); }));
    }
    item.appendChild(actions);

    item.addEventListener("click", function (evt) {
      if (evt.target.closest && evt.target.closest(".ovl-el-actions")) return;
      if (evt.ctrlKey || evt.metaKey) { basculerSelection(cle); return; }
      if (evt.shiftKey) {
        // Sans ça, le navigateur sélectionne le TEXTE des lignes traversées :
        // la liste passe en surbrillance bleue et on ne voit plus la nôtre.
        evt.preventDefault();
        etendreSelection(cle);
        return;
      }
      selectionner(cle);
    });
    // `mouseenter`/`mouseleave` et non `mouseover` : ceux-là ne se déclenchent
    // pas en repassant d'un enfant à l'autre de la ligne.
    item.addEventListener("mouseenter", function () { survoler(cle, "liste"); });
    item.addEventListener("mouseleave", function () { survoler(null, "liste"); });
    brancherGlisser(item, cle);
    return item;
  }

  function bouton(texte, titre, cls, action) {
    const b = creer("button", "ovl-act" + (cls ? " " + cls : ""), texte);
    b.title = titre;
    b.addEventListener("click", function (evt) { evt.stopPropagation(); action(); });
    return b;
  }

  // ── Tester ──────────────────────────────────────────────────────────────

  /** Le ▶ d'une ligne : affiche l'élément POUR DE VRAI, avec un contenu
   *  d'exemple, sur la seule page de la scène en cours d'édition.
   *
   *  Le slug voyage dans le corps de la requête, et l'événement le porte
   *  jusqu'à la page : c'est lui qui garantit qu'un dé d'essai ne surgit pas
   *  en plein live pendant qu'on prépare la scène de fin. */
  function tester(cle) {
    const scene = sceneCourante();
    if (!scene) return;
    const element = scene.elements[cle];
    envoyerApercu({ scene: scene.slug, element: cle }, function (reponse) {
      // Le serveur a un mot à dire : c'est le cas de l'avatar, que ▶ ne
      // déclenche pas — il dégage la scène pour le rendre visible. Écrire le
      // message ici l'aurait éloigné du code qui décide.
      if (reponse && reponse.message) { notifier(reponse.message); return; }
      if (element && element.hidden) {
        // Publié quand même — mais la page le masque, et un aperçu qui ne
        // bouge pas passerait pour un bouton cassé.
        notifier(libelle(cle) + " est masqué dans cette scène : il ne "
          + "s'affichera pas tant qu'il l'est.", "error");
        return;
      }
      notifier(libelle(cle) + " affiché dans « " + scene.nom + " »"
        + mentionApercu(scene));
    });
  }

  /** Tous les éléments visibles d'un coup, pour juger de leur cohabitation. */
  function testerTous() {
    const scene = sceneCourante();
    if (!scene) return;
    envoyerApercu({ scene: scene.slug, tous: true }, function () {
      notifier("Repères posés sur « " + scene.nom
        + " » — ils s'effacent au bout de 30 s." + mentionApercu(scene));
    });
  }

  /** Le rappel qui compte quand l'aperçu manque : sans lui, on dit « affiché »
   *  à quelqu'un qui ne voit rien bouger.
   *
   *  La scène est passée en argument plutôt que relue : la réponse arrive après
   *  coup, et `sceneCourante()` peut avoir changé — ou rendre `null` si le
   *  modèle a été rechargé entre-temps, ce qui ferait échouer le message DE
   *  SUCCÈS et l'afficherait en « Test impossible ». */
  function mentionApercu(scene) {
    if (noeuds.cadre && noeuds.cadre.classList.contains("avec-apercu")) return "";
    return " · aperçu indisponible, ouvrez " + urlScene(scene.slug)
      + " à côté pour le voir.";
  }

  /** L'appel commun. Le CORPS de la réponse compte autant que son statut : un
   *  élément qui n'a pas de widget répond 200 en disant POURQUOI il ne
   *  s'applique pas — un bouton muet passerait pour une panne. */
  function envoyerApercu(corps, succes) {
    appeler(URL_APERCU, { method: "POST", body: JSON.stringify(corps) })
      .then(function (r) {
        if (!r) throw new Error("session expirée");
        // Le corps d'une erreur FastAPI porte `detail` : le lire donne au
        // streamer la raison du refus plutôt qu'un code.
        return r.json().then(
          function (d) { return { ok: r.ok, corps: d || {} }; },
          function () { return { ok: r.ok, corps: {} }; });
      })
      .then(function (res) {
        if (!res.ok) throw new Error(res.corps.detail || "le serveur a refusé");
        if (res.corps.affiche === false) {
          notifier(res.corps.raison || "Cet élément ne se déclenche pas.", "error");
          return;
        }
        succes(res.corps);
      })
      .catch(function (e) {
        notifier("Test impossible : " + (e && e.message ? e.message : "erreur"),
                 "error");
      });
  }

  function apresBascule(cle) {
    // `poserPrincipal` et non une affectation nue : basculer l'œil ou le
    // cadenas d'un membre du bloc ne doit pas dissoudre le bloc.
    poserPrincipal(cle);
    marquerModifie();
    rendreSelection();
  }

  /** Le clic simple : la sélection se réduit à ce seul élément. */
  function selectionner(cle) {
    etat.selection = cle ? [cle] : [];
    etat.elementCourant = cle || null;
    etat.ancreSelection = cle || null;
    rendreSelection();
  }

  /** Le réordonnancement à la souris. L'ordre de la LISTE est l'empilement :
   *  ce qui est en haut passe devant.
   *
   *  `glisse` porte le NŒUD tiré, et non plus une clé d'élément : depuis les
   *  groupes, ce nœud est tantôt une ligne, tantôt un en-tête et ses membres
   *  d'un bloc.
   *
   *  ON NE RÉORDONNE QU'ENTRE VOISINS DE MÊME LISTE. Un membre glissé hors de
   *  son groupe reviendrait à sa place au rendu suivant — le groupe le
   *  rassemble —, et le geste passerait pour cassé. Sortir d'un groupe se fait
   *  au ⊖ de la ligne, qui le dit.
   */
  function brancherGlisser(item, etiquette) {
    item.addEventListener("dragstart", function (evt) {
      glisse = item;
      item.classList.add("glisse");
      if (evt.dataTransfer) {
        evt.dataTransfer.effectAllowed = "move";
        // Firefox n'amorce pas le glisser sans donnée transportée.
        try { evt.dataTransfer.setData("text/plain", etiquette); } catch (e) { /* ignoré */ }
      }
      // Sans quoi le groupe qui contient la ligne partirait AUSSI : les deux
      // nœuds sont branchés, et l'événement remonte.
      evt.stopPropagation();
    });
    item.addEventListener("dragend", function (evt) {
      item.classList.remove("glisse");
      glisse = null;
      evt.stopPropagation();
      appliquerOrdreDepuisDom();
    });
    item.addEventListener("dragover", function (evt) {
      if (!glisse || glisse === item) return;
      // Listes différentes : on laisse REMONTER plutôt que d'avaler. Un groupe
      // tiré au-dessus d'un membre d'un autre groupe doit se ranger avant ou
      // après CE groupe-là, et c'est l'en-tête parent qui sait le faire.
      if (glisse.parentNode !== item.parentNode) return;
      evt.preventDefault();
      evt.stopPropagation();
      const r = item.getBoundingClientRect();
      const avant = evt.clientY < r.top + r.height / 2;
      item.parentNode.insertBefore(glisse, avant ? item : item.nextSibling);
    });
  }

  function appliquerOrdreDepuisDom() {
    const scene = sceneCourante();
    if (!scene || !noeuds.listeElements) return;
    let ordre = [];
    noeuds.listeElements.querySelectorAll("[data-cle]").forEach(function (n) {
      ordre.push(n.dataset.cle);
    });
    // Un élément absent de `ordre` ne serait pas seulement mal empilé : il ne
    // serait pas rendu du tout. On complète toujours — même garde que côté
    // Python.
    Object.keys(scene.elements || {}).forEach(function (cle) {
      if (ordre.indexOf(cle) < 0) ordre.push(cle);
    });
    // Le complètement ci-dessus ajoute EN FIN de liste : un membre de groupe qui
    // aurait manqué à la liste s'y retrouverait détaché des siens. Le
    // regroupement est refait, et il ne coûte rien quand il n'y a rien à faire.
    ordre = ordreGroupe(ordre, scene.groupes || []);
    const identique = ordre.length === (scene.ordre || []).length
      && ordre.every(function (c, i) { return scene.ordre[i] === c; });
    if (identique) return;
    scene.ordre = ordre;
    marquerModifie();
    rendreSurface();
  }

  // ── La géométrie : l'inverse exact de `styleDepuisElement` ──────────────

  /** L'ancrage d'un élément, tel que `WallyLayout` le définit.
   *
   *  Le repli reproduit `center`, exactement comme celui de `styleApercu()`
   *  quand le module de placement manque : les deux doivent raconter la même
   *  chose, sinon le rectangle affiché et le calcul du glisser divergeraient.
   */
  function ancrage(nom) {
    const W = window.WallyLayout;
    const table = (W && W.ANCRAGES) || null;
    return (table && (table[nom] || table["center"]))
      || { h: "left", v: "top", tx: "-50%", ty: "-50%" };
  }

  /** La géométrie RENDUE d'un élément sur la surface, en pixels de celle-ci.
   *
   *  C'est l'INVERSE EXACT de `WallyLayout.styleDepuisElement` ; les deux se
   *  lisent ensemble. Deux propriétés en sortent, et tout le glisser repose
   *  dessus :
   *
   *  1. Le point d'ancrage (`ax`, `ay`) est, pour les NEUF ancrages, à `x %` du
   *     bord GAUCHE et `y %` du bord HAUT. Un ancrage à droite pose
   *     `right: (100 − x) %` : son bord droit retombe donc à `x %` depuis la
   *     gauche. Le glisser est le même pour les neuf — on suit ce point.
   *  2. Ce point est AUSSI le point fixe de l'échelle : `transform-origin` est
   *     posé sur le bord mesuré, et le `translate` subit la même échelle que
   *     l'élément (`scale()` PUIS `translate()`). Redimensionner ne déplace
   *     donc jamais l'ancrage, et x/y restent valables pendant tout le geste.
   *
   *  Le `translate` se mesurant sur la taille NON transformée, le décalage vaut
   *  `échelle × taille / 2` et non `taille / 2`. C'est le défaut qui posait un
   *  élément centré et réduit à 39 % au lieu de 50 : le reproduire ici mettrait
   *  les poignées à côté de leur rectangle.
   */
  function geometrie(cle, element, W, H) {
    const a = ancrage(element.anchor);
    // La taille MESURÉE dans l'aperçu quand elle existe, l'estimation sinon.
    // Tout ce qui suit en dépend : l'alignement, la répartition, le détecteur
    // de débordement et les poignées lisent cette même boîte.
    const t = tailleRendue(cle).taille;
    const e = borner(element.scale, ECHELLE_MIN, ECHELLE_MAX, 1) * (W / CANVAS_W);
    const largeur = t[0] * e;
    const hauteur = t[1] * e;
    const ax = borner(element.x, POS_MIN, POS_MAX, 50) / 100 * W;
    const ay = borner(element.y, POS_MIN, POS_MAX, 50) / 100 * H;
    let gauche = a.h === "right" ? ax - largeur
      : (a.tx === "-50%" ? ax - largeur / 2 : ax);
    let haut = a.v === "bottom" ? ay - hauteur
      : (a.ty === "-50%" ? ay - hauteur / 2 : ay);
    let large = largeur, haute = hauteur;

    // L'INCLINAISON élargit ce que l'élément occupe : un rectangle tourné
    // déborde de son propre cadre. Sans ce calcul, le détecteur de
    // chevauchement laisserait passer deux éléments inclinés qui se recouvrent
    // vraiment, l'alignement viserait un bord qui n'existe plus, et les
    // poignées passeraient au travers de l'élément qu'elles entourent.
    //
    // La rotation est CENTRÉE (`styleDepuisElement` l'encadre d'un aller-retour
    // de recentrage) : le point d'ancrage `ax`/`ay` ne bouge donc pas — c'est
    // ce qui laisse tout le glisser intact —, et la boîte englobante grandit
    // autour du CENTRE du rectangle d'origine.
    //
    // Le redimensionnement n'est pas faussé pour autant : il raisonne en
    // RAPPORT de bras (poignée − ancre), et le facteur d'englobement, constant
    // à angle fixe, s'y annule.
    const rot = Number(element.rotation) || 0;
    if (rot) {
      const rad = Math.abs(rot) * Math.PI / 180;
      const c = Math.abs(Math.cos(rad)), s = Math.abs(Math.sin(rad));
      large = largeur * c + hauteur * s;
      haute = largeur * s + hauteur * c;
      gauche += (largeur - large) / 2;
      haut += (hauteur - haute) / 2;
    }

    return {
      ax: ax, ay: ay, echelle: e, largeur: large, hauteur: haute,
      gauche: gauche, haut: haut, droite: gauche + large, bas: haut + haute,
    };
  }

  /** L'élément déborde-t-il de la source ? Un pixel de tolérance : un élément
   *  posé pile sur le bord ne doit pas clignoter au gré des arrondis. */
  function horsCadre(g, W, H) {
    return g.gauche < -1 || g.haut < -1 || g.droite > W + 1 || g.bas > H + 1;
  }

  /** Le pointeur en pourcentage de la surface, MOINS le décalage pris à la
   *  saisie — c'est lui qui garde sous le pointeur le point exact qu'on a
   *  attrapé, quel que soit l'ancrage. Sans lui, un élément ancré
   *  `bottom-right` saute de sa largeur entière au premier pixel.
   *
   *  Le rectangle attendu est celui du CALQUE, pas de la surface : celle-ci
   *  porte une bordure d'un pixel, et les repères se placent dans sa boîte de
   *  padding. Deux pixels d'erreur systématique, précisément ceux qu'on ne
   *  veut pas.
   */
  function positionDepuisPointeur(evt, r, decalage) {
    const d = decalage || { x: 0, y: 0 };
    return {
      x: borner(((evt.clientX - r.left) / r.width) * 100 - d.x, POS_MIN, POS_MAX, 0),
      y: borner(((evt.clientY - r.top) / r.height) * 100 - d.y, POS_MIN, POS_MAX, 0),
    };
  }

  /** L'aimantation d'UNE coordonnée : la grille de 10 %, plus les bords et le
   *  centre de l'écran — les positions qu'on vise vraiment.
   *
   *  Rend aussi la ligne à afficher : une valeur qui refuse d'avancer sans
   *  qu'on voie pourquoi passe pour un blocage.
   */
  function aimanter(valeur, tolerance, actif) {
    if (!actif) return { valeur: valeur, ligne: null };
    // Les bords et le centre EN PREMIER : à distance égale ils l'emportent sur
    // la graduation de la grille, la comparaison étant stricte.
    const cibles = [0, 50, 100];
    for (let g = 0; g <= 100; g += GRILLE) cibles.push(g);
    let cible = null;
    let ecart = tolerance;
    for (let i = 0; i < cibles.length; i++) {
      const d = Math.abs(valeur - cibles[i]);
      if (d < ecart) { ecart = d; cible = cibles[i]; }
    }
    return cible === null ? { valeur: valeur, ligne: null }
                          : { valeur: cible, ligne: cible };
  }

  /** Deux décimales. Au-delà on écrirait du bruit de virgule flottante dans un
   *  modèle qui part au serveur : 0,1 ajouté dix fois vaut 0,9999999999999999. */
  function arrondi(v) { return Math.round(v * 100) / 100; }

  /** Le déplacement d'un BLOC, réduit à ce que tous ses membres supportent.
   *
   *  C'est le cœur du glisser à plusieurs. Borner chaque élément séparément
   *  serait le réflexe — et il déforme la sélection SANS RETOUR : le premier
   *  arrivé au bord s'arrête pendant que les autres continuent, et les écarts
   *  qu'on tenait à conserver sont perdus. On borne donc le DÉCALAGE COMMUN,
   *  une fois pour tous : le bloc s'arrête entier quand son premier membre
   *  touche le bord.
   *
   *  Le décalage est arrondi ICI et pas membre par membre : deux décimales
   *  posées sur chaque position feraient dériver les écarts d'un centième à
   *  chaque geste, et `depart + delta` reste exact quand les deux le sont.
   */
  function bornerDelta(groupe, dx, dy) {
    let minX = -Infinity, maxX = Infinity, minY = -Infinity, maxY = Infinity;
    groupe.forEach(function (m) {
      const x = borner(m.depart.x, POS_MIN, POS_MAX, 50);
      const y = borner(m.depart.y, POS_MIN, POS_MAX, 50);
      minX = Math.max(minX, POS_MIN - x);
      maxX = Math.min(maxX, POS_MAX - x);
      minY = Math.max(minY, POS_MIN - y);
      maxY = Math.min(maxY, POS_MAX - y);
    });
    return {
      x: arrondi(Math.min(Math.max(isFinite(dx) ? dx : 0, minX), maxX)),
      y: arrondi(Math.min(Math.max(isFinite(dy) ? dy : 0, minY), maxY)),
    };
  }

  /** Change l'ancrage SANS déplacer l'élément à l'écran.
   *
   *  L'ancrage dit quel POINT de l'élément la position repère : le changer en
   *  laissant x/y ferait sauter l'élément d'une demi-largeur, voire d'une
   *  largeur entière. On garde donc la boîte rendue et on relit dedans la
   *  position du NOUVEAU point d'ancrage. Sans ça, changer d'ancrage est un
   *  déplacement subi, et plus personne n'ose y toucher.
   *
   *  Reste un cas où l'élément bouge quand même : un point d'ancrage qui
   *  tomberait hors de 0–100 est ramené dans les bornes du modèle. Il n'y
   *  arrive que si l'élément débordait DÉJÀ du cadre, ce que le repère signale.
   */
  function reancrer(element, cle, nom, W, H) {
    const a = ancrage(nom);
    // Surface pas encore mesurée : il n'y a pas de position à conserver.
    if (!W || !H) { element.anchor = nom; return; }
    const g = geometrie(cle, element, W, H);
    const ax = a.h === "right" ? g.droite
      : (a.tx === "-50%" ? (g.gauche + g.droite) / 2 : g.gauche);
    const ay = a.v === "bottom" ? g.bas
      : (a.ty === "-50%" ? (g.haut + g.bas) / 2 : g.haut);
    element.anchor = nom;
    element.x = arrondi(borner(ax / W * 100, POS_MIN, POS_MAX, element.x));
    element.y = arrondi(borner(ay / H * 100, POS_MIN, POS_MAX, element.y));
  }

  // ── Aligner ─────────────────────────────────────────────────────────────
  //
  // LE PIÈGE DE CE PANNEAU, et il est entier ici : `x` ne désigne PAS le bord
  // gauche de l'élément, mais son POINT D'ANCRAGE. « Coller à droite » n'est
  // donc pas `x = 100` — posé sur un élément ancré `top-left`, ce serait son
  // coin gauche qu'on plaquerait sur le bord droit, et l'élément sortirait
  // ENTIÈREMENT du cadre. Sur un `bottom-right`, la même valeur tombe juste ;
  // sur un `center`, elle laisse dépasser la moitié.
  //
  // La réponse tient en deux lignes et vient de `geometrie()`, l'inverse exact
  // de `styleDepuisElement` : l'écart entre le point d'ancrage et le bord de la
  // boîte RENDUE — `g.ax − g.gauche` — vaut 0, une demi-largeur ou une largeur
  // selon la famille d'ancrage, et il porte DÉJÀ l'échelle. Il n'y a donc pas
  // neuf cas à écrire, ni de table à tenir à jour quand un ancrage s'ajoute :
  // on colle la BOÎTE au bord, puis on relit où tombe l'ancrage.

  const BORDS = ["gauche", "centre-h", "droite", "haut", "centre-v", "bas"];

  /** La position qui colle la boîte de `element` au bord demandé.
   *
   *  Le résultat est borné à 0–100 comme partout ailleurs. Un élément PLUS
   *  LARGE que le cadre ne peut pas être collé à gauche sans que son point
   *  d'ancrage sorte des bornes : il est alors ramené dedans, donc pas
   *  parfaitement collé — le repère orange « déborde du cadre » le disait déjà
   *  avant l'alignement, et le dira encore après.
   */
  function positionAlignee(cle, element, bord, W, H) {
    const g = geometrie(cle, element, W, H);
    const dx = g.ax - g.gauche;   // 0, largeur/2 ou largeur, échelle comprise
    const dy = g.ay - g.haut;
    let ax = g.ax, ay = g.ay;
    if (bord === "gauche") ax = dx;
    else if (bord === "droite") ax = W - g.largeur + dx;
    else if (bord === "centre-h") ax = (W - g.largeur) / 2 + dx;
    else if (bord === "haut") ay = dy;
    else if (bord === "bas") ay = H - g.hauteur + dy;
    else if (bord === "centre-v") ay = (H - g.hauteur) / 2 + dy;
    return {
      x: arrondi(borner(ax / W * 100, POS_MIN, POS_MAX, element.x)),
      y: arrondi(borner(ay / H * 100, POS_MIN, POS_MAX, element.y)),
    };
  }

  /** Colle CHAQUE élément de la sélection au bord demandé — jamais les uns sur
   *  les autres. C'est le comportement de tous les éditeurs, et le seul qui ait
   *  un sens : empiler trois widgets au même endroit n'aligne rien. */
  function aligner(bord) {
    const r = boiteCalque();
    if (!r || !r.width || !r.height) return;
    const bloc = selectionDeplacable();
    if (!bloc.membres.length) {
      direLesBloques(bloc.bloques);
      if (!bloc.bloques.length) notifier("Aucun élément sélectionné.", "error");
      return;
    }
    let bouge = 0;
    bloc.membres.forEach(function (m) {
      const p = positionAlignee(m.cle, m.element, bord, r.width, r.height);
      if (p.x !== m.element.x || p.y !== m.element.y) bouge += 1;
      m.element.x = p.x;
      m.element.y = p.y;
    });
    finirOutil(bouge, bloc.bloques);
  }

  // ── Répartir ────────────────────────────────────────────────────────────

  /** Les nouveaux débuts (bord gauche, ou bord haut) d'un jeu de boîtes
   *  réparties à ESPACES ÉGAUX. Pure : elle prend des boîtes, elle rend des
   *  nombres — c'est ce qu'on teste.
   *
   *  Espaces égaux entre les BOÎTES, et non écarts égaux entre leurs centres :
   *  les éléments d'une scène n'ont pas la même taille (200 px pour l'avatar,
   *  1280 pour l'image), et des centres régulièrement espacés laisseraient des
   *  vides visuellement inégaux — ce que l'œil voit, ce sont les blancs.
   *
   *  Les deux EXTRÊMES ne bougent pas : ce sont eux qui définissent la travée,
   *  et les déplacer ferait glisser la répartition à chaque clic.
   */
  function repartitionEgale(boites, horizontal) {
    const debut = function (b) { return horizontal ? b.gauche : b.haut; };
    const fin = function (b) { return horizontal ? b.droite : b.bas; };
    const taille = function (b) { return horizontal ? b.largeur : b.hauteur; };
    const tri = boites.slice().sort(function (a, b) { return debut(a) - debut(b); });
    const n = tri.length;
    let somme = 0;
    tri.forEach(function (b) { somme += taille(b); });
    // L'espace peut être NÉGATIF : c'est le cas quand les éléments sont plus
    // larges que la travée. Ils se chevauchent alors régulièrement, ce qui
    // reste la répartition demandée — les forcer à ne pas se toucher
    // déplacerait les extrêmes, qu'on a promis de laisser en place.
    const espace = (fin(tri[n - 1]) - debut(tri[0]) - somme) / (n - 1);
    let curseur = fin(tri[0]);
    return tri.map(function (b, i) {
      if (i === 0 || i === n - 1) return { boite: b, debut: debut(b) };
      const d = curseur + espace;
      curseur = d + taille(b);
      return { boite: b, debut: d };
    });
  }

  function repartir(horizontal) {
    const r = boiteCalque();
    if (!r || !r.width || !r.height) return;
    const bloc = selectionDeplacable();
    if (bloc.membres.length < 3) {
      notifier("Il faut au moins trois éléments libres pour les répartir.", "error");
      direLesBloques(bloc.bloques);
      return;
    }
    const boites = bloc.membres.map(function (m) {
      const g = geometrie(m.cle, m.element, r.width, r.height);
      g.element = m.element;
      return g;
    });
    let bouge = 0;
    repartitionEgale(boites, horizontal).forEach(function (place) {
      const b = place.boite;
      // On repasse du bord de la boîte au POINT D'ANCRAGE, même conversion que
      // l'alignement : `debut + (ax − gauche)`.
      const ancre = place.debut + (horizontal ? b.ax - b.gauche : b.ay - b.haut);
      const cle = horizontal ? "x" : "y";
      const v = arrondi(borner(ancre / (horizontal ? r.width : r.height) * 100,
                               POS_MIN, POS_MAX, b.element[cle]));
      if (v !== b.element[cle]) bouge += 1;
      b.element[cle] = v;
    });
    finirOutil(bouge, bloc.bloques);
  }

  /** La fin commune des outils : une seule modification pour toute l'opération,
   *  le rendu, et ce que le cadenas a retenu. Un outil qui ne change rien le
   *  DIT — muet, il passerait pour cassé. */
  function finirOutil(bouge, bloques) {
    if (bouge > 0) marquerModifie();
    rendreSurface();
    rendreReglages();
    direLesBloques(bloques);
    if (!bouge && !(bloques && bloques.length)) {
      notifier("Rien à changer : c'était déjà en place.");
    }
  }

  // ── La surface de placement ─────────────────────────────────────────────

  /** La boîte du CALQUE — la référence commune du pointeur, des repères et des
   *  poignées. Prise sur le calque et pas sur la surface : lui seul couvre
   *  exactement la zone où les pourcentages s'appliquent. */
  function boiteCalque() {
    return noeuds.calque ? noeuds.calque.getBoundingClientRect() : null;
  }

  /** Le style d'un rectangle d'aperçu, dans le repère de la surface.
   *
   *  On réutilise `WallyLayout.styleDepuisElement` : c'est lui qui sait ce que
   *  chaque ancrage veut dire, et le recopier ici garantirait qu'un jour les
   *  deux divergent — l'aperçu mentirait alors sur le rendu réel. Une seule
   *  correction : son facteur de canvas se mesure sur la FENÊTRE (une source
   *  OBS occupe tout l'écran), alors qu'ici le canvas est la surface, large de
   *  quelques centaines de pixels. On lui passe donc une échelle pré-divisée
   *  par son propre facteur.
   */
  function styleApercu(element, largeurCadre) {
    const W = window.WallyLayout;
    const voulue = (element.scale || 1) * (largeurCadre / CANVAS_W);
    if (!W || typeof W.styleDepuisElement !== "function") {
      // Repli : la surface reste lisible même si le module de placement manque.
      // Une surface vide passerait pour une panne du serveur.
      return {
        left: element.x + "%", top: element.y + "%",
        transform: "translate(-50%, -50%) scale(" + voulue + ")",
        transformOrigin: "left top",
      };
    }
    const facteur = W.facteurCanvas() || 1;
    return W.styleDepuisElement(
      Object.assign({}, element, { scale: voulue / facteur }));
  }

  // ── Les chevauchements ──────────────────────────────────────────────────
  //
  // Deux éléments qui peuvent être à l'écran EN MÊME TEMPS et qui se recouvrent
  // deviennent illisibles en direct. Dit ici, dans le panneau, plutôt que
  // découvert par les viewers.
  //
  // QUI COMPARER. Seulement ce qui COHABITE : `solo: false`. Un élément
  // exclusif chasse les autres et passe par la file d'attente
  // (`docs/plans/2026-08-15…`, « Le modèle ») — deux exclusifs superposés ne
  // sont JAMAIS à l'écran ensemble, et les signaler ferait crier vingt-six
  // repères qui partent tous au centre. Un élément masqué dans la scène n'est
  // pas à l'écran non plus.
  //
  // AVEC QUELLE TAILLE. Celle qui est MESURÉE dans l'aperçu, jamais
  // l'estimation. Un chevauchement annoncé sur une taille supposée est une
  // fausse alerte, et une fausse alerte apprend à ne plus regarder l'alerte. Un
  // élément dont la taille n'a pas pu être lue est donc dit INDÉTERMINÉ — pas
  // « sans chevauchement », ce qui serait une affirmation qu'on n'a pas les
  // moyens de faire. Le ▶ de sa ligne l'affiche, et la mesure arrive.
  //
  // À PARTIR DE QUAND. Une intersection qui vaut moins de 15 % de la plus
  // petite des deux boîtes est un coin qui se touche : deux cartes posées côte
  // à côte se mordent de quelques pixels sans que rien ne devienne illisible.
  // Le seuil est en PART de la plus petite boîte et non en pixels : l'image
  // fait 1280 × 720, un dé 78 × 78, et une valeur absolue voudrait dire deux
  // choses opposées sur les deux.
  const CHEVAUCHEMENT_MIN = 0.15;

  /** Cet élément peut-il être à l'écran en même temps qu'un autre ? */
  function cohabite(element) {
    return !!element && !element.hidden && element.solo === false;
  }

  /** L'aire de l'intersection de deux boîtes rendues, 0 si elles ne se
   *  touchent pas. */
  function surfaceCommune(a, b) {
    const l = Math.min(a.droite, b.droite) - Math.max(a.gauche, b.gauche);
    const h = Math.min(a.bas, b.bas) - Math.max(a.haut, b.haut);
    return (l > 0 && h > 0) ? l * h : 0;
  }

  /** Les chevauchements de la scène. Pure au sens qui compte : elle ne lit que
   *  la scène, la taille de la surface et les tailles mesurées.
   *
   *  Rend trois choses, et la troisième est la plus importante :
   *    - `paires`  : les couples qui se recouvrent VRAIMENT (deux tailles lues) ;
   *    - `cles`    : les éléments concernés, pour la bordure orange ;
   *    - `indetermines` : les éléments qui cohabitent mais dont la taille n'a
   *      pas pu être lue. Ni « rien à signaler » ni une alerte : on ne sait pas,
   *      et on le dit.
   */
  function analyserChevauchements(scene, W, H) {
    const vide = { paires: [], cles: [], indetermines: [] };
    if (!scene || !W || !H) return vide;
    const boites = [], indetermines = [];
    (scene.ordre || []).forEach(function (cle) {
      const el = scene.elements[cle];
      if (!cohabite(el)) return;
      const m = tailleRendue(cle);
      if (!m.reelle) { indetermines.push(cle); return; }
      boites.push({ cle: cle, g: geometrie(cle, el, W, H) });
    });
    const paires = [], marques = {};
    for (let i = 0; i < boites.length; i++) {
      for (let j = i + 1; j < boites.length; j++) {
        const a = boites[i], b = boites[j];
        const commune = surfaceCommune(a.g, b.g);
        if (commune <= 0) continue;
        const aireMin = Math.min(a.g.largeur * a.g.hauteur,
                                 b.g.largeur * b.g.hauteur);
        if (aireMin <= 0 || commune / aireMin < CHEVAUCHEMENT_MIN) continue;
        paires.push([a.cle, b.cle]);
        marques[a.cle] = true;
        marques[b.cle] = true;
      }
    }
    return { paires: paires, cles: Object.keys(marques),
             indetermines: indetermines };
  }

  /** Ce que la barre d'état affiche. Séparée du calcul : c'est une phrase, et
   *  elle doit dire les trois cas — un chevauchement, aucun, et « je ne sais
   *  pas pour ceux-là ». */
  function texteChevauchements(analyse) {
    const parts = [];
    if (analyse.paires.length) {
      parts.push("⚠ " + analyse.paires.length + " chevauchement"
        + (analyse.paires.length > 1 ? "s" : "") + " : "
        + analyse.paires.slice(0, 3).map(function (p) {
            return libelle(p[0]) + " ↔ " + libelle(p[1]);
          }).join(", ")
        + (analyse.paires.length > 3 ? "…" : ""));
    } else {
      parts.push("aucun chevauchement");
    }
    if (analyse.indetermines.length) {
      parts.push(analyse.indetermines.length + " indéterminé"
        + (analyse.indetermines.length > 1 ? "s" : ""));
    }
    return parts.join(" · ");
  }

  /** Pose la marque orange sur les repères concernés et écrit la barre d'état.
   *  Appelée au rendu complet ET pendant le geste, où plus rien n'est
   *  reconstruit : un chevauchement qu'on ne voit qu'au relâchement fait refaire
   *  le placement. */
  function direChevauchements(analyse) {
    if (noeuds.calque) {
      const marques = {};
      analyse.cles.forEach(function (c) { marques[c] = true; });
      noeuds.calque.querySelectorAll("[data-cle]").forEach(function (n) {
        n.classList.toggle("chevauche", !!marques[n.dataset.cle]);
      });
    }
    // Gardée pour le clic de la pastille : il sélectionne les éléments en
    // cause, et il ne peut pas les recalculer — l'analyse dépend des tailles
    // mesurées à l'instant du rendu.
    derniereAnalyse = analyse;
    if (!noeuds.chevauchements) return;
    noeuds.chevauchements.textContent = texteChevauchements(analyse);
    noeuds.chevauchements.classList.toggle("alerte", analyse.paires.length > 0);
    noeuds.chevauchements.title = (analyse.paires.length
        ? "Ces éléments cohabitent (ils peuvent être à l'écran en même temps) "
          + "et se recouvrent d'au moins 15 % de la plus petite des deux "
          + "boîtes :\n" + analyse.paires.map(function (p) {
              return "  · " + libelle(p[0]) + " ↔ " + libelle(p[1]);
            }).join("\n")
        : "Aucun recouvrement entre les éléments qui peuvent être à l'écran en "
          + "même temps. Les éléments exclusifs ne sont pas comparés : ils ne "
          + "s'affichent jamais ensemble.")
      + (analyse.indetermines.length
         ? "\n\nIndéterminé pour " + analyse.indetermines.length + " élément(s) : "
           + analyse.indetermines.map(libelle).join(", ")
           + ".\nLeur taille n'a pas pu être lue dans l'aperçu — ils n'y "
           + "affichent rien. Le ▶ de leur ligne les affiche, et la mesure "
           + "arrive d'elle-même."
         : "");
  }

  // ── L'aperçu : la vraie page, dans une iframe ───────────────────────────

  /** Charge la page de la scène dans l'aperçu — et seulement quand elle change.
   *
   *  La garde sur `apercuSlug` n'est pas un détail : `rendreSurface()` est
   *  rappelée à CHAQUE frappe dans les champs X/Y/Taille. Sans elle, l'iframe
   *  se rechargerait à chaque caractère et l'aperçu clignoterait sans jamais
   *  finir de charger.
   */
  function chargerApercu(slug) {
    if (!noeuds.apercu || !slug || apercuSlug === slug) return;
    apercuSlug = slug;
    // Le document qu'on mesurait s'en va : garder ses tailles collerait les
    // repères d'une scène sur une autre.
    oublierMesures();
    apercuPret = false;
    majClassesVue();
    montrerRetry(false);
    etatApercu("Aperçu : chargement de " + urlScene(slug) + "…");
    clearTimeout(apercuMinuteur);
    apercuMinuteur = setTimeout(echecApercu, APERCU_DELAI_MS);
    noeuds.apercu.src = urlScene(slug);
  }

  function apercuCharge() {
    // Même origine : on peut VÉRIFIER que c'est bien la page d'overlay. Une
    // page d'erreur du serveur déclenche `load` elle aussi — s'en contenter
    // afficherait « aperçu en direct » sur un 404.
    let ok = false;
    try {
      const doc = noeuds.apercu.contentDocument;
      ok = !!(doc && doc.body && doc.body.hasAttribute("data-scene-slug"));
    } catch (e) {
      ok = false;   // origine devenue étrangère : il n'y a rien à lire
    }
    if (!ok) { echecApercu(); return; }
    clearTimeout(apercuMinuteur);
    apercuPret = true;
    majClassesVue();
    montrerRetry(false);
    etatApercu("Aperçu de " + urlScene(apercuSlug)
      + " — la mise en scène PUBLIÉE, pas le brouillon en cours.");
    ajusterApercu();
    brancherMesures();
  }

  function montrerRetry(visible) {
    if (noeuds.apercuRetry) noeuds.apercuRetry.style.display = visible ? "" : "none";
  }

  /** Le repli. On garde les rectangles nommés plutôt qu'une surface vide :
   *  un aperçu absent ne doit pas empêcher de placer. */
  function echecApercu() {
    clearTimeout(apercuMinuteur);
    if (!noeuds.cadre) return;
    // Sans document à lire, il n'y a plus une seule taille mesurée : on le DIT
    // (tous les repères repassent en pointillés) au lieu de garder à l'écran
    // des chiffres qui ne correspondent plus à rien.
    oublierMesures();
    apercuPret = false;
    majClassesVue();
    montrerRetry(true);
    etatApercu("Aperçu indisponible — placement sur les rectangles nommés.");
    rendreSurface();
  }

  /** L'état de l'aperçu.
   *
   *  En INFOBULLE du badge et non en texte de barre : la phrase porte l'adresse
   *  complète de la scène, elle faisait deux cents pixels de large sous le
   *  canvas pour une information qu'on lit une fois. Le point de couleur, lui,
   *  se voit sans lire.
   */
  function etatApercu(texte) {
    if (!noeuds.badge) return;
    noeuds.badge.title = texte;
  }

  /** L'iframe fait 1920×1080 LOGIQUES, puis on la réduit par `scale()`.
   *
   *  Lui donner directement la taille de la surface serait le piège central :
   *  la page calcule son facteur de canvas sur `window.innerWidth`
   *  (`WallyLayout.facteurCanvas`), donc sur la largeur qu'on lui donne. Large
   *  de 600 px, elle rendrait tout au tiers de sa taille — dans un cadre déjà
   *  réduit. L'aperçu mentirait alors précisément sur ce qu'on vient y voir.
   */
  function ajusterApercu() {
    if (!noeuds.apercu || !noeuds.cadre) return;
    const largeur = noeuds.cadre.clientWidth || 0;
    if (!largeur) return;
    const facteur = largeur / CANVAS_W;
    noeuds.apercu.style.transform = "scale(" + facteur + ")";
    // Le même facteur, DIT : sans lui, « ce rectangle fait 422 px » ne se
    // rapporte à rien de ce qu'on a sous les yeux.
    rendreEchelle(facteur);
  }

  // ── Les tailles RÉELLES, lues dans l'aperçu ─────────────────────────────
  //
  // Le repère disait la taille d'une TABLE ÉCRITE À LA MAIN
  // (`WallyLayout.TAILLES`), posée quand la surface n'affichait que des
  // rectangles nommés. Elle n'a jamais été autre chose qu'un ordre de grandeur,
  // et l'écart se voyait : 570 × 430 px de repère pour un meme qui en faisait
  // 200 × 220. Or l'aperçu est maintenant la VRAIE page, de même origine — la
  // taille est là, il suffit de la lire.
  //
  // Trois règles :
  //
  //   1. On lit `offsetWidth/offsetHeight` — la taille de MISE EN PAGE — et
  //      jamais `getBoundingClientRect()`, qui porte déjà le `scale()` du
  //      placement. Le panneau applique le sien : le compter deux fois donnerait
  //      un repère au carré de l'échelle.
  //   2. On mesure les ENFANTS du conteneur, pas le conteneur : celui-ci
  //      accueille aussi les repères de « Tout afficher » (`.ghost`), taillés
  //      sur la table estimée. Les mesurer rendrait l'estimation déguisée en
  //      mesure.
  //   3. Un widget qui n'affiche rien N'A PAS de taille. On ne devine pas : la
  //      clé reste absente, `tailleRendue()` retombe sur la table, et le repère
  //      le dit en pointillés. Le ▶ de la ligne l'affiche pour de vrai, et la
  //      mesure arrive d'elle-même.

  /** Le document de l'aperçu, s'il porte bien la page d'overlay. */
  function docApercu() {
    if (!noeuds.apercu) return null;
    try {
      const doc = noeuds.apercu.contentDocument;
      return (doc && doc.body && doc.body.hasAttribute("data-scene-slug")) ? doc : null;
    } catch (e) {
      return null;   // origine devenue étrangère : il n'y a rien à lire
    }
  }

  /** La taille du contenu RÉELLEMENT affiché dans un conteneur, ou `null`.
   *
   *  `null` et pas `[0, 0]` : les deux ne veulent pas dire la même chose, et
   *  c'est toute la question de ce lot — « je ne sais pas » ne doit jamais
   *  s'écrire comme un chiffre.
   */
  function mesurerConteneur(hote, vue) {
    let largeur = 0, hauteur = 0;
    const enfants = hote.children || [];
    for (let i = 0; i < enfants.length; i++) {
      const n = enfants[i];
      if (n.classList && n.classList.contains("ghost")) continue;
      const l = n.offsetWidth, h = n.offsetHeight;
      if (!l || !h) continue;   // `display: none`, ou pas encore mis en page
      // Au repos, la bulle et le cadre du rotateur restent dans le document à
      // `opacity: 0` : ils ont une boîte, mais personne ne les voit. Les
      // mesurer donnerait la taille d'une bulle VIDE (ses seules marges) comme
      // celle de l'élément.
      const st = vue.getComputedStyle ? vue.getComputedStyle(n) : null;
      if (st) {
        if (st.visibility === "hidden" || st.display === "none") continue;
        if (parseFloat(st.opacity) <= 0.01) continue;
      }
      // Le max et non une somme : les enfants d'un conteneur sont TOUS dans la
      // même cellule de grille (`[data-element] > * { grid-area: pile }`), donc
      // superposés. C'est exactement ce que `width: max-content` calcule.
      if (l > largeur) largeur = l;
      if (h > hauteur) hauteur = h;
    }
    return (largeur > 0 && hauteur > 0) ? [largeur, hauteur] : null;
  }

  /** Range des tailles lues, et dit si l'une a bougé.
   *
   *  Une mesure est ACQUISE : elle survit à la disparition du widget, et ne se
   *  remplace que par une autre mesure. Le dictionnaire était auparavant VIDÉ à
   *  chaque passe avant d'y remettre ce qui était visible — le cadre se calait
   *  le temps de l'affichage, puis retombait sur l'estimation dès que le widget
   *  s'en allait. C'est le « perdu après coup » de l'owner : on voyait le repère
   *  devenir juste, puis mentir à nouveau.
   *
   *  Ce qui reste peut vieillir — un sondage à cinq options est plus large qu'à
   *  deux — mais la lecture suivante l'écrase, et une taille d'hier reste
   *  infiniment plus proche que la table.
   *
   *  Le retour n'est pas une optimisation : `mesurerTout()` est rappelée par un
   *  `ResizeObserver`, et redessiner sans condition ferait clignoter les
   *  trente-quatre repères à chaque frame d'une animation d'entrée.
   */
  function fusionnerMesures(vues) {
    let change = false;
    Object.keys(vues || {}).forEach(function (cle) {
      const t = vues[cle];
      if (!Array.isArray(t) || t.length !== 2) return;
      const l = Number(t[0]), h = Number(t[1]);
      // Un zéro, un négatif ou un non-nombre poserait un repère d'un pixel au
      // milieu de la scène — pire que l'ordre de grandeur qu'il remplace.
      if (!(l > 0) || !(h > 0)) return;
      const a = mesures[cle];
      if (a && a[0] === l && a[1] === h) return;
      mesures[cle] = [l, h];
      change = true;
    });
    return change;
  }

  /** Relit toutes les tailles de ce qui est À L'ÉCRAN dans l'aperçu. */
  function mesurerTout() {
    const doc = docApercu();
    const vue = noeuds.apercu && noeuds.apercu.contentWindow;
    if (!doc || !vue) return;
    const vues = {};
    const hotes = doc.querySelectorAll("[data-element]");
    for (let i = 0; i < hotes.length; i++) {
      const cle = hotes[i].getAttribute("data-element");
      if (!cle) continue;
      const m = mesurerConteneur(hotes[i], vue);
      if (m) vues[cle] = m;
    }
    if (!fusionnerMesures(vues)) return;
    // Pendant un geste, la surface ne se reconstruit pas (le repère serait
    // détruit sous le pointeur) : le rendu complet revient au relâchement.
    if (!manip) rendreSurface();
    rendreCompteMesures();
  }

  /** Fait mesurer à l'aperçu les widgets que RIEN n'affiche.
   *
   *  Sans ça, une taille n'existe que pendant que son widget est à l'écran — et
   *  au chargement du panneau, aucun ne l'est : vingt-sept cadres sur
   *  trente-quatre portaient une valeur de table et ne devenaient justes qu'au
   *  premier ▶. C'est le défaut d'origine, mot pour mot : « certaines box ne se
   *  mettent à jour que au lancement de l'élément ».
   *
   *  Le ▶ ne pouvait pas servir de mesure automatique : il passe par le serveur
   *  et PUBLIE sur le bus (`POST /overlay/preview`). Mesurer les vingt-sept
   *  widgets à l'ouverture aurait donc défilé en direct devant les viewers dès
   *  qu'on règle la scène du live. Le banc, lui, construit tout dans la page
   *  d'aperçu, sans un seul appel au serveur (`WallyBanc`, overlay.js).
   *
   *  Ce qui est déjà mesuré n'est PAS retouché : le banc monte un échantillon
   *  (quatre options de sondage, deux dés), l'écran porte les vraies données.
   */
  function mesurerBanc(vue, echantillons) {
    const banc = vue && vue.WallyBanc;
    if (!banc || typeof banc.mesurer !== "function") return false;
    let vues = null;
    try {
      vues = banc.mesurer(echantillons || etat.echantillons || {});
    } catch (e) {
      // Un banc qui casse laisse le panneau sur ses estimations, comme avant.
      return false;
    }
    const neufs = {};
    Object.keys(vues || {}).forEach(function (c) {
      if (!mesures[c]) neufs[c] = vues[c];
    });
    return fusionnerMesures(neufs);
  }

  /** Regroupe une rafale de mutations en une mesure par quart de seconde, plus
   *  une de rattrapage à l'accalmie.
   *
   *  La relance différée n'est pas de la superstition : une carte qui ENTRE le
   *  fait par une transition d'opacité, et rien n'annonce sa fin quand elle est
   *  interrompue ; une image de meme change de taille au décodage, un peu après
   *  son insertion. Mesurer une seule fois, à l'instant de la mutation,
   *  laisserait le repère sur l'estimation alors que le widget est à l'écran.
   *  Mais ce rattrapage a sa place à la FIN du flot, pas dedans.
   */
  function planifierMesure() {
    // Pendant un geste, on ne mesure rien. La surface ne se reconstruit pas de
    // toute façon (le repère serait détruit sous le pointeur) : la passe ne
    // ferait que voler du temps au seul moment où la fluidité se voit. Elle est
    // reprise au relâchement, et `mesureEnRetard` s'en souvient.
    if (manip) { mesureEnRetard = true; return; }
    clearTimeout(mesureAccalmie);
    mesureAccalmie = setTimeout(mesurerMaintenant, MESURE_ACCALMIE_MS);
    if (mesureMinuteur !== null) return;
    const reste = Math.max(0, MESURE_PERIODE_MS - (Date.now() - mesureDerniere));
    mesureMinuteur = setTimeout(mesurerMaintenant, reste);
  }

  /** La passe elle-même, et le seul endroit qui touche aux minuteurs. */
  function mesurerMaintenant() {
    clearTimeout(mesureMinuteur);
    clearTimeout(mesureAccalmie);
    mesureMinuteur = null;
    mesureAccalmie = null;
    mesureEnRetard = false;
    mesureDerniere = Date.now();
    mesurerTout();
  }

  /** Branche les guetteurs sur le document de l'aperçu.
   *
   *  Trois sources, parce qu'aucune ne suffit seule : le `ResizeObserver` voit
   *  une image qui se décode mais pas une bulle qui s'allume (l'opacité ne
   *  change aucune taille) ; le `MutationObserver` voit la classe qui l'allume
   *  mais pas le décodage ; les fins de transition rattrapent l'entre-deux.
   */
  function brancherMesures() {
    detacherMesures();
    const doc = docApercu();
    const vue = noeuds.apercu && noeuds.apercu.contentWindow;
    if (!doc || !vue) return;
    mesureDoc = doc;
    const scene = doc.getElementById("stage") || doc.body;
    const RO = vue.ResizeObserver || window.ResizeObserver;
    if (RO && scene) {
      mesureRO = new RO(planifierMesure);
      const hotes = doc.querySelectorAll("[data-element]");
      for (let i = 0; i < hotes.length; i++) mesureRO.observe(hotes[i]);
    }
    const MO = vue.MutationObserver || window.MutationObserver;
    if (MO && scene) {
      mesureMO = new MO(planifierMesure);
      mesureMO.observe(scene, {
        childList: true, subtree: true,
        attributes: true, attributeFilter: ["class", "style", "src"],
      });
    }
    // En capture : ces événements ne remontent pas jusqu'au document.
    doc.addEventListener("transitionend", planifierMesure, true);
    doc.addEventListener("animationend", planifierMesure, true);
    doc.addEventListener("load", planifierMesure, true);
    planifierMesure();
    lancerBanc();
  }

  /** Fait mesurer à l'aperçu tout ce qu'il n'affiche pas, et redessine. */
  function lancerBanc() {
    // Sans échantillons, le banc monterait des widgets vides et rendrait des
    // tailles fausses — un sondage sans option n'a pas la largeur d'un sondage.
    // Le GET du layout repassera ici quand il aura répondu.
    if (!etat.echantillons) return;
    if (!docApercu()) return;
    if (!mesurerBanc(noeuds.apercu.contentWindow)) return;
    if (!manip) rendreSurface();
    rendreCompteMesures();
  }

  function detacherMesures() {
    // La mesure en attente aussi : une passe programmée avant que l'aperçu ne
    // s'en aille relirait l'ANCIEN document et remettrait ses tailles juste
    // après qu'on les a jetées.
    clearTimeout(mesureMinuteur);
    clearTimeout(mesureAccalmie);
    mesureMinuteur = null;
    mesureAccalmie = null;
    mesureEnRetard = false;
    if (mesureRO) { mesureRO.disconnect(); mesureRO = null; }
    if (mesureMO) { mesureMO.disconnect(); mesureMO = null; }
    if (mesureDoc) {
      mesureDoc.removeEventListener("transitionend", planifierMesure, true);
      mesureDoc.removeEventListener("animationend", planifierMesure, true);
      mesureDoc.removeEventListener("load", planifierMesure, true);
      mesureDoc = null;
    }
  }

  /** Coupe les guetteurs ET jette les tailles. Appelée quand le document de
   *  l'aperçu s'en va : des chiffres qui survivent à ce qu'ils décrivaient sont
   *  pires qu'une estimation assumée. */
  function oublierMesures() {
    detacherMesures();
    Object.keys(mesures).forEach(function (c) { delete mesures[c]; });
    rendreCompteMesures();
  }

  /** Combien de repères disent une taille LUE, et combien une taille supposée.
   *  Sans ce compte, les pointillés se lisent comme un choix graphique. */
  function rendreCompteMesures() {
    if (!noeuds.apercuMesures) return;
    // Le point d'état du badge suit le même fait que les pointillés : sait-on
    // de quoi on parle, ou devine-t-on ?
    if (noeuds.badgePoint) {
      noeuds.badgePoint.classList.toggle("ok", apercuPret);
    }
    const scene = sceneCourante();
    const cles = (scene && scene.ordre) || [];
    // Le MÊME critère que le pointillé (`tailleRendue().reelle`), et non la
    // seule présence dans `mesures` : les boîtes mesurées par le serveur sur le
    // dossier de memes comptaient sinon comme des suppositions, et le chiffre
    // annonçait moins de mesures qu'il n'y en avait.
    let lus = 0;
    cles.forEach(function (c) { if (tailleRendue(c).reelle) lus += 1; });
    noeuds.apercuMesures.textContent = lus
      ? lus + "/" + cles.length + " mesurés"
      : "aucune taille mesurée";
    noeuds.apercuMesures.title = lus
      ? "Ces repères épousent la taille RÉELLE : lue dans l'aperçu, ou mesurée "
        + "par le serveur pour les widgets à image. Les autres, en pointillés, "
        + "portent une taille supposée — le ▶ de leur ligne les affiche pour de "
        + "vrai, et le repère se cale dessus."
      : "Aucune taille n'a pu être lue : tous les repères portent une taille "
        + "supposée. Le ▶ d'une ligne l'affiche pour de vrai.";
  }

  /** Pose sur un nœud le placement d'un élément. Les quatre bords sont remis à
   *  `auto` d'abord : le style ne pose que les deux du côté de l'ancrage, et
   *  l'ancien resterait accroché — l'élément tenu des deux côtés à la fois. */
  function appliquerStyle(noeud, element, largeur) {
    noeud.style.left = noeud.style.right = "auto";
    noeud.style.top = noeud.style.bottom = "auto";
    const style = styleApercu(element, largeur);
    Object.keys(style).forEach(function (k) { noeud.style[k] = style[k]; });
    // L'échelle du repère, et son inverse, posées pour l'ÉTIQUETTE.
    //
    // Tout ce qui vit dans un repère subit son `scale()` : le nom s'affichait
    // donc en 34 px du canvas, c'est-à-dire d'autant plus gros que la surface
    // est large et que le widget est grand — « énorme, au milieu, par-dessus
    // l'aperçu » sur un écran large. Il DÉFAIT cette échelle (`--ovl-contre`)
    // et garde la même taille à l'écran, quel que soit le repère.
    // `--ovl-echelle` sert à le borner : `100 %` de la largeur du repère, une
    // fois l'échelle défaite, dépasserait le repère de `1/e`.
    //
    // Posé ICI et pas dans `rendreSurface()` : c'est le point de style unique,
    // et le geste de redimensionnement passe par lui (`rafraichirManip`) —
    // ailleurs, l'étiquette enflerait pendant qu'on tire une poignée.
    const e = borner(element.scale, ECHELLE_MIN, ECHELLE_MAX, 1)
      * ((largeur || CANVAS_W) / CANVAS_W);
    noeud.style.setProperty("--ovl-echelle", String(e > 0 ? e : 1));
    noeud.style.setProperty("--ovl-contre", String(e > 0 ? 1 / e : 1));
  }

  /** Le squelette d'un repère : ce qui ne change JAMAIS d'un rendu à l'autre.
   *
   *  Séparé du rendu parce que c'est là que se trouvait le prix : cinq
   *  écouteurs et deux nœuds par repère, jetés et refaits pour trente-sept
   *  éléments à chaque clic, chaque frappe dans un champ, chaque flèche et
   *  chaque taille relue dans l'aperçu.
   */
  function creerRepere(cle) {
    const rect = creer("div", "ovl-rect");
    rect.dataset.cle = cle;
    rect._nom = creer("span", "ovl-rect-nom");
    rect.appendChild(rect._nom);
    rect.addEventListener("pointerdown", function (evt) { saisirRepere(evt, cle); });
    // Le repère s'éclaire LUI-MÊME, et rien d'autre : il porte déjà son nom
    // au survol, et éclairer sa ligne — pire, amener la liste jusqu'à elle —
    // se lisait comme une sélection déclenchée par un simple passage du
    // pointeur au-dessus de la scène.
    rect.addEventListener("mouseenter", function () {
      if (!manip) survoler(cle, "surface");
    });
    rect.addEventListener("mouseleave", function () {
      if (!manip) survoler(null, "surface");
    });
    return rect;
  }

  /** La surface est RÉCONCILIÉE, jamais reconstruite.
   *
   *  Elle repartait d'un `innerHTML = ""` : trente-sept rectangles, leurs
   *  étiquettes et leurs écouteurs jetés puis refaits à chaque rendu — et un
   *  rendu part au moindre clic, à chaque caractère tapé dans X/Y/Taille, à
   *  chaque flèche, et à chaque taille relue dans l'aperçu. Mesuré à vide, un
   *  simple clic de sélection coûtait 8,3 ms de reconstruction ; avec l'aperçu
   *  chargé, chaque étiquette recréée redemande sa couche de composition.
   *
   *  Les nœuds vivent donc dans `reperes`, indexés par clé, et le rendu ne fait
   *  plus que poser des styles et basculer des classes. Effet de bord voulu :
   *  le nœud d'un élément SURVIT au rendu, donc le pointeur ne perd plus sa
   *  cible sous lui, et l'infobulle ne se referme plus toute seule.
   */
  function rendreSurface() {
    const cadre = noeuds.calque;
    const scene = sceneCourante();
    if (!cadre || !scene) return;
    // Pendant un geste, on ne redessine RIEN : le geste met à jour le nœud
    // lui-même (`rafraichirManip`), et le rendu complet revient au relâchement.
    if (manip) return;
    chargerApercu(scene.slug);
    const boite = boiteCalque();
    const largeur = boite ? boite.width : 0;
    const hauteur = boite ? boite.height : 0;
    const ordre = scene.ordre || Object.keys(scene.elements || {});
    // Calculé AVANT la boucle : la marque orange et l'infobulle de chaque repère
    // en dépendent, et il faut connaître tous les voisins pour juger d'un seul.
    const chevauchent = analyserChevauchements(scene, largeur, hauteur);
    const enChevauchement = {};
    chevauchent.cles.forEach(function (c) { enChevauchement[c] = true; });
    const vus = {};
    ordre.forEach(function (cle, rang) {
      const element = scene.elements[cle];
      if (!element) return;
      vus[cle] = true;
      let rect = reperes[cle];
      if (!rect || rect.parentNode !== cadre) {
        rect = creerRepere(cle);
        reperes[cle] = rect;
        cadre.appendChild(rect);
      }
      const mesure = tailleRendue(cle);
      rect.style.width = mesure.taille[0] + "px";
      rect.style.height = mesure.taille[1] + "px";
      // Traits pointillés tant qu'on n'a pas LU la taille : le repère ne doit
      // pas se donner l'air d'une mesure quand il ne porte qu'un ordre de
      // grandeur. C'est le reproche exact auquel ce lot répond.
      rect.classList.toggle("estime", !mesure.reelle);
      appliquerStyle(rect, element, largeur);
      const choisi = cle === etat.elementCourant;
      // L'ordre de la liste EST l'empilement : le premier passe devant.
      //
      // À une exception près, et elle est décisive : LE REPÈRE CHOISI PASSE
      // AU-DESSUS DE TOUS LES AUTRES. Vingt-six éléments partent au centre,
      // exactement superposés ; sans ça, choisir un élément dans la liste ne
      // servait à rien — c'est le repère du dessus qui recevait le pointeur, et
      // on déplaçait toujours le même. La sélection ne change PAS `scene.ordre`
      // (l'empilement réel de la page), seulement ce que la surface d'édition
      // laisse attraper.
      // Les membres du bloc montent eux aussi, juste sous le principal : sans
      // ça, sélectionner trois repères empilés au centre n'en montrerait qu'un.
      rect.style.zIndex = String(choisi ? ordre.length + 2
        : (estSelectionne(cle) ? ordre.length + 1 : ordre.length - rang));
      rect.classList.toggle("masque", !!element.hidden);
      rect.classList.toggle("verrouille", !!element.locked);
      rect.classList.toggle("actif", choisi);
      rect.classList.toggle("selectionne", estSelectionne(cle));
      // Un élément qui sort du cadre se voit ICI, pas quand les viewers le
      // découvrent : le repère passe en orange et l'infobulle le dit.
      const deborde = largeur > 0
        && horsCadre(geometrie(cle, element, largeur, hauteur), largeur, hauteur);
      rect.classList.toggle("hors-cadre", deborde);
      // Deux éléments qui cohabitent et se recouvrent : illisibles en direct.
      // Signalé ici, avant que les viewers le découvrent.
      const recouvre = !!enChevauchement[cle];
      rect.classList.toggle("chevauche", recouvre);
      rect._nom.textContent = (mesure.reelle ? "" : "≈ ") + libelle(cle);
      // La taille est DITE, en pixels du canvas 1920, et sa provenance avec :
      // « ≈ 720 × 540 supposés » se corrige d'un clic sur ▶, « 586 × 642
      // mesurés » se croit sur parole.
      const dimensions = mesure.taille[0] + " × " + mesure.taille[1] + " px"
        + (mesure.reelle
           ? " (mesurés dans l'aperçu)"
           : " (supposés — ▶ affiche l'élément pour le mesurer)");
      poserInfobulle(rect, libelle(cle) + " · " + cle
        + (description(cle) ? " — " + description(cle) : "")
        + " — " + dimensions
        + (deborde ? " — ⚠ déborde du cadre" : "")
        + (recouvre ? " — ⚠ chevauche un élément qui peut être à l'écran en "
                      + "même temps" : ""));
    });
    // Ce que la scène ne porte plus. La bulle part avec eux : posée sur
    // `<body>`, elle survivrait au nœud qui l'a ouverte et resterait plantée à
    // l'écran, puisque le `mouseleave` d'un nœud détaché ne vient jamais.
    Object.keys(reperes).forEach(function (cle) {
      if (vus[cle]) return;
      const mort = reperes[cle];
      if (mort.parentNode) mort.parentNode.removeChild(mort);
      delete reperes[cle];
      masquerInfobulle();
    });
    majPoignees(largeur, hauteur);
    placerCadresGroupes(largeur, hauteur);
    appliquerSurvol();
    rendreCompteMesures();
    // La barre d'état seulement : les classes sont déjà posées par la boucle
    // ci-dessus, à partir de la MÊME analyse.
    direChevauchements(chevauchent);
  }

  /** L'enveloppe d'un jeu de boîtes rendues. Pure — c'est elle qu'on teste. */
  function boiteEnglobante(boites) {
    if (!boites || !boites.length) return null;
    let gauche = Infinity, haut = Infinity, droite = -Infinity, bas = -Infinity;
    boites.forEach(function (g) {
      gauche = Math.min(gauche, g.gauche);
      haut = Math.min(haut, g.haut);
      droite = Math.max(droite, g.droite);
      bas = Math.max(bas, g.bas);
    });
    return { gauche: gauche, haut: haut, droite: droite, bas: bas,
             largeur: droite - gauche, hauteur: bas - haut };
  }

  /** Le cadre englobant des groupes ENTIÈREMENT sélectionnés.
   *
   *  Vingt-six repères partent au même endroit : « qu'est-ce que je manipule »
   *  est la question de tout ce panneau. Un trait autour des membres y répond
   *  d'un coup d'œil, là où le liseré des lignes demande de compter.
   *
   *  Entièrement sélectionné, et pas « au moins un membre » : un cadre autour de
   *  huit widgets dont trois seulement suivraient le prochain geste promettrait
   *  ce qu'il ne tient pas.
   *
   *  Les cadres vivent HORS du calque, comme les poignées : celui-ci est vidé à
   *  chaque rendu, et le cadre doit suivre le bloc PENDANT le geste
   *  (`rafraichirManip`), quand plus rien n'est reconstruit.
   */
  function placerCadresGroupes(W, H) {
    if (!noeuds.cadre) return;
    (noeuds.cadresGroupes || []).forEach(function (n) {
      if (n.parentNode) n.parentNode.removeChild(n);
    });
    noeuds.cadresGroupes = [];
    const scene = sceneCourante();
    if (!scene || !W || !H) return;
    groupesScene().forEach(function (groupe) {
      const membres = membresPresents(groupe);
      if (!membres.length || !membres.every(estSelectionne)) return;
      const boite = boiteEnglobante(membres.map(function (cle) {
        return geometrie(cle, scene.elements[cle], W, H);
      }));
      if (!boite) return;
      const noeud = creer("div", "ovl-cadre-groupe");
      noeud.style.left = boite.gauche + "px";
      noeud.style.top = boite.haut + "px";
      noeud.style.width = boite.largeur + "px";
      noeud.style.height = boite.hauteur + "px";
      noeud.appendChild(creer("span", "ovl-cadre-groupe-nom", groupe.nom));
      noeuds.cadre.appendChild(noeud);
      noeuds.cadresGroupes.push(noeud);
    });
  }

  // ── Le glisser, les poignées, le clavier ────────────────────────────────

  /** La saisie d'un repère. On sélectionne d'abord — ce qui REDESSINE la
   *  surface —, puis on repart du nœud neuf : celui qui a reçu l'événement
   *  vient d'être remplacé. */
  function saisirRepere(evt, cle) {
    if (manip || (evt.pointerType === "mouse" && evt.button !== 0)) return;
    const scene = sceneCourante();
    const element = scene && scene.elements[cle];
    if (!element) return;
    // Le calque porte le focus clavier : il survit aux rendus, contrairement
    // aux repères, reconstruits à chaque changement.
    if (noeuds.calque.focus) noeuds.calque.focus({ preventScroll: true });
    // Ctrl et Maj COMPOSENT la sélection : aucun glisser ne part de là. Le
    // `stopPropagation` empêche le fond d'y voir le début d'un rectangle.
    if (evt.ctrlKey || evt.metaKey) {
      evt.preventDefault(); evt.stopPropagation();
      basculerSelection(cle);
      return;
    }
    if (evt.shiftKey) {
      evt.preventDefault(); evt.stopPropagation();
      etendreSelection(cle);
      return;
    }
    // Un repère DÉJÀ dans la sélection la conserve : c'est le bloc entier qu'on
    // attrape. Un repère hors sélection la remplace, comme un clic simple.
    if (!estSelectionne(cle)) selectionner(cle);
    else if (etat.elementCourant !== cle) { poserPrincipal(cle); rendreSelection(); }
    if (element.locked) {
      notifier(libelle(cle) + " est verrouillé : le cadenas de la liste le libère.",
               "error");
      return;
    }
    const r = boiteCalque();
    if (!r || !r.width || !r.height) return;
    const p = positionDepuisPointeur(evt, r, null);
    manip = {
      mode: "position",
      cle: cle,
      element: element,
      noeud: noeuds.calque.querySelector('[data-cle="' + cle + '"]'),
      pointeur: evt.pointerId,
      // Le décalage entre le pointeur et le point d'ancrage, gardé tout le
      // geste : c'est LUI qui garde sous le doigt le point qu'on a attrapé.
      decalage: { x: p.x - borner(element.x, POS_MIN, POS_MAX, 50),
                  y: p.y - borner(element.y, POS_MIN, POS_MAX, 50) },
      depart: { x: element.x, y: element.y, scale: element.scale },
      lignes: null,
    };
    // Le bloc qui suivra le pointeur. Le principal en fait partie, avec un
    // écart nul : un seul chemin de calcul pour un élément comme pour douze.
    const bloc = selectionDeplacable();
    manip.groupe = bloc.membres.map(function (m) {
      return {
        cle: m.cle, element: m.element, depart: m.depart,
        noeud: noeuds.calque.querySelector('[data-cle="' + m.cle + '"]'),
      };
    });
    // Dit AU DÉBUT du geste, pas après : découvrir au relâchement que trois
    // éléments sur cinq n'ont pas suivi, c'est refaire le placement.
    direLesBloques(bloc.bloques);
    capturer(evt);
  }

  /** La saisie d'une poignée d'angle. Elle agit sur `scale` — le modèle ne
   *  connaît pas de largeur —, donc l'élément grandit depuis son ancrage. */
  function saisirPoignee(evt, coin) {
    if (manip || (evt.pointerType === "mouse" && evt.button !== 0)) return;
    const cle = etat.elementCourant;
    const element = elementCourant();
    if (!element || element.locked) return;
    const r = boiteCalque();
    if (!r || !r.width || !r.height) return;
    const g = geometrie(cle, element, r.width, r.height);
    const poignee = { x: coin.indexOf("w") >= 0 ? g.gauche : g.droite,
                      y: coin.charAt(0) === "n" ? g.haut : g.bas };
    const centre = { x: (g.gauche + g.droite) / 2, y: (g.haut + g.bas) / 2 };
    const rayon = Math.sqrt(Math.pow(poignee.x - centre.x, 2)
                          + Math.pow(poignee.y - centre.y, 2)) || 1;
    manip = {
      mode: "echelle",
      cle: cle,
      element: element,
      noeud: noeuds.calque.querySelector('[data-cle="' + cle + '"]'),
      pointeur: evt.pointerId,
      ancre: { x: g.ax, y: g.ay },
      // Le bras qui va de l'ancrage à la poignée : c'est ce vecteur que
      // l'échelle allonge, et sur lequel on projette le pointeur.
      bras: { x: poignee.x - g.ax, y: poignee.y - g.ay },
      // Le repli quand ce bras est nul : la direction qui s'éloigne du centre.
      sortant: { x: (poignee.x - centre.x) / rayon,
                 y: (poignee.y - centre.y) / rayon },
      rayon: rayon,
      origine: { x: evt.clientX, y: evt.clientY },
      depart: { x: element.x, y: element.y,
                scale: borner(element.scale, ECHELLE_MIN, ECHELLE_MAX, 1) },
      lignes: null,
    };
    capturer(evt);
  }

  // ── Le rectangle de sélection ───────────────────────────────────────────
  //
  // Tracé sur le FOND, jamais sur un repère : le fond est le seul endroit du
  // calque qui ne serve à rien d'autre, et un glisser parti d'un repère est
  // déjà un déplacement. Ctrl (ou Maj) maintenu ajoute à la sélection au lieu
  // de la remplacer.

  function saisirFond(evt) {
    // `evt.target` et pas `currentTarget` : un repère laisse remonter son
    // `pointerdown` quand il refuse le geste (élément verrouillé), et le fond
    // ouvrirait alors un rectangle sous le doigt.
    if (manip || evt.target !== noeuds.calque) return;
    if (evt.pointerType === "mouse" && evt.button !== 0) return;
    const r = boiteCalque();
    if (!r || !r.width || !r.height) return;
    if (noeuds.calque.focus) noeuds.calque.focus({ preventScroll: true });
    const p = {
      x: ((evt.clientX - r.left) / r.width) * 100,
      y: ((evt.clientY - r.top) / r.height) * 100,
    };
    manip = {
      mode: "bande",
      pointeur: evt.pointerId,
      depart: p,
      courant: p,
      ajout: !!(evt.ctrlKey || evt.metaKey || evt.shiftKey),
      base: etat.selection.slice(),
    };
    montrerBande(r);
    capturer(evt);
  }

  /** La bande en pixels du calque — la même référence que `geometrie()`, sans
   *  quoi le rectangle qu'on voit et les repères qu'il prend divergeraient. */
  function boiteBande(m, r) {
    return {
      gauche: Math.min(m.depart.x, m.courant.x) / 100 * r.width,
      droite: Math.max(m.depart.x, m.courant.x) / 100 * r.width,
      haut: Math.min(m.depart.y, m.courant.y) / 100 * r.height,
      bas: Math.max(m.depart.y, m.courant.y) / 100 * r.height,
    };
  }

  /** Tous les repères que la bande TOUCHE — pas seulement ceux qu'elle
   *  contient. Exiger l'inclusion complète rendrait `image` (1280×720 sur
   *  1920) insélectionnable sans balayer toute la surface. */
  function reperesDansBande(m, r) {
    const scene = sceneCourante();
    if (!scene) return [];
    const b = boiteBande(m, r);
    return (scene.ordre || []).filter(function (cle) {
      const el = scene.elements[cle];
      if (!el) return false;
      const g = geometrie(cle, el, r.width, r.height);
      return g.droite >= b.gauche && g.gauche <= b.droite
          && g.bas >= b.haut && g.haut <= b.bas;
    });
  }

  /** Le rectangle vit DANS le calque : celui-ci porte les pourcentages, et la
   *  surface a une bordure d'un pixel qui décalerait tout. Il est vidé au
   *  premier rendu complet, ce qui le fait disparaître — mais `rendreSurface()`
   *  ne redessine rien pendant un geste, donc il survit au sien. */
  function montrerBande(r) {
    if (!noeuds.calque) return;
    if (!noeuds.bande) noeuds.bande = creer("div", "ovl-bande");
    if (noeuds.bande.parentNode !== noeuds.calque) noeuds.calque.appendChild(noeuds.bande);
    const b = boiteBande(manip, r);
    noeuds.bande.style.left = b.gauche + "px";
    noeuds.bande.style.top = b.haut + "px";
    noeuds.bande.style.width = (b.droite - b.gauche) + "px";
    noeuds.bande.style.height = (b.bas - b.haut) + "px";
  }

  function retirerBande() {
    if (noeuds.bande && noeuds.bande.parentNode) {
      noeuds.bande.parentNode.removeChild(noeuds.bande);
    }
  }

  /** Ce que la bande prendrait si on relâchait maintenant. Posé sur les nœuds
   *  eux-mêmes : `rendreSurface()` ne peut rien redessiner pendant le geste. */
  function marquerBande(r) {
    const dedans = {};
    if (manip.ajout) manip.base.forEach(function (c) { dedans[c] = true; });
    reperesDansBande(manip, r).forEach(function (c) { dedans[c] = true; });
    noeuds.calque.querySelectorAll("[data-cle]").forEach(function (n) {
      n.classList.toggle("selectionne", !!dedans[n.dataset.cle]);
    });
  }

  function finirBande(fini) {
    retirerBande();
    const r = boiteCalque();
    const touches = r ? reperesDansBande(fini, r) : [];
    // Un clic sur le fond, sans rien attraper : c'est la façon la plus directe
    // de tout désélectionner.
    if (!touches.length && !fini.ajout) { viderSelection(); return; }
    const cles = fini.ajout ? fini.base.slice() : [];
    touches.forEach(function (c) { if (cles.indexOf(c) < 0) cles.push(c); });
    etat.selection = cles;
    etat.elementCourant = cles[cles.length - 1] || null;
    etat.ancreSelection = etat.elementCourant;
    nettoyerSelection();
    rendreSelection();
  }

  function capturer(evt) {
    // La capture va sur le CALQUE, jamais sur le repère : celui-ci est
    // reconstruit à chaque rendu, et une capture posée sur un nœud sorti du
    // document est perdue en silence. `pointermove` sur `document` aurait le
    // défaut inverse — le pointeur sort du cadre pendant un geste rapide et
    // l'on perd la fin du mouvement, le repère restant collé.
    masquerInfobulle();   // même raison qu'aux flèches : le repère va bouger
    try {
      noeuds.calque.setPointerCapture(evt.pointerId);
    } catch (e) {
      // Capture refusée (pointeur déjà relâché) : les écouteurs du calque
      // suffisent tant que le pointeur reste dessus.
    }
    noeuds.cadre.classList.add("en-manip");
    evt.preventDefault();
    evt.stopPropagation();
  }

  // Le glisser est COALESCÉ : un traitement par frame, pas un par événement.
  //
  // Une souris moderne émet 125 à 1000 `pointermove` par seconde, et chacun
  // refaisait le travail complet : `getBoundingClientRect()` sur la surface
  // (une LECTURE de mise en page) suivie d'écritures de style sur tout le bloc,
  // de la reconstruction des cadres de groupe et du réaffichage des champs.
  // Lire puis écrire, huit fois par frame, force le navigateur à recalculer la
  // mise en page à chaque aller-retour — le geste rame d'autant plus que la
  // souris est bonne. Ce qui compte pour l'œil est la DERNIÈRE position.
  let bougeEnAttente = null;
  let bougeRaf = null;

  function bougerCoalesce(evt) {
    bougeEnAttente = evt;
    if (bougeRaf !== null) return;
    const suivant = window.requestAnimationFrame
      || function (f) { return setTimeout(f, 16); };
    bougeRaf = suivant(function () {
      bougeRaf = null;
      const dernier = bougeEnAttente;
      bougeEnAttente = null;
      if (dernier) bougerManip(dernier);
    });
  }

  /** Jette le mouvement en attente. Sans ça, le dernier `pointermove` d'un
   *  geste s'appliquerait APRÈS le relâchement, sur la manipulation suivante. */
  function oublierBouge() {
    if (bougeRaf !== null && window.cancelAnimationFrame) {
      window.cancelAnimationFrame(bougeRaf);
    }
    bougeRaf = null;
    bougeEnAttente = null;
  }

  function bougerManip(evt) {
    if (!manip || evt.pointerId !== manip.pointeur) return;
    const r = boiteCalque();
    if (!r || !r.width || !r.height) return;
    if (manip.mode === "bande") {
      manip.courant = {
        x: ((evt.clientX - r.left) / r.width) * 100,
        y: ((evt.clientY - r.top) / r.height) * 100,
      };
      montrerBande(r);
      marquerBande(r);
      return;
    }
    if (manip.mode === "position") {
      // Alt SUSPEND l'aimantation : on la veut par défaut, et relâchée sans
      // aller décocher une case ailleurs.
      const actif = !evt.altKey;
      const p = positionDepuisPointeur(evt, r, manip.decalage);
      const ax = aimanter(p.x, (AIMANT_PX / r.width) * 100, actif);
      const ay = aimanter(p.y, (AIMANT_PX / r.height) * 100, actif);
      deplacerBloc(ax.valeur, ay.valeur);
      manip.lignes = { x: ax.ligne, y: ay.ligne };
    } else {
      manip.element.scale = arrondi(echelleDepuisPointeur(evt, r));
    }
    rafraichirManip();
  }

  /** Pose le point d'ancrage du repère attrapé en (x, y) — et emmène le reste
   *  du bloc du même mouvement, écarts conservés. */
  function deplacerBloc(x, y) {
    const groupe = manip.groupe || [];
    if (groupe.length <= 1) {
      manip.element.x = arrondi(x);
      manip.element.y = arrondi(y);
      return;
    }
    const d = bornerDelta(groupe, x - manip.depart.x, y - manip.depart.y);
    groupe.forEach(function (m) {
      m.element.x = arrondi(m.depart.x + d.x);
      m.element.y = arrondi(m.depart.y + d.y);
    });
  }

  /** L'échelle que demande le pointeur, bornée à la saisie. */
  function echelleDepuisPointeur(evt, r) {
    const d = { x: evt.clientX - r.left - manip.ancre.x,
                y: evt.clientY - r.top - manip.ancre.y };
    const n2 = manip.bras.x * manip.bras.x + manip.bras.y * manip.bras.y;
    let e;
    if (n2 > 1) {
      // La poignée suit le pointeur d'aussi près qu'elle le peut : projection
      // du pointeur sur le bras. Exacte quand le pointeur reste sur la
      // diagonale — une poignée ne peut pas suivre un mouvement qui la quitte.
      e = manip.depart.scale * (d.x * manip.bras.x + d.y * manip.bras.y) / n2;
    } else {
      // Bras nul : la poignée est POSÉE sur le point d'ancrage — le coin
      // nord-ouest d'un élément ancré `top-left`, et ses trois symétriques.
      // Elle ne bouge pas d'un pixel quelle que soit l'échelle, il n'y a donc
      // rien à suivre. On lit alors l'éloignement du centre : s'en écarter
      // agrandit, s'en rapprocher réduit.
      const dep = { x: evt.clientX - manip.origine.x,
                    y: evt.clientY - manip.origine.y };
      e = manip.depart.scale
        * (1 + (dep.x * manip.sortant.x + dep.y * manip.sortant.y) / manip.rayon);
    }
    return borner(e, ECHELLE_MIN, ECHELLE_MAX, manip.depart.scale);
  }

  function finirManip(evt) {
    if (!manip || (evt && evt.pointerId !== manip.pointeur)) return;
    // Le mouvement gardé pour la frame suivante est appliqué MAINTENANT. Sans
    // ça, la coalescence jetterait le dernier déplacement du geste : on relâche
    // là où on visait, et l'élément reste une frame en arrière — jusqu'à une
    // dizaine de pixels d'écart, exactement au moment où l'on cherche le
    // placement au pixel.
    if (bougeEnAttente) bougerManip(bougeEnAttente);
    const fini = manip;
    manip = null;
    oublierBouge();
    try {
      if (noeuds.calque.hasPointerCapture
          && noeuds.calque.hasPointerCapture(fini.pointeur)) {
        noeuds.calque.releasePointerCapture(fini.pointeur);
      }
    } catch (e) {
      // Capture déjà rendue par le navigateur : il n'y a rien à défaire.
    }
    noeuds.cadre.classList.remove("en-manip");
    montrerGuides(null);
    montrerCoords(null);
    // Ce que l'aperçu a changé pendant le geste : mesuré maintenant, pas
    // pendant. Posé AVANT le retour du mode « bande » — sans quoi une taille
    // apparue sous le doigt attendrait la prochaine mutation de l'aperçu, qui
    // peut ne jamais venir.
    if (mesureEnRetard) planifierMesure();
    if (fini.mode === "bande") { finirBande(fini); return; }
    // UNE modification pour tout le geste : en compter une par `pointermove`
    // afficherait « 340 modifications non publiées » pour un déplacement.
    const bouge = (fini.groupe || []).some(function (m) {
      return m.element.x !== m.depart.x || m.element.y !== m.depart.y;
    });
    if (bouge || fini.element.x !== fini.depart.x || fini.element.y !== fini.depart.y
        || fini.element.scale !== fini.depart.scale) {
      marquerModifie();
    }
    rendreSurface();
    rendreReglages();
  }

  /** Les flèches, sur le calque : de quoi ajuster au pixel sans se battre avec
   *  la souris. Le pas fin vaut deux pixels sur une source 1920. */
  function toucheSurface(evt) {
    const sens = TOUCHES[evt.key];
    if (!sens || manip) return;
    // Les repères SURVIVENT au rendu depuis qu'il réconcilie : une bulle
    // ouverte y resterait accrochée pendant que son repère s'en va sous elle.
    // Aux flèches et au début d'un geste — les deux seuls rendus qui DÉPLACENT
    // quelque chose —, on la referme.
    masquerInfobulle();
    if (!selection().length) return;
    evt.preventDefault();   // sinon la page défile sous la surface
    const bloc = selectionDeplacable();
    if (!bloc.membres.length) {
      // Au premier appui seulement : la répétition du clavier en ferait une
      // pluie de messages.
      if (!evt.repeat) direLesBloques(bloc.bloques);
      return;
    }
    const pas = evt.shiftKey ? PAS_GROS : PAS_FIN;
    // Le même décalage commun qu'au glisser : les flèches déplacent le bloc
    // sans jamais en changer la forme.
    const d = bornerDelta(bloc.membres, sens[0] * pas, sens[1] * pas);
    if (d.x === 0 && d.y === 0) return;   // le bloc touche déjà le bord
    bloc.membres.forEach(function (m) {
      m.element.x = arrondi(m.depart.x + d.x);
      m.element.y = arrondi(m.depart.y + d.y);
    });
    if (!evt.repeat) direLesBloques(bloc.bloques);
    // Une flèche MAINTENUE se répète : sans source commune, deux secondes
    // d'ajustement videraient les vingt pas de l'historique. Toutes directions
    // confondues — aller-retour gauche/droite pour caler un élément est UN
    // geste, et une demi-seconde d'arrêt le clôt.
    marquerModifie("fleches");
    rendreSurface();
    rendreReglages();
  }

  /** Le retour visuel pendant le geste : le repère lui-même, ses poignées, les
   *  lignes d'aimantation et les coordonnées en cours. */
  function rafraichirManip() {
    if (!manip) return;
    const r = boiteCalque();
    if (!r || !r.width || !r.height) return;
    const g = geometrie(manip.cle, manip.element, r.width, r.height);
    // Tout le bloc suit à l'écran, pas seulement le repère attrapé : sinon on
    // déplace douze éléments en n'en voyant bouger qu'un, et on découvre le
    // résultat au relâchement.
    const suivis = (manip.groupe && manip.groupe.length)
      ? manip.groupe
      : [{ cle: manip.cle, element: manip.element, noeud: manip.noeud }];
    suivis.forEach(function (m) {
      if (!m.noeud) return;
      appliquerStyle(m.noeud, m.element, r.width);
      m.noeud.classList.toggle("hors-cadre",
        horsCadre(geometrie(m.cle, m.element, r.width, r.height), r.width, r.height));
    });
    placerPoignees(g);
    // Le cadre du groupe suit le bloc pendant le geste : figé, il resterait
    // derrière les membres qu'on vient de déplacer.
    placerCadresGroupes(r.width, r.height);
    montrerGuides(manip.lignes);
    montrerCoords(g, r.width, r.height);
    rendreReglages();   // les champs X/Y/Taille suivent le geste
  }

  function majPoignees(W, H) {
    const element = elementCourant();
    // Un élément verrouillé n'a ni poignées ni glisser : il ne doit pas être
    // manipulable par mégarde, c'est tout l'objet du cadenas.
    if (!element || element.locked || !W || !H) { placerPoignees(null); return; }
    placerPoignees(geometrie(etat.elementCourant, element, W, H));
  }

  /** Les quatre poignées d'angle, posées sur la SURFACE et non dans le repère :
   *  celui-ci porte un `scale()`, qui rendrait les poignées minuscules sur un
   *  élément réduit — justement celui qu'on veut agrandir. */
  function placerPoignees(g) {
    if (!noeuds.poignees) return;
    COINS.forEach(function (coin) {
      const n = noeuds.poignees[coin];
      if (!g) { n.style.display = "none"; return; }
      n.style.display = "";
      n.style.left = (coin.indexOf("w") >= 0 ? g.gauche : g.droite) + "px";
      n.style.top = (coin.charAt(0) === "n" ? g.haut : g.bas) + "px";
    });
  }

  function montrerGuides(lignes) {
    if (!noeuds.guideV || !noeuds.guideH) return;
    const x = lignes ? lignes.x : null;
    const y = lignes ? lignes.y : null;
    noeuds.guideV.style.display = x === null || x === undefined ? "none" : "";
    if (x !== null && x !== undefined) noeuds.guideV.style.left = x + "%";
    noeuds.guideH.style.display = y === null || y === undefined ? "none" : "";
    if (y !== null && y !== undefined) noeuds.guideH.style.top = y + "%";
  }

  /** Les coordonnées en cours. Sans elles, on déplace à l'estime et on
   *  découvre le chiffre après coup. */
  function montrerCoords(g, W, H) {
    if (!noeuds.coords) return;
    if (!g || !manip) { noeuds.coords.classList.remove("visible"); return; }
    const el = manip.element;
    const deborde = horsCadre(g, W, H);
    noeuds.coords.textContent =
      "X " + arrondi(el.x).toFixed(2) + " %  ·  Y " + arrondi(el.y).toFixed(2) + " %"
      + "  ·  taille " + arrondi(borner(el.scale, ECHELLE_MIN, ECHELLE_MAX, 1)).toFixed(2)
      + (deborde ? "  ·  ⚠ déborde du cadre" : "");
    noeuds.coords.classList.toggle("alerte", deborde);
    noeuds.coords.classList.add("visible");
  }

  // ── Les raccourcis ──────────────────────────────────────────────────────
  //
  // « Un raccourci que personne ne connaît n'existe pas » : la liste est
  // AFFICHÉE, pas seulement écrite ici. Elle vit dans une seule table, qui sert
  // à la fois de documentation et de rappel à l'écran — deux listes auraient
  // divergé au premier raccourci ajouté.

  const RACCOURCIS = [
    ["Clic", "choisir un élément"],
    ["Ctrl + clic", "l'ajouter à la sélection, ou l'en retirer"],
    ["Maj + clic", "sélectionner toute la plage depuis le dernier clic simple"],
    ["Glisser sur le fond", "rectangle de sélection ; Ctrl pour ajouter"],
    ["Ctrl + A", "tout ce qui est visible et non verrouillé"],
    ["Échap", "désélectionner"],
    ["Flèches", "déplacer la sélection de 0,1 % (Maj : 1 %)"],
    ["Alt (pendant le glisser)", "suspendre l'aimantation"],
    ["Suppr", "masquer la sélection, ou la remontrer — sauf ce qui est "
              + "verrouillé"],
    ["L", "verrouiller la sélection, ou la libérer"],
    ["G", "réunir la sélection en groupe (deux éléments au minimum)"],
    ["Maj + G", "dissoudre les groupes de la sélection"],
    ["C puis V", "copier les réglages d'un élément (position, ancrage, "
                 + "échelle) et les coller sur la sélection"],
    ["Ctrl + Z", "annuler le dernier geste du brouillon (vingt pas) — sans "
                 + "rapport avec « Annuler la publication », qui touche à "
                 + "l'antenne"],
    ["Ctrl + Y", "refaire le geste annulé (Ctrl + Maj + Z aussi)"],
    ["?", "afficher ou masquer cette liste"],
  ];

  /** Le tri d'une bascule d'ensemble : ce que le cadenas laisse changer, et ce
   *  qu'il retient. Pure, donc TESTÉE — c'est ici que se joue « le verrou
   *  bloque tout », et une garde qui vit à l'intérieur d'une fonction qui
   *  redessine trois listes ne se vérifie qu'à l'œil.
   *
   *  `locked` fait exception à lui-même : sans quoi, une fois verrouillé, plus
   *  rien ne pourrait jamais lever le verrou.
   */
  function cibleBascule(scene, cles, champ) {
    const elements = (scene && scene.elements) || {};
    const libres = [], bloques = [];
    (cles || []).forEach(function (c) {
      const el = elements[c];
      if (!el) return;
      if (champ !== "locked" && el.locked) bloques.push(c);
      else libres.push(c);
    });
    return { libres: libres, bloques: bloques };
  }

  /** La bascule d'ENSEMBLE. Inverser chaque élément séparément ne convergerait
   *  jamais sur une sélection mi-visible mi-masquée : elle clignoterait d'un
   *  appui à l'autre sans jamais être toute visible ni toute masquée.
   *
   *  LE CADENAS BLOQUE TOUT — position, taille ET visibilité. Le raisonnement
   *  « le verrou ne porte que sur la position » avait sa logique, mais il
   *  laissait `Suppr` faire disparaître de l'antenne un élément qu'on avait
   *  explicitement mis à l'abri, et c'est le geste le plus facile à faire par
   *  mégarde de tout le panneau. Un élément verrouillé est un élément auquel on
   *  ne touche pas sans le déverrouiller d'abord.
   *
   *  Le verrou LUI-MÊME fait exception, évidemment : sans quoi rien ne pourrait
   *  plus jamais le lever.
   */
  function basculerChamp(champ, motActif, motInactif, surCes) {
    // `surCes` : les clés visées, quand ce n'est pas la sélection — c'est le cas
    // de l'œil et du cadenas d'un en-tête de groupe. Un groupe n'a PAS de
    // `hidden` ni de `locked` à lui : le masquer, c'est masquer ses membres.
    // Deux autorités sur la même question se contrediraient au premier membre
    // masqué à la main.
    const cles = surCes || selection();
    if (!cles.length) { notifier("Aucun élément sélectionné.", "error"); return; }
    const scene = sceneCourante();
    const tri = cibleBascule(scene, cles, champ);
    const libres = tri.libres, bloques = tri.bloques;
    if (!libres.length) { direLesBloques(bloques); return; }
    const cible = libres.some(function (c) { return !scene.elements[c][champ]; });
    libres.forEach(function (c) { scene.elements[c][champ] = cible; });
    marquerModifie();
    rendreSelection();
    notifier(libres.length + " élément" + (libres.length > 1 ? "s " : " ")
      + (cible ? motActif : motInactif) + ".");
    direLesBloques(bloques);
  }

  /** C : les réglages de l'élément PRINCIPAL. Pas de duplication d'élément ici
   *  — la scène a une liste fermée de trente-quatre clés —, mais recopier un
   *  placement d'un widget à l'autre est le geste qu'on refait le plus. */
  function copierReglages() {
    const element = elementCourant();
    if (!element) { notifier("Aucun élément choisi : rien à copier.", "error"); return; }
    etat.presse = {
      x: element.x, y: element.y,
      anchor: element.anchor,
      scale: element.scale,
    };
    notifier("Réglages de " + libelle(etat.elementCourant)
      + " copiés — V les colle sur la sélection.");
  }

  /** V : le même placement pour toute la sélection. L'ancrage voyage AVEC la
   *  position : les deux ne veulent rien dire l'un sans l'autre, et coller un
   *  x/y sur un ancrage différent poserait l'élément ailleurs. */
  function collerReglages() {
    if (!etat.presse) {
      notifier("Rien à coller : copiez d'abord un élément avec C.", "error");
      return;
    }
    const bloc = selectionDeplacable();
    if (!bloc.membres.length) {
      direLesBloques(bloc.bloques);
      if (!bloc.bloques.length) notifier("Aucun élément sélectionné.", "error");
      return;
    }
    const p = etat.presse;
    let bouge = 0;
    bloc.membres.forEach(function (m) {
      const x = arrondi(borner(p.x, POS_MIN, POS_MAX, m.element.x));
      const y = arrondi(borner(p.y, POS_MIN, POS_MAX, m.element.y));
      const e = borner(p.scale, ECHELLE_MIN, ECHELLE_MAX, m.element.scale);
      if (m.element.x !== x || m.element.y !== y || m.element.scale !== e
          || m.element.anchor !== p.anchor) {
        bouge += 1;
      }
      m.element.x = x;
      m.element.y = y;
      m.element.scale = e;
      m.element.anchor = p.anchor;
    });
    finirOutil(bouge, bloc.bloques);
  }

  // ── Propager d'une scène aux autres ─────────────────────────────────────
  //
  // Trente-quatre éléments × trois scènes = cent deux réglages. Poser un widget
  // puis refaire le geste sur chaque scène est le travail que ce panneau existe
  // pour éviter — et c'est le seul endroit où la répétition est MÉCANIQUE : la
  // place d'un élément ne dépend pas de la scène, sa VISIBILITÉ si.
  //
  // D'où le partage : le PLACEMENT se propage (position, ancrage, échelle), la
  // visibilité NON. C'est elle qui distingue les trois habillages — le bingo
  // masqué au démarrage, visible en jeu (docs/plans/2026-08-15…, « Le modèle » :
  // « `hidden` est par scène. C'est lui qui fait tout le travail des trois
  // habillages »). L'emporter par défaut effacerait en un clic le seul réglage
  // qui donne un sens aux scènes. La case la fait voyager quand on le DEMANDE.
  //
  // Ne partent pas non plus, et c'est délibéré : `solo` et `wally_visible` (des
  // règles d'affichage, pas un placement), l'ORDRE et les GROUPES (une scène de
  // fin n'a pas le découpage d'une scène de jeu). Le libellé du bouton dit ce
  // qui part, la confirmation le redit.
  //
  // Les quatre réglages visuels ajoutés le 2026-08-21 rejoignent la liste : ils
  // sont de la même famille que `scale` — COMMENT l'élément est rendu, et non
  // QUAND. Une inclinaison ou une opacité choisies pour un habillage valent
  // pour les trois, comme une taille.
  //
  // Les six réglages de RYTHME (`duree`, `delai`, les trois `anim_*`,
  // `anim_insistance`) restent dehors, du même côté que `solo` et
  // `wally_visible` : ce sont des règles d'affichage. Une scène de fin peut
  // vouloir des passages plus longs qu'une scène de jeu, c'est même tout
  // l'intérêt de les avoir par scène.
  const CHAMPS_PROPAGES = ["x", "y", "anchor", "scale",
                           "opacite", "rotation", "miroir", "largeur_max"];

  /** Les scènes autres que celle qu'on édite. */
  function autresScenes() {
    const scenes = (etat.layout && etat.layout.scenes) || [];
    return scenes.filter(function (s) { return s.slug !== etat.slugCourant; });
  }

  /** Ce qu'une propagation ÉCRIRAIT, scène de destination par scène de
   *  destination. Séparée de l'écriture, et pure : c'est elle qui alimente la
   *  demande de confirmation, et annoncer « 12 éléments dans 2 scènes » suppose
   *  de les avoir comptés pour de vrai — pas d'avoir multiplié deux longueurs.
   *
   *  Un élément déjà identique ne compte PAS : « 12 réglages écrasés » sur une
   *  scène qu'on vient de propager serait faux, et un chiffre faux dans une
   *  demande de confirmation vaut moins que pas de chiffre du tout.
   *
   *  Un élément verrouillé dans la scène de DESTINATION est mis de côté, pas
   *  écrit : le cadenas retient ici comme partout ailleurs dans ce panneau, et
   *  une propagation est justement le geste le plus facile à lancer sur trop
   *  d'éléments à la fois.
   */
  function planPropagation(source, cles, champs) {
    const plan = [];
    autresScenes().forEach(function (cible) {
      const ecrits = [], bloques = [];
      (cles || []).forEach(function (cle) {
        const de = (source.elements || {})[cle];
        const vers = (cible.elements || {})[cle];
        if (!de || !vers) return;
        if (vers.locked) { bloques.push(cle); return; }
        const change = champs.some(function (c) { return vers[c] !== de[c]; });
        if (change) ecrits.push(cle);
      });
      plan.push({ scene: cible, ecrits: ecrits, bloques: bloques });
    });
    return plan;
  }

  /** Applique un plan. Rend le nombre d'éléments réellement écrits. */
  function appliquerPropagation(source, plan, champs) {
    let ecrits = 0;
    plan.forEach(function (p) {
      p.ecrits.forEach(function (cle) {
        const de = source.elements[cle], vers = p.scene.elements[cle];
        champs.forEach(function (c) { vers[c] = de[c]; });
        ecrits += 1;
      });
    });
    return ecrits;
  }

  /** Le geste : recopier le placement de `cles` vers TOUTES les autres scènes.
   *
   *  `quoi` sert au message — « la sélection » ou « la scène entière » —, le
   *  calcul est le même : une scène entière n'est qu'une sélection de
   *  trente-quatre clés.
   *
   *  Une propagation silencieuse qui écrase un réglage fait à la main est
   *  exactement ce qu'on ne pardonne pas : la confirmation dit COMBIEN
   *  d'éléments et DANS QUELLES scènes, nommément.
   */
  function propager(cles, quoi) {
    const source = sceneCourante();
    if (!source || !etat.layout) return;
    const autres = autresScenes();
    if (!autres.length) {
    // Les chevauchements aussi : découvrir au relâchement qu'on vient de poser
    // le bingo sur les stats fait refaire le placement. Le calcul ne porte que
    // sur ce qui cohabite — six éléments par défaut, pas trente-quatre.
    direChevauchements(analyserChevauchements(sceneCourante(), r.width, r.height));
      notifier("Il n'y a qu'une scène : il n'y a nulle part où propager.", "error");
      return;
    }
    if (!cles.length) { notifier("Aucun élément sélectionné.", "error"); return; }
    const avecVis = !!(noeuds.propagerVisibilite && noeuds.propagerVisibilite.checked);
    const champs = avecVis ? CHAMPS_PROPAGES.concat(["hidden"]) : CHAMPS_PROPAGES;
    const plan = planPropagation(source, cles, champs);
    let total = 0, bloques = 0;
    plan.forEach(function (p) { total += p.ecrits.length; bloques += p.bloques.length; });
    if (!total) {
      notifier(bloques
        ? "Rien à propager : les " + bloques + " élément(s) concerné(s) sont "
          + "verrouillés dans les autres scènes."
        : "Rien à propager : " + quoi + " est déjà à la même place partout.",
        bloques ? "error" : "success");
      return;
    }
    const detail = plan.filter(function (p) { return p.ecrits.length; })
      .map(function (p) {
        return "  · « " + p.scene.nom + " » : " + p.ecrits.length + " élément(s) — "
          + p.ecrits.map(libelle).join(", ");
      }).join("\n");
    if (!window.confirm(
        "Copier le placement (position, ancrage, échelle"
        + (avecVis ? ", VISIBILITÉ" : "") + ") de « " + source.nom
        + " » vers les autres scènes ?\n\n"
        + total + " réglage(s) seront ÉCRASÉS :\n" + detail + "\n\n"
        + (avecVis
           ? "⚠ La visibilité part AUSSI : ce qui est masqué ici le sera là-bas.\n"
             + "C'est elle qui distingue vos scènes — décochez la case pour la "
             + "laisser intacte."
           : "La visibilité propre à chaque scène n'est PAS touchée.")
        + (bloques ? "\n\n" + bloques + " élément(s) verrouillé(s) dans les scènes "
                     + "de destination ne bougeront pas." : "")
        + "\n\nComme tout le reste ici, la modification passe par le brouillon.")) {
      return;
    }
    const ecrits = appliquerPropagation(source, plan, champs);
    // UNE modification pour toute l'opération : en compter une par élément
    // afficherait « 68 modifications non publiées » pour un seul clic.
    marquerModifie();
    rendreTout();
    notifier(ecrits + " réglage(s) propagé(s) depuis « " + source.nom + " » vers "
      + plan.filter(function (p) { return p.ecrits.length; }).length + " scène(s)"
      + (avecVis ? ", visibilité comprise" : ", visibilité inchangée") + "."
      + (bloques ? " " + bloques + " verrouillé(s) n'ont pas bougé." : ""));
  }

  // ── Réinitialiser ───────────────────────────────────────────────────────
  //
  // LES DÉFAUTS VIENNENT DU SERVEUR, JAMAIS D'UNE COPIE ÉCRITE ICI.
  //
  // C'est la même règle que les libellés (voir en tête de fichier) et pour la
  // même raison : `ELEMENTS` (bot/core/overlay_layout.py) bouge à chaque widget
  // ajouté, et une seconde table dans le navigateur aurait divergé de la
  // première à la première évolution du modèle. « Réinitialiser » rendrait alors
  // un élément à une position d'origine QUI N'EST PLUS celle d'origine — le pire
  // des deux mondes, puisqu'on aurait cru revenir à un état connu.
  //
  // Un seul appel, mis en cache pour la durée de la visite : ce sont des
  // constantes, elles ne changent pas d'un clic à l'autre.

  /** Les défauts servis, ou une promesse qui les rapporte. */
  function chargerDefauts() {
    if (etat.defauts) return Promise.resolve(etat.defauts);
    return appeler(URL_LAYOUT + "?defauts=1")
      .then(function (r) { return r && r.ok ? r.json() : null; })
      .then(function (layout) {
        if (!layout || !layout.scenes || !layout.scenes.length) return null;
        etat.defauts = layout;
        return layout;
      })
      .catch(function () { return null; });
  }

  /** Les éléments d'origine. Toutes les scènes livrées portent la MÊME copie
   *  d'`ELEMENTS` (`layout_par_defaut`) : on prend celle qui porte le slug
   *  courant si elle existe, la première sinon — une scène créée à la main n'a
   *  évidemment pas de scène d'origine à son nom. */
  function elementsDefaut(defauts, slug) {
    const scenes = defauts.scenes || [];
    let scene = null;
    for (let i = 0; i < scenes.length; i++) {
      if (scenes[i].slug === slug) { scene = scenes[i]; break; }
    }
    return ((scene || scenes[0]) || {}).elements || {};
  }

  /** Ce qu'une remise à zéro CHANGERAIT, et ce que le cadenas retient. Pure,
   *  et séparée de l'écriture pour la même raison que `planPropagation` : la
   *  confirmation annonce un chiffre, il doit être compté. */
  function planReinitialisation(scene, cles, origine) {
    const change = [], bloques = [];
    (cles || []).forEach(function (cle) {
      const el = (scene.elements || {})[cle];
      const def = origine[cle];
      if (!el || !def) return;
      if (el.locked) { bloques.push(cle); return; }
      const different = Object.keys(def).some(function (c) {
        return el[c] !== def[c];
      });
      if (different) change.push(cle);
    });
    return { change: change, bloques: bloques };
  }

  /** Remet des éléments à leur valeur d'origine. TOUS leurs champs, pas
   *  seulement le placement : « ses valeurs d'origine » veut dire l'élément tel
   *  qu'il est livré — position, ancrage, échelle, visibilité, exclusivité, et
   *  la cadence du rotateur pour celui qui la porte. Un reset qui laisserait
   *  `hidden` derrière ne serait pas un reset.
   *
   *  `locked` n'est jamais réécrit : il est la garde, et une garde qu'une
   *  opération peut lever n'en est pas une. Les verrouillés sont écartés avant. */
  function appliquerReinitialisation(scene, cles, origine) {
    cles.forEach(function (cle) {
      const el = scene.elements[cle], def = origine[cle];
      Object.keys(def).forEach(function (c) {
        if (c !== "locked") el[c] = def[c];
      });
    });
  }

  /** Le geste. `cles` : la sélection, ou toute la scène. */
  function reinitialiser(cles, quoi, aussiLaStructure) {
    const scene = sceneCourante();
    if (!scene) return;
    if (!cles.length) { notifier("Aucun élément sélectionné.", "error"); return; }
    chargerDefauts().then(function (defauts) {
      if (!defauts) {
        notifier("Valeurs d'origine indisponibles : le serveur n'a pas répondu. "
          + "Rien n'a été touché.", "error");
        return;
      }
      // `sceneCourante()` est RELUE : l'appel réseau a pu passer pendant qu'on
      // changeait de scène, et remettre à zéro une scène qu'on ne regarde plus
      // est exactement le genre de chose qu'on ne voit qu'après coup.
      const courante = sceneCourante();
      if (!courante || courante.slug !== scene.slug) {
        notifier("La scène a changé pendant le chargement des valeurs "
          + "d'origine : rien n'a été touché.", "error");
        return;
      }
      const origine = elementsDefaut(defauts, courante.slug);
      const plan = planReinitialisation(courante, cles, origine);
      const brute = defautsStructure(defauts, courante.slug);
      // L'empilement et les groupes ne repartent QUE sur « toute la scène » :
      // remettre l'ordre d'origine parce qu'on a réinitialisé un dé serait un
      // effet de bord qu'on découvre après coup.
      const structure = !!aussiLaStructure && (
        (courante.ordre || []).join(",") !== brute.ordre.join(",")
        || JSON.stringify(courante.groupes || []) !== JSON.stringify(brute.groupes));
      if (!plan.change.length && !structure) {
        if (plan.bloques.length) direLesBloques(plan.bloques);
        else notifier("Rien à réinitialiser : " + quoi + " est déjà d'origine.");
        return;
      }
      if (!window.confirm(
          "Remettre " + quoi + " à ses valeurs d'origine dans « " + courante.nom
          + " » ?\n\n" + plan.change.length + " élément(s) reviendront à leur "
          + "place, leur ancrage, leur échelle et leur visibilité de livraison :\n"
          + (plan.change.length
             ? "  " + plan.change.map(libelle).join(", ")
             : "  (aucun)")
          + (structure ? "\n\nL'empilement et les groupes de la scène repartent "
                         + "eux aussi de la livraison." : "")
          + (plan.bloques.length
             ? "\n\n" + plan.bloques.length + " élément(s) verrouillé(s) ne "
               + "bougeront pas : " + plan.bloques.map(libelle).join(", ") + "."
             : "")
          + "\n\nComme tout le reste ici, la modification passe par le brouillon.")) {
        return;
      }
      appliquerReinitialisation(courante, plan.change, origine);
      if (structure) {
        // Copie PROFONDE : les défauts sont gardés en cache pour toute la
        // visite, et une référence partagée ferait suivre la scène à chaque
        // regroupement fait ensuite.
        courante.ordre = brute.ordre.slice();
        courante.groupes = JSON.parse(JSON.stringify(brute.groupes));
      }
      nettoyerSelection();
      marquerModifie();
      rendreTout();
      notifier(plan.change.length + " élément(s) remis à leur valeur d'origine"
        + (structure ? ", empilement et groupes compris" : "") + "."
        + (plan.bloques.length ? " " + plan.bloques.length
           + " verrouillé(s) n'ont pas bougé." : ""));
    });
  }

  /** L'empilement et les groupes d'origine d'une scène. */
  function defautsStructure(defauts, slug) {
    const scenes = defauts.scenes || [];
    let scene = null;
    for (let i = 0; i < scenes.length; i++) {
      if (scenes[i].slug === slug) { scene = scenes[i]; break; }
    }
    scene = scene || scenes[0] || {};
    return { ordre: scene.ordre || [], groupes: scene.groupes || [] };
  }

  /** Toutes les clés de la scène — la propagation « scène entière ». Prises
   *  dans `ordre` : c'est la liste qui fait foi, et elle est complétée par le
   *  serveur à chaque enregistrement. */
  function clesScene() {
    const scene = sceneCourante();
    if (!scene) return [];
    return (scene.ordre || []).filter(function (c) { return !!scene.elements[c]; });
  }

  function dansUnChamp(noeud) {
    if (!noeud || !noeud.tagName) return false;
    if (noeud.isContentEditable) return true;
    const t = noeud.tagName.toUpperCase();
    return t === "INPUT" || t === "TEXTAREA" || t === "SELECT";
  }

  /** Le panneau est-il SOUS LES YEUX ? Le dashboard garde tous ses onglets dans
   *  le document et n'en montre qu'un : sans cette garde, `Suppr` masquerait des
   *  éléments d'overlay pendant qu'on lit les logs dans un autre onglet. */
  function panneauVisible() {
    const c = noeuds.cadre;
    return !!(c && c.isConnected && c.offsetParent !== null);
  }

  /** Les raccourcis, posés sur le DOCUMENT — la liste des éléments et les
   *  boutons de la barre d'outils prennent le focus tout autant que la surface,
   *  et un raccourci qui ne marche qu'à un endroit ne se retient pas.
   *
   *  JAMAIS dans un champ de saisie : un « l » tapé dans le nom d'une scène
   *  verrouillerait la sélection au lieu de s'écrire. */
  function toucheGlobale(evt) {
    if (!panneauVisible() || dansUnChamp(evt.target)) return;
    if (evt.altKey) return;   // Alt appartient au glisser
    if (evt.ctrlKey || evt.metaKey) {
      if (evt.key === "a" || evt.key === "A") {
        evt.preventDefault();
        toutSelectionner();
        return;
      }
      // Ctrl+Z / Ctrl+Y sur le BROUILLON. Hors d'un champ de saisie seulement —
      // la garde est en tête de fonction : dans un champ, Ctrl+Z appartient au
      // texte qu'on est en train de taper, et le lui prendre serait pire que de
      // ne pas avoir d'historique du tout.
      //
      // Maj+Z refait aussi : c'est la convention de la moitié des éditeurs, et
      // Ctrl+Y n'existe pas sous macOS.
      if (evt.key === "z" || evt.key === "Z") {
        evt.preventDefault();
        if (evt.shiftKey) direRefait(refaireHistoire());
        else direDefait(annulerHistoire());
        return;
      }
      if (evt.key === "y" || evt.key === "Y") {
        evt.preventDefault();
        direRefait(refaireHistoire());
        return;
      }
      return;   // les autres Ctrl+… restent au navigateur (copier, recharger…)
    }
    if (TOUCHES[evt.key]) {
      // Le calque a son propre écouteur, posé pour l'accessibilité au clavier :
      // le laisser faire évite de traiter la même touche deux fois.
      if (evt.target === noeuds.calque) return;
      toucheSurface(evt);
      return;
    }
    switch (evt.key) {
      case "Escape": viderSelection(); break;
      case "Delete":
        evt.preventDefault();
        basculerChamp("hidden", "masqués", "remontrés");
        break;
      case "l": case "L":
        basculerChamp("locked", "verrouillés", "libérés");
        break;
      // La majuscule EST la touche avec Maj : `evt.key` vaut "G" quand Maj est
      // tenue, "g" sinon. Deux gestes voisins pour deux gestes inverses.
      case "g": creerGroupe(); break;
      case "G": degrouperSelection(); break;
      case "c": case "C": copierReglages(); break;
      case "v": case "V": collerReglages(); break;
      case "?": evt.preventDefault(); basculerAide(); break;
      default: return;
    }
  }

  function basculerAide(force) {
    if (!noeuds.raccourcis) return;
    const ouvert = force === undefined
      ? noeuds.raccourcis.style.display === "none"
      : !!force;
    noeuds.raccourcis.style.display = ouvert ? "" : "none";
    if (noeuds.boutonAide) {
      noeuds.boutonAide.classList.toggle("actif", ouvert);
      noeuds.boutonAide.setAttribute("aria-expanded", ouvert ? "true" : "false");
    }
  }

  function blocRaccourcis() {
    const bloc = creer("div", "ovl-raccourcis");
    bloc.style.display = "none";
    bloc.appendChild(creer("div", "ovl-raccourcis-titre", "Raccourcis"));
    const liste = creer("dl", "ovl-raccourcis-liste");
    RACCOURCIS.forEach(function (r) {
      liste.appendChild(creer("dt", null, r[0]));
      liste.appendChild(creer("dd", null, r[1]));
    });
    bloc.appendChild(liste);
    return bloc;
  }

  // ── La barre de réglages ────────────────────────────────────────────────

  /** Un cran de rang pour l'élément choisi. `-1` le rapproche du spectateur.
   *
   *  L'empilement ne se réglait que par glisser dans la liste : un geste
   *  imprécis sur trente-sept lignes, et invisible pour qui regarde la surface.
   *  Deux boutons font le même travail sur l'élément qu'on a sous les yeux.
   */
  function deplacerRang(delta) {
    const scene = sceneCourante();
    const cle = etat.elementCourant;
    if (!scene || !cle) return;
    const ordre = scene.ordre || [];
    const i = ordre.indexOf(cle);
    if (i < 0) return;
    const j = i + delta;
    if (j < 0 || j >= ordre.length) {
      notifier(delta < 0 ? "Déjà tout devant." : "Déjà tout derrière.");
      return;
    }
    const avant = ordre.slice();
    ordre.splice(i, 1);
    ordre.splice(j, 0, cle);
    // Les membres d'un groupe restent contigus. Un pas qui sortirait l'élément
    // du sien est donc défait ici — et il faut le DIRE, sinon le bouton passe
    // pour cassé : on clique, rien ne bouge, rien ne s'explique.
    normaliserOrdre(scene);
    const rendu = scene.ordre;
    if (rendu.length === avant.length
        && rendu.every(function (c, k) { return avant[k] === c; })) {
      notifier("« " + libelle(cle) + " » est dans un groupe : le groupe se "
        + "déplace d'un bloc, par son en-tête dans la liste.", "error");
      return;
    }
    marquerModifie();
    rendreElements();
    rendreSurface();
    rendreReglages();
  }

  /** La bande d'inspection : tout ce qui règle l'élément CHOISI, sur une seule
   *  ligne sous le canvas.
   *
   *  Elle remplace la barre de réglages verticale. Le gain n'est pas
   *  esthétique : les champs sont maintenant à côté du repère qu'ils
   *  déplacent, et l'ancrage — le réglage le moins compris du panneau — montre
   *  enfin des flèches plutôt que nine carrés muets dont le seul indice était
   *  une infobulle en anglais.
   */
  function bandeInspection(hote) {
    const identite = creer("div", "ovl-insp-identite");
    noeuds.reglageNom = creer("div", "ovl-reglages-nom", "—");
    identite.appendChild(noeuds.reglageNom);
    noeuds.inspCle = creer("div", "ovl-insp-cle", "");
    identite.appendChild(noeuds.inspCle);
    hote.appendChild(identite);

    /** Écrit un champ numérique. Point d'écriture UNIQUE des trois chemins
     *  (saisie, − , +) : trois copies de cette garde auraient divergé, et
     *  c'est elle qui refuse d'écrire sur un élément verrouillé. */
    function ecrire(def, valeur, proprietaire) {
      if (proprietaire && etat.elementCourant !== proprietaire) return;
      const element = elementCourant();
      // Le `disabled` posé au rendu ne protège de rien si la valeur peut encore
      // entrer par ici (un navigateur qui garde le focus, un script). La garde
      // est au POINT D'ÉCRITURE.
      if (!element || element.locked) return;
      if (!portePar(element, def[0])) return;
      const borne = borner(valeur, def[2], def[3], element[def[0]]);
      if (borne === element[def[0]]) return;
      element[def[0]] = borne;
      // La source nomme LE champ et L'élément : taper « 12.5 » est un geste,
      // mais passer au champ voisin — ou au même champ d'un autre élément — en
      // est un autre, et doit rester annulable à part.
      marquerModifie("champ:" + def[0] + ":" + (etat.elementCourant || ""));
      rendreSurface();
    }

    /** Un champ numérique encadré de deux pas. `proprietaire` : la clé de
     *  l'élément qui SEUL porte ce réglage, ou `null` pour un champ commun. */
    function champNumerique(def, proprietaire, ou) {
      const bloc = creer("div", "ovl-insp-champ");
      if (def[5]) bloc.title = def[5];
      bloc.appendChild(creer("span", "ovl-champ-label", def[1]));
      const boite = creer("div", "ovl-stepper");
      const moins = creer("button", "ovl-stepper-btn", "−");
      moins.type = "button";
      moins.setAttribute("aria-label", def[1] + " : un pas en moins");
      const input = document.createElement("input");
      input.type = "number";
      input.min = String(def[2]);
      input.max = String(def[3]);
      input.step = String(def[4]);
      input.setAttribute("aria-label", def[1]);
      const plus = creer("button", "ovl-stepper-btn", "+");
      plus.type = "button";
      plus.setAttribute("aria-label", def[1] + " : un pas en plus");
      moins.addEventListener("click", function () {
        const el = elementCourant();
        if (el) ecrire(def, arrondi(el[def[0]] - def[4]), proprietaire);
        rendreReglages();
      });
      plus.addEventListener("click", function () {
        const el = elementCourant();
        if (el) ecrire(def, arrondi(el[def[0]] + def[4]), proprietaire);
        rendreReglages();
      });
      input.addEventListener("input", function () {
        // Un champ vidé pour être resaisi ne vaut PAS zéro : sans ça, l'élément
        // filait dans le coin haut-gauche entre deux frappes.
        if (input.value.trim() === "") return;
        ecrire(def, input.value, proprietaire);
      });
      boite.appendChild(moins);
      boite.appendChild(input);
      boite.appendChild(plus);
      bloc.appendChild(boite);
      (ou || hote).appendChild(bloc);
      return { bloc: bloc, input: input, pas: [moins, plus] };
    }

    /** Cet élément porte-t-il ce réglage ?
     *
     *  La garde qui remplace l'ancien `proprietaire`, et qui vaut désormais
     *  pour TOUS les champs de scène. Les blocs cachés au rendu restent dans le
     *  document : un navigateur qui garde le focus, ou un script, poserait
     *  sinon une `duree` sur un avatar qui n'en a pas. Le modèle la jetterait à
     *  l'enregistrement — mais le panneau aurait compté une modification, et le
     *  pied aurait annoncé un changement qui n'a jamais eu lieu.
     *
     *  `x`, `y`, `scale` et les autres champs de placement ne sont pas dans les
     *  portées : ils sont sur tous les éléments par construction.
     */
    function portePar(element, nom) {
      if (PLACEMENT.indexOf(nom) >= 0) return true;
      return portesDe(etat.elementCourant)[nom] !== undefined;
    }

    /** Écrit une valeur NON numérique (booléen, nom d'animation).
     *
     *  Passe par la même porte que `ecrire()` et hérite donc de sa garde : le
     *  `disabled` posé au rendu ne protège de rien si la valeur peut encore
     *  entrer par un autre chemin, et le verrou se tient au POINT D'ÉCRITURE.
     */
    function ecrireBrut(nom, valeur) {
      const element = elementCourant();
      if (!element || element.locked) return;
      if (!portePar(element, nom)) return;
      if (element[nom] === valeur) return;
      element[nom] = valeur;
      // Même granularité d'annulation que les champs numériques : le champ ET
      // l'élément nomment la source, pour que passer au voisin reste un geste
      // séparé.
      marquerModifie("champ:" + nom + ":" + (etat.elementCourant || ""));
      rendreSurface();
    }

    /** Une case à cocher. */
    function champBooleen(nom, presentation, ou) {
      const bloc = creer("div", "ovl-insp-champ");
      bloc.title = presentation.aide || "";
      bloc.appendChild(creer("span", "ovl-champ-label", presentation.label));
      const input = document.createElement("input");
      input.type = "checkbox";
      input.className = "ovl-insp-case";
      input.setAttribute("aria-label", presentation.label);
      input.addEventListener("change", function () {
        ecrireBrut(nom, input.checked);
        rendreReglages();
      });
      bloc.appendChild(input);
      (ou || hote).appendChild(bloc);
      return { bloc: bloc, input: input, pas: [] };
    }

    /** Un choix parmi un catalogue : un bouton qui ouvre le sélecteur.
     *
     *  Pas un `<select>` : quatre-vingt-dix-sept options réparties en dix
     *  familles ne se parcourent pas dans une liste déroulante native, et on ne
     *  peut y montrer ni recherche ni aperçu.
     */
    function champChoix(nom, presentation, ou) {
      const bloc = creer("div", "ovl-insp-champ");
      bloc.title = presentation.aide || "";
      bloc.appendChild(creer("span", "ovl-champ-label", presentation.label));
      const input = creer("button", "ovl-insp-choix");
      input.type = "button";
      input.setAttribute("aria-haspopup", "listbox");
      input.addEventListener("click", function () {
        const element = elementCourant();
        if (!element || element.locked) return;
        ouvrirSelecteurAnim(input, presentation.menu, element[nom],
                            function (choisi) {
                              ecrireBrut(nom, choisi);
                              rendreReglages();
                            });
      });
      bloc.appendChild(input);
      (ou || hote).appendChild(bloc);
      return { bloc: bloc, input: input, pas: [] };
    }

    noeuds.champs = {};
    noeuds.pas = {};
    [["x", "X %", POS_MIN, POS_MAX, PAS_FIN,
      "La position horizontale du POINT D'ANCRAGE, en pourcentage de la largeur."],
     ["y", "Y %", POS_MIN, POS_MAX, PAS_FIN,
      "La position verticale du POINT D'ANCRAGE, en pourcentage de la hauteur."],
    ].forEach(function (def) {
      const champ = champNumerique(def, null);
      noeuds.champs[def[0]] = champ.input;
      noeuds.pas[def[0]] = champ.pas;
    });

    // La taille au curseur ET au chiffre : le curseur pour chercher, le chiffre
    // pour reproduire à l'identique sur une autre scène. Les deux écrivent le
    // même champ, au même endroit.
    const defTaille = ["scale", "Taille", ECHELLE_MIN, ECHELLE_MAX, 0.05,
                       "L'agrandissement de l'élément. 1 = sa taille de "
                       + "livraison."];
    const blocTaille = creer("div", "ovl-insp-taille");
    blocTaille.title = defTaille[5];
    blocTaille.appendChild(creer("span", "ovl-champ-label", "Taille"));
    noeuds.tailleCurseur = document.createElement("input");
    noeuds.tailleCurseur.type = "range";
    noeuds.tailleCurseur.min = String(ECHELLE_MIN);
    noeuds.tailleCurseur.max = String(ECHELLE_MAX);
    noeuds.tailleCurseur.step = "0.01";
    noeuds.tailleCurseur.setAttribute("aria-label", "Taille");
    noeuds.tailleCurseur.addEventListener("input", function () {
      ecrire(defTaille, noeuds.tailleCurseur.value, null);
      if (noeuds.champs.scale && document.activeElement !== noeuds.champs.scale) {
        const el = elementCourant();
        if (el) noeuds.champs.scale.value = String(arrondi(el.scale));
      }
    });
    blocTaille.appendChild(noeuds.tailleCurseur);
    const saisieTaille = document.createElement("input");
    saisieTaille.type = "number";
    saisieTaille.className = "ovl-taille-valeur";
    saisieTaille.min = String(ECHELLE_MIN);
    saisieTaille.max = String(ECHELLE_MAX);
    saisieTaille.step = String(defTaille[4]);
    saisieTaille.setAttribute("aria-label", "Taille, au chiffre");
    saisieTaille.addEventListener("input", function () {
      if (saisieTaille.value.trim() === "") return;
      ecrire(defTaille, saisieTaille.value, null);
      const el = elementCourant();
      if (el) noeuds.tailleCurseur.value = String(el.scale);
    });
    blocTaille.appendChild(saisieTaille);
    noeuds.champs.scale = saisieTaille;
    hote.appendChild(blocTaille);

    // ── Les réglages de la scène, REPLIÉS ────────────────────────────────
    //
    // Onze champs de plus dans la bande, c'était sept lignes et deux cent
    // trente pixels : la surface tombait de 65 % à 48 % d'échelle. Le panneau
    // avait déjà payé exactement ça — « quinze boutons en permanence sous le
    // canvas mangeaient la hauteur qu'on regarde » — et la réponse avait été la
    // même : replier derrière un bouton.
    //
    // Ce qui RESTE à découvert est ce qu'on règle EN REGARDANT la surface :
    // position, taille, ancrage, rang. Ce qui part dans le volet est ce qu'on
    // pose une fois — l'aspect et le rythme —, et dont l'effet ne se juge pas
    // au pixel près sur un rectangle.
    //
    // UN bloc par champ connu, construit une fois — et non un bloc par
    // (élément, champ), qui en aurait fait plus de deux cents pour n'en montrer
    // que dix. Ce qui décide de leur visibilité et de leurs bornes est la
    // PORTÉE servie par le serveur, relue à chaque rendu : `duree` ne se borne
    // pas pareil sur le rotateur (1–120 s) et sur un widget qui passe (2–180 s),
    // et le même bloc sert les deux.
    noeuds.voletReglages = creer("div", "ovl-insp-volet");
    noeuds.voletReglages.hidden = true;
    noeuds.voletReglages.setAttribute("role", "group");
    noeuds.voletReglages.setAttribute("aria-label", "Aspect et rythme");
    noeuds.champsPropres = [];
    Object.keys(CHAMPS).forEach(function (nom) {
      const pres = CHAMPS[nom];
      let champ, def = null;
      const ou = noeuds.voletReglages;
      if (pres.nature === "booleen") {
        champ = champBooleen(nom, pres, ou);
      } else if (pres.nature === "choix") {
        champ = champChoix(nom, pres, ou);
      } else {
        // Les bornes posées ici sont provisoires : `rendreReglages` les remplace
        // par celles de l'élément courant, en MUTANT ce tableau — et non en le
        // remplaçant. Les gestionnaires de `champNumerique` capturent CETTE
        // référence dans leur closure : lui en substituer une autre laisserait
        // la saisie bornée sur les valeurs de construction, et une inclinaison
        // de 12° serait rangée à 1. Vu à l'écran, invisible en test.
        def = [nom, pres.label, 0, 1, pres.pas || 1, pres.aide || ""];
        champ = champNumerique(def, null, ou);
      }
      noeuds.champsPropres.push({ nom: nom, pres: pres, def: def, bloc: champ.bloc,
                                  input: champ.input, pas: champ.pas });
    });

    // Le bouton qui ouvre le volet, et le volet lui-même — posé DANS la bande,
    // qui est en `position: relative` : il remonte au-dessus d'elle plutôt que
    // de la faire grandir.
    noeuds.boutonReglages = creer("button", "ovl-insp-plus", "Aspect & rythme");
    noeuds.boutonReglages.type = "button";
    noeuds.boutonReglages.setAttribute("aria-expanded", "false");
    noeuds.boutonReglages.title = "Opacité, inclinaison, miroir, largeur max, "
      + "durée d'affichage, délai et animations. Repliés : on les pose une fois, "
      + "et leur effet ne se juge pas sur un rectangle.";
    noeuds.boutonReglages.addEventListener("click", function () {
      basculerVolet();
    });
    hote.appendChild(noeuds.boutonReglages);
    hote.appendChild(noeuds.voletReglages);

    // L'ancrage, avec ses flèches. Neuf carrés muets ne disaient pas ce qu'ils
    // faisaient, et leur seul indice était une infobulle en anglais
    // (« bottom-left ») — la clé du modèle, pas une explication.
    const blocAncrage = creer("div", "ovl-insp-groupe");
    blocAncrage.appendChild(creer("span", "ovl-champ-label", "Ancrage"));
    const grille = creer("div", "ovl-ancrages");
    grille.title = "Le point de l'élément que la position repère. En changer ne "
      + "déplace pas l'élément : x et y sont recalculés pour qu'il reste où il est.";
    noeuds.ancrages = {};
    ANCRAGES.forEach(function (a) {
      const b = creer("button", "ovl-ancrage", flecheAncrage(a));
      b.type = "button";
      b.dataset.ancrage = a;
      b.title = "Ancrer en " + nomAncrage(a);
      b.setAttribute("aria-label", "Ancrer en " + nomAncrage(a));
      b.addEventListener("click", function () {
        const element = elementCourant();
        if (!element || element.locked || element.anchor === a) return;
        const r = boiteCalque();
        reancrer(element, etat.elementCourant, a,
                 r ? r.width : 0, r ? r.height : 0);
        marquerModifie();
        rendreReglages();
        rendreSurface();
      });
      noeuds.ancrages[a] = b;
      grille.appendChild(b);
    });
    blocAncrage.appendChild(grille);
    hote.appendChild(blocAncrage);

    const blocRang = creer("div", "ovl-insp-groupe");
    blocRang.appendChild(creer("span", "ovl-champ-label", "Rang"));
    const rangs = creer("div", "ovl-segment");
    noeuds.rangDerriere = boutonSegment(rangs, "Derrière",
      "Passe l'élément d'un cran EN ARRIÈRE : ce qui le chevauche le couvrira.");
    noeuds.rangDerriere.addEventListener("click", function () { deplacerRang(1); });
    noeuds.rangDevant = boutonSegment(rangs, "Devant",
      "Passe l'élément d'un cran EN AVANT : il couvrira ce qui le chevauche.");
    noeuds.rangDevant.addEventListener("click", function () { deplacerRang(-1); });
    blocRang.appendChild(rangs);
    hote.appendChild(blocRang);

    hote.appendChild(creer("div", "ovl-espace"));

    // Une question DISTINCTE de « l'élément occupe-t-il seul la scène » : on
    // peut vouloir un meme qui chasse les autres widgets mais garde Wally à
    // côté, pour qu'il le commente.
    const bascule = creer("label", "ovl-bascule");
    bascule.title = "Décoché, cet élément efface l'avatar et la bulle le temps "
      + "de son affichage. Coché, Wally reste à l'écran à côté de lui.";
    const coche = document.createElement("input");
    coche.type = "checkbox";
    coche.addEventListener("change", function () {
      const element = elementCourant();
      if (!element) return;
      element.wally_visible = coche.checked;
      marquerModifie();
    });
    bascule.appendChild(coche);
    bascule.appendChild(creer("span", "ovl-bascule-label", "Wally reste visible"));
    noeuds.wallyVisible = coche;
    hote.appendChild(bascule);

    // Le plus gros gain de temps du panneau, à portée de main plutôt que replié
    // avec les outils : trente-sept éléments × trois scènes se règlent une fois,
    // pas trois. Le libellé DIT combien de scènes vont être touchées.
    noeuds.copierScenes = creer("button", "ovl-lien ovl-lien-cadre", "Copier vers les autres scènes");
    noeuds.copierScenes.title = "Copie le placement et l'aspect de la sélection "
      + "— position, ancrage, taille, opacité, inclinaison, miroir, largeur "
      + "max — vers TOUTES les autres scènes. Les durées et les animations ne "
      + "partent PAS : elles sont propres à chaque scène. Une confirmation dit "
      + "combien d'éléments et dans quelles scènes avant d'écrire quoi que ce "
      + "soit.";
    noeuds.copierScenes.addEventListener("click", function () {
      propager(selection(), "la sélection");
    });
    hote.appendChild(noeuds.copierScenes);
  }

  function elementCourant() {
    const scene = sceneCourante();
    if (!scene || !etat.elementCourant) return null;
    return scene.elements[etat.elementCourant] || null;
  }

  /** Ce que l'overlay fait AUJOURD'HUI de cet élément — même repli que
   *  `masqueWally()` dans `overlay.js`. Un modèle rangé avant l'ajout du champ
   *  ne le porte pas : c'était alors `solo` qui décidait de l'effacement, et la
   *  case doit montrer le comportement réel, pas un défaut inventé. */
  function gardeWally(element) {
    if (element.wally_visible === undefined || element.wally_visible === null) {
      return element.solo === false;
    }
    return !!element.wally_visible;
  }

  /** Ouvre ou ferme le volet des réglages d'aspect et de rythme.
   *
   *  Même mécanique que le panneau d'outils : le CÔTÉ se choisit à l'OUVERTURE,
   *  parce que la bande passe à la ligne selon la largeur de la fenêtre et
   *  qu'un ancrage figé sort de l'écran une fois sur deux — piège déjà payé ici.
   *  L'écouteur de fermeture est posé au tour SUIVANT, sinon le clic qui vient
   *  d'ouvrir referme aussitôt.
   */
  function basculerVolet(force) {
    const volet = noeuds.voletReglages;
    const bouton = noeuds.boutonReglages;
    if (!volet || !bouton) return;
    const ouvert = force === undefined ? volet.hidden : !!force;
    volet.hidden = !ouvert;
    bouton.classList.toggle("actif", ouvert);
    bouton.setAttribute("aria-expanded", ouvert ? "true" : "false");
    if (ouvert) {
      placerVolet();
      setTimeout(function () {
        document.addEventListener("pointerdown", fermerVoletDehors, true);
      }, 0);
    } else {
      document.removeEventListener("pointerdown", fermerVoletDehors, true);
    }
  }

  function placerVolet() {
    const volet = noeuds.voletReglages;
    const bouton = noeuds.boutonReglages;
    if (!volet || !bouton || !noeuds.travail) return;
    volet.style.left = "auto";
    volet.style.right = "auto";
    // Aligné sur le bouton, puis rabattu s'il sort du cadre de travail.
    const b = bouton.getBoundingClientRect();
    const cadre = noeuds.travail.getBoundingClientRect();
    volet.style.left = Math.max(0, b.left - cadre.left) + "px";
    const v = volet.getBoundingClientRect();
    if (v.right > cadre.right - 4) {
      volet.style.left = "auto";
      volet.style.right = "0";
    }
  }

  function fermerVoletDehors(evt) {
    if (noeuds.voletReglages && noeuds.voletReglages.contains(evt.target)) return;
    if (noeuds.boutonReglages && noeuds.boutonReglages.contains(evt.target)) return;
    // Le sélecteur d'animation est monté sur `<body>`, hors du volet : sans
    // cette garde, choisir une animation refermerait le volet sous les doigts.
    if (menuOuvert && menuOuvert.contains(evt.target)) return;
    basculerVolet(false);
  }

  function rendreReglages() {
    if (!noeuds.champs) return;
    const element = elementCourant();
    const scene = sceneCourante();
    // Le cadenas bloque TOUT ce qui touche au placement : position, taille et
    // ancrage compris. Sans ça, le verrou n'arrêtait que le glisser — on
    // déplaçait par les champs un élément qu'on croyait à l'abri.
    const fige = !!(element && element.locked);
    const titre = fige ? "Verrouillé : le cadenas de la liste le libère." : "";
    noeuds.reglageNom.textContent = element
      ? libelle(etat.elementCourant) + (fige ? " · 🔒 verrouillé" : "")
      : "Aucun élément choisi";
    // La clé technique et le rang, sous le nom : la clé est ce qui apparaît
    // dans les logs et dans le modèle, le rang est ce que « Devant / Derrière »
    // déplace — sans lui, les deux boutons agissent à l'aveugle.
    if (noeuds.inspCle) {
      const rang = element && scene
        ? (scene.ordre || []).indexOf(etat.elementCourant) : -1;
      noeuds.inspCle.textContent = element
        ? etat.elementCourant + (rang >= 0 ? " · rang " + (rang + 1) : "")
        : "";
    }
    ["x", "y", "scale"].forEach(function (cle) {
      const input = noeuds.champs[cle];
      input.disabled = !element || fige;
      input.title = titre;
      ((noeuds.pas || {})[cle] || []).forEach(function (b) {
        b.disabled = !element || fige;
      });
      // On n'écrase pas un champ en cours de saisie : la valeur sauterait sous
      // les doigts à chaque frappe.
      if (element && document.activeElement !== input) {
        input.value = String(Math.round(element[cle] * 100) / 100);
      } else if (!element) {
        input.value = "";
      }
    });
    if (noeuds.tailleCurseur) {
      noeuds.tailleCurseur.disabled = !element || fige;
      noeuds.tailleCurseur.title = titre;
      if (element && document.activeElement !== noeuds.tailleCurseur) {
        noeuds.tailleCurseur.value = String(element.scale);
      }
    }
    // Les réglages de la scène. La PORTÉE servie par le serveur décide de ce
    // qui se montre : « durée d'affichage » sur un avatar, qui vit en
    // permanence, serait un réglage qu'aucun code ne lit.
    const portes = element ? portesDe(etat.elementCourant) : {};
    (noeuds.champsPropres || []).forEach(function (champ) {
      const regle = portes[champ.nom];
      const porte = !!element && regle !== undefined;
      champ.bloc.hidden = !porte;
      champ.input.disabled = !porte || fige;
      champ.input.title = titre || (champ.pres.aide || "");
      (champ.pas || []).forEach(function (b) { b.disabled = !porte || fige; });
      if (!porte) return;
      const valeur = element[champ.nom];

      if (champ.pres.nature === "booleen") {
        champ.input.checked = !!valeur;
        return;
      }
      if (champ.pres.nature === "choix") {
        // Le bouton porte le nom FRANÇAIS de l'animation : « fadeInUpBig » ne
        // dit rien à qui règle un habillage. Le modèle, lui, garde la clé.
        champ.input.textContent = nomAnimation(valeur);
        return;
      }

      // Les bornes viennent de l'élément COURANT, pas d'une table figée à la
      // construction : le même bloc sert le rotateur (durée d'un média,
      // 1–120 s) et un widget qui passe (durée d'un passage, 2–180 s).
      const mini = regle[0], maxi = regle[1], auto = !!regle[2];
      champ.input.min = String(auto ? 0 : mini);
      champ.input.max = String(maxi);
      // Les bornes du chemin d'ÉCRITURE suivent celles de l'élément courant.
      // On MUTE le tableau, on ne le remplace pas : les gestionnaires de
      // `champNumerique` en ont capturé la référence, et une autre les
      // laisserait borner sur les valeurs de construction.
      if (champ.def) {
        champ.def[2] = auto ? 0 : mini;
        champ.def[3] = maxi;
      }
      if (document.activeElement === champ.input) return;
      // Zéro ne veut pas dire zéro sur un champ « auto » : le montrer tel quel
      // ferait lire « durée : 0 », donc « ne s'affiche pas ».
      champ.input.value = (auto && !(Number(valeur) > 0))
        ? "" : String(Math.round(Number(valeur) * 100) / 100);
      // Le repère « Auto » n'a de sens que là où zéro en a un. Posé partout, il
      // promettrait un mode automatique au rotateur, qui n'en a pas : sa durée
      // se borne au plancher, elle ne se délègue à personne.
      champ.input.placeholder = auto ? (champ.pres.auto || "") : "";
    });
    if (noeuds.wallyVisible) {
      noeuds.wallyVisible.disabled = !element;
      noeuds.wallyVisible.checked = !!element && gardeWally(element);
    }
    if (noeuds.rangDerriere) {
      const ordre = (scene && scene.ordre) || [];
      const rang = element ? ordre.indexOf(etat.elementCourant) : -1;
      noeuds.rangDerriere.disabled = rang < 0 || rang >= ordre.length - 1;
      noeuds.rangDevant.disabled = rang <= 0;
    }
    if (noeuds.copierScenes) {
      // Le libellé DIT combien de scènes vont être touchées : « copier vers les
      // autres scènes » sur un panneau qui n'en a qu'une ne copie nulle part.
      const autres = autresScenes().length;
      noeuds.copierScenes.textContent = autres
        ? "Copier vers " + (autres > 1 ? "les " + autres + " autres scènes"
                                       : "l'autre scène")
        : "Aucune autre scène";
      noeuds.copierScenes.disabled = !autres || !selection().length;
    }
    ANCRAGES.forEach(function (a) {
      noeuds.ancrages[a].classList.toggle("actif", !!element && element.anchor === a);
      noeuds.ancrages[a].disabled = !element || fige;
    });
    // Ici et pas dans `rendreSelection()` : la barre d'outils suit la SÉLECTION,
    // et tous les chemins qui la changent passent par les réglages.
    rendreOutils();
  }

  // ── La barre de publication ─────────────────────────────────────────────

  /** Le détail est-il déplié ? DANS LE NAVIGATEUR, pas dans le modèle : c'est
   *  un confort de lecture, pas une décision de mise en scène. Déplié par
   *  défaut quand quelque chose attend — le seul moment où il a du contenu. */
  let piedDeplie = true;

  // Au-delà, la grille du pied prendrait la moitié de la hauteur du panneau.
  // Ce qui est coupé est DIT (« … et 12 autres ») : une liste tronquée en
  // silence se lit comme une liste complète, et c'est sur celle-là qu'on
  // décide de publier.
  const PIED_DETAIL_MAX = 24;

  /** Depuis quand l'antenne diffuse ce qu'elle diffuse. */
  function antenneDepuis() {
    const t = etat.majAntenne ? Date.parse(etat.majAntenne) : NaN;
    if (!isFinite(t)) return "l'antenne diffuse la mise en scène enregistrée";
    const d = new Date(t);
    const deux = function (n) { return (n < 10 ? "0" : "") + n; };
    return "l'antenne diffuse toujours la version de "
      + deux(d.getHours()) + ":" + deux(d.getMinutes());
  }

  function rendreBarrePublication() {
    if (!noeuds.pied) return;
    const n = etat.brouillon;
    const diff = diffAntenne();
    // Deux comptes, et ils ne disent pas la même chose : `n` compte les GESTES
    // du brouillon, `diff.total` ce qui PART réellement. Déplacer un élément
    // puis le ramener fait deux gestes et zéro changement — et c'est le second
    // chiffre qu'on veut lire avant de cliquer.
    const connu = !!modeleAntenne();
    noeuds.pied.classList.toggle("en-attente", n > 0);

    if (n === 0) {
      noeuds.piedTitre.textContent = etat.direct
        ? "Publication au fil de l'eau — chaque geste part à l'antenne."
        : "Tout est à l'antenne.";
      const depuisQuand = antenneDepuis();
      noeuds.piedSous.textContent =
        depuisQuand.charAt(0).toUpperCase() + depuisQuand.slice(1) + ".";
    } else if (!connu || diff.total) {
      const compte = connu ? diff.total : n;
      noeuds.piedTitre.textContent = compte + " modification"
        + (compte > 1 ? "s" : "") + " en attente — " + antenneDepuis();
      const scenes = (etat.layout && etat.layout.scenes || []).length;
      noeuds.piedSous.textContent = "Publier remplace les " + scenes
        + " scène" + (scenes > 1 ? "s" : "") + " d'un coup. Les spectateurs "
        + "voient le changement en moins d'une seconde.";
    } else {
      // `n > 0` et pourtant rien à envoyer : les gestes se sont annulés. Le
      // dire, plutôt que d'afficher « 0 modification en attente » à côté d'un
      // bouton actif — c'est le genre de contradiction qu'on relit trois fois.
      noeuds.piedTitre.textContent = "Aucun changement net — les "
        + n + " geste" + (n > 1 ? "s" : "") + " du brouillon se sont annulés.";
      noeuds.piedSous.textContent = "Publier ne changerait rien à l'antenne. "
        + "« Revenir à l'antenne » solde le brouillon.";
    }

    // Le détail ne se déplie que s'il a quelque chose à montrer.
    const detail = diff.total > 0;
    noeuds.piedDetail.style.display = detail ? "" : "none";
    noeuds.piedDetail.textContent = piedDeplie ? "Masquer le détail" : "Voir le détail";
    noeuds.piedDetail.setAttribute("aria-expanded", piedDeplie ? "true" : "false");
    rendrePiedDetail(detail && piedDeplie ? diff : null);

    noeuds.publier.disabled = n === 0;
    noeuds.abandonner.disabled = n === 0;
    majBoutonsHistoire();
  }

  /** La grille du détail. `diff` à `null` la vide et la replie. */
  function rendrePiedDetail(diff) {
    const hote = noeuds.piedListe;
    if (!hote) return;
    hote.innerHTML = "";
    hote.style.display = diff ? "" : "none";
    if (!diff) return;
    // Le nom de la scène n'est répété que si le DÉTAIL en touche plusieurs —
    // pas si le panneau en compte plusieurs : tant que tout ce qui attend vient
    // du même onglet, le badge ne distingue rien et vole la place à la
    // description, qui finit en « ancrage milieu-droite → haut-… ».
    //
    // Jamais non plus sur une ligne qui porte SUR la scène : « Partie en cours ·
    // [Partie en cours] · renommée » dit deux fois le même mot.
    const scenes = {};
    diff.liste.forEach(function (l) { scenes[l.slug] = true; });
    const multi = Object.keys(scenes).length > 1;
    diff.liste.slice(0, PIED_DETAIL_MAX).forEach(function (l) {
      const ligne = creer("div", "ovl-pied-ligne");
      // La ligne entière en infobulle : la description est coupée par la
      // largeur de la colonne, et c'est justement elle qu'on veut lire en
      // entier avant de publier.
      ligne.title = l.nom + (multi ? " · " + l.scene : "") + " — " + l.d;
      ligne.appendChild(creer("span", "ovl-point"));
      ligne.appendChild(creer("span", "ovl-pied-nom", l.nom));
      if (multi && l.cle) ligne.appendChild(creer("span", "ovl-pied-scene", l.scene));
      ligne.appendChild(creer("span", "ovl-pied-quoi", l.d));
      hote.appendChild(ligne);
    });
    const reste = diff.liste.length - PIED_DETAIL_MAX;
    if (reste > 0) {
      hote.appendChild(creer("div", "ovl-pied-reste",
        "… et " + reste + " autre" + (reste > 1 ? "s" : "") + "."));
    }
  }

  // ── Le brouillon retrouvé au chargement ─────────────────────────────────

  /** Proposé, JAMAIS appliqué d'office : on doit savoir qu'on reprend un
   *  travail en cours, et pouvoir le jeter. Appliqué en silence, un brouillon
   *  d'avant-hier partirait à l'antenne au premier « Mettre à jour » sans que
   *  personne ait vu ce qu'il contenait. */
  function proposerBrouillon(d) {
    if (!d || !etat.layout || !noeuds.proposition) return;
    const n = d.n;
    // `base` est ce qui était à l'antenne quand le brouillon a été écrit : s'il
    // a bougé depuis, le reprendre écrasera le travail de l'autre onglet.
    const perime = d.base && etat.publie && d.base !== etat.publie;
    noeuds.propositionTexte.textContent =
      "Brouillon retrouvé : " + n + " modification" + (n > 1 ? "s" : "")
      + " non publiée" + (n > 1 ? "s" : "") + ", " + depuis(d.quand) + "."
      + (perime ? " ⚠ La mise en scène à l'antenne a changé depuis." : "");
    noeuds.proposition.style.display = "";
    noeuds.propositionReprendre.onclick = function () { reprendreBrouillon(d); };
    noeuds.propositionJeter.onclick = function () {
      oublierBrouillon();
      noeuds.proposition.style.display = "none";
      notifier("Brouillon jeté.");
    };
  }

  /** Même résolution que `adopter()` : la scène demandée si elle existe encore,
   *  la scène par défaut sinon. Sans ça, un brouillon dont la scène a été
   *  supprimée entre-temps laisserait la liste sans ligne active. */
  function reprendreBrouillon(d) {
    etat.layout = d.layout;
    etat.brouillon = d.n;
    const scenes = etat.layout.scenes || [];
    const voulu = d.scene || etat.slugCourant;
    const existe = scenes.some(function (s) { return s.slug === voulu; });
    etat.slugCourant = existe
      ? voulu
      : (etat.layout.defaut || (scenes[0] || {}).slug || null);
    const scene = sceneCourante();
    if (!scene || !scene.elements[etat.elementCourant]) {
      etat.elementCourant = (scene && scene.ordre && scene.ordre[0]) || null;
    }
    retenirScene(etat.slugCourant);
    noeuds.proposition.style.display = "none";
    // Les gestes qui ont produit ce brouillon appartiennent à une autre visite :
    // la pile repart d'ici, en gardant leur COMPTE (`base`) — ils sont toujours
    // en attente de publication, ils ne sont simplement plus annulables.
    reinitialiserHistoire();
    rendreTout();
    notifier("Brouillon repris — rien n'est parti à l'antenne.");
  }

  function rendreTout() {
    rendreScenes();
    rendreElements();
    rendreSurface();
    rendreReglages();
    rendreBadgeCanvas();
    rendreBarrePublication();
  }

  // ── Le squelette ────────────────────────────────────────────────────────

  /** La barre sous la surface : l'état de l'aperçu, « Tout afficher », et la
   *  bascule qui estompe les repères pour laisser voir la page dessous. */
  /** Prépare la capture : réduite, recompressée, et RASTERISÉE au passage.
   *
   *  Le canvas est ce qui rend l'opération sûre autant que légère — ce qui en
   *  sort est une image matricielle produite par nous, quelle que soit l'entrée.
   *  Un SVG déposé ici en ressort aplati, sans rien de ce qu'il contenait.
   */
  function preparerFond(fichier, fini) {
    const lecteur = new FileReader();
    lecteur.onerror = function () { notifier("Image illisible.", "error"); };
    lecteur.onload = function () {
      const img = new Image();
      img.onerror = function () {
        notifier("Ce fichier n'est pas une image affichable.", "error");
      };
      img.onload = function () {
        const large = img.naturalWidth || 0, haut = img.naturalHeight || 0;
        if (!large || !haut) {
          notifier("Image sans dimensions.", "error");
          return;
        }
        const facteur = Math.min(1, FOND_LARGEUR_MAX / large);
        const toile = document.createElement("canvas");
        toile.width = Math.max(1, Math.round(large * facteur));
        toile.height = Math.max(1, Math.round(haut * facteur));
        let url = "";
        try {
          toile.getContext("2d").drawImage(img, 0, 0, toile.width, toile.height);
          url = toile.toDataURL("image/webp", FOND_QUALITE);
          // Un navigateur sans WebP rend un PNG SANS le dire : celui-ci pèse
          // plusieurs fois plus lourd, et c'est le quota partagé avec le
          // brouillon qui le paierait. On repasse alors en JPEG.
          if (url.indexOf("data:image/webp") !== 0) {
            url = toile.toDataURL("image/jpeg", FOND_QUALITE);
          }
        } catch (e) {
          notifier("Image impossible à préparer : " + e.message, "error");
          return;
        }
        // Le ratio : les repères se placent en POURCENTAGES du canvas 16/9. Une
        // capture d'un autre format est étirée pour que x % de l'image tombe
        // sur x % de la scène — c'est ce qui garde le placement juste, au prix
        // d'une légère déformation qu'on annonce plutôt que de la laisser
        // découvrir.
        const ratio = large / haut;
        if (Math.abs(ratio - 16 / 9) > 0.05) {
          notifier("Capture en " + large + " × " + haut + " : elle sera étirée "
            + "au 16/9 de la scène pour que les repères tombent juste.", "error");
        }
        fini(url);
      };
      img.src = String(lecteur.result);
    };
    lecteur.readAsDataURL(fichier);
  }

  /** Pose la capture derrière l'aperçu. En PREMIER dans la surface : c'est
   *  l'ordre du DOM qui décide de l'empilement, et l'aperçu — une iframe au
   *  fond transparent — doit rester lisible par-dessus. */
  function appliquerFond(image, opacite) {
    if (!noeuds.cadre || !estImageRangeable(image)) return;
    if (!noeuds.fond) {
      noeuds.fond = document.createElement("img");
      noeuds.fond.className = "ovl-fond";
      noeuds.fond.alt = "";
      noeuds.cadre.insertBefore(noeuds.fond, noeuds.cadre.firstChild);
    }
    noeuds.fond.src = image;
    noeuds.fond.style.opacity = String(bornerOpaciteFond(opacite) / 100);
    if (noeuds.fondOpacite) noeuds.fondOpacite.value = String(bornerOpaciteFond(opacite));
    // Et non `majControlesFond(true)` : c'est `majReperesAide()` qui décide
    // désormais de ce qu'on voit, et lui seul allume la bascule. Poser l'image
    // sans repasser par lui la laissait cachée par le `display` du tour d'avant.
    majReperesAide();
  }

  function retirerFondAffiche() {
    if (noeuds.fond && noeuds.fond.parentNode) {
      noeuds.fond.parentNode.removeChild(noeuds.fond);
    }
    noeuds.fond = null;
    oublierFond();
    majReperesAide();
    notifier("Capture de fond retirée.");
  }

  function majControlesFond(present) {
    [noeuds.fondOpacite, noeuds.fondRetirer, noeuds.fondLabel].forEach(function (n) {
      if (n) n.style.display = present ? "" : "none";
    });
  }

  // ── La barre du canvas ──────────────────────────────────────────────────
  //
  // Ce qui décide de CE QU'ON VOIT sur la surface, et rien d'autre. Les gestes
  // qui touchent au modèle vivent ailleurs : dans la bande d'inspection pour
  // l'élément choisi, dans le panneau d'outils pour la sélection.
  //
  // Trois états de vue et non deux bascules indépendantes : « aperçu visible »
  // et « repères estompés » se combinaient en quatre cases dont une n'a aucun
  // sens (pas d'aperçu ET repères estompés — un cadre vide). Un segment à trois
  // positions dit la même chose sans le cas absurde.
  const VUES = [
    ["les-deux", "Aperçu + cadres",
     "La page réelle, avec les repères de placement par-dessus."],
    ["apercu", "Aperçu seul",
     "Les repères s'effacent pour laisser voir la page. Celui qu'on règle, et "
     + "celui qu'on survole, restent nets."],
    ["cadres", "Cadres seuls",
     "La page est masquée : on ne place plus que des rectangles nommés. Utile "
     + "quand l'aperçu bouge trop pour viser."],
  ];

  /** Pose sur la surface ce que le segment de vue demande.
   *
   *  `avec-apercu` ne dépend PAS que du chargement : elle dit « la page est
   *  visible dessous », et c'est elle qui rend les repères discrets. En
   *  « cadres seuls » il n'y a rien dessous — la retirer redonne aux repères
   *  leur style plein, sans une seule règle CSS dupliquée.
   */
  function majClassesVue() {
    if (!noeuds.cadre) return;
    const cadre = noeuds.cadre;
    cadre.classList.toggle("avec-apercu", apercuPret && vue !== "cadres");
    cadre.classList.toggle("reperes-estompes", vue === "apercu");
    cadre.classList.toggle("cadres-seuls", vue === "cadres");
    (noeuds.vues || []).forEach(function (b) {
      b.classList.toggle("actif", b.dataset.vue === vue);
      b.setAttribute("aria-pressed", b.dataset.vue === vue ? "true" : "false");
    });
  }

  function choisirVue(nom) {
    if (vue === nom) return;
    vue = nom;
    majClassesVue();
  }

  /** Les repères d'aide posés SUR la surface : la grille d'aimantation, la zone
   *  sûre, la capture de stream. Trois bascules indépendantes — elles ne
   *  s'excluent pas, on veut souvent les trois à la fois. */
  function majReperesAide() {
    if (noeuds.grille) noeuds.grille.style.display = aides.grille ? "" : "none";
    if (noeuds.zoneSure) noeuds.zoneSure.style.display = aides.zoneSure ? "" : "none";
    if (noeuds.fond) noeuds.fond.style.display = aides.capture ? "" : "none";
    (noeuds.aides || []).forEach(function (b) {
      // « Capture de jeu » n'est allumée que s'il y a une capture À MONTRER :
      // allumée sans image, elle promettrait un fond qu'on ne voit pas, et le
      // clic suivant l'éteindrait sans que rien ne change à l'écran.
      const on = b.dataset.aide === "capture"
        ? (!!noeuds.fond && aides.capture) : !!aides[b.dataset.aide];
      b.classList.toggle("actif", on);
      b.setAttribute("aria-pressed", on ? "true" : "false");
    });
    majControlesFond(!!noeuds.fond && aides.capture);
  }

  /** Un groupe de boutons collés, façon segment. */
  function segment(hote) {
    const g = creer("div", "ovl-segment");
    hote.appendChild(g);
    return g;
  }

  function boutonSegment(hote, texte, titre) {
    const b = creer("button", "ovl-segment-btn", texte);
    b.type = "button";
    if (titre) b.title = titre;
    hote.appendChild(b);
    return b;
  }

  function barreCanvas() {
    const barre = creer("div", "ovl-canvas-barre");

    // ── ce qu'on voit ──
    const gVue = segment(barre);
    noeuds.vues = VUES.map(function (v) {
      const b = boutonSegment(gVue, v[1], v[2]);
      b.dataset.vue = v[0];
      b.addEventListener("click", function () { choisirVue(v[0]); });
      return b;
    });

    // ── les repères d'aide ──
    const gAide = segment(barre);
    noeuds.aides = [];

    const bGrille = boutonSegment(gAide, "Grille 10 %",
      "Le quadrillage de l'aimantation. Les repères s'y accrochent quand on "
      + "les glisse — Alt suspend l'accroche.");
    bGrille.dataset.aide = "grille";
    bGrille.addEventListener("click", function () {
      aides.grille = !aides.grille;
      majReperesAide();
    });
    noeuds.aides.push(bGrille);

    const bZone = boutonSegment(gAide, "Zone sûre",
      "Une marge de 5 % sur les quatre bords. Ce qui en sort risque d'être "
      + "rogné par l'affichage du spectateur ou couvert par l'interface Twitch.");
    bZone.dataset.aide = "zoneSure";
    bZone.addEventListener("click", function () {
      aides.zoneSure = !aides.zoneSure;
      majReperesAide();
    });
    noeuds.aides.push(bZone);

    // La capture de stream en fond : on place par rapport au décor réel — le
    // cadre du chat, la zone de jeu — plutôt que dans le vide. Sans capture
    // posée, le bouton en demande une ; avec, il la montre ou la cache.
    const fichierFond = document.createElement("input");
    fichierFond.type = "file";
    fichierFond.accept = "image/*";
    fichierFond.style.display = "none";
    fichierFond.addEventListener("change", function () {
      const f = fichierFond.files && fichierFond.files[0];
      // Vidé APRÈS : sans ça, redéposer la même capture n'émettrait pas de
      // second `change` et le bouton semblerait mort.
      if (f) {
        preparerFond(f, function (url) {
          const opacite = noeuds.fondOpacite
            ? bornerOpaciteFond(noeuds.fondOpacite.value) : FOND_OPACITE_DEFAUT;
          aides.capture = true;
          appliquerFond(url, opacite);
          const range = rangerFond(url, opacite);
          notifier(range
            ? "Capture posée en fond — elle ne part pas à l'antenne."
            : "Capture posée, mais le stockage du navigateur est plein : elle "
              + "ne survivra pas au rechargement. Le brouillon, lui, est intact.",
            range ? "success" : "error");
        });
      }
      fichierFond.value = "";
    });
    barre.appendChild(fichierFond);

    const bCapture = boutonSegment(gAide, "Capture de jeu",
      "Affiche une capture de ton stream derrière la surface, pour placer par "
      + "rapport au décor réel. Reste dans CE navigateur : jamais en base, "
      + "jamais à l'antenne.");
    bCapture.dataset.aide = "capture";
    bCapture.addEventListener("click", function () {
      if (!noeuds.fond) { fichierFond.click(); return; }
      aides.capture = !aides.capture;
      majReperesAide();
    });
    noeuds.aides.push(bCapture);

    // L'opacité et le retrait ne s'affichent QUE quand une capture est posée :
    // un curseur qui ne pilote rien se lit comme un réglage cassé.
    noeuds.fondLabel = creer("label", "ovl-fond-reglage");
    noeuds.fondLabel.appendChild(creer("span", null, "Fond"));
    noeuds.fondOpacite = document.createElement("input");
    noeuds.fondOpacite.type = "range";
    noeuds.fondOpacite.min = String(FOND_OPACITE_MIN);
    noeuds.fondOpacite.max = "100";
    noeuds.fondOpacite.step = "5";
    noeuds.fondOpacite.value = String(FOND_OPACITE_DEFAUT);
    noeuds.fondOpacite.title = "Opacité de la capture. Trop nette, elle couvre "
      + "les repères ; trop pâle, elle ne sert plus à rien.";
    // `input` pour voir, `change` pour ranger : ranger à chaque pixel du
    // curseur réécrirait deux cents kilo-octets par mouvement.
    noeuds.fondOpacite.addEventListener("input", function () {
      if (noeuds.fond) {
        noeuds.fond.style.opacity =
          String(bornerOpaciteFond(noeuds.fondOpacite.value) / 100);
      }
    });
    noeuds.fondOpacite.addEventListener("change", function () {
      if (noeuds.fond) rangerFond(noeuds.fond.src, noeuds.fondOpacite.value);
    });
    noeuds.fondLabel.appendChild(noeuds.fondOpacite);
    barre.appendChild(noeuds.fondLabel);

    noeuds.fondRetirer = creer("button", "ovl-lien", "Retirer");
    noeuds.fondRetirer.title = "Enlève la capture de fond.";
    noeuds.fondRetirer.addEventListener("click", retirerFondAffiche);
    barre.appendChild(noeuds.fondRetirer);

    barre.appendChild(creer("div", "ovl-espace"));

    // La pastille des chevauchements. CLIQUABLE : elle nomme les éléments qui
    // se recouvrent, et le geste qui suit est toujours le même — aller les
    // voir. Elle les sélectionne donc, plutôt que de laisser chercher dans une
    // liste de trente-sept lignes.
    noeuds.chevauchements = creer("button", "ovl-chevauchements",
                                  "aucun chevauchement");
    noeuds.chevauchements.type = "button";
    noeuds.chevauchements.addEventListener("click", function () {
      const cles = (derniereAnalyse && derniereAnalyse.cles) || [];
      if (!cles.length) { notifier("Aucun chevauchement à montrer."); return; }
      etat.selection = cles.slice();
      poserPrincipal(cles[0]);
      rendreSelection();
      rendreReglages();
      notifier(cles.length + " élément(s) qui se recouvrent, sélectionnés.");
    });
    barre.appendChild(noeuds.chevauchements);

    const tous = creer("button", "ovl-lien", "Tout afficher");
    tous.title = "Pose un repère nommé à la place de chaque élément visible, "
      + "dans l'aperçu de CETTE scène seulement. Ils s'effacent au bout de 30 s.";
    tous.addEventListener("click", function () { testerTous(); });
    barre.appendChild(tous);

    noeuds.echelle = creer("span", "ovl-echelle", "échelle —");
    noeuds.echelle.title = "De combien la page 1920 × 1080 est réduite pour "
      + "tenir dans la surface. Les positions, elles, restent en pourcentage.";
    barre.appendChild(noeuds.echelle);

    // Les outils de la sélection, repliés derrière un bouton : ils ne servent
    // qu'une fois plusieurs éléments choisis, et une barre de quinze boutons en
    // permanence sous le canvas mangeait la hauteur qu'on regarde.
    const coin = creer("div", "ovl-outils-coin");
    noeuds.boutonOutils = creer("button", "ovl-lien ovl-lien-cadre", "Outils");
    noeuds.boutonOutils.title = "Aligner, grouper, répartir, propager vers les "
      + "autres scènes, réinitialiser.";
    noeuds.boutonOutils.setAttribute("aria-expanded", "false");
    noeuds.boutonOutils.addEventListener("click", function (evt) {
      evt.stopPropagation();
      basculerOutils();
    });
    coin.appendChild(noeuds.boutonOutils);
    noeuds.panneauOutils = barreOutils();
    coin.appendChild(noeuds.panneauOutils);
    barre.appendChild(coin);

    majClassesVue();
    majReperesAide();
    return barre;
  }

  /** Ouvre ou ferme le panneau d'outils. Il vit DANS le document, en absolu :
   *  `rendreOutils()` écrit dedans à chaque changement de sélection, et le
   *  reconstruire à l'ouverture perdrait ses nœuds. */
  function basculerOutils(force) {
    if (!noeuds.panneauOutils) return;
    const ouvert = force === undefined ? !outilsOuverts : !!force;
    outilsOuverts = ouvert;
    noeuds.panneauOutils.style.display = ouvert ? "" : "none";
    if (ouvert) placerOutils();
    noeuds.boutonOutils.classList.toggle("actif", ouvert);
    noeuds.boutonOutils.setAttribute("aria-expanded", ouvert ? "true" : "false");
    // En capture, et posé au tour suivant : sinon le clic qui vient d'ouvrir le
    // panneau le referme aussitôt.
    if (ouvert) {
      setTimeout(function () {
        document.addEventListener("pointerdown", fermerOutilsDehors, true);
      }, 0);
    } else {
      document.removeEventListener("pointerdown", fermerOutilsDehors, true);
    }
  }

  /** De quel côté du bouton le panneau se déploie.
   *
   *  Il ne peut pas être ancré une fois pour toutes : la barre du canvas passe
   *  à la ligne selon la largeur, et le bouton se retrouve tantôt au bord droit,
   *  tantôt au bord gauche. Ancré à droite, il sortait de l'écran par la gauche
   *  — quatre cent trente pixels de panneau posés SOUS la barre latérale.
   */
  function placerOutils() {
    const panneau = noeuds.panneauOutils;
    if (!panneau || !noeuds.travail) return;
    panneau.style.left = "0";
    panneau.style.right = "auto";
    const boite = panneau.getBoundingClientRect();
    const limite = noeuds.travail.getBoundingClientRect();
    if (boite.right > limite.right) {
      panneau.style.left = "auto";
      panneau.style.right = "0";
    }
  }

  function fermerOutilsDehors(evt) {
    if (noeuds.panneauOutils && noeuds.panneauOutils.contains(evt.target)) return;
    if (noeuds.boutonOutils && noeuds.boutonOutils.contains(evt.target)) return;
    basculerOutils(false);
  }

  /** Le badge posé dans le coin de la surface : ce qu'on regarde, et ce que le
   *  panneau sait de sa taille. Il remplace la ligne d'état qui courait sous le
   *  canvas — la même information, mais SUR ce à quoi elle se rapporte. */
  function rendreBadgeCanvas() {
    if (!noeuds.badgeScene) return;
    const scene = sceneCourante();
    noeuds.badgeScene.textContent = scene ? "scène « " + scene.nom + " »" : "—";
    rendreCompteMesures();
  }

  function rendreEchelle(facteur) {
    if (!noeuds.echelle) return;
    noeuds.echelle.textContent = facteur
      ? "échelle " + Math.round(facteur * 100) + " %" : "échelle —";
  }

  /** La barre d'outils de la sélection : ce qu'on peut faire à PLUSIEURS
   *  éléments d'un coup. Elle porte aussi le compte — sans lui, on ne sait pas
   *  sur quoi le bouton qu'on s'apprête à cliquer va tomber.
   *
   *  Des libellés écrits, pas des pictogrammes : ⇤ ⇥ ⤒ manquent à la plupart
   *  des polices système et sortent en carré vide, comme le 📋 déjà remplacé
   *  ici par un tracé SVG. Six mots tiennent sur une ligne.
   */
  function barreOutils() {
    const barre = creer("div", "ovl-outils");
    // Replié : ces outils ne servent qu'une fois plusieurs éléments choisis, et
    // quinze boutons en permanence sous le canvas mangeaient la hauteur qu'on
    // regarde. Rien n'est perdu — le bouton « Outils » les rouvre, et il dit
    // combien d'éléments sont sélectionnés.
    barre.style.display = "none";
    noeuds.compteSelection = creer("span", "ovl-outils-compte", "Aucune sélection");
    barre.appendChild(noeuds.compteSelection);
    noeuds.outils = [];

    function groupe(titre) {
      const g = creer("div", "ovl-outils-groupe");
      g.appendChild(creer("span", "ovl-outils-titre", titre));
      barre.appendChild(g);
      return g;
    }

    function outil(hote, texte, titre, mini, action) {
      const b = creer("button", "ovl-outil", texte);
      b.title = titre;
      b.addEventListener("click", function () { action(); });
      hote.appendChild(b);
      // `mini` : le nombre d'éléments sélectionnés en dessous duquel l'outil
      // n'a pas de sens. Grisé plutôt qu'absent — un bouton qui apparaît et
      // disparaît fait sauter la barre sous le pointeur.
      noeuds.outils.push({ noeud: b, mini: mini });
      return b;
    }

    const gh = groupe("Aligner");
    outil(gh, "Gauche", "Colle la sélection au bord GAUCHE du cadre. Tient "
      + "compte de l'ancrage et de la taille rendue : un élément ancré à droite "
      + "ne sort pas du cadre.", 1, function () { aligner("gauche"); });
    outil(gh, "Centre", "Centre horizontalement dans le cadre.", 1,
      function () { aligner("centre-h"); });
    outil(gh, "Droite", "Colle la sélection au bord DROIT du cadre.", 1,
      function () { aligner("droite"); });
    outil(gh, "Haut", "Colle la sélection au bord HAUT du cadre.", 1,
      function () { aligner("haut"); });
    outil(gh, "Milieu", "Centre verticalement dans le cadre.", 1,
      function () { aligner("centre-v"); });
    outil(gh, "Bas", "Colle la sélection au bord BAS du cadre.", 1,
      function () { aligner("bas"); });

    const gg = groupe("Grouper");
    outil(gg, "Grouper", "Réunit la sélection sous un en-tête pliable : elle se "
      + "déplace, se masque et se verrouille alors d'un seul geste. Deux "
      + "éléments au minimum ; un élément n'appartient qu'à un groupe.", 2,
      function () { creerGroupe(); });
    outil(gg, "Dégrouper", "Dissout les groupes dont la sélection fait partie. "
      + "Rien ne bouge, rien n'est effacé : seuls les en-têtes disparaissent.", 1,
      function () { degrouperSelection(); });

    const gr = groupe("Répartir");
    outil(gr, "Horizontal", "Espaces égaux entre les éléments, de gauche à "
      + "droite. Les deux extrêmes ne bougent pas ; ceux du milieu se "
      + "répartissent entre eux. Trois éléments libres au minimum.", 3,
      function () { repartir(true); });
    outil(gr, "Vertical", "Espaces égaux entre les éléments, de haut en bas. "
      + "Les deux extrêmes ne bougent pas. Trois éléments libres au minimum.", 3,
      function () { repartir(false); });

    // Le plus gros gain de temps du panneau : trente-quatre éléments × trois
    // scènes se règlent une fois, pas trois.
    const gp = groupe("Propager");
    outil(gp, "Sélection → autres scènes",
      "Copie la position, l'ancrage et l'échelle des éléments sélectionnés vers "
      + "TOUTES les autres scènes. La visibilité ne part que si la case ci-contre "
      + "est cochée. Une confirmation dit combien d'éléments et dans quelles "
      + "scènes avant d'écrire quoi que ce soit.", 1,
      function () { propager(selection(), "la sélection"); });
    outil(gp, "Scène → autres scènes",
      "Le même geste sur les trente-quatre éléments de cette scène d'un coup. "
      + "Ni l'ordre d'empilement, ni les groupes ne partent : une scène de fin "
      + "n'a pas le découpage d'une scène de jeu.", 0,
      function () { propager(clesScene(), "cette scène"); });
    const vis = creer("label", "ovl-propager-vis");
    noeuds.propagerVisibilite = document.createElement("input");
    noeuds.propagerVisibilite.type = "checkbox";
    vis.appendChild(noeuds.propagerVisibilite);
    vis.appendChild(creer("span", null, "avec la visibilité"));
    // DÉCOCHÉE, et le titre dit pourquoi : `hidden` est ce qui distingue les
    // trois habillages. L'emporter par défaut effacerait d'un clic le seul
    // réglage qui donne un sens aux scènes.
    vis.title = "Décoché (le défaut) : ce qui est masqué dans une scène le reste, "
      + "c'est justement ce qui distingue vos scènes — le bingo masqué au "
      + "démarrage, visible en jeu. Coché : le masquage part avec le placement.";
    gp.appendChild(vis);

    // Le filet du placement : revenir à ce qui était livré. Les valeurs viennent
    // du SERVEUR (`?defauts=1`), jamais d'une copie écrite ici.
    const gz = groupe("Réinitialiser");
    outil(gz, "Sélection",
      "Remet les éléments sélectionnés à leurs valeurs d'origine — position, "
      + "ancrage, échelle et visibilité de livraison. Les valeurs viennent du "
      + "serveur, pas d'une copie du navigateur.", 1,
      function () { reinitialiser(selection(), "la sélection", false); });
    outil(gz, "Toute la scène",
      "Remet les trente-quatre éléments de cette scène à leurs valeurs "
      + "d'origine, empilement et groupes compris. Les autres scènes ne sont "
      + "pas touchées.", 0,
      function () { reinitialiser(clesScene(), "toute la scène", true); });

    // Le « ? » à droite, hors des groupes : il ne porte pas sur la sélection,
    // et il reste cliquable quand tout le reste est grisé — c'est justement
    // quand on ne sait pas quoi faire qu'on le cherche.
    noeuds.boutonAide = creer("button", "ovl-outil ovl-outil-aide", "?");
    noeuds.boutonAide.title = "Les raccourcis clavier de ce panneau (touche ?)";
    noeuds.boutonAide.setAttribute("aria-expanded", "false");
    noeuds.boutonAide.addEventListener("click", function () { basculerAide(); });
    barre.appendChild(noeuds.boutonAide);
    return barre;
  }

  /** Le compte de la sélection, porté par le bouton qui ouvre le panneau : sans
   *  lui, on ne sait pas sur quoi les outils repliés vont tomber. */
  function rendreBoutonOutils(n) {
    if (!noeuds.boutonOutils) return;
    noeuds.boutonOutils.textContent = n > 1 ? "Outils · " + n : "Outils";
    noeuds.boutonOutils.classList.toggle("charge", n > 1);
  }

  /** L'état de la barre d'outils : le compte, et ce qui est utilisable. */
  function rendreOutils() {
    if (!noeuds.compteSelection) return;
    const bloc = selectionDeplacable();
    const n = bloc.membres.length + bloc.bloques.length;
    noeuds.compteSelection.textContent = n
      ? n + " élément" + (n > 1 ? "s" : "") + " sélectionné" + (n > 1 ? "s" : "")
        + (bloc.bloques.length ? " · " + bloc.bloques.length + " verrouillé"
           + (bloc.bloques.length > 1 ? "s" : "") : "")
      : "Aucune sélection";
    noeuds.compteSelection.classList.toggle("actif", n > 0);
    rendreBoutonOutils(n);
    (noeuds.outils || []).forEach(function (o) {
      // Sur le nombre de DÉPLAÇABLES : deux éléments dont un verrouillé ne font
      // pas une répartition à trois.
      o.noeud.disabled = bloc.membres.length < o.mini;
    });
  }

  /** L'icône « chercher », en SVG comme celle du copier : un emoji loupe sort
   *  en carré vide dans un navigateur sans police emoji couleur. */
  function iconeLoupe() {
    const NS = "http://www.w3.org/2000/svg";
    const svg = document.createElementNS(NS, "svg");
    svg.setAttribute("viewBox", "0 0 24 24");
    svg.setAttribute("width", "13");
    svg.setAttribute("height", "13");
    svg.setAttribute("fill", "none");
    svg.setAttribute("stroke", "currentColor");
    svg.setAttribute("stroke-width", "2");
    svg.setAttribute("stroke-linecap", "round");
    svg.setAttribute("aria-hidden", "true");
    ["M21 21l-6-6", "M17 10a7 7 0 11-14 0 7 7 0 0114 0z"].forEach(function (d) {
      const path = document.createElementNS(NS, "path");
      path.setAttribute("d", d);
      svg.appendChild(path);
    });
    return svg;
  }

  /** Chercher dans la liste, et n'en garder qu'une partie.
   *
   *  Trente-sept lignes dont vingt-six partent au même endroit : retrouver
   *  « celui qui s'appelle apex quelque chose » se faisait à l'œil, en
   *  déroulant. Le filtre cherche dans le nom lisible ET dans la clé technique
   *  — on connaît l'un ou l'autre selon qu'on vient du panneau ou d'un log.
   */
  function barreFiltres() {
    const barre = creer("div", "ovl-filtres");

    const champ = creer("div", "ovl-recherche");
    champ.appendChild(iconeLoupe());
    noeuds.recherche = document.createElement("input");
    noeuds.recherche.type = "search";
    noeuds.recherche.placeholder = "Filtrer par nom ou par clé";
    noeuds.recherche.setAttribute("aria-label", "Filtrer les éléments");
    noeuds.recherche.addEventListener("input", function () {
      filtre.texte = noeuds.recherche.value.trim().toLowerCase();
      rendreElements();
    });
    champ.appendChild(noeuds.recherche);
    barre.appendChild(champ);

    /** Une pastille de filtre. Les deux ne s'excluent pas : « masqués ET
     *  modifiés » est une question qu'on se pose vraiment avant de publier. */
    function pastille(cle, texte, titre) {
      const b = creer("button", "ovl-filtre-chip", texte);
      b.type = "button";
      b.title = titre;
      b.setAttribute("aria-pressed", "false");
      b.addEventListener("click", function () {
        filtre[cle] = !filtre[cle];
        b.classList.toggle("actif", filtre[cle]);
        b.setAttribute("aria-pressed", filtre[cle] ? "true" : "false");
        rendreElements();
      });
      barre.appendChild(b);
      return b;
    }

    pastille("masques", "Masqués",
      "Ne garder que ce qui est éteint dans CETTE scène. C'est le réglage qui "
      + "distingue vos scènes les unes des autres.");
    pastille("modifies", "Modifiés",
      "Ne garder que ce qui a bougé depuis l'antenne — la même chose que le "
      + "point ambre, mais sur toute la liste d'un coup.");

    return barre;
  }

  /** La barre d'onglets, en tête du panneau : le titre, les scènes, « + Scène »
   *  et l'adresse OBS de celle qu'on règle. */
  function barreScenes() {
    const barre = creer("div", "ovl-barre-scenes");

    const titre = creer("div", "ovl-barre-titre");
    titre.appendChild(creer("div", "ovl-sur-titre", "MISE EN SCÈNE"));
    titre.appendChild(creer("div", "ovl-titre", "Où va chaque élément"));
    barre.appendChild(titre);

    noeuds.listeScenes = creer("ul", "ovl-scenes");
    barre.appendChild(noeuds.listeScenes);

    const plus = creer("button", "ovl-scene-plus", "+ Scène");
    plus.title = "Une scène neuve, aux valeurs d'origine. « Dupliquer » (menu ⋮) "
      + "part au contraire de la scène affichée.";
    plus.addEventListener("click", function () { nouvelleScene(); });
    barre.appendChild(plus);

    barre.appendChild(creer("div", "ovl-espace"));

    // L'adresse à coller dans OBS, celle de la scène AFFICHÉE. Une seule, à
    // droite : trois adresses empilées prenaient la place d'une colonne sans
    // qu'on lise jamais les deux autres.
    const source = creer("div", "ovl-source");
    source.appendChild(creer("span", "ovl-source-label", "Source OBS"));
    const boite = creer("div", "ovl-source-boite");
    noeuds.sourceUrl = creer("span", "ovl-source-url", "");
    boite.appendChild(noeuds.sourceUrl);
    noeuds.sourceCopie = creer("button", "ovl-copie");
    noeuds.sourceCopie.appendChild(iconeCopie());
    noeuds.sourceCopie.addEventListener("click", function () {
      if (noeuds.sourceUrl.textContent) copier(noeuds.sourceUrl.textContent);
    });
    poserInfobulle(noeuds.sourceCopie,
      "Copier l'adresse — c'est elle qu'on colle dans une source navigateur OBS.");
    boite.appendChild(noeuds.sourceCopie);
    source.appendChild(boite);
    barre.appendChild(source);

    return barre;
  }

  /** Cocher « Publier au fil de l'eau », depuis la case OU depuis le menu ⋯.
   *
   *  Un seul chemin pour un réglage qui touche l'antenne : deux copies de cette
   *  garde auraient divergé, et c'est celle qui prévient AVANT d'envoyer.
   */
  function basculerDirect(voulu) {
    // Cocher alors que des modifications attendent les envoie : `publier()`
    // pousse le MODÈLE ENTIER, la prochaine retouche les emporterait de toute
    // façon. On le dit avant, plutôt que de le laisser découvrir à l'antenne.
    if (voulu && etat.brouillon > 0
        && !window.confirm(
          etat.brouillon + " modification(s) attendent.\n\nPublier au fil de "
          + "l'eau les enverra à l'antenne MAINTENANT.\n\nContinuer ?")) {
      return;
    }
    etat.direct = voulu;
    if (etat.direct && etat.brouillon > 0) publier();
    rendreBarrePublication();
  }

  /** Le menu ⋯ du pied : ce qui ne se clique pas tous les jours.
   *
   *  Replié et non supprimé. La maquette ne montrait ni l'export, ni le fil de
   *  l'eau, ni le cran d'annulation — mais un panneau de production ne perd pas
   *  une capacité parce qu'une maquette ne lui a pas trouvé de place. Ce qui se
   *  clique à chaque réglage reste à découvert ; le reste tient ici.
   */
  function ouvrirMenuPied(hote) {
    fermerMenu();
    const menu = creer("div", "ovl-menu ovl-menu-pied");

    const direct = actionMenu(menu, (etat.direct ? "✓ " : "") + "Publier au fil de l'eau",
      true, function () { basculerDirect(!etat.direct); });
    direct.title = "Décoché : l'overlay à l'antenne ne bouge pas tant qu'on n'a "
      + "pas cliqué « Mettre à l'antenne ». Coché : chaque déplacement part au "
      + "relâchement — rien pendant le geste.";

    const annuler = actionMenu(menu, "Annuler la dernière publication",
      !!etat.precedent, function () {
        if (etat.precedent) annulerPublication();
      });
    annuler.title = "Republie la mise en scène d'avant la dernière publication. "
      + "Un seul cran — de quoi ne pas rester coincé en direct.";

    const exporter_ = actionMenu(menu, "Exporter dans un fichier…", true, exporter);
    exporter_.title = "Enregistre la mise en scène AFFICHÉE (brouillon compris) "
      + "dans un fichier JSON daté.";

    const importer_ = actionMenu(menu, "Importer un fichier…", true, function () {
      noeuds.fichierImport.click();
    });
    importer_.title = "Remplace la mise en scène par le contenu d'un fichier "
      + "exporté. Passe par le brouillon — rien ne part à l'antenne sans "
      + "« Mettre à l'antenne ».";

    actionMenu(menu, "Raccourcis clavier", true, function () { basculerAide(true); });

    hote.parentNode.appendChild(menu);
    menuOuvert = menu;
    menuHote = hote;
    // En phase de capture, et posé au tour suivant : sinon le clic qui vient
    // d'ouvrir le menu le referme aussitôt.
    setTimeout(function () {
      document.addEventListener("pointerdown", fermerAuClicDehors, true);
    }, 0);
  }

  /** Le pied de publication : ce qui attend, et ce qui part.
   *
   *  Pleine largeur sous les deux colonnes, et non plus une barre serrée sous
   *  la surface. C'est la seule chose du panneau qui touche l'antenne : elle
   *  doit se voir sans qu'on la cherche, et pouvoir DIRE ce qui va partir —
   *  d'où le détail dépliable, qui n'existait nulle part.
   */
  function piedPublication() {
    const pied = creer("div", "ovl-pied");

    const haut = creer("div", "ovl-pied-haut");
    noeuds.piedPoint = creer("span", "ovl-pied-point");
    haut.appendChild(noeuds.piedPoint);

    const textes = creer("div", "ovl-pied-textes");
    noeuds.piedTitre = creer("div", "ovl-pied-titre", "");
    noeuds.piedSous = creer("div", "ovl-pied-sous", "");
    textes.appendChild(noeuds.piedTitre);
    textes.appendChild(noeuds.piedSous);
    haut.appendChild(textes);

    haut.appendChild(creer("div", "ovl-espace"));

    // Défaire / refaire portent sur les GESTES du brouillon, pas sur l'antenne.
    // Ils restent donc à distance de « Mettre à l'antenne » — deux « annuler »
    // côte à côte seraient le meilleur moyen de cliquer sur le mauvais un soir
    // de live.
    noeuds.defaire = creer("button", "btn ovl-histoire", "↶");
    noeuds.defaire.title = "Annuler le dernier geste du brouillon (Ctrl + Z). "
      + "N'envoie rien : le brouillon seul recule.";
    noeuds.defaire.setAttribute("aria-label", "Annuler le dernier geste");
    noeuds.defaire.disabled = true;
    noeuds.defaire.addEventListener("click", function () {
      direDefait(annulerHistoire());
    });
    haut.appendChild(noeuds.defaire);
    noeuds.refaire = creer("button", "btn ovl-histoire", "↷");
    noeuds.refaire.title = "Refaire le geste annulé (Ctrl + Y).";
    noeuds.refaire.setAttribute("aria-label", "Refaire le geste annulé");
    noeuds.refaire.disabled = true;
    noeuds.refaire.addEventListener("click", function () {
      direRefait(refaireHistoire());
    });
    haut.appendChild(noeuds.refaire);

    noeuds.piedDetail = creer("button", "ovl-pied-lien", "");
    noeuds.piedDetail.addEventListener("click", function () {
      piedDeplie = !piedDeplie;
      rendreBarrePublication();
    });
    haut.appendChild(noeuds.piedDetail);

    noeuds.abandonner = creer("button", "btn", "Revenir à l'antenne");
    noeuds.abandonner.title = "Jette le brouillon et recharge ce qui est "
      + "réellement à l'antenne.";
    noeuds.abandonner.addEventListener("click", function () { abandonner(); });
    haut.appendChild(noeuds.abandonner);

    noeuds.publier = creer("button", "btn ovl-publier", "Mettre à l'antenne");
    noeuds.publier.addEventListener("click", function () { publier(); });
    haut.appendChild(noeuds.publier);

    // Le ⋯ dans son propre conteneur positionné : le menu se pose en absolu et
    // s'ouvre VERS LE HAUT — le pied est en bas du panneau, un menu déroulant
    // vers le bas sortirait de l'écran.
    const coin = creer("div", "ovl-pied-coin");
    const plus = creer("button", "ovl-menu-btn", "⋯");
    plus.title = "Export, import, publication au fil de l'eau, raccourcis…";
    plus.setAttribute("aria-label", "Autres actions de publication");
    plus.addEventListener("click", function (evt) {
      evt.stopPropagation();
      if (menuOuvert && menuOuvert.parentNode === coin) { fermerMenu(); return; }
      ouvrirMenuPied(plus);
    });
    coin.appendChild(plus);
    haut.appendChild(coin);

    pied.appendChild(haut);

    noeuds.piedListe = creer("div", "ovl-pied-liste");
    pied.appendChild(noeuds.piedListe);

    // L'input de fichier reste DANS le document, invisible : un `click()` sur
    // un input détaché n'ouvre le sélecteur nulle part.
    noeuds.fichierImport = document.createElement("input");
    noeuds.fichierImport.type = "file";
    noeuds.fichierImport.accept = "application/json,.json";
    noeuds.fichierImport.style.display = "none";
    noeuds.fichierImport.addEventListener("change", function () {
      importer(noeuds.fichierImport.files && noeuds.fichierImport.files[0]);
      // Vidé APRÈS : sans ça, réimporter deux fois le même fichier n'émettrait
      // pas de second `change`, et l'entrée du menu semblerait morte.
      noeuds.fichierImport.value = "";
    });
    pied.appendChild(noeuds.fichierImport);

    noeuds.pied = pied;
    return pied;
  }

  function construireSquelette(conteneur) {
    conteneur.classList.add("ovl-panneau");
    conteneur.innerHTML = "";
    // Les deux caches de rendu partent avec le squelette : les repères gardés
    // pointent sur un calque qui n'existe plus, et la signature décrirait une
    // liste effacée — le panneau resterait vide en se croyant à jour.
    Object.keys(reperes).forEach(function (c) { delete reperes[c]; });
    listeSignature = null;

    conteneur.appendChild(barreScenes());

    const corps = creer("div", "ovl-corps");

    // À gauche, tout ce qui touche à la surface : elle occupe désormais la
    // place que prenait la colonne des scènes.
    const travail = creer("div", "ovl-travail");
    noeuds.travail = travail;
    travail.appendChild(barreCanvas());

    // La surface et ses deux règles graduées, dans une petite grille. Les
    // graduations ne sont pas décoratives : tout se règle ici en POURCENTAGE,
    // et rien à l'écran ne disait où tombait 50 %.
    const zone = creer("div", "ovl-zone-canvas");
    zone.appendChild(creer("div", "ovl-regle-coin"));
    const regleH = creer("div", "ovl-regle ovl-regle-h");
    const regleV = creer("div", "ovl-regle ovl-regle-v");
    GRADUATIONS.forEach(function (g) {
      // La position exacte, portée par une variable CSS : une règle graduée qui
      // répartit ses chiffres « à peu près » (`space-between`) ment sur le seul
      // point où on la consulte — savoir où tombe 50 %.
      [regleH, regleV].forEach(function (regle) {
        const n = creer("span", null, String(g));
        n.style.setProperty("--g", g + "%");
        regle.appendChild(n);
      });
    });
    zone.appendChild(regleH);
    zone.appendChild(regleV);

    noeuds.cadre = creer("div", "ovl-surface");
    // L'aperçu d'abord, le calque par-dessus : c'est l'ordre du DOM qui décide
    // lequel capte le pointeur, et le glisser vit sur le calque.
    noeuds.apercu = document.createElement("iframe");
    noeuds.apercu.className = "ovl-apercu";
    noeuds.apercu.title = "Aperçu de la scène en cours d'édition";
    noeuds.apercu.setAttribute("scrolling", "no");
    noeuds.apercu.addEventListener("load", apercuCharge);
    noeuds.apercu.addEventListener("error", echecApercu);
    noeuds.cadre.appendChild(noeuds.apercu);

    // La grille d'aimantation et la zone sûre : POSÉES entre l'aperçu et le
    // calque — au-dessus de la page, sous les rectangles — et transparentes au
    // pointeur, sinon elles voleraient le glisser.
    noeuds.grille = creer("div", "ovl-grille-aimant");
    noeuds.cadre.appendChild(noeuds.grille);
    noeuds.zoneSure = creer("div", "ovl-zone-sure");
    noeuds.zoneSure.appendChild(creer("span", "ovl-zone-sure-nom", "zone sûre"));
    noeuds.cadre.appendChild(noeuds.zoneSure);

    noeuds.calque = creer("div", "ovl-calque");
    // Le calque porte le focus clavier, et non les repères : ceux-ci sont
    // reconstruits à chaque rendu, et le focus serait perdu à la première
    // flèche. Il porte aussi les écouteurs du geste, parce que c'est LUI qui
    // reçoit la capture du pointeur.
    noeuds.calque.tabIndex = 0;
    noeuds.calque.setAttribute("aria-label",
      "Surface de placement — flèches pour déplacer la sélection, "
      + "Maj pour un pas de 1 %, Alt pour suspendre l'aimantation, "
      + "glisser sur le fond pour sélectionner plusieurs éléments");
    noeuds.calque.addEventListener("pointerdown", saisirFond);
    noeuds.calque.addEventListener("pointermove", bougerCoalesce);
    noeuds.calque.addEventListener("pointerup", finirManip);
    noeuds.calque.addEventListener("pointercancel", finirManip);
    // Le filet : une capture perdue sans `pointerup` — relâchement hors de la
    // fenêtre du navigateur, onglet qui passe en arrière-plan — laisserait
    // `manip` posé, et la surface cesserait de se redessiner. Un panneau figé
    // sans le moindre message. `finirManip` ayant déjà vidé `manip` avant de
    // rendre la capture, la voie normale n'y repasse pas deux fois.
    noeuds.calque.addEventListener("lostpointercapture", finirManip);
    noeuds.calque.addEventListener("keydown", toucheSurface);
    noeuds.cadre.appendChild(noeuds.calque);

    // Poignées, lignes d'aimantation et coordonnées vivent HORS du calque :
    // celui-ci est vidé à chaque rendu, et elles doivent survivre au geste.
    noeuds.poignees = {};
    COINS.forEach(function (coin) {
      const p = creer("div", "ovl-poignee ovl-poignee-" + coin);
      p.style.display = "none";
      p.title = "Redimensionner — le point d'ancrage ne bouge pas";
      p.addEventListener("pointerdown", function (evt) { saisirPoignee(evt, coin); });
      noeuds.poignees[coin] = p;
      noeuds.cadre.appendChild(p);
    });
    noeuds.guideV = creer("div", "ovl-guide vertical");
    noeuds.guideH = creer("div", "ovl-guide horizontal");
    noeuds.guideV.style.display = "none";
    noeuds.guideH.style.display = "none";
    noeuds.cadre.appendChild(noeuds.guideV);
    noeuds.cadre.appendChild(noeuds.guideH);
    noeuds.coords = creer("div", "ovl-coords");
    noeuds.cadre.appendChild(noeuds.coords);

    // Le badge du coin : ce qu'on regarde et ce que le panneau sait de sa
    // taille. Sur la surface plutôt que sous elle — l'information se rapporte à
    // ce cadre-là, pas au panneau.
    noeuds.badge = creer("div", "ovl-badge-canvas");
    noeuds.badgePoint = creer("span", "ovl-badge-point");
    noeuds.badge.appendChild(noeuds.badgePoint);
    noeuds.badge.appendChild(creer("span", null, CANVAS_W + " × " + CANVAS_H));
    noeuds.badge.appendChild(creer("span", "ovl-badge-sep", "·"));
    noeuds.badgeScene = creer("span", null, "—");
    noeuds.badge.appendChild(noeuds.badgeScene);
    noeuds.badge.appendChild(creer("span", "ovl-badge-sep", "·"));
    noeuds.apercuMesures = creer("span", "ovl-apercu-mesures", "aucune taille mesurée");
    noeuds.badge.appendChild(noeuds.apercuMesures);
    // Sans lui, une seule coupure réseau laisse le repli en place jusqu'au
    // prochain changement de scène — et il n'y a pas toujours de seconde scène
    // vers laquelle aller et revenir. Un bouton explicite plutôt qu'un
    // rechargement automatique : `rendreSurface()` est rappelée à chaque
    // frappe, une relance par frappe serait un pilonnage.
    noeuds.apercuRetry = creer("button", "ovl-lien", "Réessayer");
    noeuds.apercuRetry.style.display = "none";
    noeuds.apercuRetry.addEventListener("click", function () {
      const slug = apercuSlug;
      apercuSlug = null;
      chargerApercu(slug);
    });
    noeuds.badge.appendChild(noeuds.apercuRetry);
    noeuds.cadre.appendChild(noeuds.badge);

    zone.appendChild(noeuds.cadre);
    travail.appendChild(zone);

    noeuds.raccourcis = blocRaccourcis();
    travail.appendChild(noeuds.raccourcis);

    const reglages = creer("div", "ovl-inspecteur");
    bandeInspection(reglages);
    travail.appendChild(reglages);
    // Les raccourcis sont écrits : Alt et Maj ne se devinent pas, et personne
    // ne cherche une poignée qu'il ne sait pas là. La ligne dit l'essentiel et
    // renvoie au « ? » pour le reste — treize raccourcis en une phrase ne se
    // lisent pas.
    travail.appendChild(creer("div", "ovl-aide",
      "Glisser un repère pour le déplacer · les poignées d'angle changent sa "
      + "taille · Alt suspend l'aimantation · flèches : 0,1 % (Maj : 1 %) · "
      + "Ctrl+clic et glisser sur le fond pour choisir plusieurs éléments · "
      + "« ? » pour tous les raccourcis."));
    corps.appendChild(travail);

    // À droite, la liste des éléments de la scène.
    const lateral = creer("div", "ovl-lateral");
    const titreElements = creer("div", "ovl-bloc-titre");
    titreElements.appendChild(creer("span", null, "Éléments de la scène"));
    noeuds.compteElements = creer("span", "ovl-bloc-compte", "");
    titreElements.appendChild(noeuds.compteElements);
    lateral.appendChild(titreElements);
    lateral.appendChild(barreFiltres());
    noeuds.listeElements = creer("ul", "ovl-elements");
    lateral.appendChild(noeuds.listeElements);

    // Le raccourci vers ce qui est caché. Les trente-sept éléments sont
    // TOUJOURS dans chaque scène — seul `hidden` les distingue —, et remontrer
    // un masqué demandait de le retrouver à l'œil dans une liste barrée.
    noeuds.reveler = creer("button", "ovl-reveler", "+ Rendre visible");
    noeuds.reveler.title = "Les éléments masqués de cette scène. Un clic en "
      + "remontre un — rien ne part à l'antenne avant « Mettre à l'antenne ».";
    noeuds.reveler.addEventListener("click", function (evt) {
      evt.stopPropagation();
      ouvrirMenuMasques(noeuds.reveler);
    });
    lateral.appendChild(noeuds.reveler);

    noeuds.aideListe = creer("div", "ovl-aide",
      "Glisser pour changer le rang : ce qui est en haut passe devant. "
      + "Le point ambre marque un élément modifié depuis l'antenne.");
    lateral.appendChild(noeuds.aideListe);
    corps.appendChild(lateral);

    conteneur.appendChild(corps);

    // La proposition de reprise, au-dessus du pied : elle ne s'affiche qu'au
    // chargement, et seulement s'il reste un brouillon.
    noeuds.proposition = creer("div", "ovl-brouillon");
    noeuds.proposition.style.display = "none";
    noeuds.propositionTexte = creer("span", "ovl-brouillon-texte", "");
    noeuds.proposition.appendChild(noeuds.propositionTexte);
    noeuds.propositionReprendre = creer("button", "btn btn-sm", "Reprendre");
    noeuds.propositionReprendre.title =
      "Remet vos modifications en attente. Rien ne part à l'antenne.";
    noeuds.proposition.appendChild(noeuds.propositionReprendre);
    noeuds.propositionJeter = creer("button", "btn btn-sm", "Jeter");
    noeuds.propositionJeter.title = "Oublie le brouillon et garde ce qui est à l'antenne.";
    noeuds.proposition.appendChild(noeuds.propositionJeter);
    conteneur.appendChild(noeuds.proposition);

    conteneur.appendChild(piedPublication());

    // La taille des rectangles ET la réduction de l'aperçu dépendent de la
    // largeur de la surface : sans ça, replier la barre latérale les laisserait
    // à l'échelle d'avant.
    if (window.ResizeObserver) {
      if (observateur) observateur.disconnect();
      observateur = new ResizeObserver(function () {
        ajusterApercu();
        rendreSurface();
      });
      observateur.observe(noeuds.cadre);
    }
    // Les raccourcis vivent sur le DOCUMENT, une seule fois. `monter()` garde
    // déjà contre un second montage, mais un drapeau explicite coûte moins
    // qu'un doublon d'écouteur qui masquerait deux fois la sélection.
    if (!raccourcisPoses) {
      document.addEventListener("keydown", toucheGlobale);
      raccourcisPoses = true;
    }
    // La capture de fond d'une visite précédente. Reposée ici et pas au premier
    // rendu : elle ne dépend d'aucune scène, et la surface existe déjà.
    const fondRange = lireFond();
    if (fondRange) appliquerFond(fondRange.image, fondRange.opacite);
    // `barreCanvas()` est construite AVANT la surface : ses bascules n'avaient
    // alors ni cadre ni repères d'aide sur lesquels mordre. On repasse une fois
    // le cadre monté, sinon la grille est allumée dans la barre et absente à
    // l'écran.
    majClassesVue();
    majReperesAide();
    // Posée tout de suite : la surface a déjà sa largeur, et attendre le
    // premier `load` de l'iframe l'afficherait une frame en taille réelle.
    ajusterApercu();
  }

  // ── Montage ─────────────────────────────────────────────────────────────

  /** Construit le panneau dans `conteneur`. Synchrone et sans exception : une
   *  erreur ici casserait toutes les sections montées après nous. */
  function monter(conteneur) {
    if (!conteneur) return;
    // La garde AVANT tout `await` — ici, avant toute promesse : évaluée après,
    // deux montages concurrents passeraient tous les deux et le panneau
    // s'afficherait en double. C'est arrivé sur ce dashboard.
    if (conteneur.dataset.overlayAdmin === "1") return;
    conteneur.dataset.overlayAdmin = "1";
    // LU AVANT `charger()` : `adopter()` oublie le brouillon rangé — c'est ce
    // qu'on lui demande une fois la publication faite —, et le lire après
    // n'aurait plus rien trouvé.
    let enAttente = null;
    try {
      construireSquelette(conteneur);
      // Le filet du brouillon. Un placement non publié ne survit pas à un F5 —
      // et rien ne le disait : on refermait l'onglet en croyant avoir posé
      // l'élément. Le navigateur n'affiche que son message générique, mais il
      // affiche quelque chose, et c'est tout ce qu'on lui demande.
      window.addEventListener("beforeunload", function (evt) {
        if (etat.brouillon === 0) return;
        evt.preventDefault();
        evt.returnValue = "";   // exigé par les navigateurs historiques
      });
      // La scène qu'on éditait avant le rechargement. Posée AVANT `charger()` :
      // `adopter()` la garde si elle existe encore, et retombe sur la scène par
      // défaut sinon.
      etat.slugCourant = sceneRetenue();
      enAttente = lireBrouillon();
    } catch (e) {
      // DIT, pas seulement affiché : « Mise en scène indisponible » sans la
      // moindre trace laisse le panneau muet sur SA propre panne, et il n'y a
      // alors plus rien à quoi se raccrocher pour la corriger.
      if (window.console) console.error("Panneau de mise en scène :", e);
      conteneur.textContent = "Mise en scène indisponible.";
      return;
    }
    // Le brouillon est PROPOSÉ, pas appliqué : on doit savoir qu'on reprend un
    // travail en cours. Après `charger()`, donc sur le modèle réellement à
    // l'antenne — c'est lui qui dit si le brouillon a pris du retard.
    charger().then(function () { proposerBrouillon(enAttente); });
  }

  return {
    monter: monter,
    etat: etat,
    marquerModifie: marquerModifie,
    publier: publier,
    abandonner: abandonner,
    annulerPublication: annulerPublication,
    charger: charger,
    rendreTout: rendreTout,
    rendreSurface: rendreSurface,
    rendreReglages: rendreReglages,
    selectionner: selectionner,
    selection: selection,
    basculerSelection: basculerSelection,
    etendreSelection: etendreSelection,
    toutSelectionner: toutSelectionner,
    viderSelection: viderSelection,
    sceneCourante: sceneCourante,
    elementCourant: elementCourant,
    slugDepuisNom: slugDepuisNom,
    urlScene: urlScene,
    libelle: libelle,
    description: description,
    tester: tester,
    testerTous: testerTous,
    ANCRAGES: ANCRAGES,
    // Les réglages propres à un élément, exposés pour être CONFRONTÉS au modèle
    // Python : deux tables qui décrivent les mêmes bornes dérivent au premier
    // ajustement, et le panneau laisserait alors saisir ce que le serveur
    // ramène en silence.
    // La table de PRÉSENTATION des réglages (libellés, pas, natures). Les
    // bornes, les choix et les portées ne sont plus ici : elles viennent du
    // serveur. Exposée pour qu'un test vérifie qu'aucun champ affiché n'est
    // inconnu du modèle — un réglage qu'on montre sans qu'il existe laisse
    // saisir une valeur que le serveur ramène en silence.
    CHAMPS: CHAMPS,
    portesDe: portesDe,
    nomAnimation: nomAnimation,
    // Le rangement du brouillon, exposé pour la même raison : il ne touche que
    // `localStorage`, et c'est lui qui décide si un travail non publié survit à
    // un F5 — ou s'il repart à l'antenne tout seul, ce qu'on ne veut jamais.
    rangerBrouillon: rangerBrouillon,
    lireBrouillon: lireBrouillon,
    oublierBrouillon: oublierBrouillon,
    // La capture en fond : même raison, plus une garde à elle. C'est ce qui
    // décide qu'une image de décor ne chasse pas un travail non publié du
    // stockage, et que seule une image reconnue repart en `src`.
    rangerFond: rangerFond,
    lireFond: lireFond,
    oublierFond: oublierFond,
    bornerOpaciteFond: bornerOpaciteFond,
    // La géométrie du glisser, exposée pour être TESTÉE hors navigateur : ces
    // quatre fonctions sont pures, et ce sont elles qui décident si le point
    // saisi reste sous le pointeur.
    geometrie: geometrie,
    horsCadre: horsCadre,
    positionDepuisPointeur: positionDepuisPointeur,
    aimanter: aimanter,
    reancrer: reancrer,
    // Le décalage commun d'un bloc : c'est LUI qui garantit que les écarts
    // entre les éléments sélectionnés survivent au déplacement.
    bornerDelta: bornerDelta,
    // L'alignement, exposé pour la même raison : c'est un calcul pur, et c'est
    // là que se loge le piège de l'ancrage.
    positionAlignee: positionAlignee,
    aligner: aligner,
    BORDS: BORDS,
    // Les tailles lues dans l'aperçu, et la lecture elle-même. Exposées pour
    // être TESTÉES : `mesurerConteneur` ne touche pas au DOM du panneau (elle
    // reçoit l'hôte et la fenêtre), et `mesures` est l'entrée de `geometrie` —
    // donc de l'alignement, de la répartition et du détecteur de débordement.
    mesures: mesures,
    mesurerConteneur: mesurerConteneur,
    // La rétention et le banc, exposés pour la même raison : ce sont eux qui
    // décident qu'un cadre est juste SANS qu'on ait lancé l'élément, et rien de
    // tout ça ne se voit à l'œil sur une capture d'écran.
    fusionnerMesures: fusionnerMesures,
    mesurerBanc: mesurerBanc,
    // Ce que le GET joint au modèle. Exposé pour être TESTÉ : c'est l'écart
    // entre cette liste et ce que la route ajoute qui faisait poser une
    // question de concurrence à chaque publication.
    HORS_MODELE: HORS_MODELE,
    retirerHorsModele: retirerHorsModele,
    // Le diff avec l'antenne. Exposé pour être TESTÉ, et c'est le seul moyen :
    // ce qu'il OUBLIERAIT de comparer ne se verrait pas en le lisant, mais un
    // soir de live sous la forme d'un réglage parti sans être annoncé.
    // Le filtre de la liste. Exposé pour être TESTÉ : ce qu'il laisse passer se
    // vérifie à l'œil, mais ce que la SIGNATURE en retient ne se voit pas — et
    // une signature qui l'oublie fige la liste sur son état d'avant.
    filtre: filtre,
    passeFiltre: passeFiltre,
    // Le pas de rang. Exposé pour être TESTÉ : sa garde ne se voit pas en le
    // lisant — c'est `normaliserOrdre` qui DÉFAIT le pas quand il sortirait
    // l'élément de son groupe, deux appels plus loin.
    deplacerRang: deplacerRang,
    diffAntenne: diffAntenne,
    diffScene: diffScene,
    decrireElement: decrireElement,
    nomAncrage: nomAncrage,
    flecheAncrage: flecheAncrage,
    // Le sens du survol. Exposé pour être TESTÉ : c'est une règle d'un mot
    // (« surface »), et elle ne se voit sur aucune capture d'écran.
    cotesDuSurvol: cotesDuSurvol,
    // La signature de la liste. Exposée pour être TESTÉE, et c'est le seul
    // moyen : ce qu'elle OUBLIERAIT ne se verrait pas en la lisant, mais des
    // semaines plus tard, sous la forme d'un œil qui refuse de se fermer ou
    // d'un groupe qui garde son ancien nom. Le test dit ce qu'elle doit voir.
    signatureListe: signatureListe,
    tailleRendue: tailleRendue,
    // Le tri du cadenas : c'est lui qui dit que « verrouillé » vaut aussi pour
    // la visibilité, et pas seulement pour la position.
    cibleBascule: cibleBascule,
    repartitionEgale: repartitionEgale,
    repartir: repartir,
    // La propagation d'une scène aux autres. `planPropagation` est pure et
    // décide de TOUT : ce qui est écrasé, ce que le cadenas retient, et le
    // chiffre annoncé dans la confirmation. C'est elle qu'on teste — un
    // décompte faux dans une demande de confirmation est pire que pas de
    // chiffre du tout.
    CHAMPS_PROPAGES: CHAMPS_PROPAGES,
    autresScenes: autresScenes,
    planPropagation: planPropagation,
    appliquerPropagation: appliquerPropagation,
    propager: propager,
    clesScene: clesScene,
    // La remise à zéro. `planReinitialisation` est pure et décide de tout : ce
    // qui revient à l'origine, ce que le cadenas retient, et le chiffre annoncé.
    // `elementsDefaut` dit d'où sortent les valeurs — du SERVEUR, jamais d'une
    // table écrite ici.
    chargerDefauts: chargerDefauts,
    elementsDefaut: elementsDefaut,
    defautsStructure: defautsStructure,
    planReinitialisation: planReinitialisation,
    appliquerReinitialisation: appliquerReinitialisation,
    reinitialiser: reinitialiser,
    // Les groupes. `ordreGroupe` est le miroir de `_ordre_avec_groupes()`
    // (Python) : deux calculs qui doivent rendre le MÊME empilement, sans quoi
    // la liste et l'antenne racontent deux histoires. `boiteEnglobante` est le
    // cadre qu'on voit sur la surface. Les deux sont pures.
    ordreGroupe: ordreGroupe,
    boiteEnglobante: boiteEnglobante,
    groupesScene: groupesScene,
    groupeDe: groupeDe,
    membresPresents: membresPresents,
    retirerDesGroupes: retirerDesGroupes,
    normaliserOrdre: normaliserOrdre,
    creerGroupe: creerGroupe,
    dissoudreGroupe: dissoudreGroupe,
    degrouperSelection: degrouperSelection,
    selectionnerGroupe: selectionnerGroupe,
    retirerDuGroupe: retirerDuGroupe,
    ajouterAuGroupe: ajouterAuGroupe,
    // L'historique du brouillon. Exposé pour être TESTÉ hors navigateur : c'est
    // de l'état pur, et ce qu'on veut vérifier — dix annulations ramènent au
    // départ, une frappe ne vaut qu'un pas — ne se voit pas à l'œil.
    HISTOIRE_PAS: HISTOIRE_PAS,
    histoire: histoire,
    reinitialiserHistoire: reinitialiserHistoire,
    annulerHistoire: annulerHistoire,
    refaireHistoire: refaireHistoire,
    // Le tri d'un fichier importé. Exposé pour être TESTÉ : c'est la garde
    // contre le repli silencieux du serveur, et ce qu'elle REFUSE ne se voit
    // qu'en la confrontant à des fichiers tordus.
    refusImport: refusImport,
    nomExport: nomExport,
    // Le détecteur de chevauchement. Pur, et c'est là que se joue le seul
    // arbitrage qui compte : on ne compare que ce qui COHABITE, et jamais sur
    // une taille supposée — une fausse alerte apprend à ne plus regarder
    // l'alerte.
    CHEVAUCHEMENT_MIN: CHEVAUCHEMENT_MIN,
    cohabite: cohabite,
    surfaceCommune: surfaceCommune,
    analyserChevauchements: analyserChevauchements,
    texteChevauchements: texteChevauchements,
  };
})();
