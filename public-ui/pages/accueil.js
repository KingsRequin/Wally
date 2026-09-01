// public-ui/pages/accueil.js — la page longue
//
// Six sections, toutes alimentées par l'API publique. Rien n'est écrit en dur
// ici de ce qui a une source : les compteurs, les émotions, le fil cognitif,
// les images et le journal viennent du bot. Les textes de présentation, eux,
// décrivent ce qui EXISTE — pas une feuille de route.

import {
  connectCognitiveSSE, emotions, h, nomBot,
  onEmotionUpdate, openModal, pageFooter, sectionHead, surAnimation,
} from '../app.js';
import { renderMarkdown } from '../markdown.js';

// ── État du module ────────────────────────────────────────────────────────
let _pollStatut = null;
let _pollHistorique = null;
let _desabonnerEmo = null;
let _sseCognitif = null;
let _evenements = [];
let _avantId = null;      // pagination du fil vers le passé
let _chargeEnCours = false;
let _historiqueEmo = null;
let _refs = {};
let _observerCourbe = null;
let _desabonnerAnim = null;
let _premierStatut = true;

// ── Constantes d'affichage ────────────────────────────────────────────────
const EMO_LABELS = {
  curiosity: 'CURIOSITÉ', joy: 'JOIE', anger: 'COLÈRE', sadness: 'TRISTESSE', boredom: 'ENNUI',
};
const EMO_NOMS = {
  curiosity: 'Curiosité', joy: 'Joie', anger: 'Colère', sadness: 'Tristesse', boredom: 'Ennui',
};
const EMO_COULEURS = {
  curiosity: '#46d9ff', joy: '#ffb02e', anger: '#ff3d6e', sadness: '#8b7cff', boredom: '#6f6a7a',
};

// Un type d'événement cognitif = une couleur et un mot. Le mot est ce que le
// visiteur lit ; le type brut ne lui dit rien.
const FEED_META = {
  ATTN:   { c: '#46d9ff', k: 'ATTN' },
  THINK:  { c: '#ffb02e', k: 'THINK' },
  DECIDE: { c: '#ff6a2b', k: 'DECIDE' },
  SPEAK:  { c: '#7de3a4', k: 'SPEAK' },
  ACT:    { c: '#7de3a4', k: 'ACT' },
  REACT:  { c: '#7de3a4', k: 'REACT' },
  DM:     { c: '#46d9ff', k: 'DM' },
  DM_SUPPRESSED: { c: '#6f6a7a', k: 'DM×' },
  EVOLVE: { c: '#ff8a3d', k: 'EVOLVE' },
  SLEEP:  { c: '#6f6a7a', k: 'SLEEP' },
  CODEFIX: { c: '#8b7cff', k: 'FIX' },
  RSS:    { c: '#ffb02e', k: 'RSS' },
};

const BOUCLE = [
  { n: '01', k: 'ATTN',   d: "Ce qui se passe mérite-t-il qu'il lève la tête ?" },
  { n: '02', k: 'THINK',  d: 'Fil de pensée intérieur, mémoire consultée.' },
  { n: '03', k: 'DECIDE', d: 'Parler, agir, ou garder le silence.' },
  { n: '04', k: 'SPEAK',  d: 'La réponse passe par sa voix, pas la tienne.' },
  { n: '05', k: 'ACT',    d: 'Rappel, image, recherche, note, correctif.' },
];

const TROIS_VERBES = [
  {
    t: 'Il perçoit',
    d: 'Capture passive de tous les salons publics, Discord comme Twitch. Images décrites, langue détectée, plateforme taguée.',
    fond: 'rgba(255,106,43,.07)',
  },
  {
    t: 'Il se souvient',
    d: "Faits sujet-prédicat-objet en base, dédupliqués, datés, périmables. Il sait où il a appris chaque chose et oublie ce qui ne vaut plus.",
    fond: 'rgba(255,176,46,.07)',
  },
  {
    t: 'Il agit',
    d: 'Rappels planifiés, images générées, recherche web, notes, modération du spam. Et, avec autorisation, son propre code.',
    fond: 'rgba(255,61,110,.07)',
  },
];

const MARQUEE = [
  { t: 'IL PERÇOIT',      c: 'rgba(255,255,255,.06)' },
  { t: 'IL SE SOUVIENT',  c: 'rgba(255,106,43,.28)' },
  { t: 'IL RESSENT',      c: 'rgba(255,255,255,.06)' },
  { t: 'IL DÉCIDE',       c: 'rgba(255,176,46,.26)' },
  { t: 'IL SE TAIT',      c: 'rgba(255,255,255,.06)' },
  { t: 'IL AGIT',         c: 'rgba(255,61,110,.24)' },
];

const PILE = [
  'Python / asyncio', 'DeepSeek', 'aiosqlite', 'SQLite FTS5', 'discord.py', 'twitchio', 'Azure Speech', 'FastAPI',
];

