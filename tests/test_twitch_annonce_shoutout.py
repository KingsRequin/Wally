"""Annonce colorée et shoutout natif — les deux gestes Helix qui ne sont pas
un message de chat ordinaire.

Les deux répondent **204 sans corps** : contrairement à `POST /helix/chat/
messages`, il n'y a rien à relire pour savoir si c'est passé (cf. « Helix :
200 ≠ publié »). Lire le JSON d'un 204 lèverait — c'est le piège que ces tests
tiennent fermé.
"""
import json
import httpx
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from bot.core.secret_guard import clear_secrets, guard_secret
from bot.twitch.api import TwitchAPI


def make_api(bot_token="bot_tok") -> TwitchAPI:
    tm = MagicMock()
    tm.bot_token = bot_token
    tm.refresh = AsyncMock(return_value=True)
    return TwitchAPI(token_manager=tm, client_id="cid",
                     bot_id="bot_id", broadcaster_id="bc_id")


def make_204():
    """Un 204 réel : pas de corps, et `.json()` lève si on ose le lire."""
    resp = MagicMock()
    resp.status_code = 204
    resp.json = MagicMock(side_effect=ValueError("204 n'a pas de corps"))
    resp.raise_for_status = MagicMock()
    return resp


def make_erreur(status: int):
    resp = MagicMock()
    resp.status_code = status
    resp.json = MagicMock(return_value={"message": "nope"})
    resp.headers = {}
    resp.raise_for_status = MagicMock(side_effect=httpx.HTTPStatusError(
        f"HTTP {status}", request=MagicMock(), response=MagicMock()))
    return resp


def _post(resp):
    """Monte un client HTTP dont le POST rend `resp`. Rend le mock du POST."""
    client = patch("bot.twitch.api.httpx.AsyncClient")
    mock = client.start()
    http = mock.return_value.__aenter__.return_value
    http.post = AsyncMock(return_value=resp)
    return http, client


# ── annonce ───────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_l_annonce_part_avec_les_deux_ids_et_la_couleur():
    """`moderator_id` est le compte BOT, `broadcaster_id` la chaîne visée.

    Les deux sont des paramètres d'URL, pas du corps : les poser dans le JSON
    donne un 400 « missing broadcaster_id » alors que la valeur est bien là.
    """
    api = make_api()
    http, ctx = _post(make_204())
    try:
        assert await api.send_announcement("le sondage est plié", color="purple")
    finally:
        ctx.stop()
    kwargs = http.post.call_args.kwargs
    assert kwargs["params"] == {"broadcaster_id": "bc_id", "moderator_id": "bot_id"}
    assert kwargs["json"] == {"message": "le sondage est plié", "color": "purple"}


@pytest.mark.asyncio
async def test_une_couleur_inconnue_retombe_sur_l_accent_de_la_chaine():
    """Twitch n'accepte QUE blue, green, orange, purple — et en minuscules.

    La fiche de départ annonçait « RED » et des majuscules : ni l'un ni l'autre
    n'existe. Une valeur refusée fait un 400, donc pas d'annonce du tout.
    """
    api = make_api()
    http, ctx = _post(make_204())
    try:
        await api.send_announcement("bravo", color="RED")
    finally:
        ctx.stop()
    assert http.post.call_args.kwargs["json"]["color"] == "primary"


@pytest.mark.asyncio
async def test_l_annonce_est_bornee_a_500_caracteres():
    api = make_api()
    http, ctx = _post(make_204())
    try:
        await api.send_announcement("x" * 900)
    finally:
        ctx.stop()
    assert len(http.post.call_args.kwargs["json"]["message"]) == 500


@pytest.mark.asyncio
async def test_le_mot_du_pendu_ne_passe_pas_par_l_annonce():
    """Le filet de `send_message` doit couvrir CE chemin aussi.

    Une annonce est plus visible qu'un message : c'est la pire des sorties pour
    laisser filer le mot d'une partie en cours.
    """
    clear_secrets()
    guard_secret("gibraltar")
    api = make_api()
    http, ctx = _post(make_204())
    try:
        await api.send_announcement("le mot était gibraltar")
    finally:
        ctx.stop()
        clear_secrets()
    assert "gibraltar" not in http.post.call_args.kwargs["json"]["message"]


@pytest.mark.asyncio
async def test_un_401_rafraichit_le_token_et_reessaie_une_fois():
    api = make_api()
    http, ctx = _post(make_erreur(401))
    try:
        assert await api.send_announcement("coucou") is False
    finally:
        ctx.stop()
    assert http.post.await_count == 2       # l'essai, puis celui d'après refresh


