# 0002 — Accès Gramps via REST direct (httpx), gramps-mcp en référence uniquement

| | |
| --- | --- |
| **Statut** | Accepté |
| **Date** | 2026-07-17 |
| **Source** | `docs/document-de-travail.md`, §3.2 |

## Contexte

Un serveur MCP existant, `gramps-mcp`, expose déjà l'API Gramps Web sous forme d'outils MCP
(~16 outils, authentification JWT, catalogue d'appels). GeneCrew doit décider comment ses
propres agents CrewAI accèdent à Gramps Web : en passant par ce serveur MCP, ou en implémentant
son propre accès REST.

## Décision

> **Gramps Web** : source de vérité unique. Accès en REST direct (httpx). Le dépôt
> `gramps-mcp` n'est **pas** utilisé à l'exécution ; il sert de spécification de référence
> (auth `auth.py`/`client.py`, catalogue `models/api_calls.py`, schémas
> `models/parameters/`).

(document-de-travail.md, §3.2)

Le modèle d'authentification JWT est repris du même dépôt à titre de référence éprouvée :

> `POST {GRAMPS_API_URL}/token/` avec `{"username": …, "password": …}` → `access_token` envoyé
> en `Authorization: Bearer …`. Rafraîchissement automatique à expiration et sur HTTP 401 (un
> seul retry). Modèle éprouvé : `gramps-mcp/src/gramps_mcp/auth.py` et `client.py`.

(document-de-travail.md, §4.1)

## Conséquences

- `genealogy/gramps/client.py` (dans `crewai_custom_tools`) est un module Python pur (httpx +
  JWT auto-refresh) — il ne dépend à l'exécution d'aucun serveur MCP tiers, ni d'un processus
  `gramps-mcp` démarré.
- `gramps-mcp` reste utile comme documentation vivante (patron d'authentification, catalogue
  d'endpoints, schémas de paramètres compacts servant de base aux `args_schema`), mais
  genecrew n'a pas de dépendance d'exécution vers ce dépôt ni vers un serveur MCP Gramps.
- Deux consommateurs distincts du client (document-de-travail.md, §3.3) : l'orchestrateur
  genecrew directement (sans LLM, pour la collecte déterministe et les statistiques), et les
  outils CrewAI (enveloppes `BaseTool` fines, une opération par outil).
