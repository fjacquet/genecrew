# Changelog — genecrew

Projet applicatif (CLI + orchestration) qui consomme la bibliothèque `crewai_custom_tools`.
Non publié / non versionné (`0.1.0`) : entrées **datées par livraison**. La logique généalogie
(client Gramps, règles, inférence, outils d'écriture) vit dans `crewai_custom_tools` — voir son
`CHANGELOG.md` ; ici on documente la CLI, l'orchestration et la structure du projet.

---

## 2026-07-21

### Added

- **Fusion des doublons de personnes en API** — nouvelle feuille CLI `merge people` (pas de verbe
  neuf : la grammaire de l'ADR 0012 tient). Objectif : quand un doublon est prouvé, la fusion se
  fait par l'API Gramps, plus à la main dans l'interface.
  - `people_merge.py` — le **seul** code réseau du chantier : détecte les doublons (via la
    bibliothèque), exécute l'étage **auto**, dépose le reste dans un **YAML relu**, et boucle
    jusqu'à convergence — la déduplication est transitive : fusionner des parents dupliqués
    débloque la règle « mêmes parents » à la passe suivante.
  - `merge people --scope … --limit … --yaml … --max-passes … --dry-run` : détection+fusion, ou
    exécution d'un YAML d'arbitrage relu.

### Changed

- **Amendement borné de la règle fondatrice** (`document-de-travail.md`). L'interdiction « toute
  fusion reste en proposition pour revue humaine » est levée **uniquement** pour la fusion de
  personnes adossée à une **preuve structurelle vérifiable** (date de naissance exacte identique
  + mêmes parents ; ou date exacte identique seule ; ou conjoint + enfant commun). Aucun seuil
  numérique ; toute preuve partielle repasse par un YAML relu ; suppression et autres fusions
  restent interdites aux agents. La garantie d'isolation est reformulée : l'outil de fusion existe
  désormais dans la bibliothèque mais **n'est câblé à aucun agent** — il n'est appelé que par
  l'orchestration déterministe.

### Notes

- Une fusion est **irréversible** (le titanic est supprimé). Filet : le patch de genre précède la
  fusion et son échec — ou une contradiction de genres entre titanics — **abandonne** la grappe ;
  le chemin YAML relu préserve le genre au même titre que l'auto ; le dry-run **effectif**
  (`GENECREW_DRY_RUN` inclus) gouverne boucle, exécution et rapport ; le rapport liste chaque
  fusion « Gardé | Supprimé » nominativement.
- Consomme `crewai_custom_tools` **0.22.0** (voir son `CHANGELOG.md`).

## 2026-07-20

### Changed

- **⚠ La CLI passe de 16 sous-commandes plates à 7 verbes — changement cassant, sans alias.**
  Le nom encodait l'outil, pas le geste, et chaque nouveau domaine ajoutait une entrée : la
  surface grandissait linéairement avec les sources de données. Tous les domaines suivent
  pourtant le même cycle — proposer (lecture seule) → relire (humain) → appliquer (écriture) —
  appliqué partout dans le code et nulle part dans la CLI. La nouvelle grammaire :
  `stats`, `propose {audit|places|deaths|military|gender}`,
  `apply {case|gender|places|citations|all}`, `merge places`, `enrich wiki`, `import place`,
  `crew audit`. Ajouter une base devient une feuille sous `propose`, jamais un verbe.
  `deces-apply` et `militaires-apply` **fusionnent** en `apply citations` : elles pointaient
  déjà sur la même fonction, le registre étant déduit du YAML relu et non du nom de la
  commande. `stats` est le seul nom inchangé ; les 15 autres disparaissent — l'échec est
  bruyant, immédiat, et n'écrit rien. Deux flags renommés : `--merges`/`--propositions` →
  `--yaml`, `--sans-images` → `--no-images`. Le parseur sort de `main.py` dans un `cli.py`
  testable (`build_parser()`), et les flags partagés — redéclarés 10 fois à l'identique —
  sont factorisés. **Table de correspondance complète dans l'ADR 0012.**

### Added

- **CI sur chaque PR** (`.github/workflows/ci.yml`). `crewai-custom-tools` n'étant pas sur PyPI
  et `uv.lock` verrouillant le chemin relatif `../crewai_custom_tools`, le runner clone les
  **deux dépôts côte à côte** — ni `pyproject.toml` ni `uv.lock` n'ont eu à changer. Le clone du
  voisin est **épinglé sur le tag `v<version du lock>`**, donc une PR verte le reste. Une
  sentinelle non bloquante compare en parallèle le lock au `main` du voisin et émet un
  avertissement s'il a avancé : on garde la visibilité de la dérive sans qu'elle rougisse une PR
  qui n'y est pour rien. Jobs bloquants : `tests et lint`, `construction de la doc`. Job
  `sécurité` **informatif** (semgrep, rulesets explicites sans télémétrie) tant que les alertes
  Dependabot préexistantes ne sont pas traitées — ses constats partent en SARIF vers l'onglet
  Security, pour qu'un job vert ne puisse pas taire une détection.
- **Documentation publiée sur GitHub Pages** — <https://fjacquet.github.io/genecrew/>
  (`.github/workflows/docs.yml`, `mkdocs.yml`, `scripts/build-docs.sh`). MkDocs Material, en
  français. Sont publiés le README (page d'accueil), le guide, le PRD, le backlog et les 12 ADR.
  Sont **exclus** les plans et specs datés (`docs/superpowers/`), le document de travail et les
  specs d'API : un plan daté décrit ce qui était vrai à sa date, le publier comme documentation
  courante induirait en erreur. Le build tourne aussi en PR, bloquant, pour qu'un lien cassé
  soit arrêté avant merge et non découvert par un déploiement silencieusement raté.
- `test_cmd_bodies.py` — aucun test n'exécutait le corps des fonctions `*_cmd`, là où vivent
  précisément les lectures d'attributs renommées. Une faute de frappe y passait les 152 tests et
  échouait au premier vrai run.

### Fixed

- **`apply citations` n'attribue plus à l'INSEE un registre qu'il ne connaît pas.**
  `source_title_for` reconnaissait Mémoire des hommes et Gallica, puis **retombait
  silencieusement sur INSEE**. En ajoutant une base (Léonore, presse suisse), chaque citation
  aurait été écrite dans Gramps attribuée à tort à l'INSEE — sur un chemin d'écriture, sans
  bruit. Chaque registre est désormais détecté **positivement** et un `preuve_detail` non
  reconnu lève.
- **`enrich wiki` : `--limit` borne enfin le trafic, et les échecs d'image ne sont plus avalés.**
  La pagination lisait l'arbre entier avant d'appliquer la borne. Et lorsqu'un import ou un
  attachement d'image échouait, la boucle passait au suivant sans rien consigner : lien posé,
  image perdue, rapport muet. Les deux échecs alimentent maintenant la section « Erreurs ».
  Corrigé aussi `dist == 0` traité comme une distance manquante (`0 or 1e9` vaut `1e9`) —
  sans effet observable aujourd'hui, la garde d'ambiguïté masquant le cas, mais le piège
  mordrait si le seuil bougeait.
- **Documentation qui sous-décrivait des écritures** : `apply all` était présenté comme
  « casse puis genre » alors qu'il écrit aussi les lieux (le volet décès, lui, ne fait que
  proposer) ; `CLAUDE.md` rangeait `facts.py` parmi les modules genecrew alors qu'il vit dans
  `crewai_custom_tools`.

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

- **Standardisateur de lieux** — trois commandes. `lieux` (lecture seule) parse les lieux importés à plat, les résout via une **chaîne de résolveurs routée par pays** (FR = code INSEE → `geo.api.gouv.fr` ; CH = swisstopo ; monde = Nominatim/OSM), et émet des propositions (rapport Markdown + YAML). `lieux-apply` **écrit** la hiérarchie (`Pays > Région > Département > Commune`, parents créés une fois — idempotent) + les coordonnées WGS84 au-dessus d'un score (`--min-score`, défaut 0.90), et **propose** les fusions de doublons sans les exécuter. `lieux-merge` exécute ces fusions depuis un YAML **relu par un humain** (jamais automatique). Nom moderne canonique en principal + nom d'époque daté en variante ; transitions temporelles (changements de souveraineté) pilotées par données. La logique généalogie vit dans `crewai_custom_tools` 0.12.0. Voir ADR 0010.
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
