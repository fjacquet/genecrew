# GeneCrew

[![CI](https://github.com/fjacquet/genecrew/actions/workflows/ci.yml/badge.svg)](https://github.com/fjacquet/genecrew/actions/workflows/ci.yml)
[![Documentation](https://github.com/fjacquet/genecrew/actions/workflows/docs.yml/badge.svg)](https://fjacquet.github.io/genecrew/)

![Python](https://img.shields.io/badge/python-3.11%20–%203.12-3776AB?logo=python&logoColor=white)
![CrewAI](https://img.shields.io/badge/built%20with-CrewAI-FF5A50)
![uv](https://img.shields.io/badge/packaging-uv-DE5FE9?logo=uv&logoColor=white)
![Gramps Web](https://img.shields.io/badge/backend-Gramps%20Web%20API-4B8BBE)
![statut](https://img.shields.io/badge/statut-en%20développement-orange)

Équipe d'agents (et d'outils déterministes) pour la **généalogie**, travaillant sur un arbre
**Gramps Web**. Quatre buts : **nettoyer** les données, **standardiser** (noms, genres ; à venir :
lieux/dates), **trouver des pistes** de recherche, et ne conserver que des **données fiables et
vérifiées**. La généalogie est une discipline de preuve — *« c'est un devoir de mémoire »*.

> **Principe directeur : déterministe d'abord.** Les corrections mécaniques et vérifiables (casse,
> genre à haute confiance) sont faites par des **outils déterministes** — reproductibles, testables,
> sûrs sur la donnée cœur. Le LLM (crew CrewAI) est réservé aux tâches de **jugement et de langage**
> (interpréter les anomalies, chercher des pistes, rédiger) — chantier ultérieur.

## Architecture

- **`genecrew`** (ce dépôt) — CLI argparse + orchestration Python. Le paquet CrewAI garde son layout
  standard sous `genecrew/src/genecrew/` ; les métadonnées sont à la racine.
- **[`crewai_custom_tools`](../crewai_custom_tools)** (dépôt frère, dépendance éditable) — toute la
  **logique généalogie** : client Gramps (httpx + JWT), modèles, règles d'audit R1–R10 + D1–D3,
  inférence de genre (table INSEE+OFS), outils d'écriture (casse, genre, lieux, citations de
  registres).
- **Gramps Web** — le backend de données, en **REST direct** (pas via un serveur MCP). Non provisionné
  ici (voir le projet frère `gramps-mcp`).

## Installation

Prérequis : [`uv`](https://docs.astral.sh/uv/), le dépôt frère `crewai_custom_tools` cloné à côté,
une instance Gramps Web accessible, et un `.env` (copier `.env.example`).

```bash
uv sync                       # installe le projet + la lib éditable
cp .env.example .env          # puis renseigner GRAMPS_* et GENECREW_*
```

Voir **[`docs/USER_GUIDE.md`](https://github.com/fjacquet/genecrew/blob/main/docs/USER_GUIDE.md)** pour la mise en route complète (démarrage de
Gramps Web via `gramps-mcp`, `GRAMPS_API_URL`, etc.).

## Utilisation

Tout se lance **depuis la racine** :

```bash
uv run genecrew stats                             # tableau de bord de l'arbre (Phase 0)
uv run genecrew propose audit --scope all --limit 200     # audit déterministe, lecture seule (R1–R10, D1–D3)
uv run genecrew apply case --dry-run              # standardiser la casse des noms (écriture encadrée)
uv run genecrew propose gender --scope all --limit 200    # inférer le genre — propositions, lecture seule
uv run genecrew apply gender --dry-run            # écrire les corrections de genre à haute confiance
uv run genecrew apply all --dry-run               # casse, genre, lieux : écrit ; décès : proposition
```

**Sécurité des écritures** : toute écriture est encadrée par le flag `--dry-run` **et** l'interrupteur
global `GENECREW_DRY_RUN` (dans `.env`) — tant qu'il vaut `true`, tout est **simulé**. Principe
**forme vs fait** : la casse est une *forme* (écriture directe, invariant casse-seulement) ; un *fait*
(genre, dates…) n'est écrit qu'à haute confiance et de façon réversible (historique Gramps).

## Documentation

- [`docs/USER_GUIDE.md`](https://github.com/fjacquet/genecrew/blob/main/docs/USER_GUIDE.md) — guide d'utilisation, phase par phase.
- [`docs/document-de-travail.md`](https://github.com/fjacquet/genecrew/blob/main/docs/document-de-travail.md) — spécification / document de travail.
- [`docs/adr/`](https://github.com/fjacquet/genecrew/tree/main/docs/adr/) — décisions d'architecture (ADR 0001–0012).
- [`CHANGELOG.md`](https://github.com/fjacquet/genecrew/blob/main/CHANGELOG.md) — journal des livraisons · [`docs/BACKLOG.md`](https://github.com/fjacquet/genecrew/blob/main/docs/BACKLOG.md) — idées différées.

## Tests

```bash
uv run python -m pytest genecrew/tests/ -q        # suite genecrew (mockée, hors-ligne)
uv run ruff check .
```

La bibliothèque `crewai_custom_tools` a sa propre suite (100 % hors-ligne).
