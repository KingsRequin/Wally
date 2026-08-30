// public-ui/pages/galerie.js — les images générées, page dédiée
//
// Tout ce que l'ancien onglet savait faire est ici : tri, recherche,
// pagination, vote et fiche détaillée. Seul l'habillage change.

import { h, nomBot, openModal, pageFooter, sectionHead, utilisateur } from '../app.js';

const LIMIT = 24;

let _tri = 'date';
let _offset = 0;
let _recherche = '';
let _grille = null;
let _btnPlus = null;
let _debounce = null;

function enTetes() {
  const jwt = localStorage.getItem('discord_jwt');
  return jwt ? { Authorization: 'Bearer ' + jwt } : {};
}

/** `fetch` qui rejoue UNE fois après un 401, le temps de rafraîchir le JWT. */
async function fetchAuth(url, options = {}) {
  const res = await fetch(url, { ...options, headers: { ...enTetes(), ...(options.headers || {}) } });
  if (res.status !== 401) return res;
  const refresh = localStorage.getItem('discord_refresh');
  if (!refresh) return res;
  try {
    const r = await fetch('/api/chat/auth/refresh', { headers: { Authorization: 'Bearer ' + refresh } });
    if (!r.ok) {
      localStorage.removeItem('discord_jwt');
      localStorage.removeItem('discord_refresh');
      return res;
    }
    const data = await r.json();
    if (data.jwt) localStorage.setItem('discord_jwt', data.jwt);
    if (data.refresh_token) localStorage.setItem('discord_refresh', data.refresh_token);
  } catch (err) {
    console.warn('rafraîchissement du jeton impossible', err);
    return res;
  }
  return fetch(url, { ...options, headers: { ...enTetes(), ...(options.headers || {}) } });
}

/** Message éphémère. Le visiteur vient de CLIQUER : sans retour, il croit
 *  avoir voté. */
function toast(msg) {
  const vieux = document.querySelector('.toast');
  if (vieux) vieux.remove();
  const el = h('div', { class: 'toast', text: msg });
  document.body.appendChild(el);
  requestAnimationFrame(() => el.classList.add('on'));
  setTimeout(() => { el.classList.remove('on'); setTimeout(() => el.remove(), 300); }, 2600);
}

/** `created_at` est un datetime SQL UTC (« 2026-08-27 22:38:20 »), pas un
 *  timestamp Unix. L'ancien onglet faisait `new Date(ts * 1000)` et affichait
 *  « Invalid Date » sous chaque image depuis le premier jour. */
function dateCourte(sql) {
  if (!sql) return '';
  const d = new Date(String(sql).replace(' ', 'T') + 'Z');
  if (Number.isNaN(d.getTime())) return '';
  return d.toLocaleDateString('fr-FR', { day: '2-digit', month: 'short', year: 'numeric' });
}

/** Bascule le vote et rend le nouveau compte, ou `null` si refusé. */
async function basculerVote(id, compteur) {
  if (!utilisateur()) { toast('Connecte-toi avec Discord pour voter'); return null; }
  try {
    const r = await fetchAuth(`/api/public/gallery/${id}/vote`, { method: 'POST' });
    if (r.status === 401) { toast('Session expirée, reconnecte-toi'); return null; }
    if (!r.ok) { toast('Vote impossible, réessaie dans un instant'); return null; }
    const res = await r.json();
    return { voted: !!res.voted, votes: res.voted ? compteur + 1 : Math.max(0, compteur - 1) };
  } catch (err) {
    toast('Vote impossible, réessaie dans un instant');
    console.warn('vote refusé', err);
    return null;
  }
}

// ── Fiche détaillée (modale partagée) ─────────────────────────────────────
async function ouvrirFiche(id) {
  let data = null;
  try {
    const res = await fetchAuth(`/api/public/gallery/${id}`);
    if (res.ok) data = await res.json();
  } catch (err) {
    console.warn("détail de l'image indisponible", err);
  }
  // Sans détail, la modale resterait ouverte et VIDE : on montre au moins
  // l'image, qui est ce que le visiteur a cliqué.
  if (!data) { openModal(`/api/public/gallery/${id}/image`, ''); return; }

  let votes = data.votes || 0;
  const compteur = h('span', { text: String(votes) });
  const bouton = h('button', { class: 'vote-btn' + (data.user_voted ? ' voted' : ''),
    style: 'align-self:flex-start' },
    h('span', { text: '♥' }), compteur);
  bouton.addEventListener('click', async () => {
    const res = await basculerVote(id, votes);
    if (!res) return;
    votes = res.votes;
    compteur.textContent = String(votes);
    bouton.classList.toggle('voted', res.voted);
  });

  const titre = data.title || data.prompt || '';
  const badges = [data.model, data.quality, data.size].filter(Boolean);
  const fiche = h('div', { class: 'fiche' },
    h('div', { class: 'fiche-titre', text: titre }),
    h('div', { class: 'fiche-meta' },
      data.username ? h('span', { text: data.username }) : null,
      data.username && data.created_at ? h('span', { text: '·' }) : null,
      data.created_at ? h('span', { text: dateCourte(data.created_at) }) : null,
    ),
    bouton,
    badges.length ? h('div', { class: 'fiche-badges' }, ...badges.map((b) => h('span', { class: 'tag', text: b }))) : null,
    // Le prompt complet n'a d'intérêt que s'il dit autre chose que le titre.
    (data.title && data.prompt && data.prompt !== data.title)
      ? h('p', { class: 'fiche-prompt', text: data.prompt })
      : null,
  );
  openModal(`/api/public/gallery/${id}/image`, fiche);
}

