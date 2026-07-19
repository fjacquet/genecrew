import httpx
from crewai_custom_tools.tools.genealogy.gramps.client import GrampsClient, GrampsConfig
from crewai_custom_tools.tools.genealogy.models.domain import (
    DatedChain, PlaceLevel, ResolvedPlace,
)
from genecrew import places
from genecrew.places import render_places_report, run_places

CONFIG = GrampsConfig(api_url="http://g.test/api", username="u", password="p")
PLACES = [{"handle": "h1", "gramps_id": "P0001",
           "name": {"value": ", , Bourges, 18033, 18000, Cher, Centre-Val de Loire, France"},
           "place_type": "Unknown"}]


def _handler(request):
    if request.url.path == "/api/token/":
        return httpx.Response(200, json={"access_token": "t"})
    if request.method != "GET":
        return httpx.Response(405)          # read-only: no write must ever reach here
    if request.url.path == "/api/places/":
        page = int(request.url.params.get("page", "1"))
        return httpx.Response(200, json=PLACES if page == 1 else [])
    return httpx.Response(404)


def _authoritative(parsed):
    return ResolvedPlace(name="Bourges", place_type="Municipality", lat="47.081", long="2.399",
                         code="18033",
                         chains=[DatedChain(levels=[PlaceLevel(name="France", place_type="Country")])],
                         score=1.0, source="geo.api.gouv.fr", query="/communes/18033")


def test_run_places_readonly_writes_reports_no_http_write(tmp_path, monkeypatch, mocker):
    monkeypatch.setattr(places, "resolve_place", _authoritative)     # pas de réseau
    client = GrampsClient(CONFIG, transport=httpx.MockTransport(_handler))
    report, yaml_path = run_places(client, "all", tmp_path, date="2026-07-19")
    md = report.read_text(encoding="utf-8")
    assert "Bourges" in md and "geo.api.gouv.fr" in md
    assert "ecrire" in md                       # action calculée mais RIEN écrit (lecture seule)
    assert yaml_path.exists()


def _boom(parsed):
    # Un géocodeur qui échoue (503, timeout…) sur un lieu ne doit pas faire tomber tout le run.
    raise httpx.HTTPStatusError(
        "503", request=httpx.Request("GET", "http://x"), response=httpx.Response(503))


def test_build_proposition_resolver_http_error_is_indecidable(monkeypatch):
    monkeypatch.setattr(places, "resolve_place", _boom)
    prop = places.build_proposition(
        {"handle": "h", "gramps_id": "P9", "name": {"value": "Murten/Morat"}}, 0.90)
    assert prop.action == "indecidable"
    assert prop.resolution is None
    assert "erreur" in prop.preuve.lower()      # l'erreur est remontée dans la preuve


def test_run_places_continues_past_resolver_http_error(tmp_path, monkeypatch):
    monkeypatch.setattr(places, "resolve_place", _boom)
    client = GrampsClient(CONFIG, transport=httpx.MockTransport(_handler))
    report, yaml_path = run_places(client, "all", tmp_path, date="2026-07-19")
    md = report.read_text(encoding="utf-8")
    assert "P0001" in md and "indecidable" in md    # le run se termine, le lieu est indécidable


def test_run_places_indecidable_when_unresolved(tmp_path, monkeypatch):
    # resolve_place renvoie None -> proposition indécidable, sans lever, rendue avec placeholders
    monkeypatch.setattr(places, "resolve_place", lambda parsed: None)
    client = GrampsClient(CONFIG, transport=httpx.MockTransport(_handler))
    report, yaml_path = run_places(client, "all", tmp_path, date="2026-07-19")
    md = report.read_text(encoding="utf-8")
    assert "indecidable" in md
    # le YAML porte bien une proposition de type lieu_indecidable, resolution nulle
    import yaml as _yaml
    props = _yaml.safe_load(yaml_path.read_text(encoding="utf-8"))
    assert props and props[0]["type"] == "lieu_indecidable" and props[0]["resolution"] is None


def test_render_places_report_has_links_and_sections():
    from crewai_custom_tools.tools.genealogy.models.domain import PlaceProposition
    md = render_places_report("all", "2026-07-19", [PlaceProposition(
        type="lieu_resolu", gramps_id="P0001", handle="h1", original="…", country="France",
        resolution=_authoritative(None), action="ecrire", confiance="haute",
        priorite="haute", preuve="geo.api.gouv.fr | /communes/18033 | score 1.000")])
    assert "[P0001](http://localhost/place/P0001)" in md and "ecrire" in md
