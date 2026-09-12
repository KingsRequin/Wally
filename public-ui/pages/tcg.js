// public-ui/pages/tcg.js — la collection de cartes
//
// Port des maquettes Claude Design `Galerie Cartes.dc.html` (les héros) et
// `Cartes Tactique.dc.html` (les actions et les passifs) : les cartes
// TERMINÉES, ajoutées au fur et à mesure. Elle a remplacé l'annonce du TCG et
// la maquette du plateau (`/demo/plateau-tcg`), retirée le 2026-09-09.
//
// DEUX familles, deux onglets, deux sources — `GET /api/public/tcg/cartes` et
// `GET /api/public/tcg/cartes-action`. Elles ne partagent pas un champ au-delà
// du nom : un héros porte atk/pv/aura, une rareté et quatre couches
// d'illustration ; une carte action porte un type, une catégorie et un
// pochoir. Les compteurs DÉRIVENT des listes, ils ne s'écrivent pas.

import { h, inclinaisonDisponible, pageFooter, surInclinaison } from '../app.js';
import { cartes, cartesAction } from './tcg-donnees.js';
import { INDEFINI, carteHero, monterStylesCarte } from '../partage/tcg-carte.js';
import {
  REGLE_INDEFINIE,
  carteAction,
  monterStylesCarteAction,
} from '../partage/tcg-carte-action.js';

const FEUILLE = '/pages/tcg.css';

let _demonter = null;

/** L'invitation à manipuler les cartes.
 *
 * « Survole-les » n'a aucun sens au doigt, et c'est là que le site est
 * majoritairement lu : la phrase suit le moyen de pointage, pas la largeur
 * d'écran (une tablette large n'a pas de curseur non plus).
 */
function invitationHeros() {
  let geste = 'Survole-les pour voir les couches se séparer.';
  if (inclinaisonDisponible()) {
    // Deux gestes, et il faut les DEUX : l'appui ouvre, l'inclinaison joue.
    geste = 'Touche-en une pour l\'ouvrir, puis penche ton téléphone.';
  } else if (window.matchMedia('(hover: none)').matches) {
    geste = 'Touche-les pour voir les couches se séparer.';
  }
  return `Les cartes illustrées, ajoutées au fur et à mesure. ${geste}`;
}

function invitationAction() {
  const geste = inclinaisonDisponible()
    ? 'Penche ton téléphone : le vernis suit la lumière.'
    : 'Passe la souris dessus : elles se tordent sous le vernis.';
  return 'Les cartes qu\'on joue en cours de partie. Le cadre dit le type —'
    + ' action ou passif — et le bandeau du haut dit la catégorie.'
    + ` ${geste}`;
}

/** Fait suivre le gyroscope à la carte HÉROS que le lecteur a devant les yeux.
 *
 * Sur un ordinateur il suffit de PASSER la souris sur une carte. Au téléphone,
 * c'est l'APPUI qui ouvre — et un second appui qui referme.
 *
 * 🚨 L'ouverture AUTOMATIQUE au défilement a été retirée le 2026-09-09, à la
 * demande de l'owner : la page passait son temps à ouvrir et fermer des
 * cartes, ce qui se lisait comme un clignotement.
 *
 * 🚨 UNE seule carte ouverte à la fois, et c'est délibéré : la 3D d'une carte
 * coûte neuf calques GPU au lieu d'un. Ouvrir la nouvelle ferme la précédente.
 *
 * ⚠️ Rien à faire ici pour l'autorisation iOS : `app.js` la demande au premier
 * appui sur la page, une fois pour tout le site.
 */
function brancherAppuiEtGyroscope(rendues) {
  let ouverte = null;

  const basculer = (carte) => {
    if (ouverte === carte) {
      ouverte.incliner(0, 0);
      ouverte.fermer();
      ouverte = null;
      return;
    }
    if (ouverte) { ouverte.incliner(0, 0); ouverte.fermer(); }
    ouverte = carte;
    carte.ouvrir();
  };

  const surAppui = rendues.map((carte) => {
    const ecouteur = () => basculer(carte);
    carte.noeud.addEventListener('click', ecouteur);
    return () => carte.noeud.removeEventListener('click', ecouteur);
  });

  // `x` et `y` arrivent dans [−1, 1] ; `incliner` attend [−0.5, 0.5]. Le
  // facteur donne donc la course COMPLÈTE d'un curseur passant d'un bord à
  // l'autre — pareil qu'à la souris, ce qui est ce qu'on veut.
  const stop = surInclinaison((x, y) => {
    if (ouverte) ouverte.incliner(x * 0.5, y * 0.5);
  });

  return () => { surAppui.forEach((d) => d()); stop(); };
}

