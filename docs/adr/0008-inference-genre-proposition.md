# 0008 — Inférence de genre : proposition, pas écriture

## Statut
Accepté — 2026-07-18

## Contexte
Des personnes ont un genre inconnu (`gender=2`). On peut l'inférer depuis le
prénom via un dictionnaire prénom→sexe souverain (INSEE + OFS). Le genre est un
**fait** (ADR 0001, forme-vs-fait), pas une forme.

## Décision
L'inférence de genre est **lecture seule** : chaque cas devient une `Proposition`
pour revue humaine (rapport Markdown + YAML), jamais une écriture Gramps. Premier
émetteur du modèle `Proposition`, réutilisé par les futurs chantiers. Politique
conservatrice : proposer seulement si le sexe dominant ≥ 95 % sur ≥ 50 naissances.
Périmètre : genres inconnus (proposition F/M) **et** contradictions genre/prénom
(à vérifier).

## Conséquences
- Aucun outil d'écriture n'est ajouté ; la garantie lecture seule est testée.
- Le futur « apply » (relecture du YAML validé → écriture) est un chantier séparé.
- Les prénoms hors couverture INSEE/OFS restent en abstention (indécidables).
