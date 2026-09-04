// public-ui/pages/tcg-carte.js — le rendu d'UNE carte
//
// Rien ici ne décide de rien : chaque fonction prend un objet déjà écrit dans
// `tcg-demo.js` et rend du DOM. Pas une soustraction de PV, pas un test de
// « l'Ultime est-il jouable ». Le moteur de règles est en Python, côté serveur.
//
// ── L'ANATOMIE, et c'est le point ────────────────────────────────────────
//
// Une carte de TCG, c'est une ILLUSTRATION plein cadre avec les chiffres POSÉS
// DESSUS. Pas un rectangle de texte avec une image au-dessus : la première
// version de ce fichier rendait des tuiles de statistiques, et un jeu de cartes
// sans cartes perd son sens.
//
//   ┌──────────────┐
//   │ ⑦        ◈3  │   coût de l'Ultime · Aura
//   │              │
//   │ ILLUSTRATION │   plein cadre, ratio 5:7 (63 × 88 mm, la carte physique)
//   │              │
//   │ ░░ NOM ░░░░░ │   bandeau dégradé, pour que le nom reste lisible
//   │ ⚔6        ♥3 │   Attaque · PV
//   └──────────────┘
//
// 🚨 Les illustrations n'existent pas encore. Le fond de remplacement occupe
// donc EXACTEMENT la place qu'elles prendront : le jour où `illustration` porte
// une URL, seule cette propriété change et rien ne bouge dans la mise en page.
// Un remplaçant plus petit que l'image finale mentirait sur le rendu.
//
// Une seule anatomie pour les deux tailles : la grande carte AJOUTE un
// cartouche (texte d'Ultime, rareté, affinités), elle ne se redessine pas.
// Deux rendus concurrents du même héros divergeraient au premier changement.

import { h } from '../app.js';
import { HEROS, TACTIQUES } from './tcg-demo.js';

const RARETES = {
  ame: 'Âme', fidele: 'Fidèle', 'ame-promise': 'Âme Promise',
  elu: 'Élu', ange: 'Ange', archange: 'Archange',
};

const FACTIONS = { lumineuse: 'Lumineuse', sombre: 'Sombre' };

/** L'illustration, ou sa place en attendant.
 *
 *  L'URL est posée par `style.backgroundImage` et non par une chaîne CSS
 *  concaténée : un chemin de fichier peut contenir des caractères qui referment
 *  la déclaration. Le site a déjà payé ça une fois, avec un nom de son qui
 *  exécutait un `onclick`. */
function art(sujet) {
  const boite = h('div', { class: 'tcg-art', 'aria-hidden': 'true' },
    h('span', { class: 'tcg-art-ph', text: sujet.nom.slice(0, 1).toUpperCase() }));
  if (sujet.illustration) {
    boite.style.backgroundImage = `url("${encodeURI(sujet.illustration)}")`;
    boite.classList.add('a-illu');
  }
  return boite;
}

/** Une pastille de chiffre, posée SUR l'illustration. */
function pip(genre, valeur, titre) {
  return h('span', { class: `tcg-pip tcg-pip--${genre}`, title: titre },
    h('b', { text: String(valeur) }));
}

/** Le squelette commun : cadre, illustration, pied (nom puis cartouche).
 *
 *  Le nom et le cartouche sont EMPILÉS dans un même pied, et pas posés
 *  chacun en absolu au bas de la carte : le cartouche, ajouté après dans le
 *  DOM et opaque, recouvrait purement et simplement le nom du héros. */
function coquille(balise, classes, sujet, attrs, cartouche) {
  return h(balise, { class: `tcg-carte ${classes}`, ...attrs },
    art(sujet),
    h('div', { class: 'tcg-pied' },
      h('div', { class: 'tcg-bandeau' },
        h('span', { class: 'tcg-nom', text: sujet.nom })),
      cartouche),
  );
}

/**
 * Un héros. `entree` vient d'un état figé :
 * `{ id, pv, degats, ultime, tombe, nouveau }`.
 *
 * `grande` ajoute le cartouche ; elle ne change ni le cadre, ni la place de
 * l'illustration, ni celle des pastilles.
 */
