"""Offline tests for the deterministic MatchID death enrichment (zero LLM, no network)."""

import yaml
from crewai_custom_tools.tools.genealogy.models.domain import EventFact, PersonFacts

import pytest

from genecrew import deces
from genecrew.deces import (
    build_deces_proposition,
    event_iso,
    first_given,
    is_candidate,
    run_deces,
)

TODAY = 2026


@pytest.fixture(autouse=True)
def _no_throttle(monkeypatch):
    monkeypatch.setattr(deces, "THROTTLE_S", 0)


def test_first_given_strips_tree_commas():
    assert first_given("Paul, Marcel, Andre") == "Paul"        # MatchID 422 sur "Paul,"
    assert first_given("Odette") == "Odette"
    assert first_given("") == ""


def _person(gid, handle, given, surname, birth=None, death=None):
    return PersonFacts(gramps_id=gid, handle=handle, name=f"{given} {surname}",
                       surname=surname, given=given, sex="F", birth=birth, death=death)


def _event(kind, year, day=0, month=0, cited=False):
    return EventFact(type=kind, year=year, sortval=year * 400,
                     dateval=[day, month, year, False], has_citation=cited)


ODETTE_MATCH = {
    "id": "PpcgyN6TffIa",
    "source": "2021",
    "sourceLine": 610579,
    "name": {"first": ["Odette", "Henriette"], "last": "Rippert"},
    "birth": {"date": "19220929", "location": {"city": "Constantine"}},
    "death": {"date": "20211219", "certificateId": "1511",
              "location": {"city": "Bourges"}},
}


# --- sélection et dates (pur) ---

def test_event_iso_full_year_and_missing():
    assert event_iso(_event("Birth", 1922, 29, 9)) == "1922-09-29"
    assert event_iso(_event("Birth", 1922)) == "1922"
    assert event_iso(None) == ""


def test_candidate_selection():
    ok_no_death = _person("I1", "h1", "Odette", "Rippert", birth=_event("Birth", 1922))
    unsourced = _person("I2", "h2", "A", "B", birth=_event("Birth", 1950),
                        death=_event("Death", 2000))
    sourced = _person("I3", "h3", "A", "B", birth=_event("Birth", 1950),
                      death=_event("Death", 2000, cited=True))
    too_old = _person("I4", "h4", "A", "B", birth=_event("Birth", 1700))
    no_birth = _person("I5", "h5", "A", "B")
    assert is_candidate(ok_no_death, today_year=TODAY) is True
    assert is_candidate(unsourced, today_year=TODAY) is True     # décès non sourcé
    assert is_candidate(sourced, today_year=TODAY) is False      # déjà sourcé
    assert is_candidate(too_old, today_year=TODAY) is False      # < 1850
    assert is_candidate(no_birth, today_year=TODAY) is False


# --- les trois issues (pur) ---

def test_proposition_date_porte_la_donnee_machine():
    """La date et la commune sortent en champs typés, pas seulement dans la phrase."""
    from crewai_custom_tools.tools.genealogy.models.domain import PersonFacts

    from genecrew.deces import build_deces_proposition

    person = PersonFacts(gramps_id="I0174", handle="H174", name="Alain Rolland",
                         surname="Rolland", given="Alain", sex="M")
    match = {"id": "0gGveHZwLxLg",
             "death": {"date": "20211223", "certificateId": "12",
                       "location": {"city": "Saint-Palais"}},
             "source": "2021", "sourceLine": "610579"}

    prop = build_deces_proposition(person, match, 1.0, exact_birth=True)

    assert prop.type == "date"
    assert prop.date_iso == "2021-12-23"
    assert prop.lieu_nom == "Saint-Palais"


def test_missing_death_proposes_completion():
    p = _person("I0300", "h300", "Odette", "Rippert", birth=_event("Birth", 1922, 29, 9))
    prop = build_deces_proposition(p, ODETTE_MATCH, 1.0, exact_birth=True)
    assert prop.type == "date" and prop.confiance == 2
    assert "2021-12-19" in prop.action and "Bourges" in prop.action
    assert prop.preuve_url == "https://deces.matchid.io/id/PpcgyN6TffIa"
    # référence d'archive complète, rejouable sans MatchID
    assert "acte 1511" in prop.preuve_detail
    assert "fichier INSEE 2021" in prop.preuve_detail
    assert "ligne 610579" in prop.preuve_detail


