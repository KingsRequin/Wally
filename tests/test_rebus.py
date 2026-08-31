"""Le rébus : le catalogue livré, le moteur, et la partie lancée par l'outil.

Le gros morceau ici est `TestCatalogueLivre` : il ne teste pas du code, il tient
le FICHIER. Quatre relectures phonétiques ont sorti 48 entrées fausses du
catalogue initial, dont deux familles entières ; les invariants mécaniques qui
restent (jetons et lectures accordés, pas d'indicateur régional, pas d'entrée
tout en lettres) sont ceux qu'une relecture humaine rate justement le plus.
"""
from __future__ import annotations

import asyncio
import json
import random
import unicodedata

import pytest

from bot.core import rebus as noyau
from bot.core.rebus import Rebus, Sac, charger, indices, normaliser, trouve
from bot.tools import rebus_tool as jeu

CHAMEAU = Rebus("chameau", ("🐈", "M", "💧"), ("chat", "M", "eau"), "animal")


# ─────────────────────────── le catalogue livré ───────────────────────────
class TestCatalogueLivre:
    @pytest.fixture(scope="class")
    def catalogue(self):
        return charger()

    def test_le_catalogue_est_lisible_et_fourni(self, catalogue):
        assert len(catalogue) > 200

    def test_un_jeton_une_lecture(self, catalogue):
        # `charger()` saute déjà les entrées désaccordées : si le compte tombe,
        # c'est que le fichier en contient, et le test doit le dire.
        assert all(len(r.emojis) == len(r.lecture) for r in catalogue)

    def test_aucun_indicateur_regional(self, catalogue):
        """Deux indicateurs voisins fusionnent en drapeau de pays.

        🇻 + 🇪 s'affiche 🇻🇪 (Venezuela) : le rébus devient illisible avant
        d'être prononcé. 70 entrées d'une version précédente étaient mortes de
        ça. Les lettres sont désormais des caractères ordinaires.
        """
        fautifs = [r.mot for r in catalogue
                   for t in r.emojis if any("\U0001F1E6" <= c <= "\U0001F1FF" for c in t)]
        assert not fautifs, f"indicateurs régionaux : {fautifs}"

    def test_jamais_un_rebus_tout_en_lettres(self, catalogue):
        """Un rébus sans aucun dessin n'est pas un rébus, c'est de l'épellation."""
        nus = [r.mot for r in catalogue
               if all(len(t) == 1 and t.isascii() and t.isalpha() for t in r.emojis)]
        assert not nus, f"aucun emoji dans : {nus}"

    def test_trois_lettres_au_maximum(self, catalogue):
        """Au-delà, l'énigme se lit comme un mot de passe. Les noms propres de
        la commu échappent : aucun emoji ne porte « Azraël »."""
        trop = [r.mot for r in catalogue if r.categorie != "maison"
                and sum(1 for t in r.emojis if len(t) == 1 and t.isascii() and t.isalpha()) > 3]
        assert not trop, f"plus de trois lettres : {trop}"

    def test_aucun_doublon(self, catalogue):
        mots = [r.mot for r in catalogue]
        assert len(mots) == len(set(mots))

    def test_la_reponse_ne_se_lit_pas_dans_ses_propres_indices(self, catalogue):
        """Un indice qui livre la réponse n'est pas un indice.

        Le dernier jeton n'est jamais donné, mais un rébus dont un jeton
        PRÉCÉDENT est déjà le mot entier (« chat » pour « chat ») se gagnerait
        au premier indice.
        """
        fuites = [r.mot for r in catalogue
                  if any(trouve(r, i) for i in indices(r))]
        assert not fuites, f"la réponse fuit dans les indices : {fuites}"

    def test_chaque_mot_est_du_texte_simple(self, catalogue):
        """Pas d'emoji ni de ponctuation dans la réponse : elle se tape au clavier."""
        assert all(normaliser(r.mot) for r in catalogue)


# ─────────────────────────────── le moteur ────────────────────────────────
class TestNormalisationEtReponse:
    def test_les_accents_et_la_casse_ne_comptent_pas(self):
        assert trouve(Rebus("château", ("🐈", "💧"), ("chat", "eau"), "objet"),
                      "CHATEAU !!")

    def test_le_mot_se_trouve_au_milieu_d_une_phrase(self):
        assert trouve(CHAMEAU, "euh c'est un chameau non ?")

    def test_le_pluriel_en_s_et_en_x_passe(self):
        assert trouve(CHAMEAU, "des chameaux")
        assert trouve(Rebus("radis", ("🐀", "D", "I"), ("rat", "D", "I"), "nourriture"),
                      "radis")

    def test_un_morceau_du_mot_ne_gagne_pas(self):
        """« chat » ne doit pas gagner « château » : sinon la première ligne
        venue emporte la partie, et le rébus n'existe pas."""
        assert not trouve(Rebus("château", ("🐈", "💧"), ("chat", "eau"), "objet"), "un chat")

    def test_un_mot_qui_contient_la_reponse_ne_gagne_pas(self):
        assert not trouve(CHAMEAU, "chameaupolis")


