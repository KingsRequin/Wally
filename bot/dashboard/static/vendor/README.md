# Dépendances tierces de l'overlay

Servies depuis `/static/vendor/`, jamais depuis un CDN.

**Pourquoi vendorisé et pas un `<script src="https://cdn...">`** : l'overlay tourne
dans OBS, chez le streamer, à côté du jeu. Une dépendance réseau externe, c'est un
overlay muet le jour où le CDN est lent, bloqué par un DNS filtrant, ou coupé. Vécu
le 2026-08-08 : AdGuard éteint avait suffi à rendre `heywally.fr` injoignable.

Aucun build ici — l'overlay est du JS vanilla servi tel quel. Les fichiers sont donc
repris à l'identique de leur distribution officielle.

## canvas-confetti 1.9.4

- Source : <https://unpkg.com/canvas-confetti@1.9.4/dist/confetti.browser.js>
- Dépôt : <https://github.com/catdad/canvas-confetti>
- Licence : ISC — voir `LICENSE-canvas-confetti.txt`
- sha256 : `49f4bcbc56e7ceb5c3d25d13db1d0da965b6cd1c8a54a707bb055be0685b0a95`

Non modifié. Pour mettre à jour : retélécharger la même URL avec la nouvelle
version, vérifier `node --check`, et reporter la version ici.
