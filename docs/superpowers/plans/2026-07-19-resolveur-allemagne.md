# Résolveur Allemagne autoritaire — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: normalement superpowers:subagent-driven-development
> ou superpowers:executing-plans. **Ici : exécution INLINE directe** (limite de 200 subagents
> atteinte dans la session). Steps en cases `- [ ]`.

**Goal:** résoudre les lieux allemands de façon autoritaire (AGS + coordonnées officielles BKG)
au lieu du repli Nominatim, qui choisit parfois le mauvais homonyme (Waldeck en Thuringe au lieu
de la Hesse).

**Architecture:** un gazetteer allemand embarqué (OpenDataSoft `georef-germany-gemeinde`, dérivé
du VG250 officiel du BKG), indexé par AGS et par (nom, Land) ; le parser reconnaît l'AGS 8
chiffres comme code autoritaire ; le résolveur calque le Census US + France-par-nom.

**Tech Stack:** Python 3, `uv`, `csv`/`httpx` (build script), pytest, Pydantic (`domain.py`),
OpenDataSoft v2.1 export API.

**Spec:** `docs/superpowers/specs/2026-07-19-resolveur-allemagne-design.md`

## Global Constraints

- Tout dans `crewai_custom_tools/src/crewai_custom_tools/tools/genealogy/` (+ `scripts/`). Aucun
  changement de contrat d'écriture ni d'API `genecrew`.
- **AGS 8 chiffres** = code autoritaire allemand (distinct de l'INSEE/postal 5 chiffres) ; dérivé
  de l'ARS 12 chiffres par `ars[:5] + ars[-3:]`. Préfixe 2 chiffres = Land.
- **Politique miroir France** : AGS présent → autoritaire ; nom+Land unique → autoritaire ; >1 →
  proposition (`ambiguous=True`) ; 0 → `None` (repli registre).
- **Normalisation allemande** : expanser `ß→ss`, `ä/ö/ü→ae/oe/ue` **avant** le strip d'accents.
  Les Länder ont des alias FR/EN (« Hesse »↔« Hessen ») → canoniser avant comparaison.
- **GPS** : le gazetteer donne `geo_point_2d = {lat, lon}` WGS84 → `ResolvedPlace.lat=<lat>`,
  `long=<lon>`. Pas d'inversion (ce n'est pas du GeoJSON `[lon,lat]`).
- Tests **par classe**, hors-ligne, gazetteer injecté via `table=`.
- Lancer : `cd /Users/fjacquet/Projects/crewai_custom_tools && uv run python -m pytest ...`.
- Modèles (`ParsedPlace`) : ne modifier que pour AJOUTER le champ `ags`.

---

### Task 1 : Parser reconnaît l'AGS 8 chiffres (+ `ParsedPlace.ags`)

**Files:**

- Modify: `src/crewai_custom_tools/tools/genealogy/models/domain.py` (ParsedPlace)
- Modify: `src/crewai_custom_tools/tools/genealogy/standardize/places.py`
- Test: `tests/test_genealogy_places_parse.py`

**Interfaces produites:** `ParsedPlace.ags: str | None` ; `parse_pname` remplit `ags` sur un
segment de 8 chiffres et l'exclut du tail (le Land n'est plus perdu).

- [ ] **Step 1 — tests (RED)** — ajouter à `tests/test_genealogy_places_parse.py` :

```python
def test_parse_recognizes_ags_8_digit_and_keeps_land():
    from crewai_custom_tools.tools.genealogy.standardize.places import parse_pname
    p = parse_pname(", Waldeck, 06635021, 34513, Regierungsbezirk Kassel, Hesse, Germany")
    assert p.ags == "06635021"
    assert p.commune == "Waldeck"
    assert p.country == "Allemagne"
    assert p.region == "Hesse"           # Land récupéré (plus perdu par le tail)
    assert p.postal == "34513"

def test_parse_no_ags_when_no_8_digit_segment():
    from crewai_custom_tools.tools.genealogy.standardize.places import parse_pname
    p = parse_pname("Bourges, 18033, 18000, Cher, France")
    assert p.ags is None                 # non-régression: 5 chiffres reste INSEE/postal
    assert p.insee == "18033"
```

