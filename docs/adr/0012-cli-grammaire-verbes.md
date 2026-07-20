# ADR 0012 — Grammaire de verbes pour la CLI (coupure nette, sans alias)

Date : 2026-07-19 — Statut : accepté

## Contexte

`genecrew` exposait 16 sous-commandes plates : `stats`, `audit`, `names`, `gender`,
`gender-apply`, `apply-all`, `lieux`, `lieux-apply`, `lieux-merge`, `lieux-wiki`,
`lieu-import`, `deces`, `deces-apply`, `militaires`, `militaires-apply`, `crew-audit` —
dont 5 déclinaisons du seul domaine des lieux (`lieux`, `lieux-apply`, `lieux-merge`,
`lieux-wiki`, `lieu-import`). Le nom encodait l'outil — le domaine de données — pas le
geste qu'on pose dessus. Chaque nouvelle source (décès INSEE, militaires Mémoire des
hommes, enrichissement wiki, import ponctuel) a ajouté une ou deux entrées à plat au
même niveau que `stats` ; le prochain chantier (Léonore, presse suisse) en aurait
ajouté deux de plus. C'est de l'accrétion : la CLI grandit linéairement avec les
sources de données, jamais avec les gestes qu'on pose dessus.

Or tous les domaines suivent le même cycle, déjà la doctrine du projet ailleurs dans le
code (ADR 0001 : écriture directe encadrée uniquement sur la forme ; ADR 0005 :
déterministe d'abord) : **proposer** (lecture seule) → **relire** (humain) →
**appliquer** (écriture). Ce cycle était appliqué partout dans le code et nulle part
dans la structure de la CLI.

Deux preuves que la surface plate mentait sur le code :

1. `deces-apply` et `militaires-apply` dispatchaient vers **la même fonction**.
   `deces_apply.py:118` déduit le registre de la source (INSEE, Mémoire des hommes,
   presse Gallica) depuis `prop.preuve_detail` — le contenu du YAML relu par l'humain —
   jamais du nom de la commande invoquée. Deux noms de commande pour un seul moteur : le
   nom prétendait une distinction que le code n'a jamais faite.
2. Les flags `--scope`, `--limit`, `--batch-size`, `--date` étaient redéclarés **10
   fois**, à l'identique, dans le bloc parseur de l'ancien `main.py`. La répétition dans
   la CLI avait une répétition jumelle dans le code : chaque nouvelle commande recopiait
   le même bloc `add_argument` plutôt que de partager une déclaration.

## Décision

La CLI épouse le cycle plutôt que les sources de données. Sept verbes, extensibles sans
prolifération de mots de tête :

```
genecrew stats
genecrew propose  {audit | places | deaths | military | gender}   # lecture seule → rapport + YAML
genecrew apply    {case | gender | places | citations | all}      # écrit
genecrew merge    places --yaml <fusions relues>                  # jamais auto
genecrew enrich   wiki                                            # append-only
genecrew import   place "<adresse>"                               # one-shot
genecrew crew     audit                                           # LLM (escalade)
```

Ajouter une base de données devient `propose <base>` — une feuille de plus sous un verbe
existant, jamais un nouveau mot de tête. Le YAML relu qui sort d'un `propose` passe par
`apply citations`, qui existe déjà : une nouvelle source de registre n'ouvre pas de
nouvelle porte d'écriture.

Le cycle « proposer → relire → appliquer » ci-dessus décrit la doctrine, mais seules 2
des 5 feuilles d'`apply` la suivent à la lettre en consommant le YAML qu'un humain a
relu : `apply citations` et `merge places`, marquées `--yaml` dans la grammaire. Les
trois autres — `apply case`, `apply gender`, `apply places` (et `apply all`, qui les
enchaîne) — recalculent en direct depuis Gramps et ne lisent jamais ce que le `propose`
correspondant a produit ; c'est délibéré (ADR 0001 : la forme s'écrit directement, sans
relecture ; ADR 0009 : le genre à haute confiance aussi), pas un oubli de ce chantier.
L'absence de `--yaml` sur une feuille d'`apply` est déjà le marqueur de cette deuxième
famille.

