# bot/core/journal.py
from __future__ import annotations

import asyncio
import re
import time
from collections import Counter
from datetime import date, datetime, timedelta
from io import BytesIO
from typing import TYPE_CHECKING, Any, Callable, Optional
from zoneinfo import ZoneInfo

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from loguru import logger

from bot.core.emotion import EMOTIONS
from bot.core.llm import FALLBACK_RESPONSE
from bot.intelligence.identity import render_identity
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
        """Maintenance mémoire quotidienne : archive les faits éphémères périmés."""
        try:
            await self._memory.cleanup_expired_facts()
        except Exception as exc:
            logger.warning("Memory cleanup failed: {e}", e=exc)

    async def generate_and_send(self, archive: bool = True, target_date: date | None = None) -> None:
        channel_id = self._config.bot.journal_channel_id
        if not channel_id:
            logger.warning("No journal_channel_id configured, skipping journal")
            return

        # target_date=None → aujourd'hui (comportement normal du cron)
        effective_date = target_date or date.today()
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

        # ── Voice pass — dé-polit le brouillon et le ramène sous le plafond ──
        if journal_text:
            try:
                # La consigne de longueur voyage avec le brouillon : sans elle, le
                # pass n'a aucun moyen de savoir qu'il doit couper.
                voice_sections = [length_guidance]
                if style_block:
                    voice_sections.append(style_block)
                voice_sections.append(f"Brouillon :\n{journal_text}")
                voice_input = "\n\n---\n\n".join(voice_sections)
                voice_result = await self._llm_secondary.complete(
                    render_identity(_JOURNAL_VOICE_PASS_SYSTEM),
                    [{"role": "user", "content": voice_input}],
                    purpose="journal_voice_pass",
                )
                if voice_result and voice_result != FALLBACK_RESPONSE:
                    journal_text = voice_result
                else:
                    logger.warning("Journal voice pass returned fallback — keeping primary output")
            except Exception as exc:
                logger.warning("Journal voice pass failed: {e}", e=exc)

        # ── Emotion chart image (F10) ──
        chart_buf = _generate_emotion_chart(snapshots) if snapshots else None

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
            summaries.append(s)

        if len(summaries) == 1:
            return summaries[0]

        combined = "\n---\n".join(summaries)
        return await self._llm_secondary.complete(
            render_identity(_FINAL_SYSTEM),
            [{"role": "user", "content": combined}],
            purpose="journal_final_summary",
        )

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
    def _today() -> str:
        return date.today().strftime("%d/%m/%Y")

    def start(self, scheduler=None) -> None:
        owns_scheduler = scheduler is None
        if owns_scheduler:
            self._scheduler = AsyncIOScheduler()
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
            )
            logger.info("Modélisation des personnes planifiée à {t}", t=time_str)
        # Only start if we own the scheduler (no shared scheduler provided)
        if owns_scheduler:
            self._scheduler.start()
        logger.info("Daily journal scheduler started, fires at {t}", t=time_str)
