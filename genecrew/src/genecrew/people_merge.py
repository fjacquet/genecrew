"""Fusion des doublons de personnes : étage auto exécuté, reste déposé en YAML.

Seul module du chantier à toucher au réseau — toute l'analyse est pure et vit
dans crewai_custom_tools. Voir docs/superpowers/specs/2026-07-20-fusion-doublons-personnes-design.md.
"""

from __future__ import annotations

import json
from pathlib import Path

import yaml
from crewai_custom_tools.tools.genealogy.analysis.duplicates import etager
from crewai_custom_tools.tools.genealogy.analysis.merge_plan import plan_fusions
from crewai_custom_tools.tools.genealogy.gramps.client import GrampsClient
from crewai_custom_tools.tools.genealogy.gramps.facts import FactsFetcher
from crewai_custom_tools.tools.genealogy.gramps.write_tools import (
    GrampsMergePeopleTool,
    GrampsUpdateGenderTool,
    effective_dry_run,
)
from crewai_custom_tools.tools.genealogy.models.domain import (
    MergeCluster,
    MergePair,
    PersonFacts,
)

from genecrew.batching import iter_people_batches

_TAILLE_LOT = 200


def _link(gramps_id: str, base_url: str) -> str:
    return f"[{gramps_id}]({base_url}/person/{gramps_id})"


def executer_grappes(
    grappes: list[MergeCluster], *, dry_run: bool = False
) -> tuple[list[tuple[str, str]], list[tuple[str, str]]]:
    """Exécute les fusions d'une liste de grappes. Rend (faites, erreurs).

    Le patch de genre précède impérativement la fusion : `Person.merge()` ignore
    le genre, le patcher après n'aurait aucun effet sur le résultat (spec §4.4).
    """
    fusion = GrampsMergePeopleTool()
    genre = GrampsUpdateGenderTool()
    faites: list[tuple[str, str]] = []
    erreurs: list[tuple[str, str]] = []
    for grappe in grappes:
        if grappe.gender_patch is not None:
            patch = json.loads(
                genre._run(
                    handle=grappe.phoenix_handle,
                    gender=grappe.gender_patch,
                    dry_run=dry_run,
                )
            )
            if not patch["success"]:
                # Fusionner malgré l'échec du patch supprimerait le titanic ET
                # perdrait son genre sans trace — précisément ce que le patch
                # existe pour empêcher. On abandonne la grappe ; elle repassera
                # à la prochaine exécution.
                erreurs.append(
                    (
                        grappe.phoenix_gramps_id,
                        f"patch de genre échoué, fusion abandonnée : {patch['error']}",
                    )
                )
                continue
        # `titanic_handles` et `titanic_gramps_ids` sont construits ensemble, dans le
        # même ordre, à partir de la même liste `titanics` (plan_fusions) : la même
        # longueur est un invariant, pas une supposition. `strict=True` le fait
        # respecter — une désynchronisation lèverait plutôt que de tronquer en
        # silence une fusion irréversible (revue B905).
        for titanic_handle, titanic_id in zip(
            grappe.titanic_handles, grappe.titanic_gramps_ids, strict=True
        ):
            payload = json.loads(
                fusion._run(
                    phoenix_handle=grappe.phoenix_handle,
                    titanic_handle=titanic_handle,
                    dry_run=dry_run,
                )
            )
            if payload["success"]:
                faites.append((grappe.phoenix_gramps_id, titanic_id))
            else:
                erreurs.append((titanic_id, payload["error"]))
    return faites, erreurs


def filtrer_grappes_contradictoires(
    grappes: list[MergeCluster], par_handle: dict[str, PersonFacts]
) -> tuple[list[MergeCluster], list[tuple[str, str]]]:
    """Écarte les grappes dont le patch de genre masque un désaccord entre titanics.

    `plan_fusions` calcule `gender_patch` en prenant le premier titanic (trié par
    gramps_id) dont le sexe est connu — il ne vérifie jamais que TOUS les titanics
    s'accordent. Si une grappe patche le genre du phoenix (donc `phoenix.sex ==
    "U"`) alors que ses titanics portent des genres opposés (au moins un `M` ET au
    moins un `F`), c'est un signal que l'étage auto a peut-être mal jugé la paire
    (revue Task 5) : deux personnes réellement distinctes de sexes différents,
    rapprochées à tort par nom+date. On n'exécute pas la fusion — même traitement
    que l'échec du patch de genre : erreur consignée, grappe abandonnée, le lot
    continue.

    `MergeCluster` ne porte pas le sexe des titanics (seulement leurs handles/ids
    et le `gender_patch` déjà calculé) : la détection doit se faire ici, en amont
    de `executer_grappes`, tant que les `PersonFacts` du lot sont encore
    disponibles (`par_handle`).
    """
    valides: list[MergeCluster] = []
    erreurs: list[tuple[str, str]] = []
    for grappe in grappes:
        if grappe.gender_patch is not None:
            genres = {
                par_handle[h].sex for h in grappe.titanic_handles if h in par_handle
            }
            if "M" in genres and "F" in genres:
                erreurs.append(
                    (
                        grappe.phoenix_gramps_id,
                        "genres titanics contradictoires, fusion abandonnée",
                    )
                )
                continue
        valides.append(grappe)
    return valides, erreurs


