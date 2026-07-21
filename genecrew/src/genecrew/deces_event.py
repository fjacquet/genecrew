"""`apply deaths` — création d'événements décès sourcés depuis un YAML relu.

La v2 de l'ADR 0011 : là où `apply citations` pose une citation sur un décès qui
existe déjà (`type: source`), cette commande écrit le décès ABSENT de l'arbre
(`type: date`). Elle crée donc une donnée cœur, ce que l'ADR 0011 s'interdisait —
voir l'ADR 0014 pour ce que ça relâche et ce qui l'encadre.

L'écriture elle-même est déléguée à `evenements.creer_evenement_source` ; ce module
tient le filtre, la résolution de lieu, l'orchestration et le rapport.
"""

from __future__ import annotations

import json
import re
import unicodedata
from pathlib import Path

import yaml
from crewai_custom_tools.tools.genealogy.gramps.client import GrampsClient
from crewai_custom_tools.tools.genealogy.gramps.write_tools import (
    GrampsAttachTool,
    GrampsCreateCitationTool,
    GrampsCreateNoteTool,
    GrampsEnsureSourceTool,
    GrampsEnsureTagTool,
    effective_dry_run,
)

from genecrew.deces_apply import citation_page, source_title_for
from genecrew.evenements import creer_evenement_source, dateval_iso
from genecrew.propositions import PropositionsLot

TAG_DECES = "genecrew:deces"


_LIGATURES = str.maketrans({
    "œ": "oe", "Œ": "OE",
    "æ": "ae", "Æ": "AE",
})


def normaliser_lieu(nom: str) -> str:
    """Nom de commune → clé de comparaison : sans accents, minuscule, séparateurs unifiés.

    « Nohant-en-Goût », « nohant en gout » et « NOHANT-EN-GOUT » désignent la même
    commune ; l'INSEE et l'arbre ne les écrivent pas pareil. Les ligatures (« Vœuil » /
    « Voeuil ») et l'apostrophe typographique « ’ » (U+2019, courante en copier-coller,
    contre l'apostrophe ASCII « ' ») sont deux autres variantes de la même commune :
    NFD décompose les accents mais ne déplie pas les ligatures, d'où le passage explicite
    avant décomposition ; l'apostrophe courbe entre dans la classe des séparateurs.
    """
    depliee = (nom or "").translate(_LIGATURES)
    sans_accents = "".join(
        c for c in unicodedata.normalize("NFD", depliee)
        if unicodedata.category(c) != "Mn")
    return re.sub(r"[\s\-'’]+", " ", sans_accents).strip().lower()


def index_lieux(client: GrampsClient) -> dict[str, str | None]:
    """Index `{nom normalisé -> handle}` des lieux de l'arbre ; `None` si homonymes.

    Le `None` est porteur d'information : il distingue l'AMBIGU (clé présente, valeur
    None) de l'INCONNU (clé absente). Les deux mènent au même geste — un événement sans
    lieu — mais pas au même diagnostic dans le rapport.
    """
    index: dict[str, str | None] = {}
    page = 1
    while True:
        batch = client.get_json("/places/", params={"page": page, "pagesize": 200})
        if not batch:
            break
        for place in batch:
            if not isinstance(place, dict):
                continue
            cle = normaliser_lieu((place.get("name") or {}).get("value", ""))
            if not cle:
                continue
            # Deuxième occurrence (ou plus) du même nom : on écrase par None. Choisir
            # au hasard rattacherait un décès à la mauvaise commune, en silence.
            index[cle] = None if cle in index else place.get("handle")
        page += 1
    return index


def resoudre_lieu(index: dict[str, str | None], nom: str) -> str | None:
    """Handle du lieu nommé, ou None s'il est inconnu ou ambigu. Pur."""
    return index.get(normaliser_lieu(nom))