- [ ] **Step 2 — run RED**
`uv run python -m pytest tests/test_genealogy_places_parse.py -q -k ags`
Attendu : FAIL (`ParsedPlace` n'a pas `ags` / `AttributeError`).

- [ ] **Step 3 — implémenter**

`models/domain.py`, dans `ParsedPlace`, ajouter le champ (après `insee`/`postal`) :

```python
    ags: str | None = None
```

`standardize/places.py` : ajouter la regex (près des autres) :

```python
AGS_RE = re.compile(r"^\d{8}$")             # Amtlicher Gemeindeschlüssel (Allemagne)
```

Dans `parse_pname`, après la détection `postal_idx`/`postal`, ajouter :

```python
    ags_idx = next((i for i, s in enumerate(segments) if AGS_RE.match(s)), None)
    ags = segments[ags_idx] if ags_idx is not None else None
```

Ajouter `ags_idx` à l'ensemble `used` (pour exclure l'AGS du tail) :

```python
    used = {country_idx, insee_idx, postal_idx, commune_idx, ags_idx}
```

Et passer `ags=ags` au `return ParsedPlace(...)`.

- [ ] **Step 4 — run GREEN**
`uv run python -m pytest tests/test_genealogy_places_parse.py -q` → PASS (nouveaux + existants).

- [ ] **Step 5 — commit**

```bash
cd /Users/fjacquet/Projects/crewai_custom_tools
git add src/crewai_custom_tools/tools/genealogy/models/domain.py \
        src/crewai_custom_tools/tools/genealogy/standardize/places.py \
        tests/test_genealogy_places_parse.py
git commit -m "feat(genealogy): parse 8-digit AGS as authoritative German code, keep the Land"
```

---

### Task 2 : Gazetteer allemand embarqué + script de provisioning

**Files:**

- Create: `scripts/build_de_gazetteer.py`
- Create: `src/crewai_custom_tools/tools/genealogy/data/de_communes.csv`
- Test: `tests/test_genealogy_geo_allemagne.py` (un test de parsing du build)

**Interfaces produites:** `data/de_communes.csv` colonnes `ags,name,land,lat,long`.

- [ ] **Step 1 — build script** `scripts/build_de_gazetteer.py` (patron `build_us_gazetteer.py`) :

```python
"""Provision the embedded German municipality gazetteer from OpenDataSoft (BKG VG250).

Downloads georef-germany-gemeinde and writes data/de_communes.csv (ags,name,land,lat,long).
Run: uv run python scripts/build_de_gazetteer.py [--local downloaded.csv]
"""
from __future__ import annotations

import argparse
import csv
import io
from pathlib import Path

import httpx

URL = ("https://data.opendatasoft.com/api/explore/v2.1/catalog/datasets/"
       "georef-germany-gemeinde@public/exports/csv?delimiter=%3B&use_labels=false")
OUT = Path(__file__).resolve().parents[1] / \
    "src/crewai_custom_tools/tools/genealogy/data/de_communes.csv"


def _first(v: str) -> str:
    """OpenDataSoft array-ish field -> first value ('[\"Hessen\"]' or 'Hessen' -> 'Hessen')."""
    v = (v or "").strip().strip("[]")
    return v.split(",")[0].strip().strip('"').strip()


def ags_from_ars(ars: str) -> str:
    ars = "".join(ch for ch in ars if ch.isdigit())
    return ars[:5] + ars[-3:] if len(ars) >= 8 else ars


def parse_rows(text: str):
    reader = csv.DictReader(io.StringIO(text), delimiter=";")
    for r in reader:
        ars = _first(r.get("gem_code", ""))
        name = _first(r.get("gem_name_short", "")) or _first(r.get("gem_name", ""))
        land = _first(r.get("lan_name", ""))
        pt = (r.get("geo_point_2d", "") or "").strip()          # "lat,lon"
        if not (ars and name and pt and "," in pt):
            continue
        lat, lon = (x.strip() for x in pt.split(",", 1))
        yield {"ags": ags_from_ars(ars), "name": name, "land": land, "lat": lat, "long": lon}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--local", type=Path, help="parse a local CSV instead of downloading")
    args = ap.parse_args()
    text = args.local.read_text(encoding="utf-8") if args.local else \
        httpx.get(URL, timeout=120.0, follow_redirects=True).raise_for_status().text
    rows = list(parse_rows(text))
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with OUT.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["ags", "name", "land", "lat", "long"])
        w.writeheader(); w.writerows(rows)
    print(f"wrote {OUT} : {len(rows)} communes")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2 — build-parse test (RED→GREEN)** — dans `tests/test_genealogy_geo_allemagne.py` :

```python
def test_build_parse_rows_derives_ags_and_point():
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
    import build_de_gazetteer as b
    sample = ('gem_code;gem_name_short;gem_name;lan_name;geo_point_2d\n'
              '146270060060;["Großenhain"];["Stadt Großenhain"];["Sachsen"];51.3237,13.5230\n')
    rows = list(b.parse_rows(sample))
    assert rows == [{"ags": "14627060", "name": "Großenhain", "land": "Sachsen",
                     "lat": "51.3237", "long": "13.5230"}]
