# Ranger un meme depuis Discord — plan d'implémentation

> **Pour les agents :** SOUS-COMPÉTENCE REQUISE — utiliser `superpowers:subagent-driven-development`
> (recommandé) ou `superpowers:executing-plans` pour dérouler ce plan tâche par tâche. Les étapes
> sont cochables (`- [ ]`).

**But :** verser une image vue dans un salon Discord dans `data/memes/`, convertie en WebP si
l'échange est avantageux, avec une description écrite une fois pour toutes dans un `.txt`.

**Architecture :** un module `bot/core/meme_import.py` sans dépendance à Discord porte toute la
logique (conversion, numérotation, empreintes, écriture) ; la commande Discord et le script de
rattrapage n'en sont que deux appelants. La conversion WebP y est déplacée depuis
`scripts/convertir_memes_webp.py`, qui l'importe désormais — une seule garde anti-perte
d'animation, pas deux qui divergeraient.

**Pile :** Python 3.12, discord.py ≥ 2.7.1, Pillow, pytest.

**Spec :** `docs/plans/2026-08-12-meme-context-menu-design.md`

**Déjà livré :** le retrait de la légende sur l'overlay (`157df36`) — le widget ne reçoit plus que
`src`, la description ne sort plus à l'écran. Aucune tâche de ce plan n'y revient.

## Contraintes globales

- Journalisation par `loguru` uniquement — jamais `print()` ni `import logging`. Les scripts de
  `scripts/` sont l'exception : ils s'adressent à un humain sur un terminal et utilisent `print()`.
- Tout le code du bot est asynchrone ; le travail bloquant (Pillow, hachage, disque) passe par
  `asyncio.to_thread()`.
- `bot/core/meme_import.py` ne doit importer ni `discord` ni rien de `bot/discord/`.
- Extensions affichables : `.png .jpg .jpeg .gif .webp`. Servies mais non affichées : `.mp4 .webm`.
  Ces listes vivent dans `bot/core/memes.py` (`_EXTENSIONS`, `_EXTENSIONS_MEDIA`) — les importer,
  jamais les recopier.
- Plafond d'affichage : `bot.core.memes._MAX_BYTES` (8 Mo). Plafond de téléchargement : 16 Mo.
- Un test ne doit jamais affirmer une ligne de code source : `tests/test_garde_fous_qualite.py`
  le refuse. Tester le comportement.
- Vérification avant de déclarer une tâche finie : `python3 -m pytest tests/ -q` et
  `python3 scripts/lint_types.py` (cliquet à 360 erreurs, il ne doit pas monter).

---

### Tâche 1 : Déplacer la conversion WebP dans un module partagé

Refactor pur, aucun changement de comportement. Il vient en premier parce que tout le reste s'appuie
dessus.

**Fichiers :**
- Créer : `bot/core/meme_import.py`
- Modifier : `scripts/convertir_memes_webp.py` (retirer les fonctions déplacées, les importer)
- Créer : `tests/test_meme_import.py`

**Interfaces produites :**
- `A_CONVERTIR: frozenset[str]` — `{".gif", ".png"}`
- `durees_gif(im: Image.Image) -> list[int]`
- `durees_webp(path: Path) -> list[int]`
- `convertir(src: Path, dst: Path) -> None`
- `verifier_conversion(src: Path, dst: Path) -> str` — raison du refus, `""` si fidèle
- `sidecar_de(path: Path) -> Path | None`

- [ ] **Étape 1 : écrire le test qui prouve que l'animation survit**

`tests/test_meme_import.py` :

```python
# tests/test_meme_import.py
"""Le module partagé d'import de memes.

La conversion vit ici et non plus dans `scripts/convertir_memes_webp.py` :
deux gardes anti-perte d'animation qui divergent, c'est un GIF aplati en
silence — Pillow le fait sur un fichier sur trois, avec 99 % de gain qui
ressemble à une réussite.
"""
from pathlib import Path

from PIL import Image

from bot.core import meme_import


def _gif_anime(chemin: Path, frames: int = 4, duree: int = 80) -> Path:
    images = []
    for i in range(frames):
        im = Image.new("RGB", (32, 32), (i * 60 % 255, 40, 200))
        images.append(im)
    images[0].save(chemin, "GIF", save_all=True, append_images=images[1:],
                   duration=duree, loop=0)
    return chemin


def test_un_gif_anime_reste_anime(tmp_path):
    src = _gif_anime(tmp_path / "danse.gif")
    dst = tmp_path / "danse.webp"

    meme_import.convertir(src, dst)

    assert meme_import.verifier_conversion(src, dst) == ""
    assert getattr(Image.open(dst), "n_frames", 1) == 4
    assert sum(meme_import.durees_webp(dst)) == 4 * 80


def test_une_conversion_qui_perd_l_animation_est_refusee(tmp_path):
    src = _gif_anime(tmp_path / "danse.gif")
    dst = tmp_path / "aplati.webp"
    Image.open(src).convert("RGB").save(dst, "WEBP")  # une seule frame

    assert "animation perdue" in meme_import.verifier_conversion(src, dst)


def test_le_sidecar_colle_a_l_extension_est_retrouve(tmp_path):
    image = tmp_path / "meme1.webp"
    image.write_bytes(b"x")
    (tmp_path / "meme1.webp.txt").write_text("un chat", encoding="utf-8")

    assert meme_import.sidecar_de(image).name == "meme1.webp.txt"
    assert meme_import.sidecar_de(tmp_path / "meme2.webp") is None
```

- [ ] **Étape 2 : lancer le test, vérifier qu'il échoue**

Commande : `python3 -m pytest tests/test_meme_import.py -q`
Attendu : `ModuleNotFoundError: No module named 'bot.core.meme_import'`

- [ ] **Étape 3 : créer le module en déplaçant le code existant**

Créer `bot/core/meme_import.py` avec, copiés **sans modification de corps** depuis
`scripts/convertir_memes_webp.py` (lignes 38-124), les éléments renommés en public :

- `_A_CONVERTIR` → `A_CONVERTIR` (en `frozenset`)
- `_QUALITE_ANIMEE` → `QUALITE_ANIMEE`
- `_durees_gif` → `durees_gif`
- `_durees_webp` → `durees_webp`
- `_convertir` → `convertir`
- `_verifier` → `verifier_conversion`
- `_sidecar` → `sidecar_de`

Conserver mot pour mot les docstrings et commentaires : ils expliquent des pièges (la comparaison
sur la durée totale plutôt que frame à frame, les chunks ANMF que Pillow ne relit pas, l'aplatissage
des frames une à une). En-tête du module :

```python
# bot/core/meme_import.py
"""Faire entrer une image dans la banque de memes.

Toute la logique d'import vit ici, hors de Discord : la commande contextuelle et
`scripts/rattraper_memes.py` n'en sont que deux appelants, et le module se teste
sans réseau ni bot.

La conversion WebP y a été déplacée depuis `scripts/convertir_memes_webp.py`,
qui l'importe désormais. Le piège qu'elle existe pour éviter : convertir un GIF
animé « à la Pillow » perd l'animation sur un fichier sur trois — la sortie ne
garde qu'une frame et pèse 99 % de moins, ce qui ressemble à s'y méprendre à une
réussite. Deux copies de cette garde finiraient par diverger.
"""
from __future__ import annotations

import struct
from pathlib import Path

from PIL import Image, ImageSequence

from bot.core.memes import _MAX_BYTES

A_CONVERTIR = frozenset({".gif", ".png"})

# Une animation supporte le lossy sans qu'on le voie — c'est ce qui donne les
# 70 % de gain. Une image fixe de meme, c'est d'abord du texte : sans perte.
QUALITE_ANIMEE = 80
```

