// public-ui/tabs/journal.js

let _container = null;

const MONTH_SHORT = ['jan','fév','mar','avr','mai','jun','jul','aoû','sep','oct','nov','déc'];
const EMO_COLORS = { anger:'#ef4444', joy:'#eab308', curiosity:'#22c55e', sadness:'#3b82f6', boredom:'#a855f7' };

function formatDateShort(dateStr) {
  const d = new Date(dateStr + 'T00:00:00');
  return d.getDate() + ' ' + MONTH_SHORT[d.getMonth()];
}

function formatDateLong(dateStr) {
  const d = new Date(dateStr + 'T00:00:00');
  return d.toLocaleDateString('fr-FR', { weekday:'long', day:'numeric', month:'long', year:'numeric' });
}

function detectEmoBadges(content) {
  const badges = [];
  const patterns = [
    { key: 'anger',     color: EMO_COLORS.anger,     label: 'Colère' },
    { key: 'joy',       color: EMO_COLORS.joy,        label: 'Joie' },
    { key: 'curiosity', color: EMO_COLORS.curiosity,  label: 'Curiosité' },
    { key: 'sadness',   color: EMO_COLORS.sadness,    label: 'Tristesse' },
    { key: 'boredom',   color: EMO_COLORS.boredom,    label: 'Ennui' },
  ];
  patterns.forEach(p => {
    const re = new RegExp(p.label, 'i');
    if (re.test(content)) badges.push(p);
  });
  return badges;
}

function renderEntryCard(entry) {
  const card = document.createElement('div');
  card.className = 'entry-card';

  const header = document.createElement('div');
  header.className = 'entry-header';

  const left = document.createElement('div');
  const dateEl = document.createElement('div');
  dateEl.className = 'entry-date-text';
  dateEl.textContent = formatDateLong(entry.date);
  left.appendChild(dateEl);
  const subEl = document.createElement('div');
  subEl.className = 'entry-sub-text';
  subEl.textContent = (entry.word_count || 0) + ' mots · généré à 23h00';
  left.appendChild(subEl);
  header.appendChild(left);

  const badges = document.createElement('div');
  badges.className = 'badges';
  const detectedBadges = detectEmoBadges(entry.content || '');
  detectedBadges.forEach(b => {
    const span = document.createElement('span');
    span.className = 'badge';
    span.textContent = b.label;
    span.style.color = b.color;
    // Convert hex to rgba for border and background
    const hex = b.color.replace('#', '');
    const r = parseInt(hex.substring(0,2), 16);
    const g = parseInt(hex.substring(2,4), 16);
    const bl = parseInt(hex.substring(4,6), 16);
    span.style.borderColor = `rgba(${r},${g},${bl},0.3)`;
    span.style.background = `rgba(${r},${g},${bl},0.08)`;
    badges.appendChild(span);
  });
  header.appendChild(badges);
  card.appendChild(header);

  const body = document.createElement('div');
  body.className = 'entry-body';
  const paragraphs = (entry.content || '').split('\n\n').filter(Boolean);
  if (paragraphs.length > 1) {
    paragraphs.forEach(text => {
      const p = document.createElement('p');
      p.textContent = text;
      body.appendChild(p);
    });
  } else {
    const p = document.createElement('p');
    p.textContent = entry.content || '';
    body.appendChild(p);
  }
  card.appendChild(body);
  return card;
}

export function mount(el) {
  _container = el;
  el.textContent = '';

  fetch('/api/public/journal?limit=30')
    .then(r => r.json())
    .then(data => {
      const entries = data.entries || [];
      if (!entries.length) {
        const empty = document.createElement('div');
        empty.className = 'empty-state glass';
        empty.style.padding = '40px';
        empty.textContent = "Aucune entrée de journal pour l'instant.";
        el.appendChild(empty);
        return;
      }

      const wrap = document.createElement('div');
      wrap.className = 'glass';
      wrap.style.padding = '20px';

      const tlScroll = document.createElement('div');
      tlScroll.className = 'tl-scroll';

      const tlRow = document.createElement('div');
      tlRow.className = 'tl-row';

      const entryArea = document.createElement('div');
      entryArea.className = 'entry-area';

      let activeItem = null;

      // entries are DESC (newest first) — reverse to display oldest→newest left→right
      const orderedEntries = [...entries].reverse();

      orderedEntries.forEach((entry, idx) => {
        const isLast = idx === orderedEntries.length - 1;
        const item = document.createElement('div');
        item.className = 'tl-item' + (isLast ? ' active' : '');

        const dot = document.createElement('div');
        dot.className = 'tl-dot';
        item.appendChild(dot);

        const dateEl = document.createElement('div');
        dateEl.className = 'tl-date';
        dateEl.textContent = formatDateShort(entry.date) + (isLast ? ' ✦' : '');
        item.appendChild(dateEl);

        item.addEventListener('click', () => {
          if (activeItem) activeItem.classList.remove('active');
          item.classList.add('active');
          activeItem = item;
          entryArea.textContent = '';
          entryArea.appendChild(renderEntryCard(entry));
        });

        tlRow.appendChild(item);

        if (isLast) {
          activeItem = item;
          entryArea.appendChild(renderEntryCard(entry));
        }
      });

      tlScroll.appendChild(tlRow);
      wrap.appendChild(tlScroll);
      wrap.appendChild(entryArea);
      el.appendChild(wrap);

      // Scroll timeline to show most recent (rightmost) entry
      setTimeout(() => { tlScroll.scrollLeft = tlScroll.scrollWidth; }, 50);
    })
    .catch(() => {
      const err = document.createElement('div');
      err.className = 'empty-state';
      err.textContent = 'Impossible de charger le journal.';
      el.appendChild(err);
    });
}

export function unmount() {
  _container = null;
}
