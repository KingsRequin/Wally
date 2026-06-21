// public-ui/tabs/about.js — arcade

const PIPELINE_STEPS = [
  {
    label: 'Mention',
    color: 'var(--pink)',
    detail: 'Un message arrive de Discord ou Twitch. Il est normalisé, la langue détectée automatiquement (langdetect), tagué avec la plateforme, l\'auteur, le canal source et un horodatage. Les messages contenant des images reçoivent une description IA en arrière-plan. Les bots connus et les comptes sans badge humain sont ignorés.'
  },
  {
    label: 'Contexte',
    color: 'var(--cyan)',
    detail: 'Wally assemble le contexte de la conversation : fenêtre glissante des derniers messages, jour de la semaine, état du stream s\'il est en live. Le tout est combiné à la personnalité et aux émotions pour construire un prompt système cohérent avant d\'interroger le modèle.'
  },
  {
    label: 'Mémoire',
    color: 'var(--violet)',
    detail: 'Wally consulte sa mémoire vectorielle (Qdrant). Il retrouve les souvenirs les plus pertinents sur l\'utilisateur : faits biographiques (FAIT), préférences (PREF), langue habituelle (LANG), et données relationnelles (REL). Les scores de confiance et d\'affinité sont injectés séparément. Un budget de tokens (800) priorise les souvenirs les plus utiles.'
  },
  {
    label: 'Réponse',
    color: 'var(--green)',
    detail: 'Le LLM (DeepSeek) reçoit le prompt système complet (personnalité + émotions + mémoire + contexte) et l\'historique glissant, et peut appeler des outils (rappels, notes). La réponse part via l\'adaptateur approprié. En arrière-plan : le FactExtractor stocke les faits mémorables dans Qdrant, les émotions sont mises à jour (NRCLex), et les coûts LLM sont enregistrés.'
  },
];

const PILLARS = [
  {
    title: 'Mémoire vectorielle',
    color: 'var(--violet)',
    desc: 'Wally se souvient de chaque utilisateur à long terme grâce à Qdrant. Faits, préférences, langue, relation — tout est encodé en embeddings et retrouvé par similarité sémantique. Budget priorisé par catégorie : biographie > relation > questions en attente > blagues > opinions > mentions tierces.'
  },
  {
    title: 'Émotions en direct',
    color: 'var(--pink)',
    desc: 'Cinq émotions coexistent et fluctuent en temps réel via décroissance exponentielle, suppression mutuelle et compétition. Elles influencent directement le ton des réponses, déclenchent des comportements spéciaux (mode silence), et sont visibles en direct sur cet écran et sur l\'overlay OBS du stream.'
  },
  {
    title: 'Personnalité profonde',
    color: 'var(--yellow)',
    desc: 'Une personnalité construite sur quatre blocs Markdown (SOUL, IDENTITY, VOICE, EXEMPLES) et enrichie par des états émotionnels composites. Les combinaisons de deux émotions dominantes activent des directives comportementales uniques — il existe plus de 10 états composites distincts.'
  },
  {
    title: 'Journal quotidien',
    color: 'var(--green)',
    desc: 'Chaque soir à 21h00, Wally rédige un journal intime résumant sa journée : interactions marquantes, état émotionnel, pensées, visites Twitch. Ce journal narratif enrichit la cohérence de la personnalité dans le temps et est consultable ici.'
  },
  {
    title: 'Multi-plateforme',
    color: 'var(--violet)',
    desc: 'Un seul processus asyncio gère Discord et Twitch simultanément via deux adaptateurs indépendants. Les mémoires, émotions et la personnalité sont partagées entre les deux plateformes — Wally reste cohérent qu\'il soit en train de streamer ou de discuter sur Discord.'
  },
];