export function carteHeros(entree, { grande = false, surClic = null } = {}) {
  const hero = HEROS[entree.id];
  const pv = entree.pv === null || entree.pv === undefined ? hero.pv : entree.pv;
  const entame = hero.pv !== null && pv < hero.pv;

  const cartouche = grande ? h('div', { class: 'tcg-cartouche' },
    h('div', { class: 'tcg-cart-meta mono' },
      [RARETES[hero.rarete], FACTIONS[hero.faction] || 'Sans faction'].join(' · ')),
    hero.trait ? h('p', { class: 'tcg-cart-trait', text: hero.trait }) : null,
    h('div', { class: 'tcg-cart-titre' },
      h('span', { class: 'tcg-cart-tag mono', text: 'ULTIME' }),
      h('span', { text: hero.ultime.nom })),
    h('p', { class: 'tcg-cart-texte', text: hero.ultime.texte }),
    h('div', { class: 'tcg-affs' },
      ...hero.affinites.map((a) => h('span', { class: 'tcg-aff mono', text: a }))),
  ) : null;

  const carte = coquille(surClic ? 'button' : 'article',
    `tcg-r--${hero.rarete} tcg-f--${hero.faction || 'neutre'}`
    + (grande ? ' tcg-carte--grande' : '')
    + (entree.tombe ? ' est-tombe' : '')
    + (entree.ultime ? ' est-ultime' : '')
    + (entree.nouveau ? ' est-nouveau' : ''),
    hero,
    surClic
      ? { type: 'button', 'aria-label': `${hero.nom} — ${pv} points de vie sur ${hero.pv}. Voir la carte.` }
      : {},
    cartouche);

  carte.appendChild(pip('cout', hero.ultime.cout, `Ultime : ${hero.ultime.cout} d'énergie`));
  carte.appendChild(pip('aura', hero.aura, 'Aura'));
  carte.appendChild(pip('atk', hero.atk, 'Attaque'));
  carte.appendChild(pip('pv' + (entame ? ' est-entame' : ''),
    hero.pv === null ? hero.pvLibelle : pv, 'Points de vie'));

  if (entree.degats) carte.appendChild(h('span', { class: 'tcg-degats', text: `−${entree.degats}` }));
  if (entree.tombe) carte.appendChild(h('span', { class: 'tcg-sceau mono est-chute', text: 'CHUTE' }));
  if (entree.nouveau) carte.appendChild(h('span', { class: 'tcg-sceau mono est-entre', text: 'ENTRE' }));

  if (surClic) carte.addEventListener('click', () => surClic('heros', entree.id));
  return carte;
}

/** Une tactique. Même anatomie : elle n'a pas de stats, elle a un coût. */
export function carteTactique(id, { grande = false, surClic = null } = {}) {
  const t = TACTIQUES[id];
  const carte = coquille(surClic ? 'button' : 'article',
    `tcg-carte--tac tcg-tac--${t.type}` + (grande ? ' tcg-carte--grande' : ''),
    t,
    surClic ? { type: 'button', 'aria-label': `${t.nom}, ${t.cout} d'énergie. Voir la carte.` } : {},
    // Le texte est toujours là ; il n'apparaît que là où il y a la place
    // (grande carte, ou main sur grand écran).
    h('div', { class: 'tcg-cartouche' },
      h('p', { class: 'tcg-cart-texte', text: t.texte })));

  carte.appendChild(pip('cout', t.cout, `${t.cout} d'énergie`));
  carte.appendChild(h('span', { class: 'tcg-type mono', text: t.type === 'passif' ? 'PASSIF' : 'TACTIQUE' }));

  if (surClic) carte.addEventListener('click', () => surClic('tactique', id));
  return carte;
}

/** Un dos de carte : ce que l'adversaire ne montre pas. Même ratio. */
export function dosCarte(petit) {
  return h('div', {
    class: 'tcg-carte tcg-dos' + (petit ? ' tcg-dos--petit' : ''),
    'aria-hidden': 'true',
  });
}
