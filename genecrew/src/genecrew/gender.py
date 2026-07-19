"""Gender-inference orchestration: read people, infer sex, emit Propositions.

Read-only: gender is a FACT, so every inference becomes a Proposition for human
review (Markdown report + YAML). This module never writes to Gramps.
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

import yaml

from crewai_custom_tools.tools.genealogy.analysis.gender import infer_sex, load_prenoms_table
from crewai_custom_tools.tools.genealogy.gramps.client import GrampsClient
from crewai_custom_tools.tools.genealogy.models.domain import Proposition

from genecrew.batching import iter_people_batches
from crewai_custom_tools.tools.genealogy.gramps.facts import FactsFetcher

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


def _build_proposition(person, inf) -> Proposition:
    preuve = (f"prénom « {inf.key} » : {inf.ratio * 100:.1f}% "
              f"{inf.sex} sur {inf.total} naissances (INSEE+OFS)")
    if person.sex == "U":
        return Proposition(
            type="genre_inconnu", gramps_id=person.gramps_id, handle=person.handle,
            personne=person.name, valeur_actuelle="U", valeur_proposee=inf.sex,
            preuve=preuve, confiance=_confiance(inf.ratio), priorite="moyenne")
    return Proposition(
        type="genre_contradiction", gramps_id=person.gramps_id, handle=person.handle,
        personne=person.name, valeur_actuelle=person.sex, valeur_proposee=inf.sex,
        preuve=preuve, confiance=_confiance(inf.ratio), priorite="haute")


def run_gender(client: GrampsClient, scope: str, output_dir, *, date: str,
               batch_size: int = 25, limit: int | None = None,
               table: Mapping[str, tuple[int, int]] | None = None) -> tuple[Path, Path]:
    """Infer sex over `scope`; write a Markdown report + a YAML proposals file. Read-only."""
    output_dir = Path(output_dir)
    if table is None:
        table = load_prenoms_table()
    fetcher = FactsFetcher(client)
    propositions: list[Proposition] = []
    indecidables: list[tuple[str, str, str]] = []
    people_count = 0

    for batch in iter_people_batches(client, fetcher, scope, batch_size, limit):
        for person in batch:
            people_count += 1
            inf = infer_sex(person.given, table)
            if inf.sex is None:
                if person.sex == "U" and person.given.strip():
                    raison = "unisexe/rare" if inf.total else "non couvert"
                    indecidables.append((person.gramps_id, person.given, raison))
                continue
            if person.sex == "U" or inf.sex != person.sex:
                propositions.append(_build_proposition(person, inf))

    out = output_dir / "inference"
    out.mkdir(parents=True, exist_ok=True)
    scope_slug = scope.replace(":", "_")
    report_path = out / f"{date}_genres_{scope_slug}.md"
    report_path.write_text(
        render_gender_report(scope, date, propositions, indecidables, people_count),
        encoding="utf-8")
    yaml_path = out / f"{date}_propositions_genre_{scope_slug}.yaml"
    yaml_path.write_text(render_propositions_yaml(propositions), encoding="utf-8")
    return report_path, yaml_path
