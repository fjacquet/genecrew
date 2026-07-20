from crewai_custom_tools.tools.genealogy.models.domain import EventFact, PersonFacts

from genecrew.archives import collecter_pistes


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
