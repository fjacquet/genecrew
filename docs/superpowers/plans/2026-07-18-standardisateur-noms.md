# Standardisateur de noms — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Normaliser la casse des noms (patronymes + prénoms en capitales) de l'arbre Gramps par écriture directe protégée par un invariant de casse, et lister à part les noms « ? »/à chiffres.

**Architecture:** Fonctions pures de casse dans `crewai_custom_tools` + un outil d'écriture `GrampsUpdateNameTool` (GET → recase → PUT, refuse tout changement non purement de casse). Dans `genecrew`, une commande `genecrew names` réutilise l'infra de lecture de l'audit (batches de PersonFacts) et pilote l'outil, produisant un rapport + une liste de noms incomplets. C'est le **premier composant qui écrit** dans Gramps.

**Tech Stack:** Python 3.12, uv, Pydantic v2, crewai.tools.BaseTool, httpx, pytest + pytest-mock + httpx.MockTransport. Spec : `docs/superpowers/specs/2026-07-18-standardisateur-noms-design.md`.

## Global Constraints

- **`uv` pour tout** : `uv sync`, `uv run` — jamais `pip`/`python` directs.
- **Deux dépôts, deux branches** : tâches 1–3 dans `/Users/fjacquet/Projects/crewai_custom_tools` (branche `feat/genealogy-name-standardizer`, partant de `main`) ; tâches 4–7 dans `/Users/fjacquet/Projects/genecrew` (branche `feat/name-standardizer`, partant de `main`).
- **Principe forme vs fait** : la casse est de la forme (aucune preuve requise) → écriture directe. **Invariant de casse** obligatoire : aucune écriture si `old.casefold() != new.casefold()`. Les noms « ? »/à chiffres sont des faits incomplets → **listés, jamais écrits**.
- **Cible restreinte** : ne normaliser que les noms entièrement capitales ou entièrement minuscules (`needs_normalization`) ; ne jamais toucher une casse déjà mixte.
- Conventions crewai_custom_tools (`CLAUDE.md`) : `_run` renvoie l'enveloppe `ok()/err()` ; `@api_tool` sur les `_run` ; tests 100 % hors-ligne ; export `BaseTool` dans `__all__` ; bump `__version__`+`pyproject.toml`+`test_scaffold.py` en lockstep ; fichiers ≤ 500 lignes.
- **Structure Gramps** (vérifiée en direct) : `person["primary_name"]["first_name"]` (str) et `person["primary_name"]["surname_list"]` (liste de `{surname, prefix, connector, origintype, primary}`). On recase **uniquement** la chaîne `surname` (jamais le `prefix`). `PUT /api/people/{handle}` avec l'objet complet.
- **Défaut = écriture réelle** (choix utilisateur) ; `--dry-run` en option pour un aperçu. Le tool prend un paramètre `dry_run` explicite (il ne lit pas d'env).

---

### Task 1 : Fonctions pures de casse

**Files:**
- Create: `src/crewai_custom_tools/tools/genealogy/standardize/__init__.py`
- Create: `src/crewai_custom_tools/tools/genealogy/standardize/names.py`
- Test: `tests/test_genealogy_names.py`

**Interfaces:**
- Produces (consommé par T2 et genecrew) : `normalize_case(name: str) -> str`, `needs_normalization(name: str) -> bool`, `is_case_only_change(old: str, new: str) -> bool`, `is_incomplete_name(name: str) -> bool`.

- [ ] **Step 1 : Écrire les tests qui échouent**

`tests/test_genealogy_names.py` :

```python
"""Tests par table des fonctions pures de normalisation de casse."""

import pytest

from crewai_custom_tools.tools.genealogy.standardize.names import (
    is_case_only_change,
    is_incomplete_name,
    needs_normalization,
    normalize_case,
)


@pytest.mark.parametrize("raw, expected", [
    ("JACQUET", "Jacquet"),
    ("BERNARD DE SAINT-AFFRIQUE", "Bernard de Saint-Affrique"),
    ("D'ABBADIE D'ARRAST", "d'Abbadie d'Arrast"),
    ("SAINT-AFFRIQUE", "Saint-Affrique"),
    ("MACDONALD", "MacDonald"),
    ("O'BRIEN", "O'Brien"),
    ("DE LA TOUR", "de la Tour"),
    ("", ""),
])
def test_normalize_case(raw, expected):
    assert normalize_case(raw) == expected


@pytest.mark.parametrize("name, expected", [
    ("JACQUET", True),      # tout capitales
    ("jacquet", True),      # tout minuscules
    ("Jacquet", False),     # déjà casse mixte
    ("van Beethoven", False),
    ("", False),
    ("18", False),          # pas de lettre
])
def test_needs_normalization(name, expected):
    assert needs_normalization(name) is expected


def test_is_case_only_change():
    assert is_case_only_change("JACQUET", "Jacquet") is True
    assert is_case_only_change("JACQUET", "Jacque") is False   # lettre perdue
    assert is_case_only_change("A  B", "A B") is False         # espace changé


@pytest.mark.parametrize("name, expected", [
    ("?, Suzanne", True),
    ("Louis 3", True),
    ("Jacquet", False),
])
def test_is_incomplete_name(name, expected):
    assert is_incomplete_name(name) is expected
```

- [ ] **Step 2 : Vérifier l'échec**

```bash
cd /Users/fjacquet/Projects/crewai_custom_tools
uv run python -m pytest tests/test_genealogy_names.py -v
```
Attendu : ÉCHEC — `ModuleNotFoundError` sur `standardize.names`.

- [ ] **Step 3 : Implémenter**

`src/crewai_custom_tools/tools/genealogy/standardize/__init__.py` :

```python
"""Deterministic standardization helpers (name casing; places later)."""
```

`src/crewai_custom_tools/tools/genealogy/standardize/names.py` :

```python
"""Pure French-aware name-casing normalization.

Casing is *form*, not a factual claim, so these functions never assert new
data — they only decide capitalization. The invariant `is_case_only_change`
guarantees a write can re-capitalize but never re-spell.
"""

from __future__ import annotations

# Particules abaissées quand elles forment un mot entier (français + néerlandais/allemand).
PARTICLES = frozenset({
    "de", "du", "des", "la", "le", "les",
    "von", "van", "der", "den", "ten", "ter", "zur", "zum", "y",
})


def _cap(word: str) -> str:
    """First letter upper, rest lower (single segment, no separators)."""
    return word[:1].upper() + word[1:].lower() if word else word


def _recase_token(token: str) -> str:
    """Recase one space-delimited token, handling hyphens, apostrophes, Mc/Mac."""
    if "-" in token:
        return "-".join(_recase_token(part) for part in token.split("-"))
    if "'" in token:
        prefix, _, rest = token.partition("'")
        if prefix.lower() in ("d", "l"):          # particule élidée d'/l'
            return prefix.lower() + "'" + _recase_token(rest)
        return _cap(prefix) + "'" + _recase_token(rest)   # O'Brien
    return _cap(token)


def normalize_case(name: str) -> str:
    """Return `name` with French-aware title casing."""
    out = []
    for word in name.split():
        out.append(word.lower() if word.lower() in PARTICLES else _recase_token(word))
    return " ".join(out)


def needs_normalization(name: str) -> bool:
    """True only when `name`'s letters are all upper or all lower (import artifacts)."""
    letters = [c for c in name if c.isalpha()]
    if not letters:
        return False
    return all(c.isupper() for c in letters) or all(c.islower() for c in letters)


def is_case_only_change(old: str, new: str) -> bool:
    """The safety invariant: `new` differs from `old` only by capitalization."""
    return old.casefold() == new.casefold()


def is_incomplete_name(name: str) -> bool:
    """True if the name carries a placeholder '?' or a digit (incomplete fact)."""
    return "?" in name or any(c.isdigit() for c in name)
```

- [ ] **Step 4 : Vérifier le succès**

```bash
uv run python -m pytest tests/test_genealogy_names.py -v
```
Attendu : tous PASS (8 + 6 + 1 + 3 cas paramétrés).

- [ ] **Step 5 : Commit**

```bash
git add src/crewai_custom_tools/tools/genealogy/standardize/ tests/test_genealogy_names.py
git commit -m "feat(genealogy): pure French-aware name casing helpers"
```

---

### Task 2 : Outil d'écriture `GrampsUpdateNameTool`

**Files:**
- Create: `src/crewai_custom_tools/tools/genealogy/gramps/write_tools.py`
- Test: `tests/test_genealogy_write_tools.py`

**Interfaces:**
- Consumes : `get_client()` (Phase 0), les fonctions de T1.
- Produces (exporté en T3, consommé par genecrew) : `GrampsUpdateNameTool` (`BaseTool`). `_run(handle: str, dry_run: bool = False) -> str` renvoie l'enveloppe `ok()/err()`. En succès : `ok({"handle", "gramps_id", "dry_run", "changes": [{"field","old","new"}, ...]})`. Refuse (via l'invariant) tout champ non purement de casse.

