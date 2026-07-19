# Phase 0 — Plomberie : Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Un client Gramps Web (httpx + JWT) et 5 outils CrewAI de lecture dans
`crewai_custom_tools`, consommés par genecrew via un workspace uv, avec une CLI
`genecrew stats` dont la sortie égale le tableau de bord Gramps Web.

**Architecture:** Le client (`GrampsClient`) est un module Python pur dans
`crewai_custom_tools/tools/genealogy/gramps/client.py` ; les outils CrewAI sont des
enveloppes `BaseTool` fines autour de lui ; genecrew (projet imbriqué) le consomme
directement (sans LLM) pour la commande `stats`. Spécification de référence :
`genecrew/docs/document-de-travail.md` (§3, §4, §7, §9 Phase 0).

**Tech Stack:** Python 3.12, uv (workspace), httpx, Pydantic v2, crewai.tools.BaseTool,
pytest + pytest-mock + httpx.MockTransport, datamodel-code-generator (génération ponctuelle).

## Global Constraints

- **`uv` pour tout** : `uv sync`, `uv run`, `uv run --with …` — jamais `pip` ni `python` directs.
- **Deux dépôts git distincts** : les commits des tâches 1–4 se font dans
  `/Users/fjacquet/Projects/crewai_custom_tools`, ceux des tâches 5–8 dans
  `/Users/fjacquet/Projects/genecrew`.
- **Phase 0 = lecture seule** : aucun outil d'écriture Gramps ne doit exister à la fin de
  cette phase (spec §2.1 — la garantie est structurelle).
- Conventions crewai_custom_tools (CLAUDE.md du dépôt) : chaque `_run` retourne l'enveloppe
  `ok()/err()` ; décorateur `@api_tool(provider=…, endpoint=…)` ; tests 100 % hors-ligne ;
  un test succès + un test erreur par outil ; export dans `__all__` de
  `src/crewai_custom_tools/__init__.py` ; bump `__version__` + `pyproject.toml` en lockstep.
- Fichiers ≤ 500 lignes, **exception** : `*_generated.py` (code généré, ADR 0004).
- Style fonctionnel : fonctions pures pour le formatage/les transformations ; effets (HTTP,
  print) isolés dans le client et la CLI.
- Les endpoints Gramps Web se vérifient contre `genecrew/docs/swagger/openapi.json`
  (chemins préfixés `/api/...` dans la spec ; `GRAMPS_API_URL` contient déjà `/api`, donc
  les chemins du client sont sans préfixe).

---

### Task 1 : Client Gramps (config + JWT + helpers de lecture)

**Files:**

- Create: `src/crewai_custom_tools/tools/genealogy/__init__.py` (vide, docstring)
- Create: `src/crewai_custom_tools/tools/genealogy/gramps/__init__.py` (vide, docstring)
- Create: `src/crewai_custom_tools/tools/genealogy/gramps/client.py`
- Test: `tests/test_genealogy_gramps_client.py`

**Interfaces:**

- Produces (utilisé par les tâches 3 et 6) :
  - `GrampsConfig(api_url: str, username: str, password: str)` (frozen dataclass) et
    `GrampsConfig.from_env() -> GrampsConfig` (lit `GRAMPS_API_URL`, `GRAMPS_USERNAME`,
    `GRAMPS_PASSWORD` ; lève `GrampsConfigError` si absente).
  - `GrampsClient(config: GrampsConfig, transport: httpx.BaseTransport | None = None)` avec
    méthodes : `get_json(path, params=None) -> Any`,
    `count_objects(object_type: str) -> int`, `get_tree_info() -> dict`,
    `search(query: str, page: int = 1, pagesize: int = 20) -> list`,
    `get_object(object_type: str, handle: str) -> dict`,
    `find_by_gramps_id(object_type: str, gramps_id: str) -> dict`,
    `list_people(page: int = 1, pagesize: int = 25) -> list`,
    `get_timeline(handle: str) -> list`.
  - `get_client() -> GrampsClient` (singleton paresseux module-niveau, config via env).

- [ ] **Step 1 : Vérifier les hypothèses d'endpoints contre la spec OpenAPI**

```bash
cd /Users/fjacquet/Projects/genecrew
jq -r '.paths."/api/people/".get.parameters[].name' docs/swagger/openapi.json | sort | head -30
jq -r '.paths."/api/search/".get.parameters[].name' docs/swagger/openapi.json
jq -r '.paths."/api/people/{handle}/timeline".get | keys' docs/swagger/openapi.json
```

Attendu : `gramps_id`, `page`, `pagesize` figurent parmi les paramètres de `/api/people/` ;
`/api/search/` accepte `query`, `page`, `pagesize`. Si un nom diffère, adapter le client en
conséquence (la spec fait foi) et le noter dans le message de commit.

- [ ] **Step 2 : Écrire les tests qui échouent**

Créer `tests/test_genealogy_gramps_client.py` :

