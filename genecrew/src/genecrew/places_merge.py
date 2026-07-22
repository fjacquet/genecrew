"""Doublons de lieux : détection, fusion des couples PROUVÉS, arbitrage pour le reste.

Deux modes, un seul module :

  - **détection** (`run_places_detect`, `merge places --scope`) — lit le périmètre,
    groupe les homonymes, et **fusionne automatiquement** les couples que
    `etager_lieux` juge prouvés (même code officiel, ou mêmes coordonnées à type et
    contenant compatibles). Les autres partent en YAML d'arbitrage. C'est bien une
    écriture automatique, sous les gardes énumérées dans `run_places_detect` ;
  - **exécution** (`run_places_merge`, `merge places --yaml`) — rejoue un YAML
    **relu par un humain**, sans regarder le verdict : toute ligne présente est
    fusionnée.

Une fusion de lieux est IRRÉVERSIBLE : l'absorbé disparaît et ses références migrent
sans qu'on puisse ensuite dire d'où elles venaient. Tout ce qui suit — les gardes de
simulation forcée, les faits portés au fichier d'arbitrage — existe pour ça.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import NamedTuple

import httpx
import yaml

from crewai_custom_tools.tools.genealogy.analysis.place_duplicates import etager_lieux
from crewai_custom_tools.tools.genealogy.gramps.client import GrampsClient
from crewai_custom_tools.tools.genealogy.gramps.write_tools import (
    GrampsMergePlacesTool, effective_dry_run,
)
from crewai_custom_tools.tools.genealogy.models.domain import PlaceFacts

from genecrew.batching import iter_places
from genecrew.logging_setup import get_logger
from genecrew.scope import parse_scope


def _link(gramps_id: str, base_url: str) -> str:
    return f"[{gramps_id}]({base_url}/place/{gramps_id})"


_ESPACES = re.compile(r"\s+")


def _cellule_sure(valeur) -> str:
    """Rend une valeur issue des données de l'arbre sûre pour une cellule Markdown.

    Un nom de lieu ou un motif composé à partir de lui peut contenir n'importe quoi —
    l'arbre réel a des lieux du genre `', , Bourges - Cher, , , , ,'`. Deux dégâts
    possibles sur un tableau Markdown : un saut de ligne éclate la ligne du tableau en
    plusieurs lignes, et une barre verticale ajoute une colonne qui décale tout ce qui
    suit — un relecteur associerait alors la mauvaise preuve au mauvais couple
    gardé/absorbé sur une décision de fusion irréversible.

    Les blancs (dont les sauts de ligne) sont aplatis en un espace simple. La barre
    verticale est remplacée par son équivalent pleine chasse (｜, U+FF5C) : visuellement
    quasi identique, donc toujours lisible, mais jamais interprétée comme un séparateur
    de colonne par un moteur Markdown.
    """
    return _ESPACES.sub(" ", str(valeur)).strip().replace("|", "｜")


_ABSENT = "—"

# Les faits qu'un relecteur doit avoir sous les yeux pour trancher une paire d'arbitrage.
# La spécification du chantier les nomme : « types, codes, coordonnées et nombre de
# rétroliens en clair, pour que la relecture soit possible sans ouvrir Gramps ». Le
# CONTENANT s'y ajoute, et ce n'est pas du zèle : depuis qu'il discrimine les homonymes
# sans code officiel, c'est lui — et lui seul — qui explique pourquoi deux lieux de même
# type, même code absent et mêmes coordonnées atterrissent en arbitrage sous le motif
# « aucune preuve ». Sans lui, ce motif serait proprement incompréhensible.
#
# Une seule table pour l'en-tête du tableau ET pour les cellules : une colonne ne peut
# plus se décaler d'une ligne à l'autre.
_FAITS_ARBITRAGE = (
    ("Type", lambda p: p.place_type),
    ("Code", lambda p: p.code),
    ("Coordonnées", lambda p: f"{p.lat}, {p.long}" if p.lat and p.long else ""),
    ("Rétroliens", lambda p: str(p.retroliens)),
    ("Contenant", lambda p: p.parent_id),
)


def _valeur_de_fait(lieu, extraire) -> str:
    """Un fait d'un lieu, prêt pour une cellule ; `—` s'il manque ou si le lieu manque.

    Une cellule VIDE se lirait « je n'ai pas regardé » ; le tiret dit « non renseigné ».
    La distinction compte : c'est souvent l'absence d'un code qui explique le renvoi en
    arbitrage. Le lieu lui-même peut manquer quand le rapport est rendu sans les faits
    collectés (appel direct de `render_detect_report`, un rapport rejoué) — le tableau
    reste alors structurellement valide, seulement moins renseigné.
    """
    if lieu is None:
        return _ABSENT
    return _cellule_sure(extraire(lieu)) or _ABSENT


def _cellule_paire(garde, absorbe, extraire) -> str:
    """Le même fait pour les deux lieux d'une paire : « gardé / absorbé »."""
    return (f"{_valeur_de_fait(garde, extraire)} / "
            f"{_valeur_de_fait(absorbe, extraire)}")


