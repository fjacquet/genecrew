"""Execute human-reviewed place merges (never automatic). Reads a fusions YAML."""

from __future__ import annotations

import json
import re
from pathlib import Path

import httpx
import yaml

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


def render_detect_report(date: str, fusions: list, arbitrage: list, errors: list,
                         total_lieux: int, dry_run: bool,
                         base_url: str = "http://localhost") -> str:
    """Rapport Markdown du mode détection. Pur.

    Les libellés se conjuguent avec le mode : en simulation rien n'est écrit, et un
    rapport ne doit jamais annoncer au présent une fusion qui n'a pas eu lieu.
    """
    mode = "simulation (dry-run, aucune fusion)" if dry_run else "écritures appliquées"
    titre_fusions = "Fusions à appliquer" if dry_run else "Fusions appliquées"
    lines = [f"# Doublons de lieux — {date}", "",
             f"Mode : {mode}.", "",
             f"- Lieux examinés : {total_lieux}",
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
