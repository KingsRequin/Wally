# Rotateur de memes — plan d'implémentation

> **Pour un agent :** SOUS-COMPÉTENCE REQUISE — utiliser
> `superpowers:subagent-driven-development` (recommandé) ou
> `superpowers:executing-plans` pour dérouler ce plan tâche par tâche. Les étapes
> sont en cases à cocher (`- [ ]`).

**But :** une source OBS maison qui fait défiler en boucle les médias de
`data/memes`, en remplacement du widget « Asset rotator » de StreamElements dont
les fichiers finissent par ne plus charger.

**Architecture :** une page HTML autonome (`/overlay-rotation`) qui demande la
liste des médias à une route publique, puis tourne toute seule sans dépendre du
bot. Le bot n'expose que la liste ; il ne pilote rien.

**Pile :** Python 3.12 / FastAPI côté serveur, HTML + CSS + JavaScript sans
dépendance côté page. Tests avec `pytest`.

**Conception de référence :** `docs/plans/2026-08-11-overlay-rotation-memes-design.md`

## Contraintes globales

- **Aucune dépendance réseau sortante dans la page** : une source de live ne doit
  pas dépendre d'un CDN. Tout est écrit sur place.
- **La boucle ne s'arrête jamais**, quelle que soit la panne. C'est le critère
  d'acceptation de toutes les tâches côté page.
- **`MemeLibrary.list()` ne doit jamais renvoyer de vidéo** : `OverlayNarrator`
  l'affiche dans une balise `<img>`. Invariant protégé par un test.
- **Loguru uniquement** côté Python, jamais `print()` ni `logging`.
- **Vérification avant de déclarer fini** : `python3 -m pytest`,
  `python3 -m ruff check`, `python3 -m mypy`, et les cliquets
  `python3 scripts/lint_silences.py` / `python3 scripts/lint_types.py`.
- **Publication** : commit + `git push public feat/site-redesign-arcade:main` +
  `docker compose build wally` + `docker compose up -d wally`, dans la foulée.
- Le dossier `data/` est ignoré par git : les médias ne sont jamais commités.

## Structure des fichiers

| Fichier | Responsabilité |
|---|---|
| `bot/core/memes.py` *(modifié)* | Inventaire du dossier. Distingue ce que Wally peut **montrer** (images) de ce que la route peut **servir** (images + vidéos). |
| `bot/dashboard/routes/overlay.py` *(modifié)* | Expose la liste des médias sur `/api/public/rotation`. |
| `bot/dashboard/app.py` *(modifié)* | Sert la page sur `/overlay-rotation`. |
| `bot/dashboard/static/overlay_rotation.html` *(créé)* | La page : cadre, boucle, glitch, robustesse. Autonome. |
| `tests/test_memes.py` *(modifié)* | Tests de la bibliothèque. |
| `tests/test_overlay_rotation.py` *(créé)* | Tests de la route. |
| `docs/overlay.md` *(modifié)* | Réglages OBS de la nouvelle source. |

---

### Tâche 1 : la bibliothèque distingue montrer et servir

**Fichiers :**
- Modifier : `bot/core/memes.py:19-38` (la table `_MEDIA_TYPES` et `_EXTENSIONS`)
- Modifier : `bot/core/memes.py:72-89` (`MemeLibrary.list`)
- Modifier : `bot/core/memes.py:122-138` (`MemeLibrary.resolve`)
- Test : `tests/test_memes.py`

**Interfaces :**
- Consomme : rien.
- Produit : `MemeLibrary.list_medias() -> list[dict]`, chaque entrée
  `{"name": str, "genre": "image" | "video"}`, triée par nom.
  `media_type(path: Path) -> str` gagne `.mp4` et `.webm`.

- [ ] **Étape 1 : écrire les tests qui échouent**

Ajouter à la fin de `tests/test_memes.py` :

