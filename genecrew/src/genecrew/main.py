#!/usr/bin/env python
import os
import sys
import warnings
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv

from genecrew.logging_setup import configure_logging, get_logger

warnings.filterwarnings("ignore", category=SyntaxWarning, module="pysbd")

# This main file is intended to be a way for you to run your
# crew locally, so refrain from adding unnecessary logic into this file.
# Replace with inputs you want to test with, it will automatically
# interpolate any tasks and agents information


def _placeholder_inputs() -> dict:
    """Minimal inputs so train/test interpolate without real findings."""
    return {
        "anomalies_block": "(aucune anomalie fournie)",
        "date": datetime.now().date().isoformat(),
    }


def run():
    """
    Run the audit crew over a bounded sample (dry-run) via the orchestrator.

    `crewai run` / `run_crew` is a dev convenience: it runs the real audit workflow
    on a small slice so writes are always simulated. Use `genecrew crew audit` for the
    full command with flags.
    """
    from pathlib import Path

    from crewai_custom_tools.tools.genealogy.gramps.client import get_client

    from genecrew.crew_audit import run_crew_audit

    load_dotenv()
    limit = int(os.environ.get("GENECREW_CREW_LIMIT", "25"))
    output_dir = Path(os.environ.get("GENECREW_OUTPUT_DIR", "output"))
    try:
        report = run_crew_audit(
            get_client(),
            "all",
            output_dir,
            date=datetime.now().date().isoformat(),
            limit=limit,
            dry_run=True,
        )
        print(f"Rapport : {report}")
    except Exception as e:
        raise Exception(f"An error occurred while running the crew: {e}") from e


def train():
    """
    Train the crew for a given number of iterations.
    """
    from genecrew.crew import Genecrew

    try:
        Genecrew().crew().train(
            n_iterations=int(sys.argv[1]),
            filename=sys.argv[2],
            inputs=_placeholder_inputs(),
        )

    except Exception as e:
        raise Exception(f"An error occurred while training the crew: {e}") from e


def replay():
    """
    Replay the crew execution from a specific task.
    """
    from genecrew.crew import Genecrew

    try:
        Genecrew().crew().replay(task_id=sys.argv[1])

    except Exception as e:
        raise Exception(f"An error occurred while replaying the crew: {e}") from e


def test():
    """
    Test the crew execution and returns the results.
    """
    from genecrew.crew import Genecrew

    try:
        Genecrew().crew().test(
            n_iterations=int(sys.argv[1]),
            eval_llm=sys.argv[2],
            inputs=_placeholder_inputs(),
        )

    except Exception as e:
        raise Exception(f"An error occurred while testing the crew: {e}") from e


def stats() -> None:
    """Print tree statistics from Gramps Web (deterministic, no LLM)."""
    from crewai_custom_tools.tools.genealogy.gramps.client import (
        GrampsClient,
        GrampsConfig,
    )

    from genecrew.stats import collect_stats, format_stats

    client = GrampsClient(GrampsConfig.from_env())
    tree_name, counts = collect_stats(client)
    print(format_stats(tree_name, counts))


def audit_cmd(args) -> None:
    """Run the deterministic audit and print the report path."""
    from pathlib import Path

    from crewai_custom_tools.tools.genealogy.gramps.client import (
        GrampsClient,
        GrampsConfig,
    )

    from genecrew.audit import run_audit

    client = GrampsClient(GrampsConfig.from_env())
    output_dir = Path(os.environ.get("GENECREW_OUTPUT_DIR", "output"))
    date = args.date or __import__("datetime").date.today().isoformat()
    path = run_audit(
        client,
        args.scope,
        output_dir,
        date=date,
        batch_size=args.batch_size,
        limit=args.limit,
    )
    print(f"Rapport écrit : {path}")


def names_cmd(args) -> None:
    """Standardize name casing over a scope; print the report paths."""
    from pathlib import Path

    from crewai_custom_tools.tools.genealogy.gramps.client import (
        GrampsClient,
        GrampsConfig,
    )

    from genecrew.names import run_names

    client = GrampsClient(GrampsConfig.from_env())
    output_dir = Path(os.environ.get("GENECREW_OUTPUT_DIR", "output"))
    date = args.date or __import__("datetime").date.today().isoformat()
    report, incomplete = run_names(
        client,
        args.scope,
        output_dir,
        date=date,
        batch_size=args.batch_size,
        limit=args.limit,
        dry_run=args.dry_run,
    )
    print(f"Rapport : {report}")
    print(f"Noms à vérifier : {incomplete}")


