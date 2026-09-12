// public-ui/pages/tcg-donnees.js — les cartes, lues côté serveur
//
// La source est `bot/core/tcg_cartes.py` : c'est elle que lisent aussi l'outil
// de Wally et le widget de l'overlay. Ce module ne fait que l'apporter au
// front, et transformer les chemins en paires AVIF + repli WebP.

// Un seul appel par famille, mémorisé. Sans ça, aller de /tcg à
// /demo/carte-azrael redemanderait la même liste — et deux réponses, c'est
// deux occasions de diverger à l'écran. Les onglets de /tcg en profitent
// aussi : basculer d'avant en arrière ne redemande rien.
const _promesses = {};

/** Une famille de cartes, mémorisée par sa route.
 *
 * 🚨 Un échec ne se mémorise PAS : la page doit pouvoir réessayer, sinon une
 * coupure d'une seconde vide le site jusqu'au rechargement.
 */
function charger(route) {
  if (!_promesses[route]) {
    _promesses[route] = fetch(route)
      .then((r) => {
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        return r.json();
      })
      .then((d) => d.cartes)
      .catch((e) => { delete _promesses[route]; throw e; });
  }
  return _promesses[route];
}

/** Les HÉROS, de la plus haute carte à la plus basse. */
export function cartes() {
  return charger('/api/public/tcg/cartes');
}

/** Les cartes ACTION et PASSIF, rangées par catégorie.
 *
 * Deux routes et pas une avec un filtre : un héros et une carte action n'ont
 * aucun champ en commun au-delà du nom, et les fondre donnerait des objets
 * dont les deux tiers des clés sont nulles.
 */
export function cartesAction() {
  return charger('/api/public/tcg/cartes-action');
}
