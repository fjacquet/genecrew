"""Execute human-reviewed place merges (never automatic). Reads a fusions YAML."""

from __future__ import annotations

import json
from pathlib import Path

import yaml

from crewai_custom_tools.tools.genealogy.gramps.client import GrampsClient
from crewai_custom_tools.tools.genealogy.gramps.write_tools import (
    GrampsMergePlacesTool, effective_dry_run,
)
from crewai_custom_tools.tools.genealogy.models.domain import PlaceFacts

from genecrew.batching import iter_places
from genecrew.logging_setup import get_logger


def _link(gramps_id: str, base_url: str) -> str:
    return f"[{gramps_id}]({base_url}/place/{gramps_id})"


def render_merge_report(date, done, errors, dry_run, base_url="http://localhost") -> str:
    mode = "simulation (dry-run, aucune fusion)" if dry_run else "fusions appliquées"
    lines = [f"# Fusions de lieux — {date}", "", f"Mode : {mode}.", "",
             f"- Fusions : {len(done)}", f"- Erreurs : {len(errors)}", "", "## Fusions", ""]
    if done:
        lines += ["| Gardé | Fusionné | Canonique |", "|---|---|---|"]
        for keep, merge, canon in done:
            lines.append(f"| {_link(keep, base_url)} | {_link(merge, base_url)} | {canon} |")
    else:
        lines.append("Aucune.")
    lines += ["", "## Erreurs", ""]
    lines += (["| Fusionné | Erreur |", "|---|---|"] + [f"| {_link(m, base_url)} | {e} |" for m, e in errors]
              if errors else ["Aucune erreur."])
    lines.append("")
    return "\n".join(lines)


def _retroliens(client: GrampsClient, handle: str) -> int:
    """Nombre d'objets qui référencent ce lieu ; 0 si l'API ne répond pas.

    Un appel par lieu : coûteux, mais c'est la seule mesure qui dise lequel de deux
    homonymes l'arbre utilise réellement. Un échec ne doit pas faire échouer la
    détection — il dégrade seulement le départage vers les critères suivants.
    """
    try:
        objet = client.get_json(f"/places/{handle}", params={"backlinks": "1"}) or {}
    except Exception as exc:
        get_logger().warning("rétroliens de %s indisponibles : %s", handle, exc)
        return 0
    return sum(len(refs) for refs in (objet.get("backlinks") or {}).values())


def collecter_lieux(client: GrampsClient, scope: str, batch_size: int = 200,
                    limit: int | None = None) -> list[PlaceFacts]:
    """Lit les lieux du périmètre et les réduit aux faits utiles à la détection."""
    lieux: list[PlaceFacts] = []
    for lot in iter_places(client, scope, batch_size, limit):
        for place in lot:
            if not isinstance(place, dict):
                continue
            handle = place.get("handle", "")
            lieux.append(PlaceFacts(
                gramps_id=place.get("gramps_id", ""),
                handle=handle,
                nom=(place.get("name") or {}).get("value", "") or "",
                place_type=place.get("place_type") or "",
                code=place.get("code") or "",
                lat=place.get("lat") or "",
                long=place.get("long") or "",
                a_parent=bool(place.get("placeref_list")),
                retroliens=_retroliens(client, handle)))
    return lieux


def run_places_merge(client: GrampsClient, merges_yaml, output_dir, *, date: str,
                     dry_run: bool = False) -> Path:
    """Execute the merges listed in a reviewed YAML. Gated by dry_run + GENECREW_DRY_RUN."""
    output_dir = Path(output_dir)
    merges = yaml.safe_load(Path(merges_yaml).read_text(encoding="utf-8")) or []
    tool = GrampsMergePlacesTool()
    done: list = []
    errors: list = []
    for m in merges:
        payload = json.loads(tool._run(keep_handle=m["handle_keep"],
                                       merge_handle=m["handle_merge"], dry_run=dry_run))
        if payload["success"]:
            done.append((m["gramps_id_keep"], m["gramps_id_merge"], m.get("canonical", "")))
        else:
            errors.append((m["gramps_id_merge"], payload["error"]))
    out = output_dir / "lieux"
    out.mkdir(parents=True, exist_ok=True)
    slug = Path(merges_yaml).stem
    path = out / f"{date}_fusions_appliquees_{slug}.md"
    path.write_text(render_merge_report(date, done, errors, effective_dry_run(dry_run)),
                    encoding="utf-8")
    return path
