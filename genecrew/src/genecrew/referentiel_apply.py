"""`apply referentiel` : écrit les pays et subdivisions du YAML relu.

Invariant (spec §5.5) : toute écriture est une création, le remplissage d'un champ vide, ou
un ajout dans une liste. Seule exception assumée, le retypage des `Wilaya` en `Province`.
C'est cet invariant qui autorise l'écriture directe, sans détour par une seconde relecture.

Ne réinterroge JAMAIS Wikidata : le YAML relu est la seule entrée (spec §6).
"""

from __future__ import annotations

import json
from pathlib import Path

import yaml
from crewai_custom_tools.tools.genealogy.gramps.write_tools import (
    GrampsAddUrlTool, GrampsCreatePlaceTool, GrampsUpdatePlaceTool, effective_dry_run,
)
from crewai_custom_tools.tools.genealogy.models.domain import Subdivision
from crewai_custom_tools.tools.genealogy.referentiel.chargement import EntitePays
from crewai_custom_tools.tools.genealogy.referentiel.config import PAYS_REFERENTIEL

from genecrew.batching import iter_places      # pagination déjà écrite, triée par gramps_id

_WIKIDATA = "https://www.wikidata.org/wiki/"

# Types de lieux qui peuvent CONTENIR : ceux-là seuls sont candidats à l'appariement par nom
# seul. `Wilaya` y figure parce qu'il faut retrouver les 5 lieux algériens pour les retyper —
# c'est précisément leur type qui doit changer, donc la clé (nom, type) ne peut pas les voir.
TYPES_CONTENANTS = frozenset({"Country", "State", "Region", "Department", "Province",
                              "County", "District", "Wilaya"})

# Types natifs de Gramps, relevés sur `/types/default/place_types` (spec §4). Un type qui
# n'est pas dans cette liste est un type PERSONNALISÉ — `Wilaya` est le seul de l'arbre — et
# lui seul peut être réécrit. Un type natif est un choix humain : on n'y touche pas.
TYPES_NATIFS = frozenset({"Unknown", "Country", "State", "County", "City", "Parish",
                          "Locality", "Street", "Province", "Region", "Department",
                          "Neighborhood", "District", "Borough", "Municipality", "Town",
                          "Village", "Hamlet", "Farm", "Building", "Number"})

# `Unknown` est le type VIDE de Gramps : le remplir est un remplissage, pas une réécriture.
_TYPES_VIDES = frozenset({"", "Unknown"})

_PAYS_PAR_QID = {pays.qid: pays for pays in PAYS_REFERENTIEL.values()}


def index_par_qid(places: list[dict]) -> dict[str, str]:
    """QID → handle, lu dans les `urls` des lieux. L'identité durable de l'appariement."""
    index: dict[str, str] = {}
    for place in places:
        for url in place.get("urls") or []:
            chemin = url.get("path") or ""
            if chemin.startswith(_WIKIDATA):
                index.setdefault(chemin[len(_WIKIDATA):], place["handle"])
    return index


def index_par_nom_type(places: list[dict]) -> dict[tuple[str, str], str]:
    """(nom, type) → handle. Repli du premier passage, avant que les QID soient posés."""
    index: dict[tuple[str, str], str] = {}
    for place in places:
        nom = (place.get("name") or {}).get("value", "")
        if nom:
            index.setdefault((nom, place.get("place_type", "")), place["handle"])
    return index


def index_par_nom_contenant(places: list[dict]) -> dict[str, str]:
    """nom → handle, restreint aux lieux CONTENANTS. Dernière prise de l'appariement."""
    index: dict[str, str] = {}
    for place in places:
        nom = (place.get("name") or {}).get("value", "")
        if nom and place.get("place_type", "") in TYPES_CONTENANTS:
            index.setdefault(nom, place["handle"])
    return index


def subdivision_de_pays(entite: EntitePays) -> Subdivision:
    """Un pays vu comme une subdivision de niveau 0, pour n'avoir qu'un chemin d'écriture.

    Le niveau 0 le place avant ses subdivisions dans l'ordre d'écriture ; son `parent_qid`
    vide dit qu'il ne se rattache à rien. Le code ISO 3166-1 alpha-2 et le nom déjà en base
    viennent de la table des pays (spec §5.2), qui est une donnée pure — aucun appel.
    """
    ref = _PAYS_PAR_QID.get(entite.qid)
    noms = [entite.libelle_fr]
    if ref and ref.nom not in noms:
        noms.append(ref.nom)
    return Subdivision(qid=entite.qid, iso=ref.code_iso if ref else "",
                       code=ref.code_iso if ref else "", libelle_fr=entite.libelle_fr,
                       noms=noms, place_type="Country", niveau=0, parent_qid="",
                       lat=entite.lat, long=entite.long, frwiki=entite.frwiki)


