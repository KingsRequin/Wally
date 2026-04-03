// public-ui/tabs/about.js

const PIPELINE_STEPS = [
  {
    label: 'Message',
    color: '#06b6d4',
    detail: 'Un message arrive de Discord ou Twitch. Il est normalisé, tagué avec la plateforme, l\'auteur, et le canal source.'
  },
  {
    label: 'Mémoire',
    color: '#a855f7',
    detail: 'Wally consulte sa mémoire vectorielle (Qdrant) pour trouver des souvenirs pertinents sur l\'utilisateur : faits, préférences, historique. Les scores de relation (confiance, affinité) sont aussi injectés.'
  },
  {
    label: 'Émotions',
    color: '#ef4444',
    detail: 'L\'état émotionnel actuel (5 émotions : colère, joie, curiosité, tristesse, ennui) influence le ton de la réponse. Les émotions décroissent naturellement dans le temps et varient selon les interactions.'
  },
  {
    label: 'Personnalité',
    color: '#eab308',
    detail: 'Les blocs de personnalité SOUL, IDENTITY, VOICE et COMPOSITES sont assemblés en prompt système. Des directives comportementales adaptées à l\'émotion dominante sont injectées dynamiquement.'
  },
  {
    label: 'LLM',
    color: '#22c55e',
    detail: 'Le modèle de langage (Claude ou GPT) génère une réponse en tenant compte de tout le contexte : mémoire, émotions, personnalité, historique de conversation, et instructions cibles.'
  },
  {
    label: 'Réponse',
    color: '#3b82f6',
    detail: 'La réponse est envoyée via l\'adaptateur approprié (Discord ou Twitch). En parallèle, les faits importants sont extraits et sauvegardés en mémoire pour les prochaines interactions.'
  },
];

const PILLARS = [
  {
    title: 'Mémoire vectorielle',
    color: '#a855f7',
    desc: 'Wally se souvient de chaque utilisateur à long terme grâce à Qdrant. Faits, préférences, historique — tout est encodé en embeddings et retrouvé par similarité sémantique.'
  },
  {
    title: 'Émotions en direct',
    color: '#ef4444',
    desc: 'Cinq émotions coexistent et fluctuent en temps réel. Elles influencent le ton des réponses, déclenchent des comportements spéciaux, et sont visibles sur l\'overlay OBS.'
  },
  {
    title: 'Personnalité profonde',
    color: '#eab308',
    desc: 'Une personnalité construite sur des blocs : âme, identité, voix, exemples. Les combinaisons d\'émotions créent des états composites avec des comportements uniques.'
  },
  {
    title: 'Journal quotidien',
    color: '#22c55e',
    desc: 'Chaque soir, Wally rédige un journal intime résumant sa journée : interactions marquantes, état émotionnel, pensées. Une mémoire narrative qui enrichit sa cohérence.'
  },
];

export function mount(el) {
  el.textContent = '';

  const wrap = document.createElement('div');

  // ── Pipeline ──
  const pipeTitle = document.createElement('h3');
  pipeTitle.style.cssText = 'font-size:0.75rem;text-transform:uppercase;letter-spacing:0.08em;color:rgba(255,255,255,0.4);margin-bottom:16px;';
  pipeTitle.textContent = 'Pipeline de traitement';
  wrap.appendChild(pipeTitle);

  const pipelineEl = document.createElement('div');
  pipelineEl.className = 'pipeline';

  const detailEl = document.createElement('div');
  detailEl.className = 'pipe-detail';

  let activeStep = null;

  PIPELINE_STEPS.forEach((step, i) => {
    const stepWrap = document.createElement('div');
    stepWrap.className = 'pipe-step';

    const node = document.createElement('div');
    node.className = 'pipe-node';
    node.textContent = step.label;
    node.style.borderColor = step.color + '66';
    node.style.color = step.color;
    node.style.background = step.color + '11';

    node.addEventListener('click', () => {
      if (activeStep) {
        activeStep.style.background = activeStep._origBg;
        activeStep.style.boxShadow = '';
      }
      node._origBg = step.color + '11';
      node.style.background = step.color + '22';
      node.style.boxShadow = '0 0 12px ' + step.color + '44';
      activeStep = node;
      detailEl.textContent = step.detail;
      detailEl.style.borderColor = step.color + '44';
      detailEl.style.animation = 'none';
      detailEl.offsetHeight;
      detailEl.style.animation = '';
    });

    stepWrap.appendChild(node);

    if (i < PIPELINE_STEPS.length - 1) {
      const arrow = document.createElement('span');
      arrow.className = 'pipe-arrow';
      arrow.textContent = '→';
      stepWrap.appendChild(arrow);
    }

    pipelineEl.appendChild(stepWrap);
  });

  wrap.appendChild(pipelineEl);
  wrap.appendChild(detailEl);

  // Activate first step by default
  const firstNode = pipelineEl.querySelector('.pipe-node');
  if (firstNode) firstNode.click();

  // ── Pillars ──
  const pillarsTitle = document.createElement('h3');
  pillarsTitle.style.cssText = 'font-size:0.75rem;text-transform:uppercase;letter-spacing:0.08em;color:rgba(255,255,255,0.4);margin-bottom:16px;';
  pillarsTitle.textContent = 'Les piliers de Wally';
  wrap.appendChild(pillarsTitle);

  const pillarsGrid = document.createElement('div');
  pillarsGrid.className = 'pillars-grid';

  PILLARS.forEach((pillar, i) => {
    const card = document.createElement('div');
    card.className = 'pillar-card';
    card.style.animationDelay = (i * 0.08) + 's';

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
