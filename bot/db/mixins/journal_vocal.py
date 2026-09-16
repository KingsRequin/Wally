"""Le registre des cartes du journal vocal (`bot/discord/journal_vocal.py`).

Une carte est publiée par salon de logs à la CRÉATION d'un salon vocal
temporaire ; ce registre range le triplet (salon temporaire, salon de logs,
message) pour que la carte soit ÉDITÉE — et non republiée — à la suppression.
Ids en TEXT : un snowflake ne survit pas à un REAL. `participants` est une
liste d'ids JSON, alimentée à chaque entrée dans le salon.

`participants` est plafonné à `_MAX_PARTICIPANTS_STOCKES` (500) : au-delà, un
nouvel arrivant n'est plus ajouté à la colonne — les premiers sont gardés, la
ligne ne grossit pas indéfiniment. La carte elle-même n'en affiche de toute
façon qu'une fraction (budget Components V2, cf. `journal_vocal._bloc_participants`).
"""
from __future__ import annotations

import json
import time

import aiosqlite

_MAX_PARTICIPANTS_STOCKES = 500


class JournalVocalMixin:
    _conn: aiosqlite.Connection

    # Déclarés pour le type-check (implémentés dans Database). `raise` plutôt
    # que `...` : mypy exige un `return` explicite sur un corps vide dès que
    # le type de retour n'est pas `None` (cf. `scripts/lint_types.py`).
    async def fetch_all(self, query: str, params=()) -> list:
        raise NotImplementedError

    async def execute(self, query: str, params=()) -> None:
        raise NotImplementedError

    async def carte_vocale_ajouter(self, salon_temp_id: int, log_salon_id: int, message_id: int,
                                    createur_id: int, participants: list[int], salon_nom: str) -> None:
        """Range la carte publiée dans `log_salon_id` pour le salon temporaire.

        Un couple (salon_temp_id, log_salon_id) par salon de logs : autant de
        lignes que de cartes envoyées à la création. `salon_nom` est rangé
        pour que la carte orpheline (`journal_vocal.nettoyer_cartes_orphelines`)
        puisse encore nommer le salon une fois le salon Discord disparu.
        """
        await self.execute(
            "INSERT OR REPLACE INTO journal_cartes_vocales "
            "(salon_temp_id, log_salon_id, message_id, createur_id, cree_a, participants, salon_nom) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (str(salon_temp_id), str(log_salon_id), str(message_id), str(createur_id), time.time(),
             json.dumps([str(p) for p in participants][:_MAX_PARTICIPANTS_STOCKES]), salon_nom),
        )

    async def carte_vocale_participant_ajouter(self, salon_temp_id: int, user_id: int) -> None:
        """Ajoute `user_id` aux participants de CHAQUE carte de ce salon temporaire.

        Sans ligne pour ce salon (journal désactivé au moment de la création,
        ou salon non temporaire), ne fait rien : il n'y a aucune carte où
        ranger ce participant. Au-delà de `_MAX_PARTICIPANTS_STOCKES`, le
        nouvel arrivant n'est plus ajouté : la ligne ne grossit pas pour
        toujours sur un salon qui reste ouvert des jours.
        """
        lignes = await self.fetch_all(
            "SELECT log_salon_id, participants FROM journal_cartes_vocales WHERE salon_temp_id = ?",
            (str(salon_temp_id),),
        )
        for ligne in lignes:
            participants: list[str] = json.loads(ligne["participants"])
            if str(user_id) in participants or len(participants) >= _MAX_PARTICIPANTS_STOCKES:
                continue
            participants.append(str(user_id))
            await self.execute(
                "UPDATE journal_cartes_vocales SET participants = ? "
                "WHERE salon_temp_id = ? AND log_salon_id = ?",
                (json.dumps(participants), str(salon_temp_id), ligne["log_salon_id"]),
            )

    async def cartes_vocales(self, salon_temp_id: int) -> list[dict]:
        """Les cartes rangées pour ce salon temporaire, une par salon de logs.

        `salon_nom` vaut `""` sur une ligne migrée avant son ajout — aucun nom
        n'a jamais été écrit pour elle, l'appelant (`journal_vocal._vue_orpheline`)
        retombe alors sur « Salon {id} ».
        """
        lignes = await self.fetch_all(
            "SELECT log_salon_id, message_id, createur_id, cree_a, participants, salon_nom "
            "FROM journal_cartes_vocales WHERE salon_temp_id = ?",
            (str(salon_temp_id),),
        )
        return [
            {
                "log_salon_id": int(ligne["log_salon_id"]),
                "message_id": int(ligne["message_id"]),
                "createur_id": int(ligne["createur_id"]),
                "cree_a": float(ligne["cree_a"]),
                "participants": [int(p) for p in json.loads(ligne["participants"])],
                "salon_nom": ligne["salon_nom"],
            }
            for ligne in lignes
        ]

    async def cartes_vocales_supprimer(self, salon_temp_id: int) -> None:
        await self.execute(
            "DELETE FROM journal_cartes_vocales WHERE salon_temp_id = ?",
            (str(salon_temp_id),),
        )

    async def salons_temp_avec_carte(self) -> set[int]:
        """Les salons temporaires distincts qui ont encore au moins une carte.

        Sert au ménage des cartes orphelines au boot (`salons_temporaires.
        menage_au_boot`) : comparé au registre des salons temporaires encore
        valides pour trouver celles dont le salon a disparu sans que
        `vocal_supprime` ait pu les éditer (bot arrêté entre-temps).
        """
        rows = await self.fetch_all("SELECT DISTINCT salon_temp_id FROM journal_cartes_vocales")
        return {int(r["salon_temp_id"]) for r in rows}