/** Fait suivre le gyroscope aux cartes ACTION visibles à l'écran.
 *
 * 🚨 Aux cartes VISIBLES, et pas à toutes. La grille en compte plus de
 * cinquante : les incliner toutes à chaque relevé du capteur — plusieurs
 * dizaines par seconde — écrirait cinquante transformations pour deux qui se
 * voient. L'`IntersectionObserver` ne coûte rien entre deux défilements et
 * ramène le travail à ce qu'on regarde.
 *
 * ⚠️ Contrairement aux héros, il n'y a RIEN à ouvrir ici : la carte est déjà
 * entièrement lisible. Le gyroscope ne fait que la tordre, donc pas d'appui à
 * brancher — et un appui qui ne fait rien est pire qu'une carte immobile.
 */
function brancherGyroscopeAction(rendues) {
  const visibles = new Set();
  const observateur = new IntersectionObserver((entrees) => {
    entrees.forEach((e) => {
      const rendu = rendues.find((r) => r.boite === e.target);
      if (!rendu) return;
      if (e.isIntersecting) { visibles.add(rendu); rendu.eveiller(); return; }
      visibles.delete(rendu);
      rendu.endormir();
    });
  }, { threshold: 0.35 });
  rendues.forEach((r) => observateur.observe(r.boite));

  const stop = surInclinaison((x, y) => {
    visibles.forEach((r) => r.incliner(x * 0.5, y * 0.5));
  });

  return () => { observateur.disconnect(); stop(); };
}

/** Le bandeau qui dit ce qui n'est pas encore décidé.
 *
 * Le dire À L'ÉCRAN et pas seulement en commentaire : sans ça, le premier
 * lecteur construit un deck sur des valeurs qui vont toutes bouger, et c'est
 * nous qui l'y avons invité.
 *
 * 🚨 Les nombres sont COMPTÉS, jamais écrits. Une phrase écrite à la main
 * vieillit sans prévenir ; celle-ci suit la collection.
 * ⚠️ Les formes sont écrites ENTIÈRES. Un fragment interpolé dans une phrase
 * commune ne tient pas l'accord : un premier jet rendait « 4 d'entre elles
 * attendent encore SES règles ».
 */
function avisHeros(liste) {
  const ecrites = liste.filter((c) => c.description !== INDEFINI).length;
  const reste = liste.length - ecrites;
  if (!reste) {
    return h('p', { class: 'tcgal-avis' },
      h('strong', { text: 'Les chiffres sont ceux du jeu.' }),
      ' Chaque carte de la collection a ses règles et ses valeurs.');
  }
  const phrase = reste > 1
    ? `${reste} d'entre elles attendent encore leurs règles et leurs chiffres,`
      + ' et le disent en toutes lettres.'
    : "L'une d'elles attend encore ses règles et ses chiffres, et le dit en"
      + ' toutes lettres.';
  return h('p', { class: 'tcgal-avis' },
    h('strong', { text: 'Toutes ne sont pas encore écrites.' }),
    ` ${phrase} Rien n'est affiché « en attendant » : une valeur qui apparaît`
    + ' ici est une valeur décidée.',
  );
}

/** Le même bandeau pour les actions — mais le manque n'y est pas le même.
 *
 * 🚨 Le COÛT n'est pas « pas encore écrit », il est **délibérément absent** :
 * il se pose une fois la puissance de la carte arrêtée (arbitrage de l'owner
 * du 2026-09-12). Le dire comme un retard serait faux ; c'est une méthode.
 */