```python
"""Offline tests for the Gramps Web client (httpx.MockTransport, no network)."""

import json
import os

import httpx
import pytest

from crewai_custom_tools.tools.genealogy.gramps.client import (
    GrampsClient,
    GrampsConfig,
    GrampsConfigError,
)

CONFIG = GrampsConfig(api_url="http://gramps.test/api", username="u", password="p")


def _transport(handler):
    return httpx.MockTransport(handler)


def _token_response():
    return httpx.Response(200, json={"access_token": "tok-1"})


def test_from_env_reads_variables(mocker):
    mocker.patch.dict(
        os.environ,
        {"GRAMPS_API_URL": "http://h/api/", "GRAMPS_USERNAME": "u", "GRAMPS_PASSWORD": "p"},
    )
    cfg = GrampsConfig.from_env()
    assert cfg.api_url == "http://h/api"  # trailing slash stripped
    assert cfg.username == "u"


def test_from_env_missing_variable_raises(mocker):
    mocker.patch.dict(os.environ, {}, clear=True)
    with pytest.raises(GrampsConfigError):
        GrampsConfig.from_env()


def test_get_json_fetches_token_then_data():
    calls = []

    def handler(request):
        calls.append((request.method, request.url.path))
        if request.url.path == "/api/token/":
            assert json.loads(request.content) == {"username": "u", "password": "p"}
            return _token_response()
        assert request.headers["Authorization"] == "Bearer tok-1"
        return httpx.Response(200, json=[{"name": "arbre"}])

    client = GrampsClient(CONFIG, transport=_transport(handler))
    assert client.get_json("/trees/") == [{"name": "arbre"}]
    assert calls[0] == ("POST", "/api/token/")


def test_request_refreshes_token_once_on_401():
    state = {"tokens": 0, "data_calls": 0}

    def handler(request):
        if request.url.path == "/api/token/":
            state["tokens"] += 1
            return httpx.Response(200, json={"access_token": f"tok-{state['tokens']}"})
        state["data_calls"] += 1
        if state["data_calls"] == 1:
            return httpx.Response(401)
        assert request.headers["Authorization"] == "Bearer tok-2"
        return httpx.Response(200, json={"ok": True})

    client = GrampsClient(CONFIG, transport=_transport(handler))
    assert client.get_json("/people/") == {"ok": True}
    assert state["tokens"] == 2  # initial + refresh


def test_count_objects_uses_total_count_header():
    def handler(request):
        if request.url.path == "/api/token/":
            return _token_response()
        assert request.url.params["pagesize"] == "1"
        return httpx.Response(200, json=[{}], headers={"X-Total-Count": "1234"})

    client = GrampsClient(CONFIG, transport=_transport(handler))
    assert client.count_objects("people") == 1234


def test_find_by_gramps_id_returns_single_object():
    def handler(request):
        if request.url.path == "/api/token/":
            return _token_response()
        assert request.url.params["gramps_id"] == "I0042"
        return httpx.Response(200, json=[{"gramps_id": "I0042", "handle": "abc"}])

    client = GrampsClient(CONFIG, transport=_transport(handler))
    assert client.find_by_gramps_id("people", "I0042")["handle"] == "abc"


def test_http_error_propagates_as_status_error():
    def handler(request):
        if request.url.path == "/api/token/":
            return _token_response()
        return httpx.Response(500)

    client = GrampsClient(CONFIG, transport=_transport(handler))
    with pytest.raises(httpx.HTTPStatusError):
        client.get_json("/people/")
```

- [ ] **Step 3 : Vérifier que les tests échouent**

```bash
cd /Users/fjacquet/Projects/crewai_custom_tools
uv run python -m pytest tests/test_genealogy_gramps_client.py -v
```

Attendu : ÉCHEC en collecte — `ModuleNotFoundError: crewai_custom_tools.tools.genealogy`.

- [ ] **Step 4 : Implémenter le client**

`src/crewai_custom_tools/tools/genealogy/__init__.py` :

```python
"""Genealogy domain tools (Gramps Web, French & Swiss public APIs)."""
```

`src/crewai_custom_tools/tools/genealogy/gramps/__init__.py` :

```python
"""Gramps Web REST access: pure client + thin CrewAI read tools."""
```

`src/crewai_custom_tools/tools/genealogy/gramps/client.py` :

