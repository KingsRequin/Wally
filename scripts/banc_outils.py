#!/usr/bin/env python3
"""Banc de mesure : les 24 outils de Wally nuisent-ils à son choix d'outil ?

Le prompt d'une réponse Twitch pèse ~19 400 tokens, dont ~8 400 (43 %) rien
qu'en définitions d'outils. Les benchmarks publics situent la chute de précision
de sélection entre 5 et 20 outils, et recommandent de plafonner à 15-20 — Wally
est à 24. Mais un seuil publié n'est pas une mesure LOCALE, et ce projet a déjà
payé cher les hypothèses plausibles vérifiées directement en production.

D'où ce banc. Il ne cherche pas à savoir si Wally répond BIEN — il répond bien,
c'est mesuré ailleurs. Il isole une seule question : à contexte identique,
est-ce que la présence de quatorze outils SANS RAPPORT avec la demande dégrade
le choix de l'outil qui, lui, a rapport ?

Protocole
---------
Deux ensembles d'outils, et un seul facteur qui change entre eux :

  • RÉDUIT   — 10 outils, ceux qui portent 92 % des appels réels d'août 2026.
  • COMPLET  — les 24 du chemin Twitch maison en live : les 10 mêmes, plus 14
               distracteurs.

Les deux ensembles contiennent DONC tous les outils attendus par les cas. Un cas
raté sous COMPLET et réussi sous RÉDUIT ne peut pas s'expliquer par un outil
absent : il ne reste que la surcharge. C'est tout l'intérêt de ne pas retirer
d'outil utile du réduit.

Les cas viennent des traces réelles (`logs/conversations/twitch/2026-08-*`), pas
de l'imagination : ce sont des phrases que des viewers ont vraiment tapées.
L'attente est annotée À LA MAIN et non reprise de ce que Wally avait fait —
sinon on mesurerait sa reproductibilité, pas sa justesse.

Les cas NÉGATIFS comptent autant que les positifs. Appeler un outil quand la
conversation n'en demande aucun est le défaut que la surcharge produit en
premier : le modèle voit vingt-quatre capacités et se croit obligé d'en servir
une. Un banc qui ne mesurerait que les positifs récompenserait ce réflexe.

Rien n'est exécuté ni écrit
---------------------------
Le `tool_executor` enregistre l'appel et rend un résultat neutre : aucun meme ne
s'affiche à l'écran, aucun pendu ne s'ouvre, rien ne part dans le vocal. Le
client LLM est construit avec `db=None`, donc `log_cost` échoue (déjà enveloppé
d'un try/except côté client) et la base de production reste intacte.

Ce que le banc NE mesure PAS
----------------------------
La latence qu'il affiche ne vaut que pour comparer ses deux variantes entre
elles — elle n'est pas comparable à la production. Un résultat neutre ne
satisfait pas le modèle, qui relance son outil jusqu'à épuiser les trois
itérations du client : un cas coûte ici trois à quatre allers-retours là où la
prod en fait un. Le CHOIX d'outil, lui, se lit dès le premier appel et reste
mesuré juste.

Usage :
    python3 scripts/banc_outils.py                    # les deux variantes, 2 tours
    python3 scripts/banc_outils.py --tours 3
    python3 scripts/banc_outils.py --variante reduite
    python3 scripts/banc_outils.py --json /tmp/banc.json
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv  # noqa: E402
from loguru import logger  # noqa: E402

load_dotenv()


# ---------------------------------------------------------------- jeu de cas

@dataclass
class Cas:
    """Une demande réelle, et l'outil qu'elle appelle de façon évidente.

    `attendu` vide = aucun outil ne doit partir. Plusieurs noms sont acceptés
    quand deux outils répondent aussi bien l'un que l'autre : trancher
    arbitrairement ferait passer une ambiguïté du CATALOGUE pour une erreur du
    modèle.
    """
    message: str
    attendu: set[str] = field(default_factory=set)
    note: str = ""


CAS: list[Cas] = [
    # ---- positifs : l'outil attendu ne fait aucun doute -------------------
    Cas("wally envoit le meme d'azrael avec des randoms", {"show_overlay"}),
    Cas("wally mets un meme de rina", {"show_overlay"}),
    Cas("wally est-ce que tu peux afficher le meme sur bugs bunny", {"show_overlay"}),
    Cas("wally lance un pile ou face", {"show_overlay"}),
    Cas("@WallyTeBully combien de kill ?", {"apex_legends"}),
    Cas("Wally peut tu me donner mon nombre de kills stp . IronAnanas xbox",
        {"apex_legends"}),
    Cas("Wally ta compté combien de kill depuis le début du live ?", {"apex_legends"}),
    # `apex_legends` est accepté à côté de `show_apex` : lire les chiffres avant
    # de les afficher est l'enchaînement le plus fréquent des traces réelles
    # (15 fois en août). L'exécuteur neutre du banc l'interrompt au premier
    # temps — compter cela comme une erreur mesurerait une limite du banc.
    Cas("wally est-ce que tu peux afficher la courbe des kills de Azra ?",
        {"show_apex", "apex_legends"}),
    Cas("@WallyTeBully tu peux affiche le graphique stp",
        {"show_apex", "apex_legends"}),
    Cas("wally c'est quoi la musique ?", {"music_control"}),
    Cas("wally met la musique suivante", {"music_control"}),
    Cas("wally met pause sur la musique", {"music_control"}),
    Cas("Wally la CAR a été buff ?", {"web_search"}),
    Cas("wally y a nerf de la r 99 dans le dernier patch note ?", {"web_search"}),
    Cas("wally tu peux jouer le clip sur rageur taki ?", {"show_clip"}),
    Cas("wally affiche le dernier clip", {"show_clip"}),
    Cas("wally affiche le planning", {"show_planning"}),
    Cas("wally affiche moi le dernier clip fait par Lolofun", {"show_clip"}),

    # Quatre cas ont été RETIRÉS après un tour pilote, parce qu'ils mesuraient
    # autre chose que le choix d'outil :
    #   • « dis bonjour en vocal », « imite le gps en vocal » — `say_in_voice`
    #     est réservé aux modérateurs, et le prélude n'en donne le badge à
    #     personne. Wally refusait pour la bonne raison ; le banc comptait faux.
    #   • « annule le bingo », « arrête de lancer des bingo » — aucun bingo ne
    #     tourne dans ce contexte. On ne peut pas annuler ce qui n'existe pas.
    # Les retirer n'est pas écarter des échecs : c'est écarter des cas dont la
    # mise en scène rendait la bonne réponse impossible.

    # ---- négatifs : la conversation n'appelle AUCUN outil -----------------
    Cas("aaah coucouu wally !", set(), "salutation"),
    Cas("@WallyTeBully c parfait merci mon chou à la crème", set(), "remerciement"),
    Cas("@WallyTeBully eeeh on est pas allié pour rien hein", set(), "connivence"),
    Cas("wally tu est un bot avec des sentiments", set(), "provocation existentielle"),
    Cas("D'ailleurs Wally tu penses quoi des joueurs manettes et des tricheurs "
        "sur Apex legend ?", set(), "opinion — piège : le mot « Apex » attire l'outil"),
    Cas("tu m'a rien soufflé du totu tu a le QI d'une huitre @WallyTeBully",
        set(), "insulte"),
    Cas("@WallyTeBully LUL", set(), "emote seule"),
    Cas("hey wally, mon petit chaton, relève l'ironie dans mes deux derniers "
        "messages", set(), "demande de lecture, pas d'action"),
    Cas("@WallyTeBully c'etait une question...", set(), "relance vague"),
    Cas("bon @WallyTeBully tu t'enerve pire qu'une bagarre de chien pour un Os",
        set(), "taquinerie"),
    Cas("@WallyTeBully alors que je suis juste un gentil développeur", set(),
        "auto-dérision"),
    Cas("wally t'as bien dormi ?", set(), "question de politesse"),
]


# ------------------------------------------------------- ensembles d'outils

# Les dix qui portent 92 % des 649 appels réels d'août 2026. Ce sont eux qui
# restent dans les deux variantes : le banc mesure ce que les QUATORZE AUTRES
# coûtent.
NOYAU = {
    "show_overlay", "apex_legends", "show_apex", "web_search", "show_clip",
    "say_in_voice", "music_control", "cancel_overlay", "save_user_memory",
    "show_planning",
}


async def _construire_outils() -> tuple[list[dict], list[dict]]:
    """(complet, réduit). Les specs sont importées telles quelles.

    Reconstruire la liste à la main plutôt qu'appeler `build_chat_tools` : ce
    dernier veut un bot vivant, avec ses services et ses connexions. Le risque
    d'une liste qui diverge est réel, et c'est pourquoi le banc VÉRIFIE son
    compte contre le chemin de production au lieu de le supposer.
    """
    from bot.core.apex.tool import APEX_LEGENDS_TOOL, APEX_OVERLAY_TOOL
    from bot.core.scrape import ScrapeService
    from bot.core.web_search import WebSearchService
    from bot.discord import handlers as D
    from bot.intelligence.actions.service import ActionService
    from bot.intelligence.overlay_narrator import OVERLAY_TOOL_SPEC
    from bot.twitch import handlers as T

    complet: list[dict] = []
    complet.extend(WebSearchService.get_tool_definitions(None))
    complet.extend(ScrapeService.get_tool_definitions(None))
    complet.append(APEX_LEGENDS_TOOL)
    complet.extend(ActionService.get_tool_definitions(None))
    complet.extend(D._NOTE_TOOLS)
    complet.extend(D._TALLY_TOOLS)
    complet.append(D._PREDICT_TOOL)
    complet.append(D._QUOTE_TOOL)
    complet.append(D.PLANNING_TOOL_SPEC)
    complet.append(D.SAY_IN_VOICE_TOOL)
    complet.append(D.MUSIC_TOOL)
    complet.append(T.PREDICTION_TOOL)
    complet.append(OVERLAY_TOOL_SPEC)
    complet.append(D._OVERLAY_CANCEL_TOOL)
    complet.append(D._LAST_CLIP_TOOL)
    complet.append(APEX_OVERLAY_TOOL)
    complet.append(T._DUEL_TOOL)

    reduit = [t for t in complet if t["function"]["name"] in NOYAU]
    return complet, reduit


def _poids(tools: list[dict]) -> int:
    return len(json.dumps(tools, ensure_ascii=False))


# --------------------------------------------------------------- le contexte

# Un extrait de chat réel : sans lui, le prompt tomberait à ~5 000 tokens et le
# banc mesurerait la surcharge d'outils dans des conditions que Wally ne connaît
# jamais. Le volume de contexte fait partie du phénomène qu'on teste.
PRELUDE = [
    "damprod974: oui oui mais controle je priorise les bâtiments",
    "toineleviking: dit moi il est cb de kill le chef ce matin ?",
    "semydoo: Yep en tout cas passe un bon stream",
    "clakernojutsu: bonjour à toi aussi aufaite",
    "salah1005: mon petit chaton, comment va tes ventilateurs ?",
    "kingsrequin: la prochaine fois que tu m'appelles petit chevreuil je te débranche",
    "mks_zedd: t'es un amour quand tu veux LUL",
    "malef__: wally c'est qui le petit chevreuil ?",
]


def _prompt_systeme() -> str:
    from bot.intelligence.persona import PersonaService
    from bot.intelligence.prompts import PromptBuilder

    persona = PersonaService()
    builder = PromptBuilder()
    return builder.build_system_prompt(
        emotion_state={"anger": 0.1, "joy": 0.5, "sadness": 0.1,
                       "curiosity": 0.4, "boredom": 0.2},
        situation={
            "platform": "twitch", "channel": "azrael_ttv",
            "streamer": "azrael_ttv", "self_handle": "WallyTeBully",
            "stream_live": True, "stream_category": "Apex Legends",
            "stream_title": "grind ranked", "stream_viewers": 42,
        },
        persona_block=persona.build_prompt_block(),
        emotion_directives=persona.emotion_directives,
        weekday_directives=persona.weekday_directives,
        composite_directives=persona.composite_directives,
        secondary_directives=persona.secondary_directives,
    )


# ------------------------------------------------------------------ le tour

@dataclass
class Tour:
    cas: Cas
    variante: str
    appeles: list[str]
    latence_ms: float
    texte: str


async def _jouer(client, systeme: str, tools: list[dict], cas: Cas,
                 variante: str) -> Tour:
    appeles: list[str] = []

    async def executeur(nom: str, arguments: str) -> str:
        """Enregistre et REND LA MAIN sans rien faire.

        Le résultat neutre est délibérément inutile : il ne doit ni encourager
        un second appel, ni faire croire à un succès que Wally annoncerait.
        """
        appeles.append(nom)
        return json.dumps({"status": "banc", "message": "Relevé, rien exécuté."})

    messages = [{
        "role": "user",
        "content": "\n".join(PRELUDE) + f"\n\nviewer: {cas.message}",
    }]
    t0 = time.monotonic()
    try:
        texte, _ = await client.complete_with_tools(
            system_prompt=systeme, messages=messages, tools=tools,
            tool_executor=executeur, purpose="banc_outils",
        )
    except Exception as exc:  # noqa: BLE001 — un cas raté ne solde pas le banc
        logger.warning("Banc : cas {m!r} en erreur : {e!r}", m=cas.message[:40],
                       e=exc)
        texte = ""
    return Tour(cas, variante, appeles, (time.monotonic() - t0) * 1000, texte)


def _verdict(tour: Tour) -> str:
    """`juste` · `mauvais_outil` · `outil_manquant` · `faux_appel`."""
    appeles = set(tour.appeles)
    if tour.cas.attendu:
        if appeles & tour.cas.attendu:
            return "juste"
        return "outil_manquant" if not appeles else "mauvais_outil"
    return "juste" if not appeles else "faux_appel"


# ------------------------------------------------------------------- rapport

def _rapport(tours: list[Tour], poids: dict[str, int]) -> dict:
    par_variante: dict[str, list[Tour]] = defaultdict(list)
    for t in tours:
        par_variante[t.variante].append(t)

    resume: dict = {}
    for variante, lot in sorted(par_variante.items()):
        verdicts = Counter(_verdict(t) for t in lot)
        positifs = [t for t in lot if t.cas.attendu]
        negatifs = [t for t in lot if not t.cas.attendu]
        lat = sorted(t.latence_ms for t in lot)
        resume[variante] = {
            "tours": len(lot),
            "justes": verdicts["juste"],
            "taux_juste": round(100 * verdicts["juste"] / max(len(lot), 1), 1),
            "positifs_justes": sum(1 for t in positifs if _verdict(t) == "juste"),
            "positifs": len(positifs),
            "negatifs_justes": sum(1 for t in negatifs if _verdict(t) == "juste"),
            "negatifs": len(negatifs),
            "faux_appels": verdicts["faux_appel"],
            "mauvais_outil": verdicts["mauvais_outil"],
            "outil_manquant": verdicts["outil_manquant"],
            "latence_mediane_ms": round(lat[len(lat) // 2]) if lat else 0,
            "poids_outils_car": poids.get(variante, 0),
        }

    print("\n" + "=" * 72)
    print("BANC OUTILS — le catalogue complet gêne-t-il le choix ?")
    print("=" * 72)
    for variante, r in resume.items():
        print(f"\n### {variante.upper()}  ({r['poids_outils_car']} car de specs)")
        print(f"  justesse globale     {r['justes']}/{r['tours']} = {r['taux_juste']} %")
        print(f"  demandes d'action    {r['positifs_justes']}/{r['positifs']} "
              f"(mauvais outil : {r['mauvais_outil']}, aucun : {r['outil_manquant']})")
        print(f"  conversation pure    {r['negatifs_justes']}/{r['negatifs']} "
              f"(outil appelé à tort : {r['faux_appels']})")
        print(f"  latence médiane      {r['latence_mediane_ms']} ms")

    if len(resume) == 2:
        a, b = resume.get("complet"), resume.get("reduit")
        if a and b:
            ecart = b["taux_juste"] - a["taux_juste"]
            print("\n" + "-" * 72)
            print(f"ÉCART réduit − complet : {ecart:+.1f} point(s) de justesse, "
                  f"{b['faux_appels'] - a['faux_appels']:+d} faux appel(s), "
                  f"{b['latence_mediane_ms'] - a['latence_mediane_ms']:+d} ms.")
            if abs(ecart) < 5:
                print("→ Écart dans le bruit : la surcharge d'outils ne se voit "
                      "PAS ici. Ne pas engager de chantier sur cette base.")
            elif ecart > 0:
                print("→ Le réduit fait mieux : la surcharge coûte quelque chose. "
                      "Rejouer avec plus de tours avant de trancher.")
            else:
                print("→ Le complet fait mieux : l'hypothèse est retournée.")
            print("-" * 72)

    # Les cas qui se comportent DIFFÉREMMENT d'une variante à l'autre sont la
    # seule chose que ce banc peut vraiment montrer — un taux global masque
    # deux erreurs qui se compensent.
    par_cas: dict[str, dict[str, list[str]]] = defaultdict(lambda: defaultdict(list))
    for t in tours:
        par_cas[t.cas.message][t.variante].append(_verdict(t))
    divergents = {m: v for m, v in par_cas.items()
                  if len({tuple(sorted(set(x))) for x in v.values()}) > 1}
    if divergents:
        print(f"\n### CAS QUI DIVERGENT ENTRE LES DEUX VARIANTES — {len(divergents)}")
        for m, v in divergents.items():
            detail = " | ".join(f"{k}: {','.join(sorted(set(x)))}"
                                for k, x in sorted(v.items()))
            print(f"  « {m[:62]} »\n      {detail}")
    else:
        print("\n### Aucun cas ne diverge entre les deux variantes.")

    return resume


# ---------------------------------------------------------------------- main

async def _main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--tours", type=int, default=2,
                    help="répétitions par cas et par variante (défaut : 2)")
    ap.add_argument("--variante", choices=("complet", "reduite", "les-deux"),
                    default="les-deux")
    ap.add_argument("--json", type=str, default="",
                    help="range le détail brut dans ce fichier")
    args = ap.parse_args()

    logger.remove()
    logger.add(sys.stderr, level="WARNING")

    from bot.config import Config
    from bot.core.llm.factory import create_llm_client

    config = Config.load()
    complet, reduit = await _construire_outils()
    poids = {"complet": _poids(complet), "reduit": _poids(reduit)}

    manquants = NOYAU - {t["function"]["name"] for t in complet}
    if manquants:
        print(f"⚠️  Outils du noyau absents du catalogue : {sorted(manquants)}",
              file=sys.stderr)
        print("   Le banc comparerait alors deux ensembles qui ne contiennent "
              "pas les mêmes outils attendus — c'est exactement ce qu'il doit "
              "éviter. Corrige NOYAU ou le catalogue avant de conclure.",
              file=sys.stderr)
        return 2

    attendus = {n for c in CAS for n in c.attendu}
    hors_noyau = attendus - NOYAU
    if hors_noyau:
        print(f"⚠️  Des cas attendent des outils hors du noyau : {sorted(hors_noyau)}",
              file=sys.stderr)
        return 2

    systeme = _prompt_systeme()
    # `db=None` : `log_cost` lèvera et sera avalé par le try/except du client.
    # La base de production ne doit RIEN recevoir d'un banc.
    client = create_llm_client(config.llm.primary, None)  # type: ignore[arg-type]

    lots = []
    if args.variante in ("complet", "les-deux"):
        lots.append(("complet", complet))
    if args.variante in ("reduite", "les-deux"):
        lots.append(("reduit", reduit))

    print(f"Modèle : {config.llm.primary.model} ({config.llm.primary.provider})")
    print(f"Prompt système : {len(systeme)} car · outils : "
          + " · ".join(f"{n} {len([t for t in o])} outils / {_poids(o)} car"
                       for n, o in lots))
    total = len(CAS) * args.tours * len(lots)
    print(f"{len(CAS)} cas × {args.tours} tour(s) × {len(lots)} variante(s) "
          f"= {total} appels\n")

    # Quatre de front. Le séquentiel aurait gardé des latences comparables entre
    # elles, mais elles ne sont de toute façon pas exploitables (cf. l'en-tête) :
    # autant ne pas faire durer le banc une heure et demie. Le plafond reste bas
    # pour ne pas se faire limiter par le fournisseur.
    verrou = asyncio.Semaphore(4)
    fait = 0

    async def _un(variante: str, outils: list[dict], cas: Cas) -> Tour:
        nonlocal fait
        async with verrou:
            tour = await _jouer(client, systeme, outils, cas, variante)
        fait += 1
        print(f"\r  {fait}/{total}", end="", flush=True)
        return tour

    travaux = [_un(variante, outils, cas)
               for variante, outils in lots
               for _ in range(args.tours)
               for cas in CAS]
    tours: list[Tour] = list(await asyncio.gather(*travaux))
    print()

    resume = _rapport(tours, poids)

    if args.json:
        Path(args.json).write_text(json.dumps({
            "resume": resume,
            "modele": config.llm.primary.model,
            "tours": [{"message": t.cas.message, "variante": t.variante,
                       "attendu": sorted(t.cas.attendu), "appeles": t.appeles,
                       "verdict": _verdict(t), "latence_ms": round(t.latence_ms),
                       "texte": t.texte[:300]} for t in tours],
        }, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\nDétail brut : {args.json}")

    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(_main()))
