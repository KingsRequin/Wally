// public-ui/pages/wallycard-deck.js — l'éditeur de deck de la Bibliothèque
//
// Un panneau « mon deck » et, sous chaque carte de la galerie, un bouton pour
// l'ajouter ou la retirer. Les decks sont rangés sur le compte Discord
// (`/api/public/tcg/decks`) ; sans connexion on compose, mais on n'enregistre pas.
//
// 🚨 Le clic sur la CARTE ne met rien dans le deck : il ouvre un héros ou
// retourne une carte action, et ce geste existait avant l'éditeur. Un bouton
// dédié évite qu'un joueur qui voulait lire une carte la retrouve dans son deck.
//
// 🚨 Les limites (15 cartes, 3 héros, longueur du nom) sont LUES sur le serveur,
// jamais écrites ici : une limite recopiée finit par dire autre chose que celle
// qui refuse. Le serveur reste seul juge ; le panneau ne fait qu'éviter qu'on
// tente l'impossible.

import { ensureFreshToken, h, utilisateur } from '../app.js';

const API = '/api/public/tcg/decks';

function deckVide() {
  return { id: null, nom: 'Nouveau deck', heros: [], cartes: [] };
}

async function appel(methode, url, corps) {
  await ensureFreshToken();
  const jwt = localStorage.getItem('discord_jwt');
  const r = await fetch(url, {
    method: methode,
    headers: {
      ...(jwt ? { Authorization: `Bearer ${jwt}` } : {}),
      ...(corps ? { 'Content-Type': 'application/json' } : {}),
    },
    body: corps ? JSON.stringify(corps) : undefined,
  });
  const donnees = r.status === 204 ? null : await r.json().catch(() => null);
  if (!r.ok) {
    // Le serveur explique ses refus en français : le message part tel quel.
    const erreur = new Error((donnees && donnees.detail) || `Erreur ${r.status}`);
    erreur.statut = r.status;
    throw erreur;
  }
  return donnees;
}

/** L'éditeur. `heros` et `tactiques` sont les listes servies par les routes
 * des cartes : l'éditeur y retrouve le nom à afficher d'une clé. */
