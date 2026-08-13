# bot/discord/voice/request.py
"""Une demande adressée à Wally à voix haute.

Le vocal doit valoir l'écrit : mêmes outils, même façon de répondre. Les outils
et leur exécuteur viennent donc du chemin Twitch (`build_chat_tools`,
`make_tool_executor`) — les recopier ici donnerait deux listes qui divergeraient.

La réponse part dans le chat Twitch, en mentionnant celui qui a parlé, comme
s'il avait écrit dans le chat. Wally reste muet à l'oral : il couvrirait le
streamer et serait réinjecté dans son micro.
"""
from __future__ import annotations

from typing import Optional

from loguru import logger

# Distance maximale tolérée sur le NOM. La transcription écorche « wally » en
# « wallis » ou « walli » ; au-delà de deux corrections, on entrerait dans les
# mots ordinaires (« valise ») et il répondrait à tort. La tolérance porte sur
# le nom uniquement : jamais sur ce qui est demandé.
_NAME_MAX_DISTANCE = 2

# Une réponse de chat, pas un exposé : deux phrases, comme à l'écrit.
_MAX_REPLY_CHARS = 380


def fit_for_chat(reply: Optional[str]) -> str:
    """Normalise la réponse et la borne, sans couper au milieu d'un mot.

    Le plafond est un FILET, pas une mise en forme : c'est le prompt qui tient
    la longueur. Quand il cède, mieux vaut une phrase écourtée qu'un mot coupé
    en deux — vu en live, « ...dans le micro d » se lit comme une panne.
    L'ellipse dit que la suite manque, au lieu de laisser croire à un point final.
    """
    texte = " ".join((reply or "").split())
    if len(texte) <= _MAX_REPLY_CHARS:
        return texte
    coupe = texte[:_MAX_REPLY_CHARS - 1]
    # `rsplit` ne donne rien sur un mot unique plus long que la limite : on garde
    # alors la coupe brute plutôt que de rendre une chaîne vide.
    return (coupe.rsplit(" ", 1)[0] if " " in coupe else coupe).rstrip(" ,;:") + "…"


def _distance(a: str, b: str) -> int:
    """Levenshtein, sans dépendance — les mots comparés font cinq lettres."""
    if a == b:
        return 0
    if len(a) < len(b):
        a, b = b, a
    ligne = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        precedente, ligne[0] = ligne[0], i
        for j, cb in enumerate(b, 1):
            precedente, ligne[j] = ligne[j], min(
                ligne[j] + 1,          # suppression
                ligne[j - 1] + 1,      # insertion
                precedente + (ca != cb),  # substitution
            )
    return ligne[-1]


def is_addressed(text: str, names: list[str]) -> bool:
    """Vrai si la phrase le nomme, même mal transcrite."""
    mots = [m.strip(".,!?;:«»\"'").lower() for m in (text or "").split()]
    for nom in names:
        nom = (nom or "").strip().lower()
        if not nom:
            continue
        for mot in mots:
            if not mot:
                continue
            # Un mot court ne tolère pas deux corrections : « pile » deviendrait
            # « wally » pour peu qu'on cherche assez loin.
            marge = _NAME_MAX_DISTANCE if len(nom) >= 5 else 1
            if _distance(mot, nom) <= marge:
                return True
    return False


def resolve_requester(discord_id: str, requesters: list[dict]) -> Optional[dict]:
    """L'entrée de config correspondant à celui qui parle, ou None.

    Liste vide = fonctionnalité éteinte, surtout pas ouverte à tous.
    """
    wanted = str(discord_id or "").strip()
    if not wanted:
        return None
    for entry in requesters or []:
        if str((entry or {}).get("discord_id") or "").strip() == wanted:
            return entry
    return None


