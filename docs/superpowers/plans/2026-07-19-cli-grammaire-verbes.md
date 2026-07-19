# CLI grammaire de verbes — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remplacer les 16 sous-commandes plates de `genecrew` par 7 verbes
(`stats/propose/apply/merge/enrich/import/crew`) qui expriment le cycle
proposer → relire → appliquer.

**Architecture :** Sous-parseurs argparse imbriqués. La construction du parseur sort de
`main.py` vers un `cli.py` exposant `build_parser()` ; `main.py` ne garde que les fonctions
`*_cmd(args)` (inchangées) et une table de dispatch clée sur le couple `(command, target)`.
Aucune logique métier n'est touchée : les 20 modules du package restent identiques.

**Tech Stack :** Python 3.12, argparse, pytest, uv. Spec de référence :
`docs/superpowers/specs/2026-07-19-cli-grammaire-verbes-design.md`.

## Global Constraints

- Tout se lance **depuis la racine du dépôt** avec `uv` — jamais `pip` ni `python` direct.
  Tests : `uv run python -m pytest genecrew/tests/ -q`.
- **Vocabulaire tout anglais** dans la CLI : verbes et compléments. Aucun mot accentué.
- **Coupure nette** : aucun alias, aucune rétrocompatibilité pour les 16 anciens noms.
- **Aucun flag ne change de sémantique.** Deux renommages seulement : `--merges` et
  `--propositions` → `--yaml` (requis) ; `--sans-images` → `--no-images`.
- Les valeurs par défaut restent : `--min-score 0.90`, `--min-ratio 0.98`,
  `--batch-size` depuis `GENECREW_BATCH_SIZE` (défaut `25`), `--scope all`.
- Branche de travail : `cli-grammaire-verbes` (déjà créée, spec déjà commitée).
- Les archives datées ne sont **jamais** réécrites : `docs/superpowers/plans/*`,
  `docs/superpowers/specs/*` (sauf le spec de ce chantier), `.superpowers/sdd/*`,
  `output/rapports/*`.

---

### Task 1: `cli.py` — la grammaire, isolée et testable

Le parseur devient un module à part, construit par une fonction pure. Aucun sous-processus
n'est nécessaire pour le tester : on parse des listes d'arguments et on inspecte le
`Namespace`. Les 7 fichiers `test_cli_*.py` actuels lancent chacun un `uv run` complet pour
vérifier qu'un flag apparaît dans `--help` — ils sont remplacés par ce test unique.

**Files:**
- Create: `genecrew/src/genecrew/cli.py`
- Create: `genecrew/tests/test_cli_parser.py`
- Delete: `genecrew/tests/test_cli_apply_all.py`, `genecrew/tests/test_cli_audit.py`,
  `genecrew/tests/test_cli_gender.py`, `genecrew/tests/test_cli_gender_apply.py`,
  `genecrew/tests/test_cli_lieux.py`, `genecrew/tests/test_cli_lieux_apply.py`,
  `genecrew/tests/test_cli_names.py`

**Interfaces:**
- Consumes: rien (première tâche).
- Produces: `genecrew.cli.build_parser() -> argparse.ArgumentParser`. Le `Namespace`
  résultant porte toujours `args.command` (str) et, sauf pour `stats`, `args.target` (str).
  La Task 2 dispatche sur `(args.command, getattr(args, "target", None))`.

- [ ] **Step 1: Écrire le test qui échoue**

Créer `genecrew/tests/test_cli_parser.py` :

