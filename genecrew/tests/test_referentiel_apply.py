# genecrew/tests/test_referentiel_apply.py
"""Appariement et invariant d'écriture de `apply referentiel`. Hors ligne, sans base réelle.

Les QID écrits ici ont été relus sur Wikidata le 2026-07-22 (spec §9) : Q12771 canton de
Vaud, Q980 Bavière, Q236772 wilaya de Souk Ahras, Q3113 Allier, Q46130 et Q18914778 les deux
« Rhône » de la collision FR-69, Q1428 l'État américain de Géorgie, Q30 États-Unis, Q39
Suisse, Q183 Allemagne, Q262 Algérie, Q142 France, Q28 Hongrie, Q1273 Toscane.
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
    apparier,
    decider,
    handles_designant,
    identifiant,
    index_par_nom_contenant,
    index_par_nom_type,
    index_par_qid,
    motif_dexclusion,
    qid_pose,
    run_referentiel_apply,
    subdivision_de_pays,
)

VAUD = Subdivision(qid="Q12771", iso="CH-VD", code="VD", libelle_fr="canton de Vaud",
                   noms=["canton de Vaud"], place_type="State", niveau=1, parent_qid="Q39",
                   lat="46.6", long="6.6", frwiki="https://fr.wikipedia.org/wiki/Canton_de_Vaud")
SUISSE = EntitePays(qid="Q39", libelle_fr="Suisse", lat="46.8", long="8.2",
                    frwiki="https://fr.wikipedia.org/wiki/Suisse")
BAYERN = Subdivision(qid="Q980", iso="DE-BY", code="BY", libelle_fr="Bavière",
                     noms=["Bavière", "Bayern"], place_type="State", niveau=1,
                     parent_qid="Q183")
SOUK = Subdivision(qid="Q236772", iso="DZ-41", code="41", libelle_fr="Souk Ahras",
                   noms=["Souk Ahras"], place_type="Province", niveau=1, parent_qid="Q262")
GEORGIE = Subdivision(qid="Q1428", iso="US-GA", code="GA", libelle_fr="Géorgie",
                      noms=["Géorgie", "Georgia"], place_type="State", niveau=1,
                      parent_qid="Q30", lat="32.6", long="-83.4")
RHONE = Subdivision(qid="Q46130", iso="FR-69", code="69", libelle_fr="Rhône",
                    noms=["Rhône"], place_type="Department", niveau=2,
                    parent_qid="Q18338206")
ARA = Subdivision(qid="Q18338206", iso="FR-ARA", code="ARA",
                  libelle_fr="Auvergne-Rhône-Alpes", noms=["Auvergne-Rhône-Alpes"],
                  place_type="Region", niveau=1, parent_qid="Q142")
ALLEMAGNE = EntitePays(qid="Q183", libelle_fr="Allemagne", lat="51.0", long="9.0")
ALGERIE = EntitePays(qid="Q262", libelle_fr="Algérie", lat="28.0", long="2.6")
FRANCE = EntitePays(qid="Q142", libelle_fr="France", lat="46.2", long="2.2")
ETATS_UNIS = EntitePays(qid="Q30", libelle_fr="États-Unis", lat="39.8", long="-98.6")


# --- appariement -----------------------------------------------------------------------

def test_le_qid_prime_sur_les_noms():
    par_qid = {"Q12771": "h_qid"}
    par_nom_type = {("canton de Vaud", "State"): ["h_nom"]}
    assert apparier(VAUD, par_qid, par_nom_type, {}) == ("apparier", "h_qid")


def test_appariement_par_nom_vernaculaire_quand_aucun_qid_nest_pose():
    """Premier run : `Bayern` est en base en allemand, la subdivision arrive en français."""
    par_nom_type = {("Bayern", "State"): ["h_bayern"]}
    assert apparier(BAYERN, {}, par_nom_type, {}) == ("apparier", "h_bayern")


def test_appariement_par_nom_seul_pour_retyper_une_wilaya():
    """Souk Ahras est typée `Wilaya` : aucune clé (nom, type) ne peut la retrouver."""
    assert apparier(SOUK, {}, {}, {"Souk Ahras": ["h_wilaya"]}) == ("apparier", "h_wilaya")


def test_la_deuxieme_prise_exige_le_type_et_pas_seulement_le_nom():
    """Souk Ahras est à la fois une wilaya et une commune : c'est le type qui les sépare."""
    assert apparier(SOUK, {}, {("Souk Ahras", "Municipality"): ["h_commune"]}, {}) == ("creer", None)


def test_un_pays_homonyme_nest_jamais_pris_pour_une_subdivision():
    """Cas reproduit : l'État `Géorgie` s'appariait au PAYS Géorgie, qui recevait alors le
    GPS d'Atlanta, le code `GA` et un rattachement sous les États-Unis."""
    par_handle = {"h_pays": {"handle": "h_pays", "name": {"value": "Géorgie"},
                             "place_type": "Country", "placeref_list": []}}
    assert apparier(GEORGIE, {}, {}, {"Géorgie": ["h_pays"]},
                    par_handle=par_handle) == ("creer", None)


def test_un_candidat_rattache_ailleurs_est_refuse():
    """Clause « sous le même parent » du §5.3, que l'index (nom, type) ignore à lui seul."""
    par_handle = {"h_r": {"handle": "h_r", "name": {"value": "Rhône"},
                          "place_type": "Department",
                          "placeref_list": [{"ref": "h_un_autre_parent"}]}}
    assert apparier(RHONE, {}, {("Rhône", "Department"): ["h_r"]}, {},
                    par_handle=par_handle, parents={"h_ara"}) == ("creer", None)
    assert apparier(RHONE, {}, {("Rhône", "Department"): ["h_r"]}, {},
                    par_handle=par_handle,
                    parents={"h_un_autre_parent"}) == ("apparier", "h_r")


