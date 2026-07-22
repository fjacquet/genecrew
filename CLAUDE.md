# CLAUDE.md

Guide for Claude Code (claude.ai/code) working in this repo.

## Repository layout

Single `uv`/CrewAI project at repo root. Project metadata **at root**
(`pyproject.toml`, `uv.lock`, `.venv/`, `.env`, `.env.example`, `.gitignore`, `README.md`);
CrewAI package keeps standard layout under `genecrew/src/genecrew/` (with `genecrew/tests/`
and `genecrew/knowledge/` alongside). Code stays under `genecrew/src/` (CrewAI convention),
config at root, so `pyproject.toml` points hatchling at package with
`[tool.hatch.build.targets.wheel] packages = ["genecrew/src/genecrew"]`. Run everything from
repo root (no more `cd genecrew`).

Crew logic changes go inside `genecrew/src/genecrew/`.

### CrewAI project structure (`genecrew/src/genecrew/`)

- `crew.py` — real audit crew (`@CrewBase Genecrew`, `Process.sequential`, 4 agents): `detective` (judges), then `historien` (external proof: MatchID/Gallica/Wikidata), then `standardisateur` (precise propositions, strict JSON validated by `PropositionsLot`, confidence ≤ 2), then `chroniqueur` (**only** writer, append-only note/tag tools). Write isolation structural. LLM per role via `build_llm(role)` (`MODEL_<ROLE>` env, fallback `MODEL`), **always `is_litellm=True`** — CrewAI native provider hardcodes `"strict": true` on tool schemas, Mistral rejects that.
- `config/agents.yaml` — `detective`/`chroniqueur` personas (French, static).
- `config/tasks/audit.yaml` — `interpreter_anomalies` (Détective) → `rediger_annotations` (Chroniqueur), templated with `{anomalies_block}` and `{date}`. (`crew.py` sets `tasks_config` to this path; the stock `config/tasks.yaml` was deleted.)
- `cli.py` — `build_parser()`, the CLI's verb grammar: `stats`, `propose {audit|places|deaths|military|gender|wikidata|dhs}`, `apply {case|gender|places|citations|deaths|all}`, `merge {places|people}`, `enrich wiki`, `import {place|releve}`, `crew audit`. Pure — reads the environment only for flag defaults. See `docs/adr/0012-cli-grammaire-verbes.md`.
- `main.py` — the CLI dispatcher (`main()` calls `cli.build_parser()`, then routes on the `(command, target)` pair) **and** the CrewAI console entry points (`run`/`train`/`test`/`replay`). `run` delegates to a bounded dry-run `crew audit`. Sets up durable logging around every command.
- `tools/custom_tool.py` — placeholder `BaseTool` subclass template for adding custom CrewAI tools.
- `knowledge/user_preference.txt` — static knowledge file (currently placeholder content) available to the crew via CrewAI's knowledge sources.

**Current state**: two layers ship together. (1) Deterministic argparse CLI in `main.py`, exposed through 7-verb grammar above: `stats` (Phase 0), `propose audit` (read-only R1–R10/D1–D3), `apply case` (casing), `propose gender`/`apply gender` (ADR 0009), `apply all`, and `propose places`/`apply places`/`merge places` (place standardizer). (2) **Real LLM crew** (`crew audit`): 2-agent Détective→Chroniqueur audit workflow, interprets deterministic anomalies, writes **encadré** append-only note/tag annotations (marker `[genecrew:audit:<date>:detective]`), dry-run by default. Genealogy logic lives in sibling `crewai_custom_tools`; genecrew holds orchestration/CLI only.

## Where the genealogy code lives

