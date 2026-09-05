"""Les rappels que Wally publie de lui-même pendant le live.

Repris de PhantomBot, qui postait six messages en rotation toutes les 30
minutes : TikTok, YouTube, Discord, memes, « on dit bonjour », code créateur.
C'était la dernière chose que l'ancien bot faisait encore et que Wally ne
faisait pas — et la seule qui reste utile telle quelle, parce qu'un lien ne se
demande pas, il se rappelle.

Trois écarts avec l'original, chacun payé par un défaut observé :

  · **Le texte n'est pas figé.** Les six phrases sortaient au mot près, douze
    fois par live, depuis des mois. Ici chaque sujet a ses variantes dans
    `bot/persona/ANNONCES.md` — fichier bind-monté, rechargé par
    `/reload-persona`, éditable depuis le dashboard.

  · **Rien n'est généré par un LLM.** Un modèle qui réécrit une URL l'abîme une
    fois sur combien ? Personne ne le saurait : un lien mort ne renvoie aucune
    erreur, il ne mène nulle part. Les phrases sont ÉCRITES, on n'en tire
    qu'une.

  · **Un chat désert saute son tour.** PhantomBot postait dans le vide, sur un
    live à deux viewers silencieux comme sur un live plein.

La sortie passe par `send_automatic` : annonce colorée si le scope et le badge
de modérateur sont là, message ordinaire sinon. Un rappel qui ne part pas parce
que le canal des annonces se refuse serait la pire des deux options.
"""
from __future__ import annotations

import asyncio
import time
from functools import partial

from loguru import logger

from bot.core.self_trace import note_act
from bot.core.tirage import SacSansRemise

# Le tour de garde : on se réveille souvent, on ne publie que quand l'heure est
# venue. Une boucle qui dormirait la cadence entière raterait le début du live
# de la moitié de cette cadence, et ne verrait pas non plus qu'il s'est arrêté.
PAS_S = 60.0


class AnnoncesAuto:
    """Publie un rappel toutes les `cadence_s`, pendant le live et seulement là.

    Une instance, câblée dans `main.py` sur le bot Twitch. Le sac des sujets et
    les sacs de variantes relisent la persona à chaque rechargement : éditer
    `ANNONCES.md` depuis le dashboard prend effet au rappel suivant, sans
    redémarrage.
    """

    def __init__(
        self,
        bot,
        *,
        cadence_s: float,
        pas_s: float = PAS_S,
    ) -> None:
        self._bot = bot
        self._cadence_s = cadence_s
        self._pas_s = pas_s
        # L'horloge démarre MAINTENANT et non à zéro : relancé en plein live,
        # le bot attend une cadence complète avant son premier rappel. Un
        # rebuild ne doit pas se payer d'une annonce dans la minute.
        self._dernier: float = time.monotonic()
        self._sujets = SacSansRemise(lambda: list(self._annonces().keys()))
        # Un sac PAR sujet : `random.choice` resservirait la même variante de
        # TikTok deux passages de suite une fois sur six, et c'est justement la
        # répétition qu'on est venu corriger.
        self._variantes: dict[str, SacSansRemise] = {}

    def _annonces(self) -> dict[str, list[str]]:
        persona = getattr(self._bot, "persona", None)
        if persona is None:
            return {}
        return dict(getattr(persona, "annonces_auto", {}) or {})

    def _variantes_de(self, sujet: str) -> list[str]:
        """Les phrases d'un sujet, relues à chaque rechargement du sac.

        Une méthode et non un `lambda s=sujet:` — l'argument par défaut est le
        seul moyen de capturer la valeur dans une lambda, et mypy ne sait pas
        en inférer le type.
        """
        return list(self._annonces().get(sujet, []))

    def _en_live(self) -> bool:
        return bool((getattr(self._bot, "_stream_info", None) or {}).get("live"))

    def _chat_vivant(self) -> bool:
        """Le chat a-t-il donné signe de vie depuis le dernier rappel ?

        Sans flux de stream, on répond OUI : le flux est une perception de
        confort, pas une autorisation. Le laisser décider par son absence
        éteindrait la fonction en silence, ce qui est précisément le défaut que
        les garde-fous du projet visent.
        """
        feed = getattr(self._bot, "stream_feed", None)
        if feed is None:
            return True
        return feed.a_du_chat_frais(self._cadence_s)

    def choisir(self) -> tuple[str, str] | None:
        """Le prochain rappel, `(sujet, phrase)`, ou None si le fichier est vide."""
        annonces = self._annonces()
        if not annonces:
            return None
        sujet = self._sujets.tirer()
        # Un sujet retiré d'`ANNONCES.md` entre deux tirages reste dans le sac
        # en cours : on saute ce tour plutôt que de servir une phrase que
        # l'owner vient d'effacer.
        if sujet is None or sujet not in annonces:
            return None
        sac = self._variantes.get(sujet)
        if sac is None:
            sac = SacSansRemise(partial(self._variantes_de, sujet))
            self._variantes[sujet] = sac
        phrase = sac.tirer()
        return (sujet, phrase) if phrase else None

    async def publier(self) -> bool:
        """Tire et publie un rappel. Rend True s'il est parti."""
        choix = self.choisir()
        if choix is None:
            logger.debug("Rappels du live : rien à publier (ANNONCES.md vide ?)")
            return False
        sujet, phrase = choix
        api = getattr(self._bot, "twitch_api", None)
        if api is None:
            logger.warning("Rappels du live : pas d'API Twitch, « {s} » non publié", s=sujet)
            return False
        try:
            if not await api.send_automatic(phrase):
                logger.warning("Rappel « {s} » non publié du tout", s=sujet)
                return False
        except Exception as exc:  # noqa: BLE001 — un rappel ne casse pas le live
            logger.error("Rappel « {s} » non publié : {e!r}", s=sujet, e=exc)
            return False
        logger.info("Rappel du live publié ({s}) : {p}", s=sujet, p=phrase[:80])
        # Wally doit savoir ce qu'il vient de faire : sans ça, il dément avoir
        # posté le lien qu'un viewer a sous les yeux.
        note_act(f"tu as publié un rappel dans le chat du live : « {phrase[:120]} »")
        return True

    async def run(self) -> None:
        """La boucle. Ne rend jamais la main, ne lève jamais."""
        logger.info("Rappels du live actifs (toutes les {m} min)",
                    m=int(self._cadence_s // 60))
        while True:
            try:
                await asyncio.sleep(self._pas_s)
                await self.tour()
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001 — la boucle survit à tout
                logger.error("Rappels du live : tour en échec : {e!r}", e=exc)

    async def tour(self) -> None:
        """Un tour de garde : publie si l'heure est venue et le live vivant."""
        maintenant = time.monotonic()
        if not self._en_live():
            # Hors live, l'horloge repart de maintenant : sans ça, un rappel
            # tomberait dans la seconde qui suit le lancement du stream, avant
            # même que quiconque soit arrivé.
            self._dernier = maintenant
            return
        if maintenant - self._dernier < self._cadence_s:
            return
        if not self._chat_vivant():
            # Le tour est sauté, PAS reporté : l'horloge avance quand même,
            # sinon le premier mot prononcé après une heure de silence
            # déclencherait un rappel dans la seconde.
            self._dernier = maintenant
            logger.info("Rappel du live sauté : chat désert depuis {m} min",
                        m=int(self._cadence_s // 60))
            return
        self._dernier = maintenant
        await self.publier()
