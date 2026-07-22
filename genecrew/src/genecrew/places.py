"""Read-only places standardization: parse, resolve, emit proposals. Never writes."""

from __future__ import annotations

from pathlib import Path

import httpx
import yaml
from crewai_custom_tools.tools.genealogy.geo.registry import (
    confiance_of,
    decide_action,
    resolve_place,
)
from crewai_custom_tools.tools.genealogy.gramps.client import GrampsClient
from crewai_custom_tools.tools.genealogy.models.domain import PlaceProposition
from crewai_custom_tools.tools.genealogy.standardize.places import parse_pname

from genecrew.batching import iter_places

_PRIORITE = {"haute": 0, "moyenne": 1, "basse": 2}


def _link(gramps_id: str, base_url: str) -> str:
    return f"[{gramps_id}]({base_url}/place/{gramps_id})"


def build_proposition(place: dict, min_score: float) -> PlaceProposition:
    """Parse + resolve one raw Gramps place into a PlaceProposition. A geocoder HTTP error
    (503, timeout, connexion…) sur un lieu est capturé : le lieu devient indécidable et le
    run se poursuit — un seul géocodage défaillant ne doit pas faire tomber tout le lot."""
    original = (place.get("name") or {}).get("value", "")
    parsed = parse_pname(original)
    error: str | None = None
    try:
        resolved = resolve_place(parsed)
    except httpx.HTTPError as exc:
        resolved, error = None, type(exc).__name__
    action = decide_action(resolved, min_score)
    if resolved is not None:
        preuve = f"{resolved.source} | {resolved.query} | score {resolved.score:.3f}"
        priorite = "haute" if resolved.score >= 1.0 else "moyenne"
    elif error is not None:
        preuve = f"non résolu — erreur de résolution ({error})"
        priorite = "basse"
    else:
        preuve = f"non résolu (pays={parsed.country or '?'}, décalé={parsed.shifted})"
        priorite = "basse"
    return PlaceProposition(
        type="lieu_resolu" if resolved is not None else "lieu_indecidable",
        gramps_id=place.get("gramps_id", ""),
        handle=place.get("handle", ""),
        original=original,
        country=parsed.country,
        resolution=resolved,
        action=action,
        confiance=confiance_of(resolved),
        priorite=priorite,
        preuve=preuve,
    )


def render_places_report(scope, date, props, base_url="http://localhost") -> str:
    """Pure Markdown report grouped by action, priority-sorted."""
    props = sorted(props, key=lambda p: _PRIORITE.get(p.priorite, 9))
    n = {
        a: sum(1 for p in props if p.action == a)
        for a in ("ecrire", "proposition", "indecidable")
    }
    lines = [
        f"# Standardisation des lieux — {scope} — {date}",
        "",
        "## Synthèse",
        "",
        f"- Lieux analysés : {len(props)}",
        f"- À écrire (score ≥ seuil) : {n['ecrire']}",
        f"- Propositions (revue) : {n['proposition']}",
        f"- Indécidables : {n['indecidable']}",
        "",
        "## Détail",
        "",
        "| Lieu | Pays | Action | Nom proposé | Score | Confiance | Preuve |",
        "|---|---|---|---|---|---|---|",
    ]
    for p in props:
        nom = p.resolution.name if p.resolution else "—"
        score = f"{p.resolution.score:.3f}" if p.resolution else "—"
        lines.append(
            f"| {_link(p.gramps_id, base_url)} | {p.country or '?'} | {p.action} "
            f"| {nom} | {score} | {p.confiance} | {p.preuve} |"
        )
    lines.append("")
    return "\n".join(lines)


def render_propositions_yaml(props: list[PlaceProposition]) -> str:
    return yaml.safe_dump(
        [p.model_dump() for p in props], allow_unicode=True, sort_keys=False
    )


def run_places(
    client: GrampsClient,
    scope: str,
    output_dir,
    *,
    date: str,
    batch_size: int = 25,
    limit: int | None = None,
    min_score: float = 0.90,
) -> tuple[Path, Path]:
    """Resolve places over `scope`; write a Markdown report + YAML proposals. Read-only."""
    output_dir = Path(output_dir)
    props: list[PlaceProposition] = []
    for batch in iter_places(client, scope, batch_size, limit):
        for place in batch:
            props.append(build_proposition(place, min_score))
    out = output_dir / "lieux"
    out.mkdir(parents=True, exist_ok=True)
    scope_slug = scope.replace(":", "_")
    report_path = out / f"{date}_lieux_{scope_slug}.md"
    report_path.write_text(render_places_report(scope, date, props), encoding="utf-8")
    yaml_path = out / f"{date}_propositions_lieux_{scope_slug}.yaml"
    yaml_path.write_text(render_propositions_yaml(props), encoding="utf-8")
    return report_path, yaml_path
