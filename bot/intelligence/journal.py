# bot/core/journal.py
from __future__ import annotations

import asyncio
import json
import re
import time
from collections import Counter
from datetime import date, datetime, timedelta, timezone
from io import BytesIO
from typing import TYPE_CHECKING, Any, Callable, Optional
from zoneinfo import ZoneInfo

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from loguru import logger

from bot.core.emotion import EMOTIONS
from bot.core.llm import FALLBACK_RESPONSE
from bot.intelligence.identity import render_identity
from bot.intelligence.memory.facts import FactStatus
from bot.intelligence.prompts import load_prompt

if TYPE_CHECKING:
    from bot.config import Config
    from bot.core.emotion import EmotionEngine
    from bot.intelligence.memory.service import MemoryService
    from bot.core.llm import BaseLLMClient

# Traduction des noms d'émotions internes (anglais) vers le français pour l'affichage
_EMOTION_FR = {
    "anger": "colère",
    "joy": "joie",
    "sadness": "tristesse",
    "curiosity": "curiosité",
    "boredom": "ennui",
}

_JOURNAL_SYSTEM = load_prompt(
    "journal_system",
    fallback=(
        "Tu es {{BOT_NAME}}, un bot de chat Discord. Chaque soir tu écris ton journal intime.\n\n"
        "Rédige une entrée de journal à la première personne, ton sincère, écriture relâchée. "
        "Respecte la consigne de longueur indiquée dans le contexte — n'étire jamais pour remplir."
    ),
    render=False,
)
_CHUNK_SYSTEM = load_prompt(
    "journal_chunk_system",
    fallback=(
        "Tu es le module de mémoire de {{BOT_NAME}}. Résume le bloc de messages en 5 à 10 lignes, "
        "texte brut, sans titre. Mentionne toujours qui a dit ou fait quoi par son pseudo exact."
    ),
    render=False,
)
_FINAL_SYSTEM = load_prompt(
    "journal_final_system",
    fallback=(
        "Tu es le module de mémoire de {{BOT_NAME}}. Synthétise les résumés en 10 à 20 lignes, "
        "texte brut, sans titre. Mentionne toujours qui a dit ou fait quoi par son pseudo exact."
    ),
    render=False,
)
_CLEANUP_SYSTEM = load_prompt(
    "memory_cleanup_system",
    fallback=(
        "Tu es le gestionnaire de mémoire long-terme de {{BOT_NAME}}. Analyse les souvenirs, "
        'identifie les périmés et à reformuler. Retourne un JSON : '
        '{"delete": [], "update": [], "questions": []}'
    ),
    render=False,
)
_NARRATIVE_SYNTHESIS_SYSTEM = load_prompt(
    "journal_narrative_synthesis_system",
    fallback=(
        "Tu reçois des entrées de journal de {{BOT_NAME}}. Produis une narrative thématique "
        "de 8 à 12 lignes texte brut sur les thèmes récurrents, absences et fils non résolus."
    ),
    render=False,
)
_JOURNAL_VOICE_PASS_SYSTEM = load_prompt(
    "journal_voice_pass_system",
    fallback=(
        "Tu reçois un brouillon de journal de {{BOT_NAME}}. Insuffle la vraie voix intérieure : "
        "auto-interruptions, flux non linéaire, pensée du soir honnête. "
        "Retourne le journal réécrit directement en markdown Discord."
    ),
    render=False,
)
_CHARS_PER_TOKEN = 4
_JOURNAL_TOKEN_THRESHOLD = 6000
_CHUNK_SIZE = 30
_DISCORD_LIMIT = 1900  # marge de sécurité sous la limite Discord de 2000

# ── Garde anti-répétition stylistique ──
# On ne code aucune tournure en dur : les ouvertures et expressions à éviter sont
# relevées dans les entrées précédentes, donc la garde suit la dérive réelle du style.
_STYLE_LOOKBACK_DAYS = 7
_NARRATIVE_DAYS = 4
_INCIPIT_SHORT_LINE = 40  # une 1re ligne plus courte que ça est une ouverture à elle seule
_INCIPIT_WORDS = 8
# Une expression revenue dans cette fraction des entrées est un tic, pas une voix
_PHRASE_MIN_RATIO = 0.7
_PHRASE_MIN_DOCS_FLOOR = 3  # plancher, pour ne rien signaler sur un historique trop mince
_PHRASE_MAX = 6
# Un n-gramme fait uniquement de mots-outils est de la grammaire, pas une signature.
# Les auxiliaires en font partie : « je suis » est inévitable dans un journal à la 1re personne.
_FUNCTION_WORDS = frozenset(
    """a ai as au aux avec c ce ces cet cette d dans de des du elle en es est et eu il ils
    j je l la le les leur lui ma mais me mes moi mon n ne nos notre nous on ont ou par pas
    pour qu que qui s sa se ses son sommes sont suis sur t ta te tes toi ton tu un une vos
    votre vous y à ça était étais été avait avais eu plus moins très bien tout tous toute
    toutes fait faire""".split()
)

_TZ_JOURNAL = ZoneInfo("Europe/Paris")

# APScheduler abandonne un déclenchement en retard de plus d'UNE seconde par
# défaut. Trois de ces jobs tirent à la même seconde et sont lourds (appels LLM,
# rendu matplotlib) : il suffisait que la boucle soit occupée à cet instant pour
# que la journée saute — 7 journées manquantes dans `journal_archive`, sans une
# trace, le logger stdlib d'APScheduler n'étant branché sur aucun handler.
# Une heure de retard vaut mieux qu'un journal perdu ; `coalesce` évite qu'un
# arrêt prolongé n'en rejoue plusieurs d'affilée.
_TOLERANCE_RETARD = {"misfire_grace_time": 3600, "coalesce": True}

# ── Passe de ménage mémoire (une personne par nuit) ───────────────────────────
#
# La réconciliation live de `MemoryIngest` n'attrape que les faits porteurs d'un
# triplet S-P-O valide ; le reste tombe en `memory.add()` verbatim, qui ne dédupe
# que le texte exact normalisé. Comme le fact_extractor repasse sur la fenêtre de
# conversation à chaque flush, il réémet le même fait reformulé toutes les ~40 s
# et les paraphrases s'empilent. Cette passe est le rattrapage : elle relit tous
# les souvenirs d'UNE personne d'un coup — seule position d'où deux formulations
# éloignées dans le temps sont visibles ensemble — et fait trancher le LLM.
_CLEANUP_MIN_FACTS = 5
# Taille d'un lot soumis au modèle. Mesuré sur les 298 souvenirs d'un utilisateur
# réel : envoyés d'un bloc, `deepseek-v4-flash` tronque sa réponse ET part en
# énumération mécanique (232 index sur 298 marqués à supprimer). En lots courts
# il analyse au lieu d'énumérer. Le tri chronologique fait tomber les paraphrases
# d'une même session dans le même lot, là où elles sont comparables.
_CLEANUP_BATCH_SIZE = 60
# Le rôle secondaire est câblé à 1000 tokens en sortie (config.yaml) : un verdict
# portant des dizaines d'index plus des reformulations est coupé en plein JSON.
_CLEANUP_MAX_OUTPUT_TOKENS = 4000
# Borne le coût d'une nuit sur un très gros stock (668 souvenirs = 12 appels).
# Les plus anciens d'abord : c'est là que les doublons ont eu le temps de dormir.
_CLEANUP_MAX_FACTS_PER_NIGHT = 300
# Un verdict qui rase presque tout n'est pas un ménage, c'est un dérapage : on le
# refuse en bloc plutôt que d'amputer quelqu'un. Le seuil est haut parce que le
# backlog l'est aussi — mesuré sur un lot réel, quinze lignes sur soixante
# disaient « joue à Valorant ». À 50 %, le garde-fou bloquait précisément les
# lots qui avaient le plus besoin d'être nettoyés.
_CLEANUP_MAX_DELETE_RATIO = 0.75
_CLEANUP_STATE_KEY = "memory_cleanup_last_pass"
# `wally:self` (auto-narratif, plusieurs Mo) déborde toute fenêtre de contexte et
# relève d'une autre dynamique ; `wally:emotes` n'est pas une personne.
_CLEANUP_EXCLUDED_USERS = frozenset({"wally:self", "wally:emotes"})

