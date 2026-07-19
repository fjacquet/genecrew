#!/usr/bin/env python
import argparse
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
    on a small slice so writes are always simulated. Use `genecrew crew-audit` for the
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
            get_client(), "all", output_dir,
            date=datetime.now().date().isoformat(), limit=limit, dry_run=True)
        print(f"Rapport : {report}")
    except Exception as e:
        raise Exception(f"An error occurred while running the crew: {e}")


def train():
    """
    Train the crew for a given number of iterations.
    """
    from genecrew.crew import Genecrew

    try:
        Genecrew().crew().train(
            n_iterations=int(sys.argv[1]), filename=sys.argv[2], inputs=_placeholder_inputs())

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

    try:
        Genecrew().crew().test(
            n_iterations=int(sys.argv[1]), eval_llm=sys.argv[2], inputs=_placeholder_inputs())

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
    """Apply casing, then gender, then places in one pass; print all report paths."""
    from pathlib import Path

    from crewai_custom_tools.tools.genealogy.gramps.client import get_client

    from genecrew.apply_all import run_apply_all

    client = get_client()
    output_dir = Path(os.environ.get("GENECREW_OUTPUT_DIR", "output"))
    date = args.date or __import__("datetime").date.today().isoformat()
    paths = run_apply_all(client, args.scope, output_dir, date=date,
                          min_ratio=args.min_ratio, min_score=args.min_score,
                          batch_size=args.batch_size,
                          limit=args.limit, dry_run=args.dry_run)
    print(f"Casse : {paths['names']}")
    print(f"Noms à vérifier : {paths['incomplete']}")
    print(f"Genres : {paths['gender']}")
    print(f"Lieux : {paths['lieux']}")


def lieux_cmd(args) -> None:
    """Standardize places over a scope (read-only); print the report paths."""
    from pathlib import Path

    from crewai_custom_tools.tools.genealogy.gramps.client import get_client

    from genecrew.places import run_places

    client = get_client()
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

    from crewai_custom_tools.tools.genealogy.gramps.client import get_client

    from genecrew.places_apply import run_places_apply

    client = get_client()
    output_dir = Path(os.environ.get("GENECREW_OUTPUT_DIR", "output"))
    date = args.date or __import__("datetime").date.today().isoformat()
    report = run_places_apply(client, args.scope, output_dir, date=date,
                              min_score=args.min_score, batch_size=args.batch_size,
                              limit=args.limit, dry_run=args.dry_run)
    print(f"Rapport : {report}")


def lieux_merge_cmd(args) -> None:
    """Execute human-reviewed place merges from a fusions YAML; print the report path."""
    from pathlib import Path

    from crewai_custom_tools.tools.genealogy.gramps.client import get_client

    from genecrew.places_merge import run_places_merge

    client = get_client()
    output_dir = Path(os.environ.get("GENECREW_OUTPUT_DIR", "output"))
    date = args.date or __import__("datetime").date.today().isoformat()
    report = run_places_merge(client, args.merges, output_dir, date=date, dry_run=args.dry_run)
    print(f"Rapport : {report}")


def deces_cmd(args) -> None:
    """Deterministic INSEE/MatchID death enrichment (read-only); print report paths."""
    from pathlib import Path

    from crewai_custom_tools.tools.genealogy.gramps.client import get_client

    from genecrew.deces import run_deces

    client = get_client()
    output_dir = Path(os.environ.get("GENECREW_OUTPUT_DIR", "output"))
    date = args.date or __import__("datetime").date.today().isoformat()
    report, proposals = run_deces(client, args.scope, output_dir, date=date,
                                  min_score=args.min_score, batch_size=args.batch_size,
                                  limit=args.limit)
    print(f"Rapport : {report}")
    print(f"Propositions : {proposals}")


