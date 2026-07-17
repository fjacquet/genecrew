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
        batch_size=args.batch_size, limit=args.limit, resume=args.resume,
    )
    print(f"Rapport écrit : {path}")


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
    audit_p.add_argument("--resume", action="store_true",
                         help="reprendre depuis le dernier checkpoint")
    audit_p.add_argument("--date", default=None, help="date du rapport (défaut : aujourd'hui)")

    args = parser.parse_args()
    if args.command == "stats":
        stats()
    elif args.command == "audit":
        audit_cmd(args)


if __name__ == "__main__":
    main()
