"""`propose referentiel` : les subdivisions administratives des pays, en lecture seule.

Interroge Wikidata pays par pays, rend un rapport Markdown et le YAML que `apply referentiel`
consommera. N'écrit jamais dans Gramps.
"""

from __future__ import annotations

from collections import defaultdict
from pathlib import Path

import yaml

from crewai_custom_tools.tools.genealogy.referentiel.chargement import (
    EntitePays, ResultatPays, charger_entites_pays, charger_pays,
)
from crewai_custom_tools.tools.genealogy.referentiel.config import PAYS_REFERENTIEL

from genecrew.batching import iter_places


def doublons_de_larbre(places: list[dict]) -> list[dict]:
    """Lieux partageant nom + type + parent : signalés, jamais fusionnés (spec §5.4).

    C'est le cas des deux `France`. Rien ne les signalait parce que l'index
    `chemin -> handle` de `places_apply._seed_parent_index` écrase silencieusement la clé
    quand deux lieux mènent au même chemin — la structure qui sert à décider est celle qui
    les rend invisibles.
    """
    groupes: dict[tuple[str, str, str], list[dict]] = defaultdict(list)
    for place in places:
        nom = (place.get("name") or {}).get("value", "")
        if not nom:
            continue
        refs = place.get("placeref_list") or []
        parent = refs[0].get("ref", "") if refs else ""
        groupes[(nom, place.get("place_type", ""), parent)].append(place)
    return [{"nom": nom, "place_type": type_, "parent": parent,
             "gramps_ids": [p.get("gramps_id", "") for p in lot],
             "handles": [p["handle"] for p in lot]}
            for (nom, type_, parent), lot in sorted(groupes.items()) if len(lot) > 1]


def echec_du_bloc_pays(resultats: list[ResultatPays],
                       entites: dict[str, EntitePays]) -> dict | None:
    """Le bloc `pays` est vide alors que des subdivisions ont été trouvées. `None` si sain.

    `charger_entites_pays` rend `{}` quand son unique appel échoue, pendant que
    `charger_pays` réussit pays par pays. Le YAML sort alors d'apparence parfaitement
    normale — 430 subdivisions, aucun pays — et `apply referentiel` n'a plus un seul parent
    à résoudre. Un relecteur doit voir que le référentiel est incomplet **avant** d'autoriser
    l'écriture, pas après.
    """
    if entites or not any(res.subdivisions for res in resultats):
        return None
    return {"code_iso": "—",
            "erreur": "aucune entité pays résolue alors que des subdivisions l'ont été : "
                      "référentiel incomplet, relancer `propose referentiel` avant "
                      "d'appliquer ce YAML"}


