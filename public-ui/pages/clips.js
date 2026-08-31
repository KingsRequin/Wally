// public-ui/pages/clips.js — les derniers clips de la chaîne
//
// Une vignette n'est PAS un lecteur : tant qu'on n'a pas cliqué, il n'y a que
// l'image de Twitch. Poser vingt `iframe` clips.twitch.tv au montage ferait
// vingt lecteurs vidéo sur une page qui en joue au plus un — et sur mobile,
// vingt fois le décor braise à repeindre.

import { h, pageFooter, sectionHead } from '../app.js';

const PAS = 12;

let _clips = [];
let _montres = 0;
let _grille = null;
let _btnPlus = null;
let _enLecture = null;

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

/** L'URL d'embed se construit ICI, à partir du seul slug.
 *
 *  `parent` DOIT être le domaine qui héberge la page, sinon Twitch refuse le
 *  lecteur avec un écran noir muet : `location.hostname` est la seule valeur
 *  qui reste juste derrière le tunnel comme en local. */
function urlEmbed(slug) {
  const p = new URLSearchParams({
    clip: slug,
    parent: location.hostname,
    autoplay: 'true',
    muted: 'false',
  });
  return 'https://clips.twitch.tv/embed?' + p.toString();
}

/** Remplace la vignette par le lecteur Twitch, et arrête le précédent.
 *
 *  Deux lecteurs qui parlent en même temps, ce n'est pas « deux clips » : c'est
 *  du bruit et deux flux vidéo. On remet le précédent en vignette. */
function lire(carte, clip) {
  if (_enLecture && _enLecture !== carte) _enLecture.replaceWith(vignette(_enLecture._clip));
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
        allow: 'autoplay; fullscreen; encrypted-media',
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

  const carte = h('article', { class: 'clip-card' },
    bouton,
    h('div', { class: 'clip-body' },
      h('h3', { class: 'clip-titre', text: clip.title || 'Sans titre' }),
      h('div', { class: 'clip-meta' },
        h('span', { class: 'clip-auteur', text: clip.creator || 'quelqu’un' }),
        h('span', { text: '·' }),
        h('span', { text: dateCourte(clip.created_at) }),
        h('span', { text: '·' }),
        h('span', { text: `${nombre(clip.views)} vues` }),
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

function rendreSuite() {
  const lot = _clips.slice(_montres, _montres + PAS);
  lot.forEach((c) => _grille.appendChild(vignette(c)));
  _montres += lot.length;
  _btnPlus.style.display = _montres < _clips.length ? '' : 'none';
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
  _grille.textContent = '';
  if (!_clips.length) {
    _grille.appendChild(h('div', { class: 'empty', text: 'Aucun clip sur les trois derniers mois.' }));
    return;
  }
  _montres = 0;
  rendreSuite();
}

export function mount(el) {
  _clips = [];
  _montres = 0;
  _enLecture = null;

  _grille = h('div', { class: 'clip-grid mt-48' },
    h('div', { class: 'empty', text: 'Chargement des clips…' }));
  _btnPlus = h('button', { class: 'btn btn-ghost', text: 'Charger plus', style: 'display:none' });
  _btnPlus.addEventListener('click', rendreSuite);

  el.appendChild(h('section', { class: 'section', style: 'padding-top:140px; border-top:none' },
    h('div', { class: 'section-inner' },
      sectionHead('CLIPS', 'Les moments qu’on a gardés.',
        'Les derniers clips de la chaîne Azrael_TTV. Clique pour les lire ici.'),
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
  if (_enLecture) {
    const cadre = _enLecture.querySelector('.clip-media');
    if (cadre) cadre.textContent = '';
  }
  _enLecture = null;
  _clips = [];
  _grille = null;
  _btnPlus = null;
}
