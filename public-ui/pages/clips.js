// public-ui/pages/clips.js — les derniers clips de la chaîne
//
// Une vignette n'est PAS un lecteur : tant qu'on n'a pas cliqué, il n'y a que
// l'image de Twitch. Poser vingt `iframe` clips.twitch.tv au montage ferait
// vingt lecteurs vidéo sur une page qui en joue au plus un — et sur mobile,
// vingt fois le décor braise à repeindre.
//
// Les filtres travaillent sur la liste DÉJÀ chargée : la route publique sert
// les 90 derniers jours en un appel, trier ou restreindre ne coûte donc rien
// au serveur et rien au réseau. Une période au-delà de 90 jours n'existe pas —
// c'est le plafond côté Helix, qui exige une borne de fin.

import { brancherTilt, detacherTilt, h, pageFooter, sectionHead } from '../app.js';

const PAS = 12;
const PERIODES = [[7, '7 jours'], [30, '30 jours'], [90, '90 jours']];

let _clips = [];
let _filtres = [];
let _montres = 0;
let _tri = 'date';
let _jours = 90;
let _clippeur = '';
let _recherche = '';
let _grille = null;
let _btnPlus = null;
let _compte = null;
let _selClippeur = null;
let _enLecture = null;
let _debounce = null;

/** « 1 234 » plutôt que « 1234 » — c'est un nombre de vues, on le lit. */
function nombre(n) {
  return Number(n || 0).toLocaleString('fr-FR');
}

/** `0:42` à partir des secondes que Twitch renvoie en flottant. */
function duree(s) {
  const t = Math.max(0, Math.round(Number(s) || 0));
  return `${Math.floor(t / 60)}:${String(t % 60).padStart(2, '0')}`;
}

/** `created_at` est un ISO 8601 UTC (« 2026-08-30T21:14:07Z »). */
function dateCourte(iso) {
  if (!iso) return '';
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return '';
  return d.toLocaleDateString('fr-FR', { day: '2-digit', month: 'short', year: 'numeric' });
}

/** Minuscules sans accents : « pathfinder » doit trouver « Pathfinder », et
 *  « cailoux » doit trouver « caïloux ». */
function plier(t) {
  return String(t || '').toLowerCase().normalize('NFD').replace(/\p{Diacritic}/gu, '');
}

/** L'URL d'embed se construit ICI, à partir du seul slug.
 *
 *  `parent` DOIT être le domaine qui héberge la page, sinon Twitch refuse le
 *  lecteur avec un écran noir muet : `location.hostname` est la seule valeur
 *  qui reste juste derrière le tunnel comme en local.
 *
 *  Pas de `muted` : c'est déjà `false` chez Twitch. Le lecteur démarre quand
 *  même muet tant que le navigateur n'accorde pas l'autoplay sonore au
 *  domaine — ça se décide chez le visiteur, pas dans cette URL. */
function urlEmbed(slug) {
  const p = new URLSearchParams({
    clip: slug,
    parent: location.hostname,
    autoplay: 'true',
  });
  return 'https://clips.twitch.tv/embed?' + p.toString();
}

/** Coupe le lecteur en cours, s'il y en a un. Rappelable. */
function couperLecteur() {
  if (!_enLecture) return;
  const cadre = _enLecture.querySelector('.clip-media');
  if (cadre) cadre.textContent = '';
  _enLecture = null;
}

/** Remplace la vignette par le lecteur Twitch, et arrête le précédent.
 *
 *  Deux lecteurs qui parlent en même temps, ce n'est pas « deux clips » : c'est
 *  du bruit et deux flux vidéo. On remet le précédent en vignette. */
function lire(carte, clip) {
  if (_enLecture && _enLecture !== carte) {
    const rendue = vignette(_enLecture._clip);
    _enLecture.replaceWith(rendue);
    // La carte remise en vignette est NEUVE : sans ce rebranchement, la
    // première qu'on a lue serait la seule de la grille à ne plus bouger.
    brancherTilt(rendue.parentNode || undefined);
  }
  // Une vidéo ne bascule pas avec les autres : la faire tourner en 3D coûte
  // une composition de texture par image, et se regarde mal.
  detacherTilt(carte);
  _enLecture = carte;
  // Le lecteur REMPLACE le bouton, il ne se glisse pas dedans : un `iframe`
  // dans un `<button>` est invalide, et le gestionnaire du bouton continuerait
  // d'intercepter chaque clic sur le lecteur.
  carte.querySelector('.clip-media').replaceWith(
    h('div', { class: 'clip-media playing' },
      h('iframe', {
        class: 'clip-frame',
        src: urlEmbed(clip.id),
        title: clip.title || 'Clip Twitch',
        // `keyboard-map` n'est pas déléguée par défaut à un cadre d'une
        // autre origine : sans elle, le lecteur Twitch lève un
        // « getLayoutMap() must be called from a top-level browsing context »
        // dans la console du VISITEUR, à chaque clip lu.
        allow: 'autoplay; fullscreen; encrypted-media; keyboard-map',
        allowFullscreen: true,
        frameBorder: '0',
        scrolling: 'no',
      }),
    ),
  );
}