def render_people_merge_report(
    date,
    passes,
    arbitrage,
    ignores,
    dry_run,
    fusions=(),
    base_url: str = "http://localhost",
) -> str:
    """Rapport Markdown : une ligne par passe, la liste nominative des fusions faites,
    puis les paires à relire.

    `fusions` est la liste des `(gramps_id_phoenix, gramps_id_titanic)` réellement
    fusionnés. Une suppression est irréversible : le rapport doit dire quel titanic
    a été absorbé par quel phoenix, pas seulement combien (revue Task 8), comme le
    fait `places_merge`.
    """
    mode = "simulation (dry-run, aucune fusion)" if dry_run else "fusions appliquées"
    total = sum(faites for _, faites, _ in passes)
    lines = [
        f"# Fusion des doublons de personnes — {date}",
        "",
        f"Mode : {mode}.",
        "",
        f"- Fusions automatiques : {total}",
        f"- Paires en arbitrage : {len(arbitrage)}",
        f"- Blocs ignorés (trop gros) : {len(ignores)}",
        "",
        "## Passes",
        "",
        "| Passe | Fusions | Erreurs |",
        "|---|---|---|",
    ]
    for numero, faites, erreurs in passes:
        lines.append(f"| {numero} | {faites} | {erreurs} |")
    derniere = passes[-1][1] if passes else 0
    if derniere:
        lines += [
            "",
            "La dernière passe a encore fusionné : la déduplication est "
            "transitive, **relancer** la commande pour aller plus loin.",
        ]
    lines += ["", "## Fusions", ""]
    if fusions:
        lines += ["| Gardé (phoenix) | Fusionné puis supprimé (titanic) |", "|---|---|"]
        for phoenix_id, titanic_id in fusions:
            lines.append(
                f"| {_link(phoenix_id, base_url)} | {_link(titanic_id, base_url)} |"
            )
    else:
        lines.append("Aucune.")
    lines += ["", "## Paires en arbitrage", ""]
    if arbitrage:
        lines += ["| A | B | Blocs |", "|---|---|---|"]
        for paire in arbitrage:
            lines.append(
                f"| {_link(paire.gramps_id_a, base_url)} | "
                f"{_link(paire.gramps_id_b, base_url)} | "
                f"{', '.join(paire.blocs)} |"
            )
    else:
        lines.append("Aucune.")
    lines += ["", "## Blocs ignorés", ""]
    lines.append(", ".join(f"`{c}`" for c in ignores) if ignores else "Aucun.")
    lines.append("")
    return "\n".join(lines)


def _collecter(client: GrampsClient, scope: str, limit: int | None):
    """Rend (personnes, familles) pour le périmètre demandé."""
    fetcher = FactsFetcher(client)
    personnes = []
    for lot in iter_people_batches(client, fetcher, scope, _TAILLE_LOT, limit):
        personnes.extend(lot)
    familles: dict = {}
    for personne in personnes:
        for handle in (*personne.parent_family_handles, *personne.family_handles):
            if handle not in familles:
                famille = fetcher.get_family_facts(handle)
                if famille is not None:
                    familles[handle] = famille
    return personnes, familles