def gender_cmd(args) -> None:
    """Infer gender from first name (read-only); print the report + proposals paths."""
    from pathlib import Path

    from crewai_custom_tools.tools.genealogy.gramps.client import (
        GrampsClient,
        GrampsConfig,
    )

    from genecrew.gender import run_gender

    client = GrampsClient(GrampsConfig.from_env())
    output_dir = Path(os.environ.get("GENECREW_OUTPUT_DIR", "output"))
    date = args.date or __import__("datetime").date.today().isoformat()
    report, proposals = run_gender(
        client, args.scope, output_dir, date=date, limit=args.limit
    )
    print(f"Rapport : {report}")
    print(f"Propositions : {proposals}")


def gender_apply_cmd(args) -> None:
    """Apply high-confidence gender corrections (write); print the report path."""
    from pathlib import Path

    from crewai_custom_tools.tools.genealogy.gramps.client import (
        GrampsClient,
        GrampsConfig,
    )

    from genecrew.gender_apply import run_gender_apply

    client = GrampsClient(GrampsConfig.from_env())
    output_dir = Path(os.environ.get("GENECREW_OUTPUT_DIR", "output"))
    date = args.date or __import__("datetime").date.today().isoformat()
    report = run_gender_apply(
        client,
        args.scope,
        output_dir,
        date=date,
        min_ratio=args.min_ratio,
        limit=args.limit,
        dry_run=args.dry_run,
    )
    print(f"Rapport : {report}")


def archives_cmd(args, source: str) -> None:
    """Pistes depuis une source d'archives en ligne. Lecture seule : n'écrit rien."""
    from pathlib import Path

    from crewai_custom_tools.tools.genealogy.gramps.client import get_client

    from genecrew.archives import run_archives

    client = get_client()
    output_dir = Path(os.environ.get("GENECREW_OUTPUT_DIR", "output"))
    date = args.date or __import__("datetime").date.today().isoformat()
    chemin = run_archives(
        client,
        source,
        args.scope,
        output_dir,
        date=date,
        batch_size=args.batch_size,
        limit=args.limit,
    )
    print(f"Rapport : {chemin}")


def referentiel_cmd(args) -> None:
    """Interroge Wikidata pour le référentiel des subdivisions (lecture seule).

    `--country` absent (`None`) se traduit ici en « tous les pays de la table » : c'est
    `run_referentiel` qui porte cette règle par défaut (`codes_pays=None`), la CLI se
    contente de ne pas inventer de valeur quand l'utilisateur n'en a donné aucune.
    """
    from pathlib import Path

    from crewai_custom_tools.tools.genealogy.gramps.client import get_client

    from genecrew.referentiel import run_referentiel

    client = get_client()
    output_dir = Path(os.environ.get("GENECREW_OUTPUT_DIR", "output"))
    date = args.date or __import__("datetime").date.today().isoformat()
    codes_pays = ([code.strip() for code in args.country.split(",") if code.strip()]
                  if args.country else None)
    report, proposals = run_referentiel(client, output_dir, date=date, codes_pays=codes_pays)
    print(f"Rapport : {report}")
    print(f"Propositions : {proposals}")


def referentiel_apply_cmd(args) -> None:
    """Écrit le référentiel des subdivisions depuis un YAML relu ; imprime le rapport."""
    from pathlib import Path

    from crewai_custom_tools.tools.genealogy.gramps.client import get_client

    from genecrew.referentiel_apply import run_referentiel_apply

    client = get_client()
    output_dir = Path(os.environ.get("GENECREW_OUTPUT_DIR", "output"))
    date = args.date or __import__("datetime").date.today().isoformat()
    report = run_referentiel_apply(client, Path(args.yaml), output_dir,
                                   date=date, dry_run=args.dry_run)
    print(f"Rapport : {report}")


