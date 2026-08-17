/* Avalanche de memes — le séquencement, sans DOM.
 *
 * Ce que l'owner a demandé après le premier essai en direct : « tous les memes
 * doivent passer ; je sais que ça cache l'écran et que c'est long, c'est fait
 * pour. » Donc un PARCOURS du dossier, pas un tirage : la version d'origine
 * piochait au hasard à chaque lâcher (avec remise) et laissait dormir environ
 * 40 % du stock pendant que d'autres repassaient trois fois.
 *
 * Ce fichier est chargé AVANT `overlay.js` et ne touche ni au document ni au
 * réseau : c'est ce qui permet de l'exécuter tel quel dans les tests, au lieu
 * d'aller relire le code du rendu au grep.
 */
(() => {
  "use strict";

  // Ce que met un meme à traverser l'écran, au pire (cf. `animationDuration`
  // dans le rendu : 2,6 à 5,0 s). Le dernier lâcher doit tomber AVANT que la
  // carte ne se retire, sinon la fin de l'avalanche s'évapore en plein vol.
  const CHUTE_S = 5;

  // Plafond de débit : jamais plus de six lâchers par seconde, soit le double
  // de la cadence visée (3/s, `AVALANCHE_PAR_SECONDE` côté serveur). Ce n'est
  // pas une simple sécurité anti-freeze : sans lui, une fenêtre plus courte que
  // le stock — le ▶ du panneau, qui n'essaie que cinq secondes — lâchait les
  // 134 memes en une seconde. Mesuré : 52 flocons vivants d'un coup.
  // La marge ×2 absorbe un stock plus gros que celui qu'a compté le serveur ;
  // au-delà, la pluie garde sa cadence et déborde plutôt que de partir en bloc.
  const PAS_MIN_MS = 1000 / 6;

  /* Le stock dans un ordre mêlé, en entier, une fois chacun.
   *
   * Copie d'abord : la liste vient du rotateur (`window.WallyRotationMedias`),
   * qui s'en sert pour son propre défilé. La mélanger en place mêlerait aussi
   * le sien.
   */
  function ordre(medias) {
    const stock = Array.isArray(medias) ? medias.slice() : [];
    for (let i = stock.length - 1; i > 0; i--) {          // Fisher-Yates
      const j = Math.floor(Math.random() * (i + 1));
      const t = stock[i]; stock[i] = stock[j]; stock[j] = t;
    }
    return stock;
  }

  /* Millisecondes entre deux lâchers pour que `nb` memes tiennent dans la
   * fenêtre annoncée par le serveur.
   *
   * Le serveur dimensionne la fenêtre sur SON décompte du dossier, le client
   * répartit le SIEN dedans : un meme ajouté entre les deux lectures accélère
   * un peu la pluie au lieu de se faire couper par le retrait de la carte.
   */
  function cadence(nb, dureeS) {
    const combien = Math.max(1, Number(nb) || 0);
    return Math.max(PAS_MIN_MS, fenetreMs(dureeS) / combien);
  }

  /* Jusqu'à quand on LÂCHE, en millisecondes depuis le début.
   *
   * Le lâcher s'arrête avant la carte, d'une chute entière : un meme lancé à la
   * dernière seconde s'évapore en plein vol quand le widget se retire — « les
   * memes disparaissent avant la fin de la chute » (owner). Compter les memes
   * ne suffit pas : dès que le plafond de débit s'applique (fenêtre plus courte
   * que le stock), le nombre de lâchers dépasse la fenêtre, et c'est le temps
   * qui doit trancher.
   */
  function fenetreMs(dureeS) {
    return Math.max(0, (Number(dureeS) || 0) - CHUTE_S) * 1000;
  }

  window.WallyAvalanche = { ordre, cadence, fenetreMs, CHUTE_S, PAS_MIN_MS };
})();
