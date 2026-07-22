from crewai_custom_tools.tools.genealogy.models.domain import (
    Anomaly,
    DuplicateCandidate,
)
from genecrew.report import render_report


def _a(rule, sev, gid, msg):
    return Anomaly(rule=rule, severity=sev, gramps_id=gid, handle=gid, message=msg)


def test_report_orders_by_severity_and_counts():
    anoms = [
        _a("R9", "basse", "I3", "sans source"),
        _a("R1", "haute", "I1", "naissance après décès"),
        _a("R6", "moyenne", "I2", "événement hors vie"),
    ]
    out = render_report("all", "2026-07-17", anoms, [], people_count=3)
    assert "# Audit qualité" in out
    # la ligne haute apparaît avant la moyenne, qui apparaît avant la basse
    assert out.index("I1") < out.index("I2") < out.index("I3")
    assert "1 haute" in out and "1 moyenne" in out and "1 basse" in out


def test_report_includes_person_links_and_duplicates():
    dups = [
        DuplicateCandidate(
            gramps_id_a="I1", gramps_id_b="I2", score=0.92, reason="homonymes"
        )
    ]
    out = render_report("all", "2026-07-17", [], dups, people_count=2)
    assert "http://localhost/person/I1" in out
    assert "0.92" in out


def test_report_empty_is_clean():
    out = render_report("branch:I0042", "2026-07-17", [], [], people_count=0)
    assert "Aucune anomalie" in out
