"""Orchestrate the audit crew: deterministic findings → batches → LLM crew → report.

The deterministic engine (``collect_audit_findings``) does the detection; this module
groups the anomalies per person, feeds each batch to the two-agent crew, and renders a
Markdown + YAML report. Writes are gated by ``effective_dry_run``: when simulation is
in force we pin ``GENECREW_DRY_RUN=true`` so every tool the LLM calls simulates too.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path

import yaml

from crewai_custom_tools.tools.genealogy.gramps.client import GrampsClient
from crewai_custom_tools.tools.genealogy.gramps.write_tools import effective_dry_run

from genecrew.audit import collect_audit_findings
from genecrew.crew import Genecrew, PropositionsLot
from genecrew.logging_setup import get_logger


@dataclass(frozen=True)
class PersonAnomalies:
    """One flagged person and the anomalies detected on them."""

    gramps_id: str
    handle: str
    name: str
    anomalies: list  # list[Anomaly]


def group_anomalies_by_person(anomalies: list, people: list) -> list[PersonAnomalies]:
    """Group anomalies per person, preserving first-seen order; resolve names from
    ``people`` (list[PersonFacts]). Pure."""
    name_by_handle = {p.handle: p.name for p in people}
    order: list[str] = []
    by_handle: dict[str, PersonAnomalies] = {}
    for a in anomalies:
        entry = by_handle.get(a.handle)
        if entry is None:
            order.append(a.handle)
            entry = PersonAnomalies(
                gramps_id=a.gramps_id,
                handle=a.handle,
                name=name_by_handle.get(a.handle, a.gramps_id),
                anomalies=[],
            )
            by_handle[a.handle] = entry
        entry.anomalies.append(a)
    return [by_handle[h] for h in order]


def render_anomalies_block(persons: list[PersonAnomalies]) -> str:
    """Render a batch of flagged persons as the ``{anomalies_block}`` LLM input. Pure."""
    blocks = []
    for i, p in enumerate(persons, 1):
        lines = [f"Personne {i} — {p.name} (gramps_id={p.gramps_id}, handle={p.handle})"]
        for a in p.anomalies:
            lines.append(f"  - [{a.rule} / {a.severity}] {a.message}")
        blocks.append("\n".join(lines))
    return "\n\n".join(blocks)


def _chunk(items: list, size: int) -> list[list]:
    return [items[i:i + size] for i in range(0, len(items), size)]


def _parse_lot(text: str) -> PropositionsLot | None:
    """Parse a strict-JSON propositions object out of an LLM text. Pure, tolerant of
    markdown fences and surrounding prose; None when absent or schema-invalid."""
    if not text or "propositions" not in text:
        return None
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end <= start:
        return None
    try:
        data = json.loads(text[start:end + 1])
        return PropositionsLot(**data) if isinstance(data, dict) else None
    except Exception:                               # invalid JSON/schema → graceful
        return None


def extract_propositions(crew_output) -> tuple[list, bool]:
    """Pull the Standardisateur's PropositionsLot out of a CrewOutput.

    Order: native pydantic/json (future-proof) → strict-JSON parse of each task's raw
    text (the OpenRouter-compatible path) — always validated by the Pydantic schema.
    Returns (propositions, structured_ok); ([], False) lets the caller log and flag.
    """
    task_outputs = list(getattr(crew_output, "tasks_output", None) or [])
    for task_output in task_outputs:
        lot = getattr(task_output, "pydantic", None)
        if isinstance(lot, PropositionsLot):
            return list(lot.propositions), True
        json_dict = getattr(task_output, "json_dict", None)
        if isinstance(json_dict, dict) and "propositions" in json_dict:
            try:
                return list(PropositionsLot(**json_dict).propositions), True
            except Exception:                       # malformed → keep looking
                continue
    for task_output in task_outputs:
        lot = _parse_lot(getattr(task_output, "raw", "") or "")
        if lot is not None:
            return list(lot.propositions), True
    return [], False


def _usage_tokens(crew_output) -> int:
    """Best-effort total token count from a CrewOutput (0 if unavailable)."""
    usage = getattr(crew_output, "token_usage", None)
    if usage is None:
        return 0
    total = getattr(usage, "total_tokens", None)
    if total is not None:
        return int(total)
    if isinstance(usage, dict):
        return int(usage.get("total_tokens", 0))
    return 0


def render_crew_report(
    scope: str, date: str, batch_results: list[dict], *,
    dry_run: bool, n_persons: int, n_anomalies: int, n_propositions: int = 0,
) -> str:
    """Render the interpreted-audit Markdown report. Pure."""
    mode = "simulation (dry-run)" if dry_run else "écriture réelle"
    total_tokens = sum(b.get("tokens", 0) for b in batch_results)
    lines = [
        f"# Audit interprété par la crew — {scope}",
        "",
        f"- Date : {date}",
        f"- Mode : {mode}",
        f"- Personnes signalées : {n_persons}",
        f"- Anomalies déterministes : {n_anomalies}",
        f"- Propositions actionnables : {n_propositions}",
        f"- Lots traités : {len(batch_results)}",
        f"- Coût total (tokens) : {total_tokens}",
        "",
    ]
    if not batch_results:
        lines.append("_Aucune anomalie déterministe sur ce périmètre — rien à interpréter._")
        return "\n".join(lines) + "\n"
    for b in batch_results:
        lines.append(f"## Lot {b['index']} — {b['n_persons']} personne(s), {b['tokens']} tokens")
        lines.append("")
        if not b.get("structured", True):
            lines.append("> ⚠️ Sortie structurée du Standardisateur absente sur ce lot "
                         "(propositions non extraites).")
            lines.append("")
        lines.append(b["raw"] or "_(sortie vide)_")
        lines.append("")
    return "\n".join(lines) + "\n"


def run_crew_audit(
    client: GrampsClient, scope: str, output_dir: Path, *,
    date: str, batch_size: int = 25, limit: int | None = None, dry_run: bool = False,
    crew_factory=Genecrew,
) -> Path:
    """Run the audit crew over ``scope`` and write a Markdown report (+ YAML summary).

    ``crew_factory`` is injectable for offline tests; production uses ``Genecrew``.
    """
    output_dir = Path(output_dir)
    simulate = effective_dry_run(dry_run)
    if simulate:
        # Pin the global switch so tools the LLM calls without dry_run still simulate.
        os.environ["GENECREW_DRY_RUN"] = "true"

    report_dir = output_dir / "crew_audit"
    report_dir.mkdir(parents=True, exist_ok=True)
    slug = scope.replace(":", "_")
    # Durable crew trace (agents + tool calls), appended across batches. CrewAI's
    # FileHandler only accepts .txt/.json (anything else gets ".txt" appended).
    crew_log_path = report_dir / f"{date}_crew_audit_{slug}.log.txt"

    anomalies, _duplicates, all_people = collect_audit_findings(
        client, scope, batch_size=batch_size, limit=limit)
    persons = group_anomalies_by_person(anomalies, all_people)

    batch_results: list[dict] = []
    all_propositions: list = []
    for idx, batch in enumerate(_chunk(persons, batch_size), 1):
        crew = crew_factory().crew()
        crew.output_log_file = str(crew_log_path)
        try:
            crew_output = crew.kickoff(inputs={
                "anomalies_block": render_anomalies_block(batch),
                "date": date,
            })
        except Exception:
            # Un lot qui plante (fournisseur LLM, réseau...) ne tue pas le run.
            get_logger().exception("crew-audit lot %d : échec du kickoff", idx)
            batch_results.append({
                "index": idx, "n_persons": len(batch),
                "raw": "_Lot en échec (voir le log) — personnes non traitées._",
                "tokens": 0, "structured": False,
            })
            continue
        propositions, structured = extract_propositions(crew_output)
        if not structured:
            get_logger().warning(
                "crew-audit lot %d : sortie structurée du Standardisateur absente", idx)
        all_propositions.extend(propositions)
        batch_results.append({
            "index": idx,
            "n_persons": len(batch),
            "raw": getattr(crew_output, "raw", str(crew_output)),
            "tokens": _usage_tokens(crew_output),
            "structured": structured,
        })

    report = render_crew_report(
        scope, date, batch_results,
        dry_run=simulate, n_persons=len(persons), n_anomalies=len(anomalies),
        n_propositions=len(all_propositions))

    report_path = report_dir / f"{date}_crew_audit_{slug}.md"
    report_path.write_text(report, encoding="utf-8")

    # Propositions actionnables (relues par un humain) — toujours écrit, même vide.
    propositions_path = report_dir / f"{date}_propositions_audit_{slug}.yaml"
    propositions_path.write_text(
        yaml.safe_dump(
            {"propositions": [p.model_dump() for p in all_propositions]},
            allow_unicode=True, sort_keys=False),
        encoding="utf-8")

    summary = {
        "scope": scope, "date": date, "dry_run": simulate,
        "personnes_signalees": len(persons), "anomalies": len(anomalies),
        "propositions": len(all_propositions),
        "lots": [{"index": b["index"], "personnes": b["n_persons"], "tokens": b["tokens"]}
                 for b in batch_results],
        "tokens_total": sum(b["tokens"] for b in batch_results),
    }
    yaml_path = report_dir / f"{date}_crew_audit_{slug}.yaml"
    yaml_path.write_text(
        yaml.safe_dump(summary, allow_unicode=True, sort_keys=False), encoding="utf-8")
    return report_path