# ── shoutout ──────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_le_shoutout_part_avec_les_trois_ids():
    api = make_api()
    http, ctx = _post(make_204())
    try:
        assert await api.send_shoutout("42") == ""
    finally:
        ctx.stop()
    assert http.post.call_args.kwargs["params"] == {
        "from_broadcaster_id": "bc_id", "to_broadcaster_id": "42",
        "moderator_id": "bot_id",
    }


@pytest.mark.asyncio
async def test_le_cooldown_natif_rend_un_motif_lisible_pas_une_panne():
    """429 = « c'est trop tôt », pas « c'est cassé ».

    Twitch impose 2 min entre deux shoutouts et 60 min sur la même chaîne. Ce
    refus est une INFORMATION à rendre au chat, et surtout pas un nouvel essai :
    réémettre dans la seconde ne peut que rater à nouveau.
    """
    api = make_api()
    http, ctx = _post(make_erreur(429))
    try:
        motif = await api.send_shoutout("42")
    finally:
        ctx.stop()
    assert http.post.await_count == 1
    assert motif and "2 minutes" in motif


# ── scopes : une seule source, deux portes d'entrée ────────────────────────

@pytest.mark.asyncio
async def test_le_wizard_demande_exactement_les_memes_scopes_que_le_dashboard():
    """Les deux chemins d'autorisation doivent émettre le MÊME token.

    Un token fraîchement émis remplace l'ancien avec exactement ce qu'on lui
    demande : une liste amputée fait perdre des capacités sans un mot dans les
    logs. La copie manuelle du wizard avait déjà décroché de quinze jours —
    il lui manquait `user:read:emotes`.
    """
    import urllib.parse
    from unittest.mock import patch as _patch

    from bot.dashboard.routes.setup import twitch_auth_url
    from bot.dashboard.routes.twitch_auth import _BOT_SCOPES

    requete = MagicMock()
    requete.app.state.wally.db.save_setup_session = AsyncMock()
    with _patch("bot.dashboard.routes.setup._check_preview_auth"), \
         _patch("bot.dashboard.routes.setup._get_valid_invite", AsyncMock()):
        rendu = await twitch_auth_url(
            requete, "jeton", {"account_type": "bot", "client_id": "cid"},
        )
    demandes = urllib.parse.parse_qs(
        urllib.parse.urlparse(rendu["url"]).query)["scope"][0]
    assert demandes == _BOT_SCOPES
    assert "moderator:manage:announcements" in demandes
    assert "moderator:manage:shoutouts" in demandes


# ── l'outil offert au LLM ──────────────────────────────────────────────────

def _bot_avec_api(api):
    bot = MagicMock()
    bot.twitch_api = api
    return bot


@pytest.mark.asyncio
async def test_l_outil_resout_le_pseudo_puis_shoutoute():
    """Le modèle donne un pseudo ; Helix veut un identifiant numérique."""
    from bot.core.shoutout_tool import run_shoutout_tool

    api = MagicMock()
    api.get_broadcaster_id = AsyncMock(return_value="777")
    api.send_shoutout = AsyncMock(return_value="")
    rendu = await run_shoutout_tool(_bot_avec_api(api), {"user": "@Kassandre"})

    api.get_broadcaster_id.assert_awaited_once_with("kassandre")
    api.send_shoutout.assert_awaited_once_with("777")
    assert '"status": "ok"' in rendu


@pytest.mark.asyncio
async def test_un_pseudo_inconnu_ne_part_pas_vers_helix():
    from bot.core.shoutout_tool import run_shoutout_tool

    api = MagicMock()
    api.get_broadcaster_id = AsyncMock(return_value=None)
    api.send_shoutout = AsyncMock()
    rendu = await run_shoutout_tool(_bot_avec_api(api), {"user": "fantome"})

    api.send_shoutout.assert_not_awaited()
    assert "fantome" in rendu


@pytest.mark.asyncio
async def test_le_refus_de_twitch_est_rendu_tel_quel_au_modele():
    """Le cooldown doit ARRIVER jusqu'à Wally, sinon il annonce un shoutout
    qui n'a pas eu lieu — le défaut exact de `send_message` qui avalait ses
    erreurs et laissait enrichir la mémoire d'une réplique jamais partie."""
    from bot.core.shoutout_tool import run_shoutout_tool

    api = MagicMock()
    api.get_broadcaster_id = AsyncMock(return_value="777")
    api.send_shoutout = AsyncMock(return_value="c'est trop tôt.")
    rendu = json.loads(await run_shoutout_tool(_bot_avec_api(api), {"user": "kassandre"}))

    assert rendu["status"] != "ok"
    assert "trop tôt" in rendu["message"]


# ── le canal des messages AUTOMATIQUES ────────────────────────────────────