def bloc_relecture(lieu) -> dict:
    """Les faits d'un lieu, en clair, tels qu'ils partent au fichier d'arbitrage. Pur.

    Volontairement **pas** un `model_dump()` de `PlaceFacts` : le fichier d'arbitrage est
    un document de relecture, pas un miroir du modèle partagé. Il n'a que faire du
    `handle`, du `gramps_id` ni du nom, tous déjà portés par la proposition, et il ne
    doit pas se mettre à suivre l'évolution d'un modèle qui appartient à la bibliothèque.
    Les clés sont en français comme le reste du fichier.
    """
    if lieu is None:
        return {}
    return {"type": lieu.place_type, "code": lieu.code, "lat": lieu.lat,
            "long": lieu.long, "contenant": lieu.parent_id,
            "retroliens": lieu.retroliens}


def render_merge_report(date, done, errors, dry_run, base_url="http://localhost") -> str:
    mode = "simulation (dry-run, aucune fusion)" if dry_run else "fusions appliquées"
    lines = [f"# Fusions de lieux — {date}", "", f"Mode : {mode}.", "",
             f"- Fusions : {len(done)}", f"- Erreurs : {len(errors)}", "", "## Fusions", ""]
    if done:
        lines += ["| Gardé | Fusionné | Canonique |", "|---|---|---|"]
        for keep, merge, canon in done:
            lines.append(f"| {_link(keep, base_url)} | {_link(merge, base_url)} "
                        f"| {_cellule_sure(canon)} |")
    else:
        lines.append("Aucune.")
    lines += ["", "## Erreurs", ""]
    lines += (["| Fusionné | Erreur |", "|---|---|"]
              + [f"| {_link(m, base_url)} | {_cellule_sure(e)} |" for m, e in errors]
              if errors else ["Aucune erreur."])
    lines.append("")
    return "\n".join(lines)


_AVERTISSEMENT_LOT_BORNE = [
    "> **Aucune écriture : lot borné par `--limit`.**",
    "> La garde qui refuse de fusionner une grappe d'homonymes dès qu'elle contient la",
    "> preuve qu'elle mélange deux entités distinctes est une propriété du groupe",
    "> **entier**. Tronquer la lecture tronque les groupes, et fait donc tomber la garde :",
    "> le membre exclu par la troncature est parfois justement celui qui portait la",
    "> preuve du mélange. Un lot borné ne permet pas de raisonner sur des groupes, donc",
    "> il ne permet pas d'écrire — ce passage est une simulation, quoi qu'on lui ait",
    "> demandé, et rien n'est en panne. Relancez **sans `--limit`** pour appliquer les",
    "> fusions.",
]


