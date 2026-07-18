# Inférence de genre à partir du prénom — Plan d'implémentation

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Proposer un genre (F/M) pour les personnes de genre inconnu — et signaler les contradictions genre/prénom — à partir d'un dictionnaire prénom→sexe INSEE+OFS souverain et hors-ligne, en propositions pour revue humaine (aucune écriture Gramps).

**Architecture:** Fonctions pures dans `crewai_custom_tools` (normalisation de clé, `infer_sex`, chargement de la table CSV embarquée, modèle `Proposition`) + un script de build one-off qui produit le CSV depuis les sources officielles. Orchestration lecture seule dans `genecrew` (`run_gender` + rendus purs Markdown/YAML) réutilisant `scope`/`batching`/`FactsFetcher`. Premier émetteur de propositions du projet.

**Tech Stack:** Python ≥3.11, `uv`, Pydantic v2, `csv`/`unicodedata` (stdlib), PyYAML (déjà présent), pytest + pytest-mock, httpx `MockTransport` pour les tests réseau, hatchling (packaging cct).

## Global Constraints

- **Deux dépôts, deux branches.** cct : branche `feat/genealogy-gender-inference` (base = `main` courant). genecrew : branche `feat/gender-inference` (base = `main` courant). Faire les tâches cct (1–4) **avant** les tâches genecrew (5–8) : genecrew importe cct en éditable (source live), donc le code cct doit exister sur son arbre de travail pendant les tests genecrew.
- **`uv` pour tout Python** — jamais `pip`/`python` directs. Tests cct : `uv run pytest …` depuis `/Users/fjacquet/Projects/crewai_custom_tools`. Tests genecrew : `uv run python -m pytest …` depuis `/Users/fjacquet/Projects/genecrew`.
- **Lecture seule sur Gramps.** Ce chantier n'écrit **jamais** dans Gramps (ni `gender`, ni note, ni tag). La garantie est testée : le handler mocké lève `AssertionError` sur tout `PUT`/`POST` (hors `POST /api/token/`).
- **Le genre est un FAIT** (ADR 0001, forme-vs-fait) → toute inférence devient une `Proposition`, jamais une écriture directe.
- **Politique conservatrice** (valeurs exactes) : proposer un sexe **seulement si** `total = n_f + n_m ≥ 50` **et** `dominant/total ≥ 0.95`. Sinon abstention.
- **Conventions de genre** : Gramps `0=F, 1=M, 2=U` ; `PersonFacts.sex` vaut `"F"|"M"|"U"`. INSEE `SEXE` vaut `1=M, 2=F` (**inverse** — n'intervient QUE dans le script de build).
- **Prénom et sexe déjà disponibles** : `PersonFacts` porte `given` et `sex` (voir `genecrew/src/genecrew/facts.py`) — aucun appel API supplémentaire.
- **Style** : commits Conventional Commits avec scope français (ex. `feat(genealogy): …`), fonctions de rendu **pures** (aucune I/O), docstrings concises comme le code voisin (`report.py`, `names.py`, `rules.py`).

---

## Étape manuelle préalable (humaine, hors subagent) — acquisition des données

Le CSV embarqué `prenoms_sexe.csv` est produit à partir des fichiers officiels, qui doivent être **téléchargés** (réseau + sources souveraines). Les subagents travaillent hors-ligne : **tous les tests automatisés utilisent des fixtures** et n'ont pas besoin du vrai CSV. Le vrai CSV est généré **une fois par l'humain** après la Tâche 3 :

1. Télécharger le fichier national INSEE « Fichier des prénoms » (CSV `;`, colonnes `sexe;preusuel;annais;nombre`) depuis <https://www.insee.fr/fr/statistiques/8595130> ou <https://www.data.gouv.fr/datasets/fichier-des-prenoms-depuis-1900>.
2. Depuis <https://www.bfs.admin.ch/bfs/fr/home/statistiques/population/naissances-deces/prenoms-nouveaux-nes.html> (OFS/BFS), extraire deux CSV simples `;` à colonnes `prenom;nombre` : `ofs_masculin.csv` et `ofs_feminin.csv`.
3. Lancer le script de la Tâche 3 :
   ```bash
   cd /Users/fjacquet/Projects/crewai_custom_tools
   uv run python scripts/build_prenoms_sexe.py \
     --insee nat.csv --ofs-f ofs_feminin.csv --ofs-m ofs_masculin.csv \
     --out src/crewai_custom_tools/tools/genealogy/data/prenoms_sexe.csv
   git add src/crewai_custom_tools/tools/genealogy/data/prenoms_sexe.csv
   git commit -m "data(genealogy): table prenoms_sexe.csv générée (INSEE+OFS)"
   ```

Tant que ce CSV n'existe pas, `genecrew gender` échoue **franchement** (fichier absent, cf. §6 du spec) ; c'est le comportement voulu. La vérification CLI de bout en bout sur données réelles est faite par l'humain après cette étape.

---

## Structure des fichiers

**`crewai_custom_tools`**
- `src/crewai_custom_tools/tools/genealogy/models/domain.py` — **modifier** : ajouter `Proposition`.
- `src/crewai_custom_tools/tools/genealogy/analysis/gender.py` — **créer** : `normkey`, `_first_forename`, `_counts_for`, `GenderInference`, `load_prenoms_table`, `infer_sex`.
- `src/crewai_custom_tools/tools/genealogy/data/README.md` — **créer** : provenance + commande de régénération.
- `src/crewai_custom_tools/tools/genealogy/data/prenoms_sexe.csv` — **généré** (étape manuelle ; non produit par un subagent).
- `scripts/build_prenoms_sexe.py` — **créer** : build one-off (offline, lit des chemins locaux).
- `pyproject.toml`, `src/crewai_custom_tools/__init__.py`, `tests/test_scaffold.py` — **modifier** : bump `0.9.0`→`0.10.0` + inclusion CSV dans le wheel.
- `tests/test_genealogy_gender.py` — **créer** : `Proposition`, `normkey`, `infer_sex`, `load_prenoms_table`.
- `tests/test_build_prenoms_sexe.py` — **créer** : build sur fixtures.

**`genecrew`**
- `genecrew/src/genecrew/gender.py` — **créer** : `render_gender_report`, `render_propositions_yaml`, `_build_proposition`, `run_gender`.
- `genecrew/src/genecrew/main.py` — **modifier** : sous-commande `gender` + `gender_cmd`.
- `genecrew/tests/test_gender.py` — **créer** : rendus + e2e lecture seule.
- `genecrew/tests/test_cli_gender.py` — **créer** : `gender --help`.
- `uv.lock` — **modifier** via `uv sync` (bump 0.10.0).

**Docs**
- `docs/adr/0008-inference-genre-proposition.md` — **créer**.
- `docs/USER_GUIDE.md`, `CLAUDE.md` (genecrew) — **modifier** : section/commande `gender`.

---

## Task 1 : Modèle `Proposition` (cct)

**Files:**
- Modify: `src/crewai_custom_tools/tools/genealogy/models/domain.py`
- Test: `tests/test_genealogy_gender.py`

**Interfaces:**
- Produces: `Proposition(BaseModel)` avec champs `type, gramps_id, handle, personne, champ, valeur_actuelle, valeur_proposee, preuve, confiance, priorite` (tous `str`, `champ` défaut `"gender"`).

- [ ] **Step 1: Écrire le test qui échoue**

Créer `tests/test_genealogy_gender.py` :
```python
"""Tests hors-ligne de l'inférence de genre et du modèle Proposition."""

from crewai_custom_tools.tools.genealogy.models.domain import Proposition


def test_proposition_roundtrip():
    p = Proposition(
        type="genre_inconnu", gramps_id="I0001", handle="h1", personne="Suzanne Martin",
        valeur_actuelle="U", valeur_proposee="F",
        preuve="prénom « SUZANNE » : 99.0% F sur 41230 (INSEE+OFS)",
        confiance="haute", priorite="moyenne",
    )
    assert p.champ == "gender"                      # défaut
    d = p.model_dump()
    assert Proposition(**d) == p                    # round-trip
```

- [ ] **Step 2: Lancer le test — il échoue**

Run: `cd /Users/fjacquet/Projects/crewai_custom_tools && uv run pytest tests/test_genealogy_gender.py -q`
Expected: FAIL (`ImportError: cannot import name 'Proposition'`).

- [ ] **Step 3: Implémenter le modèle**

Ajouter à la fin de `models/domain.py` :
```python
class Proposition(BaseModel):
    """One proposal for human review — a FACT change is never written directly."""

    type: str                       # "genre_inconnu" | "genre_contradiction"
    gramps_id: str
    handle: str
    personne: str                   # nom lisible
    champ: str = "gender"
    valeur_actuelle: str            # "U" | "M" | "F"
    valeur_proposee: str            # "M" | "F"
    preuve: str
    confiance: str                  # "haute" | "moyenne"
    priorite: str                   # "haute" | "moyenne"
```

- [ ] **Step 4: Lancer le test — il passe**

Run: `cd /Users/fjacquet/Projects/crewai_custom_tools && uv run pytest tests/test_genealogy_gender.py -q`
Expected: PASS (1 passed).

- [ ] **Step 5: Commit**

```bash
cd /Users/fjacquet/Projects/crewai_custom_tools
git add src/crewai_custom_tools/tools/genealogy/models/domain.py tests/test_genealogy_gender.py
git commit -m "feat(genealogy): modèle Proposition (premier émetteur de propositions)"
```

---

## Task 2 : Normalisation + inférence pure (cct)

**Files:**
- Create: `src/crewai_custom_tools/tools/genealogy/analysis/gender.py`
- Test: `tests/test_genealogy_gender.py` (étend Task 1)

**Interfaces:**
- Consumes: rien (stdlib + pydantic).
- Produces :
  - `normkey(name: str) -> str` — MAJUSCULES, accents retirés, apostrophes/tirets canoniques.
  - `GenderInference(BaseModel)` : `sex: str|None`, `ratio: float`, `total: int`, `key: str`.
  - `infer_sex(given: str, table: Mapping[str, tuple[int,int]]) -> GenderInference`.
  - `load_prenoms_table(path: Path = DATA_PATH) -> dict[str, tuple[int,int]]` (caché).
  - Constantes `DATA_PATH`, `MIN_TOTAL = 50`, `MIN_RATIO = 0.95`.

- [ ] **Step 1: Écrire les tests qui échouent**

Ajouter à `tests/test_genealogy_gender.py` :
```python
import csv

import pytest

from crewai_custom_tools.tools.genealogy.analysis.gender import (
    GenderInference, infer_sex, load_prenoms_table, normkey,
)

TABLE = {
    "PIERRE": (2, 9998),        # M net
    "SUZANNE": (9990, 10),      # F net
    "DOMINIQUE": (5000, 5000),  # unisexe
    "CAMILLE": (8000, 2000),    # 80% -> sous le seuil
    "RARE": (30, 1),            # volume < 50
    "JEAN-PIERRE": (1, 3000),   # composé présent
    "MARIE": (9990, 10),        # segment de repli
    "JEAN": (5, 9000),          # 1er prénom d'un given multiple
}


@pytest.mark.parametrize("raw, expected", [
    ("josé", "JOSE"),
    ("Jean-Marie", "JEAN-MARIE"),
    ("D’Abbadie", "D'ABBADIE"),         # apostrophe typographique U+2019
    ("saint‑affrique", "SAINT-AFFRIQUE"),  # trait insécable U+2011
    ("  Anne  ", "ANNE"),
])
def test_normkey(raw, expected):
    assert normkey(raw) == expected


@pytest.mark.parametrize("given, sex", [
    ("Pierre", "M"),
    ("Suzanne", "F"),
    ("Dominique", None),        # unisexe -> abstention
    ("Camille", None),          # 80% < 95% -> abstention
    ("Rare", None),             # volume 31 < 50 -> abstention
    ("Jean-Pierre", "M"),       # composé présent
    ("Marie-Antoinette", "F"),  # composé absent -> repli sur MARIE
    ("Jean Baptiste", "M"),     # 1er prénom d'un given multiple
    ("", None),                 # vide
    ("Zzznotfound", None),      # non couvert
])
def test_infer_sex(given, sex):
    assert infer_sex(given, TABLE).sex == sex


def test_infer_sex_details():
    inf = infer_sex("Suzanne", TABLE)
    assert isinstance(inf, GenderInference)
    assert inf.total == 10000 and inf.key == "SUZANNE" and inf.ratio > 0.99
    assert infer_sex("Zzz", TABLE) == GenderInference(sex=None, ratio=0.0, total=0, key="")


def test_load_prenoms_table(tmp_path):
    csv_path = tmp_path / "t.csv"
    with open(csv_path, "w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["prenom", "n_f", "n_m"])
        w.writerow(["SUZANNE", "9990", "10"])
    table = load_prenoms_table(csv_path)
    assert table["SUZANNE"] == (9990, 10)
```

- [ ] **Step 2: Lancer — il échoue**

Run: `cd /Users/fjacquet/Projects/crewai_custom_tools && uv run pytest tests/test_genealogy_gender.py -q`
Expected: FAIL (`ModuleNotFoundError: …analysis.gender`).

- [ ] **Step 3: Implémenter `gender.py`**

Créer `src/crewai_custom_tools/tools/genealogy/analysis/gender.py` :
```python
"""Gender inference from a first name (pure, offline).

For a person of unknown sex, infer F/M from the first forename using an
INSEE+OFS births table. Gender is a FACT, not form: callers emit a Proposition
for human review — this module never writes to Gramps.
"""

from __future__ import annotations

import csv
import unicodedata
from collections.abc import Mapping
from functools import lru_cache
from pathlib import Path

from pydantic import BaseModel

DATA_PATH = Path(__file__).resolve().parents[1] / "data" / "prenoms_sexe.csv"
MIN_TOTAL = 50
MIN_RATIO = 0.95

_APOSTROPHES = "'’ʼ"
_HYPHENS = "-‐‑‒–—"


def normkey(name: str) -> str:
    """Canonical key: uppercase, accents stripped, apostrophes/hyphens canonical.

    Shared by the runtime lookup and the build script so both index names the
    same way (INSEE is already uppercase without accents; OFS keeps accents)."""
    s = name.strip().upper()
    s = "".join(c for c in unicodedata.normalize("NFD", s)
                if unicodedata.category(c) != "Mn")
    for a in _APOSTROPHES:
        s = s.replace(a, "'")
    for h in _HYPHENS:
        s = s.replace(h, "-")
    return s


def _first_forename(given: str) -> str:
    """First forename = first space-separated segment ('Jean Baptiste' -> 'Jean')."""
    parts = given.strip().split(" ")
    return parts[0] if parts and parts[0] else ""


class GenderInference(BaseModel):
    sex: str | None                 # "M" | "F" | None (abstention)
    ratio: float                    # dominant / total (0.0 if total == 0)
    total: int                      # n_f + n_m on the chosen key
    key: str                        # key actually found ("" if none)


@lru_cache(maxsize=1)
def load_prenoms_table(path: Path = DATA_PATH) -> dict[str, tuple[int, int]]:
    """Load {normalized_key: (n_f, n_m)} from the bundled CSV (cached).

    Raises FileNotFoundError if the data file is missing (explicit failure)."""
    table: dict[str, tuple[int, int]] = {}
    with open(path, encoding="utf-8", newline="") as fh:
        for row in csv.DictReader(fh):
            table[row["prenom"]] = (int(row["n_f"]), int(row["n_m"]))
    return table


def _counts_for(given: str, table: Mapping[str, tuple[int, int]]) -> tuple[str, tuple[int, int]]:
    """Whole first forename, then its first hyphen segment; else ('', (0, 0))."""
    key = normkey(_first_forename(given))
    if key in table:
        return key, table[key]
    if "-" in key:
        seg = key.split("-")[0]
        if seg in table:
            return seg, table[seg]
    return "", (0, 0)


def infer_sex(given: str, table: Mapping[str, tuple[int, int]]) -> GenderInference:
    """Infer F/M; abstain (sex=None) unless total >= MIN_TOTAL and ratio >= MIN_RATIO."""
    key, (n_f, n_m) = _counts_for(given, table)
    total = n_f + n_m
    if total == 0:
        return GenderInference(sex=None, ratio=0.0, total=0, key="")
    dominant = "F" if n_f >= n_m else "M"
    ratio = (n_f if dominant == "F" else n_m) / total
    sex = dominant if (total >= MIN_TOTAL and ratio >= MIN_RATIO) else None
    return GenderInference(sex=sex, ratio=ratio, total=total, key=key)
```

- [ ] **Step 4: Lancer — il passe**

Run: `cd /Users/fjacquet/Projects/crewai_custom_tools && uv run pytest tests/test_genealogy_gender.py -q`
Expected: PASS (tous verts).

- [ ] **Step 5: Commit**

```bash
cd /Users/fjacquet/Projects/crewai_custom_tools
git add src/crewai_custom_tools/tools/genealogy/analysis/gender.py tests/test_genealogy_gender.py
git commit -m "feat(genealogy): inférence de sexe pure (normkey, infer_sex, seuils conservateurs)"
```

---

## Task 3 : Script de build `build_prenoms_sexe.py` (cct)

**Files:**
- Create: `scripts/build_prenoms_sexe.py`
- Test: `tests/test_build_prenoms_sexe.py`

**Interfaces:**
- Consumes: `normkey` (Task 2).
- Produces: `build(insee, ofs_f, ofs_m, out) -> Path` — écrit un CSV `prenom,n_f,n_m` trié par clé ; exclut `_PRENOMS_RARES` ; INSEE `sexe==1`→`n_m`, `sexe==2`→`n_f` ; OFS-f→`n_f`, OFS-m→`n_m`.

- [ ] **Step 1: Écrire le test qui échoue**

Créer `tests/test_build_prenoms_sexe.py` :
```python
"""Test hors-ligne du build de la table prénoms (fixtures)."""

import csv

from build_prenoms_sexe import build


def _write(path, text):
    path.write_text(text, encoding="utf-8")


def test_build_merges_insee_and_ofs(tmp_path):
    insee = tmp_path / "nat.csv"
    _write(insee,
           "sexe;preusuel;annais;nombre\n"
           "1;JEAN;1900;100\n"
           "1;JEAN;1901;50\n"
           "2;MARIE;1900;200\n"
           "2;_PRENOMS_RARES;1900;9999\n"
           "1;JOSÉ;1980;30\n")
    ofs_f = tmp_path / "ofs_f.csv"
    _write(ofs_f, "prenom;nombre\nMarie;10\n")
    ofs_m = tmp_path / "ofs_m.csv"
    _write(ofs_m, "prenom;nombre\nJean;5\nUeli;40\n")
    out = tmp_path / "prenoms_sexe.csv"

    build(str(insee), str(ofs_f), str(ofs_m), str(out))

    rows = {r["prenom"]: (int(r["n_f"]), int(r["n_m"]))
            for r in csv.DictReader(open(out, encoding="utf-8"))}
    assert rows["JEAN"] == (0, 155)         # INSEE 150 + OFS-m 5
    assert rows["MARIE"] == (210, 0)        # INSEE 200 + OFS-f 10
    assert rows["JOSE"] == (0, 30)          # accent retiré
    assert rows["UELI"] == (0, 40)
    assert "_PRENOMS_RARES" not in rows     # exclu
```

`scripts/` doit être importable par le test : ajouter une ligne à `[tool.pytest.ini_options]` dans `pyproject.toml` — voir Step 3.

- [ ] **Step 2: Lancer — il échoue**

Run: `cd /Users/fjacquet/Projects/crewai_custom_tools && uv run pytest tests/test_build_prenoms_sexe.py -q`
Expected: FAIL (`ModuleNotFoundError: build_prenoms_sexe`).

- [ ] **Step 3: Implémenter le script + rendre `scripts/` importable**

Créer `scripts/build_prenoms_sexe.py` :
```python
"""Build the bundled prenoms_sexe.csv from INSEE + OFS source files (offline).

Run once, by hand, after downloading the official sources (see
src/crewai_custom_tools/tools/genealogy/data/README.md):

    uv run python scripts/build_prenoms_sexe.py \
        --insee nat.csv --ofs-f ofs_feminin.csv --ofs-m ofs_masculin.csv \
        --out src/crewai_custom_tools/tools/genealogy/data/prenoms_sexe.csv
"""

from __future__ import annotations

import argparse
import csv
from pathlib import Path

from crewai_custom_tools.tools.genealogy.analysis.gender import normkey

RARE = "_PRENOMS_RARES"


def _add(table: dict[str, tuple[int, int]], key: str, n_f: int = 0, n_m: int = 0) -> None:
    f, m = table.get(key, (0, 0))
    table[key] = (f + n_f, m + n_m)


def _read_insee(path: str, table: dict[str, tuple[int, int]]) -> None:
    with open(path, encoding="utf-8", newline="") as fh:
        for row in csv.DictReader(fh, delimiter=";"):
            name = row["preusuel"]
            if name == RARE:
                continue
            key = normkey(name)
            if not key:
                continue
            nombre = int(row["nombre"])
            if row["sexe"] == "1":
                _add(table, key, n_m=nombre)
            elif row["sexe"] == "2":
                _add(table, key, n_f=nombre)


def _read_ofs(path: str, table: dict[str, tuple[int, int]], *, female: bool) -> None:
    with open(path, encoding="utf-8", newline="") as fh:
        for row in csv.DictReader(fh, delimiter=";"):
            key = normkey(row["prenom"])
            if not key:
                continue
            nombre = int(row["nombre"])
            if female:
                _add(table, key, n_f=nombre)
            else:
                _add(table, key, n_m=nombre)


def build(insee: str, ofs_f: str, ofs_m: str, out: str) -> Path:
    table: dict[str, tuple[int, int]] = {}
    _read_insee(insee, table)
    _read_ofs(ofs_f, table, female=True)
    _read_ofs(ofs_m, table, female=False)
    out_path = Path(out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(["prenom", "n_f", "n_m"])
        for key in sorted(table):
            n_f, n_m = table[key]
            writer.writerow([key, n_f, n_m])
    return out_path


def main() -> None:
    ap = argparse.ArgumentParser(description="Build prenoms_sexe.csv (INSEE+OFS)")
    ap.add_argument("--insee", required=True)
    ap.add_argument("--ofs-f", required=True)
    ap.add_argument("--ofs-m", required=True)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    print(f"Écrit : {build(a.insee, a.ofs_f, a.ofs_m, a.out)}")


if __name__ == "__main__":
    main()
```

Modifier `pyproject.toml`, section `[tool.pytest.ini_options]`, pour que `scripts/` soit importable par les tests :
```toml
[tool.pytest.ini_options]
asyncio_mode = "auto"
pythonpath = ["scripts"]
```

- [ ] **Step 4: Lancer — il passe**

Run: `cd /Users/fjacquet/Projects/crewai_custom_tools && uv run pytest tests/test_build_prenoms_sexe.py -q`
Expected: PASS (1 passed).

- [ ] **Step 5: Commit**

```bash
cd /Users/fjacquet/Projects/crewai_custom_tools
git add scripts/build_prenoms_sexe.py tests/test_build_prenoms_sexe.py pyproject.toml
git commit -m "feat(genealogy): script de build de la table prénoms→sexe (INSEE+OFS)"
```

---

## Task 4 : Provenance des données, packaging & bump de version (cct)

**Files:**
- Create: `src/crewai_custom_tools/tools/genealogy/data/README.md`
- Modify: `pyproject.toml`, `src/crewai_custom_tools/__init__.py`, `tests/test_scaffold.py`

**Interfaces:**
- Produces: version `0.10.0` (lockstep pyproject/`__version__`/test) ; inclusion du CSV dans le wheel.

- [ ] **Step 1: Mettre à jour l'assertion de version (test d'abord)**

