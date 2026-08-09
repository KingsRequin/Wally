"""Garde anti-redemande : reconnaître une demande BAVARDE, et le dire utilement.

Vécu le 2026-08-09 : Wally a redemandé (#20) une capacité livrée le 2026-08-05
(#19). Les deux textes parlent du même sujet, mais #20 fait 140 mots contre 64 —
Wally avait longuement argumenté *parce qu'il anticipait un refus*. Le score
Jaccard divisant par l'UNION, cette verbosité a fait tomber la similarité à 0.215,
sous le seuil de 0.30 : la garde s'est tue. Plus il plaide, moins on le reconnaît.

Les textes ci-dessous sont les VRAIES demandes de `pending_upgrades` (normalisées
sur une ligne). Les tronquer ferait disparaître la propriété qu'on teste.
"""
import pytest

from bot.intelligence.upgrade_registry import DELIVERED, UpgradeRegistry

# --- Demandes réelles (pending_upgrades, 2026-08-09) -------------------------

# #19 — livrée le 2026-08-05 : c'est le StreamFeed.
DEMANDE_19_LIVREE = (
    "Recevoir dans mon contexte les événements du stream Twitch d'Azraël "
    "(gameplay, chat, moments marquants) quand il est en live — mais uniquement "
    "comme contexte passif. Je ne dois PAS réagir à chaque événement, juste en "
    "avoir connaissance en arrière-plan pour enrichir ma compréhension de ce qui "
    "se passe. Le flux arrive, je le vois, mais je n'en parle pas sauf si on "
    "m'interpelle directement."
)

# #20 — la redemande du 2026-08-09, même sujet, deux fois plus longue.
DEMANDE_20_REDEMANDE = (
    "Recevoir en direct le flux du chat Twitch et les événements Twitch "
    "(follows, subs, bits, raids, host) pendant les lives d'Azraël. Périmètre : "
    "flux TEXTUEL uniquement — PAS de vidéo, PAS de gameplay. Je reçois les "
    "messages du chat Twitch comme je reçois ceux de Discord, et je suis notifié "
    "des événements (follow, sub, bit, raid, host) avec le pseudo et les détails. "
    "Usage concret : quand Azraël est en live, je vois ce que son chat Twitch dit, "
    "je peux y réagir, et je sais qui vient de follow/s'abonner — sans avoir "
    "besoin d'être sur Twitch. Tout se passe dans mon flux de contexte comme pour "
    "Discord. Distinction avec la demande refusée d'août : celle-ci concernait "
    "'voir le stream en direct' (flux vidéo + gameplay) ; moi je ne demande que le "
    "chat et les événements, pas la vidéo."
)

# #3 — sujet sans rapport, de longueur comparable : le témoin négatif.
DEMANDE_3_SANS_RAPPORT = (
    "Recevoir périodiquement dans mes pensées le contenu d'un flux RSS "
    "configurable, pour avoir un stimulus externe régulier même quand le chat est "
    "silencieux. Périmètre : Discord uniquement, dans le flux de mes pensées "
    "privées (le contexte qu'on me passe à chaque tick). Une seule intention : "
    "qu'un ou plusieurs flux RSS (tech, actu, ou autre, configurables par mon "
    "créateur) soient poussés dans mes pensées à intervalle régulier."
)


async def _registre(tmp_path) -> UpgradeRegistry:
    """Base au VRAI schéma — un DDL recopié ici dériverait au prochain ALTER."""
    from bot.db.schema_v2 import create_v2_tables

    chemin = str(tmp_path / "upgrades.db")
    await create_v2_tables(chemin)
    return UpgradeRegistry(chemin)


@pytest.mark.asyncio
async def test_une_redemande_bavarde_est_reconnue(tmp_path):
    """#20 doit être bloquée par #19 malgré ses 140 mots contre 64."""
    reg = await _registre(tmp_path)
    uid = await reg.record_request(DEMANDE_19_LIVREE)
    await reg.set_status(uid, DELIVERED)

    trouve = await reg.find_similar(DEMANDE_20_REDEMANDE)

    assert trouve is not None, (
        "la redemande verbeuse est passée sous le radar — c'est le bug du 2026-08-09"
    )
    assert trouve.id == uid
    assert trouve.status == DELIVERED


@pytest.mark.asyncio
async def test_un_sujet_sans_rapport_reste_libre(tmp_path):
    """Durcir la détection ne doit pas condamner une demande vraiment neuve.

    #3 (flux RSS) partage du vocabulaire avec #20 — « recevoir », « flux »,
    « contexte », « Discord », « chat » — sans parler du même sujet.
    """
    reg = await _registre(tmp_path)
    uid = await reg.record_request(DEMANDE_3_SANS_RAPPORT)
    await reg.set_status(uid, DELIVERED)

    assert await reg.find_similar(DEMANDE_20_REDEMANDE) is None