const PILIERS = [
  {
    tag: 'MÉMOIRE', c: 'var(--violet)', t: 'Une mémoire par personne',
    d: "Recherche plein-texte FTS5 sur des faits sujet-prédicat-objet. Biographie, préférences, langue habituelle, relation : indexés et retrouvés par pertinence, dans un budget de tokens priorisé.",
  },
  {
    tag: 'ÉMOTIONS', c: 'var(--rose)', t: 'Cinq émotions en concurrence',
    d: "Elles décroissent de façon exponentielle, s'érodent mutuellement et se disputent le micro. Elles modulent le ton, jamais ne le colorent par défaut.",
  },
  {
    tag: 'PERSONA', c: 'var(--gold)', t: 'Une personnalité en quatre blocs',
    d: 'SOUL, IDENTITY, VOICE, EXEMPLES. Deux émotions dominantes en même temps activent une directive composite qui prime sur les directives simples.',
  },
  {
    tag: 'JOURNAL', c: 'var(--green)', t: 'Un journal chaque soir',
    d: "À 21 h, il écrit sa journée : interactions marquantes, état émotionnel, visites Twitch. Ce récit nourrit sa cohérence dans le temps, et se lit plus bas.",
  },
  {
    tag: 'MULTI-PLATEFORME', c: 'var(--cyan)', t: 'Un seul lui, deux mondes',
    d: 'Un unique processus asyncio tient Discord et Twitch. Mémoire, émotions et personnalité sont partagées : il reste le même en stream et en salon.',
  },
  {
    tag: 'VOCAL', c: 'var(--ember-lit)', t: 'Il parle pour de vrai',
    d: "Il rejoint un salon vocal, transcrit en direct et répond à voix haute. Transcription sur GPU distant avec repli local, synthèse jouée dès les premiers mots.",
  },
];

const RETIENT = ['Les faits biographiques', 'Les préférences', 'La langue habituelle', 'La relation : confiance, affinité'];
const IGNORE = ['Les messages trop courts', 'Les emojis seuls et les interjections', 'Les GIF et liens médias', 'Les bots et comptes non humains'];

// ── Formatage ─────────────────────────────────────────────────────────────
function formatUptime(secondes) {
  if (!secondes) return '—';
  const j = Math.floor(secondes / 86400);
  const hh = Math.floor((secondes % 86400) / 3600);
  const m = Math.floor((secondes % 3600) / 60);
  if (j > 0) return [String(j), h('span', { class: 'unit', text: 'j' }), ' ', String(hh), h('span', { class: 'unit', text: 'h' })];
  if (hh > 0) return [String(hh), h('span', { class: 'unit', text: 'h' }), ' ', String(m), h('span', { class: 'unit', text: 'm' })];
  return [String(m), h('span', { class: 'unit', text: 'm' })];
}

// Le CONTEXTE d'un événement : où, à qui, à propos de quoi. Il partait
// autrefois en tête du texte, si bien qu'une pensée longue commençait par
// « #general » puis se faisait couper à droite par le tag de type. Il monte
// avec l'heure sur la ligne des métadonnées, et la sortie garde la largeur.
function contexteEvenement(e) {
  if (e.type === 'SPEAK') return e.channel ? '#' + e.channel : '→ chat';
  if (e.type === 'REACT') return e.emoji || '';
  if (e.type === 'DM') return '→ ' + (e.target || 'créateur');
  if (e.type === 'DM_SUPPRESSED') return 'retenu : ' + (e.reason || '');
  if (e.type === 'ATTN') return e.target || '';
  if (e.type === 'EVOLVE') return 'persona';
  if (e.type === 'RSS') return e.feed || '';
  return e.channel ? '#' + e.channel : '';
}

// La SORTIE : ce que Wally a pensé, dit ou fait, et rien d'autre.
function texteEvenement(e) {
  if (e.type === 'THINK') return e.text || '';
  if (e.type === 'REACT') return e.detail || 'a réagi';
  if (e.type === 'DM' || e.type === 'DM_SUPPRESSED') return e.message || '';
  if (e.type === 'ATTN') return e.content_snippet || '';
  if (e.type === 'DECIDE') return (e.actions || []).join(' · ');
  if (e.type === 'RSS') return e.content_snippet || '';
  return e.detail || e.text || e.message || '';
}

/** Texte complet du dépliage, s'il dit autre chose que l'extrait affiché. */
function texteComplet(e) {
  const full = e.full;
  return (full && full !== (e.detail || '') && full !== texteEvenement(e)) ? full : null;
}

function signature(e) {
  return (e.type || '') + '|' + (e.text || e.detail || e.message || e.content_snippet || '');
}

// ── Héros ─────────────────────────────────────────────────────────────────
function bandeauStats() {
  const cellule = (libelle, id) => {
    const valeur = h('div', { class: 'stat-value', text: '—' });
    _refs[id] = valeur;
    return h('div', { class: 'stat-cell' }, h('div', { class: 'label', text: libelle }), valeur);
  };
  return h('div', { class: 'stat-strip' },
    // `total_messages` est bien un total de tous les temps depuis que le
    // compteur est persisté dans `bot_state` (report relu au boot + cycle
    // courant). Il l'a longtemps annoncé sans l'être : quinze minutes après un
    // rebuild, la vitrine affichait « 1 ».
    cellule('MESSAGES TRAITÉS', 'statMsg'),
    cellule('VIEWERS (LIVE)', 'statViewers'),
    cellule('TEMPS DE RÉPONSE', 'statLatence'),
    cellule('UPTIME', 'statUptime'),
  );
}

function heros() {
  return h('section', { class: 'section hero', id: 'a-top' },
    h('div', { class: 'hero-ring r1', 'data-px': '0.30' }),
    h('div', { class: 'hero-ring r2', 'data-px': '0.46' }),
    h('div', { class: 'hero-ring r3', 'data-px': '0.62' }),
    h('div', { class: 'hero-badge', 'data-px': '0.16' },
      h('span', { class: 'dot' }), 'DISCORD · TWITCH · VOCAL · MÉMOIRE'),
    h('h1', { class: 'h1', 'data-px': '0.10' },
      "Il n'attend pas", h('br'), 'qu\'on lui ', h('span', { class: 'flame-text', text: 'parle' }), '.'),
    h('p', { class: 'lead lead-center reveal', 'data-px': '0.05', text:
      `${nomBot()} perçoit tous les salons, se souvient de chacun, ressent ce qui s'y passe, `
      + "et décide seul du moment où il vaut mieux parler. Ou se taire." }),
    h('div', { class: 'hero-cta reveal', style: 'justify-content:center' },
      h('a', { class: 'btn btn-primary', href: '/chat', 'data-route': '/chat', text: `Parler à ${nomBot()}` }),
      h('a', { class: 'btn btn-ghost', href: '#a-cerveau', text: 'Voir son cerveau penser' }),
    ),
    bandeauStats(),
  );
}