class TestIndices:
    def test_le_dernier_jeton_n_est_jamais_donne(self):
        assert not any("eau" in i for i in indices(CHAMEAU))

    def test_les_indices_vont_du_vague_au_precis(self):
        i = indices(CHAMEAU)
        assert "animal" in i[0] and "7 lettres" in i[1] and "chat" in i[2]


class TestSac:
    def test_tirage_sans_remise(self):
        sac = Sac([CHAMEAU, Rebus("rat", ("🐀",), ("rat",), "animal")], random.Random(0))
        assert {sac.tirer().mot, sac.tirer().mot} == {"chameau", "rat"}

    def test_le_sac_se_recharge_une_fois_vide(self):
        sac = Sac([CHAMEAU], random.Random(0))
        assert sac.tirer().mot == sac.tirer().mot == "chameau"

    def test_un_catalogue_vide_ne_leve_pas(self):
        assert Sac([]).tirer() is None


class TestCatalogueAbsent:
    def test_un_fichier_manquant_rend_une_liste_vide(self, tmp_path):
        assert charger(tmp_path / "rien.json") == []

    def test_un_fichier_illisible_rend_une_liste_vide(self, tmp_path):
        f = tmp_path / "cassé.json"
        f.write_text("{pas du json", encoding="utf-8")
        assert charger(f) == []

    def test_une_entree_desaccordee_est_sautee_pas_jouee(self, tmp_path):
        """Jetons et lectures de longueurs différentes = indices décalés."""
        f = tmp_path / "r.json"
        f.write_text('{"rebus": [{"mot": "x", "emojis": ["🐈", "M"], '
                     '"lecture": ["chat"], "categorie": "animal"}]}', encoding="utf-8")
        assert charger(f) == []


# ─────────────────────────── la partie qui tourne ──────────────────────────
@pytest.fixture(autouse=True)
def partie_neuve(monkeypatch):
    """Aucune partie ne survit d'un test à l'autre, et le repos non plus."""
    monkeypatch.setattr(jeu, "_partie", None, raising=False)
    monkeypatch.setattr(jeu, "_sac", Sac([CHAMEAU]), raising=False)
    monkeypatch.setattr(jeu, "_fin_derniere", float("-inf"), raising=False)
    # L'énigme part normalement 2,5 s après l'outil, le temps que la réplique de
    # Wally sorte. Attendre ce délai pour de vrai à chaque test rendrait la suite
    # lente sans rien prouver de plus.
    monkeypatch.setattr(jeu, "DELAI_ENIGME_S", 0.0)
    yield
    if jeu._partie is not None and jeu._partie.tache is not None:
        jeu._partie.tache.cancel()


class Salon:
    """Un canal où écrire — c'est tout ce que le moteur connaît d'une plateforme."""

    def __init__(self, nom="azrael"):
        self.nom = nom
        self.lignes: list[str] = []
        self.annonces: list[str] = []

    async def publier(self, texte):
        self.lignes.append(texte)

    async def annoncer(self, fait):
        self.annonces.append(fait)

    async def lancer(self):
        return await jeu._lancer(self.nom, self.publier, self.annoncer)


async def _laisser_partir_l_enigme():
    """Rend la main au minuteur, qui publie l'énigme."""
    await asyncio.sleep(0)
    await asyncio.sleep(0)


class TestPartie:
    async def test_l_enigme_est_publiee(self):
        s = Salon()
        await s.lancer()
        await _laisser_partir_l_enigme()
        assert CHAMEAU.enigme in s.lignes[0]

    async def test_l_enigme_ne_part_pas_avant_la_replique_de_wally(self):
        """L'outil rend la main SANS avoir rien publié.

        C'est ce qui met les dessins APRÈS la phrase qui les annonce : le modèle
        répond dans l'intervalle. Publiée depuis l'outil, l'énigme arriverait
        avant « vas-y je suis chaud », et la conversation se lirait à l'envers.
        """
        s = Salon()
        await s.lancer()
        assert s.lignes == []

    async def test_l_enigme_ne_contient_jamais_la_reponse(self):
        s = Salon()
        await s.lancer()
        await _laisser_partir_l_enigme()
        assert "chameau" not in " ".join(s.lignes).lower()

    async def test_la_bonne_reponse_gagne_et_clot_la_partie(self):
        s = Salon()
        await s.lancer()
        assert await jeu.verifier_reponse("Alice", "un chameau !", "azrael")
        assert jeu._partie is None
        assert "Alice" in s.annonces[0] and "CHAMEAU" in s.annonces[0]

    async def test_une_mauvaise_reponse_ne_clot_rien(self):
        s = Salon()
        await s.lancer()
        assert not await jeu.verifier_reponse("Alice", "un dromadaire", "azrael")
        assert jeu._partie is not None

    async def test_sans_partie_la_verification_est_muette(self):
        assert not await jeu.verifier_reponse("Alice", "chameau", "azrael")

    async def test_une_reponse_venue_d_un_AUTRE_salon_ne_gagne_pas(self):
        """Sans cette garde, une bonne réponse tapée sur Discord emporterait la
        partie qui tourne sur Twitch, devant des gens qui ne l'ont jamais vue."""
        s = Salon("twitch")
        await s.lancer()
        assert not await jeu.verifier_reponse("Alice", "chameau", "un-salon-discord")
        assert jeu._partie is not None

    async def test_le_second_gagnant_ne_gagne_pas_deux_fois(self):
        s = Salon()
        await s.lancer()
        await jeu.verifier_reponse("Alice", "chameau", "azrael")
        await jeu.verifier_reponse("Bob", "chameau", "azrael")
        assert len(s.annonces) == 1

    async def test_relancer_dans_le_meme_salon_redonne_l_enigme(self):
        s = Salon()
        await s.lancer()
        await _laisser_partir_l_enigme()
        premier = jeu._partie
        await s.lancer()
        assert jeu._partie is premier and CHAMEAU.enigme in s.lignes[-1]

    async def test_wally_n_anime_pas_deux_parties_a_la_fois(self):
        await Salon("twitch").lancer()
        rapport = json.loads(await Salon("discord").lancer())
        assert rapport["status"] == "ailleurs"

    async def test_le_repos_bloque_une_relance_immediate(self):
        s = Salon()
        await s.lancer()
        await jeu.verifier_reponse("Alice", "chameau", "azrael")
        await s.lancer()
        await _laisser_partir_l_enigme()
        assert jeu._partie is None