```python
"""Pure httpx client for the Gramps Web REST API.

JWT auth with lazy fetch and single refresh on 401. `GRAMPS_API_URL` already
includes the `/api` suffix, so all paths here are relative ("/people/").
This module is NOT a CrewAI tool: it is consumed directly by the genecrew
orchestrator (no LLM) and wrapped by the thin BaseTool classes in read_tools.py.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

import httpx

DEFAULT_TIMEOUT = 15.0


class GrampsConfigError(RuntimeError):
    """Raised when the Gramps environment configuration is incomplete."""


@dataclass(frozen=True)
class GrampsConfig:
    """Connection settings for one Gramps Web instance."""

    api_url: str
    username: str
    password: str

    @staticmethod
    def from_env() -> "GrampsConfig":
        try:
            return GrampsConfig(
                api_url=os.environ["GRAMPS_API_URL"].rstrip("/"),
                username=os.environ["GRAMPS_USERNAME"],
                password=os.environ["GRAMPS_PASSWORD"],
            )
        except KeyError as exc:
            raise GrampsConfigError(
                f"Missing environment variable: {exc.args[0]}"
            ) from exc


class GrampsClient:
    """Thin synchronous Gramps Web client; one instance per process."""

    def __init__(
        self,
        config: GrampsConfig,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self._config = config
        self._http = httpx.Client(
            base_url=config.api_url, timeout=DEFAULT_TIMEOUT, transport=transport
        )
        self._token: str | None = None

    def _fetch_token(self) -> str:
        response = self._http.post(
            "/token/",
            json={"username": self._config.username, "password": self._config.password},
        )
        response.raise_for_status()
        return response.json()["access_token"]

    def request(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        if self._token is None:
            self._token = self._fetch_token()
        headers = {"Authorization": f"Bearer {self._token}"}
        response = self._http.request(method, path, headers=headers, **kwargs)
        if response.status_code == 401:  # expired token: refresh once
            self._token = self._fetch_token()
            headers = {"Authorization": f"Bearer {self._token}"}
            response = self._http.request(method, path, headers=headers, **kwargs)
        response.raise_for_status()
        return response

    def get_json(self, path: str, params: dict[str, Any] | None = None) -> Any:
        return self.request("GET", path, params=params).json()

    # -- typed read helpers -------------------------------------------------

    def count_objects(self, object_type: str) -> int:
        response = self.request("GET", f"/{object_type}/", params={"pagesize": 1})
        total = response.headers.get("X-Total-Count")
        if total is None:
            raise RuntimeError(
                f"Gramps Web response for /{object_type}/ lacks the X-Total-Count header"
            )
        return int(total)

    def get_tree_info(self) -> dict:
        trees = self.get_json("/trees/")
        return trees[0] if isinstance(trees, list) and trees else {}

    def search(self, query: str, page: int = 1, pagesize: int = 20) -> list:
        return self.get_json(
            "/search/", params={"query": query, "page": page, "pagesize": pagesize}
        )

    def get_object(self, object_type: str, handle: str) -> dict:
        return self.get_json(f"/{object_type}/{handle}")

    def find_by_gramps_id(self, object_type: str, gramps_id: str) -> dict:
        matches = self.get_json(f"/{object_type}/", params={"gramps_id": gramps_id})
        if not matches:
            raise LookupError(f"No {object_type} object with gramps_id {gramps_id}")
        return matches[0]

    def list_people(self, page: int = 1, pagesize: int = 25) -> list:
        return self.get_json(
            "/people/", params={"page": page, "pagesize": pagesize, "sort": "gramps_id"}
        )

    def get_timeline(self, handle: str) -> list:
        return self.get_json(f"/people/{handle}/timeline")


_CLIENT: GrampsClient | None = None


def get_client() -> GrampsClient:
    """Lazy per-process singleton configured from the environment."""
    global _CLIENT
    if _CLIENT is None:
        _CLIENT = GrampsClient(GrampsConfig.from_env())
    return _CLIENT
```

- [ ] **Step 5 : Vérifier que les tests passent**

```bash
uv run python -m pytest tests/test_genealogy_gramps_client.py -v
```

Attendu : 7 PASS.

- [ ] **Step 6 : Commit (dépôt crewai_custom_tools)**

```bash
git add src/crewai_custom_tools/tools/genealogy/ tests/test_genealogy_gramps_client.py
git commit -m "feat(genealogy): Gramps Web client (httpx + JWT, read helpers)"
```

---

### Task 2 : Modèles Pydantic générés depuis la spec Gramps Web

**Files:**

- Create: `src/crewai_custom_tools/tools/genealogy/models/__init__.py`
- Create: `src/crewai_custom_tools/tools/genealogy/models/gramps_generated.py` (généré)

**Interfaces:**

- Produces : module `models.gramps_generated` importable (`Person`, `Family`, etc. selon la
  spec). Phase 0 n'en consomme rien à l'exécution — il est là pour les phases 1–2 ;
  `domain.py` (Proposition, Checkpoint…) n'est **pas** créé maintenant (YAGNI, Phase 1).

- [ ] **Step 1 : Générer les modèles**

```bash
cd /Users/fjacquet/Projects/crewai_custom_tools
mkdir -p src/crewai_custom_tools/tools/genealogy/models
uv run --with datamodel-code-generator datamodel-codegen \
  --input ../genecrew/docs/swagger/openapi.json \
  --input-file-type openapi \
  --output src/crewai_custom_tools/tools/genealogy/models/gramps_generated.py \
  --output-model-type pydantic_v2.BaseModel \
  --custom-file-header '"""Généré depuis genecrew/docs/swagger/openapi.json — NE PAS ÉDITER (ADR 0004)."""'
```

Créer `src/crewai_custom_tools/tools/genealogy/models/__init__.py` :

```python
"""Pydantic models for the genealogy domain (generated + hand-written)."""
```

- [ ] **Step 2 : Vérifier que le module s'importe**

