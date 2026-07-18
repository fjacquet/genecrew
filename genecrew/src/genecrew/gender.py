"""Gender-inference orchestration: read people, infer sex, emit Propositions.

Read-only: gender is a FACT, so every inference becomes a Proposition for human
review (Markdown report + YAML). This module never writes to Gramps.
"""

from __future__ import annotations

import yaml

from crewai_custom_tools.tools.genealogy.models.domain import Proposition

_PRIORITE_ORDER = {"haute": 0, "moyenne": 1}


def _link(gramps_id: str, base_url: str) -> str:
    return f"[{gramps_id}]({base_url}/person/{gramps_id})"


def _confiance(ratio: float) -> str:
    return "haute" if ratio >= 0.99 else "moyenne"


def render_gender_report(scope, date, propositions, indecidables, people_count,
                         base_url="http://localhost") -> str:
    """Pure Markdown report: proposals (priority-sorted) + indécidables."""
    props = sorted(propositions, key=lambda p: _PRIORITE_ORDER.get(p.priorite, 9))
    n_inconnu = sum(1 for p in propositions if p.type == "genre_inconnu")
    n_contra = sum(1 for p in propositions if p.type == "genre_contradiction")
    lines = [f"# Inférence de genre — {scope} — {date}", "",
             "## Synthèse", "",
             f"- Personnes analysées : {people_count}",
             f"- Propositions : {len(propositions)} "
             f"({n_contra} contradiction, {n_inconnu} genre inconnu)",
             f"- Indécidables (genre inconnu, prénom non tranchable) : {len(indecidables)}",
             "", "## Propositions", ""]
    if props:
        lines += ["| Personne | Type | Actuel | Proposé | Confiance | Priorité | Preuve |",
                  "|---|---|---|---|---|---|---|"]
        for p in props:
            lines.append(
                f"| {_link(p.gramps_id, base_url)} | {p.type} | {p.valeur_actuelle} "
                f"| {p.valeur_proposee} | {p.confiance} | {p.priorite} | {p.preuve} |")
    else:
        lines.append("Aucune proposition.")
    lines += ["", "## Indécidables", ""]
    if indecidables:
        lines += ["| Personne | Prénom | Raison |", "|---|---|---|"]
        for gid, prenom, raison in indecidables:
            lines.append(f"| {_link(gid, base_url)} | {prenom} | {raison} |")
    else:
        lines.append("Aucun indécidable.")
    lines.append("")
    return "\n".join(lines)


def render_propositions_yaml(propositions: list[Proposition]) -> str:
    """Serialize propositions to YAML (machine-readable, for a future apply step)."""
    return yaml.safe_dump([p.model_dump() for p in propositions],
                          allow_unicode=True, sort_keys=False)