genecrew depends on sibling **`crewai_custom_tools`** library as editable uv dependency
(`[tool.uv.sources] crewai-custom-tools = { path = "../crewai_custom_tools", editable = true }`).
Genealogy logic lives THERE under `src/crewai_custom_tools/tools/genealogy/`: `gramps/`
(httpx+JWT client, read/write tools), `models/` (generated + `domain.py`), `analysis/` (pure
rules R1–R10 + D1–D3, duplicate finder), `standardize/` (name casing). **One deliberate
exception**: `releves.py`, the `import releve` smart-match engine, is a *pure* genealogy engine
that nonetheless stays in genecrew for now — spec §8 defers its extraction to the library until a
**second** relevé source appears (a single consumer doesn't justify the cross-repo release
friction). When that second source lands, `releves.py` moves to the library and this exception
goes away. genecrew otherwise holds only orchestration/CLI, plus that one engine: `cli.py` (the
verb grammar — `build_parser()`, the dispatch table's target
names), `audit.py`, `names.py`, `gender.py`, `gender_apply.py`, `apply_all.py`, `places.py`,
`places_apply.py`, `places_merge.py`, `deces.py`, `deces_apply.py`, `evenements.py`
(shared event-creation building block behind both `import releve` and `apply deaths`),
`deces_event.py` (`apply deaths` orchestration, ADR 0014), `militaires.py`,
`lieux_wiki.py`, `lieu_import.py`, `archives.py` (`propose wikidata`/`propose dhs` orchestration —
network + batching; pure Piste translation lives in library, `genealogy/pistes/`),
`releves.py` (`import releve` smart-match engine — **pure**: models + weighted matching, blocking,
verdict net/gris/aucun, country-prefixed place-code comparison; no network, offline-tested) and
`releves_import.py` (`import releve` orchestration — LLM interprets pasted text, then
deterministic collect/apparier/write of note+tag+citation on a `net`; `--person` forces target
without bypassing safety guards),
`referentiel.py` (`propose referentiel` — queries the 9-country Wikidata table, read-only
report + YAML, including the tree-duplicates section; ADR 0016), `referentiel_apply.py`
(`apply referentiel` — consumes the reviewed YAML, matches by QID first then name+type,
creates/completes countries and subdivisions, retypes the 5 `Wilaya` places to `Province`;
never re-queries Wikidata; ADR 0016),
`propositions.py`, `stats.py`, `checkpoint.py`,
`crew_audit.py` (crew orchestration), `crew.py` (the crew), `logging_setup.py`,
`scope.py`, `batching.py`, `report.py`.
Note: `facts.py` (`FactsFetcher`) **not** here — lives in library at
`crewai_custom_tools/tools/genealogy/gramps/facts.py`, imported from there.
After bumping library version, run `uv sync` from repo root to pick it up.

## Genealogy stack (Gramps Web)

This repo does **not** provision Gramps Web. Earlier root-level `docker-compose.yml` did,
but it was redundant with stack already provisioned by sibling `gramps-mcp` project and has
been **deleted**. Do not recreate `docker-compose.yml` here, do not run `docker compose`
from this repo.

Live Gramps Web stack — data backend crew works against — comes up from **`gramps-mcp`**
project (sibling repo, e.g. `/Users/fjacquet/Projects/gramps-mcp`), using its own
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
genealogy data, and tell user before doing so.

See `docs/USER_GUIDE.md` for full Phase 0 setup sequence, including `GRAMPS_API_URL`
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
# `referentiel` : décision posée (ADR 0016), câblage CLI (cli.py/main.py) pas encore livré (tâche 10 du plan)

# Train / replay / test the crew
uv run train <n_iterations> <filename>
uv run replay <task_id>
uv run test <n_iterations> <eval_llm>

