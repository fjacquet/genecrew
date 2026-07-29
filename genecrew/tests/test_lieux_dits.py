"""Cascade de résolution d'un lieu-dit — hors ligne, aucun appel réseau."""

import httpx
import pytest
from crewai_custom_tools.tools.genealogy.gramps.client import GrampsClient, GrampsConfig
from genecrew.lieux_dits import (
    RechercheArbreIndisponible,
    chercher_dans_arbre,
    normaliser_nom,
)

CONFIG = GrampsConfig(api_url="http://x/api", username="u", password="p")


def _client(handler):
    """Client Gramps sur transport simulé, jeton servi automatiquement."""

    def _h(request):
        if request.url.path == "/api/token/":
            return httpx.Response(200, json={"access_token": "t"})
        return handler(request)

    return GrampsClient(CONFIG, transport=httpx.MockTransport(_h))


def _place(gramps_id, handle, nom, place_type, parent_handle):
    """Un lieu Gramps réaliste, réduit aux clés que la cascade lit."""
    return {
        "gramps_id": gramps_id,
        "handle": handle,
        "name": {"value": nom},
        "place_type": place_type,
        "placeref_list": [{"ref": parent_handle}],
    }


def _handler_places(*places):
    """Répond /api/places/ avec la liste donnée."""

    def _h(request):
        if request.url.path == "/api/places/":
            return httpx.Response(200, json=list(places))
        return httpx.Response(404, json={})

    return _h


def test_trouve_le_lieu_dit_sous_sa_commune():
    """Nom + type + parent suffisent : 663 lieux, 3 collisions, toutes inter-types."""
    client = _client(
        _handler_places(
            _place("P0661", "h_roches", "Les Roches", "Hamlet", "h_commune")
        )
    )
    assert chercher_dans_arbre(client, "Les Roches", "h_commune") == "h_roches"


def test_ignore_l_homonyme_rattache_a_une_autre_commune():
    """Le parent est ce qui rend la recherche déterministe.

    Sans lui, un « Les Roches » d'ailleurs dans l'arbre serait attrapé — la
    version arbre du bug d'origine.
    """
    client = _client(
        _handler_places(
            _place("P0999", "h_ailleurs", "Les Roches", "Hamlet", "h_autre_commune")
        )
    )
    assert chercher_dans_arbre(client, "Les Roches", "h_commune") is None


def test_la_casse_et_les_espaces_ne_font_pas_manquer_le_lieu():
    """Normalisation : strip() puis casefold(), celle de la mesure des collisions."""
    client = _client(
        _handler_places(
            _place("P0661", "h_roches", "Les Roches", "Hamlet", "h_commune")
        )
    )
    assert chercher_dans_arbre(client, "  les roches ", "h_commune") == "h_roches"


def test_un_lieu_du_mauvais_type_n_est_pas_retenu():
    """Une COMMUNE nommée comme le lieu-dit n'est pas le lieu-dit."""
    client = _client(
        _handler_places(
            _place("P0500", "h_ville", "Les Roches", "Municipality", "h_commune")
        )
    )
    assert chercher_dans_arbre(client, "Les Roches", "h_commune") is None


def test_deux_homonymes_de_meme_type_sous_la_meme_commune_font_refuser():
    """Un refus coûte moins qu'un choix arbitraire entre deux lieux réels."""
    client = _client(
        _handler_places(
            _place("P0661", "h_a", "Les Roches", "Hamlet", "h_commune"),
            _place("P0662", "h_b", "Les Roches", "Hamlet", "h_commune"),
        )
    )
    assert chercher_dans_arbre(client, "Les Roches", "h_commune") is None


def test_une_panne_de_lecture_leve_au_lieu_de_rendre_none():
    """L'invariant central : une panne n'est PAS une absence.

    Rendre None ferait croire à la cascade que le lieu-dit n'existe pas, et
    elle en créerait un doublon. La fusion de lieux est délicate (ADR 0015) ;
    mieux vaut ne rien poser.
    """

    def _h(request):
        return httpx.Response(500, json={"error": "boom"})

    with pytest.raises(RechercheArbreIndisponible):
        chercher_dans_arbre(_client(_h), "Les Roches", "h_commune")


def test_normaliser_nom_est_strip_puis_casefold():
    """Verrouille la normalisation : la mesure des collisions n'a de sens qu'ainsi."""
    assert normaliser_nom("  Les Roches ") == "les roches"
