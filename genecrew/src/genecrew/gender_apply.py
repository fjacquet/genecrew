"""Apply gender corrections to Gramps (write) from live re-inference.

Unlike `genecrew gender` (read-only), this WRITES a fact: it re-infers each
person's sex from the INSEE+OFS table and, above a confidence threshold, sets
the gender in Gramps (fills unknowns, corrects contradictions). Bounded,
reversible, gated by dry_run + GENECREW_DRY_RUN (ADR 0009).
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path

from crewai_custom_tools.tools.genealogy.analysis.gender import infer_sex, load_prenoms_table
from crewai_custom_tools.tools.genealogy.gramps.client import GrampsClient
from crewai_custom_tools.tools.genealogy.gramps.write_tools import (
    GrampsUpdateGenderTool,
    effective_dry_run,
)

from genecrew.batching import iter_people_batches
from crewai_custom_tools.tools.genealogy.gramps.facts import FactsFetcher

_SEX_TO_INT = {"F": 0, "M": 1}
_INT_TO_SEX = {0: "F", 1: "M", 2: "U"}


def _link(gramps_id: str, base_url: str) -> str:
    return f"[{gramps_id}]({base_url}/person/{gramps_id})"


def render_apply_report(scope, date, applied, below, errors, dry_run,
                        base_url="http://localhost") -> str:
    """Pure Markdown report of gender writes (applied / below threshold / errors)."""
    mode = "simulation (dry-run, aucune écriture)" if dry_run else "écritures appliquées"
    lines = [f"# Application des corrections de genre — {scope} — {date}", "",
             f"Mode : {mode}.", "",
             f"- Genres écrits : {len(applied)}",
             f"- Sous le seuil (≥ 0.95 mais < seuil, non écrits) : {len(below)}",
             f"- Erreurs : {len(errors)}", "",
             "## Genres appliqués", ""]
    if applied:
        lines += ["| Personne | Nom | Type | Ancien | Nouveau | Ratio | Preuve |",
                  "|---|---|---|---|---|---|---|"]
        for gid, personne, typ, old_i, new_i, ratio, preuve in applied:
            lines.append(f"| {_link(gid, base_url)} | {personne} | {typ} | {_INT_TO_SEX[old_i]} "
                         f"| {_INT_TO_SEX[new_i]} | {ratio:.3f} | {preuve} |")
    else:
        lines.append("Aucune écriture.")
    lines += ["", "## Sous le seuil", ""]
    if below:
        lines += ["| Personne | Nom | Prénom | Sexe inféré | Ratio |", "|---|---|---|---|---|"]
        for gid, personne, given, sex, ratio in below:
            lines.append(f"| {_link(gid, base_url)} | {personne} | {given} | {sex} | {ratio:.3f} |")
    else:
        lines.append("Aucun.")
    lines += ["", "## Erreurs", ""]
    if errors:
        lines += ["| Personne | Erreur |", "|---|---|"]
        for gid, msg in errors:
            lines.append(f"| {_link(gid, base_url)} | {msg} |")
    else:
        lines.append("Aucune erreur.")
    lines.append("")
    return "\n".join(lines)


def run_gender_apply(client: GrampsClient, scope: str, output_dir, *, date: str,
                     min_ratio: float = 0.98, batch_size: int = 25,
                     limit: int | None = None, dry_run: bool = False,
                     table: Mapping[str, tuple[int, int]] | None = None) -> Path:
    """Re-infer sex live over `scope` and WRITE genders above `min_ratio`. Gated/reversible."""
    output_dir = Path(output_dir)
    if table is None:
        table = load_prenoms_table()
    fetcher = FactsFetcher(client)
    tool = GrampsUpdateGenderTool()
    applied: list = []
    below: list = []
    errors: list = []

    for batch in iter_people_batches(client, fetcher, scope, batch_size, limit):
        for p in batch:
            inf = infer_sex(p.given, table)
            if inf.sex is None:
                continue
            if not (p.sex == "U" or inf.sex != p.sex):
                continue                                        # déjà correct
            if inf.ratio < min_ratio:
                below.append((p.gramps_id, p.name, p.given, inf.sex, inf.ratio))
                continue
            typ = "genre_inconnu" if p.sex == "U" else "genre_contradiction"
            preuve = f"« {inf.key} » : {inf.ratio * 100:.1f}% {inf.sex} sur {inf.total} (INSEE+OFS)"
            payload = json.loads(tool._run(handle=p.handle,
                                           gender=_SEX_TO_INT[inf.sex], dry_run=dry_run))
            if payload["success"]:
                d = payload["data"]
                applied.append((p.gramps_id, p.name, typ, d["old"], d["new"], inf.ratio, preuve))
            else:
                errors.append((p.gramps_id, payload["error"]))

    out = output_dir / "inference"
    out.mkdir(parents=True, exist_ok=True)
    scope_slug = scope.replace(":", "_")
    path = out / f"{date}_genres_appliques_{scope_slug}.md"
    path.write_text(
        render_apply_report(scope, date, applied, below, errors, effective_dry_run(dry_run)),
        encoding="utf-8")
    return path
