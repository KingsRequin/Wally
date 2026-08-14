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

import time
import unicodedata
from dataclasses import dataclass
from typing import Optional

from loguru import logger

from bot.core.audit_log import conv_log_of, journal
from bot.core.conversation_log import new_trace_id
from bot.core.voice_transcript import voice_is_broadcast

# Où atterrit le journal des demandes vocales, dans l'arborescence existante :
# `logs/conversations/voice/{salon}/{date}.jsonl`. Les types d'événements sont
# ceux du format maison (`message_in`, `tool_called`, `tool_result`,
# `message_out`) : l'audit par trace fonctionne dessus sans rien y ajouter.
VOICE_JOURNAL_PLATFORM = "voice"

# Distance maximale tolérée sur le NOM. La transcription écorche « wally » en
# « wallis » ou « walli » ; au-delà de deux corrections, on entrerait dans les
# mots ordinaires (« valise ») et il répondrait à tort. La tolérance porte sur
# le nom uniquement : jamais sur ce qui est demandé.
_NAME_MAX_DISTANCE = 2

# En dessous de cette longueur, un mot n'a pas assez de lettres pour survivre à
# deux corrections sans devenir autre chose : « all » et « way » sont à distance
# 2 de « wally ». Ces mots-là doivent donc tomber JUSTE.
_MIN_FUZZY_LEN = 5

# Mots relevés en live comme ayant déclenché Wally à tort (13/08 : 9 des 31
# déclenchements ; jusqu'à 60 % sur un autre jour). Les deux règles ci-dessus les
# écartent déjà toutes ; cette liste est un cliquet explicite et nommé — elle dit
# QUELS mots ont fait parler le bot dans le vide, et ferait tomber un test si la
# tolérance était un jour rouverte.
# « wallah » n'a pas été constaté mais passe les deux règles (même initiale, 6
# lettres, distance 2) : c'est une interjection, jamais son nom.
_JAMAIS_SON_NOM = frozenset({
    "balle", "salle", "dalle", "allo", "alle", "aller", "all", "well", "way",
    "early", "wallah",
})


def _plier(mot: str) -> str:
    """Minuscules sans accents : « allô » et « allé » se rangent avec « allo »."""
    plie = unicodedata.normalize("NFD", (mot or "").lower())
    return "".join(c for c in plie if unicodedata.category(c) != "Mn")

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


@dataclass(frozen=True)
class AddressVerdict:
    """Le verdict de `address_match`, motif compris.

    Le booléen seul était un cul-de-sac de diagnostic : la détection répondait
    « non » en silence, donc les vrais ratés — quelqu'un qui dit « le bot »,
    « l'IA », « il » — restaient indénombrables, et les quasi-déclenchements
    (un mot à une lettre de son nom) invisibles.
    """

    addressed: bool
    word: str = ""          # le mot entendu qui a tranché
    name: str = ""          # le nom auquel il a été comparé
    rule: str = ""          # la règle qui a conclu
    distance: Optional[int] = None


def address_match(text: str, names: list[str]) -> AddressVerdict:
    """Décide si la phrase le nomme, et dit POURQUOI.

    Même logique que `is_addressed` (dont c'est désormais le moteur) : les trois
    garde-fous y sont inchangés. Ce qui est ajouté, c'est le motif — et, quand
    la phrase ne le nomme pas, le meilleur **quasi-déclenchement** : le mot qui
    aurait suffi si l'on avait relâché exactement une règle. C'est la seule
    façon de savoir si la tolérance est trop serrée ou trop lâche.
    """
    mots = [_plier(m.strip(".,!?;:«»\"'()…-")) for m in (text or "").split()]
    quasi: Optional[AddressVerdict] = None

    def _retiens(verdict: AddressVerdict) -> None:
        nonlocal quasi
        if quasi is None:
            quasi = verdict

    for nom in names:
        nom = _plier((nom or "").strip())
        if not nom:
            continue
        for mot in mots:
            if not mot:
                continue
            if mot == nom and mot not in _JAMAIS_SON_NOM:
                return AddressVerdict(True, mot, nom, "exact", 0)
            ecart = _distance(mot, nom)
            if mot in _JAMAIS_SON_NOM:
                if (len(mot) >= _MIN_FUZZY_LEN and len(nom) >= _MIN_FUZZY_LEN
                        and mot[0] == nom[0] and ecart <= _NAME_MAX_DISTANCE):
                    _retiens(AddressVerdict(False, mot, nom, "jamais son nom", ecart))
                continue
            if len(mot) < _MIN_FUZZY_LEN or len(nom) < _MIN_FUZZY_LEN:
                if ecart <= _NAME_MAX_DISTANCE:
                    _retiens(AddressVerdict(False, mot, nom, "mot trop court", ecart))
                continue
            if mot[0] != nom[0]:
                if ecart <= _NAME_MAX_DISTANCE:
                    _retiens(AddressVerdict(False, mot, nom, "initiale différente", ecart))
                continue
            if ecart <= _NAME_MAX_DISTANCE:
                return AddressVerdict(True, mot, nom, "approché", ecart)
            if ecart == _NAME_MAX_DISTANCE + 1:
                _retiens(AddressVerdict(False, mot, nom, "trop loin", ecart))
    return quasi or AddressVerdict(False)