```bash
uv run python -c "from crewai_custom_tools.tools.genealogy.models import gramps_generated as g; print(len(dir(g)))"
```

Attendu : un entier (> 50), aucune exception. En cas d'erreur de génération sur la spec
3.1/3.0, ajouter `--use-annotated` ou cibler `--openapi-scopes schemas` et regénérer.

- [ ] **Step 3 : Commit**

```bash
git add src/crewai_custom_tools/tools/genealogy/models/
git commit -m "feat(genealogy): generated Pydantic models from Gramps Web OpenAPI 3.17.0"
```

---

### Task 3 : Les 5 outils CrewAI de lecture

**Files:**

- Create: `src/crewai_custom_tools/tools/genealogy/gramps/read_tools.py`
- Test: `tests/test_genealogy_gramps_read_tools.py`

**Interfaces:**

- Consumes : `get_client()` de la tâche 1.
- Produces (exportés en tâche 4) : `GrampsSearchTool`, `GrampsGetObjectTool`,
  `GrampsListPeopleTool`, `GrampsTreeStatsTool`, `GrampsTimelineTool` — tous `BaseTool`,
  `_run` retourne l'enveloppe `ok()/err()` (JSON string).

- [ ] **Step 1 : Écrire les tests qui échouent**

Créer `tests/test_genealogy_gramps_read_tools.py` :

```python
"""Offline tests for the Gramps read tools (client mocked, envelope asserted)."""

import json

import httpx
import pytest

from crewai_custom_tools.tools.genealogy.gramps.client import GrampsClient, GrampsConfig
from crewai_custom_tools.tools.genealogy.gramps.read_tools import (
    GrampsGetObjectTool,
    GrampsListPeopleTool,
    GrampsSearchTool,
    GrampsTimelineTool,
    GrampsTreeStatsTool,
)

CONFIG = GrampsConfig(api_url="http://gramps.test/api", username="u", password="p")


def _client(handler):
    return GrampsClient(CONFIG, transport=httpx.MockTransport(handler))


def _mock_client(mocker, handler):
    client = _client(handler)
    mocker.patch(
        "crewai_custom_tools.tools.genealogy.gramps.read_tools.get_client",
        return_value=client,
    )


def _token_or(request, respond):
    if request.url.path == "/api/token/":
        return httpx.Response(200, json={"access_token": "tok"})
    return respond(request)


def test_search_tool_success(mocker):
    def handler(request):
        return _token_or(
            request,
            lambda r: httpx.Response(
                200, json=[{"object_type": "person", "object": {"gramps_id": "I0001"}}]
            ),
        )

    _mock_client(mocker, handler)
    payload = json.loads(GrampsSearchTool()._run(query="Dupont"))
    assert payload["success"] is True
    assert payload["data"][0]["object"]["gramps_id"] == "I0001"


def test_search_tool_empty_is_success(mocker):
    def handler(request):
        return _token_or(request, lambda r: httpx.Response(200, json=[]))

    _mock_client(mocker, handler)
    payload = json.loads(GrampsSearchTool()._run(query="Zzz"))
    assert payload["success"] is True
    assert payload["data"] == []


def test_get_object_tool_by_gramps_id(mocker):
    def handler(request):
        def respond(r):
            assert r.url.params["gramps_id"] == "I0042"
            return httpx.Response(200, json=[{"handle": "abc", "gramps_id": "I0042"}])

        return _token_or(request, respond)

    _mock_client(mocker, handler)
    payload = json.loads(
        GrampsGetObjectTool()._run(object_type="people", gramps_id="I0042")
    )
    assert payload["success"] is True
    assert payload["data"]["handle"] == "abc"


def test_get_object_tool_requires_identifier(mocker):
    _mock_client(mocker, lambda r: httpx.Response(500))
    payload = json.loads(GrampsGetObjectTool()._run(object_type="people"))
    assert payload["success"] is False


def test_tree_stats_tool_counts_all_types(mocker):
    def handler(request):
        def respond(r):
            if r.url.path == "/api/trees/":
                return httpx.Response(200, json=[{"name": "Famille"}])
            return httpx.Response(200, json=[{}], headers={"X-Total-Count": "7"})

        return _token_or(request, respond)

    _mock_client(mocker, handler)
    payload = json.loads(GrampsTreeStatsTool()._run())
    assert payload["success"] is True
    assert payload["data"]["tree_name"] == "Famille"
    assert payload["data"]["counts"]["people"] == 7


def test_list_people_tool_error_path(mocker):
    def handler(request):
        return _token_or(request, lambda r: httpx.Response(500))

    _mock_client(mocker, handler)
    payload = json.loads(GrampsListPeopleTool()._run())
    assert payload["success"] is False


def test_timeline_tool_success(mocker):
    def handler(request):
        def respond(r):
            assert r.url.path == "/api/people/abc/timeline"
            return httpx.Response(200, json=[{"label": "Birth"}])

        return _token_or(request, respond)

    _mock_client(mocker, handler)
    payload = json.loads(GrampsTimelineTool()._run(handle="abc"))
    assert payload["success"] is True
    assert payload["data"][0]["label"] == "Birth"
```

