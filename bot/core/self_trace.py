# bot/core/self_trace.py
"""Ce que Wally vient de FAIRE — une seule trace, tous canaux confondus.

Wally perçoit très bien le monde ; il ne se percevait pas lui-même agissant
dedans. Chacune de ses voies d'action — chat Twitch, chat Discord, bulles et
widgets d'overlay, réactions, outils, boucle cognitive — agissait sans que les
autres en sachent rien. D'où, en live : relancer un bingo qu'il venait
d'ouvrir, se croire muet en répondant toutes les vingt secondes, commenter à la
troisième personne une scène dont il était l'acteur, ressortir un meme trente
secondes après le précédent.

Boucher ces trous un par un rate le problème : le prochain canal branché
recrée le même angle mort. Ce module tient donc **une seule liste**, alimentée
là où les actes passent DÉJÀ tous :

* `bot/core/audit_log.observe_event()` et `journal()` — tout ce qui est
  journalisé (`message_out`, `tool_called`, `gate_decision`), sur les deux
  adaptateurs, le vocal et la cognition. Un nouveau canal qui journalise —
  c'est la convention du projet — entre ici sans une ligne de plus ;
* `bot/core/overlay_feed.OverlayFeed` — bulles, widgets et effacements. Les
  widgets ne sont pas journalisés ; `say()`/`widget()`/`clear()` sont en
  revanche le point de passage unique de tout ce qui atteint l'écran.

## Perception PASSIVE

Même contrat que `stream_feed` et `voice_transcript` : **aucun `notify_*`**.
Savoir qu'il a ouvert un bingo ne réveille pas la cadence cognitive et ne
déclenche aucune prise de parole — sans quoi un bingo ouvert le ferait parler
en boucle pendant tout le live.

## Ce qui n'entre PAS : le contenu

La trace dit ce qu'il a fait et OÙ, jamais ce qui s'est dit. Trois raisons, et
la première suffirait :

1. **Confidentialité.** Ce bloc part dans TOUS ses prompts, quel que soit le
   canal. Un extrait de DM, ou le texte d'une bulle née d'une phrase entendue
   en vocal hors diffusion, ressortirait dans un prompt de chat Twitch. La
   règle du projet (`voice_transcript`) est que la garde se pose à l'ÉCRITURE :
   ce qui n'entre pas ici ne peut pas en sortir. Un nom d'interlocuteur est
   donc tu en DM, et un texte de bulle n'est jamais retenu.
2. **Budget.** Son contexte est déjà chargé ; une ligne d'acte coûte ~15
   jetons, une ligne de contenu dix fois plus.
3. **Redondance.** Le contenu de ses réponses est déjà là où il sert : fenêtre
   de conversation, `_recent_interactions`, mémoire d'anti-répétition des
   bulles.
"""
from __future__ import annotations

import time
from collections import deque
from typing import Optional

from loguru import logger

# Une trace, pas un historique : de quoi savoir ce qu'on vient de faire.
MAX_ACTS = 12
# Au-delà, « je viens de » ne veut plus rien dire. Assez long pour couvrir une
# manche de bingo ou un aller-retour de conversation qui reprend.
ACT_TTL = 1800.0  # 30 min
# Nombre d'actes rendus à la porte de réponse, qui tourne à chaque message et
# doit rester bon marché.
COMPACT_LIMIT = 5

# Outils dont l'EFFET passe déjà par `OverlayFeed` : les compter ici les
# ferait figurer deux fois (« tu as utilisé l'outil show_overlay » PUIS « tu as
# affiché le widget bingo »). C'est une déduplication d'affichage, pas une
# décision de comportement.
OUTILS_TRACES_AILLEURS = frozenset({
    "show_overlay", "cancel_overlay", "show_clip", "duel_apex",
})

# Comment nommer la plateforme dans une phrase. `.get` avec repli sur la valeur
# brute : une plateforme inconnue s'affiche telle quelle plutôt que de
# disparaître.
_PLATEFORMES = {
    "discord": "Discord",
    "twitch": "Twitch",
    "cognitive": "Discord",
}