```python
def test_les_videos_sont_listees_a_part_des_images(tmp_path):
    """Wally affiche dans un <img> : une vidéo dans sa liste serait cassée.

    Le rotateur, lui, sait jouer les deux. Deux consommateurs, deux besoins —
    d'où deux listes.
    """
    (tmp_path / "chat.png").write_bytes(b"x")
    (tmp_path / "requin.mp4").write_bytes(b"x")
    lib = MemeLibrary(tmp_path)

    assert [m["name"] for m in lib.list()] == ["chat.png"]
    assert [(m["name"], m["genre"]) for m in lib.list_medias()] == [
        ("chat.png", "image"),
        ("requin.mp4", "video"),
    ]


def test_la_route_peut_servir_une_video(tmp_path):
    """`resolve` sert un fichier ; il n'a pas à savoir l'afficher."""
    (tmp_path / "requin.mp4").write_bytes(b"x")
    lib = MemeLibrary(tmp_path)

    assert lib.resolve("requin.mp4") == tmp_path / "requin.mp4"
    assert lib.resolve("requin.exe") is None


def test_le_type_mime_des_videos(tmp_path):
    from bot.core.memes import media_type

    assert media_type(tmp_path / "a.mp4") == "video/mp4"
    assert media_type(tmp_path / "a.WEBM") == "video/webm"
```

- [ ] **Étape 2 : jouer les tests, vérifier qu'ils échouent**

Run : `python3 -m pytest tests/test_memes.py -k "video" -v`
Attendu : `AttributeError: 'MemeLibrary' object has no attribute 'list_medias'`

- [ ] **Étape 3 : implémenter**

Dans `bot/core/memes.py`, remplacer le bloc des constantes par :

```python
# Extension acceptée -> type MIME annoncé par la route publique. On ne laisse
# PAS `mimetypes` deviner : l'image Docker (Python 3.12, sans /etc/mime.types)
# ignore `.webp`, et les memes de ce format partaient en
# `application/octet-stream`.
_MEDIA_TYPES = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".webp": "image/webp",
    ".mp4": "video/mp4",
    ".webm": "video/webm",
}

# Ce que Wally peut MONTRER : il affiche dans une balise <img>, une vidéo y
# serait cassée. `list()` s'y tient, et le test le vérifie.
_EXTENSIONS = frozenset(
    e for e, t in _MEDIA_TYPES.items() if t.startswith("image/")
)

# Ce que la route publique peut SERVIR : servir un fichier ne demande pas de
# savoir l'afficher. Le rotateur, lui, sait jouer les vidéos.
_EXTENSIONS_MEDIA = frozenset(_MEDIA_TYPES)
```

Ajouter la méthode dans `MemeLibrary`, juste après `list()` :

```python
    def list_medias(self) -> list[dict]:
        """Images ET vidéos, chacune avec son genre. Pour le rotateur.

        Séparée de `list()` à dessein : celle-ci alimente une page qui sait
        jouer une vidéo, celle-là un `<img>` qui ne le sait pas.
        """
        try:
            entries = sorted(self._dir.iterdir())
        except OSError:
            return []
        out: list[dict] = []
        for path in entries:
            suffix = path.suffix.lower()
            if not path.is_file() or suffix not in _EXTENSIONS_MEDIA:
                continue
            try:
                if path.stat().st_size > _MAX_BYTES:
                    logger.debug("Média ignoré (trop lourd) : {n}", n=path.name)
                    continue
            except OSError:
                continue
            genre = "video" if _MEDIA_TYPES[suffix].startswith("video/") else "image"
            out.append({"name": path.name, "genre": genre})
        return out
```

Dans `resolve()`, remplacer `_EXTENSIONS` par `_EXTENSIONS_MEDIA` :

```python
        if not safe or Path(safe).suffix.lower() not in _EXTENSIONS_MEDIA:
            return None
```

`list()` n'est pas touchée : elle continue de filtrer sur `_EXTENSIONS`.

- [ ] **Étape 4 : jouer les tests, vérifier qu'ils passent**

Run : `python3 -m pytest tests/test_memes.py -v`
Attendu : tout passe, y compris les tests existants (aucune régression sur `list()`).

- [ ] **Étape 5 : vérifier que l'overlay compagnon n'a pas bougé**

Run : `python3 -m pytest tests/test_memes.py tests/test_overlay_narrator.py tests/test_overlay_tool.py -q`
Attendu : tout passe. C'est le filet qui protège l'existant.

- [ ] **Étape 6 : commit**

