"""Génération d'image à l'initiative de Wally — la politique, en un seul endroit.

Jusqu'ici, une image n'existait que si un HUMAIN tapait `/wally imagine` (ou le
site). Wally sait fabriquer une image, mais uniquement quand on la lui demande :
il ne pouvait rien illustrer de lui-même, ni alimenter un fil de memes, ni
répondre en image à un post.

Ce module ne génère rien : il répond à la seule question qui coûte de l'argent —
« a-t-il le droit de le faire, ici, maintenant ? ». Le même objet sert :

* au prompt de cognition (`ReasoningAgent`), pour lui ANNONCER les salons ouverts ;
* au dispatcher (`ActionDispatcher._generate_image`), pour les FAIRE RESPECTER.

Deux listes finiraient par diverger, et il promettrait un salon interdit — ou
pire, se verrait refuser sans savoir pourquoi.

## Ce qui est en config, et ce qui est ici

Les salons, la cadence et le plafond du jour vivent dans `config.yaml`
(`image_generation.autonomous_*`, rechargé à chaud). Le code ne porte que le
MÉCANISME : l'intersection avec l'annuaire des canaux, la lecture des compteurs,
la formulation du refus.

## Pourquoi la cadence se lit en BASE et non en RAM

On rebuild plusieurs fois par soirée. Un `monotonic()` gardé en attribut repart
à zéro à chaque redémarrage : la garde de délai ne mordrait jamais les soirs où
elle sert le plus. Le compteur du jour et l'horodatage de la dernière image sont
donc dérivés de `gallery_images`, qui survit au conteneur.
"""

from __future__ import annotations

import time
from collections.abc import Callable

from loguru import logger

# Auteur des images qu'il fabrique de lui-même, faute d'id Discord connu. Le
# format `plateforme:id` est celui de toute la galerie ; l'appelant fournit
# normalement l'id RÉEL du bot (`discord:<id>`), ce qui garde `int(...)`
# valable partout où la galerie le reparse.
AUTEUR_PAR_DEFAUT = "discord:0"


class ImageInitiative:
    """Autorise (ou refuse) une génération d'image décidée par Wally seul."""

    def __init__(
        self,
        config,
        db,
        channel_names: Callable[[], dict[str, str]] | dict[str, str] | None = None,
        auteur_id: Callable[[], str] | str | None = None,
    ) -> None:
        self._config = config
        self._db = db
        self._channel_names = channel_names
        self._auteur_id = auteur_id

    # ── Lecture de l'état ────────────────────────────────────────────────────

    def _cfg(self):
        return getattr(self._config, "image_generation", None)

    def auteur_id(self) -> str:
        """Id sous lequel ses propres images sont rangées (et donc comptées)."""
        val = self._auteur_id() if callable(self._auteur_id) else self._auteur_id
        return str(val) if val else AUTEUR_PAR_DEFAUT

    def _noms(self) -> dict[str, str]:
        src = self._channel_names() if callable(self._channel_names) else self._channel_names
        return dict(src or {})

    def salons(self) -> dict[str, str]:
        """Salons ouverts à l'initiative : `id → nom lisible`, dans l'ordre de la config.

        Un id absent de l'annuaire garde son id pour nom : on n'écarte pas un
        salon autorisé parce que `CHANNELS.md` ne le décrit pas — la config est
        la source de l'autorisation, l'annuaire n'est qu'un dictionnaire de noms.
        """
        cfg = self._cfg()
        ids = list(getattr(cfg, "autonomous_channel_ids", None) or [])
        noms = self._noms()
        return {str(i): noms.get(str(i), str(i)) for i in ids if str(i).strip()}

    @property
    def enabled(self) -> bool:
        cfg = self._cfg()
        return bool(getattr(cfg, "autonomous_enabled", False)) and bool(self.salons())

    def cadence_texte(self) -> str:
        """La contrainte de coût, dite en français — pour le prompt."""
        cfg = self._cfg()
        par_jour = int(getattr(cfg, "autonomous_daily_limit", -1) or -1)
        delai = int(getattr(cfg, "autonomous_cooldown_minutes", 0) or 0)
        morceaux = []
        if par_jour >= 0:
            morceaux.append(f"{par_jour} image(s) par jour au maximum")
        if delai > 0:
            morceaux.append(f"jamais deux à moins de {delai} minutes d'intervalle")
        return ", ".join(morceaux)

    def salons_texte(self) -> str:
        """Les salons autorisés, un par ligne, avec leur id EXACT."""
        return "\n".join(f"  {cid} {nom}" for cid, nom in self.salons().items())

    def noms_salons(self) -> list[str]:
        return list(self.salons().values())

    # ── La décision ──────────────────────────────────────────────────────────

    async def refus(self, channel_id: str) -> str:
        """Motif du refus, ou chaîne vide si Wally peut y aller.

        Rend une PHRASE et pas un booléen : le motif part dans le journal des
        actions sans effet et dans sa propre trace. « action silencieuse » ne
        lui apprend rien ; « plafond du jour atteint (4/4) » lui dit d'attendre
        demain au lieu de réessayer à chaque tick.
        """
        cfg = self._cfg()
        if cfg is None:
            return "config d'image absente"
        if not getattr(cfg, "autonomous_enabled", False):
            return "génération autonome désactivée (image_generation.autonomous_enabled)"
        salons = self.salons()
        if not salons:
            return "aucun salon ouvert (image_generation.autonomous_channel_ids est vide)"
        cid = str(channel_id or "").strip()
        if cid not in salons:
            ouverts = ", ".join(salons.values()) or "aucun"
            return f"salon {cid or '?'} interdit à l'initiative (ouverts : {ouverts})"

        auteur = self.auteur_id()
        par_jour = int(getattr(cfg, "autonomous_daily_limit", -1) or -1)
        delai_min = int(getattr(cfg, "autonomous_cooldown_minutes", 0) or 0)
        try:
            if par_jour >= 0:
                deja = await self._db.get_user_image_count_today(auteur)
                if deja >= par_jour:
                    return f"plafond du jour atteint ({deja}/{par_jour})"
            if delai_min > 0:
                dernier = await self._db.get_last_image_ts(auteur)
                if dernier:
                    reste = delai_min * 60 - (time.time() - dernier)
                    if reste > 0:
                        return f"trop tôt : encore {int(reste // 60) + 1} min avant la prochaine"
        except Exception as exc:  # noqa: BLE001 — un quota illisible ne s'ouvre pas
            # Refus et non passage en force : ces deux lectures sont les seules
            # gardes de COÛT du chemin autonome. Les ouvrir sur une erreur de
            # base reviendrait à lever le plafond au pire moment.
            logger.warning("ImageInitiative: quota illisible → refus prudent: {e!r}", e=exc)
            return "état du quota d'images illisible"
        return ""
