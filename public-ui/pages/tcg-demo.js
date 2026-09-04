// public-ui/pages/tcg-demo.js — les données FIGÉES de la maquette
//
// 🚨 Ce fichier est le SEUL endroit du front où vivent des valeurs du TCG.
// Rien ici n'est calculé, et rien ne le sera : le moteur de règles vit côté
// serveur, en Python. Une règle dupliquée en JavaScript est une porte de
// triche ouverte et un second jeu à maintenir
// (`docs/superpowers/plans/2026-09-05-tcg-maquette-brief.md`).
//
// La maquette MONTRE des états, elle ne les produit pas. Un état est un objet
// écrit à la main ci-dessous ; passer d'un tour au suivant, c'est afficher
// l'objet suivant du tableau, jamais résoudre quoi que ce soit.
//
// ⚠️ Aucune valeur d'ici n'est la vérité du jeu. Les stats des six héros
// sortent de la procédure du 2026-09-04 (budget 12, rareté Âme) et seront
// recalculées ; les Ultimes, les tactiques et les factions sont des
// PLACEHOLDERS écrits pour avoir quelque chose de lisible à l'écran.

// Les valeurs de règle affichées par le plateau. Elles ne sont pas stables
// (spec §8 : le plafond d'énergie est le premier chiffre à calibrer), d'où
// leur place ici plutôt que dans le rendu.
export const REGLES = {
  energieMax: 12,
  energieParTour: 3,
};

// ── Les six héros ─────────────────────────────────────────────────────────
//
// ATK · PV · Aura calculés le 2026-09-04, budget 12, rareté Âme.
// Le coût de l'Ultime sort du style d'écriture (5 + quintile de la longueur
// médiane des messages → 6 à 10), jamais du mérite.
export const HEROS = {
  origanire: {
    nom: 'OriganireTV', atk: 6, pv: 3, aura: 3,
    rarete: 'ame', faction: 'sombre', affinites: ['Apex', 'Nuit'],
    trait: "l'éclair : il déboule fort et ne reste pas",
    ultime: {
      nom: 'Déboule', cout: 6,
      texte: "+2 d'Attaque ce tour. S'il Chute ce tour-ci, son coup part quand même.",
    },
  },
  kassandre: {
    nom: 'KassandreYunikon', atk: 5, pv: 4, aura: 3,
    rarete: 'ame', faction: 'lumineuse', affinites: ['Chat'],
    trait: 'la frappeuse',
    ultime: {
      nom: 'Frappe nette', cout: 7,
      texte: "+3 d'Attaque ce tour, et elle vise le héros adverse le plus faible "
        + 'au lieu de son vis-à-vis.',
    },
  },
  claker: {
    nom: 'ClakerNoJutsu', atk: 5, pv: 4, aura: 3,
    rarete: 'ame', faction: 'sombre', affinites: ['Apex', 'Stream'],
    trait: '',
    ultime: {
      nom: 'Second souffle', cout: 8,
      texte: "Il récupère 4 PV et gagne +2 d'Attaque jusqu'à la fin du tour suivant.",
    },
  },
  kingsrequin: {
    nom: 'KingsRequin', atk: 4, pv: 5, aura: 3,
    rarete: 'ame', faction: 'lumineuse', affinites: ['Code', 'Stream'],
    trait: "l'équilibré",
    ultime: {
      // Clin d'œil à I03 du catalogue des Réflexes. Le prix d'un hasard VISIBLE
      // se calcule au MEILLEUR cas, jamais à l'espérance (catalogue §2).
      nom: 'Ça compile ou ça casse', cout: 9,
      texte: "Tirage ≥ 5 : +5 d'Attaque à toute ta ligne. Tirage ≤ 2 : −2 à la sienne.",
    },
  },
  azrael: {
    nom: 'Azraël', atk: 3, pv: 6, aura: 3,
    rarete: 'ame', faction: null, affinites: ['Stream', 'Apex'],
    trait: 'le mur : toujours là',
    ultime: {
      nom: 'Le mur tient', cout: 7,
      texte: 'Tes héros en ligne subissent 3 dégâts de moins ce tour.',
    },
  },
  rhae: {
    nom: 'rhae___', atk: 2, pv: 5, aura: 5,
    rarete: 'ame', faction: 'lumineuse', affinites: ['Chat', 'Musique'],
    trait: 'parle peu, relie tout le monde',
    ultime: {
      // Aucun doublement sans plafond en valeur absolue (catalogue §1) : un
      // multiplicateur nu vaut +2 sur une petite carte et +9 sur une grosse.
      nom: 'Tout le monde se parle', cout: 10,
      texte: 'Son Aura est comptée deux fois ce tour, dans la limite de +5.',
    },
  },
  // Le boss du mode coopératif. Ses PV ne sont pas une stat de carte : ils
  // dérivent du nombre de joueurs (40 × N), sinon le raid est trivial à six et
  // impossible à deux.
  wally: {
    // `pv: null` et pas 0 : ses points de vie ne sont pas une stat de carte,
    // ils dérivent du nombre de joueurs. Afficher « ♥0 » sur sa fiche aurait
    // été faux, et faux d'une manière qui ressemble à une valeur calculée.
    nom: 'Wally', atk: 7, pv: null, pvLibelle: '40 × joueurs', aura: 0,
    rarete: 'archange', faction: 'sombre', affinites: ['Purgatoire'],
    trait: "il distribue, il arbitre, et il annonce qu'il triche",
    ultime: {
      nom: "Je t'avais dit que je trichais", cout: 0,
      texte: 'Une fois par partie, il révèle qu\'il lui restait des PV. '
        + "Annoncé dans les règles : c'est un bluff, jamais un mensonge du moteur.",
    },
  },
};

