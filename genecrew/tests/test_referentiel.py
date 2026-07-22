# genecrew/tests/test_referentiel.py
"""Rendu du rapport et du YAML de `propose referentiel`. Pur, hors ligne."""
import yaml

from crewai_custom_tools.tools.genealogy.models.domain import CollisionIso, Subdivision
from crewai_custom_tools.tools.genealogy.referentiel.chargement import EntitePays, ResultatPays

from genecrew.referentiel import (
    doublons_de_larbre, render_referentiel_report, render_referentiel_yaml,
)

VAUD = Subdivision(qid="Q1273", iso="CH-VD", code="VD", libelle_fr="canton de Vaud",
                   place_type="State", niveau=1, parent_qid="Q39",
                   lat="46.6", long="6.6", frwiki="https://fr.wikipedia.org/wiki/Canton_de_Vaud")
SUISSE = EntitePays(qid="Q39", libelle_fr="Suisse", lat="46.8", long="8.2",
                    frwiki="https://fr.wikipedia.org/wiki/Suisse")


def test_le_rapport_compte_les_subdivisions_par_pays():
    md = render_referentiel_report("2026-07-21", [ResultatPays(code_iso="CH", subdivisions=[VAUD])],
                                   {"Q39": SUISSE}, [])
    assert "CH" in md and "canton de Vaud" in md
    assert "State" in md


def test_doublons_de_larbre_repere_deux_lieux_identiques():
    """Le cas des deux `France` : même nom, même type, même parent. L'index chemin -> handle
    de places_apply écrase silencieusement la clé, donc rien ne les signalait."""
    places = [
        {"handle": "h1", "gramps_id": "P0295", "name": {"value": "France"},
         "place_type": "Country", "placeref_list": []},
        {"handle": "h2", "gramps_id": "P0386", "name": {"value": "France"},
         "place_type": "Country", "placeref_list": []},
        {"handle": "h3", "gramps_id": "P0340", "name": {"value": "Suisse"},
         "place_type": "Country", "placeref_list": []},
    ]
    doublons = doublons_de_larbre(places)
    assert len(doublons) == 1
    assert doublons[0]["nom"] == "France"
    assert sorted(doublons[0]["gramps_ids"]) == ["P0295", "P0386"]


def test_deux_homonymes_sous_des_parents_differents_ne_sont_pas_des_doublons():
    places = [
        {"handle": "a", "gramps_id": "P1", "name": {"value": "Saint-Jean"},
         "place_type": "Municipality", "placeref_list": [{"ref": "p1"}]},
        {"handle": "b", "gramps_id": "P2", "name": {"value": "Saint-Jean"},
         "place_type": "Municipality", "placeref_list": [{"ref": "p2"}]},
    ]
    assert doublons_de_larbre(places) == []


def test_le_rapport_signale_les_doublons_de_larbre():
    md = render_referentiel_report(
        "2026-07-21", [], {},
        [{"nom": "France", "place_type": "Country", "gramps_ids": ["P0295", "P0386"]}])
    assert "P0295" in md and "P0386" in md
    assert "merge places" in md          # la fusion reste manuelle


def test_le_rapport_signale_les_collisions_sans_les_ecrire():
    collision = CollisionIso(iso="FR-69", qids=["Q46130", "Q18914778"],
                             libelles=["Rhône", "Rhône"])
    md = render_referentiel_report(
        "2026-07-21", [ResultatPays(code_iso="FR", collisions=[collision])], {}, [])
    assert "FR-69" in md
    assert "Q46130" in md and "Q18914778" in md


def test_le_rapport_nomme_les_pays_en_echec():
    md = render_referentiel_report(
        "2026-07-21", [ResultatPays(code_iso="IT", erreur="504 Gateway Timeout")], {}, [])
    assert "IT" in md and "504" in md


def test_le_yaml_porte_les_subdivisions_et_les_pays():
    doc = yaml.safe_load(render_referentiel_yaml(
        [ResultatPays(code_iso="CH", subdivisions=[VAUD])], {"Q39": SUISSE}, []))
    assert doc["pays"][0]["qid"] == "Q39"
    assert doc["subdivisions"][0]["iso"] == "CH-VD"
    assert doc["subdivisions"][0]["place_type"] == "State"
    assert doc["subdivisions"][0]["parent_qid"] == "Q39"


def test_le_yaml_ne_contient_pas_les_collisions_dans_les_subdivisions():
    collision = CollisionIso(iso="FR-69", qids=["Q46130", "Q18914778"],
                             libelles=["Rhône", "Rhône"])
    doc = yaml.safe_load(render_referentiel_yaml(
        [ResultatPays(code_iso="FR", subdivisions=[], collisions=[collision])], {}, []))
    assert doc["subdivisions"] == []
    assert doc["collisions"][0]["iso"] == "FR-69"
