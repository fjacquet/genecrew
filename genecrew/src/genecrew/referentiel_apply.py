"""`apply referentiel` : écrit les pays et subdivisions du YAML relu.

Invariant (spec §5.5) : toute écriture est une création, le remplissage d'un champ vide, ou
un ajout dans une liste. Seule exception assumée, le retypage d'un type PERSONNALISÉ vers un
type natif (`Wilaya` → `Province`). C'est cet invariant qui autorise l'écriture directe, sans
détour par une seconde relecture.

Cet invariant protège contre la **destruction**, pas contre l'écriture d'une valeur juste sur
le **mauvais objet** : un GPS posé sur un homonyme n'écrase rien et reste une donnée fausse.
D'où les gardes d'appariement (`_candidat_recevable`), la consommation des handles, et le
refus d'un lieu qui affirme déjà une autre identité Wikidata.

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

# Types natifs de Gramps, RECOPIÉS de la spec §4 (relevé sur `/types/default/place_types`) et
# jamais relus sur l'API vivante. Un type absent d'ici passe pour personnalisé, donc
# retypable : si le serveur rendait autre chose qu'une chaîne simple, tout l'arbre deviendrait
# candidat au retypage. D'où deux gardes — `decider` refuse un type qui n'est pas une chaîne,
# et le rapport liste **chaque** retypage ligne à ligne. Un retypage de masse ne peut pas
# passer inaperçu. La spec affirme aussi que `Wilaya` est le seul type personnalisé de
# l'arbre : ce n'est pas mesuré, et la section « Retypages » est ce qui le vérifie au run.
TYPES_NATIFS = frozenset({"Unknown", "Country", "State", "County", "City", "Parish",
                          "Locality", "Street", "Province", "Region", "Department",
                          "Neighborhood", "District", "Borough", "Municipality", "Town",
                          "Village", "Hamlet", "Farm", "Building", "Number"})

# `Unknown` est le type VIDE de Gramps : le remplir est un remplissage, pas une réécriture.
_TYPES_VIDES = frozenset({"", "Unknown"})

_PAYS_PAR_QID = {pays.qid: pays for pays in PAYS_REFERENTIEL.values()}


def _cellule(valeur) -> str:
    """Aplatit une valeur en une cellule Markdown : une seule ligne, aucun `|` nu.

    Un message d'erreur d'API porte un corps de réponse multiligne ; tel quel il coupe le
    tableau en deux et le rapport devient illisible exactement quand il compte.
    """
    return " ".join(str(valeur).split()).replace("|", "\\|")


def qid_pose(place: dict) -> str | None:
    """Le QID déjà affirmé par le lieu, s'il en porte un. Une identité, pas un ornement."""
    for url in place.get("urls") or []:
        chemin = url.get("path") or ""
        if chemin.startswith(_WIKIDATA):
            return chemin[len(_WIKIDATA):]
    return None


def index_par_qid(places: list[dict]) -> dict[str, str]:
    """QID → handle, lu dans les `urls` des lieux. L'identité durable de l'appariement."""
    index: dict[str, str] = {}
    for place in places:
        qid = qid_pose(place)
        if qid:
            index.setdefault(qid, place["handle"])
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


def identifiant(sub: Subdivision) -> str:
    """De quoi nommer une ligne de rapport même sans code ISO (pays hors de la table)."""
    return sub.iso or sub.qid or sub.libelle_fr