_EMOTION_COLORS = {
    "anger": "#ff3333",
    "joy": "#ffdd00",
    "curiosity": "#00ccff",
    "sadness": "#7777ff",
    "boredom": "#888888",
}


def _generate_emotion_chart(snapshots: list[dict]) -> BytesIO | None:
    """Generate a dark-themed emotion chart. Returns PNG as BytesIO, or None if < 2 snapshots."""
    if len(snapshots) < 2:
        return None

    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import matplotlib.dates as mdates

    times = [datetime.fromtimestamp(s["snapshot_at"], tz=_TZ_JOURNAL) for s in snapshots]

    fig, ax = plt.subplots(figsize=(10, 4))
    fig.patch.set_facecolor("#1a1a1a")
    ax.set_facecolor("#1a1a1a")

    for emotion in EMOTIONS:
        values = [max(0, min(100, s[emotion] * 100)) for s in snapshots]
        color = _EMOTION_COLORS.get(emotion, "#ffffff")
        label = _EMOTION_FR.get(emotion, emotion).capitalize()
        ax.plot(times, values, color=color, label=label, linewidth=2, clip_on=True)

    ax.set_ylim(0, 100)
    ax.set_clip_on(True)
    ax.set_ylabel("Intensité (%)", color="#aaaaaa", fontsize=10)
    ax.set_xlabel("")
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%Hh", tz=_TZ_JOURNAL))
    ax.tick_params(colors="#aaaaaa")
    ax.grid(True, color="#333333", linewidth=0.5, alpha=0.5)
    for spine in ax.spines.values():
        spine.set_color("#444444")

    ax.legend(loc="upper right", fontsize=9, facecolor="#1a1a1a", edgecolor="#444444", labelcolor="#ffffff")
    fig.tight_layout()

    buf = BytesIO()
    fig.savefig(buf, format="png", facecolor="#1a1a1a", dpi=100)
    plt.close(fig)
    buf.seek(0)
    return buf


def _get_length_guidance(message_count: int) -> str:
    """Consigne de longueur : un plafond, jamais un plancher.

    Un quota minimum force le remplissage, et le remplissage produit de la
    littérature — c'est les journées sans rien qui donnaient les entrées les plus
    brodées. Ici la longueur suit ce qu'il y a à dire.
    """
    if message_count < 10:
        return (
            "Il ne s'est presque rien passé aujourd'hui. Deux ou trois lignes suffisent, "
            "et c'est très bien — n'étire pas, n'invente pas de matière. 80 mots maximum."
        )
    if message_count < 50:
        return (
            "Journée peu chargée. Écris ce que tu as à dire, pas un mot de plus : "
            "si ça tient en quatre lignes, ça tient en quatre lignes. 200 mots maximum."
        )
    if message_count <= 150:
        return "Il y a eu de la matière aujourd'hui. 400 mots maximum, moins si tu as fait le tour."
    return "Grosse journée. 600 mots maximum, moins si tu as fait le tour."


_VOICE_DRAFT_MARKER = "Brouillon :"


def _budget_reecriture(brouillon: str) -> int:
    """Plafond de sortie du pass de dé-polissage, taillé sur le brouillon.

    Le pass réémet le texte entier — il ne rallonge jamais, mais il doit pouvoir
    tout redire. Le secondaire est configuré pour des réponses de chat (1000
    tokens le 2026-08-12) : un brouillon de jour chargé ne rentrait pas, et la
    sortie repartait coupée en pleine phrase. Deux tokens et demi par mot couvre
    le français avec sa marge d'accents et de ponctuation.
    """
    return max(1200, int(len(brouillon.split()) * 2.5))


def _voice_pass_invalide(sortie: str) -> str:
    """Motif de rejet du pass de dé-polissage, ou "" s'il a fait son travail.

    Le 2026-08-12, le secondaire a recopié son message d'entrée au lieu de le
    réécrire : la consigne de longueur, le relevé des ouvertures déjà usées et
    le marqueur du brouillon sont partis sur Discord puis en archive, où le
    lendemain les relit comme « ton journal d'hier ». La seule garde était
    « non vide et pas le repli » — elle laissait passer n'importe quel texte.
    """
    if not sortie or not sortie.strip() or sortie.strip() == FALLBACK_RESPONSE:
        return "repli du modèle"
    if _VOICE_DRAFT_MARKER in sortie:
        return "le message d'entrée recopié"
    # Une sortie amputée par le plafond de tokens s'arrête sur un mot nu. Un
    # journal fini s'arrête sur une ponctuation, un emoji ou un guillemet — même
    # quand il laisse une pensée en suspens.
    if sortie.rstrip()[-1:].isalnum():
        return "sortie coupée en pleine phrase"
    # Rien sur le raccourcissement en revanche : couper fort EST le travail du
    # pass. Les jours creux le plafond tombe à 80 mots, et un brouillon de 400
    # mots doit pouvoir repartir à 80 sans être pris pour une troncature.
    return ""


def _build_active_hours(messages: list[dict]) -> str:
    """Build human-readable active hour ranges from messages."""
    if not messages:
        return ""
    hours: set[int] = set()
    for m in messages:
        ts = m.get("timestamp", 0)
        if ts:
            hours.add(datetime.fromtimestamp(ts, tz=_TZ_JOURNAL).hour)
    if not hours:
        return ""
    sorted_hours = sorted(hours)
    ranges: list[str] = []
    start = prev = sorted_hours[0]
    for h in sorted_hours[1:]:
        if h - prev <= 1:
            prev = h
        else:
            ranges.append(f"{start}h-{prev + 1}h" if start != prev else f"{start}h")
            start = prev = h
    ranges.append(f"{start}h-{prev + 1}h" if start != prev else f"{start}h")
    return ", ".join(ranges)


def _build_stats_block(messages: list[dict]) -> str:
    """Repères de la journée : qui, quand, où — sans aucun compteur.

    Les comptes de messages et de participants finissaient récités tels quels
    (« 10 messages, 4 participants »). Le volume est déjà porté par la consigne
    de longueur ; ici on ne garde que ce qui aide à raconter.
    """
    if not messages:
        return ""
    authors = Counter(m["author"] for m in messages)
    active = _build_active_hours(messages)

    lines = ["Repères de la journée :"]
    if active:
        lines.append(f"- Moments d'activité : {active}")

    platforms = Counter(m.get("platform", "discord") for m in messages)
    if len(platforms) > 1:
        lines.append(
            "- Plateformes : " + ", ".join(p.capitalize() for p, _ in platforms.most_common())
        )

    lines.append(
        "- Qui était là, du plus bavard au moins bavard : "
        + ", ".join(name for name, _ in authors.most_common(5))
    )
    return "\n".join(lines)


