// bot/dashboard/static/app.js
// WARNING: Auth token stored in localStorage — acceptable for personal use.
// For public exposure, replace with HttpOnly cookies.

'use strict';

// ── Constants ────────────────────────────────────────────────────────────────

const AUTH_KEY = 'wally_token';
const EMOTION_COLORS = {
  anger:    '#f85149',
  joy:      '#d29e0b',
  curiosity:'#3fb950',
  sadness:  '#58a6ff',
  boredom:  '#a371f7',
};
const EMOTION_EMOJIS = {
  anger: '😤', joy: '😊', sadness: '😢', curiosity: '🤔', boredom: '😴',
};
const EMOTION_LABELS = {
  anger: 'ANGER', joy: 'JOY', curiosity: 'CURIOSITY', sadness: 'SADNESS', boredom: 'BOREDOM',
};
const EMOTIONS = ['anger', 'joy', 'sadness', 'curiosity', 'boredom'];
const SECONDARY_COLORS = {
  frustration: '#f97316',
  nostalgia:   '#ec4899',
  pride:       '#f59e0b',
  anxiety:     '#8b5cf6',
  contempt:    '#6b7280',
  wonder:      '#14b8a6',
};
const SECONDARY_LABELS = ['frustration', 'nostalgia', 'pride', 'anxiety', 'contempt', 'wonder'];
const SECONDARY_LABELS_FR = {
  frustration: 'frustration', nostalgia: 'nostalgie',   pride:    'fierté',
  anxiety:     'anxiété',     contempt:  'mépris',       wonder:   'émerveillement',
};
const SECONDARY_DEFS = {
  frustration: { a: 'anger',     b: 'boredom',    threshold: 0.3         },
  nostalgia:   { a: 'joy',       b: 'sadness',    threshold: 0.3         },
  pride:       { a: 'joy',       b: 'curiosity',  threshold: 0.4         },
  anxiety:     { a: 'sadness',   b: 'curiosity',  threshold: 0.3         },
  contempt:    { a: 'anger',     b: 'boredom',    threshold: [0.4, 0.5]  },
  wonder:      { a: 'curiosity', b: 'joy',        threshold: 0.5         },
};

const PLATFORM_COLORS = {
  discord: '#5865F2',
  twitch: '#9146FF',
};

const PLATFORM_ICONS = {
  discord: '<svg width="14" height="14" viewBox="0 0 24 24" fill="currentColor"><path d="M20.317 4.37a19.791 19.791 0 00-4.885-1.515.074.074 0 00-.079.037c-.21.375-.444.864-.608 1.25a18.27 18.27 0 00-5.487 0 12.64 12.64 0 00-.617-1.25.077.077 0 00-.079-.037A19.736 19.736 0 003.677 4.37a.07.07 0 00-.032.027C.533 9.046-.32 13.58.099 18.057a.082.082 0 00.031.057 19.9 19.9 0 005.993 3.03.078.078 0 00.084-.028c.462-.63.874-1.295 1.226-1.994a.076.076 0 00-.041-.106 13.107 13.107 0 01-1.872-.892.077.077 0 01-.008-.128 10.2 10.2 0 00.372-.292.074.074 0 01.077-.01c3.928 1.793 8.18 1.793 12.062 0a.074.074 0 01.078.01c.12.098.246.198.373.292a.077.077 0 01-.006.127 12.299 12.299 0 01-1.873.892.077.077 0 00-.041.107c.36.698.772 1.362 1.225 1.993a.076.076 0 00.084.028 19.839 19.839 0 006.002-3.03.077.077 0 00.032-.054c.5-5.177-.838-9.674-3.549-13.66a.061.061 0 00-.031-.03zM8.02 15.33c-1.183 0-2.157-1.085-2.157-2.419 0-1.333.956-2.419 2.157-2.419 1.21 0 2.176 1.096 2.157 2.42 0 1.333-.956 2.418-2.157 2.418zm7.975 0c-1.183 0-2.157-1.085-2.157-2.419 0-1.333.955-2.419 2.157-2.419 1.21 0 2.176 1.096 2.157 2.42 0 1.333-.946 2.418-2.157 2.418z"/></svg>',
  twitch: '<svg width="14" height="14" viewBox="0 0 24 24" fill="currentColor"><path d="M11.571 4.714h1.715v5.143H11.57zm4.715 0H18v5.143h-1.714zM6 0L1.714 4.286v15.428h5.143V24l4.286-4.286h3.428L22.286 12V0zm14.571 11.143l-3.428 3.428h-3.429l-3 3v-3H6.857V1.714h13.714z"/></svg>',
};

// ── State ────────────────────────────────────────────────────────────────────

let logSSE      = null;
function _escHtml(s) {
  return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}
let _twitchPendingRestart = false;
let actionSSE   = null;
let currentEmotions = {};
let currentMood        = {};
let currentFatigue     = {};
let currentSecondaries = [];

// ── Tab sub-navigation state ──────────────────────────────────────

// Panneaux dont le rendu est en cours. `panel.children.length > 0` ne suffit
// pas : ces fonctions attendent `/api/admin/config` AVANT d'écrire, donc deux
// appels rapprochés franchissent la garde tous les deux et le panneau se
// retrouve monté en double — mêmes `id` présents deux fois, et
// `getElementById` ne rend que le premier, si bien qu'un réglage saisi dans la
// seconde copie était sauvegardé depuis la première.
const _panelsRendering = new WeakSet();

// Rend un panneau UNE fois, même si on le demande deux fois pendant le chargement.
// La libération est en `finally` : un rendu qui échoue doit pouvoir être retenté,
// sinon le panneau reste vide pour toute la session.
async function _renderPanelOnce(panel, render) {
  if (!panel || panel.children.length > 0 || _panelsRendering.has(panel)) return;
  _panelsRendering.add(panel);
  try {
    await render(panel);
  } finally {
    _panelsRendering.delete(panel);
  }
}

const MOOD_ADJ_FR = {
  anger: 'irritable', joy: 'joyeux', sadness: 'mélancolique',
  curiosity: 'curieux', boredom: 'apathique',
};
const FATIGUE_LABEL_FR = {
  anger: 'colère', joy: 'joie', sadness: 'tristesse', curiosity: 'curiosité', boredom: 'ennui',
};
const FATIGUE_COLORS = {
  anger:    'rgba(239,68,68,0.7)',
  joy:      'rgba(234,179,8,0.7)',
  sadness:  'rgba(59,130,246,0.7)',
  curiosity:'rgba(34,197,94,0.7)',
  boredom:  'rgba(168,85,247,0.7)',
};
const SECONDARY_ADJ_FR = {
  frustration: 'frustré',
  nostalgia:   'nostalgique',
  pride:       'fier de lui',
  anxiety:     'anxieux',
  contempt:    'méprisant',
  wonder:      'émerveillé',
};

// -- Bot Control Bar ----------------------------------------------
var _controlBarInterval = null;

function showControlBar(visible) {
  var bar = document.getElementById('control-bar');
  if (bar) bar.style.display = visible ? 'flex' : 'none';
}

async function pollBotStatus() {
  var r = await apiFetch('/api/admin/bot/status');
  if (!r || !r.ok) return;
  var data = await r.json();

  var discordDot = document.getElementById('discord-dot');
  var twitchDot = document.getElementById('twitch-dot');
  var discordBtn = document.getElementById('discord-toggle-btn');
  var twitchBtn = document.getElementById('twitch-toggle-btn');

  if (discordDot) discordDot.className = 'control-bar-dot' + (data.discord === 'connected' ? ' online' : '');
  if (twitchDot) twitchDot.className = 'control-bar-dot' + (data.twitch === 'connected' ? ' online' : '');
  if (discordBtn) {
    discordBtn.textContent = data.discord === 'connected' ? 'Stop' : 'Start';
    discordBtn.disabled = false;
  }
  if (twitchBtn) {
    twitchBtn.textContent = data.twitch === 'connected' ? 'Stop' : 'Start';
    twitchBtn.disabled = false;
  }
  var updateGroup = document.getElementById('update-group');
  if (updateGroup) updateGroup.style.display = data.update_available ? '' : 'none';
  var versionBadge = document.getElementById('version-badge');
  if (versionBadge && data.git_hash && data.git_hash !== 'unknown') {
    versionBadge.textContent = 'build ' + data.git_hash + ' · ' + _formatBuildDate(data.build_date);
  }
}

function _formatBuildDate(iso) {
  if (!iso || iso === 'unknown') return '';
  try {
    var d = new Date(iso);
    var months = ['janv','févr','mars','avr','mai','juin','juil','août','sept','oct','nov','déc'];
    return d.getUTCDate() + ' ' + months[d.getUTCMonth()] + ' ' + String(d.getUTCHours()).padStart(2,'0') + ':' + String(d.getUTCMinutes()).padStart(2,'0');
  } catch(e) { return iso; }
}

async function triggerSelfUpdate() {
  var btn = document.getElementById('update-available-btn');
  if (btn) { btn.disabled = true; btn.textContent = '⏳ Mise à jour…'; }
  var r = await apiFetch('/api/admin/self-update', { method: 'POST' });
  if (!r || !r.ok) {
    var d = r ? await r.json() : {};
    toast('Erreur : ' + (d.detail || '?'), 'error');
    if (btn) { btn.disabled = false; btn.textContent = 'Update dispo'; }
    return;
  }
  toast('Mise à jour lancée, redémarrage en cours…', 'success');
  setTimeout(function() { _waitForReconnect(); }, 3000);
}

function startControlBarPolling() {
  if (_controlBarInterval) return;
  pollBotStatus();
  _controlBarInterval = setInterval(pollBotStatus, 5000);
}

function stopControlBarPolling() {
  if (_controlBarInterval) {
    clearInterval(_controlBarInterval);
    _controlBarInterval = null;
  }
}

async function toggleBotAdapter(adapter) {
  var btn = document.getElementById(adapter + '-toggle-btn');
  if (!btn) return;
  var action = btn.textContent.trim() === 'Stop' ? 'stop' : 'start';
  btn.disabled = true;
  btn.textContent = '...';
  var r = await apiFetch('/api/admin/bot/' + adapter + '/' + action, { method: 'POST' });
  if (!r || !r.ok) {
    toast('Erreur ' + action + ' ' + adapter, 'error');
    btn.disabled = false;
    pollBotStatus();
    return;
  }
  toast(adapter + ' ' + (action === 'stop' ? 'arrêté' : 'démarré'), 'success');
  setTimeout(pollBotStatus, 2000);
}

async function restartContainer() {
  if (!confirm('Redémarrer le container Wally ? Le dashboard sera temporairement indisponible.')) return;
  var btn = document.getElementById('restart-btn');
  if (btn) btn.disabled = true;
  var r = await apiFetch('/api/admin/bot/restart', { method: 'POST' });
  if (!r || !r.ok) {
    var err = r ? await r.json().catch(function() { return {}; }) : {};
    toast(err.detail || 'Erreur restart', 'error');
    if (btn) btn.disabled = false;
    return;
  }
  toast('Restart en cours...', 'success');
  _waitForReconnect();
}

function _waitForReconnect() {
  var attempts = 0;
  var maxAttempts = 60;
  var interval = setInterval(async function() {
    attempts++;
    if (attempts > maxAttempts) {
      clearInterval(interval);
      toast('Le bot ne répond plus', 'error');
      return;
    }
    try {
      var r = await fetch('/api/public/status', { signal: AbortSignal.timeout(3000) });
      if (r.ok) {
        clearInterval(interval);
        toast('Bot reconnecté !', 'success');
        var btn = document.getElementById('restart-btn');
        if (btn) btn.disabled = false;
        pollBotStatus();
      }
    } catch(e) { /* server still down */ }
  }, 2000);
}

function _onTwitchAuthSuccess(account, username) {
  _twitchPendingRestart = true;
  var label = account === 'bot' ? 'bot' : 'streamer';
  toast('Compte ' + label + ' connecte' + (username ? ' — ' + username : '') + ' ! Redemarre le container.', 'success');
  var panel = document.getElementById('systeme-sub-twitch');
  if (panel && panel.classList.contains('active')) {
    _renderSystemeTwitch(panel);
  }
}

async function startTwitchOAuth(account) {
  var r = await apiFetch('/api/admin/twitch/auth-url', {
    method: 'POST',
    body: JSON.stringify({ account: account }),
  });
  if (!r || !r.ok) { toast('Erreur generation URL OAuth', 'error'); return; }
  var data = await r.json();
  var popup = window.open(data.url, 'twitch-oauth', 'width=600,height=700,noopener');
  if (!popup) toast('Popup bloque — autorise les popups pour ce site.', 'error');
}

async function restartTwitchContainer() {
  if (!confirm('Redémarrer le container Wally ? Le dashboard sera indisponible ~10 s.')) return;
  var r = await apiFetch('/api/admin/twitch/restart', { method: 'POST' });
  if (!r || !r.ok) {
    var err = r ? await r.json().catch(function() { return {}; }) : {};
    toast(err.detail || 'Erreur restart', 'error');
    return;
  }
  _twitchPendingRestart = false;
  toast('Redemerrage en cours...', 'success');
  _waitForReconnect();
}

// ── Routage par hash ─────────────────────────────────────────────────────────
//
// Refonte du 2026-08-28 — cf. docs/plans/2026-08-28-refonte-panel-admin-plan.md
// et design_handoff_panel_admin/. Le panel passe de 7 onglets × jusqu'à 7
// sous-onglets à 11 pages plates groupées en 3 thèmes.
//
// L'URL porte la page, et plus tard ses filtres (`#/systeme/journal?niveau=error`).
// Sans elle, un item du cockpit ne peut pas ouvrir Automatisations DÉJÀ filtré
// sur « En échec », un lien ne se partage pas, et un redémarrage du conteneur
// ramène toujours sur la même section.
//
// `pane` et `sub` sont TRANSITOIRES : tant qu'une page n'a pas été refaite, sa
// route ouvre l'ANCIEN panneau, au bon sous-onglet. C'est ce qui rend la
// refonte livrable phase par phase sans jamais casser le panel en production.
// Chaque phase remplace un couple `pane`/`sub` par un vrai rendu.

const ROUTES = {
  'cockpit': {
    titre: 'Cockpit',
    sous: '',
    pane: 'admin-cockpit',
  },
  'cerveau/personnes': {
    titre: 'Personnes',
    sous: 'Tout le monde que Wally connaît, sur les deux plateformes.',
    pane: 'admin-personnes',
  },
  // Vue de détail : le titre et le sous-titre sont réécrits par la fiche
  // elle-même, une fois qu'elle sait de QUI il s'agit.
  'cerveau/fiche': {
    titre: 'Personne',
    sous: '',
    pane: 'admin-personne',
    // Une vue de détail garde SA page allumée dans la sidebar : sans ça, ouvrir
    // une fiche éteint toute la navigation et on ne sait plus d'où l'on vient.
    parent: 'cerveau/personnes',
  },
  'cerveau/memoire': {
    titre: 'Mémoire commune',
    sous: 'Ce que Wally sait du groupe plutôt que d\'une personne.',
    pane: 'admin-memoire',
  },
  'cerveau/personnalite': {
    titre: 'Personnalité',
    sous: 'Comment Wally se comporte — par des nombres, et par des textes.',
    pane: 'admin-personnalite',
  },
  'cerveau/modeles': {
    titre: 'Modèles & coûts',
    sous: 'Quel modèle sert à quoi, et ce que ça coûte.',
    pane: 'admin-modeles',
  },
  'live/scene': {
    titre: 'Scène & overlays',
    sous: 'Le placement de ce que les viewers voient.',
    pane: 'admin-scene',
  },
  'live/voix': {
    titre: 'Voix',
    sous: 'Ce que Wally entend, et ce qu\'il répond à l\'oral.',
    pane: 'admin-voix',
  },
  'live/medias': {
    titre: 'Médias & sons',
    sous: 'Ce que Wally montre et ce qu\'il fait entendre.',
    pane: 'admin-medias',
  },
  'live/memes': {
    titre: 'Memes',
    sous: 'La banque d\'images que Wally sort sur le live.',
    pane: 'admin-memes',
  },
  'live/automatisations': {
    titre: 'Automatisations',
    sous: 'Les tâches que Wally exécute tout seul.',
    pane: 'admin-actions',
  },
  'systeme/journal': {
    titre: 'Journal',
    sous: 'Ce qui se passe, en direct.',
    pane: 'admin-journal',
  },
  'systeme/connexions': {
    titre: 'Connexions',
    sous: 'Discord, Twitch, et l\'état des jetons.',
    pane: 'admin-connexions',
  },
};

// Les routes qui portent un PARAMÈTRE : `#/cerveau/personnes/discord:123`.
// Elles n'apparaissent pas dans la sidebar — on y arrive depuis une ligne de
// liste, et on en revient par le fil d'Ariane.
const ROUTES_PARAM = [
  ['cerveau/personnes/', 'cerveau/fiche'],
];

const ROUTE_DEFAUT = 'cockpit';

// Les anciens hash — `#admin-memoire`, et les quatre noms d'onglets déjà
// redirigés avant la refonte. Un signet posé il y a six mois doit continuer de
// tomber sur la bonne page, pas sur la page d'accueil.
const ROUTES_LEGACY = {
  'admin-parametres':  'cerveau/personnalite',
  'admin-config':      'cerveau/personnalite',
  'admin-memoire':     'cerveau/personnes',
  'admin-memory-dash': 'cerveau/memoire',
  'admin-actions':     'live/automatisations',
  'admin-prompts':     'cerveau/personnalite',
  'admin-scene':       'live/scene',
  'admin-systeme':     'systeme/journal',
  'admin-logs':        'systeme/journal',
  'admin-twitch':      'systeme/connexions',
  'admin-overlay':     'live/medias',
  'admin-voice':       'live/voix',
};

// La route affichée. `null` tant que rien n'est monté, pour que le premier
// rendu passe la garde d'égalité de `_surChangementDeHash`.
/** Le thème d'une route : le premier segment, sauf le cockpit qui est seul.
 *
 *  Sert à la barre du bas mobile (quatre destinations, pas onze) et à la
 *  rangée de puces qui remplace la sidebar sous 780 px.
 */
function themeDe(route) {
  if (!route) return '';
  const i = route.indexOf('/');
  return i === -1 ? route : route.slice(0, i);
}

let currentRoute = null;
// Le paramètre de la route courante — l'identité, sur une fiche personne.
let currentParam = '';

/** Ce que dit le hash courant.
 *
 *  `canonique` distingue « l'URL désigne déjà cette page » de « on a dû
 *  deviner » (ancien hash, ou charabia). Dans le second cas seulement, le
 *  routeur réécrit l'URL — sinon il effacerait les filtres, qui vivent dans la
 *  partie requête (`#/systeme/journal?niveau=error`).
 */
function _analyserHash() {
  const brut = location.hash.replace(/^#\/?/, '');
  const coupe = brut.indexOf('?');
  const chemin = coupe === -1 ? brut : brut.slice(0, coupe);
  const requete = coupe === -1 ? '' : brut.slice(coupe);
  if (ROUTES[chemin]) {
    return { route: chemin, param: '', requete: requete, canonique: true };
  }
  for (const [prefixe, cible] of ROUTES_PARAM) {
    if (chemin.startsWith(prefixe) && chemin.length > prefixe.length) {
      return {
        route: cible,
        param: decodeURIComponent(chemin.slice(prefixe.length)),
        requete: requete,
        canonique: true,
      };
    }
  }
  if (ROUTES_LEGACY[chemin]) {
    return { route: ROUTES_LEGACY[chemin], param: '', requete: '', canonique: false };
  }
  return { route: ROUTE_DEFAUT, param: '', requete: '', canonique: false };
}

function _appliquerRoute(route, param) {
  const def = ROUTES[route];
  if (!def) return;
  currentParam = param || '';

  const surligne = def.parent || route;
  document.querySelectorAll('.sidebar-item').forEach(function (a) {
    a.classList.toggle('active', a.dataset.route === surligne);
  });
  document.querySelectorAll('.tab-content').forEach(function (c) {
    c.classList.remove('active');
  });
  const pane = document.getElementById('tab-' + def.pane);
  if (pane) pane.classList.add('active');

  _majNavigationMobile(surligne);

  const tete = document.getElementById('page-head');
  const titre = document.getElementById('page-title');
  const sous = document.getElementById('page-sub');
  if (titre) titre.textContent = def.titre;
  if (sous) { sous.textContent = def.sous || ''; sous.hidden = !def.sous; }
  if (tete) tete.hidden = false;

  if (currentRoute && ROUTES[currentRoute]) {
    noterPageRecente(currentRoute, ROUTES[currentRoute].titre);
  }
  currentRoute = route;

  // Le sommaire appartient à la page, pas à la coquille : une page sans
  // sommaire ne doit pas hériter des ancres de la précédente, qui pointeraient
  // vers des sections disparues.
  viderSommaire();
  viderChromePage();

  // Le mode « lier deux identités » est une modale sans fenêtre : il attend un
  // clic sur une AUTRE personne. Quitter l'annuaire l'abandonne, sinon le
  // prochain clic n'importe où déclencherait une fusion.
  if (def.pane !== 'admin-memoire' && _memLinkMode) cancelLinkMode();

  if (def.pane === 'admin-cockpit') renderCockpit();
  else if (def.pane === 'admin-personnes') renderPersonnes();
  else if (def.pane === 'admin-personnalite') renderPersonnalite();
  else if (def.pane === 'admin-modeles') renderModeles();
  else if (def.pane === 'admin-medias') renderMedias();
  else if (def.pane === 'admin-connexions') renderConnexions();
  else if (def.pane === 'admin-personne') renderFichePersonne(currentParam);
  else if (def.pane === 'admin-journal') renderJournal();
  else if (def.pane === 'admin-memoire') renderMemoireCommune();
  else if (def.pane === 'admin-prompts') renderPromptsTab();
  else if (def.pane === 'admin-scene') renderSceneTab();

  // Les deux flux SSE de page : ouverts sur leur page, fermés partout ailleurs.
  if (def.pane === 'admin-actions') { renderActionsTab(); startActionSSE(); } else { stopActionSSE(); }
  if (def.pane === 'admin-voix') { renderVoix(); startVoiceSSE(); } else { stopVoiceSSE(); }
  // La veille du dossier de memes : sur sa page, coupée partout ailleurs —
  // même discipline que les deux flux SSE ci-dessus.
  if (def.pane === 'admin-memes') { renderMemes(); startMemesVeille(); }
  else { stopMemesVeille(); }

  pollLinksBadge();
}

/** Le gestionnaire de `hashchange`, et le point d'entrée du premier rendu. */
function routerVersHash() {
  if (!getToken()) return;
  const vu = _analyserHash();
  // Le paramètre compte autant que la route : passer d'une fiche à une autre
  // ne change pas `route`, et la garde d'égalité seule laisserait la première
  // personne à l'écran.
  if (vu.route !== currentRoute || vu.param !== currentParam) {
    _appliquerRoute(vu.route, vu.param);
  }
  // Réécrit l'URL seulement quand on a dû deviner. Poser le hash relance
  // `hashchange`, mais la route est alors déjà courante : la garde ci-dessus
  // arrête la boucle au deuxième tour.
  if (!vu.canonique) location.hash = '#/' + vu.route;
}

window.addEventListener('hashchange', routerVersHash);

// ── Sommaire d'ancres ────────────────────────────────────────────────────────
//
// La colonne de droite d'une page longue. Générique : une page passe ses
// sections, le sommaire les rend et suit le défilement.

let _ancresCourantes = [];

/** @param route  la route qui possède ce sommaire.
 *  @param sections  liste de [id, libellé], dans l'ordre de la page.
 *  @param encartHtml  HTML déjà échappé, ou '' — un fait saillant sous les ancres.
 *
 *  La route est OBLIGATOIRE, et c'est tout l'intérêt : les pages remplissent
 *  leur sommaire après une requête réseau. Vu à l'écran le 2026-08-28 — la
 *  réponse de `/journal/erreurs` arrivait alors qu'on était déjà sur
 *  Automatisations, et y plantait « Flux en direct · Erreurs groupées ·
 *  Statistiques », des ancres vers des sections absentes de la page.
 */
function poserSommaire(route, sections, encartHtml) {
  if (route !== currentRoute) return;
  const rail = document.getElementById('page-rail');
  if (!rail) return;
  _ancresCourantes = sections || [];
  if (!_ancresCourantes.length) { viderSommaire(); return; }

  rail.innerHTML = '<div class="rail-titre">Sur cette page</div>'
    + '<div class="rail-ancres">'
    + _ancresCourantes.map(function (paire) {
        return '<a class="rail-ancre" data-ancre="' + escAttr(paire[0]) + '" href="javascript:void(0)">'
          + escHtml(paire[1]) + '</a>';
      }).join('')
    + '</div>' + (encartHtml || '');
  rail.hidden = false;
  _majAncreActive();
}

/** La barre du bas et la rangée de puces, pour le mobile.
 *
 *  Les puces sont DÉRIVÉES de la sidebar : elle porte déjà l'ordre et les
 *  libellés des onze pages. Les réécrire ici en donnerait une seconde liste,
 *  qui divergerait au premier ajout — et personne ne le verrait, puisqu'elle
 *  ne s'affiche que sous 780 px.
 */
function _majNavigationMobile(route) {
  const theme = themeDe(route);

  document.querySelectorAll('.barre-bas-item').forEach(function (a) {
    a.classList.toggle('active', a.dataset.theme === theme);
  });

  const puces = document.getElementById('theme-puces');
  if (!puces) return;
  const voisines = Array.from(document.querySelectorAll('.sidebar-item'))
    .filter(function (a) { return themeDe(a.dataset.route) === theme; });
  // Une seule page dans le thème (le cockpit) : pas de rangée à afficher.
  puces.innerHTML = voisines.length > 1
    ? voisines.map(function (a) {
        const r = a.dataset.route;
        return '<a class="theme-puce' + (r === route ? ' active' : '')
          + '" href="#/' + escAttr(r) + '">'
          + escHtml((a.querySelector('span') || a).textContent.trim()) + '</a>';
      }).join('')
    : '';
}

/** La pastille d'alerte de « Système » sur la barre du bas.
 *
 *  Elle ne s'affiche QUE sur une mesure : absente, elle ne veut pas dire « zéro
 *  erreur », elle veut dire « pas encore mesuré ». D'où l'appel unique au
 *  démarrage, pour qu'elle soit juste dès la première seconde.
 */
function majBadgeSysteme(n) {
  const el = document.getElementById('badge-systeme');
  if (!el) return;
  el.hidden = !n;
}

async function chargerBadgeSysteme() {
  const r = await apiFetch('/api/admin/decisions?max_items=1');
  if (!r || !r.ok) return;
  majBadgeSysteme((await r.json()).erreurs_du_jour);
}

/** Vide les deux emplacements que les pages peuvent remplir : les commandes à
 *  droite du titre, et les actions de la barre du haut.
 *
 *  Même discipline que le sommaire d'ancres : une page ne doit jamais hériter
 *  des boutons de la précédente. Sur la Scène, hériter d'une URL OBS d'une
 *  autre page reviendrait à proposer de copier une adresse qui n'est plus
 *  celle qu'on règle.
 */
function viderChromePage() {
  ['page-actions', 'control-bar-page'].forEach(function (id) {
    const el = document.getElementById(id);
    if (el) el.innerHTML = '';
  });
}

function viderSommaire() {
  const rail = document.getElementById('page-rail');
  if (!rail) return;
  _ancresCourantes = [];
  rail.innerHTML = '';
  rail.hidden = true;
}

/** Fait défiler la COLONNE DE CONTENU, pas la fenêtre.
 *
 *  `scrollIntoView` viserait le viewport : `.main-content` a son propre
 *  `overflow-y`, et la fenêtre, elle, ne défile pas d'un pixel. Le clic
 *  n'aurait donc aucun effet visible.
 */
function _allerAncre(id) {
  const cible = document.getElementById(id);
  const boite = document.querySelector('.main-content');
  if (!cible || !boite) return;
  const haut = cible.getBoundingClientRect().top
    - boite.getBoundingClientRect().top + boite.scrollTop;
  // 60 px : la barre du haut est collante et couvrirait le titre de section.
  boite.scrollTo({ top: Math.max(0, haut - 60), behavior: 'smooth' });
}

function _majAncreActive() {
  const boite = document.querySelector('.main-content');
  const rail = document.getElementById('page-rail');
  if (!boite || !rail || !_ancresCourantes.length) return;
  const repere = boite.getBoundingClientRect().top + 80;
  let actif = _ancresCourantes[0][0];
  for (const paire of _ancresCourantes) {
    const el = document.getElementById(paire[0]);
    if (el && el.getBoundingClientRect().top <= repere) actif = paire[0];
  }
  rail.querySelectorAll('[data-ancre]').forEach(function (a) {
    a.classList.toggle('active', a.dataset.ancre === actif);
  });
}

// Deux écouteurs posés UNE fois, au chargement du module : les reposer à chaque
// rendu de page les empilerait, et le défilement finirait par recalculer le
// sommaire une fois par visite passée.
document.addEventListener('click', function (ev) {
  const a = ev.target.closest('#page-rail [data-ancre]');
  if (a) _allerAncre(a.dataset.ancre);
});

window.addEventListener('load', function () {
  const boite = document.querySelector('.main-content');
  if (boite) boite.addEventListener('scroll', _majAncreActive, { passive: true });
});

function enterAdmin() {
  if (!getToken()) { showAuthModal(); return; }
  document.getElementById('nav-admin').style.display = 'flex';
  showControlBar(true);
  startControlBarPolling();
  // AVANT le SSE : il construit `#log-stream`, la cible dans laquelle
  // `appendLog()` écrit l'historique. Sans lui, les lignes déjà émises sont
  // perdues au démarrage — et ça, quelle que soit la page d'arrivée.
  _construireJournal();
  startLogSSE();
  chargerBadgeSysteme();
  routerVersHash();
}

// ── Auth ─────────────────────────────────────────────────────────────────────

function getToken()       { return localStorage.getItem(AUTH_KEY); }
function saveToken(t)     { localStorage.setItem(AUTH_KEY, t); }
function clearToken()     { localStorage.removeItem(AUTH_KEY); }
function showAuthModal()  { document.getElementById('auth-modal').classList.add('visible'); }
function hideAuthModal()  { document.getElementById('auth-modal').classList.remove('visible'); }

// Un refus n'est pas forcément un mauvais token. Le verrou anti-force-brute
// (`bot/dashboard/auth.py`) répond 429 AVANT toute comparaison, et son seau est
// partagé par tout ce qui arrive par le tunnel : dix requêtes rejetées — un seul
// rechargement de page avec un jeton périmé suffit — et l'owner se retrouve
// enfermé dehors. Lui annoncer « Token invalide » l'envoie chercher un jeton qui
// est le bon, et chaque nouvelle tentative DOUBLE le verrou.
async function submitToken() {
  const t = document.getElementById('token-input').value.trim();
  if (!t) return;
  const r = await fetch('/api/admin/config', { headers: { 'Authorization': `Bearer ${t}` } });
  if (r.ok) {
    saveToken(t);
    hideAuthModal();
    document.getElementById('token-input').value = '';
    _sessionExpiredFired = false;
    enterAdmin();
    toast('Accès admin accordé', 'success');
  } else if (r.status === 429) {
    toast(`Trop de tentatives refusées — réessaie dans ${retryApres(r)} s. Le jeton est peut-être le bon.`, 'error');
  } else if (r.status === 503) {
    toast('Aucun dashboard_token configuré côté serveur.', 'error');
  } else if (r.status === 401) {
    toast('Token invalide', 'error');
  } else {
    toast(`Le serveur a refusé (HTTP ${r.status})`, 'error');
  }
}

/** Secondes à attendre annoncées par `Retry-After`, 60 par défaut. */
function retryApres(r) {
  return parseInt(r.headers.get('Retry-After') || '', 10) || 60;
}

// ── API helpers ───────────────────────────────────────────────────────────────

let _sessionExpiredFired = false;
let _verrouFired = false;

async function apiFetch(url, opts = {}) {
  const headers = { 'Content-Type': 'application/json', ...(opts.headers || {}) };
  const token = getToken();
  if (token) headers['Authorization'] = `Bearer ${token}`;
  const r = await fetch(url, { ...opts, headers });
  if (r.status === 429) {
    // Le verrou d'authentification, pas une limite de débit métier : le
    // dashboard entier reçoit `{"detail": ...}` là où il attend ses données, et
    // chaque panneau se peint VIDE sans un mot. Le dire une fois vaut mieux que
    // onze écrans muets.
    if (!_verrouFired) {
      _verrouFired = true;
      toast(`Accès temporairement verrouillé (trop de tentatives) — réessaie dans ${retryApres(r)} s.`, 'error');
      setTimeout(() => { _verrouFired = false; }, 10000);
    }
    return null;
  }
  if (r.status === 401) {
    if (token && !_sessionExpiredFired) {
      _sessionExpiredFired = true;
      toast('Session expirée', 'error');
    }
    clearToken();
    showAuthModal();
    return null;
  }
  return r;
}

// ── SSE admin ─────────────────────────────────────────────────────────────────

/**
 * Ouvre un flux SSE admin.
 *
 * `EventSource` ne peut pas envoyer d'en-tête `Authorization` : ces routes
 * s'authentifient avec un ticket à usage unique (30 s), échangé ici contre le
 * Bearer. Elles étaient auparavant servies SANS aucune authentification —
 * `/sse/logs` diffuse le contenu des DM Discord.
 *
 * Renvoie null si le ticket est refusé (session expirée) ; l'appelant doit le
 * gérer plutôt que de supposer un EventSource.
 */
async function openAdminSSE(path) {
  const r = await apiFetch('/api/admin/sse/ticket');
  if (!r || !r.ok) return null;
  const { ticket } = await r.json();
  return new EventSource(`${path}?ticket=${encodeURIComponent(ticket)}`);
}

// ── Toasts — improved durations & close button ───────────────────────────────

function toast(msg, type = 'success') {
  const el = document.createElement('div');
  el.className = `toast ${type}`;

  const textSpan = document.createElement('span');
  textSpan.textContent = msg;
  el.appendChild(textSpan);

  const closeBtn = document.createElement('button');
  closeBtn.className = 'toast-close';
  closeBtn.textContent = '×';
  closeBtn.setAttribute('aria-label', 'Fermer');
  closeBtn.onclick = () => dismissToast(el);
  el.appendChild(closeBtn);

  document.getElementById('toast-container').appendChild(el);

  const duration = type === 'error' ? 6000 : 3000;
  el._timeout = setTimeout(() => dismissToast(el), duration);
}

function dismissToast(el) {
  if (el._dismissed) return;
  el._dismissed = true;
  clearTimeout(el._timeout);
  el.style.animation = 'toast-out 0.2s ease forwards';
  setTimeout(() => el.remove(), 200);
}

// ── Emotion gauges ────────────────────────────────────────────────────────────

function buildGauges(containerId, editable) {
  const c = document.getElementById(containerId);
  c.innerHTML = '';
  for (const e of EMOTIONS) {
    const row = document.createElement('div');
    row.className = 'emotion-row';
    if (!editable) {
      row.innerHTML = `
        <span class="emotion-label" style="color:${EMOTION_COLORS[e]}">${EMOTION_EMOJIS[e]} ${EMOTION_LABELS[e]}</span>
        <div class="gauge-track" role="progressbar" aria-label="${EMOTION_LABELS[e]}" aria-valuenow="0" aria-valuemin="0" aria-valuemax="1">
          <div class="gauge-fill ${e}" id="fill-${e}"></div>
        </div>
        <span class="gauge-val" id="val-${e}">0.00</span>
      `;
    } else {
      row.innerHTML = `
        <span class="emotion-label" style="color:${EMOTION_COLORS[e]}">${EMOTION_EMOJIS[e]} ${EMOTION_LABELS[e]}</span>
        <input type="range" class="emotion-slider" id="slider-${e}" min="0" max="1" step="0.01" value="0"
               aria-label="${EMOTION_LABELS[e]}"
               oninput="document.getElementById('val-${e}').textContent=parseFloat(this.value).toFixed(2)"
               onchange="setEmotion('${e}', parseFloat(this.value))">
        <span class="gauge-val" id="val-${e}">0.00</span>
      `;
    }
    c.appendChild(row);
  }
}

function updateEmotionGauges(payload) {
  // Extract organic emotion fields
  currentMood        = payload.mood        || {};
  currentFatigue     = payload.fatigue     || {};
  currentSecondaries = payload.secondaries || [];

  currentEmotions = payload;
  for (const e of EMOTIONS) {
    const v = payload[e] ?? 0;
    const fill = document.getElementById(`fill-${e}`);
    if (fill) {
      fill.style.width = `${(v * 100).toFixed(1)}%`;
      const track = fill.parentElement;
      if (track) track.setAttribute('aria-valuenow', v.toFixed(2));
    }
    const slider = document.getElementById(`slider-${e}`);
    if (slider) slider.value = v;
    const val = document.getElementById(`val-${e}`);
    if (val) val.textContent = v.toFixed(2);
  }
  updateMoodFatigueLine(currentMood, currentFatigue);
  updateEmotionalStateBlock(payload, currentMood, currentFatigue, currentSecondaries);
}

function updateMoodFatigueLine(mood, fatigue) {
  const el = document.getElementById('mood-fatigue-line');
  if (!el) return;

  const moodEntries = EMOTIONS
    .filter(e => (mood[e] ?? 0) >= 0.2)
    .sort((a, b) => (mood[b] ?? 0) - (mood[a] ?? 0))
    .slice(0, 2);

  const fatigueEntries = Object.entries(fatigue).filter(([, v]) => v > 0);

  if (moodEntries.length === 0 && fatigueEntries.length === 0) {
    el.style.display = 'none';
    return;
  }

  // Build spans from internal constants only — labels from MOOD_ADJ_FR/FATIGUE_LABEL_FR,
  // color from FATIGUE_COLORS, pct is a rounded integer. No user input reaches innerHTML.
  const parts = [];

  if (moodEntries.length > 0) {
    const labels = moodEntries.map(e => MOOD_ADJ_FR[e] || e).join(', ');
    parts.push(
      '<span class="mf-label">Humeur de fond</span>',
      `<span class="mf-value">${labels}</span>`
    );
  }

  if (fatigueEntries.length > 0) {
    if (moodEntries.length > 0) parts.push('<span class="mf-separator">|</span>');
    parts.push('<span class="mf-label">Fatigue</span>');
    for (const [emotion, v] of fatigueEntries) {
      const label = FATIGUE_LABEL_FR[emotion] || emotion;
      const pct   = Math.round(v * 100);
      const color = FATIGUE_COLORS[emotion] || 'rgba(255,255,255,0.7)';
      parts.push(
        `<span class="mf-value" style="color:${color};margin-left:6px">${label} en récupération (${pct}%)</span>`
      );
    }
  }

  el.innerHTML = parts.join(''); // safe: all content from internal constants + numeric pct
  el.style.display = 'flex';
}

function updateEmotionalStateBlock(emotions, mood, fatigue, secondaries) {
  const el     = document.getElementById('emotional-state-block');
  const textEl = document.getElementById('emotional-state-text');
  if (!el || !textEl) return;

  const fatigueActive     = Object.values(fatigue).some(v => v > 0);
  const activeSecondaries = secondaries.filter(([, intensity]) => intensity >= 0.4);

  const dominantEmotion = EMOTIONS.reduce((a, b) =>
    (emotions[a] ?? 0) > (emotions[b] ?? 0) ? a : b);
  const dominantMood = EMOTIONS.reduce((a, b) =>
    (mood[a] ?? 0) > (mood[b] ?? 0) ? a : b);
  const hasMoodDissonance = dominantMood !== dominantEmotion
    && (emotions[dominantEmotion] ?? 0) >= 0.3
    && (mood[dominantMood] ?? 0) >= 0.3;

  let sentence = '';

  // Rule 1: Secondary emotion active (intensity >= 0.4)
  if (activeSecondaries.length > 0) {
    const [secName] = activeSecondaries[0];
    const secAdj = SECONDARY_ADJ_FR[secName] || secName;
    sentence = `Wally est ${secAdj}.`;
    if (fatigueActive) {
      const firstFatigueEmotion = Object.keys(fatigue).find(k => fatigue[k] > 0);
      const fatigueLabel = firstFatigueEmotion ? (FATIGUE_LABEL_FR[firstFatigueEmotion] || firstFatigueEmotion) : '';
      if (fatigueLabel) sentence += ` Sa ${fatigueLabel} est en récupération après un pic.`;
    }
    if (hasMoodDissonance) {
      const moodAdj = MOOD_ADJ_FR[dominantMood] || dominantMood;
      sentence += ` Fond ${moodAdj} malgré tout.`;
    }
  }
  // Rule 2: Fatigue active but no secondary
  else if (fatigueActive) {
    const firstFatigueEmotion = Object.keys(fatigue).find(k => fatigue[k] > 0);
    const fatigueLabel = firstFatigueEmotion ? (FATIGUE_LABEL_FR[firstFatigueEmotion] || firstFatigueEmotion) : '';
    sentence = `Wally est dans un état normal.${fatigueLabel ? ` Sa ${fatigueLabel} est en récupération.` : ''}`;
  }
  // Rule 3: Mood dissonance
  else if (hasMoodDissonance) {
    const emotAdj = MOOD_ADJ_FR[dominantEmotion] || dominantEmotion;
    const moodAdj = MOOD_ADJ_FR[dominantMood]    || dominantMood;
    sentence = `Wally est ${emotAdj} en surface mais ${moodAdj} en profondeur.`;
  }
  // Rule 4: Nothing interesting — hide
  else {
    el.style.display = 'none';
    return;
  }

  textEl.textContent = sentence; // textContent — safe, no XSS risk
  el.style.display = 'block';
}

// ── Canvas helpers ────────────────────────────────────────────────────────────

function _canvasContentWidth(canvas) {
  const parent = canvas.parentElement;
  if (!parent) return canvas.offsetWidth || 800;
  const cs = getComputedStyle(parent);
  return Math.floor(parent.clientWidth - parseFloat(cs.paddingLeft) - parseFloat(cs.paddingRight)) || 800;
}

function showGraphEmpty(canvasId, message) {
  const canvas = document.getElementById(canvasId);
  if (!canvas) return;
  const W = _canvasContentWidth(canvas);
  const H = 165;
  const dpr = window.devicePixelRatio || 1;
  canvas.width = W * dpr;
  canvas.height = H * dpr;
  canvas.style.width = W + 'px';
  canvas.style.height = H + 'px';
  const ctx = canvas.getContext('2d');
  ctx.scale(dpr, dpr);
  ctx.fillStyle = '#11151c';
  ctx.fillRect(0, 0, W, H);
  ctx.fillStyle = 'rgba(255,255,255,0.3)';
  ctx.font = '13px Inter, sans-serif';
  ctx.textAlign = 'center';
  ctx.fillText(message, W / 2, H / 2);
}

function hexToRgba(hex, alpha) {
  const r = parseInt(hex.slice(1, 3), 16);
  const g = parseInt(hex.slice(3, 5), 16);
  const b = parseInt(hex.slice(5, 7), 16);
  return `rgba(${r},${g},${b},${alpha})`;
}

function escHtml(str) {
  return str.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}

// Options du `<select>` de provider LLM, bâties sur ce que le SERVEUR déclare
// savoir construire (`cfg.llm_providers`, issu de `SUPPORTED_TEXT_PROVIDERS`).
//
// Les deux options étaient écrites en dur — « OpenAI » et « Claude » — alors que
// la factory n'accepte que `deepseek`. Le provider en cours n'apparaissant pas
// dans la liste, le navigateur affichait « OpenAI » comme sélectionné : la
// première sauvegarde du panneau envoyait donc un provider inconstructible.
//
// Le dictionnaire de libellés est LOCAL à la fonction, pas une `const` de haut
// niveau : un `const` au sommet du fichier se lit avant son initialisation si
// quoi que ce soit l'atteint trop tôt, et cette zone morte a déjà cassé le site.
function providerOptions(cfg, role) {
  const libelles = { deepseek: 'DeepSeek', openai: 'OpenAI', claude: 'Claude (Anthropic)' };
  const actuel = (cfg.llm && cfg.llm[role] && cfg.llm[role].provider) || '';
  const dispos = cfg.llm_providers || [];
  // Un provider configuré mais non supporté reste AFFICHÉ, marqué comme tel :
  // le masquer laisserait croire que le réglage en cours est valide.
  const liste = (!actuel || dispos.indexOf(actuel) !== -1) ? dispos : dispos.concat([actuel]);
  return liste.map(function (p) {
    const suffixe = dispos.indexOf(p) !== -1 ? '' : ' — non supporté';
    return '<option value="' + escAttr(p) + '"' + (p === actuel ? ' selected' : '') + '>'
      + escHtml((libelles[p] || p) + suffixe) + '</option>';
  }).join('');
}

// Options du `<select>` de modèle. Le modèle RÉELLEMENT configuré est toujours
// présent et sélectionné, quitte à être ajouté en tête du catalogue.
//
// Sans ça, ouvrir puis sauvegarder le panneau LLM sans rien toucher suffisait à
// casser le bot : le catalogue vient de l'API OpenAI, le modèle en cours est un
// `deepseek-…` qui n'y figure pas, le navigateur sélectionnait donc le premier
// `gpt-…` de la liste, et « Enregistrer » écrivait cet identifiant OpenAI dans
// `llm.primary.model` — sur un client DeepSeek, et persisté sur disque.
function modelOptions(models, current) {
  const liste = (current && models.indexOf(current) === -1)
    ? [current].concat(models)
    : models;
  return liste.map(function (m) {
    return '<option value="' + escAttr(m) + '"' + (m === current ? ' selected' : '')
      + '>' + escHtml(m) + '</option>';
  }).join('');
}

// Le modèle qui fait foi pour un rôle : la section `llm:` d'abord, la section
// `openai:` héritée seulement en repli — c'est `llm:` que lit `bootstrap`.
function currentModel(cfg, role) {
  return (cfg.llm && cfg.llm[role] && cfg.llm[role].model)
    || (cfg.openai && cfg.openai[role + '_model'])
    || '';
}

async function loadOpenAIModels() {
  const r = await apiFetch('/api/admin/openai/models');
  if (!r || !r.ok) return [];
  const { models } = await r.json();
  return models;
}

async function loadClaudeModels() {
  const r = await apiFetch('/api/admin/claude/models');
  if (!r || !r.ok) return [];
  const { models } = await r.json();
  return models;
}

async function loadNotificationChannels(cfg) {
  const select = document.getElementById('cfg-notif-channel');
  if (!select) return;
  try {
    const r = await apiFetch('/api/admin/notification-channels');
    if (!r || !r.ok) return;
    const data = await r.json();
    const currentChannelId = cfg.bot.notification_channel_id;
    for (const guild of (data.guilds || [])) {
      const group = document.createElement('optgroup');
      group.label = guild.name;
      for (const ch of guild.channels) {
        const opt = document.createElement('option');
        opt.value = String(ch.id);
        opt.textContent = '#' + ch.name;
        if (currentChannelId && String(ch.id) === String(currentChannelId)) opt.selected = true;
        group.appendChild(opt);
      }
      select.appendChild(group);
    }
  } catch (e) { /* silently fail */ }
}

function onProviderChange() {
  const primaryProv = document.getElementById('cfg-primary-provider').value;
  const secondaryProv = document.getElementById('cfg-secondary-provider').value;
  // Toggle model dropdowns based on provider (OpenAI vs Claude)
  const primarySelect = document.getElementById('cfg-primary-model');
  const primaryClaude = document.getElementById('cfg-primary-model-claude');
  const secondarySelect = document.getElementById('cfg-secondary-model');
  const secondaryClaude = document.getElementById('cfg-secondary-model-claude');
  if (primaryProv === 'claude') {
    primarySelect.style.display = 'none';
    primaryClaude.style.display = 'block';
  } else {
    primarySelect.style.display = 'block';
    primaryClaude.style.display = 'none';
  }
  if (secondaryProv === 'claude') {
    secondarySelect.style.display = 'none';
    secondaryClaude.style.display = 'block';
  } else {
    secondarySelect.style.display = 'block';
    secondaryClaude.style.display = 'none';
  }
  // Show/hide provider-specific settings based on primary provider
  const openaiSettings = document.getElementById('openai-specific-settings');
  const claudeSettings = document.getElementById('claude-specific-settings');
  if (openaiSettings) openaiSettings.style.display = primaryProv === 'openai' ? 'block' : 'none';
  if (claudeSettings) claudeSettings.style.display = primaryProv === 'claude' ? 'block' : 'none';
  if (primaryProv === 'claude') onThinkingTypeChange();
  // Show restart notice if provider changed
  const notice = document.getElementById('llm-restart-notice');
  if (notice) notice.style.display = 'block';
}

function onThinkingTypeChange() {
  // Le champ « budget tokens » a été retiré le 2026-08-26 : il pilotait un
  // `ClaudeLLMClient` qui n'existe pas dans ce dépôt, et sa valeur n'était lue
  // par aucun client. Seul `thinking_effort` (adaptive) est branché.
  const type = document.getElementById('cfg-thinking-type')?.value || 'disabled';
  const effortGroup = document.getElementById('thinking-effort-group');
  if (effortGroup) effortGroup.style.display = type === 'adaptive' ? 'block' : 'none';
}

async function saveOpenAI() {
  const primaryProv = document.getElementById('cfg-primary-provider').value;
  const secondaryProv = document.getElementById('cfg-secondary-provider').value;
  const primaryModel = primaryProv === 'claude'
    ? document.getElementById('cfg-primary-model-claude').value
    : document.getElementById('cfg-primary-model').value;
  const secondaryModel = secondaryProv === 'claude'
    ? document.getElementById('cfg-secondary-model-claude').value
    : document.getElementById('cfg-secondary-model').value;

  const payload = {
    openai: {
      primary_model:    primaryModel,
      secondary_model:  secondaryModel,
      reasoning_effort: document.getElementById('cfg-reasoning-effort').value,
      text_verbosity:   document.getElementById('cfg-text-verbosity').value,
      max_tokens:       parseInt(document.getElementById('cfg-max-tokens').value),
    },
    llm: {
      primary: {
        provider: primaryProv,
        model: primaryModel,
        thinking_type: document.getElementById('cfg-thinking-type')?.value || 'disabled',
        thinking_effort: document.getElementById('cfg-thinking-effort')?.value || 'medium',
      },
      secondary: { provider: secondaryProv, model: secondaryModel },
    },
  };
  const r = await apiFetch('/api/admin/config', {
    method: 'POST',
    body: JSON.stringify(payload),
  });
  if (r && r.ok) toast('Config LLM sauvegardée', 'success'); else toast('Erreur sauvegarde', 'error');
}

function updateDecayTime(input, name) {
  const lam = parseFloat(input.value) || 0;
  const timeToZeroH = lam > 0 ? (Math.log(1/0.01)) / lam : Infinity;
  const timeLabel = timeToZeroH === Infinity ? '∞' : timeToZeroH < 1 ? Math.round(timeToZeroH * 60) + ' min' : Math.round(timeToZeroH * 10) / 10 + ' h';
  const span = document.getElementById(`decay-time-${name}`);
  if (span) span.innerHTML = `100→0% en <strong style="color:#e2e8f0">${timeLabel}</strong>`;
}

function updateBoredomTime(input) {
  const r = parseFloat(input.value) || 0;
  let label;
  if (r <= 0) { label = '\u221e'; }
  else { const h = 1/r; label = h < 1 ? Math.round(h*60) + ' min' : Math.round(h*10)/10 + ' h'; }
  const span = document.getElementById('boredom-time-info');
  if (span) {
    span.textContent = '';
    span.append('0\u2192100% en ');
    const strong = document.createElement('strong');
    strong.style.color = '#e2e8f0';
    strong.textContent = label;
    span.appendChild(strong);
  }
}

async function saveEmotionLambdas() {
  const emotions = {};
  for (const e of EMOTIONS) {
    if (e === 'boredom') continue;
    const el = document.getElementById(`cfg-lambda-${e}`);
    if (el) emotions[e] = { decay_lambda: parseFloat(el.value) };
  }
  const boredomRise = document.getElementById('cfg-boredom-rise');
  if (boredomRise) emotions['boredom'] = { decay_lambda: 0.01, boredom_rise_per_hour: parseFloat(boredomRise.value) };
  const r = await apiFetch('/api/admin/config', { method: 'POST', body: JSON.stringify({ emotions }) });
  if (r && r.ok) toast('Lambdas sauvegardés', 'success'); else toast('Erreur sauvegarde', 'error');
}

async function saveBotGeneral() {
  const triggers = document.getElementById('cfg-triggers').value
    .split(',').map(s => s.trim()).filter(Boolean);
  const r = await apiFetch('/api/admin/config', {
    method: 'POST',
    body: JSON.stringify({ bot: {
      language_default: document.getElementById('cfg-lang').value,
      journal_time:     document.getElementById('cfg-journal-time').value,
      context_window_size: parseInt(document.getElementById('cfg-ctx-size').value),
      trigger_names:    triggers,
      cost_alert_threshold: parseFloat(document.getElementById('cfg-cost-threshold').value),
      notification_channel_id: document.getElementById('cfg-notif-channel').value || null,
    }}),
  });
  if (r && r.ok) toast('Config bot sauvegardée', 'success'); else toast('Erreur sauvegarde', 'error');
}

// ── Anti-spam config ──────────────────────────────────────────────────────────

async function saveSpamConfig() {
  const exemptRaw = document.getElementById('cfg-spam-exempt').value;
  const exempt = exemptRaw.split(',').map(s => s.trim()).filter(Boolean).map(Number).filter(n => !isNaN(n));
  const r = await apiFetch('/api/admin/config', {
    method: 'POST',
    body: JSON.stringify({ discord: { spam_detection: {
      enabled:          document.getElementById('cfg-spam-enabled').checked,
      max_messages:     parseInt(document.getElementById('cfg-spam-max').value),
      window_seconds:   parseInt(document.getElementById('cfg-spam-window').value),
      mute_minutes:     parseInt(document.getElementById('cfg-spam-mute').value),
      spam_anger_delta: parseFloat(document.getElementById('cfg-spam-anger').value),
      exempt_channels:  exempt,
    }}}),
  });
  if (r && r.ok) toast('Config anti-spam sauvegardée', 'success'); else toast('Erreur sauvegarde', 'error');
}

// ── Guest channels ─────────────────────────────────────────────────────────────

async function addGuestChannel() {
  const input = document.getElementById('guest-channel-input');
  const errEl = document.getElementById('guest-channel-error');
  if (!input || !errEl) return;
  const name = input.value.trim().toLowerCase();
  errEl.style.display = 'none';

  if (!name || !/^[a-z0-9_]{1,25}$/.test(name)) {
    errEl.textContent = 'Nom de chaîne invalide (1–25 caractères, alphanumériques + _).';
    errEl.style.display = 'block';
    return;
  }

  const r = await apiFetch('/api/admin/twitch/channels', {
    method: 'POST',
    body: JSON.stringify({ name }),
  });

  if (!r) { errEl.textContent = 'Erreur réseau.'; errEl.style.display = 'block'; return; }
  if (r.status === 409) { errEl.textContent = 'Chaîne déjà ajoutée.'; errEl.style.display = 'block'; return; }
  if (r.status === 404) { errEl.textContent = 'Chaîne introuvable sur Twitch.'; errEl.style.display = 'block'; return; }
  if (r.status === 503) { errEl.textContent = 'API Twitch indisponible.'; errEl.style.display = 'block'; return; }
  if (!r.ok) { errEl.textContent = 'Erreur serveur.'; errEl.style.display = 'block'; return; }

  const list = document.getElementById('guest-channels-list');
  const empty = list.querySelector('p');
  if (empty) empty.remove();
  const item = document.createElement('div');
  item.id = 'guest-ch-' + name;
  item.className = 'twitch-channel-card';
  // name is validated ^[a-z0-9_]{1,25}$ before reaching here — safe for innerHTML
  item.innerHTML = '<div class="tc-dot pending"></div>'
    + '<span class="tc-name">' + name + '</span>'
    + '<span class="tc-badge offline">hors ligne</span>'
    + '<button class="tc-kick" onclick="removeGuestChannel(\'' + name + '\')">Déconnecter</button>';
  list.appendChild(item);
  input.value = '';
  toast(`Wally rejoint ${name}`, 'success');
}

async function removeGuestChannel(name) {
  const r = await apiFetch(`/api/admin/twitch/channels/${encodeURIComponent(name)}`, { method: 'DELETE' });
  if (r && r.ok) {
    const el = document.getElementById(`guest-ch-${name}`);
    if (el) el.remove();
    const list = document.getElementById('guest-channels-list');
    if (list && !list.querySelector('.twitch-channel-card, .guest-channel-item')) {
      list.innerHTML = '<p style="color:var(--text-muted);margin:0 0 12px">Aucune chaîne invitée.</p>';
    }
    toast(`Wally a quitté ${name}`, 'success');
  } else {
    toast('Erreur lors de la suppression', 'error');
  }
}

// ── Twitch Channels Tab ────────────────────────────────────────────

async function setEmotion(emotion, value) {
  const r = await apiFetch('/api/admin/emotions/set', {
    method: 'POST',
    body: JSON.stringify({ emotion, value }),
  });
  if (r && r.ok) toast(`${emotion}: ${value.toFixed(2)}`, 'success');
  else toast('Erreur', 'error');
}

async function resetEmotions() {
  const r = await apiFetch('/api/admin/emotions/reset', { method: 'POST' });
  if (r && r.ok) {
    for (const e of EMOTIONS) {
      const s = document.getElementById(`slider-${e}`);
      if (s) { s.value = 0.5; document.getElementById(`val-${e}`).textContent = '0.50'; }
    }
    toast('Émotions reset à 0.5', 'success');
  } else {
    toast('Erreur reset', 'error');
  }
}

// ── Admin logs SSE ────────────────────────────────────────────────────────────

async function startLogSSE() {
  if (logSSE) logSSE.close();
  const token = getToken();
  if (!token) return;

  await loadLogHistory();

  logSSE = await openAdminSSE('/api/admin/sse/logs');
  if (!logSSE) return;
  logSSE.onmessage = (e) => {
    try {
      const data = JSON.parse(e.data);
      if (data.type === 'links_analyzed' || data.type === 'link_accepted' || data.type === 'link_rejected' || data.type === 'link_unlinked') {
        chargerPersonnes();
        pollLinksBadge();
        if (data.type === 'links_analyzed' && data.count > 0) {
          toast(`🔗 ${data.count} liaison(s) à vérifier`, 'info');
        }
        return;
      }
      if (data.type === 'twitch_auth') {
        _onTwitchAuthSuccess(data.account, data.username);
        return;
      }
      appendLog(data);
    } catch (err) {
      // Une ligne illisible ne doit pas tuer le flux — mais elle doit se voir :
      // muet, c'est le panneau Logs qui se vide sans que personne sache pourquoi.
      console.warn('flux logs : message ignoré', err, e.data);
    }
  };
}

async function loadLogHistory() {
  const r = await apiFetch('/api/admin/logs/history');
  if (!r || !r.ok) return;
  const { entries } = await r.json();
  for (const entry of entries) appendLog(entry);
}

function stopLogSSE() {
  if (logSSE) { logSSE.close(); logSSE = null; }
}

// ── Vocal (suivi/debug STT + réponses) ───────────────────────────────────────
let voiceSSE = null;
let _voiceEvents = [];
const MAX_VOICE_EVENTS = 400;

function renderVoiceTab(cible) {
  // La cible est passée par la page Voix, qui l'héberge en section.
  const el = cible || document.getElementById('tab-admin-voice');
  if (!el || el.querySelector('#voice-stream')) return;  // déjà rendu
  el.innerHTML = `
    <div class="voice-debug">
      <div class="voice-toolbar">
        <h2 class="voice-title">🎙️ Suivi vocal <span id="voice-status" class="voice-status off">○ hors ligne</span></h2>
        <div class="voice-filters">
          <label><input type="checkbox" id="vf-heard" checked onchange="renderVoiceList()"> 🎤 entendu</label>
          <label><input type="checkbox" id="vf-reply" checked onchange="renderVoiceList()"> 💬 réponses</label>
          <label><input type="checkbox" id="vf-ignored" checked onchange="renderVoiceList()"> 🔇 ignorés</label>
          <button class="control-bar-btn" onclick="clearVoice()">Vider</button>
        </div>
      </div>
      <div id="voice-live" class="voice-live"></div>
      <div id="voice-stream" class="voice-stream"></div>
    </div>`;
}

// Transcriptions partielles en cours (STT streaming), par locuteur — éphémères, non historisées.
let _voiceLive = {};

function _renderVoiceLive() {
  const el = document.getElementById('voice-live');
  if (!el) return;
  el.innerHTML = Object.values(_voiceLive).map(e =>
    `<div class="v-row v-partial"><span class="v-ico">✍️</span>`
    + `<span class="v-who">${escapeHtml(e.speaker || '?')}</span>`
    + `<span class="v-text">${escapeHtml(e.text || '')}</span>`
    + `<span class="v-live-dot">●</span></div>`).join('');
}

function _voiceRow(e) {
  const hh = new Date(e.ts ? e.ts * 1000 : Date.now()).toLocaleTimeString('fr-FR');
  const chan = e.channel_name ? `<span class="v-chan">${escapeHtml(e.channel_name)}</span>` : '';
  if (e.type === 'reply') {
    return `<div class="v-row v-reply"><span class="v-time">${hh}</span><span class="v-ico">💬</span>`
      + `<span class="v-who">${escapeHtml(e.speaker || 'Wally')}</span>`
      + `<span class="v-text">${escapeHtml(e.text || '')}</span>`
      + (e.gen_ms != null ? `<span class="v-lat">${e.gen_ms} ms</span>` : '') + `</div>`;
  }
  if (e.type === 'ignored') {
    return `<div class="v-row v-ignored"><span class="v-time">${hh}</span><span class="v-ico">🔇</span>${chan}`
      + `<span class="v-who">${escapeHtml(e.speaker || '?')}</span>`
      + `<span class="v-text">${escapeHtml(e.text || '')}</span>`
      + `<span class="v-reason">${escapeHtml(e.reason || 'ignoré')}</span></div>`;
  }
  return `<div class="v-row v-heard"><span class="v-time">${hh}</span><span class="v-ico">🎤</span>${chan}`
    + `<span class="v-who">${escapeHtml(e.speaker || '?')}</span>`
    + `<span class="v-text">${escapeHtml(e.text || '')}</span>`
    + (e.stt_ms != null ? `<span class="v-lat">STT ${e.stt_ms} ms</span>` : '') + `</div>`;
}

function renderVoiceList() {
  const el = document.getElementById('voice-stream');
  if (!el) return;
  const show = {
    heard: document.getElementById('vf-heard')?.checked !== false,
    reply: document.getElementById('vf-reply')?.checked !== false,
    ignored: document.getElementById('vf-ignored')?.checked !== false,
  };
  const atBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 80;
  el.innerHTML = _voiceEvents.filter(e => show[e.type] !== false).map(_voiceRow).join('')
    || `<div class="voice-empty">En attente d'activité vocale… (Wally doit être dans un salon vocal)</div>`;
  if (atBottom) el.scrollTop = el.scrollHeight;
}

function _pushVoice(e) {
  _voiceEvents.push(e);
  if (_voiceEvents.length > MAX_VOICE_EVENTS) _voiceEvents = _voiceEvents.slice(-MAX_VOICE_EVENTS);
}

function clearVoice() { _voiceEvents = []; _voiceLive = {}; _renderVoiceLive(); renderVoiceList(); }

function _setVoiceStatus(txt, on) {
  const s = document.getElementById('voice-status');
  if (s) { s.textContent = txt; s.className = 'voice-status ' + (on ? 'on' : 'off'); }
}

async function startVoiceSSE() {
  if (voiceSSE) voiceSSE.close();
  if (!getToken()) return;
  _voiceEvents = [];
  _voiceLive = {}; _renderVoiceLive();
  // Historique persistant d'abord (recent() = décroissant → on inverse pour l'ordre chrono).
  const r = await apiFetch('/api/admin/voice/history?limit=200');
  if (r && r.ok) {
    const { events } = await r.json();
    (events || []).slice().reverse().forEach(_pushVoice);
  }
  renderVoiceList();
  voiceSSE = await openAdminSSE('/api/admin/sse/voice');
  if (!voiceSSE) { _setVoiceStatus('○ déconnecté', false); return; }
  voiceSSE.onopen = () => _setVoiceStatus('● live', true);
  voiceSSE.onerror = () => _setVoiceStatus('○ déconnecté', false);
  voiceSSE.onmessage = (ev) => {
    try {
      const e = JSON.parse(ev.data);
      const key = e.speaker_id || e.speaker;
      if (e.type === 'partial') {           // transcription live → bande, pas d'historique
        if (key) { _voiceLive[key] = e; _renderVoiceLive(); }
        return;
      }
      if (e.type === 'heard' && key && _voiceLive[key]) {  // final reçu → retire le live
        delete _voiceLive[key]; _renderVoiceLive();
      }
      _pushVoice(e); renderVoiceList();
    } catch (err) {
      console.warn('flux vocal : message ignoré', err, ev.data);
    }
  };
}

function stopVoiceSSE() {
  if (voiceSSE) { voiceSSE.close(); voiceSSE = null; }
}

// ── Journal ──────────────────────────────────────────────────────────────────
//
// Refonte du 2026-08-28. L'écran portait TROIS barres d'onglets empilées —
// Système › Logs › Flux — soit trois décisions avant de voir une ligne. Elles
// deviennent une ligne de filtres, et l'état vit dans l'URL : un lien vers
// « les erreurs eventsub » se partage et survit au rechargement.

const MAX_LOG_ENTRIES = 400;

const _JOURNAL_NIVEAUX = [
  ['ALL', 'Tout'], ['INFO', 'Info'], ['WARNING', 'Warning'], ['ERROR', 'Error'],
];

// Les quatre sections de la page, dans l'ordre. Le sommaire d'ancres en dérive :
// une section ajoutée ici apparaît dans le sommaire sans autre geste.
const _JOURNAL_SECTIONS = [
  ['journal-flux', 'Flux en direct'],
  ['journal-erreurs', 'Erreurs groupées'],
  ['journal-stats', 'Statistiques'],
  ['journal-vider', 'Vider le journal'],
];

// L'état des filtres SURVIT au changement de page : on quitte le Journal pour
// vérifier une tâche, on y revient, et la recherche est encore là.
let _journalFiltres = { q: '', niveau: 'ALL', vue: 'bot', sous: [] };

// Les sous-systèmes vus dans le flux. Ils ne sont pas listés en dur : une puce
// apparaît parce qu'un module a parlé. Un module neuf est donc filtrable le
// jour où il émet sa première ligne, sans que personne ait à l'ajouter ici.
let _journalSousSystemes = new Set();

// Le suivi automatique : on colle en bas tant que l'utilisateur n'a pas remonté.
let _journalSuivi = true;

/** Le sous-système d'une ligne, dérivé du module qui l'a émise.
 *
 *  `bot.twitch.events` → `twitch` · `bot.discord.voice.streaming` →
 *  `discord.voice` · `bot.core.llm.openai_client` → `core.llm`.
 *
 *  On retire le dernier segment — le fichier — parce que c'est lui qui varie :
 *  le garder ferait une puce par module, soit deux cents puces illisibles.
 */
function _sousSysteme(source) {
  if (!source) return '';
  const bouts = String(source).split('.');
  if (bouts[0] === 'bot') bouts.shift();
  if (bouts.length > 1) bouts.pop();
  return bouts.join('.');
}

// ── Filtres dans l'URL ──────────────────────────────────────────────────────

/** Lit les filtres depuis la partie requête du hash. */
function _lireFiltresJournal() {
  const brut = location.hash.replace(/^#\/?/, '');
  const coupe = brut.indexOf('?');
  if (coupe === -1) return false;
  const p = new URLSearchParams(brut.slice(coupe + 1));
  _journalFiltres = {
    q: p.get('q') || '',
    niveau: (p.get('niveau') || 'ALL').toUpperCase(),
    vue: p.get('vue') === 'visiteurs' ? 'visiteurs' : 'bot',
    sous: (p.get('sous') || '').split(',').filter(Boolean),
  };
  return true;
}

/** Réécrit la requête du hash sans toucher au chemin.
 *
 *  La route ne change pas, donc `routerVersHash` ne remonte pas la page : la
 *  garde d'égalité du routeur est exactement ce qui rend ce geste gratuit.
 */
function _ecrireFiltresJournal() {
  // Garde indispensable : `enterAdmin()` construit le Journal au démarrage,
  // quelle que soit la page d'arrivée, pour que `#log-stream` existe avant le
  // premier événement SSE. Sans cette ligne, ce montage réécrivait le hash en
  // « #/systeme/journal » AVANT que le routeur ne tourne — et un lien vers une
  // fiche personne ne survivait pas au rechargement. Vu au smoke test.
  if (currentRoute !== 'systeme/journal') return;
  const p = new URLSearchParams();
  const f = _journalFiltres;
  if (f.q) p.set('q', f.q);
  if (f.niveau !== 'ALL') p.set('niveau', f.niveau.toLowerCase());
  if (f.vue !== 'bot') p.set('vue', f.vue);
  if (f.sous.length) p.set('sous', f.sous.join(','));
  const requete = p.toString();
  const vise = '#/systeme/journal' + (requete ? '?' + requete : '');
  if (location.hash !== vise) history.replaceState(null, '', vise);
}

// ── Rendu ───────────────────────────────────────────────────────────────────

/** Construit le panneau, sans l'ouvrir comme page.
 *
 *  Appelé au démarrage par `enterAdmin()`, quelle que soit la page d'arrivée :
 *  `#log-stream` doit exister avant le premier événement du flux, sinon les
 *  lignes déjà émises sont perdues. Ce chemin ne touche NI aux filtres, NI à
 *  l'URL, NI au sommaire — il n'est pas la page.
 */
function _construireJournal() {
  const el = document.getElementById('tab-admin-journal');
  if (!el) return;

  if (!document.getElementById('log-stream')) {
    el.innerHTML = `
      <div class="journal-filtres">
        <input type="search" class="champ-recherche" id="journal-q"
               placeholder="Filtrer les lignes…" aria-label="Filtrer les lignes du journal">
        <div class="segmented" id="journal-niveaux" role="group" aria-label="Niveau"></div>
        <div class="segmented" id="journal-vues" role="group" aria-label="Source">
          <button data-vue="bot">Bot</button>
          <button data-vue="visiteurs">Visiteurs</button>
        </div>
      </div>
      <div class="journal-puces" id="journal-puces"></div>
      <div id="journal-flux">
        <div class="log-stream" id="log-stream" role="log" aria-live="polite"
             aria-label="Flux de logs"></div>
      </div>
      <div id="journal-visiteurs" hidden></div>
      <div class="page-section" id="journal-erreurs"></div>
      <div class="page-section" id="journal-stats"></div>
      <div class="page-section" id="journal-vider">
        <div class="page-section-titre">Vider le journal</div>
        <div class="page-section-sous">
          Efface ce qui est AFFICHÉ ici. <code>app.log</code> reste intact sur le
          disque — c'est lui la source de vérité.
        </div>
        <button class="btn" id="journal-vider-btn">Vider l'affichage</button>
      </div>`;

    el.querySelector('#journal-niveaux').innerHTML = _JOURNAL_NIVEAUX
      .map(([cle, lib]) => `<button data-niveau="${cle}" class="niv-${cle}">${lib}</button>`)
      .join('');

    _cablerJournal(el);
  }
}

function renderJournal() {
  _construireJournal();
  if (!document.getElementById('log-stream')) return;

  // La requête du hash prime sur l'état mémorisé : c'est elle qu'on partage.
  // Sans requête, on restitue les filtres d'avant et on les réécrit dans l'URL,
  // pour que la page affiche et l'URL disent la même chose.
  if (!_lireFiltresJournal()) _ecrireFiltresJournal();

  _majCommandesJournal();
  _rendrePucesJournal();
  _appliquerFiltresJournal();
  _rendreSommaireJournal();
  chargerErreursGroupees();
}

/** Un seul écouteur par zone, posé UNE fois. Le panneau ne se reconstruit
 *  jamais après coup — les gestes doivent donc survivre à tous les rendus de
 *  filtre, et surtout ne pas s'empiler à chaque visite de la page. */
function _cablerJournal(el) {
  const q = el.querySelector('#journal-q');
  q.addEventListener('input', function () {
    _journalFiltres.q = q.value.trim();
    _ecrireFiltresJournal();
    _appliquerFiltresJournal();
  });

  el.querySelector('#journal-niveaux').addEventListener('click', function (ev) {
    const b = ev.target.closest('[data-niveau]');
    if (!b) return;
    _journalFiltres.niveau = b.dataset.niveau;
    _ecrireFiltresJournal();
    _majCommandesJournal();
    _appliquerFiltresJournal();
  });

  el.querySelector('#journal-vues').addEventListener('click', function (ev) {
    const b = ev.target.closest('[data-vue]');
    if (!b) return;
    _journalFiltres.vue = b.dataset.vue;
    _ecrireFiltresJournal();
    _majCommandesJournal();
    if (_journalFiltres.vue === 'visiteurs') loadVisitorsInPanel();
  });

  el.querySelector('#journal-puces').addEventListener('click', function (ev) {
    const b = ev.target.closest('[data-sous]');
    if (!b) return;
    const nom = b.dataset.sous;
    const i = _journalFiltres.sous.indexOf(nom);
    if (i === -1) _journalFiltres.sous.push(nom);
    else _journalFiltres.sous.splice(i, 1);
    _ecrireFiltresJournal();
    _rendrePucesJournal();
    _appliquerFiltresJournal();
  });

  el.querySelector('#journal-vider-btn').addEventListener('click', function () {
    const flux = document.getElementById('log-stream');
    if (flux) flux.innerHTML = '';
    _journalSousSystemes = new Set();
    _rendrePucesJournal();
  });

  // Le suivi se SUSPEND dès qu'on remonte, et se réarme en revenant en bas.
  // Sans ça, lire une erreur de 15 h 02 est impossible dès que le bot parle :
  // chaque ligne ramenait la vue tout en bas.
  const flux = el.querySelector('#log-stream');
  flux.addEventListener('scroll', function () {
    const enBas = flux.scrollHeight - flux.scrollTop - flux.clientHeight < 24;
    if (enBas !== _journalSuivi) {
      _journalSuivi = enBas;
      _majSuiviJournal();
    }
  });
}

function _majCommandesJournal() {
  const el = document.getElementById('tab-admin-journal');
  if (!el) return;
  const q = el.querySelector('#journal-q');
  if (q && q.value !== _journalFiltres.q) q.value = _journalFiltres.q;
  el.querySelectorAll('[data-niveau]').forEach(function (b) {
    b.classList.toggle('active', b.dataset.niveau === _journalFiltres.niveau);
  });
  el.querySelectorAll('[data-vue]').forEach(function (b) {
    b.classList.toggle('active', b.dataset.vue === _journalFiltres.vue);
  });

  // « Visiteurs » n'est pas un autre onglet : c'est la même page, une autre
  // source. Le flux et ses filtres de ligne n'ont alors plus d'objet.
  const visiteurs = _journalFiltres.vue === 'visiteurs';
  el.querySelector('#journal-flux').hidden = visiteurs;
  el.querySelector('#journal-puces').hidden = visiteurs;
  el.querySelector('#journal-niveaux').hidden = visiteurs;
  el.querySelector('#journal-visiteurs').hidden = !visiteurs;
}

function _majSuiviJournal() {
  const el = document.getElementById('journal-suivi');
  if (!el) return;
  el.textContent = _journalSuivi ? 'suivi automatique' : 'suivi suspendu';
  el.classList.toggle('suspendu', !_journalSuivi);
}

function _rendrePucesJournal() {
  const boite = document.getElementById('journal-puces');
  if (!boite) return;
  const noms = Array.from(_journalSousSystemes).sort();
  boite.innerHTML = noms.map(function (n) {
    const actif = _journalFiltres.sous.indexOf(n) !== -1;
    return '<button class="puce' + (actif ? ' active' : '') + '" data-sous="'
      + escAttr(n) + '" aria-pressed="' + actif + '">' + escHtml(n)
      + (actif ? ' ✕' : '') + '</button>';
  }).join('') + '<span class="journal-suivi" id="journal-suivi"></span>';
  _majSuiviJournal();
}

/** Applique les trois filtres aux lignes DÉJÀ dans le DOM.
 *
 *  Un filtre masque, il ne redemande rien au serveur : le flux est un direct,
 *  pas une requête. Recharger perdrait les lignes reçues entre-temps.
 */
function _appliquerFiltresJournal() {
  const f = _journalFiltres;
  const q = f.q.toLowerCase();
  document.querySelectorAll('#log-stream .log-entry').forEach(function (e) {
    let visible = f.niveau === 'ALL' || e.dataset.niveau === f.niveau;
    if (visible && f.sous.length) visible = f.sous.indexOf(e.dataset.sous) !== -1;
    if (visible && q) visible = (e.dataset.recherche || '').indexOf(q) !== -1;
    e.classList.toggle('hidden', !visible);
  });
  _collerEnBasJournal();
}

function _collerEnBasJournal() {
  const el = document.getElementById('log-stream');
  if (el && _journalSuivi) el.scrollTop = el.scrollHeight;
}

function appendLog(entry) {
  const el = document.getElementById('log-stream');
  if (!el) return;

  const sous = _sousSysteme(entry.source);
  if (sous && !_journalSousSystemes.has(sous)) {
    _journalSousSystemes.add(sous);
    _rendrePucesJournal();
  }

  const div = document.createElement('div');
  div.className = 'log-entry ' + entry.level;
  div.dataset.niveau = entry.level;
  div.dataset.sous = sous;
  // La clé de recherche est calculée UNE fois, à l'insertion : la recalculer à
  // chaque frappe, c'est quatre cents `toLowerCase` par caractère tapé.
  div.dataset.recherche = ((entry.message || '') + ' ' + (entry.source || '')).toLowerCase();

  const heure = document.createElement('span');
  heure.className = 'log-heure';
  heure.textContent = entry.time;
  const niveau = document.createElement('span');
  niveau.className = 'log-niveau';
  niveau.textContent = entry.level === 'WARNING' ? 'WARN' : entry.level;
  const message = document.createElement('span');
  message.className = 'log-message';
  message.textContent = entry.message;
  div.append(heure, niveau, message);

  const f = _journalFiltres;
  let visible = f.niveau === 'ALL' || entry.level === f.niveau;
  if (visible && f.sous.length) visible = f.sous.indexOf(sous) !== -1;
  if (visible && f.q) visible = div.dataset.recherche.indexOf(f.q.toLowerCase()) !== -1;
  if (!visible) div.classList.add('hidden');

  el.appendChild(div);
  while (el.children.length > MAX_LOG_ENTRIES) el.removeChild(el.firstChild);
  _collerEnBasJournal();
}

// ── Erreurs groupées et statistiques ────────────────────────────────────────

/** Ce que le flux chronologique ne peut pas dire : combien de fois.
 *
 *  Quarante occurrences de la même panne défilent, on lit la dernière, et rien
 *  n'indique que c'est la quarantième.
 */
async function chargerErreursGroupees() {
  const boiteErr = document.getElementById('journal-erreurs');
  const boiteStat = document.getElementById('journal-stats');
  if (!boiteErr || !boiteStat) return;

  const r = await apiFetch('/api/admin/journal/erreurs');
  if (!r || !r.ok) {
    // Dire qu'on n'a pas pu lire, jamais afficher « 0 erreur » : un zéro faux
    // est pire qu'une absence avouée.
    boiteErr.innerHTML = '<div class="page-section-titre">Erreurs groupées</div>'
      + '<div class="page-section-sous">Journal illisible pour le moment.</div>';
    boiteStat.innerHTML = '';
    poserSommaireJournalEncart(null);
    return;
  }
  const d = await r.json();
  const groupes = d.groupes || [];
  const niveaux = d.niveaux || {};

  boiteErr.innerHTML = '<div class="page-section-titre">Erreurs groupées</div>'
    + '<div class="page-section-sous">'
    + (groupes.length
        ? 'Les mêmes erreurs rassemblées, la plus fréquente en premier — '
          + escHtml(d.fichier || '')
        : 'Aucune erreur dans ' + escHtml(d.fichier || 'le journal du jour') + '.')
    + '</div>'
    + groupes.map(function (g) {
        return '<div class="journal-groupe">'
          + '<div><div class="journal-groupe-msg">' + escHtml(g.message) + '</div>'
          + '<div class="journal-groupe-src">' + escHtml(g.source || '—') + '</div></div>'
          + '<div class="journal-groupe-compte">' + Number(g.fois) + ' fois'
          + '<br>dernière ' + escHtml(g.derniere) + '</div>'
          + '</div>';
      }).join('');

  const tuile = function (label, valeur, classe) {
    return '<div class="journal-stat"><div class="journal-stat-label">' + label
      + '</div><div class="journal-stat-valeur ' + (classe || '') + '">' + valeur
      + '</div></div>';
  };
  boiteStat.innerHTML = '<div class="page-section-titre">Statistiques</div>'
    + '<div class="page-section-sous">Sur ' + Number(d.lignes || 0)
    + ' ligne(s) de ' + escHtml(d.fichier || 'aujourd\'hui') + '.</div>'
    + '<div class="journal-stats">'
    + tuile('Info', Number(niveaux.INFO || 0))
    + tuile('Warning', Number(niveaux.WARNING || 0), 'warn')
    + tuile('Error', Number(niveaux.ERROR || 0) + Number(niveaux.CRITICAL || 0), 'err')
    + tuile('Sous-systèmes', _journalSousSystemes.size)
    + '</div>';

  poserSommaireJournalEncart(groupes[0] || null);
}

// ── Sommaire d'ancres ───────────────────────────────────────────────────────

let _journalEncart = null;

function poserSommaireJournalEncart(groupe) {
  _journalEncart = groupe;
  _rendreSommaireJournal();
}

function _rendreSommaireJournal() {
  const g = _journalEncart;
  poserSommaire('systeme/journal', _JOURNAL_SECTIONS, g
    ? '<div class="rail-encart alerte">'
      + '<div class="rail-encart-titre">Erreur la plus fréquente</div>'
      + '<div class="rail-encart-ligne">' + escHtml(g.message) + '</div>'
      + '<div class="rail-encart-meta">' + Number(g.fois) + ' fois · dernière à '
      + escHtml(g.derniere) + '</div></div>'
    : '');
}

async function loadVisitorsInPanel() {
  const el = document.getElementById('journal-visiteurs');
  if (!el) return;

  const [rc, rb] = await Promise.all([
    apiFetch('/api/admin/chat-connections?limit=100'),
    apiFetch('/api/admin/chat-bans'),
  ]);
  if (!rc || !rc.ok || !rb || !rb.ok) { el.textContent = 'Erreur de chargement'; return; }
  const conns = (await rc.json()).connections || [];
  const bans = (await rb.json()).bans || [];

  const _btnStyle = 'padding:4px 12px;font-size:12px;';

  // ── Section Bannis ──
  let bansCard = '';
  if (bans.length) {
    let brows = '';
    for (const b of bans) {
      const when = b.banned_at
        ? new Date(b.banned_at * 1000).toLocaleDateString('fr-FR', { day: '2-digit', month: '2-digit', year: '2-digit' })
        : '';
      brows += `
        <div class="visitor-row">
          <div class="visitor-avatar-placeholder"></div>
          <div class="visitor-info">
            <strong>${escHtml(b.username || b.discord_id)}</strong>
            <span class="visitor-date">banni le ${escHtml(when)}${b.reason ? ' · ' + escHtml(b.reason) : ''}</span>
          </div>
          <div class="visitor-meta">
            <button class="btn btn-outline" style="${_btnStyle}" data-action="unban" data-id="${escAttr(b.discord_id)}">Débannir</button>
          </div>
        </div>`;
    }
    bansCard = `
      <div class="card" style="margin-bottom:16px;">
        <div class="card-title">BANNIS (${bans.length})</div>
        <div class="visitor-list">${brows}</div>
      </div>`;
  }

  // ── Connexions récentes (groupées par utilisateur) ──
  let connCard;
  if (conns.length === 0) {
    connCard = '<div class="card"><p style="color:var(--text-secondary)">Aucune connexion enregistrée</p></div>';
  } else {
    // Regroupe par discord_id ; on garde les infos les plus récentes (pseudo/avatar).
    const groups = new Map();
    for (const c of conns) {
      let g = groups.get(c.discord_id);
      if (!g) {
        g = { discord_id: c.discord_id, username: c.username, avatar_url: c.avatar_url,
              banned: false, conns: [], totalMsgs: 0, online: false, lastConnected: 0 };
        groups.set(c.discord_id, g);
      }
      g.conns.push(c);
      g.totalMsgs += parseInt(c.message_count, 10) || 0;
      if (!c.disconnected_at) g.online = true;
      if (c.banned) g.banned = true;
      if (c.connected_at > g.lastConnected) {
        g.lastConnected = c.connected_at;
        g.username = c.username;
        if (c.avatar_url) g.avatar_url = c.avatar_url;
      }
    }
    const sorted = [...groups.values()].sort((a, b) => b.lastConnected - a.lastConnected);

    let rows = '';
    for (const g of sorted) {
      const lastD = new Date(g.lastConnected * 1000);
      const lastStr = lastD.toLocaleDateString('fr-FR', { day: '2-digit', month: '2-digit' })
        + ' ' + lastD.toLocaleTimeString('fr-FR', { hour: '2-digit', minute: '2-digit' });
      const avatarHtml = g.avatar_url
        ? `<img src="${escAttr(g.avatar_url)}" class="visitor-avatar" alt="">`
        : '<div class="visitor-avatar-placeholder"></div>';
      const actionBtn = g.banned
        ? `<button class="btn btn-outline" style="${_btnStyle}" data-action="unban" data-id="${escAttr(g.discord_id)}">Débannir</button>`
        : `<button class="btn btn-danger" style="${_btnStyle}" data-action="ban" data-id="${escAttr(g.discord_id)}" data-username="${escAttr(g.username || '')}">Bannir</button>`;
      const onlineBadge = g.online ? '<span style="color:#00E5A0;font-size:12px;">● en ligne</span>' : '';
      const plural = g.conns.length > 1 ? 's' : '';

      // Détail replié : historique des connexions de cet utilisateur (chrono décroissant)
      let detail = '';
      for (const c of g.conns) {
        const t = new Date(c.connected_at * 1000);
        const ds = t.toLocaleDateString('fr-FR', { day: '2-digit', month: '2-digit' });
        const ts = t.toLocaleTimeString('fr-FR', { hour: '2-digit', minute: '2-digit' });
        const dur = c.disconnected_at
          ? formatDuration(c.disconnected_at - c.connected_at)
          : '<span style="color:#00E5A0">en ligne</span>';
        detail += `
          <div class="visitor-row" style="padding-left:52px;opacity:.85;">
            <div class="visitor-info"><span class="visitor-date">${escHtml(ds)} ${escHtml(ts)}</span></div>
            <div class="visitor-meta">
              <span class="visitor-msgs">${parseInt(c.message_count, 10)} msg</span>
              <span class="visitor-duration">${dur}</span>
            </div>
          </div>`;
      }

      rows += `
        <div class="visitor-row visitor-group" style="cursor:pointer;">
          ${avatarHtml}
          <div class="visitor-info">
            <strong><span class="visitor-chevron" style="color:var(--text-secondary);font-size:11px;">▸</span> ${escHtml(g.username)}</strong>
            <span class="visitor-date">${g.conns.length} connexion${plural} · dernière ${escHtml(lastStr)}</span>
          </div>
          <div class="visitor-meta">
            ${onlineBadge}
            <span class="visitor-msgs">${g.totalMsgs} msg</span>
            ${actionBtn}
          </div>
        </div>
        <div class="visitor-detail" style="display:none;">
          <div style="padding:8px 52px 2px;font-size:10px;letter-spacing:.5px;color:var(--text-secondary);text-transform:uppercase;">Connexions</div>
          ${detail}
          <div style="padding:12px 52px 2px;font-size:10px;letter-spacing:.5px;color:var(--text-secondary);text-transform:uppercase;">Messages envoyés</div>
          <div class="visitor-messages" data-id="${escAttr(g.discord_id)}" data-loaded="0" style="padding:2px 52px 10px;">
            <span style="color:var(--text-secondary);font-size:12px;">…</span>
          </div>
        </div>`;
    }
    connCard = `
      <div class="card">
        <div class="card-title">CONNEXIONS RECENTES AU CHAT WEB</div>
        <div class="visitor-list">${rows}</div>
      </div>`;
  }

  el.innerHTML = bansCard + connCard;

  // Ban / unban (délégation — pseudos à quotes). stopPropagation : ne pas déplier le groupe.
  el.querySelectorAll('button[data-action]').forEach((btn) => {
    btn.addEventListener('click', (e) => {
      e.stopPropagation();
      const id = btn.getAttribute('data-id');
      if (btn.getAttribute('data-action') === 'ban') banUser(id, btn.getAttribute('data-username'));
      else unbanUser(id);
    });
  });

  // Clic sur un utilisateur → déplie/replie ses connexions + ses messages (lazy).
  el.querySelectorAll('.visitor-group').forEach((row) => {
    row.addEventListener('click', () => {
      const detail = row.nextElementSibling;
      if (!detail || !detail.classList.contains('visitor-detail')) return;
      const open = detail.style.display !== 'none';
      detail.style.display = open ? 'none' : '';
      const chev = row.querySelector('.visitor-chevron');
      if (chev) chev.textContent = open ? '▸' : '▾';
      if (!open) {
        const box = detail.querySelector('.visitor-messages');
        if (box && box.dataset.loaded === '0') loadUserMessages(box, box.dataset.id);
      }
    });
  });
}

async function loadUserMessages(box, discordId) {
  box.dataset.loaded = '1';
  box.innerHTML = '<span style="color:var(--text-secondary);font-size:12px;">Chargement…</span>';
  const r = await apiFetch('/api/admin/chat-connections/' + encodeURIComponent(discordId) + '/messages?limit=100');
  if (!r || !r.ok) {
    box.innerHTML = '<span style="color:var(--text-secondary);font-size:12px;">Erreur de chargement</span>';
    box.dataset.loaded = '0';
    return;
  }
  const msgs = (await r.json()).messages || [];
  if (!msgs.length) {
    box.innerHTML = '<span style="color:var(--text-secondary);font-size:12px;">Aucun message</span>';
    return;
  }
  let html = '';
  for (const m of msgs) {
    const t = new Date(m.created_at * 1000);
    const ts = t.toLocaleDateString('fr-FR', { day: '2-digit', month: '2-digit' })
      + ' ' + t.toLocaleTimeString('fr-FR', { hour: '2-digit', minute: '2-digit' });
    html += `
      <div style="padding:6px 0;border-top:1px solid rgba(255,255,255,.06);">
        <div style="font-size:11px;color:var(--text-secondary);">${escHtml(ts)}</div>
        <div style="white-space:pre-wrap;word-break:break-word;">${escHtml(m.content)}</div>
      </div>`;
  }
  box.innerHTML = html;
}

async function banUser(discordId, username) {
  if (!confirm(`Bannir ${username || discordId} ? Wally l'ignorera partout (chat web, Discord, Twitch si lié).`)) return;
  const r = await apiFetch('/api/admin/chat-bans', {
    method: 'POST',
    body: JSON.stringify({ discord_id: discordId, username }),
  });
  if (r && r.ok) { toast('Utilisateur banni', 'success'); loadVisitorsInPanel(); }
  else if (r) toast('Échec du bannissement', 'error');
}

async function unbanUser(discordId) {
  const r = await apiFetch('/api/admin/chat-bans/' + encodeURIComponent(discordId), { method: 'DELETE' });
  if (r && r.ok) { toast('Bannissement levé', 'success'); loadVisitorsInPanel(); }
  else if (r) toast('Échec', 'error');
}

// ── Init ──────────────────────────────────────────────────────────────────────

document.addEventListener('DOMContentLoaded', async () => {
  if (!getToken()) {
    showAuthModal();
    return;
  }
  // `enterAdmin()` finit par `routerVersHash()`, qui lit le hash courant :
  // rien à lui passer. Le double montage d'autrefois — on posait le hash puis
  // on le relisait — n'a plus de chemin possible, la route ne s'applique que
  // si elle DIFFÈRE de la route courante.
  enterAdmin();
});

// ── Memory tab ────────────────────────────────────────────────────────────────

// Valeur posée dans un attribut HTML : `data-id="…"`, `title="…"`, `value="…"`.
// `&` en PREMIER, sinon on ré-échapperait les entités qu'on vient d'écrire.
function escAttr(str) {
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}

// Valeur posée dans une chaîne JS **à l'intérieur** d'un attribut HTML :
// `onclick="foo('…')"`. Deux couches, dans cet ordre — c'est tout le sujet.
//
// Le parseur HTML décode les entités de la valeur d'attribut AVANT que le
// contenu ne soit compilé comme du JavaScript. `escAttr` seul écrivait `&#39;`
// pour une apostrophe : redevenue `'` au décodage, elle fermait la chaîne JS.
// Un pseudo Discord valant `x');alert(1)//` exécutait donc du code dès
// l'ouverture de l'onglet Mémoire — et le jeton admin vit en `localStorage`.
//
// On échappe donc d'abord POUR JavaScript (le `\` devant survivra au décodage),
// puis pour l'attribut HTML.
function escJs(str) {
  return escAttr(
    String(str)
      .replace(/\\/g, '\\\\')
      .replace(/'/g, "\\'")
      .replace(/"/g, '\\"')
      .replace(/\r?\n/g, '\\n')
  );
}

// ── Cockpit ─────────────────────────────────────────────────────────────────
//
// L'écran d'arrivée. Il répond à trois questions et à rien d'autre : est-ce que
// ça tourne, qu'est-ce qui a cassé, qu'est-ce que je dois décider. Aucun
// réglage ici — tout renvoie ailleurs, avec le filtre déjà posé.

const _COCKPIT_COULEURS = {
  echec: 'var(--danger)',
  erreur: 'var(--warning)',
  fusion: 'var(--accent)',
  question: 'var(--cognitive)',
};

const _COCKPIT_LIBELLES = {
  echec: 'tâche en échec',
  erreur: 'erreur répétée',
  fusion: 'identités à rattacher',
  question: 'question en attente',
};

// Les trois derniers endroits visités. Purement local — c'est une commodité de
// navigation, elle n'a rien à faire côté serveur.
const _COCKPIT_CLE_RECENTES = 'wally_pages_recentes';

function renderCockpit() {
  const el = document.getElementById('tab-admin-cockpit');
  if (!el) return;
  if (!document.getElementById('cockpit-tuiles')) {
    el.innerHTML = '<div class="cockpit-tuiles" id="cockpit-tuiles"></div>'
      + '<div class="cockpit-colonnes">'
      + '<div class="page-section" id="cockpit-decisions"></div>'
      + '<div class="page-section" id="cockpit-humeur"></div>'
      + '</div>'
      + '<div class="page-section" id="cockpit-reprendre"></div>';
    el.addEventListener('click', function (ev) {
      const a = ev.target.closest('[data-cible]');
      if (a) location.hash = a.dataset.cible;
    });
  }
  viderSommaire();
  _majSalutation();
  chargerCockpit();
  _rendreReprendre();
}

/** « Bonsoir » à 19 h, « Bonjour » à 9 h. Le titre du cockpit s'adresse à
 *  quelqu'un : le figer à une heure de la journée le rendrait faux les trois
 *  quarts du temps. */
function _majSalutation() {
  const h = new Date().getHours();
  const mot = h < 6 ? 'Bonne nuit' : h < 18 ? 'Bonjour' : 'Bonsoir';
  const titre = document.getElementById('page-title');
  if (titre) titre.textContent = mot + '. Voilà où en est Wally.';
}

async function chargerCockpit() {
  const tuiles = document.getElementById('cockpit-tuiles');
  const decisions = document.getElementById('cockpit-decisions');
  if (!tuiles || !decisions) return;

  const [rd, rc] = await Promise.all([
    apiFetch('/api/admin/decisions'),
    apiFetch('/api/admin/connexions'),
  ]);
  if (!rd || !rd.ok) {
    decisions.innerHTML = '<div class="page-section-titre">Ce qui demande une décision</div>'
      + '<div class="page-section-sous">État illisible pour le moment.</div>';
    return;
  }
  const d = await rd.json();
  const cnx = (rc && rc.ok) ? await rc.json() : {};

  const sous = document.getElementById('page-sub');
  if (sous) {
    sous.textContent = 'En ligne depuis ' + _cockpitDuree(d.uptime_seconds) + '.';
    sous.hidden = false;
  }

  tuiles.innerHTML =
      _cockpitTuile('Discord', (cnx.discord || {}).pret, 'connecté', 'coupé',
                    (cnx.discord || {}).nom || 'non configuré')
    + _cockpitTuile('Twitch', (cnx.twitch || {}).pret, 'connecté', 'coupé',
                    (cnx.twitch || {}).nom || 'non configuré')
    + _cockpitTuile('Overlay', d.overlay_visible, 'visible', 'masqué',
                    'ce que voient les viewers')
    + _cockpitTuileErreurs(d.erreurs_du_jour);
  majBadgeSysteme(d.erreurs_du_jour);

  _rendreDecisions(decisions, d);
  await chargerEmotions();
  _rendreHumeurCockpit();
}

function _cockpitTuile(nom, ok, siOui, siNon, sous) {
  return '<div class="cockpit-tuile">'
    + '<div class="cockpit-tuile-label">' + escHtml(nom) + '</div>'
    + '<div class="cockpit-tuile-valeur ' + (ok ? 'vert' : 'ambre') + '">'
    + (ok ? siOui : siNon) + '</div>'
    + '<div class="cockpit-tuile-sous">' + escHtml(sous) + '</div></div>';
}

function _cockpitTuileErreurs(n) {
  const nb = Number(n) || 0;
  return '<div class="cockpit-tuile' + (nb ? ' alerte' : '') + '">'
    + '<div class="cockpit-tuile-label">Erreurs du jour</div>'
    + '<div class="cockpit-tuile-valeur ' + (nb ? 'rouge' : 'vert') + '">' + nb + '</div>'
    + '<div class="cockpit-tuile-sous">'
    + (nb ? 'dans le journal d\'aujourd\'hui' : 'rien à signaler') + '</div></div>';
}

function _rendreDecisions(boite, d) {
  const items = d.items || [];
  const reste = (d.total || 0) - items.length;
  boite.innerHTML = '<div class="page-section-titre">Ce qui demande une décision</div>'
    + '<div class="page-section-sous">'
    + (items.length
        ? (d.total === items.length ? d.total + ' chose(s) attendent quelqu\'un.'
                                    : items.length + ' sur ' + d.total + ' — les plus urgentes.')
        : 'Rien n\'attend personne.')
    + '</div>'
    + items.map(function (i) {
        return '<div class="cockpit-item" data-cible="' + escAttr(i.cible) + '" '
          + 'role="button" tabindex="0">'
          + '<span class="cockpit-barre" style="background:'
          + (_COCKPIT_COULEURS[i.type] || 'var(--border-accent)') + '"></span>'
          + '<div class="cockpit-item-txt"><div class="cockpit-item-titre">'
          + escHtml(i.titre) + '</div>'
          + '<div class="cockpit-item-detail">'
          + escHtml(_COCKPIT_LIBELLES[i.type] || i.type) + ' · '
          + escHtml(i.detail) + '</div></div>'
          + '<span class="cockpit-ouvrir">Ouvrir</span></div>';
      }).join('')
    + (reste > 0 ? '<div class="page-section-sous">+ ' + reste + ' autre(s).</div>' : '');
}

/** L'état émotionnel RÉEL, lu au serveur.
 *
 *  `currentEmotions` n'était alimenté par AUCUN appel : les deux seuls sites
 *  qui appelaient `updateEmotionGauges` lui repassaient la variable vide.
 *  Résultat, les jauges du panel affichaient 0.00 pour tout depuis toujours,
 *  pendant que Wally tournait à joy 0.78 — la mesure existait, l'écran mentait.
 */
async function chargerEmotions() {
  const r = await apiFetch('/api/admin/emotions');
  if (!r || !r.ok) return false;
  updateEmotionGauges(await r.json());
  return true;
}

function _rendreHumeurCockpit() {
  const boite = document.getElementById('cockpit-humeur');
  if (!boite) return;
  boite.innerHTML = '<div class="page-section-titre">Humeur actuelle</div>'
    + '<div class="page-section-sous">Réglable dans '
    + '<a href="#/cerveau/personnalite">Personnalité</a>.</div>'
    + EMOTIONS.map(function (e) {
        const v = Number((currentEmotions || {})[e]) || 0;
        return '<div class="cockpit-emotion">'
          + '<span class="cockpit-emotion-nom" style="color:' + EMOTION_COLORS[e] + '">'
          + escHtml(e) + '</span>'
          + '<span class="cockpit-emotion-piste"><span style="width:'
          + Math.round(Math.max(0, Math.min(1, v)) * 100) + '%;background:'
          + EMOTION_COLORS[e] + '"></span></span>'
          + '<span class="cockpit-emotion-val">' + v.toFixed(2) + '</span></div>';
      }).join('');
}

/** Retient la page qu'on vient de quitter. Appelée par le routeur. */
function noterPageRecente(route, titre) {
  if (!route || route === 'cockpit') return;
  let liste = [];
  try {
    liste = JSON.parse(localStorage.getItem(_COCKPIT_CLE_RECENTES) || '[]');
  // Une valeur illisible (autre onglet, autre version) ne doit pas casser la
  // navigation pour une commodité d'affichage.
  } catch (e) { liste = []; }
  liste = liste.filter(function (x) { return x && x.route !== route; });
  liste.unshift({ route: route, titre: titre });
  try {
    localStorage.setItem(_COCKPIT_CLE_RECENTES, JSON.stringify(liste.slice(0, 3)));
  } catch (e) { /* quota ou mode privé : le cockpit s'en passe */ }
}

function _rendreReprendre() {
  const boite = document.getElementById('cockpit-reprendre');
  if (!boite) return;
  let liste = [];
  try {
    liste = JSON.parse(localStorage.getItem(_COCKPIT_CLE_RECENTES) || '[]');
  } catch (e) { liste = []; }
  if (!liste.length) { boite.innerHTML = ''; return; }
  boite.innerHTML = '<div class="page-section-titre">Reprendre</div>'
    + '<div class="journal-puces">' + liste.map(function (x) {
        return '<button class="puce" data-cible="#/' + escAttr(x.route) + '">'
          + escHtml(x.titre || x.route) + '</button>';
      }).join('') + '</div>';
}

function _cockpitDuree(secondes) {
  const s = Math.max(0, Number(secondes) || 0);
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  if (h >= 24) return Math.floor(h / 24) + ' j ' + (h % 24) + ' h';
  return h ? h + ' h ' + String(m).padStart(2, '0') : m + ' min';
}

// ── Cerveau › Mémoire commune ───────────────────────────────────────────────
//
// Ce que Wally sait du GROUPE, plutôt que d'une personne.
//
// L'ancien onglet « Mémoire communautaire » lisait `/memory/global`, qui rend
// une liste VIDE et refuse toute écriture en 501 depuis la refonte V2 : un
// panneau mort, qui invitait à ajouter un souvenir aussitôt rejeté.
//
// La matière existe, elle n'était exposée nulle part : les SUJETS formés par
// la passe nocturne, chacun avec l'opinion que Wally s'en fait.

const _MC_SECTIONS = [
  ['mc-sujets', 'Sujets de la communauté'],
  ['mc-questions', 'Questions de Wally'],
  ['mc-notes', 'Notes du bot'],
  ['mc-tete', 'Dans sa tête'],
];

let _mcVues = [];   // les sections montrées ; vide = toutes

function renderMemoireCommune() {
  const el = document.getElementById('tab-admin-memoire');
  if (!el) return;

  if (!document.getElementById('mc-sujets')) {
    el.innerHTML = '<div class="journal-puces" id="mc-puces"></div>'
      + _MC_SECTIONS.map(function (s) {
          return '<div class="page-section" id="' + s[0] + '"></div>';
        }).join('');
    el.querySelector('#mc-puces').addEventListener('click', function (ev) {
      const b = ev.target.closest('[data-mc]');
      if (!b) return;
      const cle = b.dataset.mc;
      if (!cle) _mcVues = [];
      else {
        const i = _mcVues.indexOf(cle);
        if (i === -1) _mcVues.push(cle);
        else _mcVues.splice(i, 1);
      }
      _majVuesMC();
    });
  }

  _majVuesMC();
  poserSommaire('cerveau/memoire', _MC_SECTIONS, '');
  chargerMemoireCommune();
  loadNotesTab(document.getElementById('mc-notes'));
  renderWallySelfTab(document.getElementById('mc-tete'));
}

/** Les puces montrent ou cachent des SECTIONS. Les entrées sont de natures
 *  différentes — un sujet, une question, une note — et un filtre qui les
 *  mélangerait dans une seule liste perdrait ce qui les distingue. */
function _majVuesMC() {
  const puces = document.getElementById('mc-puces');
  if (puces) {
    puces.innerHTML = '<button class="puce' + (_mcVues.length ? '' : ' active')
      + '" data-mc="">Tout</button>'
      + _MC_SECTIONS.map(function (s) {
          const actif = _mcVues.indexOf(s[0]) !== -1;
          return '<button class="puce' + (actif ? ' active' : '') + '" data-mc="'
            + s[0] + '">' + escHtml(s[1]) + '</button>';
        }).join('');
  }
  _MC_SECTIONS.forEach(function (s) {
    const boite = document.getElementById(s[0]);
    if (boite) boite.hidden = _mcVues.length > 0 && _mcVues.indexOf(s[0]) === -1;
  });
}

async function chargerMemoireCommune() {
  const sujets = document.getElementById('mc-sujets');
  const questions = document.getElementById('mc-questions');
  if (!sujets || !questions) return;

  const r = await apiFetch('/api/admin/memoire-commune');
  if (!r || !r.ok) {
    sujets.innerHTML = '<div class="page-section-titre">Sujets de la communauté</div>'
      + '<div class="page-section-sous">Mémoire illisible pour le moment.</div>';
    return;
  }
  const d = await r.json();
  _rendreSujets(sujets, d.sujets || []);
  _rendreQuestions(questions, d.questions || []);
}

function _rendreSujets(boite, liste) {
  boite.innerHTML = '<div class="page-section-titre">Sujets de la communauté</div>'
    + '<div class="page-section-sous">'
    + (liste.length
        ? liste.length + ' sujet(s) formé(s) par la passe nocturne. L\'opinion est '
          + 'celle de Wally, pas un résumé.'
        : 'Aucun sujet formé. La passe de 21 h les construit à partir des '
          + 'conversations du jour.')
    + '</div>'
    + liste.map(function (t) {
        const gens = (t.participants || [])
          .map(function (p) { return p && p.name; }).filter(Boolean);
        // Les participants se répètent (même personne, plusieurs identités) :
        // les dédoublonner évite « KingsRequin · KingsRequin · KingsRequin ».
        const uniques = gens.filter(function (n, i) { return gens.indexOf(n) === i; });
        return '<div class="mc-sujet">'
          + '<div class="mc-sujet-tete"><strong>' + escHtml(t.name) + '</strong>'
          + '<span class="mc-sujet-meta">' + Number(t.mention_count) + ' mention(s) · '
          + escHtml(apexDepuis(t.last_seen_at)) + '</span></div>'
          + (t.summary ? '<p class="mc-sujet-resume">' + escHtml(t.summary) + '</p>' : '')
          + (t.opinion ? '<p class="mc-sujet-avis">« ' + escHtml(t.opinion) + ' »</p>' : '')
          + (uniques.length
            ? '<div class="fiche-puces">' + uniques.slice(0, 8).map(function (n) {
                return '<span class="fiche-puce">' + escHtml(n) + '</span>';
              }).join('') + '</div>'
            : '')
          + '</div>';
      }).join('');
}

function _rendreQuestions(boite, liste) {
  boite.innerHTML = '<div class="page-section-titre">Questions de Wally</div>'
    + '<div class="page-section-sous">'
    + (liste.length
        ? 'Ce qu\'il aimerait demander. Elles sont posées d\'elles-mêmes, au fil '
          + 'des conversations — trois tentatives, puis abandon au bout de 24 h.'
        : 'Aucune question en attente.')
    + '</div>'
    + liste.map(function (q) {
        return '<div class="mc-question" id="mem-q-' + Number(q.id) + '">'
          + '<div class="mc-question-txt"><span id="mem-q-text-' + Number(q.id)
          + '">' + escHtml(q.question || '') + '</span>'
          + '<div class="fiche-memoire-meta">'
          + escHtml(q.username || q.user_id || 'personne précise')
          + ' · priorité ' + escHtml(q.priority || 'basse')
          + ' · ' + Number(q.attempts || 0) + ' tentative(s)</div></div>'
          + '<div class="fiche-memoire-actions">'
          + '<button class="lien-doux" data-mcq="editer" data-arg="' + Number(q.id)
          + '">Modifier</button>'
          + '<button class="lien-doux" data-mcq="resoudre" data-arg="' + Number(q.id)
          + '">Répondue</button>'
          + '<button class="lien-danger" data-mcq="supprimer" data-arg="' + Number(q.id)
          + '">Oublier</button>'
          + '</div></div>';
      }).join('');

  if (!boite.dataset.cable) {
    boite.dataset.cable = '1';
    boite.addEventListener('click', function (ev) {
      const b = ev.target.closest('[data-mcq]');
      if (!b) return;
      const id = Number(b.dataset.arg);
      if (b.dataset.mcq === 'editer') editMemQuestion(id);
      else if (b.dataset.mcq === 'resoudre') resolveMemQuestion(id);
      else if (b.dataset.mcq === 'supprimer') deleteMemQuestion(id);
    });
  }
}

// ── Live › Médias & sons ────────────────────────────────────────────────────
//
// Ce que Wally MONTRE et ce qu'il FAIT ENTENDRE, au même endroit : les deux
// overlays et leurs URL OBS, la génération d'images, la galerie, et les sons
// que le chat déclenche. C'était réparti entre Paramètres › Images et
// Système › Overlay, deux sections qui ne se voyaient pas.

const _MEDIAS_SECTIONS = [
  ['medias-overlays', 'Overlays'],
  ['medias-images', 'Génération d\'images'],
  ['medias-galerie', 'Galerie'],
];

function renderMedias() {
  const el = document.getElementById('tab-admin-medias');
  if (!el) return;

  if (!document.getElementById('medias-overlays')) {
    el.innerHTML = '<div class="page-section" id="medias-overlays"></div>'
      + '<div class="page-section" id="medias-images">'
      + '<div class="page-section-titre">Génération d\'images</div>'
      + '<div id="medias-images-corps"></div></div>'
      + '<div class="page-section" id="medias-galerie"></div>';
  }

  _renderPanelOnce(document.getElementById('medias-overlays'), _renderSystemeOverlay);
  _renderPanelOnce(document.getElementById('medias-images-corps'), _renderParametresImages);
  poserSommaire('live/medias', _MEDIAS_SECTIONS, '');
  chargerGalerie();
}

/** La galerie en vignettes. La dernière case porte le reste, pour ne pas
 *  charger trois cents images dans un panneau de réglages. */
const _GALERIE_MAX = 23;

async function chargerGalerie() {
  const boite = document.getElementById('medias-galerie');
  if (!boite) return;
  const r = await apiFetch('/api/public/gallery?limit=200');
  if (!r || !r.ok) {
    boite.innerHTML = '<div class="page-section-titre">Galerie</div>'
      + '<div class="page-section-sous">Galerie illisible pour le moment.</div>';
    return;
  }
  const d = await r.json();
  const images = d.images || d || [];
  const montrees = images.slice(0, _GALERIE_MAX);
  const reste = images.length - montrees.length;

  boite.innerHTML = '<div class="page-section-titre">Galerie</div>'
    + '<div class="page-section-sous">'
    + (images.length ? images.length + ' image(s) générée(s).'
                     : 'Aucune image générée pour l\'instant.') + '</div>'
    + (images.length
      ? '<div class="galerie">' + montrees.map(function (i) {
          return '<a class="galerie-case" href="/api/public/gallery/'
            + encodeURIComponent(i.id) + '/image" target="_blank" rel="noopener">'
            + '<img src="/api/public/gallery/' + encodeURIComponent(i.id)
            + '/image" alt="' + escAttr(i.title || '') + '" loading="lazy"></a>';
        }).join('')
        + (reste > 0 ? '<span class="galerie-case galerie-reste">+' + reste + '</span>' : '')
        + '</div>'
      : '');
}

// ── Live › Voix ─────────────────────────────────────────────────────────────
//
// Les deux « Vocal » fusionnés : les réglages vivaient dans Paramètres, le
// suivi en direct dans un onglet à part. On réglait donc la voix sans voir ce
// qu'elle entendait, et on regardait ce qu'elle entendait sans pouvoir y
// toucher.

const _VOIX_SECTIONS = [
  ['voix-reglages', 'Réglages'],
  ['voix-suivi', 'Suivi en direct'],
];

function renderVoix() {
  const el = document.getElementById('tab-admin-voix');
  if (!el) return;

  if (!document.getElementById('voix-reglages')) {
    el.innerHTML = '<div class="page-section" id="voix-reglages">'
      + '<div class="page-section-titre">Réglages</div>'
      + '<div id="voix-reglages-corps"></div></div>'
      + '<div class="page-section" id="voix-suivi">'
      + '<div class="page-section-titre">Suivi en direct</div>'
      + '<div class="page-section-sous">Ce que Wally entend, et ce qu\'il répond. '
      + 'Le flux ne garde rien : il montre la session en cours.</div>'
      + '<div id="voix-suivi-corps"></div></div>';
  }

  _renderPanelOnce(document.getElementById('voix-reglages-corps'), _renderParametresVoice);
  renderVoiceTab(document.getElementById('voix-suivi-corps'));
  poserSommaire('live/voix', _VOIX_SECTIONS, '');
}

// ── Système › Connexions ────────────────────────────────────────────────────
//
// « Connecté » ne suffit pas : un bot Discord prêt sur zéro serveur et un
// EventSub vivant sans souscription ont le même voyant vert. Chaque adaptateur
// rend donc ses faits.

const _CNX_SECTIONS = [
  ['cnx-adaptateurs', 'Adaptateurs'],
  ['cnx-twitch', 'Comptes et chaînes Twitch'],
  ['cnx-discord', 'Réglages Discord'],
];

function renderConnexions() {
  const el = document.getElementById('tab-admin-connexions');
  if (!el) return;

  if (!document.getElementById('cnx-adaptateurs')) {
    el.innerHTML = '<div class="page-section" id="cnx-adaptateurs"></div>'
      + '<div class="page-section" id="cnx-twitch">'
      + '<div class="page-section-titre">Comptes et chaînes Twitch</div>'
      + '<div id="cnx-twitch-corps"></div></div>'
      + '<div class="page-section" id="cnx-discord">'
      + '<div class="page-section-titre">Réglages Discord</div>'
      + '<div id="cnx-discord-corps"></div></div>';
  }

  chargerConnexions();
  _renderSystemeTwitch(document.getElementById('cnx-twitch-corps'));
  _renderPanelOnce(document.getElementById('cnx-discord-corps'), _renderReglagesDiscord);
  poserSommaire('systeme/connexions', _CNX_SECTIONS, '');
}

async function chargerConnexions() {
  const boite = document.getElementById('cnx-adaptateurs');
  if (!boite) return;
  // Délégation posée UNE fois : `chargerConnexions` réécrit les cartes après
  // chaque bascule, et un écouteur par rendu finirait par arrêter le bot trois
  // fois pour un clic.
  if (!boite.dataset.cable) {
    boite.dataset.cable = '1';
    boite.addEventListener('click', async function (ev) {
      const b = ev.target.closest('[data-cnx]');
      if (!b) return;
      b.disabled = true;
      await toggleBotAdapter(b.dataset.cnx);
      await chargerConnexions();
    });
  }
  const r = await apiFetch('/api/admin/connexions');
  if (!r || !r.ok) {
    boite.innerHTML = '<div class="page-section-titre">Adaptateurs</div>'
      + '<div class="page-section-sous">État illisible pour le moment.</div>';
    return;
  }
  const d = await r.json();
  boite.innerHTML = '<div class="page-section-titre">Adaptateurs</div>'
    + '<div class="cnx-cartes">'
    + _cnxCarte('Discord', d.discord, 'discord')
    + _cnxCarte('Twitch', d.twitch, 'twitch')
    + '</div>';
}

function _cnxCarte(nom, a, cle) {
  if (!a || !a.configure) {
    return '<div class="cnx-carte"><div class="cnx-carte-tete">'
      + '<span class="cnx-point"></span><strong>' + escHtml(nom) + '</strong>'
      + '</div><div class="page-section-sous">Non configuré.</div></div>';
  }
  const pret = !!a.pret;
  return '<div class="cnx-carte"><div class="cnx-carte-tete">'
    + '<span class="cnx-point' + (pret ? ' on' : '') + '"></span>'
    + '<strong>' + escHtml(nom) + '</strong>'
    + '<span class="cnx-nom">' + escHtml(a.nom || '—') + '</span>'
    + '<button class="btn" data-cnx="' + cle + '">'
    + (pret ? 'Stop' : 'Start') + '</button></div>'
    + '<div class="cnx-faits">' + (a.faits || []).map(function (f) {
        return '<div class="cnx-fait"><span>' + escHtml(f[0]) + '</span>'
          + '<b>' + escHtml(f[1]) + '</b></div>';
      }).join('') + '</div></div>';
}

// ── Cerveau › Personnalité ──────────────────────────────────────────────────
//
// Fusionne Paramètres › Émotions et l'onglet Prompts. Les deux disaient la même
// chose : comment Wally se comporte. L'un par des nombres, l'autre par des
// textes — et ils vivaient à deux endroits sans rapport apparent.

const _PERSO_SECTIONS = [
  ['perso-etat', 'Humeur et tempérament'],
  ['perso-textes', 'Textes de référence'],
];

function renderPersonnalite() {
  const el = document.getElementById('tab-admin-personnalite');
  if (!el) return;

  if (!document.getElementById('perso-etat')) {
    el.innerHTML = '<div class="page-section" id="perso-etat"></div>'
      + '<div class="page-section" id="perso-textes">'
      + '<div class="page-section-titre">Textes de référence</div>'
      + '<div class="page-section-sous">Les fichiers qui définissent sa voix et '
      + 'sa cognition. Ceux de <code>bot/persona/</code> se rechargent à chaud ; '
      + 'ceux de la cognition sont lus au démarrage et demandent un restart.</div>'
      + '<div id="perso-prompts"></div></div>';
  }

  _renderPanelOnce(document.getElementById('perso-etat'), _renderParametresEmotions);
  renderPromptsTab(document.getElementById('perso-prompts'));
  poserSommaire('cerveau/personnalite', _PERSO_SECTIONS, '');
}

// ── Cerveau › Modèles & coûts ───────────────────────────────────────────────
//
// Séparé de la personnalité parce que c'est une décision TECHNIQUE : quel
// modèle sert à quoi, et ce que ça coûte.
//
// `log_cost()` écrit dans `cost_log` depuis toujours. L'onglet qui le lisait a
// été retiré — remplacé par Langfuse, puis abandonné. La mesure existait donc
// sans que rien ne la montre, ce qui est la définition d'une panne silencieuse.

const _MOD_SECTIONS = [
  ['mod-modeles', 'Modèles'],
  ['mod-usage', 'Coûts par usage'],
  ['mod-jours', '14 derniers jours'],
];

function renderModeles() {
  const el = document.getElementById('tab-admin-modeles');
  if (!el) return;

  if (!document.getElementById('mod-modeles')) {
    el.innerHTML = '<div class="page-section" id="mod-modeles"></div>'
      + '<div class="page-section" id="mod-usage"></div>'
      + '<div class="page-section" id="mod-jours"></div>';
  }

  _renderPanelOnce(document.getElementById('mod-modeles'), _renderParametresLLM);
  poserSommaire('cerveau/modeles', _MOD_SECTIONS, '');
  chargerCouts();
}

async function chargerCouts() {
  const usage = document.getElementById('mod-usage');
  const jours = document.getElementById('mod-jours');
  if (!usage || !jours) return;

  const r = await apiFetch('/api/admin/couts');
  if (!r || !r.ok) {
    // Ne pas afficher « 0 $ » : un zéro faux se lit comme une bonne nouvelle.
    usage.innerHTML = '<div class="page-section-titre">Coûts par usage</div>'
      + '<div class="page-section-sous">Coûts illisibles pour le moment.</div>';
    jours.innerHTML = '';
    return;
  }
  const d = await r.json();
  const usages = d.usages || [];
  const latence = d.latence_moyenne_ms;

  usage.innerHTML = '<div class="page-section-titre">Coûts par usage</div>'
    + '<div class="page-section-sous">'
    + _dollars(d.total) + ' sur les ' + Number(d.fenetre_heures) + ' dernières heures'
    // « moyenne » et pas « médiane » : c'est ce que `AppState` tient, sur les
    // cinquante dernières réponses. L'annoncer autrement serait faux.
    + (latence ? ' · latence moyenne ' + Math.round(latence) + ' ms' : '')
    + '.</div>'
    + '<div class="liste-tete mod-tete"><span>Usage</span><span>Modèle</span>'
    + '<span>Appels</span><span>Coût</span></div>'
    + (usages.length
      ? '<div class="liste">' + usages.map(function (u) {
          return '<div class="liste-ligne mod-ligne">'
            + '<span class="mod-usage">' + escHtml(u.usage) + '</span>'
            + '<span class="mod-modele">' + escHtml((u.modeles || []).join(', ') || '—')
            + '</span>'
            + '<span class="mod-nb">' + Number(u.appels) + '</span>'
            + '<span class="mod-cout">' + _dollars(u.cout) + '</span>'
            + '</div>';
        }).join('') + '</div>'
      : '<div class="liste-vide">Aucun appel sur la fenêtre.</div>');

  _rendreCourbeCouts(jours, d.jours || []);
}

/** Le coût, au cent près quand il compte, au dixième de cent quand il est
 *  petit — « 0.00 $ » partout ne dirait rien de la répartition. */
function _dollars(v) {
  const n = Number(v) || 0;
  if (n === 0) return '0 $';
  if (n < 0.01) return n.toFixed(4) + ' $';
  return n.toFixed(2) + ' $';
}

/** Une barre par jour. Le seuil est la MOYENNE de la période : une barre au
 *  dessus se colore, et on voit d'un coup les jours qui ont coûté cher sans
 *  avoir à lire quatorze nombres. */
function _rendreCourbeCouts(boite, jours) {
  if (!jours.length) {
    boite.innerHTML = '<div class="page-section-titre">14 derniers jours</div>'
      + '<div class="page-section-sous">Rien d\'enregistré sur la période.</div>';
    return;
  }
  const couts = jours.map(function (j) { return Number(j.cost) || 0; });
  const haut = Math.max.apply(null, couts) || 1;
  const moyenne = couts.reduce(function (a, b) { return a + b; }, 0) / couts.length;

  boite.innerHTML = '<div class="page-section-titre">14 derniers jours</div>'
    + '<div class="page-section-sous">'
    + _dollars(couts.reduce(function (a, b) { return a + b; }, 0))
    + ' au total · ' + _dollars(moyenne) + ' par jour en moyenne.</div>'
    + '<div class="mod-courbe">' + jours.map(function (j) {
        const c = Number(j.cost) || 0;
        return '<div class="mod-barre" title="' + escAttr(j.date + ' — ' + _dollars(c)) + '">'
          + '<span style="height:' + Math.max(2, Math.round(c / haut * 100)) + '%"'
          + (c > moyenne ? ' class="haut"' : '') + '></span>'
          + '<em>' + escHtml(String(j.date).slice(5)) + '</em></div>';
      }).join('') + '</div>';
}

// ── Cerveau › Personnes ─────────────────────────────────────────────────────
//
// Refonte du 2026-08-28. « Que sait Wally de KingsRequin ? » demandait quatre
// onglets : ses mémoires dans Utilisateurs, son compte Apex dans Comptes Apex,
// son statut d'écoute dans Ignorés, ses surnoms dans les alias. Toujours la
// même question, jamais rassemblée.
//
// L'annuaire devient une liste unique ; « ignoré » et « Apex lié » y sont des
// FILTRES, plus des pages. Chaque ligne ouvre une fiche, qui tient dans une
// seule requête (`/api/admin/person/{identite}`).

const _PERS_SECTIONS = [
  ['pers-annuaire', 'Annuaire'],
  ['pers-fusions', 'Fusions à valider'],
  ['pers-apex', 'Lier un compte Apex'],
  ['pers-ignores', 'Personnes ignorées'],
];

// Les filtres se DÉCRIVENT, ils ne s'écrivent pas trois fois. Ajouter une
// entrée ici suffit : la puce, l'état d'URL et le tri en découlent.
const _PERS_FILTRES = [
  ['memoire', 'Avec mémoire', function (p) { return (p.memory_count || 0) > 0; }],
  ['apex', 'Compte Apex lié', function (p) { return !!p._apex; }],
  ['ignore', 'Ignorés', function (p) { return !!p._ignore; }],
  ['trust', 'Trust élevé', function (p) { return (p.trust_score || 0) >= 0.5; }],
  ['semaine', 'Vus cette semaine', function (p) {
    return (p.last_updated || 0) * 1000 > Date.now() - 7 * 86400000;
  }],
];

const _PERS_TRIS = [
  ['memories', 'Mémoires'], ['trust', 'Trust'], ['love', 'Love'], ['name', 'Nom'],
];

let _persFiltres = { q: '', plateforme: '', tri: 'memories', actifs: [] };
let _persGens = [];

function _persLireHash() {
  const brut = location.hash.replace(/^#\/?/, '');
  const coupe = brut.indexOf('?');
  if (coupe === -1) { _persEcrireHash(); return; }
  const p = new URLSearchParams(brut.slice(coupe + 1));
  const plateforme = p.get('plateforme') || '';
  const tri = p.get('tri') || 'memories';
  _persFiltres = {
    q: p.get('q') || '',
    plateforme: (plateforme === 'discord' || plateforme === 'twitch') ? plateforme : '',
    tri: _PERS_TRIS.some(function (t) { return t[0] === tri; }) ? tri : 'memories',
    actifs: (p.get('f') || '').split(',').filter(function (n) {
      return _PERS_FILTRES.some(function (f) { return f[0] === n; });
    }),
  };
}

function _persEcrireHash() {
  if (currentRoute !== 'cerveau/personnes') return;
  const p = new URLSearchParams();
  const f = _persFiltres;
  if (f.q) p.set('q', f.q);
  if (f.plateforme) p.set('plateforme', f.plateforme);
  if (f.tri !== 'memories') p.set('tri', f.tri);
  if (f.actifs.length) p.set('f', f.actifs.join(','));
  const requete = p.toString();
  const vise = '#/cerveau/personnes' + (requete ? '?' + requete : '');
  if (location.hash !== vise) history.replaceState(null, '', vise);
}

function renderPersonnes() {
  const el = document.getElementById('tab-admin-personnes');
  if (!el) return;

  if (!document.getElementById('pers-liste')) {
    el.innerHTML = `
      <div class="auto-barre">
        <input type="search" class="champ-recherche" id="pers-q"
               placeholder="Chercher quelqu'un…" aria-label="Chercher quelqu'un">
        <div class="segmented" id="pers-plateformes" role="group" aria-label="Plateforme">
          <button data-plateforme="">Tous</button>
          <button data-plateforme="discord">Discord</button>
          <button data-plateforme="twitch">Twitch</button>
        </div>
        <div class="segmented" id="pers-tris" role="group" aria-label="Tri"></div>
      </div>
      <div class="journal-puces" id="pers-puces"></div>
      <div class="mem-link-banner" id="pers-fusion-bandeau" hidden></div>
      <div id="pers-annuaire">
        <div class="liste-tete pers-tete">
          <span>Personne</span><span>Trust</span><span>Love</span><span>Apex</span>
        </div>
        <div class="liste" id="pers-liste"></div>
      </div>
      <div class="page-section" id="pers-fusions"></div>
      <div class="page-section" id="pers-apex"></div>
      <div class="page-section" id="pers-ignores"></div>`;

    el.querySelector('#pers-tris').innerHTML = _PERS_TRIS.map(function (t) {
      return '<button data-tri="' + t[0] + '">' + t[1] + '</button>';
    }).join('');
    _cablerPersonnes(el);
  }

  _persLireHash();
  poserSommaire('cerveau/personnes', _PERS_SECTIONS, '');
  chargerPersonnes();
  // « Comptes Apex » et « Ignorés » étaient deux onglets. Ce sont deux
  // FILTRES de l'annuaire — et leurs formulaires, deux sections de cette page.
  renderApexProfilesTab(document.getElementById('pers-apex'));
  renderIgnoresTab(document.getElementById('pers-ignores'));
}

function _cablerPersonnes(el) {
  const q = el.querySelector('#pers-q');
  q.addEventListener('input', function () {
    _persFiltres.q = q.value.trim();
    _persEcrireHash();
    _rendrePersonnes();
  });

  el.querySelector('#pers-plateformes').addEventListener('click', function (ev) {
    const b = ev.target.closest('[data-plateforme]');
    if (!b) return;
    _persFiltres.plateforme = b.dataset.plateforme;
    _persEcrireHash();
    _rendrePersonnes();
  });

  el.querySelector('#pers-tris').addEventListener('click', function (ev) {
    const b = ev.target.closest('[data-tri]');
    if (!b) return;
    _persFiltres.tri = b.dataset.tri;
    _persEcrireHash();
    _rendrePersonnes();
  });

  el.querySelector('#pers-puces').addEventListener('click', function (ev) {
    const b = ev.target.closest('[data-filtre]');
    if (!b) return;
    const nom = b.dataset.filtre;
    const i = _persFiltres.actifs.indexOf(nom);
    if (i === -1) _persFiltres.actifs.push(nom);
    else _persFiltres.actifs.splice(i, 1);
    _persEcrireHash();
    _rendrePersonnes();
  });

  // Une ligne est un LIEN vers la fiche : `location.hash` plutôt qu'un rendu
  // direct, pour que la fiche se partage et survive au rechargement.
  el.querySelector('#pers-fusion-bandeau').addEventListener('click', function (ev) {
    if (ev.target.closest('[data-fusion="annuler"]')) cancelLinkMode();
  });

  el.querySelector('#pers-liste').addEventListener('click', function (ev) {
    const ligne = ev.target.closest('[data-identite]');
    if (!ligne) return;
    // En mode fusion, un clic RATTACHE au lieu d'ouvrir : c'est tout l'objet du
    // mode, et le bandeau au-dessus le dit.
    if (_memLinkMode) {
      handleMemLinkClick(ligne.dataset.identite, ligne.dataset.nom || '',
                         ligne.dataset.plateforme || '');
      return;
    }
    location.hash = '#/cerveau/personnes/' + encodeURIComponent(ligne.dataset.identite);
  });
}

async function chargerPersonnes() {
  const liste = document.getElementById('pers-liste');
  if (!liste) return;
  liste.innerHTML = '<div class="liste-vide">Chargement…</div>';

  const [ru, ri, ra, rl] = await Promise.all([
    // Tout l'annuaire d'un coup, filtré ensuite dans le navigateur : une
    // pagination rendrait la recherche menteuse, elle ne chercherait que dans
    // la page chargée.
    apiFetch('/api/admin/memory/users?show_all=1&limit=1000'),
    apiFetch('/api/admin/ignored'),
    apiFetch('/api/admin/apex/profiles'),
    apiFetch('/api/admin/links'),
  ]);
  if (!ru || !ru.ok) {
    liste.innerHTML = '<div class="liste-vide">Erreur de chargement.</div>';
    return;
  }
  const gens = (await ru.json()).users || [];

  // « Ignoré » et « Apex lié » sont des filtres de CETTE liste : il faut donc
  // les rabattre sur chaque personne, sinon la puce ne pourrait rien filtrer.
  const ignores = (ri && ri.ok) ? await ri.json() : {};
  const clesIgnorees = new Set();
  (ignores.discord || []).forEach(function (e) { clesIgnorees.add('discord:' + e.id); });
  // `ignored.twitch` est une liste de CHAÎNES (les pseudos de `config.yaml`),
  // là où `ignored.discord` porte des objets. Les traiter pareil ajoutait
  // « twitch:undefined » et n'ignorait personne.
  (ignores.twitch || []).forEach(function (nom) {
    clesIgnorees.add('twitch:' + String(nom).toLowerCase());
  });

  const apex = {};
  if (ra && ra.ok) {
    ((await ra.json()).profiles || []).forEach(function (p) {
      (p.owners || []).forEach(function (o) { apex[o.identity || o] = p.apex_name; });
    });
  }

  _persGens = gens.map(function (p) {
    const identite = p.user_id;
    const nom = (p.username || '').toLowerCase();
    const plateforme = identite.split(':')[0];
    return Object.assign({}, p, {
      _plateforme: plateforme,
      _apex: apex[identite] || null,
      _ignore: clesIgnorees.has(identite)
        || (plateforme === 'twitch' && clesIgnorees.has('twitch:' + nom)),
    });
  });

  _rendrePersonnes();
  _majBandeauFusion();
  _rendreFusions((rl && rl.ok) ? (await rl.json()).proposals || [] : []);
}

function _rendrePersonnes() {
  const liste = document.getElementById('pers-liste');
  if (!liste) return;
  const f = _persFiltres;

  document.querySelectorAll('#pers-plateformes [data-plateforme]').forEach(function (b) {
    b.classList.toggle('active', b.dataset.plateforme === f.plateforme);
  });
  document.querySelectorAll('#pers-tris [data-tri]').forEach(function (b) {
    b.classList.toggle('active', b.dataset.tri === f.tri);
  });
  const champ = document.getElementById('pers-q');
  if (champ && champ.value !== f.q) champ.value = f.q;

  const q = f.q.toLowerCase();
  let gens = _persGens.filter(function (p) {
    if (f.plateforme && p._plateforme !== f.plateforme) return false;
    if (q && ((p.username || '') + ' ' + p.user_id + ' ' + (p._apex || ''))
        .toLowerCase().indexOf(q) === -1) return false;
    return f.actifs.every(function (nom) {
      const regle = _PERS_FILTRES.find(function (x) { return x[0] === nom; });
      return regle ? regle[2](p) : true;
    });
  });

  const puces = document.getElementById('pers-puces');
  if (puces) {
    puces.innerHTML = _PERS_FILTRES.map(function (x) {
      const actif = f.actifs.indexOf(x[0]) !== -1;
      return '<button class="puce' + (actif ? ' active' : '') + '" data-filtre="'
        + x[0] + '" aria-pressed="' + actif + '">' + escHtml(x[1])
        + (actif ? ' ✕' : '') + '</button>';
    }).join('');
  }

  const cles = {
    memories: function (p) { return p.memory_count || 0; },
    trust: function (p) { return p.trust_score || 0; },
    love: function (p) { return p.love_score || 0; },
    name: function (p) { return (p.username || '').toLowerCase(); },
  };
  const cle = cles[f.tri] || cles.memories;
  gens = gens.slice().sort(function (a, b) {
    const va = cle(a), vb = cle(b);
    if (f.tri === 'name') return String(va).localeCompare(String(vb));
    return vb - va;
  });

  _majSousTitrePersonnes(gens.length);

  if (!gens.length) {
    liste.innerHTML = '<div class="liste-vide">Personne ne correspond à ces filtres.</div>';
    return;
  }

  liste.innerHTML = gens.map(function (p) {
    const vu = p.last_updated ? apexDepuis(p.last_updated) : 'jamais vu';
    // Une personne ignorée n'annonce PAS ses mémoires : ce qu'on veut savoir
    // d'elle, c'est que Wally ne la lit plus.
    const meta = p._ignore
      ? '<span class="pers-ignore">ignoré</span>'
      : escHtml(p._plateforme) + ' · ' + Number(p.memory_count || 0)
        + ' mémoire' + ((p.memory_count || 0) > 1 ? 's' : '') + ' · vu ' + escHtml(vu);
    return '<div class="liste-ligne pers-ligne' + (p._ignore ? ' pers-terne' : '')
      + '" data-identite="' + escAttr(p.user_id)
      + '" data-nom="' + escAttr(p.username || p.user_id)
      + '" data-plateforme="' + escAttr(p._plateforme)
      + '" role="button" tabindex="0">'
      + '<div class="pers-qui">'
      + _persAvatar(p)
      + '<div><div class="pers-nom">' + escHtml(p.username || p.user_id) + '</div>'
      + '<div class="pers-meta">' + meta + '</div></div></div>'
      + '<span class="pers-trust">' + (p.trust_score || 0).toFixed(2) + '</span>'
      + '<span class="pers-love">' + (p.love_score || 0).toFixed(2) + '</span>'
      + '<span class="pers-apex">' + (p._apex ? escHtml(p._apex) : '—') + '</span>'
      + '</div>';
  }).join('');
}

/** L'avatar, ou l'initiale sur fond coloré quand la plateforme n'en donne pas. */
function _persAvatar(p) {
  if (p.avatar_url) {
    return '<img class="pers-avatar" src="' + escAttr(p.avatar_url)
      + '" alt="" loading="lazy">';
  }
  const nom = p.username || p.user_id || '?';
  const teinte = Math.abs(_persHash(nom)) % 360;
  return '<span class="pers-avatar pers-avatar-vide" style="background:hsl('
    + teinte + ',42%,38%)">' + escHtml(nom.slice(0, 1).toUpperCase()) + '</span>';
}

function _persHash(s) {
  let h = 0;
  for (let i = 0; i < s.length; i++) h = (h * 31 + s.charCodeAt(i)) | 0;
  return h;
}

/** Le sous-titre annonce ce que la liste MONTRE, pas ce que la base contient.
 *  Écrire « 455 connues » au-dessus de douze lignes filtrées ferait mentir la
 *  page sur ce qu'elle affiche. */
function _majSousTitrePersonnes(montrees) {
  const sous = document.getElementById('page-sub');
  if (!sous) return;
  const total = _persGens.length;
  const d = _persGens.filter(function (p) { return p._plateforme === 'discord'; }).length;
  const t = _persGens.filter(function (p) { return p._plateforme === 'twitch'; }).length;
  sous.textContent = (montrees === total
    ? total + ' connues'
    : montrees + ' sur ' + total + ' connues')
    + ' · ' + d + ' Discord · ' + t + ' Twitch';
  sous.hidden = false;
}

function _rendreFusions(propositions) {
  const boite = document.getElementById('pers-fusions');
  if (!boite) return;
  const attente = (propositions || []).filter(function (p) { return p.status === 'pending'; });

  boite.innerHTML = '<div class="page-section-titre">Fusions à valider</div>'
    + '<div class="page-section-sous">'
    + (attente.length
        ? attente.length + ' identité(s) semblent désigner quelqu\'un qu\'on connaît déjà.'
        : 'Aucune identité en attente de rattachement.')
    + '</div>';
  if (!attente.length) return;

  const hote = document.createElement('div');
  boite.appendChild(hote);
  renderPendingLinks(attente, hote);

  poserSommaire('cerveau/personnes', _PERS_SECTIONS,
    '<div class="rail-encart alerte">'
    + '<div class="rail-encart-titre">Fusions à valider</div>'
    + '<div class="rail-encart-ligne">' + attente.length
    + ' identité(s) semblent désigner la même personne.</div>'
    + '<div class="rail-encart-meta">section « Fusions à valider »</div></div>');
}

// ── Cerveau › Personnes › fiche ─────────────────────────────────────────────
//
// Tout ce que Wally sait d'une personne, en une requête. La fiche remplace la
// modale d'avant, qui ne montrait que les mémoires d'UNE identité : les faits
// d'un compte lié y étaient invisibles, sans que rien ne le dise.

const _FICHE_ONGLETS = [
  ['memoires', 'Mémoires'],
  ['notes', 'Notes qui la mentionnent'],
  ['comptes', 'Comptes liés'],
];

// Les catégories de `FactCategory`, groupées comme on les lit. « Expirent
// bientôt » n'est pas une catégorie : c'est une échéance, et c'est justement ce
// qu'on veut pouvoir isoler avant qu'elle tombe.
const _FICHE_FILTRES = [
  ['', 'Tout'],
  ['FAIT', 'Faits'],
  ['PREF', 'Préférences'],
  ['REL', 'Relations'],
  ['expire', 'Expirent bientôt'],
];

let _fiche = null;
let _ficheOnglet = 'memoires';
let _ficheFiltre = '';

async function renderFichePersonne(identite) {
  const el = document.getElementById('tab-admin-personne');
  if (!el) return;
  if (!identite) { location.hash = '#/cerveau/personnes'; return; }

  el.innerHTML = '<div class="liste-vide">Chargement…</div>';
  _fiche = null;

  const r = await apiFetch('/api/admin/person/' + encodeURIComponent(identite));
  // La route a pu changer pendant l'attente : une réponse tardive ne doit pas
  // écraser la personne qu'on regarde maintenant.
  if (currentParam !== identite) return;
  if (!r || !r.ok) {
    const detail = r ? (await r.json().catch(function () { return {}; })).detail : '';
    el.innerHTML = '<div class="liste-vide">'
      + escHtml(detail || 'Personne introuvable.')
      + ' — <a href="#/cerveau/personnes">revenir à l\'annuaire</a></div>';
    return;
  }
  _fiche = await r.json();
  _ficheOnglet = 'memoires';
  _ficheFiltre = '';
  _dessinerFiche();
}

function _dessinerFiche() {
  const el = document.getElementById('tab-admin-personne');
  const f = _fiche;
  if (!el || !f) return;

  const titre = document.getElementById('page-title');
  const sous = document.getElementById('page-sub');
  if (titre) titre.textContent = 'Personnes › ' + f.nom;
  if (sous) {
    sous.textContent = f.vu_le
      ? 'Vue ' + apexDepuis(f.vu_le) + '.'
      : 'Jamais vue depuis que Wally note les passages.';
    sous.hidden = false;
  }

  const puces = (f.identites || []).map(function (i) {
    return '<span class="fiche-puce">' + escHtml(i.plateforme) + ' · '
      + escHtml(i.nom) + '</span>';
  }).join('') + (f.alias || []).map(function (a) {
    return '<span class="fiche-puce fiche-puce-alias">« ' + escHtml(a) + ' »</span>';
  }).join('');

  el.innerHTML = '<a class="fiche-retour" href="#/cerveau/personnes">‹ Annuaire</a>'
    + '<div class="fiche-tete">'
    + _persAvatar({ avatar_url: f.avatar_url, username: f.nom, user_id: f.identity })
      .replace('pers-avatar', 'pers-avatar fiche-avatar')
    + '<div class="fiche-tete-txt">'
    + '<div class="fiche-nom">' + escHtml(f.nom)
    + (f.apex ? '<span class="fiche-badge">Apex lié</span>' : '')
    + (f.ignore ? '<span class="fiche-badge rouge">ignoré</span>' : '')
    + '</div>'
    + '<div class="fiche-puces">' + puces + '</div>'
    + '</div>'
    + '<div class="fiche-gestes">'
    + '<button class="btn" data-fiche="fusionner">Fusionner…</button>'
    + '<button class="btn" data-fiche="ignorer">'
    + (f.ignore ? 'Réécouter' : 'Ignorer') + '</button>'
    + '<button class="btn btn-danger" data-fiche="tout-oublier">Tout oublier</button>'
    + '</div></div>'

    + '<div class="fiche-tuiles">'
    + _ficheTuile('Trust', f.trust.toFixed(2), f.trust, 'var(--accent)')
    + _ficheTuile('Love', f.love.toFixed(2), f.love, 'var(--love)')
    + _ficheTuile('Mémoires', String((f.memoires || []).length), null, '')
    + _ficheTuile('Apex', f.apex ? f.apex.apex_name : '—', null, '')
    + '</div>'

    + '<div class="fiche-onglets">' + _FICHE_ONGLETS.map(function (o) {
        const n = o[0] === 'memoires' ? (f.memoires || []).length
          : o[0] === 'notes' ? (f.notes || []).length
          : (f.identites || []).length;
        return '<button data-onglet="' + o[0] + '"'
          + (o[0] === _ficheOnglet ? ' class="active"' : '') + '>'
          + escHtml(o[1]) + ' · ' + n + '</button>';
      }).join('') + '</div>'
    + '<div id="fiche-corps"></div>';

  _cablerFiche(el);
  _dessinerCorpsFiche();
  poserSommaire('cerveau/fiche', [], '');
}

function _ficheTuile(label, valeur, jauge, couleur) {
  return '<div class="fiche-tuile">'
    + '<div class="journal-stat-label">' + escHtml(label) + '</div>'
    + '<div class="fiche-tuile-valeur">' + escHtml(String(valeur)) + '</div>'
    + (jauge === null ? ''
      : '<div class="fiche-jauge"><span style="width:'
        + Math.round(Math.max(0, Math.min(1, jauge)) * 100) + '%;background:'
        + couleur + '"></span></div>')
    + '</div>';
}

/** Un seul écouteur, posé UNE fois sur le panneau.
 *
 *  `_dessinerFiche` réécrit tout le contenu à chaque geste : en reposer un à
 *  chaque rendu les empilerait, et « Oublier » finirait par demander trois
 *  confirmations pour un clic. La délégation survit aux réécritures. */
function _cablerFiche(el) {
  if (el.dataset.cable) return;
  el.dataset.cable = '1';
  el.addEventListener('click', function (ev) {
    const onglet = ev.target.closest('[data-onglet]');
    if (onglet) {
      _ficheOnglet = onglet.dataset.onglet;
      el.querySelectorAll('[data-onglet]').forEach(function (b) {
        b.classList.toggle('active', b.dataset.onglet === _ficheOnglet);
      });
      _dessinerCorpsFiche();
      return;
    }
    const filtre = ev.target.closest('[data-mfiltre]');
    if (filtre) {
      _ficheFiltre = filtre.dataset.mfiltre;
      _dessinerCorpsFiche();
      return;
    }
    const geste = ev.target.closest('[data-fiche]');
    if (geste) _gesteFiche(geste.dataset.fiche, geste.dataset.arg || '');
  });
}

function _dessinerCorpsFiche() {
  const boite = document.getElementById('fiche-corps');
  const f = _fiche;
  if (!boite || !f) return;

  if (_ficheOnglet === 'notes') {
    boite.innerHTML = '<div class="page-section-sous">Les notes du bot sont '
      + 'GLOBALES — aucune ne lui appartient. Voici celles où l\'un de ses noms '
      + 'apparaît.</div>'
      + ((f.notes || []).length
        ? (f.notes || []).map(function (n) {
            return '<div class="fiche-memoire"><div class="fiche-memoire-txt">'
              + '<strong>' + escHtml(n.title) + '</strong><br>'
              + escHtml(n.content) + '</div></div>';
          }).join('')
        : '<div class="liste-vide">Aucune note ne la mentionne.</div>');
    return;
  }

  if (_ficheOnglet === 'comptes') {
    boite.innerHTML = (f.identites || []).map(function (i) {
      const principal = i.identity === f.identity;
      return '<div class="fiche-memoire"><div class="fiche-memoire-txt">'
        + '<strong>' + escHtml(i.nom) + '</strong> '
        + '<span class="fiche-memoire-meta">' + escHtml(i.identity) + '</span></div>'
        + '<div class="fiche-memoire-actions">'
        + (principal ? '<span class="fiche-memoire-meta">compte principal</span>'
                     : '<button class="lien-danger" data-fiche="delier" data-arg="'
                       + escAttr(i.identity) + '">Détacher</button>')
        + '</div></div>';
    }).join('')
    + '<div class="fiche-alias-form">'
    + '<input id="fiche-alias" class="champ-recherche" placeholder="ajouter un surnom…" '
    + 'aria-label="Ajouter un surnom">'
    + '<button class="btn" data-fiche="alias-ajouter">Ajouter</button></div>'
    + ((f.alias || []).length
      ? '<div class="fiche-puces">' + (f.alias || []).map(function (a) {
          return '<span class="fiche-puce fiche-puce-alias">« ' + escHtml(a)
            + ' » <button class="puce-x" data-fiche="alias-retirer" data-arg="'
            + escAttr(a) + '" aria-label="Retirer ce surnom">✕</button></span>';
        }).join('') + '</div>'
      : '');
    return;
  }

  // ── Mémoires ──
  const bientot = Date.now() + 7 * 86400000;
  const memoires = (f.memoires || []).filter(function (m) {
    if (_ficheFiltre === '') return true;
    if (_ficheFiltre === 'expire') {
      return m.expires_at && new Date(m.expires_at).getTime() < bientot;
    }
    return m.category === _ficheFiltre;
  });

  boite.innerHTML = '<div class="journal-puces">' + _FICHE_FILTRES.map(function (x) {
      return '<button class="puce' + (x[0] === _ficheFiltre ? ' active' : '')
        + '" data-mfiltre="' + x[0] + '">' + escHtml(x[1]) + '</button>';
    }).join('') + '</div>'
    + '<div class="fiche-ajout">'
    + '<input id="fiche-nouvelle" class="champ-recherche" '
    + 'placeholder="ajouter un souvenir…" aria-label="Ajouter un souvenir">'
    + '<button class="btn" data-fiche="memoire-ajouter">Ajouter</button></div>'
    + (memoires.length
      ? memoires.map(_ficheMemoire).join('')
      : '<div class="liste-vide">Aucun souvenir dans cette catégorie.</div>');
}

function _ficheMemoire(m) {
  const expire = m.expires_at ? new Date(m.expires_at) : null;
  const meta = [
    m.category,
    m.origin || m.source || '',
    m.created_at ? m.created_at.slice(0, 10) : '',
    expire ? 'expire le ' + m.expires_at.slice(0, 10) : '',
  ].filter(Boolean).join(' · ');
  return '<div class="fiche-memoire' + (expire ? ' expire' : '') + '">'
    + '<div class="fiche-memoire-txt">' + escHtml(m.content)
    + '<div class="fiche-memoire-meta">' + escHtml(meta) + '</div></div>'
    + '<div class="fiche-memoire-actions">'
    + '<button class="lien-doux" data-fiche="memoire-editer" data-arg="'
    + Number(m.id) + '">Modifier</button>'
    + '<button class="lien-danger" data-fiche="memoire-oublier" data-arg="'
    + Number(m.id) + '">Oublier</button>'
    + '</div></div>';
}

/** Le propriétaire d'un fait : c'est SON identité qu'attendent les routes de
 *  mémoire, pas celle de la fiche. Un fait venu du compte Twitch lié serait
 *  sinon modifié sous l'identité Discord — et introuvable. */
function _ficheProprietaire(idMemoire) {
  const m = (_fiche.memoires || []).find(function (x) { return x.id === idMemoire; });
  return (m && m.user_id) || _fiche.identity;
}

async function _gesteFiche(geste, arg) {
  const f = _fiche;
  if (!f) return;

  if (geste === 'fusionner') {
    startLinkMode(f.identity, f.nom);
    location.hash = '#/cerveau/personnes';
    return;
  }

  if (geste === 'ignorer') {
    await _ficheBasculerEcoute(f);
    return;
  }

  if (geste === 'tout-oublier') {
    await oublierToutDe(f.identity, f.nom);
    return;
  }

  if (geste === 'memoire-ajouter') {
    const champ = document.getElementById('fiche-nouvelle');
    const contenu = (champ && champ.value || '').trim();
    if (!contenu) return;
    const r = await apiFetch('/api/admin/memory/users/'
      + encodeURIComponent(f.identity) + '/memories',
      { method: 'POST', body: JSON.stringify({ content: contenu, category: '' }) });
    if (r && r.ok) { toast('Souvenir ajouté'); _rechargerFiche(); }
    else toast('Ajout impossible', 'error');
    return;
  }

  if (geste === 'memoire-editer') {
    const id = Number(arg);
    const m = (f.memoires || []).find(function (x) { return x.id === id; });
    const texte = prompt('Modifier le souvenir :', m ? m.content : '');
    if (texte === null || !texte.trim()) return;
    const r = await apiFetch('/api/admin/memory/users/'
      + encodeURIComponent(_ficheProprietaire(id)) + '/memories/' + id,
      { method: 'PUT', body: JSON.stringify({ content: texte.trim() }) });
    if (r && r.ok) { toast('Souvenir modifié'); _rechargerFiche(); }
    else toast('Modification impossible', 'error');
    return;
  }

  if (geste === 'memoire-oublier') {
    const id = Number(arg);
    // « Oublier » ARCHIVE : le fait sort de la vue et du prompt, mais reste
    // rattrapable. Le dire, pour que le geste ne paraisse pas irréversible.
    if (!confirm('Oublier ce souvenir ? Il sort du prompt, mais reste archivé.')) return;
    const r = await apiFetch('/api/admin/memory/users/'
      + encodeURIComponent(_ficheProprietaire(id)) + '/memories/' + id,
      { method: 'DELETE' });
    if (r && r.ok) { toast('Souvenir oublié'); _rechargerFiche(); }
    else toast('Suppression impossible', 'error');
    return;
  }

  if (geste === 'alias-ajouter') {
    const champ = document.getElementById('fiche-alias');
    const nom = (champ && champ.value || '').trim();
    if (!nom) return;
    const r = await apiFetch('/api/admin/memory/aliases', {
      method: 'POST',
      body: JSON.stringify({ nickname: nom, canonical_uid: f.identity, display_name: f.nom }),
    });
    if (r && r.ok) { toast('Surnom ajouté'); _rechargerFiche(); }
    else toast('Ajout impossible', 'error');
    return;
  }

  if (geste === 'alias-retirer') {
    const r = await apiFetch('/api/admin/memory/aliases/' + encodeURIComponent(arg),
      { method: 'DELETE' });
    if (r && r.ok) { toast('Surnom retiré'); _rechargerFiche(); }
    else toast('Suppression impossible', 'error');
    return;
  }

  if (geste === 'delier') {
    if (!confirm('Détacher ' + arg + ' ? Ses souvenirs cesseront d\'apparaître ici.')) return;
    const rl = await apiFetch('/api/admin/links');
    const liens = (rl && rl.ok) ? (await rl.json()).proposals || [] : [];
    const lien = liens.find(function (l) {
      return l.status === 'accepted' && l.alias_id === arg;
    });
    if (!lien) { toast('Liaison introuvable', 'error'); return; }
    const r = await apiFetch('/api/admin/links/' + lien.id + '/unlink', { method: 'POST' });
    if (r && r.ok) { toast('Compte détaché'); _rechargerFiche(); }
    else toast('Détachement impossible', 'error');
  }
}

/** Écouter ou ignorer — le mécanisme diffère selon la plateforme.
 *
 *  Discord passe par la table des bannis du chat web, Twitch par la liste de
 *  la config. Les deux ne se voient pas l'un l'autre : n'en toucher qu'un
 *  laisserait la personne muette d'un côté et lue de l'autre.
 */
async function _ficheBasculerEcoute(f) {
  const discord = (f.identites || []).find(function (i) { return i.plateforme === 'discord'; });
  const twitch = (f.identites || []).find(function (i) { return i.plateforme === 'twitch'; });
  const remettre = f.ignore;

  if (discord) {
    const id = discord.identity.split(':')[1];
    if (remettre) await apiFetch('/api/admin/chat-bans/' + encodeURIComponent(id),
                                 { method: 'DELETE' });
    else await apiFetch('/api/admin/chat-bans', {
      method: 'POST',
      body: JSON.stringify({ discord_id: id, username: discord.nom,
                             reason: 'ignoré depuis la fiche' }),
    });
  }
  if (twitch) {
    const nom = (twitch.nom || twitch.identity.split(':')[1] || '').toLowerCase();
    // La liste courante vient de `/ignored`, pas d'un cache : la page a pu
    // rester ouverte pendant qu'on modifiait la liste ailleurs, et réécrire une
    // vieille copie effacerait ces changements.
    const ri = await apiFetch('/api/admin/ignored');
    const actuels = (ri && ri.ok) ? ((await ri.json()).twitch || []).map(String) : [];
    const suivante = remettre
      ? actuels.filter(function (n) { return n.toLowerCase() !== nom; })
      : (actuels.some(function (n) { return n.toLowerCase() === nom; })
          ? actuels : actuels.concat([nom]));
    // POST, pas PUT : `config.save()` réécrit la config en mémoire, et c'est
    // cette route-là que le panneau « Ignorés » emprunte déjà.
    await apiFetch('/api/admin/config', {
      method: 'POST',
      body: JSON.stringify({ twitch: { ignored_users: suivante } }),
    });
  }
  if (!discord && !twitch) { toast('Aucune identité à régler', 'error'); return; }
  toast(remettre ? 'Wally la réécoute' : 'Wally ne la lira plus');
  _rechargerFiche();
}

function _rechargerFiche() {
  if (_fiche) renderFichePersonne(_fiche.identity);
}

// ── Memory Tab State ────────────────────────────────────────────
let _memLinkMode = false;
let _memLinkSourceId = null;
let _memLinkSourceName = null;

/** Entre en mode « lier deux identités ».
 *
 *  Ce mode est une modale sans fenêtre : il attend un clic sur une AUTRE
 *  personne de l'annuaire. D'où le bandeau, et d'où l'abandon automatique du
 *  mode au changement de page — sans ça, le prochain clic n'importe où
 *  déclencherait une fusion.
 */
function startLinkMode(sourceUserId, sourceUsername) {
  _memLinkMode = true;
  _memLinkSourceId = sourceUserId;
  _memLinkSourceName = sourceUsername;
  _majBandeauFusion();
}

function cancelLinkMode() {
  _memLinkMode = false;
  _memLinkSourceId = null;
  _memLinkSourceName = null;
  _majBandeauFusion();
}

/** Le bandeau est rendu DANS l'annuaire, au-dessus de la liste. Il disparaît
 *  avec le mode. */
function _majBandeauFusion() {
  const boite = document.getElementById('pers-fusion-bandeau');
  if (!boite) return;
  if (!_memLinkMode) { boite.innerHTML = ''; boite.hidden = true; return; }
  boite.hidden = false;
  boite.innerHTML = '<div class="mem-link-banner-info"><strong>'
    + escHtml(_memLinkSourceName || '') + '</strong> ↔ cliquez sur la personne '
    + 'à rattacher…</div>'
    + '<button class="btn" data-fusion="annuler">Annuler</button>';
}

async function handleMemLinkClick(targetUserId, targetName, targetPlatform) {
  if (!_memLinkMode || !_memLinkSourceId) return;
  if (targetUserId === _memLinkSourceId) return;

  if (!confirm('Lier ' + _memLinkSourceName + ' avec ' + targetName + ' ?')) return;

  // Discord devient le canonique quand il est en jeu : c'est la plateforme qui
  // porte l'avatar et l'identifiant stable, Twitch n'ayant qu'un pseudo qui
  // change.
  const sourcePlatform = _memLinkSourceId.split(':')[0];
  let canonical, alias;
  if (sourcePlatform === 'discord') {
    canonical = _memLinkSourceId; alias = targetUserId;
  } else if (targetPlatform === 'discord') {
    canonical = targetUserId; alias = _memLinkSourceId;
  } else {
    canonical = _memLinkSourceId; alias = targetUserId;
  }

  const r = await apiFetch('/api/admin/links/manual', {
    method: 'POST',
    body: JSON.stringify({ canonical_id: canonical, alias_id: alias }),
  });
  if (r && r.ok) {
    toast('Comptes liés', 'success');
    cancelLinkMode();
    pollLinksBadge();
    // On ouvre la fiche du CANONIQUE : c'est elle qui porte désormais les deux
    // jeux de souvenirs, et c'est ce qu'on veut vérifier après une fusion.
    location.hash = '#/cerveau/personnes/' + encodeURIComponent(canonical);
  } else {
    const err = r ? await r.json().catch(function () { return {}; }) : {};
    toast(err.detail || 'Erreur liaison', 'error');
  }
}

/** Efface TOUT ce que Wally sait d'une personne. */
async function oublierToutDe(userId, displayName) {
  if (!confirm('Tout oublier de « ' + displayName + ' » ? '
    + 'Ses souvenirs sont archivés, pas effacés — mais la fiche sera vide.')) return;
  const r = await apiFetch('/api/admin/memory/users/' + encodeURIComponent(userId),
                           { method: 'DELETE' });
  if (r && r.ok) {
    toast('Mémoire effacée', 'success');
    location.hash = '#/cerveau/personnes';
  } else {
    toast('Suppression impossible', 'error');
  }
}

async function analyzeLinks() {
  const r = await apiFetch('/api/admin/links/analyze', { method: 'POST' });
  if (r && r.ok) {
    toast('Analyse déclenchée', 'success');
    await pollLinksBadge();
  } else {
    toast('Erreur analyse', 'error');
  }
}

async function acceptLink(id) {
  const r = await apiFetch(`/api/admin/links/${id}/accept`, { method: 'POST' });
  if (r && r.ok) {
    toast('Liaison acceptée — mémoires fusionnées', 'success');
    await Promise.all([chargerPersonnes(), pollLinksBadge()]);
  } else {
    toast('Erreur', 'error');
  }
}

async function rejectLink(id) {
  const r = await apiFetch(`/api/admin/links/${id}/reject`, { method: 'POST' });
  if (r && r.ok) {
    toast('Liaison rejetée', 'success');
    await Promise.all([chargerPersonnes(), pollLinksBadge()]);
  } else {
    toast('Erreur', 'error');
  }
}

async function unlinkAccounts(id) {
  const r = await apiFetch(`/api/admin/links/${id}/unlink`, { method: 'POST' });
  if (r && r.ok) {
    toast('Comptes déliés', 'success');
    await Promise.all([chargerPersonnes(), pollLinksBadge()]);
  } else {
    const err = r ? await r.json().catch(() => ({})) : {};
    toast(err.detail || 'Erreur déliaison', 'error');
  }
}

async function pollLinksBadge() {
  if (!getToken()) return;
  try {
    const r = await apiFetch('/api/admin/links?status=pending');
    if (!r || !r.ok) return;
    const { proposals } = await r.json();
    const badge = document.getElementById('links-badge');
    if (badge) {
      const count = proposals.length;
      badge.textContent = count;
      badge.style.display = count > 0 ? 'flex' : 'none';
    }
    renderPendingLinks(proposals);
  } catch (e) { /* ignore */ }
}

function renderPendingLinks(proposals, cible) {
  // La cible est passée par l'appelant depuis la refonte : la page Personnes
  // rend les fusions dans SA section, l'ancien onglet Mémoire dans la sienne.
  var container = cible || document.getElementById('mem-pending-links');
  if (!container) return;
  if (!proposals || proposals.length === 0) {
    container.textContent = '';
    return;
  }

  var wrapper = document.createElement('div');
  wrapper.className = 'mem-pending-links';

  var title = document.createElement('div');
  title.className = 'mem-pending-links-title';
  title.textContent = '🔗 ' + proposals.length + ' compte(s) à vérifier';
  wrapper.appendChild(title);

  proposals.forEach(function(p) {
    var card = document.createElement('div');
    card.className = 'mem-pending-link-card';

    var names = document.createElement('div');
    names.className = 'mem-pending-link-names';

    var canonical = document.createElement('span');
    canonical.className = 'mem-pending-link-user';
    canonical.textContent = p.canonical_username || p.canonical_id;
    canonical.title = p.canonical_id;
    names.appendChild(canonical);

    var arrow = document.createElement('span');
    arrow.className = 'mem-pending-link-arrow';
    arrow.textContent = '↔';
    names.appendChild(arrow);

    var alias = document.createElement('span');
    alias.className = 'mem-pending-link-user';
    alias.textContent = p.alias_username || p.alias_id;
    alias.title = p.alias_id;
    names.appendChild(alias);

    card.appendChild(names);

    if (p.confidence != null) {
      var score = document.createElement('span');
      score.className = 'mem-pending-link-score';
      score.textContent = Math.round(p.confidence * 100) + '%';
      card.appendChild(score);
    }

    var actions = document.createElement('div');
    actions.className = 'mem-pending-link-actions';

    var acceptBtn = document.createElement('button');
    acceptBtn.className = 'mem-pending-link-btn accept';
    acceptBtn.textContent = '✓';
    acceptBtn.title = 'Accepter';
    acceptBtn.onclick = function() { acceptLink(p.id); };
    actions.appendChild(acceptBtn);

    var rejectBtn = document.createElement('button');
    rejectBtn.className = 'mem-pending-link-btn reject';
    rejectBtn.textContent = '✕';
    rejectBtn.title = 'Rejeter';
    rejectBtn.onclick = function() { rejectLink(p.id); };
    actions.appendChild(rejectBtn);

    card.appendChild(actions);
    wrapper.appendChild(card);
  });

  container.textContent = '';
  container.appendChild(wrapper);
}


// ── Overlay toggle ──────────────────────────────────────────────────────────

async function toggleOverlay() {
  const r = await apiFetch('/api/admin/overlay/toggle', { method: 'POST' });
  if (r && r.ok) {
    const data = await r.json();
    updateOverlaySwitch(data.visible);
    toast(data.visible ? 'Overlay visible' : 'Overlay masqué');
  }
}

function updateOverlaySwitch(visible) {
  const sw = document.getElementById('overlay-switch');
  if (sw) {
    if (visible) sw.classList.add('on');
    else sw.classList.remove('on');
  }
  // Also update the tab-based switch if present
  if (typeof updateOverlaySwitchTab === 'function') updateOverlaySwitchTab(visible);
}

async function pollOverlayStatus() {
  try {
    const r = await apiFetch('/api/admin/overlay/status');
    if (r && r.ok) {
      const data = await r.json();
      updateOverlaySwitch(data.visible);
    }
  } catch {
    // Sondage périodique : le tour suivant réessaie dans 30 s. Journaliser
    // chaque échec noierait la console dès que le bot redémarre.
  }
}

// ── Visitors ────────────────────────────────────────────────────────────────

async function loadVisitors() {
  const el = document.getElementById('tab-admin-visitors');
  if (!el) return;

  const r = await apiFetch('/api/admin/chat-connections?limit=100');
  if (!r || !r.ok) { el.textContent = 'Erreur de chargement'; return; }
  const data = await r.json();
  const conns = data.connections || [];

  if (conns.length === 0) {
    el.innerHTML = '<div class="card"><p style="color:var(--text-secondary)">Aucune connexion enregistrée</p></div>';
    return;
  }

  // All user-provided fields escaped via escHtml()
  let rows = '';
  for (const c of conns) {
    const connTime = new Date(c.connected_at * 1000);
    const dateStr = connTime.toLocaleDateString('fr-FR', { day: '2-digit', month: '2-digit' });
    const timeStr = connTime.toLocaleTimeString('fr-FR', { hour: '2-digit', minute: '2-digit' });
    const duration = c.disconnected_at
      ? formatDuration(c.disconnected_at - c.connected_at)
      : '<span style="color:#00E5A0">en ligne</span>';
    const avatarHtml = c.avatar_url
      ? `<img src="${escAttr(c.avatar_url)}" class="visitor-avatar" alt="">`
      : '<div class="visitor-avatar-placeholder"></div>';
    rows += `
      <div class="visitor-row">
        ${avatarHtml}
        <div class="visitor-info">
          <strong>${escHtml(c.username)}</strong>
          <span class="visitor-date">${escHtml(dateStr)} ${escHtml(timeStr)}</span>
        </div>
        <div class="visitor-meta">
          <span class="visitor-msgs">${parseInt(c.message_count, 10)} msg</span>
          <span class="visitor-duration">${duration}</span>
        </div>
      </div>`;
  }

  el.innerHTML = `
    <div class="card">
      <div class="card-title">CONNEXIONS RECENTES AU CHAT WEB</div>
      <div class="visitor-list">${rows}</div>
    </div>`;
}

function formatDuration(seconds) {
  const s = Math.floor(seconds);
  if (s < 60) return s + 's';
  if (s < 3600) return Math.floor(s / 60) + 'min';
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  return h + 'h' + (m > 0 ? m + 'min' : '');
}

// ── Memory Dashboard ────────────────────────────────────────────────────────

function _removeQuestionRow(id, action) {
  const row = document.getElementById('mem-q-' + id);
  if (row) {
    row.style.transition = 'opacity 0.3s, transform 0.3s';
    row.style.opacity = '0';
    row.style.transform = 'translateX(20px)';
    setTimeout(function() { row.remove(); }, 300);
  }
  const pendingEl = document.getElementById('kpi-q-pending');
  const resolvedEl = document.getElementById('kpi-q-resolved');
  const totalEl = document.getElementById('kpi-q-total');
  const pending = pendingEl ? (parseInt(pendingEl.textContent, 10) || 0) : 0;
  if (action === 'resolve') {
    if (pendingEl && pending > 0) pendingEl.textContent = pending - 1;
    if (resolvedEl) resolvedEl.textContent = (parseInt(resolvedEl.textContent, 10) || 0) + 1;
  } else if (action === 'delete') {
    if (pendingEl && pending > 0) pendingEl.textContent = pending - 1;
    if (totalEl) totalEl.textContent = Math.max(0, (parseInt(totalEl.textContent, 10) || 0) - 1);
  }
}

async function resolveMemQuestion(id) {
  id = parseInt(id, 10);
  _removeQuestionRow(id, 'resolve');
  const r = await apiFetch(`/api/admin/memory/questions/${id}/resolve`, { method: 'POST' });
  if (r && r.ok) {
    toast('Question marquée comme résolue');
  } else {
    toast('Erreur lors de la résolution', 'error');
    chargerMemoireCommune();
  }
}

async function editMemQuestion(id) {
  id = parseInt(id, 10);
  const textEl = document.getElementById('mem-q-text-' + id);
  if (!textEl) return;
  const current = textEl.textContent;
  const newText = prompt('Modifier la question :', current);
  if (newText === null || newText.trim() === '' || newText.trim() === current) return;
  textEl.textContent = newText.trim();
  const r = await apiFetch(`/api/admin/memory/questions/${id}`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ question: newText.trim() }),
  });
  if (r && r.ok) {
    toast('Question modifiée');
  } else {
    toast('Erreur lors de la modification', 'error');
    textEl.textContent = current;
  }
}

async function deleteMemQuestion(id) {
  id = parseInt(id, 10);
  if (!confirm('Supprimer cette question ?')) return;
  _removeQuestionRow(id, 'delete');
  const r = await apiFetch(`/api/admin/memory/questions/${id}`, { method: 'DELETE' });
  if (r && r.ok) {
    toast('Question supprimée');
  } else {
    toast('Erreur lors de la suppression', 'error');
    chargerMemoireCommune();
  }
}

// ── Paramètres Tab (Émotions · LLM · Images) ─────────────────────────────────


function makeFormRow(labelText, inputEl) {
  const row = document.createElement('div');
  row.className = 'form-row';
  const lbl = document.createElement('label');
  lbl.textContent = labelText;
  row.appendChild(lbl);
  row.appendChild(inputEl);
  return row;
}

const _VOICE_OPTIONS = [
  ['fr-FR-Marc:MAI-Voice-2', '18 styles · facturée en tokens'],
  ['fr-FR-Soleil:MAI-Voice-2', '18 styles · facturée en tokens'],
  ['fr-FR-HenriNeural', '4 styles · gratuite (F0)'],
  ['fr-FR-DeniseNeural', '4 styles · gratuite (F0)'],
  ['fr-FR-RemyMultilingualNeural', 'sans émotion'],
  ['fr-FR-VivienneMultilingualNeural', 'sans émotion'],
  ['fr-FR-JeromeNeural', 'sans émotion'],
  ['fr-FR-EloiseNeural', 'sans émotion'],
];

async function _renderParametresVoice(panel) {
  if (!panel) return;
  panel.innerHTML = '';
  const r = await apiFetch('/api/admin/config');
  if (!r || !r.ok) { panel.textContent = 'Erreur de chargement'; return; }
  const cfg = await r.json();
  const v = cfg.voice || {};

  const section = document.createElement('div');
  section.className = 'overlay-section';
  const title = document.createElement('h3');
  title.textContent = 'Vocal (Discord)';
  section.appendChild(title);

  // Activé (checkbox)
  const chk = document.createElement('input');
  chk.type = 'checkbox'; chk.id = 'voice-enabled-p'; chk.checked = !!v.enabled;
  section.appendChild(makeFormRow('Activé', chk));

  // Voix (select)
  const sel = document.createElement('select');
  sel.id = 'voice-azure-p'; sel.className = 'neo-select';
  const opts = _VOICE_OPTIONS.slice();
  if (v.azure_voice && !opts.some(function(o) { return o[0] === v.azure_voice; })) {
    opts.unshift([v.azure_voice, '']);
  }
  opts.forEach(function(o) {
    const opt = document.createElement('option');
    opt.value = o[0];
    opt.textContent = o[1] ? `${o[0]} — ${o[1]}` : o[0];
    if (o[0] === v.azure_voice) opt.selected = true;
    sel.appendChild(opt);
  });
  section.appendChild(makeFormRow('Voix', sel));

  // Auto-leave (minutes)
  const al = document.createElement('input');
  al.type = 'number'; al.id = 'voice-autoleave-p'; al.className = 'neo-input';
  al.min = 1; al.max = 60; al.value = v.auto_leave_minutes != null ? v.auto_leave_minutes : 2;
  section.appendChild(makeFormRow('Auto-leave (min)', al));

  // VAD agressivité (0-3)
  const vad = document.createElement('select');
  vad.id = 'voice-vad-p'; vad.className = 'neo-select';
  ['0', '1', '2', '3'].forEach(function(o) {
    const opt = document.createElement('option');
    opt.value = o; opt.textContent = o;
    if (String(v.vad_aggressiveness) === o) opt.selected = true;
    vad.appendChild(opt);
  });
  section.appendChild(makeFormRow('Sensibilité VAD (0-3)', vad));

  const saveBtn = document.createElement('button');
  saveBtn.className = 'neo-btn'; saveBtn.textContent = 'Sauvegarder';
  saveBtn.onclick = saveVoiceConfigParams;
  section.appendChild(saveBtn);

  const note = document.createElement('p');
  note.style.cssText = 'opacity:.6;font-size:.85em;margin-top:8px';
  note.textContent = 'La voix et les seuils s\'appliquent à chaud. Activer/désactiver le vocal nécessite un redémarrage.';
  section.appendChild(note);

  panel.appendChild(section);
}

async function saveVoiceConfigParams() {
  const body = { voice: {
    enabled: document.getElementById('voice-enabled-p').checked,
    azure_voice: document.getElementById('voice-azure-p').value,
    auto_leave_minutes: parseInt(document.getElementById('voice-autoleave-p').value, 10),
    vad_aggressiveness: parseInt(document.getElementById('voice-vad-p').value, 10),
  }};
  const r = await apiFetch('/api/admin/config', { method: 'POST', body: JSON.stringify(body) });
  if (r && r.ok) toast('Config vocale sauvegardée', 'success');
  else toast('Échec de la sauvegarde', 'error');
}

async function _renderParametresEmotions(panel) {
  if (!panel) return;

  // Move config-form-container (emotions + lambdas + bot-general + spam sections) here
  // We load config then render only the emotion-related cards
  const r = await apiFetch('/api/admin/config');
  if (!r || !r.ok) { panel.textContent = 'Erreur de chargement'; return; }
  const cfg = await r.json();

  const wrapper = document.createElement('div');
  wrapper.id = 'parametres-emotions-inner';

  // Emotions sliders card
  const emotCard = document.createElement('div');
  emotCard.className = 'card config-section';
  emotCard.innerHTML = `
    <div class="config-section-title">ÉMOTIONS</div>
    <div id="gauges-parametres-inline" role="group" aria-label="Controle des emotions"></div>
    <div class="mt-4">
      <button class="btn btn-danger" onclick="resetEmotions()">RESET À NEUTRE (0.5)</button>
    </div>
  `;
  wrapper.appendChild(emotCard);

  // Decay lambdas card
  const lambdaCard = document.createElement('div');
  lambdaCard.className = 'card config-section';
  const lambdaRows = Object.entries(cfg.emotions).filter(function([name]) { return name !== 'boredom'; }).map(function([name, ec]) {
    const lam = ec.decay_lambda;
    const timeToZeroH = lam > 0 ? (Math.log(1/0.01)) / lam : Infinity;
    const timeLabel = timeToZeroH === Infinity ? '∞' : timeToZeroH < 1 ? Math.round(timeToZeroH * 60) + ' min' : Math.round(timeToZeroH * 10) / 10 + ' h';
    return `<div class="field-group" style="display:flex;align-items:center;gap:12px">
      <label class="field-label" for="cfg-lambda-${name}" style="color:${EMOTION_COLORS[name] || 'var(--text-muted)'};min-width:100px">${name.toUpperCase()} λ</label>
      <input type="number" id="cfg-lambda-${name}" min="0" max="1" step="0.001" value="${lam}" style="width:90px" oninput="updateDecayTime(this,'${name}')">
      <span id="decay-time-${name}" style="font-size:0.8rem;color:var(--text-secondary);white-space:nowrap">100→0% en <strong style="color:#e2e8f0">${timeLabel}</strong></span>
    </div>`;
  }).join('');
  const boredomRise = cfg.emotions.boredom && cfg.emotions.boredom.boredom_rise_per_hour != null ? cfg.emotions.boredom.boredom_rise_per_hour : 1.2;
  const boredomH = boredomRise > 0 ? 1/boredomRise : Infinity;
  const boredomLabel = boredomH === Infinity ? '∞' : boredomH < 1 ? Math.round(boredomH*60)+' min' : Math.round(boredomH*10)/10+' h';
  lambdaCard.innerHTML = `
    <div class="config-section-title">DÉCROISSANCE ÉMOTIONS (λ)</div>
    <p style="font-size:0.75rem;color:var(--text-muted);margin:0 0 12px">λ = vitesse de décroissance par heure. Plus la valeur est élevée, plus l'émotion retombe vite. Boredom monte avec l'inactivité et n'utilise pas ce paramètre.</p>
    ${lambdaRows}
    <div style="margin-top:16px;padding-top:12px;border-top:1px solid var(--border)">
      <div style="display:flex;align-items:center;gap:12px">
        <label class="field-label" for="cfg-boredom-rise" style="color:${EMOTION_COLORS['boredom'] || 'var(--text-muted)'};min-width:100px">BOREDOM ↑/h</label>
        <input type="number" id="cfg-boredom-rise" min="0" max="10" step="0.1" value="${boredomRise}" style="width:90px" oninput="updateBoredomTime(this)">
        <span id="boredom-time-info" style="font-size:0.8rem;color:var(--text-secondary);white-space:nowrap">0→100% en <strong style="color:#e2e8f0">${boredomLabel}</strong></span>
      </div>
      <p style="font-size:0.75rem;color:var(--text-muted);margin:8px 0 0">Vitesse de montée de l'ennui par heure d'inactivité. 1.2 = ennui max en ~50 min.</p>
    </div>
    <button class="btn btn-success" onclick="saveEmotionLambdas()">💾 SAUVEGARDER</button>
  `;
  wrapper.appendChild(lambdaCard);

  panel.appendChild(wrapper);

  // Les curseurs, puis l'état RÉEL par-dessus. Sans le second appel, ils
  // restaient tous à zéro — `currentEmotions` n'était rempli par personne.
  buildGauges('gauges-parametres-inline', true);
  await chargerEmotions();
}

/** Les réglages de l'ADAPTATEUR Discord — langue par défaut, heure du journal,
 *  fenêtre de contexte, salon de notification, anti-spam.
 *
 *  Ils vivaient dans le panneau « Émotions », où ils n'avaient rien à faire :
 *  la vitesse à laquelle la colère retombe et le nombre de messages avant un
 *  mute sont deux sujets sans rapport. La refonte les range sous Connexions,
 *  avec le reste de ce qui concerne les plateformes.
 */
async function _renderReglagesDiscord(panel) {
  if (!panel) return;
  const r = await apiFetch('/api/admin/config');
  if (!r || !r.ok) { panel.textContent = 'Erreur de chargement'; return; }
  const cfg = await r.json();

  const wrapper = document.createElement('div');
  const botCard = document.createElement('div');
  botCard.className = 'card config-section';
  botCard.innerHTML = `
    <div class="config-section-title">BOT GÉNÉRAL</div>
    <div class="field-group">
      <label class="field-label" for="cfg-lang">Langue par défaut</label>
      <input type="text" id="cfg-lang" value="${cfg.bot.language_default || ''}">
    </div>
    <div class="field-group">
      <label class="field-label" for="cfg-journal-time">Heure journal (HH:MM)</label>
      <input type="text" id="cfg-journal-time" value="${cfg.bot.journal_time || ''}">
    </div>
    <div class="field-group">
      <label class="field-label" for="cfg-ctx-size">Taille fenêtre contexte</label>
      <input type="number" id="cfg-ctx-size" value="${cfg.bot.context_window_size || 20}">
    </div>
    <div class="field-group">
      <label class="field-label" for="cfg-triggers">Triggers (séparés par virgule)</label>
      <input type="text" id="cfg-triggers" value="${(cfg.bot.trigger_names || []).join(', ')}">
    </div>
    <div class="field-group">
      <label class="field-label" for="cfg-cost-threshold">Seuil d'alerte coûts ($)</label>
      <input type="number" id="cfg-cost-threshold" min="1" max="1000" step="0.5" value="${cfg.bot.cost_alert_threshold || 25}">
    </div>
    <div class="field-group">
      <label class="field-label">Notifications Discord</label>
      <select id="cfg-notif-channel" style="width:100%">
        <option value="">Désactivé</option>
      </select>
      <p style="font-size:0.7rem;color:var(--text-muted);margin-top:4px">Alertes coûts et erreurs envoyées dans ce salon</p>
    </div>
    <button class="btn btn-success" onclick="saveBotGeneral()">💾 SAUVEGARDER</button>
  `;
  wrapper.appendChild(botCard);

  const spamCard = document.createElement('div');
  spamCard.className = 'card config-section';
  spamCard.innerHTML = `
    <div class="config-section-title">ANTI-SPAM DISCORD</div>
    <div class="field-group" style="display:flex;align-items:center;gap:12px">
      <label class="field-label" style="margin:0" for="cfg-spam-enabled">Activé</label>
      <input type="checkbox" id="cfg-spam-enabled" ${(cfg.discord.spam_detection || {}).enabled !== false ? 'checked' : ''}>
    </div>
    <div class="field-group">
      <label class="field-label" for="cfg-spam-max">Messages max</label>
      <input type="number" id="cfg-spam-max" min="3" max="50" value="${(cfg.discord.spam_detection || {}).max_messages || 10}">
      <p style="font-size:0.75rem;color:var(--text-muted);margin:4px 0 0">Nombre de messages avant déclenchement</p>
    </div>
    <div class="field-group">
      <label class="field-label" for="cfg-spam-window">Fenêtre (secondes)</label>
      <input type="number" id="cfg-spam-window" min="30" max="600" value="${(cfg.discord.spam_detection || {}).window_seconds || 120}">
      <p style="font-size:0.75rem;color:var(--text-muted);margin:4px 0 0">Période de temps pour compter les messages</p>
    </div>
    <div class="field-group">
      <label class="field-label" for="cfg-spam-mute">Durée mute (minutes)</label>
      <input type="number" id="cfg-spam-mute" min="1" max="60" value="${(cfg.discord.spam_detection || {}).mute_minutes || 5}">
    </div>
    <div class="field-group">
      <label class="field-label" for="cfg-spam-anger">Delta colère par message muté</label>
      <input type="number" id="cfg-spam-anger" min="0.01" max="0.2" step="0.01" value="${(cfg.discord.spam_detection || {}).spam_anger_delta || 0.05}">
      <p style="font-size:0.75rem;color:var(--text-muted);margin:4px 0 0">Augmentation de la colère quand un utilisateur muté continue de parler</p>
    </div>
    <div class="field-group">
      <label class="field-label" for="cfg-spam-exempt">Channels exemptés (IDs séparés par virgule)</label>
      <input type="text" id="cfg-spam-exempt" value="${((cfg.discord.spam_detection || {}).exempt_channels || []).join(', ')}">
      <p style="font-size:0.75rem;color:var(--text-muted);margin:4px 0 0">Ces salons ignorent la détection de spam</p>
    </div>
    <button class="btn btn-success" onclick="saveSpamConfig()">💾 SAUVEGARDER</button>
  `;
  wrapper.appendChild(spamCard);
  panel.appendChild(wrapper);
  loadNotificationChannels(cfg);
}

async function _renderParametresLLM(panel) {
  if (!panel) return;

  const r = await apiFetch('/api/admin/config');
  if (!r || !r.ok) { panel.textContent = 'Erreur de chargement'; return; }
  const cfg = await r.json();
  const [models, claudeModels] = await Promise.all([loadOpenAIModels(), loadClaudeModels()]);

  const REASONING_EFFORTS = ['none', 'minimal', 'low', 'medium', 'high', 'xhigh'];
  const TEXT_VERBOSITIES = ['low', 'medium', 'high'];
  const THINKING_TYPES = ['disabled', 'enabled', 'adaptive'];
  const THINKING_EFFORTS = ['low', 'medium', 'high', 'max'];

  const card = document.createElement('div');
  card.className = 'card config-section';
  card.innerHTML = `
    <div class="config-section-title">LLM — MODÈLES</div>
    <div class="field-group">
      <label class="field-label" for="cfg-primary-provider">Provider principal</label>
      <select id="cfg-primary-provider" onchange="onProviderChange()">
        ${providerOptions(cfg, 'primary')}
      </select>
    </div>
    <div class="field-group">
      <label class="field-label" for="cfg-primary-model">Modèle principal</label>
      <select id="cfg-primary-model">
        ${modelOptions(models, currentModel(cfg, 'primary'))}
      </select>
      <select id="cfg-primary-model-claude" style="display:none">
        ${claudeModels.map(function(m) { return '<option value="' + m + '"' + (m === (cfg.llm?.primary?.model || '') ? ' selected' : '') + '>' + m + '</option>'; }).join('')}
      </select>
    </div>
    <div class="field-group">
      <label class="field-label" for="cfg-secondary-provider">Provider secondaire</label>
      <select id="cfg-secondary-provider" onchange="onProviderChange()">
        ${providerOptions(cfg, 'secondary')}
      </select>
    </div>
    <div class="field-group">
      <label class="field-label" for="cfg-secondary-model">Modèle secondaire</label>
      <select id="cfg-secondary-model">
        ${modelOptions(models, currentModel(cfg, 'secondary'))}
      </select>
      <select id="cfg-secondary-model-claude" style="display:none">
        ${claudeModels.map(function(m) { return '<option value="' + m + '"' + (m === (cfg.llm?.secondary?.model || '') ? ' selected' : '') + '>' + m + '</option>'; }).join('')}
      </select>
    </div>
    <div id="openai-specific-settings">
      <div class="field-group">
        <label class="field-label" for="cfg-reasoning-effort">Niveau d'effort (reasoning) <span style="font-size:0.7rem;color:var(--text-muted)">OpenAI only</span></label>
        <select id="cfg-reasoning-effort">
          ${REASONING_EFFORTS.map(function(e) { return '<option value="' + e + '"' + (e === cfg.openai.reasoning_effort ? ' selected' : '') + '>' + e.toUpperCase() + '</option>'; }).join('')}
        </select>
      </div>
      <div class="field-group">
        <label class="field-label" for="cfg-text-verbosity">Verbosité des réponses <span style="font-size:0.7rem;color:var(--text-muted)">OpenAI only</span></label>
        <select id="cfg-text-verbosity">
          ${TEXT_VERBOSITIES.map(function(v) { return '<option value="' + v + '"' + (v === cfg.openai.text_verbosity ? ' selected' : '') + '>' + v.toUpperCase() + '</option>'; }).join('')}
        </select>
      </div>
    </div>
    <div id="claude-specific-settings" style="display:none">
      <div class="field-group">
        <label class="field-label" for="cfg-thinking-type">Réflexion (thinking) <span style="font-size:0.7rem;color:var(--text-muted)">Claude only</span></label>
        <select id="cfg-thinking-type" onchange="onThinkingTypeChange()">
          ${THINKING_TYPES.map(function(t) { return '<option value="' + t + '"' + (t === (cfg.llm?.primary?.thinking_type || 'disabled') ? ' selected' : '') + '>' + (t === 'disabled' ? 'DÉSACTIVÉ' : t === 'adaptive' ? 'ADAPTATIF' : 'ACTIVÉ (budget fixe)') + '</option>'; }).join('')}
        </select>
      </div>
      <div id="thinking-effort-group" class="field-group" style="display:none">
        <label class="field-label" for="cfg-thinking-effort">Niveau d'effort thinking</label>
        <select id="cfg-thinking-effort">
          ${THINKING_EFFORTS.map(function(e) { return '<option value="' + e + '"' + (e === (cfg.llm?.primary?.thinking_effort || 'medium') ? ' selected' : '') + '>' + e.toUpperCase() + '</option>'; }).join('')}
        </select>
        <p style="font-size:0.75rem;color:var(--text-muted);margin:4px 0 0">LOW = rapide · MEDIUM = équilibré · HIGH = défaut, pense souvent · MAX = max (Opus 4.6 only)</p>
      </div>
    </div>
    <div class="field-group">
      <label class="field-label" for="cfg-max-tokens">Max output tokens</label>
      <input type="number" id="cfg-max-tokens" min="100" max="32000" value="${cfg.openai.max_tokens}">
    </div>
    <button class="btn btn-success" onclick="saveOpenAI()">💾 SAUVEGARDER</button>
    <p id="llm-restart-notice" style="display:none;font-size:0.75rem;color:#f59e0b;margin-top:8px">⚠️ Changement de provider — redémarrage requis pour prendre effet.</p>
  `;
  panel.appendChild(card);

  onProviderChange();
}

async function _renderParametresImages(panel) {
  if (!panel) return;

  // Seule la section image_generation, lue au même endroit que le reste
  // de la config. (`loadOverlayConfig`, cité ici jusqu'au 2026-08-24,
  // était injoignable depuis la refonte des onglets.)
  const r = await apiFetch('/api/admin/config');
  if (!r || !r.ok) { panel.textContent = 'Erreur de chargement'; return; }
  const cfg = await r.json();
  const ig = cfg.image_generation || {};

  const section = document.createElement('div');
  section.className = 'overlay-section';
  const title = document.createElement('h3');
  title.textContent = 'Génération d\'images';
  section.appendChild(title);


  function makeSelect(id, options, selected) {
    const sel = document.createElement('select');
    sel.id = id + '-p';
    sel.className = 'neo-select';
    options.forEach(function(o) {
      const opt = document.createElement('option');
      opt.value = o; opt.textContent = o;
      if (o === selected) opt.selected = true;
      sel.appendChild(opt);
    });
    return sel;
  }

  section.appendChild(makeFormRow('Modèle', makeSelect('ig-model', ['gpt-image-1.5','gpt-image-1','gpt-image-1-mini'], ig.model)));
  section.appendChild(makeFormRow('Qualité', makeSelect('ig-quality', ['low','medium','high'], ig.quality)));
  section.appendChild(makeFormRow('Taille', makeSelect('ig-size', ['1024x1024','1024x1536','1536x1024'], ig.size)));
  section.appendChild(makeFormRow('Format', makeSelect('ig-format', ['png','jpeg','webp'], ig.format)));
  section.appendChild(makeFormRow('Background', makeSelect('ig-background', ['auto','transparent','opaque'], ig.background)));

  const dlRow = document.createElement('div'); dlRow.className = 'form-row';
  const dlLabel = document.createElement('label'); dlLabel.textContent = 'Limite/jour (global)'; dlRow.appendChild(dlLabel);
  const dlInput = document.createElement('input'); dlInput.type = 'number'; dlInput.id = 'ig-daily-limit-p'; dlInput.className = 'neo-input'; dlInput.value = ig.daily_limit; dlInput.style.width = '80px'; dlRow.appendChild(dlInput);
  const dlHint = document.createElement('span'); dlHint.style.color = 'rgba(255,255,255,0.35)'; dlHint.style.fontSize = '0.78rem'; dlHint.textContent = '-1 = illimité'; dlRow.appendChild(dlHint);
  section.appendChild(dlRow);

  const puRow = document.createElement('div'); puRow.className = 'form-row';
  const puLabel = document.createElement('label'); puLabel.textContent = 'Limite/jour (par user)'; puRow.appendChild(puLabel);
  const puInput = document.createElement('input'); puInput.type = 'number'; puInput.id = 'ig-per-user-limit-p'; puInput.className = 'neo-input'; puInput.value = ig.per_user_limit; puInput.style.width = '80px'; puRow.appendChild(puInput);
  const puHint = document.createElement('span'); puHint.style.color = 'rgba(255,255,255,0.35)'; puHint.style.fontSize = '0.78rem'; puHint.textContent = '-1 = illimité'; puRow.appendChild(puHint);
  section.appendChild(puRow);

  const costEst = document.createElement('div'); costEst.className = 'form-row'; costEst.id = 'ig-cost-estimate-p'; costEst.style.color = 'var(--accent)'; costEst.style.fontWeight = '600'; costEst.style.fontSize = '0.85rem';
  section.appendChild(costEst);

  const saveBtn = document.createElement('button'); saveBtn.className = 'neo-btn'; saveBtn.textContent = 'Sauvegarder'; saveBtn.onclick = saveImageGenConfigParams;
  section.appendChild(saveBtn);

  panel.appendChild(section);

  // Update cost estimate
  async function updateCostEstimateParams() {
    const model = document.getElementById('ig-model-p')?.value;
    const quality = document.getElementById('ig-quality-p')?.value;
    const size = document.getElementById('ig-size-p')?.value;
    if (!model || !quality || !size) return;
    const r2 = await fetch('/api/public/gallery/estimate-cost?model=' + model + '&quality=' + quality + '&size=' + size);
    if (r2.ok) {
      const data = await r2.json();
      const elCost = document.getElementById('ig-cost-estimate-p');
      if (elCost) elCost.textContent = 'Coût estimé : $' + data.cost_usd.toFixed(4) + ' par image';
    }
  }
  updateCostEstimateParams();
  document.getElementById('ig-model-p')?.addEventListener('change', updateCostEstimateParams);
  document.getElementById('ig-quality-p')?.addEventListener('change', updateCostEstimateParams);
  document.getElementById('ig-size-p')?.addEventListener('change', updateCostEstimateParams);
}

async function saveImageGenConfigParams() {
  const body = { image_generation: {
    model: document.getElementById('ig-model-p').value,
    quality: document.getElementById('ig-quality-p').value,
    size: document.getElementById('ig-size-p').value,
    format: document.getElementById('ig-format-p').value,
    background: document.getElementById('ig-background-p').value,
    daily_limit: parseInt(document.getElementById('ig-daily-limit-p').value),
    per_user_limit: parseInt(document.getElementById('ig-per-user-limit-p').value),
  }};
  const r = await apiFetch('/api/admin/config', { method: 'POST', body: JSON.stringify(body) });
  if (r && r.ok) toast('Config image sauvegardée', 'success');
}


// ── Système Tab (Logs · Twitch · Overlay · Instances) ────────────────────────


async function _renderSystemeTwitch(panel) {
  if (!panel) return;
  panel.innerHTML = '<p style="color:var(--text-muted);padding:16px">Chargement...</p>';

  var statusR = await apiFetch('/api/admin/twitch/auth-status');
  var status  = statusR && statusR.ok ? await statusR.json() : null;

  var botConnected      = status && status.bot.connected;
  var streamerConnected = status && status.streamer.connected;
  var clientIdSet       = status ? status.client_id_set : false;

  var BOT_SCOPES      = 'user:read:chat · user:write:chat · user:bot · moderator:read:followers · chat:read · chat:edit';
  var STREAMER_SCOPES = 'channel:read:subscriptions · bits:read · channel:read:redemptions · channel:manage:redemptions';

  function _authCard(id, icon, title, connected, username, scopes) {
    var dotColor   = connected ? '#22c55e' : '#ef4444';
    var statusText = connected ? (_escHtml(username) || 'Connecte') : 'Non connecte';
    var btnLabel   = connected ? 'Reconnecter' : 'Connecter';
    var btn = clientIdSet
      ? '<button class="btn btn-success" style="width:100%;margin-top:4px" onclick="startTwitchOAuth(\'' + id + '\')">' + btnLabel + '</button>'
      : '<p style="color:#f59e0b;font-size:0.8em;margin-top:8px">Configurer TWITCH_CLIENT_ID dans .env</p>';
    return '<div class="card" style="flex:1;min-width:220px;padding:20px">'
      + '<div style="display:flex;align-items:center;gap:10px;margin-bottom:14px">'
      + '<span style="font-size:1.5em">' + icon + '</span>'
      + '<div><div class="card-title" style="margin:0">' + title + '</div>'
      + '<div style="display:flex;align-items:center;gap:6px;margin-top:4px">'
      + '<span style="width:8px;height:8px;border-radius:50%;background:' + dotColor + ';display:inline-block"></span>'
      + '<span style="font-size:0.85em;color:' + (connected ? 'var(--text-primary)' : 'var(--text-muted)') + '">' + statusText + '</span>'
      + '</div></div></div>'
      + '<div style="font-size:0.75em;color:var(--text-muted);margin-bottom:14px;line-height:1.6"><strong>Scopes :</strong> ' + scopes + '</div>'
      + btn
      + '</div>';
  }

  // Charger les chaines invitees
  var chR = await apiFetch('/api/admin/twitch/channels');
  var channelsHtml = '';
  if (chR && chR.ok) {
    var channels = await chR.json();
    channelsHtml = channels.length === 0
      ? '<p style="color:var(--text-muted);margin-bottom:12px">Aucune chaîne invitée.</p>'
      : channels.map(function(ch) {
          var dotClass   = ch.irc_connected ? 'connected' : 'pending';
          var badgeClass = ch.live ? 'live' : 'offline';
          var badgeText  = ch.live ? 'LIVE' : 'hors ligne';
          return '<div class="twitch-channel-card" id="guest-ch-' + ch.name + '">'
            + '<div class="tc-dot ' + dotClass + '"></div>'
            + '<span class="tc-name">' + ch.name + '</span>'
            + '<span class="tc-badge ' + badgeClass + '">' + badgeText + '</span>'
            + '<button class="tc-kick" onclick="removeGuestChannel(\'' + ch.name + '\')">Déconnecter</button>'
            + '</div>';
        }).join('');
  } else {
    channelsHtml = '<p style="color:var(--text-muted);font-size:0.85em">Twitch non démarré — connecte les comptes ci-dessus et redémarre.</p>';
  }

  var restartHtml = _twitchPendingRestart
    ? '<div style="margin-top:20px">'
      + '<button class="btn" style="background:#f59e0b;color:#000;font-weight:600;width:100%" onclick="restartTwitchContainer()">Redémarrer le container</button>'
      + '<p style="font-size:0.75em;color:var(--text-muted);margin-top:6px;text-align:center">Le dashboard sera indisponible ~10 s.</p>'
      + '</div>'
    : '';

  panel.innerHTML = '<div style="padding:0 2px">'
    + '<div style="font-size:0.7em;letter-spacing:.08em;color:var(--text-muted);text-transform:uppercase;margin-bottom:12px">Authentification Twitch</div>'
    + '<div style="display:flex;gap:12px;flex-wrap:wrap;margin-bottom:20px">'
    + _authCard('bot',      '🤖', 'Compte Bot',     botConnected,      status && status.bot.username,      BOT_SCOPES)
    + _authCard('streamer', '📺', 'Compte Streamer', streamerConnected, status && status.streamer.username, STREAMER_SCOPES)
    + '</div>'
    + restartHtml
    + '<hr style="border-color:var(--border);margin:16px 0">'
    + '<div style="font-size:0.7em;letter-spacing:.08em;color:var(--text-muted);text-transform:uppercase;margin-bottom:12px">Chaînes invitées</div>'
    + '<div id="guest-channels-list">' + channelsHtml + '</div>'
    + '<div id="twitch-channels-add">'
    + '<input type="text" id="guest-channel-input" placeholder="nom de chaîne twitch…" style="flex:1" onkeydown="if(event.key===\'Enter\') addGuestChannel()">'
    + '<button class="btn btn-success" onclick="addGuestChannel()">+ Ajouter</button>'
    + '</div>'
    + '<div id="guest-channel-error" style="color:var(--c-offline);font-size:0.85em;margin-top:6px;display:none"></div>'
    + '<p style="color:var(--text-muted);font-size:0.8em;margin-top:10px">Le broadcaster doit avoir autorisé le bot (scope channel:bot) pour que Wally puisse parler.</p>'
    + '<p style="color:var(--text-muted);font-size:0.8em;margin-top:10px">'
    + 'Les comptes que Wally ignore se règlent dans <strong>Personnes</strong>, filtre « Ignorés »,'
    + ' avec ceux de Discord et la liste des bots déjà couverts d\'office.</p>'
    + '</div>';

  // Le div `tab-admin-twitch` n'existe plus depuis la refonte des onglets :
  // le vidage restait par prudence, il n'a plus de cible.
  var twitchEl = document.getElementById('tab-admin-twitch');
  if (twitchEl) twitchEl.innerHTML = '';
}

async function _renderSystemeOverlay(panel) {
  if (!panel) return;

  const base = window.location.origin;
  const urlEmotion = base + '/overlay';
  const urlImage = base + '/overlay-image';

  // Load config to get image overlay state + command name
  const cfgR = await apiFetch('/api/admin/config');
  const cfg = cfgR && cfgR.ok ? await cfgR.json() : {};
  const oi = cfg.overlay_image || {};
  const imageEnabled = !!oi.enabled;
  const imageCmd = oi.command || '!image';

  panel.innerHTML = `
    <div class="overlay-cards-grid">

      <!-- Overlay Émotions -->
      <div class="card overlay-card">
        <div class="overlay-card-header">
          <div class="overlay-card-icon" style="background:rgba(234,179,8,0.1);border-color:rgba(234,179,8,0.2)">🎭</div>
          <div>
            <div class="card-title" style="margin:0">OVERLAY COMPAGNON</div>
            <div class="overlay-card-sub">Bulles, réactions et widgets du live</div>
          </div>
        </div>
        <p class="overlay-card-desc">
          Wally commente le live en bulles courtes et affiche ses widgets
          (pile ou face, dé, roue, sondage…). Ancré en bas à gauche, fond
          transparent, compatible Browser Source OBS.
        </p>
        <div class="overlay-card-toggle-row">
          <span class="overlay-card-toggle-label">Afficher</span>
          <div class="overlay-switch" id="overlay-switch-emotion" style="cursor:pointer" onclick="toggleOverlayFromSysteme()">
            <div class="overlay-switch-knob"></div>
          </div>
          <span id="overlay-status-label-emotion" class="overlay-card-status">Masqué</span>
        </div>
        <div class="overlay-card-toggle-row">
          <span class="overlay-card-toggle-label" title="Fait croire à Wally qu'un live est en cours, pour régler l'overlay sans attendre un vrai stream. S'arrête tout seul.">Mode test (hors live)</span>
          <div class="overlay-switch" id="overlay-switch-forcelive" style="cursor:pointer" onclick="toggleOverlayForceLive()">
            <div class="overlay-switch-knob"></div>
          </div>
          <span id="overlay-status-label-forcelive" class="overlay-card-status">Inactif</span>
        </div>
        <div class="overlay-card-toggle-row">
          <span class="overlay-card-toggle-label" title="Par défaut l'overlay est ancré à droite (source posée sur le bord droit de l'écran). Bascule ici pour l'ancrer à gauche — l'URL change en conséquence.">Ancré à droite</span>
          <div class="overlay-switch on" id="overlay-switch-side" style="cursor:pointer" onclick="toggleOverlaySide()">
            <div class="overlay-switch-knob"></div>
          </div>
          <span id="overlay-status-label-side" class="overlay-card-status">Droite</span>
        </div>
        <div class="overlay-url-row">
          <span class="overlay-url-label">URL OBS</span>
          <code class="overlay-url-code" id="url-emotion">${urlEmotion}</code>
          <button class="overlay-copy-btn" onclick="copyOverlayUrl('url-emotion')">Copier</button>
        </div>
        <div class="overlay-url-hint">Browser Source · Largeur 560px · Hauteur 460px · Fond transparent</div>
      </div>

      <!-- Overlay Images -->
      <div class="card overlay-card">
        <div class="overlay-card-header">
          <div class="overlay-card-icon" style="background:rgba(6,182,212,0.1);border-color:rgba(6,182,212,0.2)">🖼️</div>
          <div>
            <div class="card-title" style="margin:0">OVERLAY IMAGES</div>
            <div class="overlay-card-sub">Galerie via commande Twitch</div>
          </div>
        </div>
        <p class="overlay-card-desc">
          Affiche une image de la galerie quand un viewer tape <code style="color:var(--accent)">${imageCmd}</code> dans le chat.
          Sa place, sa durée et ses animations se règlent dans « Mise en scène », par scène.
        </p>
        <div class="overlay-card-toggle-row">
          <span class="overlay-card-toggle-label">Activer</span>
          <div class="overlay-switch ${imageEnabled ? 'on' : ''}" id="overlay-switch-image" style="cursor:pointer" onclick="toggleOverlayImage()">
            <div class="overlay-switch-knob"></div>
          </div>
          <span id="overlay-status-label-image" class="overlay-card-status">${imageEnabled ? 'Activé' : 'Désactivé'}</span>
        </div>
        <div class="overlay-url-row">
          <span class="overlay-url-label">URL OBS</span>
          <code class="overlay-url-code" id="url-image">${urlImage}</code>
          <button class="overlay-copy-btn" onclick="copyOverlayUrl('url-image')">Copier</button>
        </div>
        <div class="overlay-url-hint">Browser Source · Largeur 1920px · Hauteur 1080px · Fond transparent</div>
      </div>
    </div>

    <!-- Image overlay config -->
    <div id="overlay-health-systeme" class="card" style="margin-top:12px">
      <div class="card-title">Rendu chez le streamer</div>
      <div id="overlay-health-line" class="muted">Mesure en cours…</div>
    </div>
    <div id="overlay-config-container-systeme"></div>
    <div id="atelier-sons" class="card" style="margin-top:12px"></div>
  `;

  pollOverlayStatusForSysteme();
  refreshOverlayForceLive();
  refreshOverlayHealth();
  loadOverlayConfigInPanel(document.getElementById('overlay-config-container-systeme'));
  renderAtelierSons();
}

// ── Mise en scène (onglet dédié) ─────────────────────────────────────────────

// Le panneau lui-même vit dans `overlay_admin.js` : app.js fait déjà près de
// 5700 lignes, et celui-ci en pèse plusieurs centaines à lui seul.
//
// Il a d'abord été une section ajoutée au bas de Système → Overlay, qu'il
// fallait dérouler pour atteindre. Un onglet de premier niveau, et un seul
// chemin : deux entrées vers le même écran, et c'est toujours celle qui traîne
// qu'on ouvre.
//
// Aucune garde ici : `OverlayAdmin.monter()` porte la sienne, posée sur le
// conteneur AVANT toute promesse. On lui passe donc le panneau de l'onglet tel
// quel — créer un sous-div à chaque appel en empilerait un par visite.
function renderSceneTab() {
  const el = document.getElementById('tab-admin-scene');
  if (!el) return;
  if (!window.OverlayAdmin) {
    el.textContent = 'Mise en scène indisponible : overlay_admin.js n\'est pas chargé.';
    return;
  }
  OverlayAdmin.monter(el);
  // La chrome vit HORS du panneau — dans l'en-tête de page et la barre du
  // haut —, et le routeur la vide à chaque changement de route. `monter()` ne
  // s'exécute qu'une fois : sans ce second appel, revenir sur la Scène
  // laisserait le sélecteur et l'URL OBS vides.
  OverlayAdmin.rendreChromePage();
}

// La télémétrie de rendu (fps, pire frame, GPU) était POSTÉE six fois par minute
// par chaque overlay et n'avait aucun consommateur : la mesure existait, elle
// n'était visible nulle part.
let _overlayHealthTimer = null;

async function refreshOverlayHealth() {
  const line = document.getElementById('overlay-health-line');
  if (!line) { clearInterval(_overlayHealthTimer); _overlayHealthTimer = null; return; }
  try {
    const r = await apiFetch('/api/admin/overlay/health');
    const d = r && r.ok ? await r.json() : null;
    if (!d || !d.connected) {
      line.textContent = 'Aucun overlay connecté.';
    } else {
      const worst = Math.round(Number(d.worst_frame_ms) || 0);
      line.textContent = `${d.fps} fps · pire frame ${worst} ms · ${d.gpu || 'GPU inconnu'}`;
    }
  } catch { /* le diagnostic ne doit jamais casser l'onglet */ }
  if (_overlayHealthTimer === null) {
    _overlayHealthTimer = setInterval(refreshOverlayHealth, 15000);
  }
}

// Mode test hors live : durée par défaut. Le serveur plafonne à 120 min.
const OVERLAY_FORCE_LIVE_MINUTES = 30;
let _forceLiveTimer = null;

function _renderForceLive(data) {
  const sw = document.getElementById('overlay-switch-forcelive');
  const lbl = document.getElementById('overlay-status-label-forcelive');
  if (!sw || !lbl) return;
  const active = !!(data && data.active);
  sw.classList.toggle('on', active);
  lbl.textContent = active
    ? `Actif · ${Math.ceil(data.remaining_minutes)} min`
    : 'Inactif';
  // L'échéance tombe toute seule : sans rafraîchissement, le bouton mentirait.
  clearInterval(_forceLiveTimer);
  if (active) _forceLiveTimer = setInterval(refreshOverlayForceLive, 30000);
}

async function refreshOverlayForceLive() {
  try {
    const r = await apiFetch('/api/admin/overlay/force-live');
    if (r && r.ok) _renderForceLive(await r.json());
  } catch {
    // Même raison qu'aux autres sondages : minuteur de 30 s, il repassera.
  }
}

async function toggleOverlayForceLive() {
  const sw = document.getElementById('overlay-switch-forcelive');
  const active = sw && sw.classList.contains('on');
  const r = await apiFetch('/api/admin/overlay/force-live', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(active ? { active: false }
                                : { minutes: OVERLAY_FORCE_LIVE_MINUTES }),
  });
  if (!r || !r.ok) { toast('Narrateur indisponible (bot Discord non connecté ?)'); return; }
  const data = await r.json();
  _renderForceLive(data);
  toast(data.active
    ? `Mode test actif ${Math.round(data.remaining_minutes)} min`
    : 'Mode test coupé');
}

// Côté d'ancrage : purement client (paramètre d'URL lu par l'overlay), donc
// rien à sauvegarder côté serveur — il suffit de recopier la bonne URL dans OBS.
function toggleOverlaySide() {
  const sw = document.getElementById('overlay-switch-side');
  const lbl = document.getElementById('overlay-status-label-side');
  const code = document.getElementById('url-emotion');
  if (!sw || !lbl || !code) return;
  // Droite = défaut, donc URL nue ; seule la gauche demande un paramètre.
  const droite = !sw.classList.contains('on');
  sw.classList.toggle('on', droite);
  lbl.textContent = droite ? 'Droite' : 'Gauche';
  const base = code.textContent.split('?')[0];
  code.textContent = droite ? base : `${base}?side=left`;
  toast(droite
    ? "URL remise au défaut (droite) — recopie-la dans OBS"
    : "URL mise à jour — recopie-la dans OBS pour passer à gauche");
}

async function toggleOverlayFromSysteme() {
  const r = await apiFetch('/api/admin/overlay/toggle', { method: 'POST' });
  if (r && r.ok) {
    const data = await r.json();
    updateOverlaySwitch(data.visible);
    const sw = document.getElementById('overlay-switch-emotion');
    const lbl = document.getElementById('overlay-status-label-emotion');
    if (sw) { if (data.visible) sw.classList.add('on'); else sw.classList.remove('on'); }
    if (lbl) lbl.textContent = data.visible ? 'Visible' : 'Masqué';
    toast(data.visible ? 'Overlay émotions visible' : 'Overlay émotions masqué');
  }
}

async function pollOverlayStatusForSysteme() {
  try {
    const r = await apiFetch('/api/admin/overlay/status');
    if (r && r.ok) {
      const data = await r.json();
      const sw = document.getElementById('overlay-switch-emotion');
      const lbl = document.getElementById('overlay-status-label-emotion');
      if (sw) { if (data.visible) sw.classList.add('on'); else sw.classList.remove('on'); }
      if (lbl) lbl.textContent = data.visible ? 'Visible' : 'Masqué';
    }
  } catch {
    // Sondage périodique : le tour suivant réessaie.
  }
}

async function toggleOverlayImage() {
  const sw = document.getElementById('overlay-switch-image');
  const lbl = document.getElementById('overlay-status-label-image');
  const isOn = sw && sw.classList.contains('on');
  const newEnabled = !isOn;
  const body = { overlay_image: { enabled: newEnabled } };
  const r = await apiFetch('/api/admin/config', { method: 'POST', body: JSON.stringify(body) });
  if (r && r.ok) {
    if (sw) { if (newEnabled) sw.classList.add('on'); else sw.classList.remove('on'); }
    if (lbl) lbl.textContent = newEnabled ? 'Activé' : 'Désactivé';
    toast(newEnabled ? 'Overlay images activé' : 'Overlay images désactivé', 'success');
  }
}

function copyOverlayUrl(elId) {
  const el = document.getElementById(elId);
  if (!el) return;
  // `navigator.clipboard` est INDÉFINI hors contexte sécurisé — c'est-à-dire
  // dès qu'on ouvre le dashboard en http sur l'IP locale. `.writeText` y levait
  // une TypeError SYNCHRONE, qu'aucun `.catch()` ne rattrape : le repli en
  // dessous n'a jamais tourné et le bouton ne faisait rien du tout.
  if (navigator.clipboard && window.isSecureContext) {
    navigator.clipboard.writeText(el.textContent)
      .then(function() { toast('URL copiée !', 'success'); })
      .catch(function() { _copyFallback(el.textContent); });
    return;
  }
  _copyFallback(el.textContent);
}

function _copyFallback(texte) {
  const ta = document.createElement('textarea');
  ta.value = texte;
  ta.setAttribute('readonly', '');
  ta.style.position = 'fixed';
  ta.style.opacity = '0';
  document.body.appendChild(ta);
  ta.select();
  let ok = false;
  try { ok = document.execCommand('copy'); } catch (e) { ok = false; }
  document.body.removeChild(ta);
  toast(ok ? 'URL copiée !' : 'Copie refusée — sélectionnez l\'URL à la main',
        ok ? 'success' : 'error');
}

async function loadOverlayConfigInPanel(container) {
  if (!container) return;
  const r = await apiFetch('/api/admin/config');
  if (!r || !r.ok) return;
  const cfg = await r.json();
  const oi = cfg.overlay_image || {};

  const oiSection = document.createElement('div');
  oiSection.className = 'overlay-section';
  const oiTitle = document.createElement('h3');
  oiTitle.textContent = 'Configuration — Overlay Images';
  oiSection.appendChild(oiTitle);


  function makeSelect(id, options, selected) {
    const sel = document.createElement('select'); sel.id = id; sel.className = 'neo-select';
    options.forEach(function(o) {
      const opt = document.createElement('option'); opt.value = o; opt.textContent = o;
      if (o === selected) opt.selected = true;
      sel.appendChild(opt);
    });
    return sel;
  }

  const cmdRow = document.createElement('div'); cmdRow.className = 'form-row';
  const cmdLabel = document.createElement('label'); cmdLabel.textContent = 'Commande Twitch'; cmdRow.appendChild(cmdLabel);
  const cmdInput = document.createElement('input'); cmdInput.type = 'text'; cmdInput.id = 'oi-command-s'; cmdInput.className = 'neo-input'; cmdInput.value = oi.command || '!image'; cmdInput.style.width = '120px'; cmdRow.appendChild(cmdInput);
  oiSection.appendChild(cmdRow);

  // Les quatre réglages d'AFFICHAGE — durée, animations d'entrée et de sortie,
  // durée d'animation — sont partis dans « Mise en scène », où ils se règlent
  // PAR SCÈNE comme ceux de tous les autres widgets. Ils vivaient ici,
  // globalement : deux endroits pour la même question, dont l'un que le panneau
  // de mise en scène ignorait. Laisser un champ mort rouvrirait le doublon.
  const oiRenvoi = document.createElement('div');
  oiRenvoi.className = 'form-row';
  oiRenvoi.style.opacity = '0.75';
  oiRenvoi.style.fontSize = '0.8rem';
  oiRenvoi.textContent = "Durée d'affichage et animations : onglet « Mise en "
    + "scène », élément « Image de la galerie » — et par scène.";
  oiSection.appendChild(oiRenvoi);

  oiSection.appendChild(makeFormRow('Filtre images', makeSelect('oi-filter-s', ['all','top','recent'], oi.random_filter)));

  const btnRow = document.createElement('div'); btnRow.className = 'form-row';
  const oiSaveBtn = document.createElement('button'); oiSaveBtn.className = 'neo-btn'; oiSaveBtn.textContent = 'Sauvegarder'; oiSaveBtn.onclick = saveOverlayImageConfigSysteme; btnRow.appendChild(oiSaveBtn);
  const oiTestBtn = document.createElement('button'); oiTestBtn.className = 'neo-btn'; oiTestBtn.textContent = 'Tester'; oiTestBtn.style.marginLeft = '8px'; oiTestBtn.onclick = testOverlayImage; btnRow.appendChild(oiTestBtn);
  oiSection.appendChild(btnRow);

  container.appendChild(oiSection);

}

async function saveOverlayImageConfigSysteme() {
  const sw = document.getElementById('overlay-switch-image');
  // Les quatre réglages d'affichage ne sont plus envoyés d'ici : ils vivent
  // dans le layout. Les laisser partirait la valeur d'un champ disparu — donc
  // `NaN` — et écraserait ce que la scène porte.
  const body = { overlay_image: {
    enabled: sw ? sw.classList.contains('on') : false,
    command: document.getElementById('oi-command-s').value,
    random_filter: document.getElementById('oi-filter-s').value,
  }};
  const r = await apiFetch('/api/admin/config', { method: 'POST', body: JSON.stringify(body) });
  if (r && r.ok) toast('Config overlay sauvegardée', 'success');
}

function _fmtNum(n) {
  if (n >= 1000000) return (n / 1000000).toFixed(1) + 'M';
  if (n >= 1000) return (n / 1000).toFixed(1) + 'k';
  return String(n);
}

// ── Merged Mémoire Tab (Users + Global + Dashboard) ──────────────────────────


// L'annuaire des gens que Wally connaît, chargé une fois pour toute la page.
// Il n'a rien d'Apex — il est né dans ce formulaire, il sert aussi au panneau
// « Ignorés ». Deux caches de la même liste, c'était deux requêtes et deux
// états qui se désynchronisent dès qu'on ajoute quelqu'un.
let _annuaireCache = null;
let _annuairePromesse = null;

async function annuairePersonnes() {
  if (_annuaireCache) return _annuaireCache;
  // La PROMESSE est mémorisée, pas seulement le résultat : deux panneaux qui
  // s'ouvrent coup sur coup lanceraient sinon deux fois la même requête, et le
  // second écraserait le cache du premier en pleine lecture.
  if (!_annuairePromesse) {
    _annuairePromesse = apiFetch('/api/admin/apex/personnes')
      .then(function(r) { return (r && r.ok) ? r.json() : null; })
      .then(function(d) { _annuaireCache = (d && d.people) || null; return _annuaireCache; })
      .catch(function(e) {
        console.error('Annuaire indisponible', e);
        return null;
      })
      .finally(function() { _annuairePromesse = null; });
  }
  return _annuairePromesse;
}

// ── Ignorés : tout ce que Wally ne lit pas ───────────────────────────────────
//
// Trois mécanismes coexistaient sans jamais se voir ensemble : la liste Twitch
// de la config (enterrée sous Système → Twitch), la table des bannis Discord
// (accessible seulement depuis la liste des visiteurs du chat web, donc
// impossible pour un membre qui n'y est jamais passé), et deux socles câblés
// en dur. La question qu'on se pose ici est « pourquoi Wally lit-il encore ce
// compte ? », et la réponse était toujours dans celui des trois qu'on n'avait
// pas sous les yeux.
//
// Tout est construit par le DOM, jamais par concaténation de HTML : ces pseudos
// viennent du chat et de Discord, personne ne les contrôle.
//
// Le socle est SERVI par `/api/admin/ignored`, jamais recopié ici : une liste
// dupliquée au front diverge du jour où quelqu'un ajoute un bot au module
// Python, et le panneau annonce alors le contraire du code qui décide.

let _ignores = null;

async function renderIgnoresTab(panel) {
  if (!panel) return;
  panel.replaceChildren();
  const attente = document.createElement('p');
  attente.style.cssText = 'color:var(--text-secondary);padding:16px';
  attente.textContent = 'Chargement…';
  panel.appendChild(attente);

  const r = await apiFetch('/api/admin/ignored');
  if (!r || !r.ok) { attente.textContent = 'Erreur de chargement'; return; }
  _ignores = await r.json();

  panel.replaceChildren(
    blocIgnores('discord'),
    blocIgnores('twitch'),
    blocSocle(),
  );
  // L'annuaire arrive après coup : le panneau est utilisable sans lui (on peut
  // toujours coller un id ou un pseudo), il ne fait qu'éviter de le chercher.
  annuairePersonnes().then(function() { majPlaceholdersIgnores(); });
}

// Ce que chaque plateforme appelle une identité, et comment on la saisit. Une
// table plutôt que deux blocs jumeaux : les deux formulaires ne diffèrent que
// par ces lignes-là, et deux copies auraient divergé au premier correctif.
const IGNORES_PLATEFORMES = {
  discord: {
    titre: 'Discord',
    aide: "Wally ne lit plus rien de ces personnes : aucune réponse, aucune "
        + "perception, aucun fait mémorisé. ⚠️ La connexion au chat web leur est "
        + "aussi refusée — c'est la même liste que le bouton « Bannir » des "
        + "visiteurs.",
    saisie: "Colle un id Discord, ou cherche quelqu'un par son nom",
    // Un id Discord est un snowflake : uniquement des chiffres.
    valide: function(v) { return /^[0-9]{5,25}$/.test(v); },
    refus: "Un id Discord ne contient que des chiffres. Pour ignorer quelqu'un "
         + "par son nom, choisis-le dans la liste qui s'ouvre.",
  },
  twitch: {
    titre: 'Twitch',
    aide: "Les bots croisés sur les chaînes invitées changent d'une chaîne à "
        + "l'autre. Wally ne lit plus une ligne de ces comptes.",
    saisie: 'Pseudo Twitch, ou cherche quelqu\'un par son nom',
    valide: function(v) { return /^[a-z0-9_]{1,25}$/.test(v); },
    refus: 'Pseudo Twitch invalide (lettres, chiffres et « _ » seulement).',
  },
};

function blocIgnores(plateforme) {
  const spec = IGNORES_PLATEFORMES[plateforme];
  const card = document.createElement('div');
  card.className = 'card apex-link-form';

  const titre = document.createElement('h3');
  titre.textContent = spec.titre;
  card.appendChild(titre);

  const aide = document.createElement('p');
  aide.className = 'apex-hint';
  aide.textContent = spec.aide;
  card.appendChild(aide);

  const liste = document.createElement('div');
  const entrees = ignoresDe(plateforme);
  if (!entrees.length) {
    const vide = document.createElement('p');
    vide.style.cssText = 'color:var(--text-secondary);margin:0 0 12px';
    vide.textContent = 'Personne d\'ignoré ici pour le moment.';
    liste.appendChild(vide);
  } else {
    entrees.forEach(function(e) { liste.appendChild(carteIgnore(plateforme, e)); });
  }
  card.appendChild(liste);

  card.appendChild(formulaireIgnore(plateforme));
  return card;
}

function ignoresDe(plateforme) {
  const brut = (_ignores || {})[plateforme] || [];
  // Twitch range des pseudos nus, Discord des objets : une seule forme en
  // sortie, pour que la carte et le retrait n'aient pas à savoir laquelle.
  return brut.map(function(e) {
    return (typeof e === 'string')
      ? { id: e, label: e, reason: null, depuis: null }
      : e;
  });
}

function carteIgnore(plateforme, e) {
  const carte = document.createElement('div');
  carte.className = 'twitch-channel-card';

  const nom = document.createElement('span');
  nom.className = 'tc-name';
  nom.textContent = e.label;
  carte.appendChild(nom);

  // L'id ne s'affiche que s'il n'EST pas déjà le libellé : sinon on écrit deux
  // fois la même chose, et la carte d'un ignoré sans pseudo devient illisible.
  const detail = [];
  if (e.id && e.id !== e.label) detail.push(e.id);
  if (e.reason) detail.push(e.reason);
  if (e.depuis) {
    detail.push('depuis le ' + new Date(e.depuis * 1000)
      .toLocaleDateString('fr-FR', { day: '2-digit', month: '2-digit', year: '2-digit' }));
  }
  if (detail.length) {
    const meta = document.createElement('span');
    meta.style.cssText = 'color:var(--text-secondary);font-size:0.75rem;margin-left:8px';
    meta.textContent = detail.join(' · ');
    carte.appendChild(meta);
  }

  const btn = document.createElement('button');
  btn.className = 'tc-kick';
  btn.textContent = 'Ne plus ignorer';
  btn.onclick = function() { retirerIgnore(plateforme, e.id); };
  carte.appendChild(btn);
  return carte;
}

function formulaireIgnore(plateforme) {
  const ligne = document.createElement('div');
  ligne.className = 'apex-link-row';

  // Le même sélecteur cherchable que le formulaire Apex — il n'a rien d'Apex,
  // il est simplement né là. 494 personnes connues en prod : un menu déroulant
  // ne se parcourt pas.
  const boite = document.createElement('div');
  boite.className = 'apex-people-box';
  const champ = document.createElement('input');
  champ.type = 'text';
  champ.id = 'ignore-champ-' + plateforme;
  champ.autocomplete = 'off';
  champ.placeholder = IGNORES_PLATEFORMES[plateforme].saisie;
  champ.oninput = function() { renderMenuIgnores(plateforme, champ.value); };
  champ.onfocus = function() { renderMenuIgnores(plateforme, champ.value); };
  champ.onblur = function() { fermerMenuIgnores(plateforme); };
  champ.onkeydown = function(e) { if (e.key === 'Enter') ajouterIgnoreSaisi(plateforme); };
  boite.appendChild(champ);

  const menu = document.createElement('div');
  menu.className = 'apex-people-menu';
  menu.id = 'ignore-menu-' + plateforme;
  boite.appendChild(menu);
  ligne.appendChild(boite);

  const btn = document.createElement('button');
  btn.className = 'btn btn-success';
  btn.textContent = '+ Ignorer';
  btn.onclick = function() { ajouterIgnoreSaisi(plateforme); };
  ligne.appendChild(btn);
  return ligne;
}

function majPlaceholdersIgnores() {
  const gens = _annuaireCache || [];
  Object.keys(IGNORES_PLATEFORMES).forEach(function(plateforme) {
    const champ = document.getElementById('ignore-champ-' + plateforme);
    if (!champ) return;
    const combien = gens.filter(function(p) {
      return String(p.identity || '').indexOf(plateforme + ':') === 0;
    }).length;
    if (combien) {
      champ.placeholder = IGNORES_PLATEFORMES[plateforme].saisie
        + ' (' + combien + ' connues)';
    }
  });
}

// Combien de propositions on montre. Au-delà, c'est un mur qu'on ne lit plus.
const IGNORES_MENU_MAX = 10;

function candidatsIgnores(plateforme, q) {
  const prefixe = plateforme + ':';
  const terme = (q || '').trim().toLowerCase();
  const deja = ignoresDe(plateforme).map(function(e) {
    return String(e.id).toLowerCase();
  });
  const trouves = [];
  (_annuaireCache || []).forEach(function(p) {
    const identite = String(p.identity || '');
    if (identite.indexOf(prefixe) !== 0) return;
    // La clé d'ignorance n'est pas la même des deux côtés : Discord range un
    // id, Twitch un pseudo — c'est ce que compare `is_ignored_chatter`.
    const cle = (plateforme === 'discord')
      ? identite.slice(prefixe.length)
      : String(p.nom || '').toLowerCase();
    if (!cle || deja.indexOf(String(cle).toLowerCase()) >= 0) return;
    if (terme) {
      const noms = (p.noms || []).concat([p.nom, cle]);
      const touche = noms.some(function(n) {
        return String(n || '').toLowerCase().indexOf(terme) >= 0;
      });
      if (!touche) return;
    }
    trouves.push({ cle: cle, nom: p.nom || cle, identite: identite });
  });
  trouves.sort(function(a, b) {
    const ap = String(a.nom).toLowerCase().indexOf(terme) === 0 ? 0 : 1;
    const bp = String(b.nom).toLowerCase().indexOf(terme) === 0 ? 0 : 1;
    return ap - bp || String(a.nom).localeCompare(String(b.nom));
  });
  return { liste: trouves.slice(0, IGNORES_MENU_MAX), total: trouves.length };
}

function renderMenuIgnores(plateforme, q) {
  const menu = document.getElementById('ignore-menu-' + plateforme);
  if (!menu) return;
  menu.replaceChildren();
  const res = candidatsIgnores(plateforme, q);
  if (!res.liste.length) {
    const rien = document.createElement('div');
    rien.className = 'apex-people-vide';
    rien.textContent = _annuaireCache
      ? 'Personne à proposer — tape l\'identité directement'
      : 'Chargement de l\'annuaire…';
    menu.appendChild(rien);
    menu.classList.add('ouvert');
    return;
  }
  res.liste.forEach(function(c, i) {
    const item = document.createElement('div');
    item.className = 'apex-people-item' + (i === 0 ? ' actif' : '');
    const nom = document.createElement('span');
    nom.className = 'apex-people-nom';
    nom.textContent = c.nom;
    const ident = document.createElement('span');
    ident.className = 'apex-people-id';
    ident.textContent = c.cle;
    item.append(nom, ident);
    // `mousedown` et non `click` : le `blur` du champ ferme le menu avant
    // qu'un `click` n'ait lieu, et le choix ne partirait jamais.
    item.onmousedown = function(e) {
      e.preventDefault();
      ajouterIgnore(plateforme, c.cle, c.nom);
    };
    menu.appendChild(item);
  });
  if (res.total > res.liste.length) {
    const reste = document.createElement('div');
    reste.className = 'apex-people-vide';
    reste.textContent = '… et ' + (res.total - res.liste.length)
      + ' autres — précise ta recherche';
    menu.appendChild(reste);
  }
  menu.classList.add('ouvert');
}

function fermerMenuIgnores(plateforme) {
  const menu = document.getElementById('ignore-menu-' + plateforme);
  if (menu) menu.classList.remove('ouvert');
}

function ajouterIgnoreSaisi(plateforme) {
  const champ = document.getElementById('ignore-champ-' + plateforme);
  if (!champ) return;
  const spec = IGNORES_PLATEFORMES[plateforme];
  const saisi = champ.value.trim().replace(/^@/, '').toLowerCase();
  if (!saisi) return;
  if (!spec.valide(saisi)) { toast(spec.refus, 'error'); return; }
  ajouterIgnore(plateforme, saisi, saisi);
}

async function ajouterIgnore(plateforme, cle, label) {
  const cible = String(cle).toLowerCase();
  if (ignoresDe(plateforme).some(function(e) {
    return String(e.id).toLowerCase() === cible;
  })) {
    toast('Déjà ignoré', 'error');
    return;
  }
  if (plateforme === 'discord') {
    await ecrireBanDiscord(cle, label);
  } else {
    await ecrireIgnoresTwitch(
      ignoresDe('twitch').map(function(e) { return e.id; }).concat([cible]));
  }
}

async function retirerIgnore(plateforme, cle) {
  if (plateforme === 'discord') {
    const r = await apiFetch('/api/admin/chat-bans/' + encodeURIComponent(cle),
                             { method: 'DELETE' });
    if (!r || !r.ok) { toast('Erreur', 'error'); return; }
    toast('Wally le lit de nouveau', 'success');
    rechargerIgnores();
  } else {
    await ecrireIgnoresTwitch(ignoresDe('twitch')
      .map(function(e) { return e.id; })
      .filter(function(v) { return v !== cle; }));
  }
}

async function ecrireBanDiscord(discordId, username) {
  const r = await apiFetch('/api/admin/chat-bans', {
    method: 'POST',
    body: JSON.stringify({ discord_id: String(discordId), username: username || null,
                           reason: 'ignoré depuis le dashboard' }),
  });
  if (!r || !r.ok) { toast('Erreur d\'enregistrement', 'error'); return; }
  toast('Wally ne le lira plus', 'success');
  rechargerIgnores();
}

async function ecrireIgnoresTwitch(liste) {
  const r = await apiFetch('/api/admin/config', {
    method: 'POST',
    body: JSON.stringify({ twitch: { ignored_users: liste } }),
  });
  if (!r || !r.ok) { toast('Erreur d\'enregistrement', 'error'); return; }
  toast('Comptes ignorés mis à jour', 'success');
  rechargerIgnores();
}

function rechargerIgnores() {
  renderIgnoresTab(document.getElementById('pers-ignores'));
  // La liste de l'annuaire porte le filtre « Ignorés » : la laisser en arrière
  // afficherait « écouté » sur quelqu'un qu'on vient de faire taire.
  if (currentRoute === 'cerveau/personnes') chargerPersonnes();
}

function blocSocle() {
  const socle = (_ignores || {}).socle || {};
  const card = document.createElement('div');
  card.className = 'card apex-link-form';

  const titre = document.createElement('h3');
  titre.textContent = 'Déjà ignorés, sans rien régler';
  card.appendChild(titre);

  const aide = document.createElement('p');
  aide.className = 'apex-hint';
  aide.textContent = 'Inutile de les ajouter ci-dessus : c\'est déjà fait, dans '
    + 'le code. Les lister ici évite de les saisir à la main puis de se demander '
    + 'pourquoi rien ne change.';
  card.appendChild(aide);

  [socle.discord, socle.twitch_badge].forEach(function(phrase) {
    if (!phrase) return;
    const p = document.createElement('p');
    p.style.cssText = 'margin:0 0 8px;font-size:0.82rem';
    p.textContent = '• ' + phrase;
    card.appendChild(p);
  });

  const bots = socle.twitch || [];
  if (bots.length) {
    const repli = document.createElement('details');
    const resume = document.createElement('summary');
    resume.style.cssText = 'cursor:pointer;font-size:0.82rem';
    resume.textContent = 'Les ' + bots.length + ' bots Twitch connus d\'office';
    repli.appendChild(resume);
    const corps = document.createElement('p');
    corps.style.cssText = 'color:var(--text-secondary);font-size:0.78rem;'
      + 'margin:8px 0 0;line-height:1.6';
    corps.textContent = bots.join(' · ');
    repli.appendChild(corps);
    card.appendChild(repli);
  }
  return card;
}

// ── Comptes Apex : le registre des profils croisés ───────────────────────────
//
// Le registre se remplit tout seul (chat, overlay, sonde du watcher) et un
// rapprochement approximatif peut y inscrire un pseudo qui mène au mauvais
// joueur. C'est le seul endroit où on peut le constater et le corriger.
//
// Tout est construit par le DOM, jamais par concaténation de HTML : ces pseudos
// viennent de l'API Apex et du chat, ils ne sont contrôlés par personne ici.

async function renderApexProfilesTab(panel) {
  if (!panel) return;
  panel.innerHTML = '<p style="color:var(--text-secondary);padding:16px">Chargement…</p>';

  const r = await apiFetch('/api/admin/apex/profiles');
  if (!r || !r.ok) { panel.textContent = 'Erreur de chargement'; return; }
  const profiles = (await r.json()).profiles || [];

  panel.innerHTML = '';
  panel.appendChild(apexLinkForm());

  if (!profiles.length) {
    const vide = document.createElement('p');
    vide.style.cssText = 'color:var(--text-secondary);padding:16px';
    vide.textContent = 'Aucun profil Apex croisé pour le moment. Le registre se '
      + 'remplit dès que quelqu\'un demande des stats, ou que la sonde du live tourne.';
    panel.appendChild(vide);
    return;
  }

  const grid = document.createElement('div');
  grid.className = 'apex-grid';
  profiles.forEach(function(p) { grid.appendChild(apexProfileCard(p)); });
  panel.appendChild(grid);
}

function apexLinkForm() {
  const card = document.createElement('div');
  card.className = 'card apex-link-form';

  const titre = document.createElement('h3');
  titre.textContent = 'Lier un compte Apex à quelqu\'un';
  card.appendChild(titre);

  const aide = document.createElement('p');
  aide.className = 'apex-hint';
  aide.textContent = "Colle le lien de la page apexlegendsstatus.com qui contient "
    + "l'uid (profile/uid/PC/1234567890), l'uid seul, ou un pseudo. Le compte est "
    + "vérifié auprès de l'API avant d'être enregistré.";
  card.appendChild(aide);

  const ligne = document.createElement('div');
  ligne.className = 'apex-link-row';

  // Un champ de recherche et non un menu déroulant : 494 personnes sont
  // connues, et parcourir la liste à la main n'est pas praticable. Le champ
  // porte l'identité choisie dans son dataset — c'est elle qui part en base.
  const boite = document.createElement('div');
  boite.className = 'apex-people-box';
  const who = document.createElement('input');
  who.type = 'text';
  who.id = 'apex-link-who';
  who.placeholder = 'Cherche une personne (pseudo, surnom, id…)';
  who.autocomplete = 'off';
  who.oninput = function() { who.dataset.identity = ''; renderApexPeopleMenu(who.value); };
  who.onfocus = function() { renderApexPeopleMenu(who.value); };
  who.onkeydown = function(e) { apexPeopleKeys(e); };
  boite.appendChild(who);
  const menu = document.createElement('div');
  menu.className = 'apex-people-menu';
  menu.id = 'apex-people-menu';
  boite.appendChild(menu);
  ligne.appendChild(boite);

  const ref = document.createElement('input');
  ref.type = 'text';
  ref.id = 'apex-link-ref';
  ref.placeholder = 'Lien du profil, uid, ou pseudo';
  ligne.appendChild(ref);

  const go = document.createElement('button');
  go.className = 'btn btn-success';
  go.textContent = 'Lier';
  go.onclick = function() { submitApexLink(); };
  ligne.appendChild(go);

  card.appendChild(ligne);
  fillApexPeople(who);
  return card;
}

async function fillApexPeople(champ) {
  const gens = await annuairePersonnes();
  champ.placeholder = gens
    ? 'Cherche parmi ' + gens.length + ' personnes (pseudo, surnom, id…)'
    : 'Annuaire indisponible — donne l\'identité à la main';
}

// Combien de propositions on affiche. Au-delà, la liste devient un mur qu'on
// ne lit plus : c'est le compte affiché en pied qui dit qu'il reste du monde.
const APEX_PEOPLE_MAX = 12;

function apexPeopleTrouves(q) {
  const gens = _annuaireCache || [];
  const terme = (q || '').trim().toLowerCase();
  if (!terme) return { liste: gens.slice(0, APEX_PEOPLE_MAX), total: gens.length };
  const trouves = [];
  gens.forEach(function(p) {
    // Le nom qui a MATCHÉ est retenu : chercher « mon ptit pote » et voir
    // s'afficher « KingsRequin » sans explication ressemble à une erreur.
    const via = (p.noms || []).find(function(n) {
      return String(n).toLowerCase().includes(terme);
    });
    if (via) trouves.push({ p: p, via: via });
  });
  // Un nom qui COMMENCE par ce qu'on tape passe devant : on tape le début.
  trouves.sort(function(a, b) {
    const ap = a.p.nom.toLowerCase().startsWith(terme) ? 0 : 1;
    const bp = b.p.nom.toLowerCase().startsWith(terme) ? 0 : 1;
    return ap - bp || a.p.nom.localeCompare(b.p.nom);
  });
  return { liste: trouves.slice(0, APEX_PEOPLE_MAX).map(function(t) {
    return Object.assign({}, t.p, { via: t.via });
  }), total: trouves.length };
}

function renderApexPeopleMenu(q) {
  const menu = document.getElementById('apex-people-menu');
  if (!menu) return;
  menu.innerHTML = '';
  const { liste, total } = apexPeopleTrouves(q);
  if (!liste.length) {
    const rien = document.createElement('div');
    rien.className = 'apex-people-vide';
    rien.textContent = _annuaireCache ? 'Personne ne porte ce nom' : 'Chargement…';
    menu.appendChild(rien);
    menu.classList.add('ouvert');
    return;
  }
  liste.forEach(function(p, i) {
    const item = document.createElement('div');
    item.className = 'apex-people-item' + (i === 0 ? ' actif' : '');
    item.dataset.identity = p.identity;
    item.dataset.nom = p.nom;

    const nom = document.createElement('span');
    nom.className = 'apex-people-nom';
    nom.textContent = p.nom;
    item.appendChild(nom);

    // Trouvé via un autre nom que celui qu'on affiche : on dit lequel.
    if (p.via && p.via.toLowerCase() !== String(p.nom).toLowerCase()) {
      const via = document.createElement('span');
      via.className = 'apex-people-via';
      via.textContent = '« ' + p.via + ' »';
      item.appendChild(via);
    }

    const ident = document.createElement('span');
    ident.className = 'apex-people-id';
    ident.textContent = p.identity;
    item.appendChild(ident);

    item.onmousedown = function(e) { e.preventDefault(); apexChoisirPersonne(item); };
    menu.appendChild(item);
  });
  if (total > liste.length) {
    const reste = document.createElement('div');
    reste.className = 'apex-people-vide';
    reste.textContent = '… et ' + (total - liste.length) + ' autres — précise ta recherche';
    menu.appendChild(reste);
  }
  menu.classList.add('ouvert');
}

function apexChoisirPersonne(item) {
  const champ = document.getElementById('apex-link-who');
  const menu = document.getElementById('apex-people-menu');
  if (!champ) return;
  champ.value = item.dataset.nom;
  // L'identité voyage à part : deux personnes peuvent porter le même pseudo,
  // et c'est l'identité — pas le texte affiché — qui part en base.
  champ.dataset.identity = item.dataset.identity;
  if (menu) menu.classList.remove('ouvert');
}

function apexPeopleKeys(e) {
  const menu = document.getElementById('apex-people-menu');
  if (!menu || !menu.classList.contains('ouvert')) return;
  const items = Array.from(menu.querySelectorAll('.apex-people-item'));
  if (!items.length) return;
  let i = items.findIndex(function(el) { return el.classList.contains('actif'); });
  if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
    e.preventDefault();
    if (i >= 0) items[i].classList.remove('actif');
    i = e.key === 'ArrowDown'
      ? (i + 1) % items.length
      : (i <= 0 ? items.length - 1 : i - 1);
    items[i].classList.add('actif');
    items[i].scrollIntoView({ block: 'nearest' });
  } else if (e.key === 'Enter') {
    e.preventDefault();
    apexChoisirPersonne(items[i >= 0 ? i : 0]);
  } else if (e.key === 'Escape') {
    menu.classList.remove('ouvert');
  }
}

async function submitApexLink() {
  const who = document.getElementById('apex-link-who');
  const ref = document.getElementById('apex-link-ref');
  if (!who || !ref) return;
  // Taper un nom ne suffit pas : il faut avoir CHOISI quelqu'un dans la liste,
  // sinon on ne sait pas quelle identité écrire — deux personnes peuvent
  // porter le même pseudo.
  if (!who.dataset.identity) {
    toast('Choisis une personne dans la liste', 'error');
    renderApexPeopleMenu(who.value);
    return;
  }
  if (!ref.value.trim()) { toast('Donne un lien, un uid ou un pseudo', 'error'); return; }

  const r = await apiFetch('/api/admin/apex/link', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      identity: who.dataset.identity,
      display_name: who.value,
      ref: ref.value.trim(),
    }),
  });
  if (r && r.ok) {
    const d = await r.json();
    // Un rapprochement se dit : la liaison est durable, et rien d'autre à
    // l'écran ne montrerait qu'elle repose sur une ressemblance de pseudos.
    if (d.rapproche) {
      toast('Lié à ' + d.apex_name + ' — rapproché de « ' + ref.value.trim()
        + ' », vérifie que c\'est le bon compte', 'info');
    } else {
      toast('Compte ' + d.apex_name + ' lié', 'success');
    }
    ref.value = '';
    who.value = '';
    who.dataset.identity = '';
    renderApexProfilesTab(document.getElementById('pers-apex'));
  } else {
    const err = r ? await r.json().catch(function() { return {}; }) : {};
    toast(err.detail || 'Liaison impossible', 'error');
  }
}

function apexProfileCard(p) {
  const card = document.createElement('div');
  card.className = 'apex-card';

  const head = document.createElement('div');
  head.className = 'apex-card-head';

  const nom = document.createElement('strong');
  nom.textContent = p.apex_name;
  head.appendChild(nom);

  const plat = document.createElement('span');
  plat.className = 'apex-platform';
  plat.textContent = p.platform || 'PC';
  head.appendChild(plat);

  // Une personne est souvent déclarée sur ses DEUX identités (Discord pour le
  // vocal, Twitch pour le chat) : autant de badges, et un déliage par identité.
  (p.owners || []).forEach(function(o) {
    const badge = document.createElement('span');
    badge.className = 'apex-owner';
    // La plateforme est DANS le badge, pas seulement en infobulle : les deux
    // identités d'une même personne portent le même pseudo, et deux badges
    // identiques côte à côte ne disent pas lequel on s'apprête à délier.
    const ou = String(o.identity || '').split(':')[0];
    badge.textContent = (ou ? ou + ' · ' : '') + (o.display_name || o.identity);
    badge.title = o.identity;
    const x = document.createElement('button');
    x.className = 'apex-chip-x';
    x.textContent = '✕';
    x.title = 'Délier ' + o.identity;
    x.onclick = function() { apexUnlink(o.identity, p.apex_name); };
    badge.appendChild(x);
    head.appendChild(badge);
  });
  // Les identités atteintes sans être déclarées : le compte vaut pour la
  // PERSONNE, et n'afficher que l'identité déclarée laissait croire que son
  // autre compte était resté sans rien.
  (p.couvre || []).forEach(function(ident) {
    const badge = document.createElement('span');
    badge.className = 'apex-owner couvert';
    badge.textContent = String(ident).split(':')[0] + ' · via ses comptes liés';
    badge.title = ident + " — atteint par la déclaration faite sur l'autre "
      + 'identité, les deux comptes étant liés';
    head.appendChild(badge);
  });
  // L'ABSENCE de badge est muette : une carte sans propriétaire se lisait comme
  // une carte normale, et on croyait le compte rattaché à quelqu'un. Cet onglet
  // liste tout le registre — croisé ≠ appartenant à quelqu'un d'ici.
  if (!(p.owners || []).length) {
    const seul = document.createElement('span');
    seul.className = 'apex-orphelin';
    seul.textContent = 'personne rattachée';
    seul.title = "Wally a croisé ce compte, mais il n'appartient à personne "
      + "d'ici. Tant qu'il n'est rattaché à personne, son prénom ne mène à rien.";
    head.appendChild(seul);

    const lier = document.createElement('button');
    lier.className = 'apex-mini-btn';
    lier.textContent = 'Lier à…';
    lier.onclick = function() { apexLierDepuisCarte(p); };
    head.appendChild(lier);
  }
  card.appendChild(head);

  const noms = document.createElement('div');
  noms.className = 'apex-names';
  p.names.forEach(function(n) {
    const chip = document.createElement('span');
    chip.className = 'apex-name-chip';
    const label = document.createElement('span');
    label.textContent = n;
    chip.appendChild(label);
    // Le nom officiel n'est pas retirable : le prochain scan le réinscrirait.
    if (n.toLowerCase() === String(p.apex_name).toLowerCase()) {
      chip.classList.add('officiel');
      chip.title = 'Nom officiel du compte — le prochain scan le réinscrirait';
    } else {
      const x = document.createElement('button');
      x.className = 'apex-chip-x';
      x.textContent = '✕';
      x.title = 'Oublier ce pseudo';
      x.onclick = function() { apexForgetName(p.uid, n); };
      chip.appendChild(x);
    }
    noms.appendChild(chip);
  });
  card.appendChild(noms);

  const pied = document.createElement('div');
  pied.className = 'apex-card-foot';

  const vu = document.createElement('span');
  vu.textContent = 'vu ' + (p.seen_count || 1) + '× · ' + apexDepuis(p.last_seen);
  pied.appendChild(vu);

  const lien = document.createElement('a');
  lien.href = p.url;
  lien.target = '_blank';
  lien.rel = 'noopener noreferrer';
  lien.className = 'apex-link';
  lien.textContent = '↗ Profil';
  pied.appendChild(lien);

  const oublier = document.createElement('button');
  oublier.className = 'apex-mini-btn danger';
  oublier.textContent = 'Oublier ce profil';
  oublier.onclick = function() {
    apexForgetProfile(p.uid, p.apex_name, (p.owners || []).length > 0);
  };
  pied.appendChild(oublier);

  card.appendChild(pied);
  return card;
}

function apexLierDepuisCarte(p) {
  // Le formulaire du haut sait déjà tout faire : on le pré-remplit avec l'uid
  // du profil plutôt que d'écrire un second chemin de liaison.
  const ref = document.getElementById('apex-link-ref');
  const who = document.getElementById('apex-link-who');
  if (!ref || !who) return;
  ref.value = p.uid;
  who.focus();
  who.scrollIntoView({ behavior: 'smooth', block: 'center' });
  toast('Choisis la personne à rattacher à ' + p.apex_name, 'info');
}

function apexDepuis(ts) {
  if (!ts) return 'jamais vu';
  const s = Math.max(0, Date.now() / 1000 - ts);
  if (s < 3600) return 'il y a ' + Math.round(s / 60) + ' min';
  if (s < 86400) return 'il y a ' + Math.round(s / 3600) + ' h';
  return 'il y a ' + Math.round(s / 86400) + ' j';
}

async function apexForgetName(uid, name) {
  if (!confirm('Oublier le pseudo « ' + name + ' » ?')) return;
  const r = await apiFetch(
    '/api/admin/apex/profiles/' + encodeURIComponent(uid) + '/names/' + encodeURIComponent(name),
    { method: 'DELETE' }
  );
  if (r && r.ok) {
    toast('Pseudo oublié', 'success');
    renderApexProfilesTab(document.getElementById('pers-apex'));
  } else {
    const err = r ? await r.json().catch(function() { return {}; }) : {};
    toast(err.detail || 'Suppression impossible', 'error');
  }
}

async function apexForgetProfile(uid, name, hasOwner) {
  let question = 'Retirer « ' + name + ' » du registre ? Wally ne saura plus '
    + 'retrouver ce compte par son pseudo.';
  // Les deux tables sont distinctes : le taire ferait croire que le geste
  // délie aussi la personne, ce qu'il ne fait pas.
  if (hasOwner) question += '\n\nLa personne restera liée à ce compte.';
  if (!confirm(question)) return;
  const r = await apiFetch('/api/admin/apex/profiles/' + encodeURIComponent(uid),
    { method: 'DELETE' });
  if (r && r.ok) {
    toast('Profil retiré du registre', 'success');
    renderApexProfilesTab(document.getElementById('pers-apex'));
  } else {
    toast('Suppression impossible', 'error');
  }
}

async function apexUnlink(identity, name) {
  if (!confirm('Délier ce compte de ' + identity + ' ? Le profil « ' + name
      + ' » reste connu de Wally.')) return;
  const r = await apiFetch('/api/admin/apex/link/' + encodeURIComponent(identity),
    { method: 'DELETE' });
  if (r && r.ok) {
    toast('Compte délié', 'success');
    renderApexProfilesTab(document.getElementById('pers-apex'));
  } else {
    toast('Déliage impossible', 'error');
  }
}

// ── « Dans la tête de Wally » : mémoire interne (#observability C4) ───────────

async function renderWallySelfTab(panel) {
  if (!panel) return;
  panel.innerHTML = '<p style="color:var(--text-secondary);padding:16px">Chargement...</p>';
  const r = await apiFetch('/api/admin/memory/self');
  if (!r || !r.ok) { panel.textContent = 'Erreur de chargement'; return; }
  const d = await r.json();

  function section(title, items, emptyMsg) {
    var rows = (items && items.length)
      ? items.map(function(it) { return '<li>' + escHtml(it) + '</li>'; }).join('')
      : '<li style="color:var(--text-secondary)">' + emptyMsg + '</li>';
    return '<div class="card" style="margin-bottom:16px">'
      + '<h3 style="margin:0 0 10px">' + escHtml(title) + '</h3>'
      + '<ul style="margin:0;padding-left:20px;line-height:1.7">' + rows + '</ul></div>';
  }

  panel.innerHTML = ''
    + section('🎯 Ses buts', d.goals, 'aucun but actif')
    + section('🔥 Ce qui le travaille (désirs)', d.desires, 'aucun désir actif')
    + section('💭 Ses pensées récentes', d.thoughts, 'aucune pensée enregistrée')
    + section('🤝 Ce qu\'il pense des gens (affinités)', d.relationships, 'aucune affinité formée')
    + section('🧭 Sa préoccupation du moment', d.focus ? [d.focus] : [], 'rien ne le préoccupe');
}


// ── Persistent notes tab ─────────────────────────────────────────────────────

async function loadNotesTab(panel) {
  if (!panel) return;
  panel.innerHTML = '<p style="color:var(--text-secondary);padding:16px">Chargement...</p>';

  const r = await apiFetch('/api/admin/notes');
  if (!r || !r.ok) { panel.textContent = 'Erreur de chargement'; return; }
  const data = await r.json();
  const notes = data.notes || [];

  const addFormId = 'notes-add-form';
  let html = '<div class="card mb-4">';
  html += '<div class="card-title">AJOUTER UNE NOTE</div>';
  html += '<div style="display:flex;flex-direction:column;gap:8px" id="' + addFormId + '">';
  html += '<input id="note-new-title" class="input" placeholder="Titre" style="background:var(--bg-surface);border:1px solid var(--border);border-radius:8px;padding:8px 12px;color:#fff" />';
  html += '<textarea id="note-new-content" class="input" rows="3" placeholder="Contenu" style="background:var(--bg-surface);border:1px solid var(--border);border-radius:8px;padding:8px 12px;color:#fff;resize:vertical"></textarea>';
  html += '<button class="btn btn-sm" onclick="saveNewNote()">Enregistrer</button>';
  html += '</div></div>';
  html += '<p style="color:var(--text-muted);font-size:0.82rem;margin:0 0 12px;padding:0 4px">Règles et engagements toujours injectés dans chaque conversation. Pour les infos critiques que le bot doit garder en tête.</p>';

  if (notes.length === 0) {
    html += '<p style="color:var(--text-secondary);padding:8px">Aucune note persistante</p>';
  } else {
    html += '<div class="card"><div class="card-title">NOTES DU BOT (' + notes.length + ')</div><div id="notes-list">';
    for (const n of notes) {
      html += renderNoteRow(n);
    }
    html += '</div></div>';
  }

  panel.innerHTML = html;
}

function renderNoteRow(n) {
  const id = parseInt(n.id, 10);
  const title = escHtml(n.title);
  const content = escHtml(n.content);
  const date = new Date(n.updated_at * 1000).toLocaleDateString('fr-FR');
  return '<div class="mem-dash-q-row" id="note-row-' + id + '" style="flex-direction:column;align-items:flex-start;gap:6px">'
    + '<div style="display:flex;justify-content:space-between;width:100%;align-items:center">'
    + '<strong>' + title + '</strong>'
    + '<span style="color:var(--text-muted);font-size:11px">' + date + '</span>'
    + '</div>'
    + '<div id="note-content-' + id + '" style="color:var(--text-primary);font-size:13px;white-space:pre-wrap">' + content + '</div>'
    + '<div class="mem-dash-q-actions">'
    + '<button class="btn btn-sm btn-outline" onclick="editNote(' + id + ')">Modifier</button>'
    + '<button class="btn btn-sm btn-danger" onclick="deleteNote(' + id + ')">Supprimer</button>'
    + '</div>'
    + '</div>';
}

async function saveNewNote() {
  const title = (document.getElementById('note-new-title') || {}).value || '';
  const content = (document.getElementById('note-new-content') || {}).value || '';
  if (!title.trim() || !content.trim()) { toast('Titre et contenu requis', 'error'); return; }
  const r = await apiFetch('/api/admin/notes', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ title: title.trim(), content: content.trim() }),
  });
  if (r && r.ok) {
    toast('Note enregistrée');
    const panel = document.getElementById('mc-notes');
    if (panel) loadNotesTab(panel);
  } else {
    toast('Erreur lors de l\'enregistrement', 'error');
  }
}

async function editNote(id) {
  id = parseInt(id, 10);
  const contentEl = document.getElementById('note-content-' + id);
  if (!contentEl) return;
  const current = contentEl.textContent;
  const newContent = prompt('Modifier la note :', current);
  if (newContent === null || newContent.trim() === '' || newContent.trim() === current) return;
  contentEl.textContent = newContent.trim();
  const r = await apiFetch('/api/admin/notes/' + id, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ title: document.getElementById('note-row-' + id).querySelector('strong').textContent, content: newContent.trim() }),
  });
  if (r && r.ok) {
    toast('Note modifiée');
  } else {
    toast('Erreur lors de la modification', 'error');
    contentEl.textContent = current;
  }
}

async function deleteNote(id) {
  id = parseInt(id, 10);
  if (!confirm('Supprimer cette note ?')) return;
  const row = document.getElementById('note-row-' + id);
  if (row) { row.style.opacity = '0'; row.style.transition = 'opacity 0.3s'; setTimeout(function() { row.remove(); }, 300); }
  const r = await apiFetch('/api/admin/notes/' + id, { method: 'DELETE' });
  if (r && r.ok) {
    toast('Note supprimée');
  } else {
    toast('Erreur lors de la suppression', 'error');
    const panel = document.getElementById('mc-notes');
    if (panel) loadNotesTab(panel);
  }
}


// ── Merged Overlay Tab (toggle + config) ────────────────────────────────────

async function toggleOverlayFromTab() {
  const r = await apiFetch('/api/admin/overlay/toggle', { method: 'POST' });
  if (r && r.ok) {
    const data = await r.json();
    updateOverlaySwitch(data.visible);
    updateOverlaySwitchTab(data.visible);
    toast(data.visible ? 'Overlay visible' : 'Overlay masqué');
  }
}

function updateOverlaySwitchTab(visible) {
  const sw = document.getElementById('overlay-switch-tab');
  const lbl = document.getElementById('overlay-status-label');
  if (sw) {
    if (visible) sw.classList.add('on');
    else sw.classList.remove('on');
  }
  if (lbl) lbl.textContent = visible ? 'Visible' : 'Masqué';
}

async function updateCostEstimate() {
  const model = document.getElementById('ig-model')?.value;
  const quality = document.getElementById('ig-quality')?.value;
  const size = document.getElementById('ig-size')?.value;
  const r = await fetch('/api/public/gallery/estimate-cost?model=' + model + '&quality=' + quality + '&size=' + size);
  if (r.ok) {
    const data = await r.json();
    const el = document.getElementById('ig-cost-estimate');
    if (el) el.textContent = 'Coût estimé : $' + data.cost_usd.toFixed(4) + ' par image';
  }
}

async function saveImageGenConfig() {
  const body = { image_generation: {
    model: document.getElementById('ig-model').value,
    quality: document.getElementById('ig-quality').value,
    size: document.getElementById('ig-size').value,
    format: document.getElementById('ig-format').value,
    background: document.getElementById('ig-background').value,
    daily_limit: parseInt(document.getElementById('ig-daily-limit').value),
    per_user_limit: parseInt(document.getElementById('ig-per-user-limit').value),
  }};
  const r = await apiFetch('/api/admin/config', { method: 'POST', body: JSON.stringify(body) });
  if (r && r.ok) toast('Config image sauvegardée', 'success');
}

async function saveOverlayImageConfig() {
  // Les quatre réglages d'affichage ne partent plus d'ici : ils vivent dans le
  // layout, par scène. Les laisser enverrait la valeur d'un champ disparu —
  // donc `NaN` — et écraserait ce que la scène porte.
  const body = { overlay_image: {
    enabled: document.getElementById('oi-enabled').checked,
    command: document.getElementById('oi-command').value,
    random_filter: document.getElementById('oi-filter').value,
  }};
  const r = await apiFetch('/api/admin/config', { method: 'POST', body: JSON.stringify(body) });
  if (r && r.ok) toast('Config overlay sauvegardée', 'success');
}

async function testOverlayImage() {
  const r = await apiFetch('/api/admin/overlay-image/test', { method: 'POST' });
  if (r && r.ok) toast('Image envoyée à l\'overlay', 'success');
  else if (r && r.status === 404) toast('Aucune image dans la galerie', 'error');
  else if (r && r.status === 429) toast('Une image est déjà affichée', 'error');
}


// ── Actions Tab ──────────────────────────────────────────────────────────────

async function startActionSSE() {
  if (actionSSE) actionSSE.close();
  actionSSE = await openAdminSSE('/api/admin/sse/actions');
  if (!actionSSE) return;
  actionSSE.onmessage = function(e) {
    try {
      var evt = JSON.parse(e.data);
      if (evt.type && evt.task_id) {
        // Une seule liste désormais : le filtre d'état est appliqué au rendu,
        // pas à la requête. Un rechargement les sert donc tous les trois.
        chargerAutomatisations();
      }
    } catch (err) {
      console.warn('flux actions : message ignoré', err, e.data);
    }
  };
  actionSSE.onerror = function () {
    // La reconnexion est celle d'`EventSource`, automatique. On le dit quand
    // même : un flux qui tombe pour de bon laisse la liste des tâches figée
    // sur un état ancien, sans que rien ne l'indique à l'écran.
    console.warn('flux actions : coupé, EventSource va retenter');
  };
}

function stopActionSSE() {
  if (actionSSE) { actionSSE.close(); actionSSE = null; }
}

// ── Automatisations ─────────────────────────────────────────────────────────
//
// Refonte du 2026-08-28. Trois onglets — Tâches, Terminées, Permissions — pour
// une seule et même liste vue sous trois angles. Les deux premiers deviennent
// un filtre d'état, le troisième une section de la page.
//
// Pas de bouton « + Tâche », malgré la maquette : il n'existe aucune route de
// création côté serveur (`routes/actions.py` n'expose que GET, cancel, pause,
// resume, execute). Les tâches naissent d'une demande faite à Wally, qui passe
// par `ActionService.create()`. Un bouton branché sur rien coûte plus cher
// qu'un bouton absent — on le saurait, le panel en a compté huit.

const _AUTO_VUES = [
  ['avenir', 'À venir'],
  ['terminees', 'Terminées'],
  ['echec', 'En échec'],
];

const _AUTO_SECTIONS = [
  ['auto-taches', 'Tâches'],
  ['auto-permissions', 'Qui peut demander quoi'],
  ['auto-historique', 'Historique d\'exécution'],
];

let _autoFiltres = { q: '', vue: 'avenir' };
let _autoTaches = [];
let _autoOuverte = null;   // l'id de la tâche dépliée, s'il y en a une

/** L'état d'une tâche, tel que la page le range.
 *
 *  `last_error` prime sur le statut : une tâche récurrente qui échoue reste
 *  `active` jusqu'à sa troisième tentative, et la ranger « à venir » sans rien
 *  dire est exactement ce qui la laissait échouer trois semaines.
 */
function _autoEtat(t) {
  // `last_error` passe AVANT le statut terminal : une tâche annulée après avoir
  // échoué reste ce qu'on cherche quand on clique « En échec ». La ranger dans
  // « Terminées » affichait son message d'erreur en rouge sous un compteur
  // « En échec · 0 » — vu à l'écran, et proprement incompréhensible.
  if (t.last_error) return 'echec';
  if (t.status === 'completed' || t.status === 'cancelled' || t.status === 'missed') {
    return 'terminees';
  }
  return 'avenir';
}

function _autoPastille(t) {
  const etat = _autoEtat(t);
  if (etat === 'echec') return ['rouge', 'en échec'];
  if (etat === 'terminees') return ['gris', t.status === 'missed' ? 'manquée' : t.status === 'cancelled' ? 'annulée' : 'terminée'];
  if (t.status === 'paused') return ['ambre', 'en pause'];
  return ['vert', t.schedule_type === 'once' ? 'programmée' : 'récurrente'];
}

function renderActionsTab() {
  const el = document.getElementById('tab-admin-actions');
  if (!el) return;

  if (!document.getElementById('auto-liste')) {
    el.innerHTML = `
      <div class="auto-barre">
        <input type="search" class="champ-recherche" id="auto-q"
               placeholder="Chercher une tâche…" aria-label="Chercher une tâche">
        <div class="segmented" id="auto-vues" role="group" aria-label="État"></div>
      </div>
      <div id="auto-taches">
        <div class="liste-tete auto-tete">
          <span>Tâche</span><span>Prochaine exécution</span>
          <span>Créateur</span><span>État</span>
        </div>
        <div class="liste auto-liste" id="auto-liste"></div>
      </div>
      <div class="page-section" id="auto-permissions"></div>
      <div class="page-section" id="auto-historique"></div>`;
    _cablerAutomatisations(el);
  }

  _lireFiltresAuto();
  poserSommaire('live/automatisations', _AUTO_SECTIONS, '');
  chargerAutomatisations();
  loadActionPermissions();
}

function _cablerAutomatisations(el) {
  const q = el.querySelector('#auto-q');
  q.addEventListener('input', function () {
    _autoFiltres.q = q.value.trim();
    _ecrireFiltresAuto();
    _rendreListeAuto();
  });

  el.querySelector('#auto-vues').addEventListener('click', function (ev) {
    const b = ev.target.closest('[data-vue]');
    if (!b) return;
    _autoFiltres.vue = b.dataset.vue;
    _autoOuverte = null;
    _ecrireFiltresAuto();
    _rendreListeAuto();
  });

  // Délégation, et jamais d'`onclick` interpolé : le titre d'une tâche est
  // dicté par un utilisateur Discord ou Twitch. Ici, l'id ne traverse aucun
  // contexte JavaScript — il vit dans un `data-`, lu comme une chaîne.
  el.querySelector('#auto-liste').addEventListener('click', function (ev) {
    const bouton = ev.target.closest('[data-geste]');
    if (bouton) {
      const id = Number(bouton.dataset.tache);
      const geste = bouton.dataset.geste;
      if (geste === 'pause') actionTaskTogglePause(id, bouton.dataset.pause === '1');
      else if (geste === 'executer') actionTaskExecuteNow(id);
      else if (geste === 'annuler') actionTaskCancel(id);
      return;
    }
    const ligne = ev.target.closest('[data-tache]');
    if (!ligne) return;
    const id = Number(ligne.dataset.tache);
    _autoOuverte = _autoOuverte === id ? null : id;
    _rendreListeAuto();
  });
}

function _lireFiltresAuto() {
  const brut = location.hash.replace(/^#\/?/, '');
  const coupe = brut.indexOf('?');
  if (coupe === -1) { _ecrireFiltresAuto(); return; }
  const p = new URLSearchParams(brut.slice(coupe + 1));
  const vue = p.get('vue') || '';
  _autoFiltres = {
    q: p.get('q') || '',
    vue: _AUTO_VUES.some(function (v) { return v[0] === vue; }) ? vue : 'avenir',
  };
}

function _ecrireFiltresAuto() {
  if (currentRoute !== 'live/automatisations') return;
  const p = new URLSearchParams();
  if (_autoFiltres.q) p.set('q', _autoFiltres.q);
  if (_autoFiltres.vue !== 'avenir') p.set('vue', _autoFiltres.vue);
  const requete = p.toString();
  const vise = '#/live/automatisations' + (requete ? '?' + requete : '');
  if (location.hash !== vise) history.replaceState(null, '', vise);
}

async function chargerAutomatisations() {
  const liste = document.getElementById('auto-liste');
  if (!liste) return;
  liste.innerHTML = '<div class="liste-vide">Chargement…</div>';

  // L'annuaire en parallèle : `creator_id` est un identifiant de plateforme,
  // et « 610550333042589752 » ne dit à personne QUI a demandé la tâche.
  const [r, annuaire] = await Promise.all([
    apiFetch('/api/actions/tasks'),
    annuairePersonnes().catch(function () { return []; }),
  ]);
  if (!r || !r.ok) {
    liste.innerHTML = '<div class="liste-vide">Erreur de chargement.</div>';
    return;
  }
  const noms = {};
  (annuaire || []).forEach(function (p) { noms[p.identity] = p.nom; });

  _autoTaches = ((await r.json()).tasks || []).map(function (t) {
    const identite = (t.creator_platform || '') + ':' + (t.creator_id || '');
    return Object.assign({}, t, { _qui: noms[identite] || t.creator_id || '?' });
  });

  _rendreListeAuto();
  _rendreHistoriqueAuto();
}

function _rendreListeAuto() {
  const liste = document.getElementById('auto-liste');
  const vues = document.getElementById('auto-vues');
  if (!liste || !vues) return;

  const q = _autoFiltres.q.toLowerCase();
  const cherche = function (t) {
    if (!q) return true;
    return ((t.description || '') + ' ' + (t.action_type || '') + ' ' + t._qui)
      .toLowerCase().indexOf(q) !== -1;
  };
  const retenues = _autoTaches.filter(cherche);

  // Les comptes du segmented se lisent APRÈS la recherche : annoncer « À venir
  // · 4 » alors que la recherche n'en laisse qu'une ferait mentir le bouton.
  vues.innerHTML = _AUTO_VUES.map(function (v) {
    const n = retenues.filter(function (t) { return _autoEtat(t) === v[0]; }).length;
    return '<button data-vue="' + v[0] + '"'
      + (v[0] === _autoFiltres.vue ? ' class="active"' : '')
      + '>' + v[1] + ' · ' + n + '</button>';
  }).join('');

  const taches = retenues.filter(function (t) { return _autoEtat(t) === _autoFiltres.vue; });
  if (!taches.length) {
    liste.innerHTML = '<div class="liste-vide">'
      + (q ? 'Aucune tâche ne correspond à cette recherche.'
           : _autoFiltres.vue === 'echec' ? 'Aucune tâche en échec. Tant mieux.'
           : _autoFiltres.vue === 'terminees' ? 'Aucune tâche terminée.'
           : 'Aucune tâche à venir.')
      + '</div>';
    return;
  }

  liste.innerHTML = taches.map(function (t) {
    const etat = _autoEtat(t);
    const pastille = _autoPastille(t);
    const quand = t.next_run_at
      ? new Date(t.next_run_at).toLocaleString('fr-FR',
          { day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit' })
      : '—';
    // Le message d'erreur PREND LA PLACE du sous-titre : c'est la seule chose
    // qu'on veut lire sur une ligne qui a échoué.
    const sous = t.last_error
      ? '<div class="auto-sous echec">' + escHtml(t.last_error) + '</div>'
      : '<div class="auto-sous">' + escHtml(t.action_type || '')
        + ' · ' + (t.schedule_type === 'once' ? 'une fois' : escHtml(t.schedule_type || ''))
        + '</div>';

    let bloc = '<div class="liste-ligne auto-ligne' + (etat === 'echec' ? ' echec' : '')
      + (etat === 'terminees' ? ' terne' : '') + '" data-tache="' + Number(t.id) + '">'
      + '<div><div class="auto-titre">' + escHtml(t.description || 'Sans description')
      + '</div>' + sous + '</div>'
      + '<span class="auto-quand">' + escHtml(quand) + '</span>'
      + '<span class="auto-qui">' + escHtml(t._qui) + '</span>'
      + '<span class="pastille ' + pastille[0] + '">' + pastille[1] + '</span>'
      + '</div>';

    if (_autoOuverte === t.id) {
      const fini = etat === 'terminees';
      bloc += '<div class="auto-detail">'
        + '<div class="auto-detail-info">'
        + 'exécutions ' + Number(t.execution_count || 0)
        + (t.max_executions ? '/' + Number(t.max_executions) : '')
        + ' · échecs consécutifs ' + Number(t.consecutive_failures || 0)
        + ' · créée le ' + escHtml(String(t.created_at || '').slice(0, 16).replace('T', ' '))
        + (t.target_channel ? ' · vers ' + escHtml(t.target_channel) : '')
        + '</div>'
        + (fini ? '' :
            '<button class="btn" data-geste="pause" data-tache="' + Number(t.id)
            + '" data-pause="' + (t.status === 'paused' ? '1' : '0') + '">'
            + (t.status === 'paused' ? 'Reprendre' : 'Mettre en pause') + '</button>'
          + '<button class="btn" data-geste="executer" data-tache="' + Number(t.id)
            + '">Exécuter maintenant</button>'
          + '<button class="btn" data-geste="annuler" data-tache="' + Number(t.id)
            + '">Annuler</button>')
        + '</div>';
    }
    return bloc;
  }).join('');
}

/** Ce qui a TOURNÉ récemment, tous statuts confondus.
 *
 *  Différent du tableau, qui range par état : une tâche récurrente saine n'y
 *  apparaît jamais comme « ayant tourné », alors que c'est elle qui tourne le
 *  plus. Il n'existe pas de table d'historique d'exécution — `last_run_at` et
 *  `execution_count` de chaque tâche sont ce qu'on a, et ils suffisent.
 */
function _rendreHistoriqueAuto() {
  const boite = document.getElementById('auto-historique');
  if (!boite) return;
  const passees = _autoTaches
    .filter(function (t) { return t.last_run_at; })
    .sort(function (a, b) { return String(b.last_run_at).localeCompare(String(a.last_run_at)); })
    .slice(0, 12);

  boite.innerHTML = '<div class="page-section-titre">Historique d\'exécution</div>'
    + '<div class="page-section-sous">'
    + (passees.length ? 'Les douze dernières tâches à avoir tourné.'
                      : 'Aucune tâche n\'a encore tourné.')
    + '</div>'
    + (passees.length ? '<div class="liste">' + passees.map(function (t) {
        const quand = new Date(t.last_run_at).toLocaleString('fr-FR',
          { day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit' });
        return '<div class="liste-ligne auto-ligne' + (t.last_error ? ' echec' : '') + '">'
          + '<div class="auto-titre">' + escHtml(t.description || 'Sans description') + '</div>'
          + '<span class="auto-quand">' + escHtml(quand) + '</span>'
          + '<span class="auto-qui">' + escHtml(t._qui) + '</span>'
          + '<span class="auto-qui">' + Number(t.execution_count || 0) + '×</span>'
          + '</div>';
      }).join('') + '</div>' : '');
}

async function actionTaskTogglePause(id, isPaused) {
  var endpoint = isPaused ? 'resume' : 'pause';
  var r = await apiFetch('/api/actions/tasks/' + id + '/' + endpoint, { method: 'POST' });
  if (!r || !r.ok) { toast('Erreur ' + endpoint, 'error'); return; }
  toast(isPaused ? 'Tâche reprise' : 'Tâche en pause', 'success');
  chargerAutomatisations();
}

async function actionTaskExecuteNow(id) {
  var r = await apiFetch('/api/actions/tasks/' + id + '/execute', { method: 'POST' });
  if (!r || !r.ok) { toast('Erreur exécution', 'error'); return; }
  toast('Exécution lancée', 'success');
  chargerAutomatisations();
}

async function actionTaskCancel(id) {
  if (!confirm('Annuler cette tâche ?')) return;
  var r = await apiFetch('/api/actions/tasks/' + id + '/cancel', { method: 'POST' });
  if (!r || !r.ok) { toast('Erreur annulation', 'error'); return; }
  toast('Tâche annulée', 'success');
  chargerAutomatisations();
}

var TWITCH_ROLES = ['everyone', 'subscriber', 'vip', 'moderator', 'admin'];
var _discordGuildRoles = []; // [{id, name, roles: [{id, name, color}]}]

async function loadDiscordRoles() {
  var r = await apiFetch('/api/actions/discord-roles');
  if (!r || !r.ok) return;
  var data = await r.json();
  _discordGuildRoles = data.guilds || [];
}

function _buildPermRow(p) {
  var actionType = p.action_type;
  var enabled = p.enabled !== false && p.enabled !== 0;
  var discordRoles = p.discord_roles || {};

  var container = document.createElement('div');
  container.className = 'action-perm-row';

  // ── Header: name + enabled + twitch ──
  var header = document.createElement('div');
  header.className = 'action-perm-header';

  var nameSpan = document.createElement('span');
  nameSpan.className = 'action-perm-name';
  nameSpan.textContent = actionType;
  header.appendChild(nameSpan);

  // Enabled toggle
  var toggleLabel = document.createElement('label');
  toggleLabel.className = 'action-toggle';
  var checkbox = document.createElement('input');
  checkbox.type = 'checkbox';
  checkbox.checked = enabled;
  checkbox.addEventListener('change', function() { updateActionPerm(actionType, 'enabled', this.checked); });
  var trackSpan = document.createElement('span');
  trackSpan.className = 'action-toggle-track';
  var thumbSpan = document.createElement('span');
  thumbSpan.className = 'action-toggle-thumb';
  trackSpan.appendChild(thumbSpan);
  toggleLabel.appendChild(checkbox);
  toggleLabel.appendChild(trackSpan);
  header.appendChild(toggleLabel);

  // Twitch dropdown
  var twitchWrap = document.createElement('div');
  twitchWrap.className = 'action-perm-twitch';
  var twitchLabel = document.createElement('span');
  twitchLabel.className = 'action-perm-platform-label';
  twitchLabel.textContent = 'Twitch';
  twitchWrap.appendChild(twitchLabel);
  var twitchSelect = document.createElement('select');
  twitchSelect.className = 'neo-select action-perm-select';
  TWITCH_ROLES.forEach(function(role) {
    var opt = document.createElement('option');
    opt.value = role;
    opt.textContent = role;
    if (p.min_role_twitch === role) opt.selected = true;
    twitchSelect.appendChild(opt);
  });
  twitchSelect.addEventListener('change', function() { updateActionPerm(actionType, 'min_role_twitch', this.value); });
  twitchWrap.appendChild(twitchSelect);
  header.appendChild(twitchWrap);

  container.appendChild(header);

  // ── Discord guilds section ──
  _discordGuildRoles.forEach(function(guild) {
    var guildSection = document.createElement('div');
    guildSection.className = 'action-perm-guild';

    var guildLabel = document.createElement('div');
    guildLabel.className = 'action-perm-guild-label';
    guildLabel.textContent = guild.name;
    guildSection.appendChild(guildLabel);

    var selectedRoles = (discordRoles[guild.id] || []).map(function(r) { return r.role_id; });

    var chipsDiv = document.createElement('div');
    chipsDiv.className = 'action-role-chips';

    var addSelect = document.createElement('select');
    addSelect.className = 'neo-select action-perm-add-role';

    function renderChips() {
      chipsDiv.textContent = '';
      selectedRoles.forEach(function(rid) {
        var roleInfo = guild.roles.find(function(r) { return r.id === rid; });
        if (!roleInfo) return;
        var chip = document.createElement('span');
        chip.className = 'action-role-chip';
        var dot = document.createElement('span');
        dot.className = 'action-role-dot';
        dot.style.backgroundColor = roleInfo.color;
        chip.appendChild(dot);
        chip.appendChild(document.createTextNode(roleInfo.name));
        var removeBtn = document.createElement('button');
        removeBtn.className = 'action-role-chip-remove';
        removeBtn.textContent = '\u00d7';
        removeBtn.addEventListener('click', function() {
          selectedRoles = selectedRoles.filter(function(r) { return r !== rid; });
          saveDiscordPerm(actionType, guild.id, selectedRoles);
          renderChips();
          renderDropdown();
        });
        chip.appendChild(removeBtn);
        chipsDiv.appendChild(chip);
      });
    }

    function renderDropdown() {
      addSelect.textContent = '';
      var placeholder = document.createElement('option');
      placeholder.value = '';
      placeholder.textContent = '+ Ajouter un r\u00f4le';
      placeholder.disabled = true;
      placeholder.selected = true;
      addSelect.appendChild(placeholder);
      guild.roles.forEach(function(role) {
        if (selectedRoles.indexOf(role.id) !== -1) return;
        var opt = document.createElement('option');
        opt.value = role.id;
        opt.textContent = role.name;
        addSelect.appendChild(opt);
      });
    }

    addSelect.addEventListener('change', function() {
      if (!this.value) return;
      selectedRoles.push(this.value);
      saveDiscordPerm(actionType, guild.id, selectedRoles);
      renderChips();
      renderDropdown();
    });

    renderChips();
    renderDropdown();

    guildSection.appendChild(chipsDiv);
    guildSection.appendChild(addSelect);
    container.appendChild(guildSection);
  });

  return container;
}

async function saveDiscordPerm(actionType, guildId, roleIds) {
  var r = await apiFetch('/api/actions/permissions/' + encodeURIComponent(actionType) + '/discord', {
    method: 'PUT',
    body: JSON.stringify({ guild_id: guildId, role_ids: roleIds }),
  });
  if (!r || !r.ok) { toast('Erreur mise \u00e0 jour permission Discord', 'error'); return; }
  toast('Permission Discord mise \u00e0 jour', 'success');
}

async function loadActionPermissions() {
  var section = document.getElementById('auto-permissions');
  if (!section) return;

  // Le TITRE est écrit une fois et ne bouge plus ; seul le corps se recharge.
  // Le vider avec le reste emportait l'en-tête que le sommaire d'ancres vise,
  // et l'ancre menait alors à un bloc anonyme.
  var container = document.getElementById('auto-permissions-corps');
  if (!container) {
    section.innerHTML = '<div class="page-section-titre">Qui peut demander quoi</div>'
      + '<div class="page-section-sous">Le rôle minimum requis pour demander '
      + 'chaque type de tâche à Wally, par plateforme.</div>'
      + '<div id="auto-permissions-corps"></div>';
    container = document.getElementById('auto-permissions-corps');
  }
  container.textContent = '';
  var loading = document.createElement('div');
  loading.style.cssText = 'color:var(--text-muted);text-align:center;padding:32px';
  loading.textContent = 'Chargement...';
  container.appendChild(loading);

  await loadDiscordRoles();
  var r = await apiFetch('/api/actions/permissions');
  if (!r || !r.ok) {
    loading.textContent = 'Erreur de chargement';
    return;
  }
  var data = await r.json();
  var perms = data.permissions || [];

  container.textContent = '';

  if (perms.length === 0) {
    var empty = document.createElement('div');
    empty.style.cssText = 'color:var(--text-muted);text-align:center;padding:32px';
    empty.textContent = 'Aucune permission configur\u00e9e';
    container.appendChild(empty);
    return;
  }

  var list = document.createElement('div');
  list.className = 'action-perms-list';
  perms.forEach(function(p) {
    list.appendChild(_buildPermRow(p));
  });
  container.appendChild(list);
}

async function updateActionPerm(actionType, field, value) {
  var body = {};
  body[field] = value;
  var r = await apiFetch('/api/actions/permissions/' + encodeURIComponent(actionType), {
    method: 'PUT',
    body: JSON.stringify(body),
  });
  if (!r || !r.ok) { toast('Erreur mise \u00e0 jour permission', 'error'); return; }
  toast('Permission mise \u00e0 jour', 'success');
}


// Les trois fonctions de gestion des liens d'invitation ont été retirées :
// elles appelaient `loadInvites()`, qui n'existe nulle part. `generateInvite`
// créait bien le lien puis basculait dans son `catch` sur la ReferenceError et
// affichait « Erreur : loadInvites is not defined » — un faux échec ;
// `revokeInvite` levait sans être rattrapée. Aucune des trois n'était câblée à
// l'UI (aucun `onclick`, aucun listener), donc sans effet aujourd'hui — mais le
// piège se serait refermé au moment de rebrancher le bouton.

// ── Prompts & Persona Management ─────────────────────────────────────────────

var _promptsData = null;        // { persona: {}, system_prompts: {} }
var _promptsSection = 'persona'; // 'persona' | 'system'
var _promptsFile = null;

let _promptsCible = null;

async function renderPromptsTab(cible) {
  // La cible est passée par « Personnalité », qui héberge l'éditeur en section.
  // Elle est MÉMORISÉE : `selectPromptFile` et `switchPromptsSection` re-rendent
  // l'éditeur, et cherchaient jusqu'ici un `#tab-admin-prompts` qui n'existe
  // plus depuis que l'onglet Prompts a été absorbé. Un clic sur un fichier
  // n'aurait rien fait, en silence.
  var el = cible || _promptsCible;
  if (!el) return;
  _promptsCible = el;
  el.innerHTML = '<div style="padding:24px;color:var(--text-muted)">Chargement...</div>';

  await _loadPromptsModels();

  await _loadPromptsData();
  _renderPromptsUI(el);
}

async function _loadPromptsData() {
  var r = await apiFetch('/api/admin/prompts');
  _promptsData = (r && r.ok) ? await r.json() : { persona: {}, system_prompts: {} };
  var files = _promptsSection === 'persona'
    ? Object.keys(_promptsData.persona)
    : Object.keys(_promptsData.system_prompts);
  if (!_promptsFile || !files.includes(_promptsFile)) {
    _promptsFile = files[0] || null;
  }
}

function _renderPromptsUI(el) {
  var personaFiles = Object.keys(_promptsData.persona);
  var systemFiles = Object.keys(_promptsData.system_prompts);
  var currentFiles = _promptsSection === 'persona' ? personaFiles : systemFiles;
  var content = _promptsFile
    ? (_promptsSection === 'persona' ? _promptsData.persona[_promptsFile] : _promptsData.system_prompts[_promptsFile])
    : '';

  // Liste de fichiers
  var fileList = currentFiles.map(function(f) {
    return '<div class="prompt-file-item' + (f === _promptsFile ? ' active' : '') + '" onclick="selectPromptFile(\'' + f + '\')">' + f.replace('.md','') + '</div>';
  }).join('');

  el.innerHTML = `
    <div style="display:flex;flex-direction:column;height:100%;gap:0">
      <!-- Toolbar -->
      <div style="display:flex;align-items:center;gap:12px;padding:16px 20px;border-bottom:1px solid var(--border);flex-wrap:wrap">
        <div class="card-title" style="margin:0;flex:0 0 auto">PROMPTS</div>
        <div class="mem-subnav" style="margin-bottom:0;margin-left:auto">
          <button class="mem-subnav-pill ${_promptsSection==='persona'?'active':''}" onclick="switchPromptsSection('persona')">Persona</button>
          <button class="mem-subnav-pill ${_promptsSection==='system'?'active':''}" onclick="switchPromptsSection('system')">Système</button>
        </div>
      </div>
      <!-- Body -->
      <div style="display:flex;flex:1;min-height:0;overflow:hidden">
        <!-- File list -->
        <div style="width:190px;flex-shrink:0;border-right:1px solid var(--border);overflow-y:auto;padding:8px">
          ${fileList || '<div style="padding:12px;font-size:12px;color:var(--text-muted)">Aucun fichier</div>'}
        </div>
        <!-- Editor -->
        <div style="flex:1;display:flex;flex-direction:column;min-width:0;padding:12px 16px;gap:8px">
          ${_promptsFile ? `
            <div style="display:flex;align-items:center;justify-content:space-between;flex-shrink:0">
              <span style="font-size:13px;font-weight:600;color:var(--text-secondary)">${_promptsFile}</span>
              <button class="btn-primary" onclick="savePromptFile()" style="font-size:12px;padding:6px 14px">💾 Sauvegarder</button>
            </div>
            <textarea id="prompt-editor" style="flex:1;background:var(--bg-canvas);border:1px solid var(--border);border-radius:10px;color:var(--text-primary);padding:14px;font-size:13px;font-family:monospace;resize:vertical;line-height:1.6;outline:none;min-height:calc(100vh - 310px);width:100%;box-sizing:border-box" spellcheck="false">${escapeHtml(content)}</textarea>
            <div style="display:flex;align-items:center;justify-content:space-between;flex-shrink:0;min-height:22px">
              <div id="prompt-token-info" style="display:flex;gap:16px;font-size:11px;color:var(--text-muted)"></div>
              <div id="prompt-save-status" style="font-size:12px"></div>
            </div>
          ` : '<div style="color:var(--text-muted);font-size:13px;padding-top:40px;text-align:center">Sélectionne un fichier</div>'}
        </div>
      </div>
    </div>`;

  // Compteur de tokens live
  var editor = document.getElementById('prompt-editor');
  if (editor) {
    _updatePromptTokenInfo(editor.value);
    editor.addEventListener('input', function() { _updatePromptTokenInfo(editor.value); });
  }

  // Styles inline pour les items de fichier
  document.querySelectorAll('.prompt-file-item').forEach(function(item) {
    item.style.cssText = 'padding:8px 12px;border-radius:8px;font-size:12px;cursor:pointer;color:var(--text-secondary);transition:all .15s;margin-bottom:2px';
    if (item.classList.contains('active')) {
      item.style.background = 'rgba(6,182,212,0.15)';
      item.style.color = 'rgb(6,182,212)';
      item.style.borderLeft = '2px solid rgb(6,182,212)';
    }
    item.addEventListener('mouseenter', function() {
      if (!item.classList.contains('active')) item.style.background = 'var(--bg-surface)';
    });
    item.addEventListener('mouseleave', function() {
      if (!item.classList.contains('active')) item.style.background = '';
    });
  });
}

function escapeHtml(s) {
  return (s || '').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
}

// Prix input par 1M tokens (source : pages tarifaires officielles)
var _MODEL_PRICE_TABLE = {
  // OpenAI
  'gpt-4o':              2.50,
  'gpt-4o-mini':         0.15,
  'gpt-4.1':             2.00,
  'gpt-4.1-mini':        0.40,
  'gpt-4.1-nano':        0.10,
  // Famille GPT-5 — prix d'ENTRÉE relevés le 2026-08-25 sur
  // https://developers.openai.com/api/docs/pricing. Ils étaient tous faux :
  // `gpt-5` porté à 5,00 au lieu de 1,25, `gpt-5-nano` au double du réel, et
  // `gpt-5.1-mini` n'existe pas au catalogue. Les familles 4o / 4.1 / o* plus
  // haut n'ont PAS été revérifiées à cette date — elles restent en l'état.
  'gpt-5':               1.25,
  'gpt-5-mini':          0.25,
  'gpt-5-nano':          0.05,
  'gpt-5-pro':          15.00,
  'gpt-5.1':             1.25,
  'gpt-5.2':             1.75,
  'gpt-5.3':             1.75,
  'gpt-5.4':             2.50,
  'gpt-5.4-mini':        0.75,
  'gpt-5.4-nano':        0.20,
  'gpt-5.4-pro':        30.00,
  'gpt-5.5':             5.00,
  'gpt-5.6-luna':        0.20,
  'gpt-5.6-terra':       2.00,
  'gpt-5.6-sol':         4.00,
  'o1':                 15.00,
  'o1-mini':             3.00,
  'o3':                 10.00,
  'o3-mini':             1.10,
  'o4-mini':             1.10,
  // Anthropic
  'claude-opus-4':      15.00,
  'claude-opus-4-5':    15.00,
  'claude-opus-4-6':    15.00,
  'claude-sonnet-4':     3.00,
  'claude-sonnet-4-5':   3.00,
  'claude-sonnet-4-6':   3.00,
  'claude-haiku-4':      0.80,
  'claude-haiku-4-5':    1.00,   // 0,80 était le tarif de Haiku 3.5, pas du 4.5
  // DeepSeek — input cache MISS en heures CREUSES, par 1M
  // (https://api-docs.deepseek.com/quick_start/pricing/, relevé le 2026-08-25).
  // La table portait encore 0,14 et 0,435 : la grille d'AVANT la hausse du
  // 2026-08-16, soit un affichage à la moitié du prix réellement facturé. Les
  // heures pleines (01–04 h et 06–10 h UTC, du lundi au vendredi) doublent
  // encore ces valeurs — le panneau annonce donc un plancher, pas une facture.
  'deepseek-v4-pro':     0.66,
  'deepseek-v4-flash':   0.22,
  'deepseek-chat':       0.22,
  'deepseek-reasoner':   0.22,
};

var _promptsModels = []; // [{ label, usd }] — peuplé depuis la config

function _priceForModel(modelId) {
  if (!modelId) return null;
  var m = modelId.toLowerCase();
  // Correspondance exacte d'abord
  if (_MODEL_PRICE_TABLE[m] !== undefined) return _MODEL_PRICE_TABLE[m];
  // Correspondance partielle (préfixe le plus long)
  var best = null, bestLen = 0;
  Object.keys(_MODEL_PRICE_TABLE).forEach(function(k) {
    if (m.startsWith(k) && k.length > bestLen) { best = _MODEL_PRICE_TABLE[k]; bestLen = k.length; }
  });
  return best;
}

async function _loadPromptsModels() {
  var r = await apiFetch('/api/admin/config');
  if (!r || !r.ok) return;
  var cfg = await r.json();
  var seen = {};
  _promptsModels = [];
  [cfg.llm && cfg.llm.primary, cfg.llm && cfg.llm.secondary].forEach(function(role, i) {
    if (!role || !role.model) return;
    var key = role.model;
    if (seen[key]) return;
    seen[key] = true;
    var price = _priceForModel(role.model);
    var label = (i === 0 ? 'primary' : 'secondary') + ' (' + role.model + ')';
    _promptsModels.push({ label: label, model: role.model, usd: price });
  });
}

function _updatePromptTokenInfo(text) {
  var el = document.getElementById('prompt-token-info');
  if (!el) return;
  var tokens = Math.round((text || '').length / 4);
  var parts = ['<span>' + tokens.toLocaleString() + ' tokens</span>'];
  _promptsModels.forEach(function(p) {
    var costStr;
    if (p.usd === null) {
      costStr = '<strong style="color:var(--text-muted)">prix inconnu</strong>';
    } else {
      var cost = (tokens / 1_000_000) * p.usd;
      var costFmt = cost < 0.0001 ? ('< $0.0001') : ('$' + cost.toFixed(4));
      costStr = '<strong style="color:var(--text-secondary)">' + costFmt + '</strong>';
    }
    parts.push('<span>' + p.label + ' : ' + costStr + '/appel</span>');
  });
  el.innerHTML = parts.join('<span style="opacity:.3"> | </span>');
}

function selectPromptFile(filename) {
  _promptsFile = filename;
  _renderPromptsUI(_promptsCible);
}

async function switchPromptsSection(section) {
  _promptsSection = section;
  _promptsFile = null;
  _renderPromptsUI(_promptsCible);
}

async function savePromptFile() {
  var editor = document.getElementById('prompt-editor');
  var status = document.getElementById('prompt-save-status');
  if (!editor || !_promptsFile) return;
  var content = editor.value;
  status.textContent = 'Sauvegarde...';
  status.style.color = 'rgba(255,255,255,0.4)';

  var type = _promptsSection === 'persona' ? 'persona' : 'system';
  var url = '/api/admin/prompts/' + type + '/' + _promptsFile;
  var r = await apiFetch(url, { method: 'POST', headers: {'Content-Type':'application/json'}, body: JSON.stringify({ content }) });
  if (r && r.ok) {
    // Mettre à jour le cache local
    if (_promptsSection === 'persona') _promptsData.persona[_promptsFile] = content;
    else _promptsData.system_prompts[_promptsFile] = content;
    status.textContent = '✓ Sauvegardé';
    status.style.color = 'rgb(34,197,94)';
    setTimeout(function() { if (status) status.textContent = ''; }, 3000);
  } else {
    status.textContent = '✗ Erreur lors de la sauvegarde';
    status.style.color = 'rgb(239,68,68)';
  }
}

// ── Live › Memes ─────────────────────────────────────────────────────────────
//
// La banque d'images que Wally sort sur le live. Une PAGE et non une section :
// elle porte 173 vignettes, et une galerie de cette taille noyait le reste de
// « Médias & sons » — l'atelier des sons, sous elle, devenait inatteignable.
//
// Le dossier `data/memes` est la seule source de vérité : il est relu à chaque
// tirage côté bot, et le rotateur de l'overlay recharge sa liste à chaque
// cycle. Un dépôt, une description ou un retrait prennent donc effet SANS
// redémarrage et sans recharger l'overlay ; rien ici n'a à les prévenir.
//
// Wally ne VOIT pas ces images : la description est sa seule prise dessus.
// C'est elle qui lui fait choisir un meme à propos plutôt qu'au hasard — d'où
// cette page, et d'où le filtre « sans description ».

const _MEMES_SECTIONS = [
  ['memes-ajout', 'Ajouter'],
  ['memes-galerie', 'Galerie'],
];

// La liste chargée. Les deux filtres travaillent dessus, sans rappeler le
// serveur : le dossier tient dans une réponse, et un aller-retour par frappe
// rendrait la recherche saccadée.
let _memes = [];
let _memesVus = [];
let _memeFiltre = '';
let _memeMuetsSeuls = false;
let _memeMax = { octets: 0, description: 0 };
// L'index DANS `_memesVus` du meme ouvert, ou -1. C'est lui qui permet les
// flèches ← → de la fiche : décrire en série est le geste principal ici, et
// refermer la fiche entre chaque meme le rendrait pénible.
let _memeOuvert = -1;
// La veille du dossier, et les noms arrivés depuis le dernier rendu.
let _memesVeille = null;
let _memesNeufs = [];

function renderMemes() {
  const el = document.getElementById('tab-admin-memes');
  if (!el) return;
  if (!document.getElementById('memes-galerie')) {
    el.innerHTML = `
      <div class="page-section" id="memes-ajout">
        <div class="page-section-titre">Ajouter</div>
        <p class="muted" style="margin-top:0">
          Wally ne VOIT pas ces images : la description est sa seule prise
          dessus — c'est elle qui lui fait sortir celui qui tombe juste plutôt
          qu'un au hasard. Cliquez une vignette pour la décrire ou la retirer.
          Tout est pris en compte aussitôt, sans redémarrage.
        </p>
        <div class="meme-barre">
          <input type="file" id="meme-fichier" multiple
                 accept=".png,.jpg,.jpeg,.gif,.webp,.mp4,.webm">
          <button class="btn" onclick="deposerMemes()">Déposer</button>
          <span id="memes-etat" class="muted"></span>
        </div>
      </div>
      <div class="page-section" id="memes-galerie">
        <div class="page-section-titre">Galerie</div>
        <div class="meme-barre">
          <input type="text" id="meme-recherche" placeholder="Chercher un meme…">
          <label class="muted" style="display:flex;align-items:center;gap:6px">
            <input type="checkbox" id="meme-muets"> Sans description
          </label>
          <span id="memes-compte" class="muted"></span>
        </div>
        <div id="memes-neufs" class="meme-annonce" hidden></div>
        <div id="meme-grille" class="meme-grille"></div>
      </div>`;
    _cablerPageMemes(el);
  }
  chargerMemes();
}

async function chargerMemes() {
  const grille = document.getElementById('meme-grille');
  if (!grille) return;
  let data = null;
  try {
    const r = await apiFetch('/api/admin/overlay/memes');
    if (r && r.ok) data = await r.json();
  } catch (e) {
    // Réseau coupé : on le DIT. Une grille vide se lit comme « aucun meme ».
  }
  if (!data) {
    grille.innerHTML = '<div class="muted">Galerie indisponible — le bot ne répond pas.</div>';
    poserSommaire('live/memes', _MEMES_SECTIONS, '');
    return;
  }
  const connus = new Set(_memes.map((m) => m.nom));
  _memes = data.memes || [];
  _memeMax = { octets: data.max_octets || 0, description: data.max_description || 0 };
  // Au PREMIER chargement, tout est nouveau et rien ne l'est : `connus` est
  // vide, et annoncer « 168 nouveaux memes » à l'ouverture de la page serait
  // absurde.
  if (connus.size) {
    _memesNeufs = _memes.filter((m) => !connus.has(m.nom)).map((m) => m.nom);
  }
  _rendreGalerieMemes();
  return true;
}

/** Le dossier change SANS passer par cette page : clic droit Discord,
 *  `/importer-memes`, boîte aux lettres. Sans veille, la galerie reste sur son
 *  état d'ouverture et il faut recharger — or on garde justement cet écran
 *  ouvert pendant qu'on poste des memes ailleurs.
 *
 *  Un sondage et non un SSE : un meme arrive quelques fois par jour, et un flux
 *  demanderait une route de plus PLUS un événement publié depuis les quatre
 *  chemins d'import — dont trois vivent loin d'ici. La réponse fait 30 Ko, elle
 *  n'est demandée que sur cette page, onglet au premier plan.
 */
function startMemesVeille() {
  stopMemesVeille();
  _memesVeille = setInterval(function () {
    // Onglet en arrière-plan : personne ne regarde, et Chrome ramène de toute
    // façon les timers d'un onglet caché à un par minute.
    if (document.hidden) return;
    // Fiche ouverte : on est en train de décrire. Redessiner la galerie
    // déplacerait le rang du meme sous les doigts, et « Suivant → » sauterait
    // sur un autre.
    if (_memeOuvert >= 0) return;
    chargerMemes();
  }, 15000);
}

function stopMemesVeille() {
  if (_memesVeille) { clearInterval(_memesVeille); _memesVeille = null; }
}

/** La grille et les compteurs. Séparée du montage : filtrer ne doit pas
 *  réécrire les champs de saisie, sinon le curseur repart au début de la
 *  recherche à chaque frappe. */
function _rendreGalerieMemes() {
  const grille = document.getElementById('meme-grille');
  if (!grille) return;
  const q = _memeFiltre.trim().toLowerCase();
  _memesVus = _memes.filter(function (m) {
    if (_memeMuetsSeuls && m.description) return false;
    if (!q) return true;
    return (m.nom + ' ' + (m.description || '')).toLowerCase().includes(q);
  });

  const muets = _memes.filter((m) => !m.description).length;
  const compte = document.getElementById('memes-compte');
  if (compte) {
    compte.textContent = _memesVus.length === _memes.length
      ? _memes.length + ' memes'
      : _memesVus.length + ' sur ' + _memes.length;
  }
  // L'encart du sommaire porte le seul chiffre qui appelle une action : les
  // memes que Wally ne sait pas nommer. Il ne les trouve pas par `pick(hint)`
  // et les commente à l'aveugle quand le tirage les sort.
  poserSommaire('live/memes', _MEMES_SECTIONS, muets
    ? '<div class="rail-encart alerte">'
      + '<div class="rail-encart-titre">Sans description</div>'
      + '<div class="rail-encart-ligne">' + muets + ' meme' + (muets > 1 ? 's' : '')
      + ' que Wally ne sait pas nommer</div>'
      + '<div class="rail-encart-meta">Il ne peut ni les choisir à propos, '
      + 'ni les commenter autrement qu\'à l\'aveugle.</div></div>'
    : '<div class="rail-encart">'
      + '<div class="rail-encart-titre">Descriptions</div>'
      + '<div class="rail-encart-ligne">Les ' + _memes.length + ' memes sont décrits.</div>'
      + '</div>');

  // Les nouveaux arrivent en FIN de galerie (le tri suit les numéros) : sans
  // cette ligne, un meme posté depuis Discord apparaît 168 cases plus bas et
  // personne ne le voit. Le bouton mène au geste qui suit — le décrire.
  const annonce = document.getElementById('memes-neufs');
  if (annonce) {
    annonce.innerHTML = _memesNeufs.length
      ? '<span>' + _memesNeufs.length + ' nouveau'
        + (_memesNeufs.length > 1 ? 'x memes' : ' meme') + ' dans le dossier.</span>'
        + '<button class="btn" data-neufs="1">Le décrire</button>'
      : '';
    annonce.hidden = !_memesNeufs.length;
  }

  if (!_memesVus.length) {
    grille.innerHTML = '<div class="muted">'
      + (_memes.length ? 'Aucun meme ne correspond.'
                       : 'Aucun meme. Déposez une image pour commencer.')
      + '</div>';
    return;
  }
  grille.innerHTML = _memesVus.map(function (m, i) {
    return '<button class="meme-case' + (m.description ? '' : ' muet')
      + '" data-rang="' + i + '" title="' + escAttr(m.lue || m.nom) + '">'
      + _apercuMeme(m, 'meme-vignette')
      + (m.genre === 'video' ? '<span class="meme-tag">vidéo</span>' : '')
      + (m.description ? '' : '<span class="meme-tag meme-tag-muet">à décrire</span>')
      + '</button>';
  }).join('');
}

/** L'aperçu d'un meme. Une vidéo n'est pas JOUÉE : `preload="metadata"` suffit
 *  à en montrer la première image, et cent lectures simultanées feraient ramer
 *  la page. */
function _apercuMeme(m, classe) {
  const url = '/api/public/meme/' + encodeURIComponent(m.nom);
  return m.genre === 'video'
    ? '<video class="' + classe + '" src="' + escAttr(url) + '" preload="metadata" muted></video>'
    : '<img class="' + classe + '" src="' + escAttr(url) + '" alt="" loading="lazy">';
}

/** Un seul écouteur pour toute la page, posé une fois.
 *
 *  Surtout pas d'`onclick="...('${nom}')"` : `escHtml` n'échappe PAS
 *  l'apostrophe, et le nom vient d'un nom de FICHIER que l'owner dépose
 *  lui-même. Un `x');alert(1);a.webp` s'exécuterait au rendu — le piège a déjà
 *  été payé sur les sons. Le RANG voyage donc dans un attribut `data-`, et le
 *  nom ne quitte jamais le tableau JavaScript où il est arrivé.
 */
function _cablerPageMemes(el) {
  el.addEventListener('click', function (ev) {
    const case_ = ev.target.closest('.meme-case');
    if (case_) { ouvrirMeme(Number(case_.dataset.rang)); return; }
    if (ev.target.closest('[data-neufs]')) { ouvrirPremierNeuf(); return; }
    const bouton = ev.target.closest('[data-fiche]');
    if (!bouton) return;
    const quoi = bouton.dataset.fiche;
    if (quoi === 'fermer') fermerMeme();
    else if (quoi === 'precedent') ouvrirMeme(_memeOuvert - 1);
    else if (quoi === 'suivant') ouvrirMeme(_memeOuvert + 1);
    else if (quoi === 'enregistrer') enregistrerMeme();
    else if (quoi === 'supprimer') supprimerMeme();
  });
  el.addEventListener('input', function (ev) {
    if (ev.target.id !== 'meme-recherche') return;
    _memeFiltre = ev.target.value;
    _rendreGalerieMemes();
  });
  el.addEventListener('change', function (ev) {
    if (ev.target.id !== 'meme-muets') return;
    _memeMuetsSeuls = ev.target.checked;
    _rendreGalerieMemes();
  });
  // Échap ferme, les flèches passent au meme suivant. Posé sur le DOCUMENT :
  // la fiche est un enfant de la page, mais le focus vit dans le textarea, et
  // un écouteur sur la page ne verrait pas Échap une fois la souris ailleurs.
  document.addEventListener('keydown', function (ev) {
    if (_memeOuvert < 0) return;
    if (ev.key === 'Escape') { fermerMeme(); return; }
    // Les flèches appartiennent au champ tant qu'on y écrit : déplacer le
    // curseur dans une description ne doit pas changer de meme.
    if (ev.target && ev.target.tagName === 'TEXTAREA') return;
    if (ev.key === 'ArrowLeft') ouvrirMeme(_memeOuvert - 1);
    else if (ev.key === 'ArrowRight') ouvrirMeme(_memeOuvert + 1);
  });
}

/** Ouvre le premier meme arrivé depuis le dernier coup d'œil.
 *
 *  Il faut le RETROUVER dans la liste affichée : un filtre actif peut l'en
 *  avoir exclu, et ouvrir un rang calculé sur une autre liste montrerait un
 *  autre meme.
 */
function ouvrirPremierNeuf() {
  for (const nom of _memesNeufs) {
    const rang = _memesVus.findIndex((m) => m.nom === nom);
    if (rang >= 0) { _memesNeufs = []; _rendreGalerieMemes(); ouvrirMeme(rang); return; }
  }
  // Tous filtrés : le dire vaut mieux qu'un bouton qui ne fait rien.
  _etatMemes('Les nouveaux memes sont masqués par le filtre en cours.');
}

function _etatMemes(texte) {
  const el = document.getElementById('memes-etat');
  if (el) el.textContent = texte;
}

// ── La fiche d'un meme ───────────────────────────────────────────────────────

/** Ouvre la fiche sur le meme de rang `i` dans la liste AFFICHÉE.
 *
 *  Le rang et non le nom : les flèches ← → suivent l'ordre de la galerie
 *  filtrée, qui est celui qu'on a sous les yeux. Filtrer sur « sans
 *  description » puis enchaîner les flèches, c'est décrire toute la pile sans
 *  jamais refermer la fiche.
 */
function ouvrirMeme(i) {
  if (i < 0 || i >= _memesVus.length) return;
  _memeOuvert = i;
  const m = _memesVus[i];
  let fiche = document.getElementById('meme-fiche');
  if (!fiche) {
    fiche = document.createElement('div');
    fiche.id = 'meme-fiche';
    fiche.className = 'modal-overlay visible';
    fiche.setAttribute('role', 'dialog');
    fiche.setAttribute('aria-modal', 'true');
    document.getElementById('tab-admin-memes').appendChild(fiche);
  }
  fiche.innerHTML = `
    <div class="modal meme-fiche-boite">
      <div class="meme-fiche-scene">
        ${_apercuMeme(m, 'meme-fiche-media')}
      </div>
      <div class="meme-fiche-corps">
        <div class="meme-fiche-tete">
          <div>
            <div class="card-title" style="margin:0">${escHtml(m.nom)}</div>
            <div class="muted" style="font-size:12px">
              ${m.genre === 'video' ? 'vidéo · ' : ''}${_octetsLisibles(m.taille || 0)}
              · ${i + 1} sur ${_memesVus.length}
              ${m.montrable ? '' : '<br>Wally ne peut pas la montrer : il affiche dans une image, pas un lecteur vidéo. Le rotateur, lui, la joue.'}
            </div>
          </div>
          <button class="btn" data-fiche="fermer" aria-label="Fermer">✕</button>
        </div>
        <label class="muted" for="meme-fiche-desc">
          Description — ce que Wally lit pour choisir ce meme
        </label>
        <textarea id="meme-fiche-desc" rows="4"
                  maxlength="${_memeMax.description || 160}"
                  placeholder="${escAttr(m.lue || '')}">${escHtml(m.description || '')}</textarea>
        <div class="muted" style="font-size:12px">
          ${m.description ? '' : 'Sans description, Wally ne lit que le nom du fichier : « '
            + escHtml(m.lue || '') + ' ».'}
        </div>
        <div class="meme-fiche-actions">
          <button class="btn" data-fiche="supprimer">Supprimer</button>
          <button class="btn active" data-fiche="enregistrer">Enregistrer</button>
        </div>
        <div class="meme-fiche-nav">
          <button class="btn" data-fiche="precedent" ${i === 0 ? 'disabled' : ''}>← Précédent</button>
          <button class="btn" data-fiche="suivant"
                  ${i === _memesVus.length - 1 ? 'disabled' : ''}>Suivant →</button>
        </div>
        <div id="meme-fiche-etat" class="muted" style="font-size:12px"></div>
      </div>
    </div>`;
  const champ = document.getElementById('meme-fiche-desc');
  if (champ) champ.focus();
}

function fermerMeme() {
  _memeOuvert = -1;
  const fiche = document.getElementById('meme-fiche');
  if (fiche) fiche.remove();
}

function _etatFiche(texte) {
  const el = document.getElementById('meme-fiche-etat');
  if (el) el.textContent = texte;
}

/** Enregistre la description du meme ouvert.
 *
 *  Le serveur rend ce que Wally LIRA — tronqué à la longueur maximale, ou
 *  retombé sur un vieux sidecar partagé si l'on vient d'effacer. C'est cette
 *  réponse qu'on garde, pas la saisie : sinon l'écran promet une phrase que le
 *  bot ne lira jamais en entier.
 */
async function enregistrerMeme() {
  const m = _memesVus[_memeOuvert];
  const champ = document.getElementById('meme-fiche-desc');
  if (!m || !champ) return;
  _etatFiche('Enregistrement…');
  const r = await apiFetch('/api/admin/overlay/memes/' + encodeURIComponent(m.nom), {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ description: champ.value }),
  });
  if (!r || !r.ok) { _etatFiche('Échec de l\'enregistrement.'); return; }
  const d = await r.json();
  m.description = d.description || '';
  m.lue = d.lue || '';
  // La galerie D'ABORD (la pastille « à décrire » doit tomber), la fiche
  // ENSUITE : `_rendreGalerieMemes` ne touche pas la fiche, mais l'ordre
  // inverse ferait clignoter le champ sous les doigts.
  _rendreGalerieMemes();
  champ.value = m.description;
  champ.placeholder = m.lue;
  _etatFiche('Enregistré. Wally lira : « ' + m.lue + ' »');
}

async function supprimerMeme() {
  const m = _memesVus[_memeOuvert];
  if (!m) return;
  if (!confirm('Supprimer ' + m.nom + ' ? Le fichier et sa description partent.')) return;
  _etatFiche('Suppression…');
  const r = await apiFetch('/api/admin/overlay/memes/' + encodeURIComponent(m.nom),
                           { method: 'DELETE' });
  if (!r || !r.ok) { _etatFiche('Échec de la suppression.'); return; }
  _memes = _memes.filter((x) => x.nom !== m.nom);
  const rang = _memeOuvert;
  _rendreGalerieMemes();
  // On reste dans la pile : le meme suivant a pris la place du supprimé. C'est
  // ce qu'on veut en faisant le ménage — sinon il faut rouvrir à chaque fois.
  if (rang < _memesVus.length) ouvrirMeme(rang);
  else if (_memesVus.length) ouvrirMeme(_memesVus.length - 1);
  else fermerMeme();
  _etatMemes(m.nom + ' supprimé.');
}

/** Dépose les fichiers choisis, un par un.
 *
 *  Un par un et non en lot : le corps de la requête EST le fichier, sans
 *  multipart — donc sans la dépendance `python-multipart` côté serveur. La
 *  boucle est séquentielle parce que le serveur numérote (`meme174.webp`) et
 *  qu'un envoi parallèle ferait tirer le même numéro à deux fichiers.
 */
async function deposerMemes() {
  const input = document.getElementById('meme-fichier');
  const fichiers = input && input.files ? [...input.files] : [];
  if (!fichiers.length) { _etatMemes('Choisissez un ou plusieurs fichiers.'); return; }
  const ranges = [];
  const refus = [];
  for (let i = 0; i < fichiers.length; i++) {
    const f = fichiers[i];
    _etatMemes('Envoi de ' + f.name + '… (' + (i + 1) + '/' + fichiers.length + ')');
    const r = await apiFetch('/api/admin/overlay/memes/' + encodeURIComponent(f.name), {
      method: 'POST',
      headers: { 'Content-Type': 'application/octet-stream' },
      body: f,
    });
    if (r && r.ok) { ranges.push((await r.json()).nom); continue; }
    // Le serveur DIT pourquoi (format, poids, doublon) : le relayer vaut mieux
    // qu'un « échec » qui laisse chercher.
    let raison = '';
    // `apiFetch` rend NULL sur 401 (session expirée) : `r.json()` lèverait, et
    // le `catch` masquerait la vraie cause derrière un « Refusé » sec.
    try { if (r) raison = (await r.json()).detail || ''; }
    catch (e) { /* corps illisible */ }
    refus.push(f.name + (raison ? ' — ' + raison : ''));
  }
  input.value = '';
  // La liste ENTIÈRE est rechargée : le serveur renomme et peut convertir en
  // WebP. Deviner les noms ici, c'est afficher des vignettes mortes.
  await chargerMemes();
  // Ce qu'on vient de déposer soi-même n'est pas une nouvelle à annoncer : la
  // bannière sert aux memes arrivés d'AILLEURS pendant qu'on regardait.
  _memesNeufs = [];
  _rendreGalerieMemes();
  _etatMemes((ranges.length ? ranges.length + ' rangé(s). Décrivez-les : sans '
    + 'description, Wally ne saura pas quand les sortir.' : '')
    + (refus.length ? ' Refusé : ' + refus.join(' · ') : ''));
  // Le premier arrivé s'ouvre : le geste suivant est TOUJOURS de le décrire.
  if (ranges.length) {
    const rang = _memesVus.findIndex((m) => m.nom === ranges[0]);
    if (rang >= 0) ouvrirMeme(rang);
  }
}


// ── Atelier des sons de commande (Système → Overlay) ─────────────────────────
//
// Ce que le chat déclenche par son nom : `!apero`, `!perks`… Le DOSSIER décide
// de ce qui existe, cet écran ne fait que déposer, régler et retirer. Il n'y a
// donc rien à tenir en mémoire ici : chaque geste se conclut par un rechargement
// de la liste depuis le serveur, seule source de vérité.

function _octetsLisibles(n) {
  return n >= 1024 * 1024 ? (n / 1048576).toFixed(1) + ' Mo'
                          : Math.round(n / 1024) + ' Ko';
}

async function renderAtelierSons() {
  const box = document.getElementById('atelier-sons');
  if (!box) return;
  let data = null;
  try {
    const r = await apiFetch('/api/admin/overlay/sons');
    if (r && r.ok) data = await r.json();
  } catch (e) {
    // Réseau coupé : on le DIT. Un panneau vide se lit comme « aucun son ».
  }
  if (!data) {
    box.innerHTML = '<div class="card-title">SONS DU CHAT</div>'
      + '<div class="muted">Liste indisponible — le bot ne répond pas.</div>';
    return;
  }
  const sons = data.sons || [];
  const lignes = sons.map(function (s) {
    return `
      <div class="son-ligne" data-commande="${_escHtml(s.commande)}"
           style="display:grid;grid-template-columns:1fr auto;gap:8px;
                  padding:10px 0;border-top:1px solid rgba(255,255,255,0.08)">
        <div>
          <div style="font-weight:600">!${_escHtml(s.commande)}
            <span class="muted" style="font-weight:400">
              · ${_escHtml(s.fichier)} · ${_octetsLisibles(s.taille)}</span>
          </div>
          <div style="display:flex;flex-wrap:wrap;gap:8px;margin-top:6px;align-items:center">
            <label class="muted">Pause
              <input type="number" min="0" step="1" value="${Number(s.cooldown)}"
                     data-champ="cooldown" style="width:72px"> s</label>
            <label class="muted">Volume
              <input type="number" min="0" max="2" step="0.05" value="${Number(s.volume)}"
                     data-champ="volume" style="width:72px"></label>
            <label class="muted" style="flex:1;min-width:220px">Autres noms
              <input type="text" value="${_escHtml((s.alias || []).join(', '))}"
                     data-champ="alias" placeholder="perk, perques"
                     style="width:100%"></label>
          </div>
        </div>
        <div style="display:flex;flex-direction:column;gap:6px;align-items:flex-end">
          <button class="btn" data-son-action="essai">▶ Écouter</button>
          <button class="btn" data-son-action="enregistrer">Enregistrer</button>
          <button class="btn" data-son-action="supprimer">Supprimer</button>
        </div>
      </div>`;
  }).join('');

  box.innerHTML = `
    <div class="card-title">SONS DU CHAT</div>
    <p class="muted" style="margin-top:0">
      Le nom du fichier EST la commande : <code>apero.mp3</code> répond à
      <code>!apero</code>. Déposez-en un, il répond aussitôt — aucun redémarrage.
      « Pause » à 0 = pas de limite. « Autres noms » sert aux fautes de frappe
      courantes, elles partagent la pause et le volume du son.
    </p>
    <div style="display:flex;gap:8px;flex-wrap:wrap;align-items:center;margin:10px 0">
      <input type="file" id="son-fichier" accept=".mp3,.wav,.ogg,.m4a">
      <button class="btn" onclick="deposerSon()">Déposer</button>
      <button class="btn" onclick="normaliserSons()"
        title="Met tous les sons au même niveau perçu (EBU R128). L'original de chaque fichier est conservé.">
        Égaliser les volumes</button>
      <span id="atelier-sons-etat" class="muted"></span>
    </div>
    ${sons.length ? lignes : '<div class="muted">Aucun son. Déposez un mp3 pour commencer.</div>'}
    <div class="muted" style="margin-top:10px;font-size:12px">
      ${_octetsLisibles(data.max_octets || 0)} par fichier au maximum.
    </div>`;

  _cablerAtelierSons(box);
}

/** Les boutons de chaque ligne, câblés par DÉLÉGATION.
 *
 *  Surtout pas d'`onclick="...('${nom}')"` : `_escHtml` n'échappe PAS
 *  l'apostrophe, et le nom vient d'un nom de FICHIER. Un `x');alert(1);a.mp3`
 *  déposé dans le dossier — par le panneau ou à la main — s'exécuterait au
 *  rendu. Ici le nom ne traverse jamais un contexte JavaScript : il vit dans un
 *  attribut `data-`, lu comme une chaîne.
 *
 *  Un seul écouteur pour toutes les lignes, posé une fois : `renderAtelierSons`
 *  réécrit `innerHTML` à chaque geste, et en reposer un par rendu les empilerait
 *  jusqu'à jouer un son trois fois pour un clic.
 */
function _cablerAtelierSons(box) {
  if (box.dataset.cable) return;
  box.dataset.cable = '1';
  box.addEventListener('click', function (ev) {
    const bouton = ev.target.closest('[data-son-action]');
    if (!bouton) return;
    const ligne = bouton.closest('.son-ligne');
    if (!ligne) return;
    const commande = ligne.dataset.commande;
    if (bouton.dataset.sonAction === 'essai') essayerSon(commande);
    else if (bouton.dataset.sonAction === 'enregistrer') enregistrerSon(ligne, commande);
    else if (bouton.dataset.sonAction === 'supprimer') supprimerSon(commande);
  });
}

function _etatAtelier(texte) {
  const el = document.getElementById('atelier-sons-etat');
  if (el) el.textContent = texte;
}

/** Lit les trois champs d'une ligne. On reçoit l'ÉLÉMENT, pas un nom : le
 *  construire en sélecteur CSS reposerait le même problème d'échappement que
 *  les `onclick` — un nom de fichier portant un guillemet casserait la requête. */
function _champsSon(ligne) {
  if (!ligne) return null;
  const lire = (c) => ligne.querySelector('[data-champ="' + c + '"]');
  return {
    cooldown: Number(lire('cooldown').value) || 0,
    volume: Number(lire('volume').value),
    // Une saisie vide doit VIDER la liste, pas la laisser en place : `split`
    // sur une chaîne vide rend [''], d'où le filtre.
    alias: lire('alias').value.split(',').map((s) => s.trim()).filter(Boolean),
  };
}

async function enregistrerSon(ligne, commande) {
  const valeurs = _champsSon(ligne);
  if (!valeurs) return;
  _etatAtelier('Enregistrement…');
  const r = await apiFetch('/api/admin/overlay/sons/' + encodeURIComponent(commande), {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(valeurs),
  });
  // Le rendu D'ABORD, le message ENSUITE : `renderAtelierSons` réécrit tout le
  // panneau, y compris la ligne d'état. Dans l'autre ordre, cliquer « Enregistrer »
  // ne renvoyait rien du tout à l'écran.
  if (r && r.ok) await renderAtelierSons();
  _etatAtelier(r && r.ok ? '!' + commande + ' enregistré.' : 'Échec de l\'enregistrement.');
}

async function essayerSon(commande) {
  _etatAtelier('Envoi sur l\'overlay…');
  const r = await apiFetch('/api/admin/overlay/sons/'
    + encodeURIComponent(commande) + '/essai', { method: 'POST' });
  _etatAtelier(r && r.ok ? 'Joué sur l\'overlay.'
                         : 'L\'overlay n\'a pas répondu.');
}

async function supprimerSon(commande) {
  if (!confirm('Supprimer !' + commande + ' ? Le fichier et ses réglages partent.')) return;
  _etatAtelier('Suppression…');
  const r = await apiFetch('/api/admin/overlay/sons/' + encodeURIComponent(commande),
                           { method: 'DELETE' });
  await renderAtelierSons();
  _etatAtelier(r && r.ok ? '!' + commande + ' supprimé.' : 'Échec de la suppression.');
}

async function deposerSon() {
  const input = document.getElementById('son-fichier');
  const fichier = input && input.files && input.files[0];
  if (!fichier) { _etatAtelier('Choisissez un fichier.'); return; }
  _etatAtelier('Envoi de ' + fichier.name + '…');
  // Le corps est le fichier BRUT : pas de multipart, donc pas de dépendance
  // `python-multipart` côté serveur pour un seul fichier à la fois.
  const r = await apiFetch('/api/admin/overlay/sons/' + encodeURIComponent(fichier.name), {
    method: 'POST',
    headers: { 'Content-Type': 'application/octet-stream' },
    body: fichier,
  });
  await renderAtelierSons();
  if (r && r.ok) {
    _etatAtelier(fichier.name + ' déposé.');
  } else {
    // Le serveur DIT pourquoi (extension, taille) : le relayer vaut mieux
    // qu'un « échec » qui laisse chercher.
    let raison = '';
    // `apiFetch` rend NULL sur 401 (session expirée) : `r.json()` lèverait,
    // et le `catch` masquerait la vraie cause derrière un « Refusé » sec.
    try { if (r) raison = (await r.json()).detail || ''; }
    catch (e) { /* corps illisible */ }
    _etatAtelier('Refusé' + (raison ? ' — ' + raison : '.'));
  }
}

async function normaliserSons() {
  _etatAtelier('Égalisation en cours (quelques secondes par son)…');
  const r = await apiFetch('/api/admin/overlay/normaliser-sons', { method: 'POST' });
  if (!r || !r.ok) { _etatAtelier('Égalisation impossible.'); return; }
  const d = await r.json();
  const n = (d.normalises || []).length, e = (d.echecs || []).length;
  await renderAtelierSons();
  _etatAtelier(n + ' son(s) égalisé(s)' + (e ? ', ' + e + ' échec(s).' : '.'));
}
