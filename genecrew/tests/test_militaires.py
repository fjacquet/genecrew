"""Offline tests for the military-death enrichment orchestration."""

import yaml
from crewai_custom_tools.tools.genealogy.models.domain import EventFact, PersonFacts

from genecrew import militaires
from genecrew.militaires import run_militaires

SYLVAIN_ROW = {
    "base": "Guerre 1914-1918", "nom": "VILLAUDY", "prenom": "Sylvain",
    "naissance_date": "1895-11-11", "naissance_lieu": "Paris 20e",
    "naissance_departement": "Seine", "naissance_pays": "France",
    "deces_date": "1915-09-28", "deces_lieu": "Neuville-Saint-Vaast",
    "deces_pays": "France", "unite": "156e RI", "reference": "cl.1915",
    "lien_ark": "https://www.memoiredeshommes.sga.defense.gouv.fr/ark/xyz",
}


def _person(gid, given, surname, birth=None, death=None):
    return PersonFacts(gramps_id=gid, handle=f"h{gid}", name=f"{given} {surname}",
                       surname=surname, given=given, sex="M", birth=birth, death=death)


def _event(kind, year, day=0, month=0, cited=False):
    return EventFact(type=kind, year=year, sortval=year * 400,
                     dateval=[day, month, year, False], has_citation=cited)


def test_proposition_date_militaire_porte_la_donnee_machine():
    """Mémoire des hommes hérite du même contrat que l'INSEE : date et commune typées."""
    from crewai_custom_tools.tools.genealogy.models.domain import PersonFacts

    from genecrew.militaires import build_militaire_proposition

    person = PersonFacts(gramps_id="I0500", handle="H500", name="Jean Dupont",
                         surname="Dupont", given="Jean", sex="M")
    row = {"deces_date": "1916-05-12", "deces_lieu": "Verdun",
           "base": "Morts pour la France 1914-1918", "unite": "42e RI",
           "reference": "1916/123", "lien_ark": "https://ark.example/x"}

    prop = build_militaire_proposition(person, row, 1.0, exact_birth=True)

    assert prop.type == "date"
    assert prop.date_iso == "1916-05-12"
    assert prop.lieu_nom == "Verdun"


def test_run_militaires_full_birth_match_proposes_with_ark(tmp_path, monkeypatch):
    sylvain = _person("I0500", "Sylvain", "Villaudy",
                      birth=_event("Birth", 1895, 11, 11))     # décès absent
    monkeypatch.setattr(militaires, "iter_people_batches",
                        lambda *a, **k: iter([[sylvain]]))
    monkeypatch.setattr(militaires, "match_militaires",
                        lambda *a, **k: [(SYLVAIN_ROW, 1.0)])
    report, proposals = run_militaires(client=None, scope="all", output_dir=tmp_path,
                                       date="2026-07-19")
    props = yaml.safe_load(proposals.read_text(encoding="utf-8"))["propositions"]
    assert len(props) == 1
    p = props[0]
    assert p["type"] == "date" and p["confiance"] == 2         # naissance exacte + ark
    assert "1915-09-28" in p["action"] and "Guerre 1914-1918" in p["action"]
    assert p["preuve_url"].endswith("/ark/xyz")
    assert "156e RI" in p["preuve_detail"]
    assert "Propositions : 1" in report.read_text(encoding="utf-8")


def test_run_militaires_year_only_and_ambiguous_are_dropped(tmp_path, monkeypatch):
    year_only = _person("I1", "Jean", "Jacquet", birth=_event("Birth", 1890))
    ambiguous = _person("I2", "Louis", "Clavier", birth=_event("Birth", 1892, 3, 4))
    monkeypatch.setattr(militaires, "iter_people_batches",
                        lambda *a, **k: iter([[year_only, ambiguous]]))

    def fake_match(surname, given, birth_iso, **kw):
        if surname == "Jacquet":
            return [({**SYLVAIN_ROW, "nom": "JACQUET"}, 0.85)]  # année seule: sous seuil
        return [({**SYLVAIN_ROW, "nom": "CLAVIER"}, 0.96),
                ({**SYLVAIN_ROW, "nom": "CLAVIER", "prenom": "Louis A."}, 0.93)]
    monkeypatch.setattr(militaires, "match_militaires", fake_match)
    _, proposals = run_militaires(client=None, scope="all", output_dir=tmp_path,
                                  date="2026-07-19")
    assert yaml.safe_load(proposals.read_text())["propositions"] == []


def test_run_militaires_exact_death_rescues_source_mode(tmp_path, monkeypatch):
    p = _person("I3", "Sylvain", "Villaudy",
                birth=_event("Birth", 1895),                   # année seule -> 0.85
                death=_event("Death", 1915, 28, 9))            # décès exact concordant
    monkeypatch.setattr(militaires, "iter_people_batches", lambda *a, **k: iter([[p]]))
    monkeypatch.setattr(militaires, "match_militaires",
                        lambda *a, **k: [(SYLVAIN_ROW, 0.85)])
    _, proposals = run_militaires(client=None, scope="all", output_dir=tmp_path,
                                  date="2026-07-19")
    props = yaml.safe_load(proposals.read_text())["propositions"]
    assert len(props) == 1 and props[0]["type"] == "source"