def render_referentiel_report(date: str, resultats: list[ResultatPays],
                              entites: dict[str, EntitePays],
                              doublons: list[dict],
                              base_url: str = "http://localhost") -> str:
    """Rapport Markdown pur : synthèse par pays, collisions, doublons, pays en échec."""
    total = sum(len(r.subdivisions) for r in resultats)
    lignes = [f"# Référentiel des subdivisions — {date}", "",
              "## Synthèse", "",
              f"- Pays interrogés : {len(resultats)}",
              f"- Pays en échec : {sum(1 for r in resultats if r.erreur)}",
              f"- Subdivisions retenues : {total}",
              f"- Collisions signalées : {sum(len(r.collisions) for r in resultats)}",
              f"- Entités écartées : {sum(len(r.ecartees) for r in resultats)}",
              f"- Entités pays résolues : {len(entites)}", ""]
    if echec_du_bloc_pays(resultats, entites):
        lignes += ["> **Référentiel incomplet — ne pas appliquer ce YAML.** Aucune entité "
                   f"pays n'a été résolue alors que {total} subdivisions l'ont été. "
                   "`apply referentiel` ne pourrait rattacher aucune d'elles : il "
                   "signalerait chaque subdivision comme « parent non résolu » sans rien "
                   "écrire. Relancer `propose referentiel` — l'appel aux entités pays est "
                   "unique et a probablement échoué seul.", ""]
    lignes += ["## Par pays", "",
               "| Pays | Niveau 1 | Niveau 2 | Collisions | Écartées | Erreur |",
               "|---|---|---|---|---|---|"]
    for res in sorted(resultats, key=lambda r: r.code_iso):
        n1 = sum(1 for s in res.subdivisions if s.niveau == 1)
        n2 = sum(1 for s in res.subdivisions if s.niveau == 2)
        lignes.append(f"| {res.code_iso} | {n1} | {n2} | {len(res.collisions)} "
                      f"| {len(res.ecartees)} | {res.erreur or '—'} |")
    lignes += ["", "## Subdivisions", "",
               "| Pays | ISO | Code | Nom | Type | Niveau | GPS | Article |",
               "|---|---|---|---|---|---|---|---|"]
    for res in sorted(resultats, key=lambda r: r.code_iso):
        for sub in sorted(res.subdivisions, key=lambda s: s.iso):
            gps = f"{sub.lat},{sub.long}" if sub.lat and sub.long else "—"
            art = "oui" if sub.frwiki else "—"
            lignes.append(f"| {res.code_iso} | {sub.iso} | {sub.code} | {sub.libelle_fr} "
                          f"| {sub.place_type} | {sub.niveau} | {gps} | {art} |")

    collisions = [(r.code_iso, c) for r in resultats for c in r.collisions]
    if collisions:
        lignes += ["", "## Collisions — signalées, jamais écrites", "",
                   "Deux entités partagent un code ISO au même niveau : rien ne dit laquelle "
                   "porte la vérité, donc aucune des deux n'est écrite.", "",
                   "| Pays | ISO | QID | Libellés |", "|---|---|---|---|"]
        for code_pays, col in collisions:
            lignes.append(f"| {code_pays} | {col.iso} | {', '.join(col.qids)} "
                          f"| {', '.join(col.libelles)} |")

    ecartees = [(r.code_iso, e) for r in resultats for e in r.ecartees]
    if ecartees:
        lignes += ["", "## Entités écartées", "",
                   "Ces entités n'ont pas passé les règles de filtrage : elles ne figurent "
                   "dans aucune liste de subdivisions. Le motif est porté ici pour qu'un rejet "
                   "anormal (par exemple un rattachement introuvable en masse sur tout un pays) "
                   "ne reste jamais invisible à qui ne lit que ce rapport.", "",
                   "| Pays | ISO | QID | Libellé | Motif |", "|---|---|---|---|---|"]
        for code_pays, ecartee in sorted(ecartees, key=lambda pe: (pe[0], pe[1].iso)):
            lignes.append(f"| {code_pays} | {ecartee.iso} | {ecartee.qid} "
                          f"| {ecartee.libelle_fr} | {ecartee.motif} |")

    if doublons:
        lignes += ["", "## Doublons déjà dans l'arbre — à fusionner à la main", "",
                   "Ces lieux partagent nom, type et parent. La fusion n'est jamais "
                   "automatique : rien ne dit lequel porte la vérité. Les arbitrer avec "
                   "`merge places`.", "",
                   "| Nom | Type | Lieux |", "|---|---|---|"]
        for doublon in doublons:
            liens = ", ".join(f"[{gid}]({base_url}/place/{gid})"
                              for gid in doublon["gramps_ids"])
            lignes.append(f"| {doublon['nom']} | {doublon['place_type']} | {liens} |")
    lignes.append("")
    return "\n".join(lignes)


def render_referentiel_yaml(resultats: list[ResultatPays],
                            entites: dict[str, EntitePays],
                            doublons: list[dict]) -> str:
    """Le YAML relu par l'humain, et seule entrée de `apply referentiel`."""
    doc = {
        "pays": [e.model_dump() for e in entites.values()],
        "subdivisions": [s.model_dump() for r in resultats for s in r.subdivisions],
        "collisions": [c.model_dump() for r in resultats for c in r.collisions],
        "ecartees": [e.model_dump() for r in resultats for e in r.ecartees],
        "doublons_arbre": doublons,
        "echecs": [{"code_iso": r.code_iso, "erreur": r.erreur}
                   for r in resultats if r.erreur]
                  + [e for e in [echec_du_bloc_pays(resultats, entites)] if e],
    }
    return yaml.safe_dump(doc, allow_unicode=True, sort_keys=False)


def run_referentiel(client, output_dir, *, date: str,
                    codes_pays: list[str] | None = None) -> tuple[Path, Path]:
    """Interroge les pays demandés (tous par défaut) ; écrit rapport et YAML. Lecture seule."""
    codes = codes_pays or sorted(PAYS_REFERENTIEL)
    resultats = [charger_pays(PAYS_REFERENTIEL[code]) for code in codes]
    entites = charger_entites_pays([PAYS_REFERENTIEL[code].qid for code in codes])
    places = [place for lot in iter_places(client, "all", 200, None) for place in lot]
    doublons = doublons_de_larbre(places)

    out = Path(output_dir) / "referentiel"
    out.mkdir(parents=True, exist_ok=True)
    suffixe = "tous" if codes_pays is None else "-".join(codes)
    report_path = out / f"{date}_referentiel_{suffixe}.md"
    report_path.write_text(render_referentiel_report(date, resultats, entites, doublons),
                           encoding="utf-8")
    yaml_path = out / f"{date}_propositions_referentiel_{suffixe}.yaml"
    yaml_path.write_text(render_referentiel_yaml(resultats, entites, doublons),
                         encoding="utf-8")
    return report_path, yaml_path
