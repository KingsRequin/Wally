"""L'historique des demandes d'amélioration doit être LISIBLE, et complet.

Vécu le 2026-08-09 : Wally a redemandé une capacité livrée quatre jours plus tôt.
Sa pensée de 07:47 dit « J'ai la liste des demandes déjà faites » puis « la demande
originale "voir le stream en direct" a été refusée » — il avait la liste sous les
yeux et en a tiré la conclusion inverse.

Deux défauts de rendu expliquent ça :

· une **liste plate** mélangeait les statuts, or #18 (refusée) et #19 (livrée) sont
  deux formulations quasi identiques du même sujet, tronquées et voisines ;
· une **fenêtre de 6** demandes, alors qu'il en a 20 dont 14 livrées : 8 capacités
  acquises étaient tout simplement absentes de son prompt.
"""
import pytest

from bot.intelligence.attention_agent import AttentionContext
from bot.intelligence.reasoning_agent import ReasoningAgent
from bot.intelligence.upgrade_registry import (
    ABANDONED,
    DECLINED,
    DELIVERED,
    REQUESTED,
    UpgradeRegistry,
    UpgradeRow,
)
from tests.intelligence.test_phase6_upgrade_awareness import _PROMPTS


def _ctx(**over):
    base = {
        "emotion_state": {"joy": 0.1},
        "active_desires": [], "active_goals": [], "recent_thoughts": [],
        "recent_interactions": [], "time_of_day": "morning",
    }
    base.update(over)
    return AttentionContext(**base)


def _rendu(*rows) -> str:
    agent = ReasoningAgent(llm=None, fact_store=None, prompts_dir=_PROMPTS)
    return agent._format_context(_ctx(upgrade_requests=list(rows)))


def _row(uid, proposal, status):
    return UpgradeRow(id=uid, proposal=proposal, status=status,
                      created_at="2026-08-05T03:09", decided_at="2026-08-05T03:21")


def _section(rendu: str, intitule: str) -> str:
    """Le texte qui suit `intitule`, jusqu'au prochain intitulé en gras."""
    debut = rendu.index(intitule) + len(intitule)
    suite = rendu[debut:]
    fin = suite.find("\n**")
    return suite if fin == -1 else suite[:fin]


# Les deux demandes réelles que Wally a confondues : même sujet, statuts opposés.
LIVREE_19 = "Recevoir dans mon contexte les événements du stream Twitch d'Azraël (chat, moments marquants)"
REFUSEE_18 = "Pouvoir voir en direct ce qui se passe sur le stream Twitch d'Azraël — le gameplay, le chat"


def test_une_capacite_obtenue_nest_pas_listee_avec_les_refus():
    """Le cas exact du 2026-08-09 : deux textes voisins, statuts opposés."""
    rendu = _rendu(_row(19, LIVREE_19, DELIVERED), _row(18, REFUSEE_18, DECLINED))

    obtenu = _section(rendu, "OBTENU")
    assert "événements du stream" in obtenu
    assert "gameplay" not in obtenu, (
        "la demande REFUSÉE est listée dans la section des capacités obtenues — "
        f"c'est la confusion du 2026-08-09.\n{rendu}"
    )

    refuse = _section(rendu, "REFUSÉ")
    assert "gameplay" in refuse


def test_les_quatre_statuts_sont_rendus_dans_leur_propre_section():
    rendu = _rendu(
        _row(1, "capacité acquise", DELIVERED),
        _row(2, "capacité refusée", DECLINED),
        _row(3, "capacité en attente", REQUESTED),
        _row(4, "capacité abandonnée", ABANDONED),
    )
    assert "capacité acquise" in _section(rendu, "OBTENU")
    assert "capacité refusée" in _section(rendu, "REFUSÉ")
    assert "capacité en attente" in _section(rendu, "attente")
    # Abandonnée = re-proposable : la masquer lui ferait perdre le souvenir d'avoir
    # essayé, alors que rien ne l'empêche de recommencer.
    assert "capacité abandonnée" in rendu


def test_aucun_bloc_quand_il_na_jamais_rien_demande():
    agent = ReasoningAgent(llm=None, fact_store=None, prompts_dir=_PROMPTS)
    out = agent._format_context(_ctx(upgrade_requests=[]))
    assert "OBTENU" not in out


@pytest.mark.asyncio
async def test_lhistorique_complet_est_rendu_sans_fenetre(tmp_path):
    """14 capacités livrées pour une fenêtre de 6 : 8 étaient invisibles."""
    from bot.db.schema_v2 import create_v2_tables

    chemin = str(tmp_path / "u.db")
    await create_v2_tables(chemin)
    reg = UpgradeRegistry(chemin)
    for i in range(14):
        uid = await reg.record_request(f"capacité numéro {i}")
        await reg.set_status(uid, DELIVERED)

    rows = await reg.recent()

    assert len(rows) == 14, f"seules {len(rows)} demandes sur 14 remontent au prompt"