def apparier(sub: Subdivision, par_qid: dict[str, str],
             par_nom_type: dict[tuple[str, str], str],
             par_nom: dict[str, str]) -> str | None:
    """Trois prises, dans l'ordre : QID, puis (nom, type), puis nom seul chez les contenants.

    Les noms essayés sont ceux de `sub.noms` — français d'abord, vernaculaire ensuite —
    parce que l'arbre porte `Bayern` là où Wikidata rend `Bavière`.
    """
    if sub.qid and sub.qid in par_qid:
        return par_qid[sub.qid]
    for nom in sub.noms:
        if (nom, sub.place_type) in par_nom_type:
            return par_nom_type[(nom, sub.place_type)]
    for nom in sub.noms:
        if nom in par_nom:
            return par_nom[nom]
    return None


def _urls_de(sub: Subdivision) -> list[dict]:
    urls = [{"path": f"{_WIKIDATA}{sub.qid}", "desc": "Wikidata"}] if sub.qid else []
    if sub.frwiki:
        urls.append({"path": sub.frwiki, "desc": "Wikipédia"})
    return urls


def decider(sub: Subdivision, place: dict | None) -> dict:
    """Les champs à écrire pour une subdivision, selon le lieu existant (None = absent).

    Rien de ce qui est déjà rempli n'est touché — le nom en particulier n'est jamais réécrit :
    `Bayern` reste `Bayern` et `Bavière` rejoint ses `alt_names`.
    """
    if place is None:
        return {"action": "creer", "name": sub.libelle_fr, "place_type": sub.place_type,
                "code": sub.code, "lat": sub.lat, "long": sub.long, "urls": _urls_de(sub)}

    plan: dict = {"action": "completer", "handle": place["handle"], "urls": _urls_de(sub)}
    if not place.get("lat") and sub.lat:
        plan["lat"] = sub.lat
    if not place.get("long") and sub.long:
        plan["long"] = sub.long
    if not place.get("code") and sub.code:
        plan["code"] = sub.code
    # Unique réécriture permise : normaliser un type PERSONNALISÉ (`Wilaya`) vers un type
    # natif, ou remplir un type vide. Un type natif déjà posé est un choix humain : intact.
    type_existant = place.get("place_type") or ""
    if type_existant != sub.place_type and (type_existant in _TYPES_VIDES
                                            or type_existant not in TYPES_NATIFS):
        plan["place_type"] = sub.place_type
    nom_existant = (place.get("name") or {}).get("value", "")
    deja = {a.get("value") for a in (place.get("alt_names") or [])}
    plan["alt_names"] = ([{"value": sub.libelle_fr}]
                         if sub.libelle_fr and sub.libelle_fr != nom_existant
                         and sub.libelle_fr not in deja else [])
    return plan


def _cibles_du_yaml(doc: dict) -> list[Subdivision]:
    """Pays puis subdivisions, triés par niveau : un parent est toujours écrit avant l'enfant."""
    pays = [subdivision_de_pays(EntitePays(**entite)) for entite in doc.get("pays") or []]
    subs = [Subdivision(**sub) for sub in doc.get("subdivisions") or []]
    return sorted(pays + subs, key=lambda s: s.niveau)


def render_apply_report(date: str, crees: list, completes: list, orphelins: list,
                        erreurs: list, urls_ajoutees: int, dry_run: bool) -> str:
    """Rapport Markdown pur. Le mode figure aussi dans le NOM du fichier (spec §9)."""
    lignes = [f"# Référentiel appliqué — {date}", "",
              f"Mode : {'simulation (aucune écriture)' if dry_run else 'écritures appliquées'}.",
              "",
              f"- Lieux créés : {len(crees)}",
              f"- Lieux complétés : {len(completes)}",
              f"- URLs ajoutées : {urls_ajoutees}",
              f"- Sans parent résolu : {len(orphelins)}",
              f"- Erreurs : {len(erreurs)}", ""]
    for titre, lot in (("Créés", crees), ("Complétés", completes)):
        lignes += [f"## {titre}", ""]
        if lot:
            lignes += ["| ISO | Nom | Type |", "|---|---|---|"]
            lignes += [f"| {iso} | {nom} | {type_} |" for iso, nom, type_ in lot] + [""]
        else:
            lignes += ["Aucun.", ""]
    if orphelins:
        lignes += ["## Sans parent résolu", "",
                   "Ces lieux ont été écrits sans rattachement : leur parent n'est ni dans "
                   "le YAML relu, ni identifiable dans l'arbre. À rattacher à la main.", "",
                   "| ISO | Parent attendu (QID) |", "|---|---|"]
        lignes += [f"| {iso} | {qid} |" for iso, qid in orphelins] + [""]
    if erreurs:
        lignes += ["## Erreurs", "", "| ISO | Message |", "|---|---|"]
        lignes += [f"| {iso} | {msg} |" for iso, msg in erreurs] + [""]
    return "\n".join(lignes)