Modifier `tests/test_scaffold.py` :
```python
import crewai_custom_tools


def test_version():
    assert crewai_custom_tools.__version__ == "0.10.0"
```

- [ ] **Step 2: Lancer — il échoue**

Run: `cd /Users/fjacquet/Projects/crewai_custom_tools && uv run pytest tests/test_scaffold.py -q`
Expected: FAIL (`assert '0.9.0' == '0.10.0'`).

- [ ] **Step 3: Bump version + provenance + packaging**

Dans `src/crewai_custom_tools/__init__.py`, remplacer `__version__ = "0.9.0"` par `__version__ = "0.10.0"`.

Dans `pyproject.toml`, remplacer `version = "0.9.0"` par `version = "0.10.0"`, et compléter la cible wheel pour garantir l'embarquement du CSV :
```toml
[tool.hatch.build.targets.wheel]
packages = ["src/crewai_custom_tools"]
artifacts = ["src/crewai_custom_tools/tools/genealogy/data/*.csv"]
```

Créer `src/crewai_custom_tools/tools/genealogy/data/README.md` :
```markdown
# Table prénoms → sexe (INSEE + OFS)

`prenoms_sexe.csv` — colonnes `prenom` (clé normalisée : MAJUSCULES, accents
retirés, apostrophes/tirets canoniques), `n_f`, `n_m` (effectifs de naissances).

## Sources (souveraines, hors-ligne une fois téléchargées)

- **INSEE — Fichier des prénoms** (national), CSV `;`, colonnes
  `sexe;preusuel;annais;nombre` (`sexe` 1=M, 2=F ; `preusuel` en capitales sans
  accents ; prénoms rares regroupés sous `_PRENOMS_RARES`, **exclus**).
  Licence Ouverte / Etalab. <https://www.insee.fr/fr/statistiques/8595130>
- **OFS/BFS — Prénoms des nouveau-nés** (Suisse), extraits en deux CSV `;`
  `prenom;nombre` (`ofs_masculin.csv`, `ofs_feminin.csv`).
  <https://www.bfs.admin.ch/bfs/fr/home/statistiques/population/naissances-deces/prenoms-nouveaux-nes.html>

## Régénération

```bash
uv run python scripts/build_prenoms_sexe.py \
  --insee nat.csv --ofs-f ofs_feminin.csv --ofs-m ofs_masculin.csv \
  --out src/crewai_custom_tools/tools/genealogy/data/prenoms_sexe.csv