_AVERTISSEMENT_SCOPE_UNITAIRE = [
    "> **Aucune écriture : périmètre `place:` réduit à un seul lieu.**",
    "> Un doublon est une propriété d'un GROUPE d'homonymes, jamais d'un lieu isolé :",
    "> `--scope place:<ID>` ne lit qu'un lieu, qui ne peut donc former aucun groupe.",
    "> La commande ne trouvera jamais rien, et une ligne « aucun doublon détecté » se",
    "> lirait à tort comme une bonne nouvelle. Ce périmètre reste utile pour inspecter",
    "> ce que la collecte lit d'un lieu précis ; pour chercher des doublons, relancez",
    "> avec **`--scope all`**.",
]


def render_detect_report(date: str, fusions: list, arbitrage: list, errors: list,
                         total_lieux: int, dry_run: bool,
                         base_url: str = "http://localhost",
                         lot_borne: bool = False,
                         scope_unitaire: bool = False,
                         faits: dict | None = None) -> str:
    """Rapport Markdown du mode détection. Pur.

    Les libellés se conjuguent avec le mode : en simulation rien n'est écrit, et un
    rapport ne doit jamais annoncer au présent une fusion qui n'a pas eu lieu.

    Deux drapeaux disent qu'une LECTURE TRONQUÉE a forcé la simulation, chacun avec sa
    cause propre — et chacun avec son encadré, parce que les remèdes diffèrent :

      - `lot_borne` : un `--limit` a tronqué la lecture. La documentation du projet
        recommande de borner les passages sur les lieux, si bien qu'un utilisateur
        consciencieux se retrouverait sans écriture ni explication et irait chercher
        une panne. Remède : relancer sans `--limit` ;
      - `scope_unitaire` : `--scope place:<ID>` ne lit qu'un lieu, qui ne forme jamais
        de groupe d'homonymes. Sans cet encadré, le rapport annonçait « écritures
        appliquées » puis « aucun doublon détecté » — une absence de doublons qui
        n'était qu'une absence de regard. Remède : `--scope all`.

    `faits` associe un handle de lieu à ses `PlaceFacts` collectés. Il alimente le
    tableau d'arbitrage, seule table du rapport que la spécification veut lisible sans
    ouvrir Gramps. Optionnel : sans lui, les colonnes de faits portent `—` et le tableau
    reste structurellement valide.
    """
    faits = faits or {}
    simule = dry_run or lot_borne or scope_unitaire
    if lot_borne:
        mode = "simulation forcée (lot borné, aucune fusion)"
    elif scope_unitaire:
        mode = "simulation forcée (périmètre à un seul lieu, aucune fusion)"
    elif dry_run:
        mode = "simulation (dry-run, aucune fusion)"
    else:
        mode = "écritures appliquées"
    titre_fusions = "Fusions à appliquer" if simule else "Fusions appliquées"
    lines = [f"# Doublons de lieux — {date}", "",
             f"Mode : {mode}.", ""]
    if lot_borne:
        lines += [*_AVERTISSEMENT_LOT_BORNE, ""]
    if scope_unitaire:
        lines += [*_AVERTISSEMENT_SCOPE_UNITAIRE, ""]
    lines += [f"- Lieux examinés : {total_lieux}",
              f"- {titre_fusions} : {len(fusions)}",
              f"- À relire : {len(arbitrage)}",
              f"- Erreurs : {len(errors)}", ""]
    if fusions:
        lines += [f"## {titre_fusions}", "",
                  "| Gardé | Absorbé | Nom | Preuve | Perte évitée |",
                  "|---|---|---|---|---|"]
        lines += [f"| {_link(p.gramps_id_keep, base_url)} "
                  f"| {_link(p.gramps_id_merge, base_url)} | {_cellule_sure(p.canonical)} "
                  f"| {_cellule_sure(p.reason)} "
                  f"| {_cellule_sure(p.perte_evitee) or '—'} |" for p in fusions]
        lines.append("")
    if arbitrage:
        colonnes = ["Gardé", "Absorbé", "Nom",
                    *(f"{titre} (G/A)" for titre, _ in _FAITS_ARBITRAGE),
                    "Motif", "Perte évitée"]
        lines += ["## Arbitrage", "",
                  "Aucune preuve ne les départage : à relire, puis à exécuter avec "
                  "`merge places --yaml`.", "",
                  "Les faits sont donnés **pour les deux lieux** — `G` = gardé, "
                  "`A` = absorbé — pour que la relecture n'oblige pas à ouvrir Gramps ; "
                  f"« {_ABSENT} » = non renseigné. « Perte évitée » est ce que l'ordre "
                  "inverse aurait effacé.", "",
                  "| " + " | ".join(colonnes) + " |",
                  "|" + "---|" * len(colonnes)]
        for p in arbitrage:
            garde, absorbe = faits.get(p.handle_keep), faits.get(p.handle_merge)
            cellules = [_link(p.gramps_id_keep, base_url),
                        _link(p.gramps_id_merge, base_url),
                        _cellule_sure(p.canonical),
                        *(_cellule_paire(garde, absorbe, extraire)
                          for _titre, extraire in _FAITS_ARBITRAGE),
                        _cellule_sure(p.reason),
                        _cellule_sure(p.perte_evitee) or _ABSENT]
            lines.append("| " + " | ".join(cellules) + " |")
        lines.append("")
    if errors:
        lines += ["## Erreurs", ""]
        lines += [f"- {gid} : {_cellule_sure(msg)}" for gid, msg in errors]
        lines.append("")
    if not fusions and not arbitrage and not errors:
        lines += ["Aucun doublon détecté.", ""]
    return "\n".join(lines)


