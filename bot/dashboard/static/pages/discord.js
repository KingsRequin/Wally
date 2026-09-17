// pages/discord.js — Discord › Serveur communautaire, et deux sections
// ajoutées à Discord › Salons et Discord › Anti-spam.
//
// Routes : `bot/dashboard/routes/config_discord.py`. Les ids Discord voyagent
// en CHAÎNES dans les deux sens (un snowflake ne survit pas à `Number`).
// Tous ces réglages sont relus par leur lecteur à chaque événement : rien ici
// n'attend un redémarrage, sauf le passage complet sur les emotes (dit à l'écran).

(function () {
  function el(tag, classe, texte) {
    const n = document.createElement(tag);
    if (classe) n.className = classe;
    if (texte != null) n.textContent = texte;
    return n;
  }

  async function lireJson(url) {
    const r = await window.apiFetch(url);
    if (!r || !r.ok) return null;
    try { return await r.json(); } catch (e) { return null; }
  }

  function entete(boite, titre, sous) {
    boite.textContent = '';
    boite.appendChild(el('div', 'page-section-titre', titre));
    if (sous) boite.appendChild(el('div', 'page-section-sous', sous));
  }

  /** Cases à cocher sur `items` ({id, name}). Les ids cochés absents de la
   *  liste restent affichés (« introuvable ») : les taire les effacerait au
   *  premier enregistrement. Lire `.lireListe()`. */
  function cases(items, valeurs, prefixe) {
    const coches = new Set((valeurs || []).map(String));
    const boite = el('div', 'form-multi');
    function ligne(id, nom, coche) {
      const l = el('label', 'form-multi-ligne');
      const cb = el('input');
      cb.type = 'checkbox';
      cb.value = String(id);
      cb.checked = coche;
      l.appendChild(cb);
      l.appendChild(el('span', '', (prefixe || '') + nom));
      boite.appendChild(l);
    }
    items.forEach(function (it) {
      ligne(it.id, it.name, coches.has(String(it.id)));
      coches.delete(String(it.id));
    });
    coches.forEach(function (id) { ligne(id, id + ' (introuvable)', true); });
    if (!boite.childNodes.length) boite.appendChild(el('span', 'form-aide', 'Rien à choisir : Wally ne voit aucun serveur.'));
    boite.lireListe = function () {
      return Array.from(boite.querySelectorAll('input[type=checkbox]:checked'))
        .map(function (cb) { return cb.value; });
    };
    return boite;
  }

  function serveurs(catalogue) {
    return catalogue.map(function (g) { return { id: g.id, name: g.name }; });
  }

  // ── Discord › Serveur communautaire ───────────────────────────────────────

  const MODULES = [
    ['comm-salons-temporaires', 'Salons vocaux temporaires', 'salons_temporaires'],
    ['comm-journal', 'Journal de modération', 'journal_moderation'],
    ['comm-statut', 'Statut du live', 'statut_stream'],
    ['comm-bienvenue', 'Bienvenue', 'bienvenue'],
  ];

  /** Monte la carte d'un module dans `boite`, et la remonte avec la réponse
   *  du serveur après chaque enregistrement (un module désactivé perd son
   *  salon : l'écran doit le montrer). */
  function monterModule(boite, cle, donnees, catalogue) {
    const construire = CARTES[cle];
    const carte = construire(donnees[cle], catalogue, async function (bouton, corps) {
      const rep = await window.Formulaire.enregistrer(
        bouton, '/api/admin/discord/communaute/' + cle, 'PATCH', corps);
      if (rep) {
        const ancien = carte.el;
        monterModule(boite, cle, rep, catalogue);
        ancien.remove();
      }
    });
    boite.appendChild(carte.el);
  }

  const CARTES = {
    salons_temporaires: function (d, catalogue, envoyer) {
      const F = window.Formulaire;
      const c = F.carte('Réglages', 'Entrer dans le salon créateur ouvre un salon vocal perso, supprimé dès qu\'il est vide.');
      const actif = F.bascule(d.actif);
      const createur = F.salon(d.salon_createur_id, 'vocal');
      const noms = F.lignes(d.noms, { lignes: 8 });
      c.corps.appendChild(F.champ('Activé', actif));
      c.corps.appendChild(F.champ('Salon créateur', createur, 'Le salon vocal où il faut entrer.'));
      c.corps.appendChild(F.champ('Noms des salons', noms, 'Un par ligne, tiré au hasard. Sans nom, le salon s\'appelle « Nouveau salon ».', true));
      c.el.appendChild(F.note('Désactivé, Wally ne crée plus de salon et ne supprime plus non plus ceux encore ouverts : ils restent jusqu\'à ce qu\'on les efface à la main. Désactiver oublie le salon créateur.'));
      const b = F.bouton('Enregistrer', function () {
        envoyer(b, { actif: actif.checked, salon_createur_id: createur.value || null, noms: noms.lireListe() });
      });
      c.el.appendChild(F.actions(b));
      return c;
    },

    journal_moderation: function (d, catalogue, envoyer) {
      const F = window.Formulaire;
      const c = F.carte('Réglages', 'Messages supprimés ou modifiés, salons et mouvements vocaux, arrivées, départs, bans, surnoms et rôles.');
      const actif = F.bascule(d.actif);
      const salons = F.salons(d.salon_ids, 'texte');
      const guildes = cases(serveurs(catalogue), d.guild_ids);
      const bots = F.bascule(d.inclure_bots);
      c.corps.appendChild(F.champ('Activé', actif));
      c.corps.appendChild(F.champ('Inclure les bots', bots, 'Wally compris : il porte lui aussi le drapeau bot.'));
      c.corps.appendChild(F.champ('Serveurs observés', guildes, 'Les serveurs dont les événements sont journalisés.', true));
      c.corps.appendChild(F.champ('Salons du journal', salons, 'La même fiche part dans chacun. Ces salons et leurs fils ne sont jamais journalisés eux-mêmes.', true));
      c.el.appendChild(F.note('Désactiver vide la liste des salons du journal.'));
      const b = F.bouton('Enregistrer', function () {
        envoyer(b, { actif: actif.checked, salon_ids: salons.lireListe(), guild_ids: guildes.lireListe(), inclure_bots: bots.checked });
      });
      c.el.appendChild(F.actions(b));
      return c;
    },

    statut_stream: function (d, catalogue, envoyer) {
      const F = window.Formulaire;
      const c = F.carte('Réglages', 'Un salon renommé selon que le live Twitch est en cours ou non.');
      const actif = F.bascule(d.actif);
      const salon = F.salon(d.salon_id, 'texte');
      const live = F.texte(d.nom_live, { max: 100 });
      const horsLive = F.texte(d.nom_hors_live, { max: 100 });
      c.corps.appendChild(F.champ('Activé', actif));
      c.corps.appendChild(F.champ('Salon renommé', salon));
      c.corps.appendChild(F.champ('Nom pendant le live', live));
      c.corps.appendChild(F.champ('Nom hors live', horsLive));
      c.el.appendChild(F.note('Discord n\'autorise que deux renommages par salon toutes les dix minutes : un changement peut attendre. Désactiver oublie le salon choisi.'));
      const b = F.bouton('Enregistrer', function () {
        envoyer(b, { actif: actif.checked, salon_id: salon.value || null, nom_live: live.value, nom_hors_live: horsLive.value });
      });
      c.el.appendChild(F.actions(b));
      return c;
    },

    bienvenue: function (d, catalogue, envoyer) {
      const F = window.Formulaire;
      const c = F.carte('Réglages', 'Une fiche d\'accueil pour chaque nouveau membre : une phrase, un GIF et une anecdote traduite.');
      const actif = F.bascule(d.actif);
      const guildes = cases(serveurs(catalogue), d.guild_ids);
      const salon = F.salon(d.salon_id, 'texte', '— salon système du serveur —');
      const messages = F.lignes(d.messages, { lignes: 8 });
      const gifs = F.lignes(d.gifs, { lignes: 5 });
      c.corps.appendChild(F.champ('Activé', actif));
      c.corps.appendChild(F.champ('Salon d\'accueil', salon, 'Sans choix, la fiche part dans le salon système du serveur.'));
      c.corps.appendChild(F.champ('Serveurs accueillis', guildes, null, true));
      c.corps.appendChild(F.champ('Phrases d\'accueil', messages, 'Une par ligne, tirée au hasard. Sans phrase : « Bienvenue ! ».', true));
      c.corps.appendChild(F.champ('GIF', gifs, 'Une adresse par ligne, tirée au hasard.', true));
      c.el.appendChild(F.note('Désactiver vide la liste des serveurs accueillis.'));
      const b = F.bouton('Enregistrer', function () {
        envoyer(b, { actif: actif.checked, salon_id: salon.value || null, guild_ids: guildes.lireListe(), messages: messages.lireListe(), gifs: gifs.lireListe() });
      });
      c.el.appendChild(F.actions(b));
      return c;
    },
  };

  const SOUS_MODULES = {
    salons_temporaires: 'Un salon vocal perso pour qui entre dans le salon créateur.',
    journal_moderation: 'Ce qui se passe sur le serveur, consigné dans des salons de logs.',
    statut_stream: 'Le nom d\'un salon suit l\'état du live.',
    bienvenue: 'L\'accueil des nouveaux membres.',
  };

  window.renderCommunaute = async function (hote) {
    if (!hote) return;
    hote.textContent = '';
    const boites = {};
    MODULES.forEach(function (m) {
      const boite = el('div', 'page-section');
      boite.id = m[0];
      entete(boite, m[1], SOUS_MODULES[m[2]]);
      boite.appendChild(el('div', 'form-aide', 'Chargement…'));
      hote.appendChild(boite);
      boites[m[2]] = boite;
    });
    window.poserSommaire('discord/communaute', MODULES.map(function (m) { return [m[0], m[1]]; }), '');

    const [donnees, catalogue] = await Promise.all([
      lireJson('/api/admin/discord/communaute'),
      window.Formulaire.catalogueDiscord(),
    ]);
    MODULES.forEach(function (m) {
      const boite = boites[m[2]];
      entete(boite, m[1], SOUS_MODULES[m[2]]);
      if (!donnees) { boite.appendChild(el('div', 'form-aide', 'Erreur de chargement.')); return; }
      monterModule(boite, m[2], donnees, catalogue);
    });
  };

  // ── Discord › Salons : salons au rôle particulier ─────────────────────────

  const REGLES_SERVEUR = [
    ['', 'Règle générale'],
    ['tous', 'Tous les salons'],
    ['liste', 'Seulement les salons cochés'],
  ];

  /** Une ligne par serveur (ceux que Wally voit, plus ceux déjà réglés mais
   *  hors de sa vue). Lire `.lire()` → `{guild_id: null | [ids]}`. */
  function reglesParServeur(catalogue, actuel) {
    const F = window.Formulaire;
    const bloc = el('div');
    const lignes = [];
    const connus = new Set();
    const guildes = catalogue.map(function (g) { connus.add(g.id); return g; });
    Object.keys(actuel || {}).forEach(function (gid) {
      if (!connus.has(gid)) guildes.push({ id: gid, name: gid + ' (introuvable)', text_channels: [] });
    });
    guildes.forEach(function (g) {
      const valeur = actuel && Object.prototype.hasOwnProperty.call(actuel, g.id) ? actuel[g.id] : undefined;
      const regle = F.choix(REGLES_SERVEUR, valeur === undefined ? '' : valeur === null ? 'tous' : 'liste');
      const salons = cases(g.text_channels || [], Array.isArray(valeur) ? valeur : [], '#');
      function majVisibilite() { salons.hidden = regle.value !== 'liste'; }
      regle.addEventListener('change', majVisibilite);
      majVisibilite();
      const conteneur = el('div', 'form-grille');
      conteneur.appendChild(F.champ(g.name, regle));
      conteneur.appendChild(F.champ('Salons autorisés', salons, null, true));
      bloc.appendChild(conteneur);
      lignes.push({ id: g.id, regle: regle, salons: salons });
    });
    bloc.lire = function () {
      const sortie = {};
      lignes.forEach(function (l) {
        if (l.regle.value === 'tous') sortie[l.id] = null;
        else if (l.regle.value === 'liste') sortie[l.id] = l.salons.lireListe();
      });
      return sortie;
    };
    return bloc;
  }

  function cartesSalonsSpeciaux(conteneur, d, catalogue) {
    const F = window.Formulaire;
    const url = '/api/admin/discord/salons-speciaux';

    const c1 = F.carte('Salons où tout message s\'adresse à Wally', 'Wally y considère chaque message comme lui étant adressé, sans qu\'on le nomme.');
    const toujours = F.salons(d.always_trigger_channels, 'texte');
    c1.corps.appendChild(F.champ('Salons', toujours, 'Un salon ignoré le reste, même coché ici.', true));
    const b1 = F.bouton('Enregistrer', function () {
      F.enregistrer(b1, url, 'PATCH', { always_trigger_channels: toujours.lireListe() });
    });
    c1.el.appendChild(F.actions(b1));
    conteneur.appendChild(c1.el);

    const c2 = F.carte('Où Wally lit et répond', 'Les salons ignorés, plus haut, restent ignorés quelle que soit la règle choisie ici.');
    const mode = F.choix([['blacklist', 'Tous les salons, sauf les ignorés'], ['whitelist', 'Seulement la liste blanche']], d.channel_filter_mode);
    const blanche = F.salons(d.channel_whitelist, 'texte');
    const parServeur = reglesParServeur(catalogue, d.per_guild_channel_whitelist);
    c2.corps.appendChild(F.champ('Règle générale', mode));
    c2.corps.appendChild(F.champ('Liste blanche', blanche, 'Ne sert qu\'avec « Seulement la liste blanche ». Vide : tous les salons.', true));
    c2.corps.appendChild(F.champ('Règle par serveur', parServeur, 'Un serveur réglé ici ne suit plus la règle générale.', true));
    const b2 = F.bouton('Enregistrer', function () {
      F.enregistrer(b2, url, 'PATCH', {
        channel_filter_mode: mode.value,
        channel_whitelist: blanche.lireListe(),
        per_guild_channel_whitelist: parServeur.lire(),
      });
    });
    c2.el.appendChild(F.actions(b2));
    conteneur.appendChild(c2.el);

    const c3 = F.carte('Salons dédiés', null);
    const clips = F.salon(d.clips_channel_id, 'texte', '— aucun : pas de republication —');
    const memes = F.salon(d.meme_channel_id, 'texte', '— aucun : dépôt coupé —');
    const emotes = F.choix([['', 'Tous les serveurs']].concat(serveurs(catalogue).map(function (g) { return [g.id, g.name]; })), d.emote_guild_id || '');
    const proba = F.nombre(d.emoji_reaction_probability, { min: 0, max: 1, pas: 0.01 });
    c3.corps.appendChild(F.champ('Salon des clips', clips, 'Les clips Twitch joués sur l\'overlay y sont republiés.'));
    c3.corps.appendChild(F.champ('Dépôt des memes', memes, 'Toute image postée ici entre dans la banque de memes.'));
    c3.corps.appendChild(F.champ('Serveur des emotes', emotes, 'Le serveur dont Wally décrit lui-même les emotes pas encore expliquées. Par défaut, tous.'));
    c3.corps.appendChild(F.champ('Réaction spontanée', proba, 'Probabilité (0 à 1) de réagir d\'un emoji à un message qui ne lui est pas adressé.'));
    c3.el.appendChild(F.note('Serveur des emotes : le passage complet a lieu au démarrage du bot. Après un changement, seules les emotes ajoutées ensuite sont décrites, jusqu\'au prochain redémarrage.'));
    const b3 = F.bouton('Enregistrer', function () {
      const p = Number(proba.value);
      if (proba.value === '' || !(p >= 0 && p <= 1)) { window.toast('Réaction spontanée : un nombre entre 0 et 1.', 'error'); return; }
      F.enregistrer(b3, url, 'PATCH', {
        clips_channel_id: clips.value || null,
        meme_channel_id: memes.value || null,
        emote_guild_id: emotes.value || null,
        emoji_reaction_probability: p,
      });
    });
    c3.el.appendChild(F.actions(b3));
    conteneur.appendChild(c3.el);
  }

  window.renderSalonsSpeciaux = async function (boite) {
    const titre = 'Salons au rôle particulier';
    const sous = 'Les salons où Wally se sent toujours sollicité, où il a le droit de parler, et ceux qui servent à une seule chose.';
    entete(boite, titre, sous);
    boite.appendChild(el('div', 'form-aide', 'Chargement…'));
    const [d, catalogue] = await Promise.all([
      lireJson('/api/admin/discord/salons-speciaux'),
      window.Formulaire.catalogueDiscord(),
    ]);
    entete(boite, titre, sous);
    if (!d) { boite.appendChild(el('div', 'form-aide', 'Erreur de chargement.')); return; }
    cartesSalonsSpeciaux(boite, d, catalogue);
  };

  // ── Discord › Anti-spam : sourdine sur colère ─────────────────────────────

  window.renderAntiSpamColere = async function (boite) {
    const F = window.Formulaire;
    const titre = 'Sourdine sur colère';
    const sous = 'Quand un message pousse la colère de Wally à 0,8 ou plus, il compte comme un déclenchement pour son auteur. '
      + 'Au seuil, en cinq minutes, la personne passe en sourdine : Wally ne lui répond plus que par des réactions. Ses proches n\'y passent jamais.';
    entete(boite, titre, sous);
    const d = await lireJson('/api/admin/discord/colere');
    if (!d) { boite.appendChild(el('div', 'form-aide', 'Erreur de chargement.')); return; }
    const c = F.carte(null, null);
    const seuil = F.nombre(d.anger_trigger_threshold, { min: 1, max: 50 });
    const duree = F.nombre(d.timeout_minutes, { min: 1, max: 1440 });
    c.corps.appendChild(F.champ('Déclenchements avant la sourdine', seuil, 'Entre 1 et 50, sur cinq minutes.'));
    c.corps.appendChild(F.champ('Durée de la sourdine (minutes)', duree, 'Entre 1 et 1440.'));
    const b = F.bouton('Enregistrer', function () {
      F.enregistrer(b, '/api/admin/discord/colere', 'PATCH', {
        anger_trigger_threshold: Number(seuil.value),
        timeout_minutes: Number(duree.value),
      });
    });
    c.el.appendChild(F.actions(b));
    boite.appendChild(c.el);
  };
})();
