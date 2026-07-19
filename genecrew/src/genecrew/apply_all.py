"""Commande parapluie : appliquer toutes les corrections auto en un passage.

Enchaîne la standardisation de la casse (forme), l'application des genres
(fait), puis la standardisation des lieux (fait), en partageant scope /
dry-run. Pure orchestration de run_names + run_gender_apply +
run_places_apply — aucun nouvel outil, aucune nouvelle règle.
"""

from __future__ import annotations

from pathlib import Path

from crewai_custom_tools.tools.genealogy.gramps.client import GrampsClient

from genecrew.gender_apply import run_gender_apply
from genecrew.names import run_names
from genecrew.places_apply import run_places_apply


def run_apply_all(client: GrampsClient, scope: str, output_dir, *, date: str,
                  min_ratio: float = 0.98, min_score: float = 0.90, batch_size: int = 25,
                  limit: int | None = None, dry_run: bool = False) -> dict[str, Path]:
    """Applique la casse (noms), le genre, puis les lieux sur `scope`.

    Retourne les chemins des rapports (ordre : casse → genre → lieux).
    """
    names_report, incomplete = run_names(
        client, scope, output_dir, date=date, batch_size=batch_size,
        limit=limit, dry_run=dry_run)
    gender_report = run_gender_apply(
        client, scope, output_dir, date=date, min_ratio=min_ratio,
        batch_size=batch_size, limit=limit, dry_run=dry_run)
    lieux_report = run_places_apply(
        client, scope, output_dir, date=date, min_score=min_score,
        batch_size=batch_size, limit=limit, dry_run=dry_run)
    return {"names": names_report, "incomplete": incomplete, "gender": gender_report,
            "lieux": lieux_report}