def _emotion_phrase(emotion: str, value: float) -> str | None:
    """Intensité d'une émotion en mots. None sous le seuil de saillance (30%).

    Volontairement sans pourcentage : les relevés de capteur finissent recopiés
    tels quels dans le journal, ce qui ne veut rien dire pour qui le lit.
    """
    pct = int(value * 100)
    if pct < 30:
        return None
    name_fr = _EMOTION_FR.get(emotion, emotion)
    if pct >= 70:
        # « pic d'ennui », pas « pic de ennui »
        liaison = "d'" if name_fr[0] in "aeiouyéèêà" else "de "
        return f"pic {liaison}{name_fr}"
    # Tournures sans adjectif : « ennui » est masculin et les quatre autres
    # émotions sont féminines — un accord unique donnait « ennui montante ».
    if pct >= 50:
        return f"{name_fr} qui monte"
    return f"{name_fr} en fond"


def _build_emotion_arc(snapshots: list[dict]) -> str:
    """Construit l'arc émotionnel de la journée depuis les snapshots horaires.

    Retourne "" si moins de 2 snapshots (pas assez de données pour une narrative).
    """
    if len(snapshots) < 2:
        return ""
    lines = []
    for snap in snapshots:
        ts = datetime.fromtimestamp(snap["snapshot_at"], tz=_TZ_JOURNAL)
        parts = [
            phrase
            for emotion in ["anger", "joy", "sadness", "curiosity", "boredom"]
            if (phrase := _emotion_phrase(emotion, snap[emotion])) is not None
        ]
        if parts:
            lines.append(f"{ts.strftime('%Hh%M')} — {', '.join(parts)}")
        else:
            lines.append(f"{ts.strftime('%Hh%M')} — neutre")
    return "Arc émotionnel de la journée :\n" + "\n".join(lines)


def _emotion_tone_hint(emotions: dict) -> str:
    """Génère une directive de ton selon l'émotion dominante (≥ 0.30).

    Sans pourcentage : même dans une consigne d'écriture, un chiffre finit recopié
    dans l'entrée publiée (« une ligne droite à 100% »).
    """
    dominant = max(emotions, key=emotions.get)
    if emotions[dominant] < 0.30:
        return ""
    hints = {
        "anger": "Ce soir ta colère domine — entrée courte, cassante, quelques lignes suffisent.",
        "joy": "Ce soir tu es plutôt joyeux — tu peux te laisser aller, plus léger et spontané.",
        "sadness": "Ce soir ta tristesse domine — écriture plus lente, introspective, quelques silences.",
        "curiosity": "Ce soir ta curiosité domine — laisse-toi partir dans les digressions si l'envie t'en prend.",
        "boredom": "Ce soir c'est l'ennui qui domine — t'as pas forcément grand chose à dire, et c'est ok. Court et honnête.",
    }
    return hints.get(dominant, "")


def _naive_utc(dt: datetime | None) -> datetime:
    """Ramène une date en UTC naïf, qu'elle porte un fuseau ou non.

    `atomic_facts.created_at` mélange les deux formes : l'ingest écrit de l'ISO
    avec offset (`…+00:00`), les autres chemins de l'UTC naïf. Les trier tels
    quels lève « can't compare offset-naive and offset-aware datetimes ».
    """
    if dt is None:
        return datetime.min
    if dt.tzinfo is None:
        return dt
    return dt.astimezone(timezone.utc).replace(tzinfo=None)


def _significant_words(text: str) -> set[str]:
    """Mots porteurs de sens d'un souvenir (mots-outils écartés)."""
    mots = re.findall(r"\w+", (text or "").lower())
    return {m for m in mots if len(m) > 1 and m not in _FUNCTION_WORDS}


def _plausible_duplicate(a: str, b: str) -> bool:
    """Deux souvenirs peuvent-ils dire la même chose ?

    Un seul mot commun ne prouve rien : chaque souvenir s'ouvre sur le pseudo de
    la personne, donc tous en partagent au moins un. Mesuré en prod, c'est
    exactement l'erreur commise — « joue à League of Legends, classé Grand
    Clash » désigné comme doublon de « est le créateur de Wally », leur seul
    point commun étant « KingsRequin ». Deux formulations d'un même fait
    partagent forcément plus que ça.
    """
    return len(_significant_words(a) & _significant_words(b)) >= 2


def _entier(v) -> bool:
    """Un entier VRAI : en Python `bool` est sous-classe de `int`, et `True`
    passe donc `isinstance(v, int)` — puis `facts[True]` désigne `facts[1]`.
    Au niveau module : la garde était imbriquée dans `_justified_deletions`, ce
    qui l'a fait oublier sur le chemin de reformulation."""
    return isinstance(v, int) and not isinstance(v, bool)


def _justified_deletions(
    raw_delete, total: int, user_id: str, contents: list[str] | None = None
) -> set[int]:
    """Ne retient que les suppressions qui nomment un remplaçant valide.

    Chaque entrée doit être `{"index": n, "duplicate_of": m}` où m désigne le
    souvenir qui porte déjà l'information. Sans remplaçant nommé, pas de
    suppression : mesuré sur une liste DÉJÀ triée, `deepseek-v4-flash` proposait
    encore d'effacer 25 souvenirs sur 60, dont « héberge Wally sur son serveur
    personnel » — unique, sans aucun équivalent. La consigne écrite dans le
    prompt ne tient pas ; celle-ci est vérifiable.

    On remonte la chaîne des remplaçants jusqu'à un souvenir qui survit. Si elle
    boucle — deux souvenirs qui se désignent l'un l'autre — le plus petit index
    du cycle sert de survivant : sans ça les deux s'effaceraient et
    l'information serait perdue au lieu d'être dédupliquée.
    """
    proposed: dict[int, int] = {}
    refused = 0
    for item in raw_delete:
        if not isinstance(item, dict):
            refused += 1
            continue
        idx, src = item.get("index"), item.get("duplicate_of")
        if (
            not _entier(idx) or not _entier(src)
            or not 0 <= idx < total or not 0 <= src < total or idx == src
        ):
            refused += 1
            continue
        if contents is not None and not _plausible_duplicate(contents[idx], contents[src]):
            logger.info(
                "Memory cleanup {u}: « {a} » n'est pas un doublon de « {b} », gardé",
                u=user_id, a=contents[idx][:60], b=contents[src][:60],
            )
            refused += 1
            continue
        proposed[idx] = src

    kept: set[int] = set()
    for idx in sorted(proposed):
        chain = {idx}
        src = proposed[idx]
        while src in proposed and src not in chain:
            chain.add(src)
            src = proposed[src]
        if src in chain and idx == min(chain):
            continue  # survivant désigné du cycle
        kept.add(idx)

    refused += len(proposed) - len(kept)
    if refused:
        logger.info(
            "Memory cleanup {u}: {n} suppression(s) sans remplaçant valide, ignorées",
            u=user_id, n=refused,
        )
    return kept


def _parse_cleanup_verdict(raw: str) -> dict | None:
    """Lit le JSON du verdict de ménage. None si illisible — on ne touche à rien.

    Le modèle secondaire enrobe volontiers sa réponse d'un ```json ou d'une
    phrase de politesse ; on récupère le premier objet accolades comprises.
    """
    if not isinstance(raw, str):
        return None
    fence = re.search(r"```(?:json)?\s*(.*?)\s*```", raw, re.DOTALL)
    text = fence.group(1) if fence else raw
    obj = re.search(r"\{.*\}", text, re.DOTALL)
    if not obj:
        return None
    try:
        data = json.loads(obj.group())
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, dict) else None


