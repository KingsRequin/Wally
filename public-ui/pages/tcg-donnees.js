// public-ui/pages/tcg-donnees.js — les cartes, lues côté serveur
//
// La source est `bot/core/tcg_cartes.py` : c'est elle que lisent aussi l'outil
// de Wally et le widget de l'overlay. Ce module ne fait que l'apporter au
// front, et transformer les chemins en paires AVIF + repli WebP.

import { image } from '../partage/tcg-carte.js';

// Un seul appel pour les deux pages qui affichent des cartes. Sans cette
// mémorisation, aller de /tcg à /demo/carte-azrael redemanderait la même
// liste — et deux réponses, c'est deux occasions de diverger à l'écran.
let _promesse = null;

export function cartes() {
  if (!_promesse) {
    _promesse = fetch('/api/public/tcg/cartes')
      .then((r) => {
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        return r.json();
      })
      .then((d) => d.cartes.map((c) => ({
        ...c,
        // Le serveur envoie un chemin sans extension, empreinte comprise
        // (`/assets/tcg-azrael-hero?v=7ff48bed`) ; c'est ici qu'on en fait la
        // paire AVIF + repli WebP.
        hero: image(c.hero),
        fond: image(c.fond),
        avantPlan: c.avantPlan ? image(c.avantPlan) : null,
        hero3d: c.hero3d ? image(c.hero3d) : null,
      })))
      // Un échec ne se mémorise PAS : la page doit pouvoir réessayer, sinon
      // une coupure d'une seconde vide le site jusqu'au rechargement.
      .catch((e) => { _promesse = null; throw e; });
  }
  return _promesse;
}
