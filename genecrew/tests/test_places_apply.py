import json

import httpx
import pytest
from crewai_custom_tools.tools.genealogy.gramps.client import GrampsClient, GrampsConfig
from crewai_custom_tools.tools.genealogy.gramps import write_tools
from crewai_custom_tools.tools.genealogy.models.domain import (
    DatedChain, PlaceLevel, ResolvedPlace,
)
from genecrew import places_apply
from genecrew.places_apply import run_places_apply

CONFIG = GrampsConfig(api_url="http://g.test/api", username="u", password="p")
PLACES = [{"handle": "h1", "gramps_id": "P0001",
           "name": {"value": ", , Bourges, 18033, 18000, Cher, Centre-Val de Loire, France"},
           "place_type": "Unknown", "alt_names": [], "placeref_list": []}]


@pytest.fixture(autouse=True)
def _no_global_dry_run(monkeypatch):
    monkeypatch.setenv("GENECREW_DRY_RUN", "false")


def _authoritative(place, min_score):
    from crewai_custom_tools.tools.genealogy.models.domain import PlaceProposition
    rp = ResolvedPlace(name="Bourges", place_type="Municipality", lat="47.081", long="2.399",
                       code="18033",
                       chains=[DatedChain(levels=[
                           PlaceLevel(name="France", place_type="Country"),
                           PlaceLevel(name="Cher", place_type="Department", code="18")])],
                       score=1.0, source="geo.api.gouv.fr", query="/communes/18033")
    return PlaceProposition(type="lieu_resolu", gramps_id=place["gramps_id"], handle=place["handle"],
                            original=place["name"]["value"], country="France", resolution=rp,
                            action="ecrire", confiance="haute", priorite="haute", preuve="…")


def _client(records, places=None, put_status=200):
    places = PLACES if places is None else places
    def handler(request):
        if request.url.path == "/api/token/":
            return httpx.Response(200, json={"access_token": "t"})
        if request.method == "GET" and request.url.path == "/api/places/":
            page = int(request.url.params.get("page", "1"))
            return httpx.Response(200, json=places if page == 1 else [])
        if request.method == "GET" and request.url.path.startswith("/api/places/"):
            handle = request.url.path.rsplit("/", 1)[-1]
            match = next((p for p in places if p["handle"] == handle), places[0])
            return httpx.Response(200, json=match)
        if request.method == "POST" and request.url.path == "/api/places/":
            records.append(("POST", json.loads(request.content)))
            return httpx.Response(201, json={"handle": "H_" + json.loads(request.content)["name"]["value"]})
        if request.method == "PUT":
            records.append(("PUT", json.loads(request.content)))
            return httpx.Response(put_status, json={} if put_status == 200 else {"detail": "boom"})
        return httpx.Response(404)
    return GrampsClient(CONFIG, transport=httpx.MockTransport(handler))


def test_apply_writes_parents_once_and_enriches_leaf(tmp_path, monkeypatch, mocker):
    monkeypatch.setattr(places_apply, "build_proposition", _authoritative)
    records = []
    client = _client(records)
    mocker.patch.object(write_tools, "get_client", return_value=client)
    report = run_places_apply(client, "all", tmp_path, date="2026-07-19", dry_run=False)
    posts = [r for m, r in records if m == "POST"]
    puts = [r for m, r in records if m == "PUT"]
    assert {p["name"]["value"] for p in posts} == {"France", "Cher"}   # 2 parents créés
    assert any(p.get("place_type") == "Municipality" for p in puts)    # feuille enrichie
    assert "à écrire" in report.read_text(encoding="utf-8").lower() or "écrit" in report.read_text(encoding="utf-8").lower()


def test_apply_dry_run_writes_nothing(tmp_path, monkeypatch, mocker):
    monkeypatch.setattr(places_apply, "build_proposition", _authoritative)
    records = []
    client = _client(records)
    mocker.patch.object(write_tools, "get_client", return_value=client)
    run_places_apply(client, "all", tmp_path, date="2026-07-19", dry_run=True)
    assert not records                                                 # aucun POST/PUT


# deux lieux DÉJÀ structurés : un parent Country et une feuille Municipality avec placeref
STRUCTURED_PLACES = [
    {"handle": "hFrance", "gramps_id": "P0100", "name": {"value": "France"},
     "place_type": "Country", "alt_names": [], "placeref_list": []},
    {"handle": "hBourges", "gramps_id": "P0002", "name": {"value": "Bourges"},
     "place_type": "Municipality", "alt_names": [], "placeref_list": [{"ref": "hFrance"}]},
]

# France existe déjà (Country) + une feuille plate (Unknown) à résoudre sous France>Cher
EXISTING_FRANCE_PLUS_LEAF = [
    {"handle": "hFrance", "gramps_id": "P0100", "name": {"value": "France"},
     "place_type": "Country", "alt_names": [], "placeref_list": []},
    {"handle": "h1", "gramps_id": "P0001",
     "name": {"value": ", , Bourges, 18033, 18000, Cher, Centre-Val de Loire, France"},
     "place_type": "Unknown", "alt_names": [], "placeref_list": []},
]


def test_apply_skips_already_structured_places_idempotent(tmp_path, monkeypatch, mocker):
    """A second real run must be a no-op: already-typed places are never reprocessed."""
    calls = []

    def _spy(place, min_score):
        calls.append(place["gramps_id"])
        return _authoritative(place, min_score)

    monkeypatch.setattr(places_apply, "build_proposition", _spy)
    records = []
    client = _client(records, places=STRUCTURED_PLACES)
    mocker.patch.object(write_tools, "get_client", return_value=client)
    report = run_places_apply(client, "all", tmp_path, date="2026-07-19", dry_run=False)
    assert records == []                                    # aucun POST/PUT : re-run idempotent
    assert calls == []                                       # build_proposition jamais appelé
    assert "Déjà structurés (ignorés) : 2" in report.read_text(encoding="utf-8")


def test_apply_seeds_parent_index_reuses_existing_parent(tmp_path, monkeypatch, mocker):
    """A parent that already exists in Gramps must be reused, not re-created."""
    monkeypatch.setattr(places_apply, "build_proposition", _authoritative)
    records = []
    client = _client(records, places=EXISTING_FRANCE_PLUS_LEAF)
    mocker.patch.object(write_tools, "get_client", return_value=client)
    run_places_apply(client, "all", tmp_path, date="2026-07-19", dry_run=False)
    posts = [r for m, r in records if m == "POST"]
    puts = [r for m, r in records if m == "PUT"]
    assert {p["name"]["value"] for p in posts} == {"Cher"}          # France réutilisé, pas re-créé
    assert posts[0]["placeref_list"][0]["ref"] == "hFrance"          # Cher rattaché au France existant
    assert len(puts) == 1                                            # seule la feuille P0001 est écrite
    assert puts[0]["placeref_list"][0]["ref"] == "H_Cher"


def test_apply_failed_leaf_write_records_error_not_applied(tmp_path, monkeypatch, mocker):
    """A failed PUT (server error) must be counted as an error, never as 'written'."""
    monkeypatch.setattr(places_apply, "build_proposition", _authoritative)
    records = []
    client = _client(records, put_status=500)
    mocker.patch.object(write_tools, "get_client", return_value=client)
    report = run_places_apply(client, "all", tmp_path, date="2026-07-19", dry_run=False)
    assert any(m == "PUT" for m, _ in records)                      # le PUT a bien été tenté
    text = report.read_text(encoding="utf-8")
    assert "Lieux écrits : 0" in text
    assert "Erreurs : 1" in text
