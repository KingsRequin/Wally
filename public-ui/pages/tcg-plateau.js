// public-ui/pages/tcg-plateau.js — le plateau, en états figés
//
// 🚨 Ce module ne calcule RIEN. Il lit un objet de `tcg-demo.js` et le dessine.
// Passer au tour suivant, c'est incrémenter un index dans un tableau — pas
// résoudre un tour. Le moteur de règles vit côté serveur, en Python : une règle
// écrite ici serait une porte de triche et un second jeu à maintenir.
//
// Le seul « calcul » du fichier est un pourcentage de largeur de barre, à
// partir de deux nombres tous les deux écrits dans la démo.
//
// Quatre dispositions à tenir, et elles ne se déduisent pas les unes des
// autres : 1v1, 2v2, 3v3 et le coopératif, qui est ASYMÉTRIQUE — Wally seul
// d'un côté, N joueurs de deux héros de l'autre, groupés par joueur pour que
// l'Aura qui traverse les joueurs se voie.

import { h } from '../app.js';
import { FORMATS, HEROS, REGLES, TACTIQUES } from './tcg-demo.js';
import { carteHeros, carteTactique, dosCarte } from './tcg-carte.js';

// Le format d'entrée : celui sur lequel les règles sont écrites.
const DEFAUT = FORMATS.find((f) => f.cle === '3v3');

let _format = DEFAUT;
let _index = 0;
let _table = null;
let _journal = null;
let _resume = null;
let _pos = null;
let _prec = null;
let _suiv = null;
let _feuille = null;
let _feuilleCorps = null;
let _pills = null;

/** La jauge d'énergie : douze pastilles, parce que le plafond EST la règle.
 *
 *  Une barre continue dirait « il en a beaucoup » ; ce qu'on veut lire, c'est
 *  « il en a 7 sur 12, l'Ultime en coûte 10 ». Le plafond n'est pas un détail
 *  d'affichage : sans lui la stratégie optimale serait de ne rien faire. */
function energie(valeur) {
  const pastilles = h('span', { class: 'tcg-nrj-pas', 'aria-hidden': 'true' });
  for (let i = 0; i < REGLES.energieMax; i += 1) {
    pastilles.appendChild(h('i', { class: i < valeur ? 'plein' : '' }));
  }
  return h('div', {
    class: 'tcg-nrj',
    role: 'img',
    'aria-label': `${valeur} énergie sur ${REGLES.energieMax}`,
  },
    pastilles,
    h('span', { class: 'tcg-nrj-n mono', text: `${valeur}/${REGLES.energieMax}` }),
  );
}

/** Réserve et main : un tableau est révélé, un nombre reste face cachée.
 *
 *  `null` veut dire « cette notion n'existe pas dans ce format » — en
 *  coopératif il n'y a pas de réserve, et une étiquette « RÉSERVE — » sur
 *  chaque joueur ne serait que du bruit. Un tableau VIDE, lui, dit « il n'en
 *  reste plus », ce qui est une information de partie : les deux se
 *  distinguent, et c'est la donnée qui tranche.  */
function pioche(contenu, etiquette) {
  if (contenu === null) return null;
  const boite = h('div', { class: 'tcg-pioche' },
    h('span', { class: 'tcg-pioche-lbl mono', text: etiquette }));
  if (Array.isArray(contenu)) {
    if (!contenu.length) boite.appendChild(h('span', { class: 'tcg-pioche-vide mono', text: '—' }));
    contenu.forEach((id) => boite.appendChild(
      h('span', { class: 'tcg-puce', text: HEROS[id].nom })));
  } else {
    for (let i = 0; i < contenu; i += 1) boite.appendChild(dosCarte(true));
    if (!contenu) boite.appendChild(h('span', { class: 'tcg-pioche-vide mono', text: '—' }));
  }
  return boite;
}

function groupe(g, n, ouvrir) {
  const ligne = h('div', { class: 'tcg-ligne' },
    ...g.heros.map((e) => carteHeros(e, { surClic: ouvrir })));

  // `data-n` vit sur le GROUPE et la ligne en hérite : la tête (énergie,
  // réserve) doit tenir la même largeur que les cartes, sinon elle flotte à
  // gauche d'une ligne centrée.
  return h('div', { class: 'tcg-groupe', 'data-n': String(n) },
    h('div', { class: 'tcg-groupe-tete' },
      g.nom ? h('span', { class: 'tcg-groupe-nom', text: g.nom }) : null,
      energie(g.energie),
      pioche(g.reserve, 'RÉSERVE'),
    ),
    ligne,
  );
}

