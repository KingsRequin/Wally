// bot/dashboard/static/overlay_tcg.js — la carte du TCG sur l'overlay
//
// Le RENDU d'une carte n'est pas ici : il vit dans `/partage/tcg-carte.js`,
// partagé avec le site public. Ce module ne fait que la faire ENTRER, la
// tourner et la faire sortir. Deux rendus divergeraient au premier réglage, et
// la carte montrée aux viewers ne serait plus celle du site.
//
// ⚠️ L'import traverse deux surfaces : cette page est servie depuis `/static/`
// et `partage/` depuis `/`. C'est la même origine, donc un import absolu
// fonctionne — mais il ne faut RIEN importer d'autre du site public, surtout
// pas `app.js`, qui tirerait Lenis, le routeur d'historique et les flux SSE.
import {
  abonnerAnimation, carteHero, monterStylesCarte,
} from '/partage/tcg-carte.js';

// Les trois temps fixes de la chorégraphie, en SECONDES et non en fractions :
// l'entrée et la sortie doivent durer pareil que la carte reste 5 s ou 20 s à
// l'écran. Seule la rotation s'étire pour occuper ce qui reste.
const ENTREE_S = 0.6;
const OUVERTURE_S = 0.8;
// 🚨 Le REPLI est un temps à part entière, et non la première moitié de la
// sortie. Replier la 3D et lancer le fondu dans le même geste faisait partir
// la carte PENDANT que ses couches se remettaient à plat : les cadres
// s'éteignaient, le héros rentrait dans son cadre et l'opacité tombait tous
// ensemble — ça se lisait comme un défaut d'affichage, pas comme une sortie.
//
// 1,2 s : le dépliage dure 0,85 s plus 0,27 s d'échelonnement, et le repli
// doit pouvoir le rejouer à l'envers en entier. Avant cet allongement,
// 0,9 s suffisait — mesuré, la carte n'est réellement À PLAT qu'après le
// minuteur d'aplatissement du composant — 0,52 s après `fermer()`, le temps
// que les Z reviennent à zéro (retirer la perspective avant se verrait). À
// 0,7 s il ne restait que 180 ms de marge avant le fondu ; sous une machine
// chargée, les deux se chevauchaient de nouveau.
const REPLI_S = 1.2;
const SORTIE_S = 0.9;
const FIXE_S = ENTREE_S + OUVERTURE_S + REPLI_S + SORTIE_S;

// Quatre cinquièmes de la course d'un curseur, soit ±12° d'inclinaison à
// intensité 1. On était parti sur la moitié en lisant « tourne légèrement »,
// mais à l'écran la torsion ne se voyait pas — et pour une bonne part parce
// que la transition du plateau écrasait l'amplitude d'un facteur DIX-NEUF
// (cf. le commentaire de `entrer()` dans `partage/tcg-carte.js`). Le lissage
// corrigé, il restait à rapprocher l'effet de celui du survol sur le site.
//
// Pas la course entière : au maximum, la carte bascule comme sous une souris
// qui balaie, et ça se lit comme un défaut d'animation.
const AMPLITUDE = 0.4;

// 340 px CSS × 2 = 680 px sur un canvas de 1920, rendu en DPR 1 : exactement
// la résolution pour laquelle les illustrations sont générées (340 CSS × DPR 2,
// cf. `scripts/generer_illustrations_tcg.py`).
//
// 🚨 Passer à 3 rendrait TOUTES les cartes floues, sans que rien ne le
// signale. La valeur ne se change pas sans régénérer les illustrations.
const ECHELLE = 2;

// Une carte qui apparaît pendant son propre décodage joue ses phases sur une
// image absente. On attend — mais avec un PLAFOND : un `decode()` qui
// n'aboutit jamais (illustration manquante, réseau coupé) transformerait une
// précaution en panne silencieuse.
// 🚨 400 ms, et surtout : on n'attend RIEN quand les illustrations sont déjà
// chargées — ce qui est le cas normal, `overlay.js` les mettant en cache au
// boot.
//
// Ce plafond a été à 2 s, puis 5. C'était l'erreur : Wally s'efface dès que le
// widget est monté, donc chaque seconde d'attente est une seconde d'écran VIDE
// devant les viewers. L'owner voyait « Wally disparaît, la carte apparaît
// cinq secondes après » — exactement la valeur du plafond. Attendre une image
// qui ne vient pas coûte plus cher que l'afficher une demi-seconde plus tard.
const PLAFOND_DECODE_MS = 400;

let _styles = null;

/** Charge la feuille de la carte une fois pour la vie de l'overlay.
 *
 * Au BOOT et non à l'affichage : une feuille qui arrive en même temps que la
 * carte la ferait apparaître non stylée pendant une image ou deux, devant les
 * viewers.
 */
export function preparerCarte() {
  if (!_styles) _styles = monterStylesCarte();
}

/** Attend que les illustrations soient décodées, sans dépasser le plafond.
 *
 * ⚠️ À n'appeler que sur un nœud DÉJÀ inséré dans le document : hors DOM, une
 * image ne charge pas (et pas du tout si elle est `lazy`), donc `decode()` ne
 * peut pas aboutir. C'est pour ça que `demarrer()` existe.
 */