def test_un_candidat_non_rattache_est_renvoye_a_confirmation():
    """Un contenant SANS rattachement n'apporte AUCUNE preuve, ni pour ni contre : ni
    l'écrire (risque du mauvais objet) ni le doubler (nettoyage imposé). On le signale."""
    par_handle = {"h_r": {"handle": "h_r", "name": {"value": "Rhône"},
                          "place_type": "Department", "placeref_list": []}}
    assert apparier(RHONE, {}, {("Rhône", "Department"): ["h_r"]}, {},
                    par_handle=par_handle, parents={"h_ara"}) == ("confirmer", "h_r")


def test_un_parent_attendu_introuvable_est_une_preuve_indisponible():
    """`charger_entites_pays` rend `{}` quand son appel échoue pendant que `charger_pays`
    réussit : un YAML d'apparence normale peut porter 430 subdivisions et AUCUN pays.
    Traiter ce cas comme « rien à exiger » rouvrirait le défaut du Limbourg en silence."""
    par_handle = {"h_r": {"handle": "h_r", "name": {"value": "Rhône"},
                          "place_type": "Department",
                          "placeref_list": [{"ref": "h_ara"}]}}
    assert apparier(RHONE, {}, {("Rhône", "Department"): ["h_r"]}, {},
                    par_handle=par_handle) == ("confirmer", "h_r")


def test_un_pays_na_pas_de_parent_a_exiger():
    """Seul un `parent_qid` VIDE autorise vraiment à ne rien exiger."""
    suisse = subdivision_de_pays(SUISSE)
    par_handle = {"h_ch": {"handle": "h_ch", "name": {"value": "Suisse"},
                           "place_type": "Country", "placeref_list": []}}
    assert apparier(suisse, {}, {("Suisse", "Country"): ["h_ch"]}, {},
                    par_handle=par_handle) == ("apparier", "h_ch")


def test_un_enfant_sous_lun_des_homonymes_du_parent_est_reconnu():
    """Arbre à deux `France` — QID sur l'une, régions sous l'autre, configuration ordinaire.
    Comparer au seul handle élu ferait créer un second exemplaire de chaque région."""
    ara = Subdivision(qid="Q18338206", iso="FR-ARA", code="ARA",
                      libelle_fr="Auvergne-Rhône-Alpes", noms=["Auvergne-Rhône-Alpes"],
                      place_type="Region", niveau=1, parent_qid="Q142")
    par_handle = {"h_ara": {"handle": "h_ara", "name": {"value": "Auvergne-Rhône-Alpes"},
                            "place_type": "Region", "placeref_list": [{"ref": "h_f1"}]}}
    assert apparier(ara, {}, {("Auvergne-Rhône-Alpes", "Region"): ["h_ara"]}, {},
                    par_handle=par_handle,
                    parents={"h_f1", "h_f2"}) == ("apparier", "h_ara")


def test_un_candidat_a_confirmer_ne_coupe_pas_la_recherche():
    """La prise 2 trouve un homonyme flottant, la prise 3 un lieu franchement sous le parent
    attendu : c'est la preuve qui l'emporte, pas l'ordre des prises."""
    par_handle = {"h_flottant": {"handle": "h_flottant", "name": {"value": "Souk Ahras"},
                                 "place_type": "Province", "placeref_list": []},
                  "h_bon": {"handle": "h_bon", "name": {"value": "Souk Ahras"},
                            "place_type": "Wilaya", "placeref_list": [{"ref": "h_dz"}]}}
    assert apparier(SOUK, {}, {("Souk Ahras", "Province"): ["h_flottant"]},
                    {"Souk Ahras": ["h_bon"]}, par_handle=par_handle,
                    parents={"h_dz"}) == ("apparier", "h_bon")


def test_le_premier_candidat_a_confirmer_est_celui_retenu():
    """Deux homonymes flottants : le premier rencontré est rendu, pour que deux exécutions
    sur le même arbre nomment le même lieu au rapport."""
    par_handle = {"h_premier": {"handle": "h_premier", "name": {"value": "Souk Ahras"},
                                "place_type": "Province", "placeref_list": []},
                  "h_second": {"handle": "h_second", "name": {"value": "Souk Ahras"},
                               "place_type": "Wilaya", "placeref_list": []}}
    assert apparier(SOUK, {}, {("Souk Ahras", "Province"): ["h_premier"]},
                    {"Souk Ahras": ["h_second"]}, par_handle=par_handle,
                    parents={"h_dz"}) == ("confirmer", "h_premier")


def test_handles_designant_ramasse_les_homonymes_et_les_porteurs_du_qid():
    france = subdivision_de_pays(EntitePays(qid="Q142", libelle_fr="France"))
    places = [{"handle": "h_f1", "name": {"value": "France"}, "place_type": "Country"},
              {"handle": "h_f2", "name": {"value": "France"}, "place_type": "Country",
               "urls": [{"path": "https://www.wikidata.org/wiki/Q142", "desc": "Wikidata"}]},
              {"handle": "h_x", "name": {"value": "Suisse"}, "place_type": "Country"}]
    assert handles_designant(france, places) == {"h_f1", "h_f2"}


def test_index_par_nom_contenant_ignore_les_communes():
    """Une commune homonyme ne doit jamais être prise pour son canton."""
    places = [{"handle": "h_commune", "name": {"value": "Genève"},
               "place_type": "Municipality"},
              {"handle": "h_wilaya", "name": {"value": "Souk Ahras"},
               "place_type": "Wilaya"}]
    assert index_par_nom_contenant(places) == {"Souk Ahras": ["h_wilaya"]}


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
    assert index_par_nom_type(places) == {("Bayern", "State"): ["h2"]}


# Le « premier gagne » des trois index n'est pas un détail d'implémentation : `iter_places`
# trie par `gramps_id`, donc c'est lui qui rend deux exécutions comparables — et une
# simulation représentative de l'écriture qu'elle autorise.

def test_index_par_qid_retient_le_premier_lieu_rencontre():
    urls = [{"path": "https://www.wikidata.org/wiki/Q142", "desc": "Wikidata"}]
    assert index_par_qid([{"handle": "h1", "urls": urls},
                          {"handle": "h2", "urls": urls}]) == {"Q142": "h1"}


