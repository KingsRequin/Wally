// public-ui/pages/credits.js — d'où viennent les images
//
// 🚨 Cette page n'est PAS décorative : les icônes de game-icons.net sont sous
// CC BY 3.0, une licence qui oblige à créditer l'AUTEUR de chaque dessin — pas
// seulement le site. Sans cette page, le TCG est en infraction dès la première
// carte affichée.
//
// La liste des auteurs est LUE (`/assets/icones/AUTEURS.json`), jamais écrite
// ici : une icône ajoutée au catalogue doit apparaître dans les crédits, et
// une liste recopiée dans le JS resterait en arrière sans que personne le
// voie. `tests/test_credits_icones.py` refuse qu'une icône du dossier manque
// au manifeste.

import { h, pageFooter, sectionHead } from '../app.js';

const FEUILLE = '/pages/credits.css';

let _demonter = null;

/** Un bloc de crédit : un titre, ce que c'est, et où ça se trouve. */
function source(titre, quoi, liens, extra) {
  return h('article', { class: 'cred-bloc' },
    h('h3', { class: 'cred-titre', text: titre }),
    h('p', { class: 'cred-quoi', text: quoi }),
    h('div', { class: 'cred-liens' },
      liens.map(([texte, href]) => h('a', {
        class: 'cred-lien', href, target: '_blank', rel: 'noopener', text: texte,
      })),
    ),
    extra || null,
  );
}

/** Les auteurs game-icons, un par ligne, avec ce qu'on leur a pris.
 *
 * Le NOMBRE d'icônes est compté, jamais écrit : c'est le seul chiffre de la
 * page, et il doit suivre le dossier.
 */
function auteursGameIcons(manifeste) {
  const auteurs = Object.entries(manifeste.auteurs)
    .sort((a, b) => b[1].length - a[1].length);
  return h('ul', { class: 'cred-auteurs' },
    auteurs.map(([nom, icones]) => h('li', { class: 'cred-auteur' },
      h('a', {
        class: 'cred-auteur-nom',
        href: `https://game-icons.net/`,
        target: '_blank',
        rel: 'noopener',
        text: nom,
      }),
      h('span', { class: 'cred-auteur-compte', text: `${icones.length} icône${icones.length > 1 ? 's' : ''}` }),
      h('span', { class: 'cred-auteur-liste', text: icones.join(' · ') }),
    )),
  );
}

export function mount(el) {
  const lien = document.createElement('link');
  lien.rel = 'stylesheet';
  lien.href = FEUILLE;
  document.head.appendChild(lien);

  const boiteIcones = h('div', {});
  let vivante = true;

  el.appendChild(h('section', { class: 'cred' },
    h('div', { class: 'cred-inner' },
      sectionHead('CRÉDITS', 'D\'où viennent les images',
        'Le TCG du Purgatoire emprunte ses pictogrammes à deux fonds : une'
        + ' banque de dessins libres, et l\'univers d\'Apex Legends. Tous'
        + ' demandent à être nommés, et l\'un d\'eux demande à nommer aussi'
        + ' l\'auteur de chaque dessin.'),

      h('div', { class: 'cred-grille' },
        source('game-icons.net',
          'Les pictogrammes génériques des cartes — l\'épée du bandeau'
          + ' d\'attaque, la pizza, le chat, la manette. Licence CC BY 3.0 :'
          + ' elle autorise l\'usage et la modification, à condition de'
          + ' créditer l\'auteur du dessin. Les fichiers ont été retouchés —'
          + ' le fond noir plein cadre livré par le dépôt est retiré, sans'
          + ' quoi ils ne peuvent pas servir de pochoir.',
          [['game-icons.net', 'https://game-icons.net'],
           ['Licence CC BY 3.0', 'https://creativecommons.org/licenses/by/3.0/']],
          boiteIcones),

        source('Apex Legends',
          'Les capacités, les objets et les armes cités par les cartes — le'
          + ' care package, le totem de Revenant, le drone de Crypto, le baril'
          + ' de Caustique, le stim d\'Octane. Le jeu appartient à Respawn'
          + ' Entertainment et Electronic Arts. Rien n\'est vendu ici : le TCG'
          + ' est un jeu de communauté, sans contrepartie, et ces références'
          + ' sont celles que la commu emploie tous les jours.',
          [['Apex Legends', 'https://www.ea.com/games/apex-legends']]),

        source('apexlegends.wiki.gg',
          'C\'est de là que viennent les icônes tirées du jeu. Le wiki les'
          + ' héberge et les tient à jour ; sans lui, il aurait fallu redessiner'
          + ' chaque carte à la main.',
          [['apexlegends.wiki.gg', 'https://apexlegends.wiki.gg']]),

        source('Le reste',
          'Les illustrations des héros sont propres au serveur et faites pour'
          + ' lui. Les typographies sont Space Grotesk et JetBrains Mono,'
          + ' toutes deux sous licence libre. Le code du bot et du site est'
          + ' ouvert.',
          [['Space Grotesk', 'https://fonts.google.com/specimen/Space+Grotesk'],
           ['JetBrains Mono', 'https://fonts.google.com/specimen/JetBrains+Mono'],
           ['Le dépôt', 'https://github.com/KingsRequin/Wally']]),
      ),
    ),
  ));
  el.appendChild(pageFooter());

  // Le manifeste est chargé APRÈS le rendu : la page doit se lire même si le
  // fichier manque. Un crédit absent est un problème de licence, pas une
  // raison de rendre une page blanche — et l'échec se dit à l'écran.
  fetch('/assets/icones/AUTEURS.json')
    .then((r) => { if (!r.ok) throw new Error(`HTTP ${r.status}`); return r.json(); })
    .then((m) => { if (vivante) boiteIcones.appendChild(auteursGameIcons(m)); })
    .catch((e) => {
      console.warn('Crédits : liste des auteurs non chargée', e);
      if (!vivante) return;
      boiteIcones.appendChild(h('p', { class: 'cred-echec' },
        'La liste des auteurs n\'a pas pu être chargée. Elle vit dans ',
        h('code', { text: '/assets/icones/AUTEURS.json' }),
        '.'));
    });

  _demonter = () => { vivante = false; lien.remove(); };
}

export function unmount() {
  if (_demonter) _demonter();
  _demonter = null;
}