- [ ] **Step 1 : Écrire les tests qui échouent**

`tests/test_genealogy_write_tools.py` :

```python
"""Tests hors-ligne de GrampsUpdateNameTool (client mické)."""

import json

import httpx

from crewai_custom_tools.tools.genealogy.gramps.client import GrampsClient, GrampsConfig
from crewai_custom_tools.tools.genealogy.gramps.write_tools import GrampsUpdateNameTool

CONFIG = GrampsConfig(api_url="http://g.test/api", username="u", password="p")

PERSON = {
    "handle": "h1", "gramps_id": "I0001", "gender": 1,
    "primary_name": {"first_name": "FREDERIC",
                     "surname_list": [{"surname": "JACQUET", "prefix": "", "primary": True}]},
}


def _mock(mocker, handler, captured=None):
    client = GrampsClient(CONFIG, transport=httpx.MockTransport(handler))
    mocker.patch(
        "crewai_custom_tools.tools.genealogy.gramps.write_tools.get_client",
        return_value=client,
    )


def test_update_name_writes_case_fix(mocker):
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
    payload = json.loads(GrampsUpdateNameTool()._run(handle="h1"))
    assert payload["success"] is True
    assert payload["data"]["dry_run"] is False
    by_field = {c["field"]: c for c in payload["data"]["changes"]}
    # prénom et nom sont des champs DISTINCTS, chacun étiqueté par son kind
    assert by_field["first_name"]["kind"] == "prénom"
    assert (by_field["first_name"]["old"], by_field["first_name"]["new"]) == ("FREDERIC", "Frederic")
    assert by_field["surname[0]"]["kind"] == "nom"
    assert (by_field["surname[0]"]["old"], by_field["surname[0]"]["new"]) == ("JACQUET", "Jacquet")
    # le PUT a bien envoyé la casse corrigée
    assert puts and puts[0]["primary_name"]["first_name"] == "Frederic"
    assert puts[0]["primary_name"]["surname_list"][0]["surname"] == "Jacquet"


def test_update_name_dry_run_does_not_put(mocker):
    def handler(request):
        if request.url.path == "/api/token/":
            return httpx.Response(200, json={"access_token": "t"})
        if request.method == "GET":
            return httpx.Response(200, json=PERSON)
        raise AssertionError("aucun PUT attendu en dry_run")

    _mock(mocker, handler)
    payload = json.loads(GrampsUpdateNameTool()._run(handle="h1", dry_run=True))
    assert payload["success"] is True and payload["data"]["dry_run"] is True
    assert len(payload["data"]["changes"]) == 2


def test_update_name_no_change_when_already_mixed(mocker):
    already = {"handle": "h2", "gramps_id": "I0002",
               "primary_name": {"first_name": "Jean",
                                 "surname_list": [{"surname": "Dupont", "primary": True}]}}

    def handler(request):
        if request.url.path == "/api/token/":
            return httpx.Response(200, json={"access_token": "t"})
        if request.method == "GET":
            return httpx.Response(200, json=already)
        raise AssertionError("aucun PUT attendu si rien à changer")

    _mock(mocker, handler)
    payload = json.loads(GrampsUpdateNameTool()._run(handle="h2"))
    assert payload["success"] is True and payload["data"]["changes"] == []
```

