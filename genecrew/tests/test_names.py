import json

import httpx
import pytest

from crewai_custom_tools.tools.genealogy.gramps.client import GrampsClient, GrampsConfig
from crewai_custom_tools.tools.genealogy.models.domain import PersonFacts
from genecrew.names import render_names_report, run_names

CONFIG = GrampsConfig(api_url="http://g.test/api", username="u", password="p")


@pytest.fixture(autouse=True)
def _no_global_dry_run(monkeypatch):
    """Défaut réel = simuler ; on pose false pour que le test d'écriture e2e écrive."""
    monkeypatch.setenv("GENECREW_DRY_RUN", "false")

# Personne A : prénom incomplet (chiffre) — NE DOIT JAMAIS être écrit.
PERSON_A = {
    "gramps_id": "I0001", "handle": "hA", "gender": 0, "citation_list": [],
    "family_list": [], "parent_family_list": [], "birth_ref_index": -1, "death_ref_index": -1,
    "primary_name": {"first_name": "MARIE2", "surname_list": [{"surname": "Dupont"}]},
    "profile": {}, "event_ref_list": [], "extended": {"events": []},
}
# Personne B : nom tout capitales propre — DOIT être recasé.
PERSON_B = {
    "gramps_id": "I0002", "handle": "hB", "gender": 1, "citation_list": [],
    "family_list": [], "parent_family_list": [], "birth_ref_index": -1, "death_ref_index": -1,
    "primary_name": {"first_name": "Jean", "surname_list": [{"surname": "JACQUET"}]},
    "profile": {}, "event_ref_list": [], "extended": {"events": []},
}


def _pf(gid, given, surname):
    return PersonFacts(gramps_id=gid, handle=gid, name=f"{given} {surname}",
                       surname=surname, given=given, sex="U", has_any_citation=True)


def test_report_separates_prenom_and_nom():
    results = [{"gramps_id": "I0001", "dry_run": False, "changes": [
        {"field": "first_name", "kind": "prénom", "old": "FREDERIC", "new": "Frederic"},
        {"field": "surname[0]", "kind": "nom", "old": "JACQUET", "new": "Jacquet"}]}]
    incomplete = [("I0009", "nom", "?, Suzanne")]
    out = render_names_report("all", "2026-07-18", results, incomplete, dry_run=False)
    # la distinction prénom / nom est visible dans le rapport
    assert "prénom" in out and "nom" in out
    assert "FREDERIC" in out and "Frederic" in out
    assert "JACQUET" in out and "Jacquet" in out
    assert "I0009" in out and "?, Suzanne" in out
    assert "http://localhost/person/I0001" in out


def test_report_dry_run_marked():
    out = render_names_report("all", "2026-07-18", [], [], dry_run=True)
    assert "aperçu" in out.lower() or "dry" in out.lower()


def test_report_shows_write_errors():
    results = [{"gramps_id": "I0007", "changes": [], "dry_run": False,
                "error": "gramps_update_name_case: h7 first_name non purement de casse"}]
    out = render_names_report("all", "2026-07-18", results, [], dry_run=False)
    assert "Erreurs" in out
    assert "I0007" in out and "non purement de casse" in out


def test_report_no_errors_line():
    out = render_names_report("all", "2026-07-18", [], [], dry_run=False)
    assert "Aucune erreur" in out


def test_run_names_lists_incomplete_but_never_writes_it(tmp_path, mocker):
    """End-to-end via run_names: incomplete names are listed for review but
    never written; clean all-caps names are still recased and PUT."""
    puts = []

    def _handler(request):
        path = request.url.path
        if path == "/api/token/":
            return httpx.Response(200, json={"access_token": "t"})
        if path == "/api/people/" and request.method == "GET":
            page = int(request.url.params.get("page", 1))
            return httpx.Response(200, json=[PERSON_A, PERSON_B] if page == 1 else [])
        if path == "/api/people/hA" and request.method == "GET":
            return httpx.Response(200, json=PERSON_A)
        if path == "/api/people/hB" and request.method == "GET":
            return httpx.Response(200, json=PERSON_B)
        if request.method == "PUT":
            puts.append(json.loads(request.content))
            return httpx.Response(200, json={})
        return httpx.Response(404, json={})

    transport = httpx.MockTransport(_handler)
    client = GrampsClient(CONFIG, transport=transport)

    # run_names() builds its own GrampsUpdateNameTool() internally, which pulls
    # its client from the module-level get_client() singleton — patch it so
    # that singleton talks to the SAME mock transport as the orchestrator client.
    write_client = GrampsClient(CONFIG, transport=transport)
    mocker.patch(
        "crewai_custom_tools.tools.genealogy.gramps.write_tools.get_client",
        return_value=write_client,
    )

    report_path, incomplete_path = run_names(
        client, "all", tmp_path, date="2026-07-18", dry_run=False)

    # 1) l'incomplet est listé pour vérification humaine ...
    incomplete_text = incomplete_path.read_text(encoding="utf-8")
    assert "MARIE2" in incomplete_text

    # 2) ... mais AUCUN PUT ne l'écrit jamais (la garantie critique).
    assert puts, "expected at least one PUT (for the clean surname)"
    for body in puts:
        dumped = json.dumps(body)
        assert "Marie2" not in dumped
        assert "MARIE2" not in dumped

    # 3) le nom propre en capitales EST bien recasé et écrit.
    assert any(
        (body.get("primary_name", {}).get("surname_list") or [{}])[0].get("surname")
        == "Jacquet"
        for body in puts
    )

    # 4) le rapport de changements montre la correction et aucune erreur.
    report_text = report_path.read_text(encoding="utf-8")
    assert "JACQUET" in report_text and "Jacquet" in report_text
    assert "Aucune erreur" in report_text