def apply_all_cmd(args) -> None:
    """Apply casing, gender and places, then propose deaths; print all report paths.

    The first three volets **write**; the deaths volet only produces propositions for
    human review (`apply citations` writes them once relu). See `apply_all.run_apply_all`.
    """
    from pathlib import Path

    from crewai_custom_tools.tools.genealogy.gramps.client import get_client

    from genecrew.apply_all import run_apply_all

    client = get_client()
    output_dir = Path(os.environ.get("GENECREW_OUTPUT_DIR", "output"))
    date = args.date or __import__("datetime").date.today().isoformat()
    paths = run_apply_all(
        client,
        args.scope,
        output_dir,
        date=date,
        min_ratio=args.min_ratio,
        min_score=args.min_score,
        batch_size=args.batch_size,
        limit=args.limit,
        dry_run=args.dry_run,
    )
    print(f"Casse : {paths['names']}")
    print(f"Noms à vérifier : {paths['incomplete']}")
    print(f"Genres : {paths['gender']}")
    print(f"Lieux : {paths['lieux']}")
    print(f"Décès : {paths['deces']}")
    print(f"Propositions décès : {paths['deces_propositions']}")


def lieux_cmd(args) -> None:
    """Standardize places over a scope (read-only); print the report paths."""
    from pathlib import Path

    from crewai_custom_tools.tools.genealogy.gramps.client import get_client

    from genecrew.places import run_places

    client = get_client()
    output_dir = Path(os.environ.get("GENECREW_OUTPUT_DIR", "output"))
    date = args.date or __import__("datetime").date.today().isoformat()
    report, proposals = run_places(
        client,
        args.scope,
        output_dir,
        date=date,
        batch_size=args.batch_size,
        limit=args.limit,
        min_score=args.min_score,
    )
    print(f"Rapport : {report}")
    print(f"Propositions : {proposals}")


def lieux_apply_cmd(args) -> None:
    """Apply place standardization (write hierarchy + GPS); print the report path."""
    from pathlib import Path

    from crewai_custom_tools.tools.genealogy.gramps.client import get_client

    from genecrew.places_apply import run_places_apply

    client = get_client()
    output_dir = Path(os.environ.get("GENECREW_OUTPUT_DIR", "output"))
    date = args.date or __import__("datetime").date.today().isoformat()
    report = run_places_apply(
        client,
        args.scope,
        output_dir,
        date=date,
        min_score=args.min_score,
        batch_size=args.batch_size,
        limit=args.limit,
        dry_run=args.dry_run,
    )
    print(f"Rapport : {report}")


def lieux_merge_cmd(args) -> None:
    """Détecte et fusionne les doublons de lieux prouvés, ou exécute un YAML relu."""
    from pathlib import Path

    from crewai_custom_tools.tools.genealogy.gramps.client import get_client

    from genecrew.places_merge import run_places_detect, run_places_merge

    client = get_client()
    output_dir = Path(os.environ.get("GENECREW_OUTPUT_DIR", "output"))
    date = args.date or __import__("datetime").date.today().isoformat()
    if args.yaml:
        report = run_places_merge(
            client, args.yaml, output_dir, date=date, dry_run=args.dry_run
        )
    else:
        resultat = run_places_detect(
            client,
            output_dir,
            scope=args.scope,
            date=date,
            limit=args.limit,
            dry_run=args.dry_run,
        )
        report = resultat.chemin
        # Les deux gardes « une lecture tronquée ne fusionne jamais » vivent dans
        # run_places_detect ET N'Y SONT DÉCIDÉES QUE LÀ ; leur explication n'est sinon
        # disponible que dans le rapport Markdown. Sans ces mots ici, quelqu'un qui voit
        # « zéro fusion » irait chercher une panne au lieu de relancer autrement. Les
        # deux drapeaux sont le retour EXACT de la fonction — jamais un recalcul depuis
        # `args.limit` ou `args.scope` : une seule source de vérité, pour que la console
        # ne puisse plus dire « simulation forcée » pendant qu'une fusion irréversible a
        # réellement lieu.
        if resultat.lot_borne:
            print(
                "Lot borné (--limit) : simulation forcée, aucune fusion. Un groupe "
                "d'homonymes tronqué ne permet pas de décider d'une fusion "
                "irréversible — relancez sans --limit pour appliquer les fusions."
            )
        if resultat.scope_unitaire:
            print(
                "Périmètre à un seul lieu (--scope place:<ID>) : simulation forcée, "
                "aucune fusion. Un lieu isolé ne forme aucun groupe d'homonymes, donc "
                "aucun doublon ne peut être détecté — ce n'est pas la preuve qu'il "
                "n'y en a pas. Relancez avec --scope all pour chercher les doublons."
            )
    print(f"Rapport : {report}")


