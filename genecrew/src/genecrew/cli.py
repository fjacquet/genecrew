"""Construction du parseur d'arguments : la grammaire de verbes de la CLI.

Sept verbes — stats, propose, apply, merge, enrich, import, crew — qui expriment le
cycle du projet : proposer (lecture seule) → relire (humain) → appliquer (écriture).
Ajouter une base de données ajoute une feuille sous `propose`, jamais un verbe.

`build_parser()` est pure : elle ne lit l'environnement que pour les valeurs par défaut,
et `main()` appelle `load_dotenv()` avant elle.

Voir docs/adr/0012-cli-grammaire-verbes.md.
"""
import argparse
import os

_DATE_HELP = "date du rapport (défaut : aujourd'hui)"


def _add_scope(p: argparse.ArgumentParser, scope_help: str = "all | person:ID") -> None:
    p.add_argument("--scope", default="all", help=scope_help)
    p.add_argument("--limit", type=int, default=None, help="limiter à N éléments")


def _add_batch(p: argparse.ArgumentParser) -> None:
    p.add_argument("--batch-size", type=int,
                   default=int(os.environ.get("GENECREW_BATCH_SIZE", "25")))


def _add_min_score(p: argparse.ArgumentParser,
                   help_text: str = "seuil de score (défaut 0.90)") -> None:
    p.add_argument("--min-score", type=float, default=0.90, help=help_text)


def _add_dry_run(p: argparse.ArgumentParser) -> None:
    p.add_argument("--dry-run", action="store_true", help="simuler sans écrire")


def _add_date(p: argparse.ArgumentParser) -> None:
    p.add_argument("--date", default=None, help=_DATE_HELP)


def _add_yaml(p: argparse.ArgumentParser) -> None:
    p.add_argument("--yaml", required=True,
                   help="chemin du YAML RELU par un humain")