function vignette(clip) {
  const bouton = h('button', {
    class: 'clip-media',
    'aria-label': `Lire le clip « ${clip.title || 'sans titre'} »`,
  },
    clip.thumbnail_url
      ? h('img', { src: clip.thumbnail_url, alt: '', loading: 'lazy' })
      : h('div', { class: 'clip-vide' }),
    h('span', { class: 'clip-play', 'aria-hidden': 'true', text: '▶' }),
    h('span', { class: 'clip-duree', text: duree(clip.duration) }),
  );

  const carte = h('article', { class: 'clip-card', 'data-tilt': '1' },
    bouton,
    h('div', { class: 'clip-body' },
      h('h3', { class: 'clip-titre', text: clip.title || 'Sans titre' }),
      h('div', { class: 'clip-meta' },
        h('span', { class: 'clip-auteur', text: clip.creator || 'quelqu’un' }),
        h('span', { text: '·' }),
        h('span', { text: dateCourte(clip.created_at) }),
        h('span', { text: '·' }),
        h('span', { text: `${nombre(clip.views)} vue${clip.views > 1 ? 's' : ''}` }),
      ),
      clip.url
        ? h('a', { class: 'clip-lien', href: clip.url, target: '_blank', rel: 'noopener',
          text: 'Voir sur Twitch ↗' })
        : null,
    ),
  );
  // La carte porte son clip : quand on remet un lecteur en vignette, on n'a que
  // le nœud sous la main.
  carte._clip = clip;
  bouton.addEventListener('click', () => lire(carte, clip));
  return carte;
}

// ── Filtres ───────────────────────────────────────────────────────────────

function appliquerFiltres() {
  const limite = Date.now() - _jours * 86400000;
  const q = plier(_recherche.trim());
  _filtres = _clips.filter((c) => {
    if (_clippeur && c.creator !== _clippeur) return false;
    const t = new Date(c.created_at).getTime();
    // Une date illisible ne doit pas faire disparaître le clip : on ne l'exclut
    // que si on sait qu'elle est trop vieille.
    if (!Number.isNaN(t) && t < limite) return false;
    return !q || plier(c.title).includes(q);
  });
  _filtres.sort(_tri === 'vues'
    ? (a, b) => b.views - a.views
    : (a, b) => String(b.created_at).localeCompare(String(a.created_at)));
}

function rendreSuite() {
  const lot = _filtres.slice(_montres, _montres + PAS);
  lot.forEach((c) => _grille.appendChild(vignette(c)));
  _montres += lot.length;
  // Le routeur branche le relief au MONTAGE de la page ; ces cartes-ci sortent
  // d'un `fetch` et de chaque clic sur « Charger plus ». L'appel saute celles
  // qui sont déjà branchées.
  brancherTilt(_grille);
  _btnPlus.style.display = _montres < _filtres.length ? '' : 'none';
}

/** Rejoue les filtres et refait la grille depuis zéro. */
function relancer() {
  // La grille est sur le point d'être vidée : le lecteur en cours pointerait
  // sur un nœud détaché, dont le son continue jusqu'au passage du GC.
  couperLecteur();
  appliquerFiltres();
  _grille.textContent = '';
  _montres = 0;
  if (!_filtres.length) {
    _grille.appendChild(h('div', { class: 'empty', text: 'Aucun clip ne correspond.' }));
    _btnPlus.style.display = 'none';
  } else {
    rendreSuite();
  }
  const total = _clips.length;
  _compte.textContent = _filtres.length === total
    ? `${total} clip${total > 1 ? 's' : ''}`
    : `${_filtres.length} sur ${total}`;
}