def _retroliens(client: GrampsClient, handle: str) -> int:
    """Nombre d'objets qui référencent ce lieu ; 0 si l'API ne répond pas.

    Un appel par lieu : coûteux, mais c'est la seule mesure qui dise lequel de deux
    homonymes l'arbre utilise réellement. Un échec ne doit pas faire échouer la
    détection — il dégrade seulement le départage vers les critères suivants.

    Un `handle` vide n'est jamais envoyé : `f"/places/{handle}"` s'effondrerait sur
    l'URL de *liste* des lieux (`/places/`) et rendrait des rétroliens sans rapport
    avec le lieu concerné — un départage faussé sur une fusion irréversible.

    La protection va jusqu'à la valeur rendue (pas seulement l'appel réseau) : une
    catégorie de rétroliens à `null` compte pour zéro sans faire tomber les autres
    catégories du même lieu, ni le reste du lot.

    On nomme ici les deux familles réellement attendues plutôt que d'attraper large :
    `httpx.HTTPError` couvre à la fois les statuts d'erreur HTTP (`raise_for_status`)
    et les coupures réseau (connexion refusée, expiration) — ce sont les deux modes
    d'échec normaux d'un appel API. Une régression future dans ce calcul (ex. une
    structure de données vraiment inattendue) doit remonter comme une erreur de
    programmation, pas se faire passer silencieusement pour une API indisponible.
    """
    if not handle:
        return 0
    try:
        objet = client.get_json(f"/places/{handle}", params={"backlinks": "1"}) or {}
        backlinks = objet.get("backlinks") or {}
        return sum(len(refs or []) for refs in backlinks.values())
    except httpx.HTTPError as exc:
        get_logger().warning("rétroliens de %s indisponibles : %s", handle, exc)
        return 0


