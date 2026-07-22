"""`apply referentiel` : écrit les pays et subdivisions du YAML relu.

Invariant (spec §5.5) : toute écriture est une création, le remplissage d'un champ vide, ou
un ajout dans une liste. Seule exception assumée, le retypage d'un type PERSONNALISÉ vers un
type natif (`Wilaya` → `Province`). C'est cet invariant qui autorise l'écriture directe, sans
détour par une seconde relecture.

Cet invariant protège contre la **destruction**, pas contre l'écriture d'une valeur juste sur
le **mauvais objet** : un GPS posé sur un homonyme n'écrase rien et reste une donnée fausse.
D'où la règle qui gouverne tout l'appariement de ce module :

    écrire sur le mauvais lieu est irréversible en pratique — une fois la donnée posée, plus
    rien ne distingue le juste du faux ; créer un doublon est réversible et outillé
    (`merge places`). Dans le doute, on crée, et on dit ce qu'on a fait.

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
# candidat au retypage. D'où deux gardes — `type_lisible` écarte de l'appariement tout lieu
# dont le type n'est pas une chaîne, et le rapport liste **chaque** retypage ligne à ligne.
# Un retypage de masse ne peut pas passer inaperçu. La spec affirme aussi que `Wilaya` est le
# seul type personnalisé de l'arbre : ce n'est pas mesuré, et c'est cette section de rapport
# qui le vérifie au run.
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


# --- lecture défensive d'un lieu --------------------------------------------------------

def type_lisible(place: dict) -> str | None:
    """Le `place_type` du lieu comme chaîne (`""` s'il est absent), `None` s'il n'en est pas.

    La normalisation se fait ICI, à la lecture, et pas au moment de décider : un
    `place_type` non hachable faisait sauter la construction des index — hors de toute
    boucle et de tout `try`, donc traceback nu et aucun rapport écrit.
    """
    brut = place.get("place_type")
    if brut is None:
        return ""
    return brut if isinstance(brut, str) else None


def qids_poses(place: dict) -> list[str]:
    """Les QID distincts affirmés par les `urls` du lieu, dans l'ordre de la liste."""
    vus: list[str] = []
    for url in place.get("urls") or []:
        if not isinstance(url, dict):
            continue
        chemin = url.get("path") or ""
        if chemin.startswith(_WIKIDATA):
            qid = chemin[len(_WIKIDATA):]
            if qid not in vus:
                vus.append(qid)
    return vus


def qid_pose(place: dict) -> str | None:
    """Le QID affirmé par le lieu. `None` s'il n'en porte aucun — **ou plusieurs**.

    Rendre le premier reviendrait à laisser l'ordre de la liste `urls` décider d'une
    identité, en silence, alors que ce module refuse par ailleurs de créer cette situation.
    """
    qids = qids_poses(place)
    return qids[0] if len(qids) == 1 else None


def motif_dexclusion(place: dict) -> str | None:
    """Pourquoi ce lieu ne peut être la cible d'aucune subdivision. `None` = exploitable.

    Un lieu exclu n'entre dans AUCUN index : on ne peut ni l'identifier ni arbitrer son
    type, donc on ne lui écrit rien. Il sort au rapport.
    """
    if type_lisible(place) is None:
        return f"type de lieu illisible ({type(place.get('place_type')).__name__})"
    qids = qids_poses(place)
    if len(qids) > 1:
        return f"identités Wikidata concurrentes ({', '.join(qids)})"
    return None


# --- index de l'arbre -------------------------------------------------------------------
# L'index par QID retient le PREMIER lieu rencontré : un QID est une identité, deux lieux
# le portant est une anomalie traitée ailleurs (`motif_dexclusion`).
#
# Les index par NOM retiennent en revanche TOUS les homonymes. N'en garder qu'un a un coût
# mesuré sur l'arbre réel : il porte deux lieux nommés `Souk Ahras` — un `Department`
# rattaché à lui-même (cycle préexistant dans les données) et la vraie `Wilaya` sous
# l'Algérie. Le premier gagnait l'index, était jugé « rattaché ailleurs », et la wilaya
# correctement rattachée n'était jamais examinée : une duplication alors qu'un appariement
# parfait existait, à deux lignes de là.
#
# Les listes sont triées par `gramps_id`, donc deux exécutions évaluent les candidats dans
# le même ordre — c'est ce déterminisme qui rend une simulation représentative de l'écriture
# qu'elle autorise.


def _handles_ordonnes(places: list[dict]) -> list[str]:
    """Les handles d'un lot d'homonymes, dans un ordre stable d'une exécution à l'autre."""
    return [p["handle"] for p in sorted(places, key=lambda p: p.get("gramps_id", ""))]


def index_par_qid(places: list[dict]) -> dict[str, str]:
    """QID → handle, lu dans les `urls` des lieux. L'identité durable de l'appariement."""
    index: dict[str, str] = {}
    for place in places:
        if motif_dexclusion(place):
            continue
        qid = qid_pose(place)
        if qid:
            index.setdefault(qid, place["handle"])
    return index


def index_par_nom_type(places: list[dict]) -> dict[tuple[str, str], list[str]]:
    """(nom, type) → TOUS les handles homonymes. Repli d'avant la pose des QID."""
    index: dict[tuple[str, str], list[dict]] = {}
    for place in places:
        if motif_dexclusion(place):
            continue
        nom = (place.get("name") or {}).get("value", "")
        if nom:
            index.setdefault((nom, type_lisible(place)), []).append(place)
    return {cle: _handles_ordonnes(lot) for cle, lot in index.items()}


def index_par_nom_contenant(places: list[dict]) -> dict[str, list[str]]:
    """nom → TOUS les handles CONTENANTS homonymes. Dernière prise de l'appariement."""
    index: dict[str, list[dict]] = {}
    for place in places:
        if motif_dexclusion(place):
            continue
        nom = (place.get("name") or {}).get("value", "")
        if nom and type_lisible(place) in TYPES_CONTENANTS:
            index.setdefault(nom, []).append(place)
    return {nom: _handles_ordonnes(lot) for nom, lot in index.items()}


def _handles_designants(qid: str, noms: list[str], place_type: str,
                        places: list[dict]) -> set[str]:
    """TOUS les lieux de l'arbre qui peuvent désigner cette entité : porteurs du QID et
    homonymes contenants. Un lieu portant un AUTRE QID est une identité distincte."""
    handles = set()
    for place in places:
        if motif_dexclusion(place):
            continue
        porte = qid_pose(place)
        if qid and porte == qid:
            handles.add(place["handle"])
            continue
        if porte is not None and porte != qid:
            continue
        nom = (place.get("name") or {}).get("value", "")
        type_ = type_lisible(place)
        if nom in noms and (type_ == place_type or type_ in TYPES_CONTENANTS):
            handles.add(place["handle"])
    return handles


def handles_designant(sub: Subdivision, places: list[dict]) -> set[str]:
    """TOUS les lieux de l'arbre qui pourraient désigner cette subdivision.

    Sert à borner les prises par le parent. Un enfant rattaché à **n'importe lequel** des
    lieux qui désignent le parent est au bon endroit : sans cet ensemble, un arbre portant
    deux `France` — le QID sur l'une, les régions sous l'autre, configuration ordinaire —
    ferait créer un second exemplaire de chaque région sous la « bonne » France, tandis que
    la région existante, correctement rattachée, ne recevrait rien.
    """
    return _handles_designants(sub.qid, sub.noms, sub.place_type, places)


def handles_designants_initiaux(places: list[dict]) -> dict[str, set[str]]:
    """QID → tous les lieux qui le désignent, AVANT toute écriture.

    Amorcer avec le seul lieu porteur du QID suffirait si l'arbre n'avait pas de doublons ;
    il en a. Un pays présent en deux exemplaires et **absent du YAML relu** — donc jamais
    réapparié pendant le run — laisserait sinon ses enfants rattachés à l'exemplaire sans
    QID passer pour mal placés, et chacun serait recréé.
    """
    index: dict[str, set[str]] = {}
    for place in places:
        if motif_dexclusion(place):
            continue
        qid = qid_pose(place)
        if not qid:
            continue
        nom = (place.get("name") or {}).get("value", "")
        index.setdefault(qid, set()).update(
            _handles_designants(qid, [nom], type_lisible(place), places))
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


# --- appariement ------------------------------------------------------------------------

def verdict_candidat(sub: Subdivision, place: dict | None, parents: set[str]) -> str:
    """Que faire d'un candidat trouvé par son NOM ? (spec §5.3) Trois issues, jamais deux.

    Le rattachement du candidat est traité comme une **preuve**, et le verdict suit ce que
    cette preuve établit :

    - `"creer"` — le candidat est prouvé étranger à la cible. Deux cas : un lieu typé
      `Country` n'est jamais une subdivision (sans quoi l'État américain `Géorgie` s'apparie
      au **pays** Géorgie et reçoit le GPS d'Atlanta) ; ou il est rattaché AILLEURS que sous
      le parent attendu, ce qui le range dans une autre branche de l'arbre — c'est ce qui
      protège le `Province` « Limbourg » néerlandais des données du Limbourg belge.
    - `"apparier"` — le candidat est sous le parent attendu, ou aucun parent n'est connu et
      il n'y a alors rien à exiger.
    - `"confirmer"` — la preuve est **indisponible**, de l'un ou l'autre côté. Soit le
      candidat n'a AUCUN rattachement — c'est exactement la population pour laquelle le nom
      vernaculaire existe, les quatre `State` allemands en base sous `Bayern`, `Hessen`… et
      créer `Bavière` à côté de `Bayern` serait le pire des trois résultats. Soit le parent
      attendu est **introuvable** : `charger_entites_pays` rend `{}` quand son appel échoue
      pendant que `charger_pays` réussit, donc un YAML d'apparence normale peut porter 430
      subdivisions et **aucun** pays. Traiter ce cas comme « rien à exiger » rouvrirait en
      silence le défaut du Limbourg néerlandais.

    Seul un `parent_qid` VIDE — un pays — autorise vraiment à ne rien exiger.
    """
    if place is None:
        return "apparier"
    if sub.niveau > 0 and type_lisible(place) == "Country":
        return "creer"
    if not sub.parent_qid:
        return "apparier"
    if not parents:
        return "confirmer"
    refs = {ref.get("ref") for ref in place.get("placeref_list") or []
            if isinstance(ref, dict)}
    if not refs:
        return "confirmer"
    return "apparier" if refs & parents else "creer"


def apparier(sub: Subdivision, par_qid: dict[str, str],
             par_nom_type: dict[tuple[str, str], list[str]],
             par_nom: dict[str, list[str]], *,
             par_handle: dict[str, dict] | None = None,
             parents: set[str] | frozenset[str] = frozenset()) -> tuple[str, str | None]:
    """Trois prises, dans l'ordre : QID, puis (nom, type), puis nom seul chez les contenants.

    Rend `(verdict, handle)` — voir `verdict_candidat` pour les trois verdicts. `"creer"`
    vient toujours avec un handle `None` : il n'y a rien à écrire.

    Les noms essayés sont ceux de `sub.noms` — français d'abord, vernaculaire ensuite —
    parce que l'arbre porte `Bayern` là où Wikidata rend `Bavière`.

    Le QID est une identité : il s'impose seul, sans passer par `verdict_candidat`. Les deux
    prises par le nom ne sont que des présomptions ; `par_handle` leur donne les lieux dont
    elles ont besoin pour se juger, `parents` les handles du parent attendu.

    **Tous** les candidats homonymes sont évalués avant de conclure — un candidat à
    confirmer, ou franchement mal placé, ne coupe pas la recherche. Le premier qui obtient
    `"apparier"` l'emporte ; à défaut c'est le verdict le plus informatif qui est rendu,
    `"confirmer"` primant sur `"creer"` puisqu'il demande un arbitrage humain au lieu de
    créer en silence.
    """
    if sub.qid and sub.qid in par_qid:
        return "apparier", par_qid[sub.qid]
    index = par_handle or {}
    a_confirmer: str | None = None
    for prise in ([h for nom in sub.noms for h in par_nom_type.get((nom, sub.place_type), [])],
                  [h for nom in sub.noms for h in par_nom.get(nom, [])]):
        for handle in prise:
            verdict = verdict_candidat(sub, index.get(handle), set(parents))
            if verdict == "apparier":
                return "apparier", handle
            if verdict == "confirmer" and a_confirmer is None:
                a_confirmer = handle
    if a_confirmer is not None:
        return "confirmer", a_confirmer
    return "creer", None


def _urls_de(sub: Subdivision) -> list[dict]:
    urls = [{"path": f"{_WIKIDATA}{sub.qid}", "desc": "Wikidata"}] if sub.qid else []
    if sub.frwiki:
        urls.append({"path": sub.frwiki, "desc": "Wikipédia"})
    return urls


def decider(sub: Subdivision, place: dict | None) -> dict:
    """Les champs à écrire pour une subdivision, selon le lieu existant (None = absent).

    Rien de ce qui est déjà rempli n'est touché — le nom en particulier n'est jamais réécrit :
    `Bayern` reste `Bayern` et `Bavière` rejoint ses `alt_names`.

    Le drapeau `type_illisible` est un contrat pour tout appelant direct : `run_referentiel_
    apply` écarte ces lieux bien avant, dès la construction des index.
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
    type_existant = type_lisible(place)
    if type_existant is None:
        plan["type_illisible"] = True
    elif type_existant != sub.place_type and (type_existant in _TYPES_VIDES
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


def resume_du_plan(plan: dict) -> str:
    """Ce qu'une écriture aurait posé, en une ligne.

    Sert la section « Homonymes non rattachés » : sans cette colonne, la relecture est une
    enquête (ouvrir le lieu, ouvrir Wikidata, comparer) au lieu d'être une décision.
    """
    morceaux = []
    if plan.get("place_type"):
        morceaux.append(f"type {plan['place_type']}")
    if plan.get("lat") or plan.get("long"):
        morceaux.append(f"GPS {plan.get('lat') or '?'}/{plan.get('long') or '?'}")
    if plan.get("code"):
        morceaux.append(f"code {plan['code']}")
    morceaux += [f"alt_name {alt['value']}" for alt in plan.get("alt_names") or []]
    if plan.get("urls"):
        morceaux.append(", ".join(url["path"] for url in plan["urls"]))
    return " ; ".join(morceaux) or "rien à poser"


def _cibles_du_yaml(doc: dict) -> list[Subdivision]:
    """Pays puis subdivisions, triés par niveau : un parent est toujours écrit avant l'enfant."""
    pays = [subdivision_de_pays(EntitePays(**entite)) for entite in doc.get("pays") or []]
    subs = [Subdivision(**sub) for sub in doc.get("subdivisions") or []]
    return sorted(pays + subs, key=lambda s: s.niveau)


# --- rapport ----------------------------------------------------------------------------

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
              f"- Homonymes non rattachés à confirmer (non écrits) : {len(bilan['a_confirmer'])}",
              f"- Appariés sur un doublon connu (non écrits) : {len(bilan['doublons_touches'])}",
              f"- Conflits d'appariement (non écrits) : {len(bilan['conflits'])}",
              f"- Descendance bloquée (non écrite) : {len(bilan['bloques'])}",
              f"- Lieux écartés de l'appariement : {len(bilan['exclus'])}",
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
        "Homonymes non rattachés — à confirmer",
        ["Lieu", "Nom en base", "ISO", "Subdivision", "Motif",
         "Ce qui aurait été posé"],
        bilan["a_confirmer"],
        chapeau="Un lieu de l'arbre porte ce nom, mais la preuve manque — il n'a aucun "
                "rattachement, ou le parent attendu est introuvable. Rien ne "
                "prouve qu'il est la cible visée, rien ne prouve le contraire. Écrire "
                "prendrait le risque du mauvais objet ; créer imposerait un nettoyage que "
                "personne n'a demandé. Donc rien n'a été fait, et la décision revient ici. "
                "Pour débloquer : poser le QID Wikidata sur le lieu (le prochain run "
                "l'appariera sans ambiguïté) ou le rattacher à son parent — sinon créer le "
                "lieu à la main.")
    lignes += _section(
        "Appariés sur un doublon de l'arbre — rien n'a été écrit",
        ["ISO", "Nom", "Lieux en doublon"], bilan["doublons_touches"],
        chapeau="`propose referentiel` a signalé ces lieux comme doublons. Rien ne dit lequel "
                "porte la vérité, donc aucune écriture (spec §5.4) : les arbitrer avec "
                "`merge places`, puis relancer.")
    lignes += _section(
        "Descendance bloquée — rien n'a été écrit",
        ["ISO", "Nom", "Bloqué par", "Motif"], bilan["bloques"],
        chapeau="Leur parent n'a pas été écrit, donc ces lieux naîtraient à la RACINE de "
                "l'arbre. Un lieu sans rattachement est un dégât silencieux ; un lieu non "
                "créé et nommé ici est un travail à faire, visible. Débloquer la cause, "
                "puis relancer.")
    lignes += _section(
        "Conflits d'appariement — rien n'a été écrit",
        ["Premier", "Second", "Nom", "Lieu"], bilan["conflits"],
        chapeau="Deux entrées du YAML relu désignent le MÊME lieu. Écrire la seconde "
                "écraserait ce que la première a posé : seule la première a été écrite, et "
                "les deux codes sont rendus ici pour arbitrage.")
    lignes += _section(
        "Lieux écartés de l'appariement", ["Lieu", "Motif"], bilan["exclus"],
        chapeau="Ces lieux de l'arbre ne peuvent servir de cible à aucune subdivision : leur "
                "type n'est pas exploitable, ou ils affirment plusieurs identités Wikidata. "
                "Ils n'entrent dans aucun index et ne reçoivent rien.")
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
    # Pas de filtre ici : un lieu écarté n'entre dans aucun index, donc `apparier` ne rend
    # jamais son handle et ce cache ne peut pas le servir.
    par_handle = {p["handle"]: p for p in places}

    createur, majeur, urleur = (GrampsCreatePlaceTool(), GrampsUpdatePlaceTool(),
                                GrampsAddUrlTool())
    handles_qid = dict(par_qid)                     # QID -> le handle où l'on écrit
    handles_designants = handles_designants_initiaux(places)
    consommes: dict[str, str] = {}                  # handle -> ISO qui l'a déjà pris
    ecartes: dict[str, tuple[str, str]] = {}        # QID non écrit -> (bloquant, motif)
    bilan: dict = {"crees": [], "completes": [], "retypages": [], "doublons_touches": [],
                   "a_confirmer": [], "conflits": [], "bloques": [], "orphelins": [],
                   "erreurs": [],
                   "exclus": [(p.get("gramps_id", p["handle"]), motif)
                              for p in places if (motif := motif_dexclusion(p))],
                   "urls_ajoutees": 0}

    # Niveau 0 (pays), puis 1, puis 2 : un enfant ne peut pas se rattacher à un parent
    # qui n'existe pas encore. `_cibles_du_yaml` a déjà trié.
    for sub in cibles:
        ident = identifiant(sub)
        # L'appariement et la décision sont DANS le try : une seule place malformée ne doit
        # pas faire sauter la boucle et emporter le rapport des écritures déjà faites.
        try:
            if sub.parent_qid and sub.parent_qid in ecartes:
                # Le parent n'a pas été écrit : créer l'enfant le ferait naître à la racine
                # de l'arbre. On propage le bloquant d'origine, pas le maillon intermédiaire.
                bilan["bloques"].append((ident, sub.libelle_fr, *ecartes[sub.parent_qid]))
                ecartes[sub.qid] = ecartes[sub.parent_qid]
                continue

            parents = handles_designants.get(sub.parent_qid, set()) if sub.parent_qid else set()
            verdict, handle = apparier(sub, par_qid, par_nom_type, par_nom,
                                       par_handle=par_handle, parents=parents)
            place = par_handle.get(handle) if handle else None
            gid = (place or {}).get("gramps_id", "")

            if handle and handle in handles_doublons:
                bilan["doublons_touches"].append(
                    (ident, sub.libelle_fr,
                     ", ".join(handles_doublons[handle].get("gramps_ids") or [])))
                ecartes[sub.qid] = (ident, "doublon de l'arbre")
                continue
            if verdict == "confirmer":
                # La preuve manque, d'un côté ou de l'autre. On rend la décision, avec de
                # quoi la prendre : le lieu visé, POURQUOI on hésite, et ce que
                # l'écriture aurait posé.
                motif = ("homonyme non rattaché" if parents
                         else f"parent {sub.parent_qid} non résolu")
                bilan["a_confirmer"].append(
                    (gid, (place or {}).get("name", {}).get("value", ""), ident,
                     sub.libelle_fr, motif, resume_du_plan(decider(sub, place))))
                ecartes[sub.qid] = (ident, motif)
                continue
            if handle and handle in consommes:
                # `par_handle` est un cache lu une fois : une seconde écriture sur le même
                # handle relirait un état périmé et écraserait ce que la première a posé.
                bilan["conflits"].append((consommes[handle], ident, sub.libelle_fr, gid))
                ecartes[sub.qid] = (ident, "conflit d'appariement")
                continue
            porte = qid_pose(place) if place else None
            if porte and sub.qid and porte != sub.qid:
                # Un QID posé est une affirmation d'identité. Diverger n'est pas un détail à
                # empiler dans `urls` : au run suivant, l'ordre de la liste déciderait.
                bilan["erreurs"].append(
                    (ident, f"le lieu {gid} affirme déjà le QID {porte}, "
                            f"incompatible avec {sub.qid}"))
                ecartes[sub.qid] = (ident, "identité Wikidata divergente")
                continue

            plan = decider(sub, place)
            parent_handle = handles_qid.get(sub.parent_qid) if sub.parent_qid else None
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
                    place_type=plan.get("place_type") or type_lisible(place) or "Unknown",
                    lat=plan.get("lat"), long=plan.get("long"), code=plan.get("code"),
                    placeref_list=placerefs, alt_names=plan["alt_names"], dry_run=dry_run))
                if not payload["success"]:
                    raise RuntimeError(payload["error"])
                bilan["completes"].append((ident, sub.libelle_fr, sub.place_type))
                if plan.get("retypage"):
                    bilan["retypages"].append((ident, sub.libelle_fr, *plan["retypage"]))

            consommes[handle] = ident
            handles_qid[sub.qid] = handle
            handles_designants[sub.qid] = {handle} | handles_designant(sub, places)
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
            if sub.qid not in handles_qid:
                # Rien n'a été écrit pour cette cible : sa descendance naîtrait à la racine.
                ecartes[sub.qid] = (ident, "erreur d'écriture")

    mode = "simulation" if dry_run else "ecritures"
    out = Path(output_dir) / "referentiel"
    out.mkdir(parents=True, exist_ok=True)
    report_path = out / f"{date}_referentiel_applique_{mode}.md"
    report_path.write_text(render_apply_report(date, bilan, dry_run), encoding="utf-8")
    return report_path