- [ ] **Étape 4 : lancer le test, vérifier qu'il passe**

Commande : `python3 -m pytest tests/test_meme_import.py -q`
Attendu : 3 tests au vert.

- [ ] **Étape 5 : faire pointer le script sur le module**

Dans `scripts/convertir_memes_webp.py`, remplacer les définitions (lignes 38-124) par un import, et
adapter les appels de `main()` (`_convertir` → `convertir`, `_verifier` → `verifier_conversion`,
`_sidecar` → `sidecar_de`, `_A_CONVERTIR` → `A_CONVERTIR`) :

```python
# Les fonctions vivaient ici ; elles sont désormais partagées avec la commande
# Discord qui range un meme. Une seule garde anti-perte d'animation.
from bot.core.meme_import import (
    A_CONVERTIR,
    convertir,
    sidecar_de,
    verifier_conversion,
)
```

Retirer les imports devenus inutiles : `struct`, `Image`, `ImageSequence`, `_MAX_BYTES`.

- [ ] **Étape 6 : vérifier que le script marche toujours, en simulation**

Commande : `python3 scripts/convertir_memes_webp.py`
Attendu : la liste des quatre fichiers convertibles (`meme77.png`, `meme78.png`, `meme79.png`,
`meme80.gif`), puis « Simulation — rien n'a été écrit. » Aucun fichier modifié : vérifier avec
`git status --short data/memes` qui doit rester vide.

- [ ] **Étape 7 : ajouter le test qui interdit la duplication**

Dans `tests/test_meme_import.py` :

```python
def test_le_script_de_conversion_ne_redefinit_pas_la_garde():
    """Le script partage l'objet, il n'en a pas une copie.

    Une identité d'objet, pas une lecture du source : le cliquet
    `test_aucun_test_ne_fige_une_ligne_de_code_source` refuse la seconde.
    """
    import importlib.util
    from pathlib import Path

    chemin = Path(__file__).resolve().parents[1] / "scripts" / "convertir_memes_webp.py"
    spec = importlib.util.spec_from_file_location("convertir_memes_webp", chemin)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    assert module.convertir is meme_import.convertir
    assert module.verifier_conversion is meme_import.verifier_conversion
```

- [ ] **Étape 8 : lancer la suite complète**

Commandes :
```bash
python3 -m pytest tests/ -q
python3 scripts/lint_types.py
```
Attendu : tout au vert, cliquet à 360 au plus.

- [ ] **Étape 9 : commit**

```bash
git add bot/core/meme_import.py scripts/convertir_memes_webp.py tests/test_meme_import.py
git commit -m "refactor(memes): la conversion WebP passe dans un module partagé

La commande Discord qui range un meme va s'en servir. Deux gardes
anti-perte d'animation qui divergent, c'est un GIF aplati en silence."
```

---

### Tâche 2 : La logique d'import — numérotation, empreintes, écriture

**Fichiers :**
- Modifier : `bot/core/meme_import.py`
- Modifier : `tests/test_meme_import.py`

**Interfaces consommées :** `convertir`, `verifier_conversion`, `A_CONVERTIR` (tâche 1).

**Interfaces produites :**
- `ResultatImport` — dataclass : `ok: bool`, `nom: str`, `raison: str`, `doublon: str`,
  `converti: bool`, `octets: int`
- `prochain_numero(dossier: Path) -> int`
- `empreintes(dossier: Path) -> dict[str, str]` — SHA-256 hexadécimal → nom de fichier
- `convertir_si_avantageux(octets: bytes, suffixe: str) -> tuple[bytes, str]` — rend
  `(octets, suffixe)` inchangés si la conversion n'apporte rien
- `importer(octets: bytes, suffixe: str, description: str, dossier: Path) -> ResultatImport`

- [ ] **Étape 1 : écrire les tests de la numérotation et des empreintes**

Ajouter à `tests/test_meme_import.py` :

```python
def test_le_prochain_numero_suit_le_maximum(tmp_path):
    for nom in ("meme3.webp", "meme7.jpg", "meme7.jpg.txt"):
        (tmp_path / nom).write_bytes(b"x")

    assert meme_import.prochain_numero(tmp_path) == 8


def test_un_sidecar_orphelin_reserve_son_numero(tmp_path):
    """Sinon le numéro est réattribué et l'ancien .txt décrit une autre image."""
    (tmp_path / "meme4.webp").write_bytes(b"x")
    (tmp_path / "meme9.webp.txt").write_text("image supprimée", encoding="utf-8")

    assert meme_import.prochain_numero(tmp_path) == 10


def test_un_dossier_vide_commence_a_un(tmp_path):
    assert meme_import.prochain_numero(tmp_path) == 1


def test_les_empreintes_indexent_les_fichiers_presents(tmp_path):
    (tmp_path / "meme1.webp").write_bytes(b"contenu")
    (tmp_path / "meme1.webp.txt").write_text("desc", encoding="utf-8")

    index = meme_import.empreintes(tmp_path)

    import hashlib
    assert index[hashlib.sha256(b"contenu").hexdigest()] == "meme1.webp"
    assert len(index) == 1  # le .txt n'est pas un meme
```

- [ ] **Étape 2 : lancer, vérifier l'échec**

Commande : `python3 -m pytest tests/test_meme_import.py -q -k "numero or empreintes"`
Attendu : `AttributeError: module 'bot.core.meme_import' has no attribute 'prochain_numero'`

- [ ] **Étape 3 : implémenter**

```python
import hashlib
import re

from bot.core.memes import _EXTENSIONS, _EXTENSIONS_MEDIA

_NUMERO = re.compile(r"^meme(\d+)\.", re.IGNORECASE)


def prochain_numero(dossier: Path) -> int:
    """Le maximum trouvé plus un — jamais le premier trou.

    Les sidecars comptent : un `meme9.webp.txt` resté seul réserve le 9, sinon
    le numéro est réattribué et cette vieille description se retrouve collée à
    une image qui n'a rien à voir.
    """
    numeros = [
        int(m.group(1))
        for p in dossier.iterdir()
        if p.is_file() and (m := _NUMERO.match(p.name))
    ]
    return max(numeros, default=0) + 1


def empreintes(dossier: Path) -> dict[str, str]:
    """SHA-256 → nom, pour les médias du dossier. Les `.txt` sont ignorés."""
    index: dict[str, str] = {}
    for p in sorted(dossier.iterdir()):
        if not p.is_file() or p.suffix.lower() not in _EXTENSIONS_MEDIA:
            continue
        index.setdefault(hashlib.sha256(p.read_bytes()).hexdigest(), p.name)
    return index
```

- [ ] **Étape 4 : lancer, vérifier le vert**

Commande : `python3 -m pytest tests/test_meme_import.py -q -k "numero or empreintes"`
Attendu : 4 tests au vert.

- [ ] **Étape 5 : écrire les tests de `convertir_si_avantageux` et `importer`**

