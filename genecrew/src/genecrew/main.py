#!/usr/bin/env python
import argparse
import os
import sys
import warnings

from datetime import datetime

from dotenv import load_dotenv

warnings.filterwarnings("ignore", category=SyntaxWarning, module="pysbd")

# This main file is intended to be a way for you to run your
# crew locally, so refrain from adding unnecessary logic into this file.
# Replace with inputs you want to test with, it will automatically
# interpolate any tasks and agents information

def run():
    """
    Run the crew.
    """
    from genecrew.crew import Genecrew

    inputs = {
        'topic': 'AI LLMs',
        'current_year': str(datetime.now().year)
    }
    
    try:
        Genecrew().crew().kickoff(inputs=inputs)
    except Exception as e:
        raise Exception(f"An error occurred while running the crew: {e}")


def train():
    """
    Train the crew for a given number of iterations.
    """
    from genecrew.crew import Genecrew

    inputs = {
        "topic": "AI LLMs",
        'current_year': str(datetime.now().year)
    }
    try:
        Genecrew().crew().train(n_iterations=int(sys.argv[1]), filename=sys.argv[2], inputs=inputs)

    except Exception as e:
        raise Exception(f"An error occurred while training the crew: {e}")

def replay():
    """
    Replay the crew execution from a specific task.
    """
    from genecrew.crew import Genecrew

    try:
        Genecrew().crew().replay(task_id=sys.argv[1])

    except Exception as e:
        raise Exception(f"An error occurred while replaying the crew: {e}")

def test():
    """
    Test the crew execution and returns the results.
    """
    from genecrew.crew import Genecrew

    inputs = {
        "topic": "AI LLMs",
        "current_year": str(datetime.now().year)
    }

    try:
        Genecrew().crew().test(n_iterations=int(sys.argv[1]), eval_llm=sys.argv[2], inputs=inputs)

    except Exception as e:
        raise Exception(f"An error occurred while testing the crew: {e}")


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
        client, args.scope, output_dir, date=date,
        batch_size=args.batch_size, limit=args.limit,
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
        client, args.scope, output_dir, date=date,
        batch_size=args.batch_size, limit=args.limit, dry_run=args.dry_run,
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
    report, proposals = run_gender(client, args.scope, output_dir, date=date, limit=args.limit)
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
    report = run_gender_apply(client, args.scope, output_dir, date=date,
                              min_ratio=args.min_ratio, limit=args.limit, dry_run=args.dry_run)
    print(f"Rapport : {report}")


def apply_all_cmd(args) -> None:
    """Apply casing then gender in one pass; print all report paths."""
    from pathlib import Path

    from crewai_custom_tools.tools.genealogy.gramps.client import (
        GrampsClient,
        GrampsConfig,
    )

    from genecrew.apply_all import run_apply_all

    client = GrampsClient(GrampsConfig.from_env())
    output_dir = Path(os.environ.get("GENECREW_OUTPUT_DIR", "output"))
    date = args.date or __import__("datetime").date.today().isoformat()
    paths = run_apply_all(client, args.scope, output_dir, date=date,
                          min_ratio=args.min_ratio, batch_size=args.batch_size,
                          limit=args.limit, dry_run=args.dry_run)
    print(f"Casse : {paths['names']}")
    print(f"Noms à vérifier : {paths['incomplete']}")
    print(f"Genres : {paths['gender']}")


def lieux_cmd(args) -> None:
    """Standardize places over a scope (read-only); print the report paths."""
    from pathlib import Path

    from crewai_custom_tools.tools.genealogy.gramps.client import GrampsClient, GrampsConfig

    from genecrew.places import run_places

    client = GrampsClient(GrampsConfig.from_env())
    output_dir = Path(os.environ.get("GENECREW_OUTPUT_DIR", "output"))
    date = args.date or __import__("datetime").date.today().isoformat()
    report, proposals = run_places(client, args.scope, output_dir, date=date,
                                   batch_size=args.batch_size, limit=args.limit,
                                   min_score=args.min_score)
    print(f"Rapport : {report}")
    print(f"Propositions : {proposals}")


def lieux_apply_cmd(args) -> None:
    """Apply place standardization (write hierarchy + GPS); print the report path."""
    from pathlib import Path

    from crewai_custom_tools.tools.genealogy.gramps.client import GrampsClient, GrampsConfig

    from genecrew.places_apply import run_places_apply

    client = GrampsClient(GrampsConfig.from_env())
    output_dir = Path(os.environ.get("GENECREW_OUTPUT_DIR", "output"))
    date = args.date or __import__("datetime").date.today().isoformat()
    report = run_places_apply(client, args.scope, output_dir, date=date,
                              min_score=args.min_score, batch_size=args.batch_size,
                              limit=args.limit, dry_run=args.dry_run)
    print(f"Rapport : {report}")


