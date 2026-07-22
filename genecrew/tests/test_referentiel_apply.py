# genecrew/tests/test_referentiel_apply.py
"""Appariement et invariant d'écriture de `apply referentiel`. Hors ligne, sans base réelle.

Les QID écrits ici ont été relus sur Wikidata le 2026-07-22 (spec §9) : Q12771 canton de
Vaud, Q980 Bavière, Q236772 wilaya de Souk Ahras, Q3113 Allier, Q46130 département du Rhône,
Q39 Suisse, Q183 Allemagne, Q262 Algérie, Q18338206 Auvergne-Rhône-Alpes.
"""

import json

import httpx
import pytest
import yaml
from crewai_custom_tools.tools.genealogy.gramps import write_tools
from crewai_custom_tools.tools.genealogy.gramps.client import GrampsClient, GrampsConfig
from crewai_custom_tools.tools.genealogy.models.domain import Subdivision
from crewai_custom_tools.tools.genealogy.referentiel.chargement import EntitePays

from genecrew.referentiel_apply import (
    apparier, decider, index_par_nom_contenant, index_par_nom_type, index_par_qid,
    run_referentiel_apply, subdivision_de_pays,
)

VAUD = Subdivision(qid="Q12771", iso="CH-VD", code="VD", libelle_fr="canton de Vaud",
                   noms=["canton de Vaud"], place_type="State", niveau=1, parent_qid="Q39",
                   lat="46.6", long="6.6", frwiki="https://fr.wikipedia.org/wiki/Canton_de_Vaud")
SUISSE = EntitePays(qid="Q39", libelle_fr="Suisse", lat="46.8", long="8.2",
                    frwiki="https://fr.wikipedia.org/wiki/Suisse")


# --- appariement -----------------------------------------------------------------------

def test_le_qid_prime_sur_les_noms():
    par_qid = {"Q12771": "h_qid"}
    par_nom_type = {("canton de Vaud", "State"): "h_nom"}
    assert apparier(VAUD, par_qid, par_nom_type, {}) == "h_qid"


def test_appariement_par_nom_vernaculaire_quand_aucun_qid_nest_pose():
    """Premier run : `Bayern` est en base en allemand, la subdivision arrive en français."""
    bayern = Subdivision(qid="Q980", iso="DE-BY", code="BY", libelle_fr="Bavière",
                         noms=["Bavière", "Bayern"], place_type="State", niveau=1,
                         parent_qid="Q183")
    par_nom_type = {("Bayern", "State"): "h_bayern"}
    assert apparier(bayern, {}, par_nom_type, {}) == "h_bayern"


def test_appariement_par_nom_seul_pour_retyper_une_wilaya():
    """Souk Ahras est typée `Wilaya` : aucune clé (nom, type) ne peut la retrouver."""
    souk = Subdivision(qid="Q236772", iso="DZ-41", code="41", libelle_fr="Souk Ahras",
                       noms=["Souk Ahras"], place_type="Province", niveau=1, parent_qid="Q262")
    assert apparier(souk, {}, {}, {"Souk Ahras": "h_wilaya"}) == "h_wilaya"


def test_index_par_nom_contenant_ignore_les_communes():
    """Une commune homonyme ne doit jamais être prise pour son canton."""
    places = [{"handle": "h_commune", "name": {"value": "Genève"},
               "place_type": "Municipality"},
              {"handle": "h_wilaya", "name": {"value": "Souk Ahras"},
               "place_type": "Wilaya"}]
    assert index_par_nom_contenant(places) == {"Souk Ahras": "h_wilaya"}


def test_index_par_qid_lit_lurl_wikidata():
    places = [{"handle": "h1", "urls": [
        {"path": "https://www.wikidata.org/wiki/Q12771", "desc": "Wikidata"}]}]
    assert index_par_qid(places) == {"Q12771": "h1"}


def test_index_par_qid_ignore_les_autres_urls():
    places = [{"handle": "h1", "urls": [
        {"path": "https://fr.wikipedia.org/wiki/Vaud", "desc": "Wikipédia"}]}]
    assert index_par_qid(places) == {}