def _journal_body(content: str) -> str:
    """Retire les titres markdown : la structure imposée ne doit pas compter comme un tic."""
    return "\n".join(
        line for line in content.splitlines() if not line.lstrip().startswith("#")
    )


def _extract_incipit(content: str) -> str:
    """Ouverture d'une entrée : la 1re ligne si elle tient seule, sinon ses premiers mots."""
    for line in _journal_body(content).splitlines():
        line = line.strip()
        if not line:
            continue
        if len(line) <= _INCIPIT_SHORT_LINE:
            return line
        words = line.split()
        return " ".join(words[:_INCIPIT_WORDS]) + "…"
    return ""


def _detect_overused_phrases(journals: list[dict]) -> list[str]:
    """Expressions de 2-3 mots revenues dans la majorité des entrées récentes.

    Les tics ne sont jamais listés en dur : ils émergent du corpus des entrées passées,
    donc la garde suit la dérive réelle du style au lieu d'une liste noire figée.
    """
    threshold = max(_PHRASE_MIN_DOCS_FLOOR, round(_PHRASE_MIN_RATIO * len(journals)))
    if len(journals) < threshold:
        return []

    doc_freq: Counter[str] = Counter()
    for entry in journals:
        words = re.findall(r"[a-zà-öø-ÿ]+", _journal_body(entry.get("content") or "").lower())
        seen: set[str] = set()
        for size in (2, 3):
            for i in range(len(words) - size + 1):
                gram = words[i : i + size]
                # Que des mots-outils → tournure grammaticale banale, pas une signature
                if all(w in _FUNCTION_WORDS for w in gram):
                    continue
                seen.add(" ".join(gram))
        doc_freq.update(seen)

    hits = [g for g, n in doc_freq.most_common() if n >= threshold]
    # Un 2-mots contenu dans un 3-mots retenu fait doublon — on garde le plus long
    longest = [g for g in hits if len(g.split()) == 3]
    kept = longest + [
        g for g in hits if len(g.split()) == 2 and not any(g in l for l in longest)
    ]
    return kept[:_PHRASE_MAX]


def _build_style_avoidance_block(journals: list[dict]) -> str:
    """Relevé de ce que les entrées récentes ont déjà usé — ouvertures et expressions.

    La consigne vise la formule, jamais la posture : sans cette nuance, s'adresser
    au journal (« cher journal », « tu sais ») serait relevé comme un tic au bout
    de quelques soirs, et Wally cesserait de lui parler.
    """
    if not journals:
        return ""
    incipits = list(
        dict.fromkeys(i for i in (_extract_incipit(j.get("content") or "") for j in journals) if i)
    )
    phrases = _detect_overused_phrases(journals)
    if not incipits and not phrases:
        return ""

    lines = [
        "Ce que tes entrées récentes ont déjà usé. Continue de parler à ton journal — "
        "c'est la formule qu'il faut changer, pas la façon de t'adresser à lui :"
    ]
    if incipits:
        lines.append("- Ouvertures déjà utilisées : " + " / ".join(f'"{i}"' for i in incipits))
        lines.append("  Aborde-le autrement ce soir.")
    if phrases:
        lines.append("- Expressions trop revenues : " + ", ".join(f'"{p}"' for p in phrases))
        lines.append("  Dis la même chose avec une autre construction, sans les remplacer par un tic neuf.")
    return "\n".join(lines)


def _split_for_discord(text: str, limit: int = _DISCORD_LIMIT) -> list[str]:
    """Découpe le texte en blocs ≤ limit caractères sur des coupures naturelles."""
    if len(text) <= limit:
        return [text]

    chunks: list[str] = []
    current = ""
    for para in text.split("\n\n"):
        candidate = (current + "\n\n" + para) if current else para
        if len(candidate) <= limit:
            current = candidate
        else:
            if current:
                chunks.append(current)
            if len(para) > limit:
                # Découpe forcée si un seul paragraphe dépasse la limite
                while len(para) > limit:
                    chunks.append(para[:limit])
                    para = para[limit:]
                current = para
            else:
                current = para
    if current:
        chunks.append(current)
    return chunks if chunks else [text]