```python
def test_un_png_est_converti_quand_il_y_gagne(tmp_path):
    src = tmp_path / "gros.png"
    Image.new("RGB", (400, 400), (200, 30, 30)).save(src, "PNG")

    octets, suffixe = meme_import.convertir_si_avantageux(src.read_bytes(), ".png")

    assert suffixe == ".webp"
    assert len(octets) < src.stat().st_size


def test_un_jpeg_n_est_jamais_converti(tmp_path):
    src = tmp_path / "photo.jpg"
    Image.new("RGB", (200, 200), (10, 10, 10)).save(src, "JPEG")
    original = src.read_bytes()

    octets, suffixe = meme_import.convertir_si_avantageux(original, ".jpg")

    assert (octets, suffixe) == (original, ".jpg")


def test_l_import_ecrit_l_image_et_son_sidecar(tmp_path):
    src = tmp_path / "src.png"
    Image.new("RGB", (120, 120), (0, 120, 255)).save(src, "PNG")

    res = meme_import.importer(src.read_bytes(), ".png", "un carré bleu", tmp_path)

    assert res.ok is True
    assert res.nom == "meme1.webp"
    assert res.converti is True
    assert (tmp_path / "meme1.webp").is_file()
    assert (tmp_path / "meme1.webp.txt").read_text(encoding="utf-8") == "un carré bleu"


def test_un_doublon_n_est_pas_range_deux_fois(tmp_path):
    src = tmp_path / "src.png"
    Image.new("RGB", (120, 120), (0, 120, 255)).save(src, "PNG")
    octets = src.read_bytes()
    src.unlink()
    premier = meme_import.importer(octets, ".png", "un carré bleu", tmp_path)

    second = meme_import.importer(octets, ".png", "le même", tmp_path)

    assert second.ok is False
    assert second.doublon == premier.nom
    assert not (tmp_path / "meme2.webp").exists()
    assert not (tmp_path / "meme2.webp.txt").exists()


def test_un_fichier_trop_lourd_est_refuse(tmp_path):
    from bot.core.memes import _MAX_BYTES

    res = meme_import.importer(b"\x00" * (_MAX_BYTES + 1), ".jpg", "trop gros", tmp_path)

    assert res.ok is False
    assert "8" in res.raison  # le plafond figure dans le message
    assert list(tmp_path.iterdir()) == []


def test_une_extension_inconnue_est_refusee(tmp_path):
    res = meme_import.importer(b"MZ", ".exe", "non merci", tmp_path)

    assert res.ok is False
    assert ".exe" in res.raison


def test_une_video_est_acceptee_sans_conversion(tmp_path):
    res = meme_import.importer(b"\x00\x00\x00\x18ftypmp42", ".mp4", "un clip", tmp_path)

    assert res.ok is True
    assert res.nom == "meme1.mp4"
    assert res.converti is False


def test_une_description_vide_n_ecrit_pas_de_sidecar(tmp_path):
    """Sans description, `_describe` retombe sur le nom du fichier — un sidecar
    vide ferait pire, en donnant une description vraiment vide."""
    res = meme_import.importer(b"\x00\x00\x00\x18ftypmp42", ".mp4", "   ", tmp_path)

    assert res.ok is True
    assert not (tmp_path / "meme1.mp4.txt").exists()
```

- [ ] **Étape 6 : lancer, vérifier l'échec**

Commande : `python3 -m pytest tests/test_meme_import.py -q -k "import or converti or jpeg"`
Attendu : échec sur `convertir_si_avantageux` absent.

- [ ] **Étape 7 : implémenter**

```python
import tempfile
from dataclasses import dataclass

# Au-delà, on n'essaie même pas de convertir : le fichier ne pourra de toute
# façon pas descendre sous le plafond d'affichage.
MAX_TELECHARGEMENT = 16 * 1024 * 1024


@dataclass
class ResultatImport:
    """Ce qu'il est advenu d'une tentative d'import."""

    ok: bool
    nom: str = ""
    raison: str = ""
    doublon: str = ""
    converti: bool = False
    octets: int = 0


def convertir_si_avantageux(octets: bytes, suffixe: str) -> tuple[bytes, str]:
    """Rend `(octets, suffixe)` en WebP si l'échange fait gagner, tels quels sinon.

    Passe par des fichiers temporaires plutôt que de travailler en mémoire : la
    vérification relit le WebP écrit pour compter ses frames et lire leurs
    durées dans les chunks ANMF. La réécrire sur des octets, c'est reprendre une
    garde éprouvée pour rien.
    """
    if suffixe.lower() not in A_CONVERTIR:
        return octets, suffixe
    with tempfile.TemporaryDirectory() as tmp:
        src = Path(tmp) / f"src{suffixe}"
        dst = Path(tmp) / "dst.webp"
        src.write_bytes(octets)
        try:
            convertir(src, dst)
            if verifier_conversion(src, dst):
                return octets, suffixe
        except Exception:  # noqa: BLE001 — un format exotique ne fait pas échouer l'import
            return octets, suffixe
        return dst.read_bytes(), ".webp"


def importer(
    octets: bytes, suffixe: str, description: str, dossier: Path
) -> ResultatImport:
    """Range une image dans la banque. N'écrit rien si elle est refusée."""
    suffixe = suffixe.lower()
    if suffixe not in _EXTENSIONS_MEDIA:
        admis = " ".join(sorted(_EXTENSIONS_MEDIA))
        return ResultatImport(False, raison=f"format {suffixe} non admis — attendus : {admis}")
    if len(octets) > MAX_TELECHARGEMENT:
        return ResultatImport(
            False, raison=f"{len(octets) / 1e6:.1f} Mo — au-delà de la limite de téléchargement"
        )

    index = empreintes(dossier)
    depuis = index.get(hashlib.sha256(octets).hexdigest())
    if depuis:
        return ResultatImport(False, doublon=depuis, raison="déjà rangé")

    finaux, suffixe_final = convertir_si_avantageux(octets, suffixe)
    converti = suffixe_final != suffixe
    if converti:
        depuis = index.get(hashlib.sha256(finaux).hexdigest())
        if depuis:
            return ResultatImport(False, doublon=depuis, raison="déjà rangé")

    # Le plafond ne s'applique qu'à ce qui doit s'AFFICHER : une vidéo n'est
    # jamais tirée par `list()`, la borner sur ce critère n'aurait pas de sens.
    if suffixe_final in _EXTENSIONS and len(finaux) > _MAX_BYTES:
        return ResultatImport(
            False,
            raison=(
                f"{len(finaux) / 1e6:.1f} Mo après conversion, au-dessus du plafond de "
                f"{_MAX_BYTES / 1e6:.0f} Mo — il serait rangé puis jamais tiré"
            ),
        )

    nom = f"meme{prochain_numero(dossier)}{suffixe_final}"
    (dossier / nom).write_bytes(finaux)
    if description.strip():
        (dossier / f"{nom}.txt").write_text(description.strip(), encoding="utf-8")
    return ResultatImport(True, nom=nom, converti=converti, octets=len(finaux))
```

- [ ] **Étape 8 : lancer les tests du module**

Commande : `python3 -m pytest tests/test_meme_import.py -q`
Attendu : 15 tests au vert.

- [ ] **Étape 9 : suite complète et types**

