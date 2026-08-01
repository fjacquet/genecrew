# CLAUDE.md

Guide for Claude Code (claude.ai/code) working in this repo.

## Repository layout

Single `uv`/CrewAI project, repo root. Project metadata **at root**
(`pyproject.toml`, `uv.lock`, `.venv/`, `.env`, `.env.example`, `.gitignore`, `README.md`);
CrewAI package standard layout under `genecrew/src/genecrew/` (plus `genecrew/tests/`,
`genecrew/knowledge/`). Code under `genecrew/src/` (CrewAI convention), config at root —
`pyproject.toml` points hatchling at package via
`[tool.hatch.build.targets.wheel] packages = ["genecrew/src/genecrew"]`. Run everything from
repo root (no more `cd genecrew`).

Crew logic changes: inside `genecrew/src/genecrew/`.

### CrewAI project structure (`genecrew/src/genecrew/`)

- `crew.py` — real audit crew (`@CrewBase Genecrew`, `Process.sequential`, 4 agents): `detective` (judges), then `historien` (external proof: MatchID/Gallica/Wikidata), then `standardisateur` (precise propositions, strict JSON validated by `PropositionsLot`, confidence ≤ 2), then `chroniqueur` (**only** writer, append-only note/tag tools). Write isolation structural. LLM per role via `build_llm(role)` (`MODEL_<ROLE>` env, fallback `MODEL`), **always `is_litellm=True`** — CrewAI native provider hardcodes `"strict": true` on tool schemas, Mistral rejects that.
- `config/agents.yaml` — `detective`/`chroniqueur` personas (French, static).
- `config/tasks/audit.yaml` — `interpreter_anomalies` (Détective) → `rediger_annotations` (Chroniqueur), templated with `{anomalies_block}` and `{date}`. (`crew.py` sets `tasks_config` to this path; the stock `config/tasks.yaml` was deleted.)
- `cli.py` — `build_parser()`, CLI's verb grammar: `stats`, `propose {audit|places|deaths|military|gender|wikidata|dhs}`, `apply {case|gender|places|citations|deaths|all}`, `merge {places|people}`, `enrich wiki`, `import {place|releve}`, `crew audit`. Pure — reads environment only, for flag defaults. See `docs/adr/0012-cli-grammaire-verbes.md`.
- `main.py` — CLI dispatcher (`main()` calls `cli.build_parser()`, routes on `(command, target)` pair) **and** CrewAI console entry points (`run`/`train`/`test`/`replay`). `run` delegates to bounded dry-run `crew audit`. Sets up durable logging around every command.
- `tools/custom_tool.py` — placeholder `BaseTool` subclass template, adding custom CrewAI tools.
- `knowledge/user_preference.txt` — static knowledge file (placeholder content), available to crew via CrewAI knowledge sources.

**Current state**: two layers ship together. (1) Deterministic argparse CLI in `main.py`, 7-verb grammar above: `stats` (Phase 0), `propose audit` (read-only R1–R10/D1–D3), `apply case` (casing), `propose gender`/`apply gender` (ADR 0009), `apply all`, `propose places`/`apply places`/`merge places` (place standardizer). (2) **Real LLM crew** (`crew audit`): 2-agent Détective→Chroniqueur audit workflow, interprets deterministic anomalies, writes **encadré** append-only note/tag annotations (marker `[genecrew:audit:<date>:detective]`), dry-run default. Genealogy logic lives in sibling `crewai_custom_tools`; genecrew holds orchestration/CLI only.

## Where the genealogy code lives

