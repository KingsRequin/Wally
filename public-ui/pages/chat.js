// public-ui/pages/chat.js — le chat web, plein écran
//
// Même mémoire, mêmes émotions qu'ailleurs : le WebSocket `/ws/chat` parle au
// même bot que Discord et Twitch. La colonne de droite montre ce qu'il sait de
// toi — c'est la partie qui distingue ce chat d'un formulaire de contact.

import { emotions, ensureFreshToken, h, nomBot, onEmotionUpdate, openModal } from '../app.js';
import { renderMarkdown } from '../markdown.js';

const DATE_MIN = new Date('2026-03-01');

const SUGGESTIONS_IMAGE = [
  'un paysage cyberpunk sous la pluie',
  'portrait impressionniste de Wally',
  'ville futuriste vue du ciel, style anime',
  'forêt enchantée la nuit, bioluminescence',
  'chat robot dans un café parisien',
];

const AMORCES = [
  'Quoi de neuf sur le stream ?',
  'Rappelle-moi ce que tu sais de moi',
  '/imagine ',
];

const EMO_NOMS = {
  curiosity: 'Curiosité', joy: 'Joie', anger: 'Colère', sadness: 'Tristesse', boredom: 'Ennui',
};
const EMO_COULEURS = {
  curiosity: '#46d9ff', joy: '#ffb02e', anger: '#ff3d6e', sadness: '#8b7cff', boredom: '#6f6a7a',
};
const EMO_PHRASES = {
  curiosity: "Il pose plus de questions qu'il n'affirme. Attends-toi à être relancé.",
  joy: 'Il est de bonne humeur. Ça se sent dans ses réponses.',
  anger: 'Il est à cran. Ses réponses seront courtes.',
  sadness: 'Il traîne un peu. Il répondra, mais sans entrain.',
  boredom: "Rien ne se passe depuis un moment. Il s'ennuie ferme.",
};

// ── État du module ────────────────────────────────────────────────────────
let _ws = null;
let _monte = false;
let _hote = null;
let _delaiReprise = 1000;
let _timerReprise = null;
let _dateCourante = null;   // null = aujourd'hui (mode direct)
let _desabonnerEmo = null;
let _refs = {};
let _fermerAuto = null;

// ── Dates ─────────────────────────────────────────────────────────────────
function aujourdhui() {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
}

function enFrancais(iso) {
  const [y, m, d] = iso.split('-').map(Number);
  return new Date(y, m - 1, d).toLocaleDateString('fr-FR', { weekday: 'long', day: 'numeric', month: 'long' });
}

function decale(iso, jours) {
  const [y, m, d] = iso.split('-').map(Number);
  const dt = new Date(y, m - 1, d);
  dt.setDate(dt.getDate() + jours);
  return `${dt.getFullYear()}-${String(dt.getMonth() + 1).padStart(2, '0')}-${String(dt.getDate()).padStart(2, '0')}`;
}

function estAujourdhui(iso) { return iso === aujourdhui(); }

function auPlusAncien(iso) {
  const [y, m, d] = iso.split('-').map(Number);
  return new Date(y, m - 1, d) <= DATE_MIN;
}

// ── Bulles ────────────────────────────────────────────────────────────────
function bulle(texte, qui) {
  const corps = h('div', { class: 'body' });
  if (qui === 'bot') renderMarkdown(texte, corps);
  else corps.textContent = texte;

  const b = h('div', { class: 'bubble' + (qui === 'moi' ? ' mine' : '') });
  if (qui === 'bot') {
    b.appendChild(h('video', { src: '/wally.webm', autoplay: true, loop: true, muted: true, playsInline: true, 'aria-hidden': 'true' }));
  }
  b.appendChild(h('div', {}, corps));
  return b;
}

function ajouterBulle(texte, qui) {
  const fil = _refs.fil;
  if (!fil) return null;
  const b = bulle(texte, qui);
  fil.insertBefore(b, _refs.frappe || null);
  collerEnBas();
  return b;
}

function ajouterSysteme(texte) {
  const fil = _refs.fil;
  if (!fil) return;
  fil.insertBefore(h('div', { class: 'chat-daysep' },
    h('div', { class: 'rule' }),
    h('span', { class: 'lbl', text: texte }),
    h('div', { class: 'rule' }),
  ), _refs.frappe || null);
  collerEnBas();
}