// Pile technique réelle (corrige les mensonges du mockup)
const TECH = [
  ['Python / asyncio', 'var(--cyan)'],
  ['DeepSeek', 'var(--yellow)'],
  ['aiosqlite', 'var(--green)'],
  ['Qdrant', 'var(--pink)'],
  ['discord.py', 'var(--cyan)'],
  ['twitchio', 'var(--violet)'],
];

function sectionTitle(text) {
  const t = document.createElement('div');
  t.className = 'arc-stat-label';
  t.style.cssText = 'font-size:11px;color:var(--yellow);margin:0 0 14px;';
  t.textContent = text;
  return t;
}

export function mount(el) {
  el.textContent = '';

  const wrap = document.createElement('div');

  // ── Header ──
  const head = document.createElement('div');
  const eyebrow = document.createElement('div');
  eyebrow.className = 'arc-eyebrow';
  eyebrow.textContent = 'LA NOTICE · WALLY';
  const h2 = document.createElement('h2');
  h2.className = 'arc-h2';
  h2.textContent = 'À PROPOS';
  const sub = document.createElement('div');
  sub.className = 'arc-sub';
  sub.textContent = 'un bot qui se souvient, qui ressent, et qui répond "feur".';
  head.appendChild(eyebrow); head.appendChild(h2); head.appendChild(sub);
  wrap.appendChild(head);

  // ── Description ──
  const descCard = document.createElement('div');
  descCard.className = 'arc-card';
  descCard.style.marginBottom = '18px';
  const descText = document.createElement('div');
  descText.style.cssText = 'font-size:20px;color:var(--text);line-height:1.5;';
  descText.textContent = 'Wally est un assistant IA pour Discord et Twitch doté d\'une personnalité persistante, d\'une mémoire à long terme et d\'un système émotionnel en temps réel. Il ne se contente pas de répondre — il se souvient, il ressent, il évolue au fil des interactions. Construit sur un monolithe Python asyncio, propulsé par DeepSeek, avec une mémoire vectorielle (Qdrant).';
  descCard.appendChild(descText);
  wrap.appendChild(descCard);

  // ── Le gag officiel ──
  const gagCard = document.createElement('div');
  gagCard.className = 'arc-card';
  gagCard.style.cssText = 'margin-bottom:18px;border-left:6px solid var(--pink);';
  gagCard.appendChild(sectionTitle('LE GAG OFFICIEL'));
  const gagBody = document.createElement('div');
  gagBody.style.cssText = 'font-size:22px;color:var(--text);';
  const q = document.createElement('span'); q.style.color = 'var(--muted2)'; q.textContent = 'quoi ';
  const arrow = document.createElement('span'); arrow.style.color = 'var(--muted)'; arrow.textContent = '→ ';
  const feur = document.createElement('span'); feur.style.color = 'var(--yellow)'; feur.textContent = 'feur.';
  gagBody.appendChild(q); gagBody.appendChild(arrow); gagBody.appendChild(feur);
  gagCard.appendChild(gagBody);
  wrap.appendChild(gagCard);

  // ── Pipeline « comment il fonctionne » ──
  const pipeCard = document.createElement('div');
  pipeCard.className = 'arc-card';
  pipeCard.style.marginBottom = '18px';
  pipeCard.appendChild(sectionTitle('COMMENT IL FONCTIONNE'));

  const pipelineEl = document.createElement('div');
  pipelineEl.className = 'pipeline';

  const detailEl = document.createElement('div');
  detailEl.className = 'pipe-detail';

  let activeStep = null;

  PIPELINE_STEPS.forEach((step, i) => {
    const node = document.createElement('div');
    node.className = 'pipe-node';
    node.textContent = step.label;
    node.style.borderColor = step.color;
    node.style.color = step.color;

    node.addEventListener('click', () => {
      if (activeStep) activeStep.style.background = 'transparent';
      node.style.background = 'rgba(124,77,255,.18)';
      activeStep = node;
      detailEl.textContent = step.detail;
    });

    pipelineEl.appendChild(node);

    if (i < PIPELINE_STEPS.length - 1) {
      const arrowEl = document.createElement('span');
      arrowEl.className = 'pipe-arrow';
      arrowEl.textContent = '→';
      pipelineEl.appendChild(arrowEl);
    }
  });

  pipeCard.appendChild(pipelineEl);
  pipeCard.appendChild(detailEl);
  wrap.appendChild(pipeCard);

  // Activate first step by default
  const firstNode = pipelineEl.querySelector('.pipe-node');
  if (firstNode) firstNode.click();

  // ── Ce qu'il retient / ignore ──
  const memGrid = document.createElement('div');
  memGrid.className = 'arc-grid';
  memGrid.style.cssText = 'grid-template-columns:repeat(auto-fit,minmax(280px,1fr));margin-bottom:18px;';

  const keepCard = document.createElement('div');
  keepCard.className = 'arc-card';
  keepCard.style.borderLeft = '6px solid var(--green)';
  keepCard.appendChild(sectionTitle('CE QU\'IL RETIENT'));
  const keepList = document.createElement('div');
  keepList.style.cssText = 'font-size:19px;color:var(--muted2);line-height:1.6;';
  ['tes faits biographiques', 'tes préférences', 'ta langue habituelle', 'votre relation (confiance, affinité)'].forEach(t => {
    const row = document.createElement('div');
    row.textContent = '› ' + t;
    keepList.appendChild(row);
  });
  keepCard.appendChild(keepList);
  memGrid.appendChild(keepCard);

  const ignoreCard = document.createElement('div');
  ignoreCard.className = 'arc-card';
  ignoreCard.style.borderLeft = '6px solid var(--muted)';
  ignoreCard.appendChild(sectionTitle('CE QU\'IL IGNORE'));
  const ignoreList = document.createElement('div');
  ignoreList.style.cssText = 'font-size:19px;color:var(--muted2);line-height:1.6;';
  ['les messages trop courts', 'les emojis seuls et les interjections', 'les GIF et liens média', 'les bots et comptes non humains'].forEach(t => {
    const row = document.createElement('div');
    row.textContent = '× ' + t;
    ignoreList.appendChild(row);
  });
  ignoreCard.appendChild(ignoreList);
  memGrid.appendChild(ignoreCard);

  wrap.appendChild(memGrid);

  // ── Sous le capot (stack corrigée) ──
  const techCard = document.createElement('div');
  techCard.className = 'arc-card';
  techCard.style.marginBottom = '18px';
  techCard.appendChild(sectionTitle('SOUS LE CAPOT'));
  const techRow = document.createElement('div');
  techRow.className = 'about-chips';
  TECH.forEach(([name, color]) => {
    const chip = document.createElement('span');
    chip.className = 'about-chip';
    chip.style.borderColor = color;
    chip.style.color = color;
    chip.textContent = name;
    techRow.appendChild(chip);
  });
  techCard.appendChild(techRow);
  wrap.appendChild(techCard);

  // ── Piliers ──
  const pillarsTitle = sectionTitle('LES PILIERS DE WALLY');
  pillarsTitle.style.margin = '0 0 14px';
  wrap.appendChild(pillarsTitle);

  const pillarsGrid = document.createElement('div');
  pillarsGrid.className = 'pillars-grid';

  PILLARS.forEach((pillar) => {
    const card = document.createElement('div');
    card.className = 'arc-card';

    const titleEl = document.createElement('div');
    titleEl.className = 'pillar-title';
    titleEl.style.color = pillar.color;
    titleEl.textContent = pillar.title;
    card.appendChild(titleEl);

    const descEl = document.createElement('div');
    descEl.className = 'pillar-desc';
    descEl.textContent = pillar.desc;
    card.appendChild(descEl);

    pillarsGrid.appendChild(card);
  });

  wrap.appendChild(pillarsGrid);
  el.appendChild(wrap);
}

export function unmount() {}