```bash
git add bot/core/memes.py tests/test_memes.py
git commit -m "feat(memes): la bibliothèque distingue ce qu'on montre de ce qu'on sert

Le rotateur sait jouer une vidéo, l'overlay compagnon non — il affiche dans un
<img>. Une seule liste et le .mp4 y finirait cassé."
```

---

### Tâche 2 : la route qui expose la liste

**Fichiers :**
- Modifier : `bot/dashboard/routes/overlay.py` (ajouter après `get_meme`, vers la ligne 111)
- Test : `tests/test_overlay_rotation.py` *(créé)*

**Interfaces :**
- Consomme : `MemeLibrary.list_medias()` de la tâche 1.
- Produit : `GET /api/public/rotation` →
  `{"medias": [{"nom": "meme1.webp", "genre": "image"}, …]}`.
  Fonction `get_rotation(request: Request) -> dict`.

⚠️ La clé s'appelle `name` côté Python (`list_medias()` suit `list()`, qui existe
déjà) et `nom` côté JSON. La route fait la conversion, une seule fois et
explicitement. Ne pas confondre les deux en écrivant la page : le JavaScript ne
voit que `nom`.

- [ ] **Étape 1 : écrire les tests qui échouent**

Créer `tests/test_overlay_rotation.py` :

```python
"""La liste des médias du rotateur.

La page la demande une fois puis tourne seule : elle doit donc être servie même
quand tout va mal, et surtout ne jamais lever une erreur qui laisserait la
source vide pour le reste du live.
"""
import pytest

from bot.core.memes import MemeLibrary
from bot.dashboard.routes.overlay import get_rotation


def _requete(state):
    return type("R", (), {
        "app": type("A", (), {"state": type("S", (), {"wally": state})()})()
    })()


@pytest.mark.asyncio
async def test_la_liste_donne_le_nom_et_le_genre(tmp_path):
    (tmp_path / "chat.webp").write_bytes(b"x")
    (tmp_path / "requin.mp4").write_bytes(b"x")
    state = type("W", (), {"memes": MemeLibrary(tmp_path)})()

    assert await get_rotation(_requete(state)) == {"medias": [
        {"nom": "chat.webp", "genre": "image"},
        {"nom": "requin.mp4", "genre": "video"},
    ]}


@pytest.mark.asyncio
async def test_un_dossier_absent_donne_une_liste_vide(tmp_path):
    """Et non une erreur : la page saurait quoi faire d'une liste vide, pas
    d'un 500 — elle réessaierait indéfiniment en croyant le bot cassé."""
    state = type("W", (), {"memes": MemeLibrary(tmp_path / "nexistepas")})()

    assert await get_rotation(_requete(state)) == {"medias": []}


@pytest.mark.asyncio
async def test_sans_bibliotheque_la_liste_est_vide():
    """Le bot peut démarrer sans bibliothèque de memes."""
    state = type("W", (), {})()

    assert await get_rotation(_requete(state)) == {"medias": []}
```

- [ ] **Étape 2 : jouer les tests, vérifier qu'ils échouent**

Run : `python3 -m pytest tests/test_overlay_rotation.py -v`
Attendu : `ImportError: cannot import name 'get_rotation'`

- [ ] **Étape 3 : implémenter**

Dans `bot/dashboard/routes/overlay.py`, après la fonction `get_meme` :

```python
@public_router.get("/rotation")
async def get_rotation(request: Request) -> dict:
    """Liste des médias du rotateur : nom et genre, rien d'autre.

    Publique parce que la page tourne dans OBS sans session. Ne lève jamais :
    une source de live préfère une liste vide à une erreur, qu'elle ne saurait
    pas distinguer d'une panne du bot.
    """
    library = getattr(request.app.state.wally, "memes", None)
    if library is None:
        return {"medias": []}
    return {"medias": [
        {"nom": m["name"], "genre": m["genre"]} for m in library.list_medias()
    ]}
```

- [ ] **Étape 4 : jouer les tests, vérifier qu'ils passent**

Run : `python3 -m pytest tests/test_overlay_rotation.py -v`
Attendu : 3 passed.

- [ ] **Étape 5 : vérifier en vrai après redéploiement**

