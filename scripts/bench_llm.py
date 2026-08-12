#!/usr/bin/env python3
"""Compare plusieurs configurations LLM sur le VRAI prompt système de Wally.

Sert à trancher un changement de modèle avec des mesures plutôt qu'avec des
prix catalogue : latence, tokens consommés, coût réel calculé par le code de
production (`DeepSeekLLMClient._log_cost`), et texte produit pour le jugement
à l'oreille.

    python3 scripts/bench_llm.py

Le prompt système est construit par le vrai `PromptBuilder` avec la vraie
persona (`bot/persona/`) : ce qu'on mesure ici est ce que le bot enverrait.
Les questions viennent des logs de conversation réels.
"""
from __future__ import annotations

import asyncio
import json
import os
import statistics
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv

load_dotenv()

from bot.core.llm.deepseek import DeepSeekLLMClient  # noqa: E402
from bot.intelligence.persona import PersonaService  # noqa: E402
from bot.intelligence.prompts import PromptBuilder  # noqa: E402


# Taux de cache miss constaté en production sur 30 jours (déduit du `cost_log`).
# Sert à comparer les configurations à conditions de cache égales.
_MISS_PROD = 0.46


def _cout_normalise(modele: str, tokens_in: int, tokens_out: int) -> float:
    """Coût USD de l'échantillon au taux de cache de la production."""
    from bot.core.llm.deepseek import _DEEPSEEK_COSTS, _DEEPSEEK_FALLBACK_COST

    hit, miss, out = _DEEPSEEK_COSTS.get(modele, _DEEPSEEK_FALLBACK_COST)
    prix_entree = _MISS_PROD * miss + (1 - _MISS_PROD) * hit
    return tokens_in / 1e6 * prix_entree + tokens_out / 1e6 * out


@dataclass
class _AppelMesure:
    """Une facturation captée au vol, telle que le client la calcule en prod."""

    model: str
    input_tokens: int
    output_tokens: int
    cost_usd: float


@dataclass
class _DbEspion:
    """Remplace la `Database` : capte `log_cost` sans écrire dans la prod."""

    appels: list[_AppelMesure] = field(default_factory=list)

    async def log_cost(
        self,
        model: str,
        input_tokens: int,
        output_tokens: int,
        cost_usd: float,
        purpose: str = "",
        user_id: str | None = None,
    ) -> None:
        self.appels.append(_AppelMesure(model, input_tokens, output_tokens, cost_usd))


# Les configurations mises en concurrence. `thinking_effort` est ignoré quand
# `thinking_type` vaut "disabled".
CONFIGS: list[tuple[str, str, str, str]] = [
    ("pro / sans raisonnement (actuel)", "deepseek-v4-pro", "disabled", "low"),
    ("flash / sans raisonnement", "deepseek-v4-flash", "disabled", "low"),
    ("flash / raisonnement low", "deepseek-v4-flash", "enabled", "low"),
    ("flash / raisonnement high", "deepseek-v4-flash", "enabled", "high"),
]


def _fuite_de_prompt(reponse: str, systeme: str) -> str | None:
    """Renvoie l'extrait recraché si la réponse récite le prompt système.

    Symptôme observé au banc d'essai : au lieu de RÉPONDRE, le modèle restitue
    la directive de comportement qu'on vient de lui donner (« Wally franchement
    enthousiaste. Tu es captivé par quelque chose… »). C'est une fuite de
    consigne visible par l'utilisateur, pas une simple maladresse de ton — donc
    un critère de sélection à part entière entre deux configurations.

    Détection par 6-grammes de mots communs, insensible à la casse et à la
    ponctuation : une phrase entière reprise du prompt est une fuite, une
    tournure de quatre mots partagée est une coïncidence.
    """
    def _mots(texte: str) -> list[str]:
        return "".join(c.lower() if c.isalnum() or c.isspace() else " " for c in texte).split()

    mots_systeme = _mots(systeme)
    grammes = {tuple(mots_systeme[i:i + 6]) for i in range(len(mots_systeme) - 5)}
    mots_reponse = _mots(reponse)
    for i in range(len(mots_reponse) - 5):
        gramme = tuple(mots_reponse[i:i + 6])
        if gramme in grammes:
            return " ".join(gramme)
    return None


def _questions_reelles(limite: int = 14) -> list[str]:
    """Messages réellement adressés à Wally, pris dans les logs les plus récents."""
    racine = Path("logs/conversations")
    fichiers = sorted(racine.rglob("*.jsonl"), key=lambda p: p.stat().st_mtime, reverse=True)
    vues: set[str] = set()
    questions: list[str] = []
    for fichier in fichiers:
        for ligne in fichier.read_text(encoding="utf-8", errors="replace").splitlines():
            try:
                evenement = json.loads(ligne)
            except json.JSONDecodeError:
                continue
            if evenement.get("type") != "message_in":
                continue
            contenu = (evenement.get("content") or "").strip()
            # Sous 20 caractères on mesure le bruit ("lol", "ok") plutôt que le modèle.
            if len(contenu) < 20 or contenu in vues:
                continue
            vues.add(contenu)
            questions.append(contenu)
            if len(questions) >= limite:
                return questions
    return questions