def is_addressed(text: str, names: list[str]) -> bool:
    """Vrai si la phrase le nomme, même mal transcrite.

    Trois garde-fous, tous nés du même constat : une tolérance de deux
    corrections sur cinq lettres attrape la moitié du français courant. Mesuré
    sur quatre jours de live, 29 % à 60 % des déclenchements portaient sur une
    phrase qui ne le nommait pas — et chacun coûte un appel au modèle ET un
    message publié dans le chat de la chaîne.

    1. **L'initiale ne se corrige pas.** « wally » sans son `w` n'est plus son
       nom : balle, salle, dalle, allô, allé, early tombent ici.
    2. **Les mots courts doivent tomber juste** (`_MIN_FUZZY_LEN`) : « all »,
       « way », « well » sont à deux corrections de « wally » alors qu'ils n'ont
       rien à voir.
    3. **Une liste de mots qui ne sont jamais son nom**, en clair.

    Ce qui doit continuer de passer : « Walli », « Wallie », « Wallis », « le
    wally », et les fautes de frappe qui gardent l'initiale et la longueur.

    Le moteur est `address_match`, qui rend en plus le motif : deux
    implémentations de cette règle finiraient par diverger, et c'est elle qui
    décide si Wally parle dans le chat d'une chaîne.
    """
    return address_match(text, names).addressed


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


class _VoiceJournal:
    """Le journal d'UNE demande vocale — ou un trou noir si elle est privée.

    Le vocal Discord est privé par défaut ; il cesse de l'être pendant un live,
    et seulement dans le salon diffusé. La frontière est la même que celle du
    tampon de contexte (`bot/core/voice_transcript.py`), et elle est évaluée
    ICI, à l'ouverture : un journal qui n'a pas la preuve que la parole est
    publique n'écrit rien du tout — pas même le nom de qui parlait.
    """

    def __init__(self, bot, channel_id, channel_name: str) -> None:
        diffuse = False
        try:
            diffuse = voice_is_broadcast(channel_id)
        except Exception as exc:  # noqa: BLE001 — dans le doute, on n'écrit pas
            logger.debug("Journal vocal : diffusion indéterminée ({e})", e=exc)
        self._clog = conv_log_of(bot, getattr(bot, "_twitch_bot", None)) if diffuse else None
        self._channel = (channel_name or str(channel_id or "salon")).strip() or "salon"
        self.trace = new_trace_id("vocal")

    @property
    def actif(self) -> bool:
        return self._clog is not None

    def write(self, event_type: str, **fields) -> None:
        journal(self._clog, VOICE_JOURNAL_PLATFORM, self._channel, event_type,
                trace_id=self.trace, **fields)


def _traced_executor(executor, jrnl: "_VoiceJournal"):
    """Enveloppe l'exécuteur d'outils pour consigner appels ET résultats.

    Sans les résultats, on ne peut pas distinguer « il a promis de noter » de
    « il a noté » : le 13/08, « Lilio c'est un homme » a reçu « promis je note »
    et rien n'a été écrit — il se trompait encore 90 minutes plus tard.
    """
    if not jrnl.actif:
        return executor

    async def _wrap(name: str, arguments: str) -> str:
        depart = time.monotonic()
        jrnl.write("tool_called", tool=name, args=str(arguments)[:500])
        try:
            result = await executor(name, arguments)
        except Exception as exc:
            jrnl.write("tool_result", tool=name, error=str(exc)[:300],
                       ms=int((time.monotonic() - depart) * 1000))
            raise
        jrnl.write("tool_result", tool=name, result=str(result)[:500],
                   ms=int((time.monotonic() - depart) * 1000))
        return result

    return _wrap


async def _answer(bot, text: str, *, requester: dict, speaker: str,
                  jrnl: Optional["_VoiceJournal"] = None) -> str:
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
    if jrnl is not None:
        executor = _traced_executor(executor, jrnl)

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


