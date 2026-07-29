"""Résolution d'un lieu-dit sous sa commune — l'arbre d'abord, OSM borné ensuite.

Le défaut que ce module répare : `import releve` cherchait un lieu-dit comme s'il
était une COMMUNE, via un Nominatim non borné. « Les Roches, Saint-Martin-d'Auxigny,
Cher, France » rendait alors un homonyme ardéchois avec un score de 1.0 — la
similarité de chaîne ne mesure pas la plausibilité géographique.

La garde n'est donc PAS un seuil de score mais l'EMPRISE : bornée à la commune
déjà résolue, la requête ne peut plus ramener l'Ardèche, quel que soit son score.

Cette tâche implémente le premier étage de la cascade : chercher le lieu-dit
DANS l'arbre, sous sa commune déjà résolue. Les étages suivants (OSM borné,
puis création) arrivent aux tâches suivantes et ne sont pas anticipés ici.
"""

from __future__ import annotations

import logging

import httpx
from crewai_custom_tools.tools.genealogy.gramps.client import GrampsClient

_LOG = logging.getLogger(__name__)

TYPES_LIEU_DIT = frozenset({"Hamlet", "Locality", "Village", "Farm"})
"""Types Gramps qu'un lieu-dit peut porter.

Liste d'INCLUSION, comme `TYPES_LIEU_DECES` : un type oublié fait manquer un
lieu (on retombe sur la commune, sans dégât), tandis qu'un type de trop
attraperait un contenant — rattacher un décès à un département en silence.
"""


class RechercheArbreIndisponible(Exception):
    """La lecture de l'arbre a échoué : on ne SAIT PAS si le lieu-dit existe.

    Distincte d'un `None`, qui signifie « lu, et absent ». La cascade a le droit
    de créer sur une absence, jamais sur une ignorance : créer sur une panne de
    lecture produirait un doublon du lieu qu'on n'a pas su lire.
    """


def normaliser_nom(nom: str) -> str:
    """`strip()` puis `casefold()` — la normalisation de la mesure des collisions.

    L'arbre porte 663 lieux pour 3 noms partagés, tous inter-types. Ce chiffre ne
    vaut que pour CETTE normalisation ; la changer invalide la garantie.
    """
    return (nom or "").strip().casefold()


def chercher_dans_arbre(client: GrampsClient, nom: str, parent_handle: str) -> str | None:
    """Handle du lieu-dit `nom` rattaché à `parent_handle`, ou None s'il est absent.

    Lève `RechercheArbreIndisponible` si l'arbre n'a pas pu être lu. Refuse (rend
    None) si deux lieux de même nom ET de même type pendent sous le même parent :
    un refus coûte moins qu'un choix arbitraire entre deux lieux réels.
    """
    cible = normaliser_nom(nom)
    if not cible or not parent_handle:
        return None
    try:
        places = client.get_json("/places/?keys=handle,name,place_type,placeref_list")
    except (httpx.HTTPError, RuntimeError, ValueError) as exc:
        raise RechercheArbreIndisponible(str(exc)) from exc

    trouves = [
        p["handle"]
        for p in places
        if normaliser_nom((p.get("name") or {}).get("value", "")) == cible
        and (p.get("place_type") or "") in TYPES_LIEU_DIT
        and any(ref.get("ref") == parent_handle for ref in (p.get("placeref_list") or []))
    ]
    if len(trouves) != 1:
        if len(trouves) > 1:
            _LOG.warning(
                "Lieu-dit « %s » ambigu sous %s (%d homonymes de même type) : refusé",
                nom,
                parent_handle,
                len(trouves),
            )
        return None
    return trouves[0]
