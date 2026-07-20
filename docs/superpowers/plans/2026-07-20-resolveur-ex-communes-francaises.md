# Résolveur des ex-communes françaises — plan d'implémentation

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Résoudre de façon autoritaire les communes françaises fusionnées (communes associées / déléguées), aujourd'hui invisibles pour `resolve_fr`, en émettant deux placerefs datées — puis s'en servir pour nettoyer le lieu `P0080` de l'arbre.

**Architecture:** Un nouveau module de résolution `geo/france_ex_communes.py` interroge `geo.api.gouv.fr/communes_associees_deleguees` (rattachement + code INSEE propre) puis Wikidata en SPARQL par `P374` (date de dissolution, successeur, GPS). Il n'émet des chaînes datées que si les deux sources concordent sur le successeur. La couche d'écriture Gramps sait déjà poser plusieurs placerefs datées : elle n'est pas touchée. Côté `genecrew`, un scope `place:<ID>` permet de valider sur un lieu unique avant d'élargir.

**Tech Stack:** Python 3, `pydantic`, `httpx` (geo.api.gouv.fr), `requests` (SPARQL Wikidata), `pytest`, `uv`.

## Global Constraints

- Deux dépôts : `/Users/fjacquet/Projects/crewai_custom_tools` (résolveur) et `/Users/fjacquet/Projects/genecrew` (scope + nettoyage). **Faire les opérations git de chaque dépôt dans des appels séparés** — un `cd A && git … && cd B && git …` exécute les deux git dans A.
- Tests **offline** : toute fonction réseau est un `_http_get` / `sparql_rows` monkeypatché. Aucun test ne sort sur le réseau.
- **Coordonnées WGS84 décimales.** `centre` de geo.api.gouv.fr est du GeoJSON `[lon, lat]` ; `P625` de Wikidata est du WKT `Point(lon lat)`. **Longitude d'abord dans les deux cas.**
- Date de dissolution retenue : `1972-12-31` (Wikidata `P576`, précision jour). Format des qualificatifs : `avant YYYY-MM-DD` / `après YYYY-MM-DD` — c'est ce qu'attend `date_qualifier_to_gramps_date`.
- Jamais de date inventée : sources discordantes ou `P576` absent → une seule chaîne non datée.
- Version de la bibliothèque : `0.18.0` → `0.19.0`. (`feat/export-missing-tools` a été
  **fusionnée dans `main`** pendant la Task 1 et y a posé `0.18.0` ; la branche a donc été
  rebasée sur `main` et part maintenant de cette version.)
- Branches déjà créées, **une par dépôt, toutes deux nommées `feat/resolveur-ex-communes`** :
  celle de `crewai_custom_tools` est rebasée sur `main` (base `d58b087`), celle de `genecrew`
  est en place.
  Ne travailler sur `main` dans aucun des deux.
- `genecrew` dépend de la bibliothèque en **editable par chemin**, sans version épinglée :
  c'est la branche *checked out* dans `../crewai_custom_tools` qui fait foi. Ne pas en
  changer pendant l'exécution.
- Spec de référence : `docs/superpowers/specs/2026-07-20-resolveur-ex-communes-francaises-design.md`.

### Écart assumé par rapport à la spec (§6)

La spec prévoyait de brancher `resolve_fr_ex_commune` **dans** `resolve_fr`. Impossible sans
import circulaire : `france_ex_communes.py` importe `map_commune` depuis `france.py`. Le
branchement se fait donc dans `registry.py`, par composition :

```python
"France": lambda p: resolve_fr(p) or resolve_fr_ex_commune(p),
```

