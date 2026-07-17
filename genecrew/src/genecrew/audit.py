"""Deterministic audit engine: batches → rules → Markdown report (no LLM)."""

from __future__ import annotations

from pathlib import Path

from crewai_custom_tools.tools.genealogy.analysis.duplicates import find_duplicates
from crewai_custom_tools.tools.genealogy.analysis.rules import check_family, check_person
from crewai_custom_tools.tools.genealogy.gramps.client import GrampsClient

from genecrew.checkpoint import Checkpoint, load_checkpoint, save_checkpoint
from genecrew.facts import FactsFetcher
from genecrew.report import render_report
from genecrew.scope import resolve_handles


def _batches(items, size):
    for i in range(0, len(items), size):
        yield items[i:i + size]


def run_audit(
    client: GrampsClient, scope: str, output_dir: Path, *,
    date: str, batch_size: int = 25, limit: int | None = None, resume: bool = False,
) -> Path:
    """Run the deterministic audit over `scope` and write a Markdown report."""
    output_dir = Path(output_dir)
    cp_path = output_dir / "checkpoints" / f"audit_{scope.replace(':', '_')}.json"
    checkpoint = load_checkpoint(cp_path) if resume else None
    if checkpoint is None:
        checkpoint = Checkpoint(workflow="audit", scope=scope)

    fetcher = FactsFetcher(client)
    handles = resolve_handles(client, scope, limit=limit)

    anomalies = []
    all_people = []
    seen_families: set[str] = set()

    for batch in _batches(handles, batch_size):
        batch_people = []
        for handle, _gid in batch:
            if handle in checkpoint.done_handles:
                continue
            person = fetcher.get_person_facts(handle)
            if person is None:
                continue
            batch_people.append(person)
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
        checkpoint.done_handles.update(h for h, _ in batch)
        save_checkpoint(cp_path, checkpoint)

    duplicates = find_duplicates(all_people)
    report = render_report(scope, date, anomalies, duplicates, people_count=len(all_people))

    report_dir = output_dir / "audit"
    report_dir.mkdir(parents=True, exist_ok=True)
    report_path = report_dir / f"{date}_audit_{scope.replace(':', '_')}.md"
    report_path.write_text(report, encoding="utf-8")
    return report_path