```

Les fichiers bruts ne sont pas versionnés ; seul `prenoms_sexe.csv` l'est.
```

- [ ] **Step 4: Lancer — il passe**

Run: `cd /Users/fjacquet/Projects/crewai_custom_tools && uv run pytest tests/test_scaffold.py -q`
Expected: PASS.

- [ ] **Step 5: Suite complète cct**

Run: `cd /Users/fjacquet/Projects/crewai_custom_tools && uv run pytest -q`
Expected: PASS (tout vert, y compris les nouveaux tests genealogy).

- [ ] **Step 6: Commit**

```bash
cd /Users/fjacquet/Projects/crewai_custom_tools
git add pyproject.toml src/crewai_custom_tools/__init__.py tests/test_scaffold.py \
        src/crewai_custom_tools/tools/genealogy/data/README.md
git commit -m "chore(genealogy): provenance données + wheel data + bump 0.10.0"
```

> **Étape manuelle** (voir « Étape manuelle préalable ») : générer et committer
> `prenoms_sexe.csv` maintenant que le script (Task 3) existe. Non exécutée par un subagent.

---

## Task 5 : Rendus purs Markdown/YAML (genecrew)

**Files:**
- Create: `genecrew/src/genecrew/gender.py`
- Test: `genecrew/tests/test_gender.py`

