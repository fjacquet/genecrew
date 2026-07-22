"""Enrichissement décès militaires (Mémoire des hommes, gazetteer local) — zéro LLM.

Même doctrine que `deces` (INSEE/MatchID) mais hors-ligne : candidates → matching
SQLite → score déterministe partagé (l'année seule ne suffit jamais) → propositions
relues. La preuve d'un match annoté est le permalien ark vers la fiche scannée.
"""

from __future__ import annotations

from datetime import date as _date
from pathlib import Path

import yaml

from crewai_custom_tools.tools.genealogy.gramps.client import GrampsClient
from crewai_custom_tools.tools.genealogy.gramps.facts import FactsFetcher
from crewai_custom_tools.tools.genealogy.militaires import match_militaires
from crewai_custom_tools.tools.genealogy.models.domain import PersonFacts

from genecrew.batching import iter_people_batches
from genecrew.deces import _dates_concordent, event_iso, is_candidate
from genecrew.logging_setup import get_logger
from genecrew.propositions import PropositionAudit

AMBIGUITY_MARGIN = 0.05
RESCUE_MIN_SCORE = 0.80


def build_militaire_proposition(
    person: PersonFacts, row: dict, score: float, *, exact_birth: bool
) -> PropositionAudit:
    """One scored register row → the typed proposition. Pure."""
    insee_iso = row.get("deces_date", "")
    lieu = row.get("deces_lieu", "")
    base = row.get("base", "Mémoire des hommes")
    detail = (
        f"Mémoire des hommes ({base}) : décès {insee_iso}"
        + (f" à {lieu}" if lieu else "")
        + (f" ; unité {row['unite']}" if row.get("unite") else "")
        + (f" ; réf. {row['reference']}" if row.get("reference") else "")
        + f" (score {score:.3f})."
    )
    confiance = 2 if (exact_birth and row.get("lien_ark")) else 1

    if person.death is None:
        return PropositionAudit(
            type="date",
            gramps_id=person.gramps_id,
            handle=person.handle,
            personne=person.name,
            cible=f"décès de {person.gramps_id} (absent de l'arbre)",
            action=f"Renseigner le décès militaire : {insee_iso}"
            + (f" à {lieu}" if lieu else "")
            + f" — {base}, avec la fiche Mémoire des hommes en citation.",
            preuve_url=row.get("lien_ark", ""),
            preuve_detail=detail,
            date_iso=insee_iso,
            lieu_nom=lieu,
            priorite="moyenne",
            confiance=confiance,
        )

    tree_iso = event_iso(person.death)
    if _dates_concordent(tree_iso, insee_iso):
        return PropositionAudit(
            type="source",
            gramps_id=person.gramps_id,
            handle=person.handle,
            personne=person.name,
            cible=f"décès de {person.gramps_id} ({tree_iso}, sans source)",
            action=f"Ajouter la source Mémoire des hommes ({base}) en citation de "
            "l'événement décès existant — les dates concordent.",
            preuve_url=row.get("lien_ark", ""),
            preuve_detail=detail,
            priorite="basse",
            confiance=confiance,
        )

    return PropositionAudit(
        type="date",
        gramps_id=person.gramps_id,
        handle=person.handle,
        personne=person.name,
        cible=f"décès de {person.gramps_id} ({tree_iso} dans l'arbre)",
        action=f"Vérifier la date de décès : l'arbre dit {tree_iso}, Mémoire des "
        f"hommes dit {insee_iso}"
        + (f" à {lieu}" if lieu else "")
        + ". Trancher sur la fiche.",
        preuve_url=row.get("lien_ark", ""),
        preuve_detail=detail,
        priorite="haute",
        confiance=1,
    )


def render_militaires_report(
    scope: str,
    date: str,
    props: list[PropositionAudit],
    *,
    candidates: int,
    errors: int,
) -> str:
    """Markdown report. Pure."""
    by_type: dict[str, int] = {}
    for p in props:
        by_type[p.type] = by_type.get(p.type, 0) + 1
    lines = [
        f"# Enrichissement décès militaires (Mémoire des hommes) — {scope}",
        "",
        f"- Date : {date}",
        "- Mode : lecture seule (donnée cœur → propositions ; gazetteer local, hors-ligne)",
        f"- Candidates : {candidates} — erreurs : {errors}",
        f"- Propositions : {len(props)} "
        f"({', '.join(f'{k}: {v}' for k, v in sorted(by_type.items())) or '—'})",
        "",
    ]
    if not props:
        lines.append("_Aucune correspondance au-dessus du seuil._")
        return "\n".join(lines) + "\n"
    lines.append("| Personne | Type | Priorité | Confiance | Action | Fiche |")
    lines.append("|---|---|---|---|---|---|")
    for p in props:
        lines.append(
            f"| {p.gramps_id} {p.personne} | {p.type} | {p.priorite} "
            f"| {p.confiance} | {p.action} | {p.preuve_url} |"
        )
    return "\n".join(lines) + "\n"


def run_militaires(
    client: GrampsClient,
    scope: str,
    output_dir,
    *,
    date: str,
    min_score: float = 0.90,
    batch_size: int = 25,
    limit: int | None = None,
) -> tuple[Path, Path]:
    """Scan `scope` against the local military gazetteer; emit report + YAML."""
    fetcher = FactsFetcher(client)
    today_year = _date.today().year
    props: list[PropositionAudit] = []
    candidates = errors = 0

    for batch in iter_people_batches(client, fetcher, scope, batch_size, limit):
        for person in batch:
            if not is_candidate(person, today_year=today_year):
                continue
            candidates += 1
            birth_iso = event_iso(person.birth)
            try:
                scored = match_militaires(person.surname, person.given, birth_iso)
            except FileNotFoundError:
                raise
            except Exception:
                errors += 1
                get_logger().warning(
                    "militaires: échec matching pour %s",
                    person.gramps_id,
                    exc_info=True,
                )
                continue
            if not scored:
                continue
            if len(scored) >= 2 and scored[0][1] - scored[1][1] < AMBIGUITY_MARGIN:
                continue  # homonymes trop proches: abstention
            row, score = scored[0]
            tree_death = event_iso(person.death) if person.death else ""
            exact_death = len(tree_death) == 10 and tree_death == row.get("deces_date")
            if score < min_score and not (exact_death and score >= RESCUE_MIN_SCORE):
                continue
            props.append(
                build_militaire_proposition(
                    person,
                    row,
                    score,
                    exact_birth=(len(birth_iso) == 10 and score >= 1.0),
                )
            )

    report = render_militaires_report(
        scope, date, props, candidates=candidates, errors=errors
    )
    out = Path(output_dir) / "militaires"
    out.mkdir(parents=True, exist_ok=True)
    slug = scope.replace(":", "_")
    report_path = out / f"{date}_militaires_{slug}.md"
    report_path.write_text(report, encoding="utf-8")
    yaml_path = out / f"{date}_propositions_militaires_{slug}.yaml"
    yaml_path.write_text(
        yaml.safe_dump(
            {"propositions": [p.model_dump() for p in props]},
            allow_unicode=True,
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    return report_path, yaml_path
