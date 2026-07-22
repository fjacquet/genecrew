"""Orchestration des sources d'archives en ligne : Wikidata et DHS.

Ce module fait le RÉSEAU et la boucle ; la traduction en Piste est pure et vit
dans la bibliothèque (crewai_custom_tools.tools.genealogy.pistes).

Voir docs/superpowers/specs/2026-07-20-sources-archives-pistes-design.md.
"""

from __future__ import annotations

import logging
import time
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

from genecrew.batching import iter_people_batches
from genecrew.pistes import render_rapport_pistes

logger = logging.getLogger(__name__)

THROTTLE_S = 2.0  # espacement entre requêtes vers query.wikidata.org ; 0 dans les tests

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
        return (
            pistes_wikidata(person, rows)
            if source == "wikidata"
            else pistes_dhs(person, rows)
        )
    raise ValueError(f"source inconnue : {source}")


def run_archives(
    client: GrampsClient,
    source: str,
    scope: str,
    output_dir: Path,
    *,
    date: str | None = None,
    batch_size: int = 25,
    limit: int | None = None,
) -> Path:
    """Parcourt `scope`, interroge `source`, rend le rapport. Lecture seule.

    `propose` n'écrit jamais (docs/adr/0012-cli-grammaire-verbes.md) : ce module
    n'appelle plus `consigner()`. La mesure du 2026-07-20 sur l'arbre réel montre
    qu'aucune piste n'est jamais forte — or `consigner()` n'écrit QUE les fortes —
    donc ce chemin d'écriture était mort dans les faits, en plus d'être rangé sous
    le mauvais verbe. Une future feuille `apply pistes` pourra le réintroduire le
    jour où une source produit des pistes fortes.
    """
    if source not in SOURCES:
        raise ValueError(f"source inconnue : {source}")
    date = date or _date.today().isoformat()
    fetcher = FactsFetcher(client)
    toutes: list[Piste] = []
    echecs = 0
    for lot in iter_people_batches(client, fetcher, scope, batch_size, limit):
        for person in lot:
            try:
                if THROTTLE_S:
                    time.sleep(THROTTLE_S)
                pistes = collecter_pistes(source, person)
            except Exception as exc:  # noqa: BLE001
                echecs += 1
                logger.warning("%s : %s a échoué (%s)", person.gramps_id, source, exc)
                continue
            toutes.extend(pistes)

    output_dir.mkdir(parents=True, exist_ok=True)
    chemin = output_dir / f"{date}_pistes_{source}_{scope.replace(':', '-')}.md"
    chemin.write_text(
        render_rapport_pistes(toutes, date, ecriture=False, echecs=echecs),
        encoding="utf-8",
    )
    logger.info("%s pistes depuis %s (%s échecs)", len(toutes), source, echecs)
    return chemin
