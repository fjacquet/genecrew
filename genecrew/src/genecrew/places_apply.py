"""Write-side places standardization: enrich leaves + build parent hierarchy (idempotent).

Writes only proposals with action=="ecrire" (authoritative or fuzzy ≥ min_score). Leaf
merges are proposed, never executed. Gated by dry_run + GENECREW_DRY_RUN.
"""

from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path

import yaml
from crewai_custom_tools.tools.genealogy.gramps.client import GrampsClient
from crewai_custom_tools.tools.genealogy.gramps.write_tools import (
    GrampsCreatePlaceTool, GrampsUpdatePlaceTool, effective_dry_run,
)
from crewai_custom_tools.tools.genealogy.models.domain import PlaceMergeProposition

from genecrew.batching import iter_places
from genecrew.places import build_proposition


def _link(gramps_id: str, base_url: str) -> str:
    return f"[{gramps_id}]({base_url}/place/{gramps_id})"


def _seed_parent_index(client: GrampsClient) -> dict[str, str]:
    """Reconstruct {path -> handle} for existing places so re-runs reuse parents (idempotent)."""
    places, page = [], 1
    while True:
        batch = client.get_json("/places/", params={"page": page, "pagesize": 200})
        if not batch:
            break
        places.extend(batch)
        page += 1
    by_handle = {p["handle"]: p for p in places}
    index: dict[str, str] = {}
    for p in places:
        names, cur, seen = [], p, set()
        while cur is not None and cur["handle"] not in seen:
            seen.add(cur["handle"])
            name = (cur.get("name") or {}).get("value", "")
            if not name:
                names = []                      # unreliable chain -> don't index this path
                break
            names.append(name)
            refs = cur.get("placeref_list") or []
            cur = by_handle.get(refs[0]["ref"]) if refs else None
        if names:
            index[">".join(reversed(names))] = p["handle"]
    return index


def _ensure_parents(chain, index, creator, dry_run) -> str | None:
    """Create/reuse each parent in `chain` (top→down); return the immediate parent handle.

    Le `date_qualifier` de la chaîne n'est **pas** propagé ici : il qualifie la relation
    entre la FEUILLE et son parent, pas la construction des parents entre eux. Il est
    posé, correctement, via `_date_qualifier` dans le `placeref_list` de la feuille.
    Le propager reviendrait à dater les rattachements des parents créés — un lieu
    fusionné en 1973 ferait naître un « Grand Est → France » daté « avant 1973-01-01 »,
    alors que le Grand Est existe depuis 2016. Ces nœuds sont partagés : la pollution
    toucherait tous les lieux ultérieurs rattachés dessous.
    """
    parent = None
    path = ""
    for level in chain.levels:
        path = f"{path}>{level.name}" if path else level.name
        if path not in index:
            payload = json.loads(creator._run(
                name=level.name, place_type=level.place_type, parent_handle=parent,
                code=level.code, dry_run=dry_run))
            if not payload["success"]:
                raise RuntimeError(f"create '{path}': {payload['error']}")
            index[path] = payload["data"]["handle"]
        parent = index[path]
    return parent


def render_apply_report(scope, date, applied, skipped, proposals, merges, errors, dry_run,
                        base_url="http://localhost") -> str:
    mode = "simulation (dry-run, aucune écriture)" if dry_run else "écritures appliquées"
    lines = [f"# Application des lieux — {scope} — {date}", "",
             f"Mode : {mode}.", "",
             f"- Lieux écrits : {len(applied)}",
             f"- Déjà structurés (ignorés) : {skipped}",
             f"- Propositions (non écrites) : {len(proposals)}",
             f"- Fusions proposées (jamais auto) : {len(merges)}",
             f"- Erreurs : {len(errors)}", "",
             "## Lieux écrits", ""]
    if applied:
        lines += ["| Lieu | Nom | Type | GPS |", "|---|---|---|---|"]
        for gid, name, ptype, lat, lon in applied:
            lines.append(f"| {_link(gid, base_url)} | {name} | {ptype} | {lat},{lon} |")
    else:
        lines.append("Aucune écriture.")
    lines += ["", "## Fusions proposées", ""]
    if merges:
        lines += ["| Garder | Fusionner | Canonique | Raison |", "|---|---|---|---|"]
        for m in merges:
            lines.append(f"| {_link(m.gramps_id_keep, base_url)} | {_link(m.gramps_id_merge, base_url)} "
                         f"| {m.canonical} | {m.reason} |")
    else:
        lines.append("Aucune.")
    lines += ["", "## Erreurs", ""]
    lines += (["| Lieu | Erreur |", "|---|---|"] + [f"| {_link(g, base_url)} | {e} |" for g, e in errors]
              if errors else ["Aucune erreur."])
    lines.append("")
    return "\n".join(lines)