def trier_propositions(propositions: list) -> tuple[list, dict[str, int]]:
    """Sépare les propositions applicables du reste. Pur.

    Trois des quatre conditions de l'ADR 0014 se jugent sur la proposition seule :
    `type: date`, `confiance == 2`, et une date ISO complète. La quatrième — « la
    personne n'a toujours pas de décès » — exige de lire l'arbre au moment de
    l'écriture, et vit dans `run_deces_event`.

    Les deux motifs de rejet sont comptés SÉPARÉMENT : « hors périmètre » est un
    non-sujet (c'est le travail d'`apply citations`), « sans donnée » est un signal
    — un YAML trop ancien, à régénérer. Les confondre ferait lire un lot périmé
    comme un lot vide.
    """
    retenues, motifs = [], {"hors_perimetre": 0, "sans_donnee": 0}
    for prop in propositions:
        if prop.type != "date" or prop.confiance != 2:
            motifs["hors_perimetre"] += 1
            continue
        if dateval_iso(prop.date_iso) is None:
            motifs["sans_donnee"] += 1
            continue
        retenues.append(prop)
    return retenues, motifs


def render_deaths_report(date: str, crees: list, refuses: list, lieux_non_resolus: list,
                         motifs: dict, errors: list, dry_run: bool) -> str:
    """Rapport Markdown d'un passage de `apply deaths`. Pur.

    `Mode:` reflète tel quel le booléen `dry_run` reçu ; c'est à l'appelant de lui
    passer le dry-run déjà résolu (variable d'environnement comprise) — cette
    fonction ne lit aucune variable d'environnement elle-même.
    """
    mode = "simulation (dry-run, aucune écriture)" if dry_run else "écritures appliquées"
    lines = [f"# Création d'événements décès sourcés — {date}", "",
             f"Mode : {mode}.", "",
             f"- Décès créés : {len(crees)}",
             f"- Refusés (décès déjà présent dans l'arbre) : {len(refuses)}",
             f"- Sans donnée machine exploitable (YAML antérieur) : {motifs['sans_donnee']}",
             f"- Hors périmètre (type ≠ date ou confiance < 2) : {motifs['hors_perimetre']}",
             f"- Erreurs : {len(errors)}", ""]
    if crees:
        lines += ["| Personne | Événement | Lieu |", "|---|---|---|"]
        lines += [f"| {gid} {nom} | {ev} | {lieu or '—'} |"
                  for gid, nom, ev, lieu in crees]
        lines.append("")
    if lieux_non_resolus:
        lines += ["## Lieux non résolus", "",
                  "Événement créé sans lieu : la commune est inconnue de l'arbre, ou "
                  "plusieurs lieux portent ce nom. À traiter avec `apply places`.", ""]
        lines += [f"- {gid} : {nom}" for gid, nom in lieux_non_resolus]
        lines.append("")
    if refuses:
        lines += ["## Refusés", ""]
        lines += [f"- {gid} : {motif}" for gid, motif in refuses]
        lines.append("")
    if errors:
        lines += ["## Erreurs", ""]
        lines += [f"- {gid} : {msg}" for gid, msg in errors]
        lines.append("")
    return "\n".join(lines)


def _a_un_deces(person: dict) -> bool:
    """La personne porte-t-elle déjà un décès ? (garde d'invariant d'`apply deaths`)

    `GrampsCreateEventTool` refuse d'ÉCRASER un `death_ref_index` existant, mais il
    créerait quand même un second événement Death et l'ajouterait à la liste —
    invisible dans les vues qui suivent l'index, bien présent dans la base. La garde
    doit donc être ici, en plus.
    """
    return person.get("death_ref_index", -1) >= 0


