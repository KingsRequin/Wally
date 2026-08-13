/* Glitch — la rafale de parasitage partagée par les sources OBS.
 *
 * Écrite une seule fois : le rotateur de memes et l'overlay principal
 * s'affichent sur le MÊME stream. Deux glitchs écrits séparément dériveraient
 * l'un de l'autre, et le spectateur verrait deux vocabulaires.
 *
 * Les états sont tirés au sort à chaque passage plutôt qu'écrits en
 * `@keyframes` : un glitch qui rejoue la même chorégraphie toutes les quinze
 * secondes se lit comme une boucle et devient mécanique. Le coût est
 * identique — ce sont les mêmes propriétés qui bougent.
 */
(() => {
  "use strict";

  const FILTRES = [
    "invert(1) hue-rotate(90deg)",
    "hue-rotate(200deg) saturate(6)",
    "brightness(2.6) saturate(0)",
    "drop-shadow(7px 0 0 rgba(255,0,64,.9)) drop-shadow(-7px 0 0 rgba(0,225,255,.9))",
    "invert(1) saturate(4)",
    "hue-rotate(-70deg) saturate(5) brightness(1.4)",
  ];

  const hasard = (min, max) => min + Math.random() * (max - min);
  const parmi = (liste) => liste[Math.floor(Math.random() * liste.length)];

  /** Un état de glitch : une bande visible, un décalage, une couleur qui dérive.
   *
   *  Les bandes coupent à angles droits, sans rayon — c'est l'effet recherché.
   *  `decalage` borne le déplacement horizontal : une bulle de 200 px ne peut
   *  pas se décaler d'autant qu'un meme plein cadre sans partir hors champ.
   */
  function etatAuHasard(decalage = 26) {
    const haut = hasard(0, 70);
    const bas = hasard(0, 100 - haut - 12);
    return {
      clipPath: `inset(${haut.toFixed(0)}% 0 ${bas.toFixed(0)}% 0)`,
      transform: `translateX(${hasard(-decalage, decalage).toFixed(0)}px) `
                 + `scaleY(${hasard(0.94, 1.07).toFixed(2)})`,
      filter: parmi(FILTRES),
      opacity: Math.random() < 0.2 ? "0.45" : "1",
    };
  }

  function appliquer(el, etat) {
    el.style.clipPath = etat.clipPath;
    el.style.transform = etat.transform;
    el.style.filter = etat.filter;
    el.style.opacity = etat.opacity;
  }

  /** Rend les quatre propriétés à la feuille de style.
   *
   *  Indispensable après une rafale : posées en ligne, elles l'emportent sur
   *  tout ce que le CSS dira ensuite, et l'élément suivant naîtrait parasité.
   */
  function nettoyer(el) {
    el.style.clipPath = "";
    el.style.transform = "";
    el.style.filter = "";
    el.style.opacity = "";
  }

  /** `round` et non un `inset` nu : un clip rectangulaire laisse l'angle droit
   *  du contenu réapparaître derrière les coins arrondis du cadre. */
  const net = (rayon) => (
    { clipPath: `inset(0 0 0 0 round ${rayon})`, transform: "none", filter: "none", opacity: "1" }
  );
  const eteint = (rayon) => (
    { clipPath: `inset(0 0 100% 0 round ${rayon})`, transform: "none", filter: "none", opacity: "0" }
  );

  /** Joue une rafale sur `el`. Rend une promesse tenue à la fin. */
  function rafale(el, { etats = 7, saccade = 33, decalage = 26 } = {}) {
    return new Promise((fini) => {
      let n = 0;
      (function saccader() {
        if (n >= etats) { fini(); return; }
        appliquer(el, etatAuHasard(decalage));
        n += 1;
        setTimeout(saccader, saccade);
      })();
    });
  }

  window.WallyGlitch = { rafale, appliquer, nettoyer, etatAuHasard, net, eteint };
})();
