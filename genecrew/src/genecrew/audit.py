"""Deterministic audit engine: batches → rules → Markdown report (no LLM)."""

from __future__ import annotations

from pathlib import Path

import yaml
from crewai_custom_tools.tools.genealogy.analysis.corrections import (
    suggest_century_typo,
    suggest_misattached_parent_event,
)
from crewai_custom_tools.tools.genealogy.analysis.duplicates import find_duplicates
from crewai_custom_tools.tools.genealogy.analysis.rules import (
    check_family,
    check_person,
)
from crewai_custom_tools.tools.genealogy.gramps.client import GrampsClient
from crewai_custom_tools.tools.genealogy.gramps.facts import FactsFetcher

from genecrew.batching import iter_people_batches
from genecrew.report import render_report


def collect_audit_findings(
    client: GrampsClient,
    scope: str,
    *,
    batch_size: int = 25,
    limit: int | None = None,
) -> tuple[list, list, list, list]:
    """Run the deterministic rules over `scope` and return the STRUCTURED findings
    `(anomalies, duplicates, all_people, propositions)` in memory — the crew consumes
    these directly (no Markdown parsing). The D-rule correction detectors run inside
    the family loop (parents + siblings already loaded, zero extra fetch)."""
    fetcher = FactsFetcher(client)

    anomalies = []
    all_people = []
    propositions = []
    seen_props: set[tuple] = set()
    seen_families: set[str] = set()

    for batch_people in iter_people_batches(client, fetcher, scope, batch_size, limit):
        for person in batch_people:
            anomalies.extend(check_person(person))

        for person in batch_people:
            for fam_handle in person.parent_family_handles:
                if fam_handle in seen_families:
                    continue
                seen_families.add(fam_handle)
                family = fetcher.get_family_facts(fam_handle)
                if family is None:
                    continue
                related = {}
                for h in filter(
                    None,
                    [family.father_handle, family.mother_handle, *family.child_handles],
                ):
                    pf = fetcher.get_person_facts(h)
                    if pf is not None:
                        related[h] = pf
                anomalies.extend(check_family(family, related))

                # Règles D : détecteurs de corrections sur le contexte déjà chargé.
                parents = [
                    p
                    for p in (
                        related.get(family.father_handle),
                        related.get(family.mother_handle),
                    )
                    if p
                ]
                children = [related[h] for h in family.child_handles if h in related]
                for child in children:
                    for prop in (
                        suggest_misattached_parent_event(child, [family]),
                        suggest_century_typo(child, family, parents, children),
                    ):
                        if prop is None:
                            continue
                        key = (prop.gramps_id, prop.type, prop.cible)
                        if key not in seen_props:
                            seen_props.add(key)
                            propositions.append(prop)

        all_people.extend(batch_people)

    duplicates = find_duplicates(all_people)
    return anomalies, duplicates, all_people, propositions


def run_audit(
    client: GrampsClient,
    scope: str,
    output_dir: Path,
    *,
    date: str,
    batch_size: int = 25,
    limit: int | None = None,
) -> Path:
    """Run the deterministic audit over `scope`; write the Markdown report and the
    D-rule propositions YAML (human-reviewed) alongside it."""
    output_dir = Path(output_dir)
    anomalies, duplicates, all_people, propositions = collect_audit_findings(
        client, scope, batch_size=batch_size, limit=limit
    )
    report = render_report(
        scope, date, anomalies, duplicates, people_count=len(all_people)
    )

    report_dir = output_dir / "audit"
    report_dir.mkdir(parents=True, exist_ok=True)
    slug = scope.replace(":", "_")
    report_path = report_dir / f"{date}_audit_{slug}.md"
    report_path.write_text(report, encoding="utf-8")

    yaml_path = report_dir / f"{date}_propositions_audit_deterministes_{slug}.yaml"
    yaml_path.write_text(
        yaml.safe_dump(
            {"propositions": [p.model_dump() for p in propositions]},
            allow_unicode=True,
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    return report_path
