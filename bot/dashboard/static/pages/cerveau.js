// pages/cerveau.js — les réglages « cerveau » : rythmes émotionnels et prise de
// parole (Personnalité), mémoire (Mémoire commune), modèles de la cognition
// (Modèles & coûts), images spontanées (Images).
//
// Le serveur (`routes/config_cerveau.py`) dit, à chaque enregistrement, ce qui
// ne s'appliquera qu'au prochain redémarrage : la carte l'affiche tel quel,
// sans rien supposer.

(function () {
  const F = window.Formulaire;

  const EMOTIONS = ['anger', 'joy', 'sadness', 'curiosity', 'boredom'];
  const EMO = { anger: 'colère', joy: 'joie', sadness: 'tristesse', curiosity: 'curiosité', boredom: 'ennui' };
  const PERIODES = { night: 'Nuit', morning: 'Matin', afternoon: 'Après-midi', evening: 'Soirée' };
  const EVENEMENTS = {
    stream_ended: ['Fin du live', 'Quand le stream s\'arrête.'],
    left_alone_in_voice: ['Laissé seul en vocal', 'Quand tout le monde quitte le salon vocal où il est.'],
    ignored: ['Ignoré', 'Quand il insiste et que personne ne lui répond.'],
  };
  const SECONDAIRES = {
    frustration: 'Frustration', nostalgia: 'Nostalgie', pride: 'Fierté',
    anxiety: 'Anxiété', contempt: 'Mépris', wonder: 'Émerveillement',
  };

  function el(tag, classe, texte) {
    const n = document.createElement(tag);
    if (classe) n.className = classe;
    if (texte != null) n.textContent = texte;
    return n;
  }

  function entete(boite, titre, sous) {
    boite.textContent = '';
    boite.appendChild(el('div', 'page-section-titre', titre));
    if (sous) boite.appendChild(el('div', 'page-section-sous', sous));
  }

  async function lireJson(url) {
    const r = await window.apiFetch(url);
    if (!r || !r.ok) return null;
    try { return await r.json(); } catch (e) { return null; }
  }

  /** Nombre saisi ; vide → `null`, que le serveur refuse avec un message clair. */
  function nb(input) {
    return input.value.trim() === '' ? null : Number(input.value);
  }

  /** Un intertitre qui occupe toute la largeur de la grille. */
  function intertitre(texte) {
    const bloc = el('div', 'form-champ form-champ-large');
    bloc.appendChild(el('span', 'form-libelle', texte));
    return bloc;
  }

  /** Bouton « Enregistrer » d'une carte : PUT, puis dit ce qui attend un redémarrage. */
  function boutonEnregistrer(carte, url, corps) {
    const etat = F.note('');
    etat.hidden = true;
    const b = F.bouton('Enregistrer', async function () {
      const rep = await F.enregistrer(b, url, 'PUT', corps());
      if (!rep) return;
      const attente = rep.au_redemarrage || [];
      etat.textContent = attente.length
        ? 'Enregistré. Pris en compte au prochain redémarrage du bot : ' + attente.join(', ') + '.'
        : '';
      etat.hidden = !attente.length;
    });
    carte.el.appendChild(F.actions(b));
    carte.el.appendChild(etat);
  }

  function echec(boite) {
    boite.appendChild(F.note('Chargement impossible : le serveur n\'a pas répondu.'));
  }

  // ── Cerveau › Personnalité : rythmes et prise de parole ───────────────────

  function carteParole(p) {
    const c = F.carte('Prise de parole spontanée',
      'Quand Wally parle sans qu\'on s\'adresse à lui. Il continue toujours de répondre quand on l\'appelle.');
    const discord = F.bascule(p.spontaneous_discord_enabled);
    const twitch = F.bascule(p.spontaneous_twitch_enabled);
    const pensees = F.bascule(p.spontaneous_channel_speak_enabled);
    const proba = F.nombre(p.spontaneous_probability, { min: 0, max: 1, pas: 0.01 });
    const passion = F.nombre(p.spontaneous_passion_probability, { min: 0, max: 1, pas: 0.01 });
    const delai = F.nombre(p.spontaneous_cooldown_seconds, { min: 0, max: 86400 });
    const questions = F.bascule(p.unanswered_question_enabled);
    const attente = F.nombre(p.unanswered_question_delay_seconds, { min: 5, max: 3600 });
    const oubli = F.nombre(p.unanswered_question_forget_seconds, { min: 10, max: 86400 });

    c.corps.appendChild(F.champ('Intervenir dans les conversations Discord', discord,
      'Il peut se joindre à une discussion en cours sans être mentionné.'));
    c.corps.appendChild(F.champ('Intervenir dans le chat Twitch', twitch,
      'Même chose dans le chat du live.'));
    c.corps.appendChild(F.champ('Probabilité d\'intervenir', proba,
      'Entre 0 et 1, sur un message qui l\'intéresse (0,05 = une fois sur vingt).'));
    c.corps.appendChild(F.champ('Probabilité sur un sujet qui le passionne', passion,
      'Entre 0 et 1, quand le message touche un sujet qui l\'anime.'));
    c.corps.appendChild(F.champ('Délai entre deux interventions (secondes)', delai,
      'Par salon. Vaut aussi pour les questions sans réponse.'));
    c.corps.appendChild(F.champ('Relever les questions restées sans réponse', questions,
      'Une question posée au chat que personne ne relève. Le filtre de réponse garde le dernier mot.'));
    c.corps.appendChild(F.champ('Temps laissé au chat pour répondre (secondes)', attente,
      'Avant ce délai, il laisse les autres répondre.'));
    c.corps.appendChild(F.champ('Oubli d\'une question (secondes)', oubli,
      'Au-delà, y répondre reviendrait à la déterrer.'));
    c.corps.appendChild(F.champ('Publier ses pensées de lui-même', pensees,
      'Les messages nés de sa réflexion intérieure, dans les salons. Les rappels et les messages privés au créateur passent toujours.', true));
    c.el.appendChild(F.note('« Publier ses pensées » est pris en compte au prochain redémarrage du bot. Le reste s\'applique tout de suite.'));

    boutonEnregistrer(c, '/api/admin/cerveau/parole', function () {
      return {
        spontaneous_discord_enabled: discord.checked,
        spontaneous_twitch_enabled: twitch.checked,
        spontaneous_channel_speak_enabled: pensees.checked,
        spontaneous_probability: nb(proba),
        spontaneous_passion_probability: nb(passion),
        spontaneous_cooldown_seconds: nb(delai),
        unanswered_question_enabled: questions.checked,
        unanswered_question_delay_seconds: nb(attente),
        unanswered_question_forget_seconds: nb(oubli),
      };
    });
    return c.el;
  }

  function carteTemperament(d) {
    const c = F.carte('Tempérament',
      'Comment ses émotions se mélangent, s\'installent et s\'usent.');
    const inertie = F.nombre(d.emotions.emotion_inertia_factor, { min: 0, max: 1, pas: 0.05 });
    const pic = F.nombre(d.emotions.emotion_peak_threshold, { min: 0.3, max: 1, pas: 0.05 });
    const alpha = F.nombre(d.mood.alpha, { min: 0, max: 1, pas: 0.01 });
    const effacement = F.nombre(d.mood.decay_lambda, { min: 0, max: 10, pas: 0.01 });
    const biais = F.nombre(d.mood.bias_factor, { min: 0, max: 2, pas: 0.05 });
    const amorti = F.nombre(d.fatigue.dampening, { min: 0, max: 1, pas: 0.05 });
    const recup = F.nombre(d.fatigue.recovery_rate, { min: 0, max: 10, pas: 0.01 });

    c.corps.appendChild(F.champ('Inertie', inertie,
      'De 0 à 1 : combien une émotion opposée déjà forte freine la nouvelle (joie qui arrive pendant une colère).'));
    c.corps.appendChild(F.champ('Seuil d\'un pic', pic,
      'Intensité à partir de laquelle une émotion compte comme un pic : elle est notée et le fatigue.'));
    c.corps.appendChild(intertitre('Humeur de fond'));
    c.corps.appendChild(F.champ('Vitesse d\'imprégnation', alpha,
      'De 0 à 1 : à quelle vitesse les émotions du moment deviennent une humeur durable.'));
    c.corps.appendChild(F.champ('Vitesse d\'effacement (par heure)', effacement,
      'Plus c\'est haut, plus l\'humeur s\'efface vite.'));
    c.corps.appendChild(F.champ('Influence sur les émotions', biais,
      'Combien l\'humeur amplifie les émotions qui vont dans son sens.'));
    c.corps.appendChild(intertitre('Fatigue après un pic'));
    c.corps.appendChild(F.champ('Amortissement', amorti,
      'De 0 à 1 : combien une émotion qui vient de culminer réagit moins ensuite.'));
    c.corps.appendChild(F.champ('Récupération par heure', recup,
      'Vitesse à laquelle cette fatigue se dissipe.'));

    boutonEnregistrer(c, '/api/admin/cerveau/emotions', function () {
      return {
        emotion_inertia_factor: nb(inertie),
        emotion_peak_threshold: nb(pic),
        mood: { alpha: nb(alpha), decay_lambda: nb(effacement), bias_factor: nb(biais) },
        fatigue: { dampening: nb(amorti), recovery_rate: nb(recup) },
      };
    });
    return c.el;
  }

  function carteLassitude(h) {
    const c = F.carte('Lassitude',
      'Quand la même personne provoque la même émotion en boucle, l\'effet s\'émousse.');
    const seuil = F.nombre(h.threshold_count, { min: 1, max: 50 });
    const fenetre = F.nombre(h.window_seconds, { min: 10, max: 86400 });
    const attenuation = F.nombre(h.decay_factor, { min: 0, max: 1, pas: 0.05 });
    const remise = F.nombre(h.reset_seconds, { min: 60, max: 86400 });
    c.corps.appendChild(F.champ('Répétitions tolérées', seuil,
      'Au-delà de ce nombre dans la fenêtre, chaque répétition compte moins.'));
    c.corps.appendChild(F.champ('Fenêtre (secondes)', fenetre,
      'La période sur laquelle les répétitions sont comptées.'));
    c.corps.appendChild(F.champ('Atténuation', attenuation,
      'De 0 à 1 : ce qui reste de l\'effet à chaque répétition de trop (0,5 = moitié).'));
    c.corps.appendChild(F.champ('Remise à zéro (secondes)', remise,
      'Après ce silence, la personne repart à neuf.'));
    const exemptes = {};
    c.corps.appendChild(intertitre('Émotions qui ne s\'usent jamais'));
    EMOTIONS.forEach(function (e) {
      exemptes[e] = F.bascule((h.exempt || []).indexOf(e) !== -1);
      c.corps.appendChild(F.champ(EMO[e], exemptes[e]));
    });

    boutonEnregistrer(c, '/api/admin/cerveau/emotions', function () {
      return {
        habituation: {
          threshold_count: nb(seuil), window_seconds: nb(fenetre),
          decay_factor: nb(attenuation), reset_seconds: nb(remise),
          exempt: EMOTIONS.filter(function (e) { return exemptes[e].checked; }),
        },
      };
    });
    return c.el;
  }

  function carteCircadien(circ) {
    const c = F.carte('Rythme de la journée',
      'Par tranche horaire, un multiplicateur par émotion : 1 = neutre, 1,3 = réagit 30 % plus fort, 0,8 = 20 % moins fort.');
    const actif = F.bascule(circ.enabled);
    c.corps.appendChild(F.champ('Activé', actif, 'Heure de Paris.', true));
    const saisies = {};
    Object.keys(circ.periods || {}).forEach(function (nom) {
      const p = circ.periods[nom];
      const s = {
        debut: F.nombre(p.hours[0], { min: 0, max: 23 }),
        fin: F.nombre(p.hours[1], { min: 1, max: 24 }),
      };
      c.corps.appendChild(intertitre(PERIODES[nom] || nom));
      c.corps.appendChild(F.champ('De (heure)', s.debut));
      c.corps.appendChild(F.champ('À (heure, exclue)', s.fin));
      EMOTIONS.forEach(function (e) {
        s[e] = F.nombre(p[e], { min: 0, max: 3, pas: 0.05 });
        c.corps.appendChild(F.champ('Multiplicateur de ' + EMO[e], s[e]));
      });
      saisies[nom] = s;
    });

    boutonEnregistrer(c, '/api/admin/cerveau/circadien', function () {
      const periodes = {};
      Object.keys(saisies).forEach(function (nom) {
        const s = saisies[nom];
        const p = { hours: [nb(s.debut), nb(s.fin)] };
        EMOTIONS.forEach(function (e) { p[e] = nb(s[e]); });
        periodes[nom] = p;
      });
      return { enabled: actif.checked, periods: periodes };
    });
    return c.el;
  }

  function carteContrecoup(after) {
    const c = F.carte('Contrecoup',
      'Quand une émotion forte retombe, une partie de la baisse en nourrit une autre (la colère qui laisse de l\'amertume).');
    const actif = F.bascule(after.enabled);
    c.corps.appendChild(F.champ('Activé', actif, null, true));
    const optionsSource = EMOTIONS.filter(function (e) { return e !== 'boredom'; })
      .map(function (e) { return [e, EMO[e]]; });
    const optionsCible = EMOTIONS.map(function (e) { return [e, EMO[e]]; });
    const saisies = {};
    Object.keys(after.rules || {}).forEach(function (nom) {
      const r = after.rules[nom];
      const s = {
        source: F.choix(optionsSource, r.source),
        target: F.choix(optionsCible, r.target),
        ratio: F.nombre(r.ratio, { min: 0, max: 1, pas: 0.05 }),
        min_peak: F.nombre(r.min_peak, { min: 0, max: 1, pas: 0.05 }),
        reset_below: F.nombre(r.reset_below, { min: 0, max: 1, pas: 0.05 }),
      };
      c.corps.appendChild(intertitre(nom.charAt(0).toUpperCase() + nom.slice(1)));
      c.corps.appendChild(F.champ('Émotion qui retombe', s.source));
      c.corps.appendChild(F.champ('Émotion nourrie', s.target));
      c.corps.appendChild(F.champ('Part convertie', s.ratio,
        'De 0 à 1 : la part de la baisse qui passe dans l\'autre émotion.'));
      c.corps.appendChild(F.champ('Pic minimal', s.min_peak,
        'Sous ce pic, pas de contrecoup : un agacement bref ne laisse pas de traces.'));
      c.corps.appendChild(F.champ('Fin de l\'épisode', s.reset_below,
        'Sous ce niveau, l\'épisode est clos et le pic repart de zéro.'));
      saisies[nom] = s;
    });

    boutonEnregistrer(c, '/api/admin/cerveau/contrecoup', function () {
      const regles = {};
      Object.keys(saisies).forEach(function (nom) {
        const s = saisies[nom];
        regles[nom] = {
          source: s.source.value, target: s.target.value,
          ratio: nb(s.ratio), min_peak: nb(s.min_peak), reset_below: nb(s.reset_below),
        };
      });
      return { enabled: actif.checked, rules: regles };
    });
    return c.el;
  }

  function carteEvenements(events) {
    const c = F.carte('Ce que le monde lui fait',
      'Ce que certains événements changent à ses émotions, de -1 à 1. 0 = aucun effet.');
    const saisies = {};
    Object.keys(events || {}).forEach(function (nom) {
      const libelle = EVENEMENTS[nom] || [nom, ''];
      const effets = events[nom].effects || {};
      const s = {};
      c.corps.appendChild(intertitre(libelle[0]));
      if (libelle[1]) c.corps.appendChild(el('div', 'form-aide form-champ-large', libelle[1]));
      EMOTIONS.forEach(function (e) {
        s[e] = F.nombre(effets[e] || 0, { min: -1, max: 1, pas: 0.05 });
        c.corps.appendChild(F.champ(EMO[e], s[e]));
      });
      saisies[nom] = s;
    });

    boutonEnregistrer(c, '/api/admin/cerveau/evenements', function () {
      const corps = {};
      Object.keys(saisies).forEach(function (nom) {
        const effets = {};
        EMOTIONS.forEach(function (e) { effets[e] = nb(saisies[nom][e]); });
        corps[nom] = { effects: effets };
      });
      return corps;
    });
    return c.el;
  }

  function carteSecondaires(sec) {
    const c = F.carte('Émotions mêlées',
      'Deux émotions présentes ensemble en forment une troisième. Le seuil est l\'intensité que les deux doivent atteindre (0,4 au minimum : en dessous, elle ne changerait rien à son comportement).');
    const saisies = {};
    Object.keys(sec || {}).forEach(function (nom) {
      const d = sec[nom];
      const libelle = (SECONDAIRES[nom] || nom) + ' (' + (EMO[d.a] || d.a) + ' + ' + (EMO[d.b] || d.b) + ')';
      if (Array.isArray(d.threshold)) {
        const a = F.nombre(d.threshold[0], { min: 0.4, max: 1, pas: 0.05 });
        const b = F.nombre(d.threshold[1], { min: 0.4, max: 1, pas: 0.05 });
        c.corps.appendChild(F.champ(libelle + ' : seuil de ' + (EMO[d.a] || d.a), a));
        c.corps.appendChild(F.champ(libelle + ' : seuil de ' + (EMO[d.b] || d.b), b));
        saisies[nom] = [a, b];
      } else {
        const s = F.nombre(d.threshold, { min: 0.4, max: 1, pas: 0.05 });
        c.corps.appendChild(F.champ(libelle, s));
        saisies[nom] = s;
      }
    });

    boutonEnregistrer(c, '/api/admin/cerveau/secondaires', function () {
      const corps = {};
      Object.keys(saisies).forEach(function (nom) {
        const s = saisies[nom];
        corps[nom] = { threshold: Array.isArray(s) ? [nb(s[0]), nb(s[1])] : nb(s) };
      });
      return corps;
    });
    return c.el;
  }

  window.renderPersonnaliteAvance = async function (boite) {
    entete(boite, 'Rythmes et prise de parole',
      'Quand il parle de lui-même, et comment ses émotions évoluent au fil du temps. Tout s\'applique sans redémarrage, sauf mention contraire.');
    const d = await lireJson('/api/admin/cerveau/rythmes');
    if (!d) { echec(boite); return; }
    boite.appendChild(carteParole(d.parole));
    boite.appendChild(carteTemperament(d));
    boite.appendChild(carteLassitude(d.habituation));
    boite.appendChild(carteCircadien(d.circadian));
    boite.appendChild(carteContrecoup(d.aftermath));
    boite.appendChild(carteEvenements(d.world_events));
    boite.appendChild(carteSecondaires(d.secondaries));
  };

  // ── Cerveau › Mémoire commune : réglages ──────────────────────────────────

  window.renderMemoireReglages = async function (boite) {
    entete(boite, 'Réglages de la mémoire',
      'Combien de souvenirs et de contexte accompagnent chaque réponse. S\'applique sans redémarrage.');
    const m = await lireJson('/api/admin/cerveau/memoire');
    if (!m) { echec(boite); return; }
    const c = F.carte('Contexte des réponses');
    const budget = F.nombre(m.memory_context_max_tokens, { min: 100, max: 8000, pas: 50 });
    const seuil = F.nombre(m.context_token_threshold, { min: 500, max: 32000, pas: 100 });
    const prelude = F.nombre(m.prelude_window_size, { min: 1, max: 100 });
    const lien = F.nombre(m.link_min_confidence, { min: 0.5, max: 1, pas: 0.01 });
    c.corps.appendChild(F.champ('Budget des souvenirs (tokens)', budget,
      'Place donnée aux souvenirs, relations et questions en attente dans chaque réponse.'));
    c.corps.appendChild(F.champ('Seuil de résumé de la conversation (tokens)', seuil,
      'Au-delà, la conversation récente d\'un salon est résumée pour rester lisible.'));
    c.corps.appendChild(F.champ('Messages lus avant de répondre', prelude,
      'Nombre de messages récents du salon qu\'il relit quand on l\'appelle.'));
    c.corps.appendChild(F.champ('Confiance minimale d\'un lien de comptes', lien,
      'De 0,5 à 1 : ressemblance exigée pour proposer qu\'un compte Discord et un compte Twitch soient la même personne.'));
    boutonEnregistrer(c, '/api/admin/cerveau/memoire', function () {
      return {
        memory_context_max_tokens: nb(budget),
        context_token_threshold: nb(seuil),
        prelude_window_size: nb(prelude),
        link_min_confidence: nb(lien),
      };
    });
    boite.appendChild(c.el);
  };

  // ── Cerveau › Modèles & coûts : cognition, vision, recherche web ──────────

  const _catalogues = {};
  async function catalogue(fournisseur) {
    if (!_catalogues[fournisseur]) {
      const d = await lireJson('/api/admin/' + encodeURIComponent(fournisseur) + '/models');
      _catalogues[fournisseur] = (d && Array.isArray(d.models)) ? d.models : [];
    }
    return _catalogues[fournisseur];
  }

  /** Un `<select>` de modèle ; la valeur actuelle reste présente même hors catalogue. */
  async function selectModele(fournisseur, actuel) {
    const liste = await catalogue(fournisseur);
    return F.choix(liste.map(function (m) { return [m, m]; }), actuel);
  }

  /** Fournisseur + modèle ; changer de fournisseur recharge la liste des modèles. */
  async function paireModele(carte, libelle, fournisseurs, fournisseur, modele, aide) {
    const choixF = F.choix(fournisseurs.map(function (f) { return [f, f === 'deepseek' ? 'DeepSeek' : f === 'openai' ? 'OpenAI' : f]; }), fournisseur);
    const paire = { fournisseur: choixF, modele: await selectModele(fournisseur, modele) };
    carte.corps.appendChild(F.champ('Fournisseur ' + libelle, choixF));
    carte.corps.appendChild(F.champ('Modèle ' + libelle, paire.modele, aide));
    choixF.onchange = async function () {
      // Le modèle configuré n'est gardé que sur son propre fournisseur.
      const garde = choixF.value === fournisseur ? modele : null;
      const neuf = await selectModele(choixF.value, garde);
      paire.modele.replaceWith(neuf);
      paire.modele = neuf;
    };
    return paire;
  }

  window.renderModelesAvance = async function (boite) {
    entete(boite, 'Cognition, vision et recherche web',
      'Les modèles qui ne répondent pas directement aux messages, et les quotas des outils web.');
    const d = await lireJson('/api/admin/cerveau/modeles');
    if (!d) { echec(boite); return; }

    // Modèles
    const cm = F.carte('Modèles spécialisés');
    const cognition = await paireModele(cm, 'de la réflexion', d.fournisseurs,
      d.cognition.provider, d.cognition.model_pro,
      'Sa vie intérieure : pensées, décisions d\'agir, évolution de sa personnalité.');
    if (!d.cognition.enabled) cm.corps.appendChild(F.note('La réflexion autonome est désactivée : ce modèle ne sert pas pour l\'instant.'));
    const gate = await paireModele(cm, 'du filtre de réponse', d.fournisseurs,
      d.gate.provider, d.gate.model,
      'Décide, avant chaque réponse, s\'il vaut mieux répondre, réagir ou se taire.');
    if (!d.gate.enabled) cm.corps.appendChild(F.note('Le filtre de réponse est désactivé : ce modèle ne sert pas pour l\'instant.'));
    const vision = F.choix(
      [['', 'par défaut (' + d.vision.defaut + ')']].concat((await catalogue('openai')).map(function (m) { return [m, m]; })),
      d.vision.model);
    cm.corps.appendChild(F.champ('Modèle de vision (OpenAI)', vision,
      'Décrit les images qu\'on lui envoie. Doit accepter les images.'));
    boutonEnregistrer(cm, '/api/admin/cerveau/modeles', function () {
      return {
        cognition: { provider: cognition.fournisseur.value, model_pro: cognition.modele.value },
        gate: { provider: gate.fournisseur.value, model: gate.modele.value },
        vision: { model: vision.value },
      };
    });
    boite.appendChild(cm.el);

    // Températures
    const ct = F.carte('Températures',
      'Plus haut = réponses plus variées et imprévisibles, plus bas = plus constantes. De 0 à 2.');
    const temp = {};
    [['primary', 'Modèle principal'], ['secondary', 'Modèle secondaire']].forEach(function (r) {
      const t = d.temperatures[r[0]];
      temp[r[0]] = F.nombre(t.temperature, { min: 0, max: 2, pas: 0.05 });
      ct.corps.appendChild(F.champ(r[1] + ' (' + t.model + ')', temp[r[0]],
        t.lue ? 'Appliquée à chaque appel.'
              : 'Ignorée par ce modèle (modèle de raisonnement ou réflexion activée) : la changer n\'a aucun effet.'));
    });
    boutonEnregistrer(ct, '/api/admin/cerveau/modeles', function () {
      return { temperatures: { primary: nb(temp.primary), secondary: nb(temp.secondary) } };
    });
    boite.appendChild(ct.el);

    // Recherche web
    const cw = F.carte('Recherche web');
    const mensuel = F.nombre(d.tavily.monthly_limit, { min: 0, max: 100000 });
    const delaiCog = F.nombre(d.tavily.cognitive_cooldown_minutes, { min: 0, max: 1440 });
    cw.corps.appendChild(F.champ('Recherches par mois', mensuel,
      'Quota total de recherches web. 0 = aucune.'));
    cw.corps.appendChild(F.champ('Délai entre deux recherches de sa réflexion (minutes)', delaiCog,
      'Évite qu\'une pensée relance la même recherche en boucle.'));
    boutonEnregistrer(cw, '/api/admin/cerveau/modeles', function () {
      return { tavily: { monthly_limit: nb(mensuel), cognitive_cooldown_minutes: nb(delaiCog) } };
    });
    boite.appendChild(cw.el);

    // Lecture de pages
    const cf = F.carte('Lecture de pages web');
    const fc = d.firecrawl;
    const actif = F.bascule(fc.enabled);
    const parJour = F.nombre(fc.daily_limit, { min: 0, max: 10000 });
    const liens = F.bascule(fc.auto_scrape_links);
    const delaiLien = F.nombre(fc.auto_scrape_cooldown_s, { min: 0, max: 3600 });
    const taille = F.nombre(fc.inline_max_tokens, { min: 100, max: 32000, pas: 100 });
    cf.corps.appendChild(F.champ('Activée', actif, 'Lire le contenu d\'une page quand il en a besoin.'));
    cf.corps.appendChild(F.champ('Pages lues par jour', parJour, 'Au-delà, plus aucune lecture jusqu\'au lendemain.'));
    cf.corps.appendChild(F.champ('Lire les liens postés sur Discord', liens,
      'Quand on lui adresse un message avec un lien, il en lit le contenu.'));
    cf.corps.appendChild(F.champ('Délai entre deux lectures de lien (secondes)', delaiLien, 'Par salon.'));
    cf.corps.appendChild(F.champ('Taille maximale d\'une page lue (tokens)', taille,
      'Au-delà, la page est raccourcie.'));
    boutonEnregistrer(cf, '/api/admin/cerveau/modeles', function () {
      return {
        firecrawl: {
          enabled: actif.checked, daily_limit: nb(parJour), auto_scrape_links: liens.checked,
          auto_scrape_cooldown_s: nb(delaiLien), inline_max_tokens: nb(taille),
        },
      };
    });
    boite.appendChild(cf.el);
  };

  // ── Cerveau › Images : images spontanées ──────────────────────────────────

  window.renderImagesAutonomes = async function (boite) {
    entete(boite, 'Images spontanées',
      'Wally décide seul de fabriquer une image et de la poster. Chaque image est payante.');
    const results = await Promise.all([lireJson('/api/admin/cerveau/images-autonomes'), F.catalogueDiscord()]);
    const d = results[0];
    if (!d) { echec(boite); return; }
    const c = F.carte('Initiative');
    const actif = F.bascule(d.autonomous_enabled);
    const salons = F.salons(d.autonomous_channel_ids, 'texte');
    const quota = F.nombre(d.autonomous_daily_limit, { min: -1, max: 50 });
    const delai = F.nombre(d.autonomous_cooldown_minutes, { min: 0, max: 10080 });
    c.corps.appendChild(F.champ('Fabriquer des images de sa propre initiative', actif, null, true));
    c.corps.appendChild(F.champ('Images par jour', quota, '-1 = pas de plafond, 0 = aucune.'));
    c.corps.appendChild(F.champ('Délai entre deux images (minutes)', delai, '0 = pas de délai.'));
    c.corps.appendChild(F.champ('Salons où il peut en poster', salons,
      'Aucun salon coché = capacité éteinte.', true));
    if (!d.cognition_active) {
      c.el.appendChild(F.note('Sa réflexion autonome est désactivée : il ne décidera d\'aucune image tant qu\'elle l\'est.'));
    }
    boutonEnregistrer(c, '/api/admin/cerveau/images-autonomes', function () {
      return {
        autonomous_enabled: actif.checked,
        autonomous_channel_ids: salons.lireListe(),
        autonomous_daily_limit: nb(quota),
        autonomous_cooldown_minutes: nb(delai),
      };
    });
    boite.appendChild(c.el);
  };
})();