```python
import pytest

from genecrew.cli import build_parser

# (argv, command, target) — les 15 feuilles de la nouvelle grammaire
LEAVES = [
    (["stats"], "stats", None),
    (["propose", "audit"], "propose", "audit"),
    (["propose", "places"], "propose", "places"),
    (["propose", "deaths"], "propose", "deaths"),
    (["propose", "military"], "propose", "military"),
    (["propose", "gender"], "propose", "gender"),
    (["apply", "case"], "apply", "case"),
    (["apply", "gender"], "apply", "gender"),
    (["apply", "places"], "apply", "places"),
    (["apply", "citations", "--yaml", "relu.yaml"], "apply", "citations"),
    (["apply", "all"], "apply", "all"),
    (["merge", "places", "--yaml", "fusions.yaml"], "merge", "places"),
    (["enrich", "wiki"], "enrich", "wiki"),
    (["import", "place", "Bourges, Cher, France"], "import", "place"),
    (["crew", "audit"], "crew", "audit"),
]


@pytest.mark.parametrize("argv,command,target", LEAVES)
def test_every_leaf_parses(argv, command, target):
    args = build_parser().parse_args(argv)
    assert args.command == command
    assert getattr(args, "target", None) == target


OLD_NAMES = [
    "audit", "names", "gender", "gender-apply", "apply-all", "lieux",
    "lieux-apply", "lieux-merge", "lieux-wiki", "deces", "deces-apply",
    "militaires", "militaires-apply", "lieu-import", "crew-audit",
]


@pytest.mark.parametrize("old", OLD_NAMES)
def test_old_names_are_rejected(old):
    """Coupure nette : les anciens noms échouent bruyamment, ils n'écrivent rien."""
    with pytest.raises(SystemExit):
        build_parser().parse_args([old])


def test_a_verb_without_target_is_rejected():
    with pytest.raises(SystemExit):
        build_parser().parse_args(["propose"])


def test_yaml_is_required_for_apply_citations():
    with pytest.raises(SystemExit):
        build_parser().parse_args(["apply", "citations"])


def test_yaml_is_required_for_merge_places():
    with pytest.raises(SystemExit):
        build_parser().parse_args(["merge", "places"])


def test_defaults_are_preserved():
    args = build_parser().parse_args(["apply", "all"])
    assert args.scope == "all"
    assert args.min_ratio == 0.98
    assert args.min_score == 0.90
    assert args.limit is None
    assert args.dry_run is False


def test_batch_size_reads_the_environment(monkeypatch):
    monkeypatch.setenv("GENECREW_BATCH_SIZE", "7")
    args = build_parser().parse_args(["propose", "audit"])
    assert args.batch_size == 7


def test_renamed_flags_land_on_the_expected_attributes():
    args = build_parser().parse_args(["apply", "citations", "--yaml", "relu.yaml"])
    assert args.yaml == "relu.yaml"
    args = build_parser().parse_args(["enrich", "wiki", "--no-images"])
    assert args.no_images is True
    args = build_parser().parse_args(["import", "place", "Bourges, Cher, France"])
    assert args.place == "Bourges, Cher, France"
```

- [ ] **Step 2: Lancer le test pour vérifier qu'il échoue**

Run: `uv run python -m pytest genecrew/tests/test_cli_parser.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'genecrew.cli'`

- [ ] **Step 3: Écrire `cli.py`**

Créer `genecrew/src/genecrew/cli.py` :

```python
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
    _add_scope(p, "all (seul supporté pour les lieux en P1–P6)")
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
    _add_scope(p, "all (seul supporté pour les lieux en P1–P6)")
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

    # --- merge : jamais automatique, toujours depuis un YAML relu ---
    merge_p = sub.add_parser("merge", help="Fusions relues par un humain (jamais auto)")
    merge_sub = merge_p.add_subparsers(dest="target", required=True)

    p = merge_sub.add_parser("places", help="Fusionne les lieux listés dans un YAML relu")
    _add_yaml(p)
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

    # --- crew : escalade LLM ---
    crew_p = sub.add_parser("crew", help="Workflows interprétés par la crew LLM (coûteux)")
    crew_sub = crew_p.add_subparsers(dest="target", required=True)

    p = crew_sub.add_parser("audit", help="Audit interprété (Détective → Chroniqueur)")
    _add_scope(p)
    _add_batch(p)
    _add_dry_run(p)
    _add_date(p)

    return parser
```

