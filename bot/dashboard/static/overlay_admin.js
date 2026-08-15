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
//      tourne sans que l'écran bouge d'un pixel. La case « aperçu en direct »,
//      la survie du brouillon et l'annulation viennent avec la tâche 8.
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

  /** L'état du panneau.
   *
   *  `brouillon` est un COMPTEUR : le nombre de modifications non publiées.
   *  Zéro vaut « rien en attente ». `direct` sera la case « aperçu en direct »
   *  (tâche 8) ; décoché par défaut, parce que le cas dangereux ne doit pas
   *  être celui qu'on obtient sans rien faire.
   */
  const etat = {
    layout: null,
    libelles: {},   // clé → {nom, description}, servi par le GET du layout
    slugCourant: null,
    elementCourant: null,
    brouillon: 0,
    direct: false,
  };

  const noeuds = {};      // les nœuds du squelette, posés une fois
  let menuOuvert = null;  // le menu ⋮ déployé, s'il y en a un
  let observateur = null; // ResizeObserver de la surface
  let glisse = null;      // la clé de l'élément en cours de glisser dans la liste
  let infobulle = null;   // l'unique bulle d'aide, posée sur <body>
  let apercuSlug = null;      // la scène actuellement chargée dans l'iframe
  let apercuMinuteur = null;  // le délai au bout duquel on bascule sur le repli

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
    const scenes = layout.scenes || [];
    const existe = scenes.some(function (s) { return s.slug === etat.slugCourant; });
    if (!existe) etat.slugCourant = layout.defaut || scenes[0].slug;
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

  /** Envoie tout le modèle. Le serveur renvoie ce qu'il a RANGÉ — on adopte sa
   *  réponse, pas ce qu'on lui a envoyé : les valeurs bornées apparaissent donc
   *  immédiatement à l'écran. */
  function publier() {
    if (!etat.layout) return Promise.resolve();
    return appeler(URL_LAYOUT, {
      method: "PUT",
      body: JSON.stringify(etat.layout),
    })
      .then(function (r) {
        if (!r || !r.ok) throw new Error("le serveur a refusé");
        return r.json();
      })
      .then(function (layout) {
        adopter(layout);
        notifier("Mise en scène publiée");
      })
      .catch(function (e) {
        notifier("Publication impossible : " + (e && e.message ? e.message : "erreur"), "error");
      });
  }

  /** Jette le brouillon et reprend ce qui est en base. */
  function abandonner() {
    if (etat.brouillon > 0 &&
        !window.confirm(etat.brouillon + " modification(s) seront perdues. Continuer ?")) {
      return Promise.resolve();
    }
    return charger();
  }

  /** À appeler après CHAQUE mutation locale du modèle. */
  function marquerModifie() {
    etat.brouillon += 1;
    rendreBarrePublication();
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
    // l'adresse figée est précisément ce qui surprend.
    notifier("Renommée « " + propre + " ». L'adresse reste " + urlScene(scene.slug) + ".");
  }

  function dupliquer(scene) {
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
    notifier("Scène « " + propre + " » créée · " + urlScene(slug));
  }

  function supprimer(scene) {
    if (!window.confirm("Supprimer « " + scene.nom + " » ? "
        + "Une source OBS pointée sur " + urlScene(scene.slug)
        + " affichera alors la scène par défaut.")) return;
    const scenes = etat.layout.scenes;
    scenes.splice(scenes.indexOf(scene), 1);
    if (etat.layout.defaut === scene.slug) etat.layout.defaut = scenes[0].slug;
    if (etat.slugCourant === scene.slug) etat.slugCourant = scenes[0].slug;
    marquerModifie();
    rendreTout();
  }

  function definirDefaut(scene) {
    etat.layout.defaut = scene.slug;
    marquerModifie();
    rendreScenes();
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
    envoyerApercu({ scene: scene.slug, element: cle }, function () {
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
        succes();
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

  // ── La surface de placement ─────────────────────────────────────────────

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

  function rendreSurface() {
    const cadre = noeuds.calque;
    const scene = sceneCourante();
    if (!cadre || !scene) return;
    masquerInfobulle();
    chargerApercu(scene.slug);
    cadre.innerHTML = "";
    const largeur = noeuds.cadre.clientWidth || 0;
    const ordre = scene.ordre || Object.keys(scene.elements || {});
    ordre.forEach(function (cle, rang) {
      const element = scene.elements[cle];
      if (!element) return;
      const taille = tailleElement(cle);
      const rect = creer("div", "ovl-rect");
      rect.dataset.cle = cle;
      rect.style.width = taille[0] + "px";
      rect.style.height = taille[1] + "px";
      const style = styleApercu(element, largeur);
      Object.keys(style).forEach(function (k) { rect.style[k] = style[k]; });
      // L'ordre de la liste EST l'empilement : le premier passe devant.
      rect.style.zIndex = String(ordre.length - rang);
      if (element.hidden) rect.classList.add("masque");
      if (element.locked) rect.classList.add("verrouille");
      if (cle === etat.elementCourant) rect.classList.add("actif");
      rect.appendChild(creer("span", "ovl-rect-nom", libelle(cle)));
      poserInfobulle(rect, libelle(cle) + " · " + cle
        + (description(cle) ? " — " + description(cle) : ""));
      rect.addEventListener("click", function () { selectionner(cle); });
      cadre.appendChild(rect);
    });
  }

  // ── La barre de réglages ────────────────────────────────────────────────

  function construireReglages(hote) {
    const titre = creer("div", "ovl-reglages-nom", "—");
    noeuds.reglageNom = titre;
    hote.appendChild(titre);

    noeuds.champs = {};
    [["x", "X %", 0, 100, 0.1], ["y", "Y %", 0, 100, 0.1],
     ["scale", "Taille", 0.2, 2, 0.05]].forEach(function (def) {
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

    const grille = creer("div", "ovl-ancrages");
    grille.title = "Le point de l'élément que la position repère.";
    noeuds.ancrages = {};
    ANCRAGES.forEach(function (a) {
      const b = creer("button", "ovl-ancrage");
      b.dataset.ancrage = a;
      b.title = a;
      b.addEventListener("click", function () {
        const element = elementCourant();
        if (!element) return;
        element.anchor = a;
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
      : "Rien en attente";
    noeuds.compteur.classList.toggle("en-attente", n > 0);
    noeuds.publier.disabled = n === 0;
    noeuds.abandonner.disabled = n === 0;
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
    noeuds.cadre.appendChild(noeuds.calque);
    droite.appendChild(noeuds.cadre);

    droite.appendChild(barreApercu());

    const reglages = creer("div", "ovl-reglages");
    construireReglages(reglages);
    droite.appendChild(reglages);

    const publication = creer("div", "ovl-publication");
    const direct = creer("label", "ovl-direct");
    const caseDirect = document.createElement("input");
    caseDirect.type = "checkbox";
    caseDirect.disabled = true;
    caseDirect.title = "Bientôt : publier chaque déplacement au fil de l'eau.";
    direct.appendChild(caseDirect);
    // Nommée « Publier au fil de l'eau » et non « Aperçu en direct » : depuis
    // que la surface montre la vraie page, « aperçu » désigne CE cadre. Deux
    // sens pour un mot, dans le même panneau, sur un réglage qui touche
    // l'antenne — c'est la confusion qu'on ne peut pas se permettre ici.
    direct.appendChild(creer("span", null, "Publier au fil de l'eau"));
    direct.title = "Décoché : l'overlay à l'antenne ne bouge pas tant qu'on "
      + "n'a pas cliqué « Mettre à jour ».";
    publication.appendChild(direct);
    noeuds.compteur = creer("span", "ovl-compteur", "Rien en attente");
    publication.appendChild(noeuds.compteur);
    noeuds.publier = creer("button", "btn btn-success", "Mettre à jour");
    noeuds.publier.addEventListener("click", function () { publier(); });
    publication.appendChild(noeuds.publier);
    noeuds.abandonner = creer("button", "btn", "Abandonner");
    noeuds.abandonner.addEventListener("click", function () { abandonner(); });
    publication.appendChild(noeuds.abandonner);
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
    try {
      construireSquelette(conteneur);
    } catch (e) {
      conteneur.textContent = "Mise en scène indisponible.";
      return;
    }
    charger();
  }

  return {
    monter: monter,
    etat: etat,
    marquerModifie: marquerModifie,
    publier: publier,
    abandonner: abandonner,
    // Pour les tâches 7 (surface) et 8 (brouillon).
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
  };
})();