def test_index_par_nom_type_retient_tous_les_homonymes_tries():
    """N'en garder qu'un cache la bonne cible derrière un homonyme mal placé. L'ordre est
    celui des `gramps_id`, pour que deux exécutions évaluent les candidats pareillement."""
    places = [{"handle": "h2", "gramps_id": "P0357", "name": {"value": "France"},
               "place_type": "Country"},
              {"handle": "h1", "gramps_id": "P0345", "name": {"value": "France"},
               "place_type": "Country"}]
    assert index_par_nom_type(places) == {("France", "Country"): ["h1", "h2"]}


def test_index_par_nom_contenant_retient_tous_les_homonymes_tries():
    places = [{"handle": "h2", "gramps_id": "P0357", "name": {"value": "France"},
               "place_type": "Country"},
              {"handle": "h1", "gramps_id": "P0345", "name": {"value": "France"},
               "place_type": "Country"}]
    assert index_par_nom_contenant(places) == {"France": ["h1", "h2"]}


def test_le_bon_homonyme_lemporte_sur_celui_qui_vient_avant():
    """Cas relevé en simulation sur l'arbre réel : deux `Souk Ahras`, un `Department`
    rattaché à lui-même (P0345, cycle préexistant) et la vraie `Wilaya` sous l'Algérie
    (P0357). Le premier gagnait l'index et faisait conclure « créer » ; la wilaya
    correctement rattachée n'était jamais examinée."""
    par_handle = {"h_345": {"handle": "h_345", "name": {"value": "Souk Ahras"},
                            "place_type": "Department",
                            "placeref_list": [{"ref": "h_345"}]},
                  "h_357": {"handle": "h_357", "name": {"value": "Souk Ahras"},
                            "place_type": "Wilaya",
                            "placeref_list": [{"ref": "h_dz"}]}}
    assert apparier(SOUK, {}, {}, {"Souk Ahras": ["h_345", "h_357"]},
                    par_handle=par_handle, parents={"h_dz"}) == ("apparier", "h_357")


def test_confirmer_prime_sur_creer_entre_homonymes():
    """Aucun candidat au bon endroit, mais l'un d'eux n'est pas rattaché : demander un
    arbitrage vaut mieux que créer en silence."""
    par_handle = {"h_ailleurs": {"handle": "h_ailleurs", "name": {"value": "Souk Ahras"},
                                 "place_type": "Department",
                                 "placeref_list": [{"ref": "h_autre"}]},
                  "h_flottant": {"handle": "h_flottant", "name": {"value": "Souk Ahras"},
                                 "place_type": "Wilaya", "placeref_list": []}}
    assert apparier(SOUK, {}, {}, {"Souk Ahras": ["h_ailleurs", "h_flottant"]},
                    par_handle=par_handle, parents={"h_dz"}) == ("confirmer", "h_flottant")


def test_un_type_illisible_ecarte_le_lieu_des_trois_index():
    """La normalisation se fait à la LECTURE : un `place_type` non hachable faisait sauter
    la construction des index, hors de toute boucle et de tout `try` — traceback nu, aucun
    rapport écrit."""
    place = {"handle": "h", "gramps_id": "P0001", "name": {"value": "Souk Ahras"},
             "place_type": {"_class": "PlaceType", "string": "Wilaya"},
             "urls": [{"path": "https://www.wikidata.org/wiki/Q236772", "desc": "Wikidata"}]}
    assert index_par_qid([place]) == {}
    assert index_par_nom_type([place]) == {}
    assert index_par_nom_contenant([place]) == {}
    assert "illisible" in motif_dexclusion(place)


def test_deux_qid_concurrents_rendent_le_lieu_inexploitable():
    """Rendre le premier laisserait l'ordre de la liste `urls` décider d'une identité, en
    silence — alors que le module refuse par ailleurs de créer cette situation."""
    place = {"handle": "h", "gramps_id": "P0002", "name": {"value": "Rhône"},
             "place_type": "Department",
             "urls": [{"path": "https://www.wikidata.org/wiki/Q46130", "desc": "Wikidata"},
                      {"path": "https://www.wikidata.org/wiki/Q18914778", "desc": "Wikidata"}]}
    assert qid_pose(place) is None
    assert index_par_nom_type([place]) == {}
    assert "concurrentes" in motif_dexclusion(place)


def test_un_meme_qid_repete_nest_pas_une_ambiguite():
    url = {"path": "https://www.wikidata.org/wiki/Q46130", "desc": "Wikidata"}
    place = {"handle": "h", "name": {"value": "Rhône"}, "place_type": "Department",
             "urls": [url, dict(url, desc="Wikidata (doublon)")]}
    assert qid_pose(place) == "Q46130"
    assert motif_dexclusion(place) is None


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
    place = {"handle": "h", "name": {"value": "Bayern"}, "place_type": "State",
             "lat": "", "long": "", "code": "", "alt_names": []}
    plan = decider(BAYERN, place)
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
    plan = decider(SOUK, place)
    assert plan["place_type"] == "Province"
    assert plan["retypage"] == ("Wilaya", "Province")     # rapporté ligne à ligne


def test_un_type_natif_different_nest_jamais_reecrit():
    """Seul un type PERSONNALISÉ est normalisé. `Region` est un type natif, donc un choix
    humain : l'appariement par nom seul ne doit pas le convertir en `Department`."""
    place = {"handle": "h", "name": {"value": "Rhône"}, "place_type": "Region",
             "lat": "", "long": "", "code": "84", "alt_names": []}
    plan = decider(RHONE, place)
    assert "place_type" not in plan


def test_un_type_inconnu_est_rempli_et_non_ecrase():
    """`Unknown` est le type vide de Gramps : le remplir n'est pas une réécriture, et ne
    compte donc pas comme un retypage dans le rapport."""
    place = {"handle": "h", "name": {"value": "canton de Vaud"}, "place_type": "Unknown",
             "lat": "", "long": "", "code": "", "alt_names": []}
    plan = decider(VAUD, place)
    assert plan["place_type"] == "State" and "retypage" not in plan


