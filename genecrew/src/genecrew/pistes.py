"""Contrat de consignation des pistes de recherche (Phase 4, document-de-travail §6.3).

Une piste n'est jamais un fait : aucune citation n'est créée ici. Ce module définit
ce qui fait une piste forte, comment on l'identifie de façon stable dans le temps,
et comment on la consigne sans jamais écrire deux fois la même.
"""

from __future__ import annotations

import hashlib
import json
import unicodedata

from crewai_custom_tools.tools.genealogy.gramps.write_tools import (
    GrampsAttachTool,
    GrampsCreateNoteTool,
    GrampsEnsureTagTool,
    effective_dry_run,
)
from crewai_custom_tools.tools.genealogy.models.domain import Piste  # noqa: F401

_LONGUEUR_CLE = 8


def _normaliser(valeur: str) -> str:
    """Casse, accents et espaces retirés — la même fiche doit donner la même clé."""
    sans_accent = "".join(
        c
        for c in unicodedata.normalize("NFD", valeur)
        if unicodedata.category(c) != "Mn"
    )
    return " ".join(sans_accent.split()).upper()


def cle_derivee(source: str, champs: list[str]) -> str:
    """Identité de repli quand la source ne fournit aucun identifiant stable.

    Ce n'est PAS une URL : elle ne s'affiche jamais comme preuve, elle sert
    uniquement à reconnaître une piste déjà consignée. Le pire qu'une collision
    puisse produire est un doublon manqué — pas un lien mort donné pour une source.

    `hashlib` et non `hash()` : ce dernier est salé à chaque exécution, ce qui
    casserait l'idempotence entre deux lancements du pipeline.
    """
    graine = "|".join([source] + [_normaliser(c) for c in champs])
    return hashlib.sha256(graine.encode("utf-8")).hexdigest()[:_LONGUEUR_CLE]


def marqueur(source: str, identite: str, derivee: bool = False) -> str:
    """Marqueur d'idempotence, porté par le corps de la note.

    Il porte l'IDENTITÉ, jamais la date : le pipeline repasse sur les mêmes
    personnes pendant des mois, et un marqueur daté recréerait la même piste à
    chaque exécution.
    """
    return f"[genecrew:piste:{source}:{'k=' if derivee else ''}{identite}]"


TAG_PISTE = "ia-piste"


def marqueurs_existants(client, gramps_id: str) -> set[str]:
    """Les marqueurs de piste déjà posés sur cette personne.

    Filtre par `gramps_id` côté serveur et demande `extend=note_list` : les notes
    complètes arrivent en UN appel, pour UNE personne. Vérifié en direct contre
    l'API — `extended.notes[i]["text"]["string"]` porte le corps de la note.
    """
    gens = (
        client.get_json(
            "/people/", params={"gramps_id": gramps_id, "extend": "note_list"}
        )
        or []
    )
    if not gens:
        return set()
    notes = (gens[0].get("extended") or {}).get("notes") or []
    marqueurs = set()
    for note in notes:
        corps = (note.get("text") or {}).get("string", "")
        if corps.startswith("[genecrew:piste:") and "]" in corps:
            marqueurs.add(corps[: corps.index("]") + 1])
    return marqueurs


def corps_note(piste: Piste) -> str:
    """Rend le corps de la note. Rapporte, ne conclut jamais."""
    lignes = [
        marqueur(piste.source, piste.identite, piste.identite_derivee),
        f"Piste — {piste.source}",
        "",
        f"Correspondance : {piste.force.upper()}",
        f"  concordent : {', '.join(piste.concordances) or '—'}",
        f"  divergent  : {', '.join(piste.divergences) or '—'}",
        "",
    ]
    if piste.url:
        lignes.append(f"URL : {piste.url}")
    else:
        lignes += [
            "Permalien ABSENT de la source.",
            "Pour retrouver la fiche : recherche manuelle par nom + date.",
        ]
    lignes += [
        f"Requête rejouable : {piste.requete}",
        "",
        "Une piste n'est pas un fait : à vérifier avant toute citation.",
    ]
    return "\n".join(lignes)