def _candidat_recevable(sub: Subdivision, place: dict | None,
                        parent_handle: str | None) -> bool:
    """Un candidat trouvé par son NOM est-il bien la cible visée ? (spec §5.3)

    Deux refus, tirés de cas reproduits :

    - un lieu typé `Country` n'est jamais la cible d'une subdivision. Sans cette règle,
      l'État américain `Géorgie` s'apparie au **pays** Géorgie, qui reçoit alors le GPS
      d'Atlanta, le code `GA` et un rattachement sous les États-Unis. Même mécanique pour
      la province belge `Luxembourg` contre le pays `Luxembourg`.
    - un lieu déjà rattaché AILLEURS que sous le parent attendu n'est pas le bon homonyme —
      c'est la clause « sous le même parent » du §5.3, que l'index (nom, type) ignore.

    Le second refus ne joue que si le parent est connu : rejeter faute de parent résolu
    ferait créer un doublon de tout lieu correctement rattaché dont le parent n'est ni dans
    le YAML relu ni porteur d'un QID.
    """
    if place is None:
        return True
    if sub.niveau > 0 and (place.get("place_type") or "") == "Country":
        return False
    refs = place.get("placeref_list") or []
    if refs and parent_handle is not None:
        return any(ref.get("ref") == parent_handle for ref in refs)
    return True


def apparier(sub: Subdivision, par_qid: dict[str, str],
             par_nom_type: dict[tuple[str, str], str],
             par_nom: dict[str, str], *,
             par_handle: dict[str, dict] | None = None,
             parent_handle: str | None = None) -> str | None:
    """Trois prises, dans l'ordre : QID, puis (nom, type), puis nom seul chez les contenants.

    Les noms essayés sont ceux de `sub.noms` — français d'abord, vernaculaire ensuite —
    parce que l'arbre porte `Bayern` là où Wikidata rend `Bavière`.

    Le QID est une identité : il s'impose seul. Les deux prises par le nom ne sont que des
    présomptions et passent par `_candidat_recevable` ; `par_handle` leur donne les lieux
    dont elles ont besoin pour se juger.
    """
    if sub.qid and sub.qid in par_qid:
        return par_qid[sub.qid]
    index = par_handle or {}
    for prise in ([par_nom_type.get((nom, sub.place_type)) for nom in sub.noms],
                  [par_nom.get(nom) for nom in sub.noms]):
        for handle in prise:
            if handle and _candidat_recevable(sub, index.get(handle), parent_handle):
                return handle
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
    brut = place.get("place_type")
    if brut is not None and not isinstance(brut, str):
        # Type illisible (objet, libellé localisé) : la table des types natifs ne peut plus
        # arbitrer, donc on ne décide rien. L'appelant refusera le lieu.
        plan["type_illisible"] = True
    else:
        type_existant = brut or ""
        if type_existant != sub.place_type and (type_existant in _TYPES_VIDES
                                                or type_existant not in TYPES_NATIFS):
            plan["place_type"] = sub.place_type
            if type_existant not in _TYPES_VIDES:
                plan["retypage"] = (type_existant, sub.place_type)

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


def _section(titre: str, entetes: list[str], lignes: list[tuple],
             chapeau: str = "", vide: str = "Aucun.") -> list[str]:
    """Une section du rapport, cellules assainies. Le titre est toujours rendu, même vide."""
    bloc = [f"## {titre}", ""]
    if not lignes:
        return bloc + [vide, ""]
    if chapeau:
        bloc += [chapeau, ""]
    bloc += ["| " + " | ".join(entetes) + " |", "|" + "---|" * len(entetes)]
    bloc += ["| " + " | ".join(_cellule(c) for c in ligne) + " |" for ligne in lignes]
    return bloc + [""]