def test_un_type_illisible_ne_decide_aucun_retypage():
    """`TYPES_NATIFS` est recopié de la spec, jamais relu sur l'API. Si le serveur rendait
    un objet au lieu d'une chaîne, TOUS les types passeraient pour personnalisés."""
    place = {"handle": "h", "name": {"value": "canton de Vaud"},
             "place_type": {"_class": "PlaceType", "string": "State"},
             "lat": "", "long": "", "code": "", "alt_names": []}
    plan = decider(VAUD, place)
    assert plan["type_illisible"] is True
    assert "place_type" not in plan


def test_le_libelle_francais_identique_nentre_pas_en_alt_names():
    place = {"handle": "h", "name": {"value": "canton de Vaud"}, "place_type": "State",
             "lat": "", "long": "", "code": "", "alt_names": []}
    plan = decider(VAUD, place)
    assert plan.get("alt_names", []) == []


def test_un_alt_name_deja_pose_ny_entre_pas_deux_fois():
    place = {"handle": "h", "name": {"value": "Bayern"}, "place_type": "State",
             "lat": "", "long": "", "code": "", "alt_names": [{"value": "Bavière"}]}
    assert decider(BAYERN, place)["alt_names"] == []


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


def test_un_pays_hors_table_garde_un_identifiant():
    """Sans code ISO, une ligne de rapport doit rester rattachable à quelque chose."""
    hongrie = subdivision_de_pays(EntitePays(qid="Q28", libelle_fr="Hongrie"))
    assert hongrie.iso == ""
    assert identifiant(hongrie) == "Q28"


# --- exécution complète : client Gramps simulé, aucun accès réseau ----------------------

CONFIG = GrampsConfig(api_url="http://g.test/api", username="u", password="p")


def _client(places, journal, panne=None):
    """Client Gramps sur transport simulé : sert les lieux, journalise GET, POST et PUT.

    `panne(request)` peut rendre une réponse d'erreur, pour simuler un serveur qui refuse.
    """
    journal.setdefault("posts", [])
    journal.setdefault("puts", [])
    journal.setdefault("gets", [])
    journal["objets"] = {p["handle"]: p for p in places}

    def handler(request):
        chemin = request.url.path
        if chemin == "/api/token/":
            return httpx.Response(200, json={"access_token": "t"})
        avarie = panne(request) if panne else None
        if avarie is not None:
            return avarie
        if request.method == "GET" and chemin == "/api/places/":
            page = int(request.url.params.get("page", "1"))
            return httpx.Response(200, json=places if page == 1 else [])
        if request.method == "GET" and chemin.startswith("/api/places/"):
            handle = chemin.rsplit("/", 1)[1]
            journal["gets"].append(handle)
            return httpx.Response(200, json=journal["objets"][handle])
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


def _yaml(tmp_path, pays=(), subdivisions=(), doublons=()):
    chemin = tmp_path / "relu.yaml"
    chemin.write_text(yaml.safe_dump({"pays": [p.model_dump() for p in pays],
                                      "subdivisions": [s.model_dump() for s in subdivisions],
                                      "doublons_arbre": list(doublons)},
                                     allow_unicode=True, sort_keys=False), encoding="utf-8")
    return chemin


@pytest.fixture(autouse=True)
def _ecritures_reelles(monkeypatch):
    monkeypatch.setenv("GENECREW_DRY_RUN", "false")


def _lancer(mocker, tmp_path, places, *, pays=(SUISSE,), subdivisions=(VAUD,),
            doublons=(), dry_run=False, panne=None):
    journal = {}
    client = _client(places, journal, panne)
    mocker.patch.object(write_tools, "get_client", return_value=client)
    rapport = run_referentiel_apply(
        client, _yaml(tmp_path, pays, subdivisions, doublons), tmp_path,
        date="2026-07-22", dry_run=dry_run)
    return journal, rapport.read_text(encoding="utf-8"), rapport


def _section_du_rapport(texte, titre):
    """Le corps d'UNE section, sans les suivantes.

    `_section` rend toujours son titre, même vide : `assert "## Titre" in texte` ne peut donc
    pas échouer et n'atteste de rien. C'est la ligne DANS sa section qu'il faut vérifier.
    """
    return texte.split(f"## {titre}")[1].split("\n## ")[0]


def _lieu(handle, gid, nom, type_, **extra):
    return {"handle": handle, "gramps_id": gid, "name": {"value": nom},
            "place_type": type_, "lat": "", "long": "", "code": "",
            "alt_names": [], "placeref_list": [], "urls": [], **extra}


def _sous(parent_handle, place):
    """Rattache un lieu — c'est ce rattachement qui fait la preuve d'appartenance.

    Sans lui, `parents` reste vide et les gardes de parent ne sont jamais éprouvées : un
    test qui tourne sur `pays=()` ne visite pas le chemin que la production empruntera.
    """
    return {**place, "placeref_list": [{"ref": parent_handle}]}


def test_le_pays_est_ecrit_avant_ses_subdivisions(mocker, tmp_path):
    """Un enfant ne peut pas se rattacher à un parent qui n'existe pas encore."""
    journal, _, _ = _lancer(mocker, tmp_path, [])
    noms = [p["name"]["value"] for p in journal["posts"]]
    assert noms == ["Suisse", "canton de Vaud"]
    handle_suisse = journal["posts"][0]["handle"]
    assert journal["posts"][1]["placeref_list"] == [{"ref": handle_suisse}]


def test_le_parent_est_pose_quand_le_lieu_existant_na_pas_de_placeref(mocker, tmp_path):
    """Le QID identifie le canton sans ambiguïté — c'est la seule prise qui accepte un lieu
    non rattaché, et donc la seule qui puisse lui poser son parent (spec §5.1)."""
    places = [_lieu("h_ch", "P0340", "Suisse", "Country",
                    urls=[{"path": "https://www.wikidata.org/wiki/Q39", "desc": "Wikidata"}]),
              _lieu("h_vd", "P0500", "canton de Vaud", "State",
                    urls=[{"path": "https://www.wikidata.org/wiki/Q12771",
                           "desc": "Wikidata"}])]
    journal, _, _ = _lancer(mocker, tmp_path, places)
    vaud = [p for p in journal["puts"] if p["handle"] == "h_vd"][-1]
    assert vaud["placeref_list"] == [{"ref": "h_ch"}]