```

Run: `uv run python -m pytest tests/test_genealogy_geo_allemagne.py -q -k build_parse` (RED: module absent → écrire le script → GREEN).

- [ ] **Step 3 — provisionner `data/de_communes.csv`**
`uv run python scripts/build_de_gazetteer.py` → produit le vrai fichier (~11 000 communes). **Si
le sandbox bloque le download** : écrire un placeholder (en-tête + communes réelles couvrant les
lieux Allemagne de l'arbre, dont `06635021,Waldeck,Hessen,51.2049,9.0653`, plus un homonyme
`16062037,Waldeck,Thüringen,50.79,11.29`, `06412000,Frankfurt am Main,Hessen,50.11,8.68`,
`09162000,München,Bayern,48.14,11.58`) et le noter dans le commit.

- [ ] **Step 4 — commit**

```bash
cd /Users/fjacquet/Projects/crewai_custom_tools
git add scripts/build_de_gazetteer.py \
        src/crewai_custom_tools/tools/genealogy/data/de_communes.csv \
        tests/test_genealogy_geo_allemagne.py
git commit -m "feat(genealogy): embedded German municipality gazetteer + build script (BKG VG250)"
```

---

### Task 3 : Résolveur `geo/allemagne.py` + routage registry

**Files:**

- Create: `src/crewai_custom_tools/tools/genealogy/geo/allemagne.py`
- Modify: `src/crewai_custom_tools/tools/genealogy/geo/registry.py`
- Test: `tests/test_genealogy_geo_allemagne.py`

**Interfaces:** consomme `best_similarity` (geo/score.py), `ParsedPlace.ags` (Task 1),
`data/de_communes.csv` (Task 2). Produit `resolve_de(parsed, table=None) -> ResolvedPlace | None`,
`load_de_gazetteer()`, `_norm_de`.

- [ ] **Step 1 — tests (RED)** — `tests/test_genealogy_geo_allemagne.py` :

```python
from crewai_custom_tools.tools.genealogy.models.domain import ParsedPlace

# gazetteer injecté : Waldeck existe en Hesse ET en Thuringe (homonyme)
FIX = {
    "by_ags": {"06635021": {"name": "Waldeck", "land": "Hessen", "ags": "06635021",
                            "lat": "51.2049", "long": "9.0653"}},
    "by_name": {"WALDECK": [
        {"name": "Waldeck", "land": "Hessen", "ags": "06635021", "lat": "51.2049", "long": "9.0653"},
        {"name": "Waldeck", "land": "Thüringen", "ags": "16062037", "lat": "50.79", "long": "11.29"},
    ], "GROSSENHAIN": [
        {"name": "Großenhain", "land": "Sachsen", "ags": "14627060", "lat": "51.32", "long": "13.52"}]},
}

def test_resolve_de_by_ags_is_authoritative():
    from crewai_custom_tools.tools.genealogy.geo.allemagne import resolve_de
    p = ParsedPlace(raw="", commune="Waldeck", country="Allemagne", ags="06635021", region="Hesse")
    rp = resolve_de(p, table=FIX)
    assert rp is not None and rp.score == 1.0 and rp.ambiguous is False
    assert rp.code == "06635021" and rp.lat == "51.2049" and rp.long == "9.0653"
    assert [l.name for l in rp.chains[0].levels] == ["Allemagne", "Hessen"]

def test_resolve_de_homonym_without_land_is_proposition():
    from crewai_custom_tools.tools.genealogy.geo.allemagne import resolve_de
    p = ParsedPlace(raw="", commune="Waldeck", country="Allemagne")
    rp = resolve_de(p, table=FIX)
    assert rp is not None and rp.ambiguous is True     # Waldeck Hesse vs Thuringe