def _contenant_unique(placeref_list) -> str:
    """Identifiant du contenant du lieu, ou `""` s'il n'est pas UNIQUE et CONNU. Pur.

    C'est le contrat que `PlaceFacts.parent_id` impose à l'orchestration, et il est
    la seule raison d'être de ce champ : `evaluer_preuve` s'en sert pour REFUSER une
    preuve par coordonnées entre deux homonymes rattachés à deux contenants
    différents — deux « Saint-Michel » au même point géocodé mais dans deux
    départements sont deux communes. Alimenter ici un booléen « a un contenant »
    laissait ce champ vide (pydantic ignore un champ inconnu **en silence**, la
    construction réussit) et rendait la garde entièrement inerte.

    Deux états rendent `""`, pour deux raisons distinctes :

      - **aucun** contenant : l'ignorance n'est pas une différence. Un arbre réel
        laisse le rattachement vide sur une bonne part de ses lieux ;
      - **plusieurs** contenants différents : une commune fusionnée porte deux
        `placeref_list` datées — le département avant la fusion, la commune
        absorbante après (`geo/france_ex_communes.py`). En choisir un
        arbitrairement — le premier de la liste, dont l'ordre n'est pas garanti —
        fabriquerait une différence là où il n'y en a pas, donc un refus de fusion
        sur un pur artefact de lecture, et pire : deux exécutions pourraient ne pas
        trancher pareil.

    L'unicité porte sur l'identifiant VISÉ, pas sur le nombre de lignes : deux
    références datées vers le même contenant restent un contenant unique. Une `ref`
    vide ou blanche n'est pas un contenant — elle ne vaut pas identifiant et ne rend
    pas ambigu celui qui l'accompagne.
    """
    refs = {(ref.get("ref") or "").strip()
            for ref in (placeref_list or []) if isinstance(ref, dict)}
    refs.discard("")
    return refs.pop() if len(refs) == 1 else ""


def collecter_lieux(client: GrampsClient, scope: str, batch_size: int = 200,
                    limit: int | None = None) -> list[PlaceFacts]:
    """Lit les lieux du périmètre et les réduit aux faits utiles à la détection."""
    lieux: list[PlaceFacts] = []
    for lot in iter_places(client, scope, batch_size, limit):
        for place in lot:
            if not isinstance(place, dict):
                continue
            handle = place.get("handle", "")
            lieux.append(PlaceFacts(
                gramps_id=place.get("gramps_id", ""),
                handle=handle,
                nom=(place.get("name") or {}).get("value", "") or "",
                place_type=place.get("place_type") or "",
                code=place.get("code") or "",
                lat=place.get("lat") or "",
                long=place.get("long") or "",
                parent_id=_contenant_unique(place.get("placeref_list")),
                retroliens=_retroliens(client, handle)))
    return lieux


def run_places_merge(client: GrampsClient, merges_yaml, output_dir, *, date: str,
                     dry_run: bool = False) -> Path:
    """Execute the merges listed in a reviewed YAML. Gated by dry_run + GENECREW_DRY_RUN."""
    output_dir = Path(output_dir)
    merges = yaml.safe_load(Path(merges_yaml).read_text(encoding="utf-8")) or []
    tool = GrampsMergePlacesTool()
    done: list = []
    errors: list = []
    for m in merges:
        payload = json.loads(tool._run(keep_handle=m["handle_keep"],
                                       merge_handle=m["handle_merge"], dry_run=dry_run))
        if payload["success"]:
            done.append((m["gramps_id_keep"], m["gramps_id_merge"], m.get("canonical", "")))
        else:
            errors.append((m["gramps_id_merge"], payload["error"]))
    out = output_dir / "lieux"
    out.mkdir(parents=True, exist_ok=True)
    slug = Path(merges_yaml).stem
    path = out / f"{date}_fusions_appliquees_{slug}.md"
    path.write_text(render_merge_report(date, done, errors, effective_dry_run(dry_run)),
                    encoding="utf-8")
    return path


_ENTETE_ARBITRAGE = """\
# Arbitrage de fusions de lieux — À RELIRE ET À ÉLAGUER AVANT EXÉCUTION.
#
# Aucune preuve suffisante ne départage les couples listés ici : la détection les a
# écartés de la fusion automatique et vous les renvoie. `merge places --yaml` ne
# regarde PAS le champ `verdict` — il exécutera TOUTES les lignes encore présentes.
# Une fusion de lieux est irréversible : le lieu absorbé est supprimé et ses
# références migrent sans qu'on puisse ensuite dire d'où elles venaient.
#
# Supprimez donc ici toute ligne que vous n'avez pas validée à la main.
# Ces lignes-ci sont des commentaires YAML : elles sont ignorées à la lecture, le
# fichier reste consommable tel quel.
#
# Le bloc `relecture` de chaque couple donne les faits des DEUX lieux — type, code,
# coordonnées, contenant, rétroliens — pour trancher sans ouvrir Gramps. Il est ignoré
# à l'exécution : `merge places --yaml` ne lit que les handles et les identifiants.
"""


