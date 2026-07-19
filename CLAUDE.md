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
- `main.py` — the argparse CLI dispatcher (all `genecrew <cmd>` subcommands) **and** the CrewAI console entry points (`run`/`train`/`test`/`replay`). `run` delegates to a bounded dry-run `crew-audit`. Sets up durable logging around every command.
- `tools/custom_tool.py` — placeholder `BaseTool` subclass template for adding custom CrewAI tools.
- `knowledge/user_preference.txt` — static knowledge file (currently placeholder content) available to the crew via CrewAI's knowledge sources.

**Current state**: two layers ship together. (1) A deterministic argparse CLI in `main.py`: `stats` (Phase 0), `audit` (read-only R1–R10/D1–D3), `names` (casing), `gender`/`gender-apply` (ADR 0009), `apply-all`, and `lieux`/`lieux-apply`/`lieux-merge` (place standardizer). (2) The **real LLM crew** (`crew-audit`): the 2-agent Détective→Chroniqueur audit workflow that interprets the deterministic anomalies and writes **encadré** append-only note/tag annotations (marker `[genecrew:audit:<date>:detective]`), dry-run by default. Genealogy logic lives in the sibling `crewai_custom_tools`; genecrew holds orchestration/CLI only.

## Where the genealogy code lives

genecrew depends on the sibling **`crewai_custom_tools`** library as an editable uv dependency
(`[tool.uv.sources] crewai-custom-tools = { path = "../crewai_custom_tools", editable = true }`).
All genealogy logic lives THERE under `src/crewai_custom_tools/tools/genealogy/`: `gramps/`
(httpx+JWT client, read/write tools), `models/` (generated + `domain.py`), `analysis/` (pure
rules R1–R10 + D1–D3, duplicate finder), `standardize/` (name casing). genecrew holds only
orchestration/CLI: `audit.py`, `names.py`, `gender.py`, `gender_apply.py`, `apply_all.py`, `places.py`, `places_apply.py`, `places_merge.py`, `crew_audit.py` (crew orchestration), `crew.py` (the crew), `logging_setup.py`, `facts.py`, `scope.py`, `batching.py`, `report.py`.
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
uv run genecrew crew-audit --scope all --limit 25 --dry-run   # ~23k tokens/personne — borne le coût avec --limit
crewai run                                        # = bounded dry-run crew-audit (dev convenience)
uv run run_crew                                   # equivalent direct entry point
# `uv run genecrew <cmd>` is the GeneCrew CLI (argparse), NOT the crew itself:
uv run genecrew stats                             # tree stats (Phase 0)
uv run genecrew audit --scope all --limit 200     # deterministic audit, read-only (Phase 1a)
uv run genecrew names --dry-run                   # name-casing standardizer (first writer)
uv run genecrew gender --scope all --limit 200    # inférence de genre, lecture seule (propositions)
uv run genecrew gender-apply --dry-run            # écrit les corrections de genre (fait, ADR 0009)
uv run genecrew apply-all --dry-run               # casse puis genre en un passage
uv run genecrew lieux --scope all                 # propositions de lieux (lecture seule)
uv run genecrew lieux-apply --dry-run             # écrit hiérarchie + GPS au-dessus du score
uv run genecrew lieux-merge --merges <fusions.yaml>  # exécute les fusions relues (jamais auto)

# Train / replay / test the crew
uv run train <n_iterations> <filename>
uv run replay <task_id>
uv run test <n_iterations> <eval_llm>

# Lint (ruff is a dev dependency; no ruff config file yet — defaults apply)
uv run ruff check .
```

Gramps Web is **not** brought up from this repo — see "Genealogy stack (Gramps Web)" above.

Tests live in `genecrew/tests/` — run `uv run python -m pytest genecrew/tests/ -q` from the root; the `crewai_custom_tools` library has its own offline suite. No CI in this repo yet.

## Environment / secrets

- `.env` (repo root) holds the LLM config (**OpenRouter**, needs `OPENROUTER_API_KEY`; per-role mix: `MODEL`=`openrouter/mistralai/mistral-small-2603` for historien/chroniqueur, `MODEL_DETECTIVE`/`MODEL_STANDARDISATEUR`=`openrouter/z-ai/glm-5.2` for judgment — mistral-small alone fails the Détective post), the `GRAMPS_*` connection vars, and `GENECREW_*` pipeline settings — see `.env.example`. Never print or commit its contents.
- The root `.gitignore` excludes `.env`, `__pycache__/`, `.DS_Store`, and standard Python build/venv artifacts.

## Gotchas

- **Bash `cd` persists within one compound command**: a single `cd repoA && git … && cd repoB && git …` runs BOTH gits in repoA. Do per-repo git operations in separate tool calls (default cwd is the repo root).
- **Efficient people fetch**: `GET /api/people/?profile=all&extend=event_ref_list` returns human strings + citation counts (`profile`) AND raw dates with `sortval` (`extended.events`) in one call per page.
- **Dates**: compare via the integer `sortval` (Julian day; `0` = unknown/unsortable). Undated events come back as `dateval=[0,0,0,False]`, `year=0`, `sortval=0` (not empty). Text-only dates have `modifier==6`.
- **Gender int**: `0=F, 1=M, 2=U`.
- **Form vs fact**: casing = *form* → direct write allowed, guarded by a case-only invariant that refuses any non-casing change. A *fact* stays a proposal for human review — **except gender**, now written at high confidence by `gender-apply` (ratio ≥ 0.98 on the INSEE+OFS table, reversible; ADR 0009 relaxes ADR 0008). Other facts (dates, relationships, name spelling) still need a source → proposal.
- **Write safety switch**: writes are gated by the per-command `--dry-run` flag OR the global `GENECREW_DRY_RUN` env var. The env can only *force* simulation; the **default when the var is absent is to simulate** (safe — via `effective_dry_run` in `crewai_custom_tools` 0.12.0). Set `GENECREW_DRY_RUN=false` in `.env` to write for real. The report's `Mode:` line reflects the **effective** dry-run (env included), so it never claims writes that didn't happen.
- Full-tree `audit`/`names` runs are slow (minutes: per-family N+1 fetch + O(n²) duplicate check); iterate with `--limit`.
- **Crew write isolation & cost**: only the `chroniqueur` agent has write tools (append-only note/tag); the `detective` cannot write. A `crew-audit` run costs ~23k LLM tokens/person (heavy read correlation) — always bound full-tree runs with `--limit`.
- **Durable logs**: every `genecrew <cmd>` appends to `output/logs/<date>_genecrew.log` (START/DONE/FAILED + the `genecrew`/`crewai_custom_tools` namespaces); `crew-audit` also writes a structured agent/tool trace to `output/crew_audit/<date>_crew_audit_<scope>.log.txt` (CrewAI only accepts `.txt`/`.json`), plus its `.md`/`.yaml` report and the human-review `<date>_propositions_audit_<scope>.yaml`.
- **GPS des lieux**: coordonnées **WGS84** décimales ; GeoJSON = `[lon, lat]` (ne pas inverser) ; swisstopo : lire `lat`/`lon`, **jamais `x`/`y`** (grille suisse LV95). Le géocodage passe par des résolveurs `geo/` routés par pays (`crewai_custom_tools`).
