# `gender-apply` — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Appliquer (ÉCRIRE dans Gramps) les corrections de genre inférées, en auto au-dessus d'un seuil de confiance, de façon déterministe, réversible et gated.

**Architecture:** Un nouvel outil d'écriture `GrampsUpdateGenderTool` (cct, patron de `GrampsUpdateNameTool`) + une orchestration `run_gender_apply` (genecrew) qui re-infère en direct sur un périmètre et écrit les genres qualifiants via l'outil. Réutilise `iter_people_batches`/`FactsFetcher`/`infer_sex`. Premier write d'un FAIT (relâche l'ADR 0008 → ADR 0009).

**Tech Stack:** Python ≥3.11, `uv`, Pydantic v2, httpx `MockTransport` (tests), pytest, hatchling (packaging cct).

## Global Constraints

- **Deux dépôts, deux branches.** cct : branche `feat/genealogy-gender-write` (base = `main` courant). genecrew : branche `feat/gender-apply` (base = `main` courant). Faire les tâches cct (1–2) **avant** les tâches genecrew (3–5) : genecrew importe cct en éditable (source live).
- **`uv` pour tout Python.** Tests cct : `uv run pytest …` depuis `/Users/fjacquet/Projects/crewai_custom_tools`. Tests genecrew : `uv run python -m pytest …` depuis `/Users/fjacquet/Projects/genecrew`.
- **Représentation du genre** : entier Gramps `0=F, 1=M, 2=U`. `PersonFacts.sex` vaut `"F"|"M"|"U"`. `infer_sex` renvoie `"F"|"M"` (ou `None`). Mapping écrit : `{"F": 0, "M": 1}`.
- **Seuil d'écriture** : `inf.sex is not None` (donc déjà `total ≥ 50` et `ratio ≥ 0.95` via `infer_sex`) **ET** `inf.ratio ≥ min_ratio` (défaut **0.98**). Aucun garde-fou supplémentaire.
- **Types écrits** : genre inconnu (`sex == "U"`) rempli, ET contradiction (`inf.sex != sex`) corrigée. Genre déjà correct → skip.
- **Double interrupteur dry-run** : le paramètre `dry_run` OU le global `GENECREW_DRY_RUN` (l'env ne peut que *forcer* la simulation). No-op si le genre demandé égale l'actuel.
- **Version cct** : bump `0.10.0` → `0.11.0` en lockstep (pyproject, `__init__.py`, `test_scaffold.py`).
- **Style** : Conventional Commits, scope français ; fonctions de rendu pures ; docstrings concises comme le code voisin.

---

## Task 1 : `GrampsUpdateGenderTool` (cct)

**Files:**
- Modify: `src/crewai_custom_tools/tools/genealogy/gramps/write_tools.py`
- Test: `tests/test_genealogy_write_tools.py`

**Interfaces:**
- Consumes: `get_client`, `api_tool`, `ok`, `BaseTool`, `BaseModel`, `Field`, `os` (déjà importés dans `write_tools.py`).
- Produces: `GrampsUpdateGenderTool` avec `_run(self, handle: str, gender: int, dry_run: bool = False) -> str` renvoyant l'enveloppe `ok({"handle","gramps_id","old","new","dry_run","noop"})`.

- [ ] **Step 1: Écrire les tests qui échouent**

Dans `tests/test_genealogy_write_tools.py`, ajouter l'import en tête (à côté de l'import existant de `GrampsUpdateNameTool`) :
```python
from crewai_custom_tools.tools.genealogy.gramps.write_tools import (
    GrampsUpdateGenderTool,
    GrampsUpdateNameTool,
)
```
(remplace la ligne `from ... import GrampsUpdateNameTool`). Puis ajouter à la fin du fichier (le fichier a déjà `_mock`, `PERSON` avec `gender: 1`, la fixture autouse `_no_global_dry_run`, `json`, `httpx`) :
```python
def test_update_gender_writes(mocker):
    puts = []

    def handler(request):
        if request.url.path == "/api/token/":
            return httpx.Response(200, json={"access_token": "t"})
        if request.method == "GET":
            return httpx.Response(200, json=PERSON)
        if request.method == "PUT":
            puts.append(json.loads(request.content))
            return httpx.Response(200, json={})
        return httpx.Response(404)

    _mock(mocker, handler)
    payload = json.loads(GrampsUpdateGenderTool()._run(handle="h1", gender=0))
    assert payload["success"] is True
    assert payload["data"]["old"] == 1 and payload["data"]["new"] == 0
    assert payload["data"]["noop"] is False and payload["data"]["dry_run"] is False
    assert puts and puts[0]["gender"] == 0


def test_update_gender_dry_run_does_not_put(mocker):
    def handler(request):
        if request.url.path == "/api/token/":
            return httpx.Response(200, json={"access_token": "t"})
        if request.method == "GET":
            return httpx.Response(200, json=PERSON)
        raise AssertionError("aucun PUT attendu en dry_run")

    _mock(mocker, handler)
    payload = json.loads(GrampsUpdateGenderTool()._run(handle="h1", gender=0, dry_run=True))
    assert payload["success"] is True and payload["data"]["dry_run"] is True
    assert payload["data"]["new"] == 0


def test_update_gender_noop_when_unchanged(mocker):
    def handler(request):
        if request.url.path == "/api/token/":
            return httpx.Response(200, json={"access_token": "t"})
        if request.method == "GET":
            return httpx.Response(200, json=PERSON)
        raise AssertionError("aucun PUT : genre déjà correct")

    _mock(mocker, handler)
    payload = json.loads(GrampsUpdateGenderTool()._run(handle="h1", gender=1))  # PERSON gender == 1
    assert payload["success"] is True and payload["data"]["noop"] is True


def test_env_dry_run_forces_gender_simulation(mocker, monkeypatch):
    monkeypatch.setenv("GENECREW_DRY_RUN", "true")

    def handler(request):
        if request.url.path == "/api/token/":
            return httpx.Response(200, json={"access_token": "t"})
        if request.method == "GET":
            return httpx.Response(200, json=PERSON)
        raise AssertionError("aucun PUT : GENECREW_DRY_RUN force la simulation")

    _mock(mocker, handler)
    payload = json.loads(GrampsUpdateGenderTool()._run(handle="h1", gender=0))  # dry_run param = False
    assert payload["success"] is True and payload["data"]["dry_run"] is True
    assert payload["data"]["new"] == 0
```

