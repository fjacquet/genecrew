"""Enrichissement décès déterministe via MatchID (fichier INSEE 1970+) — zéro LLM.

Pour chaque personne née entre 1850 et aujourd'hui : requête MatchID, score déterministe
du meilleur candidat (crewai_custom_tools), puis selon l'état de l'arbre une proposition
typée — compléter (décès absent), confirmer (décès non sourcé concordant) ou contradiction
(dates divergentes). Un décès est une donnée cœur : toujours proposition, jamais d'écriture.
"""

from __future__ import annotations

import time
from datetime import date as _date
from pathlib import Path

import yaml

from crewai_custom_tools.tools.genealogy.gramps.client import GrampsClient
from crewai_custom_tools.tools.genealogy.gramps.facts import FactsFetcher
from crewai_custom_tools.tools.genealogy.matchid import score_deces_match, search_deces
from crewai_custom_tools.tools.genealogy.models.domain import PersonFacts
from crewai_custom_tools.tools.genealogy.pistes import event_iso, first_given

from genecrew.batching import iter_people_batches
from genecrew.logging_setup import get_logger
from genecrew.propositions import PropositionAudit

MIN_BIRTH_YEAR = 1850  # né avant → mort avant 1970 quasi certain, hors fichier
THROTTLE_S = 2.0  # espacement de base entre requêtes MatchID ; 0 dans les tests
BACKOFF_S = (15, 30, 30)  # attentes sur 422/429 — mesuré: seau ~5 req, recharge ~30 s
AMBIGUITY_MARGIN = 0.05  # 2 candidats trop proches -> on s'abstient (homonymes)
RESCUE_MIN_SCORE = 0.80  # plancher du repêchage "décès exact concorde" (mode source)


def is_candidate(person: PersonFacts, *, today_year: int) -> bool:
    """Eligible for a MatchID lookup: birth year in [1850, today], death missing OR
    unsourced (a sourced death needs nothing from us). Pure."""
    if person.birth is None or not person.birth.year:
        return False
    if not (MIN_BIRTH_YEAR <= person.birth.year <= today_year):
        return False
    return person.death is None or not person.death.has_citation


def _match_deces_iso(match: dict) -> str:
    raw = ((match.get("death") or {}).get("date") or "").strip()
    if len(raw) == 8:
        return f"{raw[:4]}-{raw[4:6]}-{raw[6:]}"
    return raw


def _match_url(match: dict) -> str:
    mid = match.get("id") or ""
    return f"https://deces.matchid.io/id/{mid}" if mid else "https://deces.matchid.io"


def _search_with_backoff(surname: str, first_name: str, birth_year: str) -> list[dict]:
    """search_deces with retry on rate-limit answers (MatchID replies 422 when the
    ~5-request bucket is empty; it refills in ~30 s)."""
    for i, wait in enumerate((*BACKOFF_S, None)):
        try:
            return search_deces(
                surname, first_name=first_name, birth_date=birth_year, limit=10
            )
        except Exception as exc:
            status = getattr(getattr(exc, "response", None), "status_code", None)
            if status in (422, 429) and wait is not None:
                get_logger().info(
                    "deces: quota MatchID (HTTP %s), retry dans %ss", status, wait
                )
                time.sleep(wait)
                continue
            raise
    raise RuntimeError("unreachable")


def _dates_concordent(tree: str, insee_iso: str) -> bool:
    """Tree date vs INSEE date: full-date equality when both full, else same year. Pure."""
    if not tree or not insee_iso:
        return False
    if len(tree) == 10 and len(insee_iso) == 10:
        return tree == insee_iso
    return tree[:4] == insee_iso[:4]


def build_deces_proposition(
    person: PersonFacts, match: dict, score: float, *, exact_birth: bool
) -> PropositionAudit:
    """One scored MatchID hit → the typed proposition. Pure."""
    insee_iso = _match_deces_iso(match)
    lieu = ((match.get("death") or {}).get("location") or {}).get("city", "")
    if isinstance(lieu, list):  # MatchID renvoie parfois une liste
        lieu = " / ".join(lieu)
    acte = (match.get("death") or {}).get("certificateId", "")
    # Référence d'archive complète : millésime du fichier INSEE + ligne + n° d'acte —
    # c'est ce qui rend la citation rejouable indépendamment de MatchID.
    fichier = match.get("source", "")
    ligne = match.get("sourceLine", "")
    detail = (
        f"Fichier des décès INSEE : {insee_iso}"
        + (f" à {lieu}" if lieu else "")
        + (f", acte {acte}" if acte else "")
        + (f" — fichier INSEE {fichier}" if fichier else "")
        + (f", ligne {ligne}" if ligne else "")
        + f" (score {score:.3f})."
    )
    confiance = 2 if exact_birth else 1

    if person.death is None:
        return PropositionAudit(
            type="date",
            gramps_id=person.gramps_id,
            handle=person.handle,
            personne=person.name,
            cible=f"décès de {person.gramps_id} (absent de l'arbre)",
            action=f"Renseigner le décès : {insee_iso}"
            + (f" à {lieu}" if lieu else "")
            + ", avec la source INSEE en citation.",
            preuve_url=_match_url(match),
            preuve_detail=detail,
            priorite="moyenne",
            confiance=confiance,
        )

    tree_iso = event_iso(person.death)
    if _dates_concordent(tree_iso, insee_iso):
        # Décès concordant au jour près = le vrai discriminateur d'homonymie.
        exact_death = len(tree_iso) == 10 and tree_iso == insee_iso
        return PropositionAudit(
            type="source",
            gramps_id=person.gramps_id,
            handle=person.handle,
            personne=person.name,
            cible=f"décès de {person.gramps_id} ({tree_iso}, sans source)",
            action="Ajouter la source INSEE (fichier des décès) en citation de l'événement "
            "décès existant — les dates concordent.",
            preuve_url=_match_url(match),
            preuve_detail=detail,
            priorite="basse",
            confiance=2 if (exact_death or confiance == 2) else 1,
        )

    return PropositionAudit(
        type="date",
        gramps_id=person.gramps_id,
        handle=person.handle,
        personne=person.name,
        cible=f"décès de {person.gramps_id} ({tree_iso} dans l'arbre)",
        action=f"Vérifier la date de décès : l'arbre dit {tree_iso}, l'INSEE dit "
        f"{insee_iso}" + (f" à {lieu}" if lieu else "") + ". Trancher sur pièce.",
        preuve_url=_match_url(match),
        preuve_detail=detail,
        priorite="haute",
        confiance=1,
    )