class DailyJournal:
    def __init__(
        self,
        config: "Config",
        llm: "BaseLLMClient",
        llm_secondary: "BaseLLMClient",
        emotion: "EmotionEngine",
        memory: "MemoryService",
        db=None,
    ):
        self._config = config
        self._llm = llm
        self._llm_secondary = llm_secondary
        self._emotion = emotion
        self._memory = memory
        self._db = db
        self._send_cb: Optional[Callable[..., Any]] = None
        self._fetch_history_cb: Optional[Callable[..., Any]] = None
        self._bg_tasks: set[asyncio.Task] = set()
        self._consolidator = None
        self._user_modeler = None

    def set_consolidator(self, consolidator) -> None:
        """Injecte le MemoryConsolidator lancé par le cron nocturne."""
        self._consolidator = consolidator

    def set_user_modeler(self, user_modeler) -> None:
        """Injecte le UserModeler lancé par le cron nocturne."""
        self._user_modeler = user_modeler

    def set_send_callback(self, cb: Callable[..., Any]) -> None:
        """Inject an async callable: async def send(text: str) -> None"""
        self._send_cb = cb

    def set_history_callback(self, cb: Callable[..., Any]) -> None:
        """Inject an async callable: async def fetch_history() -> list[dict]
        Appelé quand daily_log est vide pour lire l'historique Discord du jour."""
        self._fetch_history_cb = cb

    async def run_memory_cleanup(self) -> None:
        """Maintenance mémoire quotidienne : péremption des éphémères, puis tri
        des doublons chez UNE personne (rotation, la moins récemment triée)."""
        try:
            await self._memory.cleanup_expired_facts()
        except Exception as exc:
            logger.warning("Memory cleanup failed: {e}", e=exc)

        # `cleanup_old_questions` existait depuis le début et n'était branchée
        # sur AUCUN cron : les questions en attente s'accumulaient sans fin et
        # repassaient au prompt chaque nuit (45 en base, dont 44 périmées).
        if self._db is not None:
            try:
                n = await self._db.cleanup_old_questions()
                if n:
                    logger.info("Ménage mémoire : {n} question(s) périmée(s) retirée(s)", n=n)
            except Exception as exc:
                logger.warning("Ménage des questions mémoire échoué : {e}", e=exc)

        # Repli des doublons EXACTS avant le tri LLM, et sur TOUT LE MONDE.
        # Le tri qui suit ne voit qu'une personne par nuit, par lots de 25 : deux
        # copies mot pour mot séparées dans deux lots ne se croisent jamais. Ici
        # rien n'est arbitré — deux textes identiques se replient sans LLM, donc
        # sans coût et sans limite de portée.
        store = getattr(self._memory, "fact_store", None)
        if store is not None:
            try:
                await store.merge_exact_duplicates()
            except Exception as exc:
                logger.warning("Ménage mémoire : repli des doublons exacts échoué : {e}", e=exc)

        try:
            await self._sort_one_user_memory()
        except Exception as exc:
            logger.warning("Memory cleanup: tri LLM échoué : {e}", e=exc)

    async def _sort_one_user_memory(self) -> None:
        """Relit tous les souvenirs d'une personne et applique le verdict du LLM.

        Une seule personne par nuit : le tri demande de voir TOUS ses souvenirs
        d'un coup (deux paraphrases peuvent être séparées de six semaines), donc
        un appel par personne, et un coût qui reste plat quel que soit le nombre
        d'utilisateurs connus.
        """
        store = getattr(self._memory, "fact_store", None)
        if store is None or self._db is None:
            return

        counts = await store.count_all_by_user()
        user_id = await self._pick_user_to_sort(counts)
        if user_id is None:
            logger.debug("Memory cleanup: aucun utilisateur à trier ce soir")
            return

        # Le passage est noté quoi qu'il arrive. Si on ne le notait qu'en cas de
        # succès, une personne dont le tri plante systématiquement (LLM en panne,
        # verdict jamais lisible, stock retombé sous le seuil) resterait la moins
        # récemment triée pour toujours et monopoliserait le cron : plus personne
        # d'autre ne serait jamais nettoyé. Un tour perdu se rattrape, pas un
        # blocage définitif.
        try:
            await self.sort_user_memory(user_id)
        finally:
            await self._remember_sorted_user(user_id, counts)

    async def sort_user_memory(self, user_id: str) -> bool:
        """Trie les souvenirs d'UNE personne nommée. Retourne True si le LLM a
        tranché (donc si le passage compte pour la rotation).

        Public : le script de rattrapage `scripts/menage_doublons_memoire.py`
        boucle dessus pour rejouer la passe sur tout le monde d'un coup, sans
        rejouer une deuxième implémentation du même tri.
        """
        store = getattr(self._memory, "fact_store", None)
        if store is None or self._db is None:
            return False

        facts = await store.get_by_user(user_id)
        if len(facts) < _CLEANUP_MIN_FACTS:
            return False

        # Ordre chronologique. Deux raisons : le prompt arbitre les doublons à la
        # date, et les paraphrases naissent en rafale dans une même session — les
        # trier par date les fait tomber dans le même lot, là où elles sont
        # comparables.
        facts.sort(key=lambda f: _naive_utc(f.created_at))
        if len(facts) > _CLEANUP_MAX_FACTS_PER_NIGHT:
            logger.info(
                "Memory cleanup {u}: {t} souvenirs, seuls les {n} plus anciens "
                "sont triés ce soir", u=user_id, t=len(facts), n=_CLEANUP_MAX_FACTS_PER_NIGHT,
            )
            facts = facts[:_CLEANUP_MAX_FACTS_PER_NIGHT]

        pending = await self._db.get_all_pending_questions(user_id)
        pending_block = ""
        if pending:
            pending_block = "\n\nQuestions déjà en attente (ne pas recréer) :\n" + "\n".join(
                f"- {q['question']}" for q in pending
            )
        system = _CLEANUP_SYSTEM.replace(
            "{date}", datetime.now(_TZ_JOURNAL).strftime("%d/%m/%Y")
        )

        tranche = False
        for start in range(0, len(facts), _CLEANUP_BATCH_SIZE):
            batch = facts[start : start + _CLEANUP_BATCH_SIZE]
            if await self._sort_batch(store, user_id, batch, system, pending_block):
                tranche = True
        return tranche

    async def _sort_batch(
        self, store, user_id: str, batch: list, system: str, pending_block: str
    ) -> bool:
        """Soumet un lot au LLM. Les index du verdict sont LOCAUX au lot."""
        lines = []
        for i, fact in enumerate(batch):
            day = fact.created_at.strftime("%Y-%m-%d") if fact.created_at else "?"
            lines.append(f"{i}. [{day}] {fact.content}")

        raw = await self._llm_secondary.complete(
            system,
            [{"role": "user", "content": "\n".join(lines) + pending_block}],
            purpose="memory_cleanup",
            max_tokens=_CLEANUP_MAX_OUTPUT_TOKENS,
        )
        verdict = _parse_cleanup_verdict(raw)
        if verdict is None:
            logger.warning(
                "Memory cleanup {u}: verdict illisible sur un lot de {n}, rien appliqué",
                u=user_id, n=len(batch),
            )
            return False

        await self._apply_cleanup_verdict(store, user_id, batch, verdict)
        return True

    async def _pick_user_to_sort(self, counts: dict[str, int]) -> str | None:
        """La personne triée il y a le plus longtemps ; jamais triée passe devant.

        À volume égal et ancienneté égale, le plus gros stock d'abord — c'est là
        que les doublons coûtent le plus au budget de contexte.
        """
        candidates = {
            uid: n
            for uid, n in counts.items()
            if n >= _CLEANUP_MIN_FACTS and uid not in _CLEANUP_EXCLUDED_USERS
        }
        if not candidates:
            return None
        try:
            last = json.loads(await self._db.get_state(_CLEANUP_STATE_KEY) or "{}")
        except (json.JSONDecodeError, TypeError):
            last = {}
        if not isinstance(last, dict):
            last = {}
        # "" trie avant toute date ISO : jamais trié = priorité maximale.
        return min(candidates, key=lambda u: (last.get(u, ""), -candidates[u]))

    async def _remember_sorted_user(self, user_id: str, counts: dict[str, int]) -> None:
        """Note le passage pour que la rotation avance. Les utilisateurs disparus
        sont oubliés au passage — sinon l'état grossit sans fin."""
        try:
            last = json.loads(await self._db.get_state(_CLEANUP_STATE_KEY) or "{}")
        except (json.JSONDecodeError, TypeError):
            last = {}
        if not isinstance(last, dict):
            last = {}
        last = {u: ts for u, ts in last.items() if u in counts}
        last[user_id] = datetime.now(_TZ_JOURNAL).isoformat()
        await self._db.set_state(_CLEANUP_STATE_KEY, json.dumps(last))

    async def _apply_cleanup_verdict(
        self, store, user_id: str, facts: list, verdict: dict
    ) -> None:
        """Applique reformulations puis archivages. Les index hors bornes sont
        ignorés, un effacement massif est refusé en bloc."""
        updated = 0
        for item in verdict.get("update") or []:
            if not isinstance(item, dict):
                continue
            idx, new_text = item.get("index"), (item.get("new_text") or "").strip()
            # `_entier` : en Python `bool` est sous-classe de `int`, donc
            # `idx = True` passait `isinstance(idx, int)` et `facts[True]`
            # désigne `facts[1]` — un verdict LLM malformé réécrivait
            # silencieusement le DEUXIÈME souvenir du lot. La garde existait
            # déjà côté suppression (`_justified_deletions`), elle avait été
            # oubliée ici, où aucun contrôle de plausibilité ne rattrape.
            if not _entier(idx) or not 0 <= idx < len(facts) or not new_text:
                continue
            if await store.update_content(facts[idx].id, new_text):
                updated += 1

        targets = _justified_deletions(
            verdict.get("delete") or [], len(facts), user_id,
            contents=[f.content or "" for f in facts],
        )
        if len(targets) > _CLEANUP_MAX_DELETE_RATIO * len(facts):
            logger.warning(
                "Memory cleanup {u}: verdict aberrant ({d}/{t} souvenirs à effacer), "
                "archivage refusé", u=user_id, d=len(targets), t=len(facts),
            )
            targets = set()

        for idx in targets:
            await store.set_status(facts[idx].id, FactStatus.ARCHIVED)

        questions = 0
        for q in verdict.get("questions") or []:
            if not isinstance(q, dict):
                continue
            text = (q.get("question") or "").strip()
            if not text:
                continue
            priority = q.get("priority") if q.get("priority") in ("high", "medium", "low") else "medium"
            await self._db.insert_memory_question(user_id, "", text, priority)
            questions += 1

        logger.info(
            "Memory cleanup {u}: {t} souvenirs relus → {d} archivés, {up} reformulés, "
            "{q} question(s)", u=user_id, t=len(facts), d=len(targets), up=updated, q=questions,
        )

    async def generate_and_send(self, archive: bool = True, target_date: date | None = None) -> None:
        channel_id = self._config.bot.journal_channel_id
        if not channel_id:
            logger.warning("No journal_channel_id configured, skipping journal")
            return

        # target_date=None → aujourd'hui (comportement normal du cron)
        effective_date = target_date or self._today_date()
        is_backfill = target_date is not None
        display_date = effective_date.strftime("%d/%m/%Y")

        logger.info("Generating daily journal for {d}...", d=effective_date.isoformat())

        # Source 1 : daily_log SQLite (survit aux redémarrages, toutes plateformes)
        if self._db is not None:
            try:
                if is_backfill:
                    db_messages = await self._db.get_messages_for_date(effective_date)
                else:
                    db_messages = await self._db.get_today_messages()
            except Exception as exc:
                logger.warning("Failed to get daily_log messages: {e}", e=exc)
                db_messages = []
        else:
            db_messages = []

        # Source 2 : Discord channel history (lecture API, toute la journée)
        if not db_messages and not is_backfill and self._fetch_history_cb is not None:
            try:
                db_messages = await self._fetch_history_cb()
                if db_messages:
                    logger.info(
                        "Journal: using Discord history fallback ({n} messages)",
                        n=len(db_messages),
                    )
            except Exception as exc:
                logger.warning("Journal Discord history fallback failed: {e}", e=exc)
                db_messages = []

        # Source 3 : fenêtres RAM (depuis le dernier démarrage)
        ram_messages = self._memory.get_all_contexts()
        all_messages = db_messages if db_messages else ram_messages
        if not db_messages and ram_messages:
            logger.info("Journal: using RAM context fallback ({n} messages)", n=len(ram_messages))

        if all_messages:
            context_text = await self._build_context_text(all_messages)
        else:
            # Source 4 : souvenirs de tous les utilisateurs connus
            context_text = await self._build_memory_fallback_context()
            if not context_text:
                logger.warning("Journal: all sources empty — generating with no conversation context")
                context_text = "Pas grand chose de notable aujourd'hui."

        # ── Stats block (F4, F8) ──
        stats_block = _build_stats_block(all_messages) if all_messages else ""

        # ── Longueur guidée par la matière du jour (F1) ──
        length_guidance = _get_length_guidance(len(all_messages) if all_messages else 0)

        # ── Midnight timestamp for date-based queries ──
        midnight = datetime.combine(
            effective_date, datetime.min.time(), tzinfo=_TZ_JOURNAL
        ).timestamp()
        end_of_day = midnight + 86400

        # ── Emotion peaks (F5) ──
        peaks_block = ""
        if self._db is not None:
            try:
                all_peaks = await self._db.get_emotion_peaks_since(midnight)
                peaks = [p for p in all_peaks if p["timestamp"] < end_of_day] if is_backfill else all_peaks
                if peaks:
                    peak_lines = []
                    for p in peaks:
                        ts = datetime.fromtimestamp(p["timestamp"], tz=_TZ_JOURNAL)
                        name_fr = _EMOTION_FR.get(p["emotion"], p["emotion"])
                        user = p.get("trigger_user") or "inconnu"
                        msg = p.get("trigger_message") or ""
                        msg_short = msg[:80] + "…" if len(msg) > 80 else msg
                        peak_lines.append(
                            f"- {ts.strftime('%Hh%M')} — pic de {name_fr} "
                            f"déclenché par {user} : \"{msg_short}\""
                        )
                    peaks_block = "Moments forts émotionnels :\n" + "\n".join(peak_lines)
            except Exception as exc:
                logger.warning("Failed to get emotion peaks for journal: {e}", e=exc)

        # ── Emotion arc ──
        try:
            all_snapshots = await self._db.get_emotion_snapshots_since(midnight) if self._db else []
            snapshots = [s for s in all_snapshots if s["snapshot_at"] < end_of_day] if is_backfill else all_snapshots
        except Exception as exc:
            logger.warning("Failed to get emotion snapshots for journal: {e}", e=exc)
            snapshots = []

        arc = _build_emotion_arc(snapshots)

        # ── Comparative emotion weather (F9) ──
        weather_block = ""
        if self._db is not None:
            try:
                week_avgs = await self._db.get_emotion_averages(time.time() - 7 * 86400)
                day_avgs = await self._db.get_emotion_averages(midnight)
                if week_avgs and day_avgs:
                    diffs = []
                    for emotion in ["anger", "joy", "sadness", "curiosity", "boredom"]:
                        delta = day_avgs[emotion] - week_avgs[emotion]
                        if abs(delta) >= 0.10:
                            name_fr = _EMOTION_FR.get(emotion, emotion)
                            ampleur = "nettement" if abs(delta) >= 0.25 else "un peu"
                            direction = "plus haute que d'habitude" if delta > 0 else "en baisse"
                            diffs.append(f"{name_fr} {ampleur} {direction}")
                    if diffs:
                        weather_block = "Comparé à la semaine : " + ", ".join(diffs)
            except Exception as exc:
                logger.warning("Failed to compute emotion weather: {e}", e=exc)

        # ── Yesterday's journal (F6) ──
        yesterday_block = ""
        if self._db is not None:
            try:
                yesterday = await self._db.get_yesterday_journal(today=effective_date.isoformat())
                if yesterday:
                    yesterday_block = f"Ton journal d'hier :\n{yesterday['content']}"
            except Exception as exc:
                logger.warning("Failed to get yesterday's journal: {e}", e=exc)

        # ── Habitués sans nouvelles : matière à continuité d'un soir à l'autre ──
        missing_block = ""
        if self._db is not None:
            try:
                missing = await self._db.get_missing_regulars()
                if missing:
                    missing_block = "Sans nouvelles depuis un moment : " + ", ".join(
                        f"{m['username']} ({m['days']} jours)" for m in missing
                    )
            except Exception as exc:
                logger.warning("Failed to get missing regulars: {e}", e=exc)

        # ── Entrées précédentes : synthèse narrative + garde anti-répétition stylistique ──
        past_journals: list[dict] = []
        if self._db is not None:
            try:
                past_journals = await self._db.get_journals_last_n_days(
                    n=_STYLE_LOOKBACK_DAYS, before_date=effective_date.isoformat()
                )
            except Exception as exc:
                logger.warning("Failed to load past journals: {e}", e=exc)

        style_block = _build_style_avoidance_block(past_journals)

        narrative_block = ""
        recent_journals = past_journals[-_NARRATIVE_DAYS:]
        if len(recent_journals) >= 2:
            try:
                combined = "\n\n---\n\n".join(
                    f"[{j['date']}]\n{j['content']}" for j in recent_journals
                )
                result = await self._llm_secondary.complete(
                    render_identity(_NARRATIVE_SYNTHESIS_SYSTEM),
                    [{"role": "user", "content": combined}],
                    purpose="journal_narrative_synthesis",
                )
                if result and result != FALLBACK_RESPONSE:
                    narrative_block = result
            except Exception as exc:
                logger.warning("Failed to build journal narrative synthesis: {e}", e=exc)

        # ── Gallery of the day ──
        gallery_block = ""
        if self._db is not None:
            try:
                today_images = await self._db.get_gallery_images_for_date(effective_date.isoformat())
                if today_images:
                    lines = [f"**Galerie du jour** : {len(today_images)} images"]
                    for img in today_images:
                        title = img.get("title") or "Sans titre"
                        username = img.get("username") or "inconnu"
                        votes = img.get("votes", 0)
                        lines.append(f'- "{title}" par {username} ({votes} 🔥)')
                    gallery_block = "\n".join(lines)
            except Exception as exc:
                logger.warning("Failed to get gallery images for journal: {e}", e=exc)

        # ── Twitch visits of the day ──
        twitch_visits_block = ""
        if self._db is not None:
            try:
                visits = await self._db.get_twitch_visits_for_date(effective_date.isoformat())
                if visits:
                    lines = [f"**Visites Twitch du jour** : {len(visits)} chaîne(s)"]
                    for v in visits:
                        dur = f"{v['duration_s'] // 60} min" if v.get("duration_s") else "durée inconnue"
                        lines.append(f"- {v['channel']} ({dur}) : {v.get('summary') or '...'}")
                    twitch_visits_block = "\n".join(lines)
            except Exception as exc:
                logger.warning("Failed to get twitch visits for journal: {e}", e=exc)

        # ── Current emotion state ──
        emotions = self._emotion.get_state()
        salient = [p for k, v in emotions.items() if (p := _emotion_phrase(k, v)) is not None]
        emotions_text = ", ".join(salient) if salient else "rien de très marqué"

        # ── Build user prompt ──
        sections = [
            length_guidance,
        ]
        if stats_block:
            sections.append(stats_block)
        sections.append(f"Voici un résumé de la journée :\n\n{context_text}")
        if peaks_block:
            sections.append(peaks_block)
        if arc:
            sections.append(arc)
        if weather_block:
            sections.append(weather_block)
        sections.append(f"Ton état émotionnel actuel : {emotions_text}")
        if yesterday_block:
            sections.append(yesterday_block)
        if narrative_block:
            sections.append(f"Ce que tu as vécu cette semaine :\n\n{narrative_block}")
        if missing_block:
            sections.append(missing_block)
        if gallery_block:
            sections.append(gallery_block)
        if twitch_visits_block:
            sections.append(twitch_visits_block)
        hint = _emotion_tone_hint(emotions)
        if hint:
            sections.append(hint)
        if style_block:
            sections.append(style_block)
        if is_backfill:
            sections.append(f"Écris ton journal intime pour le {display_date}.")
        else:
            sections.append("Écris ton journal intime pour aujourd'hui.")

        user_msg = "\n\n".join(sections)

        # ── Generate with primary model (F11) ──
        journal_text = await self._llm.complete(
            render_identity(_JOURNAL_SYSTEM),
            [{"role": "user", "content": user_msg}],
            purpose="daily_journal",
        )

        # `complete()` ne lève pas : il rend FALLBACK_RESPONSE. Sans ce garde, le
        # message d'excuse était publié, archivé, puis relu le lendemain comme
        # « ton journal d'hier » et intégré à la synthèse narrative — 15 journées
        # perdues entre le 2026-05-16 et le 2026-06-02.
        if not journal_text or not journal_text.strip() or journal_text.strip() == FALLBACK_RESPONSE:
            logger.warning(
                "Journal du {d} : le modèle n'a rien produit (repli) — rien publié ni archivé",
                d=effective_date.isoformat(),
            )
            return

        # ── Voice pass — dé-polit le brouillon et le ramène sous le plafond ──
        if journal_text:
            try:
                # La consigne de longueur voyage avec le brouillon : sans elle, le
                # pass n'a aucun moyen de savoir qu'il doit couper. Étiquetée,
                # parce qu'elle est écrite comme une phrase de journal : nue en
                # tête de message, « Grosse journée. » repartait en ouverture.
                voice_sections = [f"Consigne de longueur — ne la recopie pas : {length_guidance}"]
                if style_block:
                    voice_sections.append(style_block)
                voice_sections.append(f"{_VOICE_DRAFT_MARKER}\n{journal_text}")
                voice_input = "\n\n---\n\n".join(voice_sections)
                voice_result = await self._llm_secondary.complete(
                    render_identity(_JOURNAL_VOICE_PASS_SYSTEM),
                    [{"role": "user", "content": voice_input}],
                    purpose="journal_voice_pass",
                    # Le secondaire sert d'abord aux réponses de chat : son plafond
                    # de sortie (1000 tokens) ne tient pas les 600 mots d'un jour
                    # chargé. Le pass ne rallonge jamais, donc le brouillon donne
                    # la borne haute de ce qu'il a à réémettre.
                    max_tokens=_budget_reecriture(journal_text),
                )
                motif = _voice_pass_invalide(voice_result)
                if motif:
                    logger.warning(
                        "Journal : pass de dé-polissage écarté ({m}) — brouillon conservé",
                        m=motif,
                    )
                else:
                    journal_text = voice_result
            except Exception as exc:
                logger.warning("Journal voice pass failed: {e}", e=exc)

        # ── Emotion chart image (F10) ──
        # En thread : l'import de matplotlib puis le rendu du PNG sont du
        # CPU-bound synchrone, et bloquaient toute la boucle — Discord, Twitch,
        # dashboard, ticks cognitifs — pendant plusieurs centaines de ms à
        # quelques secondes. Aggravant : c'est la minute où trois autres jobs
        # lourds sont planifiés (journal, consolidation, modélisation), et le
        # `misfire_grace_time` d'APScheduler vaut 1 s par défaut.
        # Protégé : le graphe est un BONUS, il arrive après la génération du
        # texte et donc après tout le coût LLM déjà payé. Une police manquante
        # ou un backend matplotlib capricieux faisait perdre l'entière journée
        # de journal — texte compris — au lieu de la publier sans son image.
        chart_buf = None
        if snapshots:
            try:
                chart_buf = await asyncio.to_thread(_generate_emotion_chart, snapshots)
            except Exception as exc:  # noqa: BLE001 — le journal passe sans graphe
                logger.warning("Journal : graphe des émotions non rendu : {e}", e=exc)

        formatted = f"# Journal de {self._config.bot.name} — {display_date}\n\n{journal_text}"
        if self._send_cb:
            for chunk in _split_for_discord(formatted):
                await self._send_cb(chunk)
            if chart_buf:
                await self._send_cb("# Historique de mes émotions", file=chart_buf)
            logger.info("Daily journal sent to channel {ch}", ch=channel_id)
        else:
            logger.warning("No send callback set for journal — generated but not sent")

        # ── Archive (F6) ──
        if archive and self._db is not None:
            try:
                word_count = len(journal_text.split())
                # Save emotion chart PNG to disk if available
                chart_path: str | None = None
                if chart_buf is not None:
                    from pathlib import Path
                    charts_dir = Path("data/journal_charts")
                    charts_dir.mkdir(parents=True, exist_ok=True)
                    chart_file = charts_dir / f"{effective_date.isoformat()}.png"
                    chart_buf.seek(0)
                    chart_file.write_bytes(chart_buf.read())
                    chart_path = str(chart_file)
                await self._db.insert_journal(
                    effective_date.isoformat(), journal_text, word_count, chart_path,
                )
                logger.info("Journal archived ({n} words)", n=word_count)
            except Exception as exc:
                logger.warning("Failed to archive journal: {e}", e=exc)

        # ── Topic formation (fire-and-forget) ──
        if self._db is not None:
            self._fire(self._form_topics(context_text))

    def _fire(self, coro) -> asyncio.Task:
        """Fire-and-forget with strong reference to prevent GC cancellation."""
        t = asyncio.create_task(coro)
        self._bg_tasks.add(t)
        t.add_done_callback(self._bg_tasks.discard)
        return t

    _TOPIC_SCHEMA = {
        "type": "object",
        "properties": {
            "topics": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string"},
                        "summary": {"type": "string"},
                        "participants": {"type": "array", "items": {"type": "string"}},
                        "opinion": {"type": "string"},
                    },
                    "required": ["name", "opinion"],
                },
            }
        },
        "required": ["topics"],
    }

    async def _form_topics(self, summary_text: str) -> None:
        """Analyse le résumé du jour et forme/met à jour les sujets de communauté."""
        try:
            existing = await self._db.get_topics(limit=15)
            known = ", ".join(t["name"] for t in existing) or "(aucun)"
            payload = (
                f"Sujets déjà connus (réutilise ces noms si pertinent) : {known}\n\n"
                f"Résumé du jour :\n{summary_text}"
            )
            result = await self._llm_secondary.complete_structured(
                load_prompt("topic_formation"),
                [{"role": "user", "content": payload}],
                self._TOPIC_SCHEMA,
                schema_name="topics",
                purpose="topic_formation",
            )
            for item in (result.get("topics") or [])[:3]:
                name = (item.get("name") or "").strip()
                opinion = (item.get("opinion") or "").strip()
                if not name or not opinion:
                    continue
                summary = (item.get("summary") or "").strip()
                participants = []
                for pseudo in item.get("participants") or []:
                    pseudo = (pseudo or "").strip()
                    if not pseudo:
                        continue
                    uid = self._memory._alias_cache.get(f"nickname:{pseudo.lower()}")
                    participants.append({"name": pseudo, "uid": uid})
                await self._db.upsert_topic(name, summary, participants, opinion)
                logger.info("Topic formed: {n}", n=name)
            await self._db.cleanup_topics()
        except Exception as exc:  # noqa: BLE001 — non-fatal
            logger.warning("Topic formation failed: {e}", e=exc)

    async def _build_context_text(self, messages: list[dict]) -> str:
        total_chars = sum(len(m["content"]) for m in messages)
        if total_chars / _CHARS_PER_TOKEN < _JOURNAL_TOKEN_THRESHOLD:
            return "\n".join(f"[{m['author']}]: {m['content']}" for m in messages)

        # Multi-pass sliding summarization
        summaries: list[str] = []
        for i in range(0, len(messages), _CHUNK_SIZE):
            chunk = messages[i : i + _CHUNK_SIZE]
            chunk_text = "\n".join(f"[{m['author']}]: {m['content']}" for m in chunk)
            s = await self._llm_secondary.complete(
                render_identity(_CHUNK_SYSTEM),
                [{"role": "user", "content": chunk_text}],
                purpose="journal_chunk_summary",
            )
            # Un chunk en échec rend le message d'excuse : le laisser entrer
            # ferait écrire au journal qu'il s'est passé une panne technique.
            if s and s.strip() and s.strip() != FALLBACK_RESPONSE:
                summaries.append(s)
            else:
                logger.warning("Journal : résumé de chunk en échec, chunk ignoré")

        if not summaries:
            return ""
        if len(summaries) == 1:
            return summaries[0]

        combined = "\n---\n".join(summaries)
        final = await self._llm_secondary.complete(
            render_identity(_FINAL_SYSTEM),
            [{"role": "user", "content": combined}],
            purpose="journal_final_summary",
        )
        if not final or not final.strip() or final.strip() == FALLBACK_RESPONSE:
            logger.warning("Journal : synthèse finale en échec — repli sur les résumés bruts")
            return combined
        return final

    async def _build_memory_fallback_context(self) -> str:
        """Fallback final : souvenirs de tous les utilisateurs connus."""
        if self._db is None:
            return ""
        try:
            users = await self._db.list_memory_users()
        except Exception as exc:
            logger.warning("Failed to list memory users for journal fallback: {e}", e=exc)
            return ""

        if not users:
            return ""

        parts: list[str] = []
        for user in users:
            uid_full = user["user_id"]   # e.g. "discord:123456"
            platform = user["platform"]
            username = user.get("username") or uid_full
            raw_id = uid_full[len(platform) + 1:]  # "discord:123" → "123"
            try:
                facts = await self._memory.get_all(platform, raw_id)
            except Exception as exc:
                logger.debug("Journal memory fallback: failed for user {u}: {e}", u=username, e=exc)
                continue
            if facts:
                parts.append(f"[{username}] {facts}")

        if not parts:
            return ""

        logger.info("Journal fallback: using memory facts for {n} user(s)", n=len(parts))
        return "Souvenirs des utilisateurs (mémoire long-terme) :\n" + "\n".join(parts)

    @staticmethod
    def _today_date() -> date:
        """La date du jour EN HEURE DE PARIS, pas à l'horloge de la machine.

        Le serveur tourne en UTC : entre 22 h UTC et minuit, `date.today()`
        rend encore la veille alors que la journée parisienne a changé. Le
        journal demandait alors à `get_twitch_visits_for_date` — qui découpe,
        lui, en Europe/Paris — les visites d'un jour déjà clos.
        """
        return datetime.now(_TZ_JOURNAL).date()

    @classmethod
    def _today(cls) -> str:
        return cls._today_date().strftime("%d/%m/%Y")

    def start(self, scheduler=None) -> None:
        owns_scheduler = scheduler is None
        if owns_scheduler:
            # Fuseau EXPLICITE : sans lui, APScheduler prend celui du process
            # — UTC sur ce serveur — et « 21:00 » partait à 23 h française.
            self._scheduler = AsyncIOScheduler(timezone=_TZ_JOURNAL)
        else:
            self._scheduler = scheduler

        raw = self._config.bot.journal_time
        # YAML parse `21:00` sans guillemets en int sexagésimal (1260) — on normalise
        if isinstance(raw, int):
            hour, minute = divmod(raw, 60)
            time_str = f"{hour:02d}:{minute:02d}"
        else:
            time_str = str(raw)
            hour, minute = map(int, time_str.split(":"))
        self._scheduler.add_job(
            self.generate_and_send,
            "cron",
            hour=hour,
            minute=minute,
            id="daily_journal",
            replace_existing=True,
            timezone=_TZ_JOURNAL,
            **_TOLERANCE_RETARD,
        )
        # Memory cleanup 30 min before journal
        cleanup_dt = datetime(2000, 1, 1, hour, minute) - timedelta(minutes=30)
        self._scheduler.add_job(
            self.run_memory_cleanup,
            "cron",
            hour=cleanup_dt.hour,
            minute=cleanup_dt.minute,
            id="memory_cleanup",
            replace_existing=True,
            timezone=_TZ_JOURNAL,
            **_TOLERANCE_RETARD,
        )
        logger.info(
            "Memory cleanup scheduler started, fires at {h:02d}:{m:02d}",
            h=cleanup_dt.hour, m=cleanup_dt.minute,
        )
        if self._consolidator is not None:
            self._scheduler.add_job(
                self._consolidator.consolidate_day,
                "cron",
                hour=hour,
                minute=minute,
                id="memory_consolidation",
                replace_existing=True,
                timezone=_TZ_JOURNAL,
                **_TOLERANCE_RETARD,
            )
            logger.info("Consolidation nocturne planifiée à {t}", t=time_str)
        if self._user_modeler is not None:
            self._scheduler.add_job(
                self._user_modeler.refresh_profiles,
                "cron",
                hour=hour,
                minute=minute,
                id="user_model_refresh",
                replace_existing=True,
                timezone=_TZ_JOURNAL,
                **_TOLERANCE_RETARD,
            )
            logger.info("Modélisation des personnes planifiée à {t}", t=time_str)
        # Only start if we own the scheduler (no shared scheduler provided)
        if owns_scheduler:
            self._scheduler.start()
        logger.info("Daily journal scheduler started, fires at {t}", t=time_str)
