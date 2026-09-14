// public-ui/pages/wallycard-regles.js — le livre des règles (`/wallycard/regles`)
//
// Lit `donnees/wallycard-regles.json`, écrit par `scripts/export_regles_wallycard.py`
// depuis Notion. Le site ne lit JAMAIS Notion en direct : relancer l'export après
// chaque changement des règles, c'est ce qui publie.
//
// Deux parties : les chapitres, puis les fiches des cartes. Une carte citée
// n'importe où (chapitre ou autre fiche) est un lien qui ouvre sa fiche.
//
// 🚨 Tout le texte passe par `textContent` : aucune ligne de l'export n'est
// interprétée comme du HTML, même si Notion en contenait.

import { h, pageFooter, surAnimation } from '../app.js';

const FEUILLE = '/pages/wallycard-regles.css';
const DONNEES = '/donnees/wallycard-regles.json';
const PREFIXE = 'carte-';

let _lien = null;
let _vivant = false;
let _surHash = null;
let _desabonnerRail = null;

function segments(liste, ouvrir) {
  return liste.map((s) => {
    let noeud;
    if (s.carte) {
      // Une ancre `#…` : le défilement inertiel d'`app.js` la prend comme les
      // autres. Un `scrollIntoView` maison se faisait reprendre la position
      // par lui (vu au smoke test : fiche ouverte, mais hors de l'écran). Le
      // clic ne fait donc qu'OUVRIR la fiche avant que le défilement ne parte.
      noeud = h('a', {
        class: 'wcr-lien-carte',
        href: `#${PREFIXE}${s.carte}`,
        text: s.t,
        onclick: () => ouvrir(s.carte, false),
      });
    } else if (s.lien) {
      noeud = h('a', { href: s.lien, target: '_blank', rel: 'noopener', text: s.t });
    } else {
      noeud = document.createTextNode(s.t);
    }
    if (s.i) noeud = h('em', {}, noeud);
    if (s.g) noeud = h('strong', {}, noeud);
    return noeud;
  });
}

const BALISES = { h1: 'h3', h2: 'h3', h3: 'h4', p: 'p', citation: 'blockquote' };

function bloc(b, ouvrir) {
  if (BALISES[b.type]) {
    return h(BALISES[b.type], { class: `wcr-${b.type}` }, segments(b.texte, ouvrir));
  }
  if (b.type === 'ul' || b.type === 'ol') {
    return h(b.type, { class: 'wcr-liste' }, b.items.map((item) => h('li', {}, segments(item, ouvrir))));
  }
  if (b.type === 'table') {
    const [tete, ...corps] = b.entete ? b.lignes : [null, ...b.lignes];
    return h('div', { class: 'wcr-table-zone' },
      h('table', { class: 'wcr-table' },
        tete && h('thead', {}, h('tr', {}, tete.map((c) => h('th', { scope: 'col' }, segments(c, ouvrir))))),
        h('tbody', {}, corps.map((ligne) => h('tr', {}, ligne.map((c) => h('td', {}, segments(c, ouvrir)))))),
      ));
  }
  // Un type que l'export n'écrit pas : le dire plutôt que de le taire.
  console.warn('Wallycard : bloc de règles inconnu', b.type);
  return null;
}

function ancreChapitre(i) { return `chapitre-${i + 1}`; }