class TestCompteRenduAuModele:
    """Ce que l'outil rend à Wally. Il ne doit RIEN pouvoir recopier."""

    async def test_le_compte_rendu_ne_livre_ni_la_reponse_ni_les_emoji(self):
        rapport = await Salon().lancer()
        assert "chameau" not in rapport.lower()
        assert not any(c in rapport for c in CHAMEAU.emojis if not c.isascii())

    async def test_le_compte_rendu_dit_qu_il_a_lance(self):
        assert json.loads(await Salon().lancer())["status"] == "lance"

    async def test_un_catalogue_vide_le_dit_au_lieu_de_mentir(self, monkeypatch):
        """Un outil qui rendrait « ok » dans tous les cas ferait mentir Wally."""
        monkeypatch.setattr(jeu, "_sac", Sac([]))
        rapport = json.loads(await Salon().lancer())
        assert rapport["status"] == "indisponible" and jeu._partie is None

    async def test_le_repos_se_dit_au_modele(self):
        s = Salon()
        await s.lancer()
        await jeu.verifier_reponse("Alice", "chameau", "azrael")
        assert json.loads(await s.lancer())["status"] == "trop_tot"

    async def test_une_partie_en_cours_se_dit_au_modele(self):
        s = Salon()
        await s.lancer()
        assert json.loads(await s.lancer())["status"] == "deja_en_cours"


class TestFiletDuSecret:
    """`secret_guard` masque la réponse tant que la partie tourne — et la LÈVE
    avant la révélation, sinon Wally caviarderait sa propre annonce de fin."""

    async def test_le_mot_est_masque_pendant_la_partie(self):
        from bot.core.secret_guard import redact
        await Salon().lancer()
        assert "chameau" not in redact("la réponse est chameau").lower()

    async def test_le_filet_est_leve_a_la_victoire(self):
        from bot.core.secret_guard import redact
        await Salon().lancer()
        await jeu.verifier_reponse("Alice", "chameau", "azrael")
        assert redact("le mot était chameau") == "le mot était chameau"

    async def test_le_filet_est_leve_quand_le_temps_expire(self, monkeypatch):
        from bot.core.secret_guard import redact
        monkeypatch.setattr(jeu, "DELAI_INDICE_S", 0.0)
        s = Salon()
        await s.lancer()
        await asyncio.wait_for(jeu._partie.tache, timeout=2.0)
        assert jeu._partie is None
        assert redact("le mot était chameau") == "le mot était chameau"
        assert "CHAMEAU" in s.annonces[0]

    async def test_les_indices_sortent_dans_l_ordre_puis_la_reponse(self, monkeypatch):
        monkeypatch.setattr(jeu, "DELAI_INDICE_S", 0.0)
        s = Salon()
        await s.lancer()
        await asyncio.wait_for(jeu._partie.tache, timeout=2.0)
        publies = [l for l in s.lignes if "Indice" in l]
        assert len(publies) == len(indices(CHAMEAU)) and "animal" in publies[0]


class TestEntreesDeChaquePlateforme:
    """Les deux adaptateurs branchent le même moteur sur un canal différent."""

    async def test_discord_publie_dans_le_salon(self):
        envoyes: list[str] = []

        class FauxSalon:
            id = 4242

            async def send(self, texte):
                envoyes.append(texte)

        assert json.loads(await jeu.run_rebus_tool_discord(FauxSalon()))["status"] == "lance"
        await _laisser_partir_l_enigme()
        assert CHAMEAU.enigme in envoyes[0]
        assert jeu._partie.canal == "4242"

    async def test_twitch_sans_api_le_dit_au_lieu_de_planter(self):
        class SansAPI:
            twitch_api = None

        rapport = json.loads(await jeu.run_rebus_tool(SansAPI(), "azrael"))
        assert rapport["status"] == "indisponible" and jeu._partie is None
