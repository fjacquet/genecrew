import httpx

from genecrew.facts import FactsFetcher, person_from_json, family_from_json
from crewai_custom_tools.tools.genealogy.gramps.client import GrampsClient, GrampsConfig

CONFIG = GrampsConfig(api_url="http://g.test/api", username="u", password="p")

PERSON_RAW = {
    "gramps_id": "I0001", "handle": "h1", "gender": 1,
    "citation_list": ["c1"], "family_list": ["f1"], "parent_family_list": ["pf1"],
    "birth_ref_index": 0, "death_ref_index": 1,
    "primary_name": {"first_name": "Jean", "surname_list": [{"surname": "Dupont"}]},
    "profile": {"birth": {"date": "1712", "citations": 1},
                "death": {"date": "1786", "citations": 0}},
    "event_ref_list": [{"ref": "e1"}, {"ref": "e2"}],
    "extended": {"events": [
        {"type": "Birth", "citation_list": ["c1"],
         "date": {"sortval": 2346578, "year": 1712, "dateval": [11, 8, 1712, False],
                  "modifier": 0, "quality": 0}},
        {"type": "Death", "citation_list": [],
         "date": {"sortval": 2373544, "year": 1786, "dateval": [0, 0, 1786, False],
                  "modifier": 0, "quality": 0}},
    ]},
}


def test_person_from_json_maps_vitals_and_sex():
    p = person_from_json(PERSON_RAW)
    assert p.gramps_id == "I0001" and p.sex == "M"
    assert p.given == "Jean" and p.surname == "Dupont"
    assert p.birth.sortval == 2346578 and p.birth.year == 1712
    assert p.death.year == 1786
    assert p.has_any_citation is True          # person citation_list non vide
    assert p.parent_family_handles == ["pf1"] and p.family_handles == ["f1"]
    assert len(p.events) == 2


def test_person_without_any_citation():
    raw = {**PERSON_RAW, "citation_list": [],
           "profile": {"birth": {"date": "1712", "citations": 0}, "death": {}},
           "extended": {"events": [
               {"type": "Birth", "citation_list": [],
                "date": {"sortval": 2346578, "year": 1712, "dateval": [], "modifier": 0, "quality": 0}}]},
           "birth_ref_index": 0, "death_ref_index": -1,
           "event_ref_list": [{"ref": "e1"}]}
    p = person_from_json(raw)
    assert p.has_any_citation is False and p.death is None


def test_family_from_json():
    raw = {"gramps_id": "F0001", "handle": "f1",
           "father_handle": "hp", "mother_handle": "hm",
           "child_ref_list": [{"ref": "hc1"}, {"ref": "hc2"}],
           "extended": {"events": [
               {"type": "Marriage",
                "date": {"sortval": 2350000, "year": 1740, "dateval": [], "modifier": 0, "quality": 0}}]}}
    f = family_from_json(raw)
    assert f.father_handle == "hp" and f.mother_handle == "hm"
    assert f.child_handles == ["hc1", "hc2"] and f.marriage.year == 1740


def test_get_person_facts_is_cached():
    calls = {"n": 0}

    def handler(request):
        if request.url.path == "/api/token/":
            return httpx.Response(200, json={"access_token": "t"})
        calls["n"] += 1
        return httpx.Response(200, json=PERSON_RAW)

    client = GrampsClient(CONFIG, transport=httpx.MockTransport(handler))
    fetcher = FactsFetcher(client)
    a = fetcher.get_person_facts("h1")
    b = fetcher.get_person_facts("h1")
    assert a.gramps_id == b.gramps_id == "I0001"
    assert calls["n"] == 1                       # deuxième appel servi par le cache


def test_get_person_facts_returns_none_on_404():
    def handler(request):
        if request.url.path == "/api/token/":
            return httpx.Response(200, json={"access_token": "t"})
        return httpx.Response(404)

    client = GrampsClient(CONFIG, transport=httpx.MockTransport(handler))
    fetcher = FactsFetcher(client)
    assert fetcher.get_person_facts("nope") is None


def test_get_family_facts_returns_none_on_404():
    def handler(request):
        if request.url.path == "/api/token/":
            return httpx.Response(200, json={"access_token": "t"})
        return httpx.Response(404)

    client = GrampsClient(CONFIG, transport=httpx.MockTransport(handler))
    fetcher = FactsFetcher(client)
    assert fetcher.get_family_facts("nope") is None