def render_deces_report(
    scope: str,
    date: str,
    props: list[PropositionAudit],
    *,
    candidates: int,
    queried: int,
    errors: int,
) -> str:
    """Markdown report. Pure."""
    by_type: dict[str, int] = {}
    for p in props:
        by_type[p.type] = by_type.get(p.type, 0) + 1
    lines = [
        f"# Enrichissement décès (INSEE/MatchID) — {scope}",
        "",
        f"- Date : {date}",
        "- Mode : lecture seule (un décès est une donnée cœur → propositions)",
        f"- Candidates (nées {MIN_BIRTH_YEAR}+, décès absent ou non sourcé) : {candidates}",
        f"- Interrogées : {queried} — erreurs API : {errors}",
        f"- Propositions : {len(props)} ({', '.join(f'{k}: {v}' for k, v in sorted(by_type.items())) or '—'})",
        "",
    ]
    if not props:
        lines.append("_Aucune correspondance au-dessus du seuil._")
        return "\n".join(lines) + "\n"
    lines.append("| Personne | Type | Priorité | Confiance | Action | Preuve |")
    lines.append("|---|---|---|---|---|---|")
    for p in props:
        lines.append(
            f"| {p.gramps_id} {p.personne} | {p.type} | {p.priorite} "
            f"| {p.confiance} | {p.action} | {p.preuve_url} |"
        )
    return "\n".join(lines) + "\n"


def run_deces(
    client: GrampsClient,
    scope: str,
    output_dir: Path,
    *,
    date: str,
    min_score: float = 0.90,
    batch_size: int = 25,
    limit: int | None = None,
) -> tuple[Path, Path]:
    """Scan `scope`, query MatchID for candidates, emit report + propositions YAML."""
    fetcher = FactsFetcher(client)
    today_year = _date.today().year
    props: list[PropositionAudit] = []
    candidates = queried = errors = 0

    for batch in iter_people_batches(client, fetcher, scope, batch_size, limit):
        for person in batch:
            if not is_candidate(person, today_year=today_year):
                continue
            candidates += 1
            birth_iso = event_iso(person.birth)
            try:
                if THROTTLE_S:
                    time.sleep(THROTTLE_S)
                matches = _search_with_backoff(
                    person.surname, first_given(person.given), birth_iso[:4]
                )
                queried += 1
            except Exception:
                errors += 1
                get_logger().warning(
                    "deces: échec MatchID pour %s", person.gramps_id, exc_info=True
                )
                continue
            scored = sorted(
                (
                    (m, score_deces_match(person.surname, person.given, birth_iso, m))
                    for m in matches
                ),
                key=lambda pair: pair[1],
                reverse=True,
            )
            scored = [(m, s) for m, s in scored if s > 0.0]
            if not scored:
                continue
            # Garde d'ambiguïté : deux candidats trop proches = homonymes, on s'abstient.
            if len(scored) >= 2 and scored[0][1] - scored[1][1] < AMBIGUITY_MARGIN:
                continue
            match, score = scored[0]
            # L'année seule plafonne à 0.85 (< seuil) : elle ne propose JAMAIS seule.
            # Repêchage uniquement quand le décès complet de l'arbre concorde à la
            # journée près avec l'INSEE — c'est alors la date de décès qui discrimine.
            tree_death = event_iso(person.death) if person.death else ""
            exact_death = len(tree_death) == 10 and tree_death == _match_deces_iso(
                match
            )
            if score < min_score and not (exact_death and score >= RESCUE_MIN_SCORE):
                continue
            props.append(
                build_deces_proposition(
                    person,
                    match,
                    score,
                    exact_birth=(len(birth_iso) == 10 and score >= 1.0),
                )
            )

    report = render_deces_report(
        scope, date, props, candidates=candidates, queried=queried, errors=errors
    )
    out = Path(output_dir) / "deces"
    out.mkdir(parents=True, exist_ok=True)
    slug = scope.replace(":", "_")
    report_path = out / f"{date}_deces_{slug}.md"
    report_path.write_text(report, encoding="utf-8")
    yaml_path = out / f"{date}_propositions_deces_{slug}.yaml"
    yaml_path.write_text(
        yaml.safe_dump(
            {"propositions": [p.model_dump() for p in props]},
            allow_unicode=True,
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    return report_path, yaml_path