function collerEnBas() {
  const sc = _refs.scroll;
  if (sc) sc.scrollTop = sc.scrollHeight;
}

function afficherFrappe(on) {
  if (!_refs.frappe) return;
  _refs.frappe.style.display = on ? '' : 'none';
  if (on) collerEnBas();
}

// ── WebSocket ─────────────────────────────────────────────────────────────
function etatConnexion(enLigne) {
  if (!_refs.hint) return;
  _refs.hint.textContent = enLigne
    ? 'IL SE SOUVIENT DE CETTE CONVERSATION · ENTRÉE POUR ENVOYER'
    : 'RECONNEXION EN COURS…';
  _refs.hint.style.color = enLigne ? 'var(--faint)' : 'var(--gold)';
}

function connecter(token) {
  if (!_monte) return;
  const proto = location.protocol === 'https:' ? 'wss' : 'ws';
  _ws = new WebSocket(`${proto}://${location.host}/ws/chat?token=${token}`);

  _ws.onopen = () => { _delaiReprise = 1000; etatConnexion(true); };

  _ws.onmessage = (e) => {
    let data;
    try { data = JSON.parse(e.data); }
    catch (err) {
      // Muet, c'est une réponse qui disparaît sans laisser de trace.
      console.warn('chat : message illisible', err, e.data);
      return;
    }

    if (data.type === 'history') {
      (data.messages || []).forEach((m) => ajouterBulle(m.content, m.is_wally ? 'bot' : 'moi'));
      collerEnBas();
      return;
    }
    if (data.type === 'typing') { afficherFrappe(true); return; }
    if (data.type === 'message') {
      afficherFrappe(false);
      // L'écho du message de l'utilisateur est déjà affiché localement.
      if (data.is_wally !== false) ajouterBulle(data.content, 'bot');
      return;
    }
    if (data.type === 'image_generating') {
      afficherFrappe(false);
      const b = ajouterBulle('🎨 Génération en cours…', 'bot');
      if (b) b.dataset.img = String(data.id);
      return;
    }
    if (data.type === 'image_result') {
      afficherFrappe(false);
      let b = _refs.fil.querySelector(`[data-img="${data.id}"]`);
      if (!b) b = ajouterBulle('', 'bot');
      const corps = b.querySelector('.body');
      corps.textContent = '';
      delete b.dataset.img;
      if (data.title) corps.appendChild(h('div', { text: data.title }));
      const img = h('img', { src: data.image_url, alt: data.title || 'Image générée', loading: 'lazy' });
      img.addEventListener('click', () => openModal(data.image_url, data.title || ''));
      corps.appendChild(img);
      collerEnBas();
      return;
    }
    if (data.type === 'image_cancelled') {
      const b = _refs.fil.querySelector(`[data-img="${data.id}"]`);
      if (b) {
        delete b.dataset.img;
        b.querySelector('.body').textContent = '⚠️ ' + (data.error || 'Génération annulée');
      }
      return;
    }
    if (data.type === 'system') ajouterSysteme(data.content);
  };

  _ws.onclose = () => {
    if (!_monte) return;
    etatConnexion(false);
    // Reprise exponentielle : 1 s → 2 s → 4 s → … → 30 s.
    _timerReprise = setTimeout(() => {
      _delaiReprise = Math.min(_delaiReprise * 2, 30000);
      connecter(localStorage.getItem('discord_jwt'));
    }, _delaiReprise);
  };
}

// ── Colonne de droite ─────────────────────────────────────────────────────
function jaugeRelation(nom, valeur, couleur) {
  const pourcent = Math.round((valeur || 0) * 100);
  const barre = h('div', { class: 'gauge-fill', style: `background:${couleur}` });
  requestAnimationFrame(() => { barre.style.width = pourcent + '%'; });
  return h('div', { class: 'gauge' },
    h('div', { class: 'gauge-head' },
      h('span', { text: nom }),
      h('span', { class: 'val', text: pourcent + '%' }),
    ),
    h('div', { class: 'gauge-track' }, barre),
  );
}

function rendreHumeur() {
  const hote = _refs.humeur;
  if (!hote) return;
  let dominante = 'curiosity';
  let max = 0;
  Object.keys(EMO_NOMS).forEach((cle) => {
    if ((emotions[cle] || 0) > max) { max = emotions[cle]; dominante = cle; }
  });
  hote.textContent = '';
  hote.appendChild(h('div', {
    style: `margin-top:10px; font-size:26px; font-weight:600; letter-spacing:-.025em; color:${EMO_COULEURS[dominante]}`,
    text: EMO_NOMS[dominante],
  }));
  hote.appendChild(h('p', {
    style: 'margin:10px 0 0; font-size:13.5px; line-height:1.55; color:var(--muted)',
    text: EMO_PHRASES[dominante],
  }));
}

