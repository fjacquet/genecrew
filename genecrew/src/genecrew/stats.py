"""Tree statistics: deterministic collection (no LLM) + pure formatting."""

from __future__ import annotations

from crewai_custom_tools.tools.genealogy.gramps.client import GrampsClient

COUNTED_TYPES = (
    "people", "families", "events", "places", "sources",
    "citations", "repositories", "media", "notes", "tags",
)


def collect_stats(client: GrampsClient) -> tuple[str | None, dict[str, int]]:
    """Fetch tree name and per-type object counts (I/O)."""
    counts = {t: client.count_objects(t) for t in COUNTED_TYPES}
    return client.get_tree_info().get("name"), counts


def format_stats(tree_name: str | None, counts: dict[str, int]) -> str:
    """Render counts as an aligned text table (pure)."""
    name_width = max(len(k) for k in counts)
    value_width = max(len(str(v)) for v in counts.values())
    lines = [f"Arbre : {tree_name or '(sans nom)'}", ""]
    lines += [
        f"{k.ljust(name_width)}    {str(v).rjust(value_width)}" for k, v in counts.items()
    ]
    return "\n".join(lines)