function avisAction(liste) {
  const ecrites = liste.filter((c) => c.regle !== REGLE_INDEFINIE).length;
  const reste = liste.length - ecrites;
  const parties = [
    h('strong', { text: 'Aucun coût n\'est encore fixé.' }),
    ' Les pastilles affichent toutes 0, et ça veut dire « pas encore calibré » :'
    + ' le coût se calcule sur la puissance de la carte, donc il vient en'
    + ' dernier.',
  ];
  if (reste) {
    parties.push(reste > 1
      ? ` ${reste} cartes attendent encore leur règle, et le disent.`
      : ' Une carte attend encore sa règle, et le dit.');
  }
  return h('p', { class: 'tcgal-avis' }, parties);
}

// ── Les deux onglets ──────────────────────────────────────────────────────

/** Une famille de cartes : comment on la charge, la compte et la rend.
 *
 * 🚨 Les deux onglets sont DÉCRITS et pas codés deux fois. La page monte,
 * démonte et compte de la même façon des deux côtés ; seul ce tableau change.
 * Écrire deux fois la boucle de montage, c'est se garantir qu'un correctif
 * n'est posé que d'un côté — le défaut le plus courant de ce dépôt.
 */
const FAMILLES = [
  {
    cle: 'heros',
    onglet: 'Héros',
    charger: cartes,
    invitation: invitationHeros,
    avis: avisHeros,
    // La classe que `scripts/smoke_front.py` cherche pour dire que la page a
    // monté. Elle DOIT rester sur l'onglet ouvert par défaut.
    grille: 'tcgal-grille',
    ecrite: (c) => c.description !== INDEFINI,
    nomUn: 'CARTE ILLUSTRÉE',
    nomPlusieurs: 'CARTES ILLUSTRÉES',
  },
  {
    cle: 'action',
    onglet: 'Actions & passifs',
    charger: cartesAction,
    invitation: invitationAction,
    avis: avisAction,
    grille: 'tcgal-grille tcgal-grille--action',
    ecrite: (c) => c.regle !== REGLE_INDEFINIE,
    nomUn: 'CARTE',
    nomPlusieurs: 'CARTES',
  },
];

/** Les cartes à AFFICHER pour une famille.
 *
 * Une entrée `groupe: 3` en donne QUATRE : les trois exemplaires numérotés,
 * puis la carte complète, sans trait ni chiffre — c'est l'absence de barre qui
 * dit « le jeu est réuni ». Le deck, lui, n'en compte qu'une : le nombre
 * affiché ici est celui des cartes qu'on tient en main, pas celui du deck.
 */
function exemplaires(liste) {
  return liste.flatMap((carte) => (carte.groupe > 0
    ? Array.from({ length: carte.groupe + 1 },
      (_, k) => ({ carte, rang: k < carte.groupe ? k + 1 : 0 }))
    : [{ carte, rang: 0 }]));
}