- [ ] **Step 2 : Vérifier que les tests échouent**

```bash
uv run python -m pytest tests/test_genealogy_gramps_read_tools.py -v
```

Attendu : ÉCHEC en collecte — `ImportError` sur `read_tools`.

- [ ] **Step 3 : Implémenter les outils**

`src/crewai_custom_tools/tools/genealogy/gramps/read_tools.py` :

```python
"""Read-only CrewAI tools over the Gramps Web API.

Thin BaseTool wrappers around client.get_client(). Phase 0 is read-only by
design (spec §2.1): no write tool may exist in this module.
"""

import logging

from crewai.tools import BaseTool
from pydantic import BaseModel, Field

from crewai_custom_tools.core.decorators import api_tool
from crewai_custom_tools.core.results import err, ok
from crewai_custom_tools.tools.genealogy.gramps.client import get_client

logger = logging.getLogger(__name__)

COUNTED_TYPES = (
    "people", "families", "events", "places", "sources",
    "citations", "repositories", "media", "notes", "tags",
)


class GrampsSearchInput(BaseModel):
    """Input schema for GrampsSearchTool."""

    query: str = Field(..., description="Full-text query across all Gramps record types.")
    page: int = Field(1, description="Result page (1-based).")
    pagesize: int = Field(20, description="Results per page.")


class GrampsSearchTool(BaseTool):
    """Full-text search across the whole Gramps tree."""

    name: str = "gramps_search"
    description: str = (
        "Searches the Gramps genealogy database (people, families, events, places, "
        "sources, notes...) with a full-text query. Read-only."
    )
    args_schema: type[BaseModel] = GrampsSearchInput

    @api_tool(provider="GrampsWeb", endpoint="Search")
    def _run(self, query: str, page: int = 1, pagesize: int = 20) -> str:
        return ok(get_client().search(query, page=page, pagesize=pagesize))


class GrampsGetObjectInput(BaseModel):
    """Input schema for GrampsGetObjectTool."""

    object_type: str = Field(
        ...,
        description="Gramps object type: people, families, events, places, sources, "
        "citations, repositories, media or notes.",
    )
    handle: str | None = Field(None, description="Internal Gramps handle.")
    gramps_id: str | None = Field(None, description="Human-readable ID (I0042, F0007...).")


class GrampsGetObjectTool(BaseTool):
    """Fetch one Gramps object by handle or gramps_id."""

    name: str = "gramps_get_object"
    description: str = (
        "Fetches the full record of one Gramps object (person, family, event...) "
        "by handle or by gramps_id. Read-only."
    )
    args_schema: type[BaseModel] = GrampsGetObjectInput

    @api_tool(provider="GrampsWeb", endpoint="GetObject")
    def _run(
        self,
        object_type: str,
        handle: str | None = None,
        gramps_id: str | None = None,
    ) -> str:
        if handle:
            return ok(get_client().get_object(object_type, handle))
        if gramps_id:
            return ok(get_client().find_by_gramps_id(object_type, gramps_id))
        return err("gramps_get_object: provide either handle or gramps_id")


class GrampsListPeopleInput(BaseModel):
    """Input schema for GrampsListPeopleTool."""

    page: int = Field(1, description="Page number (1-based).")
    pagesize: int = Field(25, description="People per page.")


class GrampsListPeopleTool(BaseTool):
    """Paginated list of people sorted by gramps_id."""

    name: str = "gramps_list_people"
    description: str = "Lists people in the Gramps tree, paginated, sorted by gramps_id. Read-only."
    args_schema: type[BaseModel] = GrampsListPeopleInput

    @api_tool(provider="GrampsWeb", endpoint="ListPeople")
    def _run(self, page: int = 1, pagesize: int = 25) -> str:
        return ok(get_client().list_people(page=page, pagesize=pagesize))


class GrampsTreeStatsInput(BaseModel):
    """Input schema for GrampsTreeStatsTool (no parameters)."""


class GrampsTreeStatsTool(BaseTool):
    """Object counts per type + tree name."""

    name: str = "gramps_tree_stats"
    description: str = (
        "Returns the Gramps tree name and the number of objects of each type "
        "(people, families, events, places, sources, citations...). Read-only."
    )
    args_schema: type[BaseModel] = GrampsTreeStatsInput

    @api_tool(provider="GrampsWeb", endpoint="TreeStats", timeout=60.0)
    def _run(self) -> str:
        client = get_client()
        counts = {t: client.count_objects(t) for t in COUNTED_TYPES}
        info = client.get_tree_info()
        return ok({"tree_name": info.get("name"), "counts": counts})


class GrampsTimelineInput(BaseModel):
    """Input schema for GrampsTimelineTool."""

    handle: str = Field(..., description="Handle of the person.")


class GrampsTimelineTool(BaseTool):
    """Chronological life events of one person."""

    name: str = "gramps_person_timeline"
    description: str = "Returns the chronological timeline of one person's life events. Read-only."
    args_schema: type[BaseModel] = GrampsTimelineInput

    @api_tool(provider="GrampsWeb", endpoint="Timeline")
    def _run(self, handle: str) -> str:
        return ok(get_client().get_timeline(handle))
```