- [ ] **Step 2: Lancer — il échoue**

Run: `cd /Users/fjacquet/Projects/crewai_custom_tools && uv run pytest tests/test_genealogy_write_tools.py -q`
Expected: FAIL (`ImportError: cannot import name 'GrampsUpdateGenderTool'`).

- [ ] **Step 3: Implémenter l'outil**

Ajouter à la fin de `src/crewai_custom_tools/tools/genealogy/gramps/write_tools.py` :
```python
class GrampsUpdateGenderInput(BaseModel):
    """Input schema for GrampsUpdateGenderTool."""

    handle: str = Field(..., description="Handle of the person whose gender to set.")
    gender: int = Field(..., description="Gender integer: 0=F, 1=M, 2=U.")
    dry_run: bool = Field(False, description="If true, compute the change but do not write.")


class GrampsUpdateGenderTool(BaseTool):
    """Set a person's gender (0=F, 1=M, 2=U) in Gramps — a bounded, high-confidence fact write."""

    name: str = "gramps_update_gender"
    description: str = (
        "Sets one person's gender in Gramps (0=F, 1=M, 2=U). This writes a fact, so it is "
        "meant for high-confidence, human-authorized corrections. No-op when the gender is "
        "already the requested value. Writes directly unless dry_run is set or the global "
        "GENECREW_DRY_RUN env var is enabled."
    )
    args_schema: type[BaseModel] = GrampsUpdateGenderInput

    @api_tool(provider="GrampsWeb", endpoint="UpdateGender")
    def _run(self, handle: str, gender: int, dry_run: bool = False) -> str:
        # Interrupteur GLOBAL : GENECREW_DRY_RUN=true force la simulation (ne peut que rendre
        # l'appel PLUS sûr ; un dry_run explicite gagne toujours vers la sécurité).
        dry_run = dry_run or os.environ.get("GENECREW_DRY_RUN", "").strip().lower() in ("1", "true", "yes")
        client = get_client()
        person = client.get_object("people", handle)
        old = person.get("gender", 2)
        change = {"handle": handle, "gramps_id": person.get("gramps_id"),
                  "old": old, "new": gender, "dry_run": dry_run, "noop": False}
        if gender == old:
            change["noop"] = True
            return ok(change)
        person["gender"] = gender
        if not dry_run:
            client.request("PUT", f"/people/{handle}", json=person)
        return ok(change)
```