- [ ] **Step 2 : Vérifier l'échec**

```bash
uv run python -m pytest tests/test_genealogy_write_tools.py -v
```
Attendu : ÉCHEC — module `write_tools` absent.

- [ ] **Step 3 : Implémenter**

`src/crewai_custom_tools/tools/genealogy/gramps/write_tools.py` :

```python
"""Write-side CrewAI tools over the Gramps Web API.

First writer in the genealogy domain. GrampsUpdateNameTool re-capitalizes a
person's primary name in place and refuses any change that is not purely a
casing change (the invariant), so it can never re-spell a name.
"""

import logging

from crewai.tools import BaseTool
from pydantic import BaseModel, Field

from crewai_custom_tools.core.decorators import api_tool
from crewai_custom_tools.core.results import err, ok
from crewai_custom_tools.tools.genealogy.gramps.client import get_client
from crewai_custom_tools.tools.genealogy.standardize.names import (
    is_case_only_change,
    needs_normalization,
    normalize_case,
)

logger = logging.getLogger(__name__)


class GrampsUpdateNameInput(BaseModel):
    """Input schema for GrampsUpdateNameTool."""

    handle: str = Field(..., description="Handle of the person whose primary name to re-case.")
    dry_run: bool = Field(False, description="If true, compute the changes but do not write.")


class GrampsUpdateNameTool(BaseTool):
    """Re-capitalize a person's primary name (casing only; never re-spells)."""

    name: str = "gramps_update_name_case"
    description: str = (
        "Normalizes the capitalization of one person's primary name (first name and "
        "surnames) in Gramps. Only changes casing — refuses any change that alters the "
        "letters. Writes directly unless dry_run is set."
    )
    args_schema: type[BaseModel] = GrampsUpdateNameInput

    @api_tool(provider="GrampsWeb", endpoint="UpdateName")
    def _run(self, handle: str, dry_run: bool = False) -> str:
        client = get_client()
        person = client.get_object("people", handle)
        name = person.get("primary_name") or {}
        changes = []

        # Prénom (first_name) et nom (surname_list) sont traités comme deux champs
        # DISTINCTS ; chaque changement porte son `kind` ("prénom" / "nom").
        first = name.get("first_name", "")
        if needs_normalization(first):
            new_first = normalize_case(first)
            if new_first != first:
                if not is_case_only_change(first, new_first):
                    return err(f"gramps_update_name_case: {handle} first_name non purement de casse")
                name["first_name"] = new_first
                changes.append({"field": "first_name", "kind": "prénom",
                                "old": first, "new": new_first})

        for idx, entry in enumerate(name.get("surname_list") or []):
            surname = entry.get("surname", "")
            if not needs_normalization(surname):
                continue
            new_surname = normalize_case(surname)
            if new_surname == surname:
                continue
            if not is_case_only_change(surname, new_surname):
                return err(f"gramps_update_name_case: {handle} surname[{idx}] non purement de casse")
            entry["surname"] = new_surname
            changes.append({"field": f"surname[{idx}]", "kind": "nom",
                            "old": surname, "new": new_surname})

        result = {"handle": handle, "gramps_id": person.get("gramps_id"),
                  "dry_run": dry_run, "changes": changes}
        if changes and not dry_run:
            client.request("PUT", f"/people/{handle}", json=person)
        return ok(result)
```

