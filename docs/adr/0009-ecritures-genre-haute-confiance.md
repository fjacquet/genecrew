# 0009 — Écritures de genre bornées à haute confiance

| | |
| --- | --- |
| **Statut** | Accepté |
| **Date** | 2026-07-18 |
| **Source** | `docs/superpowers/specs/2026-07-18-gender-apply-design.md` |

## Contexte

L'ADR 0008 pose : le genre est un *fait* → proposition, jamais d'écriture directe. Sur l'arbre
réel, l'inférence révèle une erreur d'import systématique (des « Philippe » marqués F). La table
prénom→sexe souveraine **INSEE+OFS** (~85 500 prénoms) rend la confiance mesurable et a supprimé
les faux positifs franco-suisses connus au niveau donnée (« Ami », « Marie-Joseph » abstiennent).

## Décision

`gender-apply` peut **écrire** le genre en direct, en automatique, **au-dessus de `min_ratio`
(défaut 0.98)** sur la table INSEE+OFS (le `≥ 50` de base d'`infer_sex` s'applique aussi). Périmètre :
genres inconnus remplis + contradictions corrigées. Déterministe (pas d'agent LLM), gated par le
double interrupteur dry-run (`GENECREW_DRY_RUN` par défaut = simulation), **réversible** via
l'historique des transactions Gramps. `GrampsUpdateGenderTool` est un `BaseTool` réutilisable.

## Conséquences

- L'ADR 0008 reste la règle par défaut (fait → proposition) ; 0009 est l'exception encadrée au genre.
- Limite résiduelle assumée : un prénom rare/étranger à fort ratio et faible volume (≥ 50) peut être
  écrit à tort ; l'utilisateur relit le rapport (dry-run recommandé d'abord).
- Les autres faits (dates, relations) restent en propositions.