**Interfaces:**
- Consumes: `Proposition` (Task 1).
- Produces :
  - `render_gender_report(scope, date, propositions, indecidables, people_count, base_url="http://localhost") -> str` — `propositions: list[Proposition]`, `indecidables: list[tuple[str,str,str]]` = `(gramps_id, prenom, raison)`.
  - `render_propositions_yaml(propositions: list[Proposition]) -> str`.
  - `_confiance(ratio: float) -> str` (`"haute"` si `ratio >= 0.99` sinon `"moyenne"`).

- [ ] **Step 1: Écrire les tests qui échouent**

Créer `genecrew/tests/test_gender.py` :
```python
"""Tests de l'inférence de genre : rendus purs + orchestration lecture seule."""

import yaml

from crewai_custom_tools.tools.genealogy.models.domain import Proposition

from genecrew.gender import render_gender_report, render_propositions_yaml

_P_CONTRA = Proposition(
    type="genre_contradiction", gramps_id="I0002", handle="h2", personne="Marguerite Dupont",
    valeur_actuelle="M", valeur_proposee="F",
    preuve="prénom « MARGUERITE » : 99.9% F sur 12000 (INSEE+OFS)",
    confiance="haute", priorite="haute",
)
_P_INCONNU = Proposition(
    type="genre_inconnu", gramps_id="I0001", handle="h1", personne="Suzanne Martin",
    valeur_actuelle="U", valeur_proposee="F",
    preuve="prénom « SUZANNE » : 99.0% F sur 10000 (INSEE+OFS)",
    confiance="moyenne", priorite="moyenne",
)


def test_render_report_orders_and_links():
    md = render_gender_report(
        "all", "2026-07-18", [_P_INCONNU, _P_CONTRA],
        [("I0003", "Dominique", "unisexe/rare")], people_count=42)
    assert "# Inférence de genre — all — 2026-07-18" in md
    assert "[I0001](http://localhost/person/I0001)" in md
    # priorité haute (contradiction) listée avant la moyenne (inconnu)
    assert md.index("I0002") < md.index("I0001")
    assert "## Indécidables" in md and "Dominique" in md


def test_render_yaml_roundtrips():
    text = render_propositions_yaml([_P_CONTRA, _P_INCONNU])
    back = [Proposition(**d) for d in yaml.safe_load(text)]
    assert back == [_P_CONTRA, _P_INCONNU]
```