- [ ] **Step 4: Lancer le test pour vérifier qu'il passe**

Run: `uv run python -m pytest genecrew/tests/test_cli_parser.py -q`
Expected: PASS (26 tests)

- [ ] **Step 5: Supprimer les 7 anciens tests CLI**

```bash
git rm genecrew/tests/test_cli_apply_all.py genecrew/tests/test_cli_audit.py \
       genecrew/tests/test_cli_gender.py genecrew/tests/test_cli_gender_apply.py \
       genecrew/tests/test_cli_lieux.py genecrew/tests/test_cli_lieux_apply.py \
       genecrew/tests/test_cli_names.py
```

- [ ] **Step 6: Vérifier que la suite complète passe**

Run: `uv run python -m pytest genecrew/tests/ -q`
Expected: PASS. `main.py` porte encore l'ancien parseur — c'est normal, la Task 2 le retire.

- [ ] **Step 7: Commit**

```bash
git add genecrew/src/genecrew/cli.py genecrew/tests/test_cli_parser.py
git commit -m "feat(cli): build_parser() — la grammaire de verbes, isolée et testable

Le parseur sort de main.py dans un cli.py testable sans sous-processus.
Les 7 test_cli_*.py qui lançaient chacun un 'uv run' pour vérifier la
présence d'un flag sont remplacés par des tests de parsing directs, qui
couvrent en plus le rejet des 16 anciens noms."
```

---

### Task 2: `main.py` — dispatch sur `(command, target)`

**Files:**
- Modify: `genecrew/src/genecrew/main.py` — supprimer les lignes 358-537 (bloc parseur +
  dispatch dans `main()`), réécrire `main()` ; ajuster 3 fonctions `*_cmd` pour les flags
  renommés ; corriger le docstring de `run()` (`main.py:34`).

**Interfaces:**
- Consumes: `genecrew.cli.build_parser()` (Task 1).
- Produces: `genecrew.main.main()` opérationnel sur la nouvelle grammaire. Les 16 fonctions
  `*_cmd(args)` gardent leur nom actuel — aucune n'est renommée.

- [ ] **Step 1: Écrire le test qui échoue**

Créer `genecrew/tests/test_cli_dispatch.py` :

```python
import pytest

from genecrew import main as main_mod
from genecrew.cli import build_parser

# (argv, nom de la fonction *_cmd que main() doit appeler)
ROUTES = [
    (["propose", "audit"], "audit_cmd"),
    (["propose", "places"], "lieux_cmd"),
    (["propose", "deaths"], "deces_cmd"),
    (["propose", "military"], "militaires_cmd"),
    (["propose", "gender"], "gender_cmd"),
    (["apply", "case"], "names_cmd"),
    (["apply", "gender"], "gender_apply_cmd"),
    (["apply", "places"], "lieux_apply_cmd"),
    (["apply", "citations", "--yaml", "relu.yaml"], "deces_apply_cmd"),
    (["apply", "all"], "apply_all_cmd"),
    (["merge", "places", "--yaml", "f.yaml"], "lieux_merge_cmd"),
    (["enrich", "wiki"], "lieux_wiki_cmd"),
    (["import", "place", "Bourges"], "lieu_import_cmd"),
    (["crew", "audit"], "crew_audit_cmd"),
]


@pytest.mark.parametrize("argv,expected_fn", ROUTES)
def test_each_leaf_routes_to_its_command(argv, expected_fn, monkeypatch, tmp_path):
    called = {}

    def _spy(args):
        called["fn"] = expected_fn

    monkeypatch.setattr(main_mod, expected_fn, _spy)
    monkeypatch.setenv("GENECREW_OUTPUT_DIR", str(tmp_path))
    monkeypatch.setattr("sys.argv", ["genecrew", *argv])

    main_mod.main()

    assert called["fn"] == expected_fn


def test_stats_routes_without_a_target(monkeypatch, tmp_path):
    called = {}
    monkeypatch.setattr(main_mod, "stats", lambda: called.setdefault("ok", True))
    monkeypatch.setenv("GENECREW_OUTPUT_DIR", str(tmp_path))
    monkeypatch.setattr("sys.argv", ["genecrew", "stats"])

    main_mod.main()

    assert called["ok"] is True


def test_there_is_no_separate_military_apply_leaf():
    """La fusion revendiquée par le spec : une seule feuille pour tous les registres.

    Le moteur est déjà couvert par test_deces_apply.py (INSEE et Mémoire des hommes
    passent par run_deces_apply) ; ici on vérifie seulement que la CLI n'en réexpose
    pas deux portes.
    """
    with pytest.raises(SystemExit):
        build_parser().parse_args(["apply", "military-citations", "--yaml", "x.yaml"])
    args = build_parser().parse_args(["apply", "citations", "--yaml", "x.yaml"])
    assert args.target == "citations"
```