- [ ] **Step 4: Lancer — il passe**

Run: `cd /Users/fjacquet/Projects/crewai_custom_tools && uv run pytest tests/test_genealogy_write_tools.py -q`
Expected: PASS (tous verts).

- [ ] **Step 5: Commit**

```bash
cd /Users/fjacquet/Projects/crewai_custom_tools
git add src/crewai_custom_tools/tools/genealogy/gramps/write_tools.py tests/test_genealogy_write_tools.py
git commit -m "feat(genealogy): GrampsUpdateGenderTool (write genre, no-op, double dry-run)"
```

---

## Task 2 : Export + bump 0.11.0 (cct)

**Files:**
- Modify: `src/crewai_custom_tools/__init__.py`, `pyproject.toml`, `tests/test_scaffold.py`

**Interfaces:**
- Produces: `GrampsUpdateGenderTool` exporté depuis `crewai_custom_tools` ; version `0.11.0`.

- [ ] **Step 1: Mettre à jour l'assertion de version (test d'abord)**

Modifier `tests/test_scaffold.py` :
```python
import crewai_custom_tools


def test_version():
    assert crewai_custom_tools.__version__ == "0.11.0"
```

- [ ] **Step 2: Lancer — il échoue**

Run: `cd /Users/fjacquet/Projects/crewai_custom_tools && uv run pytest tests/test_scaffold.py -q`
Expected: FAIL (`assert '0.10.0' == '0.11.0'`).

- [ ] **Step 3: Bump + export**

Dans `src/crewai_custom_tools/__init__.py` :
- remplacer `__version__ = "0.10.0"` par `__version__ = "0.11.0"` ;
- remplacer la ligne d'import `from crewai_custom_tools.tools.genealogy.gramps.write_tools import GrampsUpdateNameTool` par :
  ```python
  from crewai_custom_tools.tools.genealogy.gramps.write_tools import (
      GrampsUpdateGenderTool,
      GrampsUpdateNameTool,
  )
  ```
- dans la liste `__all__`, ajouter `"GrampsUpdateGenderTool",` juste à côté de `"GrampsUpdateNameTool",`.

Dans `pyproject.toml`, remplacer `version = "0.10.0"` par `version = "0.11.0"`.

- [ ] **Step 4: Lancer — il passe + export vérifié**

Run: `cd /Users/fjacquet/Projects/crewai_custom_tools && uv run pytest tests/test_scaffold.py -q && uv run python -c "from crewai_custom_tools import GrampsUpdateGenderTool; print('export OK')"`
Expected: PASS puis `export OK`.

- [ ] **Step 5: Suite complète**

Run: `cd /Users/fjacquet/Projects/crewai_custom_tools && uv run pytest -q`
Expected: PASS (tout vert).

- [ ] **Step 6: Commit**

```bash
cd /Users/fjacquet/Projects/crewai_custom_tools
git add src/crewai_custom_tools/__init__.py pyproject.toml tests/test_scaffold.py
git commit -m "feat(genealogy): export GrampsUpdateGenderTool; bump 0.11.0"
```

---

## Task 3 : Orchestration `run_gender_apply` (genecrew)

**Files:**
- Create: `genecrew/src/genecrew/gender_apply.py`
- Test: `genecrew/tests/test_gender_apply.py`

**Interfaces:**
- Consumes: `infer_sex`, `load_prenoms_table`, `GrampsUpdateGenderTool` (cct) ; `iter_people_batches`, `FactsFetcher` (genecrew).
- Produces:
  - `render_apply_report(scope, date, applied, below, errors, dry_run, base_url="http://localhost") -> str` où `applied` = liste de `(gramps_id, personne, typ, old_int, new_int, ratio, preuve)`, `below` = `(gramps_id, personne, given, sex, ratio)`, `errors` = `(gramps_id, message)`.
  - `run_gender_apply(client, scope, output_dir, *, date, min_ratio=0.98, batch_size=25, limit=None, dry_run=False, table=None) -> Path`.

