// public-ui/tabs/gallery.js — arcade

let _container = null;
let _sort = 'date';
let _offset = 0;
let _search = '';
const LIMIT = 24;

// ── Gallery modal custom ──
let _modalOverlay = null;

function getJwt() {
  return localStorage.getItem('discord_jwt') || null;
}

function authHeaders() {
  const jwt = getJwt();
  return jwt ? { Authorization: 'Bearer ' + jwt } : {};
}

// Tente de rafraîchir le JWT via le refresh token. Retourne true si succès.
async function tryRefresh() {
  const refresh = localStorage.getItem('discord_refresh');
  if (!refresh) return false;
  try {
    const r = await fetch('/api/chat/auth/refresh', {
      headers: { Authorization: 'Bearer ' + refresh },
    });
    if (!r.ok) {
      localStorage.removeItem('discord_jwt');
      localStorage.removeItem('discord_refresh');
      return false;
    }
    const data = await r.json();
    if (data.jwt) localStorage.setItem('discord_jwt', data.jwt);
    if (data.refresh_token) localStorage.setItem('discord_refresh', data.refresh_token);
    return true;
  } catch (_) {
    return false;
  }
}

// fetch avec retry automatique sur 401 (refresh JWT transparent)
async function authedFetch(url, options = {}) {
  const res = await fetch(url, { ...options, headers: { ...authHeaders(), ...(options.headers || {}) } });
  if (res.status !== 401) return res;
  // Token expiré — on tente le refresh
  const refreshed = await tryRefresh();
  if (!refreshed) return res; // renvoie le 401 original
  return fetch(url, { ...options, headers: { ...authHeaders(), ...(options.headers || {}) } });
}

function buildGalleryModal() {
  if (_modalOverlay) return _modalOverlay;

  const overlay = document.createElement('div');
  overlay.className = 'gallery-modal-overlay';
  overlay.addEventListener('click', (e) => {
    if (e.target === overlay) closeGalleryModal();
  });

  const box = document.createElement('div');
  box.className = 'gallery-modal-box';

  const closeBtn = document.createElement('button');
  closeBtn.className = 'gallery-modal-close';
  closeBtn.textContent = '✕';
  closeBtn.setAttribute('aria-label', 'Fermer');
  closeBtn.addEventListener('click', closeGalleryModal);
  box.appendChild(closeBtn);

  const img = document.createElement('img');
  img.className = 'gallery-modal-img';
  img.id = 'gallery-modal-img';
  box.appendChild(img);

  const meta = document.createElement('div');
  meta.className = 'gallery-modal-meta';
  meta.id = 'gallery-modal-meta';
  box.appendChild(meta);

  overlay.appendChild(box);
  document.body.appendChild(overlay);
  _modalOverlay = overlay;
  return overlay;
}

function closeGalleryModal() {
  if (_modalOverlay) _modalOverlay.classList.remove('open');
}

function formatDate(ts) {
  if (!ts) return '';
  const d = new Date(ts * 1000);
  return d.toLocaleDateString('fr-FR', { day: '2-digit', month: 'short', year: 'numeric' });
}

