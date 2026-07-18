"""Deterministic audit engine: batches → rules → Markdown report (no LLM)."""

from __future__ import annotations

from pathlib import Path

from crewai_custom_tools.tools.genealogy.analysis.duplicates import find_duplicates
from crewai_custom_tools.tools.genealogy.analysis.rules import check_family, check_person
from crewai_custom_tools.tools.genealogy.gramps.client import GrampsClient

from genecrew.facts import FactsFetcher
from genecrew.report import render_report
from genecrew.scope import parse_scope, resolve_handles


def _people_batches(client, fetcher, scope, batch_size, limit):
    """Yield successive batches of PersonFacts for `scope`.

    'all' is bulk-fetched one page (=batch_size) per HTTP call via
    list_people_facts; 'person:' resolves and fetches the single person;
    'branch:' raises NotImplementedError (via resolve_handles).
    """
    kind, _gid = parse_scope(scope)
    if kind != "all":
        handles = resolve_handles(client, scope)
        people = [p for h, _ in handles
                  if (p := fetcher.get_person_facts(h)) is not None]
        if people:
            yield people
        return
    fetched = 0
    page = 1
    while True:
        people = fetcher.list_people_facts(page, batch_size)
        if not people:
            break
        if limit is not None and fetched + len(people) > limit:
            people = people[: limit - fetched]
        yield people
        fetched += len(people)
        if limit is not None and fetched >= limit:
            break
        page += 1


def run_audit(
    client: GrampsClient, scope: str, output_dir: Path, *,
    date: str, batch_size: int = 25, limit: int | None = None,
) -> Path:
    """Run the deterministic audit over `scope` and write a Markdown report."""
    output_dir = Path(output_dir)
    fetcher = FactsFetcher(client)

    anomalies = []
    all_people = []
    seen_families: set[str] = set()

    for batch_people in _people_batches(client, fetcher, scope, batch_size, limit):
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
    report = render_report(scope, date, anomalies, duplicates, people_count=len(all_people))

    report_dir = output_dir / "audit"
    report_dir.mkdir(parents=True, exist_ok=True)
    report_path = report_dir / f"{date}_audit_{scope.replace(':', '_')}.md"
    report_path.write_text(report, encoding="utf-8")
    return report_path
