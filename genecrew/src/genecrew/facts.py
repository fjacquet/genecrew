"""Build normalized PersonFacts / FamilyFacts from the Gramps Web API.

Pure mappers (`person_from_json` / `family_from_json`) plus a `FactsFetcher`
that performs the I/O and caches related-person lookups. One list call per page
uses `profile=all&extend=event_ref_list`, so vital dates (raw, with sortval)
and citation counts arrive together.
"""

from __future__ import annotations

import logging

import httpx

from crewai_custom_tools.tools.genealogy.gramps.client import GrampsClient
from crewai_custom_tools.tools.genealogy.models.domain import (
    EventFact, FamilyFacts, PersonFacts,
)

logger = logging.getLogger(__name__)

_SEX = {0: "F", 1: "M", 2: "U"}
_LIST_PARAMS = {"profile": "all", "extend": "event_ref_list", "sort": "gramps_id"}


def _event_from_raw(raw: dict) -> EventFact:
    date = raw.get("date") or {}
    return EventFact(
        type=raw.get("type", ""),
        sortval=date.get("sortval", 0) or 0,
        year=date.get("year"),
        modifier=date.get("modifier", 0) or 0,
        quality=date.get("quality", 0) or 0,
        dateval=date.get("dateval") or [],
        has_citation=bool(raw.get("citation_list")),
    )


def person_from_json(raw: dict) -> PersonFacts:
    """Map one raw person (profile=all & extend=event_ref_list) to PersonFacts."""
    name = raw.get("primary_name") or {}
    surnames = name.get("surname_list") or [{}]
    surname = surnames[0].get("surname", "") if surnames else ""
    given = name.get("first_name", "")
    events = [_event_from_raw(e) for e in (raw.get("extended") or {}).get("events", [])]

    bi, di = raw.get("birth_ref_index", -1), raw.get("death_ref_index", -1)
    birth = events[bi] if 0 <= bi < len(events) else None
    death = events[di] if 0 <= di < len(events) else None

    profile = raw.get("profile") or {}
    prof_cites = sum((profile.get(k) or {}).get("citations", 0) for k in ("birth", "death"))
    has_cite = bool(raw.get("citation_list")) or prof_cites > 0 or any(e.has_citation for e in events)

    return PersonFacts(
        gramps_id=raw.get("gramps_id", ""), handle=raw.get("handle", ""),
        name=f"{given} {surname}".strip(), surname=surname, given=given,
        sex=_SEX.get(raw.get("gender", 2), "U"),
        birth=birth, death=death, events=events, has_any_citation=has_cite,
        parent_family_handles=list(raw.get("parent_family_list") or []),
        family_handles=list(raw.get("family_list") or []),
    )


def family_from_json(raw: dict) -> FamilyFacts:
    """Map one raw family (extend=event_ref_list) to FamilyFacts."""
    events = [_event_from_raw(e) for e in (raw.get("extended") or {}).get("events", [])]
    marriage = next((e for e in events if e.type == "Marriage"), None)
    return FamilyFacts(
        gramps_id=raw.get("gramps_id", ""), handle=raw.get("handle", ""),
        father_handle=raw.get("father_handle"), mother_handle=raw.get("mother_handle"),
        child_handles=[c["ref"] for c in (raw.get("child_ref_list") or []) if "ref" in c],
        marriage=marriage,
    )


class FactsFetcher:
    """I/O layer: fetches raw JSON and caches per-handle person/family facts."""

    def __init__(self, client: GrampsClient) -> None:
        self._client = client
        self._people: dict[str, PersonFacts] = {}
        self._families: dict[str, FamilyFacts] = {}

    def list_people_facts(self, page: int, pagesize: int) -> list[PersonFacts]:
        raw = self._client.get_json(
            "/people/", params={**_LIST_PARAMS, "page": page, "pagesize": pagesize})
        facts = [person_from_json(r) for r in raw]
        for f in facts:
            self._people[f.handle] = f
        return facts

    def get_person_facts(self, handle: str) -> PersonFacts | None:
        if handle not in self._people:
            try:
                raw = self._client.get_json(
                    f"/people/{handle}", params={"profile": "all", "extend": "event_ref_list"})
            except httpx.HTTPStatusError as exc:
                if exc.response.status_code != 404:
                    raise
                logger.warning("Personne introuvable, ignorée : %s", handle)
                return None
            self._people[handle] = person_from_json(raw)
        return self._people.get(handle)

    def get_family_facts(self, handle: str) -> FamilyFacts | None:
        if handle not in self._families:
            try:
                raw = self._client.get_json(
                    f"/families/{handle}", params={"extend": "event_ref_list"})
            except httpx.HTTPStatusError as exc:
                if exc.response.status_code != 404:
                    raise
                logger.warning("Famille introuvable, ignorée : %s", handle)
                return None
            self._families[handle] = family_from_json(raw)
        return self._families.get(handle)
