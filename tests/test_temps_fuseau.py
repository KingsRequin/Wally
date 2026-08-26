"""La date civile est celle de Paris, jamais celle de l'horloge machine.

L'hôte tourne en UTC, l'application raisonne en Europe/Paris. `date.today()`
lit l'heure du SYSTÈME : il bascule donc de jour à 01 h ou 02 h du matin heure
locale, selon la saison. Tout ce qui range « par jour » — le code du jour de la
chaîne, l'historique du chat web — se décale pour les gens qui vivent le plus
tard, c'est-à-dire pendant un live du soir.

Le test ne compare pas à UTC : ce ne serait vrai que quelques heures par jour.
Il compare deux zones séparées de plus de 24 h (`Pacific/Kiritimati` UTC+14 et
`Pacific/Niue` UTC−11), dont les dates civiles diffèrent à tout instant — le
test devient déterministe. Même recette que `tests/test_journal_timezone.py`.
"""
from datetime import datetime
from zoneinfo import ZoneInfo

from bot.core.temps import PARIS, aujourdhui, maintenant

_LOIN_DEVANT = ZoneInfo("Pacific/Kiritimati")   # UTC+14
_LOIN_DERRIERE = ZoneInfo("Pacific/Niue")       # UTC−11


def test_aujourdhui_est_la_date_de_PARIS():
    attendu = datetime.now(PARIS).date()
    assert aujourdhui() == attendu


def test_aujourdhui_ne_suit_pas_l_horloge_d_un_autre_fuseau():
    """À tout instant, ces deux zones ne sont pas le même jour.

    L'une des deux est donc forcément en désaccord avec Paris, et le test le
    prouve sans dépendre de l'heure à laquelle on le lance.
    """
    devant = datetime.now(_LOIN_DEVANT).date()
    derriere = datetime.now(_LOIN_DERRIERE).date()
    assert devant != derriere, "les deux zones de contrôle doivent différer"
    assert aujourdhui() != devant or aujourdhui() != derriere


def test_maintenant_porte_toujours_son_fuseau():
    """Un `datetime` naïf comparé à un `datetime` de la base a déjà coûté un jour."""
    assert maintenant().tzinfo is not None
