// public-ui/tabs/gallery.js
import { openModal } from '../app.js';

let _container = null;
let _sort = 'date';
let _offset = 0;
const LIMIT = 24;

function buildGalleryItem(img, delay) {
  const item = document.createElement('div');
  item.className = 'gallery-item';
  item.style.animationDelay = (delay * 0.05) + 's';

  const imgEl = document.createElement('img');
  imgEl.src = img.url;
  imgEl.alt = img.prompt || '';
  imgEl.loading = 'lazy';
  item.appendChild(imgEl);

  const overlay = document.createElement('div');
  overlay.className = 'gallery-overlay';

  const prompt = document.createElement('div');
  prompt.className = 'gallery-prompt';
  prompt.textContent = img.prompt || '';
  overlay.appendChild(prompt);

  const votes = document.createElement('div');
  votes.className = 'gallery-votes';
  votes.textContent = (img.votes || 0) + ' votes';
  overlay.appendChild(votes);

  item.appendChild(overlay);

  item.addEventListener('click', () => openModal(img.url, img.prompt || ''));
  return item;
}

async function loadImages(grid, append) {
  const res = await fetch(`/api/public/gallery?limit=${LIMIT}&offset=${_offset}&sort=${_sort}`)
    .then(r => r.json())
    .catch(() => ({ images: [] }));

  const images = res.images || [];
  if (!append) { grid.textContent = ''; }

  images.forEach((img, i) => {
    grid.appendChild(buildGalleryItem(img, append ? i : _offset + i));
  });

  _offset += images.length;
  return images.length === LIMIT;
}

export function mount(el) {
  _container = el;
  _offset = 0;
  el.textContent = '';

  const wrap = document.createElement('div');

  // Filters
  const filters = document.createElement('div');
  filters.className = 'gallery-filters';

  const filterDefs = [
    { label: 'Récentes', value: 'date' },
    { label: 'Populaires', value: 'votes' },
  ];

  const grid = document.createElement('div');
  grid.className = 'gallery-grid';

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
}

export function unmount() {
  _container = null;
}