export function editeurDeck({ heros, tactiques }) {
  const parCle = new Map([...heros, ...tactiques].map((c) => [c.cle, c]));
  let limites = null;
  let decks = [];
  let deck = deckVide();
  let modifie = false;
  let vivant = true;
  const boutons = [];

  const choix = h('select', { class: 'wcd-choix', 'aria-label': 'Choisir un deck' });
  const nom = h('input', { class: 'wcd-nom', type: 'text', 'aria-label': 'Nom du deck' });
  const resume = h('span', { class: 'wcd-resume' });
  const emplacements = h('div', { class: 'wcd-heros' });
  const liste = h('div', { class: 'wcd-cartes' });
  const message = h('p', { class: 'wcd-message', role: 'status', 'aria-live': 'polite' });
  const enregistrer = h('button', { class: 'wcd-bouton wcd-bouton--or', type: 'button' });
  const supprimer = h('button', { class: 'wcd-bouton', type: 'button', text: 'Supprimer' });

  const dire = (texte, erreur) => {
    message.textContent = texte || '';
    message.classList.toggle('is-erreur', Boolean(erreur));
  };

  const pleinCartes = () => limites && deck.cartes.length >= limites.taille;
  const pleinHeros = () => limites && deck.heros.length >= limites.heros;

  function rafraichir() {
    if (!vivant) return;
    const connecte = Boolean(utilisateur());
    const tailleTxt = limites ? limites.taille : '…';
    const herosTxt = limites ? limites.heros : '…';
    resume.textContent = `${deck.nom || 'Sans nom'} · héros ${deck.heros.length}/${herosTxt} · cartes ${deck.cartes.length}/${tailleTxt}${modifie ? ' · non enregistré' : ''}`;
    if (document.activeElement !== nom) nom.value = deck.nom;
    if (limites) nom.maxLength = limites.nomMax;

    emplacements.textContent = '';
    for (let i = 0; i < (limites ? limites.heros : 3); i += 1) {
      const cle = deck.heros[i];
      emplacements.appendChild(h('div', { class: `wcd-emplacement${cle ? ' is-rempli' : ''}` },
        cle ? (parCle.get(cle)?.nom || cle) : 'Héros'));
    }

    liste.textContent = '';
    if (!deck.cartes.length) {
      liste.appendChild(h('span', { class: 'wcd-vide', text: 'Ajoute des cartes depuis la galerie.' }));
    }
    deck.cartes.forEach((cle) => {
      const carte = parCle.get(cle);
      liste.appendChild(h('button', {
        class: 'wcd-puce',
        type: 'button',
        title: 'Retirer du deck',
        onclick: () => basculer(cle, 'action'),
      }, carte ? carte.court : cle, h('span', { class: 'wcd-puce-x', 'aria-hidden': 'true', text: '×' })));
    });

    enregistrer.textContent = connecte ? 'Enregistrer' : 'Se connecter pour enregistrer';
    supprimer.hidden = !deck.id;

    choix.textContent = '';
    choix.appendChild(h('option', { value: '', text: '+ Nouveau deck', selected: !deck.id }));
    decks.forEach((d) => choix.appendChild(h('option', {
      value: String(d.id),
      text: `${d.nom}${d.complet ? '' : ' (incomplet)'}`,
      selected: d.id === deck.id,
    })));
    choix.disabled = !connecte;

    boutons.forEach(majBouton);
  }

  function majBouton({ bouton, carte, famille }) {
    const dans = (famille === 'heros' ? deck.heros : deck.cartes).includes(carte.cle);
    if (famille === 'heros' && !carte.jouable) {
      bouton.disabled = true;
      bouton.textContent = 'Pas encore jouable';
      bouton.classList.remove('is-dans');
      return;
    }
    const plein = famille === 'heros' ? pleinHeros() : pleinCartes();
    bouton.disabled = !dans && plein;
    bouton.textContent = dans ? 'Dans le deck' : (plein ? 'Deck plein' : 'Ajouter au deck');
    bouton.classList.toggle('is-dans', dans);
    bouton.setAttribute('aria-pressed', dans ? 'true' : 'false');
  }

  function basculer(cle, famille) {
    const cible = famille === 'heros' ? deck.heros : deck.cartes;
    const i = cible.indexOf(cle);
    if (i >= 0) cible.splice(i, 1);
    else if (!(famille === 'heros' ? pleinHeros() : pleinCartes())) cible.push(cle);
    modifie = true;
    dire('');
    rafraichir();
  }

  function ouvrir(d) {
    deck = d ? { id: d.id, nom: d.nom, heros: [...d.heros], cartes: [...d.cartes] } : deckVide();
    modifie = false;
    dire('');
    rafraichir();
  }

  async function chargerDecks() {
    if (!utilisateur() && !(await ensureFreshToken())) { decks = []; rafraichir(); return; }
    try {
      decks = (await appel('GET', API)).decks;
    } catch (e) {
      dire(`Tes decks n'ont pas pu être chargés : ${e.message}`, true);
    }
    rafraichir();
  }

  choix.addEventListener('change', () => {
    if (modifie && !window.confirm('Le deck en cours a des modifications non enregistrées. Les abandonner ?')) {
      choix.value = deck.id ? String(deck.id) : '';
      return;
    }
    ouvrir(decks.find((d) => String(d.id) === choix.value) || null);
  });

  nom.addEventListener('input', () => {
    deck.nom = nom.value;
    modifie = true;
    rafraichir();
  });

  enregistrer.addEventListener('click', async () => {
    if (!utilisateur() && !(await ensureFreshToken())) {
      window.location.href = '/api/chat/auth/login';
      return;
    }
    enregistrer.disabled = true;
    try {
      const corps = { nom: deck.nom, heros: deck.heros, cartes: deck.cartes };
      const { deck: range } = deck.id
        ? await appel('PUT', `${API}/${deck.id}`, corps)
        : await appel('POST', API, corps);
      decks = [range, ...decks.filter((d) => d.id !== range.id)];
      ouvrir(range);
      dire(range.complet ? 'Deck enregistré.' : 'Deck enregistré, encore incomplet.');
    } catch (e) {
      dire(e.message, true);
    } finally {
      enregistrer.disabled = false;
    }
  });

  supprimer.addEventListener('click', async () => {
    if (!deck.id || !window.confirm(`Supprimer le deck « ${deck.nom} » ?`)) return;
    try {
      await appel('DELETE', `${API}/${deck.id}`);
      decks = decks.filter((d) => d.id !== deck.id);
      ouvrir(null);
      dire('Deck supprimé.');
    } catch (e) {
      dire(e.message, true);
    }
  });

  const surAuth = () => { chargerDecks(); };
  window.addEventListener('wally-auth-changed', surAuth);

  const noeud = h('details', { class: 'wcd' },
    h('summary', { class: 'wcd-tete' },
      h('span', { class: 'wcd-titre', text: 'MON DECK' }),
      resume),
    h('div', { class: 'wcd-corps' },
      h('div', { class: 'wcd-ligne' }, choix, nom),
      h('div', { class: 'wcd-bloc' }, h('span', { class: 'wcd-etiquette', text: 'HÉROS' }), emplacements),
      h('div', { class: 'wcd-bloc' }, h('span', { class: 'wcd-etiquette', text: 'CARTES' }), liste),
      h('div', { class: 'wcd-ligne wcd-actions' }, enregistrer, supprimer),
      message,
    ),
  );

  fetch(`${API}/limites`)
    .then((r) => (r.ok ? r.json() : Promise.reject(new Error(`HTTP ${r.status}`))))
    .then((l) => { limites = l; rafraichir(); })
    .catch((e) => dire(`Les règles du deck n'ont pas pu être chargées : ${e.message}`, true));
  chargerDecks();
  rafraichir();

  return {
    noeud,
    /** Le bouton à poser sous une carte de la galerie. Il se tient à jour tout
     * seul quand le deck change. */
    bouton(carte, famille) {
      const bouton = h('button', {
        class: 'wcd-carte',
        type: 'button',
        onclick: (e) => { e.stopPropagation(); basculer(carte.cle, famille); },
      });
      const entree = { bouton, carte, famille };
      boutons.push(entree);
      majBouton(entree);
      return bouton;
    },
    /** Les boutons d'un onglet quitté ne doivent plus être tenus à jour. */
    oublierBoutons() { boutons.length = 0; },
    detruire() {
      vivant = false;
      boutons.length = 0;
      window.removeEventListener('wally-auth-changed', surAuth);
    },
  };
}
