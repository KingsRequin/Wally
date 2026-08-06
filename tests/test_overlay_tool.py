"""L'outil conversationnel `show_overlay`.

Le geste existait déjà côté cognition (`[ACT show_overlay]`), mais ce chemin est
inaccessible en conversation : demander « affiche un pile ou face » à Wally lui
faisait répondre, honnêtement, qu'il n'avait pas la main sur l'overlay.

Le compte rendu rendu au LLM doit rester HONNÊTE : un refus explicite, sinon
Wally annonce « c'est affiché » alors que l'écran est vide.
"""
import json
from types import SimpleNamespace
from unittest.mock import MagicMock

from bot.discord.handlers import _overlay_narrator, run_overlay_tool


def _bot(shown=True, active=True, widget_result=None):
    narrator = MagicMock()
    # show_widget rend les paramètres publiés — c'est ce qui permet à Wally
    # d'annoncer le tirage plutôt que « c'est à l'écran ».
    narrator.show_widget.return_value = (
        (widget_result or {"widget": "coinflip", "result": "heads"}) if shown else None
    )
    narrator.is_active.return_value = active
    return SimpleNamespace(overlay_narrator=narrator), narrator


def test_le_widget_est_affiche():
    bot, narrator = _bot()
    out = json.loads(run_overlay_tool(bot, {"widget": "coinflip", "comment": "allez"}))
    assert out["status"] == "ok"
    narrator.show_widget.assert_called_once_with("coinflip", "allez", result=None)


def test_hors_live_le_refus_est_explicite():
    """Sans ça, Wally annonce un affichage qui n'a pas eu lieu."""
    bot, _ = _bot(shown=False, active=False)
    out = json.loads(run_overlay_tool(bot, {"widget": "dice"}))
    assert out["status"] == "offline"
    assert "pas de live" in out["message"]


def test_un_widget_incomplet_est_signale_comme_tel():
    bot, _ = _bot(shown=False, active=True)
    out = json.loads(run_overlay_tool(bot, {"widget": "wheel", "options": ["seule"]}))
    assert out["status"] == "rejected"


def test_les_parametres_du_sondage_sont_transmis():
    bot, narrator = _bot()
    run_overlay_tool(bot, {"widget": "poll", "question": "chocolat ?",
                           "options": ["Oui", "Non"], "seconds": 30})
    _, kwargs = narrator.show_widget.call_args
    assert kwargs["question"] == "chocolat ?"
    assert kwargs["seconds"] == 30


def test_un_widget_qui_leve_ne_casse_pas_la_reponse():
    bot, narrator = _bot()
    narrator.show_widget.side_effect = RuntimeError("boum")
    assert json.loads(run_overlay_tool(bot, {"widget": "dice"}))["status"] == "error"


def test_sans_narrateur_l_outil_le_dit():
    out = json.loads(run_overlay_tool(SimpleNamespace(), {"widget": "dice"}))
    assert out["status"] == "unavailable"


def test_le_narrateur_est_trouve_depuis_le_chemin_twitch():
    """Le bot Twitch n'a pas le narrateur : il y accède par référence croisée."""
    bot, narrator = _bot()
    twitch_bot = SimpleNamespace(discord_bot=bot)
    assert _overlay_narrator(twitch_bot) is narrator


# ── la réponse de Wally doit PORTER le résultat ──

def test_le_de_annonce_son_resultat():
    bot, _ = _bot(widget_result={"widget": "dice", "result": 4})
    out = json.loads(run_overlay_tool(bot, {"widget": "dice"}))
    assert "4" in out["message"]


def test_pile_ou_face_annonce_son_cote():
    bot, _ = _bot(widget_result={"widget": "coinflip", "result": "tails"})
    assert "FACE" in json.loads(run_overlay_tool(bot, {"widget": "coinflip"}))["message"]
    bot, _ = _bot(widget_result={"widget": "coinflip", "result": "heads"})
    assert "PILE" in json.loads(run_overlay_tool(bot, {"widget": "coinflip"}))["message"]


def test_la_roue_annonce_l_option_gagnante():
    bot, _ = _bot(widget_result={"widget": "wheel", "options": ["A", "B"], "index": 1})
    assert "B" in json.loads(run_overlay_tool(bot, {"widget": "wheel"}))["message"]


def test_le_sondage_interdit_d_inventer_le_resultat():
    """Le résultat n'existe qu'à la fin du décompte."""
    bot, _ = _bot(widget_result={"widget": "poll", "question": "?", "options": ["a", "b"]})
    msg = json.loads(run_overlay_tool(bot, {"widget": "poll"}))["message"]
    assert "invente" in msg


def test_plusieurs_des_sont_annonces_avec_leur_total():
    bot, _ = _bot(widget_result={"widget": "dice", "results": [3, 5], "result": 3})
    msg = json.loads(run_overlay_tool(bot, {"widget": "dice", "count": 2}))["message"]
    assert "3 et 5" in msg and "8" in msg
