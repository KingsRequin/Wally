// public-ui/pages/tcg-carte.js — le rendu d'UNE carte
//
// Rien ici ne décide de rien : chaque fonction prend un objet déjà écrit dans
// `tcg-demo.js` et rend du DOM. Pas une soustraction de PV, pas un test de
// « l'Ultime est-il jouable ». Le moteur de règles est en Python, côté serveur.
//
// Deux tailles, et c'est un choix de fond, pas du responsive :
//
//   · la VIGNETTE tient à 3 par ligne sur 390 px de large, soit ~112 px. À
//     cette taille il y a la place pour un portrait, un nom et trois chiffres.
//     Pas pour un texte d'Ultime.
//   · la CARTE PLEINE porte tout le reste, et s'ouvre au tap sur la vignette.
//
// Sur grand écran la vignette grandit et son bloc Ultime se démasque — le
// contenu est TOUJOURS dans le DOM, seul le CSS décide de le montrer. Deux
// rendus concurrents du même héros divergeraient au premier changement.

import { h } from '../app.js';
import { HEROS, TACTIQUES } from './tcg-demo.js';

const RARETES = {
  ame: 'Âme', fidele: 'Fidèle', 'ame-promise': 'Âme Promise',
  elu: 'Élu', ange: 'Ange', archange: 'Archange',
};

const FACTIONS = { lumineuse: 'Lumineuse', sombre: 'Sombre' };

/** Le portrait — il n'y a aucune illustration, donc l'initiale sur un aplat.
 *
 *  La teinte vient de la FACTION via une classe, jamais d'une couleur écrite
 *  dans ce fichier : les tokens du thème braise vivent dans `:root`. */
function portrait(hero) {
  return h('div', { class: `tcg-por tcg-f--${hero.faction || 'neutre'}`, 'aria-hidden': 'true' },
    h('span', { text: hero.nom.slice(0, 1).toUpperCase() }));
}

/** Ce qu'on écrit dans la case PV.
 *
 *  Un héros dont les PV dérivent du nombre de joueurs (Wally, en coopératif)
 *  porte un LIBELLÉ au lieu d'un nombre : sa fiche ne doit pas afficher un
 *  chiffre qui aurait l'air calculé alors qu'il ne l'est pas. */
function pvMax(hero, pvRestants) {
  if (hero.pv === null) return hero.pvLibelle;
  return pvRestants === null ? String(hero.pv) : `${pvRestants}/${hero.pv}`;
}

/** Les trois chiffres, dans l'ordre ATK · PV · Aura partout. */
function stats(hero, pvRestants) {
  return h('div', { class: 'tcg-stats' },
    h('span', { class: 'tcg-s tcg-s--atk', title: 'Attaque' },
      h('i', { 'aria-hidden': 'true', text: '⚔' }), h('b', { text: String(hero.atk) })),
    h('span', { class: 'tcg-s tcg-s--pv', title: 'Points de vie' },
      h('i', { 'aria-hidden': 'true', text: '♥' }),
      h('b', { text: pvMax(hero, pvRestants) })),
    h('span', { class: 'tcg-s tcg-s--aura', title: 'Aura' },
      h('i', { 'aria-hidden': 'true', text: '◈' }), h('b', { text: String(hero.aura) })),
  );
}

/**
 * La carte telle qu'elle apparaît EN LIGNE sur le plateau.
 *
 * `entree` vient d'un état figé : `{ id, pv, degats, ultime, tombe, nouveau }`.
 * La barre de vie est un simple pourcentage `pv / pv_max` — c'est une règle de
 * trois d'affichage, pas une règle de jeu : aucun des deux nombres n'est
 * calculé ici, les deux sont écrits dans la démo.
 */
export function vignette(entree, surOuverture) {
  const hero = HEROS[entree.id];
  const part = Math.max(0, Math.min(100, Math.round((entree.pv / hero.pv) * 100)));

  const carte = h('button', {
    class: `tcg-vig tcg-r--${hero.rarete}`
      + (entree.tombe ? ' est-tombe' : '')
      + (entree.ultime ? ' est-ultime' : '')
      + (entree.nouveau ? ' est-nouveau' : ''),
    type: 'button',
    'aria-label': `${hero.nom} — ${entree.pv} points de vie sur ${hero.pv}. Voir la carte.`,
  },
    portrait(hero),
    h('div', { class: 'tcg-vig-nom', text: hero.nom }),
    stats(hero, entree.pv),
    h('div', { class: 'tcg-jauge', 'aria-hidden': 'true' },
      h('i', { style: `width:${part}%` })),
    // Démasqué par le CSS à partir de 900 px : la place existe, autant s'en
    // servir plutôt que d'obliger à ouvrir la carte.
    h('div', { class: 'tcg-vig-ult' },
      h('span', { class: 'tcg-cout', text: String(hero.ultime.cout) }),
      h('span', { text: hero.ultime.nom })),
    // Les dégâts encaissés CE tour-ci, tels que l'état les déclare.
    entree.degats ? h('span', { class: 'tcg-degats', text: `−${entree.degats}` }) : null,
    entree.tombe ? h('span', { class: 'tcg-chute mono', text: 'CHUTE' }) : null,
    entree.nouveau ? h('span', { class: 'tcg-entre mono', text: 'ENTRE' }) : null,
  );
  carte.addEventListener('click', () => surOuverture(entree.id));
  return carte;
}

/** La carte pleine — tout ce que la vignette ne peut pas porter. */
export function carteHeros(id) {
  const hero = HEROS[id];
  return h('article', { class: `tcg-pleine tcg-r--${hero.rarete}` },
    h('div', { class: 'tcg-pleine-haut' },
      portrait(hero),
      h('div', {},
        h('div', { class: 'tcg-pleine-nom', text: hero.nom }),
        h('div', { class: 'tcg-pleine-meta mono' },
          [RARETES[hero.rarete], FACTIONS[hero.faction] || 'Sans faction'].join(' · ')),
      ),
    ),
    hero.trait ? h('p', { class: 'tcg-pleine-trait', text: hero.trait }) : null,
    stats(hero, null),
    h('div', { class: 'tcg-ult' },
      h('div', { class: 'tcg-ult-titre' },
        h('span', { class: 'tcg-cout', text: String(hero.ultime.cout) }),
        h('span', { text: hero.ultime.nom }),
        h('span', { class: 'tcg-ult-tag mono', text: 'ULTIME' })),
      h('p', { class: 'tcg-ult-texte', text: hero.ultime.texte }),
    ),
    h('div', { class: 'tcg-affs' },
      ...hero.affinites.map((a) => h('span', { class: 'tcg-aff mono', text: a }))),
  );
}

/** Une tactique de la main : coût, type, effet. Elle n'a pas de stats. */
export function carteTactique(id) {
  const t = TACTIQUES[id];
  return h('div', { class: `tcg-tac tcg-tac--${t.type}` },
    h('div', { class: 'tcg-tac-haut' },
      h('span', { class: 'tcg-cout', text: String(t.cout) }),
      h('span', { class: 'tcg-tac-type mono', text: t.type === 'passif' ? 'PASSIF' : 'TACTIQUE' })),
    h('div', { class: 'tcg-tac-nom', text: t.nom }),
    h('p', { class: 'tcg-tac-texte', text: t.texte }),
  );
}

/** Un dos de carte : ce que l'adversaire ne montre pas. */
export function dosCarte(petit) {
  return h('div', {
    class: 'tcg-dos' + (petit ? ' tcg-dos--petit' : ''),
    'aria-hidden': 'true',
  });
}