def test_index_par_nom_type():
    places = [{"handle": "h2", "name": {"value": "Bayern"}, "place_type": "State"}]
    assert index_par_nom_type(places) == {("Bayern", "State"): "h2"}


# --- ce qui est décidé, et surtout ce qui ne l'est pas ----------------------------------

def test_creation_quand_le_lieu_est_absent():
    plan = decider(VAUD, None)
    assert plan["action"] == "creer"
    assert plan["name"] == "canton de Vaud"
    assert plan["place_type"] == "State"
    assert plan["code"] == "VD"
    assert plan["lat"] == "46.6" and plan["long"] == "6.6"


def test_un_nom_existant_nest_jamais_reecrit():
    """Bayern reste Bayern ; le libellé français rejoint les alt_names (spec §5.1)."""
    bayern = Subdivision(qid="Q980", iso="DE-BY", code="BY", libelle_fr="Bavière",
                         noms=["Bavière", "Bayern"], place_type="State", niveau=1,
                         parent_qid="Q183")
    place = {"handle": "h", "name": {"value": "Bayern"}, "place_type": "State",
             "lat": "", "long": "", "code": "", "alt_names": []}
    plan = decider(bayern, place)
    assert plan["action"] == "completer"
    assert "name" not in plan                 # aucune réécriture du nom
    assert plan["alt_names"] == [{"value": "Bavière"}]


def test_un_gps_deja_rempli_nest_pas_ecrase():
    place = {"handle": "h", "name": {"value": "canton de Vaud"}, "place_type": "State",
             "lat": "46.0", "long": "6.0", "code": "VD", "alt_names": []}
    plan = decider(VAUD, place)
    assert "lat" not in plan and "long" not in plan


def test_un_code_deja_rempli_nest_pas_ecrase():
    place = {"handle": "h", "name": {"value": "Allier"}, "place_type": "Department",
             "lat": "", "long": "", "code": "03", "alt_names": []}
    allier = Subdivision(qid="Q3113", iso="FR-03", code="03", libelle_fr="Allier",
                         noms=["Allier"], place_type="Department", niveau=2,
                         parent_qid="Q18338206")
    plan = decider(allier, place)
    assert "code" not in plan


def test_le_retypage_dune_wilaya_est_la_seule_reecriture_permise():
    place = {"handle": "h", "name": {"value": "Souk Ahras"}, "place_type": "Wilaya",
             "lat": "", "long": "", "code": "41", "alt_names": []}
    souk = Subdivision(qid="Q236772", iso="DZ-41", code="41", libelle_fr="Souk Ahras",
                       noms=["Souk Ahras"], place_type="Province", niveau=1,
                       parent_qid="Q262")
    plan = decider(souk, place)
    assert plan["place_type"] == "Province"


def test_un_type_natif_different_nest_jamais_reecrit():
    """Seul un type PERSONNALISÉ est normalisé. `Region` est un type natif, donc un choix
    humain : l'appariement par nom seul ne doit pas le convertir en `Department`."""
    place = {"handle": "h", "name": {"value": "Rhône"}, "place_type": "Region",
             "lat": "", "long": "", "code": "84", "alt_names": []}
    rhone = Subdivision(qid="Q46130", iso="FR-69", code="69", libelle_fr="Rhône",
                        noms=["Rhône"], place_type="Department", niveau=2,
                        parent_qid="Q18338206")
    plan = decider(rhone, place)
    assert "place_type" not in plan


def test_un_type_inconnu_est_rempli_et_non_ecrase():
    """`Unknown` est le type vide de Gramps : le remplir n'est pas une réécriture."""
    place = {"handle": "h", "name": {"value": "canton de Vaud"}, "place_type": "Unknown",
             "lat": "", "long": "", "code": "", "alt_names": []}
    assert decider(VAUD, place)["place_type"] == "State"


def test_le_libelle_francais_identique_nentre_pas_en_alt_names():
    place = {"handle": "h", "name": {"value": "canton de Vaud"}, "place_type": "State",
             "lat": "", "long": "", "code": "", "alt_names": []}
    plan = decider(VAUD, place)
    assert plan.get("alt_names", []) == []