- [ ] **Step 4 : Vérifier le succès**

```bash
uv run python -m pytest tests/test_genealogy_write_tools.py -v
```
Attendu : 3 PASS.

- [ ] **Step 5 : Commit**

```bash
git add src/crewai_custom_tools/tools/genealogy/gramps/write_tools.py tests/test_genealogy_write_tools.py
git commit -m "feat(genealogy): GrampsUpdateNameTool (case-only name write, dry_run)"
```

---

### Task 3 : Export + bump de version 0.9.0

**Files:**
- Modify: `src/crewai_custom_tools/__init__.py` (import + `__all__` + `__version__`)
- Modify: `pyproject.toml` (version)
- Modify: `tests/test_scaffold.py` (version attendue)

**Interfaces:**
- Produces : `from crewai_custom_tools import GrampsUpdateNameTool` fonctionne. Les fonctions pures de `standardize.names` restent importées par chemin de module (pas dans `__all__`).

- [ ] **Step 1 : Ajouter l'export**

Dans `src/crewai_custom_tools/__init__.py`, dans le groupe Genealogy Tools, ajouter l'import
`from crewai_custom_tools.tools.genealogy.gramps.write_tools import GrampsUpdateNameTool` et
le nom `GrampsUpdateNameTool` dans `__all__` (ordre alphabétique du groupe).

- [ ] **Step 2 : Bump 0.8.1 → 0.9.0** dans `__init__.py`, `pyproject.toml`, et l'attente de `tests/test_scaffold.py`.

- [ ] **Step 3 : Smoke + suite**

```bash
uv run python -c "from crewai_custom_tools import GrampsUpdateNameTool; import crewai_custom_tools as c; print(c.__version__)"
uv run python -m pytest -q
```
Attendu : `0.9.0` ; toute la suite passe.

- [ ] **Step 4 : Commit**

```bash
git add src/crewai_custom_tools/__init__.py pyproject.toml tests/test_scaffold.py
git commit -m "feat(genealogy): export GrampsUpdateNameTool; bump to 0.9.0"
```

---

### Task 4 : genecrew — itérateur de personnes partagé (`batching.py`)

> À partir d'ici : dépôt `/Users/fjacquet/Projects/genecrew`, branche `feat/name-standardizer`.

**Files:**
- Create: `genecrew/src/genecrew/batching.py`
- Modify: `genecrew/src/genecrew/audit.py` (utiliser le module partagé)
- Test: `genecrew/tests/test_batching.py`

**Interfaces:**
- Produces (consommé par `audit.py` et `names.py`) : `iter_people_batches(client, fetcher, scope, batch_size, limit) -> Iterator[list[PersonFacts]]` — extrait tel quel de l'actuel `_people_batches` d'`audit.py`.

**Contexte** : `audit.py` contient une fonction privée `_people_batches(client, fetcher, scope, batch_size, limit)` qui produit les lots de `PersonFacts` (bulk pour `all`, single pour `person:`). Le standardisateur en a besoin aussi → on l'extrait (DRY).

- [ ] **Step 1 : Test qui échoue** — `genecrew/tests/test_batching.py` :