def run_places_apply(client: GrampsClient, scope: str, output_dir, *, date: str,
                     min_score: float = 0.90, batch_size: int = 25,
                     limit: int | None = None, dry_run: bool = False) -> Path:
    """Enrich leaves + build hierarchy for action=='ecrire'; propose leaf merges. Idempotent."""
    output_dir = Path(output_dir)
    creator = GrampsCreatePlaceTool()
    updater = GrampsUpdatePlaceTool()
    index = _seed_parent_index(client)
    applied: list = []
    skipped = 0
    proposals: list = []
    errors: list = []
    by_canonical: dict[str, list[tuple[str, str]]] = defaultdict(list)

    for batch in iter_places(client, scope, batch_size, limit):
        for place in batch:
            if (place.get("place_type") or "Unknown") != "Unknown":
                skipped += 1                # déjà structuré (parent créé ou feuille enrichie) : idempotent
                continue
            prop = build_proposition(place, min_score)
            if prop.action != "ecrire":
                proposals.append(prop)
                continue
            rp = prop.resolution
            canonical = ">".join([lvl.name for c in rp.chains for lvl in c.levels] + [rp.name])
            by_canonical[canonical].append((prop.gramps_id, prop.handle))
            try:
                placeref_list = []
                for chain in rp.chains:
                    parent = _ensure_parents(chain, index, creator, dry_run)
                    ref = {"ref": parent}
                    if chain.date_qualifier:
                        ref["_date_qualifier"] = chain.date_qualifier
                    placeref_list.append(ref)
                payload = json.loads(updater._run(
                    handle=prop.handle, name=rp.name, place_type=rp.place_type,
                    lat=rp.lat, long=rp.long, code=rp.code, placeref_list=placeref_list,
                    alt_names=[a.model_dump() for a in rp.alt_names],
                    provenance=prop.preuve, dry_run=dry_run))
                if payload["success"]:
                    applied.append((prop.gramps_id, rp.name, rp.place_type, rp.lat, rp.long))
                else:
                    errors.append((prop.gramps_id, payload["error"]))
            except RuntimeError as exc:
                # levée uniquement par _ensure_parents sur un échec de création côté Gramps ;
                # toute autre exception (bug de programmation) doit remonter, pas être avalée ici.
                errors.append((prop.gramps_id, str(exc)))

    merges = [PlaceMergeProposition(
        gramps_id_keep=ids[0][0], handle_keep=ids[0][1],
        gramps_id_merge=g, handle_merge=h, canonical=canon,
        reason="même lieu canonique résolu")
        for canon, ids in by_canonical.items() if len(ids) > 1 for g, h in ids[1:]]

    out = output_dir / "lieux"
    out.mkdir(parents=True, exist_ok=True)
    scope_slug = scope.replace(":", "_")
    path = out / f"{date}_lieux_appliques_{scope_slug}.md"
    path.write_text(render_apply_report(scope, date, applied, skipped, proposals, merges, errors,
                                        effective_dry_run(dry_run)), encoding="utf-8")

    merges_path = out / f"{date}_fusions_lieux_{scope_slug}.yaml"
    merges_path.write_text(
        yaml.safe_dump([m.model_dump() for m in merges], allow_unicode=True, sort_keys=False),
        encoding="utf-8")
    return path