Sémantique identique (le chemin ex-commune n'est tenté que si `resolve_fr` rend `None`), une
seule direction d'import. Noter qu'un résultat **ambigu** de `resolve_fr` est *truthy* : une
commune vivante ambiguë ne bascule pas sur le chemin ex-commune — c'est le comportement voulu.

---

### Task 1 : Accès SPARQL réutilisable

**Files:**
- Modify: `crewai_custom_tools/src/crewai_custom_tools/tools/web/wikidata.py`
- Test: `crewai_custom_tools/tests/test_genealogy_wikidata_sparql.py` (créer)

**Interfaces:**
- Produces: `sparql_rows(query: str, *, timeout: float = 30.0) -> list[dict[str, str]]` — exécute une requête SPARQL et rend les lignes aplaties `{variable: valeur}`. Lève sur erreur HTTP. C'est le point monkeypatché par les tests de la Task 2.

Le module contient déjà `WikidataSparqlTool` (outil CrewAI) avec `SPARQL_ENDPOINT` et
`USER_AGENT`. On en extrait la partie transport en fonction libre, pour que le résolveur
l'utilise sans passer par un `BaseTool`.

- [ ] **Step 1: Écrire le test qui échoue**

Créer `crewai_custom_tools/tests/test_genealogy_wikidata_sparql.py` :

```python
# tests/test_genealogy_wikidata_sparql.py
from crewai_custom_tools.tools.web import wikidata


class _FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


def test_sparql_rows_flattens_bindings(monkeypatch):
    payload = {
        "head": {"vars": ["item", "dissolved"]},
        "results": {"bindings": [
            {"item": {"value": "http://www.wikidata.org/entity/Q25398054"},
             "dissolved": {"value": "1972-12-31T00:00:00Z"}},
        ]},
    }
    seen = {}

    def fake_get(url, params, headers, timeout):
        seen["url"] = url
        seen["query"] = params["query"]
        seen["format"] = params["format"]
        return _FakeResponse(payload)

    monkeypatch.setattr(wikidata.requests, "get", fake_get)
    rows = wikidata.sparql_rows("SELECT ?item WHERE { ?item wdt:P374 '55451' }")
    assert rows == [{"item": "http://www.wikidata.org/entity/Q25398054",
                     "dissolved": "1972-12-31T00:00:00Z"}]
    assert seen["url"] == wikidata.SPARQL_ENDPOINT
    assert seen["format"] == "json"


def test_sparql_rows_empty_results(monkeypatch):
    monkeypatch.setattr(wikidata.requests, "get",
                        lambda *a, **k: _FakeResponse({"results": {"bindings": []}}))
    assert wikidata.sparql_rows("SELECT ?x WHERE { ?x wdt:P374 '00000' }") == []
```

- [ ] **Step 2: Lancer le test, vérifier qu'il échoue**

```bash
cd /Users/fjacquet/Projects/crewai_custom_tools
uv run python -m pytest tests/test_genealogy_wikidata_sparql.py -v
```

Attendu : `FAILED` — `AttributeError: module ... has no attribute 'sparql_rows'`.

- [ ] **Step 3: Implémenter**

Dans `tools/web/wikidata.py`, insérer après la constante `USER_AGENT` :

```python
def sparql_rows(query: str, *, timeout: float = 30.0) -> list[dict[str, str]]:
    """Run a SPARQL query and return its bindings flattened as {variable: value}.

    Free transport shared by the CrewAI tool and the geo resolvers (which must not
    depend on a BaseTool). Raises on HTTP error.
    """
    response = requests.get(
        SPARQL_ENDPOINT,
        params={"query": query, "format": "json"},
        headers={"User-Agent": USER_AGENT,
                 "Accept": "application/sparql-results+json"},
        timeout=timeout,
    )
    response.raise_for_status()
    bindings = response.json().get("results", {}).get("bindings", [])
    return [{var: cell.get("value") for var, cell in binding.items()}
            for binding in bindings]
```

- [ ] **Step 4: Lancer le test, vérifier qu'il passe**

```bash
cd /Users/fjacquet/Projects/crewai_custom_tools
uv run python -m pytest tests/test_genealogy_wikidata_sparql.py -v
```

Attendu : `2 passed`.

- [ ] **Step 5: Vérifier la non-régression de l'outil existant**

```bash
cd /Users/fjacquet/Projects/crewai_custom_tools
uv run python -m pytest tests/ -q -k "wikidata or external_apis"
```

Attendu : tout passe (`WikidataSparqlTool` est inchangé).

- [ ] **Step 6: Commit**

```bash
cd /Users/fjacquet/Projects/crewai_custom_tools
git add src/crewai_custom_tools/tools/web/wikidata.py tests/test_genealogy_wikidata_sparql.py
git commit -m "feat(wikidata): sparql_rows, transport SPARQL libre réutilisable

Les résolveurs geo ont besoin d'interroger Wikidata sans passer par un
BaseTool CrewAI. Extrait le transport de WikidataSparqlTool en fonction
libre monkeypatchable."
```

---

### Task 2 : Faits d'ex-commune depuis Wikidata

**Files:**
- Create: `crewai_custom_tools/src/crewai_custom_tools/tools/genealogy/geo/france_ex_communes.py`
- Test: `crewai_custom_tools/tests/test_genealogy_geo_france_ex_communes.py` (créer)

**Interfaces:**
- Consumes: `sparql_rows(query) -> list[dict]` (Task 1).
- Produces:
  - `ExCommuneFacts` — modèle pydantic : `dissolved: str | None`, `successor_insee: str | None`, `lat: str | None`, `long: str | None`.
  - `parse_wkt_point(wkt: str) -> tuple[str, str] | None` — rend `(lat, long)` depuis `Point(lon lat)`, `None` si non parsable.
  - `wikidata_ex_commune(insee: str) -> ExCommuneFacts | None` — `None` si 0 ligne **ou** plus d'une ligne.

Cette task ne livre que la moitié Wikidata. La moitié `geo.api.gouv.fr` et l'assemblage des
chaînes arrivent en Task 3, dans le même fichier.

- [ ] **Step 1: Écrire les tests qui échouent**

Créer `crewai_custom_tools/tests/test_genealogy_geo_france_ex_communes.py` :

```python
# tests/test_genealogy_geo_france_ex_communes.py
from crewai_custom_tools.tools.genealogy.geo import france_ex_communes as fec

# Ligne réellement rendue par query.wikidata.org pour ?item wdt:P374 "55451"
_ROW_SAINT_AGNANT = {
    "item": "http://www.wikidata.org/entity/Q25398054",
    "dissolved": "1972-12-31T00:00:00Z",
    "succInsee": "55012",
    "coord": "Point(5.622588 48.842142)",
}


def test_parse_wkt_point_is_lon_lat():
    # WKT met la LONGITUDE en premier, comme GeoJSON. Inverser placerait
    # Saint-Agnant au large de la Somalie.
    assert fec.parse_wkt_point("Point(5.622588 48.842142)") == ("48.842142", "5.622588")


def test_parse_wkt_point_handles_negative_longitude():
    assert fec.parse_wkt_point("Point(-1.553621 47.218371)") == ("47.218371", "-1.553621")


def test_parse_wkt_point_rejects_garbage():
    assert fec.parse_wkt_point("") is None
    assert fec.parse_wkt_point("MULTIPOLYGON((0 0))") is None


def test_wikidata_ex_commune_single_row(monkeypatch):
    seen = {}

    def fake_rows(query):
        seen["query"] = query
        return [_ROW_SAINT_AGNANT]

    monkeypatch.setattr(fec, "sparql_rows", fake_rows)
    facts = fec.wikidata_ex_commune("55451")
    assert facts is not None
    assert facts.dissolved == "1972-12-31"           # tronqué à la date ISO
    assert facts.successor_insee == "55012"
    assert facts.lat == "48.842142" and facts.long == "5.622588"
    assert '"55451"' in seen["query"] and "wdt:P374" in seen["query"]


def test_wikidata_ex_commune_no_row_is_none(monkeypatch):
    monkeypatch.setattr(fec, "sparql_rows", lambda query: [])
    assert fec.wikidata_ex_commune("55451") is None


def test_wikidata_ex_commune_multiple_rows_is_none(monkeypatch):
    # Deux entités partageant un P374 : ambiguïté, on ne date pas.
    monkeypatch.setattr(fec, "sparql_rows",
                        lambda query: [_ROW_SAINT_AGNANT, dict(_ROW_SAINT_AGNANT)])
    assert fec.wikidata_ex_commune("55451") is None


def test_wikidata_ex_commune_missing_optionals(monkeypatch):
    # OPTIONAL non satisfaits : la variable est simplement absente de la ligne.
    monkeypatch.setattr(fec, "sparql_rows",
                        lambda query: [{"item": "http://www.wikidata.org/entity/Q1"}])
    facts = fec.wikidata_ex_commune("55451")
    assert facts is not None
    assert facts.dissolved is None and facts.successor_insee is None
    assert facts.lat is None and facts.long is None


def test_wikidata_ex_commune_network_failure_is_none(monkeypatch):
    import requests

    def boom(query):
        raise requests.ConnectionError("wikidata down")

    monkeypatch.setattr(fec, "sparql_rows", boom)
    # Wikidata n'est qu'un enrichisseur : une panne réseau ne doit pas faire
    # échouer la résolution, seulement priver de la datation.
    assert fec.wikidata_ex_commune("55451") is None


def test_wikidata_ex_commune_malformed_json_is_none(monkeypatch):
    import requests

    def boom(query):
        # requests.exceptions.JSONDecodeError hérite de RequestException (vérifié) :
        # un JSON malformé est donc couvert par la même clause que le réseau.
        raise requests.exceptions.JSONDecodeError("bad", "", 0)

    monkeypatch.setattr(fec, "sparql_rows", boom)
    assert fec.wikidata_ex_commune("55451") is None


def test_wikidata_ex_commune_programming_error_propagates(monkeypatch):
    import pytest

    def boom(query):
        raise KeyError("variable SPARQL absente du gabarit")

    monkeypatch.setattr(fec, "sparql_rows", boom)
    # Convention du dépôt (cf. places_apply.py) : un bug de programmation remonte,
    # il n'est pas déguisé en « pas de datation ».
    with pytest.raises(KeyError):
        fec.wikidata_ex_commune("55451")
```

- [ ] **Step 2: Lancer les tests, vérifier qu'ils échouent**

```bash
cd /Users/fjacquet/Projects/crewai_custom_tools
uv run python -m pytest tests/test_genealogy_geo_france_ex_communes.py -v
```

Attendu : `ModuleNotFoundError: No module named '...geo.france_ex_communes'`.

- [ ] **Step 3: Implémenter**

Créer `src/crewai_custom_tools/tools/genealogy/geo/france_ex_communes.py` :

```python
"""Résolveur des ex-communes françaises (communes associées / déléguées).

geo.api.gouv.fr/communes ne connaît que les communes VIVANTES : une commune fusionnée
(loi Marcellin, 1971) y est introuvable, et `resolve_fr` bascule alors sur Nominatim,
qui perd la hiérarchie. L'endpoint /communes_associees_deleguees les connaît, mais ne
donne aucune date de fusion — Wikidata la fournit (P576).

On ne date les rattachements que si les deux sources concordent sur le successeur.
"""

from __future__ import annotations

import re

import requests
from pydantic import BaseModel

from crewai_custom_tools.tools.web.wikidata import sparql_rows

_WKT_POINT_RE = re.compile(r"^\s*Point\(\s*(-?[\d.]+)\s+(-?[\d.]+)\s*\)\s*$", re.IGNORECASE)

# Une seule requête rend la dissolution, le successeur ET le GPS : la garde de
# recoupement (successeur vs chefLieu) ne coûte donc aucun appel supplémentaire.
_SPARQL = """SELECT ?item ?dissolved ?succInsee ?coord WHERE {{
  ?item wdt:P374 "{insee}" .
  OPTIONAL {{ ?item wdt:P576 ?dissolved }}
  OPTIONAL {{ ?item wdt:P1366 ?succ . ?succ wdt:P374 ?succInsee }}
  OPTIONAL {{ ?item wdt:P625 ?coord }}
}} LIMIT 10"""


class ExCommuneFacts(BaseModel):
    """Ce que Wikidata sait d'une ex-commune, identifiée par son code INSEE."""

    dissolved: str | None = None          # "YYYY-MM-DD"
    successor_insee: str | None = None
    lat: str | None = None                # WGS84 décimal
    long: str | None = None


def parse_wkt_point(wkt: str) -> tuple[str, str] | None:
    """'Point(lon lat)' -> ('lat', 'long'). None si non parsable.

    ATTENTION : le WKT met la LONGITUDE en premier, comme GeoJSON. Inverser rendrait
    des coordonnées parfaitement bien formées, et fausses.
    """
    match = _WKT_POINT_RE.match(wkt or "")
    if match is None:
        return None
    lon, lat = match.group(1), match.group(2)
    return lat, lon


def wikidata_ex_commune(insee: str) -> ExCommuneFacts | None:
    """Faits Wikidata pour une ex-commune. None si 0 ou >1 entité porte ce code INSEE.

    Wikidata n'est qu'un enrichisseur : toute panne réseau rend None (pas de datation)
    plutôt que de faire échouer la résolution entière.
    """
    try:
        rows = sparql_rows(_SPARQL.format(insee=insee))
    except requests.RequestException:
        # Réseau ET JSON malformé (JSONDecodeError hérite de RequestException).
        # Volontairement étroit : un KeyError ou une ValidationError seraient des
        # bugs de ce module, et doivent remonter plutôt que se déguiser en
        # « pas de datation » — même convention que places_apply.py.
        return None
    if len(rows) != 1:                     # 0 = inconnu ; >1 = ambigu -> on ne date pas
        return None
    row = rows[0]
    lat = long = None
    if row.get("coord"):
        point = parse_wkt_point(row["coord"])
        if point is not None:
            lat, long = point
    dissolved = row.get("dissolved")
    return ExCommuneFacts(
        dissolved=dissolved.split("T")[0] if dissolved else None,
        successor_insee=row.get("succInsee"),
        lat=lat, long=long,
    )
```

- [ ] **Step 4: Lancer les tests, vérifier qu'ils passent**

```bash
cd /Users/fjacquet/Projects/crewai_custom_tools
uv run python -m pytest tests/test_genealogy_geo_france_ex_communes.py -v
```

Attendu : `10 passed`.

- [ ] **Step 5: Commit**

```bash
cd /Users/fjacquet/Projects/crewai_custom_tools
git add src/crewai_custom_tools/tools/genealogy/geo/france_ex_communes.py \
        tests/test_genealogy_geo_france_ex_communes.py
git commit -m "feat(geo): faits Wikidata des ex-communes françaises

Requête SPARQL par P374 : dissolution (P576), successeur (P1366 -> son
P374) et GPS (P625) en une ligne. Parse le WKT Point(lon lat) — longitude
d'abord, comme GeoJSON. 0 ou >1 entité -> None, on ne date pas."
```

---

### Task 3 : Résolution complète de l'ex-commune

**Files:**
- Modify: `crewai_custom_tools/src/crewai_custom_tools/tools/genealogy/geo/france_ex_communes.py`
- Modify: `crewai_custom_tools/src/crewai_custom_tools/tools/genealogy/geo/france.py` (extraction du filtre partagé)
- Modify: `crewai_custom_tools/tests/test_genealogy_geo_france_ex_communes.py`

**Interfaces:**
- Consumes: `wikidata_ex_commune(insee) -> ExCommuneFacts | None` (Task 2) ; `map_commune(payload, parsed) -> ResolvedPlace` et `_norm(s) -> str` (existants).
- Produces:
  - `pick_exact_by_name(results: list, parsed: ParsedPlace) -> list` — dans `france.py`, extrait de `_resolve_fr_by_name` sans changement de comportement, désormais partagé par les deux résolveurs.
  - `resolve_fr_ex_commune(parsed: ParsedPlace) -> ResolvedPlace | None` — la signature attendue par le registre (Task 4).

- [ ] **Step 1: Écrire les tests qui échouent**

Ajouter à la fin de `tests/test_genealogy_geo_france_ex_communes.py` :

```python
from crewai_custom_tools.tools.genealogy.models.domain import ParsedPlace

# Réponse réelle de /communes_associees_deleguees?nom=…
_ASSOCIEE = {
    "nom": "Saint-Agnant-sous-les-Côtes", "code": "55451",
    "type": "commune-associee", "chefLieu": "55012",
    "centre": {"type": "Point", "coordinates": [5.6317, 48.8427]},   # [lon, lat]
    "departement": {"code": "55", "nom": "Meuse"},
    "region": {"code": "44", "nom": "Grand Est"},
}
# Réponse réelle de /communes/55012
_CHEF_LIEU = {
    "nom": "Apremont-la-Forêt", "code": "55012",
    "centre": {"type": "Point", "coordinates": [5.6207, 48.8467]},
    "departement": {"code": "55", "nom": "Meuse"},
    "region": {"code": "44", "nom": "Grand Est"},
}

_PARSED = ParsedPlace(
    raw=", , , Saint-Agnant-sous-les-Côtes, 55012, Meuse, Grand Est, France",
    commune="Saint-Agnant-sous-les-Côtes", postal="55012",
    departement="Meuse", region="Grand Est", country="France", shifted=True)


def _fake_api(associees, chef=_CHEF_LIEU):
    """Route les deux appels HTTP du résolveur sur des payloads figés."""
    def fake_get(path, params):
        if path == "/communes_associees_deleguees":
            return associees
        assert path == "/communes/55012", path
        return chef
    return fake_get


def _facts(**kw):
    defaults = {"dissolved": "1972-12-31", "successor_insee": "55012",
                "lat": "48.842142", "long": "5.622588"}
    return fec.ExCommuneFacts(**{**defaults, **kw})


def test_resolve_ex_commune_emits_two_dated_chains(monkeypatch):
    monkeypatch.setattr(fec, "_http_get", _fake_api([_ASSOCIEE]))
    monkeypatch.setattr(fec, "wikidata_ex_commune", lambda insee: _facts())
    rp = fec.resolve_fr_ex_commune(_PARSED)

    assert rp is not None
    assert rp.name == "Saint-Agnant-sous-les-Côtes"
    assert rp.place_type == "Municipality"
    assert rp.code == "55451"                       # son code propre, PAS 55012
    assert rp.score == 1.0 and rp.ambiguous is False
    # GPS Wikidata (centre du bourg), pas le centroïde de l'API
    assert rp.lat == "48.842142" and rp.long == "5.622588"

    assert len(rp.chains) == 2
    historique, moderne = rp.chains[0], rp.chains[1]
    assert historique.date_qualifier == "avant 1972-12-31"
    assert [lvl.name for lvl in historique.levels] == ["France", "Grand Est", "Meuse"]
    assert moderne.date_qualifier == "après 1972-12-31"
    assert [lvl.name for lvl in moderne.levels] == [
        "France", "Grand Est", "Meuse", "Apremont-la-Forêt"]
    assert moderne.levels[-1].code == "55012"
    assert moderne.levels[-1].place_type == "Municipality"
    assert rp.alt_names[0].value == _PARSED.raw


def test_resolve_ex_commune_successor_mismatch_degrades_to_single_chain(monkeypatch):
    # Wikidata désigne un autre successeur que le chefLieu de l'API : discordance.
    monkeypatch.setattr(fec, "_http_get", _fake_api([_ASSOCIEE]))
    monkeypatch.setattr(fec, "wikidata_ex_commune",
                        lambda insee: _facts(successor_insee="55999"))
    rp = fec.resolve_fr_ex_commune(_PARSED)

    assert rp is not None
    assert len(rp.chains) == 1
    assert rp.chains[0].date_qualifier is None      # aucune date inventée
    assert [lvl.name for lvl in rp.chains[0].levels] == [
        "France", "Grand Est", "Meuse", "Apremont-la-Forêt"]


def test_resolve_ex_commune_without_dissolution_date_is_undated(monkeypatch):
    monkeypatch.setattr(fec, "_http_get", _fake_api([_ASSOCIEE]))
    monkeypatch.setattr(fec, "wikidata_ex_commune", lambda insee: _facts(dissolved=None))
    rp = fec.resolve_fr_ex_commune(_PARSED)
    assert rp is not None and len(rp.chains) == 1
    assert rp.chains[0].date_qualifier is None


def test_resolve_ex_commune_without_wikidata_falls_back_to_api_gps(monkeypatch):
    monkeypatch.setattr(fec, "_http_get", _fake_api([_ASSOCIEE]))
    monkeypatch.setattr(fec, "wikidata_ex_commune", lambda insee: None)
    rp = fec.resolve_fr_ex_commune(_PARSED)
    assert rp is not None and len(rp.chains) == 1
    assert rp.lat == "48.8427" and rp.long == "5.6317"   # centre GeoJSON [lon, lat]


def test_resolve_ex_commune_no_match_is_none(monkeypatch):
    monkeypatch.setattr(fec, "_http_get", _fake_api([]))
    monkeypatch.setattr(fec, "wikidata_ex_commune", lambda insee: _facts())
    assert fec.resolve_fr_ex_commune(_PARSED) is None


def test_resolve_ex_commune_fuzzy_nonexact_is_none(monkeypatch):
    # La recherche par nom de l'API est floue : un quasi-homonyme ne compte pas.
    autre = {**_ASSOCIEE, "nom": "Saint-Agnant-près-Crocq", "code": "23999"}
    monkeypatch.setattr(fec, "_http_get", _fake_api([autre]))
    monkeypatch.setattr(fec, "wikidata_ex_commune", lambda insee: _facts())
    assert fec.resolve_fr_ex_commune(_PARSED) is None


def test_resolve_ex_commune_homonyms_are_ambiguous(monkeypatch):
    jumeau = {**_ASSOCIEE, "code": "88888",
              "departement": {"code": "88", "nom": "Vosges"}}
    monkeypatch.setattr(fec, "_http_get", _fake_api([_ASSOCIEE, jumeau]))
    monkeypatch.setattr(fec, "wikidata_ex_commune", lambda insee: _facts())
    sans_contexte = _PARSED.model_copy(update={"departement": "", "region": ""})
    rp = fec.resolve_fr_ex_commune(sans_contexte)
    assert rp is not None and rp.ambiguous is True


def test_resolve_ex_commune_department_disambiguates(monkeypatch):
    jumeau = {**_ASSOCIEE, "code": "88888",
              "departement": {"code": "88", "nom": "Vosges"}}
    monkeypatch.setattr(fec, "_http_get", _fake_api([jumeau, _ASSOCIEE]))
    monkeypatch.setattr(fec, "wikidata_ex_commune", lambda insee: _facts())
    rp = fec.resolve_fr_ex_commune(_PARSED)          # departement="Meuse"
    assert rp is not None and rp.ambiguous is False and rp.code == "55451"


def test_resolve_ex_commune_without_commune_is_none():
    assert fec.resolve_fr_ex_commune(ParsedPlace(raw="", commune="", country="France")) is None
```

- [ ] **Step 2: Lancer les tests, vérifier qu'ils échouent**

```bash
cd /Users/fjacquet/Projects/crewai_custom_tools
uv run python -m pytest tests/test_genealogy_geo_france_ex_communes.py -v
```

Attendu : les 9 nouveaux tests `FAILED` (`module ... has no attribute '_http_get'` / `'resolve_fr_ex_commune'`), les 10 de la Task 2 toujours `passed`.

- [ ] **Step 3: Extraire le filtre de nom exact dans `france.py`**

Les deux résolveurs ont besoin du même filtre. Plutôt que de le dupliquer, on le sort de
`_resolve_fr_by_name`, **sans en changer le comportement** — la clause sur le code de
département est verrouillée par
`test_resolve_fr_by_name_region_only_context_does_not_collapse_homonyms`, elle doit survivre
telle quelle.

Dans `geo/france.py`, ajouter cette fonction avant `_resolve_fr_by_name` :

```python
def pick_exact_by_name(results: list, parsed: ParsedPlace) -> list:
    """Ne garder que les correspondances de nom EXACTES, désambiguïsées par contexte.

    La recherche `nom` de geo.api.gouv.fr est floue : un quasi-homonyme ne doit
    jamais passer pour une résolution. Partagé par le résolveur des communes
    vivantes et par celui des ex-communes, qui interrogent deux endpoints au
    format identique.
    """
    exact = [c for c in results if _norm(c.get("nom", "")) == _norm(parsed.commune)]
    ctx = _norm(parsed.departement) or _norm(parsed.region)
    if ctx and len(exact) > 1:
        filtered = [c for c in exact
                    if ctx in (_norm((c.get("departement") or {}).get("nom", "")),
                               _norm((c.get("region") or {}).get("nom", "")))
                    or (bool(parsed.departement)
                        and (c.get("departement") or {}).get("code", "") == parsed.departement)]
        if filtered:
            exact = filtered
    return exact
```

puis, dans `_resolve_fr_by_name`, remplacer les lignes qui calculaient `exact` (de
`exact = [c for c in results ...]` jusqu'au `if filtered: exact = filtered` inclus) par :

```python
    exact = pick_exact_by_name(results, parsed)
```

Lancer immédiatement la suite France pour prouver que l'extraction est neutre :

```bash
cd /Users/fjacquet/Projects/crewai_custom_tools
uv run python -m pytest tests/test_genealogy_geo_france.py -v
```

Attendu : les 7 tests passent, **inchangés**. Si l'un tombe, l'extraction a modifié le
comportement — corriger avant de continuer.

- [ ] **Step 4: Implémenter le résolveur**

Dans `france_ex_communes.py`, remplacer le bloc d'imports par :

```python
from __future__ import annotations

import re

import httpx
from pydantic import BaseModel

from crewai_custom_tools.core.rate_limiter import get_rate_limiter
from crewai_custom_tools.tools.genealogy.geo.france import _FIELDS as _COMMUNE_FIELDS
from crewai_custom_tools.tools.genealogy.geo.france import map_commune, pick_exact_by_name
from crewai_custom_tools.tools.genealogy.models.domain import (
    DatedChain, DatedName, ParsedPlace, PlaceLevel, ResolvedPlace,
)
from crewai_custom_tools.tools.web.wikidata import sparql_rows
```

Puis ajouter, après `wikidata_ex_commune` :

```python
_BASE = "https://geo.api.gouv.fr"
_ASSOCIEE_FIELDS = "nom,code,type,chefLieu,centre,departement,region"
_PROVIDER = "GeoApiGouvFr"


def _http_get(path: str, params: dict):
    """Thin HTTP GET (monkeypatché dans les tests). WGS84 GeoJSON en sortie."""
    get_rate_limiter().acquire(_PROVIDER)
    resp = httpx.get(f"{_BASE}{path}", params=params, timeout=15.0)
    resp.raise_for_status()
    return resp.json()


def resolve_fr_ex_commune(parsed: ParsedPlace) -> ResolvedPlace | None:
    """Résout une commune française fusionnée (associée/déléguée).

    Deux chaînes datées quand geo.api.gouv.fr et Wikidata s'accordent sur le
    successeur ; sinon une seule chaîne non datée — jamais de date inventée.
    """
    if not parsed.commune:
        return None
    results = _http_get("/communes_associees_deleguees",
                        {"nom": parsed.commune, "fields": _ASSOCIEE_FIELDS, "limit": 10})
    if not isinstance(results, list) or not results:
        return None
    exact = pick_exact_by_name(results, parsed)
    if not exact:
        return None                                  # repli Nominatim côté registre
    ex = exact[0]
    chef_code = ex.get("chefLieu")
    if not chef_code:
        return None
    chef = _http_get(f"/communes/{chef_code}", {"fields": _COMMUNE_FIELDS})
    if not isinstance(chef, dict) or "centre" not in chef:
        return None
    # map_commune est réutilisé pour la hiérarchie France>Région>Département, déjà testée.
    modern = map_commune(chef, parsed)
    parents = list(modern.chains[0].levels)
    chef_level = PlaceLevel(name=modern.name, place_type="Municipality", code=modern.code)

    facts = wikidata_ex_commune(ex["code"])
    # Garde de recoupement : on ne date que si les DEUX sources désignent le même
    # successeur. Une date de fusion fausse route silencieusement les événements
    # vers la mauvaise branche — pire qu'une date absente.
    concordant = (facts is not None and facts.dissolved
                  and facts.successor_insee == chef_code)
    if concordant:
        chains = [
            DatedChain(levels=parents, date_qualifier=f"avant {facts.dissolved}"),
            DatedChain(levels=parents + [chef_level],
                       date_qualifier=f"après {facts.dissolved}"),
        ]
        source = "geo.api.gouv.fr/communes_associees_deleguees + Wikidata"
    else:
        chains = [DatedChain(levels=parents + [chef_level])]
        source = "geo.api.gouv.fr/communes_associees_deleguees"

    # GPS : Wikidata (centre du bourg) de préférence au `centre` de l'API, qui est le
    # centroïde du territoire — mesuré à ~700 m du village sur Saint-Agnant. En
    # généalogie on veut l'église, pas le barycentre cadastral. Exception assumée à
    # map_commune, qui prend toujours le centre de l'API pour les communes vivantes.
    lon, lat = (ex.get("centre") or {}).get("coordinates", [None, None])
    if facts is not None and facts.lat and facts.long:
        lat, lon = facts.lat, facts.long

    resolved = ResolvedPlace(
        name=ex["nom"], place_type="Municipality",
        lat=str(lat) if lat is not None else None,
        long=str(lon) if lon is not None else None,
        code=ex["code"], chains=chains,
        alt_names=[DatedName(value=parsed.raw)],
        score=1.0, source=source,
        query=f"/communes_associees_deleguees?nom={parsed.commune}",
    )
    if len(exact) > 1:
        resolved.ambiguous = True                    # vrais homonymes -> proposition
        resolved.source = f"{source} ({len(exact)} homonymes)"
    return resolved
```

- [ ] **Step 5: Lancer les tests, vérifier qu'ils passent**

```bash
cd /Users/fjacquet/Projects/crewai_custom_tools
uv run python -m pytest tests/test_genealogy_geo_france_ex_communes.py -v
```

Attendu : `19 passed`.

- [ ] **Step 6: Commit**

```bash
cd /Users/fjacquet/Projects/crewai_custom_tools
git add src/crewai_custom_tools/tools/genealogy/geo/france_ex_communes.py \
        src/crewai_custom_tools/tools/genealogy/geo/france.py \
        tests/test_genealogy_geo_france_ex_communes.py
git commit -m "feat(geo): resolve_fr_ex_commune, deux placerefs datées

/communes_associees_deleguees pour le rattachement et le code INSEE propre,
Wikidata pour la date de dissolution. Deux chaînes datées seulement si les
deux sources concordent sur le successeur ; sinon chaîne unique non datée.
GPS Wikidata (bourg) préféré au centroïde de l'API, ~700 m d'écart mesuré."
```

---

### Task 4 : Branchement dans le registre

**Files:**
- Modify: `crewai_custom_tools/src/crewai_custom_tools/tools/genealogy/geo/registry.py:15-19`
- Modify: `crewai_custom_tools/tests/test_genealogy_geo_registry.py`

**Interfaces:**
- Consumes: `resolve_fr_ex_commune(parsed)` (Task 3).
- Produces: rien de nouveau — `resolve_place` garde sa signature.

- [ ] **Step 1: Écrire les tests qui échouent**

Ajouter à `tests/test_genealogy_geo_registry.py` :

```python
def test_registry_falls_through_to_ex_commune_when_resolve_fr_none(monkeypatch):
    from crewai_custom_tools.tools.genealogy.geo import registry
    from crewai_custom_tools.tools.genealogy.models.domain import (
        DatedChain, ParsedPlace, PlaceLevel, ResolvedPlace)

    france = PlaceLevel(name="France", place_type="Country")
    sentinel = ResolvedPlace(
        name="Saint-Agnant-sous-les-Côtes", place_type="Municipality", code="55451",
        chains=[DatedChain(levels=[france], date_qualifier="avant 1972-12-31"),
                DatedChain(levels=[france], date_qualifier="après 1972-12-31")],
        score=1.0, source="ex-commune", query="")
    monkeypatch.setattr(registry, "resolve_fr", lambda p: None)
    monkeypatch.setattr(registry, "resolve_fr_ex_commune", lambda p: sentinel)
    monkeypatch.setattr(registry, "resolve_world", lambda p: pytest.fail("Nominatim atteint"))

    got = registry.resolve_place(ParsedPlace(
        raw="", commune="Saint-Agnant-sous-les-Côtes", country="France"))
    assert got is not None and got.code == "55451"
    # resolve_place applique apply_transition en sortie. transitions.csv ne contient
    # aucune ligne dont modern_country == "France" (la France n'y figure que comme
    # historical_parent), donc les deux chaînes datées doivent survivre intactes.
    # Cette assertion est le garde-fou : ajouter une ligne "France" au dataset
    # écraserait silencieusement les rattachements des ex-communes.
    assert [c.date_qualifier for c in got.chains] == ["avant 1972-12-31", "après 1972-12-31"]


def test_registry_live_commune_never_reaches_ex_commune_path(monkeypatch):
    from crewai_custom_tools.tools.genealogy.geo import registry
    from crewai_custom_tools.tools.genealogy.models.domain import (
        DatedChain, ParsedPlace, PlaceLevel, ResolvedPlace)

    bourges = ResolvedPlace(
        name="Bourges", place_type="Municipality", code="18033",
        chains=[DatedChain(levels=[PlaceLevel(name="France", place_type="Country")])],
        score=1.0, source="geo.api.gouv.fr", query="")
    monkeypatch.setattr(registry, "resolve_fr", lambda p: bourges)
    monkeypatch.setattr(registry, "resolve_fr_ex_commune",
                        lambda p: pytest.fail("chemin ex-commune emprunté à tort"))

    got = registry.resolve_place(ParsedPlace(raw="", commune="Bourges", country="France"))
    assert got is not None and got.code == "18033"


def test_registry_ambiguous_live_commune_does_not_fall_through(monkeypatch):
    # Un résultat ambigu est truthy : il ne doit PAS déclencher le repli ex-commune.
    from crewai_custom_tools.tools.genealogy.geo import registry
    from crewai_custom_tools.tools.genealogy.models.domain import (
        DatedChain, ParsedPlace, PlaceLevel, ResolvedPlace)

    ambigu = ResolvedPlace(
        name="Sainte-Marie", place_type="Municipality", code="97418",
        chains=[DatedChain(levels=[PlaceLevel(name="France", place_type="Country")])],
        score=1.0, ambiguous=True, source="geo.api.gouv.fr", query="")
    monkeypatch.setattr(registry, "resolve_fr", lambda p: ambigu)
    monkeypatch.setattr(registry, "resolve_fr_ex_commune",
                        lambda p: pytest.fail("repli sur une résolution ambiguë"))

    got = registry.resolve_place(ParsedPlace(raw="", commune="Sainte-Marie", country="France"))
    assert got is not None and got.ambiguous is True
```

Si `import pytest` manque en tête du fichier, l'ajouter.

- [ ] **Step 2: Lancer les tests, vérifier qu'ils échouent**

```bash
cd /Users/fjacquet/Projects/crewai_custom_tools
uv run python -m pytest tests/test_genealogy_geo_registry.py -v
```

Attendu : `AttributeError: ... has no attribute 'resolve_fr_ex_commune'`.

- [ ] **Step 3: Implémenter**

Dans `geo/registry.py`, ajouter l'import après celui de `france` :

```python
from crewai_custom_tools.tools.genealogy.geo.france_ex_communes import resolve_fr_ex_commune
```

et remplacer l'entrée France de `_BY_COUNTRY` :

```python
_BY_COUNTRY = {
    # Les communes fusionnées sont absentes de /communes : si resolve_fr rend None,
    # on tente /communes_associees_deleguees AVANT le repli Nominatim, qui perdrait
    # la hiérarchie. Le branchement est ici et non dans resolve_fr, parce que
    # france_ex_communes importe map_commune depuis france (sinon : cycle).
    # Nota : un résultat ambigu est truthy -> pas de repli, c'est voulu.
    "France": lambda p: resolve_fr(p) or resolve_fr_ex_commune(p),
    "Suisse": lambda p: resolve_ch(p),
    "Allemagne": lambda p: resolve_de(p),
    "États-Unis": lambda p: resolve_us(p),
}
```

- [ ] **Step 4: Lancer toute la suite de la bibliothèque**

```bash
cd /Users/fjacquet/Projects/crewai_custom_tools
uv run python -m pytest tests/ -q
```

Attendu : tout passe. En particulier `test_genealogy_geo_france.py` et
`test_genealogy_geo_registry.py` — aucune régression sur les communes vivantes.

- [ ] **Step 5: Lint**

```bash
cd /Users/fjacquet/Projects/crewai_custom_tools
uv run ruff check src/crewai_custom_tools/tools/genealogy/geo/ src/crewai_custom_tools/tools/web/wikidata.py
```

Attendu : `All checks passed!`. Corriger le cas échéant.

- [ ] **Step 6: Commit**

```bash
cd /Users/fjacquet/Projects/crewai_custom_tools
git add src/crewai_custom_tools/tools/genealogy/geo/registry.py \
        tests/test_genealogy_geo_registry.py
git commit -m "feat(geo): registre — repli ex-commune avant Nominatim pour la France

Branché par composition dans _BY_COUNTRY plutôt que dans resolve_fr :
france_ex_communes importe map_commune depuis france, l'inverse ferait
un cycle. Un résultat ambigu reste truthy et ne déclenche pas le repli."
```

---

### Task 5 : Vérification de bout en bout contre les vraies API

**Files:** aucun (vérification manuelle avant de livrer la bibliothèque).

Les tests sont offline : rien ne prouve encore que les payloads figés correspondent aux API
réelles. Cette task est le contrôle qui manque.

- [ ] **Step 1: Résoudre Saint-Agnant en direct**

```bash
cd /Users/fjacquet/Projects/crewai_custom_tools
uv run python -c "
from crewai_custom_tools.tools.genealogy.geo.registry import resolve_place, decide_action
from crewai_custom_tools.tools.genealogy.standardize.places import parse_pname
p = parse_pname(', , , Saint-Agnant-sous-les-Côtes, 55012, Meuse, Grand Est, France')
r = resolve_place(p)
print('action :', decide_action(r, 0.90))
print('nom    :', r.name, '| code :', r.code, '| GPS :', r.lat, r.long)
print('source :', r.source)
for c in r.chains:
    print('  chaîne', c.date_qualifier, '->', [l.name for l in c.levels])
"
```

Attendu **exactement** :

```
action : ecrire
nom    : Saint-Agnant-sous-les-Côtes | code : 55451 | GPS : 48.842142 5.622588
source : geo.api.gouv.fr/communes_associees_deleguees + Wikidata
  chaîne avant 1972-12-31 -> ['France', 'Grand Est', 'Meuse']
  chaîne après 1972-12-31 -> ['France', 'Grand Est', 'Meuse', 'Apremont-la-Forêt']
```

Si l'action n'est pas `ecrire`, ou si les chaînes ne sont pas deux, **ne pas continuer** :
signaler l'écart, il invalide un payload de test.

- [ ] **Step 2: Vérifier la non-régression sur une commune vivante**

```bash
cd /Users/fjacquet/Projects/crewai_custom_tools
uv run python -c "
from crewai_custom_tools.tools.genealogy.geo.registry import resolve_place
from crewai_custom_tools.tools.genealogy.standardize.places import parse_pname
r = resolve_place(parse_pname('Bourges, Cher, Centre-Val de Loire, France'))
print(r.name, r.code, r.source, len(r.chains))
"
```

Attendu : `Bourges 18033 geo.api.gouv.fr 1` — une seule chaîne, source inchangée.

- [ ] **Step 3: Bump de version et commit**

Dans `crewai_custom_tools/pyproject.toml`, ligne 7 : `version = "0.18.0"` → `version = "0.19.0"`.

```bash
cd /Users/fjacquet/Projects/crewai_custom_tools
git add pyproject.toml
git commit -m "chore: version 0.19.0 — résolveur des ex-communes françaises"
```

---

### Task 6 : Scope `place:<ID>` côté genecrew

**Files:**
- Modify: `genecrew/src/genecrew/scope.py:10-18` (`parse_scope`) et `:21-44` (`resolve_handles`)
- Modify: `genecrew/src/genecrew/batching.py:37-56` (`iter_places`)
- Test: `genecrew/tests/test_scope.py`, `genecrew/tests/test_places_batching.py`

**Interfaces:**
- Produces: `parse_scope("place:P0080") == ("place", "P0080")` ; `iter_places(client, "place:P0080", batch_size, limit)` rend un lot unique.

- [ ] **Step 1: Synchroniser la bibliothèque**

```bash
cd /Users/fjacquet/Projects/genecrew
uv sync
uv run python -c "import crewai_custom_tools, importlib.metadata as m; print(m.version('crewai-custom-tools'))"
```

Attendu : `0.19.0`. Sinon la Task 5 n'a pas été commitée.

- [ ] **Step 2: Écrire les tests qui échouent**

Ajouter à `genecrew/tests/test_scope.py` :

```python
def test_parse_scope_accepts_place():
    assert parse_scope("place:P0080") == ("place", "P0080")


def test_resolve_handles_rejects_place_scope():
    # parse_scope est partagé ; sans garde explicite, "place:" retomberait sur la
    # branche "all" et paginerait TOUTES les personnes en silence.
    client = GrampsClient(CONFIG, transport=httpx.MockTransport(
        lambda request: httpx.Response(200, json={"access_token": "t"})))
    with pytest.raises(NotImplementedError):
        resolve_handles(client, "place:P0080")
```

Ajouter à `genecrew/tests/test_places_batching.py` :

```python
def test_iter_places_place_scope_fetches_single_place():
    import httpx
    from crewai_custom_tools.tools.genealogy.gramps.client import GrampsClient, GrampsConfig
    from genecrew.batching import iter_places

    def handler(request):
        if request.url.path == "/api/token/":
            return httpx.Response(200, json={"access_token": "t"})
        assert request.url.path == "/api/places/"
        assert request.url.params["gramps_id"] == "P0080"
        return httpx.Response(200, json=[{"handle": "h80", "gramps_id": "P0080"}])

    client = GrampsClient(
        GrampsConfig(api_url="http://g.test/api", username="u", password="p"),
        transport=httpx.MockTransport(handler))
    batches = list(iter_places(client, "place:P0080", 25, None))
    assert batches == [[{"handle": "h80", "gramps_id": "P0080"}]]


def test_iter_places_place_scope_unknown_id_yields_nothing():
    import httpx
    from crewai_custom_tools.tools.genealogy.gramps.client import GrampsClient, GrampsConfig
    from genecrew.batching import iter_places

    def handler(request):
        if request.url.path == "/api/token/":
            return httpx.Response(200, json={"access_token": "t"})
        return httpx.Response(200, json=[])

    client = GrampsClient(
        GrampsConfig(api_url="http://g.test/api", username="u", password="p"),
        transport=httpx.MockTransport(handler))
    assert list(iter_places(client, "place:P9999", 25, None)) == []
```

Vérifier que `import pytest` est présent en tête de `test_scope.py` (il l'est déjà).

- [ ] **Step 3: Lancer les tests, vérifier qu'ils échouent**

```bash
cd /Users/fjacquet/Projects/genecrew
uv run python -m pytest genecrew/tests/test_scope.py genecrew/tests/test_places_batching.py -v
```

Attendu : `ValueError: Périmètre invalide : 'place:P0080'`.

- [ ] **Step 4: Implémenter**

Dans `genecrew/src/genecrew/scope.py`, remplacer `parse_scope` :

```python
def parse_scope(spec: str) -> tuple[str, str | None]:
    """Parse 'all' | 'person:<id>' | 'branch:<id>' | 'place:<id>' into (kind, gramps_id)."""
    if spec == "all":
        return ("all", None)
    if ":" in spec:
        kind, _, gid = spec.partition(":")
        if kind in ("person", "branch", "place"):
            return (kind, gid)
    raise ValueError(
        f"Périmètre invalide : {spec!r} "
        "(attendu 'all', 'person:ID', 'branch:ID', 'place:ID')")
```

et, dans `resolve_handles`, insérer juste après `kind, gid = parse_scope(spec)` :

```python
    if kind == "place":
        # parse_scope est partagé avec les lieux ; sans ce refus explicite, "place:"
        # retomberait sur la branche "all" et paginerait toutes les personnes.
        raise NotImplementedError(
            "Le périmètre 'place:' ne s'applique qu'aux lieux, pas aux personnes.")
```

Dans `genecrew/src/genecrew/batching.py`, remplacer le garde-fou de `iter_places` :

```python
    kind, gid = parse_scope(scope)
    if kind == "place":
        places = client.get_json("/places/", params={"gramps_id": gid})
        if places:
            yield places
        return
    if kind != "all":
        raise NotImplementedError(
            f"scope {scope!r} non supporté pour les lieux ; "
            "utilisez --scope all ou --scope place:<ID>")
```

- [ ] **Step 5: Lancer les tests, vérifier qu'ils passent**

```bash
cd /Users/fjacquet/Projects/genecrew
uv run python -m pytest genecrew/tests/ -q
```

Attendu : toute la suite passe.

- [ ] **Step 6: Lint**

```bash
cd /Users/fjacquet/Projects/genecrew
uv run ruff check .
```

Attendu : `All checks passed!`.

- [ ] **Step 7: Commit**

```bash
cd /Users/fjacquet/Projects/genecrew
git add genecrew/src/genecrew/scope.py genecrew/src/genecrew/batching.py \
        genecrew/tests/test_scope.py genecrew/tests/test_places_batching.py uv.lock
git commit -m "feat(lieux): scope place:<ID> pour cibler un lieu unique

iter_places n'acceptait que --scope all, ce qui interdisait de valider un
correctif de résolveur sur un lieu avant de le lâcher sur l'arbre entier.
resolve_handles refuse explicitement place: — sans quoi il retomberait sur
la branche 'all' et paginerait toutes les personnes en silence."
```

---

### Task 7 : Nettoyage du lieu P0080

**Files:** aucun changement de code. Opération sur les données, sous `--dry-run` d'abord.

**Prérequis :** la pile Gramps Web doit tourner (`cd /Users/fjacquet/Projects/gramps-mcp && docker compose up -d`).

- [ ] **Step 1: Photographier l'état avant**

```bash
cd /Users/fjacquet/Projects/genecrew
uv run python -c "
from crewai_custom_tools.tools.genealogy.gramps.client import get_client
c = get_client()
p = c.get_object('places', '103a536d2f236a148b278ba0230d')
print('nom  :', (p.get('name') or {}).get('value'))
print('type :', p.get('place_type'), '| code :', p.get('code'))
print('GPS  :', p.get('lat'), p.get('long'))
print('refs :', p.get('placeref_list'))
"
```

Attendu : le titre plat, `place_type` `Unknown`, aucun placeref. Conserver cette sortie —
c'est le point de comparaison.

- [ ] **Step 2: Simuler l'application**

```bash
cd /Users/fjacquet/Projects/genecrew
uv run genecrew apply places --scope place:P0080 --dry-run
```

Lire le rapport produit sous `output/lieux/`. Vérifier :
- `Mode : simulation (dry-run, aucune écriture)` ;
- `Lieux écrits : 1` ;
- la ligne du tableau porte `Saint-Agnant-sous-les-Côtes`, `Municipality`,
  GPS `48.842142,5.622588` ;
- `Erreurs : 0`.

Si le lieu ressort en proposition plutôt qu'en écriture, **s'arrêter** et remonter le rapport.

- [ ] **Step 3: Appliquer pour de vrai**

`GENECREW_DRY_RUN` vaut `false` dans `.env` — sans quoi l'écriture serait simulée malgré
l'absence de `--dry-run`. Le vérifier avant de lancer :

```bash
cd /Users/fjacquet/Projects/genecrew
grep GENECREW_DRY_RUN .env
uv run genecrew apply places --scope place:P0080
```

Le rapport doit annoncer `Mode : écritures appliquées`.

- [ ] **Step 4: Vérifier le résultat dans l'arbre**

```bash
cd /Users/fjacquet/Projects/genecrew
uv run python -c "
from crewai_custom_tools.tools.genealogy.gramps.client import get_client
c = get_client()
p = c.get_object('places', '103a536d2f236a148b278ba0230d')
print('nom  :', (p.get('name') or {}).get('value'))
print('type :', p.get('place_type'), '| code :', p.get('code'))
print('GPS  :', p.get('lat'), p.get('long'))
for r in p.get('placeref_list') or []:
    parent = c.get_object('places', r['ref'])
    print('  ->', (parent.get('name') or {}).get('value'), '| date :', r.get('date'))
print('alt  :', [a.get('value') for a in p.get('alt_names') or []])
"
```

Attendu :
- nom `Saint-Agnant-sous-les-Côtes`, type `Municipality`, code **`55451`** (plus `55012`) ;
- GPS `48.842142 / 5.622588` ;
- **deux** placerefs : l'une vers `Meuse` avec une `date` de modifier « avant », l'autre vers
  `Apremont-la-Forêt` avec un modifier « après », toutes deux au 31/12/1972 ;
- l'ancien titre plat présent dans `alt_names`.

- [ ] **Step 5: Vérifier que l'événement de décès est intact**

C'est le contrôle qui compte : l'opération est un enrichissement sur place, elle ne doit
avoir bougé aucun rattachement.

```bash
cd /Users/fjacquet/Projects/genecrew
uv run python -c "
from crewai_custom_tools.tools.genealogy.gramps.client import get_client
c = get_client()
e = c.get_json('/events/', params={'gramps_id': 'E1820'})[0]
print('event :', e['gramps_id'], '| place :', e.get('place'))
print('rattaché au bon lieu :', e.get('place') == '103a536d2f236a148b278ba0230d')
print('citations :', e.get('citation_list'))
print('notes     :', e.get('note_list'))
"
```

Attendu : `rattaché au bon lieu : True`, la citation `C1789` et la note `N0088` toujours
présentes (listes non vides).

- [ ] **Step 6: Commit du rapport**

```bash
cd /Users/fjacquet/Projects/genecrew
git add output/lieux/
git commit -m "chore(lieux): rapport — P0080 Saint-Agnant structuré

Premier lieu de l'arbre doté d'une hiérarchie complète et de placerefs
datées. Code INSEE corrigé (55012 -> 55451), GPS posé, E1820 (décès
Kléber Soulat 1914) intact."
```

Si `output/` est gitignoré, sauter ce commit et le signaler.

---

## Suite possible (hors périmètre de ce plan)

Le scope `place:` a servi à valider sur un cas. Élargir aux autres lieux plats de l'arbre est
une décision distincte, à prendre en lisant un `apply places --scope all --dry-run` — pas un
automatisme.