function rendreMemoire(data) {
  const rel = _refs.relation;
  const faits = _refs.faits;
  if (!rel || !faits) return;

  rel.textContent = '';
  faits.textContent = '';

  if (!data) {
    rel.appendChild(h('div', { style: 'font-size:13.5px; color:var(--dim)', text: 'Mémoire indisponible.' }));
    return;
  }

  const relation = data.relation || {};
  rel.appendChild(jaugeRelation('CONFIANCE', relation.trust, 'var(--gold)'));
  rel.appendChild(jaugeRelation('AFFINITÉ', relation.love, 'var(--rose)'));

  const items = [...(data.facts || []), ...(data.preferences || [])];
  if (!items.length) {
    faits.appendChild(h('div', { style: 'font-size:13.5px; color:var(--dim)', text: "Il ne sait encore rien de toi. Parle-lui." }));
    return;
  }
  items.slice(0, 8).forEach((t) => faits.appendChild(h('div', { class: 'fact', text: t })));
  if (items.length > 8) {
    faits.appendChild(h('div', { class: 'label', style: 'margin-top:4px', text: items.length + ' FAITS AU TOTAL' }));
  }
}

function colonne() {
  const relation = h('div', { style: 'margin-top:18px' });
  const humeur = h('div', {});
  const faits = h('div', { style: 'display:flex; flex-direction:column; gap:10px; margin-top:16px' });
  _refs.relation = relation;
  _refs.humeur = humeur;
  _refs.faits = faits;

  return h('aside', { class: 'chat-side' },
    h('section', {}, h('div', { class: 'label', text: 'VOTRE RELATION' }), relation),
    h('section', {}, h('div', { class: 'label', text: 'HUMEUR ACTUELLE' }), humeur),
    h('section', {}, h('div', { class: 'label', text: "CE QU'IL SAIT DE TOI" }), faits),
  );
}

// ── Navigation par date ───────────────────────────────────────────────────
function modeDirect() {
  _dateCourante = null;
  _refs.dateLbl.textContent = "AUJOURD'HUI";
  _refs.suiv.disabled = true;
  _refs.prec.disabled = false;
  _refs.input.disabled = false;
  _refs.envoyer.disabled = false;
  _refs.input.placeholder = `Écrire à ${nomBot()}…`;
  viderFil();
  if (_ws) { _ws.onclose = null; _ws.close(); _ws = null; }
  connecter(localStorage.getItem('discord_jwt'));
}

function modeHistorique(iso) {
  _dateCourante = iso;
  _refs.dateLbl.textContent = enFrancais(iso).toUpperCase();
  _refs.suiv.disabled = false;
  _refs.prec.disabled = auPlusAncien(iso);
  _refs.input.disabled = true;
  _refs.envoyer.disabled = true;
  _refs.input.placeholder = 'Lecture seule, ' + enFrancais(iso);
  _refs.hint.textContent = 'LECTURE SEULE · REVIENS À AUJOURD\'HUI POUR ÉCRIRE';
  _refs.hint.style.color = 'var(--faint)';
  chargerHistorique(iso);
}

/** Vide le fil SANS perdre l'indicateur de frappe, qui en est un enfant. */
function viderFil() {
  const fil = _refs.fil;
  if (!fil) return;
  fil.textContent = '';
  if (_refs.frappe) { _refs.frappe.style.display = 'none'; fil.appendChild(_refs.frappe); }
}

function chargerHistorique(iso) {
  viderFil();
  ajouterSysteme('CHARGEMENT…');

  fetch('/api/chat/history/' + iso, { headers: { Authorization: 'Bearer ' + localStorage.getItem('discord_jwt') } })
    .then((r) => (r.ok ? r.json() : null))
    .then((data) => {
      if (_dateCourante !== iso) return;   // l'utilisateur a déjà changé de jour
      viderFil();
      const msgs = (data && data.messages) || [];
      if (!msgs.length) { ajouterSysteme('AUCUN MESSAGE CE JOUR-LÀ'); return; }
      msgs.forEach((m) => ajouterBulle(m.content, m.is_wally ? 'bot' : 'moi'));
    })
    .catch((err) => {
      console.warn('historique du chat indisponible', err);
      if (_dateCourante !== iso) return;
      viderFil();
      ajouterSysteme("IMPOSSIBLE DE CHARGER L'HISTORIQUE");
    });
}