// ── Les tactiques ─────────────────────────────────────────────────────────
//
// Coût écrit à la main (1 à 5), contrairement aux héros. C'est la moitié du
// jeu qui change chaque saison — le contenu neuf ne coûte jamais rien à
// personne, puisqu'il ne touche pas aux cartes des gens.
export const TACTIQUES = {
  relance:  { nom: 'On reprend',           cout: 1, type: 'tactique', texte: 'Pioche une tactique.' },
  marquage: { nom: 'Marquage',             cout: 2, type: 'tactique', texte: "Désigne un héros adverse : toute ton Attaque le vise ce tour." },
  seance:   { nom: 'Séance de révision',   cout: 2, type: 'tactique', texte: "−2 d'Attaque à un héros adverse, et −1 à ton héros adjacent." },
  renfort:  { nom: 'Renfort',              cout: 2, type: 'tactique', texte: "+1 d'Attaque à un allié par autre allié en ligne (max +3)." },
  esquive:  { nom: 'Esquive',              cout: 3, type: 'tactique', texte: 'Tirage ≥ 3 : un héros allié ignore tous les dégâts ce tour.' },
  garde:    { nom: 'Garde rapprochée',     cout: 3, type: 'passif',   texte: 'Tant qu\'elle est en jeu, ton héros aux PV les plus bas prend 1 dégât de moins.' },
  ponction: { nom: 'Ponction',             cout: 4, type: 'tactique', texte: '−1 PV à tous les héros adverses en ligne.' },
  nuit:     { nom: 'Nuit sur le Purgatoire', cout: 5, type: 'tactique', texte: "Tous tes héros d'affinité Apex gagnent +2 d'Attaque ce tour." },
};