# Lint (ruff is a dev dependency; no ruff config file yet — defaults apply)
uv run ruff check .
```

Gramps Web **not** brought up from this repo — see "Genealogy stack (Gramps Web)" above.

Tests live in `genecrew/tests/` — run `uv run python -m pytest genecrew/tests/ -q` from root; `crewai_custom_tools` library has own offline suite.

**CI**: `.github/workflows/ci.yml` (tests, ruff, Semgrep en informatif) et `docs.yml` (build MkDocs +
déploiement Pages) tournent sur chaque PR. Voir aussi la garde de cohérence lock/bibliothèque dans les
gotchas — c'est elle qui impose l'ordre de livraison entre les deux dépôts.

## Environment / secrets

- `.env` (repo root) holds LLM config (**OpenRouter**, needs `OPENROUTER_API_KEY`; per-role mix: `MODEL`=`openrouter/mistralai/mistral-small-2603` for historien/chroniqueur, `MODEL_DETECTIVE`/`MODEL_STANDARDISATEUR`=`openrouter/z-ai/glm-5.2` for judgment — mistral-small alone fails Détective post), `GRAMPS_*` connection vars, `GENECREW_*` pipeline settings — see `.env.example`. Never print or commit its contents.
- Root `.gitignore` excludes `.env`, `__pycache__/`, `.DS_Store`, standard Python build/venv artifacts.

## Gotchas

- **Grammaire de la CLI** : sept verbes — `stats`, `propose`, `apply`, `merge`, `enrich`,
  `import`, `crew` — qui suivent le cycle proposer → relire → appliquer. Ajouter une base
  de données ajoute une feuille sous `propose`, jamais un verbe ; le YAML relu qui en sort
  passe par `apply citations`, qui existe déjà. `stats` mis à part, les 15 autres anciens
  noms plats (`lieux-apply`, `deces-apply`, …) ont été supprimés sans alias — voir la table
  de correspondance dans `docs/adr/0012-cli-grammaire-verbes.md`.
- **Bash `cd` persists within one compound command**: single `cd repoA && git … && cd repoB && git …` runs BOTH gits in repoA. Do per-repo git operations in separate tool calls (default cwd is repo root).
- **Efficient people fetch**: `GET /api/people/?profile=all&extend=event_ref_list` returns human strings + citation counts (`profile`) AND raw dates with `sortval` (`extended.events`) in one call per page.
- **Dates**: compare via integer `sortval` (Julian day; `0` = unknown/unsortable). Undated events come back as `dateval=[0,0,0,False]`, `year=0`, `sortval=0` (not empty). Text-only dates have `modifier==6`.
- **Gender int**: `0=F, 1=M, 2=U`.
- **Form vs fact**: casing = *form* → direct write allowed, guarded by a case-only invariant that refuses any non-casing change. A *fact* stays a proposal for human review — **except gender**, now written at high confidence by `apply gender` (ratio ≥ 0.98 on the INSEE+OFS table, reversible; ADR 0009 relaxes ADR 0008). Other facts (dates, relationships, name spelling) still need a source → proposal.
- **Créer un décès** : `apply deaths` (ADR 0014) écrit une donnée cœur, contrairement à
  `apply citations` qui reste append-only. La garde « la personne n'a pas de décès » est
  vérifiée **au moment de l'écriture** : `GrampsCreateEventTool` refuse d'écraser un
  `death_ref_index` existant, mais créerait quand même un second événement `Death` dans
  la liste — invisible dans les vues qui suivent l'index, bien présent en base.
  Le lieu se résout par **nom + type** : `index_lieux` n'indexe que les types de feuille
  des résolveurs `geo/` (`TYPES_LIEU_DECES` = `Municipality`, `City`) — liste
  d'inclusion, car un contenant oublié (`Department`, `Canton`, `State`…) rattacherait
  un décès à un département en silence. Le rapport porte le mode dans son nom
  (`…_simulation.md` / `…_ecritures.md`) pour que l'écriture n'écrase pas l'aperçu qui
  l'a autorisée.
- **Write safety switch**: writes are gated by the per-command `--dry-run` flag OR the global `GENECREW_DRY_RUN` env var. The env can only *force* simulation; the **default when the var is absent is to simulate** (safe — via `effective_dry_run`, dans `crewai_custom_tools` depuis 0.12.0). Set `GENECREW_DRY_RUN=false` in `.env` to write for real. The report's `Mode:` line reflects the **effective** dry-run (env included), so it never claims writes that didn't happen.
- Full-tree `propose audit`/`apply case` runs are slow (minutes: per-family N+1 fetch + O(n²) duplicate check); iterate with `--limit`.
- **Crew write isolation & cost**: only `chroniqueur` agent has write tools (append-only note/tag); `detective` cannot write. A `crew audit` run costs ~23k LLM tokens/person (heavy read correlation) — always bound full-tree runs with `--limit`.
- **Durable logs**: every `genecrew <verbe> <cible>` appends to `output/logs/<date>_genecrew.log` (START/DONE/FAILED + `genecrew`/`crewai_custom_tools` namespaces); `crew audit` also writes structured agent/tool trace to `output/crew_audit/<date>_crew_audit_<scope>.log.txt` (CrewAI only accepts `.txt`/`.json`), plus its `.md`/`.yaml` report and human-review `<date>_propositions_audit_<scope>.yaml`.
- **GPS des lieux**: coordonnées **WGS84** décimales ; GeoJSON = `[lon, lat]` (ne pas inverser) ; WKT Wikidata = `Point(lon lat)`, **longitude d'abord aussi** ; swisstopo : lire `lat`/`lon`, **jamais `x`/`y`** (grille suisse LV95). Le géocodage passe par des résolveurs `geo/` routés par pays (`crewai_custom_tools`).
- **Communes fusionnées** : absentes de `geo.api.gouv.fr/communes`, qui ne connaît que les communes vivantes. `geo/france_ex_communes.py` bascule sur `/communes_associees_deleguees` (rattachement + code INSEE propre) puis Wikidata (SPARQL par `P374`), et pose **deux placerefs datées** — sous le département avant la fusion, sous la commune absorbante après. La borne est la dissolution **+ 1 jour** : poser `P576` telle quelle ferait démarrer le rattachement moderne un jour où la commune existait encore. **`wdt:P576` rend toujours un `dateTime` complet quelle que soit la précision réelle** (une dissolution à l'année sort `AAAA-01-01`), d'où le contrôle `wikibase:timePrecision == 11`. Rien n'est daté si Wikidata et l'API ne concordent pas sur le successeur.
- **Ordre de livraison entre les deux dépôts** : la CI checkoute le voisin sur le **tag** `v<version>` lu dans `uv.lock`, pas sur `main`. Bumper la bibliothèque impose donc de **taguer et pousser** avant que la CI de genecrew puisse verdir — `uv sync` seul ne suffit pas, et l'échec se présente comme un `uv sync --locked` qui refuse le lock.
- **Fusion de personnes irréversible** : `Person.merge()` supprime le titanic et unionne les
  listes à plat — rien ne dit ensuite quel événement venait de qui. `merge people` ne fusionne
  donc automatiquement que sur preuve **structurelle** (date complète identique, mêmes parents,
  conjoint + enfant communs), jamais sur une ressemblance de nom : `marie pagan` et
  `marie pagani` scorent 0.957 alors que ce sont deux lignées. `PersonMergeArgs` n'offre aucun
  contrôle champ par champ, et **le genre n'est pas unionné** — d'où l'unique patch préalable.
  La déduplication est transitive : relancer jusqu'à ce qu'une passe ne fusionne plus rien.
- **Doublons de lieux** : `merge places --scope` (ADR 0015) les détecte, ce qu'`apply places`
  ne peut pas faire — il ne regarde que les lieux de type `Unknown`. Veto sur codes officiels
  différents, et les coordonnées ne prouvent rien entre types différents : Paris existe en
  `Department` 75 et en `Municipality` 75056, deux entités réelles. Le survivant est le plus
  riche, pas le plus référencé — Gramps garde ses champs simples et effacerait ceux de l'autre.
  **Un `--limit` désactive les écritures** : le veto de grappe raisonne sur le groupe entier
  d'homonymes, et borner la lecture tronque les groupes — `merge places --scope ... --limit N`
  simule donc toujours, quel que soit `--dry-run`, le réflexe qui borne ailleurs (`merge people
  --limit 200`) produisant ici une simulation silencieuse.