```bash
docker compose build wally && docker compose up -d wally && sleep 25
curl -s http://localhost:8080/api/public/rotation | head -c 300
```

Attendu : un JSON commençant par `{"medias":[{"nom":"meme1.webp","genre":"image"`
et contenant `{"nom":"meme35.mp4","genre":"video"}`.

- [ ] **Étape 6 : commit**

```bash
git add bot/dashboard/routes/overlay.py tests/test_overlay_rotation.py
git commit -m "feat(overlay): route publique listant les médias du rotateur"
```

---

### Tâche 3 : la page, le cadre et la boucle sur les images

**Fichiers :**
- Créer : `bot/dashboard/static/overlay_rotation.html`
- Modifier : `bot/dashboard/app.py` (après `overlay_image_page`, vers la ligne 197)

**Interfaces :**
- Consomme : `GET /api/public/rotation` (tâche 2), `GET /api/public/meme/{nom}`.
- Produit : la page `/overlay-rotation`. Fonctions JS internes :
  `charger()`, `tirer()`, `afficher(media)`, `tour()`.

- [ ] **Étape 1 : créer la page**

Créer `bot/dashboard/static/overlay_rotation.html` :

```html
<!DOCTYPE html>
<html lang="fr">
<head>
<meta charset="UTF-8">
<title>Wally — rotateur de memes</title>
<style>
  * { margin: 0; padding: 0; box-sizing: border-box; }
  body {
    background: transparent; overflow: hidden;
    width: 100vw; height: 100vh;
    display: flex; align-items: center; justify-content: center;
  }

  /* Passe-partout sombre. La plupart des memes sont sur fond blanc : sur un
     overlay noir, ça fait une dalle plus lumineuse que le reste de l'écran.
     Le liseré sombre casse le contact entre ce blanc et la bordure orange. */
  #cadre {
    padding: 14px;
    background: rgba(8, 6, 5, 0.94);
    border: 3px solid #ff7a2f;
    border-radius: 16px;
    box-shadow:
      0 0 24px rgba(255, 122, 47, 0.6),
      inset 0 0 30px rgba(0, 0, 0, 0.9),
      0 18px 45px rgba(0, 0, 0, 0.8);
    opacity: 0;
    line-height: 0;
  }

  /* Borné en largeur ET en hauteur, jamais agrandi : le cadre épouse l'image.
     En pourcentage de la source OBS et non en pixels, pour survivre à un
     redimensionnement de la source. */
  #cadre img, #cadre video {
    display: block;
    max-width: calc(100vw - 40px);
    max-height: calc(100vh - 40px);
    width: auto; height: auto;
    border-radius: 6px;
  }
</style>
</head>
<body>
<div id="cadre"><img id="media" alt=""></div>

<script>
(function () {
  const cadre = document.getElementById('cadre');
  const params = new URLSearchParams(location.search);
  const nombre = (cle, defaut) => {
    const v = Number(params.get(cle));
    return Number.isFinite(v) && v > 0 ? v : defaut;
  };

  const DUREE = nombre('duree', 9) * 1000;
  const PAUSE = nombre('pause', 5) * 1000;
  const ORDRE = params.get('ordre') === 'dossier' ? 'dossier' : 'hasard';

  let medias = [];
  let dernier = null;
  let rang = 0;
  let depuisRelecture = 0;

  async function charger() {
    // Une liste vide n'écrase jamais une liste qui marchait : le bot peut être
    // en train de redémarrer, la source doit continuer de tourner.
    try {
      const r = await fetch('/api/public/rotation', { cache: 'no-store' });
      const data = await r.json();
      if (Array.isArray(data.medias) && data.medias.length) medias = data.medias;
    } catch (e) { /* on garde la liste précédente */ }
  }

  function tirer() {
    if (!medias.length) return null;
    if (ORDRE === 'dossier') {
      const m = medias[rang % medias.length];
      rang += 1;
      return m;
    }
    // Deux fois le même d'affilée passerait pour un bug d'affichage.
    const pool = medias.filter(m => m.nom !== dernier);
    const choix = pool.length ? pool : medias;
    return choix[Math.floor(Math.random() * choix.length)];
  }

  function url(media) {
    return '/api/public/meme/' + encodeURIComponent(media.nom);
  }

  /** Charge le média et attend ses dimensions AVANT de l'afficher.
   *  Sans ça, le cadre naîtrait à la taille de l'ancien média puis grandirait
   *  d'un coup quand le nouveau arrive : le saut de format serait visible. */
  function precharger(media) {
    return new Promise((resolve, reject) => {
      const img = new Image();
      img.onload = () => resolve(img);
      img.onerror = () => reject(new Error('média illisible : ' + media.nom));
      img.src = url(media);
    });
  }

  async function tour() {
    if (!medias.length) {
      await charger();
      setTimeout(tour, medias.length ? 0 : 10000);
      return;
    }

    const media = tirer();
    dernier = media.nom;
    depuisRelecture += 1;
    if (depuisRelecture >= medias.length) { depuisRelecture = 0; charger(); }

    try {
      await precharger(media);
    } catch (e) {
      // Un fichier qui ne charge pas sort de la liste pour la session : sans
      // ça il reviendrait à chaque tour et laisserait un trou à l'écran.
      medias = medias.filter(m => m.nom !== media.nom);
      setTimeout(tour, 0);
      return;
    }

    document.getElementById('media').src = url(media);
    cadre.style.opacity = '1';
    setTimeout(function () {
      cadre.style.opacity = '0';
      setTimeout(tour, PAUSE);
    }, DUREE);
  }

  charger().then(tour);
})();
</script>
</body>
</html>
```

