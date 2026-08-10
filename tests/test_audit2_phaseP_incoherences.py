# tests/test_audit2_phaseP_incoherences.py
"""Phase P du second audit : silences, incohérences et code mort.

A2-setup — `/setup > Événements Twitch` ne répondait JAMAIS si la clé avait
           disparu entre l'affichage de la vue et le clic.
A2-decay — l'onglet Decay affichait `decay_lambda` pour l'ennui, alors que le
           formulaire édite la vitesse de montée : deux nombres contradictoires.
A2-rss   — le refus de recherche renvoyait le modèle vers une section du prompt
           qui n'existe pas.
A2-mort  — libellé d'annulation inatteignable, et trois fonctions JS appelant
           un `loadInvites()` qui n'existe nulle part.
"""
import inspect
from pathlib import Path


# ────────────────────────────── A2-setup ──────────────────────────────
def test_les_deux_handlers_d_evenements_repondent_toujours():
    from bot.discord.commands.setup import basic

    src = inspect.getsource(basic)
    # Une interaction non répondue affiche « L'interaction a échoué » côté
    # Discord, sans une trace côté bot.
    assert src.count("introuvable dans la config.") == 2


# ────────────────────────────── A2-decay ──────────────────────────────
def test_l_onglet_decay_affiche_la_valeur_reellement_editee():
    from bot.discord.commands.setup import advanced

    src = inspect.getsource(advanced)
    assert 'f"**boredom** : montée/heure = {cfg.boredom_rise_per_hour}"' in src


def test_le_formulaire_et_l_affichage_parlent_du_meme_champ():
    from bot.discord.commands.setup.advanced import DecayModal

    # Le libellé du champ et la ligne affichée doivent désigner la même chose.
    assert "montée par heure" in DecayModal.boredom.label
    src = inspect.getsource(DecayModal.on_submit)
    assert 'emotions["boredom"].boredom_rise_per_hour = value' in src


# ────────────────────────────── A2-rss ──────────────────────────────
def test_le_refus_de_recherche_cite_la_section_reellement_injectee():
    from bot.discord import handlers

    src = inspect.getsource(handlers)
    # L'en-tête réel du bloc RSS…
    assert "Actus que tu CONNAIS DÉJÀ sur ce sujet" in src
    # …et plus aucune référence à une section qui n'existe pas.
    assert "« Actus récentes »" not in src


# ────────────────────────────── A2-mort ──────────────────────────────
def test_le_libelle_dannulation_du_chifoumi_est_retire():
    from bot.discord.handlers import _CANCEL_LABELS
    from bot.intelligence.overlay_narrator import CANCEL_TARGETS

    assert "chifoumi" not in _CANCEL_LABELS
    # Tout libellé restant doit correspondre à une cible réellement acceptée.
    assert set(_CANCEL_LABELS) <= set(CANCEL_TARGETS)


def test_les_fonctions_d_invitation_mortes_sont_retirees():
    src = Path("bot/dashboard/static/app.js").read_text(encoding="utf-8")
    assert "async function generateInvite()" not in src
    assert "async function revokeInvite(" not in src
    assert "async function copyInviteLink(" not in src
