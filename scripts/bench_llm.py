#!/usr/bin/env python3
"""Compare plusieurs configurations LLM sur le VRAI prompt système de Wally.

Sert à trancher un changement de modèle avec des mesures plutôt qu'avec des
prix catalogue : latence, tokens consommés, facture mensuelle projetée sur le
volume réel de production, et texte produit pour le jugement à l'oreille.

    python3 scripts/bench_llm.py

Le prompt système est construit par le vrai `PromptBuilder` avec la vraie
persona (`bot/persona/`), les clients par la vraie `create_llm_client`, et les
tarifs sont lus dans les tables qui FACTURENT en production : ce qu'on mesure
ici est ce que le bot enverrait, chiffré comme le bot le chiffrerait. Les
questions viennent des logs de conversation réels.

Compare plusieurs fournisseurs, `deepseek` et `openai` — chaque entrée de
`CONFIGS` est un `LLMRoleConfig`, l'objet même que porte `config.yaml`.
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

from bot.config import LLMRoleConfig  # noqa: E402
from bot.core.llm.factory import create_llm_client  # noqa: E402
from bot.intelligence.persona import PersonaService  # noqa: E402
from bot.intelligence.prompts import PromptBuilder  # noqa: E402


# Taux de cache miss constaté en production sur 30 jours (déduit du `cost_log`).
# Sert à comparer les configurations à conditions de cache égales.
_MISS_PROD = 0.46

# Volume MENSUEL réel du poste « visible » (réponses adressées à des humains),
# mesuré dans `cost_log` sur 30 jours : millions de tokens d'entrée et de sortie.
# Sert à traduire un coût d'échantillon en facture mensuelle, la seule unité qui
# permette d'arbitrer. Le nombre de tokens n'est PAS comparable d'un fournisseur
# à l'autre (tokenizers différents) : on projette donc le volume de production
# sur les TARIFS de chacun, jamais les tokens mesurés au banc.
_VOLUME_PROD_IN_M = 39.20
_VOLUME_PROD_OUT_M = 0.319


def _tarifs(provider: str, modele: str) -> tuple[float, float, float]:
    """(entrée, entrée cachée, sortie) en USD par million, pour ce fournisseur.

    Chaque client de production porte sa propre table, dans sa propre forme —
    DeepSeek en (hit, miss, sortie) avec deux grilles horaires, OpenAI en
    (entrée, cache, sortie). On lit LEUR table plutôt que d'en recopier une
    troisième ici : un tarif dupliqué au banc dériverait de celui qui facture,
    et le banc mentirait précisément sur ce qu'on lui demande d'arbitrer.
    """
    if provider == "deepseek":
        from bot.core.llm.deepseek import _deepseek_rates

        hit, miss, out = _deepseek_rates(modele)
        return miss, hit, out
    if provider == "openai":
        from bot.core.llm.openai_client import FALLBACK_COST, MODEL_COSTS

        return MODEL_COSTS.get(modele) or next(
            (v for k, v in sorted(MODEL_COSTS.items(), key=lambda x: len(x[0]), reverse=True)
             if modele.startswith(k)),
            FALLBACK_COST,
        )
    raise ValueError(f"Pas de table de tarifs au banc pour {provider!r}")


def _cout_mensuel_projete(provider: str, modele: str) -> float:
    """Facture mensuelle sur le volume de production, au taux de cache de la prod."""
    entree, cache, sortie = _tarifs(provider, modele)
    prix_entree = _MISS_PROD * entree + (1 - _MISS_PROD) * cache
    return _VOLUME_PROD_IN_M * prix_entree + _VOLUME_PROD_OUT_M * sortie


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


# Les configurations mises en concurrence, décrites par le MÊME objet que la
# production (`LLMRoleConfig`) et bâties par la MÊME factory. Le banc
# instanciait `DeepSeekLLMClient` en dur : il ne pouvait donc mesurer qu'un seul
# fournisseur, et rien ne garantissait que le client mesuré fût celui que
# `create_llm_client` aurait construit à partir de cette config.
#
# `thinking_type` / `thinking_effort` ne parlent qu'à DeepSeek, `reasoning_effort`
# et `text_verbosity` qu'à OpenAI ; chaque client ignore ce qui ne le concerne
# pas. La PREMIÈRE entrée sert de référence à toutes les comparaisons.
CONFIGS: list[tuple[str, LLMRoleConfig]] = [
    ("deepseek flash / thinking low (ACTUEL)", LLMRoleConfig(
        provider="deepseek", model="deepseek-v4-flash", temperature=0.8, max_tokens=8192,
        thinking_type="enabled", thinking_effort="low")),
    ("deepseek flash / sans thinking", LLMRoleConfig(
        provider="deepseek", model="deepseek-v4-flash", temperature=0.8, max_tokens=8192,
        thinking_type="disabled")),
    ("gpt-5.6-luna / effort none", LLMRoleConfig(
        provider="openai", model="gpt-5.6-luna", temperature=0.8, max_tokens=8192,
        reasoning_effort="none", text_verbosity="medium")),
    ("gpt-5.6-luna / effort low", LLMRoleConfig(
        provider="openai", model="gpt-5.6-luna", temperature=0.8, max_tokens=8192,
        reasoning_effort="low", text_verbosity="medium")),
    ("gpt-5.6-luna / effort medium", LLMRoleConfig(
        provider="openai", model="gpt-5.6-luna", temperature=0.8, max_tokens=8192,
        reasoning_effort="medium", text_verbosity="medium")),
]


def _detail_config(role: LLMRoleConfig) -> str:
    """Le réglage qui distingue cette configuration, en une colonne lisible."""
    if role.provider == "deepseek":
        return (role.thinking_type if role.thinking_type == "disabled"
                else f"{role.thinking_type}/{role.thinking_effort}")
    return f"effort={role.reasoning_effort}"


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
    libelle: str, role: LLMRoleConfig, systeme: str, questions: list[str]
) -> dict:
    espion = _DbEspion()
    client = create_llm_client(role, espion)
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
        print(f"  · {libelle[:38]:38s} {latences[-1]:5.1f}s  {len(texte):4d} car.", flush=True)

    fuites = [_fuite_de_prompt(r, systeme) for r in reponses]
    tokens_in = sum(a.input_tokens for a in espion.appels)
    tokens_out = sum(a.output_tokens for a in espion.appels)
    # Une réponse VIDE est le symptôme à guetter, pas une anomalie de mesure :
    # sur la Responses API, un `reasoning_effort` actif fait omettre
    # `max_output_tokens`, et le modèle épuise son budget en raisonnement avant
    # d'écrire un mot. Sans ce compteur, la configuration fautive ressort du
    # tableau avec la MEILLEURE latence et le coût le plus bas.
    vides = sum(1 for r in reponses if not r.strip())
    return {
        "libelle": libelle,
        "modele": role.model,
        "provider": role.provider,
        "detail": _detail_config(role),
        "latence_med": statistics.median(latences),
        "latence_max": max(latences),
        "tokens_in": tokens_in,
        "tokens_out": tokens_out,
        # Le coût brut de l'échantillon n'est comparable ni entre configurations
        # (la première testée paie le cache froid) ni entre fournisseurs (les
        # tokenizers diffèrent). Ce qui s'arbitre, c'est la facture mensuelle sur
        # le volume de production, aux tarifs du fournisseur.
        "cout_mensuel": _cout_mensuel_projete(role.provider, role.model),
        "car_moyen": statistics.mean(len(r) for r in reponses),
        "vides": vides,
        "fuites": [f for f in fuites if f],
        "reponses": reponses,
    }


_CLE_PAR_PROVIDER = {"deepseek": "DEEPSEEK_API_KEY", "openai": "OPENAI_API_KEY"}


async def main() -> int:
    # Une clé manquante ne se découvre pas au milieu du banc : les
    # configurations déjà passées auraient payé pour rien, et celle qui échoue
    # sortirait du tableau avec zéro token et la meilleure latence.
    manquantes = sorted({
        cle for _, role in CONFIGS
        if (cle := _CLE_PAR_PROVIDER.get(role.provider)) and not os.environ.get(cle)
    })
    if manquantes:
        print(f"Clés absentes de l'environnement : {', '.join(manquantes)}", file=sys.stderr)
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
    for libelle, role in CONFIGS:
        print(f"{libelle}  [{role.provider} · {role.model} · {_detail_config(role)}]")
        resultats.append(await _mesurer(libelle, role, systeme, questions))
        print()

    largeur = 122
    print("=" * largeur)
    print(
        f"{'configuration':38s} {'lat.méd':>8s} {'lat.max':>8s} {'tok.in':>8s} "
        f"{'tok.out':>8s} {'$/mois':>9s} {'car/rép':>8s} {'vides':>7s} {'fuites':>7s}"
    )
    print("-" * largeur)
    for r in resultats:
        print(
            f"{r['libelle']:38s} {r['latence_med']:7.1f}s {r['latence_max']:7.1f}s "
            f"{r['tokens_in']:8d} {r['tokens_out']:8d} {r['cout_mensuel']:8.2f}$ "
            f"{r['car_moyen']:8.0f} {r['vides']:4d}/{len(questions):<2d} "
            f"{len(r['fuites']):4d}/{len(questions):<2d}"
        )
    print("=" * largeur)
    print("  $/mois = facture projetée sur le volume du poste visible "
          f"({_VOLUME_PROD_IN_M} M in / {_VOLUME_PROD_OUT_M} M out), "
          f"cache à {int((1 - _MISS_PROD) * 100)} %.")

    reference = resultats[0]
    print(f"\nRapporté à « {reference['libelle']} » :")
    for r in resultats:
        prix = r["cout_mensuel"] / reference["cout_mensuel"] if reference["cout_mensuel"] else 0
        lat = r["latence_med"] / reference["latence_med"] if reference["latence_med"] else 0
        print(f"  {r['libelle']:38s} prix ×{prix:.2f}   latence ×{lat:.2f}")

    creuses = [r["libelle"] for r in resultats if r["vides"]]
    if creuses:
        print("\n⚠️  Configurations ayant rendu des réponses VIDES — inutilisables telles quelles :")
        for libelle in creuses:
            print(f"  · {libelle}")

    fuites_vues = [(r["libelle"], f) for r in resultats for f in r["fuites"]]
    if fuites_vues:
        print("\nFuites du prompt système dans la réponse (le modèle récite sa consigne) :")
        for libelle, extrait in fuites_vues:
            print(f"  [{libelle:36s}] …{extrait}…")

    print("\n--- Réponses, pour jugement ---")
    for i, question in enumerate(questions):
        print(f"\n### {question[:90]}")
        for r in resultats:
            extrait = r["reponses"][i].replace("\n", " ")[:220]
            print(f"  [{r['libelle']:36s}] {extrait}")

    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
