# Standardisateur de lieux (P1→P6) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Livrer le Standardisateur de lieux GeneCrew de bout en bout : parser les lieux plats, les résoudre par une chaîne de résolveurs routée par pays, proposer (`genecrew lieux`), écrire la hiérarchie et le GPS au-dessus d'un score (`genecrew lieux-apply`), gérer les transitions temporelles datées (data-driven), et exécuter les fusions de doublons sous revue (`genecrew lieux-merge`).

**Architecture:** Domaine pur + résolveurs `@api_tool` dans `crewai_custom_tools` (cct) ; orchestration/CLI dans `genecrew`. Le contrat `ResolvedPlace` découple l'orchestrateur des APIs. Écriture idempotente via un index de parents par chemin. Générique : aucune particularité d'un arbre dans le code ; les cas de l'arbre = fixtures de test par classe.

**Tech Stack:** Python 3.11/3.12, `uv`, Pydantic v2, httpx (transport injectable), `pytest` + `pytest-mock`, CrewAI `BaseTool`, décorateur `@api_tool` (timeout/retry-429/rate-limit + enveloppe `ok/err`), difflib.

## Global Constraints

- **Périmètre = P1→P6 (tout, aujourd'hui).** En **P1–P4**, chaque `ResolvedPlace.chains` a **une seule `DatedChain` non datée** et les fusions de feuilles sont seulement **proposées** ; **P5** introduit les chaînes datées (transitions data-driven) + les vraies `Date` Gramps sur les placerefs ; **P6** exécute les fusions **sous revue humaine** (`lieux-merge`), jamais en auto dans `lieux-apply`.
- **Deux repos, deux branches.** cct : brancher `feat/standardisateur-lieux` dans `/Users/fjacquet/Projects/crewai_custom_tools`. genecrew : branche `feat/standardisateur-lieux` **déjà créée** (courante). genecrew consomme cct en **éditable** (`../crewai_custom_tools`) → aucun `uv sync` nécessaire pendant le dev ; le bump de version cct + CHANGELOG se fait à la toute fin.
- **Enveloppe** : tout `_run` d'outil renvoie `ok(data)` / `err(msg)` (str JSON) via `crewai_custom_tools.core.results`. Les outils HTTP externes utilisent `@api_tool(provider=…, endpoint=…)`.
- **Sûreté d'écriture** : les outils d'écriture appellent `effective_dry_run(dry_run)` (défaut absent → simuler) ; en dry-run, `GrampsCreatePlaceTool` renvoie un **handle synthétique** `f"DRYRUN:{name}"` (les noms de parents administratifs sont uniques par niveau/pays, donc sans collision). Les rapports affichent le dry-run **effectif**.
- **Narrowing assumé (provenance)** : la provenance (`source | query | score`) est **rapportée** (colonne « Preuve » des rapports MD/YAML) et passée à `GrampsUpdatePlaceTool` via `provenance`, mais son écriture comme **note Gramps** sur le lieu est **différée** (elle exigerait un `GrampsCreateNoteTool` non encore construit). Le paramètre `provenance` reste en place, prêt à être branché.
- **Invariants GPS (verrouillés par tests)** : coordonnées **WGS84** décimales, aucune reprojection ; GeoJSON = **`[lon, lat]`** (jamais inversé) ; swisstopo : lire **`lat`/`lon`**, **jamais `x`/`y`** (grille LV95).
- **Score** : autoritaire (code) = **1.0** ; flou = `confiance_fournisseur × similarité(nom_demandé, nom_rendu)` ∈ [0,1] ; **garde-fou d'ambiguïté** = si le 2ᵉ candidat est à marge **< 0.10** du 1ᵉ → `ambiguous=True` → forcé en `proposition`. `--min-score` défaut **0.90**.
- **Générique** : aucun `if pays == "Algérie"` ni constante propre à un dataset dans le code. Fixtures = une par **classe** (autoritaire FR, autoritaire CH, flou mondial, décalé/indécidable, feuilles doublons), synthétiques.
- **Idiome CLI** : sous-commandes `lieux` / `lieux-apply` (comme `gender` / `gender-apply`). Flags partagés `--scope --limit --batch-size --date --dry-run`.
- **Tests offline** : HTTP externe testé par monkeypatch de la fonction `_http_get` du module (pas d'appel réseau) ; Gramps testé via `httpx.MockTransport`. La logique pure (parser, mappers, score, index) est testée sans réseau.
- Lancer les tests avec `uv run python -m pytest` depuis la racine du repo concerné.

---

### Task 1: Modèles de lieux (domain.py)

**Files:**

- Modify: `crewai_custom_tools/src/crewai_custom_tools/tools/genealogy/models/domain.py` (append)
- Test: `crewai_custom_tools/tests/test_genealogy_places_models.py` (create)

**Interfaces:**

- Produces: `ParsedPlace`, `PlaceLevel`, `DatedChain`, `DatedName`, `ResolvedPlace`, `PlaceProposition`, `PlaceMergeProposition` (Pydantic v2 `BaseModel`).

- [ ] **Step 1: Write the failing test**

```python
# crewai_custom_tools/tests/test_genealogy_places_models.py
from crewai_custom_tools.tools.genealogy.models.domain import (
    ParsedPlace, PlaceLevel, DatedChain, DatedName,
    ResolvedPlace, PlaceProposition, PlaceMergeProposition,
)


def test_resolved_place_defaults_single_chain_roundtrip():
    rp = ResolvedPlace(
        name="Bourges", place_type="Municipality", lat="47.081", long="2.399",
        code="18033",
        chains=[DatedChain(levels=[
            PlaceLevel(name="France", place_type="Country"),
            PlaceLevel(name="Centre-Val de Loire", place_type="Region"),
            PlaceLevel(name="Cher", place_type="Department", code="18"),
        ])],
        alt_names=[DatedName(value=", , Bourges, 18033, 18000, Cher, ...")],
        score=1.0, source="geo.api.gouv.fr", query="/communes/18033",
    )
    assert rp.chains[0].date_qualifier is None      # P1-P4 : chaîne unique non datée
    assert rp.ambiguous is False                    # garde-fou d'ambiguïté, défaut
    assert ResolvedPlace(**rp.model_dump()) == rp   # round-trip


def test_parsed_place_and_propositions_roundtrip():
    pp = PlaceProposition(
        type="lieu_resolu", gramps_id="I0501", handle="h1",
        original=", , Bourges, 18033, 18000, Cher, Centre-Val de Loire, France",
        country="France", resolution=None, action="proposition",
        confiance="basse", priorite="moyenne", preuve="…",
    )
    assert PlaceProposition(**pp.model_dump()) == pp
    mp = PlaceMergeProposition(gramps_id_keep="I0501", handle_keep="h1",
                               gramps_id_merge="I0733", handle_merge="h2",
                               canonical="Bourges", reason="même commune canonique")
    assert PlaceMergeProposition(**mp.model_dump()) == mp
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/fjacquet/Projects/crewai_custom_tools && uv run python -m pytest tests/test_genealogy_places_models.py -q`
Expected: FAIL with `ImportError: cannot import name 'ResolvedPlace'`.

- [ ] **Step 3: Write minimal implementation (append to domain.py)**

```python
class ParsedPlace(BaseModel):
    """Result of parsing one flat GEDCOM-style place string (positional, country last)."""

    raw: str
    commune: str = ""
    insee: str | None = None            # 5-char INSEE code if embedded
    postal: str | None = None
    departement: str = ""
    region: str = ""
    country: str = ""                   # normalized country label/ISO
    shifted: bool = False               # positional shift detected (no reliable code)


class PlaceLevel(BaseModel):
    """One node in a place's parent chain (top→down)."""

    name: str
    place_type: str                     # "Country" | "Region" | "Department" | "Municipality"…
    code: str | None = None


class DatedName(BaseModel):
    value: str
    date_qualifier: str | None = None   # None | "avant AAAA-MM-JJ" | "après AAAA-MM-JJ"


class DatedChain(BaseModel):
    """A parent chain valid over a period (top→down)."""

    levels: list[PlaceLevel]
    date_qualifier: str | None = None


class ResolvedPlace(BaseModel):
    """Normalized output every country resolver returns (the resolver contract)."""

    name: str
    place_type: str
    lat: str | None = None              # WGS84 decimal (never Swiss x/y grid)
    long: str | None = None
    code: str | None = None
    chains: list[DatedChain] = Field(default_factory=list)
    alt_names: list[DatedName] = Field(default_factory=list)
    score: float                        # 1.0 authoritative ; <1.0 fuzzy
    ambiguous: bool = False             # ambiguity guard (spec §5) → forces proposition
    source: str
    query: str


class PlaceProposition(BaseModel):
    """One place's standardization proposal (report + YAML)."""

    type: str                           # "lieu_resolu" | "lieu_indecidable"
    gramps_id: str
    handle: str
    original: str
    country: str
    resolution: ResolvedPlace | None = None
    action: str                         # "ecrire" | "proposition" | "indecidable"
    confiance: str                      # "haute" | "moyenne" | "basse"
    priorite: str
    preuve: str


class PlaceMergeProposition(BaseModel):
    """Two existing leaf places resolving to the same canonical place (dedup). Never auto."""

    gramps_id_keep: str
    handle_keep: str
    gramps_id_merge: str
    handle_merge: str
    canonical: str
    reason: str
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /Users/fjacquet/Projects/crewai_custom_tools && uv run python -m pytest tests/test_genealogy_places_models.py -q`
Expected: PASS (2 tests).

- [ ] **Step 5: Commit**

```bash
git add crewai_custom_tools/src/crewai_custom_tools/tools/genealogy/models/domain.py \
        crewai_custom_tools/tests/test_genealogy_places_models.py
git commit -m "feat(genealogy): place domain models (ParsedPlace, ResolvedPlace, proposals)"
```

---

### Task 2: Parser positionnel + normalisation pays (standardize/places.py)

**Files:**

- Create: `crewai_custom_tools/src/crewai_custom_tools/tools/genealogy/standardize/places.py`
- Test: `crewai_custom_tools/tests/test_genealogy_places_parse.py`

**Interfaces:**

- Consumes: `ParsedPlace` (Task 1).
- Produces: `parse_pname(raw: str) -> ParsedPlace` ; `normalize_country(raw: str) -> str` (label canonique, "" si vide/inconnu).

- [ ] **Step 1: Write the failing test**

```python
# tests/test_genealogy_places_parse.py
from crewai_custom_tools.tools.genealogy.standardize.places import (
    normalize_country, parse_pname,
)


def test_parse_aligned_fr_with_insee():
    p = parse_pname(", , Bourges, 18033, 18000, Cher, Centre-Val de Loire, France")
    assert (p.commune, p.insee, p.postal) == ("Bourges", "18033", "18000")
    assert (p.departement, p.region, p.country) == ("Cher", "Centre-Val de Loire", "France")
    assert p.shifted is False


def test_parse_shifted_fr_without_code_flags_shift():
    # établissement en tête, pas de code INSEE trouvé pour un lieu français
    p = parse_pname("Hôpital, , , , , , , France")
    assert p.insee is None
    assert p.shifted is True
    assert p.country == "France"


def test_parse_non_fr_no_code_not_shifted():
    p = parse_pname(", , Zürich, , , , , Suisse")
    assert p.commune == "Zürich"
    assert p.insee is None
    assert p.country == "Suisse"
    assert p.shifted is False            # hors FR : pas de code attendu → pas un décalage


def test_normalize_country_variants():
    assert normalize_country("FRANCE") == "France"
    assert normalize_country("Switzerland") == "Suisse"
    assert normalize_country("Germany>") == "Allemagne"
    assert normalize_country("Algerie") == "Algérie"
    assert normalize_country("") == ""
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/fjacquet/Projects/crewai_custom_tools && uv run python -m pytest tests/test_genealogy_places_parse.py -q`
Expected: FAIL (`ModuleNotFoundError` on `standardize.places`).

- [ ] **Step 3: Write minimal implementation**

```python
# standardize/places.py
"""Pure parsing of flat GEDCOM-style place strings + country normalization.

A GEDCOM place is comma-delimited, most-specific first, country last. Import
tools (Geneanet/Heredis) often embed an INSEE code. This module is dataset-
agnostic: it reads positions and known-code shapes, it does not hardcode any
particular tree.
"""

from __future__ import annotations

import re
import unicodedata

from crewai_custom_tools.tools.genealogy.models.domain import ParsedPlace

INSEE_RE = re.compile(r"^(?:\d{5}|2[AB]\d{3})$")     # 18033, 2A004
POSTAL_RE = re.compile(r"^\d{4,5}$")

# Table de normalisation des pays : variantes (casse/langue/accent/parasite) → label FR.
_COUNTRY = {
    "france": "France",
    "suisse": "Suisse", "switzerland": "Suisse", "schweiz": "Suisse",
    "allemagne": "Allemagne", "germany": "Allemagne", "deutschland": "Allemagne",
    "italie": "Italie", "italia": "Italie", "italy": "Italie",
    "algerie": "Algérie", "algerie francaise": "Algérie", "algeria": "Algérie",
    "belgique": "Belgique", "belgium": "Belgique",
    "pologne": "Pologne", "poland": "Pologne",
    "etats-unis": "États-Unis", "usa": "États-Unis", "united states": "États-Unis",
}


def _strip_accents(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", s) if unicodedata.category(c) != "Mn")


def normalize_country(raw: str) -> str:
    """Map a messy country segment to a canonical French label ('' if empty/unknown)."""
    key = _strip_accents(raw).strip().strip(">").strip().lower()
    if not key:
        return ""
    return _COUNTRY.get(key, raw.strip().strip(">").strip())


def parse_pname(raw: str) -> ParsedPlace:
    """Parse one flat place string into ParsedPlace (positional + code detection)."""
    segments = [s.strip() for s in raw.split(",")]
    nonempty = [s for s in segments if s]
    country = normalize_country(nonempty[-1]) if nonempty else ""

    insee = next((s for s in segments if INSEE_RE.match(s)), None)
    postal = next((s for s in segments if s != insee and POSTAL_RE.match(s)), None)

    commune = ""
    if insee is not None:
        idx = segments.index(insee)
        commune = segments[idx - 1] if idx > 0 else ""
    else:
        # pas de code : commune = 1er segment non vide qui n'est pas le pays
        for s in nonempty[:-1] or nonempty:
            if s and not POSTAL_RE.match(s):
                commune = s
                break

    # département / région : segments non vides entre le code postal et le pays
    tail = [s for s in nonempty if s not in (commune, insee, postal, nonempty[-1] if nonempty else "")]
    departement = tail[0] if len(tail) >= 1 else ""
    region = tail[1] if len(tail) >= 2 else ""

    shifted = country == "France" and insee is None
    return ParsedPlace(raw=raw, commune=commune, insee=insee, postal=postal,
                       departement=departement, region=region, country=country, shifted=shifted)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /Users/fjacquet/Projects/crewai_custom_tools && uv run python -m pytest tests/test_genealogy_places_parse.py -q`
Expected: PASS (4 tests).

- [ ] **Step 5: Commit**

```bash
git add crewai_custom_tools/src/crewai_custom_tools/tools/genealogy/standardize/places.py \
        crewai_custom_tools/tests/test_genealogy_places_parse.py
git commit -m "feat(genealogy): pure pname parser + country normalization"
```

---

### Task 3: Score et garde-fou d'ambiguïté (geo/score.py)

**Files:**

- Create: `crewai_custom_tools/src/crewai_custom_tools/tools/genealogy/geo/__init__.py` (empty)
- Create: `crewai_custom_tools/src/crewai_custom_tools/tools/genealogy/geo/score.py`
- Test: `crewai_custom_tools/tests/test_genealogy_places_score.py`

**Interfaces:**

- Produces: `similarity(a: str, b: str) -> float` ; `fuzzy_score(provider_conf: float, asked: str, returned: str) -> float` ; `is_ambiguous(candidates: list[float], margin: float = 0.10) -> bool` ; constant `AMBIGUITY_MARGIN = 0.10`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_genealogy_places_score.py
from crewai_custom_tools.tools.genealogy.geo.score import (
    fuzzy_score, is_ambiguous, similarity,
)


def test_similarity_accent_and_case_insensitive():
    assert similarity("Zürich", "ZURICH") > 0.99


def test_fuzzy_score_penalizes_wrong_name():
    good = fuzzy_score(0.9, "Bourges", "Bourges")
    bad = fuzzy_score(0.9, "Bourges", "Paris")
    assert good > bad
    assert 0.0 <= bad <= good <= 1.0


def test_ambiguity_margin():
    assert is_ambiguous([0.95, 0.90]) is True      # marge 0.05 < 0.10
    assert is_ambiguous([0.95, 0.70]) is False     # marge 0.25 ≥ 0.10
    assert is_ambiguous([0.95]) is False           # un seul candidat
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/fjacquet/Projects/crewai_custom_tools && uv run python -m pytest tests/test_genealogy_places_score.py -q`
Expected: FAIL (`ModuleNotFoundError` on `geo.score`).

- [ ] **Step 3: Write minimal implementation**

```python
# geo/score.py
"""Pure scoring for place resolution (dataset-agnostic)."""

from __future__ import annotations

import unicodedata
from difflib import SequenceMatcher

AMBIGUITY_MARGIN = 0.10


def _norm(s: str) -> str:
    s = "".join(c for c in unicodedata.normalize("NFD", s) if unicodedata.category(c) != "Mn")
    return s.strip().upper()


def similarity(a: str, b: str) -> float:
    """Accent/case-insensitive string similarity in [0,1]."""
    return SequenceMatcher(None, _norm(a), _norm(b)).ratio()


def fuzzy_score(provider_conf: float, asked: str, returned: str) -> float:
    """Combine provider confidence with name similarity (penalizes 'right score, wrong place')."""
    return max(0.0, min(1.0, provider_conf)) * similarity(asked, returned)


def is_ambiguous(candidates: list[float], margin: float = AMBIGUITY_MARGIN) -> bool:
    """True when the top two candidate scores are within `margin` (undecidable → proposition)."""
    if len(candidates) < 2:
        return False
    top2 = sorted(candidates, reverse=True)[:2]
    return (top2[0] - top2[1]) < margin
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /Users/fjacquet/Projects/crewai_custom_tools && uv run python -m pytest tests/test_genealogy_places_score.py -q`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add crewai_custom_tools/src/crewai_custom_tools/tools/genealogy/geo/__init__.py \
        crewai_custom_tools/src/crewai_custom_tools/tools/genealogy/geo/score.py \
        crewai_custom_tools/tests/test_genealogy_places_score.py
git commit -m "feat(genealogy): pure place score + ambiguity guard"
```

---

### Task 4: Résolveur France (geo/france.py)

**Files:**

- Create: `crewai_custom_tools/src/crewai_custom_tools/tools/genealogy/geo/france.py`
- Test: `crewai_custom_tools/tests/test_genealogy_geo_france.py`

**Interfaces:**

- Consumes: `ParsedPlace`, `ResolvedPlace`, `PlaceLevel`, `DatedChain`, `DatedName`.
- Produces: pure `map_commune(payload: dict, parsed: ParsedPlace) -> ResolvedPlace` (authoritative, INSEE code path) ; `_http_get(path: str, params: dict) -> dict` (monkeypatchable) ; `resolve_fr(parsed: ParsedPlace) -> ResolvedPlace | None`.
- Note: only the authoritative INSEE path is implemented here (score 1.0). The Géoplateforme fuzzy FR path is folded into the worldwide fuzzy fallback (Task 6/Task 7) for P1–P4 to avoid a second FR provider; `resolve_fr` returns `None` when there is no usable INSEE code, delegating to the fallback via the registry (Task 7).

- [ ] **Step 1: Write the failing test**

```python
# tests/test_genealogy_geo_france.py
from crewai_custom_tools.tools.genealogy.geo.france import map_commune, resolve_fr
from crewai_custom_tools.tools.genealogy.models.domain import ParsedPlace

# forme réelle de geo.api.gouv.fr/communes/{code}?fields=nom,centre,codeDepartement,...
PAYLOAD = {
    "nom": "Bourges", "code": "18033",
    "centre": {"type": "Point", "coordinates": [2.3992, 47.0810]},   # [lon, lat]
    "codeDepartement": "18", "codeRegion": "24",
    "departement": {"code": "18", "nom": "Cher"},
    "region": {"code": "24", "nom": "Centre-Val de Loire"},
}


def test_map_commune_wgs84_lonlat_and_hierarchy():
    parsed = ParsedPlace(raw="…", commune="Bourges", insee="18033", country="France")
    rp = map_commune(PAYLOAD, parsed)
    assert rp.name == "Bourges" and rp.place_type == "Municipality"
    assert rp.lat == "47.081" and rp.long == "2.3992"        # centre = [lon, lat] → long=lon, lat=lat
    assert rp.score == 1.0 and rp.source == "geo.api.gouv.fr"
    assert len(rp.chains) == 1 and rp.chains[0].date_qualifier is None
    names = [lvl.name for lvl in rp.chains[0].levels]
    assert names == ["France", "Centre-Val de Loire", "Cher"]   # haut→bas
    assert rp.alt_names[0].value == parsed.raw and rp.alt_names[0].date_qualifier is None


def test_resolve_fr_returns_none_without_insee(monkeypatch):
    parsed = ParsedPlace(raw="…", commune="X", insee=None, country="France", shifted=True)
    assert resolve_fr(parsed) is None                          # délègue au repli flou
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/fjacquet/Projects/crewai_custom_tools && uv run python -m pytest tests/test_genealogy_geo_france.py -q`
Expected: FAIL (`ModuleNotFoundError` on `geo.france`).

- [ ] **Step 3: Write minimal implementation**

```python
# geo/france.py
"""France resolver: authoritative INSEE-code → geo.api.gouv.fr commune."""

from __future__ import annotations

import httpx

from crewai_custom_tools.tools.genealogy.models.domain import (
    DatedChain, DatedName, ParsedPlace, PlaceLevel, ResolvedPlace,
)

_BASE = "https://geo.api.gouv.fr"
_FIELDS = "nom,code,centre,departement,region"


def _http_get(path: str, params: dict) -> dict:
    """Thin HTTP GET (monkeypatched in tests). WGS84 GeoJSON out."""
    resp = httpx.get(f"{_BASE}{path}", params=params, timeout=15.0)
    resp.raise_for_status()
    return resp.json()


def map_commune(payload: dict, parsed: ParsedPlace) -> ResolvedPlace:
    """Pure map of a geo.api.gouv.fr commune payload → authoritative ResolvedPlace."""
    lon, lat = payload["centre"]["coordinates"]            # GeoJSON = [lon, lat]
    dep = payload.get("departement") or {}
    reg = payload.get("region") or {}
    levels = [PlaceLevel(name="France", place_type="Country")]
    if reg.get("nom"):
        levels.append(PlaceLevel(name=reg["nom"], place_type="Region", code=reg.get("code")))
    if dep.get("nom"):
        levels.append(PlaceLevel(name=dep["nom"], place_type="Department", code=dep.get("code")))
    return ResolvedPlace(
        name=payload["nom"], place_type="Municipality",
        lat=str(lat), long=str(lon), code=payload.get("code"),
        chains=[DatedChain(levels=levels)],
        alt_names=[DatedName(value=parsed.raw)],
        score=1.0, source="geo.api.gouv.fr", query=f"/communes/{parsed.insee}",
    )


def resolve_fr(parsed: ParsedPlace) -> ResolvedPlace | None:
    """Resolve a French place by embedded INSEE code (authoritative). None if no usable code."""
    if not parsed.insee:
        return None
    payload = _http_get(f"/communes/{parsed.insee}", {"fields": _FIELDS})
    if not isinstance(payload, dict) or "centre" not in payload:
        return None
    return map_commune(payload, parsed)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /Users/fjacquet/Projects/crewai_custom_tools && uv run python -m pytest tests/test_genealogy_geo_france.py -q`
Expected: PASS (2 tests).

- [ ] **Step 5: Commit**

```bash
git add crewai_custom_tools/src/crewai_custom_tools/tools/genealogy/geo/france.py \
        crewai_custom_tools/tests/test_genealogy_geo_france.py
git commit -m "feat(genealogy): France INSEE authoritative resolver"
```

---

### Task 5: Résolveur Suisse (geo/suisse.py)

**Files:**

- Create: `crewai_custom_tools/src/crewai_custom_tools/tools/genealogy/geo/suisse.py`
- Test: `crewai_custom_tools/tests/test_genealogy_geo_suisse.py`

**Interfaces:**

- Produces: pure `map_swiss(search_payload: dict, parsed: ParsedPlace) -> ResolvedPlace | None` (swisstopo GeoAdmin SearchServer → GPS + name) ; `_http_get(url: str, params: dict) -> dict` ; `resolve_ch(parsed: ParsedPlace) -> ResolvedPlace | None`.
- GPS gotcha: read `attrs.lat`/`attrs.lon` (WGS84), **never** `attrs.x`/`attrs.y` (LV95).

- [ ] **Step 1: Write the failing test**

```python
# tests/test_genealogy_geo_suisse.py
from crewai_custom_tools.tools.genealogy.geo.suisse import map_swiss
from crewai_custom_tools.tools.genealogy.models.domain import ParsedPlace

# forme réelle api3.geo.admin.ch SearchServer (type=locations)
PAYLOAD = {"results": [{"attrs": {
    "label": "<b>Zürich</b>", "detail": "zürich zh", "origin": "gazetteer",
    "lat": 47.3769, "lon": 8.5417,          # WGS84 (à lire)
    "x": 1247000.0, "y": 2683000.0,          # LV95 (à IGNORER)
}}]}


def test_map_swiss_reads_latlon_not_xy():
    parsed = ParsedPlace(raw="…", commune="Zürich", country="Suisse")
    rp = map_swiss(PAYLOAD, parsed)
    assert rp is not None
    assert rp.lat == "47.3769" and rp.long == "8.5417"   # jamais 1247000/2683000
    assert rp.source == "swisstopo"
    assert rp.name == "Zürich"                            # label nettoyé des <b>
    assert rp.chains[0].levels[0].name == "Suisse"
    assert 0.0 < rp.score <= 1.0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/fjacquet/Projects/crewai_custom_tools && uv run python -m pytest tests/test_genealogy_geo_suisse.py -q`
Expected: FAIL (`ModuleNotFoundError` on `geo.suisse`).

- [ ] **Step 3: Write minimal implementation**

```python
# geo/suisse.py
"""Switzerland resolver: swisstopo GeoAdmin SearchServer (WGS84 lat/lon)."""

from __future__ import annotations

import re

import httpx

from crewai_custom_tools.tools.genealogy.geo.score import fuzzy_score, is_ambiguous
from crewai_custom_tools.tools.genealogy.models.domain import (
    DatedChain, DatedName, ParsedPlace, PlaceLevel, ResolvedPlace,
)

_URL = "https://api3.geo.admin.ch/rest/services/api/SearchServer"
_TAG = re.compile(r"<[^>]+>")


def _http_get(url: str, params: dict) -> dict:
    resp = httpx.get(url, params=params, timeout=15.0)
    resp.raise_for_status()
    return resp.json()


def map_swiss(payload: dict, parsed: ParsedPlace) -> ResolvedPlace | None:
    """Pure map of a swisstopo SearchServer payload → ResolvedPlace (lat/lon WGS84)."""
    results = payload.get("results") or []
    if not results:
        return None
    scores = [fuzzy_score(1.0, parsed.commune, _TAG.sub("", r["attrs"].get("label", "")))
              for r in results]
    attrs = results[0]["attrs"]
    name = _TAG.sub("", attrs.get("label", "")).strip()
    return ResolvedPlace(
        name=name or parsed.commune, place_type="Municipality",
        lat=str(attrs["lat"]), long=str(attrs["lon"]),     # WGS84 ; jamais x/y (LV95)
        chains=[DatedChain(levels=[PlaceLevel(name="Suisse", place_type="Country")])],
        alt_names=[DatedName(value=parsed.raw)],
        score=scores[0], ambiguous=is_ambiguous(scores),
        source="swisstopo", query=parsed.commune,
    )


def resolve_ch(parsed: ParsedPlace) -> ResolvedPlace | None:
    """Resolve a Swiss place by name via swisstopo. None if no commune to search."""
    if not parsed.commune:
        return None
    payload = _http_get(_URL, {"searchText": parsed.commune, "type": "locations",
                               "sr": "4326", "limit": 5})
    return map_swiss(payload, parsed)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /Users/fjacquet/Projects/crewai_custom_tools && uv run python -m pytest tests/test_genealogy_geo_suisse.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add crewai_custom_tools/src/crewai_custom_tools/tools/genealogy/geo/suisse.py \
        crewai_custom_tools/tests/test_genealogy_geo_suisse.py
git commit -m "feat(genealogy): Switzerland swisstopo resolver (WGS84 lat/lon)"
```

---

### Task 6: Résolveur mondial Nominatim (geo/nominatim.py)

**Files:**

- Create: `crewai_custom_tools/src/crewai_custom_tools/tools/genealogy/geo/nominatim.py`
- Test: `crewai_custom_tools/tests/test_genealogy_geo_nominatim.py`

**Interfaces:**

- Produces: pure `map_nominatim(results: list[dict], parsed: ParsedPlace) -> ResolvedPlace | None` ; `_http_get(params: dict) -> list` ; `resolve_world(parsed: ParsedPlace) -> ResolvedPlace | None`.
- Nominatim result carries `lat`, `lon` (strings, WGS84) and `importance` (0..1) as provider confidence.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_genealogy_geo_nominatim.py
from crewai_custom_tools.tools.genealogy.geo.nominatim import map_nominatim
from crewai_custom_tools.tools.genealogy.models.domain import ParsedPlace

RESULTS = [
    {"display_name": "Alger, Algérie", "lat": "36.7538", "lon": "3.0588", "importance": 0.82},
    {"display_name": "Alger (autre)", "lat": "0", "lon": "0", "importance": 0.40},
]


def test_map_nominatim_score_and_gps():
    parsed = ParsedPlace(raw="…", commune="Alger", country="Algérie")
    rp = map_nominatim(RESULTS, parsed)
    assert rp.lat == "36.7538" and rp.long == "3.0588"
    assert rp.source == "Nominatim/OSM"
    assert 0.0 < rp.score <= 1.0
    assert rp.ambiguous is False           # 0.82 vs 0.40 top-conf → marge large
    assert rp.chains[0].levels[0].name == "Algérie"   # pays parent depuis parsed.country


def test_map_nominatim_empty_returns_none():
    assert map_nominatim([], ParsedPlace(raw="x", commune="Nowhere")) is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/fjacquet/Projects/crewai_custom_tools && uv run python -m pytest tests/test_genealogy_geo_nominatim.py -q`
Expected: FAIL (`ModuleNotFoundError` on `geo.nominatim`).

- [ ] **Step 3: Write minimal implementation**

```python
# geo/nominatim.py
"""Worldwide fallback resolver: Nominatim/OSM (ODbL, 1 req/s, User-Agent)."""

from __future__ import annotations

import httpx

from crewai_custom_tools.tools.genealogy.geo.score import fuzzy_score, is_ambiguous
from crewai_custom_tools.tools.genealogy.models.domain import (
    DatedChain, DatedName, ParsedPlace, PlaceLevel, ResolvedPlace,
)

_URL = "https://nominatim.openstreetmap.org/search"
_UA = "genecrew/1.0 (genealogy place standardizer; +https://github.com/)"


def _http_get(params: dict) -> list:
    resp = httpx.get(_URL, params=params, headers={"User-Agent": _UA}, timeout=15.0)
    resp.raise_for_status()
    return resp.json()


def map_nominatim(results: list[dict], parsed: ParsedPlace) -> ResolvedPlace | None:
    """Pure map of Nominatim results → ResolvedPlace (worldwide, fuzzy)."""
    if not results:
        return None
    scores = [fuzzy_score(float(r.get("importance", 0.0)), parsed.commune,
                          r.get("display_name", "").split(",")[0]) for r in results]
    top = results[0]
    levels = []
    if parsed.country:
        levels.append(PlaceLevel(name=parsed.country, place_type="Country"))
    return ResolvedPlace(
        name=top.get("display_name", parsed.commune).split(",")[0].strip(),
        place_type="Municipality",
        lat=str(top["lat"]), long=str(top["lon"]),
        chains=[DatedChain(levels=levels)],
        alt_names=[DatedName(value=parsed.raw)],
        score=scores[0], ambiguous=is_ambiguous(scores),
        source="Nominatim/OSM", query=f"{parsed.commune}, {parsed.country}".strip(", "),
    )


def resolve_world(parsed: ParsedPlace) -> ResolvedPlace | None:
    """Resolve any place by name via Nominatim. None if nothing to search."""
    if not parsed.commune:
        return None
    q = f"{parsed.commune}, {parsed.country}".strip(", ")
    return map_nominatim(_http_get({"q": q, "format": "jsonv2", "limit": 5}), parsed)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /Users/fjacquet/Projects/crewai_custom_tools && uv run python -m pytest tests/test_genealogy_geo_nominatim.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add crewai_custom_tools/src/crewai_custom_tools/tools/genealogy/geo/nominatim.py \
        crewai_custom_tools/tests/test_genealogy_geo_nominatim.py
git commit -m "feat(genealogy): worldwide Nominatim fallback resolver"
```

---

### Task 7: Registre de routage + décision d'action (geo/registry.py)

**Files:**

- Create: `crewai_custom_tools/src/crewai_custom_tools/tools/genealogy/geo/registry.py`
- Test: `crewai_custom_tools/tests/test_genealogy_geo_registry.py`

**Interfaces:**

- Consumes: `resolve_fr` (Task 4), `resolve_ch` (Task 5), `resolve_world` (Task 6), `ParsedPlace`, `ResolvedPlace`.
- Produces: `resolve_place(parsed: ParsedPlace) -> ResolvedPlace | None` (route par pays, repli mondial) ; `decide_action(resolved: ResolvedPlace | None, min_score: float) -> str` ; `confiance_of(resolved: ResolvedPlace | None) -> str`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_genealogy_geo_registry.py
from crewai_custom_tools.tools.genealogy.geo import registry
from crewai_custom_tools.tools.genealogy.models.domain import ParsedPlace, ResolvedPlace


def _rp(score, ambiguous=False):
    return ResolvedPlace(name="X", place_type="Municipality", score=score,
                         ambiguous=ambiguous, source="s", query="q")


def test_route_france_uses_fr_resolver(monkeypatch):
    called = {}
    monkeypatch.setattr(registry, "resolve_fr", lambda p: called.setdefault("fr", _rp(1.0)))
    monkeypatch.setattr(registry, "resolve_world", lambda p: _rp(0.5))
    out = registry.resolve_place(ParsedPlace(raw="…", commune="Bourges",
                                             insee="18033", country="France"))
    assert out.score == 1.0 and "fr" in called          # FR autoritaire, pas de repli


def test_route_falls_back_to_world_when_country_resolver_returns_none(monkeypatch):
    monkeypatch.setattr(registry, "resolve_fr", lambda p: None)     # pas d'INSEE utilisable
    monkeypatch.setattr(registry, "resolve_world", lambda p: _rp(0.93))
    out = registry.resolve_place(ParsedPlace(raw="…", commune="X",
                                             insee=None, country="France", shifted=True))
    assert out.score == 0.93                             # repli mondial


def test_decide_action_thresholds():
    assert registry.decide_action(_rp(1.0), 0.90) == "ecrire"
    assert registry.decide_action(_rp(0.92), 0.90) == "ecrire"
    assert registry.decide_action(_rp(0.92, ambiguous=True), 0.90) == "proposition"
    assert registry.decide_action(_rp(0.80), 0.90) == "proposition"
    assert registry.decide_action(None, 0.90) == "indecidable"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/fjacquet/Projects/crewai_custom_tools && uv run python -m pytest tests/test_genealogy_geo_registry.py -q`
Expected: FAIL (`ModuleNotFoundError` on `geo.registry`).

- [ ] **Step 3: Write minimal implementation**

```python
# geo/registry.py
"""Country-routed resolver chain + action/confidence decision (dataset-agnostic)."""

from __future__ import annotations

from crewai_custom_tools.tools.genealogy.geo.france import resolve_fr
from crewai_custom_tools.tools.genealogy.geo.nominatim import resolve_world
from crewai_custom_tools.tools.genealogy.geo.suisse import resolve_ch
from crewai_custom_tools.tools.genealogy.models.domain import ParsedPlace, ResolvedPlace

# Résolveurs autoritaires par pays. Ajouter un pays = une ligne (générique).
_BY_COUNTRY = {
    "France": lambda p: resolve_fr(p),
    "Suisse": lambda p: resolve_ch(p),
}


def resolve_place(parsed: ParsedPlace) -> ResolvedPlace | None:
    """Route to the country resolver; fall back to the worldwide fuzzy resolver."""
    country_resolver = _BY_COUNTRY.get(parsed.country)
    if country_resolver is not None:
        resolved = country_resolver(parsed)
        if resolved is not None:
            return resolved
    return resolve_world(parsed)


def decide_action(resolved: ResolvedPlace | None, min_score: float) -> str:
    """Map a resolution to 'ecrire' | 'proposition' | 'indecidable'."""
    if resolved is None:
        return "indecidable"
    if resolved.score >= 1.0:
        return "ecrire"
    if resolved.score >= min_score and not resolved.ambiguous:
        return "ecrire"
    return "proposition"


def confiance_of(resolved: ResolvedPlace | None) -> str:
    if resolved is None:
        return "basse"
    if resolved.score >= 1.0:
        return "haute"
    if resolved.score >= 0.90 and not resolved.ambiguous:
        return "moyenne"
    return "basse"
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /Users/fjacquet/Projects/crewai_custom_tools && uv run python -m pytest tests/test_genealogy_geo_registry.py -q`
Expected: PASS (4 tests).

- [ ] **Step 5: Commit**

```bash
git add crewai_custom_tools/src/crewai_custom_tools/tools/genealogy/geo/registry.py \
        crewai_custom_tools/tests/test_genealogy_geo_registry.py
git commit -m "feat(genealogy): country-routed resolver registry + action decision"
```

---

### Task 8: Itérateur de lieux Gramps (genecrew batching.py)

**Files:**

- Modify: `genecrew/src/genecrew/batching.py` (append `iter_places`)
- Test: `genecrew/tests/test_places_batching.py`

**Interfaces:**

- Consumes: `GrampsClient` (has `.get_json`).
- Produces: `iter_places(client, scope, batch_size, limit) -> Iterator[list[dict]]` — yields batches of raw Gramps place JSON dicts (each has `handle`, `gramps_id`, `name`, `placeref_list`, `place_type`, `lat`, `long`).

- [ ] **Step 1: Write the failing test**

```python
# genecrew/tests/test_places_batching.py
import httpx
from crewai_custom_tools.tools.genealogy.gramps.client import GrampsClient, GrampsConfig
from genecrew.batching import iter_places

CONFIG = GrampsConfig(api_url="http://g.test/api", username="u", password="p")
PLACES = [{"handle": f"h{i}", "gramps_id": f"P{i:04d}",
           "name": {"value": f"L{i}"}, "place_type": "Unknown"} for i in range(3)]


def _handler(request):
    if request.url.path == "/api/token/":
        return httpx.Response(200, json={"access_token": "t"})
    if request.url.path == "/api/places/":
        page = int(request.url.params.get("page", "1"))
        return httpx.Response(200, json=PLACES if page == 1 else [])
    return httpx.Response(404)


def test_iter_places_paginates_and_limits():
    client = GrampsClient(CONFIG, transport=httpx.MockTransport(_handler))
    batches = list(iter_places(client, "all", batch_size=25, limit=2))
    flat = [p for b in batches for p in b]
    assert [p["handle"] for p in flat] == ["h0", "h1"]     # limit respecté
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/fjacquet/Projects/genecrew && uv run python -m pytest genecrew/tests/test_places_batching.py -q`
Expected: FAIL (`ImportError: cannot import name 'iter_places'`).

- [ ] **Step 3: Write minimal implementation (append to batching.py)**

```python
def iter_places(client: GrampsClient, scope: str, batch_size: int, limit: int | None):
    """Yield successive batches of raw Gramps place dicts for `scope` (all supported in P1-P4)."""
    fetched = 0
    page = 1
    while True:
        places = client.get_json("/places/", params={"page": page, "pagesize": batch_size,
                                                      "sort": "gramps_id"})
        if not places:
            break
        if limit is not None and fetched + len(places) > limit:
            places = places[: limit - fetched]
        yield places
        fetched += len(places)
        if limit is not None and fetched >= limit:
            break
        page += 1
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /Users/fjacquet/Projects/genecrew && uv run python -m pytest genecrew/tests/test_places_batching.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add genecrew/src/genecrew/batching.py genecrew/tests/test_places_batching.py
git commit -m "feat(places): paginated raw place iterator"
```

---

### Task 9: Orchestration lecture seule + rapport (genecrew places.py)

**Files:**

- Create: `genecrew/src/genecrew/places.py`
- Test: `genecrew/tests/test_places.py`

**Interfaces:**

- Consumes: `iter_places` (Task 8) ; `parse_pname` (Task 2) ; `registry.resolve_place`, `registry.decide_action`, `registry.confiance_of` (Task 7) ; `PlaceProposition`.
- Produces: `run_places(client, scope, output_dir, *, date, batch_size=25, limit=None, min_score=0.90) -> tuple[Path, Path]` (rapport MD + YAML) ; `render_places_report(scope, date, props, base_url="http://localhost") -> str` (pur) ; `build_proposition(place: dict, min_score: float) -> PlaceProposition` (pur-ish : appelle resolve_place).

- [ ] **Step 1: Write the failing test**

```python
# genecrew/tests/test_places.py
import httpx
import pytest
from crewai_custom_tools.tools.genealogy.gramps.client import GrampsClient, GrampsConfig
from crewai_custom_tools.tools.genealogy.models.domain import (
    DatedChain, PlaceLevel, ResolvedPlace,
)
from genecrew import places
from genecrew.places import render_places_report, run_places

CONFIG = GrampsConfig(api_url="http://g.test/api", username="u", password="p")
PLACES = [{"handle": "h1", "gramps_id": "P0001",
           "name": {"value": ", , Bourges, 18033, 18000, Cher, Centre-Val de Loire, France"},
           "place_type": "Unknown"}]


def _handler(request):
    if request.url.path == "/api/token/":
        return httpx.Response(200, json={"access_token": "t"})
    if request.url.path == "/api/places/":
        page = int(request.url.params.get("page", "1"))
        return httpx.Response(200, json=PLACES if page == 1 else [])
    return httpx.Response(404)


def _authoritative(parsed):
    return ResolvedPlace(name="Bourges", place_type="Municipality", lat="47.081", long="2.399",
                         code="18033",
                         chains=[DatedChain(levels=[PlaceLevel(name="France", place_type="Country")])],
                         score=1.0, source="geo.api.gouv.fr", query="/communes/18033")


def test_run_places_readonly_writes_reports_no_http_write(tmp_path, monkeypatch, mocker):
    monkeypatch.setattr(places, "resolve_place", _authoritative)     # pas de réseau
    client = GrampsClient(CONFIG, transport=httpx.MockTransport(_handler))
    report, yaml_path = run_places(client, "all", tmp_path, date="2026-07-19")
    md = report.read_text(encoding="utf-8")
    assert "Bourges" in md and "geo.api.gouv.fr" in md
    assert "ecrire" in md                       # action calculée mais RIEN écrit (lecture seule)
    assert yaml_path.exists()


def test_render_places_report_has_links_and_sections():
    from crewai_custom_tools.tools.genealogy.models.domain import PlaceProposition
    md = render_places_report("all", "2026-07-19", [PlaceProposition(
        type="lieu_resolu", gramps_id="P0001", handle="h1", original="…", country="France",
        resolution=_authoritative(None), action="ecrire", confiance="haute",
        priorite="haute", preuve="geo.api.gouv.fr | /communes/18033 | score 1.000")])
    assert "[P0001](http://localhost/place/P0001)" in md and "ecrire" in md
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/fjacquet/Projects/genecrew && uv run python -m pytest genecrew/tests/test_places.py -q`
Expected: FAIL (`ModuleNotFoundError` on `genecrew.places`).

- [ ] **Step 3: Write minimal implementation**

```python
# genecrew/src/genecrew/places.py
"""Read-only places standardization: parse, resolve, emit proposals. Never writes."""

from __future__ import annotations

from pathlib import Path

import yaml

from crewai_custom_tools.tools.genealogy.geo.registry import (
    confiance_of, decide_action, resolve_place,
)
from crewai_custom_tools.tools.genealogy.gramps.client import GrampsClient
from crewai_custom_tools.tools.genealogy.models.domain import PlaceProposition
from crewai_custom_tools.tools.genealogy.standardize.places import parse_pname

from genecrew.batching import iter_places

_PRIORITE = {"haute": 0, "moyenne": 1, "basse": 2}


def _link(gramps_id: str, base_url: str) -> str:
    return f"[{gramps_id}]({base_url}/place/{gramps_id})"


def build_proposition(place: dict, min_score: float) -> PlaceProposition:
    """Parse + resolve one raw Gramps place into a PlaceProposition."""
    original = (place.get("name") or {}).get("value", "")
    parsed = parse_pname(original)
    resolved = resolve_place(parsed)
    action = decide_action(resolved, min_score)
    if resolved is not None:
        preuve = f"{resolved.source} | {resolved.query} | score {resolved.score:.3f}"
        priorite = "haute" if resolved.score >= 1.0 else "moyenne"
    else:
        preuve = f"non résolu (pays={parsed.country or '?'}, décalé={parsed.shifted})"
        priorite = "basse"
    return PlaceProposition(
        type="lieu_resolu" if resolved is not None else "lieu_indecidable",
        gramps_id=place.get("gramps_id", ""), handle=place.get("handle", ""),
        original=original, country=parsed.country, resolution=resolved,
        action=action, confiance=confiance_of(resolved), priorite=priorite, preuve=preuve)


def render_places_report(scope, date, props, base_url="http://localhost") -> str:
    """Pure Markdown report grouped by action, priority-sorted."""
    props = sorted(props, key=lambda p: _PRIORITE.get(p.priorite, 9))
    n = {a: sum(1 for p in props if p.action == a) for a in ("ecrire", "proposition", "indecidable")}
    lines = [f"# Standardisation des lieux — {scope} — {date}", "",
             "## Synthèse", "",
             f"- Lieux analysés : {len(props)}",
             f"- À écrire (score ≥ seuil) : {n['ecrire']}",
             f"- Propositions (revue) : {n['proposition']}",
             f"- Indécidables : {n['indecidable']}", "",
             "## Détail", "",
             "| Lieu | Pays | Action | Nom proposé | Score | Confiance | Preuve |",
             "|---|---|---|---|---|---|---|"]
    for p in props:
        nom = p.resolution.name if p.resolution else "—"
        score = f"{p.resolution.score:.3f}" if p.resolution else "—"
        lines.append(f"| {_link(p.gramps_id, base_url)} | {p.country or '?'} | {p.action} "
                     f"| {nom} | {score} | {p.confiance} | {p.preuve} |")
    lines.append("")
    return "\n".join(lines)


def render_propositions_yaml(props: list[PlaceProposition]) -> str:
    return yaml.safe_dump([p.model_dump() for p in props], allow_unicode=True, sort_keys=False)


def run_places(client: GrampsClient, scope: str, output_dir, *, date: str,
               batch_size: int = 25, limit: int | None = None,
               min_score: float = 0.90) -> tuple[Path, Path]:
    """Resolve places over `scope`; write a Markdown report + YAML proposals. Read-only."""
    output_dir = Path(output_dir)
    props: list[PlaceProposition] = []
    for batch in iter_places(client, scope, batch_size, limit):
        for place in batch:
            props.append(build_proposition(place, min_score))
    out = output_dir / "lieux"
    out.mkdir(parents=True, exist_ok=True)
    scope_slug = scope.replace(":", "_")
    report_path = out / f"{date}_lieux_{scope_slug}.md"
    report_path.write_text(render_places_report(scope, date, props), encoding="utf-8")
    yaml_path = out / f"{date}_propositions_lieux_{scope_slug}.yaml"
    yaml_path.write_text(render_propositions_yaml(props), encoding="utf-8")
    return report_path, yaml_path
```

Note: `run_places` references `resolve_place` imported at module top; the test monkeypatches `genecrew.places.resolve_place`, so `build_proposition` must call the module-level name (it does, via the import). Keep the import as `from …registry import … resolve_place`.

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /Users/fjacquet/Projects/genecrew && uv run python -m pytest genecrew/tests/test_places.py -q`
Expected: PASS (2 tests).

- [ ] **Step 5: Commit**

```bash
git add genecrew/src/genecrew/places.py genecrew/tests/test_places.py
git commit -m "feat(places): read-only run_places + Markdown/YAML report"
```

---

### Task 10: CLI `lieux` (genecrew main.py)

**Files:**

- Modify: `genecrew/src/genecrew/main.py` (add `lieux_cmd` + subparser + dispatch)
- Test: `genecrew/tests/test_cli_lieux.py`

**Interfaces:**

- Consumes: `run_places` (Task 9).
- Produces: CLI subcommand `genecrew lieux --scope --limit --batch-size --min-score --date`.

- [ ] **Step 1: Write the failing test**

```python
# genecrew/tests/test_cli_lieux.py
import subprocess


def test_lieux_help_lists_min_score():
    out = subprocess.run(["uv", "run", "genecrew", "lieux", "--help"],
                         capture_output=True, text=True, cwd="/Users/fjacquet/Projects/genecrew")
    assert out.returncode == 0
    assert "--min-score" in out.stdout and "--scope" in out.stdout
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/fjacquet/Projects/genecrew && uv run python -m pytest genecrew/tests/test_cli_lieux.py -q`
Expected: FAIL (subcommand `lieux` unknown → non-zero return).

- [ ] **Step 3: Write minimal implementation**

Add `lieux_cmd` (after `apply_all_cmd`):

```python
def lieux_cmd(args) -> None:
    """Standardize places over a scope (read-only); print the report paths."""
    from pathlib import Path

    from crewai_custom_tools.tools.genealogy.gramps.client import GrampsClient, GrampsConfig

    from genecrew.places import run_places

    client = GrampsClient(GrampsConfig.from_env())
    output_dir = Path(os.environ.get("GENECREW_OUTPUT_DIR", "output"))
    date = args.date or __import__("datetime").date.today().isoformat()
    report, proposals = run_places(client, args.scope, output_dir, date=date,
                                   batch_size=args.batch_size, limit=args.limit,
                                   min_score=args.min_score)
    print(f"Rapport : {report}")
    print(f"Propositions : {proposals}")
```

Add the subparser (after the `apply-all` block):

```python
    lieux_p = sub.add_parser("lieux", help="Standardisation des lieux (lecture seule)")
    lieux_p.add_argument("--scope", default="all", help="all | person:ID")
    lieux_p.add_argument("--limit", type=int, default=None, help="limiter à N lieux")
    lieux_p.add_argument("--batch-size", type=int,
                         default=int(os.environ.get("GENECREW_BATCH_SIZE", "25")))
    lieux_p.add_argument("--min-score", type=float, default=0.90,
                         help="seuil de score pour action=ecrire (défaut 0.90)")
    lieux_p.add_argument("--date", default=None, help="date du rapport (défaut : aujourd'hui)")
```

Add dispatch (in `main`, after the `apply-all` branch):

```python
    elif args.command == "lieux":
        lieux_cmd(args)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /Users/fjacquet/Projects/genecrew && uv run python -m pytest genecrew/tests/test_cli_lieux.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add genecrew/src/genecrew/main.py genecrew/tests/test_cli_lieux.py
git commit -m "feat(places): genecrew lieux CLI subcommand (read-only)"
```

---

### Task 11: Outils d'écriture de lieux (cct write_tools.py)

**Files:**

- Modify: `crewai_custom_tools/src/crewai_custom_tools/tools/genealogy/gramps/write_tools.py` (append two tools)
- Test: `crewai_custom_tools/tests/test_genealogy_place_write_tools.py`

**Interfaces:**

- Consumes: `effective_dry_run`, `get_client`, `ok`, `err`, `@api_tool`.
- Produces: `GrampsCreatePlaceTool` (`_run(name, place_type, parent_handle=None, date_qualifier=None, lat=None, long=None, code=None, dry_run=False) -> str`; returns `data.handle` — a real POST handle, or a synthetic `f"DRYRUN:{name}"` in dry-run) ; `GrampsUpdatePlaceTool` (`_run(handle, name, place_type, lat=None, long=None, code=None, placeref_list=None, alt_names=None, provenance=None, dry_run=False) -> str`; GET→modify→PUT, no-op when already conforming).

- [ ] **Step 1: Write the failing test**

```python
# crewai_custom_tools/tests/test_genealogy_place_write_tools.py
import json

import httpx
import pytest

from crewai_custom_tools.tools.genealogy.gramps.client import GrampsClient, GrampsConfig
from crewai_custom_tools.tools.genealogy.gramps import write_tools
from crewai_custom_tools.tools.genealogy.gramps.write_tools import (
    GrampsCreatePlaceTool, GrampsUpdatePlaceTool,
)

CONFIG = GrampsConfig(api_url="http://g.test/api", username="u", password="p")


@pytest.fixture(autouse=True)
def _no_global_dry_run(monkeypatch):
    monkeypatch.setenv("GENECREW_DRY_RUN", "false")


def _client(on_put=None, on_post=None, existing=None):
    def handler(request):
        if request.url.path == "/api/token/":
            return httpx.Response(200, json={"access_token": "t"})
        if request.method == "GET" and request.url.path.startswith("/api/places/"):
            return httpx.Response(200, json=existing or {})
        if request.method == "POST" and request.url.path == "/api/places/":
            return on_post(request) if on_post else httpx.Response(201, json={"handle": "NEW"})
        if request.method == "PUT":
            return on_put(request) if on_put else httpx.Response(200, json={})
        return httpx.Response(404)
    return GrampsClient(CONFIG, transport=httpx.MockTransport(handler))


def test_create_place_dry_run_returns_synthetic_handle(mocker):
    mocker.patch.object(write_tools, "get_client", return_value=_client())
    data = json.loads(GrampsCreatePlaceTool()._run(name="France", place_type="Country", dry_run=True))
    assert data["success"] is True
    assert data["data"]["handle"] == "DRYRUN:France"     # handle synthétique, aucun POST


def test_create_place_writes_and_returns_handle(mocker):
    posts = []

    def on_post(request):
        posts.append(json.loads(request.content))
        return httpx.Response(201, json={"handle": "H_FR"})

    mocker.patch.object(write_tools, "get_client", return_value=_client(on_post=on_post))
    data = json.loads(GrampsCreatePlaceTool()._run(name="France", place_type="Country"))
    assert data["data"]["handle"] == "H_FR" and len(posts) == 1
    assert posts[0]["place_type"] == "Country"


def test_update_place_noop_when_conforming(mocker):
    existing = {"handle": "h1", "gramps_id": "P1", "name": {"value": "Bourges"},
                "place_type": "Municipality", "lat": "47.081", "long": "2.399",
                "placeref_list": [{"ref": "H_CHER"}], "alt_names": []}

    def on_put(request):
        raise AssertionError("no PUT expected when already conforming")

    mocker.patch.object(write_tools, "get_client", return_value=_client(on_put=on_put, existing=existing))
    data = json.loads(GrampsUpdatePlaceTool()._run(
        handle="h1", name="Bourges", place_type="Municipality", lat="47.081", long="2.399",
        placeref_list=[{"ref": "H_CHER"}]))
    assert data["data"]["noop"] is True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/fjacquet/Projects/crewai_custom_tools && uv run python -m pytest tests/test_genealogy_place_write_tools.py -q`
Expected: FAIL (`ImportError` on `GrampsCreatePlaceTool`).

- [ ] **Step 3: Write minimal implementation (append to write_tools.py)**

```python
class GrampsCreatePlaceInput(BaseModel):
    name: str = Field(..., description="Place name value.")
    place_type: str = Field(..., description="Gramps place type (Country, Region, Department…).")
    parent_handle: str | None = Field(None, description="Handle of the parent place, if any.")
    date_qualifier: str | None = Field(None, description="Optional placeref date qualifier.")
    lat: str | None = Field(None, description="WGS84 latitude decimal string.")
    long: str | None = Field(None, description="WGS84 longitude decimal string.")
    code: str | None = Field(None, description="Place code (INSEE/OFS/postal).")
    dry_run: bool = Field(False, description="If true, simulate and return a synthetic handle.")


class GrampsCreatePlaceTool(BaseTool):
    """Create a parent/leaf place. Returns its handle (synthetic 'DRYRUN:<name>' in dry-run)."""

    name: str = "gramps_create_place"
    description: str = (
        "Creates a Gramps place with an optional parent (placeref). Returns the new handle. "
        "In dry-run (flag or GENECREW_DRY_RUN) it POSTs nothing and returns 'DRYRUN:<name>'."
    )
    args_schema: type[BaseModel] = GrampsCreatePlaceInput

    @api_tool(provider="GrampsWeb", endpoint="CreatePlace")
    def _run(self, name, place_type, parent_handle=None, date_qualifier=None,
             lat=None, long=None, code=None, dry_run=False) -> str:
        dry_run = effective_dry_run(dry_run)
        placeref_list = []
        if parent_handle:
            ref = {"ref": parent_handle}
            if date_qualifier:
                ref["_date_qualifier"] = date_qualifier      # P5 turns this into a Gramps Date
            placeref_list.append(ref)
        payload = {"_class": "Place", "name": {"value": name}, "place_type": place_type,
                   "placeref_list": placeref_list}
        if lat:
            payload["lat"] = lat
        if long:
            payload["long"] = long
        if code:
            payload["code"] = code
        if dry_run:
            return ok({"handle": f"DRYRUN:{name}", "dry_run": True, "created": False})
        resp = get_client().request("POST", "/places/", json=payload)
        handle = resp.json().get("handle") if resp.content else None
        return ok({"handle": handle, "dry_run": False, "created": True})


class GrampsUpdatePlaceInput(BaseModel):
    handle: str = Field(..., description="Handle of the existing place to enrich.")
    name: str = Field(..., description="Canonical modern name value.")
    place_type: str = Field(..., description="Gramps place type.")
    lat: str | None = Field(None, description="WGS84 latitude.")
    long: str | None = Field(None, description="WGS84 longitude.")
    code: str | None = Field(None, description="Place code.")
    placeref_list: list | None = Field(None, description="Parent placerefs [{ref, ...}].")
    alt_names: list | None = Field(None, description="Alt names [{value, ...}] to add if absent.")
    provenance: str | None = Field(None, description="Provenance string for a note (informational).")
    dry_run: bool = Field(False, description="If true, compute changes but do not write.")


class GrampsUpdatePlaceTool(BaseTool):
    """Enrich an existing place in place (name/type/GPS/placerefs/alt_names). No-op when conforming."""

    name: str = "gramps_update_place"
    description: str = (
        "Enriches one existing Gramps place: canonical name, type, WGS84 lat/long, parent "
        "placerefs, and adds alt_names if absent. No-op when already conforming. Writes "
        "directly unless dry_run is set or GENECREW_DRY_RUN is enabled."
    )
    args_schema: type[BaseModel] = GrampsUpdatePlaceInput

    @api_tool(provider="GrampsWeb", endpoint="UpdatePlace")
    def _run(self, handle, name, place_type, lat=None, long=None, code=None,
             placeref_list=None, alt_names=None, provenance=None, dry_run=False) -> str:
        dry_run = effective_dry_run(dry_run)
        place = get_client().get_object("places", handle)
        before = {"name": (place.get("name") or {}).get("value"),
                  "place_type": place.get("place_type"), "lat": place.get("lat"),
                  "long": place.get("long"), "placeref_list": place.get("placeref_list") or []}
        place["name"] = {**(place.get("name") or {}), "value": name}
        place["place_type"] = place_type
        if lat is not None:
            place["lat"] = lat
        if long is not None:
            place["long"] = long
        if code is not None:
            place["code"] = code
        if placeref_list is not None:
            place["placeref_list"] = placeref_list
        existing_alt = place.get("alt_names") or []
        existing_values = {a.get("value") for a in existing_alt}
        for a in (alt_names or []):
            if a.get("value") not in existing_values:
                existing_alt.append(a)
        place["alt_names"] = existing_alt
        after = {"name": name, "place_type": place_type, "lat": lat if lat is not None else place.get("lat"),
                 "long": long if long is not None else place.get("long"),
                 "placeref_list": placeref_list if placeref_list is not None else before["placeref_list"]}
        noop = before == after and set(existing_values) >= {a.get("value") for a in (alt_names or [])}
        change = {"handle": handle, "gramps_id": place.get("gramps_id"),
                  "dry_run": dry_run, "noop": noop}
        if not noop and not dry_run:
            get_client().request("PUT", f"/places/{handle}", json=place)
        return ok(change)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /Users/fjacquet/Projects/crewai_custom_tools && uv run python -m pytest tests/test_genealogy_place_write_tools.py -q`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add crewai_custom_tools/src/crewai_custom_tools/tools/genealogy/gramps/write_tools.py \
        crewai_custom_tools/tests/test_genealogy_place_write_tools.py
git commit -m "feat(genealogy): GrampsCreatePlaceTool + GrampsUpdatePlaceTool (gated dry-run, no-op)"
```

---

### Task 12: Orchestration d'écriture + fusions proposées (genecrew places_apply.py)

**Files:**

- Create: `genecrew/src/genecrew/places_apply.py`
- Test: `genecrew/tests/test_places_apply.py`

**Interfaces:**

- Consumes: `iter_places` (Task 8) ; `build_proposition` (Task 9) ; `GrampsCreatePlaceTool`, `GrampsUpdatePlaceTool` (Task 11) ; `effective_dry_run` ; `PlaceMergeProposition`.
- Produces: `run_places_apply(client, scope, output_dir, *, date, min_score=0.90, batch_size=25, limit=None, dry_run=False) -> Path` (writes `action="ecrire"`, proposes merges, leaves the rest) ; `render_apply_report(scope, date, applied, proposals, merges, errors, dry_run, base_url="http://localhost") -> str` (pur).
- Parent index: `dict[str, str]` path→handle, seeded from existing places, filled as parents are created; each unique canonical path is created once.

- [ ] **Step 1: Write the failing test**

```python
# genecrew/tests/test_places_apply.py
import json

import httpx
import pytest
from crewai_custom_tools.tools.genealogy.gramps.client import GrampsClient, GrampsConfig
from crewai_custom_tools.tools.genealogy.gramps import write_tools
from crewai_custom_tools.tools.genealogy.models.domain import (
    DatedChain, PlaceLevel, ResolvedPlace,
)
from genecrew import places_apply
from genecrew.places_apply import run_places_apply

CONFIG = GrampsConfig(api_url="http://g.test/api", username="u", password="p")
PLACES = [{"handle": "h1", "gramps_id": "P0001",
           "name": {"value": ", , Bourges, 18033, 18000, Cher, Centre-Val de Loire, France"},
           "place_type": "Unknown", "alt_names": [], "placeref_list": []}]


@pytest.fixture(autouse=True)
def _no_global_dry_run(monkeypatch):
    monkeypatch.setenv("GENECREW_DRY_RUN", "false")


def _authoritative(place, min_score):
    from crewai_custom_tools.tools.genealogy.models.domain import PlaceProposition
    rp = ResolvedPlace(name="Bourges", place_type="Municipality", lat="47.081", long="2.399",
                       code="18033",
                       chains=[DatedChain(levels=[
                           PlaceLevel(name="France", place_type="Country"),
                           PlaceLevel(name="Cher", place_type="Department", code="18")])],
                       score=1.0, source="geo.api.gouv.fr", query="/communes/18033")
    return PlaceProposition(type="lieu_resolu", gramps_id=place["gramps_id"], handle=place["handle"],
                            original=place["name"]["value"], country="France", resolution=rp,
                            action="ecrire", confiance="haute", priorite="haute", preuve="…")


def _client(records):
    def handler(request):
        if request.url.path == "/api/token/":
            return httpx.Response(200, json={"access_token": "t"})
        if request.method == "GET" and request.url.path == "/api/places/":
            page = int(request.url.params.get("page", "1"))
            return httpx.Response(200, json=PLACES if page == 1 else [])
        if request.method == "GET" and request.url.path.startswith("/api/places/"):
            return httpx.Response(200, json=PLACES[0])
        if request.method == "POST" and request.url.path == "/api/places/":
            records.append(("POST", json.loads(request.content)))
            return httpx.Response(201, json={"handle": "H_" + json.loads(request.content)["name"]["value"]})
        if request.method == "PUT":
            records.append(("PUT", json.loads(request.content)))
            return httpx.Response(200, json={})
        return httpx.Response(404)
    return GrampsClient(CONFIG, transport=httpx.MockTransport(handler))


def test_apply_writes_parents_once_and_enriches_leaf(tmp_path, monkeypatch, mocker):
    monkeypatch.setattr(places_apply, "build_proposition", _authoritative)
    records = []
    client = _client(records)
    mocker.patch.object(write_tools, "get_client", return_value=client)
    report = run_places_apply(client, "all", tmp_path, date="2026-07-19", dry_run=False)
    posts = [r for m, r in records if m == "POST"]
    puts = [r for m, r in records if m == "PUT"]
    assert {p["name"]["value"] for p in posts} == {"France", "Cher"}   # 2 parents créés
    assert any(p.get("place_type") == "Municipality" for p in puts)    # feuille enrichie
    assert "à écrire" in report.read_text(encoding="utf-8").lower() or "écrit" in report.read_text(encoding="utf-8").lower()


def test_apply_dry_run_writes_nothing(tmp_path, monkeypatch, mocker):
    monkeypatch.setattr(places_apply, "build_proposition", _authoritative)
    records = []
    client = _client(records)
    mocker.patch.object(write_tools, "get_client", return_value=client)
    run_places_apply(client, "all", tmp_path, date="2026-07-19", dry_run=True)
    assert not records                                                 # aucun POST/PUT
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/fjacquet/Projects/genecrew && uv run python -m pytest genecrew/tests/test_places_apply.py -q`
Expected: FAIL (`ModuleNotFoundError` on `genecrew.places_apply`).

- [ ] **Step 3: Write minimal implementation**

```python
# genecrew/src/genecrew/places_apply.py
"""Write-side places standardization: enrich leaves + build parent hierarchy (idempotent).

Writes only proposals with action=="ecrire" (authoritative or fuzzy ≥ min_score). Leaf
merges are proposed, never executed. Gated by dry_run + GENECREW_DRY_RUN.
"""

from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path

from crewai_custom_tools.tools.genealogy.gramps.client import GrampsClient
from crewai_custom_tools.tools.genealogy.gramps.write_tools import (
    GrampsCreatePlaceTool, GrampsUpdatePlaceTool, effective_dry_run,
)
from crewai_custom_tools.tools.genealogy.models.domain import PlaceMergeProposition

from genecrew.batching import iter_places
from genecrew.places import build_proposition


def _link(gramps_id: str, base_url: str) -> str:
    return f"[{gramps_id}]({base_url}/place/{gramps_id})"


def _ensure_parents(chain, index, creator, dry_run) -> str | None:
    """Create/reuse each parent in `chain` (top→down); return the immediate parent handle."""
    parent = None
    path = ""
    for level in chain.levels:
        path = f"{path}>{level.name}" if path else level.name
        if path not in index:
            payload = json.loads(creator._run(
                name=level.name, place_type=level.place_type, parent_handle=parent,
                date_qualifier=chain.date_qualifier, code=level.code, dry_run=dry_run))
            index[path] = payload["data"]["handle"]
        parent = index[path]
    return parent


def render_apply_report(scope, date, applied, proposals, merges, errors, dry_run,
                        base_url="http://localhost") -> str:
    mode = "simulation (dry-run, aucune écriture)" if dry_run else "écritures appliquées"
    lines = [f"# Application des lieux — {scope} — {date}", "",
             f"Mode : {mode}.", "",
             f"- Lieux écrits : {len(applied)}",
             f"- Propositions (non écrites) : {len(proposals)}",
             f"- Fusions proposées (jamais auto) : {len(merges)}",
             f"- Erreurs : {len(errors)}", "",
             "## Lieux écrits", ""]
    if applied:
        lines += ["| Lieu | Nom | Type | GPS |", "|---|---|---|---|"]
        for gid, name, ptype, lat, lon in applied:
            lines.append(f"| {_link(gid, base_url)} | {name} | {ptype} | {lat},{lon} |")
    else:
        lines.append("Aucune écriture.")
    lines += ["", "## Fusions proposées", ""]
    if merges:
        lines += ["| Garder | Fusionner | Canonique | Raison |", "|---|---|---|---|"]
        for m in merges:
            lines.append(f"| {_link(m.gramps_id_keep, base_url)} | {_link(m.gramps_id_merge, base_url)} "
                         f"| {m.canonical} | {m.reason} |")
    else:
        lines.append("Aucune.")
    lines += ["", "## Erreurs", ""]
    lines += (["| Lieu | Erreur |", "|---|---|"] + [f"| {_link(g, base_url)} | {e} |" for g, e in errors]
              if errors else ["Aucune erreur."])
    lines.append("")
    return "\n".join(lines)


def run_places_apply(client: GrampsClient, scope: str, output_dir, *, date: str,
                     min_score: float = 0.90, batch_size: int = 25,
                     limit: int | None = None, dry_run: bool = False) -> Path:
    """Enrich leaves + build hierarchy for action=='ecrire'; propose leaf merges. Idempotent."""
    output_dir = Path(output_dir)
    creator = GrampsCreatePlaceTool()
    updater = GrampsUpdatePlaceTool()
    index: dict[str, str] = {}
    applied: list = []
    proposals: list = []
    errors: list = []
    by_canonical: dict[str, list[tuple[str, str]]] = defaultdict(list)

    for batch in iter_places(client, scope, batch_size, limit):
        for place in batch:
            prop = build_proposition(place, min_score)
            if prop.action != "ecrire":
                proposals.append(prop)
                continue
            rp = prop.resolution
            canonical = ">".join([lvl.name for c in rp.chains for lvl in c.levels] + [rp.name])
            by_canonical[canonical].append((prop.gramps_id, prop.handle))
            try:
                placeref_list = []
                for chain in rp.chains:
                    parent = _ensure_parents(chain, index, creator, dry_run)
                    ref = {"ref": parent}
                    if chain.date_qualifier:
                        ref["_date_qualifier"] = chain.date_qualifier
                    placeref_list.append(ref)
                json.loads(updater._run(
                    handle=prop.handle, name=rp.name, place_type=rp.place_type,
                    lat=rp.lat, long=rp.long, code=rp.code, placeref_list=placeref_list,
                    alt_names=[a.model_dump() for a in rp.alt_names],
                    provenance=prop.preuve, dry_run=dry_run))
                applied.append((prop.gramps_id, rp.name, rp.place_type, rp.lat, rp.long))
            except Exception as exc:  # noqa: BLE001
                errors.append((prop.gramps_id, str(exc)))

    merges = [PlaceMergeProposition(
        gramps_id_keep=ids[0][0], handle_keep=ids[0][1],
        gramps_id_merge=g, handle_merge=h, canonical=canon,
        reason="même lieu canonique résolu")
        for canon, ids in by_canonical.items() if len(ids) > 1 for g, h in ids[1:]]

    out = output_dir / "lieux"
    out.mkdir(parents=True, exist_ok=True)
    scope_slug = scope.replace(":", "_")
    path = out / f"{date}_lieux_appliques_{scope_slug}.md"
    path.write_text(render_apply_report(scope, date, applied, proposals, merges, errors,
                                        effective_dry_run(dry_run)), encoding="utf-8")
    return path
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /Users/fjacquet/Projects/genecrew && uv run python -m pytest genecrew/tests/test_places_apply.py -q`
Expected: PASS (2 tests).

- [ ] **Step 5: Commit**

```bash
git add genecrew/src/genecrew/places_apply.py genecrew/tests/test_places_apply.py
git commit -m "feat(places): run_places_apply — idempotent hierarchy write + proposed merges"
```

---

### Task 13: CLI `lieux-apply` (genecrew main.py)

**Files:**

- Modify: `genecrew/src/genecrew/main.py` (add `lieux_apply_cmd` + subparser + dispatch)
- Test: `genecrew/tests/test_cli_lieux_apply.py`

**Interfaces:**

- Consumes: `run_places_apply` (Task 12).
- Produces: CLI subcommand `genecrew lieux-apply --scope --limit --batch-size --min-score --dry-run --date`.

- [ ] **Step 1: Write the failing test**

```python
# genecrew/tests/test_cli_lieux_apply.py
import subprocess


def test_lieux_apply_help_lists_flags():
    out = subprocess.run(["uv", "run", "genecrew", "lieux-apply", "--help"],
                         capture_output=True, text=True, cwd="/Users/fjacquet/Projects/genecrew")
    assert out.returncode == 0
    assert "--min-score" in out.stdout and "--dry-run" in out.stdout
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/fjacquet/Projects/genecrew && uv run python -m pytest genecrew/tests/test_cli_lieux_apply.py -q`
Expected: FAIL (subcommand unknown → non-zero return).

- [ ] **Step 3: Write minimal implementation**

Add `lieux_apply_cmd` (after `lieux_cmd`):

```python
def lieux_apply_cmd(args) -> None:
    """Apply place standardization (write hierarchy + GPS); print the report path."""
    from pathlib import Path

    from crewai_custom_tools.tools.genealogy.gramps.client import GrampsClient, GrampsConfig

    from genecrew.places_apply import run_places_apply

    client = GrampsClient(GrampsConfig.from_env())
    output_dir = Path(os.environ.get("GENECREW_OUTPUT_DIR", "output"))
    date = args.date or __import__("datetime").date.today().isoformat()
    report = run_places_apply(client, args.scope, output_dir, date=date,
                              min_score=args.min_score, batch_size=args.batch_size,
                              limit=args.limit, dry_run=args.dry_run)
    print(f"Rapport : {report}")
```

Add the subparser (after the `lieux` block):

```python
    la_p = sub.add_parser("lieux-apply",
                          help="Applique (écrit) la standardisation des lieux au-dessus du score")
    la_p.add_argument("--scope", default="all", help="all | person:ID")
    la_p.add_argument("--min-score", type=float, default=0.90,
                      help="seuil de score pour écrire (défaut 0.90)")
    la_p.add_argument("--limit", type=int, default=None, help="limiter à N lieux")
    la_p.add_argument("--batch-size", type=int,
                      default=int(os.environ.get("GENECREW_BATCH_SIZE", "25")))
    la_p.add_argument("--dry-run", action="store_true", help="simuler sans écrire")
    la_p.add_argument("--date", default=None, help="date du rapport (défaut : aujourd'hui)")
```

Add dispatch (in `main`, after the `lieux` branch):

```python
    elif args.command == "lieux-apply":
        lieux_apply_cmd(args)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /Users/fjacquet/Projects/genecrew && uv run python -m pytest genecrew/tests/test_cli_lieux_apply.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add genecrew/src/genecrew/main.py genecrew/tests/test_cli_lieux_apply.py
git commit -m "feat(places): genecrew lieux-apply CLI subcommand (write)"
```

---

### Task 14: Capacité de transitions temporelles (geo/transitions.py + dataset)

**Files:**

- Create: `crewai_custom_tools/src/crewai_custom_tools/tools/genealogy/geo/transitions.py`
- Create: `crewai_custom_tools/src/crewai_custom_tools/tools/genealogy/data/transitions.csv`
- Modify: `crewai_custom_tools/src/crewai_custom_tools/tools/genealogy/geo/registry.py` (wire `apply_transition` into `resolve_place`)
- Test: `crewai_custom_tools/tests/test_genealogy_geo_transitions.py`

**Interfaces:**

- Consumes: `ParsedPlace`, `ResolvedPlace`, `DatedChain`, `DatedName`, `PlaceLevel`.
- Produces: `Transition(BaseModel)` ; `load_transitions() -> list[Transition]` (empty-safe) ; `apply_transition(resolved, parsed, transitions) -> ResolvedPlace | None` (pure).
- **Générique** : aucune connaissance codée d'un pays. Le comportement daté vient **du dataset** ; dataset vide → chaîne unique non datée (identique à P1–P4).

- [ ] **Step 1: Write the failing test**

```python
# tests/test_genealogy_geo_transitions.py
from crewai_custom_tools.tools.genealogy.geo.transitions import (
    Transition, apply_transition,
)
from crewai_custom_tools.tools.genealogy.models.domain import (
    DatedChain, ParsedPlace, PlaceLevel, ResolvedPlace,
)


def _base(country):
    return ResolvedPlace(name="Alger", place_type="Municipality", score=0.9, source="Nominatim/OSM",
                         query="q",
                         chains=[DatedChain(levels=[PlaceLevel(name=country, place_type="Country")])])


def test_empty_transitions_leave_single_undated_chain():
    parsed = ParsedPlace(raw="…", commune="Alger", country="Algérie")
    out = apply_transition(_base("Algérie"), parsed, [])
    assert len(out.chains) == 1 and out.chains[0].date_qualifier is None


def test_one_transition_row_yields_two_dated_chains_and_dated_altname():
    t = Transition(modern_country="Algérie", historical_country="Algérie française",
                   historical_parent="France", date="1962-07-05")
    parsed = ParsedPlace(raw=", , Alger, , , Alger, , France", commune="Alger",
                         departement="Alger", country="Algérie")
    out = apply_transition(_base("Algérie"), parsed, [t])
    quals = sorted(c.date_qualifier for c in out.chains)
    assert quals == ["après 1962-07-05", "avant 1962-07-05"]
    hist = next(c for c in out.chains if c.date_qualifier.startswith("avant"))
    names = [lvl.name for lvl in hist.levels]
    assert names[0] == "France" and "Algérie française" in names and "Alger" in names
    assert out.alt_names[0].date_qualifier == "avant 1962-07-05"


def test_transition_not_matching_country_is_noop():
    t = Transition(modern_country="Algérie", historical_country="Algérie française",
                   historical_parent="France", date="1962-07-05")
    out = apply_transition(_base("Italie"), ParsedPlace(raw="…", commune="Roma", country="Italie"), [t])
    assert len(out.chains) == 1 and out.chains[0].date_qualifier is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/fjacquet/Projects/crewai_custom_tools && uv run python -m pytest tests/test_genealogy_geo_transitions.py -q`
Expected: FAIL (`ModuleNotFoundError` on `geo.transitions`).

- [ ] **Step 3: Write minimal implementation**

Create `data/transitions.csv` (header + **une ligne de DONNÉES** pour l'arbre courant — le code n'y fait aucune référence ; ajouter/retirer une ligne suffit) :

```csv
modern_country,historical_country,historical_parent,date
Algérie,Algérie française,France,1962-07-05
```

Create `geo/transitions.py` :

```python
"""Data-driven temporal transitions (sovereignty/name changes). Dataset-agnostic.

Gramps natively models dated names and dated placerefs. This module emits two
dated parent chains (before/after) + a dated alt_name WHEN a transition row
matches the resolved country. Empty dataset → single undated chain (generic).
"""

from __future__ import annotations

import csv
from pathlib import Path

from pydantic import BaseModel

from crewai_custom_tools.tools.genealogy.models.domain import (
    DatedChain, DatedName, ParsedPlace, PlaceLevel, ResolvedPlace,
)

_DATA = Path(__file__).resolve().parent.parent / "data" / "transitions.csv"
_COLS = ("modern_country", "historical_country", "historical_parent", "date")


class Transition(BaseModel):
    """One known transition: the modern country splits from a historical parent at `date`."""

    modern_country: str
    historical_country: str
    historical_parent: str
    date: str                      # ISO YYYY-MM-DD


def load_transitions() -> list[Transition]:
    """Load transitions from the embedded CSV (empty/missing → [])."""
    if not _DATA.exists():
        return []
    with _DATA.open(encoding="utf-8") as f:
        return [Transition(**{c: row[c] for c in _COLS})
                for row in csv.DictReader(f) if row.get("modern_country")]


def apply_transition(resolved: ResolvedPlace | None, parsed: ParsedPlace,
                     transitions: list[Transition]) -> ResolvedPlace | None:
    """If a transition matches `parsed.country`, split into two dated chains + dated alt_name."""
    if resolved is None:
        return resolved
    t = next((t for t in transitions if t.modern_country == parsed.country), None)
    if t is None:
        return resolved
    modern = [DatedChain(levels=c.levels, date_qualifier=f"après {t.date}")
              for c in resolved.chains] or \
             [DatedChain(levels=[PlaceLevel(name=parsed.country, place_type="Country")],
                         date_qualifier=f"après {t.date}")]
    hist_levels = [PlaceLevel(name=t.historical_parent, place_type="Country"),
                   PlaceLevel(name=t.historical_country, place_type="Region")]
    if parsed.departement:
        hist_levels.append(PlaceLevel(name=parsed.departement, place_type="Department"))
    historical = DatedChain(levels=hist_levels, date_qualifier=f"avant {t.date}")
    return resolved.model_copy(update={
        "chains": modern + [historical],
        "alt_names": [DatedName(value=parsed.raw, date_qualifier=f"avant {t.date}")],
    })
```

Modify `geo/registry.py` — import and apply transitions inside `resolve_place`:

```python
# add near the other imports:
from crewai_custom_tools.tools.genealogy.geo.transitions import apply_transition, load_transitions

# replace the body of resolve_place's return statements with a single post-step:
def resolve_place(parsed: ParsedPlace) -> ResolvedPlace | None:
    """Route to the country resolver; fall back to worldwide; apply temporal transitions."""
    country_resolver = _BY_COUNTRY.get(parsed.country)
    resolved = country_resolver(parsed) if country_resolver is not None else None
    if resolved is None:
        resolved = resolve_world(parsed)
    return apply_transition(resolved, parsed, load_transitions())
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /Users/fjacquet/Projects/crewai_custom_tools && uv run python -m pytest tests/test_genealogy_geo_transitions.py tests/test_genealogy_geo_registry.py -q`
Expected: PASS (transitions 3 tests + registry 4 tests still green — dataset match on "Algérie" only; registry tests use "France"/"X").

- [ ] **Step 5: Commit**

```bash
git add crewai_custom_tools/src/crewai_custom_tools/tools/genealogy/geo/transitions.py \
        crewai_custom_tools/src/crewai_custom_tools/tools/genealogy/data/transitions.csv \
        crewai_custom_tools/src/crewai_custom_tools/tools/genealogy/geo/registry.py \
        crewai_custom_tools/tests/test_genealogy_geo_transitions.py
git commit -m "feat(genealogy): data-driven temporal transitions (dated chains)"
```

---

### Task 15: Dates Gramps réelles sur les placerefs (write tools)

**Files:**

- Modify: `crewai_custom_tools/src/crewai_custom_tools/tools/genealogy/gramps/write_tools.py`
- Test: `crewai_custom_tools/tests/test_genealogy_place_dates.py`

**Interfaces:**

- Produces: `date_qualifier_to_gramps_date(qualifier: str | None) -> dict | None` (pure) ; both place write tools normalize a placeref `_date_qualifier` string into a Gramps `date` object.
- Gramps Date : `{"_class": "Date", "modifier": 1|2, "dateval": [d, m, y, False]}` (modifier 1=before, 2=after).

- [ ] **Step 1: Write the failing test**

```python
# tests/test_genealogy_place_dates.py
import json

import httpx
import pytest

from crewai_custom_tools.tools.genealogy.gramps.client import GrampsClient, GrampsConfig
from crewai_custom_tools.tools.genealogy.gramps import write_tools
from crewai_custom_tools.tools.genealogy.gramps.write_tools import (
    GrampsCreatePlaceTool, date_qualifier_to_gramps_date,
)

CONFIG = GrampsConfig(api_url="http://g.test/api", username="u", password="p")


@pytest.fixture(autouse=True)
def _no_global_dry_run(monkeypatch):
    monkeypatch.setenv("GENECREW_DRY_RUN", "false")


def test_date_qualifier_before_after_none():
    assert date_qualifier_to_gramps_date("avant 1962-07-05") == {
        "_class": "Date", "modifier": 1, "dateval": [5, 7, 1962, False]}
    assert date_qualifier_to_gramps_date("après 1962-07-05")["modifier"] == 2
    assert date_qualifier_to_gramps_date(None) is None
    assert date_qualifier_to_gramps_date("n'importe quoi") is None


def test_create_place_parent_placeref_carries_gramps_date(mocker):
    posts = []

    def handler(request):
        if request.url.path == "/api/token/":
            return httpx.Response(200, json={"access_token": "t"})
        if request.method == "POST" and request.url.path == "/api/places/":
            posts.append(json.loads(request.content))
            return httpx.Response(201, json={"handle": "H"})
        return httpx.Response(404)

    mocker.patch.object(write_tools, "get_client",
                        return_value=GrampsClient(CONFIG, transport=httpx.MockTransport(handler)))
    GrampsCreatePlaceTool()._run(name="Alger", place_type="Municipality",
                                 parent_handle="H_DZ", date_qualifier="après 1962-07-05")
    ref = posts[0]["placeref_list"][0]
    assert ref["ref"] == "H_DZ"
    assert ref["date"] == {"_class": "Date", "modifier": 2, "dateval": [5, 7, 1962, False]}
    assert "_date_qualifier" not in ref                # remplacé par une vraie Date
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/fjacquet/Projects/crewai_custom_tools && uv run python -m pytest tests/test_genealogy_place_dates.py -q`
Expected: FAIL (`ImportError` on `date_qualifier_to_gramps_date`).

- [ ] **Step 3: Write minimal implementation**

Add the pure helper near the top of `write_tools.py` (after `effective_dry_run`):

```python
_DATE_MODIFIER = {"avant": 1, "après": 2, "apres": 2}


def date_qualifier_to_gramps_date(qualifier: str | None) -> dict | None:
    """Convert 'avant/après YYYY-MM-DD' into a Gramps Date object (None if unrecognized)."""
    if not qualifier:
        return None
    word, _, iso = qualifier.partition(" ")
    modifier = _DATE_MODIFIER.get(word.strip().lower())
    if modifier is None:
        return None
    try:
        year, month, day = (int(x) for x in iso.strip().split("-"))
    except ValueError:
        return None
    return {"_class": "Date", "modifier": modifier, "dateval": [day, month, year, False]}
```

In `GrampsCreatePlaceTool._run`, replace the placeref build:

```python
        placeref_list = []
        if parent_handle:
            ref = {"ref": parent_handle}
            gdate = date_qualifier_to_gramps_date(date_qualifier)
            if gdate is not None:
                ref["date"] = gdate
            placeref_list.append(ref)
```

In `GrampsUpdatePlaceTool._run`, normalize any incoming `_date_qualifier` on placerefs before assigning (just before `place["placeref_list"] = placeref_list`):

```python
        if placeref_list is not None:
            normalized = []
            for ref in placeref_list:
                ref = dict(ref)
                gdate = date_qualifier_to_gramps_date(ref.pop("_date_qualifier", None))
                if gdate is not None:
                    ref["date"] = gdate
                normalized.append(ref)
            place["placeref_list"] = normalized
```

(Remove the earlier bare `place["placeref_list"] = placeref_list` line — this replaces it.)

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /Users/fjacquet/Projects/crewai_custom_tools && uv run python -m pytest tests/test_genealogy_place_dates.py tests/test_genealogy_place_write_tools.py -q`
Expected: PASS (dates 2 tests + place-write 3 tests still green — undated placerefs unaffected).

- [ ] **Step 5: Commit**

```bash
git add crewai_custom_tools/src/crewai_custom_tools/tools/genealogy/gramps/write_tools.py \
        crewai_custom_tools/tests/test_genealogy_place_dates.py
git commit -m "feat(genealogy): real Gramps Date on dated placerefs"
```

---

### Task 16: Outil de fusion de lieux (GrampsMergePlacesTool)

**Files:**

- Modify: `crewai_custom_tools/src/crewai_custom_tools/tools/genealogy/gramps/write_tools.py` (append)
- Test: `crewai_custom_tools/tests/test_genealogy_place_merge_tool.py`

**Interfaces:**

- Produces: `GrampsMergePlacesTool` (`_run(keep_handle, merge_handle, dry_run=False) -> str`; `POST /places/{keep}/merge/{merge}`; gated dry-run; no-op nothing but returns the pair).

- [ ] **Step 1: Write the failing test**

```python
# tests/test_genealogy_place_merge_tool.py
import json

import httpx
import pytest

from crewai_custom_tools.tools.genealogy.gramps.client import GrampsClient, GrampsConfig
from crewai_custom_tools.tools.genealogy.gramps import write_tools
from crewai_custom_tools.tools.genealogy.gramps.write_tools import GrampsMergePlacesTool

CONFIG = GrampsConfig(api_url="http://g.test/api", username="u", password="p")


@pytest.fixture(autouse=True)
def _no_global_dry_run(monkeypatch):
    monkeypatch.setenv("GENECREW_DRY_RUN", "false")


def _client(calls):
    def handler(request):
        if request.url.path == "/api/token/":
            return httpx.Response(200, json={"access_token": "t"})
        if request.method == "POST" and "/merge/" in request.url.path:
            calls.append(request.url.path)
            return httpx.Response(200, json={})
        return httpx.Response(404)
    return GrampsClient(CONFIG, transport=httpx.MockTransport(handler))


def test_merge_dry_run_calls_nothing(mocker):
    calls = []
    mocker.patch.object(write_tools, "get_client", return_value=_client(calls))
    data = json.loads(GrampsMergePlacesTool()._run(keep_handle="A", merge_handle="B", dry_run=True))
    assert data["success"] is True and data["data"]["dry_run"] is True
    assert calls == []


def test_merge_posts_to_right_path(mocker):
    calls = []
    mocker.patch.object(write_tools, "get_client", return_value=_client(calls))
    GrampsMergePlacesTool()._run(keep_handle="A", merge_handle="B")
    assert calls == ["/api/places/A/merge/B"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/fjacquet/Projects/crewai_custom_tools && uv run python -m pytest tests/test_genealogy_place_merge_tool.py -q`
Expected: FAIL (`ImportError` on `GrampsMergePlacesTool`).

- [ ] **Step 3: Write minimal implementation (append to write_tools.py)**

```python
class GrampsMergePlacesInput(BaseModel):
    keep_handle: str = Field(..., description="Handle of the surviving place (phoenix).")
    merge_handle: str = Field(..., description="Handle of the place absorbed then deleted (titanic).")
    dry_run: bool = Field(False, description="If true, simulate without merging.")


class GrampsMergePlacesTool(BaseTool):
    """Merge two places (moves backlinks). Human-triggered only; never called automatically."""

    name: str = "gramps_merge_places"
    description: str = (
        "Merges the 'merge' place into the 'keep' place in Gramps (migrates event backlinks, "
        "then removes the duplicate). Writes unless dry_run is set or GENECREW_DRY_RUN is enabled."
    )
    args_schema: type[BaseModel] = GrampsMergePlacesInput

    @api_tool(provider="GrampsWeb", endpoint="MergePlaces")
    def _run(self, keep_handle: str, merge_handle: str, dry_run: bool = False) -> str:
        dry_run = effective_dry_run(dry_run)
        change = {"keep": keep_handle, "merge": merge_handle, "dry_run": dry_run}
        if not dry_run:
            get_client().request("POST", f"/places/{keep_handle}/merge/{merge_handle}")
        return ok(change)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /Users/fjacquet/Projects/crewai_custom_tools && uv run python -m pytest tests/test_genealogy_place_merge_tool.py -q`
Expected: PASS (2 tests).

- [ ] **Step 5: Commit**

```bash
git add crewai_custom_tools/src/crewai_custom_tools/tools/genealogy/gramps/write_tools.py \
        crewai_custom_tools/tests/test_genealogy_place_merge_tool.py
git commit -m "feat(genealogy): GrampsMergePlacesTool (gated, human-triggered)"
```

---

### Task 17: `run_places_apply` émet un YAML de fusions

**Files:**

- Modify: `genecrew/src/genecrew/places_apply.py` (write a `*_fusions_*.yaml` alongside the report)
- Test: `genecrew/tests/test_places_apply_fusions.py`

**Interfaces:**

- Produces: `run_places_apply` additionally writes `output_dir/lieux/{date}_fusions_lieux_{scope}.yaml` containing the `PlaceMergeProposition` list (may be empty). Return value unchanged (report `Path`).

- [ ] **Step 1: Write the failing test**

```python
# genecrew/tests/test_places_apply_fusions.py
import json

import httpx
import pytest
import yaml
from crewai_custom_tools.tools.genealogy.gramps.client import GrampsClient, GrampsConfig
from crewai_custom_tools.tools.genealogy.gramps import write_tools
from crewai_custom_tools.tools.genealogy.models.domain import (
    DatedChain, PlaceLevel, PlaceProposition, ResolvedPlace,
)
from genecrew import places_apply
from genecrew.places_apply import run_places_apply

CONFIG = GrampsConfig(api_url="http://g.test/api", username="u", password="p")
# deux feuilles DIFFÉRENTES qui résolvent vers le MÊME lieu canonique → une fusion proposée
PLACES = [{"handle": "h1", "gramps_id": "P0001", "name": {"value": "A"}, "alt_names": [], "placeref_list": []},
          {"handle": "h2", "gramps_id": "P0002", "name": {"value": "B"}, "alt_names": [], "placeref_list": []}]


@pytest.fixture(autouse=True)
def _no_global_dry_run(monkeypatch):
    monkeypatch.setenv("GENECREW_DRY_RUN", "false")


def _same_canonical(place, min_score):
    rp = ResolvedPlace(name="Bourges", place_type="Municipality", lat="47.081", long="2.399",
                       chains=[DatedChain(levels=[PlaceLevel(name="France", place_type="Country")])],
                       score=1.0, source="geo.api.gouv.fr", query="q")
    return PlaceProposition(type="lieu_resolu", gramps_id=place["gramps_id"], handle=place["handle"],
                            original=place["name"]["value"], country="France", resolution=rp,
                            action="ecrire", confiance="haute", priorite="haute", preuve="…")


def _client():
    def handler(request):
        if request.url.path == "/api/token/":
            return httpx.Response(200, json={"access_token": "t"})
        if request.method == "GET" and request.url.path == "/api/places/":
            page = int(request.url.params.get("page", "1"))
            return httpx.Response(200, json=PLACES if page == 1 else [])
        if request.method == "GET" and request.url.path.startswith("/api/places/"):
            return httpx.Response(200, json=PLACES[0])
        if request.method == "POST" and request.url.path == "/api/places/":
            return httpx.Response(201, json={"handle": "H_" + json.loads(request.content)["name"]["value"]})
        if request.method == "PUT":
            return httpx.Response(200, json={})
        return httpx.Response(404)
    return GrampsClient(CONFIG, transport=httpx.MockTransport(handler))


def test_apply_emits_fusions_yaml(tmp_path, monkeypatch, mocker):
    monkeypatch.setattr(places_apply, "build_proposition", _same_canonical)
    mocker.patch.object(write_tools, "get_client", return_value=_client())
    run_places_apply(_client(), "all", tmp_path, date="2026-07-19", dry_run=False)
    fusions = tmp_path / "lieux" / "2026-07-19_fusions_lieux_all.yaml"
    data = yaml.safe_load(fusions.read_text(encoding="utf-8"))
    assert len(data) == 1                                        # une fusion proposée
    assert data[0]["gramps_id_keep"] == "P0001" and data[0]["gramps_id_merge"] == "P0002"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/fjacquet/Projects/genecrew && uv run python -m pytest genecrew/tests/test_places_apply_fusions.py -q`
Expected: FAIL (`FileNotFoundError` — the fusions YAML is not written yet).

- [ ] **Step 3: Write minimal implementation**

Add `import yaml` at the top of `places_apply.py`, then before `return path` in `run_places_apply` write the merges YAML:

```python
    merges_path = out / f"{date}_fusions_lieux_{scope_slug}.yaml"
    merges_path.write_text(
        yaml.safe_dump([m.model_dump() for m in merges], allow_unicode=True, sort_keys=False),
        encoding="utf-8")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /Users/fjacquet/Projects/genecrew && uv run python -m pytest genecrew/tests/test_places_apply_fusions.py genecrew/tests/test_places_apply.py -q`
Expected: PASS (fusions 1 test + apply 2 tests still green).

- [ ] **Step 5: Commit**

```bash
git add genecrew/src/genecrew/places_apply.py genecrew/tests/test_places_apply_fusions.py
git commit -m "feat(places): emit reviewed-merge proposals as YAML"
```

---

### Task 18: `run_places_merge` + CLI `lieux-merge` (fusions sous revue)

**Files:**

- Create: `genecrew/src/genecrew/places_merge.py`
- Modify: `genecrew/src/genecrew/main.py` (add `lieux_merge_cmd` + subparser + dispatch)
- Test: `genecrew/tests/test_places_merge.py`

**Interfaces:**

- Consumes: `GrampsMergePlacesTool` (Task 16) ; the fusions YAML (Task 17).
- Produces: `run_places_merge(client, merges_yaml, output_dir, *, date, dry_run=False) -> Path` (execute the merges listed in a **human-reviewed** YAML) ; CLI `genecrew lieux-merge --merges <path.yaml> --dry-run --date`.
- **Never auto** : merges run only from an explicit YAML the human passes.

- [ ] **Step 1: Write the failing test**

```python
# genecrew/tests/test_places_merge.py
import json

import httpx
import pytest
import yaml
from crewai_custom_tools.tools.genealogy.gramps.client import GrampsClient, GrampsConfig
from crewai_custom_tools.tools.genealogy.gramps import write_tools
from genecrew.places_merge import run_places_merge

CONFIG = GrampsConfig(api_url="http://g.test/api", username="u", password="p")


@pytest.fixture(autouse=True)
def _no_global_dry_run(monkeypatch):
    monkeypatch.setenv("GENECREW_DRY_RUN", "false")


def _client(calls):
    def handler(request):
        if request.url.path == "/api/token/":
            return httpx.Response(200, json={"access_token": "t"})
        if request.method == "POST" and "/merge/" in request.url.path:
            calls.append(request.url.path)
            return httpx.Response(200, json={})
        return httpx.Response(404)
    return GrampsClient(CONFIG, transport=httpx.MockTransport(handler))


def _write_fusions(tmp_path):
    p = tmp_path / "fusions.yaml"
    p.write_text(yaml.safe_dump([{
        "gramps_id_keep": "P0001", "handle_keep": "h1",
        "gramps_id_merge": "P0002", "handle_merge": "h2",
        "canonical": "Bourges", "reason": "même lieu"}], allow_unicode=True), encoding="utf-8")
    return p


def test_merge_executes_from_reviewed_yaml(tmp_path, mocker):
    calls = []
    mocker.patch.object(write_tools, "get_client", return_value=_client(calls))
    report = run_places_merge(_client(calls), _write_fusions(tmp_path), tmp_path,
                              date="2026-07-19", dry_run=False)
    assert calls == ["/api/places/h1/merge/h2"]
    assert "Bourges" in report.read_text(encoding="utf-8")


def test_merge_dry_run_executes_nothing(tmp_path, mocker):
    calls = []
    mocker.patch.object(write_tools, "get_client", return_value=_client(calls))
    run_places_merge(_client(calls), _write_fusions(tmp_path), tmp_path, date="2026-07-19", dry_run=True)
    assert calls == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/fjacquet/Projects/genecrew && uv run python -m pytest genecrew/tests/test_places_merge.py -q`
Expected: FAIL (`ModuleNotFoundError` on `genecrew.places_merge`).

- [ ] **Step 3: Write minimal implementation**

Create `genecrew/src/genecrew/places_merge.py` :

```python
"""Execute human-reviewed place merges (never automatic). Reads a fusions YAML."""

from __future__ import annotations

import json
from pathlib import Path

import yaml

from crewai_custom_tools.tools.genealogy.gramps.client import GrampsClient
from crewai_custom_tools.tools.genealogy.gramps.write_tools import (
    GrampsMergePlacesTool, effective_dry_run,
)


def _link(gramps_id: str, base_url: str) -> str:
    return f"[{gramps_id}]({base_url}/place/{gramps_id})"


def render_merge_report(date, done, errors, dry_run, base_url="http://localhost") -> str:
    mode = "simulation (dry-run, aucune fusion)" if dry_run else "fusions appliquées"
    lines = [f"# Fusions de lieux — {date}", "", f"Mode : {mode}.", "",
             f"- Fusions : {len(done)}", f"- Erreurs : {len(errors)}", "", "## Fusions", ""]
    if done:
        lines += ["| Gardé | Fusionné | Canonique |", "|---|---|---|"]
        for keep, merge, canon in done:
            lines.append(f"| {_link(keep, base_url)} | {_link(merge, base_url)} | {canon} |")
    else:
        lines.append("Aucune.")
    lines += ["", "## Erreurs", ""]
    lines += (["| Fusionné | Erreur |", "|---|---|"] + [f"| {_link(m, base_url)} | {e} |" for m, e in errors]
              if errors else ["Aucune erreur."])
    lines.append("")
    return "\n".join(lines)


def run_places_merge(client: GrampsClient, merges_yaml, output_dir, *, date: str,
                     dry_run: bool = False) -> Path:
    """Execute the merges listed in a reviewed YAML. Gated by dry_run + GENECREW_DRY_RUN."""
    output_dir = Path(output_dir)
    merges = yaml.safe_load(Path(merges_yaml).read_text(encoding="utf-8")) or []
    tool = GrampsMergePlacesTool()
    done: list = []
    errors: list = []
    for m in merges:
        payload = json.loads(tool._run(keep_handle=m["handle_keep"],
                                       merge_handle=m["handle_merge"], dry_run=dry_run))
        if payload["success"]:
            done.append((m["gramps_id_keep"], m["gramps_id_merge"], m.get("canonical", "")))
        else:
            errors.append((m["gramps_id_merge"], payload["error"]))
    out = output_dir / "lieux"
    out.mkdir(parents=True, exist_ok=True)
    path = out / f"{date}_fusions_appliquees.md"
    path.write_text(render_merge_report(date, done, errors, effective_dry_run(dry_run)),
                    encoding="utf-8")
    return path
```

Add `lieux_merge_cmd` to `main.py` (after `lieux_apply_cmd`):

```python
def lieux_merge_cmd(args) -> None:
    """Execute human-reviewed place merges from a fusions YAML; print the report path."""
    from pathlib import Path

    from crewai_custom_tools.tools.genealogy.gramps.client import GrampsClient, GrampsConfig

    from genecrew.places_merge import run_places_merge

    client = GrampsClient(GrampsConfig.from_env())
    output_dir = Path(os.environ.get("GENECREW_OUTPUT_DIR", "output"))
    date = args.date or __import__("datetime").date.today().isoformat()
    report = run_places_merge(client, args.merges, output_dir, date=date, dry_run=args.dry_run)
    print(f"Rapport : {report}")
```

Add the subparser (after the `lieux-apply` block):

```python
    lm_p = sub.add_parser("lieux-merge",
                          help="Exécute les fusions de lieux depuis un YAML relu (jamais auto)")
    lm_p.add_argument("--merges", required=True, help="chemin du YAML de fusions (relu par un humain)")
    lm_p.add_argument("--dry-run", action="store_true", help="simuler sans fusionner")
    lm_p.add_argument("--date", default=None, help="date du rapport (défaut : aujourd'hui)")
```

Add dispatch (in `main`, after the `lieux-apply` branch):

```python
    elif args.command == "lieux-merge":
        lieux_merge_cmd(args)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /Users/fjacquet/Projects/genecrew && uv run python -m pytest genecrew/tests/test_places_merge.py -q`
Expected: PASS (2 tests).

- [ ] **Step 5: Commit**

```bash
git add genecrew/src/genecrew/places_merge.py genecrew/src/genecrew/main.py \
        genecrew/tests/test_places_merge.py
git commit -m "feat(places): genecrew lieux-merge — execute reviewed merges (never auto)"
```

---

## Finalisation (après Task 18, hors boucle par-tâche)

- [ ] **cct** : bump `version` (`0.11.1` → `0.12.0`) dans `crewai_custom_tools/pyproject.toml` + entrée `CHANGELOG.md` (nouveau domaine `geo/` : résolveurs FR/CH/Nominatim, registre, score, transitions data-driven ; modèles de lieux ; outils Create/Update/MergePlace + dates Gramps). Suite complète : `cd /Users/fjacquet/Projects/crewai_custom_tools && uv run python -m pytest -q`.
- [ ] **genecrew** : entrée `CHANGELOG.md` (2026-07-19, commandes `lieux` / `lieux-apply` / `lieux-merge`), mention dans `CLAUDE.md` (liste des commandes + gotchas GPS WGS84/`[lon,lat]`/swisstopo) + ADR `docs/adr/0010-ecriture-lieux-hierarchie.md` (relâche bornée « lieu = proposition » ; fusions sous revue). Suite complète : `cd /Users/fjacquet/Projects/genecrew && uv run python -m pytest genecrew/tests/ -q`.
- [ ] Revue finale de branche (subagent-driven : final whole-branch review) sur les DEUX repos, puis `superpowers:finishing-a-development-branch`.
