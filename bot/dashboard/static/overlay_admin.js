// bot/dashboard/static/overlay_admin.js
//
// Le panneau de mise en scène de l'overlay : la liste des scènes, la liste des
// éléments, et la surface où on les place.
//
// Écrit hors d'`app.js` — qui pèse déjà 5679 lignes — parce que ce seul panneau
// en vaut plusieurs centaines. `app.js` n'en connaît que trois lignes : le
// conteneur qu'il nous passe.
//
// Deux principes gouvernent le fichier :
//
//   1. **Rien ne part tout seul.** Une modification reste dans le navigateur
//      jusqu'à « Mettre à jour ». On règle la scène de fin pendant que le live
//      tourne sans que l'écran bouge d'un pixel. La case « Publier au fil de
//      l'eau » lève cette règle, et elle est DÉCOCHÉE par défaut : le cas
//      dangereux ne doit jamais être celui qu'on obtient sans rien faire.
//   2. **Aucune exception ne sort d'ici.** Un `throw` dans un montage casse
//      toutes les sections suivantes du panneau — c'est un incident déjà payé
//      ici (`buildSections`). `monter()` est synchrone et enveloppé ; le
//      chargement réseau vit dans sa propre promesse.
window.OverlayAdmin = (function () {
  "use strict";

  const URL_LAYOUT = "/api/admin/overlay/layout";
  const URL_APERCU = "/api/admin/overlay/preview";
  const CANVAS_W = 1920;
  // Au-delà, on considère que l'aperçu ne viendra pas et on reste sur les
  // rectangles nommés. Un aperçu absent ne doit jamais empêcher de placer.
  const APERCU_DELAI_MS = 8000;

  // Les slugs que les routes existantes occupent déjà (`/overlay-image`,
  // `/overlay-rotation`, `/api/.../version`, `/health`). Une scène qui en
  // prendrait un masquerait la route. Miroir de `SLUGS_RESERVES`
  // (bot/core/overlay_layout.py) — le serveur tranche, on évite juste de lui
  // proposer l'impossible.
  const SLUGS_RESERVES = ["image", "rotation", "version", "health"];

  // Les libellés lisibles NE SONT PAS écrits ici : ils viennent du serveur, avec
  // le layout (`bot/core/overlay_elements.py`, joint à la réponse du GET). Une
  // seconde table ici aurait dérivé de la première au premier widget ajouté, et
  // c'est justement le reproche auquel ce panneau répond — « apex prédateur ??
  // ». Une clé sans libellé s'affiche telle quelle plutôt que de disparaître.

  // L'encombrement supposé de chaque élément vit dans `WallyLayout` : la page
  // d'overlay s'en sert AUSSI (les repères de « Tout afficher »), et deux
  // tables auraient divergé au premier widget ajouté. Le repli couvre le cas où
  // `overlay_layout.js` n'aurait pas été servi.
  const TAILLE_REPLI = [400, 260];

  function tailleElement(cle) {
    const W = window.WallyLayout;
    return (W && typeof W.taille === "function" && W.taille(cle)) || TAILLE_REPLI;
  }

  // La grille de neuf cases, dans l'ordre où elle s'affiche.
  const ANCRAGES = [
    "top-left", "top-center", "top-right",
    "middle-left", "center", "middle-right",
    "bottom-left", "bottom-center", "bottom-right",
  ];

  // ── Les bornes et les pas de la manipulation ────────────────────────────
  //
  // Les mêmes bornes que le modèle (`bot/core/overlay_layout.py`). Elles sont
  // appliquées À LA SAISIE et pas seulement à l'enregistrement : sinon le
  // repère continue de suivre le pointeur hors du cadre, puis revient en
  // arrière au relâchement — on ne sait plus ce qu'on a posé.
  const POS_MIN = 0, POS_MAX = 100;
  const ECHELLE_MIN = 0.2, ECHELLE_MAX = 2.0;
  // Une flèche vaut 0,1 % — environ deux pixels sur 1920. Avec Maj, 1 %.
  const PAS_FIN = 0.1, PAS_GROS = 1;
  // Le pas de la grille d'aimantation, en pourcentage, et sa portée en PIXELS
  // d'écran : exprimée en pourcentage, elle accrocherait deux fois plus fort
  // sur une surface deux fois plus petite.
  const GRILLE = 10, AIMANT_PX = 8;
  const COINS = ["nw", "ne", "sw", "se"];
  const TOUCHES = {
    ArrowLeft: [-1, 0], ArrowRight: [1, 0], ArrowUp: [0, -1], ArrowDown: [0, 1],
  };

  /** L'état du panneau.
   *
   *  `brouillon` est un COMPTEUR : le nombre de modifications non publiées.
   *  Zéro vaut « rien en attente ». `direct` porte la case « Publier au fil de
   *  l'eau » ; toujours faux au chargement, et JAMAIS retenu d'une visite à
   *  l'autre — une préférence qui survit ferait qu'on ouvre le panneau en plein
   *  live avec la publication immédiate déjà armée, sans l'avoir demandé.
   *
   *  `publie` est le modèle À L'ANTENNE, sérialisé, tel que le serveur nous l'a
   *  rendu au dernier aller-retour. Il sert deux fois : à repérer qu'un autre
   *  onglet a publié entre-temps, et à garder un cran d'annulation.
   *  `precedent` est ce même modèle d'AVANT la dernière publication.
   */
  const etat = {
    layout: null,
    libelles: {},   // clé → {nom, description}, servi par le GET du layout
    slugCourant: null,
    elementCourant: null,
    brouillon: 0,
    direct: false,
    publie: null,
    precedent: null,
  };

  const noeuds = {};      // les nœuds du squelette, posés une fois
  let menuOuvert = null;  // le menu ⋮ déployé, s'il y en a un
  let manip = null;       // la manipulation en cours sur la surface, ou null
  let observateur = null; // ResizeObserver de la surface
  let glisse = null;      // la clé de l'élément en cours de glisser dans la liste
  let infobulle = null;   // l'unique bulle d'aide, posée sur <body>
  let apercuSlug = null;      // la scène actuellement chargée dans l'iframe
  let apercuMinuteur = null;  // le délai au bout duquel on bascule sur le repli
  let survole = null;         // la clé de l'élément survolé, liste OU surface

  // La scène qu'on éditait, d'une visite à l'autre. Sans elle, un F5 ramène sur
  // la scène par défaut : le réglage qu'on venait de publier sur une AUTRE
  // scène a alors l'air d'avoir disparu — l'élément est bien à sa place, mais
  // on regarde une autre scène. C'est exactement ce qu'on lit comme « ça ne
  // persiste pas ».
  const CLE_SCENE = "wally.overlay.scene";

  /** Le stockage local peut lever (mode privé, stockage refusé, quota) : une
   *  préférence d'affichage ne doit jamais empêcher le panneau de s'ouvrir. */
  function sceneRetenue() {
    try {
      return window.localStorage.getItem(CLE_SCENE);
    } catch (e) {
      return null;
    }
  }

  function retenirScene(slug) {
    if (!slug) return;
    try {
      window.localStorage.setItem(CLE_SCENE, slug);
    } catch (e) {
      // Stockage refusé : on perd la mémoire de la scène, rien d'autre.
    }
  }

  // Le brouillon en attente, d'une visite à l'autre. Dans le NAVIGATEUR et
  // jamais en base : rangé côté serveur, il serait servi aux pages d'overlay au
  // prochain redémarrage du bot — donc publié à l'antenne sans avoir jamais été
  // validé. C'est exactement ce que le brouillon existe pour empêcher.
  const CLE_BROUILLON = "wally.overlay.brouillon";

  function rangerBrouillon() {
    if (!etat.layout) return;
    try {
      window.localStorage.setItem(CLE_BROUILLON, JSON.stringify({
        quand: Date.now(),
        n: etat.brouillon,
        base: etat.publie,      // ce qui était à l'antenne quand on l'a écrit
        scene: etat.slugCourant,
        layout: etat.layout,
      }));
    } catch (e) {
      // Stockage refusé ou plein : le brouillon reste valable à l'écran, il ne
      // survivra simplement pas au rechargement.
    }
  }

  function oublierBrouillon() {
    try {
      window.localStorage.removeItem(CLE_BROUILLON);
    } catch (e) {
      // Rien à défaire.
    }
  }

  /** Le brouillon rangé, ou `null`. Un contenu tordu (quota tronqué, version
   *  d'avant) ne doit pas empêcher le panneau de s'ouvrir : on le jette. */
  function lireBrouillon() {
    let brut = null;
    try {
      brut = window.localStorage.getItem(CLE_BROUILLON);
    } catch (e) {
      return null;
    }
    if (!brut) return null;
    let d = null;
    try {
      d = JSON.parse(brut);
    } catch (e) {
      return null;
    }
    if (!d || !d.n || !d.layout || !d.layout.scenes || !d.layout.scenes.length) {
      return null;
    }
    return d;
  }

  /** L'âge du brouillon, en clair. « Il y a deux heures » dit tout de suite
   *  s'il s'agit du travail d'avant le F5 ou d'un oubli d'avant-hier. */
  function depuis(quand) {
    const s = Math.max(0, Math.round((Date.now() - Number(quand || 0)) / 1000));
    if (!isFinite(s) || s < 90) return "il y a moins d'une minute";
    const m = Math.round(s / 60);
    if (m < 90) return "il y a " + m + " minutes";
    const h = Math.round(m / 60);
    if (h < 36) return "il y a " + h + " heure" + (h > 1 ? "s" : "");
    return "il y a " + Math.round(h / 24) + " jours";
  }

  // ── Petits outils ───────────────────────────────────────────────────────

  function creer(tag, cls, texte) {
    const n = document.createElement(tag);
    if (cls) n.className = cls;
    if (texte !== undefined && texte !== null) n.textContent = texte;
    return n;
  }

  /** L'icône « copier », en SVG comme celles de la barre latérale.
   *
   *  Ni emoji ni glyphe Unicode : 📋 sort en carré vide dans un navigateur sans
   *  police emoji couleur — constaté à l'écran ici même —, et ⧉ manque à
   *  presque toutes les polices système. Un tracé ne dépend d'aucune police.
   *  `createElementNS` est obligatoire — `createElement("svg")` fabrique un
   *  élément HTML inconnu, qui ne dessine rien. */
  function iconeCopie() {
    const NS = "http://www.w3.org/2000/svg";
    const svg = document.createElementNS(NS, "svg");
    svg.setAttribute("viewBox", "0 0 24 24");
    svg.setAttribute("width", "13");
    svg.setAttribute("height", "13");
    svg.setAttribute("fill", "none");
    svg.setAttribute("stroke", "currentColor");
    svg.setAttribute("stroke-width", "2");
    svg.setAttribute("stroke-linecap", "round");
    svg.setAttribute("stroke-linejoin", "round");
    svg.setAttribute("aria-hidden", "true");
    [
      "M9 9h10v12H9z",                       // la feuille de devant
      "M15 5H5v12h2",                        // celle de derrière
    ].forEach(function (d) {
      const p = document.createElementNS(NS, "path");
      p.setAttribute("d", d);
      svg.appendChild(p);
    });
    return svg;
  }

  function notifier(msg, type) {
    if (typeof window.toast === "function") window.toast(msg, type || "success");
  }

  function libelle(cle) {
    const l = etat.libelles[cle];
    return (l && l.nom) || cle;
  }

  function description(cle) {
    const l = etat.libelles[cle];
    return (l && l.description) || "";
  }

  /** L'adresse à coller dans OBS. Le domaine se DÉDUIT de la page courante :
   *  écrit en dur, il aurait renvoyé sur heywally.fr un dashboard ouvert par
   *  son IP locale — donc une source OBS pointée hors du réseau. */
  function urlScene(slug) {
    return window.location.origin + "/overlay-" + slug;
  }

  /** Copie, y compris hors contexte sécurisé. `navigator.clipboard` est
   *  INDÉFINI en http sur une IP locale : y appeler `.writeText` lève une
   *  TypeError synchrone qu'aucun `.catch()` n'attrape — d'où le test avant. */
  function copier(texte) {
    if (navigator.clipboard && window.isSecureContext) {
      navigator.clipboard.writeText(texte)
        .then(function () { notifier("Adresse copiée"); })
        .catch(function () { copierAncienneMethode(texte); });
      return;
    }
    copierAncienneMethode(texte);
  }

  function copierAncienneMethode(texte) {
    const zone = document.createElement("textarea");
    zone.value = texte;
    zone.setAttribute("readonly", "");
    zone.style.position = "fixed";
    zone.style.opacity = "0";
    document.body.appendChild(zone);
    zone.select();
    let ok = false;
    try { ok = document.execCommand("copy"); } catch (e) { ok = false; }
    document.body.removeChild(zone);
    notifier(ok ? "Adresse copiée" : "Copie refusée — sélectionnez l'adresse à la main",
             ok ? "success" : "error");
  }

  // ── L'infobulle ─────────────────────────────────────────────────────────

  /** Une vraie bulle, pas l'attribut `title` : celui-ci met deux secondes à
   *  venir et s'affiche en noir sur blanc système, illisible sur ce fond.
   *
   *  Posée sur `<body>` en `position: fixed` : la liste des éléments est en
   *  `overflow-y: auto`, une bulle placée dedans y serait rognée. */
  function poserInfobulle(hote, texte) {
    if (!texte) return;
    hote.addEventListener("mouseenter", function () { montrerInfobulle(hote, texte); });
    hote.addEventListener("mouseleave", masquerInfobulle);
  }

  function montrerInfobulle(hote, texte) {
    if (!infobulle) {
      infobulle = creer("div", "ovl-infobulle");
      infobulle.setAttribute("role", "tooltip");
      document.body.appendChild(infobulle);
      // En CAPTURE : `scroll` ne remonte pas, et il y a trois conteneurs qui
      // défilent ici (la page, la liste des éléments, la colonne). Un seul
      // écouteur les couvre tous. Sinon la bulle, posée en `fixed`, reste
      // accrochée là où elle est née pendant que sa cible s'en va.
      document.addEventListener("scroll", masquerInfobulle, true);
    }
    infobulle.textContent = texte;
    infobulle.classList.add("visible");
    // Mesurée APRÈS avoir reçu son texte, sinon la bulle se place sur la
    // largeur de la précédente et déborde de l'écran une fois sur deux.
    const cible = hote.getBoundingClientRect();
    const bulle = infobulle.getBoundingClientRect();
    let gauche = cible.right + 10;
    if (gauche + bulle.width > window.innerWidth - 8) {
      gauche = Math.max(8, cible.left - bulle.width - 10);
    }
    let haut = cible.top + cible.height / 2 - bulle.height / 2;
    haut = Math.max(8, Math.min(haut, window.innerHeight - bulle.height - 8));
    infobulle.style.left = gauche + "px";
    infobulle.style.top = haut + "px";
  }

  function masquerInfobulle() {
    if (infobulle) infobulle.classList.remove("visible");
  }

  function sceneCourante() {
    if (!etat.layout) return null;
    const scenes = etat.layout.scenes || [];
    for (let i = 0; i < scenes.length; i++) {
      if (scenes[i].slug === etat.slugCourant) return scenes[i];
    }
    return scenes[0] || null;
  }

  function borner(valeur, mini, maxi, defaut) {
    const n = Number(valeur);
    if (!isFinite(n)) return defaut;
    return Math.max(mini, Math.min(maxi, n));
  }

  /** Le slug d'URL d'un nom, miroir de `slug_depuis_nom()` (Python).
   *
   *  Le Python ne garantit PAS l'unicité contre les scènes existantes : deux
   *  scènes du même slug, et le serveur n'en garde qu'une (`fusionner()` jette
   *  les doublons). L'unicité se joue donc ici, avant l'envoi.
   */
  function slugDepuisNom(nom) {
    let s = String(nom || "");
    if (typeof s.normalize === "function") s = s.normalize("NFKD");
    s = s.replace(/[\u0300-\u036f]/g, "")  // les diacritiques décomposés
         .toLowerCase()
         .replace(/[^a-z0-9]+/g, "-")
         .replace(/^-+|-+$/g, "");
    if (!s) s = "scene";
    if (SLUGS_RESERVES.indexOf(s) >= 0) s = s + "-2";
    return s;
  }

  function slugUnique(base) {
    const pris = {};
    (etat.layout.scenes || []).forEach(function (s) { pris[s.slug] = true; });
    if (!pris[base]) return base;
    let n = 2;
    while (pris[base + "-" + n]) n += 1;
    return base + "-" + n;
  }

  // ── Réseau ──────────────────────────────────────────────────────────────

  /** L'appel admin d'`app.js` : c'est lui qui pose le Bearer et gère le 401.
   *  Refaire un `fetch` nu ici enverrait la requête sans jeton. */
  function appeler(url, options) {
    if (typeof window.apiFetch !== "function") {
      return Promise.reject(new Error("apiFetch absent"));
    }
    return window.apiFetch(url, options);
  }

  function charger() {
    return appeler(URL_LAYOUT)
      .then(function (r) { return r && r.ok ? r.json() : null; })
      .then(function (layout) {
        if (!layout || !layout.scenes || !layout.scenes.length) {
          echouer("Mise en scène illisible");
          return;
        }
        // Les libellés sortent du modèle avant tout le reste : `publier()`
        // renvoie `etat.layout` tel quel au serveur, et le PUT ne les rend pas.
        // Les laisser dedans les ferait donc disparaître à la première
        // publication — tous les noms redeviendraient des clés techniques.
        if (layout.libelles) {
          etat.libelles = layout.libelles;
          delete layout.libelles;
        }
        adopter(layout);
      })
      .catch(function (e) {
        echouer("Mise en scène : " + (e && e.message ? e.message : "erreur"));
      });
  }

  /** Prend un layout du serveur pour vérité et redessine tout. */
  function adopter(layout) {
    etat.layout = layout;
    etat.brouillon = 0;
    etat.publie = JSON.stringify(layout);
    // Plus rien en attente : un brouillon qui survivrait ici serait proposé au
    // prochain chargement alors qu'il est déjà à l'antenne.
    oublierBrouillon();
    const scenes = layout.scenes || [];
    const existe = scenes.some(function (s) { return s.slug === etat.slugCourant; });
    if (!existe) etat.slugCourant = layout.defaut || scenes[0].slug;
    retenirScene(etat.slugCourant);
    const scene = sceneCourante();
    const ordre = (scene && scene.ordre) || [];
    if (!scene || !scene.elements[etat.elementCourant]) {
      etat.elementCourant = ordre[0] || null;
    }
    rendreTout();
  }

  function echouer(message) {
    if (noeuds.cadre) noeuds.cadre.innerHTML = "";
    if (noeuds.listeScenes) {
      noeuds.listeScenes.innerHTML = "";
      noeuds.listeScenes.appendChild(creer("li", "ovl-vide", message));
    }
    notifier(message, "error");
  }

  /** Le modèle servi a-t-il bougé depuis notre dernier aller-retour ?
   *
   *  Deux onglets du panneau renvoient chacun le MODÈLE ENTIER tel qu'il l'a
   *  chargé : le second efface le travail du premier sans que rien ne le dise.
   *  Le serveur ne porte pas de numéro de révision — on relit donc juste avant
   *  d'écrire. Une lecture qui échoue NE BLOQUE PAS la publication : on est en
   *  direct, et un réseau capricieux ne doit pas coincer le streamer. */
  function verifierConcurrence() {
    if (!etat.publie) return Promise.resolve(true);
    return appeler(URL_LAYOUT)
      .then(function (r) { return r && r.ok ? r.json() : null; })
      .then(function (servi) {
        if (!servi || !servi.scenes) return true;
        // Les libellés ne voyagent qu'au GET : les laisser rendrait toute
        // comparaison fausse.
        delete servi.libelles;
        if (JSON.stringify(servi) === etat.publie) return true;
        return window.confirm(
          "La mise en scène à l'antenne a changé depuis votre chargement — "
          + "un autre onglet du panneau, sans doute.\n\nPublier maintenant "
          + "écrasera ces changements.\n\nContinuer ?");
      })
      .catch(function () { return true; });
  }

  /** Envoie un modèle. Le serveur renvoie ce qu'il a RANGÉ — on adopte sa
   *  réponse, pas ce qu'on lui a envoyé : les valeurs bornées apparaissent donc
   *  immédiatement à l'écran.
   *
   *  `message` remplace l'annonce générique : une opération de scène dit ce
   *  qu'elle a fait, et elle ne le dit qu'une fois le serveur d'accord. Un
   *  échec laisse le compteur en attente — la modification n'est pas perdue,
   *  « Mettre à jour » la renverra. */
  function publierModele(modele, message) {
    if (!modele) return Promise.resolve();
    // Une publication demandée à la main solde le fil de l'eau en attente :
    // sinon le minuteur repartirait derrière pour renvoyer la même chose.
    annulerPublicationDifferee();
    return verifierConcurrence().then(function (feuVert) {
      if (!feuVert) return undefined;
      // Ce qui est à l'antenne AVANT cet envoi : le cran d'annulation.
      const avant = etat.publie;
      return appeler(URL_LAYOUT, {
        method: "PUT",
        body: JSON.stringify(modele),
      })
        .then(function (r) {
          if (!r || !r.ok) throw new Error("le serveur a refusé");
          return r.json();
        })
        .then(function (layout) {
          // Un envoi qui ne change rien à l'écran ne doit pas consommer le
          // cran : on garderait un « annuler » qui ne fait rien.
          if (avant && avant !== JSON.stringify(layout)) etat.precedent = avant;
          if (manip) {
            // Un glisser a COMMENCÉ pendant l'aller-retour. `adopter()`
            // remplacerait `etat.layout` par la réponse du serveur, et
            // `manip.element` désignerait alors un objet détaché : le
            // mouvement en cours partirait dans le vide et sauterait en
            // arrière au relâchement. On note ce qui est parti, on laisse le
            // modèle sous les doigts — le geste comptera dans le brouillon
            // suivant, et ses valeurs bornées reviendront à la publication
            // d'après.
            etat.publie = JSON.stringify(layout);
            rendreBarrePublication();
            notifier(message || "Mise en scène publiée");
            return;
          }
          adopter(layout);
          notifier(message || "Mise en scène publiée");
        })
        .catch(function (e) {
          notifier("Publication impossible : " + (e && e.message ? e.message : "erreur"),
                   "error");
        });
    });
  }

  function publier(message) {
    return publierModele(etat.layout, message);
  }

  /** Le filet : republier ce qui était à l'antenne avant la dernière
   *  publication. UN SEUL cran — c'est de quoi ne pas rester coincé en plein
   *  live, pas un historique. Comme `publierModele()` garde à son tour l'état
   *  qu'on vient de remplacer, un second clic refait le chemin inverse. */
  function annulerPublication() {
    if (!etat.precedent) return Promise.resolve();
    let modele = null;
    try {
      modele = JSON.parse(etat.precedent);
    } catch (e) {
      etat.precedent = null;
      rendreBarrePublication();
      return Promise.resolve();
    }
    const perte = etat.brouillon > 0
      ? "\n\nATTENTION : vos " + etat.brouillon
        + " modification(s) en attente seront perdues."
      : "";
    if (!window.confirm(
        "Republier la mise en scène d'avant la dernière publication ?" + perte)) {
      return Promise.resolve();
    }
    return publierModele(modele, "Publication précédente rétablie.");
  }

  /** Jette le brouillon et reprend ce qui est réellement à l'antenne. */
  function abandonner() {
    if (etat.brouillon > 0 &&
        !window.confirm(etat.brouillon + " modification(s) seront perdues. Continuer ?")) {
      return Promise.resolve();
    }
    annulerPublicationDifferee();
    oublierBrouillon();
    return charger();
  }

  // ── Le fil de l'eau ─────────────────────────────────────────────────────

  // Le repos au bout duquel une modification part, case cochée. Un glisser ne
  // compte qu'une fois (`finirManip`), mais une frappe dans un champ ou une
  // flèche maintenue en produit une par événement : sans ce délai, un PUT par
  // caractère tapé.
  const DIRECT_DELAI_MS = 250;
  let directMinuteur = null;

  function annulerPublicationDifferee() {
    if (directMinuteur) {
      clearTimeout(directMinuteur);
      directMinuteur = null;
    }
  }

  function programmerPublicationDirecte() {
    annulerPublicationDifferee();
    directMinuteur = setTimeout(function () {
      directMinuteur = null;
      // Rien PENDANT le geste : `adopter()` remplace `etat.layout`, et
      // `manip.element` pointerait alors sur un objet détaché — le glisser en
      // cours se poursuivrait dans le vide. On attend le relâchement.
      if (manip) { programmerPublicationDirecte(); return; }
      if (etat.brouillon > 0) publier();
    }, DIRECT_DELAI_MS);
  }

  /** À appeler après CHAQUE mutation locale du modèle. */
  function marquerModifie() {
    etat.brouillon += 1;
    rangerBrouillon();
    rendreBarrePublication();
    if (etat.direct) programmerPublicationDirecte();
  }

  /** Le feu vert avant une opération de STRUCTURE (renommer, dupliquer,
   *  supprimer, définir par défaut). Ces quatre-là partent tout de suite, à la
   *  différence d'un placement : leur résultat est une ADRESSE qu'on colle dans
   *  OBS, et une adresse qui n'existe qu'en brouillon est un mensonge — elle
   *  disparaît au premier F5, ce qu'on découvrait sans le moindre message.
   *
   *  Mais `publier()` envoie le MODÈLE ENTIER : un placement en attente
   *  partirait à l'antenne avec l'opération. On le dit AVANT plutôt que de le
   *  laisser découvrir en plein live. Sans brouillon — le cas courant —, aucune
   *  question n'est posée.
   */
  function accordPourPublier() {
    if (etat.brouillon === 0) return true;
    return window.confirm(
      etat.brouillon + " modification(s) de placement non publiée(s) partiront "
      + "AUSSI à l'antenne avec cette opération.\n\nContinuer ?");
  }

  // ── La liste des scènes ─────────────────────────────────────────────────

  function rendreScenes() {
    const liste = noeuds.listeScenes;
    if (!liste || !etat.layout) return;
    fermerMenu();
    // Même raison que dans `rendreElements()` : le nœud survolé disparaît, son
    // `mouseleave` ne partira jamais.
    masquerInfobulle();
    liste.innerHTML = "";
    (etat.layout.scenes || []).forEach(function (scene) {
      const item = creer("li", "ovl-scene");
      if (scene.slug === etat.slugCourant) item.classList.add("actif");
      const corps = creer("div", "ovl-scene-corps");
      corps.appendChild(creer("span", "ovl-scene-nom", scene.nom));
      if (scene.slug === etat.layout.defaut) {
        corps.appendChild(creer("span", "ovl-badge", "défaut"));
      }
      item.appendChild(corps);
      const adresse = urlScene(scene.slug);

      const copie = creer("button", "ovl-copie");
      copie.appendChild(iconeCopie());
      copie.setAttribute("aria-label", "Copier l'adresse de « " + scene.nom + " »");
      copie.addEventListener("click", function (evt) {
        evt.stopPropagation();
        copier(adresse);
      });
      poserInfobulle(copie, "Copier " + adresse + " — l'adresse à coller dans "
        + "une source navigateur OBS.");
      item.appendChild(copie);

      const bouton = creer("button", "ovl-menu-btn", "⋮");
      bouton.title = "Renommer, dupliquer, supprimer…";
      bouton.addEventListener("click", function (evt) {
        evt.stopPropagation();
        if (menuOuvert && menuOuvert.parentNode === item) { fermerMenu(); return; }
        ouvrirMenu(item, scene);
      });
      item.appendChild(bouton);

      // L'adresse ENTIÈRE, pas le seul chemin : c'est elle qu'on colle dans
      // OBS, et la déduire de tête est exactement ce qu'on reprochait. Sur sa
      // propre ligne, sous les boutons : la colonne fait 280 px et une adresse
      // en fait 250, chaque pixel volé au bouton se paie en caractères perdus.
      const url = creer("span", "ovl-scene-url", adresse);
      poserInfobulle(url, adresse);
      item.appendChild(url);

      corps.addEventListener("click", function () { choisirScene(scene.slug); });
      liste.appendChild(item);
    });
  }

  function choisirScene(slug) {
    if (etat.slugCourant === slug) return;
    etat.slugCourant = slug;
    retenirScene(slug);
    const scene = sceneCourante();
    if (scene && !scene.elements[etat.elementCourant]) {
      etat.elementCourant = (scene.ordre || [])[0] || null;
    }
    rendreTout();
  }

  function fermerMenu() {
    if (menuOuvert && menuOuvert.parentNode) menuOuvert.parentNode.removeChild(menuOuvert);
    menuOuvert = null;
    document.removeEventListener("pointerdown", fermerAuClicDehors, true);
  }

  function fermerAuClicDehors(evt) {
    if (menuOuvert && menuOuvert.contains(evt.target)) return;
    fermerMenu();
  }

  function actionMenu(menu, texte, actif, action) {
    const b = creer("button", "ovl-menu-item", texte);
    if (!actif) b.classList.add("inactif");
    b.addEventListener("click", function (evt) {
      evt.stopPropagation();
      fermerMenu();
      action();
    });
    menu.appendChild(b);
    return b;
  }

  function ouvrirMenu(item, scene) {
    fermerMenu();
    const menu = creer("div", "ovl-menu");
    const seule = (etat.layout.scenes || []).length <= 1;

    actionMenu(menu, "Renommer", true, function () { renommer(scene); });
    actionMenu(menu, "Dupliquer", true, function () { dupliquer(scene); });
    actionMenu(menu, "Supprimer", !seule, function () {
      if (seule) {
        notifier("Il faut au moins une scène : celle-ci ne peut pas partir.", "error");
        return;
      }
      supprimer(scene);
    });
    actionMenu(menu, "Définir par défaut", scene.slug !== etat.layout.defaut, function () {
      definirDefaut(scene);
    });
    // L'avertissement vit dans l'interface, pas seulement dans le code : c'est
    // le streamer qui pointe ses sources OBS, et il découvrirait une URL morte
    // en plein direct, écran noir.
    menu.appendChild(creer("div", "ovl-menu-note",
      "Renommer ne touche jamais à l'adresse " + urlScene(scene.slug) + " : "
      + "la source OBS continue de fonctionner."));

    item.appendChild(menu);
    menuOuvert = menu;
    // En phase de capture, et posé au tour suivant : sinon le clic qui vient
    // d'ouvrir le menu le referme aussitôt.
    setTimeout(function () {
      document.addEventListener("pointerdown", fermerAuClicDehors, true);
    }, 0);
  }

  function renommer(scene) {
    if (!accordPourPublier()) return;
    const nom = window.prompt(
      "Nouveau nom de la scène.\n\nL'adresse ne change PAS :\n"
      + urlScene(scene.slug)
      + "\n\nC'est voulu — vos sources OBS restent valables.", scene.nom);
    if (nom === null) return;
    const propre = nom.trim();
    if (!propre) { notifier("Un nom vide n'a rien à afficher.", "error"); return; }
    scene.nom = propre;
    marquerModifie();
    rendreScenes();
    // Redit APRÈS coup : l'avertissement du `prompt` est lu en diagonale, et
    // l'adresse figée est précisément ce qui surprend. Annoncé par `publier()`,
    // donc seulement une fois le serveur d'accord : l'annoncer ici l'aurait dit
    // aussi quand l'enregistrement échoue.
    publier("Renommée « " + propre + " ». L'adresse reste " + urlScene(scene.slug) + ".");
  }

  function dupliquer(scene) {
    if (!accordPourPublier()) return;
    const nom = window.prompt("Nom de la copie :", scene.nom + " (copie)");
    if (nom === null) return;
    const propre = nom.trim();
    if (!propre) { notifier("Un nom vide n'a rien à afficher.", "error"); return; }
    const slug = slugUnique(slugDepuisNom(propre));
    // Copie PROFONDE des éléments : un dictionnaire partagé ferait bouger les
    // deux scènes ensemble au premier réglage, ce qui est exactement le
    // contraire de ce qu'on duplique.
    const elements = {};
    Object.keys(scene.elements || {}).forEach(function (cle) {
      elements[cle] = Object.assign({}, scene.elements[cle]);
    });
    const copie = {
      slug: slug,
      nom: propre,
      ordre: (scene.ordre || []).slice(),
      elements: elements,
    };
    const scenes = etat.layout.scenes;
    scenes.splice(scenes.indexOf(scene) + 1, 0, copie);
    etat.slugCourant = slug;
    marquerModifie();
    rendreTout();
    // L'adresse annoncée doit EXISTER : elle part dans OBS dans la minute qui
    // suit. Elle n'est donc dite qu'une fois la scène enregistrée.
    publier("Scène « " + propre + " » créée · " + urlScene(slug));
  }

  function supprimer(scene) {
    if (!accordPourPublier()) return;
    if (!window.confirm("Supprimer « " + scene.nom + " » ? "
        + "Une source OBS pointée sur " + urlScene(scene.slug)
        + " affichera alors la scène par défaut.")) return;
    const scenes = etat.layout.scenes;
    scenes.splice(scenes.indexOf(scene), 1);
    if (etat.layout.defaut === scene.slug) etat.layout.defaut = scenes[0].slug;
    if (etat.slugCourant === scene.slug) etat.slugCourant = scenes[0].slug;
    marquerModifie();
    rendreTout();
    publier("Scène « " + scene.nom + " » supprimée.");
  }

  function definirDefaut(scene) {
    if (!accordPourPublier()) return;
    etat.layout.defaut = scene.slug;
    marquerModifie();
    rendreScenes();
    publier("« " + scene.nom + " » est la scène par défaut.");
  }

  // ── Le survol, des deux côtés ───────────────────────────────────────────

  /** Le survol relie la LISTE et la SURFACE, dans les deux sens.
   *
   *  Trente-quatre éléments, dont vingt-six partent exactement au même endroit :
   *  une ligne de la liste ne disait pas LEQUEL des repères empilés elle
   *  désigne, et un repère ne disait pas quelle ligne aller cliquer. Le survol
   *  marque les deux à la fois — c'est le seul moyen de s'y retrouver.
   *
   *  Le nom, lui, reste au survol et sur l'élément choisi : posé en permanence,
   *  il recouvrait la page qu'on est venu regarder (`.ovl-rect-nom`).
   */
  function survoler(cle, defilerVersLaLigne) {
    survole = cle;
    appliquerSurvol();
    if (!cle || !defilerVersLaLigne || !noeuds.listeElements) return;
    const liste = noeuds.listeElements;
    const ligne = liste.querySelector('[data-cle="' + cle + '"]');
    if (!ligne) return;
    // La liste défile sur 420 px pour trente-quatre lignes : éclairer une ligne
    // hors de vue n'éclaire personne. Le calcul à la main plutôt que
    // `scrollIntoView` : celui-ci fait aussi défiler les conteneurs PARENTS, et
    // la page entière sauterait sous le pointeur au milieu d'un placement.
    // Et rien ne bouge tant que la ligne est visible.
    const r = ligne.getBoundingClientRect();
    const cadre = liste.getBoundingClientRect();
    if (r.top < cadre.top) liste.scrollTop -= cadre.top - r.top;
    else if (r.bottom > cadre.bottom) liste.scrollTop += r.bottom - cadre.bottom;
  }

  /** Repose la marque après coup. Les repères ET les lignes sont reconstruits à
   *  chaque rendu — au moindre appui sur une flèche, par exemple : sans ce
   *  rappel, la marque disparaîtrait sous un pointeur qui n'a pas bougé, et le
   *  `mouseleave` du nœud détruit ne viendrait jamais la retirer de l'autre
   *  côté. */
  function appliquerSurvol() {
    [noeuds.calque, noeuds.listeElements].forEach(function (hote) {
      if (!hote) return;
      hote.querySelectorAll(".survole").forEach(function (n) {
        n.classList.remove("survole");
      });
      if (!survole) return;
      const n = hote.querySelector('[data-cle="' + survole + '"]');
      if (n) n.classList.add("survole");
    });
  }

  // ── La liste des éléments ───────────────────────────────────────────────

  function rendreElements() {
    const liste = noeuds.listeElements;
    const scene = sceneCourante();
    if (!liste || !scene) return;
    // Le nœud survolé va disparaître : son `mouseleave` ne partira jamais, et
    // la bulle resterait plantée à l'écran.
    masquerInfobulle();
    liste.innerHTML = "";
    (scene.ordre || []).forEach(function (cle) {
      const element = scene.elements[cle];
      if (!element) return;   // une clé d'ordre sans élément : on l'ignore
      liste.appendChild(itemElement(cle, element));
    });
    if (noeuds.compteElements) {
      noeuds.compteElements.textContent = (scene.ordre || []).length + " éléments";
    }
    appliquerSurvol();
  }

  function itemElement(cle, element) {
    const item = creer("li", "ovl-el");
    item.dataset.cle = cle;
    item.draggable = true;
    if (cle === etat.elementCourant) item.classList.add("actif");
    if (element.hidden) item.classList.add("masque");
    if (element.locked) item.classList.add("verrouille");

    item.appendChild(creer("span", "ovl-el-poignee", "⠿"));
    const corps = creer("div", "ovl-el-corps");
    // Le nom lisible passe devant ; la clé technique reste sous les yeux, en
    // petit — c'est elle qui apparaît dans les logs et dans le JSON exporté.
    corps.appendChild(creer("span", "ovl-el-nom", libelle(cle)));
    corps.appendChild(creer("span", "ovl-el-cle", cle));
    item.appendChild(corps);
    poserInfobulle(corps, description(cle));

    const actions = creer("div", "ovl-el-actions");
    actions.appendChild(bouton(
      element.hidden ? "🚫" : "👁",
      element.hidden ? "Masqué dans cette scène — cliquer pour montrer"
                     : "Visible — cliquer pour masquer dans cette scène",
      element.hidden ? "actif" : "",
      function () { element.hidden = !element.hidden; apresBascule(cle); }));
    actions.appendChild(bouton(
      element.locked ? "🔒" : "🔓",
      element.locked ? "Verrouillé — il ne bougera pas au glisser"
                     : "Libre — cliquer pour le verrouiller",
      element.locked ? "actif" : "",
      function () { element.locked = !element.locked; apresBascule(cle); }));
    actions.appendChild(bouton("▶",
      "Afficher cet élément avec un contenu d'exemple, dans l'aperçu de CETTE "
      + "scène — jamais sur celle qui est à l'antenne.", "",
      function () { tester(cle); }));
    item.appendChild(actions);

    item.addEventListener("click", function (evt) {
      if (evt.target.closest && evt.target.closest(".ovl-el-actions")) return;
      selectionner(cle);
    });
    // `mouseenter`/`mouseleave` et non `mouseover` : ceux-là ne se déclenchent
    // pas en repassant d'un enfant à l'autre de la ligne.
    item.addEventListener("mouseenter", function () { survoler(cle, false); });
    item.addEventListener("mouseleave", function () { survoler(null, false); });
    brancherGlisser(item, cle);
    return item;
  }

  function bouton(texte, titre, cls, action) {
    const b = creer("button", "ovl-act" + (cls ? " " + cls : ""), texte);
    b.title = titre;
    b.addEventListener("click", function (evt) { evt.stopPropagation(); action(); });
    return b;
  }

  // ── Tester ──────────────────────────────────────────────────────────────

  /** Le ▶ d'une ligne : affiche l'élément POUR DE VRAI, avec un contenu
   *  d'exemple, sur la seule page de la scène en cours d'édition.
   *
   *  Le slug voyage dans le corps de la requête, et l'événement le porte
   *  jusqu'à la page : c'est lui qui garantit qu'un dé d'essai ne surgit pas
   *  en plein live pendant qu'on prépare la scène de fin. */
  function tester(cle) {
    const scene = sceneCourante();
    if (!scene) return;
    const element = scene.elements[cle];
    envoyerApercu({ scene: scene.slug, element: cle }, function (reponse) {
      // Le serveur a un mot à dire : c'est le cas de l'avatar, que ▶ ne
      // déclenche pas — il dégage la scène pour le rendre visible. Écrire le
      // message ici l'aurait éloigné du code qui décide.
      if (reponse && reponse.message) { notifier(reponse.message); return; }
      if (element && element.hidden) {
        // Publié quand même — mais la page le masque, et un aperçu qui ne
        // bouge pas passerait pour un bouton cassé.
        notifier(libelle(cle) + " est masqué dans cette scène : il ne "
          + "s'affichera pas tant qu'il l'est.", "error");
        return;
      }
      notifier(libelle(cle) + " affiché dans « " + scene.nom + " »"
        + mentionApercu(scene));
    });
  }

  /** Tous les éléments visibles d'un coup, pour juger de leur cohabitation. */
  function testerTous() {
    const scene = sceneCourante();
    if (!scene) return;
    envoyerApercu({ scene: scene.slug, tous: true }, function () {
      notifier("Repères posés sur « " + scene.nom
        + " » — ils s'effacent au bout de 30 s." + mentionApercu(scene));
    });
  }

  /** Le rappel qui compte quand l'aperçu manque : sans lui, on dit « affiché »
   *  à quelqu'un qui ne voit rien bouger.
   *
   *  La scène est passée en argument plutôt que relue : la réponse arrive après
   *  coup, et `sceneCourante()` peut avoir changé — ou rendre `null` si le
   *  modèle a été rechargé entre-temps, ce qui ferait échouer le message DE
   *  SUCCÈS et l'afficherait en « Test impossible ». */
  function mentionApercu(scene) {
    if (noeuds.cadre && noeuds.cadre.classList.contains("avec-apercu")) return "";
    return " · aperçu indisponible, ouvrez " + urlScene(scene.slug)
      + " à côté pour le voir.";
  }

  /** L'appel commun. Le CORPS de la réponse compte autant que son statut : un
   *  élément qui n'a pas de widget répond 200 en disant POURQUOI il ne
   *  s'applique pas — un bouton muet passerait pour une panne. */
  function envoyerApercu(corps, succes) {
    appeler(URL_APERCU, { method: "POST", body: JSON.stringify(corps) })
      .then(function (r) {
        if (!r) throw new Error("session expirée");
        // Le corps d'une erreur FastAPI porte `detail` : le lire donne au
        // streamer la raison du refus plutôt qu'un code.
        return r.json().then(
          function (d) { return { ok: r.ok, corps: d || {} }; },
          function () { return { ok: r.ok, corps: {} }; });
      })
      .then(function (res) {
        if (!res.ok) throw new Error(res.corps.detail || "le serveur a refusé");
        if (res.corps.affiche === false) {
          notifier(res.corps.raison || "Cet élément ne se déclenche pas.", "error");
          return;
        }
        succes(res.corps);
      })
      .catch(function (e) {
        notifier("Test impossible : " + (e && e.message ? e.message : "erreur"),
                 "error");
      });
  }

  function apresBascule(cle) {
    etat.elementCourant = cle;
    marquerModifie();
    rendreElements();
    rendreSurface();
    rendreReglages();
  }

  function selectionner(cle) {
    etat.elementCourant = cle;
    rendreElements();
    rendreSurface();
    rendreReglages();
  }

  /** Le réordonnancement à la souris. L'ordre de la LISTE est l'empilement :
   *  ce qui est en haut passe devant. */
  function brancherGlisser(item, cle) {
    item.addEventListener("dragstart", function (evt) {
      glisse = cle;
      item.classList.add("glisse");
      if (evt.dataTransfer) {
        evt.dataTransfer.effectAllowed = "move";
        // Firefox n'amorce pas le glisser sans donnée transportée.
        try { evt.dataTransfer.setData("text/plain", cle); } catch (e) { /* ignoré */ }
      }
    });
    item.addEventListener("dragend", function () {
      item.classList.remove("glisse");
      glisse = null;
      appliquerOrdreDepuisDom();
    });
    item.addEventListener("dragover", function (evt) {
      if (!glisse || glisse === cle) return;
      evt.preventDefault();
      const porte = noeuds.listeElements.querySelector('[data-cle="' + glisse + '"]');
      if (!porte) return;
      const r = item.getBoundingClientRect();
      const avant = evt.clientY < r.top + r.height / 2;
      noeuds.listeElements.insertBefore(porte, avant ? item : item.nextSibling);
    });
  }

  function appliquerOrdreDepuisDom() {
    const scene = sceneCourante();
    if (!scene || !noeuds.listeElements) return;
    const ordre = [];
    noeuds.listeElements.querySelectorAll("[data-cle]").forEach(function (n) {
      ordre.push(n.dataset.cle);
    });
    // Un élément absent de `ordre` ne serait pas seulement mal empilé : il ne
    // serait pas rendu du tout. On complète toujours — même garde que côté
    // Python.
    Object.keys(scene.elements || {}).forEach(function (cle) {
      if (ordre.indexOf(cle) < 0) ordre.push(cle);
    });
    const identique = ordre.length === (scene.ordre || []).length
      && ordre.every(function (c, i) { return scene.ordre[i] === c; });
    if (identique) return;
    scene.ordre = ordre;
    marquerModifie();
    rendreSurface();
  }

  // ── La géométrie : l'inverse exact de `styleDepuisElement` ──────────────

  /** L'ancrage d'un élément, tel que `WallyLayout` le définit.
   *
   *  Le repli reproduit `center`, exactement comme celui de `styleApercu()`
   *  quand le module de placement manque : les deux doivent raconter la même
   *  chose, sinon le rectangle affiché et le calcul du glisser divergeraient.
   */
  function ancrage(nom) {
    const W = window.WallyLayout;
    const table = (W && W.ANCRAGES) || null;
    return (table && (table[nom] || table["center"]))
      || { h: "left", v: "top", tx: "-50%", ty: "-50%" };
  }

  /** La géométrie RENDUE d'un élément sur la surface, en pixels de celle-ci.
   *
   *  C'est l'INVERSE EXACT de `WallyLayout.styleDepuisElement` ; les deux se
   *  lisent ensemble. Deux propriétés en sortent, et tout le glisser repose
   *  dessus :
   *
   *  1. Le point d'ancrage (`ax`, `ay`) est, pour les NEUF ancrages, à `x %` du
   *     bord GAUCHE et `y %` du bord HAUT. Un ancrage à droite pose
   *     `right: (100 − x) %` : son bord droit retombe donc à `x %` depuis la
   *     gauche. Le glisser est le même pour les neuf — on suit ce point.
   *  2. Ce point est AUSSI le point fixe de l'échelle : `transform-origin` est
   *     posé sur le bord mesuré, et le `translate` subit la même échelle que
   *     l'élément (`scale()` PUIS `translate()`). Redimensionner ne déplace
   *     donc jamais l'ancrage, et x/y restent valables pendant tout le geste.
   *
   *  Le `translate` se mesurant sur la taille NON transformée, le décalage vaut
   *  `échelle × taille / 2` et non `taille / 2`. C'est le défaut qui posait un
   *  élément centré et réduit à 39 % au lieu de 50 : le reproduire ici mettrait
   *  les poignées à côté de leur rectangle.
   */
  function geometrie(cle, element, W, H) {
    const a = ancrage(element.anchor);
    const t = tailleElement(cle);
    const e = borner(element.scale, ECHELLE_MIN, ECHELLE_MAX, 1) * (W / CANVAS_W);
    const largeur = t[0] * e;
    const hauteur = t[1] * e;
    const ax = borner(element.x, POS_MIN, POS_MAX, 50) / 100 * W;
    const ay = borner(element.y, POS_MIN, POS_MAX, 50) / 100 * H;
    const gauche = a.h === "right" ? ax - largeur
      : (a.tx === "-50%" ? ax - largeur / 2 : ax);
    const haut = a.v === "bottom" ? ay - hauteur
      : (a.ty === "-50%" ? ay - hauteur / 2 : ay);
    return {
      ax: ax, ay: ay, echelle: e, largeur: largeur, hauteur: hauteur,
      gauche: gauche, haut: haut, droite: gauche + largeur, bas: haut + hauteur,
    };
  }

  /** L'élément déborde-t-il de la source ? Un pixel de tolérance : un élément
   *  posé pile sur le bord ne doit pas clignoter au gré des arrondis. */
  function horsCadre(g, W, H) {
    return g.gauche < -1 || g.haut < -1 || g.droite > W + 1 || g.bas > H + 1;
  }

  /** Le pointeur en pourcentage de la surface, MOINS le décalage pris à la
   *  saisie — c'est lui qui garde sous le pointeur le point exact qu'on a
   *  attrapé, quel que soit l'ancrage. Sans lui, un élément ancré
   *  `bottom-right` saute de sa largeur entière au premier pixel.
   *
   *  Le rectangle attendu est celui du CALQUE, pas de la surface : celle-ci
   *  porte une bordure d'un pixel, et les repères se placent dans sa boîte de
   *  padding. Deux pixels d'erreur systématique, précisément ceux qu'on ne
   *  veut pas.
   */
  function positionDepuisPointeur(evt, r, decalage) {
    const d = decalage || { x: 0, y: 0 };
    return {
      x: borner(((evt.clientX - r.left) / r.width) * 100 - d.x, POS_MIN, POS_MAX, 0),
      y: borner(((evt.clientY - r.top) / r.height) * 100 - d.y, POS_MIN, POS_MAX, 0),
    };
  }

  /** L'aimantation d'UNE coordonnée : la grille de 10 %, plus les bords et le
   *  centre de l'écran — les positions qu'on vise vraiment.
   *
   *  Rend aussi la ligne à afficher : une valeur qui refuse d'avancer sans
   *  qu'on voie pourquoi passe pour un blocage.
   */
  function aimanter(valeur, tolerance, actif) {
    if (!actif) return { valeur: valeur, ligne: null };
    // Les bords et le centre EN PREMIER : à distance égale ils l'emportent sur
    // la graduation de la grille, la comparaison étant stricte.
    const cibles = [0, 50, 100];
    for (let g = 0; g <= 100; g += GRILLE) cibles.push(g);
    let cible = null;
    let ecart = tolerance;
    for (let i = 0; i < cibles.length; i++) {
      const d = Math.abs(valeur - cibles[i]);
      if (d < ecart) { ecart = d; cible = cibles[i]; }
    }
    return cible === null ? { valeur: valeur, ligne: null }
                          : { valeur: cible, ligne: cible };
  }

  /** Deux décimales. Au-delà on écrirait du bruit de virgule flottante dans un
   *  modèle qui part au serveur : 0,1 ajouté dix fois vaut 0,9999999999999999. */
  function arrondi(v) { return Math.round(v * 100) / 100; }

  /** Change l'ancrage SANS déplacer l'élément à l'écran.
   *
   *  L'ancrage dit quel POINT de l'élément la position repère : le changer en
   *  laissant x/y ferait sauter l'élément d'une demi-largeur, voire d'une
   *  largeur entière. On garde donc la boîte rendue et on relit dedans la
   *  position du NOUVEAU point d'ancrage. Sans ça, changer d'ancrage est un
   *  déplacement subi, et plus personne n'ose y toucher.
   *
   *  Reste un cas où l'élément bouge quand même : un point d'ancrage qui
   *  tomberait hors de 0–100 est ramené dans les bornes du modèle. Il n'y
   *  arrive que si l'élément débordait DÉJÀ du cadre, ce que le repère signale.
   */
  function reancrer(element, cle, nom, W, H) {
    const a = ancrage(nom);
    // Surface pas encore mesurée : il n'y a pas de position à conserver.
    if (!W || !H) { element.anchor = nom; return; }
    const g = geometrie(cle, element, W, H);
    const ax = a.h === "right" ? g.droite
      : (a.tx === "-50%" ? (g.gauche + g.droite) / 2 : g.gauche);
    const ay = a.v === "bottom" ? g.bas
      : (a.ty === "-50%" ? (g.haut + g.bas) / 2 : g.haut);
    element.anchor = nom;
    element.x = arrondi(borner(ax / W * 100, POS_MIN, POS_MAX, element.x));
    element.y = arrondi(borner(ay / H * 100, POS_MIN, POS_MAX, element.y));
  }

  // ── La surface de placement ─────────────────────────────────────────────

  /** La boîte du CALQUE — la référence commune du pointeur, des repères et des
   *  poignées. Prise sur le calque et pas sur la surface : lui seul couvre
   *  exactement la zone où les pourcentages s'appliquent. */
  function boiteCalque() {
    return noeuds.calque ? noeuds.calque.getBoundingClientRect() : null;
  }

  /** Le style d'un rectangle d'aperçu, dans le repère de la surface.
   *
   *  On réutilise `WallyLayout.styleDepuisElement` : c'est lui qui sait ce que
   *  chaque ancrage veut dire, et le recopier ici garantirait qu'un jour les
   *  deux divergent — l'aperçu mentirait alors sur le rendu réel. Une seule
   *  correction : son facteur de canvas se mesure sur la FENÊTRE (une source
   *  OBS occupe tout l'écran), alors qu'ici le canvas est la surface, large de
   *  quelques centaines de pixels. On lui passe donc une échelle pré-divisée
   *  par son propre facteur.
   */
  function styleApercu(element, largeurCadre) {
    const W = window.WallyLayout;
    const voulue = (element.scale || 1) * (largeurCadre / CANVAS_W);
    if (!W || typeof W.styleDepuisElement !== "function") {
      // Repli : la surface reste lisible même si le module de placement manque.
      // Une surface vide passerait pour une panne du serveur.
      return {
        left: element.x + "%", top: element.y + "%",
        transform: "translate(-50%, -50%) scale(" + voulue + ")",
        transformOrigin: "left top",
      };
    }
    const facteur = W.facteurCanvas() || 1;
    return W.styleDepuisElement(
      Object.assign({}, element, { scale: voulue / facteur }));
  }

  // ── L'aperçu : la vraie page, dans une iframe ───────────────────────────

  /** Charge la page de la scène dans l'aperçu — et seulement quand elle change.
   *
   *  La garde sur `apercuSlug` n'est pas un détail : `rendreSurface()` est
   *  rappelée à CHAQUE frappe dans les champs X/Y/Taille. Sans elle, l'iframe
   *  se rechargerait à chaque caractère et l'aperçu clignoterait sans jamais
   *  finir de charger.
   */
  function chargerApercu(slug) {
    if (!noeuds.apercu || !slug || apercuSlug === slug) return;
    apercuSlug = slug;
    noeuds.cadre.classList.remove("avec-apercu");
    montrerRetry(false);
    etatApercu("Aperçu : chargement de " + urlScene(slug) + "…");
    clearTimeout(apercuMinuteur);
    apercuMinuteur = setTimeout(echecApercu, APERCU_DELAI_MS);
    noeuds.apercu.src = urlScene(slug);
  }

  function apercuCharge() {
    // Même origine : on peut VÉRIFIER que c'est bien la page d'overlay. Une
    // page d'erreur du serveur déclenche `load` elle aussi — s'en contenter
    // afficherait « aperçu en direct » sur un 404.
    let ok = false;
    try {
      const doc = noeuds.apercu.contentDocument;
      ok = !!(doc && doc.body && doc.body.hasAttribute("data-scene-slug"));
    } catch (e) {
      ok = false;   // origine devenue étrangère : il n'y a rien à lire
    }
    if (!ok) { echecApercu(); return; }
    clearTimeout(apercuMinuteur);
    noeuds.cadre.classList.add("avec-apercu");
    montrerRetry(false);
    etatApercu("Aperçu de " + urlScene(apercuSlug)
      + " — la mise en scène PUBLIÉE, pas le brouillon en cours.");
    ajusterApercu();
  }

  function montrerRetry(visible) {
    if (noeuds.apercuRetry) noeuds.apercuRetry.style.display = visible ? "" : "none";
  }

  /** Le repli. On garde les rectangles nommés plutôt qu'une surface vide :
   *  un aperçu absent ne doit pas empêcher de placer. */
  function echecApercu() {
    clearTimeout(apercuMinuteur);
    if (!noeuds.cadre) return;
    noeuds.cadre.classList.remove("avec-apercu");
    montrerRetry(true);
    etatApercu("Aperçu indisponible — placement sur les rectangles nommés.");
  }

  function etatApercu(texte) {
    if (noeuds.apercuEtat) noeuds.apercuEtat.textContent = texte;
  }

  /** L'iframe fait 1920×1080 LOGIQUES, puis on la réduit par `scale()`.
   *
   *  Lui donner directement la taille de la surface serait le piège central :
   *  la page calcule son facteur de canvas sur `window.innerWidth`
   *  (`WallyLayout.facteurCanvas`), donc sur la largeur qu'on lui donne. Large
   *  de 600 px, elle rendrait tout au tiers de sa taille — dans un cadre déjà
   *  réduit. L'aperçu mentirait alors précisément sur ce qu'on vient y voir.
   */
  function ajusterApercu() {
    if (!noeuds.apercu || !noeuds.cadre) return;
    const largeur = noeuds.cadre.clientWidth || 0;
    if (!largeur) return;
    noeuds.apercu.style.transform = "scale(" + (largeur / CANVAS_W) + ")";
  }

  /** Pose sur un nœud le placement d'un élément. Les quatre bords sont remis à
   *  `auto` d'abord : le style ne pose que les deux du côté de l'ancrage, et
   *  l'ancien resterait accroché — l'élément tenu des deux côtés à la fois. */
  function appliquerStyle(noeud, element, largeur) {
    noeud.style.left = noeud.style.right = "auto";
    noeud.style.top = noeud.style.bottom = "auto";
    const style = styleApercu(element, largeur);
    Object.keys(style).forEach(function (k) { noeud.style[k] = style[k]; });
  }

  function rendreSurface() {
    const cadre = noeuds.calque;
    const scene = sceneCourante();
    if (!cadre || !scene) return;
    // Pendant un geste, on ne reconstruit RIEN : le repère manipulé serait
    // détruit sous le pointeur. Le geste met à jour le nœud lui-même
    // (`rafraichirManip`), et le rendu complet revient au relâchement.
    if (manip) return;
    masquerInfobulle();
    chargerApercu(scene.slug);
    cadre.innerHTML = "";
    const boite = boiteCalque();
    const largeur = boite ? boite.width : 0;
    const hauteur = boite ? boite.height : 0;
    const ordre = scene.ordre || Object.keys(scene.elements || {});
    ordre.forEach(function (cle, rang) {
      const element = scene.elements[cle];
      if (!element) return;
      const taille = tailleElement(cle);
      const rect = creer("div", "ovl-rect");
      rect.dataset.cle = cle;
      rect.style.width = taille[0] + "px";
      rect.style.height = taille[1] + "px";
      appliquerStyle(rect, element, largeur);
      const choisi = cle === etat.elementCourant;
      // L'ordre de la liste EST l'empilement : le premier passe devant.
      //
      // À une exception près, et elle est décisive : LE REPÈRE CHOISI PASSE
      // AU-DESSUS DE TOUS LES AUTRES. Vingt-six éléments partent au centre,
      // exactement superposés ; sans ça, choisir un élément dans la liste ne
      // servait à rien — c'est le repère du dessus qui recevait le pointeur, et
      // on déplaçait toujours le même. La sélection ne change PAS `scene.ordre`
      // (l'empilement réel de la page), seulement ce que la surface d'édition
      // laisse attraper.
      rect.style.zIndex = String(choisi ? ordre.length + 1 : ordre.length - rang);
      if (element.hidden) rect.classList.add("masque");
      if (element.locked) rect.classList.add("verrouille");
      if (choisi) rect.classList.add("actif");
      // Un élément qui sort du cadre se voit ICI, pas quand les viewers le
      // découvrent : le repère passe en orange et l'infobulle le dit.
      const deborde = largeur > 0
        && horsCadre(geometrie(cle, element, largeur, hauteur), largeur, hauteur);
      if (deborde) rect.classList.add("hors-cadre");
      rect.appendChild(creer("span", "ovl-rect-nom", libelle(cle)));
      poserInfobulle(rect, libelle(cle) + " · " + cle
        + (description(cle) ? " — " + description(cle) : "")
        + (deborde ? " — ⚠ déborde du cadre" : ""));
      rect.addEventListener("pointerdown", function (evt) { saisirRepere(evt, cle); });
      // Le sens retour : le repère éclaire sa ligne, et l'amène sous les yeux
      // si la liste a défilé ailleurs. Pas pendant un geste — la liste
      // sauterait sous le pointeur au milieu d'un déplacement.
      rect.addEventListener("mouseenter", function () {
        if (!manip) survoler(cle, true);
      });
      rect.addEventListener("mouseleave", function () {
        if (!manip) survoler(null, false);
      });
      cadre.appendChild(rect);
    });
    majPoignees(largeur, hauteur);
    appliquerSurvol();
  }

  // ── Le glisser, les poignées, le clavier ────────────────────────────────

  /** La saisie d'un repère. On sélectionne d'abord — ce qui REDESSINE la
   *  surface —, puis on repart du nœud neuf : celui qui a reçu l'événement
   *  vient d'être remplacé. */
  function saisirRepere(evt, cle) {
    if (manip || (evt.pointerType === "mouse" && evt.button !== 0)) return;
    const scene = sceneCourante();
    const element = scene && scene.elements[cle];
    if (!element) return;
    if (etat.elementCourant !== cle) selectionner(cle);
    // Le calque porte le focus clavier : il survit aux rendus, contrairement
    // aux repères, reconstruits à chaque changement.
    if (noeuds.calque.focus) noeuds.calque.focus({ preventScroll: true });
    if (element.locked) {
      notifier(libelle(cle) + " est verrouillé : le cadenas de la liste le libère.",
               "error");
      return;
    }
    const r = boiteCalque();
    if (!r || !r.width || !r.height) return;
    const p = positionDepuisPointeur(evt, r, null);
    manip = {
      mode: "position",
      cle: cle,
      element: element,
      noeud: noeuds.calque.querySelector('[data-cle="' + cle + '"]'),
      pointeur: evt.pointerId,
      // Le décalage entre le pointeur et le point d'ancrage, gardé tout le
      // geste : c'est LUI qui garde sous le doigt le point qu'on a attrapé.
      decalage: { x: p.x - borner(element.x, POS_MIN, POS_MAX, 50),
                  y: p.y - borner(element.y, POS_MIN, POS_MAX, 50) },
      depart: { x: element.x, y: element.y, scale: element.scale },
      lignes: null,
    };
    capturer(evt);
  }

  /** La saisie d'une poignée d'angle. Elle agit sur `scale` — le modèle ne
   *  connaît pas de largeur —, donc l'élément grandit depuis son ancrage. */
  function saisirPoignee(evt, coin) {
    if (manip || (evt.pointerType === "mouse" && evt.button !== 0)) return;
    const cle = etat.elementCourant;
    const element = elementCourant();
    if (!element || element.locked) return;
    const r = boiteCalque();
    if (!r || !r.width || !r.height) return;
    const g = geometrie(cle, element, r.width, r.height);
    const poignee = { x: coin.indexOf("w") >= 0 ? g.gauche : g.droite,
                      y: coin.charAt(0) === "n" ? g.haut : g.bas };
    const centre = { x: (g.gauche + g.droite) / 2, y: (g.haut + g.bas) / 2 };
    const rayon = Math.sqrt(Math.pow(poignee.x - centre.x, 2)
                          + Math.pow(poignee.y - centre.y, 2)) || 1;
    manip = {
      mode: "echelle",
      cle: cle,
      element: element,
      noeud: noeuds.calque.querySelector('[data-cle="' + cle + '"]'),
      pointeur: evt.pointerId,
      ancre: { x: g.ax, y: g.ay },
      // Le bras qui va de l'ancrage à la poignée : c'est ce vecteur que
      // l'échelle allonge, et sur lequel on projette le pointeur.
      bras: { x: poignee.x - g.ax, y: poignee.y - g.ay },
      // Le repli quand ce bras est nul : la direction qui s'éloigne du centre.
      sortant: { x: (poignee.x - centre.x) / rayon,
                 y: (poignee.y - centre.y) / rayon },
      rayon: rayon,
      origine: { x: evt.clientX, y: evt.clientY },
      depart: { x: element.x, y: element.y,
                scale: borner(element.scale, ECHELLE_MIN, ECHELLE_MAX, 1) },
      lignes: null,
    };
    capturer(evt);
  }

  function capturer(evt) {
    // La capture va sur le CALQUE, jamais sur le repère : celui-ci est
    // reconstruit à chaque rendu, et une capture posée sur un nœud sorti du
    // document est perdue en silence. `pointermove` sur `document` aurait le
    // défaut inverse — le pointeur sort du cadre pendant un geste rapide et
    // l'on perd la fin du mouvement, le repère restant collé.
    try {
      noeuds.calque.setPointerCapture(evt.pointerId);
    } catch (e) {
      // Capture refusée (pointeur déjà relâché) : les écouteurs du calque
      // suffisent tant que le pointeur reste dessus.
    }
    noeuds.cadre.classList.add("en-manip");
    evt.preventDefault();
    evt.stopPropagation();
  }

  function bougerManip(evt) {
    if (!manip || evt.pointerId !== manip.pointeur) return;
    const r = boiteCalque();
    if (!r || !r.width || !r.height) return;
    if (manip.mode === "position") {
      // Alt SUSPEND l'aimantation : on la veut par défaut, et relâchée sans
      // aller décocher une case ailleurs.
      const actif = !evt.altKey;
      const p = positionDepuisPointeur(evt, r, manip.decalage);
      const ax = aimanter(p.x, (AIMANT_PX / r.width) * 100, actif);
      const ay = aimanter(p.y, (AIMANT_PX / r.height) * 100, actif);
      manip.element.x = arrondi(ax.valeur);
      manip.element.y = arrondi(ay.valeur);
      manip.lignes = { x: ax.ligne, y: ay.ligne };
    } else {
      manip.element.scale = arrondi(echelleDepuisPointeur(evt, r));
    }
    rafraichirManip();
  }

  /** L'échelle que demande le pointeur, bornée à la saisie. */
  function echelleDepuisPointeur(evt, r) {
    const d = { x: evt.clientX - r.left - manip.ancre.x,
                y: evt.clientY - r.top - manip.ancre.y };
    const n2 = manip.bras.x * manip.bras.x + manip.bras.y * manip.bras.y;
    let e;
    if (n2 > 1) {
      // La poignée suit le pointeur d'aussi près qu'elle le peut : projection
      // du pointeur sur le bras. Exacte quand le pointeur reste sur la
      // diagonale — une poignée ne peut pas suivre un mouvement qui la quitte.
      e = manip.depart.scale * (d.x * manip.bras.x + d.y * manip.bras.y) / n2;
    } else {
      // Bras nul : la poignée est POSÉE sur le point d'ancrage — le coin
      // nord-ouest d'un élément ancré `top-left`, et ses trois symétriques.
      // Elle ne bouge pas d'un pixel quelle que soit l'échelle, il n'y a donc
      // rien à suivre. On lit alors l'éloignement du centre : s'en écarter
      // agrandit, s'en rapprocher réduit.
      const dep = { x: evt.clientX - manip.origine.x,
                    y: evt.clientY - manip.origine.y };
      e = manip.depart.scale
        * (1 + (dep.x * manip.sortant.x + dep.y * manip.sortant.y) / manip.rayon);
    }
    return borner(e, ECHELLE_MIN, ECHELLE_MAX, manip.depart.scale);
  }

  function finirManip(evt) {
    if (!manip || (evt && evt.pointerId !== manip.pointeur)) return;
    const fini = manip;
    manip = null;
    try {
      if (noeuds.calque.hasPointerCapture
          && noeuds.calque.hasPointerCapture(fini.pointeur)) {
        noeuds.calque.releasePointerCapture(fini.pointeur);
      }
    } catch (e) {
      // Capture déjà rendue par le navigateur : il n'y a rien à défaire.
    }
    noeuds.cadre.classList.remove("en-manip");
    montrerGuides(null);
    montrerCoords(null);
    // UNE modification pour tout le geste : en compter une par `pointermove`
    // afficherait « 340 modifications non publiées » pour un déplacement.
    if (fini.element.x !== fini.depart.x || fini.element.y !== fini.depart.y
        || fini.element.scale !== fini.depart.scale) {
      marquerModifie();
    }
    rendreSurface();
    rendreReglages();
  }

  /** Les flèches, sur le calque : de quoi ajuster au pixel sans se battre avec
   *  la souris. Le pas fin vaut deux pixels sur une source 1920. */
  function toucheSurface(evt) {
    const sens = TOUCHES[evt.key];
    if (!sens || manip) return;
    const element = elementCourant();
    if (!element) return;
    evt.preventDefault();   // sinon la page défile sous la surface
    if (element.locked) {
      // Au premier appui seulement : la répétition du clavier en ferait une
      // pluie de messages.
      if (!evt.repeat) {
        notifier(libelle(etat.elementCourant)
          + " est verrouillé : le cadenas de la liste le libère.", "error");
      }
      return;
    }
    const pas = evt.shiftKey ? PAS_GROS : PAS_FIN;
    element.x = arrondi(borner(element.x + sens[0] * pas, POS_MIN, POS_MAX, element.x));
    element.y = arrondi(borner(element.y + sens[1] * pas, POS_MIN, POS_MAX, element.y));
    marquerModifie();
    rendreSurface();
    rendreReglages();
  }

  /** Le retour visuel pendant le geste : le repère lui-même, ses poignées, les
   *  lignes d'aimantation et les coordonnées en cours. */
  function rafraichirManip() {
    if (!manip) return;
    const r = boiteCalque();
    if (!r || !r.width || !r.height) return;
    const g = geometrie(manip.cle, manip.element, r.width, r.height);
    if (manip.noeud) {
      appliquerStyle(manip.noeud, manip.element, r.width);
      manip.noeud.classList.toggle("hors-cadre", horsCadre(g, r.width, r.height));
    }
    placerPoignees(g);
    montrerGuides(manip.lignes);
    montrerCoords(g, r.width, r.height);
    rendreReglages();   // les champs X/Y/Taille suivent le geste
  }

  function majPoignees(W, H) {
    const element = elementCourant();
    // Un élément verrouillé n'a ni poignées ni glisser : il ne doit pas être
    // manipulable par mégarde, c'est tout l'objet du cadenas.
    if (!element || element.locked || !W || !H) { placerPoignees(null); return; }
    placerPoignees(geometrie(etat.elementCourant, element, W, H));
  }

  /** Les quatre poignées d'angle, posées sur la SURFACE et non dans le repère :
   *  celui-ci porte un `scale()`, qui rendrait les poignées minuscules sur un
   *  élément réduit — justement celui qu'on veut agrandir. */
  function placerPoignees(g) {
    if (!noeuds.poignees) return;
    COINS.forEach(function (coin) {
      const n = noeuds.poignees[coin];
      if (!g) { n.style.display = "none"; return; }
      n.style.display = "";
      n.style.left = (coin.indexOf("w") >= 0 ? g.gauche : g.droite) + "px";
      n.style.top = (coin.charAt(0) === "n" ? g.haut : g.bas) + "px";
    });
  }

  function montrerGuides(lignes) {
    if (!noeuds.guideV || !noeuds.guideH) return;
    const x = lignes ? lignes.x : null;
    const y = lignes ? lignes.y : null;
    noeuds.guideV.style.display = x === null || x === undefined ? "none" : "";
    if (x !== null && x !== undefined) noeuds.guideV.style.left = x + "%";
    noeuds.guideH.style.display = y === null || y === undefined ? "none" : "";
    if (y !== null && y !== undefined) noeuds.guideH.style.top = y + "%";
  }

  /** Les coordonnées en cours. Sans elles, on déplace à l'estime et on
   *  découvre le chiffre après coup. */
  function montrerCoords(g, W, H) {
    if (!noeuds.coords) return;
    if (!g || !manip) { noeuds.coords.classList.remove("visible"); return; }
    const el = manip.element;
    const deborde = horsCadre(g, W, H);
    noeuds.coords.textContent =
      "X " + arrondi(el.x).toFixed(2) + " %  ·  Y " + arrondi(el.y).toFixed(2) + " %"
      + "  ·  taille " + arrondi(borner(el.scale, ECHELLE_MIN, ECHELLE_MAX, 1)).toFixed(2)
      + (deborde ? "  ·  ⚠ déborde du cadre" : "");
    noeuds.coords.classList.toggle("alerte", deborde);
    noeuds.coords.classList.add("visible");
  }

  // ── La barre de réglages ────────────────────────────────────────────────

  function construireReglages(hote) {
    const titre = creer("div", "ovl-reglages-nom", "—");
    noeuds.reglageNom = titre;
    hote.appendChild(titre);

    noeuds.champs = {};
    [["x", "X %", POS_MIN, POS_MAX, PAS_FIN], ["y", "Y %", POS_MIN, POS_MAX, PAS_FIN],
     ["scale", "Taille", ECHELLE_MIN, ECHELLE_MAX, 0.05]].forEach(function (def) {
      const bloc = creer("label", "ovl-champ");
      bloc.appendChild(creer("span", "ovl-champ-label", def[1]));
      const input = document.createElement("input");
      input.type = "number";
      input.min = String(def[2]);
      input.max = String(def[3]);
      input.step = String(def[4]);
      input.addEventListener("input", function () {
        const element = elementCourant();
        if (!element) return;
        // Un champ vidé pour être resaisi ne vaut PAS zéro : sans ça,
        // l'élément filait dans le coin haut-gauche entre deux frappes.
        if (input.value.trim() === "") return;
        element[def[0]] = borner(input.value, def[2], def[3], element[def[0]]);
        marquerModifie();
        rendreSurface();
      });
      bloc.appendChild(input);
      noeuds.champs[def[0]] = input;
      hote.appendChild(bloc);
    });

    // Une question DISTINCTE de « l'élément occupe-t-il seul la scène » : on
    // peut vouloir un meme qui chasse les autres widgets mais garde Wally à
    // côté, pour qu'il le commente. Une case par élément, comme le reste de
    // cette barre : elle porte le réglage de l'élément choisi.
    const bascule = creer("label", "ovl-bascule");
    bascule.title = "Décoché, cet élément efface l'avatar et la bulle le temps "
      + "de son affichage. Coché, Wally reste à l'écran à côté de lui.";
    const coche = document.createElement("input");
    coche.type = "checkbox";
    coche.addEventListener("change", function () {
      const element = elementCourant();
      if (!element) return;
      element.wally_visible = coche.checked;
      marquerModifie();
    });
    bascule.appendChild(coche);
    bascule.appendChild(creer("span", "ovl-bascule-label", "Wally reste visible"));
    noeuds.wallyVisible = coche;
    hote.appendChild(bascule);

    const grille = creer("div", "ovl-ancrages");
    grille.title = "Le point de l'élément que la position repère. En changer ne "
      + "déplace pas l'élément : x et y sont recalculés pour qu'il reste où il est.";
    noeuds.ancrages = {};
    ANCRAGES.forEach(function (a) {
      const b = creer("button", "ovl-ancrage");
      b.dataset.ancrage = a;
      b.title = a;
      b.addEventListener("click", function () {
        const element = elementCourant();
        if (!element || element.anchor === a) return;
        const r = boiteCalque();
        reancrer(element, etat.elementCourant, a,
                 r ? r.width : 0, r ? r.height : 0);
        marquerModifie();
        rendreReglages();
        rendreSurface();
      });
      noeuds.ancrages[a] = b;
      grille.appendChild(b);
    });
    hote.appendChild(grille);
  }

  function elementCourant() {
    const scene = sceneCourante();
    if (!scene || !etat.elementCourant) return null;
    return scene.elements[etat.elementCourant] || null;
  }

  /** Ce que l'overlay fait AUJOURD'HUI de cet élément — même repli que
   *  `masqueWally()` dans `overlay.js`. Un modèle rangé avant l'ajout du champ
   *  ne le porte pas : c'était alors `solo` qui décidait de l'effacement, et la
   *  case doit montrer le comportement réel, pas un défaut inventé. */
  function gardeWally(element) {
    if (element.wally_visible === undefined || element.wally_visible === null) {
      return element.solo === false;
    }
    return !!element.wally_visible;
  }

  function rendreReglages() {
    if (!noeuds.champs) return;
    const element = elementCourant();
    noeuds.reglageNom.textContent = element
      ? libelle(etat.elementCourant) + " · " + etat.elementCourant
      : "Aucun élément choisi";
    ["x", "y", "scale"].forEach(function (cle) {
      const input = noeuds.champs[cle];
      input.disabled = !element;
      // On n'écrase pas un champ en cours de saisie : la valeur sauterait sous
      // les doigts à chaque frappe.
      if (element && document.activeElement !== input) {
        input.value = String(Math.round(element[cle] * 100) / 100);
      } else if (!element) {
        input.value = "";
      }
    });
    if (noeuds.wallyVisible) {
      noeuds.wallyVisible.disabled = !element;
      noeuds.wallyVisible.checked = !!element && gardeWally(element);
    }
    ANCRAGES.forEach(function (a) {
      noeuds.ancrages[a].classList.toggle("actif", !!element && element.anchor === a);
    });
  }

  // ── La barre de publication ─────────────────────────────────────────────

  function rendreBarrePublication() {
    if (!noeuds.compteur) return;
    const n = etat.brouillon;
    noeuds.compteur.textContent = n
      ? n + " modification" + (n > 1 ? "s" : "") + " non publiée" + (n > 1 ? "s" : "")
      : (etat.direct ? "Publication immédiate" : "Rien en attente");
    noeuds.compteur.classList.toggle("en-attente", n > 0);
    noeuds.publier.disabled = n === 0;
    noeuds.abandonner.disabled = n === 0;
    if (noeuds.annuler) noeuds.annuler.disabled = !etat.precedent;
  }

  // ── Le brouillon retrouvé au chargement ─────────────────────────────────

  /** Proposé, JAMAIS appliqué d'office : on doit savoir qu'on reprend un
   *  travail en cours, et pouvoir le jeter. Appliqué en silence, un brouillon
   *  d'avant-hier partirait à l'antenne au premier « Mettre à jour » sans que
   *  personne ait vu ce qu'il contenait. */
  function proposerBrouillon(d) {
    if (!d || !etat.layout || !noeuds.proposition) return;
    const n = d.n;
    // `base` est ce qui était à l'antenne quand le brouillon a été écrit : s'il
    // a bougé depuis, le reprendre écrasera le travail de l'autre onglet.
    const perime = d.base && etat.publie && d.base !== etat.publie;
    noeuds.propositionTexte.textContent =
      "Brouillon retrouvé : " + n + " modification" + (n > 1 ? "s" : "")
      + " non publiée" + (n > 1 ? "s" : "") + ", " + depuis(d.quand) + "."
      + (perime ? " ⚠ La mise en scène à l'antenne a changé depuis." : "");
    noeuds.proposition.style.display = "";
    noeuds.propositionReprendre.onclick = function () { reprendreBrouillon(d); };
    noeuds.propositionJeter.onclick = function () {
      oublierBrouillon();
      noeuds.proposition.style.display = "none";
      notifier("Brouillon jeté.");
    };
  }

  /** Même résolution que `adopter()` : la scène demandée si elle existe encore,
   *  la scène par défaut sinon. Sans ça, un brouillon dont la scène a été
   *  supprimée entre-temps laisserait la liste sans ligne active. */
  function reprendreBrouillon(d) {
    etat.layout = d.layout;
    etat.brouillon = d.n;
    const scenes = etat.layout.scenes || [];
    const voulu = d.scene || etat.slugCourant;
    const existe = scenes.some(function (s) { return s.slug === voulu; });
    etat.slugCourant = existe
      ? voulu
      : (etat.layout.defaut || (scenes[0] || {}).slug || null);
    const scene = sceneCourante();
    if (!scene || !scene.elements[etat.elementCourant]) {
      etat.elementCourant = (scene && scene.ordre && scene.ordre[0]) || null;
    }
    retenirScene(etat.slugCourant);
    noeuds.proposition.style.display = "none";
    rendreTout();
    notifier("Brouillon repris — rien n'est parti à l'antenne.");
  }

  function rendreTout() {
    rendreScenes();
    rendreElements();
    rendreSurface();
    rendreReglages();
    rendreBarrePublication();
  }

  // ── Le squelette ────────────────────────────────────────────────────────

  /** La barre sous la surface : l'état de l'aperçu, « Tout afficher », et la
   *  bascule qui estompe les repères pour laisser voir la page dessous. */
  function barreApercu() {
    const barre = creer("div", "ovl-apercu-barre");
    noeuds.apercuEtat = creer("span", "ovl-apercu-etat", "Aperçu : en attente…");
    barre.appendChild(noeuds.apercuEtat);

    // Sans lui, une seule coupure réseau laisse le repli en place jusqu'au
    // prochain changement de scène — et il n'y a pas toujours de seconde scène
    // vers laquelle aller et revenir. Un bouton explicite plutôt qu'un
    // rechargement automatique : `rendreSurface()` est rappelée à chaque
    // frappe, une relance par frappe serait un pilonnage.
    noeuds.apercuRetry = creer("button", "btn btn-sm", "Réessayer");
    noeuds.apercuRetry.style.display = "none";
    noeuds.apercuRetry.addEventListener("click", function () {
      const slug = apercuSlug;
      apercuSlug = null;
      chargerApercu(slug);
    });
    barre.appendChild(noeuds.apercuRetry);

    const tous = creer("button", "btn btn-sm", "Tout afficher");
    tous.title = "Pose un repère nommé à la place de chaque élément visible, "
      + "dans l'aperçu de CETTE scène seulement. Ils s'effacent au bout de 30 s.";
    tous.addEventListener("click", function () { testerTous(); });
    barre.appendChild(tous);

    const estomper = creer("label", "ovl-estomper");
    const caseEstomper = document.createElement("input");
    caseEstomper.type = "checkbox";
    caseEstomper.addEventListener("change", function () {
      noeuds.cadre.classList.toggle("reperes-estompes", caseEstomper.checked);
    });
    estomper.appendChild(caseEstomper);
    estomper.appendChild(creer("span", null, "Estomper les repères"));
    estomper.title = "Les rectangles de placement s'effacent pour laisser voir "
      + "l'aperçu. Celui qu'on règle, et celui qu'on survole, restent nets.";
    barre.appendChild(estomper);
    return barre;
  }

  function construireSquelette(conteneur) {
    conteneur.classList.add("ovl-panneau");
    conteneur.innerHTML = "";

    const entete = creer("div", "ovl-entete");
    entete.appendChild(creer("div", "card-title", "MISE EN SCÈNE"));
    entete.appendChild(creer("div", "ovl-entete-sub",
      "Où va chaque élément, scène par scène. Rien ne part à l'antenne avant "
      + "« Mettre à jour »."));
    conteneur.appendChild(entete);

    const corps = creer("div", "ovl-corps");

    // Colonne de gauche : les scènes, puis les éléments.
    const colonne = creer("div", "ovl-colonne");

    const blocScenes = creer("div", "ovl-bloc ovl-bloc-scenes");
    const titreScenes = creer("div", "ovl-bloc-titre");
    titreScenes.appendChild(creer("span", null, "Scènes"));
    blocScenes.appendChild(titreScenes);
    noeuds.listeScenes = creer("ul", "ovl-scenes");
    blocScenes.appendChild(noeuds.listeScenes);
    colonne.appendChild(blocScenes);

    const blocElements = creer("div", "ovl-bloc ovl-bloc-elements");
    const titreElements = creer("div", "ovl-bloc-titre");
    titreElements.appendChild(creer("span", null, "Éléments"));
    noeuds.compteElements = creer("span", "ovl-bloc-compte", "");
    titreElements.appendChild(noeuds.compteElements);
    blocElements.appendChild(titreElements);
    noeuds.listeElements = creer("ul", "ovl-elements");
    blocElements.appendChild(noeuds.listeElements);
    blocElements.appendChild(creer("div", "ovl-aide",
      "Glisser pour réordonner : ce qui est en haut passe devant."));
    colonne.appendChild(blocElements);

    corps.appendChild(colonne);

    // À droite : la surface, ses réglages, puis la publication.
    const droite = creer("div", "ovl-droite");
    noeuds.cadre = creer("div", "ovl-surface");
    // L'aperçu d'abord, le calque par-dessus : c'est l'ordre du DOM qui décide
    // lequel capte le pointeur, et le glisser (lot suivant) vivra sur le calque.
    noeuds.apercu = document.createElement("iframe");
    noeuds.apercu.className = "ovl-apercu";
    noeuds.apercu.title = "Aperçu de la scène en cours d'édition";
    noeuds.apercu.setAttribute("scrolling", "no");
    noeuds.apercu.addEventListener("load", apercuCharge);
    noeuds.apercu.addEventListener("error", echecApercu);
    noeuds.cadre.appendChild(noeuds.apercu);
    noeuds.calque = creer("div", "ovl-calque");
    // Le calque porte le focus clavier, et non les repères : ceux-ci sont
    // reconstruits à chaque rendu, et le focus serait perdu à la première
    // flèche. Il porte aussi les écouteurs du geste, parce que c'est LUI qui
    // reçoit la capture du pointeur.
    noeuds.calque.tabIndex = 0;
    noeuds.calque.setAttribute("aria-label",
      "Surface de placement — flèches pour déplacer l'élément choisi, "
      + "Maj pour un pas de 1 %, Alt pour suspendre l'aimantation");
    noeuds.calque.addEventListener("pointermove", bougerManip);
    noeuds.calque.addEventListener("pointerup", finirManip);
    noeuds.calque.addEventListener("pointercancel", finirManip);
    // Le filet : une capture perdue sans `pointerup` — relâchement hors de la
    // fenêtre du navigateur, onglet qui passe en arrière-plan — laisserait
    // `manip` posé, et la surface cesserait de se redessiner. Un panneau figé
    // sans le moindre message. `finirManip` ayant déjà vidé `manip` avant de
    // rendre la capture, la voie normale n'y repasse pas deux fois.
    noeuds.calque.addEventListener("lostpointercapture", finirManip);
    noeuds.calque.addEventListener("keydown", toucheSurface);
    noeuds.cadre.appendChild(noeuds.calque);

    // Poignées, lignes d'aimantation et coordonnées vivent HORS du calque :
    // celui-ci est vidé à chaque rendu, et elles doivent survivre au geste.
    noeuds.poignees = {};
    COINS.forEach(function (coin) {
      const p = creer("div", "ovl-poignee ovl-poignee-" + coin);
      p.style.display = "none";
      p.title = "Redimensionner — le point d'ancrage ne bouge pas";
      p.addEventListener("pointerdown", function (evt) { saisirPoignee(evt, coin); });
      noeuds.poignees[coin] = p;
      noeuds.cadre.appendChild(p);
    });
    noeuds.guideV = creer("div", "ovl-guide vertical");
    noeuds.guideH = creer("div", "ovl-guide horizontal");
    noeuds.guideV.style.display = "none";
    noeuds.guideH.style.display = "none";
    noeuds.cadre.appendChild(noeuds.guideV);
    noeuds.cadre.appendChild(noeuds.guideH);
    noeuds.coords = creer("div", "ovl-coords");
    noeuds.cadre.appendChild(noeuds.coords);

    droite.appendChild(noeuds.cadre);

    droite.appendChild(barreApercu());

    const reglages = creer("div", "ovl-reglages");
    construireReglages(reglages);
    droite.appendChild(reglages);
    // Les raccourcis sont écrits : Alt et Maj ne se devinent pas, et personne
    // ne cherche une poignée qu'il ne sait pas là.
    droite.appendChild(creer("div", "ovl-aide",
      "Glisser un repère pour le déplacer · les poignées d'angle changent sa "
      + "taille · Alt suspend l'aimantation · flèches : 0,1 % (Maj : 1 %)."));

    // La proposition de reprise, au-dessus de la barre : elle ne s'affiche
    // qu'au chargement, et seulement s'il reste un brouillon.
    noeuds.proposition = creer("div", "ovl-brouillon");
    noeuds.proposition.style.display = "none";
    noeuds.propositionTexte = creer("span", "ovl-brouillon-texte", "");
    noeuds.proposition.appendChild(noeuds.propositionTexte);
    noeuds.propositionReprendre = creer("button", "btn btn-sm", "Reprendre");
    noeuds.propositionReprendre.title =
      "Remet vos modifications en attente. Rien ne part à l'antenne.";
    noeuds.proposition.appendChild(noeuds.propositionReprendre);
    noeuds.propositionJeter = creer("button", "btn btn-sm", "Jeter");
    noeuds.propositionJeter.title = "Oublie le brouillon et garde ce qui est à l'antenne.";
    noeuds.proposition.appendChild(noeuds.propositionJeter);
    droite.appendChild(noeuds.proposition);

    const publication = creer("div", "ovl-publication");
    const direct = creer("label", "ovl-direct");
    const caseDirect = document.createElement("input");
    caseDirect.type = "checkbox";
    caseDirect.checked = false;   // le cas dangereux ne s'obtient pas sans rien faire
    caseDirect.addEventListener("change", function () {
      // Cocher alors que des modifications attendent les envoie : `publier()`
      // pousse le MODÈLE ENTIER, la prochaine retouche les emporterait de toute
      // façon. On le dit avant, plutôt que de le laisser découvrir à l'antenne.
      if (caseDirect.checked && etat.brouillon > 0
          && !window.confirm(
            etat.brouillon + " modification(s) attendent.\n\nPublier au fil de "
            + "l'eau les enverra à l'antenne MAINTENANT.\n\nContinuer ?")) {
        caseDirect.checked = false;
        return;
      }
      etat.direct = caseDirect.checked;
      if (etat.direct && etat.brouillon > 0) publier();
      rendreBarrePublication();
    });
    direct.appendChild(caseDirect);
    // Nommée « Publier au fil de l'eau » et non « Aperçu en direct » : depuis
    // que la surface montre la vraie page, « aperçu » désigne CE cadre. Deux
    // sens pour un mot, dans le même panneau, sur un réglage qui touche
    // l'antenne — c'est la confusion qu'on ne peut pas se permettre ici.
    direct.appendChild(creer("span", null, "Publier au fil de l'eau"));
    direct.title = "Décoché : l'overlay à l'antenne ne bouge pas tant qu'on "
      + "n'a pas cliqué « Mettre à jour ». Coché : chaque déplacement part au "
      + "relâchement — rien pendant le geste.";
    publication.appendChild(direct);
    noeuds.compteur = creer("span", "ovl-compteur", "Rien en attente");
    publication.appendChild(noeuds.compteur);
    noeuds.publier = creer("button", "btn btn-success", "Mettre à jour");
    noeuds.publier.addEventListener("click", function () { publier(); });
    publication.appendChild(noeuds.publier);
    noeuds.abandonner = creer("button", "btn", "Abandonner");
    noeuds.abandonner.title = "Jette le brouillon et recharge ce qui est "
      + "réellement à l'antenne.";
    noeuds.abandonner.addEventListener("click", function () { abandonner(); });
    publication.appendChild(noeuds.abandonner);
    noeuds.annuler = creer("button", "btn", "Annuler la publication");
    noeuds.annuler.title = "Republie la mise en scène d'avant la dernière "
      + "publication. Un seul cran — de quoi ne pas rester coincé en direct.";
    noeuds.annuler.disabled = true;
    noeuds.annuler.addEventListener("click", function () { annulerPublication(); });
    publication.appendChild(noeuds.annuler);
    droite.appendChild(publication);

    corps.appendChild(droite);
    conteneur.appendChild(corps);

    // La taille des rectangles ET la réduction de l'aperçu dépendent de la
    // largeur de la surface : sans ça, replier la barre latérale les laisserait
    // à l'échelle d'avant.
    if (window.ResizeObserver) {
      if (observateur) observateur.disconnect();
      observateur = new ResizeObserver(function () {
        ajusterApercu();
        rendreSurface();
      });
      observateur.observe(noeuds.cadre);
    }
    // Posée tout de suite : la surface a déjà sa largeur, et attendre le
    // premier `load` de l'iframe l'afficherait une frame en taille réelle.
    ajusterApercu();
  }

  // ── Montage ─────────────────────────────────────────────────────────────

  /** Construit le panneau dans `conteneur`. Synchrone et sans exception : une
   *  erreur ici casserait toutes les sections montées après nous. */
  function monter(conteneur) {
    if (!conteneur) return;
    // La garde AVANT tout `await` — ici, avant toute promesse : évaluée après,
    // deux montages concurrents passeraient tous les deux et le panneau
    // s'afficherait en double. C'est arrivé sur ce dashboard.
    if (conteneur.dataset.overlayAdmin === "1") return;
    conteneur.dataset.overlayAdmin = "1";
    // LU AVANT `charger()` : `adopter()` oublie le brouillon rangé — c'est ce
    // qu'on lui demande une fois la publication faite —, et le lire après
    // n'aurait plus rien trouvé.
    let enAttente = null;
    try {
      construireSquelette(conteneur);
      // Le filet du brouillon. Un placement non publié ne survit pas à un F5 —
      // et rien ne le disait : on refermait l'onglet en croyant avoir posé
      // l'élément. Le navigateur n'affiche que son message générique, mais il
      // affiche quelque chose, et c'est tout ce qu'on lui demande.
      window.addEventListener("beforeunload", function (evt) {
        if (etat.brouillon === 0) return;
        evt.preventDefault();
        evt.returnValue = "";   // exigé par les navigateurs historiques
      });
      // La scène qu'on éditait avant le rechargement. Posée AVANT `charger()` :
      // `adopter()` la garde si elle existe encore, et retombe sur la scène par
      // défaut sinon.
      etat.slugCourant = sceneRetenue();
      enAttente = lireBrouillon();
    } catch (e) {
      conteneur.textContent = "Mise en scène indisponible.";
      return;
    }
    // Le brouillon est PROPOSÉ, pas appliqué : on doit savoir qu'on reprend un
    // travail en cours. Après `charger()`, donc sur le modèle réellement à
    // l'antenne — c'est lui qui dit si le brouillon a pris du retard.
    charger().then(function () { proposerBrouillon(enAttente); });
  }

  return {
    monter: monter,
    etat: etat,
    marquerModifie: marquerModifie,
    publier: publier,
    abandonner: abandonner,
    annulerPublication: annulerPublication,
    charger: charger,
    rendreTout: rendreTout,
    rendreSurface: rendreSurface,
    rendreReglages: rendreReglages,
    selectionner: selectionner,
    sceneCourante: sceneCourante,
    elementCourant: elementCourant,
    slugDepuisNom: slugDepuisNom,
    urlScene: urlScene,
    libelle: libelle,
    description: description,
    tester: tester,
    testerTous: testerTous,
    ANCRAGES: ANCRAGES,
    // Le rangement du brouillon, exposé pour la même raison : il ne touche que
    // `localStorage`, et c'est lui qui décide si un travail non publié survit à
    // un F5 — ou s'il repart à l'antenne tout seul, ce qu'on ne veut jamais.
    rangerBrouillon: rangerBrouillon,
    lireBrouillon: lireBrouillon,
    oublierBrouillon: oublierBrouillon,
    // La géométrie du glisser, exposée pour être TESTÉE hors navigateur : ces
    // quatre fonctions sont pures, et ce sont elles qui décident si le point
    // saisi reste sous le pointeur.
    geometrie: geometrie,
    horsCadre: horsCadre,
    positionDepuisPointeur: positionDepuisPointeur,
    aimanter: aimanter,
    reancrer: reancrer,
  };
})();