// ── Vignette ──────────────────────────────────────────────────────────────
function vignette(img) {
  let votes = img.votes || 0;
  const badge = h('button', {
    class: 'gal-votes' + (img.user_voted ? ' voted' : ''),
    'aria-label': 'Voter pour cette image',
    text: '♥ ' + votes,
  });
  badge.addEventListener('click', async (e) => {
    e.stopPropagation();
    const res = await basculerVote(img.id, votes);
    if (!res) return;
    votes = res.votes;
    badge.textContent = '♥ ' + votes;
    badge.classList.toggle('voted', res.voted);
  });

  const tuile = h('div', { class: 'gal-tile' },
    h('img', { src: `/api/public/gallery/${img.id}/image`, alt: img.title || img.prompt || '', loading: 'lazy' }),
    h('div', { class: 'gal-caption', text: img.title || img.prompt || '' }),
    badge,
  );
  tuile.addEventListener('click', () => ouvrirFiche(img.id));
  return tuile;
}

/** Charge une page d'images. Retourne `true` s'il en reste à charger. */
async function chargerImages(grille, ajouter) {
  const params = new URLSearchParams({ limit: LIMIT, offset: _offset, sort_by: _tri });
  if (_recherche.trim()) params.set('search', _recherche.trim());

  let images = [];
  try {
    const r = await fetchAuth('/api/public/gallery?' + params.toString());
    images = (await r.json()).images || [];
  } catch (err) {
    console.warn('galerie indisponible', err);
    if (!ajouter) {
      grille.textContent = '';
      grille.appendChild(h('div', { class: 'empty', text: 'La galerie est momentanément indisponible.' }));
    }
    return false;
  }

  if (!ajouter) grille.textContent = '';
  if (!images.length && !ajouter) {
    grille.appendChild(h('div', { class: 'empty', text: 'Aucune image ne correspond.' }));
    return false;
  }
  images.forEach((img) => grille.appendChild(vignette(img)));
  _offset += images.length;
  return images.length === LIMIT;
}

function relancer() {
  _offset = 0;
  chargerImages(_grille, false).then((reste) => { _btnPlus.style.display = reste ? '' : 'none'; });
}

export function mount(el) {
  _tri = 'date';
  _offset = 0;
  _recherche = '';

  _grille = h('div', { class: 'gal-grid mt-48' });
  _btnPlus = h('button', { class: 'btn btn-ghost', text: 'Charger plus', style: 'display:none' });
  _btnPlus.addEventListener('click', () => {
    chargerImages(_grille, true).then((reste) => { _btnPlus.style.display = reste ? '' : 'none'; });
  });

  const recherche = h('input', {
    type: 'search',
    class: 'chat-input',
    placeholder: 'Rechercher…',
    'aria-label': 'Rechercher dans la galerie',
    style: 'max-width:260px; padding:9px 16px; border-radius:999px; font-size:13px',
  });
  recherche.addEventListener('input', () => {
    clearTimeout(_debounce);
    _debounce = setTimeout(() => { _recherche = recherche.value; relancer(); }, 300);
  });

  const filtres = h('div', { class: 'gal-filters' }, recherche);
  [['Récentes', 'date'], ['Populaires', 'votes']].forEach(([libelle, valeur]) => {
    const b = h('button', { class: 'pill' + (valeur === _tri ? ' active' : ''), text: libelle });
    b.addEventListener('click', () => {
      _tri = valeur;
      filtres.querySelectorAll('.pill').forEach((x) => x.classList.remove('active'));
      b.classList.add('active');
      relancer();
    });
    filtres.appendChild(b);
  });

  el.appendChild(h('section', { class: 'section', style: 'padding-top:140px; border-top:none' },
    h('div', { class: 'section-inner' },
      h('div', { class: 'gal-bar' },
        sectionHead('GALERIE', 'Ce qu\'il a fabriqué.',
          `Les images générées par ${nomBot()}. Connecte ton Discord pour voter.`),
        filtres,
      ),
      _grille,
      h('div', { class: 'gal-more' }, _btnPlus),
    ),
  ));
  el.appendChild(pageFooter());

  relancer();
}

export function unmount() {
  clearTimeout(_debounce);
  _debounce = null;
  _grille = null;
  _btnPlus = null;
}