genecrew depends on sibling **`crewai_custom_tools`** library as editable uv dependency
(`[tool.uv.sources] crewai-custom-tools = { path = "../crewai_custom_tools", editable = true }`).
Genealogy logic lives THERE, under `src/crewai_custom_tools/tools/genealogy/`: `gramps/`
(httpx+JWT client, read/write tools), `models/` (generated + `domain.py`), `analysis/` (pure
rules R1–R10 + D1–D3, duplicate finder), `standardize/` (name casing). **One deliberate
exception**: `releves.py`, the `import releve` smart-match engine, pure genealogy engine,
stays in genecrew for now — spec §8 defers extraction to library until **second** relevé
source appears (single consumer doesn't justify cross-repo release friction). When second
source lands, `releves.py` moves to library, exception gone. genecrew otherwise holds only
orchestration/CLI, plus that one engine: `cli.py` (verb grammar — `build_parser()`, dispatch
table's target names), `audit.py`, `names.py`, `gender.py`, `gender_apply.py`, `apply_all.py`,
`places.py`, `places_apply.py`, `places_merge.py`, `deces.py`, `deces_apply.py`,
`evenements.py` (shared event-creation building block behind both `import releve` and
`apply deaths`), `deces_event.py` (`apply deaths` orchestration, ADR 0014), `militaires.py`,
`lieux_wiki.py`, `lieu_import.py`, `archives.py` (`propose wikidata`/`propose dhs`
orchestration — network + batching; pure Piste translation lives in library,
`genealogy/pistes/`), `lieux_dits.py` (`import releve` lieu-dit cascade — tree lookup, then
OSM bounded to commune's bbox/fallback square, then creation under commune; finest place an
act names, never bare Nominatim search), `releves.py` (`import releve` smart-match engine —
**pure**: models + weighted matching, blocking, verdict net/gris/aucun, country-prefixed
place-code comparison; no network, offline-tested) and `releves_import.py` (`import releve`
orchestration — LLM interprets pasted text, then deterministic collect/apparier/write of
note+tag+citation on a `net`; `--person` forces target, no bypass of safety guards),
`referentiel.py` (`propose referentiel` — queries 9-country Wikidata table, read-only report
+ YAML, incl. tree-duplicates section; ADR 0016), `referentiel_apply.py` (`apply referentiel`
— consumes reviewed YAML, matches by QID first then name+type, creates/completes countries
and subdivisions, retypes 5 `Wilaya` places to `Province`; never re-queries Wikidata; ADR
0016), `propositions.py`, `stats.py`, `checkpoint.py`, `crew_audit.py` (crew orchestration),
`crew.py` (the crew), `logging_setup.py`, `scope.py`, `batching.py`, `report.py`.
Note: `facts.py` (`FactsFetcher`) **not** here — lives in library at
`crewai_custom_tools/tools/genealogy/gramps/facts.py`, imported from there.
After bumping library version, run `uv sync` from repo root to pick it up.

## Genealogy stack (Gramps Web)

This repo does **not** provision Gramps Web. Earlier root-level `docker-compose.yml` did,
but redundant with stack already provisioned by sibling `gramps-mcp` project — **deleted**.
Do not recreate `docker-compose.yml` here, don't run `docker compose` from this repo.

Live Gramps Web stack — data backend crew works against — comes up from **`gramps-mcp`**
project (sibling repo, e.g. `/Users/fjacquet/Projects/gramps-mcp`), via its own
`docker-compose.yml`:

```bash
cd /Users/fjacquet/Projects/gramps-mcp
docker compose up -d
```

Starts containers `gramps-mcp-grampsweb-1` (Gramps Web app/API), `grampsweb_celery`
(Celery worker), `grampsweb_redis` (Valkey/Redis broker/rate-limit store), and
`gramps-mcp-grampsweb_postgres-1` (Postgres). Named volumes persist Gramps user DB, search
index, thumbnails, export cache, Flask secret, genealogy database, media files — durable
state, not disposable. Gramps Web exposed on host port `80`.

`gramps-mcp` also exposes MCP server at `http://localhost:8000/mcp` with ~16 tools for
querying Gramps Web API (people, families, events, etc.). Not registered with Claude Code by
default (`claude mcp list` won't show it) — add with `claude mcp add` if task needs live
genealogy data, tell user before doing so.

See `docs/USER_GUIDE.md` for full Phase 0 setup sequence, incl. `GRAMPS_API_URL`
distinction between host-run `genecrew` (`http://localhost:80/api`) and containerized
`gramps-mcp` (`host.docker.internal:80`, no `/api` suffix).

## Commands

Run everything **from repo root** (single project, single `.venv`).

```bash
# Install/sync dependencies
uv sync

# The LLM audit crew (Détective → Chroniqueur), dry-run by default:
uv run genecrew crew audit --scope all --limit 25 --dry-run   # ~23k tokens/personne — borne le coût avec --limit
crewai run                                        # = bounded dry-run crew audit (dev convenience)
uv run run_crew                                   # equivalent direct entry point
# `uv run genecrew <verbe> <cible>` is the GeneCrew CLI (argparse), NOT the crew itself:
uv run genecrew stats                             # tree stats (Phase 0)
uv run genecrew propose audit --scope all --limit 200     # deterministic audit, read-only (Phase 1a)
uv run genecrew apply case --dry-run              # name-casing standardizer (first writer)
uv run genecrew propose gender --scope all --limit 200    # inférence de genre, lecture seule (propositions)
uv run genecrew apply gender --dry-run            # écrit les corrections de genre (fait, ADR 0009)
uv run genecrew apply all --dry-run               # casse, genre, lieux : écrit ; décès : proposition
uv run genecrew propose places --scope all        # propositions de lieux (lecture seule)
uv run genecrew apply places --dry-run            # écrit hiérarchie + GPS au-dessus du score
uv run genecrew apply places --scope place:P0080 --dry-run  # cibler UN lieu avant d'élargir
uv run genecrew apply deaths --yaml <relu.yaml> --dry-run  # crée les décès absents (ADR 0014)
uv run genecrew merge places --yaml <fusions.yaml>  # exécute les fusions relues (sans relire le verdict)
uv run genecrew merge places --scope all --dry-run   # détecte les doublons de lieux (ADR 0015)
# `merge places --scope all` FUSIONNE les doublons prouvés ; --limit et --scope place:<ID>
# forcent la simulation (une lecture tronquée ne décide pas d'une fusion irréversible)
pbpaste | uv run genecrew import releve            # relevé collé → smart match (stdin ; simule par défaut)
uv run genecrew import releve --file acte.txt --person I0421  # trancher un gris : forcer la personne
uv run genecrew merge people --scope all --limit 200 --dry-run  # fusionne les doublons prouvés, YAML pour le reste
uv run genecrew merge people --yaml <arbitrage.yaml>            # exécute les paires relues
uv run genecrew propose wikidata --scope person:I0042  # pistes Wikidata ; scan complet = exception, borner avec --limit
uv run genecrew propose dhs --scope person:I0042       # pistes DHS (projection de Wikidata via P902) ; aucune citation créée
uv run genecrew propose referentiel --country FR,CH   # subdivisions Wikidata par pays, lecture seule (ADR 0016)
uv run genecrew apply referentiel --yaml <relu.yaml> --dry-run   # écrit pays + subdivisions du YAML relu (ADR 0016)

# Train / replay / test the crew
uv run train <n_iterations> <filename>
uv run replay <task_id>
uv run test <n_iterations> <eval_llm>

# Lint. Les deux dépôts portent DÉSORMAIS la même configuration (select E,W,I,UP,B,C4,SIM,RUF ;
# line-length 120 ; RUF001-003 ignorés — projet francophone). Jusqu'au 2026-07-22 genecrew
# n'en avait aucune et tournait sur le jeu par défaut de ruff (E4, E7, E9, F) : ni tri
# d'imports, ni longueur de ligne, ni `zip` qui tronque en silence. Un `ruff check` vert
# des deux côtés dit maintenant la même chose.
uv run ruff check .
```

Suite doit être **entièrement verte** — aucun échec connu. (Longtemps rouge permanent sur
`test_deces.py::test_proposition_date_porte_la_donnee_machine` ; `deces.py` ne renseignait pas
champs `date_iso` / `lieu_nom` exigés par son propre test. Réparé 2026-07-22 : échec de nouveau
signal, pas bruit de fond.)

Gramps Web **not** brought up from this repo — see "Genealogy stack (Gramps Web)" above.

Tests live in `genecrew/tests/` — run `uv run python -m pytest genecrew/tests/ -q` from root; `crewai_custom_tools` library has own offline suite.

**CI**: `.github/workflows/ci.yml` (tests, ruff, Semgrep informatif) et `docs.yml` (build MkDocs +
déploiement Pages) tournent chaque PR. Voir aussi garde cohérence lock/bibliothèque dans
gotchas — impose ordre livraison entre deux dépôts.

## Environment / secrets

- `.env` (repo root) holds LLM config (**OpenRouter**, needs `OPENROUTER_API_KEY`; per-role mix: `MODEL`=`openrouter/mistralai/mistral-small-2603` for historien/chroniqueur, `MODEL_DETECTIVE`/`MODEL_STANDARDISATEUR`=`openrouter/z-ai/glm-5.2` for judgment — mistral-small alone fails Détective post), `GRAMPS_*` connection vars, `GENECREW_*` pipeline settings — see `.env.example`. Never print or commit contents.
- Root `.gitignore` excludes `.env`, `__pycache__/`, `.DS_Store`, standard Python build/venv artifacts.

## Outillage Claude Code (`.claude/`, versionné)

- **`.mcp.json`** déclare `gramps-mcp` sur `http://localhost:8000/mcp` — pile doit tourner
  (voir « Genealogy stack »). Interroger l'arbre passe par là, pas scripts jetables.
- **Hooks** (`.claude/settings.json`) : lecture/écriture `.env` **bloquées** (`.env.example`
  accessible) ; édition `pyproject.toml` vérifie `version` et `__version__` concordent — oubli
  du second a déjà fait rougir CI.
- **Sous-agents** : `verificateur-qid` (QID écrit de mémoire s'est révélé désigner un
  biplan), `chasseur-de-tests-muets` (éprouve tests par mutation).
- **Compétences** : `release-croisee` (séquence bump → tag → `uv sync`, ordre que CI
  impose), `etat-des-branches` (inventaire de ce qui dort hors `main` dans deux dépôts).

## Gotchas

- **Grammaire CLI** : sept verbes — `stats`, `propose`, `apply`, `merge`, `enrich`,
  `import`, `crew` — suivent cycle proposer → relire → appliquer. Ajouter base de données
  ajoute feuille sous `propose`, jamais verbe ; YAML relu qui sort passe par `apply citations`,
  déjà existant. `stats` mis à part, 15 autres anciens noms plats (`lieux-apply`,
  `deces-apply`, …) supprimés sans alias — voir table correspondance dans
  `docs/adr/0012-cli-grammaire-verbes.md`.
- **Bash `cd` persists within one compound command**: single `cd repoA && git … && cd repoB && git …` runs BOTH gits in repoA. Do per-repo git ops in separate tool calls (default cwd repo root).
- **Efficient people fetch**: `GET /api/people/?profile=all&extend=event_ref_list` returns human strings + citation counts (`profile`) AND raw dates with `sortval` (`extended.events`), one call per page.
- **Dates**: compare via integer `sortval` (Julian day; `0` = unknown/unsortable). Undated events come back `dateval=[0,0,0,False]`, `year=0`, `sortval=0` (not empty). Text-only dates: `modifier==6`.
- **Gender int**: `0=F, 1=M, 2=U`.
- **Form vs fact**: casing = *form* → direct write allowed, guarded by case-only invariant refusing any non-casing change. *Fact* stays proposal for human review — **except gender**, now written high confidence by `apply gender` (ratio ≥ 0.98 on INSEE+OFS table, reversible; ADR 0009 relaxes ADR 0008). Other facts (dates, relationships, name spelling) still need source → proposal.
- **`gramps-mcp create_person` ne pose pas `birth_ref_index`/`death_ref_index`.** Personne
  créée en un seul POST avec `event_ref_list` sort avec deux index à `-1` : événements bien
  attachés, mais Gramps ne sait pas lequel est naissance, et toutes vues suivant l'index
  (profil, chronologie, `propose audit`) la voient sans dates. Serveur recalcule index au PUT
  — second appel `create_person` avec `handle` suffit à réparer, préserve événements et
  familles. Nos propres outils n'ont pas ce défaut (`write_tools.py` pose index à
  l'attachement) : propre au serveur MCP voisin.
- **Créer un décès** : `apply deaths` (ADR 0014) écrit donnée cœur, contrairement à
  `apply citations` qui reste append-only. Garde « personne n'a pas de décès » vérifiée **au
  moment de l'écriture** : `GrampsCreateEventTool` refuse d'écraser `death_ref_index`
  existant, mais créerait quand même second événement `Death` dans liste — invisible dans
  vues suivant l'index, bien présent en base. Lieu se résout par **nom + type** :
  `index_lieux` n'indexe que types de feuille des résolveurs `geo/` (`TYPES_LIEU_DECES` =
  `Municipality`, `City`) — liste d'inclusion, car contenant oublié (`Department`, `State`,
  `Province`…) rattacherait décès à département en silence. Rapport porte mode dans nom
  (`…_simulation.md` / `…_ecritures.md`) pour que écriture n'écrase pas aperçu qui l'a
  autorisée.
- **Write safety switch**: writes gated by per-command `--dry-run` flag OR global
  `GENECREW_DRY_RUN` env var. Env can only *force* simulation; **default when var absent:
  simulate** (safe — via `effective_dry_run`, in `crewai_custom_tools` since 0.12.0). Set
  `GENECREW_DRY_RUN=false` in `.env` to write for real. Report's `Mode:` line reflects
  **effective** dry-run (env included) — never claims writes that didn't happen.
- Full-tree `propose audit`/`apply case` runs slow (minutes: per-family N+1 fetch + O(n²) duplicate check); iterate with `--limit`.
- **Crew write isolation & cost**: only `chroniqueur` agent has write tools (append-only
  note/tag); `detective` cannot write. `crew audit` run costs ~23k LLM tokens/person (heavy
  read correlation) — always bound full-tree runs with `--limit`.
- **Durable logs**: every `genecrew <verbe> <cible>` appends to
  `output/logs/<date>_genecrew.log` (START/DONE/FAILED + `genecrew`/`crewai_custom_tools`
  namespaces); `crew audit` also writes structured agent/tool trace to
  `output/crew_audit/<date>_crew_audit_<scope>.log.txt` (CrewAI only accepts `.txt`/`.json`),
  plus `.md`/`.yaml` report and human-review `<date>_propositions_audit_<scope>.yaml`.
- **Un rapport n'écrase plus le précédent.** Tous noms de rapport datés au JOUR
  (`<date>_<verbe>_<portée>.md`), donc deux passages du même verbe même jour même périmètre
  visaient même fichier et second gagnait en silence. Mesuré 2026-07-27 : `enrich wiki` de 15
  lieux a effacé compte rendu du run qui venait d'en illustrer 591 — dégât ne se limite pas au
  récit, **YAML de propositions** suivent même règle et sont relus par humain avant consommés
  par `apply`. `chemins.chemin_libre()` rend chemin inchangé tant que libre (pas de bruit dans
  noms) et n'y insère heure que quand fichier existe déjà. 31 chemins de rapport des 18 modules
  passent par lui ; nouveau rapport doit faire de même.
- **GPS des lieux**: coordonnées **WGS84** décimales ; GeoJSON = `[lon, lat]` (ne pas
  inverser) ; WKT Wikidata = `Point(lon lat)`, **longitude d'abord aussi** ; swisstopo : lire
  `lat`/`lon`, **jamais `x`/`y`** (grille suisse LV95). Géocodage passe par résolveurs `geo/`
  routés par pays (`crewai_custom_tools`).
- **Lien Wikipédia d'un lieu** (`enrich wiki`) : chercher **par titre**, vérifier **par
  position** — jamais l'inverse. Géorecherche trie par distance, et dix articles les plus
  proches du centre de Lyon sont ses rues et monuments : article « Lyon » n'y figure pas. Run du
  2026-07-26 posait 1 lien sur 49 pour cette raison, élargir `gslimit` n'aurait soigné que
  symptôme. `frwiki_page_info` porte `redirects=1`, résout gratuitement exonymes de l'arbre
  (`München` → `Munich`, `Lenzburg` → `Lenzbourg`) — `similarity` les classait sous seuil de
  0.85, donc perdus par construction. `frwiki_search_geo` sert qu'au rattrapage (page
  d'homonymie sans coordonnées : `Valence` → `Valence (Drôme)`), et là seulement similarité et
  garde d'ambiguïté reprennent la main.
- **Le référentiel ne convient pas au Royaume-Uni** — mesuré 2026-07-27, ne pas
  ajouter `GB` à `PAYS_REFERENTIEL` en croyant ligne de plus. Deux désaccords structurels, tous
  deux vérifiés sur l'endpoint : (1) **`Q145` porte lui-même un `P300`, `GB-UKM`**, donc filtre
  `STRSTARTS(?iso, "GB-")` ramène pays dans propres subdivisions, où il se prend pour propre
  parent — écrire créerait doublon du pays ; (2) comtés pendent sous régions anglaises **sans
  code ISO** (Kent → `Q48015` Angleterre du Sud-Est), donc sans parent dans univers, et ancre
  pays — écrite pour régions françaises sous « France métropolitaine » — les promeut niveau 1,
  **devant** Angleterre qui tombe niveau 2. Hiérarchie sort inversée : 209 entités écartées sur
  ~230. `GB-ESX` de surcroît porté par deux entités (`Q23293` comté cérémoniel, `Q21694646`
  comté non métropolitain), collision que règle 5 refuse d'écrire de toute façon. Sur 9 pays
  livrés, **seul** Royaume-Uni porte son propre code ISO 3166-2 : défaut (1) latent, non
  déclenché en production. Hiérarchie britannique se saisit donc à la main — `Country`
  Royaume-Uni, `Region` nation constitutive, `Province` comté, `Municipality` ville — ordre
  généalogique anglais étant « Ville/Paroisse, Comté, Angleterre », comté étant clé des County
  Record Offices.
- **Communes fusionnées** : absentes de `geo.api.gouv.fr/communes`, qui connaît que
  communes vivantes. `geo/france_ex_communes.py` bascule sur
  `/communes_associees_deleguees` (rattachement + code INSEE propre) puis Wikidata (SPARQL par
  `P374`), pose **deux placerefs datées** — sous département avant fusion, sous commune
  absorbante après. Borne est dissolution **+ 1 jour** : poser `P576` telle quelle ferait
  démarrer rattachement moderne un jour où commune existait encore. **`wdt:P576` rend toujours
  `dateTime` complet quelle que soit précision réelle** (dissolution à l'année sort
  `AAAA-01-01`), d'où contrôle `wikibase:timePrecision == 11`. Rien n'est daté si Wikidata et
  API ne concordent pas sur successeur.
- **Ordre de livraison entre deux dépôts** : CI checkoute voisin sur **tag**
  `v<version>` lu dans `uv.lock`, pas sur `main`. Bumper bibliothèque impose donc **taguer et
  pousser** avant que CI de genecrew puisse verdir — `uv sync` seul ne suffit pas, échec se
  présente comme `uv sync --locked` qui refuse lock.
- **Fusion de personnes irréversible** : `Person.merge()` supprime titanic et unionne
  listes à plat — rien ne dit ensuite quel événement venait de qui. `merge people` fusionne
  donc automatiquement que sur preuve **structurelle** (date complète identique, mêmes
  parents, conjoint + enfant communs), jamais sur ressemblance de nom : `marie pagan` et
  `marie pagani` scorent 0.957 alors que deux lignées. `PersonMergeArgs` n'offre aucun
  contrôle champ par champ, et **genre pas unionné** — d'où patch préalable unique.
  Déduplication transitive : relancer jusqu'à ce qu'une passe ne fusionne plus rien.
- **Doublons de lieux** : `merge places --scope` (ADR 0015) les détecte, ce qu'`apply places`
  ne peut pas faire — il ne regarde que les lieux de type `Unknown`. Veto sur codes officiels
  différents, et les coordonnées ne prouvent rien entre types différents : Paris existe en
  `Department` 75 et en `Municipality` 75056, deux entités réelles. Le survivant est le plus
  riche, pas le plus référencé — Gramps garde ses champs simples et effacerait ceux de l'autre.
  **Un `--limit` désactive les écritures** : le veto de grappe raisonne sur le groupe entier
  d'homonymes, et borner la lecture tronque les groupes — `merge places --scope ... --limit N`
  simule donc toujours, quel que soit `--dry-run`, le réflexe qui borne ailleurs (`merge people
  --limit 200`) produisant ici une simulation silencieuse.
- **Créer une famille par écriture directe (`GrampsClient`, sans passer par un outil
  de la bibliothèque — aucun `GrampsCreateFamilyTool` n'existe)** : réponse de
  `POST /families/` ne rend pas fiablement handle créé — peut rendre celui d'un des parents
  passés en `father_handle`/`mother_handle`, jamais celui de la famille. Retrouver famille par
  ses parents (`GET /families/`, filtrer sur `father_handle`/`mother_handle`) est seule source
  fiable. Second piège, complémentaire : serveur pose déjà tout seul
  `family_list`/`parent_family_list` en retour quand on écrit famille avec parents ou enfants
  — poser aussi à la main duplique entrées et, pire, y insère mauvaise valeur (mesuré
  2026-07-29 : handle d'un époux s'est retrouvé dans son PROPRE `family_list`, à la place du
  handle de la famille). Ne rien écrire côté personne pour ces deux champs ; serveur s'en
  charge.