// ── Les états figés ───────────────────────────────────────────────────────
//
// Chaque entrée de `etats` est un instantané COMPLET du plateau, écrit à la
// main. Le rendu lit `pv`, `degats`, `tombe` — il ne les déduit jamais d'un
// état précédent, sinon la soustraction serait une règle de plus.
//
// Forme d'un camp :
//   { nom, boss?, groupes: [ { nom, energie, heros, main, reserve } ] }
//   · `heros`   : [{ id, pv, degats, ultime, tombe, nouveau }]
//   · `main`    : un tableau d'ids (révélée) OU un nombre (cartes face cachée)
//   · `reserve` : idem
//   · `boss`    : { id, pv, pvMax } — le mode coopératif seulement
//
// ⚠️ Les six héros servent aux deux camps : c'est un jeu de collection, deux
// personnes peuvent posséder la même carte. Une carte peut donc apparaître des
// deux côtés du plateau. Un vrai deck n'aura pas cette symétrie.

// ⚠️ Ce que la maquette a rendu visible dès la première écriture de ces états,
// et qui appartient à la conception des règles, pas à l'affichage :
//
//   L'Aura reçue rend le premier échange létal. Un héros frappe pour
//   `Attaque + Aura reçue` ; en 3 contre 3, chacun reçoit 6 d'Aura, donc frappe
//   pour 8 à 12 — face à des PV de 3 à 6. Au tour 1, les six héros Chutent.
//   En 1 contre 1 il n'y a aucun allié, donc aucune Aura : la stat ne sert à
//   rien et l'Attaque nue tue aussi en un coup.
//
// Les états 1v1 et 2v2 ci-dessous montrent ce résultat TEL QUEL. Ceux du 3v3
// sont volontairement ADOUCIS — sans quoi il n'y aurait que deux tours à
// regarder, et la maquette ne montrerait aucune disposition de fin de partie.

const T = REGLES.energieParTour;

/** Un héros en ligne, à ses PV pleins et sans rien de particulier. */
function neuf(id, extra) {
  return { id, pv: HEROS[id].pv, degats: 0, ultime: false, tombe: false, ...extra };
}