def test_unsourced_concordant_death_proposes_source():
    p = _person("I0300", "h300", "Odette", "Rippert",
                birth=_event("Birth", 1922, 29, 9),
                death=_event("Death", 2021, 19, 12))
    prop = build_deces_proposition(p, ODETTE_MATCH, 1.0, exact_birth=True)
    assert prop.type == "source" and prop.priorite == "basse"
    assert "les dates concordent" in prop.action


def test_divergent_death_flags_contradiction():
    p = _person("I0300", "h300", "Odette", "Rippert",
                birth=_event("Birth", 1922, 29, 9),
                death=_event("Death", 2019, 1, 1))
    prop = build_deces_proposition(p, ODETTE_MATCH, 1.0, exact_birth=True)
    assert prop.type == "date" and prop.priorite == "haute" and prop.confiance == 1
    assert "2019-01-01" in prop.action and "2021-12-19" in prop.action


# --- anti-homonymes (retour terrain: Paul/Monique/Michel VIVANTS proposés décédés) ---

PAUL_HOMONYME = {                                  # même nom + même ANNÉE, autre personne
    "id": "xxHOMONYME",
    "name": {"first": ["Paul"], "last": "Jacquet"},
    "birth": {"date": "19450312"},
    "death": {"date": "19920907", "location": {"city": "Varces"}},
}


def test_year_only_match_never_proposes_a_death(tmp_path, monkeypatch):
    # Paul est VIVANT: arbre = année seule (1945), l'INSEE a un homonyme né en 1945.
    paul = _person("I0161", "h161", "Paul, Marcel", "Jacquet",
                   birth=_event("Birth", 1945))               # année seule
    monkeypatch.setattr(deces, "iter_people_batches", lambda *a, **k: iter([[paul]]))
    monkeypatch.setattr(deces, "search_deces", lambda *a, **k: [PAUL_HOMONYME])
    _, proposals = run_deces(client=None, scope="all", output_dir=tmp_path,
                             date="2026-07-19")
    assert yaml.safe_load(proposals.read_text())["propositions"] == []


def test_divergent_death_with_year_only_birth_is_dropped_not_contradiction(tmp_path, monkeypatch):
    # Roger: arbre décès 1961, homonyme INSEE mort 1987 — naissance année seule ->
    # c'est un homonyme, pas une contradiction de l'arbre.
    roger = _person("I0165", "h165", "Roger", "Jacquet",
                    birth=_event("Birth", 1920), death=_event("Death", 1961, 29, 9))
    insee = {"name": {"first": ["Roger"], "last": "Jacquet"},
             "birth": {"date": "19200504"}, "death": {"date": "19870908"}}
    monkeypatch.setattr(deces, "iter_people_batches", lambda *a, **k: iter([[roger]]))
    monkeypatch.setattr(deces, "search_deces", lambda *a, **k: [insee])
    _, proposals = run_deces(client=None, scope="all", output_dir=tmp_path,
                             date="2026-07-19")
    assert yaml.safe_load(proposals.read_text())["propositions"] == []


def test_exact_death_date_rescues_source_mode(tmp_path, monkeypatch):
    # Odette: naissance arbre 1922-10-02 vs INSEE 1922-09-29 (année seule -> 0.85),
    # MAIS décès complet identique (2021-12-19) -> repêchée en mode source, confiance 2.
    odette = _person("I0300", "h300", "Odette", "Rippert",
                     birth=_event("Birth", 1922, 2, 10),
                     death=_event("Death", 2021, 19, 12))
    monkeypatch.setattr(deces, "iter_people_batches", lambda *a, **k: iter([[odette]]))
    monkeypatch.setattr(deces, "search_deces", lambda *a, **k: [ODETTE_MATCH])
    _, proposals = run_deces(client=None, scope="all", output_dir=tmp_path,
                             date="2026-07-19")
    props = yaml.safe_load(proposals.read_text())["propositions"]
    assert len(props) == 1
    assert props[0]["type"] == "source" and props[0]["confiance"] == 2


