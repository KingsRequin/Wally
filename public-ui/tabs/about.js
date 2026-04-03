// public-ui/tabs/about.js

const PIPELINE_STEPS = [
  {
    label: 'Message',
    color: '#06b6d4',
    detail: 'Un message arrive de Discord ou Twitch. Il est normalisé, la langue détectée automatiquement (langdetect), tagué avec la plateforme, l\'auteur, le canal source et un horodatage. Les messages contenant des images reçoivent une description IA en arrière-plan. Les bots connus et les comptes sans badge humain sont ignorés.'
  },
  {
    label: 'Mémoire',
    color: '#a855f7',
    detail: 'Wally consulte sa mémoire vectorielle (Qdrant) via embeddings OpenAI. Il retrouve les souvenirs les plus pertinents sur l\'utilisateur : faits biographiques (FAIT), préférences (PREF), langue habituelle (LANG), et données relationnelles (REL). Les scores de confiance et d\'affinité sont injectés séparément. Un budget de tokens (800) priorise les souvenirs les plus utiles. Un rappel spontané peut se déclencher aléatoirement si une mémoire dépasse le seuil de pertinence.'
  },
  {
    label: 'Émotions',
    color: '#ef4444',
    detail: 'Cinq émotions coexistent : colère, joie, curiosité, tristesse, ennui. Chacune est un float 0–1 avec décroissance exponentielle propre (λ par émotion). Elles se suppriment mutuellement (joie atténue colère × 0,8, etc.) et entrent en compétition (−5 % mutuel si ≥ 0,3). La colère élevée déclenche un mode silence : Wally ne répond plus que par réactions emoji. L\'ennui monte linéairement en cas d\'inactivité prolongée.'
  },
  {
    label: 'Personnalité',
    color: '#eab308',
    detail: 'Quatre blocs chargés depuis des fichiers Markdown : SOUL (philosophie profonde), IDENTITY (qui est Wally), VOICE (style d\'expression), EXEMPLES (exemples de réponses). L\'émotion dominante injecte des directives comportementales spécifiques. Si deux émotions dépassent 0,4 simultanément, un bloc COMPOSITE est activé à la place (ex : colère + joie → énergie agressive et sarcastique). Les directives varient aussi selon le jour de la semaine.'
  },
  {
    label: 'LLM',
    color: '#22c55e',
    detail: 'Couche multi-provider : Claude (Anthropic) ou GPT (OpenAI) selon la configuration. Pour Claude : prompt caching, mode thinking adaptatif, tool use avec blocs thinking préservés. Pour GPT o1/o3/o4 : Responses API, reasoning_effort sans max_output_tokens. Le LLM reçoit le prompt système complet (personnalité + émotions + mémoire + contexte), l\'historique de conversation glissant, et peut appeler des outils (rappels, notes, recherche mémoire).'
  },
  {
    label: 'Réponse',
    color: '#3b82f6',
    detail: 'La réponse est envoyée via l\'adaptateur approprié (Discord ou Twitch). En parallèle (arrière-plan) : le FactExtractor analyse le message pour en extraire des faits mémorables et les stocker dans Qdrant ; les émotions sont mises à jour selon l\'analyse de sentiment NRCLex ; les coûts LLM sont enregistrés en base. Des questions de suivi peuvent être générées pour enrichir la mémoire lors des prochaines interactions.'
  },
];

