// public-ui/tabs/journal.js — arcade
import { parseInline, renderMarkdown } from '../markdown.js';

let _container = null;

const MONTH_SHORT = ['jan','fév','mar','avr','mai','jun','jul','aoû','sep','oct','nov','déc'];
const EMO_COLORS = { anger:'#ef4444', joy:'#eab308', curiosity:'#22c55e', sadness:'#3b82f6', boredom:'#a855f7' };
const BORDER_CYCLE = ['var(--yellow)','var(--cyan)','var(--pink)','var(--green)','var(--violet)'];
let _entryColorIdx = 0;

function formatDateShort(dateStr) {
  const d = new Date(dateStr + 'T00:00:00');
  return d.getDate() + ' ' + MONTH_SHORT[d.getMonth()];
}

function formatDateLong(dateStr) {
  const d = new Date(dateStr + 'T00:00:00');
  return d.toLocaleDateString('fr-FR', { weekday:'long', day:'numeric', month:'long', year:'numeric' });
}

// Extrait l'heure HHhMM depuis un ISO string UTC "2026-04-03T21:00:00"
// Traité comme UTC puis converti en heure locale du navigateur
function formatGenTime(isoStr) {
  if (!isoStr) return null;
  try {
    const d = new Date(isoStr + 'Z'); // force UTC parsing
    return d.toLocaleTimeString('fr-FR', { hour: '2-digit', minute: '2-digit' }).replace(':', 'h');
  } catch (_) {
    return null;
  }
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
    if (new RegExp(p.label, 'i').test(content)) badges.push(p);
  });
  return badges;
}

function renderEntryCard(entry) {
  const card = document.createElement('div');
  card.className = 'entry-card';
  card.style.borderLeftColor = BORDER_CYCLE[_entryColorIdx % BORDER_CYCLE.length];
  _entryColorIdx++;

  const header = document.createElement('div');
  header.className = 'entry-header';

  const left = document.createElement('div');
  const dateEl = document.createElement('div');
  dateEl.className = 'entry-date-text';
  dateEl.textContent = formatDateLong(entry.date);
  left.appendChild(dateEl);

  const subEl = document.createElement('div');
  subEl.className = 'entry-sub-text';
  const genTime = formatGenTime(entry.created_at);
  subEl.textContent = (entry.word_count || 0) + ' mots' + (genTime ? ' · généré à ' + genTime : '');
  left.appendChild(subEl);
  header.appendChild(left);

  const badges = document.createElement('div');
  badges.className = 'badges';
  detectEmoBadges(entry.content || '').forEach(b => {
    const span = document.createElement('span');
    span.className = 'badge';
    span.textContent = b.label;
    span.style.color = b.color;
    const hex = b.color.replace('#', '');
    const r = parseInt(hex.substring(0,2), 16);
    const g = parseInt(hex.substring(2,4), 16);
    const bl = parseInt(hex.substring(4,6), 16);
    span.style.borderColor = `rgba(${r},${g},${bl},0.3)`;
    span.style.background  = `rgba(${r},${g},${bl},0.08)`;
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

function buildHeader() {
  const head = document.createElement('div');
  const eyebrow = document.createElement('div');
  eyebrow.className = 'arc-eyebrow';
  eyebrow.textContent = 'JOURNAL INTIME · WALLY';
  const h2 = document.createElement('h2');
  h2.className = 'arc-h2';
  h2.textContent = 'JOURNAL';
  const sub = document.createElement('div');
  sub.className = 'arc-sub';
  sub.textContent = 'chaque soir à 21h, wally écrit sa journée.';
  head.appendChild(eyebrow); head.appendChild(h2); head.appendChild(sub);
  return head;
}

export function mount(el) {
  _container = el;
  _entryColorIdx = 0;
  el.textContent = '';
  el.appendChild(buildHeader());

  fetch('/api/public/journal?limit=30')
    .then(r => r.json())
    .then(data => {
      const entries = data.entries || [];
      if (!entries.length) {
        const empty = document.createElement('div');
        empty.className = 'empty-state arc-card';
        empty.textContent = 'Le journal est généré chaque soir à 21h00. Aucune entrée pour le moment.';
        el.appendChild(empty);
        return;
      }

      const wrap = document.createElement('div');
      wrap.className = 'arc-card';

      const tlScroll = document.createElement('div');
      tlScroll.className = 'tl-scroll';

      const tlRow = document.createElement('div');
      tlRow.className = 'tl-row';

      const entryArea = document.createElement('div');
      entryArea.className = 'entry-area';

      let activeItem = null;

      // entries DESC → reverse pour afficher oldest→newest gauche→droite
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

      // Scroll timeline vers l'entrée la plus récente (droite)
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
