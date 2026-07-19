# Changelog — genecrew

Projet applicatif (CLI + orchestration) qui consomme la bibliothèque `crewai_custom_tools`.
Non publié / non versionné (`0.1.0`) : entrées **datées par livraison**. La logique généalogie
(client Gramps, règles, inférence, outils d'écriture) vit dans `crewai_custom_tools` — voir son
`CHANGELOG.md` ; ici on documente la CLI, l'orchestration et la structure du projet.

---

## 2026-07-19

### Changed

- **Aplatissement du layout** : projet unique à la racine. Les métadonnées (`.env`, `.env.example`,
  `.gitignore`, `README.md`, `pyproject.toml`, `uv.lock`) vivent **à la racine** ; le code CrewAI
  garde son layout standard sous `genecrew/src/genecrew/` (avec `genecrew/tests/` et
  `genecrew/knowledge/`). Suppression du workspace uv à deux niveaux ; `pyproject.toml` pointe
  hatchling vers le paquet via `[tool.hatch.build.targets.wheel] packages = ["genecrew/src/genecrew"]`
  et corrige le chemin de la dépendance éditable (`../crewai_custom_tools`). **Les commandes se
  lancent désormais depuis la racine** (plus de `cd genecrew`).

### Added

- `docs/BACKLOG.md` — idées d'amélioration différées (progression/logs des runs longs, borner
  `gender` en `Literal`, liens `base_url`, types `Literal` sur `Proposition`, retry 429…).

### Fixed

- **Dry-run sûr et honnête** (double correctif). (1) La ligne « Mode » des rapports (casse et
  genre) reflète désormais le dry-run **effectif** — override `GENECREW_DRY_RUN` inclus, plus
  seulement le flag CLI `--dry-run` : un run ne peut plus annoncer « écritures appliquées » alors
  que rien n'est écrit. (2) Défaut **sûr** : quand `GENECREW_DRY_RUN` est *absente*, on **simule**
  (helper `effective_dry_run` côté `crewai_custom_tools` 0.11.1) au lieu d'écrire. Mettre
  `GENECREW_DRY_RUN=false` pour écrire pour de vrai.

## 2026-07-18

### Added

- **`apply-all`** — commande parapluie : applique la casse des noms puis les genres à haute
  confiance en un passage (`run_names` + `run_gender_apply`), garde-fous partagés.
- **`gender-apply`** — écrit les corrections de genre à haute confiance (re-inférence live sur un
  périmètre, `ratio ≥ 0.98`, genres inconnus remplis + contradictions corrigées), réversible,
  gated par le double interrupteur dry-run. ADR 0009.
- **`gender`** — inférence de genre en **lecture seule** : propositions (rapport Markdown + YAML)
  à partir de la table prénom→sexe INSEE+OFS. ADR 0008. Modèle `Proposition`.
- **`names`** — standardisateur de la **casse** des noms (premier writer, écriture directe encadrée
  par invariant casse-seulement). ADR 0007 (+ raffinement de l'ADR 0001, forme vs fait).

## 2026-07-17

### Added

- **Phase 1a** — audit déterministe (`audit`) : règles de cohérence R1–R10 + complétude D1–D3,
  rapport Markdown, aucun LLM. `facts.py`/`scope.py`/`report.py`/`batching.py`/`audit.py`. ADR 0006.
- **Phase 0** — plomberie : client Gramps en lecture seule, CLI `stats`, dépendance éditable à
  `crewai_custom_tools`, spec-first (OpenAPI vendorées dans `docs/swagger/`). ADR 0001–0005.
