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

## spin-wheel 5.0.2

- Source : <https://cdn.jsdelivr.net/npm/spin-wheel@5.0.2/dist/spin-wheel-iife.js>
- Dépôt : <https://github.com/CrazyTim/spin-wheel>
- Licence : MIT — voir `LICENSE-spin-wheel.md`
- sha256 : `f02a1704248a9b069f2624b2770d0d67dcf81a073d43bfb270bd72e3b528706c`
- Expose le global `spinWheel.Wheel`

Build **IIFE** et non ESM : l'overlay est chargé par de simples balises `<script>`,
sans module ni bundler.

⚠️ `Wheel.remove()` est obligatoire quand le widget disparaît — la boucle
d'animation survit au retrait du canvas du DOM. Voir `disposeWheel()` dans
`overlay.js`.

## three.js 0.185.1

- Source : <https://unpkg.com/three@0.185.1/build/three.module.min.js>
  et <https://unpkg.com/three@0.185.1/build/three.core.min.js>
- Dépôt : <https://github.com/mrdoob/three.js>
- Licence : MIT — voir `LICENSE-three.txt`
- sha256 : `86bcee248b64f44bcfc23c331ae74619061957d59cab040171dcb6fb5900beb6`
  (`three.module.min.js`), `05b2609338c76cd65daf74f3ac515bc9a5045e1b3b33edc07d8c9bd55250fa90`
  (`three.core.min.js`)

**Les deux fichiers vont ensemble** : `three.module.min.js` importe
`./three.core.min.js` en relatif. Séparer les deux casse le chargement.

Build **ESM** — contrairement aux deux autres, il se charge par
`import ... from "/static/vendor/three.module.min.js"` dans un
`<script type="module">`.

Utilisé par `avatar3d.js` (maquette d'avatar 3D). **Rien en production ne
dépend de three.js aujourd'hui** : l'overlay sert toujours `avatar/wally.webm`.

⚠️ `THREE.Clock` est déprécié depuis r185 — utiliser `performance.now()` ou
`THREE.Timer`.

## MarchingCubes (addon three.js 0.185.1)

- Source : <https://unpkg.com/three@0.185.1/examples/jsm/objects/MarchingCubes.js>
- Licence : MIT — celle de three.js, voir `LICENSE-three.txt`
- sha256 amont : `fe9c6ace2c079bf540befd164ce492de98c820d8b86a722b1060833d42ad9c80`
- sha256 local : `f22973b54d1476a9d5e423a3e58ec33f03d2a720cf371f8efc9cd6ecbdee8a8a`

**Seule modification** — l'import, qui pointe sur le three local :

```
-} from 'three';
+} from './three.module.min.js';
```

C'est la seule façon de charger un addon `three/addons/…` sans bundler ni
import map. Refaire ce `sed` à chaque mise à jour de three.

Utilisé par `avatar3d.js` : le corps de Wally est une union de métaballes
polygonisée à chaque image. Deux pièges relevés à l'usage :

- `addBall(x, y, z, force, soustrait)` attend des coordonnées dans **0..1**, mais
  le maillage produit va de **−1 à 1**. Tout ce qu'on pose dessus doit donc être
  converti (`× 2 − 1`).
- La portée de fusion d'une boule vaut `rayon × √((isolation + soustrait) / soustrait)`.
  Avec le `soustrait = 12` des exemples officiels, elle atteint 2,7 rayons et
  toutes les formes se soudent en une patate. `avatar3d.js` utilise 45.