async function openGalleryModal(imageId) {
  const overlay = buildGalleryModal();
  const imgEl = document.getElementById('gallery-modal-img');
  const metaEl = document.getElementById('gallery-modal-meta');

  // Show immediately with loading state
  imgEl.src = `/api/public/gallery/${imageId}/image`;
  imgEl.alt = '';
  metaEl.textContent = '';
  overlay.classList.add('open');

  // Fetch details
  let data = null;
  try {
    const res = await authedFetch(`/api/public/gallery/${imageId}`);
    if (res.ok) data = await res.json();
  } catch (_) {}

  if (!data) return;

  imgEl.alt = data.title || data.prompt || '';
  metaEl.textContent = '';

  // Title row
  const titleEl = document.createElement('div');
  titleEl.className = 'gallery-modal-title';
  titleEl.textContent = data.title || data.prompt || '';
  metaEl.appendChild(titleEl);

  // Author + date row
  const authRow = document.createElement('div');
  authRow.className = 'gallery-modal-authrow';
  if (data.username) {
    const authorEl = document.createElement('span');
    authorEl.className = 'gallery-modal-author';
    authorEl.textContent = data.username;
    authRow.appendChild(authorEl);
  }
  if (data.created_at) {
    const sep = document.createElement('span');
    sep.className = 'gallery-modal-sep';
    sep.textContent = '·';
    authRow.appendChild(sep);
    const dateEl = document.createElement('span');
    dateEl.className = 'gallery-modal-date';
    dateEl.textContent = formatDate(data.created_at);
    authRow.appendChild(dateEl);
  }
  metaEl.appendChild(authRow);

  // Vote row
  const voteRow = document.createElement('div');
  voteRow.className = 'gallery-modal-voterow';

  const voteBtn = document.createElement('button');
  voteBtn.className = 'gallery-modal-vote-btn' + (data.user_voted ? ' voted' : '');
  const heartEl = document.createElement('span');
  heartEl.textContent = '♥';
  voteBtn.appendChild(heartEl);
  const voteCount = document.createElement('span');
  voteCount.className = 'gallery-modal-vote-count';
  voteCount.textContent = String(data.votes || 0);
  voteBtn.appendChild(voteCount);

  voteBtn.addEventListener('click', async () => {
    if (!getJwt()) {
      showVoteToast('Connecte-toi via le chat pour voter');
      return;
    }
    try {
      const r = await authedFetch(`/api/public/gallery/${imageId}/vote`, { method: 'POST' });
      if (r.ok) {
        const result = await r.json();
        const current = parseInt(voteCount.textContent, 10) || 0;
        voteCount.textContent = String(result.voted ? current + 1 : Math.max(0, current - 1));
        voteBtn.classList.toggle('voted', result.voted);
      } else if (r.status === 401) {
        showVoteToast('Session expirée — reconnecte-toi dans le Chat');
      }
    } catch (_) {}
  });

  voteRow.appendChild(voteBtn);
  metaEl.appendChild(voteRow);

  // Badges row (model, quality, size)
  const badges = [data.model, data.quality, data.size].filter(Boolean);
  if (badges.length) {
    const badgeRow = document.createElement('div');
    badgeRow.className = 'gallery-modal-badges';
    badges.forEach(b => {
      const badge = document.createElement('span');
      badge.className = 'gallery-modal-badge';
      badge.textContent = b;
      badgeRow.appendChild(badge);
    });
    metaEl.appendChild(badgeRow);
  }

  // Full prompt (only if different from title)
  const hasTitle = Boolean(data.title);
  const promptText = data.prompt || '';
  if (hasTitle && promptText && promptText !== data.title) {
    const promptEl = document.createElement('div');
    promptEl.className = 'gallery-modal-prompt';
    promptEl.textContent = promptText;
    metaEl.appendChild(promptEl);
  }
}

function showVoteToast(msg) {
  const existing = document.querySelector('.vote-toast');
  if (existing) existing.remove();
  const toast = document.createElement('div');
  toast.className = 'vote-toast';
  toast.textContent = msg;
  document.body.appendChild(toast);
  setTimeout(() => toast.classList.add('visible'), 10);
  setTimeout(() => {
    toast.classList.remove('visible');
    setTimeout(() => toast.remove(), 300);
  }, 2500);
}

// ── Gallery item builder ──
function buildGalleryItem(img, delay) {
  const item = document.createElement('div');
  item.className = 'gallery-item';
  item.style.animationDelay = (delay * 0.05) + 's';

  const imgEl = document.createElement('img');
  imgEl.src = `/api/public/gallery/${img.id}/image`;
  imgEl.alt = img.prompt || '';
  imgEl.loading = 'lazy';
  item.appendChild(imgEl);

  const meta = document.createElement('div');
  meta.className = 'gallery-meta';

  const prompt = document.createElement('div');
  prompt.className = 'gallery-prompt';
  prompt.textContent = img.title || img.prompt || '';
  meta.appendChild(prompt);

  // Votes display + vote button
  const votesRow = document.createElement('div');
  votesRow.className = 'gallery-votes-row';

  const votesLabel = document.createElement('span');
  votesLabel.className = 'gallery-votes';
  votesLabel.textContent = (img.votes || 0) + ' ♥';
  votesRow.appendChild(votesLabel);

  const voteBtn = document.createElement('button');
  voteBtn.className = 'gallery-vote-btn' + (img.user_voted ? ' voted' : '');
  voteBtn.setAttribute('aria-label', 'Voter');
  voteBtn.textContent = img.user_voted ? '♥' : '♡';
  voteBtn.addEventListener('click', async (e) => {
    e.stopPropagation();
    if (!getJwt()) {
      showVoteToast('Connecte-toi via le chat pour voter');
      return;
    }
    try {
      const r = await authedFetch(`/api/public/gallery/${img.id}/vote`, { method: 'POST' });
      if (r.ok) {
        const result = await r.json();
        const current = parseInt(votesLabel.textContent, 10) || 0;
        voteBtn.classList.toggle('voted', result.voted);
        voteBtn.textContent = result.voted ? '♥' : '♡';
        votesLabel.textContent = (result.voted ? current + 1 : Math.max(0, current - 1)) + ' ♥';
      } else if (r.status === 401) {
        showVoteToast('Session expirée — reconnecte-toi dans le Chat');
      }
    } catch (_) {}
  });
  votesRow.appendChild(voteBtn);

  meta.appendChild(votesRow);
  item.appendChild(meta);

  item.addEventListener('click', () => openGalleryModal(img.id));
  return item;
}