- [ ] **Étape 2 : servir la page**

Dans `bot/dashboard/app.py`, après `overlay_image_page` :

```python
    @app.get("/overlay-rotation")
    async def overlay_rotation_page():
        return FileResponse(
            "bot/dashboard/static/overlay_rotation.html",
            headers={"Cache-Control": "no-cache, no-store, must-revalidate"},
        )
```

- [ ] **Étape 3 : déployer et vérifier au navigateur**

```bash
docker compose build wally && docker compose up -d wally && sleep 25
curl -s -o /dev/null -w "%{http_code}\n" http://localhost:8080/overlay-rotation
```

Attendu : `200`.

Puis ouvrir `http://192.168.1.185:8080/overlay-rotation` et observer une minute.
Attendu : les memes défilent, le cadre épouse chaque format sans jamais sauter,
jamais deux fois le même d'affilée.

- [ ] **Étape 4 : commit**

```bash
git add bot/dashboard/static/overlay_rotation.html bot/dashboard/app.py
git commit -m "feat(overlay): page du rotateur de memes, boucle sur les images"
```

---

### Tâche 4 : le glitch datamosh

**Fichiers :**
- Modifier : `bot/dashboard/static/overlay_rotation.html`

**Interfaces :**
- Consomme : `cadre`, la constante `SACCADE`.
- Produit : `rafale(): Promise<void>`, `appliquer(etat)`, les constantes d'état
  `NET` et `ETEINT`.

- [ ] **Étape 1 : ajouter le moteur de glitch**

Dans le `<script>`, après la lecture des paramètres, ajouter :

