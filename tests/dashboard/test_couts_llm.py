"""`GET /api/admin/couts` — la mesure qui existait sans être montrée.

`log_cost()` écrit dans `cost_log` depuis toujours. L'onglet Coûts a été retiré
(remplacé par Langfuse, puis abandonné) : la table s'est remplie pendant des
mois sans que rien ne la lise. C'est la signature de panne que tout le projet
traque — quelque chose se passe, personne n'est prévenu.
"""
from __future__ import annotations

import time
import types

from bot.dashboard.routes.admin import couts_llm


class _FauxDB:
    def __init__(self, lignes: list[dict]):
        self.lignes = lignes

    def _fenetre(self, depuis):
        return [l for l in self.lignes if l["timestamp"] >= depuis]

    async def get_cost_breakdown(self, depuis, group_by):
        groupes: dict[str, dict] = {}
        for l in self._fenetre(depuis):
            g = groupes.setdefault(l[group_by], {"key": l[group_by], "total": 0.0, "count": 0})
            g["total"] += l["cost_usd"]
            g["count"] += 1
        return sorted(groupes.values(), key=lambda g: -g["total"])

    async def get_daily_costs(self, depuis, jusqu=None):
        return [{"date": f"2026-08-{j:02d}", "cost": 1.0} for j in range(1, 21)]

    async def fetch_all(self, query, params=()):
        depuis = params[0]
        vus: dict[tuple, int] = {}
        for l in self._fenetre(depuis):
            vus[(l["purpose"], l["model"])] = vus.get((l["purpose"], l["model"]), 0) + 1
        return [{"purpose": p, "model": m, "n": n} for (p, m), n in vus.items()]


def _requete(lignes, latence=None):
    wally = types.SimpleNamespace(db=_FauxDB(lignes), avg_response_ms=latence)
    return types.SimpleNamespace(
        app=types.SimpleNamespace(state=types.SimpleNamespace(wally=wally))
    )


def _ligne(purpose, model, cout, il_y_a_h=1.0):
    return {
        "timestamp": time.time() - il_y_a_h * 3600,
        "purpose": purpose, "model": model, "cost_usd": cout,
    }


async def test_les_usages_sont_rendus_du_plus_cher_au_moins_cher():
    d = await couts_llm(_requete([
        _ligne("gate", "flash", 0.01),
        _ligne("reasoning", "flash", 3.10),
        _ligne("response", "flash", 0.64),
    ]))
    assert [u["usage"] for u in d["usages"]] == ["reasoning", "response", "gate"]
    assert d["total"] == 3.75


async def test_chaque_usage_dit_quel_modele_le_sert():
    """La question qu'on se pose devant une ligne chère : par QUOI ?
    La table de coûts seule n'y répond pas."""
    d = await couts_llm(_requete([
        _ligne("twitch_response", "gpt-5.6-luna", 1.0),
        _ligne("twitch_response", "gpt-5.6-luna", 1.0),
        _ligne("reasoning", "deepseek-v4-flash", 0.5),
    ]))
    par_usage = {u["usage"]: u["modeles"] for u in d["usages"]}
    assert par_usage["twitch_response"] == ["gpt-5.6-luna"]
    assert par_usage["reasoning"] == ["deepseek-v4-flash"]


async def test_un_usage_servi_par_deux_modeles_les_montre_tous_les_deux():
    d = await couts_llm(_requete([
        _ligne("response", "flash", 1.0),
        _ligne("response", "luna", 1.0),
    ]))
    modeles = next(u for u in d["usages"] if u["usage"] == "response")["modeles"]
    assert set(modeles) == {"flash", "luna"}


async def test_la_fenetre_exclut_ce_qui_est_trop_vieux():
    d = await couts_llm(_requete([
        _ligne("récent", "flash", 1.0, il_y_a_h=2),
        _ligne("vieux", "flash", 9.0, il_y_a_h=48),
    ]), heures=24)
    assert [u["usage"] for u in d["usages"]] == ["récent"]
    assert d["total"] == 1.0


async def test_la_courbe_rend_exactement_le_nombre_de_jours_demande():
    """`now - 14 × 86400` touche QUINZE dates civiles : le titre
    « 14 derniers jours » se retrouvait au-dessus de quinze barres."""
    d = await couts_llm(_requete([]), jours=14)
    assert len(d["jours"]) == 14
    # Et ce sont bien les plus RÉCENTS.
    assert d["jours"][-1]["date"] == "2026-08-20"


async def test_un_usage_vide_ne_disparait_pas_sous_une_chaine_nulle():
    d = await couts_llm(_requete([_ligne(None, "flash", 1.0)]))
    assert d["usages"][0]["usage"] == "(sans usage)"


async def test_la_latence_est_relayee_telle_quelle():
    d = await couts_llm(_requete([], latence=1234.5))
    assert d["latence_moyenne_ms"] == 1234.5


async def test_une_fenetre_absurde_est_bornee():
    """`?heures=0` ne doit devenir ni « tout », ni « rien »."""
    d = await couts_llm(_requete([_ligne("x", "flash", 1.0, il_y_a_h=0.5)]), heures=0)
    assert d["fenetre_heures"] == 1
    assert d["total"] == 1.0
