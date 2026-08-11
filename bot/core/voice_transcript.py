# bot/core/voice_transcript.py
"""Ce qui se dit dans le vocal, restitué comme contexte aux réponses ÉCRITES.

À ne pas confondre avec `bot/discord/voice/feed.py` (`VoiceFeed`, exposé en
`bot.voice_feed`) : celui-là diffuse les événements du pipeline vocal vers le
panneau de debug SSE. Ici, on garde la CONVERSATION pour la remettre au prompt.

Wally entend le salon vocal ; à l'écrit — chat Twitch, salons Discord — il en
était totalement coupé. Un viewer qui demande « il dit quoi Azraël ? » recevait
un « je sais pas » exact mais absurde, puisque Wally était dans le vocal.

Ce tampon roulant garde les dernières répliques entendues et les rend au prompt
sous forme de bloc de CONTEXTE PASSIF, sur le patron de `stream_feed` : aucun
`notify_*` derrière, donc entendre parler ne réveille jamais la cadence
cognitive et ne déclenche aucune prise de parole.

## La confidentialité se joue à l'ÉCRITURE

Un vocal Discord est privé par défaut. Il cesse de l'être pendant un live, où
le micro du streamer le diffuse aux viewers — mais SEULEMENT dans le salon
d'où il streame, et SEULEMENT pendant le live.

La garde est donc posée sur `record()`, pas sur `render()` : hors diffusion,
rien n'entre. Un tampon qui ne contient jamais de parole privée ne peut pas la
fuiter, quel que soit le consommateur qu'on lui branchera plus tard (journal,
cognition, overlay). L'inverse — filtrer au rendu — laissait passer les 30
minutes de vocal PRÉCÉDANT le lancement du live, que personne n'avait
entendues.
"""
from __future__ import annotations

import time
from collections import deque
from collections.abc import Callable
from typing import Optional

from loguru import logger

from bot.core.stream_watcher import current_stream_status

# Une conversation, pas un historique : de quoi savoir de quoi on parle.
MAX_LINES = 14
# Généreux à dessein. Dix minutes de silence pendant une partie tendue ne
# veulent pas dire que la conversation est finie — l'ancienneté est affichée,
# Wally juge lui-même de la fraîcheur (même choix que `stream_feed`).
LINE_TTL = 1800.0   # 30 min
# Au-delà, on ne dit plus « en ce moment » sans le dater.
STALE_AFTER = 120.0  # 2 min

_active: "VoiceTranscriptFeed | None" = None


def active_voice_transcript() -> "VoiceTranscriptFeed | None":
    """Le tampon de conversation vocale actif, ou None."""
    return _active


def current_voice_transcript_block() -> Optional[str]:
    """Bloc de conversation vocale prêt à injecter au prompt, ou None."""
    if _active is None:
        return None
    return _active.render() or None


