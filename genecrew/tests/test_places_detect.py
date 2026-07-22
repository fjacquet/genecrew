"""Tests offline du mode détection de `merge places`."""

import httpx
import pytest
from crewai_custom_tools.tools.genealogy.gramps.client import GrampsClient, GrampsConfig

from genecrew.places_merge import collecter_lieux

CONFIG = GrampsConfig(api_url="http://g.test/api", username="u", password="p")


@pytest.fixture(autouse=True)
def _real_writes(monkeypatch):
    monkeypatch.setenv("GENECREW_DRY_RUN", "false")


def _client(handler):
    def _h(request):
        if request.url.path == "/api/token/":
            return httpx.Response(200, json={"access_token": "t"})
        return handler(request)
    return GrampsClient(CONFIG, transport=httpx.MockTransport(_h))


def _arbre(places, backlinks=None):
    backlinks = backlinks or {}

    def _h(request):
        p = request.url.path
        if p == "/api/places/":
            page = int(request.url.params.get("page", 1))
            return httpx.Response(200, json=places if page == 1 else [])
        if p.startswith("/api/places/"):
            handle = p.rsplit("/", 1)[-1]
            return httpx.Response(200, json={"backlinks": backlinks.get(handle, {})})
        return httpx.Response(404, json={})
    return _client(_h)


PLACE = {"handle": "H1", "gramps_id": "P0001", "name": {"value": "Bourges"},
         "place_type": "Municipality", "code": "18033", "lat": "47.081",
         "long": "2.398", "placeref_list": [{"ref": "HP"}]}


def test_collecte_les_champs_utiles():
    lieux = collecter_lieux(_arbre([PLACE]), "all")
    assert len(lieux) == 1
    p = lieux[0]
    assert (p.gramps_id, p.handle, p.nom) == ("P0001", "H1", "Bourges")
    assert p.place_type == "Municipality"
    assert p.code == "18033"
    assert (p.lat, p.long) == ("47.081", "2.398")
    assert p.a_parent is True


def test_compte_les_retroliens():
    client = _arbre([PLACE], backlinks={"H1": {"event": ["e1", "e2", "e3"],
                                               "place": ["p1"]}})
    assert collecter_lieux(client, "all")[0].retroliens == 4


def test_absence_de_retroliens_donne_zero():
    assert collecter_lieux(_arbre([PLACE]), "all")[0].retroliens == 0


def test_lieu_sans_nom_collecte_quand_meme_avec_nom_vide():
    """Le filtrage des noms vides appartient à la détection, pas à la collecte."""
    sans_nom = {**PLACE, "name": {}}
    assert collecter_lieux(_arbre([sans_nom]), "all")[0].nom == ""


def test_champs_absents_donnent_des_defauts_vides():
    nu = {"handle": "H2", "gramps_id": "P0002", "name": {"value": "X"}}
    p = collecter_lieux(_arbre([nu]), "all")[0]
    assert (p.place_type, p.code, p.lat, p.long, p.a_parent) == ("", "", "", "", False)


def test_echec_du_comptage_degrade_vers_zero_sans_faire_echouer_la_collecte():
    """Un vrai échec réseau/API sur le comptage ne doit ni lever, ni perdre le lieu."""
    def _h(request):
        p = request.url.path
        if p == "/api/places/":
            page = int(request.url.params.get("page", 1))
            return httpx.Response(200, json=[PLACE] if page == 1 else [])
        if p.startswith("/api/places/"):
            return httpx.Response(500, json={"error": "boom"})
        return httpx.Response(404, json={})

    lieux = collecter_lieux(_client(_h), "all")
    assert len(lieux) == 1
    assert lieux[0].retroliens == 0
