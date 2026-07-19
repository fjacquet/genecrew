# 0010 — Écriture de la hiérarchie des lieux (relâche bornée « lieu = proposition »)

| | |
| --- | --- |
| **Statut** | Accepté |
| **Date** | 2026-07-19 |
| **Source** | `docs/superpowers/specs/2026-07-19-standardisateur-lieux-design.md` |

## Contexte

L'ADR 0001 pose : une donnée cœur (dont le lieu) → proposition, jamais d'écriture directe. Or les
lieux importés à plat (GEDCOM) ont perdu le modèle natif Gramps (Place typé, PlaceName, placeref
hiérarchiques datés, lat/long) ; le Standardisateur doit le **reconstruire**. La résolution par code
INSEE/OFS est autoritaire (une commune unique, source officielle) ; le géocodage par nom porte un
score de confiance ; Gramps trace et sait annuler ses transactions.

## Décision

`lieux-apply` peut **écrire** en automatique, au-dessus de `min_score` (défaut 0.90) :
l'enrichissement d'un lieu (nom canonique moderne, type, GPS WGS84, code, alt-names datés) et la
**création/réutilisation de lieux parents** avec placerefs (la hiérarchie). Score autoritaire (code
INSEE/OFS) = 1.0 ; appariement flou géocodé écrit ≥ seuil, sinon proposition. La **fusion de feuilles
existantes** (qui déplace des backlinks d'événements) reste une **proposition** : jamais automatique,
exécutée seulement par `lieux-merge` sur un YAML relu par un humain. Déterministe, gated par le double
interrupteur dry-run, réversible via l'historique des transactions Gramps.

## Conséquences

- L'ADR 0001 reste la règle par défaut ; 0010 est l'exception encadrée aux lieux (dans l'esprit de
  l'ADR 0009 pour le genre).
- Idempotent : relancer ne duplique pas les parents (index par chemin) et n'écrit pas un lieu déjà
  conforme (no-op).
- Limite assumée : un appariement flou à haut score peut écrire un lieu erroné ; l'utilisateur relit
  le rapport (dry-run recommandé d'abord). Le géocodage contourne encore le cache/rate-limiter de
  `crewai_custom_tools` (suivi noté).