- [ ] **Step 2: Lancer le test pour vérifier qu'il échoue**

Run: `uv run python -m pytest genecrew/tests/test_cli_dispatch.py -q`
Expected: FAIL — `main()` construit encore son propre parseur et ne connaît pas `propose`
(erreur `SystemExit: 2`, `invalid choice: 'propose'`).

- [ ] **Step 3: Ajuster les 3 fonctions `*_cmd` pour les flags renommés**

Dans `genecrew/src/genecrew/main.py` :

`lieux_merge_cmd` (ligne ~258) — `args.merges` devient `args.yaml` :

```python
    report = run_places_merge(client, args.yaml, output_dir, date=date, dry_run=args.dry_run)
```

`lieux_wiki_cmd` (ligne ~310) — `args.sans_images` devient `args.no_images` :

```python
    report = run_lieux_wiki(client, output_dir, date=date, limit=args.limit,
                            images=not args.no_images, dry_run=args.dry_run)
```

`deces_apply_cmd` (ligne ~326) — `args.propositions` devient `args.yaml` :

```python
    report = run_deces_apply(client, Path(args.yaml), output_dir,
                             date=date, dry_run=args.dry_run)
```

- [ ] **Step 4: Remplacer `main()`**

Supprimer intégralement le corps de `main()` (de `parser = argparse.ArgumentParser(...)`
jusqu'au `finally:` inclus, soit les lignes 361-537) et le remplacer par :

```python
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
    log.info("START command=%s target=%s args=%s", args.command, target,
             {k: v for k, v in vars(args).items() if k not in ("command", "target")})

    dispatch = {
        ("stats", None): lambda: stats(),
        ("propose", "audit"): lambda: audit_cmd(args),
        ("propose", "places"): lambda: lieux_cmd(args),
        ("propose", "deaths"): lambda: deces_cmd(args),
        ("propose", "military"): lambda: militaires_cmd(args),
        ("propose", "gender"): lambda: gender_cmd(args),
        ("apply", "case"): lambda: names_cmd(args),
        ("apply", "gender"): lambda: gender_apply_cmd(args),
        ("apply", "places"): lambda: lieux_apply_cmd(args),
        # Un seul point d'entrée pour tous les registres : INSEE, Mémoire des hommes,
        # presse Gallica. La source Gramps est déduite de chaque proposition du YAML
        # (deces_apply.source_title_for), pas du nom de la commande — ADR 0011.
        ("apply", "citations"): lambda: deces_apply_cmd(args),
        ("apply", "all"): lambda: apply_all_cmd(args),
        ("merge", "places"): lambda: lieux_merge_cmd(args),
        ("enrich", "wiki"): lambda: lieux_wiki_cmd(args),
        ("import", "place"): lambda: lieu_import_cmd(args),
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
```

Le dispatch est indirecté via le module (`main_mod.audit_cmd`) au moment de l'appel, ce qui
permet au test de la Step 1 de le monkeypatcher.

> Note pour l'implémenteur : les lambdas capturent les fonctions par résolution globale au
> moment de l'exécution, donc `monkeypatch.setattr(main_mod, "audit_cmd", ...)` fonctionne.
> Ne pas remplacer les lambdas par des références directes (`audit_cmd` sans lambda), ce qui
> figerait la fonction à la construction du dict et casserait les tests.

- [ ] **Step 5: Corriger le docstring de `run()`**

Dans `run()` (`main.py:34`), remplacer :

```
    on a small slice so writes are always simulated. Use `genecrew crew-audit` for the
```

par :

```
    on a small slice so writes are always simulated. Use `genecrew crew audit` for the
```

- [ ] **Step 6: Supprimer l'import argparse devenu inutile**

`main.py` n'utilise plus `argparse` (ligne 2). Le retirer.

Run: `uv run ruff check genecrew/src/genecrew/main.py`
Expected: aucune erreur (notamment aucun `F401 imported but unused`)

- [ ] **Step 7: Lancer les tests**

Run: `uv run python -m pytest genecrew/tests/ -q`
Expected: PASS, suite complète

- [ ] **Step 8: Vérifier la surface réelle de bout en bout**

```bash
uv run genecrew --help
uv run genecrew propose --help
uv run genecrew apply citations --help
uv run genecrew lieux-apply --dry-run   # doit ÉCHOUER
```
Expected: les trois premières commandes affichent l'aide ; la quatrième sort en code 2 avec
`invalid choice: 'lieux-apply'`.

- [ ] **Step 9: Commit**

```bash
git add genecrew/src/genecrew/main.py genecrew/tests/test_cli_dispatch.py
git commit -m "feat(cli)!: dispatch sur (verbe, cible), coupure nette des anciens noms

main() consomme build_parser() et dispatche sur le couple (command, target).
Les 16 anciens noms n'existent plus. --merges et --propositions fusionnent en
--yaml, --sans-images devient --no-images.

BREAKING CHANGE: 'genecrew lieux-apply' → 'genecrew apply places', etc.
Table de correspondance complète dans docs/adr/0012-cli-grammaire-verbes.md."
```

---

### Task 3: documentation vivante et ADR 0012

**Files:**
- Create: `docs/adr/0012-cli-grammaire-verbes.md`
- Modify: `CLAUDE.md` (9 occurrences d'anciens noms)
- Modify: `README.md` (5 occurrences)
- Modify: `docs/USER_GUIDE.md` (16 occurrences)
- **Ne pas toucher** : `docs/superpowers/plans/*`, `docs/superpowers/specs/*` (sauf le spec de
  ce chantier, déjà commité), `.superpowers/sdd/*`, `output/rapports/*`

**Interfaces:**
- Consumes: la surface finale livrée par les Tasks 1-2.
- Produces: rien de programmatique.

- [ ] **Step 1: Écrire l'ADR 0012**

Créer `docs/adr/0012-cli-grammaire-verbes.md` en suivant le format des ADR existants
(lire d'abord `docs/adr/0011-citations-insee-deces-apply.md` pour le gabarit exact :
titre, statut, date, contexte, décision, conséquences).

L'ADR doit porter :
- le constat d'accrétion (16 sous-commandes, 5 préfixes `lieux-*`, croissance linéaire
  avec les sources de données) ;
- les deux preuves que la surface plate mentait sur le code (dispatch identique
  `deces-apply`/`militaires-apply` ; `--scope/--limit/--batch-size/--date` déclarés 10 fois) ;
- la grammaire des 7 verbes ;
- **la table de correspondance complète des 16 anciens noms**, copiée depuis
  `docs/superpowers/specs/2026-07-19-cli-grammaire-verbes-design.md` ;
- la coupure nette et sa conséquence assumée (échec bruyant, aucune écriture) ;
- le fait que les archives datées ne sont pas réécrites, et que cet ADR est le pont.

- [ ] **Step 2: Mettre à jour `CLAUDE.md`**

Remplacer chaque ancienne commande par la nouvelle dans le bloc « Commands » et dans les
sections « Current state » / « Where the genealogy code lives ». Ajouter dans « Gotchas » :

```markdown
- **Grammaire de la CLI** : sept verbes — `stats`, `propose`, `apply`, `merge`, `enrich`,
  `import`, `crew` — qui suivent le cycle proposer → relire → appliquer. Ajouter une base
  de données ajoute une feuille sous `propose`, jamais un verbe ; le YAML relu qui en sort
  passe par `apply citations`, qui existe déjà. Les 16 anciens noms plats
  (`lieux-apply`, `deces-apply`, …) ont été supprimés sans alias — voir la table de
  correspondance dans `docs/adr/0012-cli-grammaire-verbes.md`.
```

Vérifier ensuite qu'aucun ancien nom ne subsiste :

```bash
grep -nE "genecrew (audit|names|gender|gender-apply|apply-all|lieux|lieux-apply|lieux-merge|lieux-wiki|deces|deces-apply|militaires|militaires-apply|lieu-import|crew-audit)\b" CLAUDE.md
```
Expected: aucune sortie

- [ ] **Step 3: Mettre à jour `README.md` et `docs/USER_GUIDE.md`**

Même traitement. `docs/USER_GUIDE.md` porte la séquence Phase 0 complète — relire les
enchaînements de commandes pour que le récit reste cohérent, pas seulement les noms.

```bash
grep -nE "genecrew (audit|names|gender|gender-apply|apply-all|lieux|lieux-apply|lieux-merge|lieux-wiki|deces|deces-apply|militaires|militaires-apply|lieu-import|crew-audit)\b" README.md docs/USER_GUIDE.md
```
Expected: aucune sortie

- [ ] **Step 4: Vérifier qu'aucune archive n'a été touchée**

```bash
git status --porcelain docs/superpowers/plans docs/superpowers/specs .superpowers output
```
Expected: aucune sortie (les archives datées sont intactes)

- [ ] **Step 5: Suite complète et lint**

Run: `uv run python -m pytest genecrew/tests/ -q && uv run ruff check .`
Expected: PASS, aucune erreur

- [ ] **Step 6: Commit**

```bash
git add docs/adr/0012-cli-grammaire-verbes.md CLAUDE.md README.md docs/USER_GUIDE.md
git commit -m "docs(cli): ADR 0012 et documentation vivante sur la grammaire de verbes

L'ADR porte la table de correspondance des 16 anciens noms. Les plans, specs
et rapports datés ne sont pas réécrits : ils décrivent ce qui était vrai à leur
date, et c'est l'ADR qui fait le pont."
```

---

## Ordre et parallélisme

Task 1 → Task 2 sont séquentielles (Task 2 consomme `build_parser()`).
**Task 3 ne dépend que du spec** et peut tourner en parallèle de la Task 2.

## Écarts assumés par rapport au spec

Deux points où l'écriture du plan a corrigé le spec :

1. Le spec prévoyait de renommer les 7 `test_cli_*.py` « d'après le verbe ». Ils sont à la
   place **fusionnés** dans `test_cli_parser.py` : chacun ne faisait qu'un `uv run` complet
   pour vérifier la présence d'un flag dans `--help`. Sept sous-processus deviennent des
   tests de parsing directs, et la couverture augmente (rejet des anciens noms inclus).
2. Le spec prévoyait un test vérifiant qu'`apply citations` accepte indifféremment un YAML
   INSEE et un YAML Mémoire des hommes. **Ce test existe déjà** —
   `test_deces_apply.py:54` (`test_source_title_routed_per_register`) et
   `test_deces_apply.py:62` (`test_apply_militaires_prop_creates_mdh_source`). La tâche
   correspondante a été supprimée du plan plutôt que de dupliquer une couverture existante.
   Il ne reste, dans `test_cli_dispatch.py`, que la vérification que la CLI n'expose pas
   deux portes vers ce moteur.
