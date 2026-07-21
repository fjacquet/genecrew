"""Tests offline de `apply deaths` — création d'événements décès sourcés."""

import httpx
import pytest
from crewai_custom_tools.tools.genealogy.gramps.client import GrampsClient, GrampsConfig

from genecrew.deces_event import (
    index_lieux,
    normaliser_lieu,
    render_deaths_report,
    resoudre_lieu,
    trier_propositions,
)

CONFIG = GrampsConfig(api_url="http://g.test/api", username="u", password="p")


@pytest.fixture(autouse=True)
def _real_writes(monkeypatch):
    monkeypatch.setenv("GENECREW_DRY_RUN", "false")


def _client(handler):
    def _h(request):
        if request.url.path == "/api/token/":
            return httpx.Response(200, json={"access_token": "t"})
        return handler(request)
    return GrampsClient(CONFIG, transport=httpx.MockTransport(_h))


def _places_client(places):
    def _h(request):
        if request.url.path == "/api/places/":
            page = int(request.url.params.get("page", 1))
            return httpx.Response(200, json=places if page == 1 else [])
        return httpx.Response(404, json={})
    return _client(_h)


def test_normalisation_ignore_casse_accents_et_separateurs():
    assert normaliser_lieu("Saint-Palais") == normaliser_lieu("SAINT PALAIS")
    assert normaliser_lieu("Nohant-en-Goût") == normaliser_lieu("nohant en gout")


def test_index_rend_le_handle_d_un_lieu_unique():
    client = _places_client([
        {"handle": "P1", "name": {"value": "Bourges"}},
        {"handle": "P2", "name": {"value": "Vierzon"}},
    ])
    index = index_lieux(client)
    assert resoudre_lieu(index, "bourges") == "P1"


def test_lieu_absent_rend_none():
    client = _places_client([{"handle": "P1", "name": {"value": "Bourges"}}])
    index = index_lieux(client)
    assert resoudre_lieu(index, "Saint-Palais") is None


def test_homonymes_rendent_none_plutot_qu_un_choix():
    """Deux lieux du même nom : rattacher au hasard poserait un décès dans la
    mauvaise commune sans que rien ne le signale."""
    client = _places_client([
        {"handle": "P1", "name": {"value": "Saint-Palais"}},
        {"handle": "P2", "name": {"value": "Saint-Palais"}},
    ])
    index = index_lieux(client)
    assert "saint palais" in index          # connu…
    assert resoudre_lieu(index, "Saint-Palais") is None   # …mais pas résolu


def test_lieu_sans_nom_est_ignore():
    client = _places_client([
        {"handle": "P1", "name": {}},
        {"handle": "P2", "name": {"value": "Bourges"}},
    ])
    index = index_lieux(client)
    assert resoudre_lieu(index, "Bourges") == "P2"


def test_normalisation_ignore_apostrophe_typographique():
    """« L'Isle-Adam » (apostrophe ASCII) et « L’Isle-Adam » (apostrophe
    typographique U+2019, usage courant en copier-coller) doivent produire la
    même clé — sinon la commune n'est jamais reconnue, sans que rien ne le
    signale."""
    assert normaliser_lieu("L'Isle-Adam") == normaliser_lieu("L’Isle-Adam")


def test_normalisation_deplie_la_ligature_oe():
    """« Vœuil-et-Giget » (commune de Charente) et « Voeuil-et-Giget »
    désignent la même commune ; NFD décompose les accents mais pas les
    ligatures, donc sans dépliage explicite les deux clés diffèrent."""
    assert normaliser_lieu("Vœuil-et-Giget") == normaliser_lieu("Voeuil-et-Giget")


def test_trois_homonymes_rendent_toujours_none():
    """Verrou de non-régression : au-delà de deux occurrences du même nom, la
    résolution doit rester None. Le code actuel teste la présence de la clé
    (pas sa valeur), donc il est déjà correct à trois — mais rien ne l'exerçait
    avant ce test ; une réécriture par compteur pourrait « ressusciter » un
    handle à la troisième occurrence sans que la CI ne le voie."""
    client = _places_client([
        {"handle": "P1", "name": {"value": "Saint-Palais"}},
        {"handle": "P2", "name": {"value": "Saint-Palais"}},
        {"handle": "P3", "name": {"value": "Saint-Palais"}},
    ])
    index = index_lieux(client)
    assert "saint palais" in index
    assert resoudre_lieu(index, "Saint-Palais") is None