- [ ] **Step 4 : Vérifier que les tests passent**

```bash
uv run python -m pytest tests/test_genealogy_gramps_read_tools.py -v
```

Attendu : 7 PASS. Note : `test_get_object_tool_requires_identifier` passe parce que `_run`
retourne `err(...)` avant tout appel réseau.

- [ ] **Step 5 : Commit**

```bash
git add src/crewai_custom_tools/tools/genealogy/gramps/read_tools.py tests/test_genealogy_gramps_read_tools.py
git commit -m "feat(genealogy): 5 read-only Gramps CrewAI tools"
```

---

### Task 4 : Exports, version, suite complète

**Files:**

- Modify: `src/crewai_custom_tools/__init__.py` (imports + `__all__` + `__version__`)
- Modify: `pyproject.toml` (version)

**Interfaces:**

- Produces : `from crewai_custom_tools import GrampsSearchTool, …` fonctionne ; le serveur
  MCP de la bibliothèque expose automatiquement les 5 outils (auto-registration `__all__`).

- [ ] **Step 1 : Ajouter les exports**

Dans `src/crewai_custom_tools/__init__.py`, suivre le motif existant du fichier : ajouter
l'import groupé…

```python
from crewai_custom_tools.tools.genealogy.gramps.read_tools import (
    GrampsGetObjectTool,
    GrampsListPeopleTool,
    GrampsSearchTool,
    GrampsTimelineTool,
    GrampsTreeStatsTool,
)
```

…et les 5 noms dans la liste `__all__` (ordre alphabétique local, comme les autres blocs).

- [ ] **Step 2 : Bump de version en lockstep**

`__version__ = "0.7.0"` dans `src/crewai_custom_tools/__init__.py` **et** `version = "0.7.0"`
dans `pyproject.toml` (nouveau domaine ⇒ mineure). `tests/test_scaffold.py` vérifie le
lockstep.

- [ ] **Step 3 : Suite complète**

```bash
uv run python -m pytest -v
```

Attendu : tous les tests passent (423 existants + 14 nouveaux), aucun test réseau.

- [ ] **Step 4 : Commit**

```bash
git add src/crewai_custom_tools/__init__.py pyproject.toml
git commit -m "feat(genealogy): export Gramps read tools; bump to 0.7.0"
```

---

### Task 5 : Câblage genecrew → bibliothèque (workspace uv)

**Files:**

- Modify: `/Users/fjacquet/Projects/genecrew/pyproject.toml` (racine — devient workspace virtuel)
- Modify: `/Users/fjacquet/Projects/genecrew/genecrew/pyproject.toml` (membre)

**Interfaces:**

- Produces : depuis la racine genecrew, `uv run genecrew …` exécute le script console du
  membre ; `crewai_custom_tools` importable dans ce venv.

**Contexte du problème** : la racine et le paquet imbriqué s'appellent tous deux `genecrew`
(collision de nom si l'un dépend de l'autre) et la racine est un projet uv « nu ». La
solution KISS est un **workspace uv à racine virtuelle** : un seul venv (racine), le membre
`genecrew/` y est installé avec ses scripts console.

- [ ] **Step 1 : Racine — workspace virtuel**

Remplacer intégralement `/Users/fjacquet/Projects/genecrew/pyproject.toml` par :

```toml
[tool.uv.workspace]
members = ["genecrew"]

[dependency-groups]
dev = [
    "ruff>=0.15.22",
    "pytest>=8.3",
    "pytest-mock>=3.14",
]
```

- [ ] **Step 2 : Membre — dépendances et source locale**

Remplacer `/Users/fjacquet/Projects/genecrew/genecrew/pyproject.toml` par :

```toml
[project]
name = "genecrew"
version = "0.1.0"
description = "GeneCrew - équipe d'agents IA pour la généalogie (Gramps Web)"
authors = [{ name = "Frederic Jacquet" }]
requires-python = ">=3.11,<3.13"
dependencies = [
    "crewai[tools]>=1.15.2",
    "crewai-custom-tools",
    "python-dotenv>=1.0.0",
]

[project.scripts]
genecrew = "genecrew.main:main"
run_crew = "genecrew.main:run"
train = "genecrew.main:train"
replay = "genecrew.main:replay"
test = "genecrew.main:test"

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.crewai]
type = "crew"

[tool.uv.sources]
crewai-custom-tools = { path = "../../crewai_custom_tools", editable = true }
```

Note : le script `genecrew` pointe désormais vers `main:main` (CLI argparse, tâche 6) ;
`run_crew` reste pour `crewai run`.

- [ ] **Step 3 : Synchroniser et vérifier**

```bash
cd /Users/fjacquet/Projects/genecrew
uv sync
uv run python -c "import crewai_custom_tools as c; print(c.__version__)"
```