def test_un_placeref_existant_nest_pas_remplace(mocker, tmp_path):
    """Le rattachement déjà saisi est une valeur : il n'est jamais réécrit.

    Second run, les QID sont posés : l'appariement ne passe plus par les noms, donc pas non
    plus par la garde « sous le même parent ». Si un humain a depuis rattaché le canton
    ailleurs, c'est SON rattachement qui reste.
    """
    places = [_lieu("h_ch", "P0340", "Suisse", "Country",
                    urls=[{"path": "https://www.wikidata.org/wiki/Q39", "desc": "Wikidata"}]),
              _lieu("h_vd", "P0500", "canton de Vaud", "State",
                    placeref_list=[{"ref": "h_autre"}],
                    urls=[{"path": "https://www.wikidata.org/wiki/Q12771",
                           "desc": "Wikidata"}])]
    journal, _, _ = _lancer(mocker, tmp_path, places)
    vaud = [p for p in journal["puts"] if p["handle"] == "h_vd"][-1]
    assert vaud["placeref_list"] == [{"ref": "h_autre"}]


def test_le_nom_en_base_survit_a_lexecution(mocker, tmp_path):
    """L'invariant de bout en bout : aucun PUT ne change `name.value`."""
    places = [_lieu("h_de", "P0700", "Allemagne", "Country"),
              _sous("h_de", _lieu("h_by", "P0600", "Bayern", "State"))]
    journal, _, _ = _lancer(mocker, tmp_path, places, pays=(ALLEMAGNE,),
                            subdivisions=(BAYERN,))
    assert {p["name"]["value"] for p in journal["puts"]} == {"Bayern", "Allemagne"}
    assert journal["puts"][-1]["alt_names"] == [{"value": "Bavière"}]


def test_les_urls_wikidata_et_wikipedia_sont_ajoutees(mocker, tmp_path):
    places = [_lieu("h_ch", "P0340", "Suisse", "Country"),
              _sous("h_ch", _lieu("h_vd", "P0500", "canton de Vaud", "State"))]
    journal, _, _ = _lancer(mocker, tmp_path, places)
    chemins = {u["path"] for u in journal["objets"]["h_vd"]["urls"]}
    assert chemins == {"https://www.wikidata.org/wiki/Q12771",
                       "https://fr.wikipedia.org/wiki/Canton_de_Vaud"}


def test_la_simulation_necrit_rien(mocker, tmp_path):
    journal, _, _ = _lancer(mocker, tmp_path, [], dry_run=True)
    assert journal["posts"] == [] and journal["puts"] == []


def test_la_simulation_ninterroge_aucun_handle_simule(mocker, tmp_path):
    """Le handle d'un lieu créé en simulation ne désigne rien : le lire ferait un 404."""
    journal, texte, _ = _lancer(mocker, tmp_path, [], dry_run=True)
    assert [h for h in journal["gets"] if h.startswith("DRYRUN:")] == []
    assert "Aucune erreur." in texte


def test_la_simulation_compte_les_urls_quelle_poserait(mocker, tmp_path):
    """L'aperçu qui autorise l'écriture ne doit pas annoncer 0 URL pour un run qui en pose 4."""
    _, texte, _ = _lancer(mocker, tmp_path, [], dry_run=True)
    assert "- URLs à poser : 4" in texte


def test_le_rapport_porte_le_mode_dans_son_nom(mocker, tmp_path):
    """Une écriture réelle ne doit pas écraser l'aperçu qui l'a autorisée (spec §9)."""
    *_, simule = _lancer(mocker, tmp_path, [], dry_run=True)
    *_, ecrit = _lancer(mocker, tmp_path, [], dry_run=False)
    assert simule.name.endswith("_simulation.md")
    assert ecrit.name.endswith("_ecritures.md")
    assert simule != ecrit


# --- les deux régressions relevées en revue --------------------------------------------

def test_le_pays_georgie_nest_ni_enrichi_ni_rerattache(mocker, tmp_path):
    """Cas reproduit : le PAYS Géorgie prenait le GPS d'Atlanta, le code `GA`, et devenait
    un enfant des États-Unis. L'invariant tenait — rien n'était écrasé — et la donnée était
    fausse quand même : il protège de la destruction, pas du mauvais objet."""
    places = [_lieu("h_geo", "P0700", "Géorgie", "Country")]
    journal, _texte, _ = _lancer(mocker, tmp_path, places, pays=(ETATS_UNIS,),
                                subdivisions=(GEORGIE,))
    assert [p for p in journal["puts"] if p["handle"] == "h_geo"] == []
    assert [p["place_type"] for p in journal["posts"]] == ["Country", "State"]
    assert journal["objets"]["h_geo"]["code"] == ""      # le pays n'a rien reçu


def test_deux_entrees_sur_le_meme_lieu_nen_ecrivent_quune(mocker, tmp_path):
    """Cas reproduit avec la collision FR-69 remise dans le YAML par un relecteur : la
    seconde passe relisait un cache périmé, écrasait le code posé par la première, et
    rattachait le lieu à lui-même."""
    second = RHONE.model_copy(update={"qid": "Q18914778", "iso": "FR-69D", "code": "69D"})
    places = [_lieu("h_fr", "P0295", "France", "Country"),
              _sous("h_fr", _lieu("h_ara", "P0400", "Auvergne-Rhône-Alpes", "Region")),
              _sous("h_ara", _lieu("h_r", "P0800", "Rhône", "Department"))]
    journal, texte, _ = _lancer(mocker, tmp_path, places, pays=(FRANCE,),
                                subdivisions=(ARA, RHONE, second))
    ecrits = [p for p in journal["puts"] if p["handle"] == "h_r"]
    assert [p["code"] for p in ecrits] == ["69", "69"]      # jamais réécrit en 69D
    assert "| FR-69 | FR-69D | Rhône |" in _section_du_rapport(
        texte, "Conflits d'appariement")