def render_apply_report(date: str, bilan: dict, dry_run: bool) -> str:
    """Rapport Markdown pur. Le mode figure aussi dans le NOM du fichier (spec §9).

    C'est la seule trace d'audit d'une commande qui écrit ~430 lieux : chaque anomalie y a
    sa section, et chaque cellule passe par `_cellule` pour ne pas casser son tableau.
    """
    lignes = [f"# Référentiel appliqué — {date}", "",
              f"Mode : {'simulation (aucune écriture)' if dry_run else 'écritures appliquées'}.",
              "",
              f"- Lieux créés : {len(bilan['crees'])}",
              f"- Lieux complétés : {len(bilan['completes'])}",
              f"- Retypages : {len(bilan['retypages'])}",
              f"- URLs à poser : {bilan['urls_ajoutees']}",
              f"- Appariés sur un doublon connu (non écrits) : {len(bilan['doublons_touches'])}",
              f"- Conflits d'appariement (non écrits) : {len(bilan['conflits'])}",
              f"- Sans parent résolu : {len(bilan['orphelins'])}",
              f"- Erreurs : {len(bilan['erreurs'])}", ""]
    lignes += _section("Créés", ["ISO", "Nom", "Type"], bilan["crees"])
    lignes += _section("Complétés", ["ISO", "Nom", "Type"], bilan["completes"])
    lignes += _section(
        "Retypages", ["ISO", "Nom", "Ancien type", "Nouveau type"], bilan["retypages"],
        chapeau="Seule écriture destructive du lot (spec §4) : un type PERSONNALISÉ devient "
                "natif. Chaque ligne figure ici pour qu'un retypage de masse — signe que la "
                "table des types natifs ne correspond plus au serveur — saute aux yeux.")
    lignes += _section(
        "Appariés sur un doublon de l'arbre — rien n'a été écrit",
        ["ISO", "Nom", "Lieux en doublon"], bilan["doublons_touches"],
        chapeau="`propose referentiel` a signalé ces lieux comme doublons. Rien ne dit lequel "
                "porte la vérité, donc aucune écriture (spec §5.4) : les arbitrer avec "
                "`merge places`, puis relancer.")
    lignes += _section(
        "Conflits d'appariement — rien n'a été écrit",
        ["Premier", "Second", "Nom", "Lieu"], bilan["conflits"],
        chapeau="Deux entrées du YAML relu désignent le MÊME lieu. Écrire la seconde "
                "écraserait ce que la première a posé : seule la première a été écrite, et "
                "les deux codes sont rendus ici pour arbitrage.")
    lignes += _section(
        "Sans parent résolu", ["ISO", "Parent attendu (QID)"], bilan["orphelins"],
        chapeau="Ces lieux ont été écrits sans rattachement : leur parent n'est ni dans le "
                "YAML relu, ni identifiable dans l'arbre. À rattacher à la main.")
    lignes += _section("Erreurs", ["ISO", "Message"], bilan["erreurs"], vide="Aucune erreur.")
    return "\n".join(lignes)


