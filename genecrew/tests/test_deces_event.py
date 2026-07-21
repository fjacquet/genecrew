"""Tests offline de `apply deaths` — création d'événements décès sourcés."""

import httpx
import pytest
from crewai_custom_tools.tools.genealogy.gramps.client import GrampsClient, GrampsConfig

from genecrew.deces_event import index_lieux, normaliser_lieu, resoudre_lieu

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


def _places_client(places):
    def _h(request):
        if request.url.path == "/api/places/":
            page = int(request.url.params.get("page", 1))
            return httpx.Response(200, json=places if page == 1 else [])
        return httpx.Response(404, json={})
    return _client(_h)


def test_normalisation_ignore_casse_accents_et_separateurs():
    assert normaliser_lieu("Saint-Palais") == normaliser_lieu("SAINT PALAIS")
    assert normaliser_lieu("Nohant-en-Goût") == normaliser_lieu("nohant en gout")


def test_index_rend_le_handle_d_un_lieu_unique():
    client = _places_client([
        {"handle": "P1", "name": {"value": "Bourges"}},
        {"handle": "P2", "name": {"value": "Vierzon"}},
    ])
    index = index_lieux(client)
    assert resoudre_lieu(index, "bourges") == "P1"


def test_lieu_absent_rend_none():
    client = _places_client([{"handle": "P1", "name": {"value": "Bourges"}}])
    index = index_lieux(client)
    assert resoudre_lieu(index, "Saint-Palais") is None


def test_homonymes_rendent_none_plutot_qu_un_choix():
    """Deux lieux du même nom : rattacher au hasard poserait un décès dans la
    mauvaise commune sans que rien ne le signale."""
    client = _places_client([
        {"handle": "P1", "name": {"value": "Saint-Palais"}},
        {"handle": "P2", "name": {"value": "Saint-Palais"}},
    ])
    index = index_lieux(client)
    assert "saint palais" in index          # connu…
    assert resoudre_lieu(index, "Saint-Palais") is None   # …mais pas résolu


def test_lieu_sans_nom_est_ignore():
    client = _places_client([
        {"handle": "P1", "name": {}},
        {"handle": "P2", "name": {"value": "Bourges"}},
    ])
    index = index_lieux(client)
    assert resoudre_lieu(index, "Bourges") == "P2"
