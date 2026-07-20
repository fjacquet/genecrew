"""Orchestration des sources d'archives en ligne : Wikidata et DHS.

Ce module fait le RÉSEAU et la boucle ; la traduction en Piste est pure et vit
dans la bibliothèque (crewai_custom_tools.tools.genealogy.pistes).

Voir docs/superpowers/specs/2026-07-20-sources-archives-pistes-design.md.
"""
from __future__ import annotations

import logging
from datetime import date as _date
from pathlib import Path

from crewai_custom_tools.tools.genealogy.gramps.client import GrampsClient
from crewai_custom_tools.tools.genealogy.gramps.facts import FactsFetcher
from crewai_custom_tools.tools.genealogy.models.domain import PersonFacts, Piste
from crewai_custom_tools.tools.genealogy.pistes import (
    pistes_dhs,
    pistes_wikidata,
    requete_wikidata,
)
from crewai_custom_tools.tools.web.wikidata import sparql_rows

from genecrew.pistes import consigner, render_rapport_pistes

logger = logging.getLogger(__name__)

# Gallica est ABSENTE : mesuré contre l'API réelle, son SRU rend des notices de
# COLLECTION, pas des articles — « ce nom est quelque part dans ce volume de 500
# pages » n'est pas une piste. L'API adéquate (services/ContentSearch, qui rend des
# passages avec numéro de page) impose une conception à deux étapes : sous-projet
# séparé. `pistes/gallica.py` reste dans la bibliothèque, non exposé. Voir BACKLOG.md.
SOURCES = ("wikidata", "dhs")


def collecter_pistes(source: str, person: PersonFacts) -> list[Piste]:
    """Interroge la source pour UNE personne et rend ses pistes. Réseau ici."""
    if source in ("wikidata", "dhs"):
        rows = sparql_rows(requete_wikidata(person))
        return pistes_wikidata(person, rows) if source == "wikidata" else pistes_dhs(person, rows)
    raise ValueError(f"source inconnue : {source}")


def run_archives(client: GrampsClient, source: str, scope: str, output_dir: Path, *,
                 date: str | None = None, batch_size: int = 25,
                 limit: int | None = None, dry_run: bool = False) -> Path:
    """Parcourt `scope`, interroge `source`, consigne les fortes, rend le rapport."""
    if source not in SOURCES:
        raise ValueError(f"source inconnue : {source}")
    date = date or _date.today().isoformat()
    fetcher = FactsFetcher(client)
    toutes: list[Piste] = []
    vues = 0
    page = 1
    while True:
        lot = fetcher.list_people_facts(page=page, pagesize=batch_size)
        if not lot:
            break
        for person in lot:
            if limit is not None and vues >= limit:
                break
            vues += 1
            try:
                pistes = collecter_pistes(source, person)
            except Exception as exc:                       # noqa: BLE001
                logger.warning("%s : %s a échoué (%s)", person.gramps_id, source, exc)
                continue
            for piste in pistes:
                consigner(client, piste, dry_run=dry_run)
            toutes.extend(pistes)
        if limit is not None and vues >= limit:
            break
        page += 1

    output_dir.mkdir(parents=True, exist_ok=True)
    chemin = output_dir / f"{date}_pistes_{source}_{scope.replace(':', '-')}.md"
    chemin.write_text(render_rapport_pistes(toutes, date, dry_run=dry_run), encoding="utf-8")
    logger.info("%s pistes depuis %s (%s personnes vues)", len(toutes), source, vues)
    return chemin