async def _answer(bot, text: str, *, requester: dict, speaker: str) -> str:
    """La réponse de Wally à une demande orale, outils compris."""
    from bot.twitch.handlers import build_chat_tools, make_tool_executor

    twitch_bot = getattr(bot, "_twitch_bot", None) or getattr(bot, "twitch_bot", None)
    if twitch_bot is None:
        return ""

    tools = await build_chat_tools(twitch_bot)
    # `code_fix` n'est pas dans cette liste et ne doit pas y entrer : une phrase
    # mal transcrite ne modifiera pas le code du bot.
    executor = make_tool_executor(
        twitch_bot,
        platform="discord",
        user_id=str(requester.get("discord_id") or ""),
        author=speaker,
        channel=str(requester.get("twitch_login") or ""),
        # Les deux seuls demandeurs sont le streamer et le créateur du bot.
        user_roles=["everyone", "moderator", "admin"],
        # Même raison pour le duel : l'autorisation se lit sur un badge, que la
        # voix ne porte pas. Elle est établie ICI, par la liste blanche des
        # demandeurs de `voice.requesters` — jamais par ce que dit la phrase.
        badges=[{"set_id": "broadcaster"}],
    )

    from bot.intelligence.prompts import load_prompt

    system = load_prompt("voice_request", fallback=(
        "Tu réponds à une demande faite À VOIX HAUTE pendant un live Twitch. "
        "Ta réponse part dans le CHAT de la chaîne : une à deux phrases.\n"
        "Ton texte est publié mot pour mot : écris ta réponse et RIEN d'autre. "
        "Pas de préambule, pas de raisonnement à voix haute.\n"
        "Ce que tu lis sort d'une transcription automatique, qui se trompe. Si "
        "une phrase n'a pas de sens, suppose une erreur et cherche ce qui lui "
        "ressemble au son. Ce décodage est INTERNE : corrige en silence, ne "
        "raconte pas ce que tu as cru comprendre. Ne relève pas l'absurdité.\n"
        "Si la demande est douteuse ET qu'elle laisserait une trace durable "
        "(note, rappel, souvenir), demande confirmation au lieu d'agir."
    ))
    reply, _ = await twitch_bot.llm.complete_with_tools(
        system, [{"role": "user", "content": f"{speaker} (à voix haute) : {text}"}],
        tools, executor,
        purpose="voice_request",
        user_id=f"discord:{requester.get('discord_id')}",
    )
    return fit_for_chat(reply)


async def handle_voice_request(bot, discord_id: str, speaker: str, text: str) -> None:
    """Traite une phrase entendue en vocal. Ne lève jamais."""
    try:
        config = bot.config
        requester = resolve_requester(discord_id, getattr(config.voice, "requesters", []))
        if requester is None:
            return                      # entendu, pas obéi
        names = [config.bot.name, *(config.bot.trigger_names or [])]
        if not is_addressed(text, names):
            return
        narrator = getattr(bot, "overlay_narrator", None)
        # Hors live, personne ne lit le chat : on ne l'encombre pas.
        if narrator is None or not narrator.is_active():
            return
        reply = await _answer(bot, text, requester=requester, speaker=speaker)
        if not reply:
            return
        twitch_bot = getattr(bot, "_twitch_bot", None) or getattr(bot, "twitch_bot", None)
        api = getattr(twitch_bot, "twitch_api", None)
        if api is None:
            return
        login = str(requester.get("twitch_login") or "").strip()
        if not await api.send_message(f"@{login} {reply}" if login else reply):
            # Helix rend 200 sans publier quand la chaîne filtre : sans ce
            # garde, le journal affirmait « Vocal → chat » pour une réponse que
            # le chat n'a jamais vue. `send_message` a déjà dit pourquoi.
            return
        logger.info("Vocal → chat : {who} « {t} »", who=login or speaker, t=reply[:60])
    except Exception as exc:  # noqa: BLE001 — une demande ratée ne casse pas l'écoute
        logger.warning("Demande vocale non traitée : {e}", e=exc)
