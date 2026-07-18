"""Name-casing standardization: iterate people, re-case names, report.

Casing is form, not a fact (spec §2), so changes are written directly under the
GrampsUpdateNameTool case-only invariant. Incomplete names ('?'/digits) are only
listed for human research.
"""

from __future__ import annotations

import json
from pathlib import Path

from crewai_custom_tools.tools.genealogy.gramps.client import GrampsClient
from crewai_custom_tools.tools.genealogy.gramps.write_tools import GrampsUpdateNameTool
from crewai_custom_tools.tools.genealogy.standardize.names import (
    is_incomplete_name,
    needs_normalization,
)

from genecrew.batching import iter_people_batches
from genecrew.facts import FactsFetcher


def _link(gramps_id: str, base_url: str) -> str:
    return f"[{gramps_id}]({base_url}/person/{gramps_id})"


def render_names_report(scope, date, results, incomplete, dry_run,
                        base_url="http://localhost") -> str:
    """Pure Markdown report of casing changes (applied or simulated)."""
    mode = "aperçu (dry-run, aucune écriture)" if dry_run else "écritures appliquées"
    rows = []
    for r in results:
        for c in r.get("changes", []):
            rows.append(f"| {_link(r['gramps_id'], base_url)} | {c['kind']} "
                        f"| {c['old']} | {c['new']} |")
    lines = [f"# Standardisation des noms — {scope} — {date}", "",
             f"Mode : {mode}.", "",
             f"- Personnes avec correction de casse : {len({r['gramps_id'] for r in results if r.get('changes')})}",
             f"- Corrections de casse : {len(rows)}", ""]
    lines.append("## Corrections de casse")
    lines.append("")
    if rows:
        lines += ["| Personne | Type | Avant | Après |", "|---|---|---|---|", *rows]
    else:
        lines.append("Aucune correction de casse.")
    lines.append("")
    lines.append("## Noms à vérifier (incomplets)")
    lines.append("")
    if incomplete:
        lines += ["| Personne | Type | Valeur |", "|---|---|---|"]
        for gid, label, value in incomplete:
            lines.append(f"| {_link(gid, base_url)} | {label} | {value} |")
    else:
        lines.append("Aucun nom incomplet.")
    lines.append("")
    return "\n".join(lines)


def render_incomplete_report(scope, date, incomplete, base_url="http://localhost") -> str:
    """Pure Markdown list of incomplete names ('?'/digits) — human research."""
    lines = [f"# Noms à vérifier (incomplets) — {scope} — {date}", "",
             f"- Noms « ? » ou à chiffres : {len(incomplete)}", ""]
    if incomplete:
        lines += ["| Personne | Champ | Valeur |", "|---|---|---|"]
        for gid, field, value in incomplete:
            lines.append(f"| [{gid}]({base_url}/person/{gid}) | {field} | {value} |")
    else:
        lines.append("Aucun nom incomplet.")
    lines.append("")
    return "\n".join(lines)


def run_names(client: GrampsClient, scope: str, output_dir: Path, *,
              date: str, batch_size: int = 25, limit: int | None = None,
              dry_run: bool = False) -> tuple[Path, Path]:
    """Re-case names over `scope`; write a changes report + an incomplete-names list."""
    output_dir = Path(output_dir)
    fetcher = FactsFetcher(client)
    tool = GrampsUpdateNameTool()
    results = []
    incomplete = []

    for batch in iter_people_batches(client, fetcher, scope, batch_size, limit):
        for person in batch:
            # prénom et nom restent des entrées SÉPARÉES et étiquetées
            for label, value in (("prénom", person.given), ("nom", person.surname)):
                if is_incomplete_name(value):
                    incomplete.append((person.gramps_id, label, value))
            if needs_normalization(person.given) or needs_normalization(person.surname):
                payload = json.loads(tool._run(handle=person.handle, dry_run=dry_run))
                if payload["success"]:
                    results.append(payload["data"])
                else:
                    results.append({"gramps_id": person.gramps_id, "changes": [],
                                    "error": payload["error"], "dry_run": dry_run})

    out = output_dir / "standardize"
    out.mkdir(parents=True, exist_ok=True)
    scope_slug = scope.replace(":", "_")
    report_path = out / f"{date}_noms_{scope_slug}.md"
    report_path.write_text(render_names_report(scope, date, results, incomplete, dry_run),
                           encoding="utf-8")
    incomplete_path = out / f"{date}_noms_a_verifier_{scope_slug}.md"
    incomplete_path.write_text(render_incomplete_report(scope, date, incomplete),
                               encoding="utf-8")
    return report_path, incomplete_path