def test_two_close_candidates_are_ambiguous_and_skipped(tmp_path, monkeypatch):
    p = _person("I1", "h1", "Jean", "Jacquet", birth=_event("Birth", 1930, 1, 1))
    twin_a = {"name": {"first": ["Jean"], "last": "Jacquet"},
              "birth": {"date": "19300101"}, "death": {"date": "19990101"}}
    twin_b = {"name": {"first": ["Jean"], "last": "Jacquet"},
              "birth": {"date": "19300101"}, "death": {"date": "20050101"}}
    monkeypatch.setattr(deces, "iter_people_batches", lambda *a, **k: iter([[p]]))
    monkeypatch.setattr(deces, "search_deces", lambda *a, **k: [twin_a, twin_b])
    _, proposals = run_deces(client=None, scope="all", output_dir=tmp_path,
                             date="2026-07-19")
    assert yaml.safe_load(proposals.read_text())["propositions"] == []


# --- backoff quota MatchID ---

class _Quota(Exception):
    def __init__(self, status):
        self.response = type("R", (), {"status_code": status})()


def test_backoff_retries_on_quota_then_succeeds(monkeypatch):
    monkeypatch.setattr(deces, "BACKOFF_S", (0, 0, 0))
    calls = {"n": 0}

    def fake(last_name, **kw):
        calls["n"] += 1
        if calls["n"] < 3:
            raise _Quota(422)                                  # seau vide 2 fois
        return [ODETTE_MATCH]
    monkeypatch.setattr(deces, "search_deces", fake)
    out = deces._search_with_backoff("Rippert", "Odette", "1922")
    assert out == [ODETTE_MATCH] and calls["n"] == 3


def test_backoff_raises_immediately_on_other_errors(monkeypatch):
    monkeypatch.setattr(deces, "BACKOFF_S", (0, 0, 0))

    def fake(last_name, **kw):
        raise _Quota(500)                                      # pas un quota
    monkeypatch.setattr(deces, "search_deces", fake)
    import pytest as _pytest
    with _pytest.raises(_Quota):
        deces._search_with_backoff("Rippert", "Odette", "1922")


# --- orchestration (offline) ---

def test_run_deces_queries_candidates_scores_and_writes_yaml(tmp_path, monkeypatch):
    odette = _person("I0300", "h300", "Odette, Henriette", "Rippert",
                     birth=_event("Birth", 1922, 29, 9))
    ancien = _person("I0010", "h10", "Claude", "Villaudy", birth=_event("Birth", 1703))
    monkeypatch.setattr(deces, "iter_people_batches",
                        lambda *a, **k: iter([[odette, ancien]]))
    calls = []

    def fake_search(last_name, first_name="", birth_date="", limit=10, **kw):
        calls.append((last_name, first_name, birth_date))
        return [ODETTE_MATCH]
    monkeypatch.setattr(deces, "search_deces", fake_search)

    report, proposals = run_deces(client=None, scope="all", output_dir=tmp_path,
                                  date="2026-07-19")
    # seul Odette est candidate (Claude 1703 < 1850) ; requête = nom + prénom + année
    assert calls == [("Rippert", "Odette", "1922")]
    data = yaml.safe_load(proposals.read_text(encoding="utf-8"))
    assert len(data["propositions"]) == 1
    assert data["propositions"][0]["gramps_id"] == "I0300"
    md = report.read_text(encoding="utf-8")
    assert "Candidates" in md and "Propositions : 1" in md


def test_run_deces_below_threshold_and_api_error_are_silent(tmp_path, monkeypatch):
    p1 = _person("I1", "h1", "Zoe", "Autre", birth=_event("Birth", 1900))
    p2 = _person("I2", "h2", "Ana", "Casse", birth=_event("Birth", 1901))
    monkeypatch.setattr(deces, "iter_people_batches", lambda *a, **k: iter([[p1, p2]]))

    def fake_search(last_name, **kw):
        if last_name == "Casse":
            raise RuntimeError("API down")
        return [ODETTE_MATCH]                                  # score 0 pour Zoe Autre
    monkeypatch.setattr(deces, "search_deces", fake_search)

    report, proposals = run_deces(client=None, scope="all", output_dir=tmp_path,
                                  date="2026-07-19")
    data = yaml.safe_load(proposals.read_text(encoding="utf-8"))
    assert data["propositions"] == []                          # rien: éliminé + erreur
    assert "erreurs API : 1" in report.read_text(encoding="utf-8")