def test_un_homonyme_non_rattache_ne_recoit_rien(mocker, tmp_path):
    """Cas reproduit : un `Province` « Limbourg » néerlandais, non rattaché, recevait le GPS
    et le code du Limbourg belge. C'est le lieu de l'arbre, pas la subdivision, qui décide :
    rien n'est écrit dessus."""
    limbourg = Subdivision(qid="Q1095", iso="BE-VLI", code="VLI", libelle_fr="Limbourg",
                           noms=["Limbourg"], place_type="Province", niveau=1,
                           parent_qid="Q31", lat="51.0", long="5.4")
    belgique = EntitePays(qid="Q31", libelle_fr="Belgique", lat="50.6", long="4.6")
    places = [_lieu("h_nl", "P1000", "Limbourg", "Province")]   # le Limbourg néerlandais
    journal, _, _ = _lancer(mocker, tmp_path, places, pays=(belgique,),
                            subdivisions=(limbourg,))
    assert [p for p in journal["puts"] if p["handle"] == "h_nl"] == []
    assert [p["name"]["value"] for p in journal["posts"]] == ["Belgique"]


def test_un_homonyme_non_rattache_est_signale_au_lieu_detre_double(mocker, tmp_path):
    """Les 4 `State` allemands sont en base en allemand, non rattachés — ils sont la raison
    d'être du nom vernaculaire. Créer `Bavière` à côté de `Bayern` serait le pire des trois
    résultats ; l'écrire prendrait le risque du mauvais objet. On rend la décision."""
    allemagne = EntitePays(qid="Q183", libelle_fr="Allemagne", lat="51.0", long="9.0")
    places = [_lieu("h_by", "P0600", "Bayern", "State")]
    journal, texte, _ = _lancer(mocker, tmp_path, places, pays=(allemagne,),
                                subdivisions=(BAYERN,))
    assert [p for p in journal["puts"] if p["handle"] == "h_by"] == []   # rien n'est écrit
    assert [p["name"]["value"] for p in journal["posts"]] == ["Allemagne"]   # rien créé
    ligne = _section_du_rapport(texte, "Homonymes non rattachés — à confirmer")
    assert "| P0600 | Bayern | DE-BY | Bavière | homonyme non rattaché |" in ligne
    # La colonne « ce qui aurait été posé » : une décision, pas une enquête.
    assert "code BY" in ligne and "alt_name Bavière" in ligne
    assert "https://www.wikidata.org/wiki/Q980" in ligne


def test_la_wilaya_bien_rattachee_est_apparie_malgre_son_homonyme(mocker, tmp_path):
    """Cas relevé par `apply referentiel --dry-run` sur l'arbre réel. Deux `Souk Ahras` :
    P0345 typée `Department` et rattachée à elle-même (cycle préexistant dans les données),
    P0357 la vraie `Wilaya` sous l'Algérie. `iter_places` triant par `gramps_id`, P0345
    gagnait l'index par nom, était jugée « rattachée ailleurs », et la wilaya correctement
    rattachée n'était jamais examinée — duplication alors qu'un appariement parfait
    existait."""
    places = [_lieu("h_dz", "P0100", "Algérie", "Country"),
              _lieu("h_345", "P0345", "Souk Ahras", "Department",
                    placeref_list=[{"ref": "h_345"}]),
              _sous("h_dz", _lieu("h_357", "P0357", "Souk Ahras", "Wilaya"))]
    journal, texte, _ = _lancer(mocker, tmp_path, places, pays=(ALGERIE,),
                                subdivisions=(SOUK,))
    assert journal["posts"] == []                              # aucune wilaya dupliquée
    assert journal["objets"]["h_357"]["code"] == "41"          # la bonne est servie
    assert journal["objets"]["h_345"]["code"] == ""            # l'homonyme reste intact
    assert "| DZ-41 | Souk Ahras | Wilaya | Province |" in _section_du_rapport(
        texte, "Retypages")


def test_un_yaml_sans_pays_nautorise_aucune_ecriture_par_le_nom(mocker, tmp_path):
    """Cas reproduit : `charger_entites_pays` rend `{}` quand son appel échoue pendant que
    `charger_pays` réussit. Le YAML sort d'apparence normale — des subdivisions, aucun pays
    — et le Limbourg néerlandais recevait les données du Limbourg belge, sans même figurer
    au rapport. Ici le lieu est même rattaché AILLEURS : la preuve contraire existait.
    """
    limbourg = Subdivision(qid="Q1095", iso="BE-VLI", code="VLI", libelle_fr="Limbourg",
                           noms=["Limbourg"], place_type="Province", niveau=1,
                           parent_qid="Q31", lat="51.0", long="5.4")
    places = [_lieu("h_nl_pays", "P1001", "Pays-Bas", "Country"),
              _sous("h_nl_pays", _lieu("h_nl", "P1000", "Limbourg", "Province"))]
    journal, texte, _ = _lancer(mocker, tmp_path, places, pays=(),
                                subdivisions=(limbourg,))
    assert [p for p in journal["puts"] if p["handle"] == "h_nl"] == []
    assert journal["posts"] == []
    assert "| P1000 | Limbourg | BE-VLI | Limbourg | parent Q31 non résolu |" in (
        _section_du_rapport(texte, "Homonymes non rattachés — à confirmer"))


def test_un_pays_absent_du_yaml_ne_fait_pas_naitre_une_seconde_region(mocker, tmp_path):
    """C3 par une autre porte : le pays est en base avec son QID mais absent du YAML, donc
    jamais réapparié pendant le run. Amorcer sur le seul porteur du QID ferait passer la
    région rattachée à l'exemplaire sans QID pour mal placée, et la ferait recréer."""
    places = [_lieu("h_f1", "P0295", "France", "Country"),
              _lieu("h_f2", "P0386", "France", "Country",
                    urls=[{"path": "https://www.wikidata.org/wiki/Q142", "desc": "Wikidata"}]),
              _sous("h_f1", _lieu("h_ara", "P0400", "Auvergne-Rhône-Alpes", "Region"))]
    journal, _, _ = _lancer(mocker, tmp_path, places, pays=(), subdivisions=(ARA,))
    assert journal["posts"] == []                                  # aucune région créée
    assert journal["objets"]["h_ara"]["code"] == "ARA"             # l'existante est servie


