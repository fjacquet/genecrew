"""Création d'un événement sourcé sur une personne — brique partagée.

`import releve` et `apply deaths` créent tous deux un événement daté, situé et cité
sur une personne existante. Ce qu'ils ont en commun n'est PAS la collecte — un relevé
de cercle et une correspondance INSEE n'ont rien à voir — mais l'ÉCRITURE : appeler
`GrampsCreateEventTool`, puis décoder son succès *qualifié*. Cet outil rend
`attached: False` quand l'événement a bien été créé mais n'a pas pu être rattaché à
la personne ; le handle rendu est alors la seule prise pour retrouver l'orphelin.
Lire ce cas correctement ne doit exister qu'à un seul endroit — deux copies, c'est
une copie qui finira par le rapporter comme un simple succès.
"""

from __future__ import annotations

import json

from crewai_custom_tools.tools.genealogy.gramps.write_tools import (
    GrampsCreateEventTool,
    effective_dry_run,
)


def dateval_iso(iso: str) -> list[int] | None:
    """« AAAA-MM-JJ » → `[jour, mois, année]` pour un `dateval` Gramps ; None sinon.

    None fait poser l'événement SANS date plutôt qu'avec une date inventée. Une année
    seule rend donc None : elle n'est jamais discriminante (règle projet — trop
    d'homonymes naissent et meurent la même année).
    """
    parts = (iso or "").split("-")
    if len(parts) != 3:
        return None
    try:
        annee, mois, jour = (int(p) for p in parts)
    except ValueError:
        return None
    return [jour, mois, annee]


def creer_evenement_source(person_handle: str, *, event_type: str,
                           dateval: list[int] | None = None,
                           place_handle: str | None = None,
                           citation_handle: str | None = None,
                           modifier: int = 0, quality: int = 0,
                           dry_run: bool = False) -> dict:
    """Crée un événement rattaché à une personne, et décode le résultat de l'outil.

    Rend `{"posee", "event_handle", "attache", "raison"}` :
      - `posee` : l'événement EXISTE dans la base ;
      - `attache` : il est rattaché à la personne. `False` = orphelin, et `raison`
        porte alors son handle en clair — jamais un « créé » trompeur.
    """
    dry_run = effective_dry_run(dry_run)
    evt = json.loads(GrampsCreateEventTool()._run(
        person_handle=person_handle, event_type=event_type, dateval=dateval,
        modifier=modifier, quality=quality, place_handle=place_handle,
        citation_handle=citation_handle, dry_run=dry_run))
    if not evt["success"]:
        return {"posee": False, "event_handle": None, "attache": False,
                "raison": f"création {event_type} refusée : {evt['error']}"}
    data = evt["data"]
    event_handle = data["handle"]
    attache = data.get("attached", True)
    raison = (f"{event_type} créé"
              if attache else
              f"{event_type} créé mais NON rattaché (orphelin {event_handle}) : "
              f"{data.get('attach_error', '')}")
    return {"posee": True, "event_handle": event_handle, "attache": attache,
            "raison": raison}
