// public-ui/tabs/community.js — arcade
// Cartes chaîne/réveil + classement des viewers. (Graphe social retiré.)

function escapeHtml(s) {
  return String(s).replace(/[&<>"']/g, c => ({ '&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;' }[c]));
}

function buildHeader() {
  const head = document.createElement('div');
  const eyebrow = document.createElement('div');
  eyebrow.className = 'arc-eyebrow';
  eyebrow.textContent = 'LES GENS · WALLY';
  const h2 = document.createElement('h2');
  h2.className = 'arc-h2';
  h2.textContent = 'COMMUNAUTÉ';
  const sub = document.createElement('div');
  sub.className = 'arc-sub';
  sub.textContent = 'qui parle à wally, et ce qu\'il pense d\'eux.';
  head.appendChild(eyebrow); head.appendChild(h2); head.appendChild(sub);
  return head;
}

function buildTopCards() {
  const grid = document.createElement('div');
  grid.className = 'arc-grid';
  grid.style.gridTemplateColumns = 'repeat(auto-fit,minmax(260px,1fr))';
  grid.style.marginBottom = '18px';

  const chan = document.createElement('div');
  chan.className = 'arc-card';
  const chanLbl = document.createElement('div');
  chanLbl.className = 'arc-stat-label';
  chanLbl.style.cssText = 'font-size:11px;color:var(--yellow);';
  chanLbl.textContent = 'LA CHAÎNE';
  const chanVal = document.createElement('div');
  chanVal.style.cssText = 'font-size:24px;color:var(--cyan);margin-top:12px;';
  chanVal.textContent = 'twitch.tv/Azrael_TTV';
  chan.appendChild(chanLbl); chan.appendChild(chanVal);
  grid.appendChild(chan);

  const wake = document.createElement('div');
  wake.className = 'arc-card';
  const wakeLbl = document.createElement('div');
  wakeLbl.className = 'arc-stat-label';
  wakeLbl.style.cssText = 'font-size:11px;color:var(--yellow);';
  wakeLbl.textContent = 'POUR LE RÉVEILLER';
  const wakeVal = document.createElement('div');
  wakeVal.style.cssText = 'font-size:24px;color:var(--pink);margin-top:12px;';
  wakeVal.textContent = '@WallyTeBully';
  const wakeSub = document.createElement('div');
  wakeSub.style.cssText = 'font-size:18px;color:var(--muted);margin-top:6px;';
  wakeSub.textContent = 'mentionne-le dans le chat, il finira par répondre.';
  wake.appendChild(wakeLbl); wake.appendChild(wakeVal); wake.appendChild(wakeSub);
  grid.appendChild(wake);

  return grid;
}

async function loadRanking(host) {
  let ranking = [];
  try {
    ranking = (await (await fetch('/api/public/community/ranking')).json()).ranking || [];
  } catch (_) {}
  if (!ranking.length) {
    host.innerHTML = '<div class="empty-state">Pas encore de classement.</div>';
    return;
  }
  host.innerHTML = ranking.map((r, i) => {
    const isMax = r.score === 'MAX';
    const rk = isMax ? '∞' : '#' + (i + 1);
    const rkCol = isMax ? 'var(--pink)' : (i === 0 ? 'var(--yellow)' : 'var(--muted)');
    const nameCol = isMax ? 'var(--yellow)' : 'var(--text)';
    const scoreCol = isMax ? 'var(--pink)' : 'var(--cyan)';
    return `<div class="feed-row" style="font-size:22px;align-items:center">
      <span style="color:${rkCol};width:46px;flex:none">${escapeHtml(rk)}</span>
      <span style="flex:1;color:${nameCol}">${escapeHtml(r.name)}</span>
      <span style="color:var(--muted);flex:none">${escapeHtml(r.trait)}</span>
      <span style="color:${scoreCol};width:80px;text-align:right;flex:none">${escapeHtml(r.score)}</span>
    </div>`;
  }).join('');
}

function buildRankingCard() {
  const card = document.createElement('div');
  card.className = 'arc-card';
  card.style.marginBottom = '18px';
  const title = document.createElement('div');
  title.className = 'arc-stat-label';
  title.style.cssText = 'font-size:11px;color:var(--yellow);margin-bottom:14px;';
  title.textContent = 'CLASSEMENT DES VIEWERS';
  card.appendChild(title);
  const list = document.createElement('div');
  list.innerHTML = '<div class="empty-state">Chargement…</div>';
  card.appendChild(list);
  loadRanking(list);
  return card;
}

export function mount(el) {
  el.textContent = '';
  el.appendChild(buildHeader());
  el.appendChild(buildTopCards());
  el.appendChild(buildRankingCard());
}

export function unmount() {}