def _age(seconds: float) -> str:
    """Ancienneté lisible : « à l'instant », « il y a 12 min », « il y a 2 h »."""
    if seconds < 60:
        return "à l'instant"
    minutes = int(seconds // 60)
    if minutes < 60:
        return f"il y a {minutes} min"
    return f"il y a {minutes // 60} h"


class SelfTrace:
    """Tampon roulant de ses propres actes, rendu comme contexte passif."""

    def __init__(self, *, max_acts: int = MAX_ACTS, ttl: float = ACT_TTL) -> None:
        # (dernier_ts, résumé, nombre)
        self._acts: deque[list] = deque(maxlen=max_acts)
        self._ttl = ttl

    def record(self, summary: str) -> None:
        """Empile un acte, déjà rédigé en français à la deuxième personne.

        Deux actes identiques QUI SE SUIVENT sont comptés, pas empilés : cocher
        six cases de bingo ou répondre huit fois à la même personne ne doit pas
        chasser le reste de la fenêtre. Le compte est ce qui répond à « il en a
        sorti deux ? » — l'écraser purement et simplement effacerait justement
        la répétition qu'on cherche à lui rendre visible.
        """
        summary = " ".join((summary or "").split())
        if not summary:
            return
        now = time.monotonic()
        if self._acts and self._acts[-1][1] == summary:
            self._acts[-1][0] = now
            self._acts[-1][2] += 1
            return
        self._acts.append([now, summary, 1])

    def _fresh(self, now: float) -> list[list]:
        return [a for a in self._acts if now - a[0] <= self._ttl]

    def render(self, *, limit: int = MAX_ACTS, compact: bool = False) -> str:
        """Bloc texte des actes récents, ou "" s'il n'a rien fait de frais.

        `compact` retire les consignes et ne garde que la liste : c'est la
        forme servie à la porte de réponse, qui tourne à chaque message.
        """
        now = time.monotonic()
        acts = self._fresh(now)[-max(1, limit):]
        if not acts:
            return ""
        lignes = [
            "\n--- Ce que TU viens de faire ---"
            if not compact else "Ce que tu viens de faire toi-même :"
        ]
        for ts, summary, count in acts:
            suffixe = f" (×{count})" if count > 1 else ""
            lignes.append(f"· {_age(now - ts)}, {summary}{suffixe}")
        if not compact:
            lignes.append(
                "Ces actes sont les TIENS, sur tous tes canaux à la fois. Quand "
                "on te parle de ce qui vient de se passer, de ce qui s'affiche à "
                "l'écran ou de ce que tu viens de faire, la réponse est dans "
                "cette liste : ne suppose pas, et ne raconte jamais l'un de ces "
                "actes comme s'il était de quelqu'un d'autre. Tu n'ouvres pas le "
                "sujet de toi-même."
            )
        return "\n".join(lignes)


# Singleton de processus. Même choix que `audit_log._RECEPTION` : la trace n'a
# pas de propriétaire naturel — six services y écrivent, trois la lisent — et
# la faire descendre par injection demanderait de la câbler dans autant de
# constructeurs pour la même information.
_TRACE = SelfTrace()


def reset_self_trace() -> None:
    """Vide la trace (tests)."""
    _TRACE._acts.clear()


def note_act(summary: str) -> None:
    """Consigne un acte de Wally. **Ne lève jamais** — un journal ne casse
    jamais ce qu'il observe (même contrat que `audit_log.journal`)."""
    try:
        _TRACE.record(summary)
    except Exception as exc:  # noqa: BLE001 — une trace ne casse pas son sujet
        logger.debug("SelfTrace: acte non consigné: {e!r}", e=exc)


def note_voice_speech(channel_id, present: Optional[list] = None) -> None:
    """Wally vient de parler À VOIX HAUTE dans un salon vocal Discord.

    Le vocal ne passe par aucun journal de conversation quand il est privé (cf.
    `bot/discord/voice/request._VoiceJournal`) : il n'a donc pas d'événement
    `message_out` à traduire, et c'était le dernier de ses canaux dont il ne
    savait rien. Il pouvait répondre à un viewer « je n'ai pas parlé de la
    soirée » pendant qu'il tenait une conversation à l'oral.

    **Ce qu'il a dit n'entre pas**, comme partout ailleurs dans ce module — et
    ici la raison est plus dure qu'une convention : la parole d'un vocal non
    diffusé ne doit jamais être retenue (`voice_transcript`, § la
    confidentialité se joue à l'écriture). Le contenu, lui, est déjà là où il
    est légitime : dans `service.history` sur le chemin vocal, et dans le
    tampon `voice_transcript` — sous le label `[Toi]`, et seulement quand le
    live le diffuse — pour ses réponses écrites.

    **Le NOM des présents suit la même règle que le DM** : il n'est écrit que si
    la parole est diffusée au live, donc déjà publique. Hors diffusion, dire
    « tu as parlé avec X » dans un prompt de chat Twitch révélerait que X est en
    vocal avec lui. Le verdict est pris ici, jamais chez l'appelant : c'est la
    règle de `voice_transcript.broadcast_refusal`, en un seul exemplaire.

    Ne lève jamais.
    """
    try:
        from bot.core.voice_transcript import voice_is_broadcast

        diffuse = bool(voice_is_broadcast(channel_id))
    except Exception as exc:  # noqa: BLE001 — dans le doute, la parole est privée
        logger.debug("SelfTrace: diffusion vocale indéterminée: {e!r}", e=exc)
        diffuse = False
    if not diffuse:
        note_act("tu as parlé à voix haute dans un salon vocal privé (Discord)")
        return
    qui = ", ".join(str(n).strip() for n in (present or []) if str(n or "").strip())
    note_act(
        f"tu as parlé à voix haute dans le salon vocal du live, avec {qui}"
        if qui else "tu as parlé à voix haute dans le salon vocal du live"
    )


def current_self_trace_block(*, limit: int = MAX_ACTS,
                             compact: bool = False) -> Optional[str]:
    """Bloc prêt à injecter au prompt, ou None s'il n'a rien fait récemment."""
    try:
        return _TRACE.render(limit=limit, compact=compact) or None
    except Exception as exc:  # noqa: BLE001 — un bloc de contexte ne casse pas un prompt
        logger.debug("SelfTrace: bloc illisible: {e!r}", e=exc)
        return None


# ── dérivation depuis les journaux ────────────────────────────────────────


def _lieu(platform: str, channel: str) -> str:
    """« dans #général (Discord) », ou « en DM privé » quand il faut se taire.

    Le nom du salon Discord arrive sous la forme ``serveur/salon`` : seul le
    salon est gardé, le serveur n'apprend rien à Wally et coûte des jetons.
    """
    salon = (channel or "").split("/")[-1].strip()
    plat = _PLATEFORMES.get(platform, platform)
    if not salon or salon == "dm":
        # Un DM ne dit ni avec qui ni où : ce bloc part aussi dans les prompts
        # publics, et « tu as répondu à X en DM » y révélerait que X lui écrit.
        return "en DM privé"
    return f"dans #{salon} ({plat})" if plat else f"dans #{salon}"


def _note_message_out(platform: str, channel: str, fields: dict) -> None:
    """Un message publié par Wally."""
    # Une réplique jamais partie n'est pas un acte. Le journal garde la ligne
    # (elle sert à voir la panne) ; la trace, elle, ne doit pas lui faire
    # croire qu'il a répondu.
    if fields.get("published") is False:
        return
    if platform == "voice":
        # Une demande faite EN VOCAL, répondue dans le chat Twitch : la réponse
        # est publique, la question ne l'est pas. Le salon vocal n'est donc pas
        # nommé — il n'apprendrait rien à Wally et dirait où il se trouve.
        cible = str(fields.get("target") or "").strip()
        note_act(
            f"tu as répondu à {cible} dans le chat Twitch, à une demande "
            f"faite en vocal" if cible else
            "tu as répondu dans le chat Twitch, à une demande faite en vocal"
        )
        return
    lieu = _lieu(platform, channel)
    spontane = str(fields.get("kind") or "") in ("cognitive", "spontaneous")
    if lieu == "en DM privé":
        note_act("tu as écrit en DM privé")
        return
    cible = str(fields.get("target") or "").strip()
    if spontane:
        note_act(f"tu as pris la parole de toi-même {lieu}")
    elif cible:
        note_act(f"tu as répondu à {cible} {lieu}")
    else:
        note_act(f"tu as répondu {lieu}")


def note_journal_act(platform: str, channel: str, event_type: str,
                     fields: dict) -> None:
    """Traduit un événement de journal en acte, s'il en est un. Ne lève jamais.

    Table volontairement courte : un journal contient surtout des mesures
    (latences, coûts, décisions internes). Seuls les événements qui laissent
    une trace DANS LE MONDE ont leur place ici.
    """
    try:
        fields = fields or {}
        if event_type == "message_out":
            _note_message_out(platform, channel, fields)
        elif event_type == "gate_decision":
            if str(fields.get("decision") or "").strip().lower() == "react":
                emoji = str(fields.get("emoji") or "").strip()
                quoi = f"réagi {emoji}" if emoji else "posé une réaction"
                note_act(f"tu as {quoi} sans répondre, {_lieu(platform, channel)}")
        elif event_type == "tool_called":
            outil = str(fields.get("tool") or "").strip()
            if outil and outil not in OUTILS_TRACES_AILLEURS:
                note_act(f"tu as utilisé ton outil « {outil} »")
    except Exception as exc:  # noqa: BLE001 — une trace ne casse pas son sujet
        logger.debug("SelfTrace: événement {t} non traduit: {e!r}", t=event_type, e=exc)
