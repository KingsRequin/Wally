// public-ui/partage/tcg-carte-action.js — le recto des cartes ACTION / PASSIF
//
// Port du recto figé dans le projet Claude Design « Conception plateau TCG
// Wally » (`Carte Tactique.dc.html`, relevé du 2026-09-12). Pendant de
// `tcg-carte.js`, qui rend les HÉROS — et volontairement séparé de lui : un
// héros a quatre couches d'illustration parallaxées, des particules et un
// vitrage holographique ; une carte action a un pochoir et un vernis. Les
// fondre donnerait un composant dont les deux tiers du code ne servent qu'à
// une famille sur deux.
//
// 🚨 Les couleurs de catégorie ne sont PAS ici. Elles arrivent servies par
// `GET /api/public/tcg/cartes-action` (`categorieCouleur`, `categorieIcone`,
// `categorieLabel`). Une table recopiée côté front diverge le jour où une
// teinte bouge, et le bandeau garde l'ancienne pendant que le cadre prend la
// nouvelle — personne ne le voit avant une capture d'écran.

import { h } from './dom.js';

const FEUILLE = '/partage/tcg-carte-action.css';

/** Ce qui s'écrit quand la règle n'est pas arrêtée. Le serveur envoie ce mot
 * tel quel ; il est répété ici pour que la page puisse COMPTER les cartes
 * écrites sans connaître le format du champ. */
export const REGLE_INDEFINIE = 'INDÉFINI';

/** Charge la feuille des cartes action. Rend de quoi la retirer.
 *
 * Appelé par la PAGE et non par la carte : une grille de cinquante cartes ne
 * doit poser le `<link>` qu'une fois.
 */
export function monterStylesCarteAction() {
  if (document.head.querySelector(`link[href="${FEUILLE}"]`)) return () => {};
  const lien = document.createElement('link');
  lien.rel = 'stylesheet';
  lien.href = FEUILLE;
  document.head.appendChild(lien);
  return () => lien.remove();
}

// ── Les dispositions d'illustration ───────────────────────────────────────

/** Le semis : l'icône répétée, en désordre STABLE.
 *
 * 🚨 La graine est fixe et dérivée du nom. Un `Math.random()` redonnerait des
 * positions neuves à chaque repeinture : les dix pizzas sauteraient au moindre
 * changement d'état, et deux captures de la même carte ne se ressembleraient
 * pas.
 *
 * 🚨 La grille se DÉDUIT de `n`, elle n'est pas écrite. Trois colonnes en dur
 * tenaient jusqu'à neuf ; à dix, une quatrième rangée s'ouvrait à y ≈ 120 % et
 * deux icônes allaient se poser hors du cadre. Rien ne rognait, donc rien ne
 * prévenait.
 */
function semisDe(nom, n) {
  let g = 2166136261;
  for (const ch of String(nom)) g = ((g ^ ch.charCodeAt(0)) * 16777619) >>> 0;
  const alea = () => { g = (g * 1664525 + 1013904223) >>> 0; return g / 4294967296; };
  const cols = Math.ceil(Math.sqrt(n));
  const rows = Math.ceil(n / cols);
  const cellH = 100 / rows;
  // La taille suit la densité : dix icônes à la taille de sept se chevauchent,
  // et un semis serré ne se lit plus comme un semis.
  const base = 6 / Math.sqrt(n);
  const out = [];
  for (let i = 0; i < n; i++) {
    const lig = Math.floor(i / cols);
    // La dernière rangée est souvent incomplète — dix sur quatre colonnes en
    // laisse deux. Elles s'étalent sur TOUTE la largeur au lieu de se serrer à
    // gauche, sinon le coin bas-droit reste vide et le désordre se lit comme
    // un oubli.
    const parRangee = Math.min(cols, n - lig * cols);
    const cellW = 100 / parRangee;
    const col = i - lig * cols;
    // Grille SECOUÉE plutôt que tirage libre : au hasard pur les icônes se
    // tassent dans un coin. Les bornes .22/.56 gardent chaque centre dans sa
    // cellule, donc dans le cadre.
    out.push({
      x: `${((col + 0.22 + alea() * 0.56) * cellW).toFixed(1)}%`,
      y: `${((lig + 0.22 + alea() * 0.56) * cellH).toFixed(1)}%`,
      t: `${(base * (0.78 + alea() * 0.46)).toFixed(2)}em`,
      r: `${(alea() * 60 - 30).toFixed(1)}deg`,
    });
  }
  return out;
}

/** L'arc : le contraire du semis. Le semis veut du désordre, l'arc veut une
 * figure. Même taille pour toutes, aucune rotation, la courbe seule fait la
 * composition — c'est ce qui dit « ensemble » là où le semis dit « en vrac ». */
function arcDe(n, taille) {
  const out = [];
  for (let i = 0; i < n; i++) {
    const a = n === 1 ? 0 : (i / (n - 1)) * 2 - 1;
    out.push({
      x: `${(50 + a * 30).toFixed(1)}%`,
      y: `${(44 + a * a * 20).toFixed(1)}%`,
      t: taille,
      r: '0deg',
    });
  }
  return out;
}

