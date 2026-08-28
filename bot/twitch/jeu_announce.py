"""Les fins de partie s'annoncent dans le chat, sur fond coloré.

Un sondage se dépouillait à l'ÉCRAN et mourait là : rien ne partait dans le
chat, et Wally n'en parlait que si quelqu'un pensait à demander « ça a donné
quoi ? ». Le pendu pareil. Le moment le plus collectif du jeu — celui où on
apprend qui avait raison — n'atteignait personne d'autre que ceux qui
regardaient l'overlay à la bonne seconde.

L'ANNONCE plutôt que le message ordinaire (`POST /helix/chat/announcements`) :
fond coloré, bordure, l'œil s'y arrête. C'est ce qui sépare deux registres qui
sortaient jusqu'ici avec exactement le même poids visuel — « lol » et « le mot
était GIBRALTAR, personne ne l'a eu ».

Deux règles reprises telles quelles de l'annonceur du duel :

  · **le fait part toujours.** Un appel LLM raté ne doit pas avaler le
    résultat : sans habillage, c'est le texte FACTUEL qui est publié nu.
  · **le résultat n'est jamais laissé au modèle.** Il est calculé par le
    narrateur et écrit en toutes lettres ; le modèle ne fait que l'habiller.

Une troisième s'y ajoute, propre à ce canal : **un canal indisponible n'est pas
une raison de se taire.** Le scope peut manquer, ou le compte bot ne pas être
modérateur — le résultat retombe alors sur un message ordinaire.
"""
from __future__ import annotations

from loguru import logger

from bot.core.llm import FALLBACK_RESPONSE

# Plafond d'une annonce Twitch (500 caractères), même valeur que le message.
MAX_ANNONCE = 500

_SOCLE = (
    "Une partie vient de se terminer sur le live. On te donne le RÉSULTAT : tu "
    "l'habilles d'une phrase, tu ne le changes pas, tu n'inventes ni chiffre ni "
    "nom. UNE phrase courte, adressée aux SPECTATEURS du live — jamais au "
    "streamer, il ne te lit pas pendant qu'il joue. Réponds uniquement par la "
    "phrase, sans guillemets."
)


class JeuAnnouncer:
    """Publie la fin d'une partie. Une instance, câblée sur le narrateur."""

    def __init__(self, bot, channel: str = "") -> None:
        self._bot = bot
        self._channel = channel

    async def annoncer(self, genre: str, fait: str) -> None:
        """`genre` sert au journal et au ton ; `fait` est le résultat, intouchable."""
        fait = (fait or "").strip()
        if not fait:
            # Un pendu sans mot, un sondage sans vote : rien à dire, et une
            # annonce vide serait pire que le silence.
            return
        ligne = (await self._rediger(fait) or fait)[:MAX_ANNONCE]
        await self._publier(ligne, genre)

    async def _rediger(self, fait: str) -> str:
        """La phrase de Wally, ou `""` s'il n'a rien pu produire."""
        try:
            from bot.twitch.handlers import _build_situation

            system = self._bot.prompts.build_system_prompt(
                emotion_state=self._bot.emotion.get_state(),
                situation=_build_situation(self._bot, self._channel),
                persona_block=self._bot.persona.build_prompt_block(),
                emotion_directives=self._bot.persona.emotion_directives,
                weekday_directives=self._bot.persona.weekday_directives,
                composite_directives=self._bot.persona.composite_directives,
            )
            reponse = await self._bot.llm.complete(
                f"{system}\n\n{_SOCLE}",
                [{"role": "user", "content": fait}],
                purpose="jeu_fin",
            )
        except Exception as exc:  # noqa: BLE001 — sans habillage, le fait part nu
            logger.warning("Fin de partie : annonce non rédigée : {e!r}", e=exc)
            return ""
        reponse = (reponse or "").strip()
        if not reponse or reponse == FALLBACK_RESPONSE.strip():
            logger.warning("Fin de partie : rédaction indisponible, fait publié nu")
            return ""
        return reponse

    async def _publier(self, texte: str, genre: str) -> None:
        api = getattr(self._bot, "twitch_api", None)
        if api is None:
            logger.warning("Fin de partie ({g}) : pas d'API Twitch, rien publié", g=genre)
            return
        try:
            # Le repli — scope absent, bot non modérateur, AutoMod — vit dans
            # `send_automatic`, avec les huit autres chemins qui publient sans
            # qu'on ait parlé à Wally. Il était écrit ici en premier ; le garder
            # en double aurait fait deux réponses à la même question.
            if not await api.send_automatic(texte):
                logger.warning("Fin de partie ({g}) non publiée du tout", g=genre)
                return
            logger.info("Fin de partie ({g}) annoncée : {t}", g=genre, t=texte[:80])
        except Exception as exc:  # noqa: BLE001 — une fin de partie n'est pas critique
            logger.error("Fin de partie ({g}) non publiée : {e!r}", g=genre, e=exc)
