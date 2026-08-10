"""Vérification des invariants au démarrage — le canari dans la mine.

Pourquoi ce module existe : lors des deux audits du 2026-08-10, presque tous les
défauts partageaient le même trait — le bot démarrait « vert » alors qu'un
invariant était rompu depuis des semaines. Le ménage nocturne était un stub vide
depuis sept semaines. Deux prompts persona restaient éditables dans le panel
admin alors que plus rien ne les lisait. `get_due_facts` scannait 14 391 lignes
faute d'index. Deux formats de date cohabitaient dans la même colonne. Aucun de
ces cas n'a jamais produit une ligne de log.

Un test ne les voit pas : ils dépendent de l'état RÉEL de la base et du disque,
pas du code. C'est donc au démarrage, sur la vraie installation, qu'il faut les
regarder.

Règle du module : on ne bloque JAMAIS le démarrage. Un bot qui tourne avec un
index manquant vaut mieux qu'un bot qui refuse de démarrer. On journalise
bruyamment, c'est tout — c'est précisément ce qui manquait.
"""
from __future__ import annotations

import os
from pathlib import Path

import aiosqlite
from loguru import logger

# Index dont l'absence coûte cher en production, avec ce qu'elle provoque.
_INDEX_ATTENDUS: dict[str, tuple[str, str]] = {
    "idx_facts_scheduled": (
        "atomic_facts",
        "get_due_facts scanne toute la table à chaque tick cognitif",
    ),
    "idx_facts_user_status": (
        "atomic_facts",
        "toute lecture de mémoire par personne devient un scan",
    ),
}


async def _verifier_index(db_path: str) -> list[str]:
    alertes: list[str] = []
    try:
        async with aiosqlite.connect(db_path) as db:
            curseur = await db.execute(
                "SELECT name FROM sqlite_master WHERE type = 'index'"
            )
            presents = {r[0] for r in await curseur.fetchall()}
    except Exception as exc:  # noqa: BLE001 — un canari ne fait jamais échouer le boot
        return [f"index illisibles ({exc})"]
    for nom, (table, consequence) in _INDEX_ATTENDUS.items():
        if nom not in presents:
            alertes.append(f"index {nom} absent sur {table} — {consequence}")
    return alertes


async def _verifier_formats_de_date(db_path: str) -> list[str]:
    """Deux formats dans la même colonne = `TypeError` à la première soustraction.

    Vécu : 24 955 valeurs en aware pour 14 407 faits, parce qu'UN point
    d'écriture utilisait `datetime.now(timezone.utc)` là où tout le reste
    utilisait `utcnow()`.
    """
    try:
        async with aiosqlite.connect(db_path) as db:
            curseur = await db.execute(
                "SELECT COUNT(*) FROM atomic_facts "
                "WHERE created_at LIKE '%+00:00' OR last_seen_at LIKE '%+00:00'"
            )
            ligne = await curseur.fetchone()
    except Exception:  # noqa: BLE001 — table absente sur une base neuve
        return []
    melanges = ligne[0] if ligne else 0
    if melanges:
        return [
            f"{melanges} dates en format aware dans atomic_facts — "
            "un point d'écriture a divergé, toute soustraction directe lèvera "
            "(cf. scripts/normaliser_dates_faits.py)"
        ]
    return []


def _verifier_prompts(racine: Path) -> list[str]:
    """Un prompt référencé mais absent = un repli silencieux sur un texte inline.

    L'inverse — un fichier que plus rien ne lit — est déjà couvert par
    `test_prompts_orphelins`, qui l'a d'ailleurs attrapé pendant l'audit.
    """
    alertes: list[str] = []
    for dossier in (racine / "bot" / "persona" / "prompts",
                    racine / "bot" / "intelligence" / "persona" / "prompts"):
        if not dossier.is_dir():
            alertes.append(f"dossier de prompts absent : {dossier}")
    return alertes


def _verifier_identite(config) -> list[str]:
    """Des réglages dont l'absence rend une fonctionnalité muette, sans erreur."""
    alertes: list[str] = []
    bot_cfg = getattr(config, "bot", None)
    if bot_cfg is not None and not getattr(bot_cfg, "owner_discord_id", ""):
        alertes.append(
            "owner_discord_id vide — self-fix, DM cognitifs et bouton ADMIN "
            "resteront inaccessibles, sans message d'erreur"
        )
    openai_cfg = getattr(config, "openai", None)
    if openai_cfg is not None and not getattr(openai_cfg, "vision_model", ""):
        alertes.append(
            "openai.vision_model vide — la vision retombera sur un repli, "
            "et une mauvaise valeur la rendrait aveugle en silence"
        )
    return alertes


async def verifier_invariants(config, db_path: str | None = None) -> list[str]:
    """Passe tous les invariants en revue. Retourne la liste des alertes.

    Ne lève jamais, ne bloque jamais : la valeur est dans le LOG.
    """
    racine = Path(__file__).resolve().parents[2]
    chemin: str = db_path or os.getenv("DB_PATH") or "data/wally.db"

    alertes: list[str] = []
    alertes += _verifier_prompts(racine)
    alertes += _verifier_identite(config)
    if Path(chemin).exists():
        alertes += await _verifier_index(chemin)
        alertes += await _verifier_formats_de_date(chemin)

    if alertes:
        logger.warning(
            "🐤 Canari : {n} invariant(s) rompu(s) au démarrage — "
            "le bot tourne, mais quelque chose ne fonctionnera pas comme prévu :",
            n=len(alertes),
        )
        for a in alertes:
            logger.warning("🐤   · {a}", a=a)
    else:
        logger.info("🐤 Canari : tous les invariants de démarrage sont tenus")
    return alertes