def main() -> None:
    """CLI entry point: genecrew <command>."""
    load_dotenv()
    parser = argparse.ArgumentParser(prog="genecrew", description="GeneCrew CLI")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("stats", help="Statistiques de l'arbre Gramps Web")

    audit_p = sub.add_parser("audit", help="Audit qualité déterministe (sans LLM)")
    audit_p.add_argument("--scope", default="all",
                         help="all | person:ID (branch:ID en Phase 1b)")
    audit_p.add_argument("--limit", type=int, default=None,
                         help="limiter à N personnes (échantillon)")
    audit_p.add_argument("--batch-size", type=int,
                         default=int(os.environ.get("GENECREW_BATCH_SIZE", "25")))
    audit_p.add_argument("--date", default=None, help="date du rapport (défaut : aujourd'hui)")

    names_p = sub.add_parser("names", help="Standardisation de la casse des noms")
    names_p.add_argument("--scope", default="all", help="all | person:ID")
    names_p.add_argument("--limit", type=int, default=None, help="limiter à N personnes")
    names_p.add_argument("--batch-size", type=int,
                         default=int(os.environ.get("GENECREW_BATCH_SIZE", "25")))
    names_p.add_argument("--dry-run", action="store_true",
                         help="aperçu sans écrire (défaut : écriture réelle)")
    names_p.add_argument("--date", default=None, help="date du rapport (défaut : aujourd'hui)")

    gender_p = sub.add_parser("gender",
                              help="Inférence de genre à partir du prénom (lecture seule)")
    gender_p.add_argument("--scope", default="all", help="all | person:ID")
    gender_p.add_argument("--limit", type=int, default=None, help="limiter à N personnes")
    gender_p.add_argument("--date", default=None, help="date du rapport (défaut : aujourd'hui)")

    apply_p = sub.add_parser("gender-apply",
                             help="Applique (écrit) les corrections de genre à haute confiance")
    apply_p.add_argument("--scope", default="all", help="all | person:ID")
    apply_p.add_argument("--min-ratio", type=float, default=0.98,
                         help="seuil de confiance pour écrire (défaut 0.98)")
    apply_p.add_argument("--limit", type=int, default=None, help="limiter à N personnes")
    apply_p.add_argument("--dry-run", action="store_true", help="simuler sans écrire")
    apply_p.add_argument("--date", default=None, help="date du rapport (défaut : aujourd'hui)")

    all_p = sub.add_parser("apply-all",
                           help="Applique toutes les corrections auto : casse puis genre")
    all_p.add_argument("--scope", default="all", help="all | person:ID")
    all_p.add_argument("--min-ratio", type=float, default=0.98,
                       help="seuil de confiance du volet genre (défaut 0.98)")
    all_p.add_argument("--limit", type=int, default=None, help="limiter à N personnes")
    all_p.add_argument("--batch-size", type=int,
                       default=int(os.environ.get("GENECREW_BATCH_SIZE", "25")))
    all_p.add_argument("--dry-run", action="store_true", help="simuler sans écrire")
    all_p.add_argument("--date", default=None, help="date des rapports (défaut : aujourd'hui)")

    lieux_p = sub.add_parser("lieux", help="Standardisation des lieux (lecture seule)")
    lieux_p.add_argument("--scope", default="all", help="all | person:ID")
    lieux_p.add_argument("--limit", type=int, default=None, help="limiter à N lieux")
    lieux_p.add_argument("--batch-size", type=int,
                         default=int(os.environ.get("GENECREW_BATCH_SIZE", "25")))
    lieux_p.add_argument("--min-score", type=float, default=0.90,
                         help="seuil de score pour action=ecrire (défaut 0.90)")
    lieux_p.add_argument("--date", default=None, help="date du rapport (défaut : aujourd'hui)")

    la_p = sub.add_parser("lieux-apply",
                          help="Applique (écrit) la standardisation des lieux au-dessus du score")
    la_p.add_argument("--scope", default="all", help="all | person:ID")
    la_p.add_argument("--min-score", type=float, default=0.90,
                      help="seuil de score pour écrire (défaut 0.90)")
    la_p.add_argument("--limit", type=int, default=None, help="limiter à N lieux")
    la_p.add_argument("--batch-size", type=int,
                      default=int(os.environ.get("GENECREW_BATCH_SIZE", "25")))
    la_p.add_argument("--dry-run", action="store_true", help="simuler sans écrire")
    la_p.add_argument("--date", default=None, help="date du rapport (défaut : aujourd'hui)")

    args = parser.parse_args()
    if args.command == "stats":
        stats()
    elif args.command == "audit":
        audit_cmd(args)
    elif args.command == "names":
        names_cmd(args)
    elif args.command == "gender":
        gender_cmd(args)
    elif args.command == "gender-apply":
        gender_apply_cmd(args)
    elif args.command == "apply-all":
        apply_all_cmd(args)
    elif args.command == "lieux":
        lieux_cmd(args)
    elif args.command == "lieux-apply":
        lieux_apply_cmd(args)


if __name__ == "__main__":
    main()