// ── Écran connecté ────────────────────────────────────────────────────────
function ecranChat() {
  const frappe = h('div', { class: 'chat-typing', style: 'display:none' },
    h('span', { class: 'dot' }), 'il écrit…');
  // DANS le fil, pas à côté : le fil est centré sur 820 px, un frère du fil
  // se collerait au bord gauche de la colonne, à 60 px des bulles.
  const fil = h('div', { class: 'chat-thread' }, frappe);
  const scroll = h('div', { class: 'chat-scroll' }, fil);

  const input = h('input', {
    class: 'chat-input',
    type: 'text',
    'aria-label': `Écrire à ${nomBot()}`,
    placeholder: `Écrire à ${nomBot()}…`,
  });
  const envoyer = h('button', { class: 'btn btn-primary chat-send', text: 'Envoyer' });
  const hint = h('div', { class: 'chat-hint', text: 'CONNEXION…' });

  // Suggestions d'`/imagine` : elles ne s'affichent que quand la commande est
  // déjà tapée, sinon elles masquent le champ à chaque frappe.
  const auto = h('div', { class: 'chat-ac', style: 'display:none' },
    ...SUGGESTIONS_IMAGE.map((s) => {
      const item = h('div', { class: 'chat-ac-item', text: s });
      item.addEventListener('mousedown', (e) => {
        e.preventDefault();          // ne pas retirer le focus du champ
        input.value = '/imagine ' + s;
        auto.style.display = 'none';
        input.focus();
      });
      return item;
    }),
  );

  const ligne = h('div', { class: 'chat-input-row' }, auto, input, envoyer);

  const prec = h('button', { class: 'chat-nav-btn', text: '‹', title: 'Jour précédent' });
  const suiv = h('button', { class: 'chat-nav-btn', text: '›', title: 'Jour suivant', disabled: true });
  const dateLbl = h('span', { class: 'lbl', text: "AUJOURD'HUI" });

  _refs = {
    ..._refs, fil, frappe, scroll, input, envoyer, hint, auto, prec, suiv, dateLbl,
  };

  const amorces = h('div', { class: 'chat-chips' },
    ...AMORCES.map((p) => {
      const b = h('button', { class: 'chip', text: p.trim() || p });
      b.addEventListener('click', () => {
        input.value = p;
        input.focus();
        input.dispatchEvent(new Event('input'));
      });
      return b;
    }),
  );

  const dock = h('div', { class: 'chat-dock' },
    h('div', { class: 'chat-dock-inner' }, amorces, ligne, hint));

  const separateur = h('div', { class: 'chat-datebar' },
    h('div', { class: 'chat-daysep' },
      prec, h('div', { class: 'rule' }), dateLbl, h('div', { class: 'rule' }), suiv));

  const envoi = () => {
    const texte = input.value.trim();
    if (!texte || _dateCourante !== null) return;
    if (!_ws || _ws.readyState !== WebSocket.OPEN) return;
    ajouterBulle(texte, 'moi');
    _ws.send(JSON.stringify({ type: 'message', content: texte }));
    input.value = '';
    auto.style.display = 'none';
  };
  envoyer.addEventListener('click', envoi);
  input.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') { auto.style.display = 'none'; return; }
    if (e.key === 'Enter') { auto.style.display = 'none'; envoi(); }
  });
  input.addEventListener('input', () => {
    auto.style.display = input.value.startsWith('/imagine ') ? 'block' : 'none';
  });
  _fermerAuto = (e) => { if (!ligne.contains(e.target)) auto.style.display = 'none'; };
  document.addEventListener('click', _fermerAuto);

  prec.addEventListener('click', () => modeHistorique(decale(_dateCourante || aujourdhui(), -1)));
  suiv.addEventListener('click', () => {
    if (suiv.disabled) return;
    const n = decale(_dateCourante, 1);
    if (estAujourdhui(n)) modeDirect(); else modeHistorique(n);
  });

  return h('div', { class: 'chat-vue' },
    h('div', { class: 'chat-grid' },
      h('div', { class: 'chat-main' }, separateur, scroll, dock),
      colonne(),
    ),
  );
}

