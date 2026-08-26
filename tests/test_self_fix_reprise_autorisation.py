"""Une demande d'auto-modification doit survivre au redémarrage du bot.

`_await_reaction` est un `wait_for` EN MÉMOIRE, et un self-fix se termine par un
`docker_rebuild` : le cas est structurel. Jusqu'au 2026-08-26, rien ne relisait
le DM au démarrage — cliquer ✅ après un rebuild ne déclenchait plus rien et la
demande mourait en `abandoned` sans que personne ne l'ait refusée. Deux fois la
même demande sur ce dépôt (#22 le 2026-08-17, #25 le 2026-08-25).
"""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from bot.db.schema_v2 import create_v2_tables
from bot.intelligence.self_fix import SelfFix
from bot.intelligence.upgrade_registry import (
    ABANDONED,
    DECLINED,
    REQUESTED,
    UpgradeRegistry,
)

OWNER = "610550333042589752"


async def make_registry(tmp_path):
    chemin = str(tmp_path / "reprise.db")
    await create_v2_tables(chemin)
    return UpgradeRegistry(chemin)


def make_reaction(emoji: str, *user_ids: str):
    """Une réaction Discord dont `users()` est un itérateur asynchrone."""

    async def users():
        for uid in user_ids:
            yield SimpleNamespace(id=uid)

    return SimpleNamespace(emoji=emoji, users=users)


def make_self_fix(registry, message, *, owner_id: str = OWNER):
    dm = SimpleNamespace(id=777, fetch_message=AsyncMock(return_value=message), send=AsyncMock())
    bot = SimpleNamespace(
        config=SimpleNamespace(bot=SimpleNamespace(owner_discord_id=owner_id, name="wally")),
        memory=None,
        fetch_user=AsyncMock(return_value=SimpleNamespace(create_dm=AsyncMock(return_value=dm))),
    )
    sf = SelfFix(bridge=MagicMock(), bot=bot, registry=registry)
    return sf, dm


# --- le registre range et rend le DM ----------------------------------------


async def test_une_demande_sans_dm_range_n_est_pas_reprenable(tmp_path):
    """Les 25 demandes d'avant ce correctif n'ont pas de `message_id` : il ne
    faut pas prétendre les reprendre."""
    registry = await make_registry(tmp_path)
    await registry.record_request("faire quelque chose")

    assert await registry.reprenables() == []


async def test_le_dm_range_rend_la_demande_reprenable(tmp_path):
    registry = await make_registry(tmp_path)
    uid = await registry.record_request("faire quelque chose")

    await registry.set_message(uid, "555", "777")

    lignes = await registry.reprenables()
    assert [(x.id, x.message_id, x.dm_channel_id) for x in lignes] == [(uid, "555", "777")]


async def test_une_demande_deja_tranchee_n_est_plus_reprenable(tmp_path):
    registry = await make_registry(tmp_path)
    uid = await registry.record_request("faire quelque chose")
    await registry.set_message(uid, "555", "777")
    await registry.set_status(uid, DECLINED)

    assert await registry.reprenables() == []


# --- le DM est rangé AU MOMENT de la demande --------------------------------


async def test_la_demande_range_son_dm_avant_de_se_mettre_a_attendre(tmp_path):
    """Le maillon dont tout le reste dépend : sans ce couple en base, il n'y a
    rien à relire au démarrage et la reprise ne peut pas exister."""
    registry = await make_registry(tmp_path)
    message = SimpleNamespace(id=555, add_reaction=AsyncMock())
    sf, dm = make_self_fix(registry, message)
    dm.send = AsyncMock(return_value=message)
    sf._attendre_et_conclure = AsyncMock()
    uid = await registry.record_request("faire quelque chose")

    await sf._run_upgrade("faire quelque chose", "faire quelque chose", uid)

    lignes = await registry.reprenables()
    assert [(x.id, x.message_id, x.dm_channel_id) for x in lignes] == [(uid, "555", "777")]


async def test_un_registre_muet_ne_fait_pas_tomber_la_demande(tmp_path):
    """Ranger le DM est un filet ; s'il casse, la demande doit partir quand même."""
    registry = await make_registry(tmp_path)
    registry.set_message = AsyncMock(side_effect=RuntimeError("base verrouillée"))
    message = SimpleNamespace(id=555, add_reaction=AsyncMock())
    sf, dm = make_self_fix(registry, message)
    dm.send = AsyncMock(return_value=message)
    sf._attendre_et_conclure = AsyncMock()

    await sf._run_upgrade("faire quelque chose", "faire quelque chose", 1)

    sf._attendre_et_conclure.assert_awaited_once()


# --- la reprise au démarrage ------------------------------------------------


async def test_un_refus_cliqué_pendant_le_rebuild_est_bien_pris(tmp_path):
    registry = await make_registry(tmp_path)
    uid = await registry.record_request("faire quelque chose")
    await registry.set_message(uid, "555", "777")
    message = SimpleNamespace(id=555, reactions=[make_reaction("❌", OWNER)])
    sf, _ = make_self_fix(registry, message)

    assert await sf.reprendre_demandes_en_attente() == 1

    ligne = await registry.get(uid)
    assert ligne.status == DECLINED


