# Standardisateur de lieux — correctifs vrai arbre — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development
> (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use
> checkbox (`- [ ]`) syntax for tracking.

**Goal:** rendre le Standardisateur de lieux opérationnel sur le vrai arbre Gramps (lieux « à
plat », sans code INSEE) en corrigeant 3 défauts : parser, scoring, résolution France par nom.

**Architecture:** tout dans la bibliothèque `crewai_custom_tools` (domaine pur + résolveurs
géo). Un parser positionnel corrigé, une similarité « cœur » monotone partagée, et une
résolution France par nom autoritaire (geo.api.gouv.fr). Aucun changement du contrat d'écriture
ni de l'orchestration `genecrew` ; validation finale par dry-run réel depuis `genecrew`.

**Tech Stack:** Python 3, `uv`, `httpx` (+ `MockTransport`/mappers purs en test), pytest,
Pydantic (modèles `domain.py`), geo.api.gouv.fr, swisstopo GeoAdmin SearchServer, Nominatim/OSM.

**Spec:** `docs/superpowers/specs/2026-07-19-standardisateur-lieux-vrai-arbre-design.md`

## Global Constraints

- Tout le code de correctif est dans `crewai_custom_tools/src/crewai_custom_tools/tools/genealogy/`.
  Aucun changement de code `genecrew` (seule la validation réelle s'y exécute).
- **Contrat d'écriture inchangé** : dry-run par défaut, idempotence, garde-fou d'ambiguïté
  (marge <0.10 sur le top-2), propositions pour revue humaine, fusions jamais auto.
- **`best_similarity` est monotone** : `best_similarity(a,b) >= similarity(a,b)` pour tout
  `(a,b)` — les correspondances exactes restent à 1.0.
- **France** : code INSEE prioritaire (chemin inchangé). Sans INSEE, résolution par nom ;
  **nom exact unique → `ecrire`** (autoritaire, score 1.0) ; **>1 exact → proposition**
  (`ambiguous=True`) ; **0 exact → `None`** (bascule registre). Département/région de la chaîne
  départagent d'abord.
- **Le score décide pour toutes les sources.** Nominatim : `provider_conf = 1.0` (ne plus
  multiplier par `importance`).
- **swisstopo** : requête restreinte aux communes via `origins=gg25` (vérifié : renvoie
  « Lausanne (VD) » et exclut écoles/POI).
- **Invariants GPS** : WGS84 décimal ; GeoJSON = `[lon, lat]` (ne pas inverser) ; swisstopo lire
  `lat`/`lon`, **jamais `x`/`y`**.
- **Tests par classe**, hors-ligne : fixtures synthétiques, `_http_get` monkeypatché ou mappers
  purs. Jamais d'extraits du vrai arbre.
- Lancer les tests depuis le repo cct :
  `cd /Users/fjacquet/Projects/crewai_custom_tools && uv run python -m pytest ...`.
- Modèles (`models/domain.py`, ne pas modifier) :
  `ParsedPlace(raw, commune='', insee=None, postal=None, departement='', region='', country='', shifted=False)` ;
  `ResolvedPlace(name, place_type, lat=None, long=None, code=None, chains, alt_names, score, ambiguous=False, source, query)` ;
  `PlaceLevel(name, place_type, code=None)` ; `DatedChain(levels, date_qualifier=None)` ;
  `DatedName(value, date_qualifier=None)`.

---

### Task 1 : Parser — un nom nu tronqué à droite est une commune, pas un pays (D1)

**Files:**
- Modify: `crewai_custom_tools/src/crewai_custom_tools/tools/genealogy/standardize/places.py`
- Test: `crewai_custom_tools/tests/test_genealogy_places_parse.py`

**Interfaces:**
- Consumes: `normalize_country`, `_COUNTRY` (déjà dans le module).
- Produces: `parse_pname(raw: str) -> ParsedPlace` — comportement inchangé sauf : quand aucune
  commune n'est trouvée et que le segment « pays » n'est pas un pays connu, ce segment devient
  `commune` et `country` devient `""`.

- [ ] **Step 1: Write the failing tests**

Ajouter à `tests/test_genealogy_places_parse.py` :

```python
def test_parse_right_truncated_flat_name_is_commune():
    from crewai_custom_tools.tools.genealogy.standardize.places import parse_pname
    p = parse_pname(", , BOURGES, , , , ,")
    assert p.commune == "BOURGES"
    assert p.country == ""

def test_parse_single_token_is_commune():
    from crewai_custom_tools.tools.genealogy.standardize.places import parse_pname
    p = parse_pname("Bourges")
    assert p.commune == "Bourges"
    assert p.country == ""

def test_parse_known_country_last_segment_unchanged():
    from crewai_custom_tools.tools.genealogy.standardize.places import parse_pname
    p = parse_pname("Lausanne, Vaud, Suisse")
    assert p.commune == "Lausanne"
    assert p.country == "Suisse"

def test_parse_full_french_chain_unchanged():
    from crewai_custom_tools.tools.genealogy.standardize.places import parse_pname
    p = parse_pname("Bourges, Cher, Centre-Val de Loire, France")
    assert p.commune == "Bourges"
    assert p.country == "France"
    assert p.departement == "Cher"

def test_parse_garbage_becomes_commune_not_country():
    # A date/URL/description in the name field must NOT be invented as a country;
    # it becomes the commune so the downstream resolver returns nothing -> indecidable.
    from crewai_custom_tools.tools.genealogy.standardize.places import parse_pname
    p = parse_pname(", , 1790 ( avant), , , , ,")
    assert p.commune == "1790 ( avant)"
    assert p.country == ""
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /Users/fjacquet/Projects/crewai_custom_tools && uv run python -m pytest tests/test_genealogy_places_parse.py -q -k "right_truncated or single_token or garbage"`
Expected: FAIL — `p.commune == ''` / `p.country == 'BOURGES'` (actuel).

- [ ] **Step 3: Implement**

Dans `standardize/places.py`, ajouter le jeu de pays connus au niveau module (après `_COUNTRY`) :

```python
_KNOWN_COUNTRIES = frozenset(_COUNTRY.values())
```

Dans `parse_pname`, juste **après** le bloc qui calcule `commune`/`commune_idx` (le
`if insee_idx is not None ... else: for i in nonempty_idx: ...`) et **avant** le calcul de
`used`/`tail`, insérer :

```python
    # Nom nu tronqué à droite (", , BOURGES, , ,") : le seul segment rempli a été pris pour
    # le pays et la commune est restée vide. Si ce "pays" n'est pas un pays connu, c'est en
    # réalité le nom le plus spécifique -> commune, pas pays. Le garbage (date/URL) suit le
    # même chemin et sera laissé indécidable par le résolveur.
    if not commune and country and country not in _KNOWN_COUNTRIES:
        commune = segments[country_idx]
        commune_idx = country_idx
        country = ""
```

(`shifted` reste `country == "France" and insee is None` — inchangé, calculé après ce bloc.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /Users/fjacquet/Projects/crewai_custom_tools && uv run python -m pytest tests/test_genealogy_places_parse.py -q`
Expected: PASS (nouveaux + existants).

- [ ] **Step 5: Commit**

```bash
cd /Users/fjacquet/Projects/crewai_custom_tools
git add src/crewai_custom_tools/tools/genealogy/standardize/places.py tests/test_genealogy_places_parse.py
git commit -m "fix(genealogy): parse right-truncated flat place name as commune, not country

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01EGpms5iNHmbNbvp28nimYu"
```

---

### Task 2 : `best_similarity` — similarité « cœur » monotone (D2, fondation)

**Files:**
- Modify: `crewai_custom_tools/src/crewai_custom_tools/tools/genealogy/geo/score.py`
- Test: `crewai_custom_tools/tests/test_genealogy_places_score.py`

**Interfaces:**
- Consumes: `similarity` (déjà présent).
- Produces: `best_similarity(asked: str, returned: str) -> float` — meilleure similarité entre
  `asked` et une forme-cœur de `returned` (label entier, sans suffixe parenthésé, jetons).
  Monotone : `>= similarity(asked, returned)`. `fuzzy_score`, `similarity`, `is_ambiguous`
  restent inchangés.

- [ ] **Step 1: Write the failing tests**

Ajouter à `tests/test_genealogy_places_score.py` :

```python
def test_best_similarity_strips_paren_suffix():
    from crewai_custom_tools.tools.genealogy.geo.score import best_similarity
    assert best_similarity("Lausanne", "Lausanne (VD)") == 1.0
    assert best_similarity("Bern", "Bern (BE)") == 1.0

def test_best_similarity_multiscript_token():
    from crewai_custom_tools.tools.genealogy.geo.score import best_similarity
    assert best_similarity("Annaba", "Annaba ⵄⴻⵍⵃⴲⵃ عنابة") == 1.0

def test_best_similarity_monotone_ge_similarity():
    from crewai_custom_tools.tools.genealogy.geo.score import best_similarity, similarity
    for a, b in [("Lausanne", "Lausanne (VD)"), ("Aix en Provence", "Aix-en-Provence"),
                 ("Paris", "Marseille"), ("x", "y")]:
        assert best_similarity(a, b) >= similarity(a, b)

def test_best_similarity_no_substring_inflation():
    from crewai_custom_tools.tools.genealogy.geo.score import best_similarity
    # a shorter query must not reach 1.0 against a longer token
    assert best_similarity("Ann", "Annaba") < 1.0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /Users/fjacquet/Projects/crewai_custom_tools && uv run python -m pytest tests/test_genealogy_places_score.py -q -k best_similarity`
Expected: FAIL — `AttributeError`/`ImportError: cannot import name 'best_similarity'`.

- [ ] **Step 3: Implement**

Dans `geo/score.py`, ajouter `import re` en tête si absent, puis :

```python
_PAREN = re.compile(r"\s*\([^)]*\)")             # " (VD)", " (68)"


def _forms(returned: str) -> set[str]:
    """Formes-cœur candidates d'un libellé décoré : le tout, le tout sans suffixe parenthésé,
    et chaque jeton (espaces) de chacun — pour matcher un nom-cœur dans un libellé multi-mots
    ou multi-scripts."""
    stripped = _PAREN.sub("", returned).strip()
    forms = {returned.strip(), stripped}
    for base in (returned, stripped):
        forms.update(tok for tok in base.split() if tok)
    return {f for f in forms if f}


def best_similarity(asked: str, returned: str) -> float:
    """Meilleure similarité entre `asked` et une forme-cœur de `returned`. Monotone :
    toujours >= similarity(asked, returned) — les exacts restent 1.0, les décorations
    ('(VD)', alias multi-scripts) ne dépriment plus le score."""
    return max((similarity(asked, f) for f in _forms(returned)), default=0.0)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /Users/fjacquet/Projects/crewai_custom_tools && uv run python -m pytest tests/test_genealogy_places_score.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
cd /Users/fjacquet/Projects/crewai_custom_tools
git add src/crewai_custom_tools/tools/genealogy/geo/score.py tests/test_genealogy_places_score.py
git commit -m "feat(genealogy): add monotone core-name best_similarity

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01EGpms5iNHmbNbvp28nimYu"
```

---

### Task 3 : Résolveur suisse — score sur le nom-cœur, argmax, communes seules (D2)

**Files:**
- Modify: `crewai_custom_tools/src/crewai_custom_tools/tools/genealogy/geo/suisse.py`
- Test: `crewai_custom_tools/tests/test_genealogy_geo_suisse.py`

**Interfaces:**
- Consumes: `best_similarity` (Task 2), `is_ambiguous`.
- Produces: `map_swiss(payload, parsed)` — score = `best_similarity(commune, label_cœur)`,
  choisit le **meilleur** résultat (argmax) et non `results[0]` ; `resolve_ch` ajoute
  `origins=gg25` à la requête.

- [ ] **Step 1: Write the failing tests**

Ajouter à `tests/test_genealogy_geo_suisse.py` (mappers purs, offline) :

```python
def _swiss_payload(*labels):
    return {"results": [{"attrs": {"label": f"<b>{lbl}</b>", "lat": 46.5, "lon": 6.6}}
                        for lbl in labels]}

def test_map_swiss_exact_match_scores_one_despite_canton_suffix():
    from crewai_custom_tools.tools.genealogy.geo.suisse import map_swiss
    from crewai_custom_tools.tools.genealogy.models.domain import ParsedPlace
    rp = map_swiss(_swiss_payload("Lausanne (VD)"),
                   ParsedPlace(raw="Lausanne, Vaud, Suisse", commune="Lausanne", country="Suisse"))
    assert rp is not None
    assert rp.score == 1.0
    assert rp.name == "Lausanne (VD)"
    assert rp.lat == "46.5" and rp.long == "6.6"          # WGS84 lat/lon, jamais x/y

def test_map_swiss_picks_best_not_first():
    from crewai_custom_tools.tools.genealogy.geo.suisse import map_swiss
    from crewai_custom_tools.tools.genealogy.models.domain import ParsedPlace
    # exact match is second in the list -> argmax must pick it
    rp = map_swiss(_swiss_payload("Belmont-sur-Lausanne (VD)", "Lausanne (VD)"),
                   ParsedPlace(raw="", commune="Lausanne", country="Suisse"))
    assert rp.name == "Lausanne (VD)"
    assert rp.score == 1.0

def test_resolve_ch_requests_municipalities_only(monkeypatch):
    from crewai_custom_tools.tools.genealogy.geo import suisse
    from crewai_custom_tools.tools.genealogy.models.domain import ParsedPlace
    seen = {}
    def fake_get(url, params):
        seen.update(params)
        return _swiss_payload("Lausanne (VD)")
    monkeypatch.setattr(suisse, "_http_get", fake_get)
    suisse.resolve_ch(ParsedPlace(raw="", commune="Lausanne", country="Suisse"))
    assert seen.get("origins") == "gg25"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /Users/fjacquet/Projects/crewai_custom_tools && uv run python -m pytest tests/test_genealogy_geo_suisse.py -q -k "scores_one or best_not_first or municipalities"`
Expected: FAIL — score `0.762` au lieu de `1.0` ; `origins` absent.

- [ ] **Step 3: Implement**

Dans `geo/suisse.py`, remplacer l'import de score :

```python
from crewai_custom_tools.tools.genealogy.geo.score import best_similarity, is_ambiguous
```

Dans `map_swiss`, remplacer le calcul des scores et le choix du résultat :

```python
    results = payload.get("results") or []
    if not results:
        return None
    labels = [_TAG.sub("", r["attrs"].get("label", "")).strip() for r in results]
    scores = [best_similarity(parsed.commune, lbl) for lbl in labels]
    best = max(range(len(results)), key=lambda i: scores[i])
    attrs = results[best]["attrs"]
    name = labels[best]
    return ResolvedPlace(
        name=name or parsed.commune, place_type="Municipality",
        lat=str(attrs["lat"]), long=str(attrs["lon"]),     # WGS84 ; jamais x/y (LV95)
        chains=[DatedChain(levels=[PlaceLevel(name="Suisse", place_type="Country")])],
        alt_names=[DatedName(value=parsed.raw)],
        score=scores[best], ambiguous=is_ambiguous(scores),
        source="swisstopo", query=parsed.commune,
    )
```

Dans `resolve_ch`, ajouter `origins=gg25` à la requête :

```python
    payload = _http_get(_URL, {"searchText": parsed.commune, "type": "locations",
                               "origins": "gg25", "sr": "4326", "limit": 5})
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /Users/fjacquet/Projects/crewai_custom_tools && uv run python -m pytest tests/test_genealogy_geo_suisse.py -q`
Expected: PASS. Mettre à jour tout test existant qui asseyait un score déprécié (ex. 0.762) —
c'est l'objet du correctif ; les tests d'exact/ambiguïté restent inchangés.

- [ ] **Step 5: Commit**

```bash
cd /Users/fjacquet/Projects/crewai_custom_tools
git add src/crewai_custom_tools/tools/genealogy/geo/suisse.py tests/test_genealogy_geo_suisse.py
git commit -m "fix(genealogy): swiss resolver scores core name, picks argmax, municipalities only

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01EGpms5iNHmbNbvp28nimYu"
```

---

### Task 4 : Résolveur Nominatim — score sur le nom-cœur, sans `importance` (D2)

**Files:**
- Modify: `crewai_custom_tools/src/crewai_custom_tools/tools/genealogy/geo/nominatim.py`
- Test: `crewai_custom_tools/tests/test_genealogy_geo_nominatim.py`

**Interfaces:**
- Consumes: `best_similarity` (Task 2), `is_ambiguous`.
- Produces: `map_nominatim(results, parsed)` — score = `best_similarity(commune,
  display_name.split(",")[0])` (plus de multiplication par `importance`). Argmax + ResolvedPlace
  inchangés.

- [ ] **Step 1: Write the failing tests**

Ajouter à `tests/test_genealogy_geo_nominatim.py` :

```python
def test_map_nominatim_ignores_low_importance_on_exact_name():
    from crewai_custom_tools.tools.genealogy.geo.nominatim import map_nominatim
    from crewai_custom_tools.tools.genealogy.models.domain import ParsedPlace
    results = [{"display_name": "Stuttgart, Bade-Wurtemberg, Allemagne",
                "lat": "48.77", "lon": "9.18", "importance": 0.25}]
    rp = map_nominatim(results, ParsedPlace(raw="", commune="Stuttgart", country="Allemagne"))
    assert rp is not None
    assert rp.score == 1.0                       # was ~0.25 * 1.0 before
    assert rp.lat == "48.77" and rp.long == "9.18"

def test_map_nominatim_multiscript_core_match():
    from crewai_custom_tools.tools.genealogy.geo.nominatim import map_nominatim
    from crewai_custom_tools.tools.genealogy.models.domain import ParsedPlace
    results = [{"display_name": "Annaba ⵄⴻⵍⵃⴲⵃ عنابة, Algérie",
                "lat": "36.9", "lon": "7.76", "importance": 0.3}]
    rp = map_nominatim(results, ParsedPlace(raw="", commune="Annaba", country="Algérie"))
    assert rp.score == 1.0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /Users/fjacquet/Projects/crewai_custom_tools && uv run python -m pytest tests/test_genealogy_geo_nominatim.py -q -k "low_importance or multiscript"`
Expected: FAIL — score ~0.25/0.08 au lieu de 1.0.

- [ ] **Step 3: Implement**

Dans `geo/nominatim.py`, remplacer l'import :

```python
from crewai_custom_tools.tools.genealogy.geo.score import best_similarity, is_ambiguous
```

Dans `map_nominatim`, remplacer le calcul des scores (le reste — `best`, `top`, `levels`,
`ResolvedPlace` — est inchangé) :

```python
    scores = [best_similarity(parsed.commune, r.get("display_name", "").split(",")[0])
              for r in results]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /Users/fjacquet/Projects/crewai_custom_tools && uv run python -m pytest tests/test_genealogy_geo_nominatim.py -q`
Expected: PASS. Mettre à jour tout test existant asseyant un score déprécié dépendant de
`importance`.

- [ ] **Step 5: Commit**

```bash
cd /Users/fjacquet/Projects/crewai_custom_tools
git add src/crewai_custom_tools/tools/genealogy/geo/nominatim.py tests/test_genealogy_geo_nominatim.py
git commit -m "fix(genealogy): nominatim scores core name, drops importance multiplier

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01EGpms5iNHmbNbvp28nimYu"
```

---

### Task 5 : Résolveur France par nom — autoritaire, filtre nom exact, garde homonymes (D3)

**Files:**
- Modify: `crewai_custom_tools/src/crewai_custom_tools/tools/genealogy/geo/france.py`
- Test: `crewai_custom_tools/tests/test_genealogy_geo_france.py`

**Interfaces:**
- Consumes: `_norm` (de `geo/score.py`), `_http_get`, `map_commune` (déjà dans france.py),
  `_FIELDS`.
- Produces: `resolve_fr(parsed)` — code INSEE prioritaire (inchangé) ; sinon résolution par
  nom : 1 exact → autoritaire (score 1.0, `ambiguous=False`) ; >1 exact → `ambiguous=True` ;
  0 exact → `None`. Dept/région départagent. `map_commune` : `query` dérivé du code résolu.

- [ ] **Step 1: Write the failing tests**

Ajouter à `tests/test_genealogy_geo_france.py` :

```python
_BOURGES = {"nom": "Bourges", "code": "18033",
            "centre": {"type": "Point", "coordinates": [2.3983, 47.078]},
            "departement": {"code": "18", "nom": "Cher"},
            "region": {"code": "24", "nom": "Centre-Val de Loire"}}

def _sm(code, dept):
    return {"nom": "Sainte-Marie", "code": code,
            "centre": {"type": "Point", "coordinates": [0.0, 0.0]},
            "departement": {"code": "", "nom": dept}, "region": {"code": "", "nom": ""}}

def test_resolve_fr_by_name_unique_is_authoritative(monkeypatch):
    from crewai_custom_tools.tools.genealogy.geo import france
    from crewai_custom_tools.tools.genealogy.models.domain import ParsedPlace
    monkeypatch.setattr(france, "_http_get", lambda path, params: [_BOURGES])
    rp = france.resolve_fr(ParsedPlace(raw="", commune="Bourges", country="France"))
    assert rp is not None
    assert rp.code == "18033" and rp.score == 1.0 and rp.ambiguous is False
    assert rp.lat == "47.078" and rp.long == "2.3983"        # GeoJSON [lon,lat] -> lat/lon
    assert [l.name for l in rp.chains[0].levels] == ["France", "Centre-Val de Loire", "Cher"]

def test_resolve_fr_by_name_fuzzy_nonexact_returns_none(monkeypatch):
    from crewai_custom_tools.tools.genealogy.geo import france
    from crewai_custom_tools.tools.genealogy.models.domain import ParsedPlace
    # geo.api.gouv.fr's nom search is fuzzy: "Sainte-Marie" also returns this near-name,
    # which must NOT count as an exact match.
    fuzzy = {"nom": "Saintes-Maries-de-la-Mer", "code": "13096",
             "centre": {"type": "Point", "coordinates": [4.4, 43.4]},
             "departement": {"code": "13", "nom": "Bouches-du-Rhône"}, "region": {"nom": ""}}
    monkeypatch.setattr(france, "_http_get", lambda path, params: [fuzzy])
    rp = france.resolve_fr(ParsedPlace(raw="", commune="Sainte-Marie", country="France"))
    assert rp is None

def test_resolve_fr_by_name_homonyms_are_proposition(monkeypatch):
    from crewai_custom_tools.tools.genealogy.geo import france
    from crewai_custom_tools.tools.genealogy.models.domain import ParsedPlace
    monkeypatch.setattr(france, "_http_get",
                        lambda path, params: [_sm("97418", "La Réunion"), _sm("35294", "Ille-et-Vilaine")])
    rp = france.resolve_fr(ParsedPlace(raw="", commune="Sainte-Marie", country="France"))
    assert rp is not None and rp.ambiguous is True

def test_resolve_fr_by_name_department_disambiguates(monkeypatch):
    from crewai_custom_tools.tools.genealogy.geo import france
    from crewai_custom_tools.tools.genealogy.models.domain import ParsedPlace
    monkeypatch.setattr(france, "_http_get",
                        lambda path, params: [_sm("97418", "La Réunion"), _sm("25523", "Doubs")])
    rp = france.resolve_fr(ParsedPlace(raw="", commune="Sainte-Marie", departement="Doubs", country="France"))
    assert rp is not None and rp.ambiguous is False and rp.code == "25523"

def test_resolve_fr_insee_path_still_used(monkeypatch):
    from crewai_custom_tools.tools.genealogy.geo import france
    from crewai_custom_tools.tools.genealogy.models.domain import ParsedPlace
    calls = []
    def fake_get(path, params):
        calls.append(path)
        return dict(_BOURGES)
    monkeypatch.setattr(france, "_http_get", fake_get)
    rp = france.resolve_fr(ParsedPlace(raw="", commune="Bourges", insee="18033", country="France"))
    assert rp is not None and rp.code == "18033"
    assert calls == ["/communes/18033"]        # code path, not by-name
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /Users/fjacquet/Projects/crewai_custom_tools && uv run python -m pytest tests/test_genealogy_geo_france.py -q -k by_name`
Expected: FAIL — `resolve_fr` renvoie `None` sans INSEE (chemin par nom absent).

- [ ] **Step 3: Implement**

Dans `geo/france.py`, ajouter l'import de `_norm` :

```python
from crewai_custom_tools.tools.genealogy.geo.score import _norm
```

Dans `map_commune`, rendre `query` indépendant de `parsed.insee` (dérivé du code résolu) :

```python
        chains=[DatedChain(levels=levels)],
        alt_names=[DatedName(value=parsed.raw)],
        score=1.0, source="geo.api.gouv.fr", query=f"/communes/{payload.get('code')}",
    )
```

Remplacer `resolve_fr` et ajouter le helper par nom :

```python
def resolve_fr(parsed: ParsedPlace) -> ResolvedPlace | None:
    """Résout une commune française. Code INSEE prioritaire (autoritaire) ; sinon par nom."""
    if parsed.insee:
        payload = _http_get(f"/communes/{parsed.insee}", {"fields": _FIELDS})
        if isinstance(payload, dict) and "centre" in payload:
            return map_commune(payload, parsed)
        return None
    if not parsed.commune:
        return None
    return _resolve_fr_by_name(parsed)


def _resolve_fr_by_name(parsed: ParsedPlace) -> ResolvedPlace | None:
    """Résolution par nom via geo.api.gouv.fr. La recherche `nom` est floue -> on ne garde que
    les correspondances de nom EXACTES. 1 exact -> autoritaire ; >1 -> proposition ; 0 -> None."""
    results = _http_get("/communes", {"nom": parsed.commune, "fields": _FIELDS,
                                      "boost": "population", "limit": 10})
    if not isinstance(results, list) or not results:
        return None
    exact = [c for c in results if _norm(c.get("nom", "")) == _norm(parsed.commune)]
    ctx = _norm(parsed.departement) or _norm(parsed.region)
    if ctx and len(exact) > 1:
        filtered = [c for c in exact
                    if ctx in (_norm((c.get("departement") or {}).get("nom", "")),
                               _norm((c.get("region") or {}).get("nom", "")))
                    or (c.get("departement") or {}).get("code", "") == parsed.departement]
        if filtered:
            exact = filtered
    if not exact:
        return None                                  # abréviations/fautes -> bascule registre
    resolved = map_commune(exact[0], parsed)         # exact[0] = le plus peuplé (boost)
    if len(exact) > 1:
        resolved.ambiguous = True                    # vrais homonymes -> proposition
        resolved.source = f"geo.api.gouv.fr ({len(exact)} homonymes)"
    return resolved
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /Users/fjacquet/Projects/crewai_custom_tools && uv run python -m pytest tests/test_genealogy_geo_france.py -q`
Expected: PASS (nouveaux + existants ; le chemin INSEE reste inchangé).

- [ ] **Step 5: Commit**

```bash
cd /Users/fjacquet/Projects/crewai_custom_tools
git add src/crewai_custom_tools/tools/genealogy/geo/france.py tests/test_genealogy_geo_france.py
git commit -m "feat(genealogy): resolve French places by name (authoritative unique, homonyms proposed)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01EGpms5iNHmbNbvp28nimYu"
```

---

## Validation finale (après les 5 tâches)

- [ ] **Suite complète cct verte** :
  `cd /Users/fjacquet/Projects/crewai_custom_tools && uv run python -m pytest -q` → tout PASS.
  `uv run ruff check .` propre sur les fichiers touchés.

- [ ] **Validation réelle depuis genecrew** (la leçon « valider sur le vrai arbre ») :
  après `uv sync` si besoin, depuis `/Users/fjacquet/Projects/genecrew` :
  ```bash
  GENECREW_DRY_RUN=true uv run genecrew lieux --scope all
  GENECREW_DRY_RUN=true uv run genecrew lieux-apply --scope all --dry-run
  ```
  Attendu : le rapport `lieux` montre des lignes `ecrire` non nulles pour la France (par nom)
  et la Suisse (score corrigé) — ordre de grandeur ~25 CH + jusqu'à ~39 FR selon les
  homonymes ; le rapport `lieux-apply` (dry-run) montre « Lieux écrits » > 0 (simulés), **0
  erreur**, et un re-run immédiat reste idempotent (0 nouvel écrit, tout « déjà structuré » ou
  « proposition »). Les communes françaises homonymes restent en proposition ; le garbage
  (dates/URL/descriptions) reste indécidable.

---

## Self-Review (rempli par l'auteur du plan)

- **Couverture spec** : D1 → Task 1 ; D2 → Task 2 (`best_similarity`) + Task 3 (suisse) + Task 4
  (nominatim) ; D3 → Task 5 (france). USA écarté (noms Census propres, sans décoration →
  `best_similarity` == `similarity`, aucun gain — YAGNI). Registre inchangé (routage déjà
  correct : bare commune → `country=""` → Nominatim ; France-tagged → resolve_fr). Contrat
  d'écriture/ambiguïté inchangé. Validation réelle couverte.
- **Cohérence des types** : `best_similarity(asked, returned) -> float` utilisé identiquement
  en Tasks 3/4 ; `resolve_fr(parsed) -> ResolvedPlace | None` signature inchangée (registre non
  impacté) ; `map_commune` garde sa signature, seule la ligne `query` change ; GeoJSON
  `[lon, lat]` → `lat`/`long` respecté dans les tests France ; swisstopo `lat`/`lon` (jamais
  `x`/`y`) respecté dans les tests suisse.
- **Placeholders** : aucun — chaque étape porte le code et la commande réels.