- [ ] **Step 2: Lancer — il échoue**

Run: `cd /Users/fjacquet/Projects/genecrew && uv run python -m pytest genecrew/tests/test_gender.py -q`
Expected: FAIL (`ModuleNotFoundError: genecrew.gender`).

- [ ] **Step 3: Implémenter les rendus (fichier partiel)**

Créer `genecrew/src/genecrew/gender.py` (les fonctions d'orchestration arrivent en Task 6) :
```python
"""Gender-inference orchestration: read people, infer sex, emit Propositions.

Read-only: gender is a FACT, so every inference becomes a Proposition for human
review (Markdown report + YAML). This module never writes to Gramps.
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

import yaml

from crewai_custom_tools.tools.genealogy.analysis.gender import (
    infer_sex, load_prenoms_table,
)
from crewai_custom_tools.tools.genealogy.gramps.client import GrampsClient
from crewai_custom_tools.tools.genealogy.models.domain import Proposition

from genecrew.batching import iter_people_batches
from genecrew.facts import FactsFetcher

_PRIORITE_ORDER = {"haute": 0, "moyenne": 1}


def _link(gramps_id: str, base_url: str) -> str:
    return f"[{gramps_id}]({base_url}/person/{gramps_id})"


def _confiance(ratio: float) -> str:
    return "haute" if ratio >= 0.99 else "moyenne"


def render_gender_report(scope, date, propositions, indecidables, people_count,
                         base_url="http://localhost") -> str:
    """Pure Markdown report: proposals (priority-sorted) + indécidables."""
    props = sorted(propositions, key=lambda p: _PRIORITE_ORDER.get(p.priorite, 9))
    n_inconnu = sum(1 for p in propositions if p.type == "genre_inconnu")
    n_contra = sum(1 for p in propositions if p.type == "genre_contradiction")
    lines = [f"# Inférence de genre — {scope} — {date}", "",
             "## Synthèse", "",
             f"- Personnes analysées : {people_count}",
             f"- Propositions : {len(propositions)} "
             f"({n_contra} contradiction, {n_inconnu} genre inconnu)",
             f"- Indécidables (genre inconnu, prénom non tranchable) : {len(indecidables)}",
             "", "## Propositions", ""]
    if props:
        lines += ["| Personne | Type | Actuel | Proposé | Confiance | Priorité | Preuve |",
                  "|---|---|---|---|---|---|---|"]
        for p in props:
            lines.append(
                f"| {_link(p.gramps_id, base_url)} | {p.type} | {p.valeur_actuelle} "
                f"| {p.valeur_proposee} | {p.confiance} | {p.priorite} | {p.preuve} |")
    else:
        lines.append("Aucune proposition.")
    lines += ["", "## Indécidables", ""]
    if indecidables:
        lines += ["| Personne | Prénom | Raison |", "|---|---|---|"]
        for gid, prenom, raison in indecidables:
            lines.append(f"| {_link(gid, base_url)} | {prenom} | {raison} |")
    else:
        lines.append("Aucun indécidable.")
    lines.append("")
    return "\n".join(lines)


def render_propositions_yaml(propositions: list[Proposition]) -> str:
    """Serialize propositions to YAML (machine-readable, for a future apply step)."""
    return yaml.safe_dump([p.model_dump() for p in propositions],
                          allow_unicode=True, sort_keys=False)
```

- [ ] **Step 4: Lancer — les deux tests de rendu passent**

Run: `cd /Users/fjacquet/Projects/genecrew && uv run python -m pytest genecrew/tests/test_gender.py -q`
Expected: PASS (2 passed) — `run_gender` importé mais non encore appelé par ces tests.

- [ ] **Step 5: Commit**

```bash
cd /Users/fjacquet/Projects/genecrew
git add genecrew/src/genecrew/gender.py genecrew/tests/test_gender.py
git commit -m "feat(gender): rendus purs rapport Markdown + propositions YAML"
```

---

## Task 6 : Orchestration `run_gender` lecture seule (genecrew)

**Files:**
- Modify: `genecrew/src/genecrew/gender.py`
- Test: `genecrew/tests/test_gender.py` (étend Task 5)

**Interfaces:**
- Consumes: `infer_sex`, `load_prenoms_table` (Task 2), `iter_people_batches`, `FactsFetcher`, `Proposition`, rendus (Task 5).
- Produces :
  - `_build_proposition(person, inf) -> Proposition`.
  - `run_gender(client, scope, output_dir, *, date, batch_size=25, limit=None, table=None) -> tuple[Path, Path]` — écrit `output/inference/<date>_genres_<scope>.md` et `…_propositions_genre_<scope>.yaml`. `table` injectable pour les tests ; par défaut `load_prenoms_table()`.

- [ ] **Step 1: Écrire le test e2e qui échoue**

Ajouter ces imports en tête de `genecrew/tests/test_gender.py` (après les imports existants) :
```python
import httpx

from crewai_custom_tools.tools.genealogy.gramps.client import GrampsClient, GrampsConfig

from genecrew.gender import run_gender
```

Puis ajouter le test e2e à la fin du fichier :
```python
CONFIG = GrampsConfig(api_url="http://g.test/api", username="u", password="p")

PEOPLE = [
    {"handle": "h1", "gramps_id": "I0001", "gender": 2,          # inconnu -> F
     "primary_name": {"first_name": "Suzanne", "surname_list": [{"surname": "Martin"}]}},
    {"handle": "h2", "gramps_id": "I0002", "gender": 1,          # M mais prénom F -> contradiction
     "primary_name": {"first_name": "Marguerite", "surname_list": [{"surname": "Dupont"}]}},
    {"handle": "h3", "gramps_id": "I0003", "gender": 2,          # inconnu, unisexe -> indécidable
     "primary_name": {"first_name": "Dominique", "surname_list": [{"surname": "Roy"}]}},
    {"handle": "h4", "gramps_id": "I0004", "gender": 0,          # F et prénom F -> rien
     "primary_name": {"first_name": "Suzanne", "surname_list": [{"surname": "Blanc"}]}},
]

TABLE = {"SUZANNE": (9990, 10), "MARGUERITE": (11988, 12), "DOMINIQUE": (5000, 5000)}


def _readonly_handler(request):
    if request.url.path == "/api/token/":
        return httpx.Response(200, json={"access_token": "t"})
    if request.method == "GET" and request.url.path == "/api/people/":
        page = int(request.url.params.get("page", "1"))
        return httpx.Response(200, json=PEOPLE if page == 1 else [])
    if request.method in ("PUT", "POST"):
        raise AssertionError("lecture seule : aucune écriture attendue")
    return httpx.Response(404)


def test_run_gender_is_read_only_and_classifies(tmp_path):
    client = GrampsClient(CONFIG, transport=httpx.MockTransport(_readonly_handler))
    report, proposals = run_gender(
        client, "all", tmp_path, date="2026-07-18", batch_size=25, table=TABLE)

    props = yaml.safe_load(proposals.read_text(encoding="utf-8"))
    by_id = {p["gramps_id"]: p for p in props}
    assert by_id["I0001"]["type"] == "genre_inconnu" and by_id["I0001"]["valeur_proposee"] == "F"
    assert by_id["I0002"]["type"] == "genre_contradiction"
    assert by_id["I0002"]["valeur_actuelle"] == "M" and by_id["I0002"]["valeur_proposee"] == "F"
    assert "I0003" not in by_id and "I0004" not in by_id     # indécidable / correct
    md = report.read_text(encoding="utf-8")
    assert "Dominique" in md                                 # I0003 listé en indécidable
```

- [ ] **Step 2: Lancer — il échoue**

Run: `cd /Users/fjacquet/Projects/genecrew && uv run python -m pytest genecrew/tests/test_gender.py::test_run_gender_is_read_only_and_classifies -q`
Expected: FAIL (`ImportError`/`AttributeError` : `run_gender` incomplet — pas encore défini).

- [ ] **Step 3: Implémenter `_build_proposition` + `run_gender`**

Ajouter à la fin de `genecrew/src/genecrew/gender.py` :
```python
def _build_proposition(person, inf) -> Proposition:
    preuve = (f"prénom « {inf.key} » : {inf.ratio * 100:.1f}% "
              f"{inf.sex} sur {inf.total} naissances (INSEE+OFS)")
    if person.sex == "U":
        return Proposition(
            type="genre_inconnu", gramps_id=person.gramps_id, handle=person.handle,
            personne=person.name, valeur_actuelle="U", valeur_proposee=inf.sex,
            preuve=preuve, confiance=_confiance(inf.ratio), priorite="moyenne")
    return Proposition(
        type="genre_contradiction", gramps_id=person.gramps_id, handle=person.handle,
        personne=person.name, valeur_actuelle=person.sex, valeur_proposee=inf.sex,
        preuve=preuve, confiance=_confiance(inf.ratio), priorite="haute")


def run_gender(client: GrampsClient, scope: str, output_dir, *, date: str,
               batch_size: int = 25, limit: int | None = None,
               table: Mapping[str, tuple[int, int]] | None = None) -> tuple[Path, Path]:
    """Infer sex over `scope`; write a Markdown report + a YAML proposals file. Read-only."""
    output_dir = Path(output_dir)
    if table is None:
        table = load_prenoms_table()
    fetcher = FactsFetcher(client)
    propositions: list[Proposition] = []
    indecidables: list[tuple[str, str, str]] = []
    people_count = 0

    for batch in iter_people_batches(client, fetcher, scope, batch_size, limit):
        for person in batch:
            people_count += 1
            inf = infer_sex(person.given, table)
            if inf.sex is None:
                if person.sex == "U" and person.given.strip():
                    raison = "unisexe/rare" if inf.total else "non couvert"
                    indecidables.append((person.gramps_id, person.given, raison))
                continue
            if person.sex == "U" or inf.sex != person.sex:
                propositions.append(_build_proposition(person, inf))

    out = output_dir / "inference"
    out.mkdir(parents=True, exist_ok=True)
    scope_slug = scope.replace(":", "_")
    report_path = out / f"{date}_genres_{scope_slug}.md"
    report_path.write_text(
        render_gender_report(scope, date, propositions, indecidables, people_count),
        encoding="utf-8")
    yaml_path = out / f"{date}_propositions_genre_{scope_slug}.yaml"
    yaml_path.write_text(render_propositions_yaml(propositions), encoding="utf-8")
    return report_path, yaml_path
```

- [ ] **Step 4: Lancer — le fichier de tests complet passe**

Run: `cd /Users/fjacquet/Projects/genecrew && uv run python -m pytest genecrew/tests/test_gender.py -q`
Expected: PASS (3 passed).

- [ ] **Step 5: Commit**

```bash
cd /Users/fjacquet/Projects/genecrew
git add genecrew/src/genecrew/gender.py genecrew/tests/test_gender.py
git commit -m "feat(gender): orchestration run_gender lecture seule (inconnus + contradictions)"
```

---

## Task 7 : Sous-commande CLI `genecrew gender` (genecrew)

**Files:**
- Modify: `genecrew/src/genecrew/main.py`
- Test: `genecrew/tests/test_cli_gender.py`

**Interfaces:**
- Consumes: `run_gender` (Task 6).
- Produces: sous-commande `gender` avec `--scope` (défaut `all`), `--limit`, `--date`. Pas de `--dry-run` (lecture seule).

- [ ] **Step 1: Écrire le test qui échoue**

Créer `genecrew/tests/test_cli_gender.py` :
```python
import subprocess
import sys


def test_gender_help_lists_options():
    out = subprocess.run(
        [sys.executable, "-m", "genecrew.main", "gender", "--help"],
        capture_output=True, text=True, cwd="genecrew/src",
    )
    assert out.returncode == 0
    assert "--scope" in out.stdout and "--limit" in out.stdout
    assert "--dry-run" not in out.stdout        # lecture seule
```

- [ ] **Step 2: Lancer — il échoue**

Run: `cd /Users/fjacquet/Projects/genecrew && uv run python -m pytest genecrew/tests/test_cli_gender.py -q`
Expected: FAIL (`gender` n'est pas une sous-commande valide → returncode ≠ 0).

- [ ] **Step 3: Câbler la sous-commande**

Dans `genecrew/src/genecrew/main.py`, ajouter la fonction `gender_cmd` après `names_cmd` :
```python
def gender_cmd(args) -> None:
    """Infer gender from first name (read-only); print the report + proposals paths."""
    from pathlib import Path

    from crewai_custom_tools.tools.genealogy.gramps.client import (
        GrampsClient,
        GrampsConfig,
    )

    from genecrew.gender import run_gender

    client = GrampsClient(GrampsConfig.from_env())
    output_dir = Path(os.environ.get("GENECREW_OUTPUT_DIR", "output"))
    date = args.date or __import__("datetime").date.today().isoformat()
    report, proposals = run_gender(client, args.scope, output_dir, date=date, limit=args.limit)
    print(f"Rapport : {report}")
    print(f"Propositions : {proposals}")
```

Dans `main()`, après le bloc `names_p` et avant `args = parser.parse_args()` :
```python
    gender_p = sub.add_parser("gender",
                              help="Inférence de genre à partir du prénom (lecture seule)")
    gender_p.add_argument("--scope", default="all", help="all | person:ID")
    gender_p.add_argument("--limit", type=int, default=None, help="limiter à N personnes")
    gender_p.add_argument("--date", default=None, help="date du rapport (défaut : aujourd'hui)")
```

Dans le dispatch, après le `elif args.command == "names":` :
```python
    elif args.command == "gender":
        gender_cmd(args)
```

- [ ] **Step 4: Lancer — il passe**

Run: `cd /Users/fjacquet/Projects/genecrew && uv run python -m pytest genecrew/tests/test_cli_gender.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
cd /Users/fjacquet/Projects/genecrew
git add genecrew/src/genecrew/main.py genecrew/tests/test_cli_gender.py
git commit -m "feat(gender): sous-commande CLI genecrew gender (lecture seule)"
```

---

## Task 8 : ADR, guide utilisateur, sync du lockfile (genecrew)

**Files:**
- Create: `docs/adr/0008-inference-genre-proposition.md`
- Modify: `docs/USER_GUIDE.md`, `CLAUDE.md`, `uv.lock`

**Interfaces:** aucune (docs + lock). Termine le chantier côté genecrew.

- [ ] **Step 1: ADR 0008**

Créer `docs/adr/0008-inference-genre-proposition.md` :
```markdown
# 0008 — Inférence de genre : proposition, pas écriture

## Statut
Accepté — 2026-07-18

## Contexte
Des personnes ont un genre inconnu (`gender=2`). On peut l'inférer depuis le
prénom via un dictionnaire prénom→sexe souverain (INSEE + OFS). Le genre est un
**fait** (ADR 0001, forme-vs-fait), pas une forme.

## Décision
L'inférence de genre est **lecture seule** : chaque cas devient une `Proposition`
pour revue humaine (rapport Markdown + YAML), jamais une écriture Gramps. Premier
émetteur du modèle `Proposition`, réutilisé par les futurs chantiers. Politique
conservatrice : proposer seulement si le sexe dominant ≥ 95 % sur ≥ 50 naissances.
Périmètre : genres inconnus (proposition F/M) **et** contradictions genre/prénom
(à vérifier).

## Conséquences
- Aucun outil d'écriture n'est ajouté ; la garantie lecture seule est testée.
- Le futur « apply » (relecture du YAML validé → écriture) est un chantier séparé.
- Les prénoms hors couverture INSEE/OFS restent en abstention (indécidables).
```

- [ ] **Step 2: Section USER_GUIDE**

Ajouter à `docs/USER_GUIDE.md` une section « Inférence de genre » :
```markdown
## Inférence de genre (lecture seule)

Propose un genre (F/M) pour les personnes de genre inconnu et signale les
contradictions genre/prénom, à partir d'un dictionnaire prénom→sexe INSEE+OFS.
**Aucune écriture Gramps** : sortie en propositions pour revue humaine.

```bash
cd genecrew && uv run genecrew gender --scope all --limit 200
```

Produit dans `output/inference/` : un rapport Markdown (`*_genres_*.md`) et un
fichier de propositions YAML (`*_propositions_genre_*.yaml`, pour un futur
« apply »). Prérequis : la table `prenoms_sexe.csv` doit avoir été générée
(voir `crewai_custom_tools/.../data/README.md`) ; sinon la commande échoue en
signalant le fichier absent.
```

- [ ] **Step 3: CLAUDE.md (commande)**

Dans `CLAUDE.md` (genecrew), section Commands, ajouter sous les exemples `genecrew` :
```bash
cd genecrew && uv run genecrew gender --scope all --limit 200  # inférence de genre, lecture seule
```

- [ ] **Step 4: Sync du lockfile (cct 0.10.0)**

Run: `cd /Users/fjacquet/Projects/genecrew && uv sync -q && uv run python -m pytest genecrew/tests/ -q`
Expected: `uv.lock` référence `crewai-custom-tools` en `0.10.0` ; tous les tests genecrew passent.

- [ ] **Step 5: Commit**

```bash
cd /Users/fjacquet/Projects/genecrew
git add docs/adr/0008-inference-genre-proposition.md docs/USER_GUIDE.md CLAUDE.md uv.lock
git commit -m "docs(gender): ADR 0008 + guide + sync lockfile 0.10.0"
```

---

## Notes d'exécution finale (après les 8 tâches)

1. Revue finale de branche (whole-branch) sur chaque dépôt via superpowers:requesting-code-review.
2. **Étape manuelle humaine** : générer + committer `prenoms_sexe.csv` (sources INSEE+OFS).
3. Vérification CLI réelle : `cd genecrew && uv run genecrew gender --limit 50` → rapport + YAML cohérents.
4. Finir via superpowers:finishing-a-development-branch : merger cct (`feat/genealogy-gender-inference`) **puis** genecrew (`feat/gender-inference`) dans `main`, tests verts après chaque merge.