// ── 01 · boucle cognitive ─────────────────────────────────────────────────
function sectionCerveau() {
  const corps = h('div', { class: 'feed-body' },
    h('div', { class: 'feed-text', text: 'en attente de pensées…' }));
  corps.addEventListener('scroll', () => { if (corps.scrollTop < 40) chargerPlusDeFil(corps); });
  _refs.feed = corps;

  // Le fil qui se remplit au-dessus des cinq étapes : il DIT que la boucle
  // tourne, là où cinq cartes immobiles disent qu'elle est un schéma.
  const fil = h('div', { class: 'wire-fill' });
  _refs.wire = fil;

  return h('section', { class: 'section', id: 'a-cerveau' },
    h('div', { class: 'section-inner' },
      sectionHead('01 · BOUCLE COGNITIVE',
        'Une boucle tourne en continu, même quand le salon est vide.',
        "Cinq étapes, en permanence. Il évalue ce qui mérite son attention, réfléchit, décide s'il a "
        + 'quelque chose à dire, puis parle ou agit. Le droit au silence est une étape à part entière.'),
      h('div', { class: 'grid grid-5 loop-grid mt-48' },
        h('div', { class: 'wire' }, fil),
        ...BOUCLE.map((s) => h('div', { class: 'loop-card reveal', 'data-tilt': '1' },
          h('div', { class: 'label', text: s.n }),
          h('div', { class: 'loop-key', text: s.k }),
          h('div', { class: 'loop-desc', text: s.d }),
          h('div', { class: 'loop-underline' }),
        )),
      ),
      h('div', { class: 'feed mt-16 reveal', 'data-tilt': '1' },
        h('div', { class: 'feed-head' },
          h('div', { class: 'feed-live' }, h('span', { class: 'dot' }), 'FLUX COGNITIF EN DIRECT'),
          h('div', { class: 'label', style: 'letter-spacing:.04em', text: '/api/public/sse/cognitive' }),
        ),
        corps,
      ),
      h('div', { class: 'grid grid-3 mt-16' },
        ...TROIS_VERBES.map((v) => h('div', {
          class: 'card reveal', 'data-tilt': '1',
          style: `background:linear-gradient(180deg, ${v.fond}, rgba(255,255,255,.015))`,
        },
        h('div', { class: 'h3', text: v.t }),
        h('p', { class: 'lead lead-sm', text: v.d }),
        )),
      ),
    ),
  );
}

// Au-delà, la ligne du flux est repliée à trois lignes et cliquable. Un
// message court (« a réagi », un nom d'action) n'a rien à replier.
const REPLI_MAX = 160;

function metaEvenement(type) {
  return FEED_META[type] || { c: 'var(--soft)', k: (type || '·').slice(0, 6) };
}

/** Une entrée du flux. Deux lignes et non trois colonnes : à 390 px, l'heure
 *  et un tag de 92 px mangeaient la moitié de la largeur, et il restait une
 *  colonne de mots pour la pensée elle-même.
 */
function construireLigne(e) {
  const meta = metaEvenement(e.type);
  const complet = texteComplet(e);
  const texte = (e._deplie && complet) ? complet : texteEvenement(e);
  const contexte = contexteEvenement(e);
  // Une pensée de Wally pèse 2 400 caractères et porte VINGT retours à la
  // ligne — mesuré sur le flux de prod le 2026-09-01. Rendus tels quels, le
  // HTML écrasait les retours et la page affichait deux cents pavés d'un bloc :
  // illisible, et deux cents fois la hauteur d'un écran à disposer à chaque
  // défilement. Repliée à trois lignes, la même entrée se lit d'un coup d'œil
  // et se déplie au clic.
  const long = Boolean(complet) || texte.length > REPLI_MAX || texte.includes('\n');
  const ligne = h('div', {
    class: 'feed-row' + (long ? ' clickable' : ''),
    style: `--type: ${meta.c}`,
  },
  h('div', { class: 'feed-meta' },
    h('span', { class: 'feed-time', text: e._t || '' }),
    h('span', { class: 'feed-tag', text: meta.k }),
    contexte ? h('span', { class: 'feed-ou', text: contexte }) : null,
  ),
  // L'indice de dépliage est un mot, pas un « … » noyé dans la phrase : au
  // doigt, il n'y a ni survol ni `title`, et rien ne disait qu'il restait
  // quelque chose à lire. Il vit HORS du texte : le repli est un
  // `-webkit-line-clamp`, qui pose son propre « … » et masquerait un enfant
  // laissé à l'intérieur.
  h('div', { class: 'feed-text' + (long && !e._deplie ? ' replie' : '') }, texte),
  long ? h('div', { class: 'feed-plus', text: e._deplie ? '↑ replier' : '… déplier' }) : null,
  );
  if (long) {
    ligne.title = 'cliquer pour ' + (e._deplie ? 'replier' : 'déplier');
    // Le clic REMPLACE sa propre ligne au lieu de redessiner les deux cents :
    // déplier une pensée ne regarde que celle-là.
    ligne.addEventListener('click', () => {
      e._deplie = !e._deplie;
      ligne.replaceWith(construireLigne(e));
    });
  }
  return ligne;
}

