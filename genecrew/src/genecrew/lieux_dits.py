"""Résolution d'un lieu-dit sous sa commune — l'arbre d'abord, OSM borné ensuite.

Le défaut que ce module répare : `import releve` cherchait un lieu-dit comme s'il
était une COMMUNE, via un Nominatim non borné. « Les Roches, Saint-Martin-d'Auxigny,
Cher, France » rendait alors un homonyme ardéchois avec un score de 1.0 — la
similarité de chaîne ne mesure pas la plausibilité géographique.

La garde n'est donc PAS un seuil de score mais l'EMPRISE : bornée à la commune
déjà résolue, la requête ne peut plus ramener l'Ardèche, quel que soit son score.

La cascade compte trois étages, du moins cher au plus cher, le premier qui
répond gagne : l'arbre (gratuit, déterministe), Nominatim borné à l'emprise de
la commune (une requête), puis la création du lieu sous la commune, sans
coordonnées si ni l'arbre ni OSM ne l'ont trouvé. `resoudre_lieu_dit` les
assemble.
"""

from __future__ import annotations

import json
import logging

import httpx
from crewai_custom_tools.core.rate_limiter import get_rate_limiter
from crewai_custom_tools.tools.genealogy.gramps.client import GrampsClient
from crewai_custom_tools.tools.genealogy.gramps.write_tools import GrampsCreatePlaceTool

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
    places: list[dict] = []
    try:
        page = 1
        while True:
            batch = client.get_json(
                "/places/",
                params={
                    "page": page,
                    "pagesize": 200,
                    "keys": "handle,name,place_type,placeref_list",
                },
            )
            if not batch:
                break
            places.extend(batch)
            page += 1
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
    # Aucun résolveur `geo/` ne rend de bbox aujourd'hui — branche gardée pour
    # le jour où l'un d'eux en produira une (voir docstring : ordre à respecter).
    bbox: tuple[float, float, float, float] | None,
) -> str | None:
    """Paramètre `viewbox` Nominatim (`lon_min,lat_max,lon_max,lat_min`), ou None.

    Préfère la bounding box réelle de la commune ; à défaut, un carré de
    ±`MARGE_EMPRISE_DEG` autour de son centre. Sans centre ni bbox, rend None :
    l'étage 2 est alors sauté plutôt que borné sur du vide.

    ATTENTION À L'ORDRE si `bbox` est un jour câblé : ce paramètre attend
    l'ordre *viewbox* de Nominatim, `(lon_min, lat_max, lon_max, lat_min)` —
    PAS l'ordre que rend le champ `boundingbox` des réponses Nominatim,
    `[lat_min, lat_max, lon_min, lon_max]`. Les deux ordres diffèrent à la
    fois sur l'axe (lat/lon inversés) et sur le regroupement ; les confondre
    reproduirait le gotcha maison sur l'inversion longitude/latitude.
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


def _creer_lieu(
    *,
    nom: str,
    parent_handle: str,
    lat: str | None,
    long: str | None,
    dry_run: bool,
) -> str:
    """Crée le lieu-dit sous sa commune. Rend son handle. Lève si l'écriture échoue."""
    creator = GrampsCreatePlaceTool()
    payload = json.loads(
        creator._run(
            name=nom,
            place_type="Hamlet",
            parent_handle=parent_handle,
            lat=lat,
            long=long,
            dry_run=dry_run,
        )
    )
    if not payload["success"]:
        raise RuntimeError(f"création du lieu-dit '{nom}' : {payload['error']}")
    return payload["data"]["handle"]


def resoudre_lieu_dit(
    client: GrampsClient,
    nom: str,
    commune_handle: str,
    commune_lat: float | None,
    commune_lon: float | None,
    # Toujours None en production : `ResolvedPlace` ne porte aucun champ de bbox
    # et aucun résolveur `geo/` n'en produit — branche gardée pour le jour où.
    commune_bbox: tuple[float, float, float, float] | None = None,
    *,
    dry_run: bool = False,
) -> tuple[str | None, str]:
    """(handle, provenance) du lieu-dit. Cascade à trois étages, le premier qui répond.

    provenance ∈ {"arbre", "osm", "cree_sans_gps", "abandon"} — le rapport
    l'affiche telle quelle, pour que le relecteur distingue un hameau confirmé
    par OSM d'un hameau créé sur la seule foi d'une transcription.
    """
    if not nom or not commune_handle:
        return None, "abandon"

    # Étage 1 — l'arbre. Une PANNE n'est pas une absence : on abandonne plutôt
    # que de créer un doublon du lieu qu'on n'a pas su lire.
    try:
        handle = chercher_dans_arbre(client, nom, commune_handle)
    except RechercheArbreIndisponible as exc:
        _LOG.warning("Arbre illisible pour le lieu-dit « %s », aucun lieu posé : %s", nom, exc)
        return None, "abandon"
    if handle:
        return handle, "arbre"

    # Étage 2 — OSM borné à l'emprise de la commune.
    viewbox = emprise_de_commune(commune_lat, commune_lon, commune_bbox)
    coords = interroger_osm(nom, viewbox) if viewbox else None
    if coords:
        lat, long = coords
        return (
            _creer_lieu(nom=nom, parent_handle=commune_handle, lat=lat, long=long, dry_run=dry_run),
            "osm",
        )

    # Étage 3 — création sans coordonnées.
    return (
        _creer_lieu(nom=nom, parent_handle=commune_handle, lat=None, long=None, dry_run=dry_run),
        "cree_sans_gps",
    )