async def handle_voice_request(
    bot, discord_id: str, speaker: str, text: str, *,
    channel_id: Optional[int] = None, channel_name: str = "", stt_ms: float = 0.0,
) -> None:
    """Traite une phrase entendue en vocal. Ne lève jamais.

    Journalise le cycle complet (`logs/conversations/voice/{salon}/`) : la
    transcription source, qui parlait, les outils appelés AVEC leurs résultats,
    la réponse entière et les étapes de latence. Ce chemin passait auparavant
    en direct par l'API Twitch, sans laisser autre chose que 60 caractères dans
    `app.log` — impossible d'y voir qu'un « promis je note » n'avait rien noté.

    Les étapes de temps répondent à la question qui manquait : le délai perçu
    par le viewer court depuis la FIN DE LA PHRASE, pas depuis la fin de la
    transcription. `stt_ms` est donc compté dans le total.
    """
    depart = time.monotonic()
    jrnl: Optional[_VoiceJournal] = None
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

        jrnl = _VoiceJournal(bot, channel_id, channel_name)
        decide_ms = int((time.monotonic() - depart) * 1000)
        jrnl.write("message_in", kind="vocal", author=speaker,
                   author_id=str(discord_id or ""), content=text,
                   stt_ms=round(stt_ms), decide_ms=decide_ms)

        avant_llm = time.monotonic()
        reply = await _answer(bot, text, requester=requester, speaker=speaker, jrnl=jrnl)
        llm_ms = int((time.monotonic() - avant_llm) * 1000)
        if not reply:
            jrnl.write("gate_decision", kind="vocal", decision="silence",
                       reason="réponse vide du modèle", llm_ms=llm_ms)
            return
        twitch_bot = getattr(bot, "_twitch_bot", None) or getattr(bot, "twitch_bot", None)
        api = getattr(twitch_bot, "twitch_api", None)
        if api is None:
            jrnl.write("gate_decision", kind="vocal", decision="silence",
                       reason="API Twitch indisponible", llm_ms=llm_ms)
            return
        login = str(requester.get("twitch_login") or "").strip()
        avant_envoi = time.monotonic()
        publie = await api.send_message(f"@{login} {reply}" if login else reply)
        publish_ms = int((time.monotonic() - avant_envoi) * 1000)
        if not publie:
            # Helix rend 200 sans publier quand la chaîne filtre : sans ce
            # garde, le journal affirmait « Vocal → chat » pour une réponse que
            # le chat n'a jamais vue. `send_message` a déjà dit pourquoi.
            jrnl.write("gate_decision", kind="vocal", decision="silence",
                       reason="Helix a refusé de publier (is_sent=false)",
                       llm_ms=llm_ms, publish_ms=publish_ms)
            return
        logger.info("Vocal → chat : {who} « {t} »", who=login or speaker, t=reply[:60])
        jrnl.write(
            "message_out", kind="vocal", author=config.bot.name, content=reply,
            target=login or speaker, stt_ms=round(stt_ms), decide_ms=decide_ms,
            llm_ms=llm_ms, publish_ms=publish_ms,
            total_ms=int(stt_ms + (time.monotonic() - depart) * 1000),
        )
    except Exception as exc:  # noqa: BLE001 — une demande ratée ne casse pas l'écoute
        logger.warning("Demande vocale non traitée : {e}", e=exc)
        if jrnl is not None:
            jrnl.write("gate_decision", kind="vocal", decision="silence",
                       reason=f"demande non traitée : {exc}")


def journal_near_miss(bot, channel_id, channel_name: str, speaker: str,
                      text: str, names: list[str]) -> None:
    """Consigne un quasi-déclenchement vocal, quand il y en a un. Ne lève jamais.

    Le vrai raté — « le bot », « l'IA », « il » — reste indénombrable : aucune
    règle mécanique ne le voit. Ce qui est comptable, c'est le mot qui a FRÔLÉ
    son nom : c'est lui qui dit si la tolérance est trop serrée ou trop lâche,
    et c'est la seule mesure qu'on puisse rendre sans devinette.
    """
    try:
        verdict = address_match(text, names)
        if verdict.addressed or not verdict.word:
            return
        jrnl = _VoiceJournal(bot, channel_id, channel_name)
        if not jrnl.actif:
            return
        jrnl.write("voice_near_miss", speaker=speaker, content=text,
                   word=verdict.word, name=verdict.name, rule=verdict.rule,
                   distance=verdict.distance)
    except Exception as exc:  # noqa: BLE001 — un journal ne casse pas l'écoute
        logger.debug("Quasi-déclenchement vocal non consigné : {e}", e=exc)
