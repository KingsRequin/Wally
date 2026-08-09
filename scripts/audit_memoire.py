#!/usr/bin/env python3
"""Audit d'hygiène de la mémoire de Wally — LECTURE SEULE, aucune écriture.

Né du 2026-08-09 : Wally avait redemandé par `code_fix` une capacité livrée quatre
jours plus tôt. Ce n'était pas un incident isolé mais le bout visible d'un stock —
156 désirs actifs, dont dix portaient sur des capacités qu'il possédait déjà.

Ce script ne corrige rien. Il produit une liste de ce qui mérite un coup d'œil, et
c'est le propriétaire qui tranche. **Règle d'usage : tout motif qui revient deux
semaines de suite doit devenir un correctif dans le code, pas une ligne de ménage
de plus.** Le rapport est un détecteur de mécanismes manquants ; s'il se vide de
lui-même, les mécanismes sont bons et ce script n'a plus de raison de tourner.

Ce qu'il remonte :

  • désir qui recoupe une capacité DÉJÀ LIVRÉE   → le motif exact du 2026-08-09
  • désir périmé encore actif                    → `expires_at` dépassé
  • désir daté SANS péremption                   → un marqueur temporel, pas d'`expires_at`
  • désir vieux et jamais confirmé               → candidat à l'archivage
  • capacité livrée sans phrase au présent       → rien ne lui dit qu'il l'a

Usage :
    python3 scripts/audit_memoire.py
    python3 scripts/audit_memoire.py --db data/wally.db --age-max 30
"""
from __future__ import annotations

import argparse
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

_RACINE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_RACINE))

from bot.intelligence.upgrade_registry import (
    _MIN_TOKENS_RECOUVREMENT,
    _jaccard,
    _recouvrement,
    _tokens,
)


def _connexion(chemin: str) -> sqlite3.Connection:
    """Connexion STRICTEMENT en lecture — un audit ne mute jamais rien."""
    db = sqlite3.connect(f"file:{chemin}?mode=ro", uri=True)
    db.row_factory = sqlite3.Row
    return db


def _jours(iso: str | None) -> int | None:
    if not iso:
        return None
    try:
        d = datetime.fromisoformat(iso)
    except ValueError:
        return None
    if d.tzinfo is None:
        d = d.replace(tzinfo=timezone.utc)
    return max(0, (datetime.now(timezone.utc) - d).days)


def _une_ligne(texte: str, taille: int = 110) -> str:
    plat = " ".join((texte or "").split())
    return plat if len(plat) <= taille else plat[: taille - 1] + "…"


def desirs_actifs(db: sqlite3.Connection) -> list[sqlite3.Row]:
    return list(db.execute(
        """SELECT id, content, created_at, last_seen_at, support_count, expires_at
           FROM atomic_facts
           WHERE user_id='wally:self' AND category='DESIRE' AND status='active'
           ORDER BY created_at"""
    ))


def capacites_livrees(db: sqlite3.Connection) -> list[sqlite3.Row]:
    return list(db.execute(
        "SELECT id, proposal, capability, decided_at FROM pending_upgrades WHERE status='delivered'"
    ))


# Seuil de recoupement désir ↔ capacité livrée. DÉLIBÉRÉMENT plus bas que le
# `_SEUIL_RECOUVREMENT` de la garde (0.45), qui compare deux DEMANDES entre elles :
# un désir est écrit dans un registre télégraphique, souvent mêlé de méta (« —
# progression — », « reformuler un code_fix propre »), et ne partage donc qu'une
# fraction du vocabulaire de la demande correspondante. Mesuré sur le cas réel du
# 2026-08-09, désir #15265 contre capacité #19 : 0.267 seulement.
#
# Un audit en lecture seule n'a pas le même arbitrage qu'une garde qui bloque : ici
# un faux positif coûte un coup d'œil, un faux négatif coûte une redemande inutile.
SEUIL_RECOUPEMENT_DESIR = 0.25


# Un désir n'est comparé aux capacités livrées que s'il RÉCLAME quelque chose. Sans
# ce pré-filtre, un seuil assez bas pour attraper le vrai cas (#15265 à 0.267)
# remontait surtout du hasard lexical — « Azraël stream mardi et mercredi » rapproché
# d'une demande sur Twitch, « KingsRequin dit ne pas avoir de mémoire » d'une autre.
# Neuf lignes dont une pertinente : un rapport illisible ne se lit pas, donc ne sert
# à rien. Ce qu'on cherche n'est pas un désir qui PARLE du même sujet, c'est un désir
# qui DEMANDE une capacité déjà acquise.
_MARQUEURS_RECLAMATION = (
    "capacité", "capacite", "me manque", "demander à kingsrequin",
    "demander a kingsrequin", "j'aimerais pouvoir", "avoir accès", "avoir acces",
    "obtenir", "pouvoir enfin", "soumettre à kingsrequin", "demande de capacité",
    # Un désir qui parle de `code_fix` ou d'une demande refusée EST une réclamation,
    # même sans le mot « capacité » : c'est le cas du désir #15265, qui a relancé la
    # demande du 2026-08-09 en disant seulement « reformuler un code_fix propre ».
    "code_fix", "demande refusée", "demande refusee",
)


def reclame_une_capacite(texte: str) -> bool:
    bas = (texte or "").lower()
    return any(m in bas for m in _MARQUEURS_RECLAMATION)


