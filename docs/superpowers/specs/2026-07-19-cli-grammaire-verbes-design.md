# CLI : de 16 sous-commandes plates à une grammaire de verbes

**Date** : 2026-07-19
**Statut** : validé, prêt pour plan d'implémentation

## Problème

`genecrew` expose 16 sous-commandes plates, dont 5 préfixées `lieux-*`. Le nom encode
l'outil, pas le geste. Chaque nouveau domaine (décès, militaires, wiki, import) a ajouté
une ou deux entrées, et le prochain (Léonore, presse suisse) en ajouterait deux de plus.
C'est de l'accrétion : la CLI grandit linéairement avec les sources de données.

Or tous les domaines suivent **le même cycle** : proposer (lecture seule) → relire (humain)
→ appliquer (écriture). Ce cycle est la doctrine du projet — il est appliqué partout dans
le code et nulle part dans la CLI.

Deux preuves que la structure plate ment sur le code :

1. `main.py:527` — `militaires-apply` et `deces-apply` sont dispatchées vers **la même
   fonction**. `deces_apply.py:118` déduit le registre de `prop.preuve_detail`, c'est-à-dire
   du contenu du YAML relu, pas du nom de la commande. Ce sont deux noms pour une commande.
2. Les flags `--scope/--limit/--batch-size/--date` sont redéclarés **10 fois** à l'identique
   dans le bloc parseur. La répétition dans la CLI a une répétition jumelle dans le code.

## Décision

La CLI épouse le cycle. Sept verbes, extensibles sans prolifération.

```
genecrew stats
genecrew propose  {audit | places | deaths | military | gender}   # lecture seule → rapport + YAML
genecrew apply    {case | gender | places | citations | all}      # écrit
genecrew merge    places --yaml <fusions relues>                  # jamais auto
genecrew enrich   wiki                                            # append-only
genecrew import   place "<adresse>"                               # one-shot
genecrew crew     audit                                           # LLM (escalade)
```

Ajouter une base de données devient `propose <base>` — une feuille, zéro verbe. Le YAML
relu qui en sort passe par `apply citations`, qui existe déjà.

### Vocabulaire : tout anglais

La CLI mélangeait `names`/`gender`/`audit` (anglais) et `lieux`/`deces`/`militaires`
(français). On unifie en anglais : verbes **et** compléments. Bénéfice secondaire — plus
aucun mot accentué dans la CLI, donc plus d'hésitation sur `deces` vs `décès`.

Le flag `--sans-images` de `lieux-wiki` devient `--no-images` par la même règle.

### Correspondance complète

16 feuilles → **15**, la disparition étant la fusion démontrée plus haut.

| ancien | nouveau |
|---|---|
| `stats` | `stats` |
| `audit` | `propose audit` |
| `lieux` | `propose places` |
| `deces` | `propose deaths` |
| `militaires` | `propose military` |
| `gender` | `propose gender` |
| `names` | `apply case` |
| `gender-apply` | `apply gender` |
| `lieux-apply` | `apply places` |
| `deces-apply` | `apply citations --yaml` |
| `militaires-apply` | ⟶ **idem** `apply citations --yaml` |
| `apply-all` | `apply all` |
| `lieux-merge` | `merge places --yaml` |
| `lieux-wiki` | `enrich wiki` |
| `lieu-import` | `import place` |
| `crew-audit` | `crew audit` |

### Flags conservés, à l'identique

Aucun flag ne change de sémantique. Deux renommages seulement, imposés par la grammaire :

- `--merges` (sur `lieux-merge`) et `--propositions` (sur `deces-apply` /
  `militaires-apply`) désignent la même chose — le YAML relu par un humain. Tous deux
  deviennent **`--yaml`**, requis.
- `--sans-images` → `--no-images`.