- [ ] **Step 1: Écrire les tests qui échouent**

Créer `genecrew/tests/test_gender_apply.py` :
```python
"""Tests de l'application des corrections de genre (write gated)."""

import json

import httpx
import pytest

from crewai_custom_tools.tools.genealogy.gramps.client import GrampsClient, GrampsConfig

from genecrew.gender_apply import render_apply_report, run_gender_apply

CONFIG = GrampsConfig(api_url="http://g.test/api", username="u", password="p")


@pytest.fixture(autouse=True)
def _no_global_dry_run(monkeypatch):
    """Tests déterministes : neutralise un GENECREW_DRY_RUN ambiant."""
    monkeypatch.delenv("GENECREW_DRY_RUN", raising=False)


PEOPLE = [
    {"handle": "h1", "gramps_id": "I0001", "gender": 2,          # inconnu -> F (écrit)
     "primary_name": {"first_name": "Suzanne", "surname_list": [{"surname": "Martin"}]}},
    {"handle": "h2", "gramps_id": "I0002", "gender": 1,          # M mais prénom F -> contradiction (écrit)
     "primary_name": {"first_name": "Marguerite", "surname_list": [{"surname": "Dupont"}]}},
    {"handle": "h3", "gramps_id": "I0003", "gender": 2,          # inconnu, ratio 0.96 < 0.98 -> sous seuil
     "primary_name": {"first_name": "Camille", "surname_list": [{"surname": "Roy"}]}},
    {"handle": "h4", "gramps_id": "I0004", "gender": 0,          # F et prénom F -> déjà correct
     "primary_name": {"first_name": "Suzanne", "surname_list": [{"surname": "Blanc"}]}},
]
TABLE = {"SUZANNE": (9990, 10), "MARGUERITE": (11988, 12), "CAMILLE": (96, 4)}


def _people_handler(on_put):
    def handler(request):
        if request.url.path == "/api/token/":
            return httpx.Response(200, json={"access_token": "t"})
        if request.method == "GET" and request.url.path == "/api/people/":
            page = int(request.url.params.get("page", "1"))
            return httpx.Response(200, json=PEOPLE if page == 1 else [])
        if request.method == "PUT":
            return on_put(request)
        return httpx.Response(404)
    return handler


def test_run_gender_apply_writes_above_threshold(tmp_path):
    puts = []

    def on_put(request):
        puts.append(json.loads(request.content))
        return httpx.Response(200, json={})

    client = GrampsClient(CONFIG, transport=httpx.MockTransport(_people_handler(on_put)))
    report = run_gender_apply(client, "all", tmp_path, date="2026-07-18",
                              min_ratio=0.98, dry_run=False, table=TABLE)
    md = report.read_text(encoding="utf-8")
    written = {p["gramps_id"]: p["gender"] for p in puts}
    assert written == {"I0001": 0, "I0002": 0}      # inconnu + contradiction écrits ; pas Camille/déjà-correct
    assert "Genres écrits : 2" in md
    assert "Camille" in md                           # listé sous le seuil


def test_run_gender_apply_dry_run_writes_nothing(tmp_path):
    def on_put(request):
        raise AssertionError("aucun PUT attendu en dry-run")

    client = GrampsClient(CONFIG, transport=httpx.MockTransport(_people_handler(on_put)))
    report = run_gender_apply(client, "all", tmp_path, date="2026-07-18",
                              dry_run=True, table=TABLE)
    md = report.read_text(encoding="utf-8")
    assert "simulation" in md and "Genres écrits : 2" in md   # cibles listées, pas écrites


def test_render_apply_report_sections_and_links():
    md = render_apply_report(
        "all", "2026-07-18",
        applied=[("I0001", "Suzanne Martin", "genre_inconnu", 2, 0, 0.999, "« SUZANNE » : 99.9% F")],
        below=[("I0003", "Camille Roy", "Camille", "F", 0.96)],
        errors=[("I0009", "boom")],
        dry_run=False)
    assert "[I0001](http://localhost/person/I0001)" in md
    assert "genre_inconnu" in md and "Camille" in md and "boom" in md
```

- [ ] **Step 2: Lancer — il échoue**