def _prop(**kw):
    base = {
        "type": "date", "gramps_id": "I0174", "handle": "H174",
        "personne": "Alain Rolland", "cible": "décès de I0174 (absent de l'arbre)",
        "action": "Renseigner le décès : 2021-12-23 à Saint-Palais.",
        "preuve_url": "https://deces.matchid.io/id/X",
        "preuve_detail": "Fichier des décès INSEE : 2021-12-23 à Saint-Palais "
                         "(score 1.000).",
        "priorite": "moyenne", "confiance": 2,
        "date_iso": "2021-12-23", "lieu_nom": "Saint-Palais",
    }
    base.update(kw)
    from crewai_custom_tools.tools.genealogy.models.domain import PropositionAudit
    return PropositionAudit(**base)


def test_retient_une_proposition_date_confiance_2_datee():
    retenues, motifs = trier_propositions([_prop()])
    assert len(retenues) == 1
    assert motifs == {"hors_perimetre": 0, "sans_donnee": 0}


def test_ecarte_le_type_source():
    """`type: source` est le métier de `apply citations`, pas de `apply deaths`."""
    retenues, motifs = trier_propositions([_prop(type="source")])
    assert retenues == []
    assert motifs["hors_perimetre"] == 1


def test_ecarte_la_confiance_1():
    """Confiance 1 = date de naissance non concordante : homonyme possible."""
    retenues, motifs = trier_propositions([_prop(confiance=1)])
    assert retenues == []
    assert motifs["hors_perimetre"] == 1


def test_ecarte_un_yaml_sans_champs_structures():
    """Un lot produit avant les champs structurés ne doit pas se lire comme un lot vide."""
    retenues, motifs = trier_propositions([_prop(date_iso="", lieu_nom="")])
    assert retenues == []
    assert motifs["sans_donnee"] == 1
    assert motifs["hors_perimetre"] == 0


def test_ecarte_une_date_incomplete():
    retenues, motifs = trier_propositions([_prop(date_iso="2021")])
    assert retenues == []
    assert motifs["sans_donnee"] == 1


def test_rapport_annonce_le_mode_effectif():
    md = render_deaths_report("2026-07-21", [], [], [], {"hors_perimetre": 0,
                              "sans_donnee": 0}, [], dry_run=True)
    assert "simulation" in md
    assert "écritures appliquées" not in md


def test_rapport_liste_les_evenements_crees():
    md = render_deaths_report(
        "2026-07-21",
        [("I0174", "Alain Rolland", "E9001", "Saint-Palais")],
        [], [], {"hors_perimetre": 0, "sans_donnee": 0}, [], dry_run=False)
    assert "I0174 Alain Rolland" in md
    assert "E9001" in md
    assert "Saint-Palais" in md
    assert "Décès créés : 1" in md


def test_rapport_distingue_les_deux_motifs_de_rejet():
    """Chaque libellé doit porter SON compte, pas celui de l'autre motif.

    Une simple présence indépendante des deux libellés et des deux nombres ne
    verrouille rien : intervertir les compteurs dans `render_deaths_report`
    laisserait ce test passer. On exige donc que le nombre attendu soit sur la
    MÊME ligne que son libellé.
    """
    md = render_deaths_report("2026-07-21", [], [], [],
                              {"hors_perimetre": 8, "sans_donnee": 3}, [], dry_run=False)
    lignes = md.splitlines()
    ligne_hors_perimetre = next(ligne for ligne in lignes if "Hors périmètre" in ligne)
    ligne_sans_donnee = next(ligne for ligne in lignes if "sans donnée machine" in ligne.lower())
    assert "8" in ligne_hors_perimetre
    assert "3" in ligne_sans_donnee


def test_rapport_signale_les_lieux_non_resolus():
    md = render_deaths_report("2026-07-21", [], [], [("I0186", "Nohant-en-Goût")],
                              {"hors_perimetre": 0, "sans_donnee": 0}, [], dry_run=False)
    assert "Lieux non résolus" in md
    assert "Nohant-en-Goût" in md


def test_rapport_porte_le_handle_de_l_orphelin():
    """Un événement non rattaché doit être retrouvable : son handle en clair."""
    md = render_deaths_report(
        "2026-07-21", [], [], [], {"hors_perimetre": 0, "sans_donnee": 0},
        [("I0174", "Death créé mais NON rattaché (orphelin EV_ORPH) : timeout")],
        dry_run=False)
    assert "EV_ORPH" in md
