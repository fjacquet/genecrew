"""Import d'un lieu unique depuis une adresse libre — le moteur fuzzy en une commande.

`genecrew import place "Bourges, Cher, France"` : parse → résolution par pays (même
moteur que `propose places`) → si le score autorise l'écriture, création idempotente de la
hiérarchie (réutilise l'index de parents et la création de `places_apply`) + GPS/code
sur la feuille. Sous le seuil ou ambigu : affichage de la proposition, aucune écriture.
"""

from __future__ import annotations

import json

from crewai_custom_tools.tools.genealogy.geo.registry import (
    confiance_of, decide_action, resolve_place,
)
from crewai_custom_tools.tools.genealogy.gramps.client import GrampsClient
from crewai_custom_tools.tools.genealogy.gramps.write_tools import (
    GrampsCreatePlaceTool, effective_dry_run,
)
from crewai_custom_tools.tools.genealogy.standardize.places import parse_pname

from genecrew.places_apply import _ensure_parents, _seed_parent_index


def run_lieu_import(client: GrampsClient, raw: str, *, min_score: float = 0.90,
                    dry_run: bool = False) -> dict:
    """Resolve one raw place string; create its hierarchy when the score allows.

    Returns a summary dict: raw, action, confiance, resolved (or None), created,
    existing, handle, chain (chemin canonique), dry_run (effectif).
    """
    dry_run = effective_dry_run(dry_run)
    parsed = parse_pname(raw)
    resolved = resolve_place(parsed)
    action = decide_action(resolved, min_score)
    out = {
        "raw": raw, "action": action, "confiance": confiance_of(resolved, min_score),
        "resolved": resolved.model_dump() if resolved else None,
        "created": False, "existing": False, "handle": None, "chain": "",
        "dry_run": dry_run,
    }
    if action != "ecrire" or not resolved or not resolved.chains:
        return out

    # Contrat des résolveurs : chains = les PARENTS seuls ; la feuille vit dans
    # resolved.name/place_type/GPS/code (même lecture que places_apply).
    chain = resolved.chains[0]
    parents_path = ">".join(level.name for level in chain.levels)
    full_path = f"{parents_path}>{resolved.name}" if parents_path else resolved.name
    out["chain"] = full_path

    index = _seed_parent_index(client)
    if full_path in index:                          # déjà dans l'arbre — rien à créer
        out["existing"] = True
        out["handle"] = index[full_path]
        return out

    creator = GrampsCreatePlaceTool()
    parent_handle = _ensure_parents(chain, index, creator, dry_run)
    payload = json.loads(creator._run(
        name=resolved.name, place_type=resolved.place_type, parent_handle=parent_handle,
        date_qualifier=chain.date_qualifier, lat=resolved.lat, long=resolved.long,
        code=resolved.code, dry_run=dry_run))
    if not payload["success"]:
        raise RuntimeError(f"création de '{resolved.name}' : {payload['error']}")
    out["created"] = True
    out["handle"] = payload["data"]["handle"]
    return out


def format_lieu_import(out: dict) -> str:
    """Console rendering of a run_lieu_import summary. Pure."""
    lines = [f"Adresse   : {out['raw']}",
             f"Action    : {out['action']} (confiance {out['confiance']})"]
    r = out.get("resolved")
    if r:
        lines.append(f"Résolu    : {r['name']} [{r['place_type']}] "
                     f"GPS {r.get('lat')},{r.get('long')} code {r.get('code') or '—'} "
                     f"— {r['source']} (score {r['score']})")
    if out["chain"]:
        lines.append(f"Chaîne    : {out['chain'].replace('>', ' › ')}")
    if out["existing"]:
        lines.append(f"Déjà présent dans l'arbre : handle {out['handle']}")
    elif out["created"]:
        mode = "SIMULÉ (dry-run)" if out["dry_run"] else "créé"
        lines.append(f"Lieu {mode} : handle {out['handle']}")
    elif out["action"] != "ecrire":
        lines.append("Aucune écriture : score sous le seuil ou résolution ambiguë — "
                     "à traiter en proposition.")
    return "\n".join(lines)
