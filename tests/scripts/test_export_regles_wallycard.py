"""L'export du livre des règles : ce qui sort de Notion, ce qui n'en sort pas."""

import pytest

from scripts.export_regles_wallycard import convertir_blocs, decouper_chapitres

ID_FEUR = "3d7e93ddd545818cbefdd1d581684d58"
CARTES = {ID_FEUR: "feur"}


def _texte(contenu, **notes):
    return {"type": "text", "plain_text": contenu, "href": None, "annotations": notes}


def _bloc(genre, *morceaux, enfants=False):
    return {"id": "b", "type": genre, "has_children": enfants, genre: {"rich_text": list(morceaux)}}


def test_puces_consecutives_forment_une_seule_liste():
    blocs = convertir_blocs(
        [_bloc("bulleted_list_item", _texte("un")), _bloc("bulleted_list_item", _texte("deux")),
         _bloc("paragraph", _texte("fin")), _bloc("bulleted_list_item", _texte("trois"))],
        CARTES)
    assert [b["type"] for b in blocs] == ["ul", "p", "ul"]
    assert len(blocs[0]["items"]) == 2


def test_carte_citee_par_mention_ou_par_lien_devient_un_lien_de_fiche():
    mention = {"type": "mention", "plain_text": "FEUR", "href": None, "annotations": {},
               "mention": {"type": "page", "page": {"id": "3d7e93dd-d545-818c-befd-d1d581684d58"}}}
    lien = {**_texte("FEUR", bold=True), "href": f"https://app.notion.com/p/{ID_FEUR}"}
    [bloc] = convertir_blocs([_bloc("paragraph", mention, lien)], CARTES)
    assert bloc["texte"] == [{"t": "FEUR", "carte": "feur"}, {"t": "FEUR", "g": True, "carte": "feur"}]


def test_lien_notion_vers_autre_chose_quune_carte_nest_pas_un_lien_externe():
    # Une page de travail Notion n'est pas publique : le lien ne doit pas partir sur le site.
    lien = {**_texte("page"), "href": "https://app.notion.com/p/" + "a" * 32}
    [bloc] = convertir_blocs([_bloc("paragraph", lien)], CARTES)
    assert bloc["texte"] == [{"t": "page"}]


def test_bloc_inconnu_arrete_lexport():
    with pytest.raises(ValueError, match="toggle"):
        convertir_blocs([_bloc("toggle", _texte("caché"))], CARTES)


def test_bloc_imbrique_arrete_lexport():
    with pytest.raises(ValueError, match="imbriqué"):
        convertir_blocs([_bloc("bulleted_list_item", _texte("parent"), enfants=True)], CARTES)


def test_tableau_lit_ses_lignes():
    table = {"id": "t", "type": "table", "has_children": True, "table": {"has_column_header": True}}
    lignes = [{"table_row": {"cells": [[_texte("État")], [_texte("Effet")]]}}]
    [bloc] = convertir_blocs([table], CARTES, lambda _id: lignes)
    assert bloc == {"type": "table", "entete": True, "lignes": [[[{"t": "État"}], [{"t": "Effet"}]]]}


def test_chapitres_sarretent_a_la_partie_non_decidee():
    h1 = lambda t: {"type": "h1", "texte": [{"t": t}]}  # noqa: E731
    p = {"type": "p", "texte": [{"t": "x"}]}
    chapitres = decouper_chapitres([p, h1("1. Bref"), p, h1("❓ À trancher"), p, h1("💡 Propositions"), p])
    assert chapitres == [{"titre": "1. Bref", "blocs": [p]}]