function pochoir(url, classe, style) {
  return h('div', {
    class: classe,
    style: `-webkit-mask-image:url('${url}');mask-image:url('${url}');${style || ''}`,
  });
}

/** Ce que la carte montre dans sa fenêtre. UNE disposition et une seule. */
function fenetre(carte, rang) {
  const enfants = [];
  const url = carte.visuel || carte.categorieIcone;

  if (rang > 0) {
    // Une carte numérotée rend son pochoir dans une boîte CARRÉE : le trait de
    // coupe est un angle absolu, la découpe est en %, et les deux ne
    // coïncident que si les deux axes ont la même unité.
    enfants.push(pochoir(url, 'ca-pochoir ca-pochoir--rang'));
    enfants.push(h('div', { class: 'ca-barre' }, h('i', {}), h('i', {})));
    enfants.push(h('div', { class: 'ca-rang' },
      h('b', { text: String(rang) }),
      h('span', { text: `SUR ${carte.groupe}` }),
    ));
  } else if (carte.semis > 0) {
    const points = carte.arc
      ? arcDe(carte.semis, '3.6em')
      : semisDe(carte.nom, carte.semis);
    enfants.push(h('div', { class: 'ca-semis' },
      points.map((p) => pochoir(url, 'ca-pochoir',
        `left:${p.x};top:${p.y};width:${p.t};height:${p.t};--r:${p.r}`)),
    ));
  } else if (carte.texte) {
    enfants.push(h('div', { class: 'ca-motclef', text: carte.texte }));
  } else {
    enfants.push(pochoir(url, 'ca-pochoir'));
  }
  return h('div', { class: 'ca-fenetre' }, enfants);
}

// ── La carte ──────────────────────────────────────────────────────────────

/** Le degré de torsion, en degrés, au bord de la carte.
 *
 * 9° et pas 15° : ces cartes sont RANGÉES EN GRILLE, contrairement aux héros
 * qu'on regarde un par un. Au-delà, les voisines se chevauchent visuellement
 * et la grille se met à onduler quand le curseur la traverse.
 */
const TORSION = 9;

/** Un décalage de traînée dans [-22, 22], dérivé du nom de la carte. */
function phaseDe(cle) {
  let g = 2166136261;
  for (const ch of String(cle)) g = ((g ^ ch.charCodeAt(0)) * 16777619) >>> 0;
  return (g % 4400) / 100 - 22;
}

/** Une carte action ou passive.
 *
 * @param carte  l'objet servi par `GET /api/public/tcg/cartes-action`
 * @param options.rang       exemplaire d'une carte à regrouper (1..groupe), 0 = complète
 * @param options.interactif branche souris et tactile. `false` quand la PAGE
 *                           pilote (gyroscope) — sans quoi les deux se
 *                           disputeraient la même transformation.
 * @returns {{boite, incliner, detruire}} `incliner(x, y)` attend [-0.5, 0.5].
 */
