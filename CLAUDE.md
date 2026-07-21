# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Repository layout

Single `uv`/CrewAI project rooted at the repo root. Project metadata lives **at the root**
(`pyproject.toml`, `uv.lock`, `.venv/`, `.env`, `.env.example`, `.gitignore`, `README.md`); the
CrewAI package keeps its standard layout under `genecrew/src/genecrew/` (with `genecrew/tests/`
and `genecrew/knowledge/` alongside). Because the code stays under `genecrew/src/` (CrewAI
convention) while the config is at the root, `pyproject.toml` points hatchling at the package with
`[tool.hatch.build.targets.wheel] packages = ["genecrew/src/genecrew"]`. Run everything from the
repo root (no more `cd genecrew`).

When making changes, work inside `genecrew/src/genecrew/` for crew logic.

### CrewAI project structure (`genecrew/src/genecrew/`)

- `crew.py` — the real audit crew (`@CrewBase Genecrew`, `Process.sequential`, 4 agents): `detective` (judges) → `historien` (external proof: MatchID/Gallica/Wikidata) → `standardisateur` (precise propositions, strict JSON validated by `PropositionsLot`, confidence ≤ 2) → `chroniqueur` (the **only** writer, append-only note/tag tools). Write isolation is structural. LLM per role via `build_llm(role)` (`MODEL_<ROLE>` env, fallback `MODEL`), **always `is_litellm=True`** — CrewAI's native provider hardcodes `"strict": true` on tool schemas, which Mistral rejects.
- `config/agents.yaml` — `detective`/`chroniqueur` personas (French, static).
- `config/tasks/audit.yaml` — `interpreter_anomalies` (Détective) → `rediger_annotations` (Chroniqueur), templated with `{anomalies_block}` and `{date}`. (`crew.py` sets `tasks_config` to this path; the stock `config/tasks.yaml` was deleted.)
- `cli.py` — `build_parser()`, the CLI's verb grammar: `stats`, `propose {audit|places|deaths|military|gender|wikidata|dhs}`, `apply {case|gender|places|citations|deaths|all}`, `merge {places|people}`, `enrich wiki`, `import {place|releve}`, `crew audit`. Pure — reads the environment only for flag defaults. See `docs/adr/0012-cli-grammaire-verbes.md`.
- `main.py` — the CLI dispatcher (`main()` calls `cli.build_parser()`, then routes on the `(command, target)` pair) **and** the CrewAI console entry points (`run`/`train`/`test`/`replay`). `run` delegates to a bounded dry-run `crew audit`. Sets up durable logging around every command.
- `tools/custom_tool.py` — placeholder `BaseTool` subclass template for adding custom CrewAI tools.
- `knowledge/user_preference.txt` — static knowledge file (currently placeholder content) available to the crew via CrewAI's knowledge sources.

**Current state**: two layers ship together. (1) A deterministic argparse CLI in `main.py`, exposed through the 7-verb grammar above: `stats` (Phase 0), `propose audit` (read-only R1–R10/D1–D3), `apply case` (casing), `propose gender`/`apply gender` (ADR 0009), `apply all`, and `propose places`/`apply places`/`merge places` (place standardizer). (2) The **real LLM crew** (`crew audit`): the 2-agent Détective→Chroniqueur audit workflow that interprets the deterministic anomalies and writes **encadré** append-only note/tag annotations (marker `[genecrew:audit:<date>:detective]`), dry-run by default. Genealogy logic lives in the sibling `crewai_custom_tools`; genecrew holds orchestration/CLI only.

## Where the genealogy code lives

genecrew depends on the sibling **`crewai_custom_tools`** library as an editable uv dependency
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
network + batching; the pure Piste translation lives in the library, `genealogy/pistes/`),
`releves.py` (`import releve` smart-match engine — **pure**: models + weighted matching, blocking,
verdict net/gris/aucun, country-prefixed place-code comparison; no network, offline-tested) and
`releves_import.py` (`import releve` orchestration — LLM interprets the pasted text, then
deterministic collect/apparier/write of note+tag+citation on a `net`; `--person` forces the target
without bypassing the safety guards),
`propositions.py`, `stats.py`, `checkpoint.py`,
`crew_audit.py` (crew orchestration), `crew.py` (the crew), `logging_setup.py`,
`scope.py`, `batching.py`, `report.py`.
Note: `facts.py` (`FactsFetcher`) is **not** here — it lives in the library, at
`crewai_custom_tools/tools/genealogy/gramps/facts.py`, and is imported from there.
After bumping the library version, run `uv sync` from the repo root to pick it up.