def test_la_descendance_dun_homonyme_a_confirmer_nest_pas_creee(mocker, tmp_path):
    """Même règle que pour un doublon : sans son parent, l'enfant naîtrait à la racine."""
    ara = Subdivision(qid="Q18338206", iso="FR-ARA", code="ARA",
                      libelle_fr="Auvergne-Rhône-Alpes", noms=["Auvergne-Rhône-Alpes"],
                      place_type="Region", niveau=1, parent_qid="Q142")
    france = EntitePays(qid="Q142", libelle_fr="France", lat="46.2", long="2.2")
    places = [_lieu("h_ara", "P0400", "Auvergne-Rhône-Alpes", "Region")]
    journal, texte, _ = _lancer(mocker, tmp_path, places, pays=(france,),
                                subdivisions=(ara, RHONE.model_copy(update={"niveau": 2})))
    assert [p["name"]["value"] for p in journal["posts"]] == ["France"]
    assert "| FR-69 | Rhône | FR-ARA | homonyme non rattaché |" in (
        _section_du_rapport(texte, "Descendance bloquée"))


def test_les_deux_france_ne_font_pas_naitre_une_seconde_region(mocker, tmp_path):
    """Cas reproduit : QID sur la seconde `France`, régions sous la première. Comparer au
    seul handle élu refusait la région existante et en créait un second exemplaire sous
    l'autre France — la clause de parent produisait le doublon qu'elle voulait éviter."""
    ara = Subdivision(qid="Q18338206", iso="FR-ARA", code="ARA",
                      libelle_fr="Auvergne-Rhône-Alpes", noms=["Auvergne-Rhône-Alpes"],
                      place_type="Region", niveau=1, parent_qid="Q142", lat="45.7", long="4.8")
    france = EntitePays(qid="Q142", libelle_fr="France", lat="46.2", long="2.2")
    places = [_lieu("h_f1", "P0295", "France", "Country"),
              _lieu("h_f2", "P0386", "France", "Country",
                    urls=[{"path": "https://www.wikidata.org/wiki/Q142", "desc": "Wikidata"}]),
              _lieu("h_ara", "P0400", "Auvergne-Rhône-Alpes", "Region",
                    placeref_list=[{"ref": "h_f1"}])]
    journal, _, _ = _lancer(mocker, tmp_path, places, pays=(france,), subdivisions=(ara,))
    assert journal["posts"] == []                                  # aucune région créée
    assert journal["objets"]["h_ara"]["code"] == "ARA"             # l'existante est servie


def test_la_descendance_dun_doublon_ecarte_nest_pas_creee(mocker, tmp_path):
    """Le pays écarté ne résout plus aucun parent : ses régions naîtraient à la RACINE de
    l'arbre. Sur l'arbre réel, un doublon `France` en ferait ~119."""
    ara = Subdivision(qid="Q18338206", iso="FR-ARA", code="ARA",
                      libelle_fr="Auvergne-Rhône-Alpes", noms=["Auvergne-Rhône-Alpes"],
                      place_type="Region", niveau=1, parent_qid="Q142")
    rhone = RHONE.model_copy(update={"niveau": 2})
    france = EntitePays(qid="Q142", libelle_fr="France", lat="46.2", long="2.2")
    places = [_lieu("h_f1", "P0295", "France", "Country"),
              _lieu("h_f2", "P0386", "France", "Country")]
    doublons = [{"nom": "France", "place_type": "Country", "parent": "",
                 "gramps_ids": ["P0295", "P0386"], "handles": ["h_f1", "h_f2"]}]
    journal, texte, _ = _lancer(mocker, tmp_path, places, pays=(france,),
                                subdivisions=(ara, rhone), doublons=doublons)
    assert journal["posts"] == [] and journal["puts"] == []
    bloques = _section_du_rapport(texte, "Descendance bloquée")
    # La cascade nomme le doublon d'origine, pas le maillon intermédiaire.
    assert "| FR-ARA | Auvergne-Rhône-Alpes | FR | doublon de l'arbre |" in bloques
    assert "| FR-69 | Rhône | FR | doublon de l'arbre |" in bloques


def test_un_lieu_inexploitable_ne_recoit_rien_et_sort_au_rapport(mocker, tmp_path):
    """Un type illisible ne fait plus sauter le run : le lieu est écarté et nommé."""
    places = [_lieu("h_dz", "P0100", "Algérie", "Country"),
              _sous("h_dz", _lieu("h_sa", "P0900", "Souk Ahras", "Wilaya")),
              _sous("h_dz", _lieu("h_x", "P0901", "Souk Ahras", {"_class": "PlaceType"}))]
    journal, texte, _ = _lancer(mocker, tmp_path, places, pays=(ALGERIE,),
                                subdivisions=(SOUK,))
    assert "h_x" not in {p["handle"] for p in journal["puts"]}     # jamais écrit
    ecartes = _section_du_rapport(texte, "Lieux écartés de l'appariement")
    assert "P0901" in ecartes and "illisible" in ecartes


def test_un_lieu_nest_jamais_son_propre_parent(mocker, tmp_path):
    """Un YAML où une subdivision se déclare son propre parent ferait un cycle dans la
    hiérarchie des lieux : invisible en base, fatal à tout parcours de contenants."""
    boucle = VAUD.model_copy(update={"parent_qid": "Q12771"})
    places = [_lieu("h_vd", "P0500", "canton de Vaud", "State",
                    urls=[{"path": "https://www.wikidata.org/wiki/Q12771",
                           "desc": "Wikidata"}])]
    journal, texte, _ = _lancer(mocker, tmp_path, places, pays=(), subdivisions=(boucle,))
    assert [p for p in journal["puts"] if p["placeref_list"]] == []
    assert "parent identique au lieu lui-même" in texte