def crew_audit_cmd(args) -> None:
    """Run the two-agent audit crew over a scope; print the report path."""
    from pathlib import Path

    from crewai_custom_tools.tools.genealogy.gramps.client import get_client

    from genecrew.crew_audit import run_crew_audit

    client = get_client()
    output_dir = Path(os.environ.get("GENECREW_OUTPUT_DIR", "output"))
    date = args.date or __import__("datetime").date.today().isoformat()
    report = run_crew_audit(client, args.scope, output_dir, date=date,
                            batch_size=args.batch_size, limit=args.limit,
                            dry_run=args.dry_run)
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
                           help="Applique toutes les corrections auto : casse puis genre puis lieux")
    all_p.add_argument("--scope", default="all", help="all | person:ID")
    all_p.add_argument("--min-ratio", type=float, default=0.98,
                       help="seuil de confiance du volet genre (défaut 0.98)")
    all_p.add_argument("--min-score", type=float, default=0.90,
                       help="seuil de score du volet lieux (défaut 0.90)")
    all_p.add_argument("--limit", type=int, default=None, help="limiter à N personnes")
    all_p.add_argument("--batch-size", type=int,
                       default=int(os.environ.get("GENECREW_BATCH_SIZE", "25")))
    all_p.add_argument("--dry-run", action="store_true", help="simuler sans écrire")
    all_p.add_argument("--date", default=None, help="date des rapports (défaut : aujourd'hui)")

    lieux_p = sub.add_parser("lieux", help="Standardisation des lieux (lecture seule)")
    lieux_p.add_argument("--scope", default="all",
                         help="all (seul supporté pour les lieux en P1–P6)")
    lieux_p.add_argument("--limit", type=int, default=None, help="limiter à N lieux")
    lieux_p.add_argument("--batch-size", type=int,
                         default=int(os.environ.get("GENECREW_BATCH_SIZE", "25")))
    lieux_p.add_argument("--min-score", type=float, default=0.90,
                         help="seuil de score pour action=ecrire (défaut 0.90)")
    lieux_p.add_argument("--date", default=None, help="date du rapport (défaut : aujourd'hui)")

    la_p = sub.add_parser("lieux-apply",
                          help="Applique (écrit) la standardisation des lieux au-dessus du score")
    la_p.add_argument("--scope", default="all",
                      help="all (seul supporté pour les lieux en P1–P6)")
    la_p.add_argument("--min-score", type=float, default=0.90,
                      help="seuil de score pour écrire (défaut 0.90)")
    la_p.add_argument("--limit", type=int, default=None, help="limiter à N lieux")
    la_p.add_argument("--batch-size", type=int,
                      default=int(os.environ.get("GENECREW_BATCH_SIZE", "25")))
    la_p.add_argument("--dry-run", action="store_true", help="simuler sans écrire")
    la_p.add_argument("--date", default=None, help="date du rapport (défaut : aujourd'hui)")

    lm_p = sub.add_parser("lieux-merge",
                          help="Exécute les fusions de lieux depuis un YAML relu (jamais auto)")
    lm_p.add_argument("--merges", required=True, help="chemin du YAML de fusions (relu par un humain)")
    lm_p.add_argument("--dry-run", action="store_true", help="simuler sans fusionner")
    lm_p.add_argument("--date", default=None, help="date du rapport (défaut : aujourd'hui)")

    dc_p = sub.add_parser("deces",
                          help="Enrichissement décès INSEE/MatchID, déterministe (lecture seule)")
    dc_p.add_argument("--scope", default="all", help="all | person:ID")
    dc_p.add_argument("--limit", type=int, default=None, help="limiter à N personnes")
    dc_p.add_argument("--batch-size", type=int,
                      default=int(os.environ.get("GENECREW_BATCH_SIZE", "25")))
    dc_p.add_argument("--min-score", type=float, default=0.90,
                      help="seuil du score déterministe (défaut 0.90)")
    dc_p.add_argument("--date", default=None, help="date du rapport (défaut : aujourd'hui)")

    ca_p = sub.add_parser("crew-audit",
                          help="Audit interprété par la crew LLM (Détective → Chroniqueur)")
    ca_p.add_argument("--scope", default="all", help="all | person:ID")
    ca_p.add_argument("--limit", type=int, default=None, help="limiter à N personnes (borne le coût LLM)")
    ca_p.add_argument("--batch-size", type=int,
                      default=int(os.environ.get("GENECREW_BATCH_SIZE", "25")))
    ca_p.add_argument("--dry-run", action="store_true",
                      help="simuler les écritures (défaut sûr : simulation via GENECREW_DRY_RUN)")
    ca_p.add_argument("--date", default=None, help="date du rapport (défaut : aujourd'hui)")

    args = parser.parse_args()

    output_dir = Path(os.environ.get("GENECREW_OUTPUT_DIR", "output"))
    date = getattr(args, "date", None) or datetime.now().date().isoformat()
    log_path = configure_logging(output_dir, date=date)
    log = get_logger()
    log.info("START command=%s args=%s", args.command,
             {k: v for k, v in vars(args).items() if k != "command"})

    dispatch = {
        "stats": lambda: stats(),
        "audit": lambda: audit_cmd(args),
        "names": lambda: names_cmd(args),
        "gender": lambda: gender_cmd(args),
        "gender-apply": lambda: gender_apply_cmd(args),
        "apply-all": lambda: apply_all_cmd(args),
        "lieux": lambda: lieux_cmd(args),
        "lieux-apply": lambda: lieux_apply_cmd(args),
        "lieux-merge": lambda: lieux_merge_cmd(args),
        "crew-audit": lambda: crew_audit_cmd(args),
        "deces": lambda: deces_cmd(args),
    }
    try:
        dispatch[args.command]()
        log.info("DONE command=%s", args.command)
    except Exception:
        log.exception("FAILED command=%s", args.command)
        raise
    finally:
        print(f"Log : {log_path}")


if __name__ == "__main__":
    main()