## Genealogy stack (Gramps Web)

This repo does **not** provision Gramps Web. An earlier root-level `docker-compose.yml` did,
but it was redundant with the stack already provisioned by the sibling `gramps-mcp` project
and has been **deleted**. Do not recreate a `docker-compose.yml` here and do not run
`docker compose` from this repo.

The live Gramps Web stack — this is the data backend the crew is intended to work against — is
brought up from the **`gramps-mcp`** project (sibling repo, e.g.
`/Users/fjacquet/Projects/gramps-mcp`), using its own `docker-compose.yml`:

```bash
cd /Users/fjacquet/Projects/gramps-mcp
docker compose up -d
```

This starts the containers `gramps-mcp-grampsweb-1` (Gramps Web app/API), `grampsweb_celery`
(Celery worker), `grampsweb_redis` (Valkey/Redis broker/rate-limit store), and
`gramps-mcp-grampsweb_postgres-1` (Postgres). Named volumes persist the Gramps user DB, search
index, thumbnails, export cache, Flask secret, the genealogy database, and media files — treat
these as durable state, not disposable. Gramps Web itself is exposed on host port `80`.

`gramps-mcp` also exposes an MCP server at `http://localhost:8000/mcp` with ~16 tools for
querying the Gramps Web API (people, families, events, etc.). It is not registered with Claude
Code by default (`claude mcp list` won't show it) — add it with `claude mcp add` if a task
requires querying live genealogy data, and mention that to the user before doing so.

See `docs/USER_GUIDE.md` for the full Phase 0 setup sequence, including the `GRAMPS_API_URL`
distinction between host-run `genecrew` (`http://localhost:80/api`) and containerized
`gramps-mcp` (`host.docker.internal:80`, no `/api` suffix).

## Commands

Run everything **from the repo root** (single project, single `.venv`).

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
uv run genecrew merge places --yaml <fusions.yaml>  # exécute les fusions relues (jamais auto)
pbpaste | uv run genecrew import releve            # relevé collé → smart match (stdin ; simule par défaut)
uv run genecrew import releve --file acte.txt --person I0421  # trancher un gris : forcer la personne
uv run genecrew merge people --scope all --limit 200 --dry-run  # fusionne les doublons prouvés, YAML pour le reste
uv run genecrew merge people --yaml <arbitrage.yaml>            # exécute les paires relues
uv run genecrew propose wikidata --scope person:I0042  # pistes Wikidata ; scan complet = exception, borner avec --limit
uv run genecrew propose dhs --scope person:I0042       # pistes DHS (projection de Wikidata via P902) ; aucune citation créée

# Train / replay / test the crew
uv run train <n_iterations> <filename>
uv run replay <task_id>
uv run test <n_iterations> <eval_llm>

# Lint (ruff is a dev dependency; no ruff config file yet — defaults apply)
uv run ruff check .
```

Gramps Web is **not** brought up from this repo — see "Genealogy stack (Gramps Web)" above.

Tests live in `genecrew/tests/` — run `uv run python -m pytest genecrew/tests/ -q` from the root; the `crewai_custom_tools` library has its own offline suite.

**CI**: `.github/workflows/ci.yml` (tests, ruff, Semgrep en informatif) et `docs.yml` (build MkDocs +
déploiement Pages) tournent sur chaque PR. Voir aussi la garde de cohérence lock/bibliothèque dans les
gotchas — c'est elle qui impose l'ordre de livraison entre les deux dépôts.

## Environment / secrets

- `.env` (repo root) holds the LLM config (**OpenRouter**, needs `OPENROUTER_API_KEY`; per-role mix: `MODEL`=`openrouter/mistralai/mistral-small-2603` for historien/chroniqueur, `MODEL_DETECTIVE`/`MODEL_STANDARDISATEUR`=`openrouter/z-ai/glm-5.2` for judgment — mistral-small alone fails the Détective post), the `GRAMPS_*` connection vars, and `GENECREW_*` pipeline settings — see `.env.example`. Never print or commit its contents.
- The root `.gitignore` excludes `.env`, `__pycache__/`, `.DS_Store`, and standard Python build/venv artifacts.

## Gotchas

- **Grammaire de la CLI** : sept verbes — `stats`, `propose`, `apply`, `merge`, `enrich`,
  `import`, `crew` — qui suivent le cycle proposer → relire → appliquer. Ajouter une base
  de données ajoute une feuille sous `propose`, jamais un verbe ; le YAML relu qui en sort
  passe par `apply citations`, qui existe déjà. `stats` mis à part, les 15 autres anciens
  noms plats (`lieux-apply`, `deces-apply`, …) ont été supprimés sans alias — voir la table
  de correspondance dans `docs/adr/0012-cli-grammaire-verbes.md`.
- **Bash `cd` persists within one compound command**: a single `cd repoA && git … && cd repoB && git …` runs BOTH gits in repoA. Do per-repo git operations in separate tool calls (default cwd is the repo root).
- **Efficient people fetch**: `GET /api/people/?profile=all&extend=event_ref_list` returns human strings + citation counts (`profile`) AND raw dates with `sortval` (`extended.events`) in one call per page.
- **Dates**: compare via the integer `sortval` (Julian day; `0` = unknown/unsortable). Undated events come back as `dateval=[0,0,0,False]`, `year=0`, `sortval=0` (not empty). Text-only dates have `modifier==6`.
- **Gender int**: `0=F, 1=M, 2=U`.
- **Form vs fact**: casing = *form* → direct write allowed, guarded by a case-only invariant that refuses any non-casing change. A *fact* stays a proposal for human review — **except gender**, now written at high confidence by `apply gender` (ratio ≥ 0.98 on the INSEE+OFS table, reversible; ADR 0009 relaxes ADR 0008). Other facts (dates, relationships, name spelling) still need a source → proposal.
- **Créer un décès** : `apply deaths` (ADR 0014) écrit une donnée cœur, contrairement à
  `apply citations` qui reste append-only. La garde « la personne n'a pas de décès » est
  vérifiée **au moment de l'écriture** : `GrampsCreateEventTool` refuse d'écraser un
  `death_ref_index` existant, mais créerait quand même un second événement `Death` dans
  la liste — invisible dans les vues qui suivent l'index, bien présent en base.
- **Write safety switch**: writes are gated by the per-command `--dry-run` flag OR the global `GENECREW_DRY_RUN` env var. The env can only *force* simulation; the **default when the var is absent is to simulate** (safe — via `effective_dry_run`, dans `crewai_custom_tools` depuis 0.12.0). Set `GENECREW_DRY_RUN=false` in `.env` to write for real. The report's `Mode:` line reflects the **effective** dry-run (env included), so it never claims writes that didn't happen.
- Full-tree `propose audit`/`apply case` runs are slow (minutes: per-family N+1 fetch + O(n²) duplicate check); iterate with `--limit`.
- **Crew write isolation & cost**: only the `chroniqueur` agent has write tools (append-only note/tag); the `detective` cannot write. A `crew audit` run costs ~23k LLM tokens/person (heavy read correlation) — always bound full-tree runs with `--limit`.
- **Durable logs**: every `genecrew <verbe> <cible>` appends to `output/logs/<date>_genecrew.log` (START/DONE/FAILED + the `genecrew`/`crewai_custom_tools` namespaces); `crew audit` also writes a structured agent/tool trace to `output/crew_audit/<date>_crew_audit_<scope>.log.txt` (CrewAI only accepts `.txt`/`.json`), plus its `.md`/`.yaml` report and the human-review `<date>_propositions_audit_<scope>.yaml`.
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