def desirs_deja_livres(
    desirs, livrees, seuil: float = SEUIL_RECOUPEMENT_DESIR
) -> list[tuple[sqlite3.Row, sqlite3.Row, float]]:
    """Désirs qui RÉCLAMENT une capacité déjà livrée — le motif du 2026-08-09.

    Réutilise les mesures de la garde anti-redemande (`_jaccard`, `_recouvrement`)
    avec son propre seuil (cf. `SEUIL_RECOUPEMENT_DESIR`), restreint aux désirs qui
    formulent une réclamation (cf. `_MARQUEURS_RECLAMATION`).
    """
    trouves = []
    for d in desirs:
        if not reclame_une_capacite(d["content"]):
            continue
        jetons = _tokens(d["content"])
        meilleur: tuple[sqlite3.Row, float] | None = None
        for u in livrees:
            autres = _tokens(f"{u['proposal']} {u['capability'] or ''}")
            rec = (
                _recouvrement(jetons, autres)
                if min(len(jetons), len(autres)) >= _MIN_TOKENS_RECOUVREMENT
                else 0.0
            )
            score = max(_jaccard(jetons, autres), rec)
            if score >= seuil and (meilleur is None or score > meilleur[1]):
                meilleur = (u, score)
        if meilleur is not None:
            trouves.append((d, meilleur[0], meilleur[1]))
    return trouves


def desirs_perimes(desirs) -> list[sqlite3.Row]:
    maintenant = datetime.utcnow().isoformat()
    return [d for d in desirs if d["expires_at"] and d["expires_at"] <= maintenant]


def desirs_dates_sans_peremption(desirs) -> list[sqlite3.Row]:
    """Un marqueur temporel dans le texte, mais aucune date de péremption.

    Signe que le désir est né par un chemin qui n'appelle pas `_compute_expiry`.
    """
    from bot.intelligence.fact_extractor import _TTL_MARKERS

    marqueurs = [m for _, groupe in _TTL_MARKERS for m in groupe]
    return [
        d for d in desirs
        if not d["expires_at"] and any(m in (d["content"] or "").lower() for m in marqueurs)
    ]


def desirs_vieux(desirs, age_max: int) -> list[tuple[sqlite3.Row, int]]:
    vieux = []
    for d in desirs:
        age = _jours(d["created_at"])
        if age is not None and age > age_max and (d["support_count"] or 1) <= 1:
            vieux.append((d, age))
    return vieux


def capacites_sans_phrase_au_present(livrees) -> list[sqlite3.Row]:
    """Capacités livrées dont la colonne `capability` est vide.

    Critère FACTUEL, et c'est délibéré. La version précédente comparait le
    vocabulaire de la demande à celui de `CAPABILITIES.md` : sur 15 livraisons elle
    en signalait 8 comme absentes alors que quatre venaient d'y être ajoutées —
    comparer une demande technique à un portrait reformulé ne mesure rien. Ici pas
    d'heuristique : sans phrase au présent, rien ne garantit que Wally sache qu'il
    possède la capacité, et c'est ce trou qui le fait redemander.
    """
    return [u for u in livrees if not (u["capability"] or "").strip()]


def rapport(chemin_db: str, age_max: int) -> list[str]:
    db = _connexion(chemin_db)
    try:
        desirs = desirs_actifs(db)
        livrees = capacites_livrees(db)
    finally:
        db.close()

    lignes = [
        "=== Audit mémoire de Wally (lecture seule) ===",
        f"{len(desirs)} désirs actifs · {len(livrees)} capacités livrées",
    ]

    def section(titre: str, items: list, rendu) -> None:
        lignes.append("")
        lignes.append(f"--- {titre} : {len(items)}")
        if not items:
            lignes.append("    (rien)")
            return
        for item in items:
            lignes.append(f"    {rendu(item)}")

    section(
        "Désirs qui recoupent une capacité DÉJÀ LIVRÉE",
        desirs_deja_livres(desirs, livrees),
        lambda t: f"#{t[0]['id']} (≈ demande #{t[1]['id']}, score {t[2]:.2f}) — {_une_ligne(t[0]['content'], 80)}",
    )
    section(
        "Désirs périmés encore actifs",
        desirs_perimes(desirs),
        lambda d: f"#{d['id']} (expiré le {d['expires_at'][:10]}) — {_une_ligne(d['content'], 80)}",
    )
    section(
        "Désirs datés SANS péremption (nés hors du chemin qui la pose)",
        desirs_dates_sans_peremption(desirs),
        lambda d: f"#{d['id']} — {_une_ligne(d['content'], 90)}",
    )
    section(
        f"Désirs de plus de {age_max} jours jamais reconfirmés",
        desirs_vieux(desirs, age_max),
        lambda t: f"#{t[0]['id']} ({t[1]} j) — {_une_ligne(t[0]['content'], 85)}",
    )
    section(
        "Capacités livrées SANS phrase au présent (rien ne lui dit qu'il les a)",
        capacites_sans_phrase_au_present(livrees),
        lambda u: f"demande #{u['id']} — {_une_ligne(u['proposal'], 90)}",
    )

    lignes += [
        "",
        "Rappel : ce rapport ne corrige rien. Un motif qui revient deux semaines de",
        "suite doit devenir un correctif de mécanisme, pas une ligne de ménage.",
    ]
    return lignes


def main() -> None:
    ap = argparse.ArgumentParser(description="Audit d'hygiène de la mémoire (lecture seule)")
    ap.add_argument("--db", default=str(_RACINE / "data" / "wally.db"))
    ap.add_argument("--age-max", type=int, default=30,
                    help="âge en jours au-delà duquel un désir jamais reconfirmé est signalé")
    args = ap.parse_args()
    print("\n".join(rapport(args.db, args.age_max)))


if __name__ == "__main__":
    main()
