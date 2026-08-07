"""Compteurs à la demande.

Le modèle ne travaille qu'à la création (traduire la demande en formulations) ;
la détection qui suit est mécanique. Wally entend des centaines de phrases par
live — les faire juger une à une par un LLM serait ruineux et lent.
"""
import json
import time

import pytest

from bot.core.tally import TallyService, _normalize


class _FakeDB:
    """Base en mémoire : on teste la logique de comptage, pas SQLite."""

    def __init__(self):
        self.rows: list[dict] = []
        self._next = 1

    async def execute(self, query, params=()):
        q = " ".join(query.split())
        if q.startswith("INSERT INTO tally_counters"):
            label, keywords, target, created = params
            for r in self.rows:
                if r["label"] == label:
                    r.update(active=1, keywords=keywords)
                    return
            self.rows.append({"id": self._next, "label": label, "keywords": keywords,
                              "target": target, "count": 0, "active": 1,
                              "created_at": created, "last_hit_at": None})
            self._next += 1
        elif q.startswith("UPDATE tally_counters SET count"):
            at, rid = params
            for r in self.rows:
                if r["id"] == rid:
                    r["count"] += 1
                    r["last_hit_at"] = at
        elif q.startswith("UPDATE tally_counters SET active"):
            for r in self.rows:
                if r["id"] == params[0]:
                    r["active"] = 0

    async def fetch_one(self, query, params=()):
        return next((r for r in self.rows if r["label"] == params[0]), None)

    async def fetch_all(self, query, params=()):
        rows = self.rows
        if "active = 1" in query:
            rows = [r for r in rows if r["active"]]
        return list(rows)


def _svc():
    return TallyService(_FakeDB())


# ── normalisation ──

def test_les_accents_ne_font_pas_rater_une_occurrence():
    """Le STT accentue au petit bonheur : « recharge » / « rechargé »."""
    assert _normalize("J'ai pas RECHARGÉ !") == " j ai pas recharge "


@pytest.mark.asyncio
async def test_un_mot_court_ne_compte_pas_au_milieu_d_un_autre():
    """« lag » est contenu dans « village » : sans bornes, on compterait faux."""
    s = _svc()
    await s.start("lag", ["lag"])
    assert await s.scan("on traverse le village") == []
    assert len(await s.scan("c'est le lag")) == 1


# ── cycle de vie ──

@pytest.mark.asyncio
async def test_un_compteur_s_ouvre_et_compte():
    s = _svc()
    await s.start("pas rechargé", ["pas recharge", "plus de balles"])
    touched = await s.scan("mais j'ai pas rechargé encore")
    assert len(touched) == 1 and touched[0]["count"] == 1


@pytest.mark.asyncio
async def test_une_phrase_hors_sujet_ne_compte_pas():
    s = _svc()
    await s.start("pas rechargé", ["pas recharge"])
    assert await s.scan("belle partie les gars") == []


@pytest.mark.asyncio
async def test_une_meme_phrase_ne_compte_qu_une_fois():
    """« j'ai pas rechargé, j'avais plus de balles » = une occurrence."""
    s = _svc()
    await s.start("pas rechargé", ["pas recharge", "plus de balles"])
    touched = await s.scan("j'ai pas rechargé, j'avais plus de balles")
    assert len(touched) == 1


@pytest.mark.asyncio
async def test_deux_occurrences_espacees_comptent_deux_fois():
    s = _svc()
    await s.start("pas rechargé", ["pas recharge"])
    t0 = time.time()
    await s.scan("pas rechargé", now=t0)
    await s.scan("pas rechargé", now=t0 + 60)
    assert (await s.get("pas rechargé"))["count"] == 2


@pytest.mark.asyncio
async def test_un_compteur_arrete_ne_compte_plus():
    s = _svc()
    await s.start("morts", ["je suis mort"])
    await s.stop("morts")
    assert await s.scan("je suis mort") == []


@pytest.mark.asyncio
async def test_un_compteur_arrete_garde_son_total():
    """« Alors, ça a donné quoi ? » doit rester répondable après coup."""
    s = _svc()
    await s.start("morts", ["je suis mort"])
    await s.scan("je suis mort")
    stopped = await s.stop("morts")
    assert stopped["count"] == 1


@pytest.mark.asyncio
async def test_relancer_un_compteur_reprend_son_total():
    """On ne remet pas à zéro un gag qui court depuis trois streams."""
    s = _svc()
    await s.start("morts", ["je suis mort"])
    await s.scan("je suis mort")
    await s.stop("morts")
    await s.start("morts", ["je suis mort"])
    assert (await s.get("morts"))["count"] == 1


@pytest.mark.asyncio
async def test_une_demande_sans_formulation_est_refusee():
    s = _svc()
    assert await s.start("truc", []) is None
    assert await s.start("truc", ["ab"]) is None      # trop court : compterait tout


@pytest.mark.asyncio
async def test_le_nombre_de_formulations_est_borne():
    """Au-delà, ce n'est plus un compteur mais un filtre à faux positifs."""
    s = _svc()
    await s.start("truc", [f"formulation {i}" for i in range(30)])
    assert len(json.loads((await s.get("truc"))["keywords"])) == 8


@pytest.mark.asyncio
async def test_plusieurs_compteurs_coexistent():
    s = _svc()
    await s.start("morts", ["je suis mort"])
    await s.start("ping", ["c est le ping", "lag"])
    touched = await s.scan("je suis mort, c'est le ping")
    assert {t["label"] for t in touched} == {"morts", "ping"}


@pytest.mark.asyncio
async def test_lister_montre_les_totaux():
    s = _svc()
    await s.start("morts", ["je suis mort"])
    await s.scan("je suis mort")
    rows = await s.list()
    assert rows[0]["label"] == "morts" and rows[0]["count"] == 1


# ── un compteur de morts n'est qu'un compteur parmi d'autres ──

@pytest.mark.asyncio
async def test_le_compteur_de_morts_fonctionne_comme_les_autres():
    """Le widget 15 était bloqué faute de signal ; il n'a pas besoin d'un
    mécanisme à lui, juste de bonnes formulations."""
    s = _svc()
    await s.start("morts d'Azraël", ["je suis mort", "je suis down", "ah putain je meurs"])
    assert len(await s.scan("non mais je suis mort là")) == 1
    assert await s.scan("belle partie") == []


@pytest.mark.asyncio
async def test_une_formulation_avec_accents_est_retrouvee():
    """Les transcriptions vocales accentuent au hasard."""
    s = _svc()
    await s.start("rechargé", ["j ai pas recharge"])
    assert len(await s.scan("J'AI PAS RECHARGÉ !!")) == 1