function rendre(racine, donnees) {
  const fiches = new Map();

  function ouvrir(cle, defiler = true) {
    const fiche = fiches.get(cle);
    if (!fiche) return;
    fiche.open = true;
    history.replaceState(history.state, '', `#${PREFIXE}${cle}`);
    if (defiler) fiche.scrollIntoView({ block: 'start' });
    fiche.querySelector('summary').focus({ preventScroll: true });
  }

  // Les liens `#…` du sommaire et du rail ne portent AUCUN gestionnaire : le
  // défilement inertiel d'`app.js` prend déjà toutes les ancres internes. Un
  // `scrollIntoView` en plus se disputerait la position avec lui.
  const sections = [
    ...donnees.chapitres.map((c, i) => [ancreChapitre(i), c.titre]),
    ['cartes', 'Les cartes'],
  ];
  const sommaire = h('nav', { class: 'wcr-sommaire', 'aria-label': 'Sommaire des règles' },
    h('ol', {}, sections.map(([id, titre]) => h('li', {}, h('a', { href: `#${id}`, text: titre })))));

  const chapitres = donnees.chapitres.map((c, i) => h('section', { class: 'wcr-chapitre', id: ancreChapitre(i) },
    h('h2', { class: 'wcr-chapitre-titre', text: c.titre }),
    c.blocs.map((b) => bloc(b, ouvrir)),
  ));

  const listeFiches = donnees.fiches.map((f) => {
    const noeud = h('details', { class: 'wcr-fiche', id: `${PREFIXE}${f.cle}`, 'data-type': f.type },
      h('summary', { class: 'wcr-fiche-tete' },
        h('span', { class: 'wcr-fiche-court', text: f.court }),
        h('span', { class: 'wcr-fiche-nom', text: f.nom }),
        h('span', { class: 'wcr-fiche-type', text: f.type })),
      h('div', { class: 'wcr-fiche-corps' }, f.blocs.map((b) => bloc(b, ouvrir))),
    );
    fiches.set(f.cle, noeud);
    return noeud;
  });

  racine.append(
    sommaire,
    ...chapitres,
    h('section', { class: 'wcr-chapitre', id: 'cartes' },
      h('h2', { class: 'wcr-chapitre-titre', text: 'Les cartes' }),
      h('p', { class: 'wcr-p', text: `${donnees.fiches.length} fiches, une par carte action ou passif.` }),
      listeFiches),
    h('p', { class: 'wcr-date', text: `Règles exportées le ${donnees.exporte_le.split('-').reverse().join('/')}.` }),
  );

  // Le rail : un trait par chapitre sur la droite, celui qu'on lit s'allume.
  // Mêmes classes que celui de l'accueil, dont il reprend le style.
  const rail = h('nav', { class: 'rail', 'aria-label': 'Chapitres des règles' },
    sections.map(([id, titre]) => h('a', { href: `#${id}`, title: titre },
      h('span', { class: 'lbl', text: titre.toUpperCase() }),
      h('span', { class: 'tick' }))));
  racine.appendChild(rail);
  const cibles = sections.map(([id]) => document.getElementById(id));
  const liens = Array.from(rail.children);
  let allume = -1;
  const suivre = (_sy, vh) => {
    // La DERNIÈRE section dont le haut a passé les 42 % de l'écran : toujours
    // exactement une allumée, comme sur l'accueil.
    let actif = 0;
    cibles.forEach((el, i) => { if (el && el.getBoundingClientRect().top < vh * 0.42) actif = i; });
    if (actif === allume) return;
    allume = actif;
    liens.forEach((a, i) => a.classList.toggle('active', i === actif));
  };
  _desabonnerRail = surAnimation(suivre);
  suivre(window.scrollY, window.innerHeight);

  // Arrivée par un lien partagé vers une fiche, ou ancre changée sans
  // rechargement (lien collé dans la barre d'adresse, page déjà ouverte).
  _surHash = () => {
    const hash = decodeURIComponent(location.hash.slice(1));
    if (hash.startsWith(PREFIXE)) ouvrir(hash.slice(PREFIXE.length));
  };
  window.addEventListener('hashchange', _surHash);
  _surHash();
}

export function mount(el) {
  _vivant = true;
  _lien = document.createElement('link');
  _lien.rel = 'stylesheet';
  _lien.href = FEUILLE;
  document.head.appendChild(_lien);

  const corps = h('div', { class: 'wcr-corps' }, h('p', { class: 'wcr-p', text: 'Chargement des règles…' }));
  el.appendChild(h('section', { class: 'wcr' },
    h('div', { class: 'wcr-inner' },
      h('a', { class: 'wcr-retour', href: '/wallycard', 'data-route': '/wallycard', text: '← Wallycard' }),
      h('h1', { class: 'wcr-titre', text: 'Règles' }),
      corps,
    ),
  ));
  el.appendChild(pageFooter());

  fetch(DONNEES)
    .then((r) => (r.ok ? r.json() : Promise.reject(new Error(`HTTP ${r.status}`))))
    .then((donnees) => {
      if (!_vivant) return;
      corps.textContent = '';
      rendre(corps, donnees);
    })
    .catch((e) => {
      if (!_vivant) return;
      corps.textContent = '';
      corps.appendChild(h('p', { class: 'wcr-p wcr-erreur', text: `Les règles n'ont pas pu être chargées : ${e.message}` }));
    });
}

export function unmount() {
  _vivant = false;
  if (_desabonnerRail) _desabonnerRail();
  _desabonnerRail = null;
  if (_surHash) window.removeEventListener('hashchange', _surHash);
  _surHash = null;
  if (_lien) _lien.remove();
  _lien = null;
}
