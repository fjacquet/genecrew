"""Pure Markdown rendering of an audit run (no I/O)."""

from __future__ import annotations

from crewai_custom_tools.tools.genealogy.models.domain import Anomaly, DuplicateCandidate

_SEVERITY_ORDER = {"haute": 0, "moyenne": 1, "basse": 2}


def _link(gramps_id: str, base_url: str) -> str:
    return f"[{gramps_id}]({base_url}/person/{gramps_id})"


def render_report(
    scope: str, date: str, anomalies: list[Anomaly],
    duplicates: list[DuplicateCandidate], people_count: int,
    base_url: str = "http://localhost",
) -> str:
    counts = {"haute": 0, "moyenne": 0, "basse": 0}
    for a in anomalies:
        counts[a.severity] = counts.get(a.severity, 0) + 1

    lines = [
        f"# Audit qualité — {scope} — {date}", "",
        "## Synthèse", "",
        f"- Personnes analysées : {people_count}",
        f"- Anomalies : {len(anomalies)} "
        f"({counts['haute']} haute, {counts['moyenne']} moyenne, {counts['basse']} basse)",
        f"- Candidats doublons : {len(duplicates)}", "",
    ]

    lines.append("## Anomalies")
    lines.append("")
    if anomalies:
        ordered = sorted(anomalies, key=lambda a: (_SEVERITY_ORDER.get(a.severity, 9), a.gramps_id))
        lines += ["| Personne | Sévérité | Règle | Détail |", "|---|---|---|---|"]
        for a in ordered:
            lines.append(f"| {_link(a.gramps_id, base_url)} | {a.severity} | {a.rule} | {a.message} |")
    else:
        lines.append("Aucune anomalie détectée.")
    lines.append("")

    lines.append("## Candidats doublons")
    lines.append("")
    if duplicates:
        lines += ["| Personne A | Personne B | Score | Motif |", "|---|---|---|---|"]
        for d in sorted(duplicates, key=lambda x: -x.score):
            lines.append(f"| {_link(d.gramps_id_a, base_url)} | {_link(d.gramps_id_b, base_url)} "
                         f"| {d.score} | {d.reason} |")
    else:
        lines.append("Aucun doublon candidat.")
    lines.append("")
    return "\n".join(lines)
