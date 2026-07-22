"""Offline tests for lieu-import (resolver mocked, Gramps via MockTransport)."""

import json

import httpx
from crewai_custom_tools.tools.genealogy.gramps import write_tools
from crewai_custom_tools.tools.genealogy.gramps.client import GrampsClient, GrampsConfig
from crewai_custom_tools.tools.genealogy.models.domain import (
    DatedChain,
    PlaceLevel,
    ResolvedPlace,
)
from genecrew.lieu_import import format_lieu_import, run_lieu_import

from genecrew import lieu_import

CONFIG = GrampsConfig(api_url="http://g.test/api", username="u", password="p")

_RESOLVED = ResolvedPlace(
    name="Bourges",
    place_type="Commune",
    lat="47.081",
    long="2.399",
    code="18033",
    # contrat résolveurs: chains = les PARENTS seuls; la feuille = name/place_type
    chains=[
        DatedChain(
            levels=[
                PlaceLevel(name="France", place_type="Country"),
                PlaceLevel(name="Cher", place_type="Department"),
            ]
        )
    ],
    score=1.0,
    source="geo.api.gouv.fr",
    query="Bourges, Cher, France",
)


def _client(handler):
    def _h(request):
        if request.url.path == "/api/token/":
            return httpx.Response(200, json={"access_token": "t"})
        return handler(request)

    return GrampsClient(CONFIG, transport=httpx.MockTransport(_h))


def _existing_places(*specs):
    """specs: (handle, name, parent_handle|None) -> raw Gramps place list."""
    return [
        {
            "handle": h,
            "name": {"value": n},
            "placeref_list": ([{"ref": p}] if p else []),
        }
        for h, n, p in specs
    ]


def test_import_creates_missing_levels_with_gps_on_leaf(monkeypatch, mocker):
    monkeypatch.setenv("GENECREW_DRY_RUN", "false")
    posts = []

    def h(request):
        if request.method == "GET" and request.url.path == "/api/places/":
            page = int(request.url.params.get("page"))
            return httpx.Response(
                200, json=_existing_places(("HF", "France", None)) if page == 1 else []
            )
        if request.method == "POST" and request.url.path == "/api/places/":
            body = json.loads(request.content)
            posts.append(body)
            return httpx.Response(
                201,
                json=[
                    {
                        "type": "add",
                        "_class": "Place",
                        "handle": f"H_{body['name']['value']}",
                    }
                ],
            )
        return httpx.Response(404)

    client = _client(h)
    mocker.patch.object(write_tools, "get_client", return_value=client)
    mocker.patch.object(lieu_import, "resolve_place", return_value=_RESOLVED)

    out = run_lieu_import(client, "Bourges, Cher, France")
    assert out["action"] == "ecrire" and out["created"] is True
    assert out["chain"] == "France>Cher>Bourges"
    # France existait ; Cher puis Bourges créés, GPS/code sur la feuille seulement
    assert [p["name"]["value"] for p in posts] == ["Cher", "Bourges"]
    assert posts[1]["lat"] == "47.081" and posts[1]["code"] == "18033"
    assert "lat" not in posts[0] or not posts[0].get("lat")
    assert out["handle"] == "H_Bourges"


def test_import_existing_place_creates_nothing(monkeypatch, mocker):
    monkeypatch.setenv("GENECREW_DRY_RUN", "false")

    def h(request):
        if request.method == "GET" and request.url.path == "/api/places/":
            page = int(request.url.params.get("page"))
            return httpx.Response(
                200,
                json=_existing_places(
                    ("HF", "France", None),
                    ("HC", "Cher", "HF"),
                    ("HB", "Bourges", "HC"),
                )
                if page == 1
                else [],
            )
        if request.method == "POST":
            raise AssertionError("aucune création attendue")
        return httpx.Response(404)

    client = _client(h)
    mocker.patch.object(lieu_import, "resolve_place", return_value=_RESOLVED)
    out = run_lieu_import(client, "Bourges, Cher, France")
    assert out["existing"] is True and out["created"] is False
    assert out["handle"] == "HB"
    assert "Déjà présent" in format_lieu_import(out)


def test_import_below_threshold_writes_nothing(monkeypatch, mocker):
    monkeypatch.setenv("GENECREW_DRY_RUN", "false")
    low = _RESOLVED.model_copy(update={"score": 0.7})
    mocker.patch.object(lieu_import, "resolve_place", return_value=low)
    client = _client(lambda r: (_ for _ in ()).throw(AssertionError("aucun appel")))
    out = run_lieu_import(client, "Bourges")
    assert out["action"] == "proposition" and out["created"] is False
    assert "Aucune écriture" in format_lieu_import(out)


def test_import_dry_run_simulates(monkeypatch, mocker):
    monkeypatch.setenv("GENECREW_DRY_RUN", "true")  # coupe-circuit global

    def h(request):
        if request.method == "GET" and request.url.path == "/api/places/":
            return httpx.Response(200, json=[])
        if request.method == "POST":
            raise AssertionError("dry-run : aucun POST attendu")
        return httpx.Response(404)

    client = _client(h)
    mocker.patch.object(write_tools, "get_client", return_value=client)
    mocker.patch.object(lieu_import, "resolve_place", return_value=_RESOLVED)
    out = run_lieu_import(client, "Bourges, Cher, France")  # dry_run forcé par l'env
    assert out["created"] is True and out["dry_run"] is True
    assert str(out["handle"]).startswith("DRYRUN:")
    assert "SIMULÉ" in format_lieu_import(out)