def people_merge_cmd(args) -> None:
    """Détecte et fusionne les doublons prouvés, ou exécute un YAML d'arbitrage relu."""
    from pathlib import Path

    from crewai_custom_tools.tools.genealogy.gramps.client import get_client

    from genecrew.people_merge import run_people_merge, run_people_merge_yaml

    client = get_client()
    output_dir = Path(os.environ.get("GENECREW_OUTPUT_DIR", "output"))
    date = args.date or __import__("datetime").date.today().isoformat()
    if args.yaml:
        report = run_people_merge_yaml(
            client, args.yaml, output_dir, date=date, dry_run=args.dry_run
        )
    else:
        report = run_people_merge(
            client,
            output_dir,
            scope=args.scope,
            date=date,
            limit=args.limit,
            max_passes=args.max_passes,
            dry_run=args.dry_run,
        )
    print(f"Rapport : {report}")


def deces_cmd(args) -> None:
    """Deterministic INSEE/MatchID death enrichment (read-only); print report paths."""
    from pathlib import Path

    from crewai_custom_tools.tools.genealogy.gramps.client import get_client

    from genecrew.deces import run_deces

    client = get_client()
    output_dir = Path(os.environ.get("GENECREW_OUTPUT_DIR", "output"))
    date = args.date or __import__("datetime").date.today().isoformat()
    report, proposals = run_deces(
        client,
        args.scope,
        output_dir,
        date=date,
        min_score=args.min_score,
        batch_size=args.batch_size,
        limit=args.limit,
    )
    print(f"Rapport : {report}")
    print(f"Propositions : {proposals}")


def militaires_cmd(args) -> None:
    """Military-death enrichment against the local MdH gazetteer; print report paths."""
    from pathlib import Path

    from crewai_custom_tools.tools.genealogy.gramps.client import get_client

    from genecrew.militaires import run_militaires

    client = get_client()
    output_dir = Path(os.environ.get("GENECREW_OUTPUT_DIR", "output"))
    date = args.date or __import__("datetime").date.today().isoformat()
    report, proposals = run_militaires(
        client,
        args.scope,
        output_dir,
        date=date,
        min_score=args.min_score,
        batch_size=args.batch_size,
        limit=args.limit,
    )
    print(f"Rapport : {report}")
    print(f"Propositions : {proposals}")


def lieux_wiki_cmd(args) -> None:
    """Verified Wikipedia links + images on GPS-bearing places; print the report path."""
    from pathlib import Path

    from crewai_custom_tools.tools.genealogy.gramps.client import get_client

    from genecrew.lieux_wiki import run_lieux_wiki

    client = get_client()
    output_dir = Path(os.environ.get("GENECREW_OUTPUT_DIR", "output"))
    date = args.date or __import__("datetime").date.today().isoformat()
    report = run_lieux_wiki(
        client,
        output_dir,
        date=date,
        limit=args.limit,
        images=not args.no_images,
        dry_run=args.dry_run,
    )
    print(f"Rapport : {report}")


def deces_apply_cmd(args) -> None:
    """Apply reviewed death propositions (INSEE citations); print the report path."""
    from pathlib import Path

    from crewai_custom_tools.tools.genealogy.gramps.client import get_client

    from genecrew.deces_apply import run_deces_apply

    client = get_client()
    output_dir = Path(os.environ.get("GENECREW_OUTPUT_DIR", "output"))
    date = args.date or __import__("datetime").date.today().isoformat()
    report = run_deces_apply(
        client, Path(args.yaml), output_dir, date=date, dry_run=args.dry_run
    )
    print(f"Rapport : {report}")


def deces_event_cmd(args) -> None:
    """Create the missing death events from a reviewed YAML; print the report path."""
    from pathlib import Path

    from crewai_custom_tools.tools.genealogy.gramps.client import get_client

    from genecrew.deces_event import run_deces_event

    client = get_client()
    output_dir = Path(os.environ.get("GENECREW_OUTPUT_DIR", "output"))
    date = args.date or __import__("datetime").date.today().isoformat()
    report = run_deces_event(
        client, Path(args.yaml), output_dir, date=date, dry_run=args.dry_run
    )
    print(f"Rapport : {report}")


def lieu_import_cmd(args) -> None:
    """Import one place from a free-form address (fuzzy engine); print the summary."""
    from crewai_custom_tools.tools.genealogy.gramps.client import get_client

    from genecrew.lieu_import import format_lieu_import, run_lieu_import

    out = run_lieu_import(
        get_client(), args.place, min_score=args.min_score, dry_run=args.dry_run
    )
    print(format_lieu_import(out))