def consigner(client, piste: Piste, *, dry_run: bool = False) -> dict:
    """Écrit une piste FORTE dans l'arbre, une seule fois. Rend le verdict et sa raison.

    Une faible n'entre jamais dans l'arbre : elle vit dans le rapport seul.
    """
    if piste.force != "forte":
        return {"ecrite": False, "raison": "faible"}
    if marqueur(
        piste.source, piste.identite, piste.identite_derivee
    ) in marqueurs_existants(client, piste.gramps_id):
        return {"ecrite": False, "raison": "déjà consignée"}
    if effective_dry_run(dry_run):
        return {"ecrite": False, "raison": "simulation"}

    note = json.loads(
        GrampsCreateNoteTool()._run(text=corps_note(piste), note_type="Research")
    )
    if not note["success"]:
        return {"ecrite": False, "raison": f"note refusée : {note['error']}"}
    tag = json.loads(GrampsEnsureTagTool()._run(name=TAG_PISTE))
    if not tag["success"]:
        return {"ecrite": False, "raison": f"tag refusé : {tag['error']}"}
    attache = json.loads(
        GrampsAttachTool()._run(
            handle=piste.handle,
            note_handle=note["data"]["handle"],
            tag_handle=tag["data"]["handle"],
        )
    )
    if not attache["success"]:
        return {"ecrite": False, "raison": f"rattachement refusé : {attache['error']}"}
    return {"ecrite": True, "raison": "consignée"}


def render_rapport_pistes(
    pistes: list[Piste],
    date: str,
    *,
    dry_run: bool = False,
    ecriture: bool = True,
    echecs: int = 0,
) -> str:
    """Rapport Markdown. Les faibles n'existent QUE là — les perdre les perdrait.

    `ecriture` distingue deux appelants possibles de ce rendu partagé :

    - `ecriture=True` (défaut) : l'appelant EST une commande qui écrit (ou pourrait
      écrire) dans l'arbre — `dry_run`/`effective_dry_run` s'appliquent alors comme
      dans `consigner`, et le mode affiché doit être le mode EFFECTIF, jamais celui
      demandé, faute de quoi un appelant passant `dry_run=False` alors que
      `GENECREW_DRY_RUN` impose la simulation annoncerait « écritures appliquées »
      à un rapport dont aucune piste n'a été écrite.
    - `ecriture=False` : l'appelant est une commande `propose` qui N'A AUCUN mode
      d'écriture — `dry_run` est alors ignoré, et le rapport ne doit jamais employer
      un vocabulaire de simulation (« dry-run ») qui laisserait croire qu'une
      écriture réelle existe quelque part pour cette commande.

    `echecs` compte les personnes pour lesquelles la source a échoué (erreur réseau,
    504, …) plutôt que de n'avoir rien renvoyé. Sans lui, une panne de source sur
    tout le lot produit exactement le même rapport (« Aucune piste ») qu'un arbre
    sans aucun résultat — les deux sont indiscernables si le rapport ne les distingue
    pas explicitement.
    """
    if ecriture:
        dry_run = effective_dry_run(dry_run)
        mode = (
            "simulation (dry-run, aucune écriture)"
            if dry_run
            else "écritures appliquées"
        )
        libelle_fortes = "Pistes fortes (écrites dans l'arbre)"
    else:
        mode = "lecture seule (cette commande n'écrit rien)"
        libelle_fortes = (
            "Pistes fortes (au moins deux facteurs concordants, aucune divergence)"
        )
    fortes = [p for p in pistes if p.force == "forte"]
    faibles = [p for p in pistes if p.force == "faible"]
    lignes = [
        f"# Pistes de recherche — {date}",
        "",
        f"Mode : {mode}.",
        "",
        f"- {libelle_fortes} : {len(fortes)}",
        f"- Pistes faibles (ce rapport seulement) : {len(faibles)}",
        f"- Échecs de la source (personne non interrogée, ex. erreur réseau) : {echecs}",
        "",
    ]
    if not pistes:
        lignes += ["Aucune piste.", ""]
        return "\n".join(lignes)
    for titre, lot in (("Pistes fortes", fortes), ("Pistes faibles", faibles)):
        lignes += [f"## {titre}", ""]
        if not lot:
            lignes += ["Aucune.", ""]
            continue
        lignes += [
            "| Personne | Source | Identité | Concordances | Divergences | URL |",
            "|---|---|---|---|---|---|",
        ]
        for p in lot:
            url = p.url or "— (permalien absent de la source)"
            lignes.append(
                f"| {p.gramps_id} | {p.source} | {p.identite} | "
                f"{', '.join(p.concordances) or '—'} | "
                f"{', '.join(p.divergences) or '—'} | {url} |"
            )
        lignes.append("")
    lignes += ["> Une piste n'est pas un fait : aucune citation n'a été créée.", ""]
    return "\n".join(lignes)