export function carteAction(carte, options = {}) {
  const rang = Number(options.rang) || 0;
  const interactif = options.interactif !== false;
  const indefinie = carte.regle === REGLE_INDEFINIE;
  // 🚨 Le décalage de traînée, propre à chaque carte. Au gyroscope toutes les
  // cartes visibles reçoivent la MÊME inclinaison : sans ce déphasage, les
  // cinquante reflets passent exactement au même endroit au même instant, et
  // la grille clignote d'un bloc comme un seul objet plat. Décalées, elles se
  // lisent comme cinquante cartes posées à plat sous la même lumière.
  // Dérivé du nom, donc STABLE : deux chargements donnent la même carte.
  const phase = phaseDe(carte.nom + rang);

  const carteEl = h('div', {
    class: 'ca',
    'data-type': carte.type,
    style: `--cat:${carte.categorieCouleur}`,
    role: 'group',
    'aria-label': `${carte.nom} — ${carte.type}, ${carte.categorieLabel}`,
  },
    h('div', { class: 'ca-vignette' }),
    h('div', { class: 'ca-tete' },
      // Un coût à 0 n'est pas gratuit, il n'est pas CALIBRÉ (arbitrage de
      // l'owner du 2026-09-12). Afficher « 0 » en pastille d'or affirmerait
      // une valeur que personne n'a décidée — et le site tient justement la
      // ligne inverse : ce qui apparaît ici a été décidé.
      h('span', {
        class: carte.cout > 0 ? 'ca-cout' : 'ca-cout ca-cout--indefini',
        text: carte.cout > 0 ? String(carte.cout) : '—',
        title: carte.cout > 0 ? 'Coût en énergie' : 'Coût pas encore calibré',
      }),
      h('span', { class: 'ca-cat' },
        pochoir(carte.categorieIcone, 'ca-cat-icone'),
        h('span', { class: 'ca-cat-nom', text: carte.categorieLabel }),
      ),
    ),
    fenetre(carte, rang),
    h('div', { class: 'ca-pied' },
      h('div', { class: 'ca-titres' },
        h('div', { class: 'ca-court', text: carte.court }),
        h('div', { class: 'ca-nom', text: carte.nom }),
      ),
      h('p', {
        class: indefinie ? 'ca-regle ca-regle--indefini' : 'ca-regle',
        text: indefinie ? 'Règle pas encore écrite.' : carte.regle,
      }),
      h('div', { class: 'ca-bandeaux' },
        h('span', { class: 'ca-type', text: carte.type === 'passif' ? 'PASSIF' : 'ACTION' }),
        carte.faceCachee ? h('span', { class: 'ca-cachee', text: 'FACE CACHÉE' }) : null,
      ),
    ),
    h('div', { class: 'ca-vernis' }),
    h('div', { class: 'ca-grain' }),
    h('div', { class: 'ca-biseau' }),
  );

  // 🚨 La perspective vit sur le PARENT, jamais sur l'élément qui tourne. Elle
  // est donc posée ici et pas laissée à la page : une page qui oublierait le
  // conteneur rendrait des cartes parfaitement plates — la transformation
  // s'applique, elle n'a simplement plus de profondeur — et rien ne le dirait.
  const boite = h('div', { class: 'ca-scene' }, carteEl);

  /** Tord la carte et déplace le point chaud du vernis.
   *
   * `x` et `y` arrivent dans [-0.5, 0.5] — la course complète d'un curseur
   * passant d'un bord à l'autre. C'est la même convention que `carteHero`,
   * pour qu'une page puisse piloter les deux familles au même gyroscope.
   *
   * ⚠️ Les deux axes sont INVERSÉS l'un par rapport à l'autre : pousser le
   * curseur vers la droite doit faire fuir le bord droit, donc `rotateY`
   * positif ; le pousser vers le bas doit faire fuir le bord bas, donc
   * `rotateX` NÉGATIF. Écrire les deux dans le même sens donne une carte qui
   * se penche à l'envers en vertical, et ça ne se voit qu'en le faisant.
   */
  const incliner = (x, y) => {
    carteEl.style.setProperty('--ry', `${(x * 2 * TORSION).toFixed(2)}deg`);
    carteEl.style.setProperty('--rx', `${(-y * 2 * TORSION).toFixed(2)}deg`);
    // La traînée balaie la carte à contresens de la torsion : on l'incline
    // VERS la lumière, donc le reflet remonte du côté qui s'est relevé.
    // Course volontairement plus large que [0, 100] — la bande doit pouvoir
    // SORTIR du cadre aux deux extrémités, sinon elle s'arrête au bord et on
    // la voit s'écraser au lieu de partir.
    const bande = 50 - (x * 96) - (y * 34) + phase;
    carteEl.style.setProperty('--bande', `${bande.toFixed(1)}%`);
    // Le halo d'ambiance suit le même côté, en beaucoup plus mou.
    carteEl.style.setProperty('--gx', `${(50 - x * 70).toFixed(0)}%`);
    carteEl.style.setProperty('--gy', `${(50 - y * 80).toFixed(0)}%`);
    // L'arête qui remonte, pour le biseau. Bornée à ±1.
    carteEl.style.setProperty('--ex', (-x * 2).toFixed(2));
    carteEl.style.setProperty('--ey', (-y * 2).toFixed(2));
  };

  const reposer = () => {
    carteEl.classList.remove('ca--vif');
    carteEl.style.setProperty('--rx', '0deg');
    carteEl.style.setProperty('--ry', '0deg');
    carteEl.style.setProperty('--gy', '0%');
    carteEl.style.setProperty('--ex', '0');
    carteEl.style.setProperty('--ey', '0');
  };

  const detachements = [];

  if (interactif) {
    // Un seul jeu d'écouteurs pour la souris ET le doigt : `pointermove` porte
    // les deux. Le tactile relâche sur `pointercancel` autant que sur
    // `pointerup` — un défilement qui démarre sur la carte émet le premier, et
    // sans lui la carte resterait tordue.
    const surEntree = () => carteEl.classList.add('ca--vif');
    const surMouvement = (e) => {
      const r = carteEl.getBoundingClientRect();
      if (!r.width || !r.height) return;
      incliner((e.clientX - r.left) / r.width - 0.5, (e.clientY - r.top) / r.height - 0.5);
    };
    carteEl.addEventListener('pointerenter', surEntree);
    carteEl.addEventListener('pointermove', surMouvement);
    carteEl.addEventListener('pointerleave', reposer);
    carteEl.addEventListener('pointercancel', reposer);
    detachements.push(() => {
      carteEl.removeEventListener('pointerenter', surEntree);
      carteEl.removeEventListener('pointermove', surMouvement);
      carteEl.removeEventListener('pointerleave', reposer);
      carteEl.removeEventListener('pointercancel', reposer);
    });
  }

  return {
    boite,
    incliner,
    /** Allume le vernis sans pointeur — pour le pilotage au gyroscope. */
    eveiller: () => carteEl.classList.add('ca--vif'),
    endormir: reposer,
    detruire: () => detachements.forEach((d) => d()),
  };
}
