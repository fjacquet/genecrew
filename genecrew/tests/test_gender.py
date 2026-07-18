"""Tests de l'inférence de genre : rendus purs + orchestration lecture seule."""

import yaml

from crewai_custom_tools.tools.genealogy.models.domain import Proposition

from genecrew.gender import render_gender_report, render_propositions_yaml

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
