"""Tests de l'inférence de genre : rendus purs + orchestration lecture seule."""

import httpx
import yaml

from crewai_custom_tools.tools.genealogy.gramps.client import GrampsClient, GrampsConfig
from crewai_custom_tools.tools.genealogy.models.domain import Proposition

from genecrew.gender import render_gender_report, render_propositions_yaml, run_gender

_P_CONTRA = Proposition(
    type="genre_contradiction", gramps_id="I0002", handle="h2", personne="Marguerite Dupont",
    valeur_actuelle="M", valeur_proposee="F",
    preuve="prénom « MARGUERITE » : 99.9% F sur 12000 (INSEE+OFS)",
    confiance="haute", priorite="haute",
)
_P_INCONNU = Proposition(
    type="genre_inconnu", gramps_id="I0001", handle="h1", personne="Suzanne Martin",
    valeur_actuelle="U", valeur_proposee="F",
    preuve="prénom « SUZANNE » : 99.0% F sur 10000 (INSEE+OFS)",
    confiance="moyenne", priorite="moyenne",
)


def test_render_report_orders_and_links():
    md = render_gender_report(
        "all", "2026-07-18", [_P_INCONNU, _P_CONTRA],
        [("I0003", "Dominique", "unisexe/rare")], people_count=42)
    assert "# Inférence de genre — all — 2026-07-18" in md
    assert "[I0001](http://localhost/person/I0001)" in md
    # priorité haute (contradiction) listée avant la moyenne (inconnu)
    assert md.index("I0002") < md.index("I0001")
    assert "## Indécidables" in md and "Dominique" in md


def test_render_yaml_roundtrips():
    text = render_propositions_yaml([_P_CONTRA, _P_INCONNU])
    back = [Proposition(**d) for d in yaml.safe_load(text)]
    assert back == [_P_CONTRA, _P_INCONNU]


CONFIG = GrampsConfig(api_url="http://g.test/api", username="u", password="p")

PEOPLE = [
    {"handle": "h1", "gramps_id": "I0001", "gender": 2,          # inconnu -> F
     "primary_name": {"first_name": "Suzanne", "surname_list": [{"surname": "Martin"}]}},
    {"handle": "h2", "gramps_id": "I0002", "gender": 1,          # M mais prénom F -> contradiction
     "primary_name": {"first_name": "Marguerite", "surname_list": [{"surname": "Dupont"}]}},
    {"handle": "h3", "gramps_id": "I0003", "gender": 2,          # inconnu, unisexe -> indécidable
     "primary_name": {"first_name": "Dominique", "surname_list": [{"surname": "Roy"}]}},
    {"handle": "h4", "gramps_id": "I0004", "gender": 0,          # F et prénom F -> rien
     "primary_name": {"first_name": "Suzanne", "surname_list": [{"surname": "Blanc"}]}},
    {"handle": "h5", "gramps_id": "I0005", "gender": 2,          # inconnu, ratio 0.96 -> confiance moyenne
     "primary_name": {"first_name": "Camille", "surname_list": [{"surname": "Petit"}]}},
]

TABLE = {"SUZANNE": (9990, 10), "MARGUERITE": (11988, 12), "DOMINIQUE": (5000, 5000),
         "CAMILLE": (96, 4)}


def _readonly_handler(request):
    if request.url.path == "/api/token/":
        return httpx.Response(200, json={"access_token": "t"})
    if request.method == "GET" and request.url.path == "/api/people/":
        page = int(request.url.params.get("page", "1"))
        return httpx.Response(200, json=PEOPLE if page == 1 else [])
    if request.method in ("PUT", "POST"):
        raise AssertionError("lecture seule : aucune écriture attendue")
    return httpx.Response(404)


def test_run_gender_is_read_only_and_classifies(tmp_path):
    client = GrampsClient(CONFIG, transport=httpx.MockTransport(_readonly_handler))
    report, proposals = run_gender(
        client, "all", tmp_path, date="2026-07-18", batch_size=25, table=TABLE)

    props = yaml.safe_load(proposals.read_text(encoding="utf-8"))
    by_id = {p["gramps_id"]: p for p in props}
    assert by_id["I0001"]["type"] == "genre_inconnu" and by_id["I0001"]["valeur_proposee"] == "F"
    assert by_id["I0002"]["type"] == "genre_contradiction"
    assert by_id["I0002"]["valeur_actuelle"] == "M" and by_id["I0002"]["valeur_proposee"] == "F"
    assert "I0003" not in by_id and "I0004" not in by_id     # indécidable / correct
    assert by_id["I0002"]["priorite"] == "haute"             # contradiction -> haute
    assert by_id["I0001"]["priorite"] == "moyenne"           # genre inconnu -> moyenne
    assert by_id["I0001"]["confiance"] == "haute"            # ratio 99.9% >= 0.99
    assert by_id["I0005"]["type"] == "genre_inconnu"
    assert by_id["I0005"]["confiance"] == "moyenne"          # ratio 0.96 dans [0.95, 0.99)
    md = report.read_text(encoding="utf-8")
    assert "Dominique" in md                                 # I0003 listé en indécidable