def _ligne_arbitrage(proposition, faits: dict) -> dict:
    """Une proposition d'arbitrage augmentée des faits des deux lieux. Pur.

    Les faits vivent sous une clé `relecture` À PART, jamais mêlés aux champs de la
    proposition. Deux raisons, dans cet ordre :

      - le contrat de `merge places --yaml` ne change pas — il lit les mêmes clés
        qu'avant, à la même place, et ignore ce qu'il ne connaît pas. Le fichier reste
        consommable **tel quel**, sans transformation ;
      - `PlaceMergeProposition` appartient à la bibliothèque et sert aussi à
        `apply places`. L'élargir pour les besoins d'un document de relecture ferait
        porter à un modèle partagé la forme d'un fichier qui n'est pas le sien.
    """
    return {**proposition.model_dump(),
            "relecture": {"garde": bloc_relecture(faits.get(proposition.handle_keep)),
                          "absorbe": bloc_relecture(
                              faits.get(proposition.handle_merge))}}


def _ecrire_sorties(output_dir: Path, *, date: str, scope: str, fusions: list,
                    arbitrage: list, errors: list, total_lieux: int, dry_run: bool,
                    lot_borne: bool, scope_unitaire: bool, faits: dict) -> Path:
    """Dépose le YAML d'arbitrage et le rapport ; rend le chemin du rapport.

    Extrait de `run_places_detect` pour être appelable depuis un `finally` : une
    fusion déjà exécutée est irréversible, elle doit être rapportée même quand une
    exception traverse la boucle.
    """
    out = Path(output_dir) / "lieux"
    out.mkdir(parents=True, exist_ok=True)
    scope_slug = scope.replace(":", "_")
    (out / f"{date}_arbitrage_lieux_{scope_slug}.yaml").write_text(
        _ENTETE_ARBITRAGE + yaml.safe_dump([_ligne_arbitrage(p, faits)
                                            for p in arbitrage],
                                           allow_unicode=True, sort_keys=False),
        encoding="utf-8")
    path = out / f"{date}_doublons_lieux_{scope_slug}.md"
    path.write_text(render_detect_report(date, fusions, arbitrage, errors, total_lieux,
                                         dry_run, lot_borne=lot_borne,
                                         scope_unitaire=scope_unitaire, faits=faits),
                    encoding="utf-8")
    return path


class ResultatDetection(NamedTuple):
    """Ce que `run_places_detect` rend, et la SEULE source de vérité de ses gardes.

    Les deux drapeaux sont les booléens EXACTS qui ont servi à forcer la simulation,
    pas des valeurs recalculées après coup. La couche ligne de commande
    (`main.py::lieux_merge_cmd`) les consomme tels quels pour décider d'afficher ses
    avertissements — jamais en réinspectant `args.limit` ou `args.scope` de son côté,
    sous peine de pouvoir un jour annoncer « simulation forcée » pendant qu'une fusion
    irréversible a réellement lieu.

    Ils restent distincts plutôt que réunis en un « simulation forcée » : les causes
    diffèrent, et les remèdes aussi — relancer sans `--limit` d'un côté, avec
    `--scope all` de l'autre.
    """

    chemin: Path
    lot_borne: bool
    scope_unitaire: bool