/** Le boss du mode coopératif : une seule carte, et une barre de PV large. */
function boss(camp, ouvrir) {
  const b = camp.boss;
  const part = Math.max(0, Math.min(100, Math.round((b.pv / b.pvMax) * 100)));
  // La carte du boss est une carte comme les autres — c'en est une. Ce qui
  // lui est propre, c'est la barre de PV : les siens ne sont pas une stat de
  // carte, ils dérivent du nombre de joueurs.
  return h('div', { class: 'tcg-boss' + (b.ultime ? ' est-ultime' : '') },
    carteHeros({ id: b.id, pv: null, degats: b.degats, ultime: b.ultime },
      { surClic: ouvrir }),
    h('div', { class: 'tcg-boss-vie' },
      h('div', { class: 'tcg-boss-pv mono', text: `${b.pv} / ${b.pvMax} PV` }),
      h('div', { class: 'tcg-jauge tcg-jauge--boss', 'aria-hidden': 'true' },
        h('i', { style: `width:${part}%` })),
      b.ultime ? h('span', { class: 'tcg-sceau mono est-triche', text: 'IL TRICHE' }) : null,
    ),
  );
}

function cote(camp, n, ou, ouvrir) {
  const bloc = h('div', { class: `tcg-cote tcg-cote--${ou}` },
    h('div', { class: 'tcg-cote-nom mono', text: camp.nom }));
  if (camp.boss) {
    bloc.appendChild(boss(camp, ouvrir));
  } else {
    bloc.appendChild(h('div', { class: 'tcg-groupes' },
      ...camp.groupes.map((g) => groupe(g, n, ouvrir))));
  }
  return bloc;
}

/** La main : un rail qui défile HORIZONTALEMENT, dans son propre conteneur.
 *
 *  Cinq tactiques à plat sur 390 px n'existent pas. Le débordement reste
 *  enfermé ici — la page, elle, ne glisse pas d'un pixel. */
function main(camp) {
  const revelees = camp.groupes.filter((g) => Array.isArray(g.main));
  if (!revelees.length) return null;
  const rail = h('div', { class: 'tcg-main-rail' });
  let n = 0;
  revelees.forEach((g) => g.main.forEach((id) => {
    rail.appendChild(carteTactique(id, { surClic: ouvrirFeuille }));
    n += 1;
  }));
  // Le COMPTE dans le libellé, et pas seulement un fondu au bord : sur
  // téléphone deux cartes sur trois sont hors champ, et un rail sans barre de
  // défilement ne dit rien de ce qu'il cache. Même piège que les onglets du
  // haut, qui coupaient « TCG » en « T » sans que rien ne l'annonce.
  return h('div', { class: 'tcg-main' },
    h('div', { class: 'tcg-main-lbl mono', text: `TA MAIN · ${n} CARTE${n > 1 ? 'S' : ''}` }),
    rail);
}

function ouvrirFeuille(type, id) {
  const nom = type === 'heros' ? HEROS[id].nom : TACTIQUES[id].nom;
  _feuilleCorps.textContent = '';
  _feuilleCorps.appendChild(type === 'heros'
    ? carteHeros({ id, pv: null }, { grande: true })
    : carteTactique(id, { grande: true }));
  // Sans ce libellé, un lecteur d'écran annonce « boîte de dialogue » et rien
  // d'autre : la carte qu'on vient d'ouvrir n'a pas de nom.
  _feuille.setAttribute('aria-label', `Carte de ${nom}`);
  _feuille.showModal();
}

