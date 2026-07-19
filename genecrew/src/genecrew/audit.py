"""Deterministic audit engine: batches → rules → Markdown report (no LLM)."""

from __future__ import annotations

from pathlib import Path

from crewai_custom_tools.tools.genealogy.analysis.duplicates import find_duplicates
from crewai_custom_tools.tools.genealogy.analysis.rules import check_family, check_person
from crewai_custom_tools.tools.genealogy.gramps.client import GrampsClient

from genecrew.batching import iter_people_batches
from crewai_custom_tools.tools.genealogy.gramps.facts import FactsFetcher
from genecrew.report import render_report


def collect_audit_findings(
    client: GrampsClient, scope: str, *, batch_size: int = 25, limit: int | None = None,
) -> tuple[list, list, list]:
    """Run the deterministic rules over `scope` and return the STRUCTURED findings
    `(anomalies, duplicates, all_people)` in memory — the crew consumes these directly
    (no Markdown parsing). `run_audit` reuses this, then renders the report."""
    fetcher = FactsFetcher(client)

    anomalies = []
    all_people = []
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
                for h in filter(None, [family.father_handle, family.mother_handle,
                                        *family.child_handles]):
                    pf = fetcher.get_person_facts(h)
                    if pf is not None:
                        related[h] = pf
                anomalies.extend(check_family(family, related))

        all_people.extend(batch_people)

    duplicates = find_duplicates(all_people)
    return anomalies, duplicates, all_people


def run_audit(
    client: GrampsClient, scope: str, output_dir: Path, *,
    date: str, batch_size: int = 25, limit: int | None = None,
) -> Path:
    """Run the deterministic audit over `scope` and write a Markdown report."""
    output_dir = Path(output_dir)
    anomalies, duplicates, all_people = collect_audit_findings(
        client, scope, batch_size=batch_size, limit=limit)
    report = render_report(scope, date, anomalies, duplicates, people_count=len(all_people))

    report_dir = output_dir / "audit"
    report_dir.mkdir(parents=True, exist_ok=True)
    report_path = report_dir / f"{date}_audit_{scope.replace(':', '_')}.md"
    report_path.write_text(report, encoding="utf-8")
    return report_path
