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

// ── Discord Markdown → DOM ──
// Supports: # h1-3, **bold**, *italic*, _italic_, ~~strike~~, `code`, > blockquote
function parseInline(text, container) {
  // Split text by inline tokens using matchAll (avoids exec/shell confusion)
  const INLINE = /(\*\*(.+?)\*\*|\*(.+?)\*|_(.+?)_|~~(.+?)~~|`(.+?)`)/gs;
  let last = 0;
  const tokens = [];
  for (const m of text.matchAll(INLINE)) {
    if (m.index > last) tokens.push({ type: 'text', val: text.slice(last, m.index) });
    if (m[2] !== undefined)      tokens.push({ type: 'strong', val: m[2] });
    else if (m[3] !== undefined) tokens.push({ type: 'em',     val: m[3] });
    else if (m[4] !== undefined) tokens.push({ type: 'em',     val: m[4] });
    else if (m[5] !== undefined) tokens.push({ type: 'del',    val: m[5] });
    else if (m[6] !== undefined) tokens.push({ type: 'code',   val: m[6] });
    last = m.index + m[0].length;
  }
  if (last < text.length) tokens.push({ type: 'text', val: text.slice(last) });

  for (const tok of tokens) {
    if (tok.type === 'text') {
      container.appendChild(document.createTextNode(tok.val));
    } else if (tok.type === 'strong') {
      const el = document.createElement('strong'); el.textContent = tok.val; container.appendChild(el);
    } else if (tok.type === 'em') {
      const el = document.createElement('em'); el.textContent = tok.val; container.appendChild(el);
    } else if (tok.type === 'del') {
      const el = document.createElement('s'); el.textContent = tok.val; container.appendChild(el);
    } else if (tok.type === 'code') {
      const el = document.createElement('code'); el.className = 'md-code'; el.textContent = tok.val; container.appendChild(el);
    }
  }
}

function renderMarkdown(text, container) {
  const HEADING = /^(#{1,3})\s+(.+)$/;
  const SMALL_HEADING = /^-#\s+(.+)$/;
  const BLOCKQUOTE = /^>\s?(.*)/;

  const blocks = text.split(/\n{2,}/);
  for (const block of blocks) {
    if (!block.trim()) continue;
    const lines = block.split('\n');
    const firstLine = lines[0];
    const hMatch = firstLine.match(HEADING);
    const smMatch = firstLine.match(SMALL_HEADING);

    if (smMatch) {
      const el = document.createElement('div');
      el.className = 'md-small-heading';
      parseInline(smMatch[1], el);
      container.appendChild(el);
      if (lines.length > 1) {
        const p = document.createElement('p');
        lines.slice(1).forEach((line, i) => {
          parseInline(line, p);
          if (i < lines.length - 2) p.appendChild(document.createElement('br'));
        });
        container.appendChild(p);
      }
    } else if (hMatch) {
      const level = Math.min(hMatch[1].length + 2, 6); // h3-h5
      const el = document.createElement('h' + level);
      el.className = 'md-heading';
      parseInline(hMatch[2], el);
      container.appendChild(el);
      if (lines.length > 1) {
        const p = document.createElement('p');
        lines.slice(1).forEach((line, i) => {
          parseInline(line, p);
          if (i < lines.length - 2) p.appendChild(document.createElement('br'));
        });
        container.appendChild(p);
      }
    } else if (lines.every(l => BLOCKQUOTE.test(l))) {
      const bq = document.createElement('blockquote');
      bq.className = 'md-blockquote';
      lines.forEach((line, i) => {
        const m = line.match(BLOCKQUOTE);
        parseInline(m ? m[1] : line, bq);
        if (i < lines.length - 1) bq.appendChild(document.createElement('br'));
      });
      container.appendChild(bq);
    } else {
      const p = document.createElement('p');
      lines.forEach((line, i) => {
        parseInline(line, p);
        if (i < lines.length - 1) p.appendChild(document.createElement('br'));
      });
      container.appendChild(p);
    }
  }
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
  subEl.textContent = (entry.word_count || 0) + ' mots · généré à 21h00';
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
  renderMarkdown(entry.content || '', body);
  card.appendChild(body);

  if (entry.has_chart) {
    const chartWrap = document.createElement('div');
    chartWrap.className = 'entry-chart';
    const chartImg = document.createElement('img');
    chartImg.src = `/api/public/journal/${entry.date}/chart`;
    chartImg.alt = 'Historique des émotions';
    chartImg.loading = 'lazy';
    chartWrap.appendChild(chartImg);
    card.appendChild(chartWrap);
  }

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
        empty.textContent = "Le journal est généré chaque soir à 21h00. Aucune entrée pour le moment.";
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