def run_places_detect(client: GrampsClient, output_dir, *, scope: str, date: str,
                      limit: int | None = None,
                      dry_run: bool = False) -> ResultatDetection:
    """Détecte les doublons de lieux, fusionne les prouvés, dépose le reste en YAML.

    Une seule passe : les candidats sont groupés par égalité de nom normalisé, une
    relation d'équivalence — les groupes sont complets dès la lecture, et fusionner
    deux lieux n'en renomme aucun autre.

    **Une lecture tronquée ne fusionne jamais.** Un doublon est une propriété d'un
    GROUPE d'homonymes ; tout ce qui empêche de lire un groupe entier interdit donc de
    conclure. Deux périmètres tronquent, et forcent la simulation quel que soit
    `dry_run` :

      - `limit` tronque les groupes. Or la garde qui disqualifie une grappe mélangeant
        deux entités distinctes (codes officiels différents entre deux membres) est une
        propriété du groupe entier, et le membre écarté par la troncature peut être
        justement celui qui portait la preuve du mélange — la fusion irréversible
        partirait alors toute seule ;
      - `scope` en `place:<ID>` ne lit qu'UN lieu, qui ne forme jamais de groupe. Rien
        ne peut en sortir : la commande annonçait « écritures appliquées » puis « aucun
        doublon détecté », c'est-à-dire une absence de regard présentée comme une
        absence de doublons. Ce périmètre tronque plus fort que `--limit`, il méritait
        au moins la même garde.

    Le rapport dit les deux noir sur blanc, chacun avec son remède.

    Rend un `ResultatDetection` — voir sa docstring pour le contrat avec la CLI.
    """
    lot_borne = limit is not None
    scope_unitaire = parse_scope(scope)[0] == "place"
    eff = effective_dry_run(dry_run) or lot_borne or scope_unitaire
    lieux = collecter_lieux(client, scope, limit=limit)
    faits = {lieu.handle: lieu for lieu in lieux}
    propositions = etager_lieux(lieux)
    arbitrage = [p for p in propositions if p.verdict != "auto"]
    log = get_logger()
    if lot_borne:
        log.info("lot borné (limit=%s) : simulation forcée, un groupe d'homonymes "
                 "tronqué ne permet pas de décider d'une fusion irréversible", limit)
    if scope_unitaire:
        log.info("périmètre à un seul lieu (scope=%s) : simulation forcée, un lieu "
                 "isolé ne forme aucun groupe d'homonymes", scope)

    tool = GrampsMergePlacesTool()
    fusions: list = []
    errors: list = []
    try:
        # Le tri se fait sur `verdict`, JAMAIS sur le texte de `reason` : un couple
        # peut porter le motif « code officiel identique » et valoir quand même
        # « arbitrage » (quand la fusion écraserait un champ simple que seul
        # l'absorbé renseigne).
        for prop in (p for p in propositions if p.verdict == "auto"):
            if eff:
                fusions.append(prop)             # simulation : rapporté, jamais exécuté
                continue
            # `dry_run=False` en clair : la branche simulation ci-dessus a déjà pris la
            # main, donc `eff` vaudrait forcément False ici. Le transmettre laisserait
            # croire à une seconde barrière — il n'y en a qu'une, et elle est plus haut.
            payload = json.loads(tool._run(keep_handle=prop.handle_keep,
                                           merge_handle=prop.handle_merge,
                                           dry_run=False))
            if payload["success"]:
                # Journalisée ICI, au moment de l'écriture : c'est la seule trace qui
                # survive à une coupure ou à un Ctrl-C au milieu du lot.
                log.info("fusion de lieux exécutée : %s absorbé dans %s (%s)",
                         prop.gramps_id_merge, prop.gramps_id_keep, prop.canonical)
                fusions.append(prop)
            else:
                errors.append((prop.gramps_id_merge, payload["error"]))
    finally:
        # `finally` et non `except` : `KeyboardInterrupt` dérive de `BaseException`.
        # L'exception poursuit son chemin — on la trace, on ne l'avale pas.
        chemin = _ecrire_sorties(output_dir, date=date, scope=scope, fusions=fusions,
                                 arbitrage=arbitrage, errors=errors,
                                 total_lieux=len(lieux), dry_run=eff,
                                 lot_borne=lot_borne, scope_unitaire=scope_unitaire,
                                 faits=faits)
    return ResultatDetection(chemin, lot_borne, scope_unitaire)
