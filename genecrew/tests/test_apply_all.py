"""Tests de la commande parapluie apply-all (orchestration casse + genre + lieux)."""

import json

import httpx
import pytest

from crewai_custom_tools.tools.genealogy.gramps.client import GrampsClient, GrampsConfig
from crewai_custom_tools.tools.genealogy.models.domain import (
    PlaceProposition,
    ResolvedPlace,
)

from genecrew import places_apply
from genecrew import deces as deces_mod
from genecrew.apply_all import run_apply_all

CONFIG = GrampsConfig(api_url="http://g.test/api", username="u", password="p")

# Personne en CAPITALES (déclenche la casse) au prénom nettement féminin (déclenche le genre).
PEOPLE = [
    {
        "handle": "h1",
        "gramps_id": "I0001",
        "gender": 2,
        "primary_name": {
            "first_name": "SUZANNE",
            "surname_list": [{"surname": "MARTIN"}],
        },
    },
]

# Un lieu plat (place_type Unknown) pour déclencher le volet lieux.
PLACES = [
    {
        "handle": "hp1",
        "gramps_id": "P0001",
        "name": {"value": "Bourges, Cher, France"},
        "place_type": "Unknown",
        "alt_names": [],
        "placeref_list": [],
    },
]


@pytest.fixture(autouse=True)
def _no_global_dry_run(monkeypatch):
    monkeypatch.setenv(
        "GENECREW_DRY_RUN", "false"
    )  # défaut réel = simuler ; ici on écrit


@pytest.fixture(autouse=True)
def _small_table(monkeypatch):
    # Le volet genre appelle load_prenoms_table() ; on injecte une petite table hors-ligne.
    monkeypatch.setattr(
        "genecrew.gender_apply.load_prenoms_table", lambda: {"SUZANNE": (9990, 10)}
    )


def _authoritative_place(place, min_score):
    # chains=[] : suffit à exercer l'écriture de la feuille sans simuler la création de
    # parents (déjà couvert par genecrew/tests/test_places_apply.py) ; évite resolve_place (réseau).
    rp = ResolvedPlace(
        name="Bourges",
        place_type="Municipality",
        lat="47.081",
        long="2.399",
        code="18033",
        chains=[],
        score=1.0,
        source="test",
        query="test",
    )
    return PlaceProposition(
        type="lieu_resolu",
        gramps_id=place["gramps_id"],
        handle=place["handle"],
        original=place["name"]["value"],
        country="France",
        resolution=rp,
        action="ecrire",
        confiance="haute",
        priorite="haute",
        preuve="test",
    )


@pytest.fixture(autouse=True)
def _canned_place_proposition(monkeypatch):
    monkeypatch.setattr(places_apply, "build_proposition", _authoritative_place)


def _patch_write_client(mocker, client):
    # Les outils d'écriture (nom, genre, lieux) résolvent leur client via write_tools.get_client().
    mocker.patch(
        "crewai_custom_tools.tools.genealogy.gramps.write_tools.get_client",
        return_value=client,
    )


def _handler(on_write):
    def handler(request):
        if request.url.path == "/api/token/":
            return httpx.Response(200, json={"access_token": "t"})
        if request.method == "GET" and request.url.path == "/api/people/":
            page = int(request.url.params.get("page", "1"))
            return httpx.Response(200, json=PEOPLE if page == 1 else [])
        if request.method == "GET" and request.url.path == "/api/places/":
            page = int(request.url.params.get("page", "1"))
            return httpx.Response(200, json=PLACES if page == 1 else [])
        if request.method == "GET" and request.url.path.startswith("/api/people/"):
            return httpx.Response(
                200, json=PEOPLE[0]
            )  # fetch mono-personne (outils write)
        if request.method == "GET" and request.url.path.startswith("/api/places/"):
            return httpx.Response(200, json=PLACES[0])  # fetch mono-lieu (outils write)
        if request.method == "POST" and request.url.path == "/api/places/":
            return on_write(request)
        if request.method == "PUT":
            return on_write(request)
        return httpx.Response(404)

    return handler


def test_run_apply_all_runs_all_three_steps(tmp_path, mocker):
    writes = []

    def on_write(request):
        payload = json.loads(request.content)
        writes.append((request.method, payload))
        if request.method == "POST":
            return httpx.Response(
                201, json={"handle": "H_" + payload.get("name", {}).get("value", "new")}
            )
        return httpx.Response(200, json={})

    client = GrampsClient(CONFIG, transport=httpx.MockTransport(_handler(on_write)))
    _patch_write_client(mocker, client)
    mocker.patch.object(
        deces_mod, "search_deces", return_value=[]
    )  # MatchID hors-ligne
    mocker.patch.object(deces_mod, "THROTTLE_S", 0)
    paths = run_apply_all(
        client,
        "all",
        tmp_path,
        date="2026-07-18",
        min_ratio=0.98,
        min_score=0.90,
        dry_run=False,
    )
    assert set(paths) == {
        "names",
        "incomplete",
        "gender",
        "lieux",
        "deces",
        "deces_propositions",
    }
    assert all(p.exists() for p in paths.values())
    # casse appliquée (SUZANNE -> Suzanne) ET genre écrit (U -> F = 0)
    assert paths["names"].read_text(encoding="utf-8").count("Suzanne") >= 1
    assert "Genres écrits : 1" in paths["gender"].read_text(encoding="utf-8")
    puts = [payload for method, payload in writes if method == "PUT"]
    genders = [p["primary_name"]["first_name"] for p in puts if "primary_name" in p]
    assert "Suzanne" in genders  # un PUT a recasé le prénom
    assert any(p.get("gender") == 0 for p in puts)  # un PUT a écrit le genre F
    # volet lieux : la feuille plate (Unknown) a été écrite (place_type -> Municipality)
    assert any(p.get("place_type") == "Municipality" for p in puts)
    assert "Lieux écrits : 1" in paths["lieux"].read_text(encoding="utf-8")


def test_run_apply_all_dry_run_writes_nothing(tmp_path, mocker):
    def on_write(request):
        raise AssertionError("aucune écriture (personne ou lieu) attendue en dry-run")

    client = GrampsClient(CONFIG, transport=httpx.MockTransport(_handler(on_write)))
    _patch_write_client(mocker, client)
    mocker.patch.object(
        deces_mod, "search_deces", return_value=[]
    )  # MatchID hors-ligne
    mocker.patch.object(deces_mod, "THROTTLE_S", 0)
    paths = run_apply_all(client, "all", tmp_path, date="2026-07-18", dry_run=True)
    assert set(paths) == {
        "names",
        "incomplete",
        "gender",
        "lieux",
        "deces",
        "deces_propositions",
    }
    assert all(p.exists() for p in paths.values())  # rapports produits, rien écrit