def releve_import_cmd(args) -> None:
    """`genecrew import releve` : lit le collage (stdin ou --file), apparie, écrit le net."""
    from crewai_custom_tools.tools.genealogy.gramps.client import get_client

    from genecrew.releves_import import format_import_releve, run_import_releve

    texte = (
        Path(args.file).read_text(encoding="utf-8") if args.file else sys.stdin.read()
    )
    if not texte.strip():
        raise SystemExit("Rien à importer : le relevé est vide.")
    # `--person` (args.person, None par défaut) force QUI on rattache, jamais le
    # DROIT d'écrire : il tranche un `gris` en désignant la bonne personne, mais
    # l'import reste soumis à toutes les gardes de sûreté (voir run_import_releve).
    resultat = run_import_releve(
        get_client(), texte, dry_run=args.dry_run, person=args.person
    )
    print(format_import_releve(resultat))


def crew_audit_cmd(args) -> None:
    """Run the two-agent audit crew over a scope; print the report path."""
    from pathlib import Path

    from crewai_custom_tools.tools.genealogy.gramps.client import get_client

    from genecrew.crew_audit import run_crew_audit

    client = get_client()
    output_dir = Path(os.environ.get("GENECREW_OUTPUT_DIR", "output"))
    date = args.date or __import__("datetime").date.today().isoformat()
    report = run_crew_audit(
        client,
        args.scope,
        output_dir,
        date=date,
        batch_size=args.batch_size,
        limit=args.limit,
        dry_run=args.dry_run,
    )
    print(f"Rapport : {report}")


def main() -> None:
    """CLI entry point: genecrew <verbe> <cible>."""
    load_dotenv()
    from genecrew.cli import build_parser

    args = build_parser().parse_args()
    target = getattr(args, "target", None)

    output_dir = Path(os.environ.get("GENECREW_OUTPUT_DIR", "output"))
    date = getattr(args, "date", None) or datetime.now().date().isoformat()
    log_path = configure_logging(output_dir, date=date)
    log = get_logger()
    log.info(
        "START command=%s target=%s args=%s",
        args.command,
        target,
        {k: v for k, v in vars(args).items() if k not in ("command", "target")},
    )

    dispatch = {
        ("stats", None): lambda: stats(),
        ("propose", "audit"): lambda: audit_cmd(args),
        ("propose", "places"): lambda: lieux_cmd(args),
        ("propose", "deaths"): lambda: deces_cmd(args),
        ("propose", "military"): lambda: militaires_cmd(args),
        ("propose", "gender"): lambda: gender_cmd(args),
        ("propose", "wikidata"): lambda: archives_cmd(args, "wikidata"),
        ("propose", "dhs"): lambda: archives_cmd(args, "dhs"),
        ("propose", "referentiel"): lambda: referentiel_cmd(args),
        ("apply", "case"): lambda: names_cmd(args),
        ("apply", "gender"): lambda: gender_apply_cmd(args),
        ("apply", "places"): lambda: lieux_apply_cmd(args),
        # Un seul point d'entrée pour tous les registres : INSEE, Mémoire des hommes,
        # presse Gallica. La source Gramps est déduite de chaque proposition du YAML
        # (deces_apply.source_title_for), pas du nom de la commande — ADR 0011.
        ("apply", "citations"): lambda: deces_apply_cmd(args),
        # `citations` pose une source sur un événement EXISTANT ; `deaths` CRÉE
        # l'événement absent. Deux commandes, un même YAML, des propositions
        # disjointes (`type: source` / `type: date`) — ADR 0014.
        ("apply", "deaths"): lambda: deces_event_cmd(args),
        ("apply", "all"): lambda: apply_all_cmd(args),
        ("apply", "referentiel"): lambda: referentiel_apply_cmd(args),
        ("merge", "places"): lambda: lieux_merge_cmd(args),
        ("merge", "people"): lambda: people_merge_cmd(args),
        ("enrich", "wiki"): lambda: lieux_wiki_cmd(args),
        ("import", "place"): lambda: lieu_import_cmd(args),
        ("import", "releve"): lambda: releve_import_cmd(args),
        ("crew", "audit"): lambda: crew_audit_cmd(args),
    }
    try:
        dispatch[(args.command, target)]()
        log.info("DONE command=%s target=%s", args.command, target)
    except Exception:
        log.exception("FAILED command=%s target=%s", args.command, target)
        raise
    finally:
        print(f"Log : {log_path}")


if __name__ == "__main__":
    main()