def run_people_merge(
    client: GrampsClient,
    output_dir,
    *,
    scope: str,
    date: str,
    limit: int | None = None,
    max_passes: int = 5,
    dry_run: bool = False,
) -> Path:
    """Détecte, fusionne l'étage auto, dépose l'arbitrage en YAML. Rend le rapport."""
    output_dir = Path(output_dir)
    # Le dry-run EFFECTIF (env inclus) gouverne TOUT : la boucle, l'exécution et le
    # rapport. Sans cette normalisation, une simulation venue de GENECREW_DRY_RUN=true
    # (le garde-fou du projet) laissait la boucle tourner max_passes fois pour rien et
    # produisait un rapport qui s'annonçait « simulation » tout en comptant des fusions.
    eff = effective_dry_run(dry_run)
    passes: list[tuple[int, int, int]] = []
    fusions: list[tuple[str, str]] = []
    arbitrage: list = []
    ignores: list[str] = []
    for numero in range(1, max_passes + 1):
        personnes, familles = _collecter(client, scope, limit)
        par_handle = {p.handle: p for p in personnes}
        paires, ignores = etager(personnes, familles)
        arbitrage = [p for p in paires if p.tier == "arbitrage"]
        grappes = plan_fusions(paires, par_handle)
        grappes, erreurs_contradiction = filtrer_grappes_contradictoires(
            grappes, par_handle
        )
        faites, erreurs = executer_grappes(grappes, dry_run=eff)
        erreurs = erreurs_contradiction + erreurs
        fusions.extend(faites)
        passes.append((numero, len(faites), len(erreurs)))
        # En simulation, rien n'a changé côté serveur : une seconde passe
        # relirait les mêmes données et boucler serait sans objet.
        if not faites or eff:
            break
    out = output_dir / "doublons"
    out.mkdir(parents=True, exist_ok=True)
    scope_slug = scope.replace(":", "_")
    (out / f"{date}_arbitrage_doublons_{scope_slug}.yaml").write_text(
        yaml.safe_dump(
            [p.model_dump() for p in arbitrage], allow_unicode=True, sort_keys=False
        ),
        encoding="utf-8",
    )
    path = out / f"{date}_fusions_doublons_{scope_slug}.md"
    path.write_text(
        render_people_merge_report(
            date, passes, arbitrage, ignores, eff, fusions=fusions
        ),
        encoding="utf-8",
    )
    return path


def run_people_merge_yaml(
    client: GrampsClient, merges_yaml, output_dir, *, date: str, dry_run: bool = False
) -> Path:
    """Exécute les paires d'arbitrage conservées après relecture humaine.

    Le survivant et le patch de genre sont recalculés à partir des VRAIS
    `PersonFacts` des deux personnes, via le même `plan_fusions` que le chemin
    automatique. C'est essentiel : figer phoenix=A/titanic=B avec `gender_patch=None`
    perdrait le genre d'un titanic connu face à un phoenix « inconnu » — le chemin
    relu par un humain serait alors moins sûr que le chemin auto (revue Task 8).
    Passer par `plan_fusions` fait aussi profiter le YAML de l'union-find (une paire
    A-B et B-C relues forment une seule grappe) et du filtre des genres contradictoires.
    """
    eff = effective_dry_run(dry_run)
    output_dir = Path(output_dir)
    paires_yaml = yaml.safe_load(Path(merges_yaml).read_text(encoding="utf-8")) or []
    fetcher = FactsFetcher(client)
    mpaires: list[MergePair] = []
    par_handle: dict[str, PersonFacts] = {}
    erreurs_collecte: list[tuple[str, str]] = []
    for p in paires_yaml:
        a = fetcher.get_person_facts(p["handle_a"])
        b = fetcher.get_person_facts(p["handle_b"])
        if a is None or b is None:
            manquant = p["gramps_id_a"] if a is None else p["gramps_id_b"]
            erreurs_collecte.append((manquant, "personne introuvable, paire ignorée"))
            continue
        par_handle[a.handle] = a
        par_handle[b.handle] = b
        mpaires.append(
            MergePair(
                gramps_id_a=a.gramps_id,
                gramps_id_b=b.gramps_id,
                handle_a=a.handle,
                handle_b=b.handle,
                tier="auto",
            )
        )
    grappes = plan_fusions(mpaires, par_handle)
    grappes, erreurs_contradiction = filtrer_grappes_contradictoires(
        grappes, par_handle
    )
    faites, erreurs = executer_grappes(grappes, dry_run=eff)
    erreurs = erreurs_collecte + erreurs_contradiction + erreurs
    out = output_dir / "doublons"
    out.mkdir(parents=True, exist_ok=True)
    slug = Path(merges_yaml).stem
    path = out / f"{date}_fusions_relues_{slug}.md"
    path.write_text(
        render_people_merge_report(
            date, [(1, len(faites), len(erreurs))], [], [], eff, fusions=faites
        ),
        encoding="utf-8",
    )
    return path
