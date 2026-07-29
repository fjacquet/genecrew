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
from crewai_custom_tools.core.rate_limiter import get_rate_limiter
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


_URL_OSM = "https://nominatim.openstreetmap.org/search"
_UA_OSM = "genecrew/1.0 (genealogy place standardizer; +https://github.com/)"
_PROVIDER_OSM = "Nominatim"

TYPES_OSM_LIEU_DIT = frozenset({"hamlet", "locality", "village", "isolated_dwelling"})
"""Types OSM acceptés pour un lieu-dit.

`road`, `administrative`, `house` sont rejetés : « Rue de la Rose » n'est pas le
lieu-dit La Rose, et la BAN en rend quatre variantes pour cette seule commune.
"""

MARGE_EMPRISE_DEG = 0.06
"""Demi-côté du carré de repli, en degrés (≈ 6,7 km en latitude).

Valeur employée pour la mesure de conception ; elle a suffi à trouver La Rose à
2,7 km du bourg. Volontairement généreuse : une emprise trop large ne peut
ramener qu'un lieu-dit de la commune voisine, jamais l'Ardèche.
"""


def emprise_de_commune(
    lat: float | None,
    lon: float | None,
    bbox: tuple[float, float, float, float] | None,
) -> str | None:
    """Paramètre `viewbox` Nominatim (`lon_min,lat_max,lon_max,lat_min`), ou None.

    Préfère la bounding box réelle de la commune ; à défaut, un carré de
    ±`MARGE_EMPRISE_DEG` autour de son centre. Sans centre ni bbox, rend None :
    l'étage 2 est alors sauté plutôt que borné sur du vide.
    """
    if bbox is not None:
        return ",".join(str(v) for v in bbox)
    if lat is None or lon is None:
        return None
    return (
        f"{lon - MARGE_EMPRISE_DEG},{lat + MARGE_EMPRISE_DEG},"
        f"{lon + MARGE_EMPRISE_DEG},{lat - MARGE_EMPRISE_DEG}"
    )


def _http_get_osm(params: dict) -> list:
    """Appel Nominatim, cadencé par le limiteur PARTAGÉ de la bibliothèque.

    Le limiteur est importé, pas réimplémenté : la politique d'usage de Nominatim
    est d'une requête par seconde tous appelants confondus, donc un compteur
    propre à ce module la violerait dès qu'un autre chemin appelle aussi.
    """
    get_rate_limiter().acquire(_PROVIDER_OSM)
    resp = httpx.get(_URL_OSM, params=params, headers={"User-Agent": _UA_OSM}, timeout=15.0)
    resp.raise_for_status()
    return resp.json()


def interroger_osm(nom: str, viewbox: str) -> tuple[str, str] | None:
    """(lat, lon) du lieu-dit dans l'emprise, ou None.

    `bounded=1` est ce qui rend la garde géométrique : hors de la boîte, aucun
    résultat ne remonte, quel que soit son score de similarité.
    """
    if not nom or not viewbox:
        return None
    try:
        resultats = _http_get_osm(
            {
                "q": nom,
                "format": "jsonv2",
                "limit": 5,
                "accept-language": "fr",
                "viewbox": viewbox,
                "bounded": 1,
            }
        )
    except (httpx.HTTPError, ValueError) as exc:
        _LOG.warning("Nominatim borné indisponible pour « %s » : %s", nom, exc)
        return None
    for r in resultats:
        if (r.get("addresstype") or r.get("type") or "") in TYPES_OSM_LIEU_DIT:
            return str(r["lat"]), str(r["lon"])
    return None
