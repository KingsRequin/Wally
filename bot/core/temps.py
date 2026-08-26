"""Le fuseau de l'application, à un seul endroit.

L'hôte (CT100) tourne en **UTC** ; le conteneur pose `TZ=Europe/Paris` et
l'application raisonne en `Europe/Paris`. Les deux ne se recouvrent jamais
qu'une heure ou deux par jour, ce qui rend le défaut saisonnier et rare — donc
long à voir.

`ZoneInfo("Europe/Paris")` était redéclaré **dix-sept fois**, sous six noms
différents (`_TZ`, `_PARIS`, `TZ`, `_TZ_DB`, `_TZ_COSTS`, `_TZ_JOURNAL`). Rien
n'oblige un nouveau module à le faire, et c'est exactement ce qui s'est passé :
`date.today()` et `datetime.utcnow()` traînaient encore à plusieurs endroits,
chacun basculant de jour une à deux heures trop tôt selon la saison.

Un seul nom, importé, ne garantit pas qu'on l'utilise — mais il enlève la
question « quel fuseau, déjà ? » à celui qui écrit la ligne suivante.
"""
from __future__ import annotations

from datetime import date, datetime
from zoneinfo import ZoneInfo

#: Le fuseau dans lequel l'application raisonne. Jamais UTC, jamais l'heure
#: machine — les deux mentent ici, et pas au même moment.
PARIS = ZoneInfo("Europe/Paris")


def maintenant() -> datetime:
    """L'instant présent, avec son fuseau.

    Toujours conscient du fuseau : comparer un `datetime` naïf issu de la base
    à un `datetime.now()` naïf a déjà coûté un décalage d'une journée entière.
    """
    return datetime.now(PARIS)


def aujourdhui() -> date:
    """La date civile ICI — pas celle de l'horloge machine.

    `date.today()` lit l'heure du système : sur un hôte en UTC, il bascule à
    01 h ou 02 h du matin heure locale. Tout ce qui range « par jour » (le code
    du jour, l'historique du chat web, les coûts) s'en trouve décalé pour les
    gens qui vivent le plus tard — c'est-à-dire pendant un live du soir.
    """
    return maintenant().date()