def test_resolve_de_name_plus_land_alias_disambiguates():
    from crewai_custom_tools.tools.genealogy.geo.allemagne import resolve_de
    # 'Hesse' (FR) doit matcher le Land 'Hessen' du gazetteer
    p = ParsedPlace(raw="", commune="Waldeck", country="Allemagne", region="Hesse")
    rp = resolve_de(p, table=FIX)
    assert rp is not None and rp.ambiguous is False and rp.land_ok()  # voir helper ci-dessous

def test_resolve_de_unknown_name_returns_none():
    from crewai_custom_tools.tools.genealogy.geo.allemagne import resolve_de
    p = ParsedPlace(raw="", commune="Nowhere", country="Allemagne")
    assert resolve_de(p, table=FIX) is None

def test_norm_de_umlaut_and_eszett():
    from crewai_custom_tools.tools.genealogy.geo.allemagne import _norm_de
    assert _norm_de("Großenhain") == _norm_de("Grossenhain")
    assert _norm_de("München") == _norm_de("Muenchen")
```

(Remplacer `rp.land_ok()` par une assertion concrète : `assert rp.code == "06635021"` — la
version Hesse, pas Thuringe.)

- [ ] **Step 2 — run RED**
`uv run python -m pytest tests/test_genealogy_geo_allemagne.py -q` → FAIL (module `allemagne` absent).

- [ ] **Step 3 — implémenter** `geo/allemagne.py` :

```python
"""Germany resolver: authoritative AGS / (name, Land) -> embedded BKG VG250 gazetteer."""
from __future__ import annotations

import csv
import unicodedata
from collections import defaultdict
from functools import lru_cache
from pathlib import Path

from crewai_custom_tools.tools.genealogy.models.domain import (
    DatedChain, DatedName, ParsedPlace, PlaceLevel, ResolvedPlace,
)

DATA_PATH = Path(__file__).resolve().parents[1] / "data" / "de_communes.csv"
_SOURCE = "BKG VG250"
_UMLAUT = {"ß": "ss", "ä": "ae", "ö": "oe", "ü": "ue", "Ä": "Ae", "Ö": "Oe", "Ü": "Ue"}


def _norm_de(s: str) -> str:
    """German-aware key: expand ß/umlauts BEFORE stripping accents, then upper/trim."""
    for k, v in _UMLAUT.items():
        s = s.replace(k, v)
    s = "".join(c for c in unicodedata.normalize("NFD", s) if unicodedata.category(c) != "Mn")
    return s.strip().upper()


# Land canon : variantes FR/EN/DE normalisées -> Land allemand normalisé.
_LAND_ALIASES = {
    "Baden-Württemberg": ["Bade-Wurtemberg", "Baden-Wurttemberg"], "Bayern": ["Bavière", "Bavaria"],
    "Berlin": [], "Brandenburg": ["Brandebourg"], "Bremen": ["Brême"], "Hamburg": ["Hambourg"],
    "Hessen": ["Hesse"], "Mecklenburg-Vorpommern": ["Mecklembourg-Poméranie"],
    "Niedersachsen": ["Basse-Saxe", "Lower Saxony"], "Nordrhein-Westfalen": ["Rhénanie-du-Nord-Westphalie"],
    "Rheinland-Pfalz": ["Rhénanie-Palatinat"], "Saarland": ["Sarre"], "Sachsen": ["Saxe", "Saxony"],
    "Sachsen-Anhalt": ["Saxe-Anhalt"], "Schleswig-Holstein": [], "Thüringen": ["Thuringe", "Thuringia"],
}
_LAND_CANON: dict[str, str] = {}
for _canon, _aliases in _LAND_ALIASES.items():
    _LAND_CANON[_norm_de(_canon)] = _norm_de(_canon)
    for _a in _aliases:
        _LAND_CANON[_norm_de(_a)] = _norm_de(_canon)


def _land_canon(s: str) -> str | None:
    return _LAND_CANON.get(_norm_de(s)) if s else None


@lru_cache(maxsize=1)
def load_de_gazetteer(path: Path = DATA_PATH) -> dict:
    by_ags: dict[str, dict] = {}
    by_name: dict[str, list] = defaultdict(list)
    with path.open(encoding="utf-8") as f:
        for row in csv.DictReader(f):
            by_ags[row["ags"]] = row
            by_name[_norm_de(row["name"])].append(row)
    return {"by_ags": by_ags, "by_name": dict(by_name)}