def test_un_alt_name_deja_pose_ny_entre_pas_deux_fois():
    place = {"handle": "h", "name": {"value": "Bayern"}, "place_type": "State",
             "lat": "", "long": "", "code": "", "alt_names": [{"value": "Bavière"}]}
    bayern = Subdivision(qid="Q980", iso="DE-BY", code="BY", libelle_fr="Bavière",
                         noms=["Bavière", "Bayern"], place_type="State", niveau=1,
                         parent_qid="Q183")
    assert decider(bayern, place)["alt_names"] == []


def test_les_urls_a_poser_sont_le_qid_et_larticle():
    plan = decider(VAUD, None)
    chemins = [u["path"] for u in plan["urls"]]
    assert "https://www.wikidata.org/wiki/Q12771" in chemins
    assert "https://fr.wikipedia.org/wiki/Canton_de_Vaud" in chemins


def test_un_pays_devient_une_subdivision_de_niveau_zero():
    """Le pays passe par le même chemin d'écriture, et avant ses subdivisions."""
    pays = subdivision_de_pays(SUISSE)
    assert pays.place_type == "Country"
    assert pays.niveau == 0                  # écrit avant le niveau 1
    assert pays.code == "CH"                 # ISO 3166-1 alpha-2 (spec §5.2)
    assert pays.parent_qid == ""


# --- exécution complète : client Gramps simulé, aucun accès réseau ----------------------

CONFIG = GrampsConfig(api_url="http://g.test/api", username="u", password="p")


def _client(places, journal):
    """Client Gramps sur transport simulé : sert les lieux, journalise POST et PUT."""
    journal.setdefault("posts", [])
    journal.setdefault("puts", [])
    journal["objets"] = {p["handle"]: p for p in places}

    def handler(request):
        chemin = request.url.path
        if chemin == "/api/token/":
            return httpx.Response(200, json={"access_token": "t"})
        if request.method == "GET" and chemin == "/api/places/":
            page = int(request.url.params.get("page", "1"))
            return httpx.Response(200, json=places if page == 1 else [])
        if request.method == "GET" and chemin.startswith("/api/places/"):
            return httpx.Response(200, json=journal["objets"][chemin.rsplit("/", 1)[1]])
        if request.method == "POST" and chemin == "/api/places/":
            corps = json.loads(request.content)
            journal["posts"].append(corps)
            journal["objets"][corps["handle"]] = corps
            return httpx.Response(201, json=[{"type": "add", "_class": "Place",
                                              "handle": corps["handle"]}])
        if request.method == "PUT" and chemin.startswith("/api/places/"):
            corps = json.loads(request.content)
            journal["puts"].append(corps)
            journal["objets"][corps["handle"]] = corps
            return httpx.Response(200, json=corps)
        raise AssertionError(f"appel inattendu : {request.method} {chemin}")

    return GrampsClient(CONFIG, transport=httpx.MockTransport(handler))


def _yaml(tmp_path, pays=(), subdivisions=()):
    chemin = tmp_path / "relu.yaml"
    chemin.write_text(yaml.safe_dump({"pays": [p.model_dump() for p in pays],
                                      "subdivisions": [s.model_dump() for s in subdivisions]},
                                     allow_unicode=True, sort_keys=False), encoding="utf-8")
    return chemin


@pytest.fixture(autouse=True)
def _ecritures_reelles(monkeypatch):
    monkeypatch.setenv("GENECREW_DRY_RUN", "false")


def _lancer(mocker, tmp_path, places, *, pays=(SUISSE,), subdivisions=(VAUD,), dry_run=False):
    journal = {}
    client = _client(places, journal)
    mocker.patch.object(write_tools, "get_client", return_value=client)
    rapport = run_referentiel_apply(client, _yaml(tmp_path, pays, subdivisions), tmp_path,
                                    date="2026-07-22", dry_run=dry_run)
    return journal, rapport


def test_le_pays_est_ecrit_avant_ses_subdivisions(mocker, tmp_path):
    """Un enfant ne peut pas se rattacher à un parent qui n'existe pas encore."""
    journal, _ = _lancer(mocker, tmp_path, [])
    noms = [p["name"]["value"] for p in journal["posts"]]
    assert noms == ["Suisse", "canton de Vaud"]
    handle_suisse = journal["posts"][0]["handle"]
    assert journal["posts"][1]["placeref_list"] == [{"ref": handle_suisse}]