// ── Écran de connexion ────────────────────────────────────────────────────
function portail() {
  return h('div', { class: 'chat-vue' },
    h('div', { class: 'chat-gate' },
      h('video', { src: '/wally.webm', autoplay: true, loop: true, muted: true, playsInline: true, 'aria-hidden': 'true' }),
      h('h1', { class: 'h2', style: 'margin:0', text: `Parler à ${nomBot()}` }),
      h('p', { class: 'lead lead-center', style: 'margin-top:8px', text:
        `Connecte ton compte Discord : ${nomBot()} te reconnaît, retrouve ce qu'il sait de toi, `
        + "et reprend la conversation là où elle s'était arrêtée." }),
      h('button', {
        class: 'btn btn-discord',
        text: 'Continuer avec Discord',
        onclick: () => { window.location.href = '/api/chat/auth/login'; },
      }),
    ),
  );
}

function attente(texte) {
  return h('div', { class: 'chat-vue' },
    h('div', { class: 'chat-gate' }, h('div', { class: 'spinner' }), h('div', { class: 'lead', text: texte })));
}

// ── Montage ───────────────────────────────────────────────────────────────
function decoderJwt(t) {
  try {
    const b64 = t.split('.')[1].replace(/-/g, '+').replace(/_/g, '/');
    return JSON.parse(atob(b64));
  } catch (_) { return null; }
}

export function mount(el) {
  _hote = el;
  _monte = true;
  _dateCourante = null;
  el.textContent = '';

  // Retour OAuth : le serveur ne sait rediriger que vers `/`, le routeur nous
  // a envoyés ici avec le code encore dans l'URL.
  const code = new URLSearchParams(location.search).get('chat_code');
  if (code) {
    history.replaceState({}, '', '/chat');
    el.appendChild(attente('Connexion en cours…'));
    fetch('/api/chat/auth/exchange?code=' + encodeURIComponent(code))
      .then((r) => (r.ok ? r.json() : null))
      .then((data) => {
        if (data && data.jwt) {
          localStorage.setItem('discord_jwt', data.jwt);
          if (data.refresh_token) localStorage.setItem('discord_refresh', data.refresh_token);
          window.dispatchEvent(new CustomEvent('wally-auth-changed'));
        }
        if (_monte && _hote === el) { el.textContent = ''; mount(el); }
      })
      .catch((err) => {
        console.warn('échange OAuth impossible', err);
        if (_monte && _hote === el) { el.textContent = ''; mount(el); }
      });
    return;
  }

  const jwt = localStorage.getItem('discord_jwt');
  const p = jwt ? decoderJwt(jwt) : null;
  const valide = p && (!p.exp || p.exp * 1000 > Date.now());

  // JWT absent ou expiré : on tente un rafraîchissement silencieux avant de
  // montrer le portail, sinon un simple rechargement déconnecte au bout d'1 h.
  if (!valide) {
    if (localStorage.getItem('discord_refresh')) {
      el.appendChild(attente('Reconnexion…'));
      ensureFreshToken().then((ok) => {
        if (!_monte || _hote !== el) return;
        if (ok) window.dispatchEvent(new CustomEvent('wally-auth-changed'));
        el.textContent = '';
        mount(el);
      });
      return;
    }
    el.appendChild(portail());
    return;
  }

  el.appendChild(ecranChat());
  rendreHumeur();
  _desabonnerEmo = onEmotionUpdate(rendreHumeur);

  etatConnexion(false);
  connecter(jwt);

  fetch('/api/public/memory/me', { headers: { Authorization: 'Bearer ' + jwt } })
    .then((r) => (r.ok ? r.json() : null))
    .then(rendreMemoire)
    .catch((err) => {
      console.warn('mémoire personnelle indisponible', err);
      rendreMemoire(null);
    });
}

export function unmount() {
  _monte = false;
  _hote = null;
  _dateCourante = null;
  clearTimeout(_timerReprise);
  _timerReprise = null;
  _delaiReprise = 1000;
  if (_ws) { _ws.onclose = null; _ws.close(); _ws = null; }
  if (_desabonnerEmo) { _desabonnerEmo(); _desabonnerEmo = null; }
  if (_fermerAuto) { document.removeEventListener('click', _fermerAuto); _fermerAuto = null; }
  _refs = {};
}