def _build(entry: dict, parsed: ParsedPlace, *, ambiguous: bool) -> ResolvedPlace:
    return ResolvedPlace(
        name=entry["name"], place_type="Municipality",
        lat=str(entry["lat"]), long=str(entry["long"]), code=entry["ags"],
        chains=[DatedChain(levels=[PlaceLevel(name="Allemagne", place_type="Country"),
                                   PlaceLevel(name=entry["land"], place_type="State")])],
        alt_names=[DatedName(value=parsed.raw)],
        score=1.0, ambiguous=ambiguous,
        source=_SOURCE + (f" ({'homonymes'})" if ambiguous else ""), query=entry["ags"],
    )


def resolve_de(parsed: ParsedPlace, table: dict | None = None) -> ResolvedPlace | None:
    """AGS -> authoritative ; (name, Land) unique -> authoritative ; homonyms -> proposition."""
    table = table if table is not None else load_de_gazetteer()
    if parsed.ags and parsed.ags in table["by_ags"]:
        return _build(table["by_ags"][parsed.ags], parsed, ambiguous=False)
    if not parsed.commune:
        return None
    candidates = table["by_name"].get(_norm_de(parsed.commune), [])
    if not candidates:
        return None
    land = next((_land_canon(x) for x in (parsed.region, parsed.departement) if _land_canon(x)), None)
    if land and len(candidates) > 1:
        narrowed = [c for c in candidates if _land_canon(c["land"]) == land]
        if narrowed:
            candidates = narrowed
    return _build(candidates[0], parsed, ambiguous=len(candidates) > 1)
```

`geo/registry.py` : importer et router :

```python
from crewai_custom_tools.tools.genealogy.geo.allemagne import resolve_de
...
_BY_COUNTRY = {
    "France": lambda p: resolve_fr(p),
    "Suisse": lambda p: resolve_ch(p),
    "Allemagne": lambda p: resolve_de(p),
    "États-Unis": lambda p: resolve_us(p),
}
```

- [ ] **Step 4 — run GREEN**
`uv run python -m pytest tests/test_genealogy_geo_allemagne.py tests/test_genealogy_geo_registry.py -q`
→ PASS (registry France/Suisse/US inchangé). Puis suite complète `uv run python -m pytest -q`.
`uv run ruff check` propre sur les fichiers touchés.

- [ ] **Step 5 — commit**

```bash
cd /Users/fjacquet/Projects/crewai_custom_tools
git add src/crewai_custom_tools/tools/genealogy/geo/allemagne.py \
        src/crewai_custom_tools/tools/genealogy/geo/registry.py \
        tests/test_genealogy_geo_allemagne.py
git commit -m "feat(genealogy): authoritative Germany resolver (AGS + name/Land, BKG VG250)"
```

---

## Validation finale

- [ ] Suite cct complète verte + ruff propre.
- [ ] Depuis `genecrew` (dépendance éditable) : `GENECREW_DRY_RUN=true uv run genecrew lieux --scope all`.
  Attendu : les lieux Allemagne passent en autoritaire là où l'AGS ou (nom+Land) le permet —
  en particulier **Waldeck + `06635021` → Waldeck (Hessen), GPS ~51.20/9.06** (source BKG VG250,
  action `ecrire`), et non plus le mauvais Waldeck de Thuringe via Nominatim. Un « Waldeck » nu
  reste proposition (homonyme). Comparer le nb de lignes `| Allemagne | ecrire | … | BKG VG250 |`
  avant (0) / après.

## Self-Review (auteur)

- **Couverture spec** : §1 données → Task 2 ; §2 parser AGS → Task 1 ; §3 résolveur+normalisation
  +registry → Task 3 ; §4 GPS lat/lon → `_build` ; §5 tests+validation → Tasks + validation finale.
  Alias Land (Hesse↔Hessen) traité (`_LAND_CANON`), non explicite dans la spec mais nécessaire —
  ajouté. `ß`/umlaut → `_norm_de`.
- **Types** : `resolve_de(parsed, table=None) -> ResolvedPlace | None`, `_norm_de(str)->str`,
  `ParsedPlace.ags: str | None` cohérents entre Tasks 1 et 3. Registry route `"Allemagne"`.
- **Placeholders** : aucun — code et commandes réels. (Le test Step 1 mentionnant `rp.land_ok()`
  est corrigé en `rp.code == "06635021"` dans la note qui suit.)