def build_parser() -> argparse.ArgumentParser:
    """Le parseur complet de la CLI genecrew."""
    parser = argparse.ArgumentParser(prog="genecrew", description="GeneCrew CLI")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("stats", help="Statistiques de l'arbre Gramps Web")

    # --- propose : lecture seule → rapport (+ YAML de propositions) ---
    propose = sub.add_parser(
        "propose", help="Analyses en lecture seule : rapport et propositions à relire")
    propose_sub = propose.add_subparsers(dest="target", required=True)

    p = propose_sub.add_parser("audit", help="Audit qualité déterministe (sans LLM)")
    _add_scope(p, "all | person:ID (branch:ID en Phase 1b)")
    _add_batch(p)
    _add_date(p)

    p = propose_sub.add_parser("places", help="Standardisation des lieux")
    _add_scope(p, "all | place:ID (cibler un lieu unique)")
    _add_batch(p)
    _add_min_score(p, "seuil de score pour action=ecrire (défaut 0.90)")
    _add_date(p)

    p = propose_sub.add_parser(
        "deaths", help="Enrichissement décès INSEE/MatchID, déterministe")
    _add_scope(p)
    _add_batch(p)
    _add_min_score(p, "seuil du score déterministe (défaut 0.90)")
    _add_date(p)

    p = propose_sub.add_parser(
        "military",
        help="Enrichissement décès militaires (Mémoire des hommes, gazetteer hors-ligne)")
    _add_scope(p)
    _add_batch(p)
    _add_min_score(p, "seuil du score déterministe (défaut 0.90)")
    _add_date(p)

    p = propose_sub.add_parser("gender", help="Inférence de genre à partir du prénom")
    _add_scope(p)
    _add_date(p)

    p = propose_sub.add_parser(
        "wikidata", help="Pistes Wikidata (personnes notables ; seules pistes fortes)")
    _add_scope(p)
    _add_batch(p)
    _add_date(p)

    p = propose_sub.add_parser(
        "dhs", help="Pistes DHS — Dictionnaire historique de la Suisse (via Wikidata P902)")
    _add_scope(p)
    _add_batch(p)
    _add_date(p)

    # --- apply : écrit dans Gramps ---
    apply_p = sub.add_parser("apply", help="Applique des corrections (écrit)")
    apply_sub = apply_p.add_subparsers(dest="target", required=True)

    p = apply_sub.add_parser("case", help="Standardisation de la casse des noms")
    _add_scope(p)
    _add_batch(p)
    _add_dry_run(p)
    _add_date(p)

    p = apply_sub.add_parser(
        "gender", help="Corrections de genre à haute confiance (ADR 0009)")
    _add_scope(p)
    p.add_argument("--min-ratio", type=float, default=0.98,
                   help="seuil de confiance pour écrire (défaut 0.98)")
    _add_dry_run(p)
    _add_date(p)

    p = apply_sub.add_parser("places", help="Hiérarchie et GPS des lieux au-dessus du score")
    _add_scope(p, "all | place:ID (cibler un lieu unique)")
    _add_batch(p)
    _add_min_score(p, "seuil de score pour écrire (défaut 0.90)")
    _add_dry_run(p)
    _add_date(p)

    p = apply_sub.add_parser(
        "citations",
        help="Citations de registres depuis un YAML relu — INSEE, Mémoire des hommes, "
             "presse Gallica : le registre vient du YAML, pas de la commande (ADR 0011)")
    _add_yaml(p)
    _add_dry_run(p)
    _add_date(p)

    p = apply_sub.add_parser("all", help="Casse, puis genre, puis lieux, en un passage")
    _add_scope(p)
    p.add_argument("--min-ratio", type=float, default=0.98,
                   help="seuil de confiance du volet genre (défaut 0.98)")
    _add_min_score(p, "seuil de score du volet lieux (défaut 0.90)")
    _add_batch(p)
    _add_dry_run(p)
    _add_date(p)

    # --- merge : lieux et personnes se fusionnent selon le même schéma — détection
    # automatique au-dessus d'une preuve STRUCTURELLE, jamais d'un score, ou exécution
    # d'un YAML relu quand la preuve manque (voir
    # docs/superpowers/specs/2026-07-20-fusion-doublons-personnes-design.md pour les
    # personnes, ADR 0015 pour les lieux).
    merge_p = sub.add_parser(
        "merge", help="Fusions : lieux et personnes, sur preuve ou depuis un YAML relu")
    merge_sub = merge_p.add_subparsers(dest="target", required=True)

    p = merge_sub.add_parser(
        "places", help="Détecte les doublons de lieux et fusionne les prouvés ; "
             "ou exécute un YAML relu (ADR 0015)")
    # `place:ID` ne lit qu'un lieu, qui ne forme jamais de groupe d'homonymes : le
    # périmètre sert à inspecter, pas à détecter, et force la simulation comme --limit.
    _add_scope(p, "all | place:ID (place:ID n'inspecte qu'un lieu : aucune détection "
                  "possible, écritures désactivées)")
    p.add_argument("--yaml", default=None,
                   help="exécuter les fusions d'un YAML relu, au lieu de détecter")
    _add_dry_run(p)
    _add_date(p)

    p = merge_sub.add_parser(
        "people",
        help="Fusionne les doublons prouvés ; dépose le reste en YAML d'arbitrage")
    _add_scope(p)
    p.add_argument("--yaml", default=None,
                   help="exécuter les paires d'un YAML d'arbitrage relu, au lieu de détecter")
    p.add_argument("--max-passes", type=int, default=5,
                   help="bornes des passes de convergence (défaut : 5)")
    _add_dry_run(p)
    _add_date(p)

    # --- enrich : append-only ---
    enrich_p = sub.add_parser("enrich", help="Enrichissements append-only")
    enrich_sub = enrich_p.add_subparsers(dest="target", required=True)

    p = enrich_sub.add_parser(
        "wiki",
        help="Lien Wikipédia vérifié (nom+GPS) et image d'article sur les lieux géoréférencés")
    p.add_argument("--limit", type=int, default=None, help="limiter à N lieux")
    p.add_argument("--no-images", action="store_true",
                   help="ne poser que les liens, pas les images")
    _add_dry_run(p)
    _add_date(p)

    # --- import : one-shot ---
    import_p = sub.add_parser("import", help="Imports ponctuels")
    import_sub = import_p.add_subparsers(dest="target", required=True)

    p = import_sub.add_parser("place", help="Importer un lieu depuis une adresse libre")
    p.add_argument("place", help='adresse, ex. "Bourges, Cher, France"')
    _add_min_score(p, "seuil de score pour créer (défaut 0.90)")
    _add_dry_run(p)

    p = import_sub.add_parser(
        "releve", help="Importer un relevé collé (stdin par défaut) avec smart match")
    p.add_argument("--file", default=None,
                   help="fichier contenant le relevé (défaut : stdin)")
    p.add_argument("--person", default=None,
                   help="forcer le rattachement à cette personne (ID Gramps)")
    _add_dry_run(p)

    # --- crew : escalade LLM ---
    crew_p = sub.add_parser("crew", help="Workflows interprétés par la crew LLM (coûteux)")
    crew_sub = crew_p.add_subparsers(dest="target", required=True)

    p = crew_sub.add_parser("audit", help="Audit interprété (Détective → Chroniqueur)")
    _add_scope(p)
    _add_batch(p)
    _add_dry_run(p)
    _add_date(p)

    return parser