# --- le rapport est la seule trace d'audit d'une commande qui écrit ~430 lieux ----------

def test_le_rapport_liste_les_lieux_completes(mocker, tmp_path):
    places = [_lieu("h_ch", "P0340", "Suisse", "Country"),
              _sous("h_ch", _lieu("h_vd", "P0500", "canton de Vaud", "State"))]
    _, texte, _ = _lancer(mocker, tmp_path, places)
    assert "| CH-VD | canton de Vaud | State |" in texte


def test_le_rapport_liste_chaque_retypage(mocker, tmp_path):
    """Un retypage de masse — la table des types natifs ne correspond plus au serveur —
    doit sauter aux yeux, pas se cacher derrière un compteur."""
    places = [_lieu("h_dz", "P0100", "Algérie", "Country"),
              _sous("h_dz", _lieu("h_sa", "P0900", "Souk Ahras", "Wilaya"))]
    _, texte, _ = _lancer(mocker, tmp_path, places, pays=(ALGERIE,), subdivisions=(SOUK,))
    assert "| DZ-41 | Souk Ahras | Wilaya | Province |" in texte


def _panne_sur_le_canton(request):
    """Ne frappe que `h_vd` : le pays du même run doit s'écrire normalement, sans quoi le
    compte d'erreurs mesurerait la panne du harnais et non le canal d'erreur."""
    return (httpx.Response(500, text="boom")
            if request.method == "PUT" and request.url.path.endswith("h_vd") else None)


def test_le_rapport_porte_les_erreurs_dapi(mocker, tmp_path):
    places = [_lieu("h_ch", "P0340", "Suisse", "Country"),
              _sous("h_ch", _lieu("h_vd", "P0500", "canton de Vaud", "State"))]
    _, texte, _ = _lancer(mocker, tmp_path, places, panne=_panne_sur_le_canton)
    assert "- Erreurs : 1" in texte
    assert "CH-VD" in _section_du_rapport(texte, "Erreurs")
    assert "500" in texte


def test_un_message_derreur_multiligne_ne_casse_pas_le_tableau(mocker, tmp_path):
    """Un 500 rend un message sur plusieurs lignes ; tel quel il coupe le tableau en deux."""
    places = [_lieu("h_ch", "P0340", "Suisse", "Country"),
              _sous("h_ch", _lieu("h_vd", "P0500", "canton de Vaud", "State"))]
    _, texte, _ = _lancer(mocker, tmp_path, places, panne=_panne_sur_le_canton)
    corps = [ligne for ligne in texte.split("## Erreurs")[1].splitlines()
             if ligne.strip()]
    assert len(corps) == 3                       # en-tête, séparateur, UNE ligne d'erreur
    assert all(ligne.startswith("|") and ligne.endswith("|") for ligne in corps)


def test_le_rapport_signale_les_lieux_sans_parent_resolu(mocker, tmp_path):
    """Un rattachement manquant est une anomalie, pas un silence."""
    _, texte, _ = _lancer(mocker, tmp_path, [], pays=(), subdivisions=(VAUD,))
    assert "| CH-VD | Q39 |" in _section_du_rapport(texte, "Sans parent résolu")


def test_un_lieu_en_doublon_nest_pas_ecrit_et_est_signale(mocker, tmp_path):
    """`propose referentiel` a signalé les deux `France` : rien ne dit laquelle porte la
    vérité, donc aucune écriture (spec §5.4)."""
    places = [_lieu("h_f1", "P0295", "France", "Country"),
              _lieu("h_f2", "P0386", "France", "Country")]
    doublons = [{"nom": "France", "place_type": "Country", "parent": "",
                 "gramps_ids": ["P0295", "P0386"], "handles": ["h_f1", "h_f2"]}]
    france = EntitePays(qid="Q142", libelle_fr="France", lat="46.2", long="2.2")
    journal, texte, _ = _lancer(mocker, tmp_path, places, pays=(france,), subdivisions=(),
                                doublons=doublons)
    assert journal["puts"] == [] and journal["posts"] == []
    assert "P0295, P0386" in _section_du_rapport(
        texte, "Appariés sur un doublon de l'arbre")


def test_un_lieu_portant_un_autre_qid_est_refuse(mocker, tmp_path):
    """Un QID posé est une affirmation d'identité : diverger est une erreur, pas un ajout
    silencieux — au run suivant, l'ordre de la liste `urls` déciderait."""
    places = [_lieu("h_ch", "P0340", "Suisse", "Country"),
              _sous("h_ch", _lieu("h_vd", "P0500", "canton de Vaud", "State",
                                  urls=[{"path": "https://www.wikidata.org/wiki/Q1273",
                                         "desc": "Wikidata"}]))]
    journal, texte, _ = _lancer(mocker, tmp_path, places)
    assert [p for p in journal["puts"] if p["handle"] == "h_vd"] == []
    assert "Q1273" in texte and "Q12771" in texte


def test_une_place_malformee_narrete_pas_la_boucle(mocker, tmp_path):
    """Sinon les écritures déjà faites restent et aucun rapport n'est écrit."""
    places = [_lieu("h_ch", "P0340", "Suisse", "Country"),
              _lieu("h_de", "P0700", "Allemagne", "Country"),
              _sous("h_ch", _lieu("h_vd", "P0500", "canton de Vaud", "State",
                                  alt_names="Vaud")),
              _sous("h_de", _lieu("h_by", "P0600", "Bayern", "State"))]
    journal, texte, _ = _lancer(mocker, tmp_path, places, pays=(SUISSE, ALLEMAGNE),
                                subdivisions=(VAUD, BAYERN))
    assert "- Erreurs : 1" in texte
    assert "h_by" in {p["handle"] for p in journal["puts"]}   # la boucle a continué
    assert "h_vd" not in {p["handle"] for p in journal["puts"]}