export function mount(el) {
  const lien = document.createElement('link');
  lien.rel = 'stylesheet';
  lien.href = FEUILLE;
  document.head.appendChild(lien);
  // Les deux feuilles de carte sont posées dès le montage, pas au changement
  // d'onglet : une feuille chargée à la bascule fait clignoter la grille le
  // temps qu'elle arrive, et le premier rendu se fait sans styles.
  const demonterStyles = [monterStylesCarte(), monterStylesCarteAction()];

  const compte = h('span', { class: 'tcgal-compte', text: '' });
  const chapo = h('p', { class: 'tcgal-chapo', text: '' });
  const avisBoite = h('div', {});
  const panneau = h('div', {});
  const onglets = h('div', { class: 'tcgal-onglets', role: 'tablist' });

  el.appendChild(h('section', { class: 'tcgal' },
    h('div', { class: 'tcgal-inner' },
      h('header', { class: 'tcgal-head' },
        h('h1', { class: 'tcgal-titre', text: 'La collection' }),
        compte,
      ),
      onglets,
      chapo,
      avisBoite,
      panneau,
    ),
  ));
  el.appendChild(pageFooter());

  // La page peut être quittée pendant qu'une requête est en vol : sans ce
  // drapeau, on insérerait des cartes dans un `<main>` que le routeur a déjà
  // vidé, et elles resteraient abonnées à la boucle d'animation pour toujours.
  let vivante = true;
  // Ce que l'onglet AFFICHÉ a posé. Vidé à chaque bascule — les cartes héros
  // s'abonnent à une boucle d'animation, et une carte non détruite y reste
  // abonnée alors qu'elle n'est plus dans le document.
  let posees = [];
  let debrancherGyro = null;
  let familleActive = null;

  const vider = () => {
    if (debrancherGyro) { debrancherGyro(); debrancherGyro = null; }
    posees.forEach((r) => r.detruire());
    posees = [];
    panneau.textContent = '';
  };

  const remplirHeros = (famille, liste) => {
    const grille = h('div', { class: famille.grille });
    const auGyroscope = inclinaisonDisponible();
    liste.forEach((carte) => {
      const rendu = carteHero(carte, { interactif: !auGyroscope });
      const noeud = h('div', { class: 'tcgal-case' },
        rendu.boite,
        h('div', { class: 'tcgal-legende', text: carte.legende }),
      );
      posees.push({ ...rendu, noeud });
      grille.appendChild(noeud);
    });
    panneau.appendChild(grille);
    if (auGyroscope) debrancherGyro = brancherAppuiEtGyroscope(posees);
  };

  const remplirAction = (famille, liste) => {
    const grille = h('div', { class: famille.grille });
    const auGyroscope = inclinaisonDisponible();
    exemplaires(liste).forEach(({ carte, rang }) => {
      const rendu = carteAction(carte, { rang, interactif: !auGyroscope });
      grille.appendChild(h('div', { class: 'tcgal-case tcgal-case--action' },
        rendu.boite));
      posees.push(rendu);
    });
    panneau.appendChild(grille);
    if (auGyroscope) debrancherGyro = brancherGyroscopeAction(posees);
  };

  const compter = (famille, liste, affichees) => {
    const pluriel = affichees > 1 ? famille.nomPlusieurs : famille.nomUn;
    const ecrites = liste.filter(famille.ecrite).length;
    compte.textContent = ecrites
      ? `${affichees} ${pluriel} · ${ecrites} ÉCRITE${ecrites > 1 ? 'S' : ''}`
      : `${affichees} ${pluriel}`;
  };

  // Un échec doit se DIRE. Une grille vide se lit « il n'y a pas de cartes »,
  // ce qui est faux — l'absence n'est pas le vide, et un visiteur qui tombe
  // dessus repart en croyant la collection abandonnée.
  const echouer = (famille, e) => {
    if (!vivante) return;
    console.warn('TCG : cartes non chargées', e);
    compte.textContent = '';
    panneau.textContent = '';
    panneau.appendChild(h('div', { class: 'tcgal-echec' },
      h('p', { text: "Les cartes n'ont pas pu être chargées." }),
      h('button', {
        class: 'btn btn-ghost',
        text: 'Réessayer',
        onclick: () => ouvrir(famille, true),
      }),
    ));
  };

  function ouvrir(famille, forcer) {
    if (familleActive === famille && !forcer) return;
    familleActive = famille;
    vider();
    chapo.textContent = famille.invitation();
    avisBoite.textContent = '';
    onglets.querySelectorAll('.tcgal-onglet').forEach((b) => {
      const actif = b.dataset.famille === famille.cle;
      b.classList.toggle('is-actif', actif);
      b.setAttribute('aria-selected', actif ? 'true' : 'false');
    });
    famille.charger().then((liste) => {
      // Deux bascules rapprochées laissent deux requêtes en vol : sans ce
      // second garde, la plus lente écrirait sa grille par-dessus la plus
      // récente — et l'onglet marqué ne serait plus celui affiché.
      if (!vivante || familleActive !== famille) return;
      avisBoite.appendChild(famille.avis(liste));
      if (famille.cle === 'heros') remplirHeros(famille, liste);
      else remplirAction(famille, liste);
      compter(famille, liste, posees.length);
    }).catch((e) => {
      if (familleActive !== famille) return;
      echouer(famille, e);
    });
  }

  FAMILLES.forEach((famille) => {
    onglets.appendChild(h('button', {
      class: 'tcgal-onglet',
      'data-famille': famille.cle,
      role: 'tab',
      'aria-selected': 'false',
      text: famille.onglet,
      onclick: () => ouvrir(famille, false),
    }));
  });

  ouvrir(FAMILLES[0], false);

  _demonter = () => {
    vivante = false;
    vider();
    demonterStyles.forEach((d) => d());
    lien.remove();
  };
}

export function unmount() {
  if (_demonter) _demonter();
  _demonter = null;
}