| commande | flags |
|---|---|
| `stats` | — |
| `propose audit` | `--scope --limit --batch-size --date` |
| `propose places` | `--scope --limit --batch-size --min-score --date` |
| `propose deaths` | `--scope --limit --batch-size --min-score --date` |
| `propose military` | `--scope --limit --batch-size --min-score --date` |
| `propose gender` | `--scope --limit --date` |
| `apply case` | `--scope --limit --batch-size --dry-run --date` |
| `apply gender` | `--scope --min-ratio --limit --dry-run --date` |
| `apply places` | `--scope --min-score --limit --batch-size --dry-run --date` |
| `apply citations` | `--yaml` (requis) `--dry-run --date` |
| `apply all` | `--scope --min-ratio --min-score --limit --batch-size --dry-run --date` |
| `merge places` | `--yaml` (requis) `--dry-run --date` |
| `enrich wiki` | `--limit --no-images --dry-run --date` |
| `import place` | `<adresse>` (positionnel) `--min-score --dry-run` |
| `crew audit` | `--scope --limit --batch-size --dry-run --date` |

### `merge places`, et pas `merge`

L'esquisse initiale proposait `merge --yaml` sans complément, la fusion de lieux étant
la seule qui existe. On met le complément dès maintenant : un futur `merge people`
(doublons R7/R8, déjà détectés par l'audit) casserait la grammaire une deuxième fois.

### Coupure nette, pas d'alias

Les 16 anciens noms disparaissent. `genecrew lieux-apply` produit une erreur argparse.

Conséquence assumée : toute commande copiée depuis un ancien rapport ou une ancienne note
échoue. Le risque reste faible — l'échec est bruyant, immédiat, et **n'écrit rien**. Le
tableau de correspondance ci-dessus sert de table de conversion, et l'ADR 0012 le porte.

## Implémentation

Sous-parseurs argparse imbriqués ; dispatch sur le couple `(command, target)`.

**Aucune logique métier n'est touchée.** Les fonctions `*_cmd(args)` et les 20 modules
(`audit.py`, `places_apply.py`, `deces_apply.py`, …) restent identiques. Seules changent
la construction du parseur et la table de dispatch.

Deux améliorations ciblées, dans le code qu'on ouvre de toute façon :

- Le bloc parseur occupe ~140 des 541 lignes de `main.py`. Il part dans un **`cli.py`**
  exposant `build_parser()` — testable directement, sans sous-processus.
- Les flags partagés sont factorisés en `_add_scope_flags(p)` / `_add_write_flags(p)`,
  supprimant les 10 répétitions.

Le point d'entrée `run()` (`crewai run` / `run_crew`, `main.py:29`) délègue à `crew-audit` :
mis à jour vers la nouvelle surface.

## Documentation

**Mis à jour** — documentation vivante :

- `CLAUDE.md` (9 occurrences)
- `README.md` (5)
- `docs/USER_GUIDE.md` (16)
- nouvel **ADR 0012** actant la bascule et portant la table de correspondance

**Volontairement non touchés** — archives datées :
`docs/superpowers/plans/*`, `docs/superpowers/specs/*` (sauf celui-ci),
`.superpowers/sdd/*`, `output/rapports/*`.

Les réécrire ferait croire que `apply places` existait en juillet. Un plan daté décrit ce
qui a été fait à sa date ; c'est l'ADR 0012 qui fait le pont, pas la réécriture du passé.

## Tests

- Les 7 `genecrew/tests/test_cli_*.py` sont adaptés à la nouvelle surface et renommés
  d'après le verbe (`test_cli_propose_places.py`, `test_cli_apply_citations.py`, …).
- Ils appellent `build_parser()` directement plutôt que `subprocess` là où c'est possible —
  plus rapide, et ça teste la construction du parseur, pas l'installation de `uv`.
- **Un test nouveau** vérifie que chacun des 16 anciens noms échoue avec un code de retour
  non nul. La coupure nette devient un comportement testé, pas un effet de bord.
- Un test vérifie que `apply citations` accepte indifféremment un YAML INSEE et un YAML
  Mémoire des hommes — la fusion des deux commandes est vérifiée, pas supposée.

## Ce que ce chantier n'est pas

- Pas de changement de comportement d'écriture. Les garde-fous (`--dry-run`,
  `GENECREW_DRY_RUN`, `effective_dry_run`) sont inchangés.
- Pas de refonte des modules métier.
- Pas de nouvelle source de données. `propose leonore` est ce que la grammaire *permettra* ;
  ce chantier ne l'implémente pas.