Attendu : `uv sync` résout le workspace sans conflit (l'ancien lock est régénéré) et
affiche `0.7.0`. Si la résolution échoue sur la borne Python, ajuster `requires-python` du
membre à l'intersection exigée par le résolveur et noter la valeur retenue dans le commit.

- [ ] **Step 4 : Commit (dépôt genecrew)**

```bash
git add pyproject.toml genecrew/pyproject.toml uv.lock
git commit -m "build: uv workspace racine + dépendance crewai-custom-tools 0.7.0"
```

---

### Task 6 : Module stats + CLI `genecrew stats`

**Files:**

- Create: `genecrew/src/genecrew/stats.py`
- Modify: `genecrew/src/genecrew/main.py` (ajout de `main()` argparse ; fonctions
  existantes `run/train/replay/test` conservées telles quelles)
- Test: `genecrew/tests/test_stats.py`

**Interfaces:**

- Consumes : `GrampsClient`, `GrampsConfig` (tâche 1) — directement, sans LLM (spec §3.3).
- Produces : `collect_stats(client) -> dict`, `format_stats(tree_name, counts) -> str`
  (pure), commande `uv run genecrew stats`.

- [ ] **Step 1 : Écrire le test qui échoue (fonction pure uniquement)**

Créer `genecrew/tests/test_stats.py` :

```python
"""Tests of the pure stats formatting (no network, no client)."""

from genecrew.stats import format_stats


def test_format_stats_aligns_and_orders():
    out = format_stats("Famille Jacquet", {"people": 1234, "tags": 7})
    lines = out.splitlines()
    assert lines[0] == "Arbre : Famille Jacquet"
    assert lines[2] == "people    1234"
    assert lines[3] == "tags         7"


def test_format_stats_unknown_tree_name():
    out = format_stats(None, {"people": 1})
    assert out.splitlines()[0] == "Arbre : (sans nom)"
```

- [ ] **Step 2 : Vérifier que le test échoue**

```bash
cd /Users/fjacquet/Projects/genecrew
uv run python -m pytest genecrew/tests/test_stats.py -v
```

Attendu : ÉCHEC — `ModuleNotFoundError: genecrew.stats`.

- [ ] **Step 3 : Implémenter stats.py**

`genecrew/src/genecrew/stats.py` :

```python
"""Tree statistics: deterministic collection (no LLM) + pure formatting."""

from __future__ import annotations

from crewai_custom_tools.tools.genealogy.gramps.client import GrampsClient

COUNTED_TYPES = (
    "people", "families", "events", "places", "sources",
    "citations", "repositories", "media", "notes", "tags",
)


def collect_stats(client: GrampsClient) -> tuple[str | None, dict[str, int]]:
    """Fetch tree name and per-type object counts (I/O)."""
    counts = {t: client.count_objects(t) for t in COUNTED_TYPES}
    return client.get_tree_info().get("name"), counts


def format_stats(tree_name: str | None, counts: dict[str, int]) -> str:
    """Render counts as an aligned text table (pure)."""
    name_width = max(len(k) for k in counts)
    value_width = max(len(str(v)) for v in counts.values())
    lines = [f"Arbre : {tree_name or '(sans nom)'}", ""]
    lines += [
        f"{k.ljust(name_width)}  {str(v).rjust(value_width)}" for k, v in counts.items()
    ]
    return "\n".join(lines)
```

- [ ] **Step 4 : Vérifier que les tests passent**

```bash
uv run python -m pytest genecrew/tests/test_stats.py -v
```

Attendu : 2 PASS.

- [ ] **Step 5 : Ajouter la CLI argparse dans main.py**

Dans `genecrew/src/genecrew/main.py`, **ajouter** en tête de fichier (sous les imports
existants) puis en fin de fichier — sans toucher aux fonctions `run/train/replay/test` :

```python
import argparse

from dotenv import load_dotenv


def stats() -> None:
    """Print tree statistics from Gramps Web (deterministic, no LLM)."""
    from crewai_custom_tools.tools.genealogy.gramps.client import (
        GrampsClient,
        GrampsConfig,
    )

    from genecrew.stats import collect_stats, format_stats

    client = GrampsClient(GrampsConfig.from_env())
    tree_name, counts = collect_stats(client)
    print(format_stats(tree_name, counts))


def main() -> None:
    """CLI entry point: genecrew <command>."""
    load_dotenv()
    parser = argparse.ArgumentParser(prog="genecrew", description="GeneCrew CLI")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("stats", help="Statistiques de l'arbre Gramps Web")
    args = parser.parse_args()
    if args.command == "stats":
        stats()
```

Attention (résolution post-revue) : l'import `from genecrew.crew import Genecrew` est
déplacé **dans le corps** de `run/train/replay/test` (comportement inchangé) pour que
`genecrew --help`/`stats` ne charge pas CrewAI via ce chemin. Limite connue : `stats`
importe `crewai_custom_tools`, dont l'`__init__` monolithique charge `crewai.tools` —
optimisation éventuelle côté bibliothèque, hors Phase 0.

- [ ] **Step 6 : Vérifier l'aide CLI**

```bash
uv run genecrew --help
```

Attendu : usage `genecrew {stats}` sans erreur d'import.

- [ ] **Step 7 : Commit**

```bash
git add genecrew/src/genecrew/stats.py genecrew/src/genecrew/main.py genecrew/tests/test_stats.py
git commit -m "feat: CLI genecrew stats (collecte déterministe + formatage pur)"
```

---

### Task 7 : Configuration .env et critère de sortie Phase 0

**Files:**

- Modify: `genecrew/.env` (ajout de clés — **jamais commité**, il est gitignoré)
- Create: `genecrew/.env.example`

**Interfaces:**

- Consumes : la CLI de la tâche 6 ; le Gramps Web local (`docker compose up -d`).

- [ ] **Step 1 : Gabarit d'environnement**

Créer `genecrew/.env.example` (committable — aucune valeur secrète) :

```bash
# LLM (LiteLLM)
MODEL=gemini/gemini-2.5-flash-preview-04-17

# Gramps Web (Phase 0 : lecture seule — n'importe quel compte lecteur suffit ;
# le compte dédié genecrew-ia rôle Editor n'est requis qu'en Phase 2)
GRAMPS_API_URL=http://localhost:80/api
GRAMPS_USERNAME=
GRAMPS_PASSWORD=

# Pipeline
GENECREW_DRY_RUN=true
GENECREW_BATCH_SIZE=25
GENECREW_OUTPUT_DIR=output/
```

- [ ] **Step 2 : Demander à l'utilisateur de remplir `genecrew/.env`**

Ajouter les mêmes clés `GRAMPS_*` dans `genecrew/.env` avec les vraies valeurs.
**STOP : action utilisateur requise** — identifiants Gramps Web. Ne jamais afficher ni
committer les valeurs.

- [ ] **Step 3 : Démarrer le backend et exécuter**

```bash
cd /Users/fjacquet/Projects/genecrew
docker compose up -d
uv run genecrew stats
```

Attendu : le tableau des comptes par type. **Critère de sortie Phase 0 (spec §9)** :
l'utilisateur confronte ces nombres au tableau de bord Gramps Web (<http://localhost>) — ils
doivent être identiques. En cas d'écart, corriger le client (probablement le paramètre de
pagination ou le header de comptage) avant de continuer.

