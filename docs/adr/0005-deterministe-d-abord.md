# 0005 — Déterministe d'abord : règles pures avant LLM, orchestration Python hors CrewAI

| | |
|---|---|
| **Statut** | Accepté |
| **Date** | 2026-07-17 |
| **Source** | `docs/document-de-travail.md`, §2 (principe « Déterministe d'abord ») et §6.5 |

## Contexte

L'arbre compte 1 000 à 5 000 personnes (~2 119 personnes réelles), le travail s'étale sur des
mois, et le coût LLM doit rester maîtrisé (§1.3). La détection d'anomalies (R1–R10, doublons),
la résolution de périmètre et le découpage en lots sont des calculs mécaniques : les confier à
un LLM serait à la fois plus coûteux et moins fiable qu'un calcul déterministe.

## Décision

Principe directeur (§2) :

> **Déterministe d'abord** | Ce qui peut être calculé par du code l'est (règles R1–R10,
> doublons, géocodage). Le LLM interprète, priorise, contextualise et rédige — il ne calcule
> pas les anomalies.

Conséquence sur l'orchestration, le batching et les coûts (§6.5) :

> - **Périmètre** (`scope.py`, pur) : `--scope all` (personnes paginées triées par
>   gramps_id), `--scope I0042` (une personne), `--scope branch:I0042 --generations N`
>   (ascendants + descendants via relations/timeline). Tri déterministe → lots de
>   `GENECREW_BATCH_SIZE`.
> - **Checkpoint** : `output/checkpoints/<workflow>_<scope>.json` =
>   `{workflow, scope, batch_size, handles_traites, lot_courant, demarre_le, maj_le}` ; écrit
>   après chaque lot (`@after_kickoff`), lu par `--resume`. Interruption sans perte à tout
>   moment.
> - **Coûts** : le volume passe par les outils déterministes et le cache de la bibliothèque ;
>   mesure tokens/lot en Phase 1 pour extrapoler le coût d'un run complet avant de le lancer ;
>   multi-modèle par agent pour descendre en gamme sur les tâches simples.
> - **Note CrewAI** (API validées dans la doc officielle) : la boucle de lots appelle
>   `crew().kickoff(inputs={…})` une fois par lot dans notre propre boucle Python —
>   `kickoff_for_each` existe mais est écarté car le checkpoint doit être écrit entre deux
>   lots, sous notre contrôle. Le hook `@after_kickoff` (module `crewai.project`) sert à
>   déclencher l'écriture du checkpoint.

## Conséquences

- Les règles R1–R10 (§6.1) et le calcul de candidats doublons sont des fonctions Python pures,
  testées par tables de cas, jamais déléguées à un LLM pour le calcul lui-même — le LLM
  n'intervient qu'en aval pour éliminer les faux positifs évidents, classer par gravité et
  rédiger.
- La boucle de lots (périmètre → découpage → kickoff → checkpoint) est écrite en Python pur
  dans `orchestrator.py`/`scope.py`/`checkpoint.py`, sous le contrôle direct de genecrew — pas
  en `kickoff_for_each` CrewAI, précisément pour pouvoir écrire le checkpoint entre deux lots.
- La collecte de statistiques et de lots par l'orchestrateur ne consomme aucun token LLM
  (appel direct au client Gramps, §3.3) ; seule l'interprétation par les agents consomme des
  tokens, mesurés par lot dès la Phase 1 pour extrapoler le coût avant un run complet.
