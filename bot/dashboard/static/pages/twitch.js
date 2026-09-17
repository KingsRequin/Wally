// pages/twitch.js — Twitch › Chat & événements, Twitch › Apex.
//
// Chaque réglage affiché a un lecteur dans le code du bot. Ce qui est relu à
// chaque usage prend effet tout de suite ; ce qui n'est lu qu'au démarrage
// (`bot/main.py`) porte une note qui le dit — jamais « à chaud » par défaut.

(function () {
  const F = window.Formulaire;
  const NOTE_REDEMARRAGE = 'Pris en compte au prochain redémarrage du bot.';

  function el(tag, classe, texte) {
    const n = document.createElement(tag);
    if (classe) n.className = classe;
    if (texte != null) n.textContent = texte;
    return n;
  }

  function section(id, titre, sous) {
    const s = el('div', 'page-section');
    s.id = id;
    s.appendChild(el('div', 'page-section-titre', titre));
    if (sous) s.appendChild(el('div', 'page-section-sous', sous));
    return s;
  }

  async function charger(hote, url) {
    hote.textContent = 'Chargement…';
    const r = await window.apiFetch(url);
    let d = null;
    // Une réponse qui n'est pas du JSON (route absente d'une image pas encore
    // reconstruite : le catch-all rend la page HTML en 200) se dit à l'écran.
    try { d = (r && r.ok) ? await r.json() : null; } catch (e) { d = null; }
    hote.textContent = d ? '' : 'Impossible de charger les réglages (' + url + ').';
    return d;
  }

  function nombreLu(input) {
    return input.value === '' ? null : Number(input.value);
  }

  // ─── Chat & événements ──────────────────────────────────────────────────

  window.renderTwitchChat = async function (hote) {
    if (!hote) return;
    const d = await charger(hote, '/api/admin/twitch/chat');
    if (!d) return;
    const b = d.bornes;

    // Remerciements automatiques
    const sEv = section('twitch-chat-evenements', 'Remerciements automatiques',
      'Le message sert de consigne : Wally rédige sa propre réaction à partir de lui. '
      + 'Désactivé, l\'événement est quand même perçu (émotion, overlay), seul le message ne part pas.');
    const champsEv = {};
    d.evenements.forEach(function (ev) {
      const c = F.carte(ev.libelle, null);
      const actif = F.bascule(ev.active);
      const msg = F.zone(ev.message, { lignes: 2, max: b.message_max });
      const vars = ev.variables.map(function (v) { return '{' + v + '}'; }).join(', ');
      c.corps.appendChild(F.champ('Activé', actif));
      c.corps.appendChild(F.champ('Message', msg, 'Variables disponibles : ' + vars, true));
      champsEv[ev.cle] = { actif: actif, msg: msg };
      sEv.appendChild(c.el);
    });
    const cEvActions = F.carte(null, null);
    const btnEv = F.bouton('Enregistrer les remerciements', async function () {
      const evenements = {};
      Object.keys(champsEv).forEach(function (cle) {
        evenements[cle] = { active: champsEv[cle].actif.checked, message: champsEv[cle].msg.value };
      });
      await F.enregistrer(btnEv, '/api/admin/twitch/chat', 'PATCH', { evenements: evenements },
        'Remerciements enregistrés');
    });
    cEvActions.corps.appendChild(F.note('Pris en compte dès le prochain événement.'));
    cEvActions.el.appendChild(F.actions(btnEv));
    sEv.appendChild(cEvActions.el);

    // Réponses dans le chat
    const sRep = section('twitch-chat-reponses', 'Réponses dans le chat',
      'Le rythme des réponses de Wally aux viewers.');
    const cRep = F.carte(null, null);
    const cooldown = F.nombre(d.cooldown_seconds, { min: 0, max: b.cooldown_max_s });
    const attente = F.nombre(d.attente_seuil_s, { min: 0, max: b.attente_max_s, pas: 0.5 });
    cRep.corps.appendChild(F.champ('Délai entre deux réponses à une même personne (s)', cooldown,
      '0 pour aucun délai.'));
    cRep.corps.appendChild(F.champ('Message d\'attente au-delà de (s)', attente,
      'Si la réponse tarde plus que ce délai, Wally prévient qu\'il arrive. 0 l\'éteint.'));
    const btnRep = F.bouton('Enregistrer', async function () {
      await F.enregistrer(btnRep, '/api/admin/twitch/chat', 'PATCH', {
        cooldown_seconds: nombreLu(cooldown),
        attente_seuil_s: nombreLu(attente),
      });
    });
    cRep.corps.appendChild(F.note('Pris en compte au prochain message.'));
    cRep.el.appendChild(F.actions(btnRep));
    sRep.appendChild(cRep.el);

    // Raid
    const sRaid = section('twitch-chat-raid', 'Raid',
      'Le shoutout officiel Twitch du raideur, indépendant du message de remerciement.');
    const cRaid = F.carte(null, null);
    const shoutout = F.bascule(d.shoutout_raid);
    cRaid.corps.appendChild(F.champ('Shoutout automatique au raid', shoutout,
      'Twitch impose sa propre cadence (2 min entre deux shoutouts, 1 h sur la même chaîne).'));
    const btnRaid = F.bouton('Enregistrer', async function () {
      await F.enregistrer(btnRaid, '/api/admin/twitch/chat', 'PATCH', { shoutout_raid: shoutout.checked });
    });
    cRaid.corps.appendChild(F.note('Pris en compte au prochain raid.'));
    cRaid.el.appendChild(F.actions(btnRaid));
    sRaid.appendChild(cRaid.el);

    // Rappels automatiques
    const sAnn = section('twitch-chat-rappels', 'Rappels automatiques',
      'Les rappels que Wally publie seul pendant le live. Leur texte vit dans la persona (ANNONCES.md).');
    const cAnn = F.carte(null, null);
    const annActif = F.bascule(d.annonces_auto.active);
    const annCadence = F.nombre(d.annonces_auto.cadence_minutes,
      { min: b.cadence_annonces_min, max: b.cadence_annonces_max });
    cAnn.corps.appendChild(F.champ('Activés', annActif));
    cAnn.corps.appendChild(F.champ('Un rappel toutes les (minutes)', annCadence));
    const btnAnn = F.bouton('Enregistrer', async function () {
      await F.enregistrer(btnAnn, '/api/admin/twitch/chat', 'PATCH', {
        annonces_auto: { active: annActif.checked, cadence_minutes: nombreLu(annCadence) },
      });
    });
    cAnn.corps.appendChild(F.note(NOTE_REDEMARRAGE));
    cAnn.el.appendChild(F.actions(btnAnn));
    sAnn.appendChild(cAnn.el);

    [sEv, sRep, sRaid, sAnn].forEach(function (s) { hote.appendChild(s); });
    window.poserSommaire('twitch/chat', [
      ['twitch-chat-evenements', 'Remerciements automatiques'],
      ['twitch-chat-reponses', 'Réponses dans le chat'],
      ['twitch-chat-raid', 'Raid'],
      ['twitch-chat-rappels', 'Rappels automatiques'],
    ], '');
  };

  // ─── Apex ───────────────────────────────────────────────────────────────

  window.renderApex = async function (hote) {
    if (!hote) return;
    const d = await charger(hote, '/api/admin/apex/reglages');
    if (!d) return;
    const b = d.bornes;
    const du = d.duel;

    // Compte suivi
    const sCompte = section('apex-compte', 'Compte suivi',
      'Le compte Apex du streamer, suivi pendant ses lives. Vide, le suivi est désactivé.');
    const cCompte = F.carte(null, null);
    const compte = F.texte(d.streamer_account, { max: b.compte_max, placeholder: 'pseudo Apex' });
    const plateforme = F.choix(d.plateformes, d.streamer_platform);
    cCompte.corps.appendChild(F.champ('Pseudo Apex', compte));
    cCompte.corps.appendChild(F.champ('Plateforme', plateforme));
    const btnCompte = F.bouton('Enregistrer', async function () {
      await F.enregistrer(btnCompte, '/api/admin/apex/reglages', 'PATCH', {
        streamer_account: compte.value, streamer_platform: plateforme.value,
      });
    });
    cCompte.corps.appendChild(F.note(NOTE_REDEMARRAGE));
    cCompte.el.appendChild(F.actions(btnCompte));
    sCompte.appendChild(cCompte.el);

    // Duel
    const sDuel = section('apex-duel', 'Duel en points de chaîne',
      'Un viewer paie pour affronter le streamer : le plus de kills sur les manches gagne.');
    const cDuel = F.carte(null, null);
    const actif = F.bascule(du.active);
    const manches = F.nombre(du.manches, { min: 1, max: b.manches_max });
    const modeJeu = F.texte(du.mode_jeu, { max: b.mode_jeu_max });
    const attente = F.nombre(du.attente_squad_min, { min: 1, max: b.attente_squad_max_min, pas: 1 });
    cDuel.corps.appendChild(F.champ('Duel activé', actif,
      'Il faut aussi la récompense active, une clé Apex, et l\'uid du compte dans les demandeurs vocaux.'));
    cDuel.corps.appendChild(F.champ('Manches', manches,
      'Le texte de la récompense annonce le nombre de manches : le garder cohérent.'));
    cDuel.corps.appendChild(F.champ('Mode de jeu annoncé', modeJeu,
      'Dit à l\'ouverture du duel. L\'API ne permet pas de le vérifier ; la Mixtape ne compte aucun kill.'));
    cDuel.corps.appendChild(F.champ('Attente de l\'escouade (minutes)', attente,
      'Délai laissé aux deux joueurs pour lancer la première partie.'));
    const lien = el('a', '', 'Prix et texte : Twitch › Récompenses');
    lien.href = '#/twitch/recompenses';
    cDuel.corps.appendChild(lien);
    sDuel.appendChild(cDuel.el);

    // Mesure
    const cMesure = F.carte('Mesure des manches', 'Réglages fins de la lecture des scores. Les défauts sont mesurés en live.');
    const cadence = F.nombre(du.cadence_s, { min: b.cadence_min_s, max: b.cadence_max_s, pas: 0.5 });
    const marge = F.nombre(du.marge_lobby_s, { min: 0, max: b.plafond_marge_lobby_s, pas: 1 });
    const plafond = F.nombre(du.plafond_kills_manche, { min: b.plafond_kills_min, max: b.plafond_kills_max });
    const muette = F.nombre(du.api_muette_max_s, { min: b.api_muette_min_s, max: b.api_muette_max_s, pas: 10 });
    cMesure.corps.appendChild(F.champ('Un relevé toutes les (s)', cadence,
      'Pendant une manche. Chaque relevé interroge deux comptes.'));
    cMesure.corps.appendChild(F.champ('Marge au lobby (s)', marge,
      'Attente avant de figer le score. Marge + deux relevés doit tenir en '
      + b.plafond_marge_lobby_s + ' s, le temps entre deux parties.'));
    cMesure.corps.appendChild(F.champ('Plafond de kills par manche', plafond,
      'Au-delà, c\'est un compteur qui rattrape des semaines, pas un score. Un ordre de grandeur, pas une limite serrée.'));
    cMesure.corps.appendChild(F.champ('Silence de l\'API toléré (s)', muette,
      'Au-delà, le duel est abandonné et les points rendus.'));
    sDuel.appendChild(cMesure.el);

    const cAct = F.carte(null, null);
    const btnDuel = F.bouton('Enregistrer le duel', async function () {
      await F.enregistrer(btnDuel, '/api/admin/apex/reglages', 'PATCH', {
        duel: {
          active: actif.checked,
          manches: nombreLu(manches),
          mode_jeu: modeJeu.value,
          attente_squad_min: nombreLu(attente),
          cadence_s: nombreLu(cadence),
          marge_lobby_s: nombreLu(marge),
          plafond_kills_manche: nombreLu(plafond),
          api_muette_max_s: nombreLu(muette),
        },
      }, 'Duel enregistré');
    });
    cAct.corps.appendChild(F.note(NOTE_REDEMARRAGE + ' Un duel déjà en cours garde ses règles.'));
    cAct.el.appendChild(F.actions(btnDuel));
    sDuel.appendChild(cAct.el);

    hote.appendChild(sCompte);
    hote.appendChild(sDuel);
    window.poserSommaire('twitch/apex', [
      ['apex-compte', 'Compte suivi'],
      ['apex-duel', 'Duel en points de chaîne'],
    ], '');
  };
})();
