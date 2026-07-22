import json

import httpx
import pytest
import yaml
from crewai_custom_tools.tools.genealogy.gramps.client import GrampsClient, GrampsConfig
from crewai_custom_tools.tools.genealogy.gramps import write_tools
from crewai_custom_tools.tools.genealogy.models.domain import (
    DatedChain,
    PlaceLevel,
    PlaceProposition,
    ResolvedPlace,
)
from genecrew import places_apply
from genecrew.places_apply import run_places_apply

CONFIG = GrampsConfig(api_url="http://g.test/api", username="u", password="p")
# deux feuilles DIFFÉRENTES qui résolvent vers le MÊME lieu canonique → une fusion proposée
PLACES = [
    {
        "handle": "h1",
        "gramps_id": "P0001",
        "name": {"value": "A"},
        "alt_names": [],
        "placeref_list": [],
    },
    {
        "handle": "h2",
        "gramps_id": "P0002",
        "name": {"value": "B"},
        "alt_names": [],
        "placeref_list": [],
    },
]


@pytest.fixture(autouse=True)
def _no_global_dry_run(monkeypatch):
    monkeypatch.setenv("GENECREW_DRY_RUN", "false")


def _same_canonical(place, min_score):
    rp = ResolvedPlace(
        name="Bourges",
        place_type="Municipality",
        lat="47.081",
        long="2.399",
        chains=[DatedChain(levels=[PlaceLevel(name="France", place_type="Country")])],
        score=1.0,
        source="geo.api.gouv.fr",
        query="q",
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
        preuve="…",
    )


def _client():
    def handler(request):
        if request.url.path == "/api/token/":
            return httpx.Response(200, json={"access_token": "t"})
        if request.method == "GET" and request.url.path == "/api/places/":
            page = int(request.url.params.get("page", "1"))
            return httpx.Response(200, json=PLACES if page == 1 else [])
        if request.method == "GET" and request.url.path.startswith("/api/places/"):
            return httpx.Response(200, json=PLACES[0])
        if request.method == "POST" and request.url.path == "/api/places/":
            return httpx.Response(
                201,
                json={"handle": "H_" + json.loads(request.content)["name"]["value"]},
            )
        if request.method == "PUT":
            return httpx.Response(200, json={})
        return httpx.Response(404)

    return GrampsClient(CONFIG, transport=httpx.MockTransport(handler))


def test_apply_emits_fusions_yaml(tmp_path, monkeypatch, mocker):
    monkeypatch.setattr(places_apply, "build_proposition", _same_canonical)
    mocker.patch.object(write_tools, "get_client", return_value=_client())
    run_places_apply(_client(), "all", tmp_path, date="2026-07-19", dry_run=False)
    fusions = tmp_path / "lieux" / "2026-07-19_fusions_lieux_all.yaml"
    data = yaml.safe_load(fusions.read_text(encoding="utf-8"))
    assert len(data) == 1  # une fusion proposée
    assert (
        data[0]["gramps_id_keep"] == "P0001" and data[0]["gramps_id_merge"] == "P0002"
    )