def run_referentiel_apply(client, yaml_path, output_dir, *, date: str,
                          dry_run: bool = False) -> Path:
    """Applique le YAML relu : crée les lieux absents, complète les autres. Rend le rapport."""
    dry_run = effective_dry_run(dry_run)
    doc = yaml.safe_load(Path(yaml_path).read_text(encoding="utf-8")) or {}
    cibles = _cibles_du_yaml(doc)
    handles_doublons = {h: d for d in (doc.get("doublons_arbre") or [])
                        for h in d.get("handles") or []}

    places = [place for lot in iter_places(client, "all", 200, None) for place in lot]
    par_qid = index_par_qid(places)
    par_nom_type = index_par_nom_type(places)
    par_nom = index_par_nom_contenant(places)
    par_handle = {p["handle"]: p for p in places}

    createur, majeur, urleur = (GrampsCreatePlaceTool(), GrampsUpdatePlaceTool(),
                                GrampsAddUrlTool())
    handles_qid = dict(par_qid)
    consommes: dict[str, str] = {}          # handle -> ISO de l'entrée qui l'a déjà pris
    bilan: dict = {"crees": [], "completes": [], "retypages": [], "doublons_touches": [],
                   "conflits": [], "orphelins": [], "erreurs": [], "urls_ajoutees": 0}

    # Niveau 0 (pays), puis 1, puis 2 : un enfant ne peut pas se rattacher à un parent
    # qui n'existe pas encore. `_cibles_du_yaml` a déjà trié.
    for sub in cibles:
        ident = identifiant(sub)
        # L'appariement et la décision sont DANS le try : une seule place malformée ne doit
        # pas faire sauter la boucle et emporter le rapport des écritures déjà faites.
        try:
            parent_handle = handles_qid.get(sub.parent_qid) if sub.parent_qid else None
            handle = apparier(sub, par_qid, par_nom_type, par_nom,
                              par_handle=par_handle, parent_handle=parent_handle)
            place = par_handle.get(handle) if handle else None
            gid = (place or {}).get("gramps_id", "")

            if handle and handle in handles_doublons:
                doublon = handles_doublons[handle]
                bilan["doublons_touches"].append(
                    (ident, sub.libelle_fr, ", ".join(doublon.get("gramps_ids") or [])))
                continue
            if handle and handle in consommes:
                # `par_handle` est un cache lu une fois : une seconde écriture sur le même
                # handle relirait un état périmé, écraserait le code posé par la première,
                # et rattacherait le lieu à lui-même.
                bilan["conflits"].append((consommes[handle], ident, sub.libelle_fr, gid))
                continue
            porte = qid_pose(place) if place else None
            if porte and sub.qid and porte != sub.qid:
                # Un QID posé est une affirmation d'identité. Diverger n'est pas un détail à
                # empiler dans `urls` : au run suivant, l'ordre de la liste déciderait.
                bilan["erreurs"].append(
                    (ident, f"le lieu {gid} affirme déjà le QID {porte}, "
                            f"incompatible avec {sub.qid}"))
                continue

            plan = decider(sub, place)
            if plan.get("type_illisible"):
                bilan["erreurs"].append(
                    (ident, f"type de lieu illisible sur {gid} "
                            f"({type(place.get('place_type')).__name__}) : aucune écriture, "
                            "la table des types natifs ne peut pas arbitrer"))
                continue

            if sub.parent_qid and parent_handle is None:
                bilan["orphelins"].append((ident, sub.parent_qid))
            if parent_handle is not None and parent_handle == handle:
                # Jamais un lieu comme son propre parent : ce serait un cycle dans la
                # hiérarchie, invisible en base et fatal à tout parcours de contenants.
                bilan["erreurs"].append((ident, "parent identique au lieu lui-même : "
                                                "rattachement abandonné"))
                parent_handle = None

            if plan["action"] == "creer":
                payload = json.loads(createur._run(
                    name=plan["name"], place_type=plan["place_type"],
                    parent_handle=parent_handle, lat=plan["lat"], long=plan["long"],
                    code=plan["code"], dry_run=dry_run))
                if not payload["success"]:
                    raise RuntimeError(payload["error"])
                handle = payload["data"]["handle"]
                bilan["crees"].append((ident, sub.libelle_fr, sub.place_type))
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
                bilan["completes"].append((ident, sub.libelle_fr, sub.place_type))
                if plan.get("retypage"):
                    bilan["retypages"].append((ident, sub.libelle_fr, *plan["retypage"]))

            consommes[handle] = ident
            handles_qid[sub.qid] = handle
            if handle.startswith("DRYRUN:"):
                # Un handle simulé ne désigne aucun objet : l'interroger ferait un 404. Les
                # URLs sont comptées quand même, sans quoi l'aperçu qui autorise l'écriture
                # annoncerait 0 URL là où le run réel en posera deux par lieu créé.
                bilan["urls_ajoutees"] += len(plan["urls"])
            else:
                for url in plan["urls"]:
                    reponse = json.loads(urleur._run(
                        object_type="places", handle=handle, url=url["path"],
                        description=url["desc"], dry_run=dry_run))
                    if not reponse["success"]:
                        raise RuntimeError(reponse["error"])
                    bilan["urls_ajoutees"] += int(reponse["data"]["changed"])
        except (RuntimeError, KeyError, TypeError, ValueError, AttributeError) as exc:
            # Tuple explicite plutôt qu'un `except Exception` : on absorbe l'échec d'API et
            # la donnée malformée, pas une erreur de programmation d'une autre nature.
            bilan["erreurs"].append((ident, exc))

    mode = "simulation" if dry_run else "ecritures"
    out = Path(output_dir) / "referentiel"
    out.mkdir(parents=True, exist_ok=True)
    report_path = out / f"{date}_referentiel_applique_{mode}.md"
    report_path.write_text(render_apply_report(date, bilan, dry_run), encoding="utf-8")
    return report_path
