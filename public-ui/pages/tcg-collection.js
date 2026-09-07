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
// Les illustrations sont déclarées SANS extension, via `image()` : chacune est
// servie en AVIF avec un repli WebP, et les deux ne peuvent pas être oubliées
// séparément.
//
// ⚠️ Ne pas confondre avec `tcg-demo.js`, qui porte les six héros PLACEHOLDER
// de la maquette du plateau (`/demo/plateau-tcg`) : ceux-là sont là pour avoir
// quelque chose à l'écran, pas pour être exacts.

import { image } from './tcg-carte-hero.js';

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
      hero: image('/assets/tcg-azrael-hero'),
      fond: image('/assets/tcg-azrael-fond'),
      particules: 'braises',
    },
  },
  {
    legende: 'CLAKERNOJUTSU · ÂME',
    // Budget 12 (rareté Âme, aucun bonus) réparti en 5/4/3.
    carte: {
      nom: 'CLAKER',
      classe: 'ÂME · NO JUTSU',
      ultime: 'NO JUTSU',
      description: 'Annule la prochaine tactique jouée par un adversaire.',
      ambiance: "La technique, c'est de ne pas en avoir.",
      cout: 8, atk: 5, pv: 4, aura: 3,
      accent: '#7de3a4',
      hero: image('/assets/tcg-claker-hero'),
      fond: image('/assets/tcg-claker-fond'),
      // Ses pieds passent DEVANT lui : c'est la couche d'avant-plan, et c'est
      // elle qui donne la profondeur quand la carte s'ouvre.
      avantPlan: image('/assets/tcg-claker-pieds'),
      avantPlanLargeur: '100%',
      avantPlanBas: '15%',
      heroCote: '5%',
      heroHaut: '-8%',
      heroEchelle: 1.1,
      particules: 'poussiere',
      parallaxe: 0.9,
      intensite: 0.6,
    },
  },
];
