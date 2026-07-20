"""Resolve an audit scope specification into an ordered list of person handles."""

from __future__ import annotations

from crewai_custom_tools.tools.genealogy.gramps.client import GrampsClient

_PAGESIZE = 200


def parse_scope(spec: str) -> tuple[str, str | None]:
    """Parse 'all' | 'person:<id>' | 'branch:<id>' | 'place:<id>' into (kind, gramps_id)."""
    if spec == "all":
        return ("all", None)
    if ":" in spec:
        kind, _, gid = spec.partition(":")
        if kind in ("person", "branch", "place"):
            return (kind, gid)
    raise ValueError(
        f"Périmètre invalide : {spec!r} "
        "(attendu 'all', 'person:ID', 'branch:ID', 'place:ID')")


def resolve_handles(
    client: GrampsClient, spec: str, limit: int | None = None
) -> list[tuple[str, str]]:
    """Return sorted (handle, gramps_id) pairs for the given scope."""
    kind, gid = parse_scope(spec)
    if kind == "place":
        # parse_scope est partagé avec les lieux ; sans ce refus explicite, "place:"
        # retomberait sur la branche "all" et paginerait toutes les personnes.
        raise NotImplementedError(
            "Le périmètre 'place:' ne s'applique qu'aux lieux, pas aux personnes.")
    if kind == "person":
        raw = client.get_json("/people/", params={"gramps_id": gid})
        return [(r["handle"], r["gramps_id"]) for r in raw]
    if kind == "branch":
        raise NotImplementedError(
            "Le périmètre 'branch:' arrive en Phase 1b (graphe de parenté).")
    # kind == "all" : pagination jusqu'à épuisement
    out: list[tuple[str, str]] = []
    page = 1
    while True:
        raw = client.get_json(
            "/people/", params={"page": page, "pagesize": _PAGESIZE, "sort": "gramps_id"})
        if not raw:
            break
        out.extend((r["handle"], r["gramps_id"]) for r in raw)
        if limit is not None and len(out) >= limit:
            return out[:limit]
        page += 1
    return out