def run_referentiel_apply(client, yaml_path, output_dir, *, date: str,
                          dry_run: bool = False) -> Path:
    """Applique le YAML relu : crée les lieux absents, complète les autres. Rend le rapport."""
    dry_run = effective_dry_run(dry_run)
    doc = yaml.safe_load(Path(yaml_path).read_text(encoding="utf-8")) or {}
    cibles = _cibles_du_yaml(doc)

    places = [place for lot in iter_places(client, "all", 200, None) for place in lot]
    par_qid = index_par_qid(places)
    par_nom_type = index_par_nom_type(places)
    par_nom = index_par_nom_contenant(places)
    par_handle = {p["handle"]: p for p in places}

    createur, majeur, urleur = (GrampsCreatePlaceTool(), GrampsUpdatePlaceTool(),
                                GrampsAddUrlTool())
    handles_qid = dict(par_qid)
    crees: list[tuple[str, str, str]] = []
    completes: list[tuple[str, str, str]] = []
    orphelins: list[tuple[str, str]] = []
    erreurs: list[tuple[str, str]] = []
    urls_ajoutees = 0

    # Niveau 0 (pays), puis 1, puis 2 : un enfant ne peut pas se rattacher à un parent
    # qui n'existe pas encore. `_cibles_du_yaml` a déjà trié.
    for sub in cibles:
        handle = apparier(sub, par_qid, par_nom_type, par_nom)
        place = par_handle.get(handle) if handle else None
        plan = decider(sub, place)
        parent_handle = handles_qid.get(sub.parent_qid) if sub.parent_qid else None
        if sub.parent_qid and parent_handle is None:
            orphelins.append((sub.iso, sub.parent_qid))
        try:
            if plan["action"] == "creer":
                payload = json.loads(createur._run(
                    name=plan["name"], place_type=plan["place_type"],
                    parent_handle=parent_handle, lat=plan["lat"], long=plan["long"],
                    code=plan["code"], dry_run=dry_run))
                if not payload["success"]:
                    raise RuntimeError(payload["error"])
                handle = payload["data"]["handle"]
                crees.append((sub.iso, sub.libelle_fr, sub.place_type))
            else:
                # `placeref_list=None` laisse le rattachement existant intact ; on ne le
                # pose que sur une liste VIDE, c'est-à-dire un champ à remplir (spec §5.1).
                placerefs = ([{"ref": parent_handle}]
                             if parent_handle and not place.get("placeref_list") else None)
                payload = json.loads(majeur._run(
                    handle=handle,
                    name=(place.get("name") or {}).get("value", ""),   # jamais réécrit
                    place_type=plan.get("place_type") or place.get("place_type") or "Unknown",
                    lat=plan.get("lat"), long=plan.get("long"), code=plan.get("code"),
                    placeref_list=placerefs, alt_names=plan["alt_names"], dry_run=dry_run))
                if not payload["success"]:
                    raise RuntimeError(payload["error"])
                completes.append((sub.iso, sub.libelle_fr, sub.place_type))
            handles_qid[sub.qid] = handle
            # Un handle simulé ne désigne aucun objet : l'interroger ferait un 404. Les URLs
            # d'un lieu créé en simulation ne sont donc pas tentées.
            if not handle.startswith("DRYRUN:"):
                for url in plan["urls"]:
                    reponse = json.loads(urleur._run(
                        object_type="places", handle=handle, url=url["path"],
                        description=url["desc"], dry_run=dry_run))
                    if not reponse["success"]:
                        raise RuntimeError(reponse["error"])
                    urls_ajoutees += int(reponse["data"]["changed"])
        except (RuntimeError, KeyError) as exc:
            erreurs.append((sub.iso, str(exc)))

    mode = "simulation" if dry_run else "ecritures"
    out = Path(output_dir) / "referentiel"
    out.mkdir(parents=True, exist_ok=True)
    report_path = out / f"{date}_referentiel_applique_{mode}.md"
    report_path.write_text(
        render_apply_report(date, crees, completes, orphelins, erreurs, urls_ajoutees, dry_run),
        encoding="utf-8")
    return report_path