def run_deces_event(client: GrampsClient, propositions_yaml, output_dir, *,
                    date: str, dry_run: bool = False) -> Path:
    """Applique les propositions `type: date` d'un YAML relu : crée les décès absents."""
    dry_run = effective_dry_run(dry_run)
    data = yaml.safe_load(Path(propositions_yaml).read_text(encoding="utf-8")) or {}
    lot = PropositionsLot(**data)                   # validation stricte du YAML relu
    retenues, motifs = trier_propositions(lot.propositions)

    index = index_lieux(client) if retenues else {}
    source_handles: dict[str, str] = {}             # titre -> handle (une source/registre)

    def _ensure_source(title: str, author: str) -> str:
        if title not in source_handles:
            payload = json.loads(GrampsEnsureSourceTool()._run(
                title=title, author=author, dry_run=dry_run))
            if not payload["success"]:
                raise RuntimeError(f"source '{title}' : {payload['error']}")
            source_handles[title] = payload["data"]["handle"]
        return source_handles[title]

    crees, refuses, lieux_non_resolus, errors = [], [], [], []
    for prop in retenues:
        try:
            person = client.get_object("people", prop.handle)
        except Exception:
            errors.append((prop.gramps_id, "personne introuvable"))
            continue
        if _a_un_deces(person):
            refuses.append((prop.gramps_id,
                            "un décès existe déjà dans l'arbre (lot périmé ?)"))
            continue

        title, author = source_title_for(prop.preuve_detail)
        source_handle = _ensure_source(title, author)
        citation = json.loads(GrampsCreateCitationTool()._run(
            source_handle=source_handle,
            page=citation_page(prop.preuve_detail, prop.preuve_url),
            dry_run=dry_run))
        if not citation["success"]:
            errors.append((prop.gramps_id, f"citation : {citation['error']}"))
            continue

        lieu_handle = resoudre_lieu(index, prop.lieu_nom) if prop.lieu_nom else None
        if prop.lieu_nom and lieu_handle is None:
            lieux_non_resolus.append((prop.gramps_id, prop.lieu_nom))

        evt = creer_evenement_source(
            prop.handle, event_type="Death", dateval=dateval_iso(prop.date_iso),
            place_handle=lieu_handle, citation_handle=citation["data"]["handle"],
            dry_run=dry_run)
        if not evt["posee"]:
            errors.append((prop.gramps_id, evt["raison"]))
            continue
        if not evt["attache"]:
            # L'événement EXISTE : on le dit en erreur (avec le handle de l'orphelin)
            # et NON en créé, pour ne pas annoncer un décès que l'arbre ne montre pas.
            errors.append((prop.gramps_id, evt["raison"]))
            continue

        # L'écriture irréversible est faite. Note et tag sont des annotations : leur
        # échec ne remet pas l'événement en cause, il se rapporte.
        note = json.loads(GrampsCreateNoteTool()._run(
            text=f"[genecrew:deces:{date}] {prop.action} — {prop.preuve_url}",
            note_type="Research", dry_run=dry_run))
        tag = json.loads(GrampsEnsureTagTool()._run(name=TAG_DECES, dry_run=dry_run))
        if note["success"] and tag["success"]:
            attache = json.loads(GrampsAttachTool()._run(
                handle=prop.handle, note_handle=note["data"]["handle"],
                tag_handle=tag["data"]["handle"], dry_run=dry_run))
            if not attache["success"]:
                errors.append((prop.gramps_id,
                               f"décès {evt['event_handle']} créé, "
                               f"annotation refusée : {attache['error']}"))
        else:
            refus = note.get("error") or tag.get("error")
            errors.append((prop.gramps_id,
                           f"décès {evt['event_handle']} créé, "
                           f"note/tag refusé : {refus}"))

        crees.append((prop.gramps_id, prop.personne, evt["event_handle"],
                      prop.lieu_nom if lieu_handle else ""))

    report = render_deaths_report(date, crees, refuses, lieux_non_resolus, motifs,
                                  errors, dry_run)
    out = Path(output_dir) / "deces"
    out.mkdir(parents=True, exist_ok=True)
    report_path = out / f"{date}_apply_deaths_{Path(propositions_yaml).stem}.md"
    report_path.write_text(report, encoding="utf-8")
    return report_path
