// formulaires.js — LE modèle de formulaire du panel admin.
//
// Quatre styles cohabitaient (titres en capitales + « 💾 SAUVEGARDER », `h3` +
// boutons `neo-*`, grilles maison, mise en page brute). Toute section de
// réglages se construit désormais ici : une carte, des champs libellés en
// français, une ligne d'actions, un enregistrement qui dit ce que le serveur a
// répondu.
//
// Chargé AVANT app.js et les pages : ses fonctions n'appellent `window.apiFetch` et
// `window.toast` qu'au moment d'un clic, quand app.js est chargé (le lint ne
// connaît pas les globales d'app.js : on les lit sur `window`, comme overlay_admin.js).
//
// Les ids Discord voyagent en CHAÎNES d'un bout à l'autre (un snowflake dépasse
// 2^53 : `Number` l'arrondit sans rien dire).

window.Formulaire = (function () {
  function el(tag, classe, texte) {
    const n = document.createElement(tag);
    if (classe) n.className = classe;
    if (texte != null) n.textContent = texte;
    return n;
  }

  /** Une section de réglages : `{ el, corps }`. `corps` reçoit les champs. */
  function carte(titre, sous) {
    const racine = el('div', 'form-carte');
    if (titre) racine.appendChild(el('div', 'form-carte-titre', titre));
    if (sous) racine.appendChild(el('div', 'form-carte-sous', sous));
    const corps = el('div', 'form-grille');
    racine.appendChild(corps);
    return { el: racine, corps: corps };
  }

  /** Un champ libellé. `large` le fait tenir toute la largeur de la grille. */
  function champ(libelle, input, aide, large) {
    const bloc = el('label', 'form-champ' + (large ? ' form-champ-large' : ''));
    bloc.appendChild(el('span', 'form-libelle', libelle));
    bloc.appendChild(input);
    if (aide) bloc.appendChild(el('span', 'form-aide', aide));
    return bloc;
  }

  function texte(valeur, opts) {
    const i = el('input', 'form-input');
    i.type = (opts && opts.type) || 'text';
    i.value = valeur == null ? '' : String(valeur);
    if (opts && opts.max) i.maxLength = opts.max;
    if (opts && opts.placeholder) i.placeholder = opts.placeholder;
    return i;
  }

  function nombre(valeur, opts) {
    const i = el('input', 'form-input');
    i.type = 'number';
    if (opts && opts.min != null) i.min = String(opts.min);
    if (opts && opts.max != null) i.max = String(opts.max);
    i.step = String((opts && opts.pas) || 1);
    i.value = valeur == null ? '' : String(valeur);
    return i;
  }

  /** Case à cocher ; lire `.checked`. */
  function bascule(valeur) {
    const i = el('input', 'form-bascule');
    i.type = 'checkbox';
    i.checked = !!valeur;
    return i;
  }

  /** `options` = [[valeur, libellé], …]. La valeur actuelle reste présente
   *  même absente de la liste : la masquer ferait écrire autre chose. */
  function choix(options, actuel) {
    const s = el('select', 'form-input');
    const liste = options.slice();
    if (actuel != null && actuel !== '' && !liste.some(function (o) { return String(o[0]) === String(actuel); })) {
      liste.unshift([actuel, String(actuel)]);
    }
    liste.forEach(function (o) {
      const opt = el('option', '', o[1]);
      opt.value = String(o[0]);
      if (actuel != null && String(o[0]) === String(actuel)) opt.selected = true;
      s.appendChild(opt);
    });
    return s;
  }

  function zone(valeur, opts) {
    const t = el('textarea', 'form-input');
    t.rows = (opts && opts.lignes) || 3;
    if (opts && opts.max) t.maxLength = opts.max;
    t.value = valeur == null ? '' : String(valeur);
    return t;
  }

  /** Une liste de lignes (une par ligne) → tableau de chaînes non vides. */
  function lignes(valeurs, opts) {
    const t = zone((valeurs || []).join('\n'), opts);
    t.lireListe = function () {
      return t.value.split('\n').map(function (s) { return s.trim(); }).filter(Boolean);
    };
    return t;
  }

  // Catalogue Discord (serveurs, salons textuels/vocaux, catégories, rôles),
  // chargé une fois par page et partagé.
  let _catalogue = null;
  async function catalogueDiscord(forcer) {
    if (_catalogue && !forcer) return _catalogue;
    const r = await window.apiFetch('/api/admin/discord/catalogue');
    let guilds = [];
    try {
      guilds = (r && r.ok) ? ((await r.json()) || {}).guilds || [] : [];
    } catch (e) {
      // Route absente (bot pas encore reconstruit) : le catch-all SPA répond
      // 200 en HTML, et `json()` lève. Un catalogue vide laisse les sélecteurs
      // montrer les ids connus « (introuvable) » au lieu de casser la section.
      guilds = [];
    }
    _catalogue = guilds;
    return _catalogue;
  }

  /** Sélecteur de salon. `genre` : 'texte' | 'vocal' | 'categorie'.
   *  À appeler après `await catalogueDiscord()`. Vide = aucun. */
  function salon(valeur, genre, libelleVide) {
    const cle = { texte: 'text_channels', vocal: 'voice_channels', categorie: 'categories' }[genre || 'texte'];
    const s = el('select', 'form-input');
    const vide = el('option', '', libelleVide || '— aucun —');
    vide.value = '';
    s.appendChild(vide);
    let trouve = !valeur;
    (_catalogue || []).forEach(function (g) {
      const groupe = el('optgroup');
      groupe.label = g.name;
      (g[cle] || []).forEach(function (c) {
        const opt = el('option', '', (genre === 'categorie' ? '' : genre === 'vocal' ? '🔊 ' : '#') + c.name);
        opt.value = String(c.id);
        if (valeur && String(c.id) === String(valeur)) { opt.selected = true; trouve = true; }
        groupe.appendChild(opt);
      });
      s.appendChild(groupe);
    });
    if (!trouve) {
      // Un salon supprimé ou hors de portée reste affiché : le faire
      // disparaître changerait le réglage au premier enregistrement.
      const opt = el('option', '', String(valeur) + ' (introuvable)');
      opt.value = String(valeur);
      opt.selected = true;
      s.appendChild(opt);
    }
    return s;
  }

  /** Plusieurs salons (cases à cocher par serveur). Lire `.lireListe()`. */
  function salons(valeurs, genre) {
    const cle = { texte: 'text_channels', vocal: 'voice_channels', categorie: 'categories' }[genre || 'texte'];
    const coches = new Set((valeurs || []).map(String));
    const boite = el('div', 'form-multi');
    (_catalogue || []).forEach(function (g) {
      boite.appendChild(el('div', 'form-multi-groupe', g.name));
      (g[cle] || []).forEach(function (c) {
        const ligne = el('label', 'form-multi-ligne');
        const cb = el('input');
        cb.type = 'checkbox';
        cb.value = String(c.id);
        cb.checked = coches.has(String(c.id));
        coches.delete(String(c.id));
        ligne.appendChild(cb);
        ligne.appendChild(el('span', '', (genre === 'vocal' ? '🔊 ' : '#') + c.name));
        boite.appendChild(ligne);
      });
    });
    // Ids inconnus du catalogue : montrés cochés, « (introuvable) ». Ni perdus
    // en silence, ni gardés invisibles — on doit pouvoir les décocher.
    const orphelins = Array.from(coches);
    if (orphelins.length) boite.appendChild(el('div', 'form-multi-groupe', 'Hors catalogue'));
    orphelins.forEach(function (id) {
      const ligne = el('label', 'form-multi-ligne');
      const cb = el('input');
      cb.type = 'checkbox';
      cb.value = id;
      cb.checked = true;
      ligne.appendChild(cb);
      ligne.appendChild(el('span', '', id + ' (introuvable)'));
      boite.appendChild(ligne);
    });
    if (!(_catalogue || []).length && !orphelins.length) {
      boite.appendChild(el('div', 'form-aide', 'Aucun salon disponible (bot Discord arrêté ?).'));
    }
    boite.lireListe = function () {
      return Array.from(boite.querySelectorAll('input[type=checkbox]:checked'))
        .map(function (cb) { return cb.value; });
    };
    return boite;
  }

  /** Choix de fichier(s) : un bouton en français à la place du champ natif
   *  « Choose File / No file chosen ». Rend `{ el, input }` ; lire `input.files`. */
  function fichier(opts) {
    const o = opts || {};
    const racine = el('label', 'form-fichier');
    const input = el('input');
    input.type = 'file';
    if (o.id) input.id = o.id;
    if (o.accept) input.accept = o.accept;
    input.multiple = !!o.multiple;
    const bouton_ = el('span', 'btn btn-outline', o.multiple ? 'Choisir des fichiers' : 'Choisir un fichier');
    const nom = el('span', 'form-fichier-nom', 'Aucun fichier choisi');
    input.addEventListener('change', function () {
      const n = input.files ? input.files.length : 0;
      nom.textContent = n === 0 ? 'Aucun fichier choisi'
        : n === 1 ? input.files[0].name : n + ' fichiers choisis';
    });
    racine.appendChild(input);
    racine.appendChild(bouton_);
    racine.appendChild(nom);
    return { el: racine, input: input };
  }

  function bouton(libelle, onclick, opts) {
    const b = el('button', 'btn ' + ((opts && opts.danger) ? 'btn-danger' : (opts && opts.discret) ? 'btn-outline' : 'btn-success'), libelle);
    b.type = 'button';
    b.onclick = onclick;
    return b;
  }

  function actions() {
    const ligne = el('div', 'form-actions');
    Array.prototype.slice.call(arguments).forEach(function (b) { if (b) ligne.appendChild(b); });
    return ligne;
  }

  /** Avertissement « pris en compte au prochain redémarrage », etc. */
  function note(texteNote) {
    return el('div', 'form-note', texteNote);
  }

  /** Envoie `corps()` et dit ce que le serveur a répondu. Rend la réponse JSON
   *  (ou `null` en échec). Le bouton est désactivé pendant l'envoi. */
  async function enregistrer(bouton_, url, methode, corps, messageOk) {
    if (bouton_) bouton_.disabled = true;
    let r = null, donnees = null;
    try {
      r = await window.apiFetch(url, { method: methode || 'POST', body: JSON.stringify(corps) });
      try { donnees = r ? await r.json() : null; } catch (e) { donnees = null; }
    } finally {
      if (bouton_) bouton_.disabled = false;
    }
    if (!r || !r.ok) {
      const detail = donnees && donnees.detail;
      window.toast(typeof detail === 'string' ? detail : 'Erreur d\'enregistrement', 'error');
      return null;
    }
    window.toast(messageOk || 'Enregistré', 'success');
    return donnees || {};
  }

  return {
    carte: carte, champ: champ, texte: texte, nombre: nombre, bascule: bascule,
    choix: choix, zone: zone, lignes: lignes, salon: salon, salons: salons,
    fichier: fichier,
    catalogueDiscord: catalogueDiscord, bouton: bouton, actions: actions,
    note: note, enregistrer: enregistrer,
  };
})();
