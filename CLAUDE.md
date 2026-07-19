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

- `crew.py` — defines the `Genecrew` class (`@CrewBase`). Agents and tasks are declared here with `@agent`/`@task` decorators and pull their prompts from the YAML config files below. The crew currently runs as `Process.sequential`.
- `config/agents.yaml` — agent definitions (role/goal/backstory), templated with `{topic}`.
- `config/tasks.yaml` — task definitions (description/expected_output), templated with `{topic}` and `{current_year}`.
- `main.py` — entry points (`run`, `train`, `replay`, `test`) that build the `inputs` dict and call `Genecrew().crew().kickoff(...)`. Keep custom input logic here, not business logic.
- `tools/custom_tool.py` — placeholder `BaseTool` subclass template for adding custom CrewAI tools.
- `knowledge/user_preference.txt` — static knowledge file (currently placeholder content) available to the crew via CrewAI's knowledge sources.

**Current state**: the `crew.py`/`agents.yaml`/`tasks.yaml` scaffold is still the stock template (unused for now), but real functionality is built alongside it as an argparse CLI in `main.py`: Phase 0 (`stats`), Phase 1a deterministic audit (`audit`), and the name-casing standardizer (`names`). The genealogy logic itself lives in the sibling `crewai_custom_tools` library (see below), not here. The LLM crew (agents.yaml personas) is a later phase.

## Where the genealogy code lives

genecrew depends on the sibling **`crewai_custom_tools`** library as an editable uv dependency
(`[tool.uv.sources] crewai-custom-tools = { path = "../crewai_custom_tools", editable = true }`).
All genealogy logic lives THERE under `src/crewai_custom_tools/tools/genealogy/`: `gramps/`
(httpx+JWT client, read/write tools), `models/` (generated + `domain.py`), `analysis/` (pure
rules R1–R10 + D1–D3, duplicate finder), `standardize/` (name casing). genecrew holds only
orchestration/CLI: `audit.py`, `names.py`, `facts.py`, `scope.py`, `batching.py`, `report.py`.
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

# Run the crew via its console script
crewai run
uv run run_crew                                   # equivalent direct entry point
# `uv run genecrew <cmd>` is the GeneCrew CLI (argparse), NOT the crew itself:
uv run genecrew stats                             # tree stats (Phase 0)
uv run genecrew audit --scope all --limit 200     # deterministic audit, read-only (Phase 1a)
uv run genecrew names --dry-run                   # name-casing standardizer (first writer)
uv run genecrew gender --scope all --limit 200    # inférence de genre, lecture seule (propositions)
uv run genecrew gender-apply --dry-run            # écrit les corrections de genre (fait, ADR 0009)
uv run genecrew apply-all --dry-run               # casse puis genre en un passage

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

- `.env` (repo root) holds `MODEL` (LiteLLM, currently Gemini), the `GRAMPS_*` connection vars, and `GENECREW_*` pipeline settings — see `.env.example`. Never print or commit its contents.
- The root `.gitignore` excludes `.env`, `__pycache__/`, `.DS_Store`, and standard Python build/venv artifacts.

## Gotchas

- **Bash `cd` persists within one compound command**: a single `cd repoA && git … && cd repoB && git …` runs BOTH gits in repoA. Do per-repo git operations in separate tool calls (default cwd is the repo root).
- **Efficient people fetch**: `GET /api/people/?profile=all&extend=event_ref_list` returns human strings + citation counts (`profile`) AND raw dates with `sortval` (`extended.events`) in one call per page.
- **Dates**: compare via the integer `sortval` (Julian day; `0` = unknown/unsortable). Undated events come back as `dateval=[0,0,0,False]`, `year=0`, `sortval=0` (not empty). Text-only dates have `modifier==6`.
- **Gender int**: `0=F, 1=M, 2=U`.
- **Form vs fact**: casing = *form* → direct write allowed, guarded by a case-only invariant that refuses any non-casing change (whitespace normalization isn't implemented yet); anything asserting a *fact* (dates, gender, relationships, a name's spelling) needs a source → proposal for human review.
- **Write safety switch**: writes are gated by the per-command `--dry-run` flag AND the global `GENECREW_DRY_RUN` env var — if `GENECREW_DRY_RUN=true` (the default in `.env.example`), every write is simulated; set it false to write for real.
- Full-tree `audit`/`names` runs are slow (minutes: per-family N+1 fetch + O(n²) duplicate check); iterate with `--limit`.