/** Ajoute la DERNIÈRE entrée, sans toucher aux précédentes.
 *
 *  Le flux se redessinait en entier à chaque événement SSE : deux cents lignes
 *  de quatre nœuds jetées et reconstruites pour une pensée de plus, plusieurs
 *  fois par minute. C'est le geste du journal admin — on ajoute en bas, on
 *  retire en haut — et c'est ce qui rend le panneau gratuit entre deux
 *  événements.
 */
function ajouterLigne(e) {
  const liste = _refs.feed;
  if (!liste) return false;
  // Une liste encore vide porte le message d'attente : elle passe par le
  // rendu complet, qui sait l'effacer.
  if (!liste.firstElementChild || !liste.firstElementChild.classList.contains('feed-row')) {
    return false;
  }
  const enBas = liste.scrollHeight - liste.scrollTop - liste.clientHeight < 40;
  liste.appendChild(construireLigne(e));
  while (liste.children.length > 200) liste.removeChild(liste.firstChild);
  if (enBas) liste.scrollTop = liste.scrollHeight;
  return true;
}

function rendreFil() {
  const liste = _refs.feed;
  if (!liste) return;
  // Capture AVANT le vidage : `textContent = ''` remet `scrollTop` à 0.
  const avant = liste.scrollTop;
  const enBas = !avant || liste.scrollHeight - avant - liste.clientHeight < 40;
  liste.textContent = '';

  if (!_evenements.length) {
    liste.appendChild(h('div', { class: 'feed-text', text: 'en attente de pensées…' }));
    return;
  }

  // Plus ancien en haut, plus récent en bas — lecture de terminal.
  _evenements.slice(0, 200).reverse().forEach((e) => {
    liste.appendChild(construireLigne(e));
  });

  liste.scrollTop = enBas ? liste.scrollHeight : avant;
}

function pousserEvenement(e) {
  // Le SSE rejoue son tampon récent au branchement, qui recoupe l'historique
  // déjà chargé → on ignore un événement identique aux 40 plus récents.
  const sig = signature(e);
  for (let i = 0; i < Math.min(_evenements.length, 40); i++) {
    if (signature(_evenements[i]) === sig) return;
  }
  e._t = new Date().toLocaleTimeString('fr-FR');
  _evenements.unshift(e);
  if (_evenements.length > 300) _evenements.length = 300;
  if (!ajouterLigne(e)) rendreFil();
}

async function amorcerFil() {
  try {
    const data = await (await fetch('/api/public/cognitive/history?limit=40')).json();
    _evenements = (data.events || []).map((e) => ({
      ...e,
      _t: e.ts ? new Date(e.ts * 1000).toLocaleTimeString('fr-FR') : '',
    }));
    _avantId = data.next_before !== undefined ? data.next_before : null;
    rendreFil();
  } catch (err) {
    // Le fil restera vide jusqu'au premier événement SSE.
    console.warn('historique du fil cognitif indisponible', err);
  }
}

async function chargerPlusDeFil(liste) {
  if (_chargeEnCours || _avantId === null || _avantId === undefined) return;
  _chargeEnCours = true;
  try {
    const data = await (await fetch('/api/public/cognitive/history?limit=40&before=' + _avantId)).json();
    const evts = data.events || [];
    if (!evts.length) { _avantId = null; return; }
    const hAvant = liste.scrollHeight;
    evts.forEach((e) => _evenements.push({
      ...e,
      _t: e.ts ? new Date(e.ts * 1000).toLocaleTimeString('fr-FR') : '',
    }));
    _avantId = data.next_before !== undefined ? data.next_before : null;
    rendreFil();
    // Compense l'ajout en haut pour ne pas faire sauter la vue.
    liste.scrollTop += liste.scrollHeight - hAvant;
  } catch (err) {
    console.warn('page suivante du fil indisponible', err);
  } finally {
    _chargeEnCours = false;
  }
}

// ── bandeau défilant ──────────────────────────────────────────────────────
function bandeauDefilant() {
  const piste = h('div', { class: 'marquee-track' },
    ...MARQUEE.concat(MARQUEE).map((w) => h('span', { class: 'marquee-word', style: `color:${w.c}`, text: w.t })),
  );
  _refs.marquee = piste;
  return h('div', { class: 'marquee' }, piste);
}

// ── 02 · état émotionnel ──────────────────────────────────────────────────
function sectionEmotions() {
  const jauges = h('div', { style: 'margin-top:32px' });
  _refs.jauges = jauges;
  const nom = h('div', { class: 'mood-name', text: '—' });
  _refs.moodNom = nom;

  const courbe = h('canvas', { class: 'emo-chart' });
  _refs.courbe = courbe;

  const tete = h('div', { style: 'margin-top:14px; display:flex; flex-direction:column; gap:10px' },
    h('div', { class: 'feed-text', text: 'chargement…' }));
  _refs.tete = tete;

  return h('section', { class: 'section', id: 'a-statut' },
    h('div', { class: 'section-halos', 'aria-hidden': 'true' },
      h('div', { class: 'section-halo halo-cyan', 'data-px': '0.20' })),
    h('div', { class: 'section-inner' },
      sectionHead('02 · ÉTAT ÉMOTIONNEL',
        'Cinq émotions qui décroissent, se suppriment et se disputent le micro.'),
      h('div', { class: 'grid grid-emo mt-48' },
        h('div', { class: 'card reveal', 'data-tilt': '1', style: 'padding:30px 30px 34px' },
          h('div', { class: 'card-top' },
            h('div', { class: 'label', text: 'HUMEUR DOMINANTE' }),
            h('div', { style: 'font-size:13px; color:var(--dim)', text: 'maintenant' }),
          ),
          nom,
          jauges,
        ),
        h('div', { style: 'display:flex; flex-direction:column; gap:16px' },
          h('div', { class: 'card reveal', 'data-tilt': '1', style: 'padding:26px' },
            h('div', { class: 'label', text: '24 DERNIÈRES HEURES' }),
            courbe,
          ),
          h('div', { class: 'card reveal', 'data-tilt': '1', style: 'padding:26px' },
            h('div', { class: 'label', text: 'DANS SA TÊTE, LÀ' }),
            tete,
          ),
        ),
      ),
    ),
  );
}