def _prompt_systeme() -> str:
    """Le prompt système tel que le bot le construit, persona de prod incluse."""
    persona = PersonaService()
    builder = PromptBuilder()
    return builder.build_system_prompt(
        emotion_state={"anger": 0.1, "joy": 0.45, "sadness": 0.05, "curiosity": 0.5, "boredom": 0.2},
        situation={"platform": "discord", "channel": "chambre-de-wally"},
        persona_block=persona.build_prompt_block(),
        emotion_directives=persona.emotion_directives,
        weekday_directives=persona.weekday_directives,
        composite_directives=persona.composite_directives,
        secondary_directives=persona.secondary_directives,
    )


async def _mesurer(
    libelle: str, modele: str, thinking: str, effort: str, systeme: str, questions: list[str]
) -> dict:
    espion = _DbEspion()
    client = DeepSeekLLMClient(
        model=modele,
        db=espion,
        temperature=0.8,
        max_tokens=8192,
        thinking_type=thinking,
        thinking_effort=effort,
    )
    latences: list[float] = []
    reponses: list[str] = []
    for question in questions:
        debut = time.monotonic()
        texte = await client.complete(
            system_prompt=systeme,
            messages=[{"role": "user", "content": question}],
            purpose="bench",
        )
        latences.append(time.monotonic() - debut)
        reponses.append(texte)
        print(f"  · {libelle[:34]:34s} {latences[-1]:5.1f}s  {len(texte):4d} car.", flush=True)

    fuites = [_fuite_de_prompt(r, systeme) for r in reponses]
    tokens_in = sum(a.input_tokens for a in espion.appels)
    tokens_out = sum(a.output_tokens for a in espion.appels)
    return {
        "libelle": libelle,
        "modele": modele,
        "thinking": thinking if thinking == "disabled" else f"{thinking}/{effort}",
        "latence_med": statistics.median(latences),
        "latence_max": max(latences),
        "tokens_in": tokens_in,
        "tokens_out": tokens_out,
        # Le coût brut n'est PAS comparable entre configurations : la première
        # testée paie le cache froid, les suivantes profitent du préfixe déjà
        # chaud. On recalcule donc chacune au taux de cache observé en prod.
        "cout_normalise": _cout_normalise(modele, tokens_in, tokens_out),
        "car_moyen": statistics.mean(len(r) for r in reponses),
        "fuites": [f for f in fuites if f],
        "reponses": reponses,
    }


async def main() -> int:
    if not os.environ.get("DEEPSEEK_API_KEY"):
        print("DEEPSEEK_API_KEY absente de l'environnement.", file=sys.stderr)
        return 1

    questions = _questions_reelles()
    if not questions:
        print("Aucun message exploitable dans logs/conversations/.", file=sys.stderr)
        return 1

    systeme = _prompt_systeme()
    print(f"Prompt système : {len(systeme)} caractères")
    print(f"Questions réelles : {len(questions)}\n")
    for i, q in enumerate(questions, 1):
        print(f"  {i}. {q[:100]}")
    print()

    resultats = []
    for libelle, modele, thinking, effort in CONFIGS:
        print(f"{libelle}")
        resultats.append(await _mesurer(libelle, modele, thinking, effort, systeme, questions))
        print()

    print("=" * 100)
    entete = (
        f"{'configuration':34s} {'lat.méd':>8s} {'lat.max':>8s} {'tok.in':>8s} "
        f"{'tok.out':>8s} {'coût norm.':>11s} {'car/rép':>8s} {'fuites':>7s}"
    )
    print(entete)
    print("-" * 110)
    for r in resultats:
        print(
            f"{r['libelle']:34s} {r['latence_med']:7.1f}s {r['latence_max']:7.1f}s "
            f"{r['tokens_in']:8d} {r['tokens_out']:8d} {r['cout_normalise']:10.5f}$ "
            f"{r['car_moyen']:8.0f} {len(r['fuites']):4d}/{len(questions):<2d}"
        )
    print("=" * 110)

    reference_prix = next(r for r in resultats if "pro" in r["modele"])
    print("\nCoût rapporté à la configuration actuelle (pro, sans raisonnement) :")
    for r in resultats:
        part = r["cout_normalise"] / reference_prix["cout_normalise"]
        print(f"  {r['libelle']:34s} ×{part:.2f}")

    fuites_vues = [(r["libelle"], f) for r in resultats for f in r["fuites"]]
    if fuites_vues:
        print("\nFuites du prompt système dans la réponse (le modèle récite sa consigne) :")
        for libelle, extrait in fuites_vues:
            print(f"  [{libelle:32s}] …{extrait}…")

    # Extrapolation sur le volume mensuel constaté en production. Le coût mesuré
    # ci-dessus est un coût de premier appel (cache froid) sur un échantillon :
    # ce qui se transpose, c'est le RATIO de tokens de sortie entre configs.
    reference = next(r for r in resultats if r["thinking"] == "disabled" and "flash" in r["modele"])
    print("\nEffet du raisonnement sur le volume de sortie (base = flash sans raisonnement) :")
    for r in resultats:
        facteur = r["tokens_out"] / reference["tokens_out"] if reference["tokens_out"] else 0
        print(f"  {r['libelle']:34s} ×{facteur:.2f}")

    print("\n--- Réponses, pour jugement ---")
    for i, question in enumerate(questions):
        print(f"\n### {question[:90]}")
        for r in resultats:
            extrait = r["reponses"][i].replace("\n", " ")[:220]
            print(f"  [{r['libelle']:32s}] {extrait}")

    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
