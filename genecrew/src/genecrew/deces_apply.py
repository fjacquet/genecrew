"""Application des propositions décès : citations de registres sur les événements existants.

Une source Gramps par registre (INSEE, ou chaque base Mémoire des hommes), déduite de
chaque proposition (`source_title_for`).

`genecrew deces-apply --propositions <yaml relu>` — patron `lieux-merge` : jamais auto,
la commande consomme le YAML que l'humain a relu. v1 : type `source` et confiance 2
uniquement (ajout d'une citation à l'événement décès EXISTANT — append-only). Les types
`date` (créer l'événement) restent manuels jusqu'à la v2. ADR 0011.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import yaml

from crewai_custom_tools.tools.genealogy.gramps.client import GrampsClient
from crewai_custom_tools.tools.genealogy.gramps.write_tools import (
    GrampsAttachCitationTool,
    GrampsCreateCitationTool,
    GrampsEnsureSourceTool,
    effective_dry_run,
)

from genecrew.propositions import PropositionsLot

SOURCE_TITLE = "INSEE — Fichier des personnes décédées"
_SCORE_RE = re.compile(r"\s*\(score [^)]*\)\.?\s*$")
_MDH_RE = re.compile(r"Mémoire des hommes \(([^)]+)\)")


def citation_page(preuve_detail: str, preuve_url: str) -> str:
    """Citation locator: the archive reference without the score, plus the URL. Pure."""
    cleaned = _SCORE_RE.sub("", preuve_detail or "").strip()
    return " — ".join(filter(None, [cleaned, preuve_url])).strip()


def source_title_for(preuve_detail: str) -> tuple[str, str]:
    """(title, author) of the Gramps source a proposition should cite. Pure.

    One source per register: INSEE, a Mémoire des hommes base, or the Gallica press.
    """
    m = _MDH_RE.search(preuve_detail or "")
    if m:
        return f"Mémoire des hommes — {m.group(1).strip()}", "Ministère des Armées"
    if "gallica" in (preuve_detail or "").lower():
        return ("Gallica (BnF) — presse numérisée",
                "Bibliothèque nationale de France")
    return SOURCE_TITLE, "INSEE"


def _death_event_handle(person: dict) -> str | None:
    idx = person.get("death_ref_index", -1)
    refs = person.get("event_ref_list") or []
    if idx is None or idx < 0 or idx >= len(refs):
        return None
    return (refs[idx] or {}).get("ref")


def _already_cited(client: GrampsClient, event: dict, source_handle: str) -> bool:
    for ch in event.get("citation_list") or []:
        try:
            citation = client.get_object("citations", ch)
        except Exception:
            continue
        if citation.get("source_handle") == source_handle:
            return True
    return False


def render_apply_report(date: str, applied: list, skipped: list, errors: list,
                        ignored: int, dry_run: bool) -> str:
    """Markdown report. Pure."""
    mode = "simulation (dry-run, aucune écriture)" if dry_run else "écritures appliquées"
    lines = [f"# Application des propositions décès (citations de registres) — {date}", "",
             f"Mode : {mode}.", "",
             f"- Citations posées : {len(applied)}",
             f"- Déjà citées (ignorées, idempotent) : {len(skipped)}",
             f"- Hors périmètre v1 (type ≠ source ou confiance < 2) : {ignored}",
             f"- Erreurs : {len(errors)}", ""]
    if applied:
        lines += ["| Personne | Événement | Citation |", "|---|---|---|"]
        lines += [f"| {gid} {name} | {ev} | {page[:80]} |" for gid, name, ev, page in applied]
    if errors:
        lines += ["", "## Erreurs", ""]
        lines += [f"- {gid} : {msg}" for gid, msg in errors]
    lines.append("")
    return "\n".join(lines)


def run_deces_apply(client: GrampsClient, propositions_yaml: Path, output_dir, *,
                    date: str, dry_run: bool = False) -> Path:
    """Apply reviewed death propositions: INSEE citations on existing death events."""
    dry_run = effective_dry_run(dry_run)
    data = yaml.safe_load(Path(propositions_yaml).read_text(encoding="utf-8")) or {}
    lot = PropositionsLot(**data)                   # validation stricte du YAML relu

    todo = [p for p in lot.propositions if p.type == "source" and p.confiance == 2]
    ignored = len(lot.propositions) - len(todo)

    source_handles: dict[str, str] = {}             # titre -> handle (une source/registre)

    def _ensure_source(title: str, author: str) -> str:
        if title not in source_handles:
            payload = json.loads(GrampsEnsureSourceTool()._run(
                title=title, author=author, dry_run=dry_run))
            if not payload["success"]:
                raise RuntimeError(f"source '{title}' : {payload['error']}")
            source_handles[title] = payload["data"]["handle"]
        return source_handles[title]

    applied, skipped, errors = [], [], []
    creator, attacher = GrampsCreateCitationTool(), GrampsAttachCitationTool()
    for prop in todo:
        title, author = source_title_for(prop.preuve_detail)
        source_handle = _ensure_source(title, author)
        try:
            person = client.get_object("people", prop.handle)
        except Exception:
            errors.append((prop.gramps_id, "personne introuvable"))
            continue
        event_handle = _death_event_handle(person)
        if not event_handle:
            errors.append((prop.gramps_id, "aucun événement décès sur la personne"))
            continue
        event = client.get_object("events", event_handle)
        if not dry_run and _already_cited(client, event, source_handle):
            skipped.append(prop.gramps_id)
            continue
        page = citation_page(prop.preuve_detail, prop.preuve_url)
        citation = json.loads(creator._run(source_handle=source_handle, page=page,
                                           dry_run=dry_run))
        if not citation["success"]:
            errors.append((prop.gramps_id, f"citation : {citation['error']}"))
            continue
        attach = json.loads(attacher._run(object_type="events", handle=event_handle,
                                          citation_handle=citation["data"]["handle"],
                                          dry_run=dry_run))
        if not attach["success"]:
            errors.append((prop.gramps_id, f"rattachement : {attach['error']}"))
            continue
        applied.append((prop.gramps_id, prop.personne,
                        event.get("gramps_id", event_handle), page))

    report = render_apply_report(date, applied, skipped, errors, ignored, dry_run)
    out = Path(output_dir) / "deces"
    out.mkdir(parents=True, exist_ok=True)
    report_path = out / f"{date}_apply_{Path(propositions_yaml).stem}.md"
    report_path.write_text(report, encoding="utf-8")
    return report_path
