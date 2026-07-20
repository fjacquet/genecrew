import httpx
import pytest

from crewai_custom_tools.tools.genealogy.gramps.client import GrampsClient, GrampsConfig
from crewai_custom_tools.tools.genealogy.models.domain import EventFact, PersonFacts

from genecrew import archives
from genecrew.archives import collecter_pistes, run_archives

CONFIG = GrampsConfig(api_url="http://g.test/api", username="u", password="p")


@pytest.fixture(autouse=True)
def _no_throttle(monkeypatch):
    monkeypatch.setattr(archives, "THROTTLE_S", 0)


def _raw_person(gid: str, handle: str, given: str = "Jean", surname: str = "Dupont") -> dict:
    return {
        "gramps_id": gid, "handle": handle, "gender": 1, "citation_list": [],
        "family_list": [], "parent_family_list": [], "birth_ref_index": -1,
        "death_ref_index": -1,
        "primary_name": {"first_name": given, "surname_list": [{"surname": surname}]},
        "profile": {}, "event_ref_list": [], "extended": {"events": []},
    }


def _person():
    birth = EventFact(type="Birth", year=1900, dateval=[14, 7, 1900, False],
                      place_name="Montbéliard", place="Montbéliard, Doubs, France")
    return PersonFacts(gramps_id="I0042", handle="H42", name="Jean Dupont",
                       surname="Dupont", given="Jean", sex="M", birth=birth)


def test_collecter_wikidata_traduit_les_lignes_sparql(mocker):
    mocker.patch("genecrew.archives.sparql_rows", return_value=[
        {"item": "http://www.wikidata.org/entity/Q42", "itemLabel": "Jean Dupont",
         "birthDate": "1900-07-14T00:00:00Z", "birthPlaceLabel": "Montbéliard"}])
    pistes = collecter_pistes("wikidata", _person())
    assert len(pistes) == 1 and pistes[0].source == "wikidata"
    assert pistes[0].force == "forte"


def test_gallica_n_est_pas_une_source_exposee():
    """Livrée dans la bibliothèque mais pas branchée : son SRU rend des notices
    de collection, pas des articles. Voir docs/BACKLOG.md."""
    import pytest
    with pytest.raises(ValueError, match="source inconnue"):
        collecter_pistes("gallica", _person())


def test_source_inconnue_leve():
    import pytest
    with pytest.raises(ValueError, match="source inconnue"):
        collecter_pistes("scriptorium", _person())


# --- orchestration (offline, transport HTTP simulé) ---

def test_run_archives_scope_person_interroge_la_source_une_seule_fois(tmp_path, mocker):
    """Verrou du défaut Critique : `--scope person:<ID>` ne doit toucher QU'UNE
    personne, pas tout l'arbre. La pagination « all » ci-dessous répond avec DEUX
    autres personnes : si `run_archives` ignore le scope et retombe sur elle, la
    source serait interrogée pour I0001/I0002 au lieu du seul I0042 demandé."""
    appels: list[str] = []

    def fake_collecter(source, person):
        appels.append(person.gramps_id)
        return []
    mocker.patch("genecrew.archives.collecter_pistes", side_effect=fake_collecter)

    def handler(request):
        if request.url.path == "/api/token/":
            return httpx.Response(200, json={"access_token": "t"})
        params = request.url.params
        if request.url.path == "/api/people/H42":
            return httpx.Response(200, json=_raw_person("I0042", "H42"))
        if "gramps_id" in params:
            assert params["gramps_id"] == "I0042"
            return httpx.Response(200, json=[_raw_person("I0042", "H42")])
        # Pagination « all » : n'importe quelle personne ici prouve que le scope
        # a été ignoré.
        page = int(params.get("page", 1))
        if page == 1:
            return httpx.Response(
                200, json=[_raw_person("I0001", "H1"), _raw_person("I0002", "H2")])
        return httpx.Response(200, json=[])

    client = GrampsClient(CONFIG, transport=httpx.MockTransport(handler))
    run_archives(client, "wikidata", "person:I0042", tmp_path, date="2026-07-20",
                dry_run=True)
    assert appels == ["I0042"]


def test_run_archives_erreur_sur_une_personne_ninterrompt_pas_le_parcours(tmp_path, mocker):
    appels: list[str] = []

    def fake_collecter(source, person):
        appels.append(person.gramps_id)
        if person.gramps_id == "I0001":
            raise RuntimeError("wikidata indisponible")
        return []
    mocker.patch("genecrew.archives.collecter_pistes", side_effect=fake_collecter)

    def handler(request):
        if request.url.path == "/api/token/":
            return httpx.Response(200, json={"access_token": "t"})
        page = int(request.url.params.get("page", 1))
        if page == 1:
            return httpx.Response(
                200, json=[_raw_person("I0001", "H1"), _raw_person("I0002", "H2")])
        return httpx.Response(200, json=[])

    client = GrampsClient(CONFIG, transport=httpx.MockTransport(handler))
    chemin = run_archives(client, "wikidata", "all", tmp_path, date="2026-07-20",
                          dry_run=True)
    # les deux personnes sont vues malgré l'échec sur la première
    assert appels == ["I0001", "I0002"]
    assert chemin.exists()
