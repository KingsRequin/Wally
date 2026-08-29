// public-ui/pages/tcg.js — « Il collectionne aussi les cartes »
//
// Page d'annonce : rien n'est jouable, le code s'écrit. Elle ne consomme
// AUCUNE API — tout ce qu'elle affiche est une intention, pas un état.

import { h, nomBot, pageFooter, sectionHead } from '../app.js';

// L'éventail de dos de cartes du héros : purement décoratif, jamais annoncé
// aux lecteurs d'écran.
const EVENTAIL = [
  { x: -430, y: 40,  w: 150, h: 210, rot: '-16deg', o: .30, dur: '7s',   bg: 'linear-gradient(160deg,#2a1f3d,#4a2a52)' },
  { x: -270, y: -10, w: 160, h: 224, rot: '-8deg',  o: .40, dur: '8s',   bg: 'linear-gradient(160deg,#3a2410,#7a4a18)' },
  { x: 120,  y: -10, w: 160, h: 224, rot: '8deg',   o: .40, dur: '8.6s', bg: 'linear-gradient(160deg,#123043,#2b6b7a)' },
  { x: 290,  y: 40,  w: 150, h: 210, rot: '16deg',  o: .30, dur: '7.4s', bg: 'linear-gradient(160deg,#3a1420,#7a2038)' },
  { x: -70,  y: 250, w: 140, h: 196, rot: '-3deg',  o: .18, dur: '9s',   bg: 'linear-gradient(160deg,#1a1430,#3a2a60)' },
];

const ETAPES = [
  {
    n: '01',
    t: 'Ta collection',
    d: 'Chaque carte gagnée en discutant, en streamant ou en jouant arrive dans ton compte. Il sait qui possède quoi.',
    tag: 'EN COURS', couleur: 'var(--gold)', bord: 'rgba(255,176,46,.35)',
  },
  {
    n: '02',
    t: 'Ton deck',
    d: 'Construis, renomme, teste. Il commentera tes choix, il a des avis sur les decks trop sûrs.',
    tag: 'À VENIR', couleur: 'var(--dim)', bord: 'rgba(255,255,255,.14)',
  },
  {
    n: '03',
    t: 'Les duels',
    d: 'Deux comptes connectés, une table, lui comme arbitre et commentateur. Il se souviendra de qui a gagné.',
    tag: 'À VENIR', couleur: 'var(--dim)', bord: 'rgba(255,255,255,.14)',
  },
];

function heros() {
  const eventail = h('div', { class: 'tcg-fan', 'aria-hidden': 'true', 'data-px': '0.35' });
  EVENTAIL.forEach((c) => {
    const carte = h('div', { class: 'tcg-card' });
    carte.style.cssText = `left:${c.x}px; top:${c.y}px; --r:${c.rot}; width:${c.w}px; height:${c.h}px;`
      + `background:${c.bg}; opacity:${c.o}; animation-duration:${c.dur}`;
    eventail.appendChild(carte);
  });

  return h('section', { class: 'section tcg-hero' },
    eventail,
    h('div', { class: 'badge-chantier' }, h('span', { class: 'dot' }), 'EN CHANTIER'),
    h('h1', { class: 'h1' },
      'Il collectionne aussi', h('br'), 'les ', h('span', { class: 'flame-text', text: 'cartes' }), '.'),
    h('p', { class: 'lead lead-center reveal' },
      `Un jeu de cartes où ${nomBot()} distribue, arbitre et se souvient de tes parties. `
      + 'Les comptes Discord connectés auront leur collection, leurs decks et leurs duels. '
      + "Rien n'est encore jouable, le code s'écrit."),
    h('div', { class: 'hero-cta reveal' },
      h('button', {
        class: 'btn btn-discord',
        text: 'Connecter mon Discord',
        onclick: () => { window.location.href = '/api/chat/auth/login'; },
      }),
      h('a', { class: 'btn btn-ghost', href: '/chat', 'data-route': '/chat', text: `Parler à ${nomBot()}` }),
    ),
    h('div', { class: 'hero-note mono', text: 'TOUTES LES ANNONCES PASSENT PAR LE DISCORD' }),
  );
}

function etapes() {
  return h('section', { class: 'section' },
    h('div', { class: 'section-inner' },
      sectionHead('CE QUI ARRIVE', 'Trois choses, dans cet ordre.'),
      h('div', { class: 'grid grid-3 mt-48' },
        ...ETAPES.map((s) => h('div', { class: 'card card-lift reveal', 'data-tilt': '1' },
          h('div', { class: 'card-top' },
            h('span', { class: 'label', text: s.n }),
            h('span', { class: 'tag', style: `border-color:${s.bord}; color:${s.couleur}; font-size:9.5px; letter-spacing:.12em`, text: s.tag }),
          ),
          h('div', { class: 'h3 mt-20', text: s.t }),
          h('p', { class: 'lead lead-sm', text: s.d }),
        )),
      ),
    ),
  );
}

function rappel() {
  return h('section', { class: 'section' },
    h('div', { class: 'section-inner split' },
      h('div', { class: 'reveal', style: 'max-width:520px' },
        h('h2', { class: 'h2', style: 'font-size:40px', text: 'En attendant, il est déjà là pour parler.' }),
        h('p', { class: 'lead', text: 'La mémoire, les émotions et le journal tournent depuis des mois. Le TCG vient s\'y greffer, pas le remplacer.' }),
      ),
      h('div', { class: 'hero-cta reveal' },
        h('a', { class: 'btn btn-primary', href: '/chat', 'data-route': '/chat', text: 'Ouvrir le chat' }),
        h('a', { class: 'btn btn-ghost', href: '/', 'data-route': '/', text: "Retour à l'accueil" }),
      ),
    ),
  );
}

export function mount(el) {
  el.appendChild(heros());
  el.appendChild(etapes());
  el.appendChild(rappel());
  el.appendChild(pageFooter());
}