async def test_les_reactions_posees_par_wally_ne_valent_pas_decision(tmp_path):
    """Wally pose lui-même ✅ et ❌ pour offrir les boutons — leurs compteurs sont
    donc à 1 sans que personne n'ait répondu. Compter, c'est se tromper.

    ⚠️ Ce test guettait d'abord le STATUT, et ne mordait pas : sur un bridge
    simulé, le pipeline lève de toute façon et laisse la ligne en REQUESTED.
    Retirer le filtre « qui a réagi » passait au vert. C'est l'appel qu'il faut
    guetter, pas sa conséquence.
    """
    registry = await make_registry(tmp_path)
    uid = await registry.record_request("faire quelque chose")
    await registry.set_message(uid, "555", "777")
    wally = "999000111"
    message = SimpleNamespace(
        id=555,
        reactions=[make_reaction("✅", wally), make_reaction("❌", wally)],
    )
    sf, _ = make_self_fix(registry, message)
    sf._apres_decision = AsyncMock()
    sf._attendre_et_conclure = AsyncMock()

    await sf.reprendre_demandes_en_attente()
    await asyncio.sleep(0)

    sf._apres_decision.assert_not_called()
    assert (await registry.get(uid)).status == REQUESTED


async def test_une_autorisation_cliquee_pendant_le_rebuild_relance_le_chantier(tmp_path):
    """Le pendant du refus : un ✅ posé pendant que le bot était éteint doit
    reprendre le fil là où il s'était arrêté."""
    registry = await make_registry(tmp_path)
    uid = await registry.record_request("faire quelque chose")
    await registry.set_message(uid, "555", "777")
    message = SimpleNamespace(
        id=555,
        reactions=[make_reaction("✅", OWNER), make_reaction("❌", "999000111")],
    )
    sf, _ = make_self_fix(registry, message)
    sf._apres_decision = AsyncMock()

    assert await sf.reprendre_demandes_en_attente() == 1

    sf._apres_decision.assert_awaited_once()
    emoji, goal, _norm, upgrade_id, _dm = sf._apres_decision.await_args.args
    assert (emoji, goal, upgrade_id) == ("✅", "faire quelque chose", uid)


async def test_sans_reaction_l_attente_est_reprise_et_non_abandonnee(tmp_path):
    registry = await make_registry(tmp_path)
    uid = await registry.record_request("faire quelque chose")
    await registry.set_message(uid, "555", "777")
    message = SimpleNamespace(id=555, reactions=[])
    sf, _ = make_self_fix(registry, message)
    attendu = {}

    async def _attendre(*args):
        attendu["timeout"] = args[-1]
        await asyncio.sleep(0)

    sf._attendre_et_conclure = _attendre

    assert await sf.reprendre_demandes_en_attente() == 1
    await asyncio.sleep(0)

    assert (await registry.get(uid)).status == REQUESTED
    # Le temps qui reste, pas la fenêtre entière : la demande a déjà vieilli.
    assert 0 < attendu["timeout"] <= sf._approval_timeout


async def test_une_fenetre_ecoulee_ne_relance_aucune_attente(tmp_path):
    """Passé le délai, c'est `reconcile_stale` qui tranche, pas la reprise."""
    registry = await make_registry(tmp_path)
    uid = await registry.record_request("faire quelque chose")
    await registry.set_message(uid, "555", "777")
    message = SimpleNamespace(id=555, reactions=[])
    sf, _ = make_self_fix(registry, message)
    sf._approval_timeout = 0.0
    sf._attendre_et_conclure = AsyncMock()

    assert await sf.reprendre_demandes_en_attente() == 0

    sf._attendre_et_conclure.assert_not_called()
    assert (await registry.get(uid)).status == REQUESTED


async def test_un_dm_disparu_ne_fait_pas_tomber_le_demarrage(tmp_path):
    registry = await make_registry(tmp_path)
    uid = await registry.record_request("faire quelque chose")
    await registry.set_message(uid, "555", "777")
    sf, dm = make_self_fix(registry, SimpleNamespace(id=555, reactions=[]))
    dm.fetch_message = AsyncMock(side_effect=RuntimeError("Unknown Message"))

    assert await sf.reprendre_demandes_en_attente() == 0
    assert (await registry.get(uid)).status == REQUESTED


async def test_sans_createur_configure_on_ne_reprend_rien(tmp_path):
    registry = await make_registry(tmp_path)
    uid = await registry.record_request("faire quelque chose")
    await registry.set_message(uid, "555", "777")
    sf, _ = make_self_fix(registry, SimpleNamespace(id=555, reactions=[]), owner_id="")

    assert await sf.reprendre_demandes_en_attente() == 0
    assert (await registry.get(uid)).status == REQUESTED


async def test_rien_a_reprendre_ne_touche_pas_au_dm(tmp_path):
    registry = await make_registry(tmp_path)
    sf, dm = make_self_fix(registry, SimpleNamespace(id=555, reactions=[]))

    assert await sf.reprendre_demandes_en_attente() == 0
    dm.fetch_message.assert_not_called()


# --- le temps restant -------------------------------------------------------


def test_une_date_illisible_vaut_fenetre_ecoulee():
    """Plutôt relancer une attente de zéro qu'en ouvrir une de 72 h sur une
    ligne dont on ne sait rien."""
    sf = SelfFix(bridge=MagicMock(), bot=SimpleNamespace())

    assert sf._temps_restant("pas une date") == 0.0
    assert sf._temps_restant(None) == 0.0


def test_la_fenetre_restante_decroit_avec_l_age():
    from datetime import datetime, timedelta, timezone

    sf = SelfFix(bridge=MagicMock(), bot=SimpleNamespace())
    maintenant = datetime.now(timezone.utc).replace(tzinfo=None)
    jeune = sf._temps_restant((maintenant - timedelta(hours=1)).isoformat())
    vieille = sf._temps_restant((maintenant - timedelta(hours=48)).isoformat())

    assert jeune > vieille > 0
    assert vieille == pytest.approx(sf._approval_timeout - 48 * 3600, abs=60)
