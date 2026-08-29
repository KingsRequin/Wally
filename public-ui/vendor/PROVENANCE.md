# public-ui/vendor/

Dépendances tierces servies telles quelles. **Ne rien éditer ici** : à la
prochaine mise à jour, tout modification locale disparaît sans laisser de trace.

| Fichier | Version | Licence | Source |
|---|---|---|---|
| `lenis.min.js` | 1.1.18 | MIT (Darkroom Engineering) | `https://unpkg.com/lenis@1.1.18/dist/lenis.min.js` |

Vendoré plutôt que chargé depuis unpkg : un CDN tiers sur le chemin critique du
site public, c'est une dépendance réseau de plus ET une surface d'exécution
qu'on ne contrôle pas. La seule modification apportée au fichier est le retrait
du commentaire `sourceMappingURL`, qui pointait vers un fichier absent et
provoquait un 404 à chaque chargement.

Mise à jour : retélécharger, retirer la ligne `sourceMappingURL`, relancer
`python3 scripts/smoke_front.py --public`.