function rendreJauges() {
  const hote = _refs.jauges;
  if (!hote) return;
  hote.textContent = '';
  let dominante = null;
  Object.keys(EMO_LABELS).forEach((cle) => {
    const v = emotions[cle] || 0;
    if (!dominante || v > (emotions[dominante] || 0)) dominante = cle;
    const barre = h('div', { class: 'gauge-fill', style: `background:${EMO_COULEURS[cle]}; box-shadow:0 0 14px ${EMO_COULEURS[cle]}` });
    hote.appendChild(h('div', { class: 'gauge' },
      h('div', { class: 'gauge-head' },
        h('span', { text: EMO_LABELS[cle] }),
        h('span', { class: 'val', text: v.toFixed(2) }),
      ),
      h('div', { class: 'gauge-track' }, barre),
    ));
    // Posée au tick suivant : une largeur écrite au montage ne s'anime pas.
    requestAnimationFrame(() => { barre.style.width = Math.round(v * 100) + '%'; });
  });
  if (_refs.moodNom && dominante) {
    _refs.moodNom.textContent = EMO_NOMS[dominante];
    _refs.moodNom.style.color = EMO_COULEURS[dominante];
  }
}

function tracerCourbe() {
  const canvas = _refs.courbe;
  if (!canvas || !_historiqueEmo || _historiqueEmo.length < 2) return;
  const dpr = window.devicePixelRatio || 1;
  const W = canvas.clientWidth || 400;
  const H = canvas.clientHeight || 160;
  canvas.width = W * dpr;
  canvas.height = H * dpr;
  const ctx = canvas.getContext('2d');
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  ctx.clearRect(0, 0, W, H);

  const PAD = { top: 10, right: 8, bottom: 22, left: 8 };
  const cW = W - PAD.left - PAD.right;
  const cH = H - PAD.top - PAD.bottom;
  const n = _historiqueEmo.length;
  const xOf = (i) => PAD.left + (i / (n - 1)) * cW;
  const yOf = (v) => PAD.top + cH - v * cH;

  ctx.strokeStyle = 'rgba(255,255,255,.07)';
  ctx.lineWidth = 1;
  for (let v = 0; v <= 1; v += 0.25) {
    ctx.beginPath();
    ctx.moveTo(PAD.left, yOf(v));
    ctx.lineTo(PAD.left + cW, yOf(v));
    ctx.stroke();
  }
  Object.keys(EMO_COULEURS).forEach((cle) => {
    ctx.beginPath();
    ctx.lineWidth = 1.6;
    ctx.strokeStyle = EMO_COULEURS[cle];
    ctx.globalAlpha = .9;
    _historiqueEmo.forEach((snap, i) => {
      const x = xOf(i);
      const y = yOf(snap[cle] || 0);
      if (i === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
    });
    ctx.stroke();
  });
  ctx.globalAlpha = 1;

  const tMin = _historiqueEmo[0].snapshot_at;
  const tMax = _historiqueEmo[n - 1].snapshot_at;
  ctx.fillStyle = 'rgba(164,158,174,.55)';
  ctx.font = "10px 'JetBrains Mono', monospace";
  ctx.textAlign = 'center';
  [tMin, (tMin + tMax) / 2, tMax].forEach((t) => {
    const x = PAD.left + ((t - tMin) / (tMax - tMin || 1)) * cW;
    const d = new Date(t * 1000);
    ctx.fillText(d.getHours() + 'h' + String(d.getMinutes()).padStart(2, '0'), x, H - 5);
  });
}

async function chargerHistoriqueEmo() {
  try {
    const r = await fetch('/api/public/emotions/history?since=' + Math.floor(Date.now() / 1000 - 86400));
    _historiqueEmo = ((await r.json()).history || []).filter((s) => s.snapshot_at);
    tracerCourbe();
  } catch (err) {
    // La courbe reste absente — repli voulu, mais qui ne doit pas être
    // indiscernable d'un « pas encore assez de points ».
    console.warn('historique des émotions indisponible', err);
  }
}

async function chargerTete() {
  const hote = _refs.tete;
  if (!hote) return;
  let data = null;
  try { data = await (await fetch('/api/public/cognitive/goal')).json(); }
  catch (err) { console.warn('objectifs indisponibles', err); }

  hote.textContent = '';
  if (!data) {
    hote.appendChild(h('div', { class: 'feed-text', text: 'indisponible pour le moment.' }));
    return;
  }
  const bloc = (titre, items, vide) => {
    hote.appendChild(h('div', { class: 'label', style: 'color:var(--gold)', text: titre }));
    if (!items || !items.length) {
      hote.appendChild(h('div', { style: 'font-size:14px; color:var(--dim)', text: vide }));
      return;
    }
    items.forEach((it) => hote.appendChild(
      h('div', { style: 'font-size:14.5px; line-height:1.55; color:var(--text-3)', text: '· ' + it })));
  };
  bloc('SON BUT', data.goals, 'il vagabonde, aucun but fixé.');
  bloc('SA PRÉOCCUPATION', data.preoccupation ? [data.preoccupation] : [], 'rien ne le préoccupe là.');
}

// ── 03 · chat web ─────────────────────────────────────────────────────────
function sectionChat() {
  const etat = h('div', { class: 'state', text: 'MÉMOIRE CHARGÉE' });
  _refs.chatEtat = etat;
  return h('section', { class: 'section', id: 'a-chat' },
    h('div', { class: 'section-inner' },
      sectionHead('03 · CHAT WEB', 'La même mémoire, depuis le navigateur.',
        `Connecte ton compte Discord : ${nomBot()} te reconnaît, retrouve ce qu'il sait de toi, `
        + "et continue la conversation là où elle s'était arrêtée."),
      h('div', { class: 'chat-band mt-48 reveal', 'data-tilt': '1' },
        h('div', { class: 'who' },
          h('video', { src: '/wally.webm', autoplay: true, loop: true, muted: true, playsInline: true, 'aria-hidden': 'true' }),
          h('div', {},
            h('div', { class: 'h3', text: 'Il attend ton message.' }),
            etat,
          ),
        ),
        h('a', { class: 'btn btn-primary', href: '/chat', 'data-route': '/chat', text: 'Ouvrir le chat' }),
      ),
    ),
  );
}

// ── 04 · galerie ──────────────────────────────────────────────────────────
function sectionGalerie() {
  const grille = h('div', { class: 'gal-grid mt-48' });
  _refs.galerie = grille;
  return h('section', { class: 'section', id: 'a-galerie' },
    h('div', { class: 'section-inner' },
      sectionHead('04 · GALERIE', "Ce qu'il a fabriqué."),
      grille,
      h('div', { class: 'gal-more' },
        h('a', { class: 'btn btn-ghost', href: '/galerie', 'data-route': '/galerie', text: 'Voir la galerie' })),
    ),
  );
}

async function chargerApercuGalerie() {
  const grille = _refs.galerie;
  if (!grille) return;
  let images = [];
  try {
    const r = await fetch('/api/public/gallery?limit=8&offset=0&sort_by=date');
    images = (await r.json()).images || [];
  } catch (err) {
    console.warn('aperçu de la galerie indisponible', err);
  }
  grille.textContent = '';
  if (!images.length) {
    grille.appendChild(h('div', { class: 'empty', text: "Aucune image générée pour l'instant." }));
    return;
  }
  images.forEach((img) => {
    const legende = img.title || img.prompt || '';
    const tuile = h('div', { class: 'gal-tile' },
      h('img', { src: `/api/public/gallery/${img.id}/image`, alt: legende, loading: 'lazy' }),
      h('div', { class: 'gal-caption', text: legende }),
      h('div', { class: 'gal-votes', text: '♥ ' + (img.votes || 0) }),
    );
    // L'aperçu montre, la page dédiée fait voter : un clic ouvre l'image,
    // le bouton du bas mène à la galerie complète.
    tuile.addEventListener('click', () => openModal(`/api/public/gallery/${img.id}/image`, legende));
    grille.appendChild(tuile);
  });
}

// ── 05 · journal ──────────────────────────────────────────────────────────
function sectionJournal() {
  const jours = h('div', { class: 'days mt-48 reveal' });
  const entree = h('div', { class: 'mt-16' },
    h('div', { class: 'empty', text: 'Chargement du journal…' }));
  _refs.jours = jours;
  _refs.entree = entree;
  return h('section', { class: 'section', id: 'a-journal' },
    h('div', { class: 'section-halos', 'aria-hidden': 'true' },
      h('div', { class: 'section-halo halo-rose', 'data-px': '0.22' })),
    h('div', { class: 'section-inner' },
      sectionHead('05 · JOURNAL', "Chaque soir à 21 h, il écrit sa journée."),
      jours,
      entree,
    ),
  );
}

const MOIS = ['janv.', 'févr.', 'mars', 'avr.', 'mai', 'juin', 'juil.', 'août', 'sept.', 'oct.', 'nov.', 'déc.'];

function dateCourteJournal(iso) {
  const d = new Date(iso + 'T00:00:00');
  return d.getDate() + ' ' + MOIS[d.getMonth()];
}

function dateLongue(iso) {
  return new Date(iso + 'T00:00:00')
    .toLocaleDateString('fr-FR', { weekday: 'long', day: 'numeric', month: 'long', year: 'numeric' });
}

/** « 21h00 » depuis un ISO UTC sans suffixe (c'est ainsi que l'API le rend). */
function heureGeneration(iso) {
  if (!iso) return null;
  try {
    return new Date(iso + 'Z').toLocaleTimeString('fr-FR', { hour: '2-digit', minute: '2-digit' }).replace(':', 'h');
  } catch (_) { return null; }
}

function rendreEntree(entry) {
  const corps = h('div', { class: 'entry-body' });
  renderMarkdown(entry.content || '', corps);
  const gen = heureGeneration(entry.created_at);
  return h('div', { class: 'entry' },
    h('div', { class: 'entry-head' },
      h('div', { class: 'entry-title', text: dateLongue(entry.date) }),
      h('div', { class: 'label', text: (entry.word_count || 0) + ' MOTS' + (gen ? ' · GÉNÉRÉ À ' + gen.toUpperCase() : '') }),
    ),
    corps,
    entry.has_chart
      ? h('div', { class: 'entry-chart' },
        h('img', { src: `/api/public/journal/${entry.date}/chart`, alt: 'Historique des émotions de la journée', loading: 'lazy' }))
      : null,
  );
}

async function chargerJournal() {
  const jours = _refs.jours;
  const zone = _refs.entree;
  if (!jours || !zone) return;

  let entries = [];
  try {
    entries = (await (await fetch('/api/public/journal?limit=30')).json()).entries || [];
  } catch (err) {
    console.warn('journal indisponible', err);
    zone.textContent = '';
    zone.appendChild(h('div', { class: 'empty', text: 'Impossible de charger le journal.' }));
    return;
  }

  jours.textContent = '';
  zone.textContent = '';
  if (!entries.length) {
    zone.appendChild(h('div', { class: 'empty', text: 'Le journal est écrit chaque soir à 21 h. Aucune entrée pour le moment.' }));
    return;
  }

  // L'API rend du plus récent au plus ancien ; on lit de gauche à droite.
  const ordonnees = [...entries].reverse();
  let actif = null;
  ordonnees.forEach((entry, i) => {
    const dernier = i === ordonnees.length - 1;
    const bouton = h('button', { class: 'day' + (dernier ? ' active' : '') },
      h('div', { class: 'd', text: dateCourteJournal(entry.date) }),
      h('div', { class: 'dot' }),
    );
    bouton.addEventListener('click', () => {
      if (actif) actif.classList.remove('active');
      bouton.classList.add('active');
      actif = bouton;
      zone.textContent = '';
      zone.appendChild(rendreEntree(entry));
    });
    jours.appendChild(bouton);
    if (dernier) {
      actif = bouton;
      zone.appendChild(rendreEntree(entry));
    }
  });
  jours.scrollLeft = jours.scrollWidth;
}

// ── 06 · sous le capot ────────────────────────────────────────────────────
function sectionCapot() {
  return h('section', { class: 'section', id: 'a-propos' },
    h('div', { class: 'section-inner' },
      sectionHead('06 · SOUS LE CAPOT',
        'Un monolithe asyncio, une base SQLite, et beaucoup de prompts.'),
      h('div', { style: 'display:flex; flex-wrap:wrap; gap:8px; margin-top:38px' },
        ...PILE.map((s) => h('span', { class: 'stack-tag', text: s })),
      ),
      h('div', { class: 'grid grid-3 mt-48' },
        ...PILIERS.map((p) => h('div', { class: 'card reveal', 'data-tilt': '1' },
          h('div', { class: 'label', style: `color:${p.c}`, text: p.tag }),
          h('div', { class: 'h3 mt-20', text: p.t }),
          h('p', { class: 'lead lead-sm', text: p.d }),
        )),
      ),
      h('div', { class: 'keeps mt-16 reveal', 'data-tilt': '1' },
        h('div', {},
          h('div', { class: 'label', style: 'color:var(--green)', text: 'CE QU\'IL RETIENT' }),
          h('ul', {}, ...RETIENT.map((t) => h('li', { text: t }))),
        ),
        h('div', {},
          h('div', { class: 'label', style: 'color:var(--rose)', text: 'CE QU\'IL IGNORE' }),
          h('ul', { style: 'color:var(--muted)' }, ...IGNORE.map((t) => h('li', { text: t }))),
        ),
      ),
    ),
  );
}

// ── Rail de sections ──────────────────────────────────────────────────────
// Sept traits à droite de l'écran. Survolés ils se nomment, atteints ils
// s'allument : c'est le seul repère de position sur une page de 8 000 px.
const RAIL = [
  ['a-top', 'HAUT'],
  ['a-cerveau', 'CERVEAU'],
  ['a-statut', 'ÉMOTIONS'],
  ['a-chat', 'CHAT'],
  ['a-galerie', 'GALERIE'],
  ['a-journal', 'JOURNAL'],
  ['a-propos', 'CAPOT'],
];

function rail() {
  const nav = h('nav', { class: 'rail', 'aria-label': 'Sections de la page' });
  RAIL.forEach(([id, nom]) => {
    nav.appendChild(h('a', { href: '#' + id, title: nom, 'data-rail': id },
      h('span', { class: 'lbl', text: nom }),
      h('span', { class: 'tick' }),
    ));
  });
  _refs.rail = nav;
  return nav;
}

/** Une image d'animation : le bandeau, le fil et le rail, dans cet ordre.
 *
 *  Les trois lisent la MÊME position de défilement. Séparés, ils la mesuraient
 *  chacun de leur côté et se décalaient d'une image les uns des autres — ce qui
 *  se voit exactement là où on ne veut pas : entre le trait allumé du rail et
 *  la section qu'on est en train de lire.
 */
function image(sy, vh) {
  // TOUTES les mesures d'abord, les écritures ensuite. Intercalées, chaque
  // `getBoundingClientRect()` qui suit une écriture de style force le
  // navigateur à redisposer la page sur-le-champ, une fois par image.
  const piste = _refs.marquee;
  const moitie = piste ? piste.scrollWidth / 2 : 0;
  const section = document.getElementById('a-cerveau');
  const hautCerveau = section ? section.getBoundingClientRect().top : null;
  const nav = _refs.rail;
  // Le rail : la DERNIÈRE section dont le haut a passé les 42 % de l'écran.
  // Toujours exactement une active — un `IntersectionObserver` avec une bande
  // centrale n'en allume aucune quand deux sections se relaient hors de cette
  // bande, et le rail s'éteint en plein milieu de la page.
  let actif = 0;
  if (nav) {
    RAIL.forEach(([id], i) => {
      if (i === 0) return;
      const el = document.getElementById(id);
      if (el && el.getBoundingClientRect().top < vh * 0.42) actif = i;
    });
  }

  // Le bandeau défile AVEC la page, il ne tourne pas tout seul : c'est ce qui
  // le relie au geste du lecteur au lieu d'en faire une décoration.
  if (piste) {
    const x = moitie > 0 ? -((((sy * 0.45) % moitie) + moitie) % moitie) : 0;
    piste.style.transform = 'translate3d(' + x.toFixed(1) + 'px,0,0)';
  }

  // Le fil se remplit pendant que la section de la boucle traverse l'écran.
  const fil = _refs.wire;
  if (fil && hautCerveau !== null) {
    const p = Math.max(0, Math.min(1, (vh * 0.8 - hautCerveau) / (vh * 0.7)));
    fil.style.transform = 'scaleX(' + p.toFixed(3) + ')';
  }

  if (!nav) return;
  Array.from(nav.children).forEach((a, i) => a.classList.toggle('active', i === actif));
}

/** Les compteurs montent depuis zéro, une fois, à l'arrivée de la vraie valeur. */
function compter(el, cible) {
  const t0 = performance.now();
  const pas = (t) => {
    if (!_refs.statMsg) return;   // page démontée entre deux images
    const k = Math.min(1, (t - t0) / 1600);
    const e = 1 - Math.pow(1 - k, 3);
    el.textContent = Math.round(cible * e).toLocaleString('fr-FR');
    if (k < 1) requestAnimationFrame(pas);
  };
  requestAnimationFrame(pas);
}

// ── Statut en direct ──────────────────────────────────────────────────────
async function rafraichirStatut() {
  const [statut, stream] = await Promise.all([
    fetch('/api/public/status').then((r) => r.json()).catch(() => ({})),
    fetch('/api/public/twitch/stream').then((r) => r.json()).catch(() => null),
  ]);

  const poser = (id, contenu) => {
    const el = _refs[id];
    if (!el) return;
    el.textContent = '';
    (Array.isArray(contenu) ? contenu : [contenu]).forEach((c) => {
      el.appendChild(typeof c === 'string' ? document.createTextNode(c) : c);
    });
  };

  // Au PREMIER chargement les compteurs montent depuis zéro : un nombre qui
  // grimpe se lit comme une activité, le même nombre posé d'un coup se lit
  // comme une étiquette. Aux rafraîchissements suivants (toutes les 30 s), on
  // pose la valeur — la faire remonter de zéro serait un mensonge sur ce qui
  // vient de changer.
  const messages = statut.total_messages || 0;
  const viewers = (stream && stream.live) ? (stream.viewers || stream.viewer_count || 0) : null;
  if (_premierStatut && _refs.statMsg) {
    _premierStatut = false;
    compter(_refs.statMsg, messages);
    if (viewers !== null) compter(_refs.statViewers, viewers);
    else poser('statViewers', '—');
  } else {
    poser('statMsg', messages.toLocaleString('fr-FR'));
    poser('statViewers', viewers === null ? '—' : viewers.toLocaleString('fr-FR'));
  }
  const ms = statut.avg_response_ms;
  poser('statLatence', (ms === null || ms === undefined)
    ? '—'
    : [(ms / 1000).toFixed(1), h('span', { class: 'unit', text: 's' })]);
  poser('statUptime', formatUptime(statut.uptime_seconds));

  if (_refs.chatEtat) {
    const enLigne = !!statut.uptime_seconds;
    _refs.chatEtat.textContent = enLigne
      ? 'EN LIGNE · MÉMOIRE CHARGÉE' + (ms ? ' · ' + (ms / 1000).toFixed(1) + ' s DE LATENCE' : '')
      : 'HORS LIGNE POUR LE MOMENT';
    _refs.chatEtat.style.color = enLigne ? 'var(--green)' : 'var(--dim)';
  }
}

// ── Montage ───────────────────────────────────────────────────────────────
export function mount(el) {
  _refs = {};
  _evenements = [];
  _avantId = null;
  _chargeEnCours = false;
  _premierStatut = true;

  el.appendChild(rail());
  el.appendChild(heros());
  el.appendChild(sectionCerveau());
  el.appendChild(bandeauDefilant());
  el.appendChild(sectionEmotions());
  el.appendChild(sectionChat());
  el.appendChild(sectionGalerie());
  el.appendChild(sectionJournal());
  el.appendChild(sectionCapot());
  el.appendChild(pageFooter());

  rafraichirStatut();
  chargerHistoriqueEmo();
  chargerTete();
  amorcerFil();
  chargerApercuGalerie();
  chargerJournal();
  rendreJauges();

  _sseCognitif = connectCognitiveSSE(pousserEvenement);
  _desabonnerEmo = onEmotionUpdate(rendreJauges);
  _pollStatut = setInterval(rafraichirStatut, 30000);
  _pollHistorique = setInterval(chargerHistoriqueEmo, 300000);

  if (window.ResizeObserver) {
    _observerCourbe = new ResizeObserver(tracerCourbe);
    _observerCourbe.observe(_refs.courbe);
  }

  _desabonnerAnim = surAnimation(image);
  image(window.scrollY || 0, window.innerHeight);

}

export function unmount() {
  clearInterval(_pollStatut);
  clearInterval(_pollHistorique);
  _pollStatut = null;
  _pollHistorique = null;
  if (_desabonnerEmo) { _desabonnerEmo(); _desabonnerEmo = null; }
  if (_sseCognitif) { _sseCognitif.close(); _sseCognitif = null; }
  if (_observerCourbe) { _observerCourbe.disconnect(); _observerCourbe = null; }
  if (_desabonnerAnim) { _desabonnerAnim(); _desabonnerAnim = null; }
  _evenements = [];
  _historiqueEmo = null;
  _refs = {};
}