```python
import httpx

from genecrew.batching import iter_people_batches
from genecrew.facts import FactsFetcher
from crewai_custom_tools.tools.genealogy.gramps.client import GrampsClient, GrampsConfig

CONFIG = GrampsConfig(api_url="http://g.test/api", username="u", password="p")

PERSON = {
    "gramps_id": "I0001", "handle": "h1", "gender": 1, "citation_list": ["c"],
    "family_list": [], "parent_family_list": [], "birth_ref_index": -1, "death_ref_index": -1,
    "primary_name": {"first_name": "Jean", "surname_list": [{"surname": "Test"}]},
    "profile": {}, "event_ref_list": [], "extended": {"events": []},
}


def test_iter_all_scope_bulk():
    def handler(request):
        if request.url.path == "/api/token/":
            return httpx.Response(200, json={"access_token": "t"})
        page = int(request.url.params.get("page", 1))
        return httpx.Response(200, json=[PERSON] if page == 1 else [])

    client = GrampsClient(CONFIG, transport=httpx.MockTransport(handler))
    batches = list(iter_people_batches(client, FactsFetcher(client), "all", 25, None))
    assert len(batches) == 1 and batches[0][0].gramps_id == "I0001"
```

- [ ] **Step 2 : Vérifier l'échec** :
```bash
cd /Users/fjacquet/Projects/genecrew
uv run python -m pytest genecrew/tests/test_batching.py -v
```
Attendu : ÉCHEC — module `batching` absent.

- [ ] **Step 3 : Créer `genecrew/src/genecrew/batching.py`** — déplacer le corps de `_people_batches` d'`audit.py` :

```python
"""Shared people-batch iterator over a scope (bulk for 'all', single for 'person:')."""

from __future__ import annotations

from crewai_custom_tools.tools.genealogy.gramps.client import GrampsClient

from genecrew.facts import FactsFetcher
from genecrew.scope import parse_scope, resolve_handles


def iter_people_batches(client: GrampsClient, fetcher: FactsFetcher,
                        scope: str, batch_size: int, limit: int | None):
    """Yield successive batches of PersonFacts for `scope`."""
    kind, _gid = parse_scope(scope)
    if kind != "all":
        handles = resolve_handles(client, scope)
        people = [p for h, _ in handles
                  if (p := fetcher.get_person_facts(h)) is not None]
        if people:
            yield people
        return
    fetched = 0
    page = 1
    while True:
        people = fetcher.list_people_facts(page, batch_size)
        if not people:
            break
        if limit is not None and fetched + len(people) > limit:
            people = people[: limit - fetched]
        yield people
        fetched += len(people)
        if limit is not None and fetched >= limit:
            break
        page += 1
```