const PILLARS = [
  {
    title: 'Mémoire vectorielle',
    color: '#a855f7',
    desc: 'Wally se souvient de chaque utilisateur à long terme grâce à Qdrant. Faits, préférences, langue, relation — tout est encodé en embeddings OpenAI et retrouvé par similarité sémantique. Budget priorisé par catégorie : biographie > relation > questions en attente > blagues > opinions > mentions tierces.'
  },
  {
    title: 'Émotions en direct',
    color: '#ef4444',
    desc: 'Cinq émotions coexistent et fluctuent en temps réel via décroissance exponentielle, suppression mutuelle et compétition. Elles influencent directement le ton des réponses, déclenchent des comportements spéciaux (mode silence), et sont visibles en direct sur cet écran et sur l\'overlay OBS du stream.'
  },
  {
    title: 'Personnalité profonde',
    color: '#eab308',
    desc: 'Une personnalité construite sur quatre blocs Markdown (SOUL, IDENTITY, VOICE, EXEMPLES) et enrichie par des états émotionnels composites. Les combinaisons de deux émotions dominantes activent des directives comportementales uniques — il existe plus de 10 états composites distincts.'
  },
  {
    title: 'Journal quotidien',
    color: '#22c55e',
    desc: 'Chaque soir à 21h00, Wally rédige un journal intime résumant sa journée : interactions marquantes, état émotionnel, pensées, visites Twitch. Ce journal narratif enrichit la cohérence de la personnalité dans le temps et est consultable ici.'
  },
  {
    title: 'Graphe social',
    color: '#06b6d4',
    desc: 'Un graphe de connaissances (Neo4j + Graphiti) modélise les relations entre utilisateurs, entités et événements. Les signaux sociaux (mentions, co-présence, interactions fréquentes) alimentent un score d\'affinité dynamique entre Wally et chaque membre de la communauté.'
  },
  {
    title: 'Multi-plateforme',
    color: '#3b82f6',
    desc: 'Un seul processus asyncio gère Discord et Twitch simultanément via deux adaptateurs indépendants. Les mémoires, émotions et la personnalité sont partagées entre les deux plateformes — Wally reste cohérent qu\'il soit en train de streamer ou de discuter sur Discord.'
  },
];

export function mount(el) {
  el.textContent = '';

  const wrap = document.createElement('div');

  // ── Header ──
  const header = document.createElement('div');
  header.className = 'glass';
  header.style.cssText = 'padding:24px 28px;margin-bottom:20px;display:flex;align-items:center;gap:24px;';

  const headerText = document.createElement('div');
  const headerTitle = document.createElement('div');
  headerTitle.style.cssText = 'font-size:1.3rem;font-weight:700;margin-bottom:8px;';
  headerTitle.textContent = 'Wally';
  headerText.appendChild(headerTitle);
  const headerDesc = document.createElement('div');
  headerDesc.style.cssText = 'font-size:0.85rem;color:rgba(255,255,255,0.55);line-height:1.65;max-width:680px;';
  headerDesc.textContent = 'Wally est un assistant IA pour Discord et Twitch doté d\'une personnalité persistante, d\'une mémoire à long terme et d\'un système émotionnel en temps réel. Il ne se contente pas de répondre — il se souvient, il ressent, il évolue au fil des interactions. Construit sur un monolithe Python asyncio avec une couche LLM multi-provider (Claude · GPT), une mémoire vectorielle (Qdrant) et un graphe de connaissances (Neo4j).';
  headerText.appendChild(headerDesc);
  header.appendChild(headerText);
  wrap.appendChild(header);

  // ── Tech stack ──
  const techTitle = document.createElement('h3');
  techTitle.style.cssText = 'font-size:0.75rem;text-transform:uppercase;letter-spacing:0.08em;color:rgba(255,255,255,0.4);margin-bottom:12px;';
  techTitle.textContent = 'Stack technique';
  wrap.appendChild(techTitle);

  const techRow = document.createElement('div');
  techRow.style.cssText = 'display:flex;flex-wrap:wrap;gap:8px;margin-bottom:24px;';
  const TECH = [
    ['Python asyncio','#06b6d4'],['Discord.py','#5865f2'],['Twitchio','#9146ff'],
    ['FastAPI','#22c55e'],['Claude · GPT','#eab308'],['Qdrant','#ef4444'],
    ['Neo4j + Graphiti','#a855f7'],['NRCLex','#3b82f6'],['Langfuse','#f97316'],
  ];
  TECH.forEach(([name, color]) => {
    const chip = document.createElement('span');
    chip.style.cssText = `padding:4px 12px;border-radius:20px;font-size:0.72rem;font-weight:500;border:1px solid ${color}44;color:${color};background:${color}11;`;
    chip.textContent = name;
    techRow.appendChild(chip);
  });
  wrap.appendChild(techRow);

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