```js
  const SACCADE = nombre('saccade', 33);   // ms par état
  const ETATS = 7;                          // états par rafale

  const FILTRES = [
    'invert(1) hue-rotate(90deg)',
    'hue-rotate(200deg) saturate(6)',
    'brightness(2.6) saturate(0)',
    'drop-shadow(7px 0 0 rgba(255,0,64,.9)) drop-shadow(-7px 0 0 rgba(0,225,255,.9))',
    'invert(1) saturate(4)',
    'hue-rotate(-70deg) saturate(5) brightness(1.4)',
  ];

  const hasard = (min, max) => min + Math.random() * (max - min);
  const parmi = (liste) => liste[Math.floor(Math.random() * liste.length)];

  /** Un état de glitch : une bande visible, un décalage, une couleur qui dérive.
   *  Tiré au sort à chaque passage : un glitch qui rejoue la même chorégraphie
   *  toutes les quinze secondes se lit comme une boucle et devient mécanique. */
  function etatAuHasard() {
    const haut = hasard(0, 70);
    const bas = hasard(0, 100 - haut - 12);
    return {
      clipPath: 'inset(' + haut.toFixed(0) + '% 0 ' + bas.toFixed(0) + '% 0)',
      transform: 'translateX(' + hasard(-26, 26).toFixed(0) + 'px) scaleY('
                 + hasard(0.94, 1.07).toFixed(2) + ')',
      filter: parmi(FILTRES),
      opacity: Math.random() < 0.2 ? '0.45' : '1',
    };
  }

  const NET = { clipPath: 'inset(0 0 0 0)', transform: 'none', filter: 'none', opacity: '1' };
  const ETEINT = { clipPath: 'inset(0 0 100% 0)', transform: 'none', filter: 'none', opacity: '0' };

  function appliquer(etat) {
    cadre.style.clipPath = etat.clipPath;
    cadre.style.transform = etat.transform;
    cadre.style.filter = etat.filter;
    cadre.style.opacity = etat.opacity;
  }

  function rafale() {
    return new Promise(function (fini) {
      let n = 0;
      (function saccade() {
        if (n >= ETATS) { fini(); return; }
        appliquer(etatAuHasard());
        n += 1;
        setTimeout(saccade, SACCADE);
      })();
    });
  }
```

- [ ] **Étape 2 : brancher le glitch sur le cycle**

Remplacer la fin de `tour()` (à partir de `document.getElementById('media').src`) par :

```js
    document.getElementById('media').src = url(media);
    await rafale();
    appliquer(NET);
    setTimeout(async function () {
      await rafale();
      appliquer(ETEINT);
      setTimeout(tour, PAUSE);
    }, DUREE);
```

Et au tout début de `tour()`, avant le tirage, éteindre le bloc :

```js
    appliquer(ETEINT);
```

- [ ] **Étape 3 : déployer et vérifier au navigateur**

```bash
docker compose build wally && docker compose up -d wally && sleep 25
```

Ouvrir `http://192.168.1.185:8080/overlay-rotation` et observer trois transitions.
Attendu : les bandes se décalent, les couleurs déraillent, le **cadre est pris
dans l'effet** (il se fait couper par les bandes), et deux transitions
consécutives ne sont pas identiques.

- [ ] **Étape 4 : commit**

```bash
git add bot/dashboard/static/overlay_rotation.html
git commit -m "feat(overlay): transition datamosh, saccades tirées au sort"
```

---

### Tâche 5 : les vidéos, avec son et jusqu'au bout

**Fichiers :**
- Modifier : `bot/dashboard/static/overlay_rotation.html`

**Interfaces :**
- Consomme : `url(media)`, `rafale()`, `appliquer()`.
- Produit : `jouerVideo(media): Promise<void>`, `precharger(media)` étendu aux
  vidéos.

- [ ] **Étape 1 : ajouter la balise vidéo**

Remplacer le corps du cadre dans le HTML :

```html
<div id="cadre">
  <img id="media" alt="">
  <video id="video" class="absent" playsinline></video>
</div>
```

La classe `absent` est posée **dès le HTML** : sans elle, la balise vidéo vide
occuperait le cadre au premier chargement, avant que le premier média ne prenne
la main.

Et dans le CSS, cacher celui des deux qui ne sert pas :

```css
  #cadre img.absent, #cadre video.absent { display: none; }
```

- [ ] **Étape 2 : précharger aussi les vidéos**

Remplacer `precharger()` par :

```js
  function precharger(media) {
    return new Promise((resolve, reject) => {
      if (media.genre === 'video') {
        const v = document.getElementById('video');
        v.onloadedmetadata = () => resolve();
        v.onerror = () => reject(new Error('vidéo illisible : ' + media.nom));
        v.src = url(media);
        v.load();
        return;
      }
      const img = new Image();
      img.onload = () => resolve(img);
      img.onerror = () => reject(new Error('média illisible : ' + media.nom));
      img.src = url(media);
    });
  }
```

- [ ] **Étape 3 : jouer la vidéo jusqu'au bout**

Ajouter :

