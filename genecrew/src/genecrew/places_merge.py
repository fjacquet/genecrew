"""Execute human-reviewed place merges (never automatic). Reads a fusions YAML."""

from __future__ import annotations

import json
import re
from pathlib import Path

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


def render_detect_report(date: str, fusions: list, arbitrage: list, errors: list,
                         total_lieux: int, dry_run: bool,
                         base_url: str = "http://localhost",
                         lot_borne: bool = False) -> str:
    """Rapport Markdown du mode détection. Pur.

    Les libellés se conjuguent avec le mode : en simulation rien n'est écrit, et un
    rapport ne doit jamais annoncer au présent une fusion qui n'a pas eu lieu.

    `lot_borne` dit qu'un `--limit` a tronqué la lecture. Il force les libellés au
    conditionnel comme une simulation ordinaire, mais **dit en plus pourquoi** : la
    documentation du projet recommande de borner les passages sur les lieux, si bien
    qu'un utilisateur consciencieux se retrouverait sans écriture ni explication et
    irait chercher une panne. La cause est nommée dans le rapport, pas seulement
    devinable depuis la ligne « Lieux examinés ».
    """
    simule = dry_run or lot_borne
    if lot_borne:
        mode = "simulation forcée (lot borné, aucune fusion)"
    elif dry_run:
        mode = "simulation (dry-run, aucune fusion)"
    else:
        mode = "écritures appliquées"
    titre_fusions = "Fusions à appliquer" if simule else "Fusions appliquées"
    lines = [f"# Doublons de lieux — {date}", "",
             f"Mode : {mode}.", ""]
    if lot_borne:
        lines += [*_AVERTISSEMENT_LOT_BORNE, ""]
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
        lines += ["## Arbitrage", "",
                  "Aucune preuve ne les départage : à relire, puis à exécuter avec "
                  "`merge places --yaml`.", "",
                  "| Gardé | Absorbé | Nom | Motif |", "|---|---|---|---|"]
        lines += [f"| {_link(p.gramps_id_keep, base_url)} "
                  f"| {_link(p.gramps_id_merge, base_url)} | {_cellule_sure(p.canonical)} "
                  f"| {_cellule_sure(p.reason)} |" for p in arbitrage]
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
                a_parent=bool(place.get("placeref_list")),
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
"""


def _ecrire_sorties(output_dir: Path, *, date: str, scope: str, fusions: list,
                    arbitrage: list, errors: list, total_lieux: int, dry_run: bool,
                    lot_borne: bool) -> Path:
    """Dépose le YAML d'arbitrage et le rapport ; rend le chemin du rapport.

    Extrait de `run_places_detect` pour être appelable depuis un `finally` : une
    fusion déjà exécutée est irréversible, elle doit être rapportée même quand une
    exception traverse la boucle.
    """
    out = Path(output_dir) / "lieux"
    out.mkdir(parents=True, exist_ok=True)
    scope_slug = scope.replace(":", "_")
    (out / f"{date}_arbitrage_lieux_{scope_slug}.yaml").write_text(
        _ENTETE_ARBITRAGE + yaml.safe_dump([p.model_dump() for p in arbitrage],
                                           allow_unicode=True, sort_keys=False),
        encoding="utf-8")
    path = out / f"{date}_doublons_lieux_{scope_slug}.md"
    path.write_text(render_detect_report(date, fusions, arbitrage, errors, total_lieux,
                                         dry_run, lot_borne=lot_borne),
                    encoding="utf-8")
    return path


def run_places_detect(client: GrampsClient, output_dir, *, scope: str, date: str,
                      limit: int | None = None, dry_run: bool = False) -> Path:
    """Détecte les doublons de lieux, fusionne les prouvés, dépose le reste en YAML.

    Une seule passe : les candidats sont groupés par égalité de nom normalisé, une
    relation d'équivalence — les groupes sont complets dès la lecture, et fusionner
    deux lieux n'en renomme aucun autre.

    **Un lot borné ne fusionne jamais.** `limit` tronque la lecture, donc tronque les
    groupes d'homonymes ; or la garde qui disqualifie une grappe mélangeant deux
    entités distinctes (codes officiels différents entre deux membres) est une
    propriété du groupe entier. Le membre écarté par la troncature peut être
    justement celui qui portait la preuve du mélange — et la fusion irréversible
    partirait alors toute seule. Poser `--limit` force donc la simulation, quel que
    soit `dry_run`, et le rapport le dit noir sur blanc.
    """
    lot_borne = limit is not None
    eff = effective_dry_run(dry_run) or lot_borne
    lieux = collecter_lieux(client, scope, limit=limit)
    propositions = etager_lieux(lieux)
    arbitrage = [p for p in propositions if p.verdict != "auto"]
    log = get_logger()
    if lot_borne:
        log.info("lot borné (limit=%s) : simulation forcée, un groupe d'homonymes "
                 "tronqué ne permet pas de décider d'une fusion irréversible", limit)

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
                                 lot_borne=lot_borne)
    return chemin
