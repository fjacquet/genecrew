from crewai_custom_tools.tools.genealogy.models.domain import PersonFacts
from genecrew.names import render_names_report


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