Run: `cd /Users/fjacquet/Projects/genecrew && uv run python -m pytest genecrew/tests/test_gender_apply.py -q`
Expected: FAIL (`ModuleNotFoundError: genecrew.gender_apply`).

- [ ] **Step 3: Implémenter `gender_apply.py`**

Créer `genecrew/src/genecrew/gender_apply.py` :
```python
"""Apply gender corrections to Gramps (write) from live re-inference.

Unlike `genecrew gender` (read-only), this WRITES a fact: it re-infers each
person's sex from the INSEE+OFS table and, above a confidence threshold, sets
the gender in Gramps (fills unknowns, corrects contradictions). Bounded,
reversible, gated by dry_run + GENECREW_DRY_RUN (ADR 0009).
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path

from crewai_custom_tools.tools.genealogy.analysis.gender import infer_sex, load_prenoms_table
from crewai_custom_tools.tools.genealogy.gramps.client import GrampsClient
from crewai_custom_tools.tools.genealogy.gramps.write_tools import GrampsUpdateGenderTool

from genecrew.batching import iter_people_batches
from genecrew.facts import FactsFetcher

_SEX_TO_INT = {"F": 0, "M": 1}
_INT_TO_SEX = {0: "F", 1: "M", 2: "U"}


def _link(gramps_id: str, base_url: str) -> str:
    return f"[{gramps_id}]({base_url}/person/{gramps_id})"


def render_apply_report(scope, date, applied, below, errors, dry_run,
                        base_url="http://localhost") -> str:
    """Pure Markdown report of gender writes (applied / below threshold / errors)."""
    mode = "simulation (dry-run, aucune écriture)" if dry_run else "écritures appliquées"
    lines = [f"# Application des corrections de genre — {scope} — {date}", "",
             f"Mode : {mode}.", "",
             f"- Genres écrits : {len(applied)}",
             f"- Sous le seuil (≥ 0.95 mais < seuil, non écrits) : {len(below)}",
             f"- Erreurs : {len(errors)}", "",
             "## Genres appliqués", ""]
    if applied:
        lines += ["| Personne | Nom | Type | Ancien | Nouveau | Ratio | Preuve |",
                  "|---|---|---|---|---|---|---|"]
        for gid, personne, typ, old_i, new_i, ratio, preuve in applied:
            lines.append(f"| {_link(gid, base_url)} | {personne} | {typ} | {_INT_TO_SEX[old_i]} "
                         f"| {_INT_TO_SEX[new_i]} | {ratio:.3f} | {preuve} |")
    else:
        lines.append("Aucune écriture.")
    lines += ["", "## Sous le seuil", ""]
    if below:
        lines += ["| Personne | Nom | Prénom | Sexe inféré | Ratio |", "|---|---|---|---|---|"]
        for gid, personne, given, sex, ratio in below:
            lines.append(f"| {_link(gid, base_url)} | {personne} | {given} | {sex} | {ratio:.3f} |")
    else:
        lines.append("Aucun.")
    lines += ["", "## Erreurs", ""]
    if errors:
        lines += ["| Personne | Erreur |", "|---|---|"]
        for gid, msg in errors:
            lines.append(f"| {_link(gid, base_url)} | {msg} |")
    else:
        lines.append("Aucune erreur.")
    lines.append("")
    return "\n".join(lines)


def run_gender_apply(client: GrampsClient, scope: str, output_dir, *, date: str,
                     min_ratio: float = 0.98, batch_size: int = 25,
                     limit: int | None = None, dry_run: bool = False,
                     table: Mapping[str, tuple[int, int]] | None = None) -> Path:
    """Re-infer sex live over `scope` and WRITE genders above `min_ratio`. Gated/reversible."""
    output_dir = Path(output_dir)
    if table is None:
        table = load_prenoms_table()
    fetcher = FactsFetcher(client)
    tool = GrampsUpdateGenderTool()
    applied: list = []
    below: list = []
    errors: list = []

    for batch in iter_people_batches(client, fetcher, scope, batch_size, limit):
        for p in batch:
            inf = infer_sex(p.given, table)
            if inf.sex is None:
                continue
            if not (p.sex == "U" or inf.sex != p.sex):
                continue                                        # déjà correct
            if inf.ratio < min_ratio:
                below.append((p.gramps_id, p.name, p.given, inf.sex, inf.ratio))
                continue
            typ = "genre_inconnu" if p.sex == "U" else "genre_contradiction"
            preuve = f"« {inf.key} » : {inf.ratio * 100:.1f}% {inf.sex} sur {inf.total} (INSEE+OFS)"
            payload = json.loads(tool._run(handle=p.handle,
                                           gender=_SEX_TO_INT[inf.sex], dry_run=dry_run))
            if payload["success"]:
                d = payload["data"]
                applied.append((p.gramps_id, p.name, typ, d["old"], d["new"], inf.ratio, preuve))
            else:
                errors.append((p.gramps_id, payload["error"]))

    out = output_dir / "inference"
    out.mkdir(parents=True, exist_ok=True)
    scope_slug = scope.replace(":", "_")
    path = out / f"{date}_genres_appliques_{scope_slug}.md"
    path.write_text(render_apply_report(scope, date, applied, below, errors, dry_run),
                    encoding="utf-8")
    return path
```