async function attendreImages(noeud) {
  const images = [...noeud.querySelectorAll('img')];
  // Le chemin normal : tout est déjà en cache, on ne rend pas la main au
  // navigateur pour rien. `complete` est vrai dès que les octets sont là ; le
  // décodage d'une image en cache tient dans la même image d'animation.
  const enAttente = images.filter((i) => !i.complete || !i.naturalWidth);
  if (!enAttente.length) return;

  console.warn(`[carte] ${enAttente.length} illustration(s) pas encore prête(s) — `
               + `attente plafonnée à ${PLAFOND_DECODE_MS} ms`,
               enAttente.map((i) => i.currentSrc || i.src));
  await Promise.race([
    Promise.all(enAttente.map((i) => i.decode().catch((e) => {
      // Une image qui refuse de se décoder n'empêche pas les autres : la carte
      // s'affiche amputée plutôt que pas du tout, et la trace dit laquelle.
      console.warn('[carte] illustration non décodée', i.currentSrc, e);
    }))),
    new Promise((r) => setTimeout(r, PLAFOND_DECODE_MS)),
  ]);
}

/** Monte une carte. Rend `{ noeud, demarrer, arreter }`.
 *
 * 🚨 `demarrer()` est appelé par l'appelant APRÈS avoir inséré `noeud` dans le
 * document, et jamais avant : la chorégraphie commence par attendre le
 * décodage des illustrations, ce qui n'aboutit pas sur un nœud détaché.
 *
 * `params` porte la carte entière, telle que le bus l'a envoyée, plus la durée
 * totale en secondes.
 *
 * Les quatre temps :
 *   1. elle arrive À PLAT, en fondu — c'est l'état de repos du composant ;
 *   2. `ouvrir()` : les couches se séparent, exactement comme au survol ;
 *   3. `incliner()` sur une trajectoire lente en huit — la rotation parallaxe ;
 *   4. `fermer()`, puis retrait.
 */
export function carteOverlay(params) {
  preparerCarte();

  // `interactif: false` : l'overlay n'a ni curseur ni doigt. Sans ça, le
  // composant brancherait des écouteurs de pointeur qui ne serviraient jamais.
  const { boite, detruire, ouvrir, fermer, incliner } = carteHero(params, {
    interactif: false,
    // Le reflet des quatre bords est réglé pour une carte de galerie, à
    // 340 px. Ici elle en fait 680, seule à l'écran : sans ce gain, l'éclat
    // qui suit la lumière ne se voit pas.
    gainReflet: 1.6,
    // Le dépliage est le spectacle ici : personne ne pointe la carte, elle se
    // présente. Sous le curseur on veut l'inverse — une réponse immédiate —
    // d'où les valeurs par défaut, plus courtes, dans la feuille du composant.
    depli: '.85s',
    etape: '.09s',
  });
  boite.style.setProperty('--chero-k', String(ECHELLE));
  // Le dépliage est le spectacle ici : personne ne pointe la carte, elle se
  // présente. Sous le curseur on veut l'inverse — une réponse immédiate —
  // d'où les valeurs par défaut, plus courtes, dans la feuille du composant.

  const noeud = document.createElement('div');
  noeud.className = 'tcg-carte-scene';
  noeud.appendChild(boite);

  let desabonner = null;
  let minuteurs = [];
  const plusTard = (fn, ms) => { minuteurs.push(setTimeout(fn, ms)); };

  const arreter = () => {
    minuteurs.forEach(clearTimeout);
    minuteurs = [];
    if (desabonner) { desabonner(); desabonner = null; }
    detruire();
  };

  const jouer = async () => {
    await attendreImages(noeud);

    // La durée vient du RÉGLAGE du widget, jamais d'une constante d'ici :
    // `duree = 0` vaut « auto, le serveur décide », et `showWidget` a déjà
    // tranché avant de nous appeler.
    const totale = Math.max(FIXE_S + 0.4, Number(params.duration) || 9);
    // Ce qui reste pour tourner, une fois l'entrée, l'ouverture et la sortie
    // prélevées. Le plancher ci-dessus garantit que ce reste est positif :
    // sans lui, une durée réglée sous 2,2 s ferait tourner la carte À REBOURS.
    const rotationS = totale - FIXE_S;

    noeud.classList.add('tcg-carte-entre');

    plusTard(() => {
      ouvrir();
      const depart = performance.now();
      // Une Lissajous 2:1 : la carte revient à son point de départ sans
      // à-coup, et les deux axes ne s'inversent jamais en même temps — c'est
      // ce qui donne un mouvement de présentation plutôt qu'un balayage.
      desabonner = abonnerAnimation((maintenant) => {
        const t = ((maintenant - depart) / 1000 / rotationS) * Math.PI * 2;
        incliner(AMPLITUDE * Math.sin(t), AMPLITUDE * Math.sin(2 * t) * 0.6);
      });
    }, ENTREE_S * 1000);

    // Le repli : la carte revient À PLAT, et rien d'autre. Elle reste
    // pleinement visible pendant ce temps — c'est le geste inverse de
    // l'ouverture, et il doit se lire comme tel.
    plusTard(() => {
      if (desabonner) { desabonner(); desabonner = null; }
      // Revenir au centre AVANT de fermer : sinon la carte se replie en
      // biais, depuis l'angle où la trajectoire l'a laissée.
      incliner(0, 0);
      fermer();
    }, (totale - SORTIE_S - REPLI_S) * 1000);

    // Puis seulement, la disparition — sur une carte déjà à plat.
    plusTard(() => {
      noeud.classList.remove('tcg-carte-entre');
      noeud.classList.add('tcg-carte-sort');
    }, (totale - SORTIE_S) * 1000);
  };

  return { noeud, demarrer: jouer, arreter };
}