def _age(seconds: float) -> str:
    """Ancienneté lisible : « à l'instant », « il y a 12 min », « il y a 2 h »."""
    if seconds < 60:
        return "à l'instant"
    minutes = int(seconds // 60)
    if minutes < 60:
        return f"il y a {minutes} min"
    return f"il y a {minutes // 60} h"


class VoiceTranscriptFeed:
    """Tampon roulant des répliques du vocal, rendu comme contexte passif."""

    def __init__(
        self,
        *,
        max_lines: int = MAX_LINES,
        line_ttl: float = LINE_TTL,
    ) -> None:
        self._lines: deque[tuple[float, str, str]] = deque(maxlen=max_lines)
        self._line_ttl = line_ttl
        # Salon dont la parole est diffusée au live. None = rien n'est diffusé,
        # donc rien n'est retenu.
        self._broadcast_channel_id: int | None = None
        # Fournisseur paresseux des présents (branché sur `members_names()`) :
        # rendu toujours à jour sans que le service ait à pousser quoi que ce
        # soit, et sans référence inverse. Même patron que `set_observer`.
        self._presence_source: Optional[Callable[[], list[str]]] = None
        # Dernier verdict d'injection et dernier motif de refus : on ne logge
        # qu'aux transitions, ces deux chemins étant parcourus à chaque message
        # reçu et à chaque phrase entendue.
        self._last_verdict: str | None = None
        self._last_refusal: str | None = None

    def activate(self) -> None:
        """Enregistre ce flux comme source globale du bloc de contexte."""
        global _active
        _active = self

    def set_presence_source(self, source: Optional[Callable[[], list[str]]]) -> None:
        """Branche le fournisseur des présents en vocal (None pour couper)."""
        self._presence_source = source

    # ------------------------------------------------------------------
    # Diffusion
    # ------------------------------------------------------------------

    def open_broadcast(self, channel_id: int | None) -> None:
        """Ouvre la captation : la parole de `channel_id` est diffusée au live.

        Appelé au démarrage du live (et par le veilleur, qui couvre le
        redémarrage en plein stream). Idempotent — le veilleur repasse toutes
        les 30 s et ne doit pas remplir les logs.
        """
        if channel_id is None:
            return
        channel_id = int(channel_id)
        if self._broadcast_channel_id == channel_id:
            return
        # Changement de salon diffusé : ce qui précède venait d'ailleurs.
        if self._broadcast_channel_id is not None:
            self._lines.clear()
        self._broadcast_channel_id = channel_id
        logger.info(
            "VoiceTranscript: captation OUVERTE sur le salon vocal {c} (live en cours)",
            c=channel_id,
        )

    def close_broadcast(self) -> None:
        """Ferme la captation et purge : le live est fini, plus rien n'est diffusé."""
        if self._broadcast_channel_id is None:
            return
        logger.info(
            "VoiceTranscript: captation FERMÉE (salon {c}), {n} réplique(s) oubliée(s)",
            c=self._broadcast_channel_id, n=len(self._lines),
        )
        self._broadcast_channel_id = None
        self._lines.clear()

    def clear(self, reason: str = "") -> None:
        """Oublie les répliques retenues (départ du salon, déplacement)."""
        if not self._lines:
            return
        logger.info(
            "VoiceTranscript: {n} réplique(s) oubliée(s) ({r})",
            n=len(self._lines), r=reason or "sans raison précisée",
        )
        self._lines.clear()

    # ------------------------------------------------------------------
    # Écriture
    # ------------------------------------------------------------------

    def record(self, channel_id: int | None, speaker: str, text: str) -> bool:
        """Retient une réplique entendue. Renvoie True si elle a été retenue.

        Refuse tout ce qui n'est pas diffusé au live : c'est ici, et nulle part
        ailleurs, que se joue la confidentialité du vocal.
        """
        text = " ".join((text or "").split())
        speaker = (speaker or "").strip()
        if not text or not speaker:
            return False

        if self._broadcast_channel_id is None:
            self._refus("aucune captation ouverte (hors live)")
            return False
        if channel_id is None or int(channel_id) != self._broadcast_channel_id:
            self._refus(
                f"salon {channel_id} hors diffusion "
                f"(le salon diffusé est {self._broadcast_channel_id})"
            )
            return False
        # Deuxième verrou : le drapeau de captation pourrait rester ouvert si la
        # transition de fin de live était ratée (le watcher lit parfois une
        # erreur d'API comme un stream éteint, l'inverse n'est pas exclu).
        if not (current_stream_status() or {}).get("live"):
            self._refus("le live n'est plus actif")
            return False

        self._lines.append((time.monotonic(), speaker, text[:200]))
        # Le CONTENU reste en DEBUG, donc hors des journaux de prod : c'est la
        # parole de vraies personnes, `app.log` est gardé 30 jours.
        logger.debug("VoiceTranscript: [{s}] {t}", s=speaker, t=text[:200])
        self._last_refusal = None
        return True

    def _refus(self, raison: str) -> None:
        """Trace un refus d'enregistrement, au CHANGEMENT de raison seulement.

        En INFO, pas en DEBUG : les trois sinks de `setup_logging` filtrent à
        INFO, un diagnostic en DEBUG serait donc invisible exactement le jour
        où on le cherche. Et sans le filtre par raison, un vocal actif hors
        live écrirait une ligne par phrase entendue.
        """
        if raison == self._last_refusal:
            return
        self._last_refusal = raison
        logger.info("VoiceTranscript: réplique NON retenue — {r}", r=raison)

    # ------------------------------------------------------------------
    # Rendu
    # ------------------------------------------------------------------

    def _fresh(self, now: float) -> list[tuple[float, str, str]]:
        return [line for line in self._lines if now - line[0] <= self._line_ttl]

    def _present_label(self) -> str:
        if self._presence_source is None:
            return ""
        try:
            names = self._presence_source() or []
        except Exception as exc:  # noqa: BLE001 — un fournisseur cassé ne casse pas le bloc
            logger.warning("VoiceTranscript: présents illisibles: {e}", e=exc)
            return ""
        return ", ".join(names)

    def _verdict(self, reason: str, detail: str = "") -> None:
        """Logge la raison d'injection/non-injection, aux transitions seulement.

        `build_system_prompt` tourne à chaque message : sans ce filtre, la
        moindre soirée noierait les logs. Une absence non tracée, en revanche,
        est un `continue` silencieux qu'on met des semaines à voir.

        `detail` (le nombre de répliques) reste hors du verdict comparé : le
        faire varier à chaque parole rendrait CHAQUE rendu « nouveau », et le
        filtre anti-bruit ne filtrerait plus rien.
        """
        logger.debug("VoiceTranscript: bloc {r}{d}", r=reason, d=f" ({detail})" if detail else "")
        if reason == self._last_verdict:
            return
        self._last_verdict = reason
        logger.info("VoiceTranscript: bloc {r}", r=reason)

    def render(self) -> str:
        """Bloc texte de la conversation vocale, ou "" si rien à montrer."""
        if self._broadcast_channel_id is None:
            self._verdict("absent — aucune captation ouverte (hors live)")
            return ""
        now = time.monotonic()
        lines = self._fresh(now)
        if not lines:
            self._verdict("absent — aucune réplique fraîche au tampon")
            return ""

        who = self._present_label()
        header = (
            f"Tu es dans le salon vocal avec {who}." if who
            else "Tu es dans le salon vocal et tu entends ce qui s'y dit."
        )
        # Le vocal d'un live est diffusé aux viewers : ce bloc ne révèle rien
        # que le chat Twitch n'ait déjà entendu (cf. la garde de `record`).
        out = [
            "\n--- Conversation vocale en cours (Discord) ---",
            header,
            "Ce que tu lis est une transcription automatique : elle écorche les "
            "mots et les noms. Ne cite personne au mot près, et si une phrase "
            "n'a pas de sens, c'est la transcription qu'il faut soupçonner.",
        ]
        last_age = now - lines[-1][0]
        if last_age > STALE_AFTER:
            out.append(f"Dernier échange entendu {_age(last_age)} — ça s'est calmé depuis.")
        for _ts, speaker, text in lines:
            out.append(f"· [{speaker}] {text}")
        out.append(
            "Ces gens te parlent EN VOCAL : ils ne sont pas dans la conversation "
            "écrite où tu réponds là, et ils ne liront pas ta réponse. Ne leur "
            "réponds pas ici. Tu peux faire référence à ce qui se dit en vocal "
            "si on t'en parle ou si c'est pertinent, mais tu ne racontes pas le "
            "vocal de toi-même à des gens qui ne l'entendent pas."
        )
        self._verdict("injecté", detail=f"{len(lines)} réplique(s)")
        return "\n".join(out)