Puis dans `genecrew/src/genecrew/audit.py` : supprimer la fonction `_people_batches` et son
usage `for batch_people in _people_batches(client, fetcher, scope, batch_size, limit):` →
remplacer par `from genecrew.batching import iter_people_batches` (en tête) et
`for batch_people in iter_people_batches(client, fetcher, scope, batch_size, limit):`. Retirer
de `audit.py` les imports devenus inutiles (`parse_scope`, `resolve_handles` s'ils ne servent
plus qu'à `_people_batches` — vérifier).

- [ ] **Step 4 : Vérifier** :
```bash
uv run python -m pytest genecrew/tests/test_batching.py genecrew/tests/test_audit.py -v
```
Attendu : le nouveau test PASS **et** les tests d'audit existants PASS (comportement inchangé).

- [ ] **Step 5 : Commit**
```bash
git add genecrew/src/genecrew/batching.py genecrew/src/genecrew/audit.py genecrew/tests/test_batching.py
git commit -m "refactor(audit): extract shared iter_people_batches"
```

---

### Task 5 : genecrew — orchestration `names.py`

**Files:**
- Create: `genecrew/src/genecrew/names.py`
- Test: `genecrew/tests/test_names.py`

**Interfaces:**
- Consumes : `iter_people_batches` (T4), `FactsFetcher`, `GrampsUpdateNameTool`, les fonctions pures de T1.
- Produces : `render_names_report(scope, date, results, incomplete, dry_run) -> str` (pur) ; `run_names(client, scope, output_dir, *, date, batch_size=25, limit=None, dry_run=False) -> tuple[Path, Path]` (écrit rapport + liste, rend les deux chemins).

Logique : pour chaque `PersonFacts` du lot — (a) si `is_incomplete_name(given)` ou `(surname)`, l'ajouter à la liste « à vérifier » (aucune écriture) ; (b) si `needs_normalization(given)` ou `needs_normalization(surname)`, appeler `GrampsUpdateNameTool._run(handle, dry_run)` et collecter le résultat. Limite v1 connue : le pré-filtre s'appuie sur le patronyme primaire de `PersonFacts` ; un patronyme secondaire tout-capitales sur une personne au patronyme primaire mixte ne déclenche pas l'appel (rare — noté).

- [ ] **Step 1 : Test qui échoue** — `genecrew/tests/test_names.py` :

```python
from crewai_custom_tools.tools.genealogy.models.domain import PersonFacts
from genecrew.names import render_names_report


def _pf(gid, given, surname):
    return PersonFacts(gramps_id=gid, handle=gid, name=f"{given} {surname}",
                       surname=surname, given=given, sex="U", has_any_citation=True)


def test_report_separates_prenom_and_nom():
    results = [{"gramps_id": "I0001", "dry_run": False, "changes": [
        {"field": "first_name", "kind": "prénom", "old": "FREDERIC", "new": "Frederic"},
        {"field": "surname[0]", "kind": "nom", "old": "JACQUET", "new": "Jacquet"}]}]
    incomplete = [("I0009", "nom", "?, Suzanne")]
    out = render_names_report("all", "2026-07-18", results, incomplete, dry_run=False)
    # la distinction prénom / nom est visible dans le rapport
    assert "prénom" in out and "nom" in out
    assert "FREDERIC" in out and "Frederic" in out
    assert "JACQUET" in out and "Jacquet" in out
    assert "I0009" in out and "?, Suzanne" in out
    assert "http://localhost/person/I0001" in out


def test_report_dry_run_marked():
    out = render_names_report("all", "2026-07-18", [], [], dry_run=True)
    assert "aperçu" in out.lower() or "dry" in out.lower()
```

- [ ] **Step 2 : Vérifier l'échec** :
```bash
uv run python -m pytest genecrew/tests/test_names.py -v
```
Attendu : ÉCHEC — module `names` absent.

- [ ] **Step 3 : Implémenter** — `genecrew/src/genecrew/names.py` :

```python
"""Name-casing standardization: iterate people, re-case names, report.

Casing is form, not a fact (spec §2), so changes are written directly under the
GrampsUpdateNameTool case-only invariant. Incomplete names ('?'/digits) are only
listed for human research.
"""

from __future__ import annotations

import json
from pathlib import Path

from crewai_custom_tools.tools.genealogy.gramps.client import GrampsClient
from crewai_custom_tools.tools.genealogy.gramps.write_tools import GrampsUpdateNameTool
from crewai_custom_tools.tools.genealogy.standardize.names import (
    is_incomplete_name,
    needs_normalization,
)

from genecrew.batching import iter_people_batches
from genecrew.facts import FactsFetcher


def _link(gramps_id: str, base_url: str) -> str:
    return f"[{gramps_id}]({base_url}/person/{gramps_id})"


def render_names_report(scope, date, results, incomplete, dry_run,
                        base_url="http://localhost") -> str:
    """Pure Markdown report of casing changes (applied or simulated)."""
    mode = "aperçu (dry-run, aucune écriture)" if dry_run else "écritures appliquées"
    rows = []
    for r in results:
        for c in r.get("changes", []):
            rows.append(f"| {_link(r['gramps_id'], base_url)} | {c['kind']} "
                        f"| {c['old']} | {c['new']} |")
    lines = [f"# Standardisation des noms — {scope} — {date}", "",
             f"Mode : {mode}.", "",
             f"- Personnes avec correction de casse : {len({r['gramps_id'] for r in results if r.get('changes')})}",
             f"- Corrections de casse : {len(rows)}", ""]
    lines.append("## Corrections de casse")
    lines.append("")
    if rows:
        lines += ["| Personne | Type | Avant | Après |", "|---|---|---|---|", *rows]
    else:
        lines.append("Aucune correction de casse.")
    lines.append("")
    return "\n".join(lines)


def render_incomplete_report(scope, date, incomplete, base_url="http://localhost") -> str:
    """Pure Markdown list of incomplete names ('?'/digits) — human research."""
    lines = [f"# Noms à vérifier (incomplets) — {scope} — {date}", "",
             f"- Noms « ? » ou à chiffres : {len(incomplete)}", ""]
    if incomplete:
        lines += ["| Personne | Champ | Valeur |", "|---|---|---|"]
        for gid, field, value in incomplete:
            lines.append(f"| [{gid}]({base_url}/person/{gid}) | {field} | {value} |")
    else:
        lines.append("Aucun nom incomplet.")
    lines.append("")
    return "\n".join(lines)


def run_names(client: GrampsClient, scope: str, output_dir: Path, *,
              date: str, batch_size: int = 25, limit: int | None = None,
              dry_run: bool = False) -> tuple[Path, Path]:
    """Re-case names over `scope`; write a changes report + an incomplete-names list."""
    output_dir = Path(output_dir)
    fetcher = FactsFetcher(client)
    tool = GrampsUpdateNameTool()
    results = []
    incomplete = []

    for batch in iter_people_batches(client, fetcher, scope, batch_size, limit):
        for person in batch:
            # prénom et nom restent des entrées SÉPARÉES et étiquetées
            for label, value in (("prénom", person.given), ("nom", person.surname)):
                if is_incomplete_name(value):
                    incomplete.append((person.gramps_id, label, value))
            if needs_normalization(person.given) or needs_normalization(person.surname):
                payload = json.loads(tool._run(handle=person.handle, dry_run=dry_run))
                if payload["success"]:
                    results.append(payload["data"])
                else:
                    results.append({"gramps_id": person.gramps_id, "changes": [],
                                    "error": payload["error"], "dry_run": dry_run})

    out = output_dir / "standardize"
    out.mkdir(parents=True, exist_ok=True)
    scope_slug = scope.replace(":", "_")
    report_path = out / f"{date}_noms_{scope_slug}.md"
    report_path.write_text(render_names_report(scope, date, results, incomplete, dry_run),
                           encoding="utf-8")
    incomplete_path = out / f"{date}_noms_a_verifier_{scope_slug}.md"
    incomplete_path.write_text(render_incomplete_report(scope, date, incomplete),
                               encoding="utf-8")
    return report_path, incomplete_path
```

- [ ] **Step 4 : Vérifier** :
```bash
uv run python -m pytest genecrew/tests/test_names.py -v
```
Attendu : 2 PASS.

- [ ] **Step 5 : Commit**
```bash
git add genecrew/src/genecrew/names.py genecrew/tests/test_names.py
git commit -m "feat(names): orchestration + reports for name-casing standardization"
```

---

### Task 6 : genecrew — sous-commande CLI `genecrew names`

**Files:**
- Modify: `genecrew/src/genecrew/main.py`
- Test: `genecrew/tests/test_cli_names.py`

**Interfaces:**
- Consumes : `run_names` (T5).
- Produces : `uv run genecrew names --scope all|person:ID [--limit N] [--batch-size 25] [--dry-run] [--date …]`.

- [ ] **Step 1 : Test qui échoue** — `genecrew/tests/test_cli_names.py` :

```python
import subprocess
import sys


def test_names_help_lists_options():
    out = subprocess.run(
        [sys.executable, "-m", "genecrew.main", "names", "--help"],
        capture_output=True, text=True, cwd="genecrew/src",
    )
    assert out.returncode == 0
    assert "--scope" in out.stdout and "--dry-run" in out.stdout
```

- [ ] **Step 2 : Vérifier l'échec** :
```bash
uv run python -m pytest genecrew/tests/test_cli_names.py -v
```
Attendu : ÉCHEC (sous-commande `names` inconnue).

- [ ] **Step 3 : Implémenter** — dans `genecrew/src/genecrew/main.py`, ajouter `names_cmd` :

```python
def names_cmd(args) -> None:
    """Standardize name casing over a scope; print the report paths."""
    import os
    from pathlib import Path

    from crewai_custom_tools.tools.genealogy.gramps.client import GrampsClient, GrampsConfig

    from genecrew.names import run_names

    client = GrampsClient(GrampsConfig.from_env())
    output_dir = Path(os.environ.get("GENECREW_OUTPUT_DIR", "output"))
    date = args.date or __import__("datetime").date.today().isoformat()
    report, incomplete = run_names(
        client, args.scope, output_dir, date=date,
        batch_size=args.batch_size, limit=args.limit, dry_run=args.dry_run,
    )
    print(f"Rapport : {report}")
    print(f"Noms à vérifier : {incomplete}")
```

Puis, dans `main()`, après le sous-parseur `audit`, ajouter :

```python
    names_p = sub.add_parser("names", help="Standardisation de la casse des noms")
    names_p.add_argument("--scope", default="all", help="all | person:ID")
    names_p.add_argument("--limit", type=int, default=None, help="limiter à N personnes")
    names_p.add_argument("--batch-size", type=int,
                         default=int(os.environ.get("GENECREW_BATCH_SIZE", "25")))
    names_p.add_argument("--dry-run", action="store_true",
                         help="aperçu sans écrire (défaut : écriture réelle)")
    names_p.add_argument("--date", default=None, help="date du rapport (défaut : aujourd'hui)")
```

et dans le dispatch : `elif args.command == "names": names_cmd(args)`.

- [ ] **Step 4 : Vérifier** :
```bash
uv run python -m pytest genecrew/tests/test_cli_names.py -v
uv run genecrew names --help
```
Attendu : test PASS ; l'aide liste `--scope/--limit/--batch-size/--dry-run/--date`.

- [ ] **Step 5 : Commit**
```bash
git add genecrew/src/genecrew/main.py genecrew/tests/test_cli_names.py
git commit -m "feat(names): CLI sous-commande genecrew names"
```

---

### Task 7 : Validation terrain + documentation

**Files:**
- Modify: `docs/adr/0001-ecriture-directe-encadree.md` (raffinement forme vs fait)
- Create: `docs/adr/0007-standardisation-casse-invariant.md`
- Modify: `docs/USER_GUIDE.md` (section « Standardisation — noms »)

**Interfaces:** aucune ; c'est le **critère de sortie** + la doc.

- [ ] **Step 1 : Aperçu (dry-run) sur un échantillon**

```bash
cd /Users/fjacquet/Projects/genecrew
uv sync -q   # prend crewai_custom_tools 0.9.0
uv run genecrew names --scope all --limit 200 --dry-run
```
Attendu : `output/standardize/AAAA-MM-JJ_noms_all.md` listant des recapitalisations plausibles
(patronymes capitales → casse propre ; casses mixtes ignorées), et `..._noms_a_verifier_all.md`
listant les noms « ? »/chiffres. Aucune écriture. Examiner le rapport.

- [ ] **Step 2 : Écriture réelle sur le même échantillon**

```bash
uv run genecrew names --scope all --limit 200
```
**Critère de sortie** : les corrections sont visibles dans Gramps Web (patronymes recapitalisés)
et dans l'historique des transactions (`GET /api/transactions/history/`), chacune ne modifiant
que la casse. Si le compte renvoie 403 en écriture, l'utilisateur bascule sur un compte Gramps
au rôle Editor (noter dans le rapport de tâche). Vérifier qu'aucune casse mixte préexistante
n'a été touchée.

- [ ] **Step 3 : Suites de test des deux dépôts**

```bash
uv run python -m pytest genecrew/tests/ -q
(cd /Users/fjacquet/Projects/crewai_custom_tools && uv run python -m pytest -q)
```
Attendu : tout passe.

- [ ] **Step 4 : Documentation**
- `docs/adr/0001-ecriture-directe-encadree.md` : ajouter une note de raffinement — la preuve est
  requise pour les **faits**, pas pour la **forme** ; les écritures purement formelles (casse,
  garanties par l'invariant `is_case_only_change`) sont autorisées en direct.
- `docs/adr/0007-standardisation-casse-invariant.md` (Contexte / Décision / Conséquences,
  Statut Accepté, date 2026-07-18) : décision d'écrire la casse directement, protégée par
  l'invariant ; cible restreinte (tout-capitales/minuscules) ; noms « ? »/chiffres listés,
  pas écrits ; premier composant qui écrit dans Gramps.
- `docs/USER_GUIDE.md` : section « Standardisation — noms » : `genecrew names --dry-run` puis
  écriture réelle ; où sont les deux rapports ; la casse ne change que la casse ; réversible
  via l'historique Gramps.

- [ ] **Step 5 : Commit**
```bash
git add docs/adr/0001-ecriture-directe-encadree.md docs/adr/0007-standardisation-casse-invariant.md docs/USER_GUIDE.md
git commit -m "docs: ADR 0007 casse par invariant + raffinement ADR 0001 + USER_GUIDE noms"
```

---

## Self-Review (fait à l'écriture du plan)

- **Couverture spec** : fonctions pures §3.1 → T1 ; `GrampsUpdateNameTool` §3.2 + invariant §4 → T2 ; export/version → T3 ; CLI + orchestration §3.3 → T4/T5/T6 ; règles de casse §5 → T1 (table de tests) ; garde-fous §4 → T2 (invariant), T5 (cible restreinte via `needs_normalization`) ; critère de sortie §8 → T7 ; impact doc §10 → T7.
- **Placeholders** : aucun — tout le code est fourni.
- **Cohérence des types** : `normalize_case`/`needs_normalization`/`is_case_only_change`/`is_incomplete_name` (T1) consommées par T2 et T5 ; `GrampsUpdateNameTool._run(handle, dry_run)` (T2) appelé par T5 avec la même signature ; `iter_people_batches` (T4) consommé par T5 ; `run_names(...) -> (Path, Path)` (T5) appelé par T6 ; `render_names_report(scope, date, results, incomplete, dry_run)` cohérent entre T5 def et T5 tests.
- **Hors périmètre assumé (YAGNI)** : lieux (spec séparée), `alternate_names`, restructuration `prefix`, résolution des « ? », écriture par lots transactionnelle.
- **Limite v1 notée** : pré-filtre sur le patronyme primaire seulement (T5).
- **Défaut écriture réelle** : le tool prend `dry_run` explicite (ne lit pas d'env) ; la CLI défaut `--dry-run` absent = écriture réelle, conforme au choix utilisateur.
