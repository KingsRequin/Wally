// pages/systeme.js — Discord › Voix (transcription et accès), Système › Veille,
// Système › Connexions (salons de service et chat web).
//
// Chaque réglage affiché a un lecteur dans le code du bot. Ce qui est relu à
// chaque usage prend effet tout de suite ; ce qui n'est lu qu'au démarrage le
// dit, champ par champ ou dans la note de la carte.

(function () {
  const F = window.Formulaire;
  const NOTE_REDEMARRAGE = 'Pris en compte au prochain redémarrage du bot.';

  function el(tag, classe, texte) {
    const n = document.createElement(tag);
    if (classe) n.className = classe;
    if (texte != null) n.textContent = texte;
    return n;
  }

  function entete(boite, titre, sous) {
    boite.appendChild(el('div', 'page-section-titre', titre));
    if (sous) boite.appendChild(el('div', 'page-section-sous', sous));
  }

  function section(id, titre, sous) {
    const s = el('div', 'page-section');
    s.id = id;
    entete(s, titre, sous);
    return s;
  }

  async function charger(hote, url) {
    const attente = el('div', 'form-note', 'Chargement…');
    hote.appendChild(attente);
    const r = await window.apiFetch(url);
    attente.remove();
    if (!r || !r.ok) {
      hote.appendChild(el('div', 'form-note', 'Impossible de charger les réglages.'));
      return null;
    }
    return r.json();
  }

  function nombreLu(input) {
    return input.value === '' ? null : Number(input.value);
  }

  // Un champ qu'on masque sans le détruire (adresse ou appid selon le type).
  function montrer(champ, visible) {
    champ.style.display = visible ? '' : 'none';
  }

  // ─── Discord › Voix : transcription et accès ────────────────────────────

  function ligneDemandeur(liste, d, plateformes) {
    const c = F.carte(null, null);
    const champs = {
      discord_id: F.texte(d.discord_id, { max: 21, placeholder: '610550333042589752' }),
      twitch_id: F.texte(d.twitch_id, { max: 20, placeholder: 'id numérique' }),
      twitch_login: F.texte(d.twitch_login, { max: 25, placeholder: 'pseudo' }),
      apex_name: F.texte(d.apex_name, { max: 64 }),
      apex_uid: F.texte(d.apex_uid, { max: 30 }),
      apex_platform: F.choix([['', 'PC (par défaut)']].concat(plateformes.map(function (p) { return [p, p]; })),
        d.apex_platform || ''),
    };
    c.corps.appendChild(F.champ('Id Discord', champs.discord_id,
      'Reconnaît sa voix en salon ; ses énoncés passent en priorité sur le serveur GPU.'));
    c.corps.appendChild(F.champ('Id Twitch', champs.twitch_id,
      'Celui du streamer lui donne ses droits sur la chaîne.'));
    c.corps.appendChild(F.champ('Pseudo Twitch', champs.twitch_login,
      'Sert à le mentionner quand la réponse part dans le chat.'));
    c.corps.appendChild(F.champ('Compte Apex', champs.apex_name,
      'Inscrit au démarrage pour « mes stats ». Vide : aucun compte déclaré.'));
    c.corps.appendChild(F.champ('Uid Apex', champs.apex_uid,
      'Requis pour arbitrer le duel sur le compte du streamer.'));
    c.corps.appendChild(F.champ('Plateforme Apex', champs.apex_platform));
    const entree = { champs: champs };
    const retirer = F.bouton('Retirer', function () {
      liste.splice(liste.indexOf(entree), 1);
      c.el.remove();
    }, { discret: true });
    c.el.appendChild(F.actions(retirer));
    liste.push(entree);
    return c.el;
  }

  window.renderVoixAvance = async function (boite) {
    if (!boite) return;
    boite.textContent = '';
    entete(boite, 'Transcription et accès',
      'Comment Wally entend en salon vocal, et qui peut lui demander quelque chose à voix haute.');
    const d = await charger(boite, '/api/admin/systeme/voix');
    if (!d) return;
    const ch = d.choix;

    // Chaîne de transcription
    const cStt = F.carte('Chaîne de transcription',
      'Avec le serveur GPU : les demandeurs déclarés passent par le GPU puis la soupape ; les autres par le repli local, le GPU s\'il reste une place, puis la soupape.');
    const moteur = F.choix(ch.moteurs, d.stt_provider);
    const url = F.texte(d.remote_stt_url, { max: 200, placeholder: 'ws://192.168.1.49:9090' });
    const places = F.nombre(d.remote_stt_max_connections, { min: 1, max: 8 });
    const repli = F.choix(ch.replis, d.remote_stt_fallback);
    const modele = F.choix(ch.modeles_whisper.map(function (m) { return [m, m]; }), d.whisper_model);
    const silence = F.nombre(d.vad_silence_timeout_s, { min: 0.2, max: 5, pas: 0.1 });
    cStt.corps.appendChild(F.champ('Moteur principal', moteur,
      'Changé pendant une session, il ne s\'applique qu\'au prochain salon rejoint.'));
    const champUrl = F.champ('Adresse du serveur GPU', url, 'Serveur RealtimeSTT, sur le PC de l\'owner.');
    const champPlaces = F.champ('Places sur le serveur GPU', places,
      'Locuteurs transcrits en même temps. Limité par la mémoire de la carte (2 sur une RTX 4070).');
    const champRepli = F.champ('Repli si le serveur GPU manque', repli,
      'Utilisé quand le serveur est injoignable ou que ses places sont prises.');
    [champUrl, champPlaces, champRepli].forEach(function (c) { cStt.corps.appendChild(c); });
    cStt.corps.appendChild(F.champ('Modèle local', modele,
      'Pour faster-whisper sur le CPU. Plus gros = plus juste mais plus lent. Les messages vocaux Discord le prennent au prochain redémarrage.'));
    cStt.corps.appendChild(F.champ('Fin de parole (s)', silence,
      'Silence après lequel un énoncé est clos. Appliqué au prochain salon rejoint.'));
    function suivreMoteur() {
      const distant = moteur.value === 'remote_stream';
      [champUrl, champPlaces, champRepli].forEach(function (c) { montrer(c, distant); });
    }
    moteur.addEventListener('change', suivreMoteur);
    suivreMoteur();

    // Soupape de débordement
    const cSoupape = F.carte('Soupape de débordement',
      'Quand le moteur local est saturé, l\'énoncé part ici au lieu d\'être perdu.');
    const soupape = F.choix(ch.soupapes, d.overflow_stt_provider);
    const delai = F.nombre(d.overflow_stt_timeout_s, { min: 1, max: 120, pas: 1 });
    const tarif = F.nombre(d.overflow_stt_usd_per_hour, { min: 0, max: 10, pas: 0.01 });
    const enVol = F.nombre(d.overflow_stt_max_inflight, { min: 1, max: 32 });
    cSoupape.corps.appendChild(F.champ('Fournisseur', soupape));
    cSoupape.corps.appendChild(F.champ('Délai d\'attente (s)', delai, 'Au-delà, l\'énoncé est abandonné.'));
    cSoupape.corps.appendChild(F.champ('Tarif ($ par heure d\'audio)', tarif,
      'Sert à inscrire la dépense dans les coûts. 0 : rien n\'est compté.'));
    cSoupape.corps.appendChild(F.champ('Appels simultanés au plus', enVol,
      'Borne une rafale sur un salon qui déraille.'));
    const alerteCle = F.note('XAI_API_KEY est absente du .env : la soupape xAI ne s\'ouvrira pas.');
    cSoupape.corps.appendChild(alerteCle);
    function suivreSoupape() {
      montrer(alerteCle, soupape.value === 'xai' && !d.cle_xai_presente);
    }
    soupape.addEventListener('change', suivreSoupape);
    suivreSoupape();

    const cActStt = F.carte(null, null);
    const btnStt = F.bouton('Enregistrer la transcription', async function () {
      await F.enregistrer(btnStt, '/api/admin/systeme/voix', 'PUT', {
        stt_provider: moteur.value,
        remote_stt_url: url.value,
        remote_stt_max_connections: nombreLu(places),
        remote_stt_fallback: repli.value,
        whisper_model: modele.value,
        vad_silence_timeout_s: nombreLu(silence),
        overflow_stt_provider: soupape.value,
        overflow_stt_timeout_s: nombreLu(delai),
        overflow_stt_usd_per_hour: nombreLu(tarif),
        overflow_stt_max_inflight: nombreLu(enVol),
      }, 'Transcription enregistrée');
    });
    cActStt.corps.appendChild(F.note('Enregistrer reconstruit la transcription tout de suite, même en '
      + 'pleine session (les connexions au serveur GPU sont rouvertes). Sauf le moteur principal changé '
      + 'en session et la fin de parole : au prochain salon rejoint. Vocal désactivé au démarrage : '
      + 'rien ne tourne, tout attend le redémarrage.'));
    cActStt.el.appendChild(F.actions(btnStt));

    // Demandeurs
    const cDem = F.carte('Qui peut appeler Wally en vocal',
      'Les personnes reconnues à la voix, avec leurs identités Twitch et Apex. Liste vide : aucune demande vocale outillée.');
    const liste = [];
    const conteneur = el('div', '');
    (d.requesters || []).forEach(function (r) {
      conteneur.appendChild(ligneDemandeur(liste, r, ch.plateformes_apex));
    });
    cDem.el.appendChild(conteneur);
    const btnAjout = F.bouton('Ajouter une personne', function () {
      conteneur.appendChild(ligneDemandeur(liste, {}, ch.plateformes_apex));
    }, { discret: true });
    const btnDem = F.bouton('Enregistrer les demandeurs', async function () {
      const requesters = liste.map(function (e) {
        const sortie = {};
        Object.keys(e.champs).forEach(function (k) { sortie[k] = e.champs[k].value.trim(); });
        return sortie;
      });
      await F.enregistrer(btnDem, '/api/admin/systeme/voix', 'PUT', { requesters: requesters },
        'Demandeurs enregistrés');
    });
    cDem.el.appendChild(F.note('Reconnaissance et droits : tout de suite. Être dans la liste ne donne '
      + 'aucun droit de modération : seuls le streamer et le créateur en ont. Comptes Apex : ' + NOTE_REDEMARRAGE.toLowerCase()));
    cDem.el.appendChild(F.actions(btnAjout, btnDem));

    [cStt.el, cSoupape.el, cActStt.el, cDem.el].forEach(function (n) { boite.appendChild(n); });
  };

  // ─── Système › Veille ───────────────────────────────────────────────────

  function carteFlux(liste, f, ch) {
    const c = F.carte(null, null);
    const champs = {
      name: F.texte(f.name, { max: 60 }),
      kind: F.choix(ch.types, f.kind || 'rss'),
      url: F.texte(f.url, { max: 500, placeholder: 'https://…' }),
      appid: F.texte(f.appid, { max: 12, placeholder: '1172470' }),
      role: F.choix(ch.roles, f.role || 'stimulus'),
      lang: F.texte(f.lang || 'fr', { max: 2 }),
      enabled: F.bascule(f.enabled !== false),
    };
    c.corps.appendChild(F.champ('Nom', champs.name,
      'Sert de clé aux articles rangés : le renommer sépare les anciens des nouveaux.'));
    c.corps.appendChild(F.champ('Type', champs.kind));
    const champUrl = F.champ('Adresse du flux', champs.url, null, true);
    const champAppid = F.champ('Appid Steam', champs.appid,
      'Le numéro du jeu dans l\'URL de sa page Steam. Apex Legends : 1172470.');
    c.corps.appendChild(champUrl);
    c.corps.appendChild(champAppid);
    c.corps.appendChild(F.champ('Usage', champs.role,
      'Amorce : de quoi penser quand il s\'ennuie. Connaissances : cité quand le sujet vient dans la conversation.'));
    c.corps.appendChild(F.champ('Langue', champs.lang, 'Deux lettres : fr, en…'));
    c.corps.appendChild(F.champ('Actif', champs.enabled));
    function suivreType() {
      const steam = champs.kind.value === 'steam';
      montrer(champUrl, !steam);
      montrer(champAppid, steam);
    }
    champs.kind.addEventListener('change', suivreType);
    suivreType();
    const entree = { champs: champs };
    const retirer = F.bouton('Retirer ce flux', function () {
      liste.splice(liste.indexOf(entree), 1);
      c.el.remove();
    }, { discret: true });
    c.el.appendChild(F.actions(retirer));
    liste.push(entree);
    return c.el;
  }

  window.renderVeille = async function (hote) {
    if (!hote) return;
    // Rappelée à chaque visite de la page : seul le dernier rendu lancé écrit,
    // sinon deux clics rapprochés empileraient deux fois les cartes.
    const jeton = String(Date.now()) + Math.random();
    hote.dataset.rendu = jeton;
    hote.textContent = '';
    const d = await charger(hote, '/api/admin/systeme/veille');
    if (!d || hote.dataset.rendu !== jeton) return;
    const ch = d.choix;

    // Flux
    const sFlux = section('veille-flux', 'Flux',
      'Ce que Wally lit. Les annonces Steam arrivent découpées en sections, pour citer un patch légende par légende.');
    const liste = [];
    const conteneur = el('div', '');
    (d.feeds || []).forEach(function (f) { conteneur.appendChild(carteFlux(liste, f, ch)); });
    sFlux.appendChild(conteneur);
    const cActFlux = F.carte(null, null);
    const btnAjout = F.bouton('Ajouter un flux', function () {
      conteneur.appendChild(carteFlux(liste, { kind: 'rss', role: 'stimulus', lang: 'fr', enabled: true }, ch));
    }, { discret: true });
    const btnFlux = F.bouton('Enregistrer les flux', async function () {
      const feeds = liste.map(function (e) {
        const c = e.champs;
        return {
          name: c.name.value.trim(), kind: c.kind.value, url: c.url.value.trim(),
          appid: c.appid.value.trim(), role: c.role.value, lang: c.lang.value.trim(),
          enabled: c.enabled.checked,
        };
      });
      await F.enregistrer(btnFlux, '/api/admin/systeme/veille', 'PUT', { feeds: feeds }, 'Flux enregistrés');
    });
    cActFlux.corps.appendChild(F.note('Pris en compte au prochain relevé. Exception : si la veille '
      + 'n\'avait aucun flux au démarrage, le relevé ne tourne pas encore — ' + NOTE_REDEMARRAGE.toLowerCase()));
    cActFlux.el.appendChild(F.actions(btnAjout, btnFlux));
    sFlux.appendChild(cActFlux.el);

    // Relevé et conservation
    const sReg = section('veille-reglages', 'Relevé et conservation', null);
    const cReg = F.carte(null, null);
    const actif = F.bascule(d.enabled);
    const intervalle = F.nombre(d.poll_interval_minutes, { min: 5, max: 1440 });
    const retention = F.nombre(d.retention_days, { min: 1, max: 365 });
    const resume = F.nombre(d.summary_max_chars, { min: 50, max: 2000 });
    const fraicheurAmorce = F.nombre(d.stimulus_max_age_hours, { min: 1, max: 720 });
    const fraicheurSavoir = F.nombre(d.knowledge_max_age_days, { min: 1, max: 3650 });
    cReg.corps.appendChild(F.champ('Veille active', actif,
      'Coupée, les connaissances ne sont plus citées tout de suite ; relevé et amorces s\'arrêtent au prochain redémarrage.'));
    cReg.corps.appendChild(F.champ('Relevé des flux toutes les (minutes)', intervalle, NOTE_REDEMARRAGE));
    cReg.corps.appendChild(F.champ('Conservation des articles (jours)', retention,
      'Au-delà, la purge (toutes les 6 h) les efface. Pris en compte à la prochaine purge.'));
    cReg.corps.appendChild(F.champ('Longueur des résumés (caractères)', resume,
      'Flux RSS seulement, pour les articles relevés ensuite. Les sections Steam ne sont pas coupées.'));
    cReg.corps.appendChild(F.champ('Fraîcheur d\'une amorce (heures)', fraicheurAmorce,
      'Plus vieux, un article n\'amorce plus de pensée. ' + NOTE_REDEMARRAGE));
    cReg.corps.appendChild(F.champ('Fraîcheur d\'une connaissance (jours)', fraicheurSavoir,
      'Plus vieux, un article n\'est plus cité. Une saison Apex dure environ trois mois. Tout de suite.'));
    const btnReg = F.bouton('Enregistrer', async function () {
      await F.enregistrer(btnReg, '/api/admin/systeme/veille', 'PUT', {
        enabled: actif.checked,
        poll_interval_minutes: nombreLu(intervalle),
        retention_days: nombreLu(retention),
        summary_max_chars: nombreLu(resume),
        stimulus_max_age_hours: nombreLu(fraicheurAmorce),
        knowledge_max_age_days: nombreLu(fraicheurSavoir),
      });
    });
    cReg.el.appendChild(F.actions(btnReg));
    sReg.appendChild(cReg.el);

    hote.appendChild(sFlux);
    hote.appendChild(sReg);
    window.poserSommaire('systeme/veille', [
      ['veille-flux', 'Flux'],
      ['veille-reglages', 'Relevé et conservation'],
    ], '');
  };

  // ─── Système › Connexions : salons de service et chat web ───────────────

  window.renderConnexionsAvance = async function (boite) {
    if (!boite) return;
    boite.textContent = '';
    entete(boite, 'Salons de service et chat web', 'Où Wally publie de lui-même, et le rythme du chat du site.');
    const d = await charger(boite, '/api/admin/systeme/salons-service');
    if (!d) return;
    await F.catalogueDiscord();

    const c = F.carte(null, null);
    const journal = F.salon(d.journal_channel_id, 'texte');
    const chambre = F.salon(d.bedroom_channel_id, 'texte');
    const vocal = F.salon(d.stream_voice_channel_id, 'vocal');
    const cooldown = F.nombre(d.web_chat_cooldown_seconds, { min: 0, max: 3600 });
    c.corps.appendChild(F.champ('Salon du journal', journal,
      'Où part le journal quotidien du soir. Aucun : le journal n\'est pas écrit.'));
    c.corps.appendChild(F.champ('Chambre de Wally', chambre,
      'Son salon : ses prises de parole spontanées, l\'annonce du live et les rappels créés en vocal.'));
    c.corps.appendChild(F.champ('Salon vocal du live', vocal,
      'Rejoint en écoute seule au lancement du stream. Le changer oublie le dernier salon retenu.'));
    c.corps.appendChild(F.champ('Délai du chat web (s)', cooldown,
      'Attente minimale entre deux messages d\'une même personne sur le chat du site. 0 : aucune.'));
    const btn = F.bouton('Enregistrer', async function () {
      await F.enregistrer(btn, '/api/admin/systeme/salons-service', 'PUT', {
        journal_channel_id: journal.value,
        bedroom_channel_id: chambre.value,
        stream_voice_channel_id: vocal.value,
        web_chat_cooldown_seconds: nombreLu(cooldown),
      });
    });
    c.corps.appendChild(F.note('Pris en compte tout de suite.'));
    c.el.appendChild(F.actions(btn));
    boite.appendChild(c.el);
  };
})();
