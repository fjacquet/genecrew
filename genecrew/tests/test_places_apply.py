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


def _client(records):
    def handler(request):
        if request.url.path == "/api/token/":
            return httpx.Response(200, json={"access_token": "t"})
        if request.method == "GET" and request.url.path == "/api/places/":
            page = int(request.url.params.get("page", "1"))
            return httpx.Response(200, json=PLACES if page == 1 else [])
        if request.method == "GET" and request.url.path.startswith("/api/places/"):
            return httpx.Response(200, json=PLACES[0])
        if request.method == "POST" and request.url.path == "/api/places/":
            records.append(("POST", json.loads(request.content)))
            return httpx.Response(201, json={"handle": "H_" + json.loads(request.content)["name"]["value"]})
        if request.method == "PUT":
            records.append(("PUT", json.loads(request.content)))
            return httpx.Response(200, json={})
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
