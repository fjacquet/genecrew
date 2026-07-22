"""Shared people-batch iterator over a scope (bulk for 'all', single for 'person:')."""

from __future__ import annotations

from crewai_custom_tools.tools.genealogy.gramps.client import GrampsClient

from crewai_custom_tools.tools.genealogy.gramps.facts import FactsFetcher
from genecrew.scope import parse_scope, resolve_handles


def iter_people_batches(
    client: GrampsClient,
    fetcher: FactsFetcher,
    scope: str,
    batch_size: int,
    limit: int | None,
):
    """Yield successive batches of PersonFacts for `scope`."""
    kind, _gid = parse_scope(scope)
    if kind != "all":
        handles = resolve_handles(client, scope)
        people = [
            p for h, _ in handles if (p := fetcher.get_person_facts(h)) is not None
        ]
        if people:
            yield people
        return
    fetched = 0
    page = 1
    while True:
        people = fetcher.list_people_facts(page, batch_size)
        if not people:
            break
        if limit is not None and fetched + len(people) > limit:
            people = people[: limit - fetched]
        yield people
        fetched += len(people)
        if limit is not None and fetched >= limit:
            break
        page += 1


def iter_places(client: GrampsClient, scope: str, batch_size: int, limit: int | None):
    """Yield successive batches of raw Gramps place dicts for `scope` ('all' or 'place:<ID>')."""
    kind, gid = parse_scope(scope)
    if kind == "place":
        places = client.get_json("/places/", params={"gramps_id": gid})
        if places:
            yield places
        return
    if kind != "all":
        raise NotImplementedError(
            f"scope {scope!r} non supporté pour les lieux ; "
            "utilisez --scope all ou --scope place:<ID>"
        )
    fetched = 0
    page = 1
    while True:
        places = client.get_json(
            "/places/",
            params={"page": page, "pagesize": batch_size, "sort": "gramps_id"},
        )
        if not places:
            break
        if limit is not None and fetched + len(places) > limit:
            places = places[: limit - fetched]
        yield places
        fetched += len(places)
        if limit is not None and fetched >= limit:
            break
        page += 1