Commandes :
```bash
python3 -m pytest tests/ -q
python3 scripts/lint_types.py
```

- [ ] **Étape 10 : commit**

```bash
git add bot/core/meme_import.py tests/test_meme_import.py
git commit -m "feat(memes): la logique d'import, hors de Discord

Numérotation qui suit le maximum (un sidecar orphelin réserve son
numéro), doublons par empreinte SHA-256 sans index à maintenir, refus
motivé au-dessus du plafond d'affichage."
```

---

### Tâche 3 : Un registre de description dédié aux memes

**Fichiers :**
- Modifier : `bot/core/vision.py` (paramètre `prompt_name` sur `analyze`)
- Créer : `bot/persona/prompts/meme_describe_system.md`
- Modifier : `tests/test_vision.py`

**Interfaces produites :**
- `VisionService.analyze(image_urls, caption="", purpose="image_analysis", prompt_name="image_analyze_system") -> str | None`

- [ ] **Étape 1 : écrire le test**

Ajouter à `tests/test_vision.py` :

```python
@pytest.mark.asyncio
async def test_analyze_accepte_un_registre_dedie(monkeypatch):
    """Décrire un meme n'est pas commenter une capture d'écran de partie.

    Le registre par défaut consacre un bloc entier à l'extraction de stats de
    jeu : appliqué à un meme, il produit une fiche au lieu d'une phrase.
    """
    vus = []
    monkeypatch.setattr(
        "bot.core.vision.load_prompt",
        lambda nom, defaut="": vus.append(nom) or f"registre {nom}",
    )
    client = _FauxClient(reponse="un chat à lunettes")
    svc = VisionService(client)

    await svc.analyze(["data:image/png;base64,AAA"], prompt_name="meme_describe_system")

    assert vus == ["meme_describe_system"]
    assert client.dernier_system == "registre meme_describe_system"
```

Si `_FauxClient` n'existe pas dans le fichier, l'ajouter en s'alignant sur le double déjà utilisé
par les tests voisins ; il doit mémoriser le `system_prompt` reçu dans `dernier_system`.

- [ ] **Étape 2 : lancer, vérifier l'échec**

Commande : `python3 -m pytest tests/test_vision.py -q -k registre`
Attendu : `TypeError: analyze() got an unexpected keyword argument 'prompt_name'`

- [ ] **Étape 3 : implémenter**

Dans `bot/core/vision.py`, ajouter le paramètre et s'en servir :

```python
    async def analyze(
        self,
        image_urls: Iterable[str] | None,
        caption: str = "",
        purpose: str = "image_analysis",
        prompt_name: str = "image_analyze_system",
    ) -> str | None:
```

et remplacer le chargement en dur :

```python
        # Le registre est un paramètre : décrire un meme pour la banque et
        # commenter une image du chat ne demandent pas la même sortie.
        system = load_prompt(prompt_name, _DEFAULT_PROMPT)
```

- [ ] **Étape 4 : lancer, vérifier le vert**

Commande : `python3 -m pytest tests/test_vision.py -q`

- [ ] **Étape 5 : écrire le registre**

`bot/persona/prompts/meme_describe_system.md` :

```markdown
Tu décris un MEME pour la banque d'images de {{BOT_NAME}}.

Ta phrase sera enregistrée à côté de l'image et relue plus tard : c'est la seule prise que
{{BOT_NAME}} aura dessus au moment de la montrer, puisqu'il ne la verra pas. Elle sert à la
retrouver par mot-clé et à la commenter juste. Elle n'est jamais affichée aux spectateurs.

## Ce que tu écris
Une à deux phrases, en français, sur une seule ligne. Dans cet ordre :

1. Le format ou le modèle du meme s'il est reconnaissable (« Format bébé sceptique », « BD 4
   cases », « Drake qui refuse puis approuve »).
2. Ce qu'on voit : sujet, action, expression, décor. Bref et concret.
3. Le texte visible, recopié entre guillemets, tel qu'il est écrit.
4. Un ou deux mots de contexte s'ils sautent aux yeux : le jeu, la personne visée, le thème.

## Règles
- N'invente rien. Un texte illisible se signale (« légende illisible »), il ne se devine pas.
- Pas de préambule, pas de « cette image montre », pas de conclusion. La description seule.
- Ne juge pas si le meme est drôle, ne l'explique pas.
- Si des pseudos apparaissent, recopie-les tels quels.

## Exemples de la forme attendue
BD 4 cases : EA offre un tour de montgolfière gratuit, le ballon s'envole, pancarte l'atterrissage est 19.99$. Microtransactions, arnaque, payant.

Format bébé sceptique : nourrisson qui roule des yeux, moue dubitative, pas convaincu. Texte : « AZRAEL : FUSE AURAIT BIEN BESOIN D'UN BUFF... » Apex
```

- [ ] **Étape 6 : vérifier le registre sur une vraie image**

Commande :
```bash
python3 -c "
import asyncio, base64, sys; sys.path.insert(0,'.')
from dotenv import load_dotenv; load_dotenv()
from bot.core.llm.openai_client import OpenAILLMClient
from bot.core.vision import VisionService
class Db:
    async def log_cost(self, **k): pass
async def main():
    url='data:image/png;base64,'+base64.b64encode(open('data/memes/meme77.png','rb').read()).decode()
    svc=VisionService(OpenAILLMClient(model='gpt-5-nano', db=Db(), max_tokens=400))
    print(await svc.analyze([url], prompt_name='meme_describe_system'))
asyncio.run(main())"
```
Attendu : une à deux phrases dans le style des sidecars existants, sans préambule. Si la sortie
reste bavarde ou commence par « Cette image montre », resserrer le registre et relancer — il est
bind-monté, aucun rebuild nécessaire.

- [ ] **Étape 7 : suite complète, types, commit**

```bash
python3 -m pytest tests/ -q && python3 scripts/lint_types.py
git add bot/core/vision.py bot/persona/prompts/meme_describe_system.md tests/test_vision.py
git commit -m "feat(memes): un registre de description dédié à la banque

Le registre de vision par défaut vise le commentaire d'une image de chat
et consacre un bloc à l'extraction de stats de jeu. Celui-ci produit la
ligne dense des sidecars : format, ce qu'on voit, le texte cité."
```

---

### Tâche 4 : La commande contextuelle Discord