- [ ] **Step 4: Lancer — il passe**

Run: `cd /Users/fjacquet/Projects/genecrew && uv run python -m pytest genecrew/tests/test_gender_apply.py -q && uv run ruff check genecrew/src/genecrew/gender_apply.py`
Expected: PASS (3 passed) puis ruff `[]`.

- [ ] **Step 5: Commit**

```bash
cd /Users/fjacquet/Projects/genecrew
git add genecrew/src/genecrew/gender_apply.py genecrew/tests/test_gender_apply.py
git commit -m "feat(gender): run_gender_apply — écriture de genre gated (inconnus + contradictions)"
```

---

## Task 4 : Sous-commande CLI `gender-apply` (genecrew)

**Files:**
- Modify: `genecrew/src/genecrew/main.py`
- Test: `genecrew/tests/test_cli_gender_apply.py`

**Interfaces:**
- Consumes: `run_gender_apply` (Task 3).
- Produces: sous-commande `gender-apply` avec `--scope` (défaut `all`), `--min-ratio` (float, défaut `0.98`), `--limit`, `--dry-run`, `--date`.

- [ ] **Step 1: Écrire le test qui échoue**

Créer `genecrew/tests/test_cli_gender_apply.py` :
```python
import subprocess
import sys


def test_gender_apply_help_lists_options():
    out = subprocess.run(
        [sys.executable, "-m", "genecrew.main", "gender-apply", "--help"],
        capture_output=True, text=True, cwd="genecrew/src",
    )
    assert out.returncode == 0
    assert "--scope" in out.stdout and "--min-ratio" in out.stdout and "--dry-run" in out.stdout
```

- [ ] **Step 2: Lancer — il échoue**

Run: `cd /Users/fjacquet/Projects/genecrew && uv run python -m pytest genecrew/tests/test_cli_gender_apply.py -q`
Expected: FAIL (`gender-apply` non reconnue → returncode 2).

- [ ] **Step 3: Câbler la sous-commande**

Dans `genecrew/src/genecrew/main.py`, ajouter la fonction après `gender_cmd` :
```python
def gender_apply_cmd(args) -> None:
    """Apply high-confidence gender corrections (write); print the report path."""
    from pathlib import Path

    from crewai_custom_tools.tools.genealogy.gramps.client import (
        GrampsClient,
        GrampsConfig,
    )

    from genecrew.gender_apply import run_gender_apply

    client = GrampsClient(GrampsConfig.from_env())
    output_dir = Path(os.environ.get("GENECREW_OUTPUT_DIR", "output"))
    date = args.date or __import__("datetime").date.today().isoformat()
    report = run_gender_apply(client, args.scope, output_dir, date=date,
                              min_ratio=args.min_ratio, limit=args.limit, dry_run=args.dry_run)
    print(f"Rapport : {report}")
```

