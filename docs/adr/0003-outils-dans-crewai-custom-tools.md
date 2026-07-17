# 0003 — Les outils vivent dans `crewai_custom_tools`, genecrew est un simple consommateur

| | |
|---|---|
| **Statut** | Accepté |
| **Date** | 2026-07-17 |
| **Source** | `docs/document-de-travail.md`, §3.2–3.4 |

## Contexte

`crewai_custom_tools` est une bibliothèque frère existante, avec sa propre infrastructure
d'outils (schémas, retry, cache, tests). GeneCrew doit décider où vit la logique d'accès aux
API (Gramps + API externes françaises/suisses) : directement dans le dépôt `genecrew`, ou dans
cette bibliothèque partagée.

## Décision

> - **genecrew** : orchestration, personas, tâches, CLI, rapports finaux. Aucune logique
>   d'accès API.
> - **crewai_custom_tools** : 100 % des outils (Gramps + externes + analyse), avec l'infra
>   existante de la bibliothèque : `BaseTool` + `args_schema` Pydantic + décorateur
>   `@api_tool(provider, endpoint, timeout)` (timeout, retry 429, rate-limit) + enveloppe
>   `ok()/err()` + cache SHA-256 mémoire+disque + tests pytest mockés hors-ligne.
> - **Gramps Web** : source de vérité unique. Accès en REST direct (httpx). Le dépôt
>   `gramps-mcp` n'est **pas** utilisé à l'exécution ; il sert de spécification de référence
>   (auth `auth.py`/`client.py`, catalogue `models/api_calls.py`, schémas
>   `models/parameters/`).

(document-de-travail.md, §3.2)

Cette répartition est cohérente avec le principe DRY du document de travail (§2) : « Toute
logique d'accès API vit dans `crewai_custom_tools` (réutilisable au-delà de genecrew) ; un seul
client Gramps ; un seul `agents.yaml` ; l'état qualité vit dans Gramps (tags), jamais
dupliqué. »

Intégration des deux dépôts frères (§3.4) :

> Les deux dépôts sont frères sous `/Users/fjacquet/Projects/`. Dans le `pyproject.toml`
> **racine** de genecrew :
>
> ```toml
> [project]
> dependencies = ["crewai>=1.15.2", "crewai-custom-tools"]
>
> [tool.uv.sources]
> crewai-custom-tools = { path = "../../crewai_custom_tools", editable = true }
> ```

## Conséquences

- Tous les nouveaux outils Gramps, outils d'analyse purs (R1–R10, doublons) et outils d'API
  externes sont ajoutés dans `crewai_custom_tools/src/crewai_custom_tools/tools/genealogy/`,
  jamais dans `genecrew/src/genecrew/`.
- `genecrew` déclare `crewai-custom-tools` comme dépendance éditable vers le dépôt frère — toute
  modification d'outil se fait dans la bibliothèque, pas dans genecrew.
- Le scaffold initial (`crewai create crew`, agents `researcher`/`reporting_analyst`, tâches
  `{topic}`) sera entièrement remplacé par la structure cible décrite en §3.5 du document de
  travail, sans que genecrew n'accumule de logique d'accès API en cours de route.