**Fichiers :**
- Créer : `bot/discord/commands/meme_cmd.py`
- Modifier : `bot/discord/bot.py` (enregistrement du cog, à côté des `add_cog` existants)
- Créer : `tests/test_meme_cmd.py`
- Modifier : `data/memes/LISEZ-MOI.md` (la nouvelle voie d'entrée)

**Interfaces consommées :** `meme_import.importer`, `meme_import.ResultatImport`,
`VisionService.analyze(..., prompt_name=...)`.

**Interfaces produites :**
- `MemeCog(bot)` — cog portant la commande
- `image_du_message(message) -> tuple[str, str] | None` — `(url, suffixe)` ou `None`

- [ ] **Étape 1 : écrire le test de l'extraction d'image**

`tests/test_meme_cmd.py` :

```python
# tests/test_meme_cmd.py
"""La commande contextuelle qui range un meme."""
from unittest.mock import AsyncMock, MagicMock

import pytest

from bot.discord.commands.meme_cmd import MemeCog, image_du_message


def _piece_jointe(url="https://cdn.discordapp.com/a/chat.png", content_type="image/png"):
    a = MagicMock()
    a.url = url
    a.content_type = content_type
    return a


def _message(attachments=(), embeds=()):
    m = MagicMock()
    m.attachments = list(attachments)
    m.embeds = list(embeds)
    return m


def test_la_piece_jointe_est_prioritaire():
    embed = MagicMock()
    embed.image.url = "https://tenor.com/x.gif"
    assert image_du_message(_message([_piece_jointe()], [embed])) == (
        "https://cdn.discordapp.com/a/chat.png", ".png",
    )


def test_l_image_d_un_embed_sert_de_repli():
    embed = MagicMock()
    embed.image.url = "https://media.tenor.com/abc.gif"
    embed.thumbnail.url = None
    assert image_du_message(_message([], [embed])) == (
        "https://media.tenor.com/abc.gif", ".gif",
    )


def test_un_message_sans_image_ne_donne_rien():
    assert image_du_message(_message()) is None


def test_une_piece_jointe_non_image_est_ignoree():
    doc = _piece_jointe(url="https://cdn.discordapp.com/a/notes.pdf",
                        content_type="application/pdf")
    assert image_du_message(_message([doc])) is None
```

- [ ] **Étape 2 : lancer, vérifier l'échec**

Commande : `python3 -m pytest tests/test_meme_cmd.py -q`
Attendu : `ModuleNotFoundError: No module named 'bot.discord.commands.meme_cmd'`

- [ ] **Étape 3 : implémenter l'extraction**

Créer `bot/discord/commands/meme_cmd.py` :

```python
# bot/discord/commands/meme_cmd.py
"""« Ranger ce meme » — clic droit sur un message, menu Applications.

Discord impose qu'un formulaire soit la PREMIÈRE réponse à une interaction, sous
trois secondes, et interdit de faire patienter avant. Décrire une image en prend
cinq à dix : un formulaire déjà rempli par la description est donc impossible.
D'où le passage par un aperçu à boutons, où « Corriger » ouvre le formulaire —
un clic de plus, mais la description est relue avant d'être écrite.
"""
from __future__ import annotations

import asyncio
from pathlib import Path
from urllib.parse import urlparse

import discord
from discord import app_commands
from discord.ext import commands
from loguru import logger

from bot.core import meme_import
from bot.core.memes import _EXTENSIONS, _EXTENSIONS_MEDIA

DOSSIER_MEMES = Path("data/memes")

# Ce que l'aperçu laisse le temps de décider avant de se figer.
DELAI_APERCU = 120.0


def image_du_message(message) -> tuple[str, str] | None:
    """`(url, suffixe)` de la première image du message, ou None.

    Les pièces jointes d'abord ; à défaut l'image d'un embed, ce qui rattrape
    les liens Tenor ou Klipy postés sans fichier.
    """
    for a in message.attachments:
        if a.content_type and a.content_type.startswith(("image/", "video/")):
            suffixe = Path(urlparse(a.url).path).suffix.lower()
            if suffixe:
                return a.url, suffixe
    for embed in message.embeds:
        for source in (getattr(embed, "image", None), getattr(embed, "thumbnail", None)):
            url = getattr(source, "url", None)
            if not url:
                continue
            suffixe = Path(urlparse(url).path).suffix.lower()
            if suffixe in _EXTENSIONS_MEDIA:
                return url, suffixe
    return None
```

- [ ] **Étape 4 : lancer, vérifier le vert**

Commande : `python3 -m pytest tests/test_meme_cmd.py -q`
Attendu : 4 tests au vert.

- [ ] **Étape 5 : écrire le test du parcours complet**

Ajouter à `tests/test_meme_cmd.py` :

```python
def _bot(tmp_path):
    bot = MagicMock()
    bot.tree.add_command = MagicMock()
    bot.vision.available = True
    bot.vision.analyze = AsyncMock(return_value="Chat à lunettes. Texte : « QUAND TU ATTENDS ».")
    return bot


def _interaction():
    i = MagicMock()
    i.user.id = 42
    i.user.display_name = "Testeur"
    i.response.defer = AsyncMock()
    i.response.send_message = AsyncMock()
    i.response.send_modal = AsyncMock()
    i.followup.send = AsyncMock()
    i.channel.send = AsyncMock()
    return i


@pytest.mark.asyncio
async def test_l_apercu_propose_la_description_sans_rien_ecrire(tmp_path, monkeypatch):
    monkeypatch.setattr("bot.discord.commands.meme_cmd.DOSSIER_MEMES", tmp_path)
    monkeypatch.setattr(
        "bot.discord.commands.meme_cmd.telecharger",
        AsyncMock(return_value=b"\x89PNG\r\n\x1a\n"),
    )
    cog = MemeCog(_bot(tmp_path))
    interaction = _interaction()

    await cog.ranger(interaction, _message([_piece_jointe()]))

    envoi = interaction.followup.send.call_args
    assert "Chat à lunettes" in envoi.kwargs["content"]
    assert list(tmp_path.iterdir()) == []  # rien n'est écrit avant validation


@pytest.mark.asyncio
async def test_un_message_sans_image_est_refuse(tmp_path, monkeypatch):
    monkeypatch.setattr("bot.discord.commands.meme_cmd.DOSSIER_MEMES", tmp_path)
    cog = MemeCog(_bot(tmp_path))
    interaction = _interaction()

    await cog.ranger(interaction, _message())

    assert "image" in interaction.followup.send.call_args.kwargs["content"].lower()
    assert list(tmp_path.iterdir()) == []


@pytest.mark.asyncio
async def test_un_doublon_nomme_le_fichier_deja_range(tmp_path, monkeypatch):
    from PIL import Image

    Image.new("RGB", (60, 60), (9, 9, 9)).save(tmp_path / "meme1.webp", "WEBP")
    octets = (tmp_path / "meme1.webp").read_bytes()
    monkeypatch.setattr("bot.discord.commands.meme_cmd.DOSSIER_MEMES", tmp_path)
    monkeypatch.setattr(
        "bot.discord.commands.meme_cmd.telecharger", AsyncMock(return_value=octets)
    )
    cog = MemeCog(_bot(tmp_path))
    interaction = _interaction()

    await cog.ranger(interaction, _message([_piece_jointe(url="https://cdn/x.webp",
                                                          content_type="image/webp")]))

    assert "meme1.webp" in interaction.followup.send.call_args.kwargs["content"]
    assert not (tmp_path / "meme2.webp").exists()
```

- [ ] **Étape 6 : lancer, vérifier l'échec**

Commande : `python3 -m pytest tests/test_meme_cmd.py -q -k "apercu or refuse or doublon"`
Attendu : échec, `MemeCog` n'existe pas encore.

- [ ] **Étape 7 : implémenter le cog, l'aperçu et le formulaire**

Ajouter à `bot/discord/commands/meme_cmd.py` :

```python
import aiohttp


async def telecharger(url: str, limite: int = meme_import.MAX_TELECHARGEMENT) -> bytes:
    """Rapatrie l'image. Coupe net au-delà de la limite plutôt que de tout avaler."""
    async with aiohttp.ClientSession() as session:
        async with session.get(url) as reponse:
            reponse.raise_for_status()
            morceaux: list[bytes] = []
            total = 0
            async for bloc in reponse.content.iter_chunked(64 * 1024):
                total += len(bloc)
                if total > limite:
                    raise ValueError(f"fichier au-delà de {limite / 1e6:.0f} Mo")
                morceaux.append(bloc)
    return b"".join(morceaux)


class FormulaireDescription(discord.ui.Modal, title="Description du meme"):
    """Le texte qui servira de vision à Wally — jamais affiché aux spectateurs."""

    def __init__(self, vue: "VueRangement") -> None:
        super().__init__()
        self._vue = vue
        self.description = discord.ui.TextInput(
            label="Ce que Wally doit savoir de l'image",
            style=discord.TextStyle.paragraph,
            default=vue.description,
            required=False,
            max_length=400,
        )
        self.add_item(self.description)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        self._vue.description = str(self.description.value).strip()
        await self._vue.ranger(interaction)


class VueRangement(discord.ui.View):
    """Aperçu avant écriture : ranger tel quel, corriger, ou renoncer."""

    def __init__(self, auteur_id: int, octets: bytes, suffixe: str, description: str,
                 salon) -> None:
        super().__init__(timeout=DELAI_APERCU)
        self.auteur_id = auteur_id
        self.octets = octets
        self.suffixe = suffixe
        self.description = description
        self.salon = salon

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.auteur_id:
            await interaction.response.send_message(
                "Ce rangement n'est pas le tien.", ephemeral=True
            )
            return False
        return True

    async def ranger(self, interaction: discord.Interaction) -> None:
        resultat = await asyncio.to_thread(
            meme_import.importer, self.octets, self.suffixe, self.description, DOSSIER_MEMES
        )
        if not resultat.ok:
            message = (f"Déjà rangé sous **{resultat.doublon}**." if resultat.doublon
                       else f"Pas rangé : {resultat.raison}")
            await interaction.response.edit_message(content=message, view=None)
            return

        poids = f"{resultat.octets / 1024:.0f} Ko"
        converti = " (converti en WebP)" if resultat.converti else ""
        await interaction.response.edit_message(
            content=f"Rangé sous **{resultat.nom}**{converti}, {poids}.", view=None
        )
        logger.info("Meme rangé : {n} par {u}", n=resultat.nom, u=interaction.user.display_name)
        await self.salon.send(
            f"📥 **{interaction.user.display_name}** a rangé un meme — `{resultat.nom}`",
            file=discord.File(DOSSIER_MEMES / resultat.nom),
        )
        self.stop()

    @discord.ui.button(label="Ranger", style=discord.ButtonStyle.success)
    async def bouton_ranger(self, interaction: discord.Interaction, _b) -> None:
        await self.ranger(interaction)

    @discord.ui.button(label="Corriger", style=discord.ButtonStyle.secondary)
    async def bouton_corriger(self, interaction: discord.Interaction, _b) -> None:
        await interaction.response.send_modal(FormulaireDescription(self))

    @discord.ui.button(label="Annuler", style=discord.ButtonStyle.danger)
    async def bouton_annuler(self, interaction: discord.Interaction, _b) -> None:
        await interaction.response.edit_message(content="Abandonné.", view=None)
        self.stop()


class MemeCog(commands.Cog):
    def __init__(self, bot) -> None:
        self.bot = bot
        self.menu = app_commands.ContextMenu(name="Ranger ce meme", callback=self.ranger)
        # Le dossier alimente un overlay diffusé en direct : un dépôt malvenu
        # sortirait à l'antenne.
        self.menu.default_permissions = discord.Permissions(manage_guild=True)
        bot.tree.add_command(self.menu)

    async def cog_unload(self) -> None:
        self.bot.tree.remove_command(self.menu.name, type=self.menu.type)

    async def ranger(self, interaction: discord.Interaction, message: discord.Message) -> None:
        await interaction.response.defer(ephemeral=True)
        trouve = image_du_message(message)
        if trouve is None:
            await interaction.followup.send(
                content="Ce message ne porte aucune image.", ephemeral=True
            )
            return
        url, suffixe = trouve

        try:
            octets = await telecharger(url)
        except Exception as e:  # noqa: BLE001 — un CDN qui refuse ne casse rien
            logger.warning("Meme non rapatrié depuis {u} : {e}", u=url, e=e)
            await interaction.followup.send(
                content=f"Image impossible à récupérer : {e}", ephemeral=True
            )
            return

        deja = await asyncio.to_thread(meme_import.empreintes, DOSSIER_MEMES)
        import hashlib
        depuis = deja.get(hashlib.sha256(octets).hexdigest())
        if depuis:
            await interaction.followup.send(
                content=f"Déjà rangé sous **{depuis}**.", ephemeral=True
            )
            return

        description = ""
        vision = getattr(self.bot, "vision", None)
        if suffixe in _EXTENSIONS and vision is not None and vision.available:
            description = await vision.analyze(
                [url], purpose="meme_describe", prompt_name="meme_describe_system"
            ) or ""

        reste = max(0, len(message.attachments) - 1)
        note = f"\n_{reste} autre(s) image(s) laissée(s)._" if reste else ""
        apercu = description or "_(à écrire — pas d'analyse pour une vidéo)_"
        vue = VueRangement(interaction.user.id, octets, suffixe, description, message.channel)
        await interaction.followup.send(
            content=f"**Description proposée :**\n{apercu}{note}",
            view=vue,
            ephemeral=True,
        )
```

- [ ] **Étape 8 : lancer les tests de la commande**

Commande : `python3 -m pytest tests/test_meme_cmd.py -q`
Attendu : 7 tests au vert.

- [ ] **Étape 9 : enregistrer le cog**

Dans `bot/discord/bot.py`, à côté des `add_cog` existants (vers la ligne 495) :

```python
        from bot.discord.commands.meme_cmd import MemeCog
        await self.add_cog(MemeCog(self))
```

- [ ] **Étape 10 : documenter la voie d'entrée**

Ajouter à `data/memes/LISEZ-MOI.md`, après la section « Formats acceptés » :

```markdown
## Depuis Discord

Clic droit sur un message qui porte une image → *Applications* → **Ranger ce meme**. Réservé à qui
a « Gérer le serveur ». L'image est convertie en WebP si elle y gagne, numérotée à la suite, et sa
description est écrite pour toi — tu peux la corriger avant de valider.

Ça marche aussi sur les images que Wally génère lui-même avec `/wally imagine`.
```

- [ ] **Étape 11 : suite complète, types**

```bash
python3 -m pytest tests/ -q
python3 scripts/lint_types.py
```

- [ ] **Étape 12 : commit**

```bash
git add bot/discord/commands/meme_cmd.py bot/discord/bot.py tests/test_meme_cmd.py data/memes/LISEZ-MOI.md
git commit -m "feat(memes): ranger un meme d'un clic droit sur Discord

Menu Applications sur un message, réservé à « Gérer le serveur ».
Discord exigeant qu'un formulaire soit la première réponse sous 3 s, la
description proposée passe par un aperçu à boutons plutôt que par un
formulaire pré-rempli, impossible à obtenir."
```

- [ ] **Étape 13 : vérifier en production**

```bash
GIT_HASH=$(git rev-parse --short HEAD) BUILD_DATE=$(date -u +%Y-%m-%dT%H:%M:%SZ) \
  docker compose up -d --build wally
docker logs wally-bot --since 3m 2>&1 | grep -iE "error|traceback"
```

Puis, sur Discord : clic droit sur un message avec image → *Applications*. La commande doit
apparaître pour un compte administrateur, et rester absente pour un compte sans « Gérer le
serveur ». Ranger une image, vérifier que `data/memes/meme81.webp` et son `.txt` existent, et que
le message public est parti dans le salon.

---

### Tâche 5 : Le rattrapage de l'existant

**Fichiers :**
- Créer : `scripts/rattraper_memes.py`
- Modifier : `tests/test_meme_import.py` (la fonction de rattrapage, testée sans réseau)
- Modifier : `bot/core/meme_import.py` (`memes_sans_description`)

**Interfaces consommées :** `empreintes`, `sidecar_de`, `convertir`, `verifier_conversion`.

**Interfaces produites :**
- `memes_sans_description(dossier: Path) -> list[Path]`

- [ ] **Étape 1 : écrire le test**

Ajouter à `tests/test_meme_import.py` :

```python
def test_les_memes_sans_sidecar_sont_reperes(tmp_path):
    (tmp_path / "meme1.webp").write_bytes(b"a")
    (tmp_path / "meme1.webp.txt").write_text("décrit", encoding="utf-8")
    (tmp_path / "meme2.png").write_bytes(b"b")
    (tmp_path / "meme3.jpg").write_bytes(b"c")
    (tmp_path / "meme3.txt").write_text("forme sans extension", encoding="utf-8")

    muets = meme_import.memes_sans_description(tmp_path)

    assert [p.name for p in muets] == ["meme2.png"]
```

- [ ] **Étape 2 : lancer, vérifier l'échec**

Commande : `python3 -m pytest tests/test_meme_import.py -q -k sans_sidecar`
Attendu : `AttributeError: ... has no attribute 'memes_sans_description'`

- [ ] **Étape 3 : implémenter**

Dans `bot/core/meme_import.py` :

```python
def memes_sans_description(dossier: Path) -> list[Path]:
    """Les médias dont aucun `.txt` ne parle.

    Leur description retombe alors sur le nom du fichier — « meme80 » : ils sont
    introuvables par `pick(hint)`, qui cherche dans les descriptions, et Wally
    les commente à l'aveugle quand le tirage les sort.

    Les deux formes de sidecar comptent : `meme3.jpg.txt` et `meme3.txt`.
    """
    muets: list[Path] = []
    for p in sorted(dossier.iterdir()):
        if not p.is_file() or p.suffix.lower() not in _EXTENSIONS_MEDIA:
            continue
        if sidecar_de(p) is None and not p.with_suffix(".txt").is_file():
            muets.append(p)
    return muets
```

- [ ] **Étape 4 : lancer, vérifier le vert**

Commande : `python3 -m pytest tests/test_meme_import.py -q`

- [ ] **Étape 5 : écrire le script**

`scripts/rattraper_memes.py` :

```python
#!/usr/bin/env python3
"""Rattrape la banque de memes : décrit les muets, convertit ce qui y gagne.

Les memes déposés à la main n'ont pas toujours de `.txt`. Leur description
retombe alors sur le nom du fichier — « meme80 » : `pick(hint)` cherchant dans
les descriptions, ils sont introuvables par mot-clé, et Wally les commente à
l'aveugle. Ceux déposés depuis la dernière conversion pèsent aussi dix fois leur
poids.

Ce script n'a pas de logique propre : il déroule `bot.core.meme_import` sur le
dossier. Ce que fait la commande Discord à l'unité, il le fait en série.

Usage :
    python3 scripts/rattraper_memes.py                  # simulation
    python3 scripts/rattraper_memes.py --apply          # écrit vraiment
    python3 scripts/rattraper_memes.py --apply --sans-decrire
"""
from __future__ import annotations

import argparse
import asyncio
import base64
import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv

load_dotenv()

from bot.core import meme_import  # noqa: E402
from bot.core.memes import _MEDIA_TYPES  # noqa: E402


async def _decrire(chemin: Path) -> str:
    """Décrit un fichier LOCAL : il n'est pas en ligne, on l'envoie en base64."""
    from bot.core.llm.openai_client import OpenAILLMClient
    from bot.core.vision import VisionService

    class _Db:
        async def log_cost(self, **_):
            return None

    mime = _MEDIA_TYPES.get(chemin.suffix.lower(), "image/png")
    url = f"data:{mime};base64," + base64.b64encode(chemin.read_bytes()).decode()
    svc = VisionService(OpenAILLMClient(model="gpt-5-nano", db=_Db(), max_tokens=400))
    if not svc.available:
        return ""
    return await svc.analyze([url], prompt_name="meme_describe_system") or ""


def _convertir_dossier(dossier: Path, apply: bool) -> None:
    """La même garde que `convertir_memes_webp.py`, sur les fichiers restants.

    Seule la boucle de parcours est écrite ici : `convertir` et
    `verifier_conversion` viennent du module partagé, donc l'unique garde
    anti-perte d'animation reste unique.
    """
    gagne = perdu = 0
    for src in sorted(dossier.iterdir()):
        if not src.is_file() or src.suffix.lower() not in meme_import.A_CONVERTIR:
            continue
        dst = src.with_suffix(".webp")
        if dst.exists():
            print(f"  {src.name:16} laissé — {dst.name} existe déjà")
            continue
        try:
            meme_import.convertir(src, dst)
            probleme = meme_import.verifier_conversion(src, dst)
        except Exception as exc:  # noqa: BLE001 — un format exotique n'interrompt rien
            dst.unlink(missing_ok=True)
            print(f"  {src.name:16} laissé — {exc}")
            continue
        if probleme:
            dst.unlink()
            print(f"  {src.name:16} laissé — {probleme}")
            continue

        avant, apres = src.stat().st_size, dst.stat().st_size
        gagne, perdu = gagne + avant, perdu + apres
        print(f"  {src.name:16} {avant / 1e6:6.2f} Mo -> {apres / 1e6:5.2f} Mo"
              f"  ({100 - 100 * apres / avant:3.0f} %)")
        if apply:
            txt = meme_import.sidecar_de(src)
            if txt is not None:
                txt.rename(dst.with_name(dst.name + ".txt"))
            src.unlink()
        else:
            dst.unlink()
    if gagne:
        print(f"  → {gagne / 1e6:.1f} Mo deviennent {perdu / 1e6:.1f} Mo")


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dossier", default="data/memes")
    parser.add_argument("--apply", action="store_true",
                        help="écrit ; sans lui, rien n'est modifié")
    parser.add_argument("--sans-decrire", action="store_true",
                        help="ne fait que la conversion")
    args = parser.parse_args()

    dossier = Path(args.dossier)
    if not dossier.is_dir():
        print(f"Dossier introuvable : {dossier}")
        return 1

    muets = meme_import.memes_sans_description(dossier)
    print(f"{len(muets)} meme(s) sans description")
    if not args.sans_decrire:
        for chemin in muets:
            if chemin.suffix.lower() not in {".png", ".jpg", ".jpeg", ".gif", ".webp"}:
                print(f"  {chemin.name:16} laissé — pas d'analyse possible sur une vidéo")
                continue
            texte = await _decrire(chemin)
            if not texte:
                print(f"  {chemin.name:16} aucune description obtenue")
                continue
            print(f"  {chemin.name:16} {texte[:90]}")
            if args.apply:
                chemin.with_name(chemin.name + ".txt").write_text(texte, encoding="utf-8")

    print("\nConversion en WebP :")
    _convertir_dossier(dossier, args.apply)

    if not args.apply:
        print("\nSimulation — rien n'a été écrit. Relancer avec --apply.")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
```

- [ ] **Étape 6 : lancer en simulation et lire la sortie**

Commande : `python3 scripts/rattraper_memes.py`
Attendu : cinq memes muets annoncés (`meme35.mp4` écarté comme vidéo), quatre descriptions
proposées, puis le tableau de conversion des quatre fichiers. Vérifier que rien n'a bougé :
`git status --short data/memes` doit rester vide.

- [ ] **Étape 7 : appliquer et vérifier**

```bash
python3 scripts/rattraper_memes.py --apply
python3 -c "
from pathlib import Path
from bot.core import meme_import
muets = meme_import.memes_sans_description(Path('data/memes'))
print('muets restants :', [p.name for p in muets])
print('poids :', sum(p.stat().st_size for p in Path('data/memes').iterdir()) / 1e6, 'Mo')"
```
Attendu : ne reste que `meme35.mp4` (la vidéo), et le dossier est passé sous 29 Mo. Relire deux
descriptions écrites à la main pour vérifier qu'elles ressemblent aux sidecars existants.

- [ ] **Étape 8 : suite complète, types, commit**

```bash
python3 -m pytest tests/ -q && python3 scripts/lint_types.py
git add scripts/rattraper_memes.py bot/core/meme_import.py tests/test_meme_import.py data/memes
git commit -m "feat(memes): rattraper les memes muets et les fichiers trop lourds

Cinq memes n'avaient pas de .txt : introuvables par pick(hint), qui
cherche dans les descriptions, et commentés à l'aveugle. Quatre fichiers
déposés après la dernière conversion pesaient 4,1 Mo pour 0,9 en WebP."
```

---

### Tâche 6 : Le canari voit l'état de la banque

**Fichiers :**
- Modifier : `bot/core/canari.py`
- Modifier : `tests/test_canari.py` (ou création si absent)

**Interfaces consommées :** `memes_sans_description`, `bot.core.memes._MAX_BYTES`.

**Interfaces produites :** `_verifier_memes(racine: Path) -> list[str]`

- [ ] **Étape 1 : écrire le test**

```python
def test_le_canari_signale_un_meme_sans_description(tmp_path):
    from bot.core.canari import _verifier_memes

    memes = tmp_path / "data" / "memes"
    memes.mkdir(parents=True)
    (memes / "meme1.webp").write_bytes(b"a")

    alertes = _verifier_memes(tmp_path)

    assert any("meme1.webp" in a for a in alertes)


def test_le_canari_signale_un_fichier_au_dessus_du_plafond(tmp_path):
    from bot.core.canari import _verifier_memes
    from bot.core.memes import _MAX_BYTES

    memes = tmp_path / "data" / "memes"
    memes.mkdir(parents=True)
    (memes / "enorme.webp").write_bytes(b"\x00" * (_MAX_BYTES + 1))
    (memes / "enorme.webp.txt").write_text("d", encoding="utf-8")

    alertes = _verifier_memes(tmp_path)

    assert any("enorme.webp" in a and "jamais tiré" in a for a in alertes)


def test_le_canari_se_tait_sur_une_banque_saine(tmp_path):
    from bot.core.canari import _verifier_memes

    memes = tmp_path / "data" / "memes"
    memes.mkdir(parents=True)
    (memes / "meme1.webp").write_bytes(b"a")
    (memes / "meme1.webp.txt").write_text("un chat", encoding="utf-8")

    assert _verifier_memes(tmp_path) == []
```

- [ ] **Étape 2 : lancer, vérifier l'échec**

Commande : `python3 -m pytest tests/test_canari.py -q -k memes`
Attendu : `ImportError: cannot import name '_verifier_memes'`

- [ ] **Étape 3 : implémenter**

Dans `bot/core/canari.py`, à côté des autres `_verifier_*` :

```python
def _verifier_memes(racine: Path) -> list[str]:
    """Ce que la banque de memes tait.

    `MemeLibrary.list()` écarte un fichier trop lourd avec un log DEBUG, muet en
    production où les sinks sont à INFO ; une vidéo ne s'affiche jamais sans que
    rien ne le dise ; un meme sans `.txt` est introuvable par mot-clé. Trois
    silences, aucune erreur.
    """
    from bot.core.meme_import import memes_sans_description
    from bot.core.memes import _EXTENSIONS, _MAX_BYTES

    dossier = racine / "data" / "memes"
    if not dossier.is_dir():
        return []

    alertes: list[str] = []
    muets = memes_sans_description(dossier)
    if muets:
        noms = ", ".join(p.name for p in muets[:5])
        suite = f" (+{len(muets) - 5})" if len(muets) > 5 else ""
        alertes.append(
            f"{len(muets)} meme(s) sans description — introuvables par mot-clé et "
            f"commentés à l'aveugle : {noms}{suite}"
        )
    for p in sorted(dossier.iterdir()):
        if not p.is_file() or p.suffix.lower() not in _EXTENSIONS:
            continue
        if p.stat().st_size > _MAX_BYTES:
            alertes.append(
                f"{p.name} pèse {p.stat().st_size / 1e6:.1f} Mo : au-dessus du plafond, "
                f"il ne sera jamais tiré"
            )
    return alertes
```

et l'appeler dans `verifier_invariants`, après `_verifier_identite` :

```python
    alertes += _verifier_memes(racine)
```

- [ ] **Étape 4 : lancer, vérifier le vert**

Commande : `python3 -m pytest tests/test_canari.py -q`

- [ ] **Étape 5 : suite complète, types**

```bash
python3 -m pytest tests/ -q
python3 scripts/lint_types.py
```

- [ ] **Étape 6 : commit et vérification au démarrage**

```bash
git add bot/core/canari.py tests/test_canari.py
git commit -m "feat(canari): la banque de memes ne se tait plus

Un fichier trop lourd était écarté avec un log DEBUG, invisible en
production ; une vidéo ne s'affiche jamais sans rien dire. Le canari les
compte au démarrage."

GIT_HASH=$(git rev-parse --short HEAD) BUILD_DATE=$(date -u +%Y-%m-%dT%H:%M:%SZ) \
  docker compose up -d --build wally
docker logs wally-bot 2>&1 | grep "🐤"
```
Attendu : après le rattrapage de la tâche 5, le canari ne doit signaler que `meme35.mp4` s'il reste
sans description, et rien d'autre côté memes.

- [ ] **Étape 7 : publier**

```bash
git push public feat/site-redesign-arcade:main
```

---

## Ce que ce plan ne fait pas

- Retirer ou renommer un meme depuis Discord — le dashboard et le disque s'en chargent
- La détection perceptuelle de doublons (un même meme ré-encodé passera pour neuf)
- Afficher le meme sur l'overlay dans la foulée de l'ajout
- Toucher au rotateur de memes ou à la route publique qui sert les fichiers