Dans `main()`, après le bloc du subparser `gender_p` (et avant `args = parser.parse_args()`) :
```python
    apply_p = sub.add_parser("gender-apply",
                             help="Applique (écrit) les corrections de genre à haute confiance")
    apply_p.add_argument("--scope", default="all", help="all | person:ID")
    apply_p.add_argument("--min-ratio", type=float, default=0.98,
                         help="seuil de confiance pour écrire (défaut 0.98)")
    apply_p.add_argument("--limit", type=int, default=None, help="limiter à N personnes")
    apply_p.add_argument("--dry-run", action="store_true", help="simuler sans écrire")
    apply_p.add_argument("--date", default=None, help="date du rapport (défaut : aujourd'hui)")
```

Dans le dispatch, après `elif args.command == "gender":` … ajouter :
```python
    elif args.command == "gender-apply":
        gender_apply_cmd(args)
```

- [ ] **Step 4: Lancer — il passe (+ non-régression)**

Run: `cd /Users/fjacquet/Projects/genecrew && uv run python -m pytest genecrew/tests/test_cli_gender_apply.py genecrew/tests/test_cli_gender.py genecrew/tests/test_cli_names.py -q`
Expected: PASS (3 passed).

- [ ] **Step 5: Commit**

```bash
cd /Users/fjacquet/Projects/genecrew
git add genecrew/src/genecrew/main.py genecrew/tests/test_cli_gender_apply.py
git commit -m "feat(gender): sous-commande CLI genecrew gender-apply"
```

---

## Task 5 : ADR 0009, guide, sync du lockfile (genecrew)

**Files:**
- Create: `docs/adr/0009-ecritures-genre-haute-confiance.md`
- Modify: `docs/USER_GUIDE.md`, `CLAUDE.md`, `uv.lock`

- [ ] **Step 1: ADR 0009**

Créer `docs/adr/0009-ecritures-genre-haute-confiance.md` :
```markdown
# 0009 — Écritures de genre bornées à haute confiance

| | |
|---|---|
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
```

- [ ] **Step 2: Section USER_GUIDE**

Ajouter à `docs/USER_GUIDE.md` (après la section « Inférence de genre ») :
```markdown
## Appliquer les corrections de genre (écriture)

Écrit dans Gramps les corrections de genre à haute confiance : remplit les genres inconnus et
corrige les contradictions, au-dessus d'un seuil (défaut 0.98) sur la table INSEE+OFS. **Écrit une
donnée cœur** (ADR 0009) — réversible via l'historique des transactions Gramps.

```bash
# 1) Simuler d'abord (aucune écriture) et relire le rapport :
cd genecrew && uv run genecrew gender-apply --scope all --dry-run
# 2) Écrire pour de vrai (nécessite GENECREW_DRY_RUN=false dans .env) :
cd genecrew && uv run genecrew gender-apply --scope all
```

Rapport dans `output/inference/*_genres_appliques_*.md` : genres écrits, cas sous le seuil, erreurs.
Le global `GENECREW_DRY_RUN=true` (défaut du `.env`) force la simulation quel que soit le flag.
```

- [ ] **Step 3: CLAUDE.md (commande)**

Dans `CLAUDE.md` (genecrew), section Commands, ajouter sous la ligne `genecrew gender` :
```bash
cd genecrew && uv run genecrew gender-apply --dry-run          # applique les corrections de genre (write, ADR 0009)
```

- [ ] **Step 4: Sync du lockfile (cct 0.11.0)**

Run: `cd /Users/fjacquet/Projects/genecrew && uv sync -q && uv run python -m pytest genecrew/tests/ -q`
Expected: `uv.lock` référence `crewai-custom-tools` en `0.11.0` ; tous les tests genecrew passent.

- [ ] **Step 5: Commit**

```bash
cd /Users/fjacquet/Projects/genecrew
git add docs/adr/0009-ecritures-genre-haute-confiance.md docs/USER_GUIDE.md CLAUDE.md uv.lock
git commit -m "docs(gender): ADR 0009 écritures de genre + guide + sync lockfile 0.11.0"
```

---

## Notes d'exécution finale (après les 5 tâches)

1. Revue finale de branche sur chaque dépôt (superpowers:requesting-code-review).
2. Vérification réelle (optionnelle, données live) : `cd genecrew && uv run genecrew gender-apply --dry-run --limit 50` puis relecture du rapport.
3. Finir via superpowers:finishing-a-development-branch : merger cct (`feat/genealogy-gender-write`) **puis** genecrew (`feat/gender-apply`) dans `main`, tests verts après chaque merge.