@pytest.mark.asyncio
async def test_un_message_automatique_part_en_annonce():
    """Tout ce qui n'est pas une réponse à quelqu'un passe par là.

    Récompense de points de chaîne, follow, raid, étape de duel, fin de
    partie, `!mood` : ces lignes sortaient avec exactement le même poids
    visuel qu'un « lol » de viewer. L'annonce les sépare.
    """
    api = make_api()
    http, ctx = _post(make_204())
    try:
        assert await api.send_automatic("Azraël vient de passer Diamant") is True
    finally:
        ctx.stop()
    assert http.post.call_args.kwargs["json"]["color"] == "purple"


@pytest.mark.asyncio
async def test_sans_le_scope_le_message_automatique_sort_QUAND_MEME():
    """Le canal peut manquer — scope pas encore ré-autorisé, bot non modérateur.
    Ce n'est pas une raison de se taire : une récompense payée en points doit
    produire une réponse visible, colorée ou non."""
    api = make_api()
    refus, ctx = make_erreur(401), None
    with patch("bot.twitch.api.httpx.AsyncClient") as MockClient:
        http = MockClient.return_value.__aenter__.return_value
        # L'annonce échoue (401 même après refresh), le message ordinaire passe.
        http.post = AsyncMock(side_effect=[refus, refus, make_http_message_ok()])
        assert await api.send_automatic("merci pour les 100 bits") is True
    assert http.post.await_count == 3


def make_http_message_ok():
    """Un 200 de `POST /helix/chat/messages` : le corps dit qu'il est publié."""
    resp = MagicMock()
    resp.status_code = 200
    resp.json = MagicMock(return_value={
        "data": [{"message_id": "abc", "is_sent": True, "drop_reason": None}]})
    resp.raise_for_status = MagicMock()
    return resp


# ── l'invariant : aucun chemin automatique ne repasse par le chat ordinaire ─

_AUTOMATIQUES = [
    ("bot/twitch/duel_announce.py", "les étapes du duel Apex"),
    ("bot/twitch/jeu_announce.py", "les fins de sondage et de pendu"),
    ("bot/twitch/events/im_out.py", "la récompense « I'm out »"),
    ("bot/twitch/events/redemptions.py", "les récompenses de points de chaîne"),
    ("bot/twitch/events/humeur.py", "l'humeur forcée et son remboursement"),
    ("bot/twitch/events/social.py", "follow, sub, bits, raid"),
    ("bot/twitch/events/virus_popups.py", "l'attaque de popups"),
    ("bot/twitch/commands/mood.py", "!mood — cinq valeurs, aucune rédaction"),
    ("bot/twitch/commands/code.py", "!code — un lien, aucune rédaction"),
]


@pytest.mark.parametrize("chemin,quoi", _AUTOMATIQUES)
def test_un_chemin_automatique_ne_publie_pas_en_message_ordinaire(chemin, quoi):
    """Neuf fichiers, un seul canal. Un dixième s'ajoutera un jour.

    L'invariant se vérifie sur le TEXTE parce qu'il porte sur des sites d'appel
    dispersés : les rejouer tous demanderait neuf harnais d'événements, et
    c'est justement le genre de couverture qu'on n'écrit pas — puis un site
    repart en `send_message` sans que personne ne le voie.

    `send_automatic` retombe DÉJÀ sur `send_message` quand le canal manque :
    un appel direct ici n'est donc jamais un repli, seulement un oubli.
    """
    from pathlib import Path

    source = (Path(__file__).resolve().parents[1] / chemin).read_text(encoding="utf-8")
    assert "send_message(" not in source, (
        f"{chemin} ({quoi}) publie en message ordinaire. Ce chemin est "
        "AUTOMATIQUE : personne n'a parlé à Wally, il doit passer par "
        "`send_automatic`, qui gère déjà le repli."
    )
    assert "send_automatic(" in source, (
        f"{chemin} ({quoi}) n'appelle plus le canal automatique."
    )


def test_les_chemins_de_CONVERSATION_restent_en_message_ordinaire():
    """L'autre moitié de l'invariant, et la plus facile à perdre.

    Trois sorties doivent garder le poids visuel d'un message de chat, parce
    que ce sont des tours de parole : la réponse à quelqu'un, la prise de
    parole spontanée dans une conversation en cours, et la confirmation d'un
    `say_in_voice` adressée à celui qui l'a demandée. Les passer en violet
    ferait dire au fond coloré le contraire de ce qu'il dit — et noierait le
    signal en une soirée, ce qui est le risque nommé dès la fiche de départ.
    """
    from pathlib import Path

    racine = Path(__file__).resolve().parents[1]
    handlers = (racine / "bot/twitch/handlers.py").read_text(encoding="utf-8")
    voice = (racine / "bot/discord/voice/request.py").read_text(encoding="utf-8")

    # `_envoyer_reponse_twitch` (la réponse) et le chemin spontané.
    assert handlers.count("twitch_api.send_message(") == 2
    assert "api.send_message(" in voice