/** Remplit la liste des clippeurs à partir de ce qui a été reçu.
 *
 *  Elle se DÉDUIT des clips, elle ne se maintient pas à la main : un nouveau
 *  clippeur apparaît tout seul, et personne ne reste dans la liste après être
 *  sorti de la fenêtre de 90 jours. */
function remplirClippeurs() {
  const comptes = new Map();
  _clips.forEach((c) => comptes.set(c.creator, (comptes.get(c.creator) || 0) + 1));
  const noms = [...comptes.entries()].sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]));
  _selClippeur.textContent = '';
  _selClippeur.appendChild(h('option', { value: '', text: 'Tout le monde' }));
  noms.forEach(([nom, n]) => {
    _selClippeur.appendChild(h('option', { value: nom, text: `${nom} (${n})` }));
  });
}

function barreFiltres() {
  const recherche = h('input', {
    type: 'search',
    class: 'chat-input clip-recherche',
    placeholder: 'Rechercher un titre…',
    'aria-label': 'Rechercher dans les titres de clips',
  });
  recherche.addEventListener('input', () => {
    clearTimeout(_debounce);
    _debounce = setTimeout(() => { _recherche = recherche.value; relancer(); }, 250);
  });

  _selClippeur = h('select', { class: 'champ', 'aria-label': 'Filtrer par clippeur' },
    h('option', { value: '', text: 'Tout le monde' }));
  _selClippeur.addEventListener('change', () => { _clippeur = _selClippeur.value; relancer(); });

  const periode = h('select', { class: 'champ', 'aria-label': 'Période' },
    ...PERIODES.map(([j, l]) => h('option', { value: String(j), text: l, selected: j === _jours })));
  periode.addEventListener('change', () => { _jours = Number(periode.value); relancer(); });

  const tris = h('div', { class: 'clip-tris' });
  [['Récents', 'date'], ['Plus vus', 'vues']].forEach(([libelle, valeur]) => {
    const b = h('button', { class: 'pill' + (valeur === _tri ? ' active' : ''), text: libelle });
    b.addEventListener('click', () => {
      _tri = valeur;
      tris.querySelectorAll('.pill').forEach((x) => x.classList.remove('active'));
      b.classList.add('active');
      relancer();
    });
    tris.appendChild(b);
  });

  return h('div', { class: 'clip-filtres' }, recherche, _selClippeur, periode, tris);
}

async function charger() {
  try {
    const r = await fetch('/api/public/twitch/clips');
    _clips = (await r.json()).clips || [];
  } catch (err) {
    console.warn('clips indisponibles', err);
    _grille.textContent = '';
    _grille.appendChild(h('div', { class: 'empty', text: 'Les clips sont momentanément indisponibles.' }));
    return;
  }
  if (!_clips.length) {
    _grille.textContent = '';
    _grille.appendChild(h('div', { class: 'empty', text: 'Aucun clip sur les trois derniers mois.' }));
    return;
  }
  remplirClippeurs();
  relancer();
}

export function mount(el) {
  _clips = [];
  _filtres = [];
  _montres = 0;
  _tri = 'date';
  _jours = 90;
  _clippeur = '';
  _recherche = '';
  _enLecture = null;

  _grille = h('div', { class: 'clip-grid mt-20' },
    h('div', { class: 'empty', text: 'Chargement des clips…' }));
  _btnPlus = h('button', { class: 'btn btn-ghost', text: 'Charger plus', style: 'display:none' });
  _btnPlus.addEventListener('click', rendreSuite);
  _compte = h('span', { class: 'clip-compte' });

  el.appendChild(h('section', { class: 'section', style: 'padding-top:140px; border-top:none' },
    h('div', { class: 'section-inner' },
      sectionHead('CLIPS', 'Les moments qu’on a gardés.',
        'Les derniers clips de la chaîne Azrael_TTV. Clique pour les lire ici.'),
      h('div', { class: 'clip-barre mt-48' }, barreFiltres(), _compte),
      _grille,
      h('div', { class: 'gal-more' }, _btnPlus),
    ),
  ));
  el.appendChild(pageFooter());

  charger();
}

export function unmount() {
  // Le routeur vide `#vue`, mais un `iframe` retiré du DOM sans être vidé garde
  // son flux vivant le temps que le GC passe : on coupe le son tout de suite.
  couperLecteur();
  clearTimeout(_debounce);
  _debounce = null;
  _clips = [];
  _filtres = [];
  _grille = null;
  _btnPlus = null;
  _compte = null;
  _selClippeur = null;
}