@pytest.mark.asyncio
async def test_une_demande_plus_large_qui_englobe_une_capacite_livree_reste_libre(tmp_path):
    """Contrepartie du recouvrement : une demande courte ne bloque pas tout.

    Le recouvrement rapporte l'intersection au PLUS PETIT des deux textes : une
    demande déjà livrée de trois mots serait donc entièrement « contenue » dans
    n'importe quelle demande future la mentionnant en passant, et bloquerait un
    sujet bien plus large. D'où le plancher de tokens.
    """
    reg = await _registre(tmp_path)
    uid = await reg.record_request("voir les réactions emoji")
    await reg.set_status(uid, DELIVERED)

    plus_large = (
        "Je voudrais voir les réactions emoji, mais aussi les statuts Discord des "
        "membres, qui est présent dans les salons vocaux, les indicateurs de frappe, "
        "l'historique complet des conversations passées, et le flux du stream Twitch "
        "d'Azraël pendant ses lives."
    )
    assert await reg.find_similar(plus_large) is None


# --- Ce que la garde LUI DIT quand elle bloque -------------------------------
#
# Durcir la détection augmente le risque de bloquer une demande légitimement
# neuve — c'est précisément ce que `reconcile_stale()` venait de corriger dans
# l'autre sens. Un blocage doit donc être explicite et re-négociable, pas un mur
# muet : sinon Wally réessaie indéfiniment sans jamais savoir pourquoi.


def _fixer_avec_garde(hit_status, hit_id=19, hit_proposal=DEMANDE_19_LIVREE):
    """SelfFix dont la garde trouve TOUJOURS une demande bloquante `hit_status`."""
    import types
    from unittest.mock import AsyncMock, MagicMock

    from bot.intelligence.self_fix import SelfFix
    from bot.intelligence.upgrade_registry import UpgradeRow

    bot = MagicMock()
    bot.config = types.SimpleNamespace(
        bot=types.SimpleNamespace(
            owner_discord_id="610550333042589752", name="Wally", creator_name="KingsRequin"
        )
    )
    bot.memory.fact_store.add = AsyncMock(return_value=1)

    registre = MagicMock()
    registre.find_similar = AsyncMock(
        return_value=UpgradeRow(
            id=hit_id, proposal=hit_proposal, status=hit_status,
            created_at="2026-08-05T03:09:51", decided_at="2026-08-05T03:21:12",
        )
    )
    return SelfFix(MagicMock(), bot, poll_interval=0.0, registry=registre), bot


async def _texte_memorise(bot) -> str:
    """Contenu du fait écrit dans la mémoire de Wally par la garde."""
    assert bot.memory.fact_store.add.await_count == 1, "la garde n'a rien mémorisé"
    return bot.memory.fact_store.add.await_args.args[0].content


@pytest.mark.asyncio
async def test_un_blocage_sur_capacite_livree_dit_qu_il_la_possede(tmp_path):
    """« delivered » doit devenir « tu l'as déjà », pas un statut anglais brut."""
    from bot.intelligence.self_fix import UpgradeRequest

    fixer, bot = _fixer_avec_garde(DELIVERED)
    await fixer.request_upgrade(UpgradeRequest(goal=DEMANDE_20_REDEMANDE))

    texte = await _texte_memorise(bot)
    assert "delivered" not in texte, f"statut anglais brut laissé tel quel : {texte}"
    assert "tu l'as déjà" in texte.lower()
    # Re-négociable : sans cette porte, un blocage devient un mur et il réessaie.
    assert "en quoi" in texte.lower(), (
        f"rien n'invite à dire en quoi sa demande différerait : {texte}"
    )


@pytest.mark.asyncio
async def test_un_blocage_sur_demande_en_cours_ne_dit_pas_qu_il_la_possede(tmp_path):
    """« requested » = en attente d'autorisation. Dire « tu l'as » serait faux."""
    from bot.intelligence.self_fix import UpgradeRequest
    from bot.intelligence.upgrade_registry import REQUESTED

    fixer, bot = _fixer_avec_garde(REQUESTED)
    await fixer.request_upgrade(UpgradeRequest(goal=DEMANDE_20_REDEMANDE))

    texte = await _texte_memorise(bot)
    assert "requested" not in texte, f"statut anglais brut laissé tel quel : {texte}"
    assert "tu l'as déjà" not in texte.lower(), (
        f"une demande en attente n'est pas une capacité acquise : {texte}"
    )
    assert "autorisation" in texte.lower()