def test_le_parent_est_pose_quand_le_lieu_existant_na_pas_de_placeref(mocker, tmp_path):
    places = [{"handle": "h_ch", "gramps_id": "P0340", "name": {"value": "Suisse"},
               "place_type": "Country", "lat": "", "long": "", "code": "",
               "alt_names": [], "placeref_list": [], "urls": []},
              {"handle": "h_vd", "gramps_id": "P0500", "name": {"value": "canton de Vaud"},
               "place_type": "State", "lat": "", "long": "", "code": "",
               "alt_names": [], "placeref_list": [], "urls": []}]
    journal, _ = _lancer(mocker, tmp_path, places)
    vaud = [p for p in journal["puts"] if p["handle"] == "h_vd"][-1]
    assert vaud["placeref_list"] == [{"ref": "h_ch"}]


def test_un_placeref_existant_nest_pas_remplace(mocker, tmp_path):
    """Le rattachement déjà saisi est une valeur : il n'est jamais réécrit."""
    places = [{"handle": "h_ch", "gramps_id": "P0340", "name": {"value": "Suisse"},
               "place_type": "Country", "lat": "", "long": "", "code": "",
               "alt_names": [], "placeref_list": [], "urls": []},
              {"handle": "h_vd", "gramps_id": "P0500", "name": {"value": "canton de Vaud"},
               "place_type": "State", "lat": "", "long": "", "code": "",
               "alt_names": [], "placeref_list": [{"ref": "h_autre"}], "urls": []}]
    journal, _ = _lancer(mocker, tmp_path, places)
    vaud = [p for p in journal["puts"] if p["handle"] == "h_vd"][-1]
    assert vaud["placeref_list"] == [{"ref": "h_autre"}]


def test_le_nom_en_base_survit_a_lexecution(mocker, tmp_path):
    """L'invariant de bout en bout : aucun PUT ne change `name.value`."""
    bayern = Subdivision(qid="Q980", iso="DE-BY", code="BY", libelle_fr="Bavière",
                         noms=["Bavière", "Bayern"], place_type="State", niveau=1,
                         parent_qid="Q183")
    places = [{"handle": "h_by", "gramps_id": "P0600", "name": {"value": "Bayern"},
               "place_type": "State", "lat": "", "long": "", "code": "",
               "alt_names": [], "placeref_list": [], "urls": []}]
    journal, _ = _lancer(mocker, tmp_path, places, pays=(), subdivisions=(bayern,))
    assert {p["name"]["value"] for p in journal["puts"]} == {"Bayern"}
    assert journal["puts"][-1]["alt_names"] == [{"value": "Bavière"}]


def test_les_urls_wikidata_et_wikipedia_sont_ajoutees(mocker, tmp_path):
    places = [{"handle": "h_vd", "gramps_id": "P0500", "name": {"value": "canton de Vaud"},
               "place_type": "State", "lat": "", "long": "", "code": "",
               "alt_names": [], "placeref_list": [], "urls": []}]
    journal, _ = _lancer(mocker, tmp_path, places, pays=(), subdivisions=(VAUD,))
    chemins = {u["path"] for u in journal["objets"]["h_vd"]["urls"]}
    assert chemins == {"https://www.wikidata.org/wiki/Q12771",
                       "https://fr.wikipedia.org/wiki/Canton_de_Vaud"}


def test_la_simulation_necrit_rien(mocker, tmp_path):
    journal, _ = _lancer(mocker, tmp_path, [], dry_run=True)
    assert journal["posts"] == [] and journal["puts"] == []


def test_le_rapport_porte_le_mode_dans_son_nom(mocker, tmp_path):
    """Une écriture réelle ne doit pas écraser l'aperçu qui l'a autorisée (spec §9)."""
    _, simule = _lancer(mocker, tmp_path, [], dry_run=True)
    _, ecrit = _lancer(mocker, tmp_path, [], dry_run=False)
    assert simule.name.endswith("_simulation.md")
    assert ecrit.name.endswith("_ecritures.md")
    assert simule != ecrit