function rendreEtat() {
  const etat = _format.etats[_index];
  // Le nombre de colonnes vient des DONNÉES, jamais d'un « 3 » écrit en dur.
  // Le MAXIMUM sur les groupes, et pas la longueur du premier : en coopératif
  // un joueur qui a perdu un héros n'en a plus qu'un, et lire ce 1 mettait
  // toutes les lignes sur une colonne — le plateau passait de 950 à 1 270 px
  // de haut sur téléphone, au moment précis où il devait rester lisible.
  const n = Math.max(...etat.bas.groupes.map((g) => g.heros.length));

  _table.textContent = '';
  _table.setAttribute('data-format', _format.cle);
  _table.appendChild(cote(etat.haut, n, 'haut', ouvrirFeuille));
  _table.appendChild(h('div', { class: 'tcg-bande' },
    h('span', { class: 'tcg-de mono', title: 'Tirage du tour — un seul dé, public, avant la pose' },
      h('i', { 'aria-hidden': 'true', text: '⚄' }), String(etat.tirage)),
    h('p', { class: 'tcg-note', text: etat.note }),
  ));
  _table.appendChild(cote(etat.bas, n, 'bas', ouvrirFeuille));
  const m = main(etat.bas);
  if (m) _table.appendChild(m);

  _journal.textContent = '';
  etat.journal.forEach((l) => _journal.appendChild(h('li', { text: l })));

  _pos.textContent = `Tour ${etat.tour} · ${_index + 1} / ${_format.etats.length}`;
  _prec.disabled = _index === 0;
  _suiv.disabled = _index === _format.etats.length - 1;
  _resume.textContent = _format.resume;
}

function changerFormat(f) {
  _format = f;
  _index = 0;
  _pills.querySelectorAll('.pill').forEach((b) => {
    b.classList.toggle('active', b.dataset.cle === f.cle);
  });
  rendreEtat();
}

/** Monte la section « Aperçu du plateau » et rend le premier état. */
export function plateau() {
  _pills = h('div', { class: 'tcg-formats' });
  FORMATS.forEach((f) => {
    const b = h('button', {
      class: 'pill' + (f.cle === _format.cle ? ' active' : ''),
      type: 'button',
      'data-cle': f.cle,
      text: f.libelle,
    });
    b.addEventListener('click', () => changerFormat(f));
    _pills.appendChild(b);
  });

  _resume = h('p', { class: 'tcg-resume' });
  _table = h('div', { class: 'tcg-table' });
  _journal = h('ol', { class: 'tcg-journal' });

  _prec = h('button', { class: 'tcg-fleche', type: 'button', 'aria-label': 'Tour précédent', text: '◀' });
  _suiv = h('button', { class: 'tcg-fleche', type: 'button', 'aria-label': 'Tour suivant', text: '▶' });
  _pos = h('span', { class: 'tcg-pos mono' });
  _prec.addEventListener('click', () => { if (_index > 0) { _index -= 1; rendreEtat(); } });
  _suiv.addEventListener('click', () => {
    if (_index < _format.etats.length - 1) { _index += 1; rendreEtat(); }
  });

  _feuilleCorps = h('div', { class: 'tcg-feuille-corps' });
  const fermer = h('button', { class: 'tcg-feuille-x', type: 'button', 'aria-label': 'Fermer', text: '✕' });
  fermer.addEventListener('click', () => _feuille.close());
  _feuille = h('dialog', { class: 'tcg-feuille' }, fermer, _feuilleCorps);
  // Un clic hors de la carte ferme : sur `<dialog>`, le fond EST la boîte de
  // dialogue elle-même, l'événement ne vient donc pas d'un enfant.
  _feuille.addEventListener('click', (ev) => { if (ev.target === _feuille) _feuille.close(); });

  const section = h('section', { class: 'section tcg-plateau' },
    h('div', { class: 'section-inner' },
      h('div', { class: 'reveal' },
        h('div', { class: 'eyebrow', text: 'MAQUETTE' }),
        h('h2', { class: 'h2', text: 'À quoi ça ressemble.' }),
        h('p', { class: 'lead' },
          'Un plateau et des cartes, pour juger le design autrement que sur du texte. ',
          h('b', { text: 'Rien n’est jouable ici' }),
          ' : chaque tour est un instantané écrit à la main, pas une partie qui tourne. '
          + 'Les valeurs bougeront encore.'),
      ),
      _pills,
      _resume,
      _table,
      h('div', { class: 'tcg-tours' }, _prec, _pos, _suiv),
      h('div', { class: 'tcg-journal-boite' },
        h('div', { class: 'tcg-main-lbl mono', text: 'CE QUI S’EST PASSÉ' }),
        _journal),
      _feuille,
    ),
  );

  rendreEtat();
  return section;
}

export function demonterPlateau() {
  // Un `<dialog>` ouvert que le routeur détache laisserait le focus et le
  // verrou de défilement du document derrière lui.
  if (_feuille && _feuille.open) _feuille.close();
  _format = DEFAUT;
  _index = 0;
  _table = null;
  _journal = null;
  _resume = null;
  _pos = null;
  _prec = null;
  _suiv = null;
  _feuille = null;
  _feuilleCorps = null;
  _pills = null;
}