- [ ] **Step 4 : Commit**

```bash
git add genecrew/.env.example
git commit -m "chore: .env.example (Gramps Web + pipeline)"
```

---

### Task 8 : Documentation Phase 0 (PRD, USER_GUIDE, ADR)

**Files:**

- Create: `docs/PRD.md`
- Create: `docs/USER_GUIDE.md`
- Create: `docs/adr/0001-ecriture-directe-encadree.md`
- Create: `docs/adr/0002-acces-gramps-rest-direct.md`
- Create: `docs/adr/0003-outils-dans-crewai-custom-tools.md`
- Create: `docs/adr/0004-spec-first-generation-pydantic.md`
- Create: `docs/adr/0005-deterministe-d-abord.md`

**Interfaces:** aucune (documentation). Contenu : chaque ADR au format court
contexte / décision / conséquences, en reprenant **textuellement** les décisions de
`docs/document-de-travail.md` (§2.1, §3.2–3.4, §4.2.1, §6.5, §11 — ne pas reformuler les
règles, les citer). `PRD.md` dérive du §1 (mission, 4 objectifs, contrainte d'échelle,
non-objectifs : pas de modification autonome des données cœur, pas de publication externe).
`USER_GUIDE.md` couvre pour l'instant : prérequis (docker compose, `.env`), `uv sync`,
`uv run genecrew stats`, et la promesse « chaque phase ajoute sa section ».

- [ ] **Step 1 : Rédiger les 7 fichiers** (contenu par transposition directe du document de
  travail — le rédacteur reprend les sections citées ci-dessus sans les réinventer)

- [ ] **Step 2 : Auto-relecture** — cohérence avec `docs/document-de-travail.md`, zéro
  « TBD », liens relatifs valides.

- [ ] **Step 3 : Commit**

```bash
git add docs/PRD.md docs/USER_GUIDE.md docs/adr/
git commit -m "docs: PRD, USER_GUIDE et ADR 0001-0005 (Phase 0)"
```

---

## Self-Review (fait à l'écriture du plan)

- **Couverture spec Phase 0** : client JWT ✔ (T1), modèles générés ✔ (T2), outils lecture ✔
  (T3+T4), dépendance genecrew→bibliothèque ✔ (T5), CLI stats ✔ (T6), critère de sortie ✔
  (T7), discipline documentaire §11 ✔ (T8).
- **Placeholders** : aucun — tout le code est donné ; T8 référence des sections précises du
  document de travail comme source de contenu.
- **Cohérence de types** : `get_client()` (T1) consommé par T3 ; `count_objects`/
  `get_tree_info` (T1) consommés par T3 (`GrampsTreeStatsTool`) et T6 (`collect_stats`) ;
  scripts console (T5) alignés sur `main:main` (T6).
- **Hors périmètre assumé (YAGNI)** : `domain.py`, outils d'écriture, `GenealogyConsistencyTool`,
  checkpoints, `scope.py`, crews — Phase 1+.