```js
  /** Joue la vidéo et rend la main à la fin.
   *
   *  Trois façons de ne jamais rendre la main, trois parades :
   *  - le navigateur refuse la lecture audio automatique -> seconde tentative
   *    en muet, puis abandon ;
   *  - le fichier est tronqué et `ended` n'arrive jamais -> minuteur de secours ;
   *  - la lecture cale -> le même minuteur.
   *  Sans elles, la source resterait figée sur cette vidéo pour le reste du live.
   */
  function jouerVideo() {
    const v = document.getElementById('video');
    return new Promise(function (fini) {
      let rendu = false;
      const rendreLaMain = function () {
        if (rendu) return;
        rendu = true;
        clearTimeout(secours);
        v.onended = null;
        fini();
      };

      const limite = Number.isFinite(v.duration) && v.duration > 0
        ? (v.duration + 5) * 1000
        : 60000;
      const secours = setTimeout(rendreLaMain, limite);

      v.onended = rendreLaMain;
      v.muted = false;
      v.currentTime = 0;
      v.play().catch(function () {
        // Chrome bloque la lecture audio automatique tant qu'OBS n'a pas
        // autorisé la source. Muet vaut mieux que rien.
        v.muted = true;
        v.play().catch(rendreLaMain);
      });
    });
  }
```

- [ ] **Étape 4 : brancher dans le cycle**

Dans `tour()`, après le préchargement réussi, remplacer l'affichage par :

```js
    const img = document.getElementById('media');
    const video = document.getElementById('video');
    const estVideo = media.genre === 'video';
    img.classList.toggle('absent', estVideo);
    video.classList.toggle('absent', !estVideo);
    if (!estVideo) img.src = url(media);

    await rafale();
    appliquer(NET);

    if (estVideo) {
      await jouerVideo();
      await rafale();
      appliquer(ETEINT);
      setTimeout(tour, PAUSE);
    } else {
      setTimeout(async function () {
        await rafale();
        appliquer(ETEINT);
        setTimeout(tour, PAUSE);
      }, DUREE);
    }
```

- [ ] **Étape 5 : déployer et vérifier au navigateur**

```bash
docker compose build wally && docker compose up -d wally && sleep 25
```

Ouvrir `http://192.168.1.185:8080/overlay-rotation?duree=3&pause=1` (cadence
accélérée pour atteindre le `.mp4` plus vite) et attendre que `meme35.mp4` sorte.

Attendu : la vidéo joue **en entier**, puis la boucle repart. Le navigateur
coupera sans doute le son (c'est OBS qui l'autorise) — vérifier que ça ne
bloque rien.

- [ ] **Étape 6 : vérifier qu'une vidéo cassée ne fige pas la boucle**

```bash
head -c 2000 data/memes/meme35.mp4 > /tmp/casse.mp4
cp /tmp/casse.mp4 data/memes/zz-test-casse.mp4
```

Recharger la page, attendre que le fichier tronqué sorte.
Attendu : la boucle passe au suivant, elle ne s'arrête pas.

Puis nettoyer : `rm data/memes/zz-test-casse.mp4`

- [ ] **Étape 7 : commit**

```bash
git add bot/dashboard/static/overlay_rotation.html
git commit -m "feat(overlay): les vidéos du rotateur jouent jusqu'au bout"
```

---

### Tâche 6 : le chien de garde et la documentation OBS

**Fichiers :**
- Modifier : `bot/dashboard/static/overlay_rotation.html`
- Modifier : `docs/overlay.md`

**Interfaces :**
- Consomme : le cycle des tâches 3 à 5.
- Produit : `signeDeVie()`, appelée à chaque affichage et sur `timeupdate`.

- [ ] **Étape 1 : ajouter le chien de garde**

Dans le `<script>`, avant `charger().then(tour)` :

```js
  // Une source de live qui se fige ne le dit à personne : on ne s'en aperçoit
  // qu'en revoyant le VOD. Le gardien la relance tout seul.
  let derniereVie = Date.now();
  function signeDeVie() { derniereVie = Date.now(); }

  document.getElementById('video').addEventListener('timeupdate', signeDeVie);

  setInterval(function () {
    // Une vidéo longue est un signe de vie par ses `timeupdate` : sans cette
    // condition, le gardien couperait un média de deux minutes en plein milieu.
    if (Date.now() - derniereVie > 3 * (DUREE + PAUSE)) location.reload();
  }, 5000);
```