// ── Load images ──
async function loadImages(grid, append) {
  const params = new URLSearchParams({
    limit: LIMIT,
    offset: _offset,
    sort_by: _sort,
  });
  if (_search.trim()) params.set('search', _search.trim());

  const res = await authedFetch('/api/public/gallery?' + params.toString())
    .then(r => r.json()).catch(() => ({ images: [] }));

  const images = res.images || [];
  if (!append) { grid.textContent = ''; }

  images.forEach((img, i) => {
    grid.appendChild(buildGalleryItem(img, append ? i : _offset + i));
  });

  _offset += images.length;
  return images.length === LIMIT;
}

// ── Mount ──
export function mount(el) {
  _container = el;
  _offset = 0;
  _search = '';
  el.textContent = '';

  const wrap = document.createElement('div');

  // Header arcade
  const head = document.createElement('div');
  const eyebrow = document.createElement('div');
  eyebrow.className = 'arc-eyebrow';
  eyebrow.textContent = 'CRÉATIONS · WALLY';
  const h2 = document.createElement('h2');
  h2.className = 'arc-h2';
  h2.textContent = 'GALERIE';
  const sub = document.createElement('div');
  sub.className = 'arc-sub';
  sub.textContent = 'les images générées par wally. votez pour vos préférées.';
  head.appendChild(eyebrow); head.appendChild(h2); head.appendChild(sub);
  wrap.appendChild(head);

  // Filters bar
  const filters = document.createElement('div');
  filters.className = 'gallery-filters';

  const filterDefs = [
    { label: 'Récentes', value: 'date' },
    { label: 'Populaires', value: 'votes' },
  ];

  const grid = document.createElement('div');
  grid.className = 'gallery-grid';

  let searchDebounce = null;

  // Search input
  const searchInput = document.createElement('input');
  searchInput.type = 'text';
  searchInput.className = 'gallery-search';
  searchInput.placeholder = 'Rechercher…';
  searchInput.setAttribute('aria-label', 'Rechercher dans la galerie');
  searchInput.addEventListener('input', () => {
    clearTimeout(searchDebounce);
    searchDebounce = setTimeout(() => {
      _search = searchInput.value;
      _offset = 0;
      loadImages(grid, false).then(hasMore => {
        loadMoreBtn.style.display = hasMore ? '' : 'none';
      });
    }, 300);
  });
  filters.appendChild(searchInput);

  filterDefs.forEach(({ label, value }) => {
    const btn = document.createElement('button');
    btn.className = 'filter-btn' + (value === _sort ? ' active' : '');
    btn.textContent = label;
    btn.addEventListener('click', () => {
      _sort = value;
      _offset = 0;
      filters.querySelectorAll('.filter-btn').forEach(b => b.classList.remove('active'));
      btn.classList.add('active');
      loadImages(grid, false).then(hasMore => {
        loadMoreBtn.style.display = hasMore ? '' : 'none';
      });
    });
    filters.appendChild(btn);
  });

  wrap.appendChild(filters);
  wrap.appendChild(grid);

  // Load more
  const loadMoreBtn = document.createElement('button');
  loadMoreBtn.className = 'load-more';
  loadMoreBtn.textContent = 'Charger plus';
  loadMoreBtn.addEventListener('click', () => {
    loadImages(grid, true).then(hasMore => {
      loadMoreBtn.style.display = hasMore ? '' : 'none';
    });
  });
  wrap.appendChild(loadMoreBtn);

  loadImages(grid, false).then(hasMore => {
    loadMoreBtn.style.display = hasMore ? '' : 'none';
  });

  el.appendChild(wrap);

  // Keyboard close
  document.addEventListener('keydown', _handleKeydown);
}

function _handleKeydown(e) {
  if (e.key === 'Escape') closeGalleryModal();
}

export function unmount() {
  _container = null;
  document.removeEventListener('keydown', _handleKeydown);
}
