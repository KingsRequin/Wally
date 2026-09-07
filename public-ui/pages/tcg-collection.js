// public-ui/pages/tcg-collection.js — les cartes TERMINÉES
//
// 🚨 Une carte n'entre ici que quand son illustration EXISTE. Ce fichier n'est
// pas la liste des cartes prévues, c'est la liste de celles qu'on peut
// montrer : la galerie affiche exactement son contenu, et son compteur en
// dérive. Une entrée sans image donnerait une carte noire annoncée comme
// terminée.
//
// 🚨 Rien ici n'est calculé et rien ne le sera : le moteur de règles vit côté
// serveur, en Python. Ces valeurs sont RECOPIÉES depuis la base Notion
// « 🃏 Cartes du Purgatoire », qui est la source. Les faire dériver d'une
// formule en JavaScript ouvrirait une porte de triche et un second jeu à
// maintenir.
//
// ⚠️ Ne pas confondre avec `tcg-demo.js`, qui porte les six héros PLACEHOLDER
// de la maquette du plateau (`/demo/plateau-tcg`) : ceux-là sont là pour avoir
// quelque chose à l'écran, pas pour être exacts.

// Les réglages visuels (`heroCote`, `heroEchelle`, `avantPlan`…) viennent de la
// maquette Claude Design : ils cadrent une illustration donnée dans le cadre de
// la carte. Ils sont propres à chaque image et n'ont aucun sens de règle.
export const CARTES = [
  {
    legende: 'AZRAËL · ARCHANGE',
    // Budget 12 + 8 (Archange) = 20, réparti en 5/10/5. Ultime F07 « Rework »
    // à 10 d'énergie — catalogue des Réflexes §F07, arbitré le 2026-09-07.
    carte: {
      nom: 'AZRAËL',
      classe: 'ARCHANGE · UNIQUE',
      ultime: 'REWORK',
      description: 'Rework : désigne un héros adverse. Pour le reste de la partie, '
        + 'son Ultime coûte +3 et tous ses nombres baissent de 2.',
      ambiance: 'Il ne te dit jamais non. Il attend le prochain patch, '
        + 'et un matin plus personne ne te craint.',
      cout: 10, atk: 5, pv: 10, aura: 5,
      accent: '#ffb02e',
      hero: '/assets/tcg-azrael-hero.webp',
      fond: '/assets/tcg-azrael-fond.webp',
      particules: 'braises',
    },
  },
];
