"""Tests de l'application des corrections de genre (write gated)."""

import json

import httpx
import pytest

from crewai_custom_tools.tools.genealogy.gramps.client import GrampsClient, GrampsConfig

from genecrew.gender_apply import render_apply_report, run_gender_apply

CONFIG = GrampsConfig(api_url="http://g.test/api", username="u", password="p")


@pytest.fixture(autouse=True)
def _no_global_dry_run(monkeypatch):
    """Tests déterministes : neutralise un GENECREW_DRY_RUN ambiant."""
    monkeypatch.delenv("GENECREW_DRY_RUN", raising=False)


PEOPLE = [
    {"handle": "h1", "gramps_id": "I0001", "gender": 2,          # inconnu -> F (écrit)
     "primary_name": {"first_name": "Suzanne", "surname_list": [{"surname": "Martin"}]}},
    {"handle": "h2", "gramps_id": "I0002", "gender": 1,          # M mais prénom F -> contradiction (écrit)
     "primary_name": {"first_name": "Marguerite", "surname_list": [{"surname": "Dupont"}]}},
    {"handle": "h3", "gramps_id": "I0003", "gender": 2,          # inconnu, ratio 0.96 < 0.98 -> sous seuil
     "primary_name": {"first_name": "Camille", "surname_list": [{"surname": "Roy"}]}},
    {"handle": "h4", "gramps_id": "I0004", "gender": 0,          # F et prénom F -> déjà correct
     "primary_name": {"first_name": "Suzanne", "surname_list": [{"surname": "Blanc"}]}},
]
TABLE = {"SUZANNE": (9990, 10), "MARGUERITE": (11988, 12), "CAMILLE": (96, 4)}


_BY_HANDLE = {p["handle"]: p for p in PEOPLE}


def _people_handler(on_put):
    def handler(request):
        path = request.url.path
        if path == "/api/token/":
            return httpx.Response(200, json={"access_token": "t"})
        if request.method == "GET" and path == "/api/people/":
            page = int(request.url.params.get("page", "1"))
            return httpx.Response(200, json=PEOPLE if page == 1 else [])
        if request.method == "GET" and path.startswith("/api/people/"):
            # GrampsUpdateGenderTool._run() reads the person before deciding to
            # write (to compare against the current gender) — serve it here too.
            person = _BY_HANDLE.get(path.rsplit("/", 1)[-1])
            return httpx.Response(200, json=person) if person else httpx.Response(404)
        if request.method == "PUT":
            return on_put(request)
        return httpx.Response(404)
    return handler


def test_run_gender_apply_writes_above_threshold(tmp_path, mocker):
    puts = []

    def on_put(request):
        puts.append(json.loads(request.content))
        return httpx.Response(200, json={})

    transport = httpx.MockTransport(_people_handler(on_put))
    client = GrampsClient(CONFIG, transport=transport)
    # run_gender_apply() builds its own GrampsUpdateGenderTool() internally, which
    # pulls its client from the module-level get_client() singleton — patch it so
    # that singleton talks to the SAME mock transport as the orchestrator client
    # (mirrors genecrew/tests/test_names.py::test_run_names_lists_incomplete_...).
    write_client = GrampsClient(CONFIG, transport=transport)
    mocker.patch(
        "crewai_custom_tools.tools.genealogy.gramps.write_tools.get_client",
        return_value=write_client,
    )
    report = run_gender_apply(client, "all", tmp_path, date="2026-07-18",
                              min_ratio=0.98, dry_run=False, table=TABLE)
    md = report.read_text(encoding="utf-8")
    written = {p["gramps_id"]: p["gender"] for p in puts}
    assert written == {"I0001": 0, "I0002": 0}      # inconnu + contradiction écrits ; pas Camille/déjà-correct
    assert "Genres écrits : 2" in md
    assert "Camille" in md                           # listé sous le seuil


def test_run_gender_apply_dry_run_writes_nothing(tmp_path, mocker):
    def on_put(request):
        raise AssertionError("aucun PUT attendu en dry-run")

    transport = httpx.MockTransport(_people_handler(on_put))
    client = GrampsClient(CONFIG, transport=transport)
    write_client = GrampsClient(CONFIG, transport=transport)
    mocker.patch(
        "crewai_custom_tools.tools.genealogy.gramps.write_tools.get_client",
        return_value=write_client,
    )
    report = run_gender_apply(client, "all", tmp_path, date="2026-07-18",
                              dry_run=True, table=TABLE)
    md = report.read_text(encoding="utf-8")
    assert "simulation" in md and "Genres écrits : 2" in md   # cibles listées, pas écrites


def test_render_apply_report_sections_and_links():
    md = render_apply_report(
        "all", "2026-07-18",
        applied=[("I0001", "Suzanne Martin", "genre_inconnu", 2, 0, 0.999, "« SUZANNE » : 99.9% F")],
        below=[("I0003", "Camille Roy", "Camille", "F", 0.96)],
        errors=[("I0009", "boom")],
        dry_run=False)
    assert "[I0001](http://localhost/person/I0001)" in md
    assert "genre_inconnu" in md and "Camille" in md and "boom" in md