export const FORMATS = [
  {
    cle: '1v1',
    libelle: '1 v 1',
    resume: 'Un héros chacun. Aucun allié en ligne, donc aucune Aura : la stat ne joue pas.',
    etats: [
      {
        tour: 1, tirage: 4,
        note: 'Chacun gagne 3 d’énergie, puis pose à l’aveugle.',
        haut: { nom: 'Kass', groupes: [{ nom: null, energie: T, heros: [neuf('origanire')], main: 3, reserve: 1 }] },
        bas: { nom: 'Toi', groupes: [{ nom: null, energie: T, heros: [neuf('kingsrequin')], main: ['marquage', 'esquive', 'relance'], reserve: ['azrael'] }] },
        journal: ['Tour 1 — 3 d’énergie pour chacun.', 'Les deux camps posent en simultané, puis on révèle.'],
      },
      {
        tour: 2, tirage: 1,
        note: 'Le premier échange emporte les deux héros. Sans allié, l’Aura ne compense rien.',
        haut: { nom: 'Kass', groupes: [{ nom: null, energie: T, heros: [{ id: 'origanire', pv: 0, degats: 4, ultime: false, tombe: true }], main: 3, reserve: 1 }] },
        bas: { nom: 'Toi', groupes: [{ nom: null, energie: 1 + T, heros: [{ id: 'kingsrequin', pv: 0, degats: 6, ultime: false, tombe: true }], main: ['esquive', 'relance'], reserve: ['azrael'] }] },
        journal: [
          'OriganireTV frappe pour 6 · KingsRequin frappe pour 4.',
          'Les dégâts s’appliquent des DEUX côtés avant de retirer quoi que ce soit.',
          'Les deux héros Chutent. Les réserves entrent au tour suivant.',
        ],
      },
    ],
  },
  {
    cle: '2v2',
    libelle: '2 v 2',
    resume: 'Deux héros chacun. L’Aura commence à compter : chacun reçoit celle de son seul allié.',
    etats: [
      {
        tour: 1, tirage: 6,
        note: 'KingsRequin reçoit 5 d’Aura de rhae___ : il frappera pour 9, pas pour 4.',
        haut: { nom: 'Kass', groupes: [{ nom: null, energie: T, heros: [neuf('kassandre'), neuf('claker')], main: 3, reserve: 1 }] },
        bas: { nom: 'Toi', groupes: [{ nom: null, energie: T, heros: [neuf('kingsrequin'), neuf('rhae')], main: ['renfort', 'ponction', 'garde'], reserve: ['azrael'] }] },
        journal: ['Tour 1 — 3 d’énergie pour chacun.', 'Tirage du tour : 6. Un seul dé, public, avant la pose.'],
      },
      {
        tour: 2, tirage: 3,
        note: 'Quatre héros, quatre Chutes. C’est l’Aura reçue qui fait ces chiffres, pas l’Attaque.',
        haut: {
          nom: 'Kass',
          groupes: [{
            nom: null, energie: 1 + T, main: 3, reserve: 1,
            heros: [
              { id: 'kassandre', pv: 0, degats: 9, ultime: false, tombe: true },
              { id: 'claker', pv: 0, degats: 5, ultime: false, tombe: true },
            ],
          }],
        },
        bas: {
          nom: 'Toi',
          groupes: [{
            nom: null, energie: 1 + T, main: ['ponction', 'garde'], reserve: ['azrael'],
            heros: [
              { id: 'kingsrequin', pv: 0, degats: 8, ultime: false, tombe: true },
              { id: 'rhae', pv: 0, degats: 8, ultime: false, tombe: true },
            ],
          }],
        },
        journal: [
          'KingsRequin frappe pour 4 + 5 d’Aura = 9 · rhae___ pour 2 + 3 = 5.',
          'En face : 5 + 3 = 8, des deux côtés.',
          'Les quatre héros Chutent dans le même échange.',
        ],
      },
    ],
  },
  {
    cle: '3v3',
    libelle: '3 v 3',
    resume: 'Le format de référence des règles : 3 en ligne, 2 en réserve, victoire aux 5 Chutes.',
    etats: [
      {
        tour: 1, tirage: 3,
        note: 'Rien n’est encore résolu : les deux camps ont posé, on n’a pas révélé.',
        haut: { nom: 'Kass', groupes: [{ nom: null, energie: T, heros: [neuf('kassandre'), neuf('claker'), neuf('origanire')], main: 3, reserve: 2 }] },
        bas: { nom: 'Toi', groupes: [{ nom: null, energie: T, heros: [neuf('kingsrequin'), neuf('azrael'), neuf('rhae')], main: ['marquage', 'garde', 'esquive'], reserve: ['origanire', 'claker'] }] },
        journal: ['Tour 1 — 3 d’énergie pour chacun, plafond 12.', 'Tirage du tour : 3.'],
      },
      {
        tour: 2, tirage: 5,
        note: 'Marquage a concentré l’Attaque sur OriganireTV. Il Chute : sa carte quitte la ligne.',
        haut: {
          nom: 'Kass',
          groupes: [{
            nom: null, energie: T, main: 3, reserve: 2,
            heros: [
              { id: 'kassandre', pv: 1, degats: 3, ultime: false, tombe: false },
              { id: 'claker', pv: 2, degats: 2, ultime: false, tombe: false },
              { id: 'origanire', pv: 0, degats: 3, ultime: false, tombe: true },
            ],
          }],
        },
        bas: {
          nom: 'Toi',
          groupes: [{
            nom: null, energie: 1 + T, main: ['garde', 'esquive'], reserve: ['origanire', 'claker'],
            heros: [
              { id: 'kingsrequin', pv: 2, degats: 3, ultime: false, tombe: false },
              { id: 'azrael', pv: 3, degats: 3, ultime: false, tombe: false },
              { id: 'rhae', pv: 3, degats: 2, ultime: false, tombe: false },
            ],
          }],
        },
        journal: [
          'Marquage (2) : toute ton Attaque vise OriganireTV.',
          'Échange de coups — les dégâts s’appliquent des deux côtés avant tout retrait.',
          'OriganireTV Chute.',
        ],
      },
      {
        tour: 3, tirage: 3,
        note: 'La réserve adverse entre. Tu ne dépenses rien : tu vises l’Ultime de rhae___, à 10.',
        haut: {
          nom: 'Kass',
          groupes: [{
            nom: null, energie: 4, main: 3, reserve: 1,
            heros: [
              { id: 'kassandre', pv: 1, degats: 0, ultime: false, tombe: false },
              { id: 'claker', pv: 2, degats: 0, ultime: false, tombe: false },
              neuf('azrael', { nouveau: true }),
            ],
          }],
        },
        bas: {
          nom: 'Toi',
          groupes: [{
            nom: null, energie: 1 + T, main: ['garde', 'esquive', 'renfort'], reserve: ['origanire', 'claker'],
            heros: [
              { id: 'kingsrequin', pv: 2, degats: 0, ultime: false, tombe: false },
              { id: 'azrael', pv: 1, degats: 2, ultime: false, tombe: false },
              { id: 'rhae', pv: 3, degats: 0, ultime: false, tombe: false },
            ],
          }],
        },
        journal: [
          'La réserve adverse entre : Azraël prend la place laissée vide.',
          'Esquive (Tirage 3 ≥ 3) : ton Azraël ignore les dégâts du tour.',
          'Tu gardes 4 d’énergie. Épargner est possible — jamais indéfiniment.',
        ],
      },
      {
        tour: 4, tirage: 2,
        note: '7 sur 12. L’Ultime en coûte 10 : encore un tour à tenir, et l’énergie au-delà de 12 est perdue.',
        haut: {
          nom: 'Kass',
          groupes: [{
            nom: null, energie: T, main: 2, reserve: 1,
            heros: [
              { id: 'kassandre', pv: 0, degats: 1, ultime: false, tombe: true },
              { id: 'claker', pv: 2, degats: 0, ultime: false, tombe: false },
              { id: 'azrael', pv: 3, degats: 3, ultime: false, tombe: false },
            ],
          }],
        },
        bas: {
          nom: 'Toi',
          groupes: [{
            nom: null, energie: 7, main: ['garde', 'renfort'], reserve: ['origanire', 'claker'],
            heros: [
              { id: 'kingsrequin', pv: 2, degats: 0, ultime: false, tombe: false },
              { id: 'azrael', pv: 1, degats: 0, ultime: false, tombe: false },
              { id: 'rhae', pv: 3, degats: 0, ultime: false, tombe: false },
            ],
          }],
        },
        journal: [
          'KassandreYunikon Chute. Quatre héros adverses sont tombés.',
          'Tu montes à 7 d’énergie sur 12.',
        ],
      },
      {
        tour: 5, tirage: 6,
        note: 'L’Ultime part : l’Aura de rhae___ compte deux fois, plafonnée à +5. Toute la ligne en profite.',
        haut: {
          nom: 'Kass',
          groupes: [{
            nom: null, energie: 6, main: 2, reserve: null,
            heros: [
              { id: 'claker', pv: 0, degats: 9, ultime: false, tombe: true },
              { id: 'azrael', pv: 0, degats: 12, ultime: false, tombe: true },
              neuf('origanire', { nouveau: true, pv: 0, degats: 7, tombe: true }),
            ],
          }],
        },
        bas: {
          nom: 'Toi',
          groupes: [{
            nom: null, energie: 0, main: ['garde', 'renfort'], reserve: [],
            heros: [
              { id: 'kingsrequin', pv: 2, degats: 0, ultime: false, tombe: false },
              { id: 'azrael', pv: 1, degats: 0, ultime: false, tombe: false },
              { id: 'rhae', pv: 3, degats: 0, ultime: true, tombe: false },
            ],
          }],
        },
        journal: [
          'Ultime — rhae___ : « Tout le monde se parle » (10 d’énergie).',
          'Son Aura est comptée deux fois, dans la limite de +5. Aucun doublement n’est sans plafond.',
          'Les cinq héros adverses ont Chuté. Partie gagnée au tour 5.',
        ],
      },
    ],
  },
  {
    cle: 'coop',
    libelle: 'Coop',
    resume: 'Toute la commu contre Wally. Ses PV valent 40 × le nombre de joueurs — jamais un chiffre fixe.',
    etats: [
      {
        tour: 1, tirage: 2,
        note: 'Trois joueurs, deux héros chacun. L’Aura TRAVERSE les joueurs : ton héros renforce celui du voisin.',
        haut: { nom: 'Wally', boss: { id: 'wally', pv: 120, pvMax: 120 }, groupes: [] },
        bas: {
          nom: 'La commu',
          groupes: [
            { nom: 'Toi', energie: T, main: ['renfort', 'garde', 'nuit'], reserve: null, heros: [neuf('kingsrequin'), neuf('azrael')] },
            { nom: 'Kass', energie: T, main: 3, reserve: null, heros: [neuf('kassandre'), neuf('rhae')] },
            { nom: 'Claker', energie: T, main: 3, reserve: null, heros: [neuf('claker'), neuf('origanire')] },
          ],
        },
        journal: ['Trois joueurs : Wally démarre à 40 × 3 = 120 PV.', 'Il frappe UNE cible par tour, désignée par sa propre logique.'],
      },
      {
        tour: 2, tirage: 5,
        note: 'L’Attaque cumulée du groupe frappe Wally. Lui n’a frappé qu’une seule fois.',
        haut: { nom: 'Wally', boss: { id: 'wally', pv: 98, pvMax: 120, degats: 22 }, groupes: [] },
        bas: {
          nom: 'La commu',
          groupes: [
            { nom: 'Toi', energie: 1 + T, main: ['garde', 'nuit'], reserve: null, heros: [{ id: 'kingsrequin', pv: 0, degats: 7, ultime: false, tombe: true }, neuf('azrael')] },
            { nom: 'Kass', energie: T, main: 3, reserve: null, heros: [neuf('kassandre'), neuf('rhae')] },
            { nom: 'Claker', energie: 1 + T, main: 3, reserve: null, heros: [neuf('claker'), neuf('origanire')] },
          ],
        },
        journal: [
          'Renfort (2) : +2 d’Attaque à Azraël.',
          'Les six héros frappent pour 22 au total.',
          'Wally vise le plus menaçant : KingsRequin Chute.',
        ],
      },
      {
        tour: 3, tirage: 4,
        note: 'La triche annoncée : il déclare un total, et une fois par partie il révèle qu’il en restait plus.',
        haut: { nom: 'Wally', boss: { id: 'wally', pv: 41, pvMax: 150, ultime: true }, groupes: [] },
        bas: {
          nom: 'La commu',
          groupes: [
            { nom: 'Toi', energie: 7, main: ['garde', 'nuit'], reserve: null, heros: [{ id: 'azrael', pv: 4, degats: 2, ultime: false, tombe: false }] },
            { nom: 'Kass', energie: 4, main: 2, reserve: null, heros: [{ id: 'kassandre', pv: 2, degats: 2, ultime: false, tombe: false }, neuf('rhae')] },
            { nom: 'Claker', energie: 5, main: 2, reserve: null, heros: [neuf('claker'), { id: 'origanire', pv: 0, degats: 7, ultime: false, tombe: true }] },
          ],
        },
        journal: [
          'Wally tombe à 11 PV — puis annonce qu’il lui en restait 30 de plus.',
          'C’est une RÈGLE, pas un bug du moteur : annoncée, c’est un bluff ; cachée, elle serait indiscernable d’une erreur de calcul.',
          'OriganireTV Chute. Il reste cinq héros debout.',
        ],
      },
    ],
  },
];