Vocabulaire unifié en anglais, verbes et compléments — la CLI mélangeait `names`/
`gender`/`audit` (anglais) et `lieux`/`deces`/`militaires` (français). `--sans-images`
devient `--no-images` par la même règle : plus aucun mot accentué ne subsiste dans la
grammaire de la CLI.

### Table de correspondance complète

16 anciens noms plats → **15 feuilles** dans la nouvelle grammaire. `stats` ne change
pas de nom (il s'appelait `stats`, il s'appelle toujours `stats`) : ce sont donc **15
noms qui disparaissent**, pas 16. La seule vraie disparition — au sens d'une fusion,
pas d'un simple renommage — est celle de `deces-apply`/`militaires-apply` en
`apply citations` (2 → 1), justifiée ci-dessus par `deces_apply.py:118`.

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

Deux flags renommés par la grammaire, aucune sémantique changée : `--merges` (sur
`lieux-merge`) et `--propositions` (sur `deces-apply`/`militaires-apply`) désignaient
déjà la même chose — le YAML relu par un humain — et deviennent tous deux **`--yaml`**,
requis. `--sans-images` (sur `lieux-wiki`) devient `--no-images` (sur `enrich wiki`).

### Implémentation

Sous-parseurs argparse imbriqués dans `genecrew/src/genecrew/cli.py` (`build_parser()`),
dispatch sur le couple `(command, target)`. **Aucune logique métier n'est touchée** : les
**14 fonctions `*_cmd(args)`** de `main.py` — et les modules qu'elles appellent
(`audit.py`, `places_apply.py`, `deces_apply.py`, …) — restent identiques ; seules
changent la construction du parseur et la table de dispatch. Les flags partagés sont
désormais factorisés (`_add_scope`, `_add_batch`, `_add_min_score`, `_add_dry_run`,
`_add_date`, `_add_yaml`), supprimant les 10 répétitions relevées ci-dessus.

### Coupure nette, pas d'alias

`stats` mis à part, les 15 autres anciens noms disparaissent sans alias. `genecrew
lieux-apply` produit une erreur argparse immédiate. Conséquence assumée : toute
commande copiée depuis un ancien rapport ou une ancienne note échoue. Le risque reste
faible et délibérément accepté — l'échec est bruyant, immédiat, et **n'écrit rien**
(argparse rejette avant tout appel à Gramps) ; le tableau ci-dessus sert de table de
conversion, et c'est le rôle de cet ADR de la porter.

## Hors périmètre

Pas de changement de comportement d'écriture : les garde-fous (`--dry-run`,
`GENECREW_DRY_RUN`, `effective_dry_run`) sont inchangés. Pas de refonte des modules
métier — seule la couche CLI bouge. Pas de nouvelle source de données : `propose
leonore` est ce que la grammaire *permettra*, ce chantier ne l'implémente pas.

## Conséquences

La CLI grandit désormais avec les verbes, pas avec les sources : une nouvelle base de
données ajoute une feuille sous `propose` (et, le cas échéant, sous `apply`), jamais un
nouveau mot de tête. La documentation vivante (`CLAUDE.md`, `README.md`,
`docs/USER_GUIDE.md`) est mise à jour vers la nouvelle grammaire par ce même chantier.
Les archives datées — `docs/superpowers/plans/*`, `docs/superpowers/specs/*` (sauf le
spec de ce chantier, corrigé sur ses seuls chiffres imprécis), `.superpowers/sdd/*`,
`output/*` — ne sont **pas** réécrites : elles décrivent ce qui était vrai à leur date,
et c'est cet ADR qui fait le pont entre l'ancienne et la nouvelle surface.
