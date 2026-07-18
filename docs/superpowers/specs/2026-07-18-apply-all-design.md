# `apply-all` — commande parapluie — Design

> Statut : approuvé (brainstorming inline) — 2026-07-18
> Portée : petit incrément d'orchestration (genecrew seul). Aucun nouvel outil, aucune nouvelle
> logique métier — enchaîne deux commandes existantes déjà testées et fusionnées.

## Objectif

Une seule commande `genecrew apply-all` qui applique **toutes** les corrections automatiques
disponibles en un passage : d'abord la **casse** des noms (forme, sûre), puis les **genres** à
haute confiance (fait, borné). Partage les mêmes garde-fous (périmètre, dry-run, interrupteur
global) que les commandes sous-jacentes.

## Comportement

`run_apply_all(client, scope, output_dir, *, date, min_ratio=0.98, batch_size=25, limit=None,
dry_run=False) -> dict[str, Path]` enchaîne, dans cet ordre :

1. **Casse** — `run_names(client, scope, output_dir, date=…, batch_size=…, limit=…, dry_run=…)`
   → rapport de casse + liste des noms incomplets.
2. **Genre** — `run_gender_apply(client, scope, output_dir, date=…, min_ratio=…, batch_size=…,
   limit=…, dry_run=…)` → rapport des genres appliqués.

Retourne `{"names": Path, "incomplete": Path, "gender": Path}`. La CLI affiche les trois chemins.

**Ordre casse → genre** : indépendant (la casse ne change pas l'inférence de genre, `normkey`
met en MAJUSCULES) ; on met la forme (sûre) avant le fait (sensible).

## CLI

`genecrew apply-all [--scope all] [--limit N] [--min-ratio 0.98] [--batch-size N] [--dry-run]
[--date]`. `--min-ratio` ne concerne que le volet genre. Le dry-run (`--dry-run` ou
`GENECREW_DRY_RUN`, défaut = simulation) est propagé aux deux étapes.

## Ce que ça n'est pas (YAGNI)

- Pas de rapport combiné : on réutilise les rapports des deux commandes (deux/trois fichiers).
- Pas de nouvel outil d'écriture ni de nouvelle règle : pure orchestration.
- Pas de gestion d'erreur spécifique : chaque commande a déjà la sienne (les erreurs de genre
  sont consignées dans son rapport, pas fatales).

## Fichiers

- `genecrew/src/genecrew/apply_all.py` (nouveau) : `run_apply_all` (mince orchestration).
- `genecrew/src/genecrew/main.py` : sous-commande `apply-all` + `apply_all_cmd`.
- `genecrew/tests/test_apply_all.py`, `genecrew/tests/test_cli_apply_all.py`.
- `docs/USER_GUIDE.md` : courte section « Tout appliquer ».

## Tests

- `run_apply_all` (mock httpx, table injectée pour le volet genre via monkeypatch de
  `load_prenoms_table`, ou un client mock renvoyant peu de personnes) : vérifie que les deux
  étapes tournent et que le dict des chemins est retourné ; `--dry-run` → aucun PUT (mock lève).
- CLI `apply-all --help` : `--scope`, `--min-ratio`, `--dry-run` présents.
