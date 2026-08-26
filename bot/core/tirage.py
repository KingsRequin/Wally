"""Tirage sans remise — dire cent phrases avant d'en répéter une.

`random.choice` sur cent phrases en répète une toutes les dix tirages environ
(paradoxe des anniversaires), et deux fois de suite une fois sur cent. Dans un
chat, cette répétition-là se voit : c'est le moment où le viewer comprend qu'il
lit une liste. Le même piège est déjà consigné ailleurs dans ce projet — « pile
ou face n'épuise jamais un stock ».

Un sac épuise donc l'ensemble avant de le recharger.
"""
from __future__ import annotations

import random
from collections.abc import Callable


class SacSansRemise:
    """Tire dans un stock jusqu'à l'épuiser, puis recommence.

    Le stock est relu à CHAQUE rechargement, jamais capturé une fois pour
    toutes : les phrases viennent d'un fichier persona bind-monté qu'un
    `/reload-persona` peut changer sous les pieds du sac. Une liste capturée à
    la construction aurait servi l'ancienne version jusqu'au prochain
    redémarrage — exactement le genre de rechargement à chaud qui n'en est pas un.
    """

    def __init__(self, source: Callable[[], list[str]]) -> None:
        self._source = source
        self._restant: list[str] = []
        # La dernière servie, pour ne pas la resservir en tête du sac suivant.
        self._derniere: str | None = None

    def tirer(self) -> str | None:
        """Une entrée, ou None si le stock est vide.

        None n'est pas une erreur : un fichier de phrases vidé éteint la
        fonction qui s'en sert, et c'est une façon légitime de la couper.
        """
        if not self._restant:
            self._recharger()
        if not self._restant:
            return None
        choisie = self._restant.pop()
        self._derniere = choisie
        return choisie

    def _recharger(self) -> None:
        stock = list(self._source() or [])
        random.shuffle(stock)
        # Le sac se vide par la FIN (`pop()`), donc la prochaine servie est la
        # dernière du tableau : c'est elle qu'on écarte si elle répète la
        # précédente. Sans ça, un sac de cent phrases en répéterait quand même
        # une immédiatement une fois sur cent, à la jointure — le seul endroit
        # où le tirage sans remise ne protège de rien.
        if len(stock) > 1 and stock[-1] == self._derniere:
            stock[-1], stock[0] = stock[0], stock[-1]
        self._restant = stock