Et appeler `signeDeVie();` juste après `appliquer(NET);` dans `tour()`.

- [ ] **Étape 2 : vérifier le gardien**

Dans la console du navigateur, sur la page ouverte :

```js
// On simule un figeage en empêchant tout nouveau signe de vie.
signeDeVie = function () {};
```

Attendu : la page se recharge d'elle-même dans les `3 × (durée + pause)` secondes.

*(Si `signeDeVie` n'est pas accessible depuis la console parce que le script est
dans une fermeture, vérifier autrement : ouvrir la page avec `?duree=1&pause=1`,
couper le conteneur — `docker compose stop wally` — et constater que la page
tente de se recharger. La relancer ensuite.)*

- [ ] **Étape 3 : documenter la source dans `docs/overlay.md`**

Ajouter une section, après le tableau d'installation existant :

```markdown
## La source « rotateur de memes »

Un second overlay, indépendant de Wally : il fait défiler en boucle les médias
de `data/memes`, vidéos comprises. Wally n'y touche pas — il garde l'overlay
compagnon pour les memes qu'il commente.

| Réglage | Valeur |
|---|---|
| Source | Navigateur (`Browser Source`) |
| URL | `https://heywally.fr/overlay-rotation` |
| Largeur × hauteur | au goût — 800 × 600 reproduit l'ancien widget StreamElements |
| Fond | transparent |
| Contrôler l'audio via OBS | **coché**, sinon les vidéos restent muettes |

Réglages, dans l'URL : `duree` (9 s), `pause` (5 s), `ordre`
(`hasard` ou `dossier`), `saccade` (33 ms par état de glitch).
Exemple : `/overlay-rotation?duree=12&pause=3`

La taille et la position ne sont pas des paramètres : elles se règlent en
redimensionnant la source dans OBS.

Un média qui ne charge pas est écarté et le suivant prend sa place ; la page se
recharge d'elle-même si elle se fige. Elle ne dépend pas du bot une fois
chargée : un rebuild de Wally ne coupe pas la rotation.
```

- [ ] **Étape 4 : vérification complète avant de clore**

```bash
python3 -m pytest tests/test_memes.py tests/test_overlay_rotation.py tests/test_overlay_narrator.py tests/test_overlay_tool.py tests/test_dashboard_routes.py -q
python3 -m ruff check bot/core/memes.py bot/dashboard/routes/overlay.py bot/dashboard/app.py tests/test_overlay_rotation.py
python3 -m mypy bot/core/memes.py bot/dashboard/routes/overlay.py
python3 scripts/lint_silences.py
python3 scripts/lint_types.py
```

Attendu : tests verts, aucune nouvelle erreur de lint, cliquets au niveau ou en dessous.

- [ ] **Étape 5 : publier**

```bash
git add bot/dashboard/static/overlay_rotation.html docs/overlay.md
git commit -m "feat(overlay): chien de garde du rotateur + réglages OBS documentés"
git push public feat/site-redesign-arcade:main
docker compose build --build-arg GIT_HASH=$(git rev-parse --short HEAD) \
  --build-arg BUILD_DATE=$(date -u +%Y-%m-%dT%H:%M:%SZ) wally
docker compose up -d wally && sleep 25
curl -s -o /dev/null -w "%{http_code}\n" http://localhost:8080/overlay-rotation
docker logs wally-bot --since 2m 2>&1 | grep -icE "error|traceback"
```

Attendu : `200`, et `0` erreur dans les logs.

---

## Ce que ce plan ne couvre pas

- **Aucun contrôle par Wally** : pas de SSE, pas d'outil `show_rotation`. Si le
  besoin apparaît, il s'ajoutera par-dessus une page qui tourne déjà.
- **Aucun réglage en base ni dans le panneau admin** : l'URL suffit.
- **Aucune sélection de médias** : le pool est `data/memes` en entier.
- **Aucun test JavaScript automatisé** : le projet n'en a pas de harnais et on
  n'en invente pas un pour l'occasion. Les vérifications au navigateur des
  tâches 3 à 6 en tiennent lieu, et le critère est toujours le même — la boucle
  ne s'arrête jamais.
