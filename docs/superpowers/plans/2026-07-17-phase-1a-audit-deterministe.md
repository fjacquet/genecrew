# Phase 1a — Audit déterministe : Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Un moteur d'audit généalogique 100 % déterministe (règles R1–R10 en fonctions pures) et une CLI `genecrew audit` qui le lance par lots sur l'arbre Gramps réel et produit un rapport Markdown des anomalies — sans LLM ni écriture Gramps.

**Architecture:** Les règles sont des fonctions pures dans `crewai_custom_tools/tools/genealogy/analysis/`, opérant sur un modèle normalisé `PersonFacts`/`FamilyFacts` (Pydantic, `models/domain.py`). L'orchestrateur genecrew construit ces faits depuis l'API (`facts.py`, via `profile=all&extend=event_ref_list`), découpe en lots avec reprise (`scope.py`, `checkpoint.py`), applique les règles et écrit un rapport Markdown (`report.py`). La comparaison de dates repose sur le `sortval` Gramps (numéro de jour julien entier), robuste aux dates partielles.

**Tech Stack:** Python 3.12, uv, Pydantic v2, pytest + pytest-mock + httpx.MockTransport, `difflib` (stdlib), le client Gramps de la Phase 0.

## Global Constraints

- **`uv` pour tout** : `uv sync`, `uv run` — jamais `pip`/`python` directs.
- **Deux dépôts, deux branches** : tâches 1–5 dans `/Users/fjacquet/Projects/crewai_custom_tools` (branche `feat/genealogy-audit`, partant de `main`) ; tâches 6–12 dans `/Users/fjacquet/Projects/genecrew` (branche `feat/phase1a-audit`, partant de `main`).
- **Phase 1a = lecture seule, sans LLM** : aucun appel LLM, aucune écriture Gramps, aucun `BaseTool` d'écriture. Les règles sont des **fonctions pures** (pas de `BaseTool` non plus en 1a — les enveloppes CrewAI `GenealogyConsistencyTool`/`DuplicateFinderTool` sont la Phase 1b). Réf. spec `docs/document-de-travail.md` §6.1, §7.2, §8.
- Conventions crewai_custom_tools (son `CLAUDE.md`) : tests 100 % hors-ligne ; fichiers ≤ 500 lignes ; bump `__version__` + `pyproject.toml` en lockstep (`tests/test_scaffold.py` l'assure).
- **Style fonctionnel** : les règles et le formatage du rapport sont des fonctions pures (entrées → sorties, sans I/O) ; les effets (HTTP, fichiers) vivent dans `facts.py`, `checkpoint.py` et la commande CLI.
- **Sévérités normalisées** (chaîne française) : `"haute"`, `"moyenne"`, `"basse"`.
- **Convention Gramps** : genre `gender` int `0=F, 1=M, 2=U` ; date d'un événement = objet `date` avec `sortval` (int, jour julien ; `0` = inconnu/non triable), `year` (int|null), `modifier` (0 exact,1 avant,2 après,3 vers,4 intervalle,5 durée,6 texte), `quality` (0 normal,1 estimé,2 calculé), `dateval` (`[jour, mois, année, false, ...]`).
- **Spec de référence des endpoints** : `genecrew/docs/swagger/openapi.json` (Gramps Web 3.17.0).

---

## Rappel des règles (spec §6.1) et de leur découpage

| # | Règle | Portée | Sévérité |
| --- | --- | --- | --- |
| R1 | naissance postérieure au décès | personne | haute |
| R2 | âge au décès > 105 ans | personne | haute |
| R3 | mère < 13 ou > 55 ans, ou père < 13 ou > 80 ans, à la naissance d'un enfant | famille | haute |
| R4 | mariage avant 13 ans | famille | haute |
| R5 | enfant né après le décès de la mère, ou > 9 mois (280 j) après celui du père | famille | haute |
| R6 | événement de vie daté hors de la vie de la personne | personne | moyenne |
| R7 | baptême avant naissance ; inhumation avant décès | personne | moyenne |
| R8 | date malformée (présente mais non triable, ou composantes hors bornes) | personne | basse |
| R9 | personne sans aucune source/citation | personne | basse |
| R10 | candidats doublons (nom normalisé + naissance à ±2 ans + difflib ≥ 0,85) | lot | — (score) |

- **Règles personne** (R1, R2, R6, R7, R8, R9) : `check_person(person: PersonFacts) -> list[Anomaly]`.
- **Règles famille** (R3, R4, R5) : `check_family(family: FamilyFacts, persons: dict[str, PersonFacts]) -> list[Anomaly]`.
- **Doublons** (R10) : `find_duplicates(people: list[PersonFacts]) -> list[DuplicateCandidate]`.

---

### Task 1 : Modèles de domaine (Pydantic)

**Files:**

- Create: `src/crewai_custom_tools/tools/genealogy/analysis/__init__.py`
- Create: `src/crewai_custom_tools/tools/genealogy/models/domain.py`
- Test: `tests/test_genealogy_domain.py`

**Interfaces:**

- Produces (consommé par toutes les tâches suivantes) : `EventFact`, `PersonFacts`, `FamilyFacts`, `Anomaly`, `DuplicateCandidate` dans `models/domain.py`.

- [ ] **Step 1 : Écrire le test qui échoue**

`tests/test_genealogy_domain.py` :

```python
"""Construction/validation des modèles de domaine de l'audit."""

from crewai_custom_tools.tools.genealogy.models.domain import (
    Anomaly,
    DuplicateCandidate,
    EventFact,
    FamilyFacts,
    PersonFacts,
)


def test_eventfact_defaults():
    e = EventFact(type="Birth", sortval=2346578, year=1712)
    assert e.modifier == 0 and e.quality == 0 and e.has_citation is False


def test_personfacts_minimal_and_lists_default_empty():
    p = PersonFacts(gramps_id="I0001", handle="h1", name="Jean Test",
                    surname="Test", given="Jean", sex="M")
    assert p.birth is None and p.death is None
    assert p.events == [] and p.family_handles == [] and p.parent_family_handles == []
    assert p.has_any_citation is False


def test_familyfacts_and_anomaly_and_duplicate():
    f = FamilyFacts(gramps_id="F0001", handle="fh1")
    assert f.father_handle is None and f.child_handles == [] and f.marriage is None
    a = Anomaly(rule="R1", severity="haute", gramps_id="I0001", handle="h1",
                message="naissance après décès")
    assert a.detail == {}
    d = DuplicateCandidate(gramps_id_a="I0001", gramps_id_b="I0002",
                           score=0.91, reason="homonymes, naissances proches")
    assert d.score == 0.91
```

- [ ] **Step 2 : Vérifier l'échec**

```bash
cd /Users/fjacquet/Projects/crewai_custom_tools
uv run python -m pytest tests/test_genealogy_domain.py -v
```

Attendu : ÉCHEC — `ModuleNotFoundError` sur `models.domain`.

- [ ] **Step 3 : Implémenter les modèles**

`src/crewai_custom_tools/tools/genealogy/analysis/__init__.py` :

```python
"""Deterministic genealogy analysis: pure consistency rules + duplicate finder."""
```

`src/crewai_custom_tools/tools/genealogy/models/domain.py` :

```python
"""Hand-written domain models for the deterministic audit (Phase 1a).

These are the normalized facts the pure rules operate on — decoupled from the
raw Gramps Web JSON, which the genecrew orchestrator maps into these shapes.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class EventFact(BaseModel):
    """One dated event, reduced to what the rules need."""

    type: str                       # "Birth", "Death", "Baptism", "Burial", "Marriage"...
    sortval: int = 0                # Julian day number; 0 = unknown/unsortable
    year: int | None = None
    modifier: int = 0               # 0 exact,1 before,2 after,3 about,4 range,5 span,6 text
    quality: int = 0                # 0 normal,1 estimated,2 calculated
    dateval: list = Field(default_factory=list)
    has_citation: bool = False


class PersonFacts(BaseModel):
    """Normalized person facts for the rules engine."""

    gramps_id: str
    handle: str
    name: str
    surname: str
    given: str
    sex: str                        # "M", "F", "U"
    birth: EventFact | None = None
    death: EventFact | None = None
    events: list[EventFact] = Field(default_factory=list)
    has_any_citation: bool = False
    parent_family_handles: list[str] = Field(default_factory=list)
    family_handles: list[str] = Field(default_factory=list)


class FamilyFacts(BaseModel):
    """Normalized family facts for the family rules (R3, R4, R5)."""

    gramps_id: str
    handle: str
    father_handle: str | None = None
    mother_handle: str | None = None
    child_handles: list[str] = Field(default_factory=list)
    marriage: EventFact | None = None


class Anomaly(BaseModel):
    """One detected inconsistency, attached to a person."""

    rule: str                       # "R1".."R9"
    severity: str                   # "haute" | "moyenne" | "basse"
    gramps_id: str
    handle: str
    message: str                    # human-readable, French
    detail: dict = Field(default_factory=dict)


class DuplicateCandidate(BaseModel):
    """A pair of persons that may be duplicates (R10)."""

    gramps_id_a: str
    gramps_id_b: str
    score: float
    reason: str
```

- [ ] **Step 4 : Vérifier le succès**

```bash
uv run python -m pytest tests/test_genealogy_domain.py -v
```

Attendu : 3 PASS.

- [ ] **Step 5 : Commit**

```bash
git add src/crewai_custom_tools/tools/genealogy/analysis/__init__.py \
        src/crewai_custom_tools/tools/genealogy/models/domain.py \
        tests/test_genealogy_domain.py
git commit -m "feat(genealogy): domain models for the deterministic audit"
```

---

### Task 2 : Règles personne (R1, R2, R6, R7, R8, R9)

**Files:**

- Create: `src/crewai_custom_tools/tools/genealogy/analysis/rules.py`
- Test: `tests/test_genealogy_rules_person.py`

**Interfaces:**

- Consumes : les modèles de la tâche 1.
- Produces (consommé par la tâche 3 et par genecrew) : helpers `is_valid(ev)`, `years_between(a, b)` ; `check_person(person: PersonFacts) -> list[Anomaly]`.

Décisions de conception (fixées ici) :

- Comparaisons de dates via `sortval` (entier) uniquement quand `sortval > 0` (sinon date inconnue → règle ignorée, pas de faux positif).
- Âge en années = `(b.sortval - a.sortval) / 365.25`.
- R6 « événement de vie hors de la vie » : ne concerne que les types **de vie** (tout sauf les post-mortem `Burial`, `Cremation`, `Probate`, `Will` et les jalons `Birth`/`Death` eux-mêmes) ; on signale `sortval < birth.sortval` (avant naissance) ou `sortval > death.sortval` (après décès).
- R8 « date malformée » : un événement dont la `dateval` est non vide **ou** `year` est renseigné mais `sortval == 0` (non triable), **ou** dont la composante mois (`dateval[1]`) est > 12 ou jour (`dateval[0]`) est > 31.

- [ ] **Step 1 : Écrire les tests qui échouent**

`tests/test_genealogy_rules_person.py` :

```python
"""Tests par table des règles personne R1, R2, R6, R7, R8, R9 (pures, hors-ligne)."""

from crewai_custom_tools.tools.genealogy.models.domain import EventFact, PersonFacts
from crewai_custom_tools.tools.genealogy.analysis.rules import check_person


def _p(**kw):
    base = dict(gramps_id="I1", handle="h1", name="X", surname="X", given="x",
                sex="M", has_any_citation=True)
    base.update(kw)
    return PersonFacts(**base)


def _rules(anoms):
    return {a.rule for a in anoms}


def test_r1_birth_after_death():
    p = _p(birth=EventFact(type="Birth", sortval=2400000, year=1850),
           death=EventFact(type="Death", sortval=2390000, year=1820))
    assert "R1" in _rules(check_person(p))


def test_r1_ok_when_order_correct():
    p = _p(birth=EventFact(type="Birth", sortval=2390000, year=1820),
           death=EventFact(type="Death", sortval=2400000, year=1850))
    assert "R1" not in _rules(check_person(p))


def test_r2_age_over_105():
    # ~120 ans : 120 * 365.25 ≈ 43830 jours
    p = _p(birth=EventFact(type="Birth", sortval=2300000, year=1700),
           death=EventFact(type="Death", sortval=2343830, year=1820))
    assert "R2" in _rules(check_person(p))


def test_r2_ok_normal_lifespan():
    p = _p(birth=EventFact(type="Birth", sortval=2300000, year=1700),
           death=EventFact(type="Death", sortval=2325000, year=1768))
    assert "R2" not in _rules(check_person(p))


def test_r6_life_event_before_birth():
    p = _p(birth=EventFact(type="Birth", sortval=2400000, year=1850),
           death=EventFact(type="Death", sortval=2420000, year=1905),
           events=[EventFact(type="Marriage", sortval=2399000, year=1848)])
    assert "R6" in _rules(check_person(p))


def test_r6_burial_after_death_is_not_flagged():
    p = _p(birth=EventFact(type="Birth", sortval=2400000, year=1850),
           death=EventFact(type="Death", sortval=2420000, year=1905),
           events=[EventFact(type="Burial", sortval=2420010, year=1905)])
    assert "R6" not in _rules(check_person(p))


def test_r7_baptism_before_birth():
    p = _p(birth=EventFact(type="Birth", sortval=2400000, year=1850),
           events=[EventFact(type="Baptism", sortval=2399990, year=1849)])
    assert "R7" in _rules(check_person(p))


def test_r7_burial_before_death():
    p = _p(death=EventFact(type="Death", sortval=2420000, year=1905),
           events=[EventFact(type="Burial", sortval=2419990, year=1905)])
    assert "R7" in _rules(check_person(p))


def test_r8_malformed_date_unsortable():
    # date présente (year renseigné) mais sortval == 0
    p = _p(events=[EventFact(type="Residence", sortval=0, year=1850, dateval=[0, 0, 1850, False])])
    # year renseigné + sortval 0 → R8
    p.events[0].dateval = [40, 13, 1850, False]  # jour 40, mois 13 hors bornes
    assert "R8" in _rules(check_person(p))


def test_r9_no_citation():
    p = _p(has_any_citation=False)
    assert "R9" in _rules(check_person(p))


def test_r9_absent_when_cited():
    p = _p(has_any_citation=True)
    assert "R9" not in _rules(check_person(p))
```

- [ ] **Step 2 : Vérifier l'échec**

```bash
uv run python -m pytest tests/test_genealogy_rules_person.py -v
```

Attendu : ÉCHEC — `ImportError` sur `analysis.rules`.

- [ ] **Step 3 : Implémenter les règles personne**

`src/crewai_custom_tools/tools/genealogy/analysis/rules.py` :

```python
"""Pure deterministic genealogy consistency rules (R1–R9).

Every function is side-effect free: it takes normalized facts and returns
Anomaly objects. Date comparisons use the Gramps Julian-day `sortval`
(integer); a rule is skipped when the dates it needs are unknown (sortval 0),
so unknown data never produces a false positive.
"""

from __future__ import annotations

from crewai_custom_tools.tools.genealogy.models.domain import (
    Anomaly,
    FamilyFacts,
    PersonFacts,
)

DAYS_PER_YEAR = 365.25
POSTMORTEM_TYPES = {"Burial", "Cremation", "Probate", "Will"}


def is_valid(ev) -> bool:
    """True when the event exists and carries a sortable date."""
    return ev is not None and ev.sortval > 0


def years_between(a, b) -> float:
    """Signed years from a to b using sortval (both must be valid)."""
    return (b.sortval - a.sortval) / DAYS_PER_YEAR


def _anom(rule, severity, p: PersonFacts, message, **detail) -> Anomaly:
    return Anomaly(rule=rule, severity=severity, gramps_id=p.gramps_id,
                   handle=p.handle, message=message, detail=detail)


def check_person(person: PersonFacts) -> list[Anomaly]:
    """Run all person-scoped rules (R1, R2, R6, R7, R8, R9)."""
    out: list[Anomaly] = []
    b, d = person.birth, person.death

    # R1 — birth after death
    if is_valid(b) and is_valid(d) and b.sortval > d.sortval:
        out.append(_anom("R1", "haute", person,
                         "Naissance postérieure au décès.",
                         birth_year=b.year, death_year=d.year))

    # R2 — age at death > 105
    if is_valid(b) and is_valid(d):
        age = years_between(b, d)
        if age > 105:
            out.append(_anom("R2", "haute", person,
                             f"Âge au décès de {age:.0f} ans (> 105).",
                             birth_year=b.year, death_year=d.year, age=round(age, 1)))

    # R6 — life event outside the person's lifespan
    for ev in person.events:
        if ev.type in POSTMORTEM_TYPES or ev.type in {"Birth", "Death"}:
            continue
        if not is_valid(ev):
            continue
        if is_valid(b) and ev.sortval < b.sortval:
            out.append(_anom("R6", "moyenne", person,
                             f"Événement « {ev.type} » ({ev.year}) daté avant la naissance.",
                             event_type=ev.type, event_year=ev.year, birth_year=b.year))
        elif is_valid(d) and ev.sortval > d.sortval:
            out.append(_anom("R6", "moyenne", person,
                             f"Événement « {ev.type} » ({ev.year}) daté après le décès.",
                             event_type=ev.type, event_year=ev.year, death_year=d.year))

    # R7 — baptism before birth ; burial before death
    for ev in person.events:
        if ev.type == "Baptism" and is_valid(ev) and is_valid(b) and ev.sortval < b.sortval:
            out.append(_anom("R7", "moyenne", person,
                             "Baptême antérieur à la naissance.",
                             baptism_year=ev.year, birth_year=b.year))
        if ev.type == "Burial" and is_valid(ev) and is_valid(d) and ev.sortval < d.sortval:
            out.append(_anom("R7", "moyenne", person,
                             "Inhumation antérieure au décès.",
                             burial_year=ev.year, death_year=d.year))

    # R8 — malformed date
    for ev in person.events:
        has_date = bool(ev.dateval) or ev.year is not None
        out_of_bounds = (len(ev.dateval) >= 2
                         and isinstance(ev.dateval[0], int) and isinstance(ev.dateval[1], int)
                         and (ev.dateval[0] > 31 or ev.dateval[1] > 12))
        if out_of_bounds or (has_date and ev.sortval == 0):
            out.append(_anom("R8", "basse", person,
                             f"Date malformée ou non interprétable sur « {ev.type} ».",
                             event_type=ev.type, dateval=ev.dateval))

    # R9 — no source at all
    if not person.has_any_citation:
        out.append(_anom("R9", "basse", person,
                         "Aucune source ni citation rattachée."))

    return out
```

- [ ] **Step 4 : Vérifier le succès**

```bash
uv run python -m pytest tests/test_genealogy_rules_person.py -v
```

Attendu : 11 PASS.

- [ ] **Step 5 : Commit**

```bash
git add src/crewai_custom_tools/tools/genealogy/analysis/rules.py \
        tests/test_genealogy_rules_person.py
git commit -m "feat(genealogy): person consistency rules R1,R2,R6,R7,R8,R9"
```

---

### Task 3 : Règles famille (R3, R4, R5)

**Files:**

- Modify: `src/crewai_custom_tools/tools/genealogy/analysis/rules.py` (ajout de `check_family`)
- Test: `tests/test_genealogy_rules_family.py`

**Interfaces:**

- Consumes : `is_valid`, `years_between` (tâche 2) ; `FamilyFacts`, `PersonFacts`, `Anomaly`.
- Produces (consommé par genecrew) : `check_family(family: FamilyFacts, persons: dict[str, PersonFacts]) -> list[Anomaly]`. `persons` mappe handle → PersonFacts pour le père, la mère et les enfants ; les handles absents du dict sont ignorés (données hors périmètre).

Décisions : bornes d'âge parental de la spec — mère < 13 ou > 55, père < 13 ou > 80 (à la naissance de l'enfant). R5 : enfant après décès mère (sortval strictement supérieur) ; après décès père + 280 jours (≈ 9 mois). Les anomalies famille sont rattachées à **l'enfant** concerné (ou au parent pour R4), pour apparaître sur la bonne fiche.

- [ ] **Step 1 : Écrire les tests qui échouent**

`tests/test_genealogy_rules_family.py` :

```python
"""Tests des règles famille R3, R4, R5 (pures)."""

from crewai_custom_tools.tools.genealogy.models.domain import (
    EventFact, FamilyFacts, PersonFacts,
)
from crewai_custom_tools.tools.genealogy.analysis.rules import check_family


def _person(hid, sex, birth_sort=None, birth_year=None, death_sort=None, death_year=None):
    b = EventFact(type="Birth", sortval=birth_sort, year=birth_year) if birth_sort else None
    d = EventFact(type="Death", sortval=death_sort, year=death_year) if death_sort else None
    return PersonFacts(gramps_id=hid, handle=hid, name=hid, surname=hid, given=hid,
                       sex=sex, birth=b, death=d, has_any_citation=True)


def _rules(anoms):
    return {a.rule for a in anoms}


def test_r3_mother_too_old():
    mother = _person("M", "F", birth_sort=2300000, birth_year=1700)
    # enfant né ~60 ans après la naissance de la mère : 60*365.25≈21915
    child = _person("C", "M", birth_sort=2321915, birth_year=1760)
    fam = FamilyFacts(gramps_id="F1", handle="F1", mother_handle="M", child_handles=["C"])
    anoms = check_family(fam, {"M": mother, "C": child})
    assert "R3" in _rules(anoms)
    assert any(a.gramps_id == "C" for a in anoms if a.rule == "R3")


def test_r3_father_too_old():
    father = _person("P", "M", birth_sort=2300000, birth_year=1700)
    child = _person("C", "M", birth_sort=2330000, birth_year=1782)  # ~82 ans
    fam = FamilyFacts(gramps_id="F1", handle="F1", father_handle="P", child_handles=["C"])
    assert "R3" in _rules(check_family(fam, {"P": father, "C": child}))


def test_r3_ok_normal_ages():
    mother = _person("M", "F", birth_sort=2300000, birth_year=1700)
    child = _person("C", "M", birth_sort=2309131, birth_year=1725)  # ~25 ans
    fam = FamilyFacts(gramps_id="F1", handle="F1", mother_handle="M", child_handles=["C"])
    assert "R3" not in _rules(check_family(fam, {"M": mother, "C": child}))


def test_r4_marriage_before_13():
    wife = _person("W", "F", birth_sort=2300000, birth_year=1700)
    fam = FamilyFacts(gramps_id="F1", handle="F1", mother_handle="W",
                      marriage=EventFact(type="Marriage", sortval=2303652, year=1710))  # ~10 ans
    assert "R4" in _rules(check_family(fam, {"W": wife}))


def test_r5_child_after_mother_death():
    mother = _person("M", "F", birth_sort=2300000, birth_year=1700,
                     death_sort=2320000, death_year=1755)
    child = _person("C", "M", birth_sort=2320500, birth_year=1756)  # après décès mère
    fam = FamilyFacts(gramps_id="F1", handle="F1", mother_handle="M", child_handles=["C"])
    assert "R5" in _rules(check_family(fam, {"M": mother, "C": child}))


def test_r5_child_within_9_months_of_father_death_is_ok():
    father = _person("P", "M", birth_sort=2300000, birth_year=1700,
                     death_sort=2320000, death_year=1755)
    child = _person("C", "M", birth_sort=2320100, birth_year=1755)  # 100 j après, < 280
    fam = FamilyFacts(gramps_id="F1", handle="F1", father_handle="P", child_handles=["C"])
    assert "R5" not in _rules(check_family(fam, {"P": father, "C": child}))
```

- [ ] **Step 2 : Vérifier l'échec**

```bash
uv run python -m pytest tests/test_genealogy_rules_family.py -v
```

Attendu : ÉCHEC — `check_family` non défini.

- [ ] **Step 3 : Implémenter `check_family` (ajout à `rules.py`)**

Ajouter à la fin de `rules.py` :

```python
DAYS_9_MONTHS = 280


def _fanom(rule, p: PersonFacts, message, **detail) -> Anomaly:
    return Anomaly(rule=rule, severity="haute", gramps_id=p.gramps_id,
                   handle=p.handle, message=message, detail=detail)


def check_family(family: FamilyFacts, persons: dict[str, PersonFacts]) -> list[Anomaly]:
    """Run family-scoped rules (R3, R4, R5). Missing handles are skipped."""
    out: list[Anomaly] = []
    father = persons.get(family.father_handle) if family.father_handle else None
    mother = persons.get(family.mother_handle) if family.mother_handle else None
    children = [persons[h] for h in family.child_handles if h in persons]

    # R3 — parent age at each child's birth
    for child in children:
        if not is_valid(child.birth):
            continue
        for parent, lo, hi, label in (
            (mother, 13, 55, "mère"),
            (father, 13, 80, "père"),
        ):
            if parent and is_valid(parent.birth):
                age = years_between(parent.birth, child.birth)
                if age < lo or age > hi:
                    out.append(_fanom("R3", child,
                        f"Âge de la {label} à la naissance : {age:.0f} ans (hors [{lo}, {hi}]).",
                        parent_gramps_id=parent.gramps_id, parent_age=round(age, 1)))

    # R4 — marriage before age 13 (each dated spouse)
    if is_valid(family.marriage):
        for spouse in (mother, father):
            if spouse and is_valid(spouse.birth):
                age = years_between(spouse.birth, family.marriage)
                if age < 13:
                    out.append(_fanom("R4", spouse,
                        f"Mariage à {age:.0f} ans (< 13).",
                        marriage_year=family.marriage.year))

    # R5 — child born after a parent's death
    for child in children:
        if not is_valid(child.birth):
            continue
        if mother and is_valid(mother.death) and child.birth.sortval > mother.death.sortval:
            out.append(_fanom("R5", child,
                "Naissance postérieure au décès de la mère.",
                mother_gramps_id=mother.gramps_id))
        if father and is_valid(father.death) and \
                child.birth.sortval > father.death.sortval + DAYS_9_MONTHS:
            out.append(_fanom("R5", child,
                "Naissance plus de 9 mois après le décès du père.",
                father_gramps_id=father.gramps_id))

    return out
```

- [ ] **Step 4 : Vérifier le succès**

```bash
uv run python -m pytest tests/test_genealogy_rules_family.py -v
```

Attendu : 6 PASS.

- [ ] **Step 5 : Commit**

```bash
git add src/crewai_custom_tools/tools/genealogy/analysis/rules.py \
        tests/test_genealogy_rules_family.py
git commit -m "feat(genealogy): family consistency rules R3,R4,R5"
```

---

### Task 4 : Détecteur de doublons (R10)

**Files:**

- Create: `src/crewai_custom_tools/tools/genealogy/analysis/duplicates.py`
- Test: `tests/test_genealogy_duplicates.py`

**Interfaces:**

- Consumes : `PersonFacts`, `DuplicateCandidate`.
- Produces (consommé par genecrew) : `normalize_name(s: str) -> str` ; `find_duplicates(people: list[PersonFacts], threshold: float = 0.85) -> list[DuplicateCandidate]`.

Algorithme (spec §6.1 R10) : clé = nom normalisé (sans accents, minuscules, espaces réduits) ; deux personnes sont candidates si leurs années de naissance sont connues et à ±2 ans **et** `difflib.SequenceMatcher` sur `"given surname"` normalisé ≥ 0,85. Comparaison O(n²) sur le lot (lots de 25 → négligeable).

- [ ] **Step 1 : Écrire les tests qui échouent**

`tests/test_genealogy_duplicates.py` :

```python
"""Tests du détecteur de doublons R10 (pur)."""

from crewai_custom_tools.tools.genealogy.models.domain import EventFact, PersonFacts
from crewai_custom_tools.tools.genealogy.analysis.duplicates import (
    find_duplicates, normalize_name,
)


def _p(gid, given, surname, birth_year):
    return PersonFacts(
        gramps_id=gid, handle=gid, name=f"{given} {surname}",
        surname=surname, given=given, sex="M",
        birth=EventFact(type="Birth", sortval=birth_year * 366, year=birth_year),
        has_any_citation=True,
    )


def test_normalize_strips_accents_and_case():
    assert normalize_name("Frédéric  DUPONT") == "frederic dupont"


def test_finds_near_homonyms_with_close_birth_years():
    people = [_p("I1", "Jean", "Dupont", 1850), _p("I2", "Jean", "Dupond", 1851)]
    dups = find_duplicates(people)
    assert len(dups) == 1
    assert {dups[0].gramps_id_a, dups[0].gramps_id_b} == {"I1", "I2"}
    assert dups[0].score >= 0.85


def test_ignores_when_birth_years_too_far_apart():
    people = [_p("I1", "Jean", "Dupont", 1850), _p("I2", "Jean", "Dupont", 1860)]
    assert find_duplicates(people) == []


def test_ignores_different_names():
    people = [_p("I1", "Jean", "Dupont", 1850), _p("I2", "Marie", "Lefevre", 1850)]
    assert find_duplicates(people) == []


def test_ignores_persons_without_birth_year():
    p1 = PersonFacts(gramps_id="I1", handle="I1", name="Jean Dupont",
                     surname="Dupont", given="Jean", sex="M", has_any_citation=True)
    p2 = PersonFacts(gramps_id="I2", handle="I2", name="Jean Dupont",
                     surname="Dupont", given="Jean", sex="M", has_any_citation=True)
    assert find_duplicates([p1, p2]) == []
```

- [ ] **Step 2 : Vérifier l'échec**

```bash
uv run python -m pytest tests/test_genealogy_duplicates.py -v
```

Attendu : ÉCHEC — module `duplicates` absent.

- [ ] **Step 3 : Implémenter le détecteur**

`src/crewai_custom_tools/tools/genealogy/analysis/duplicates.py` :

```python
"""Deterministic duplicate detection (R10) — pure, stdlib only."""

from __future__ import annotations

import unicodedata
from difflib import SequenceMatcher

from crewai_custom_tools.tools.genealogy.models.domain import (
    DuplicateCandidate,
    PersonFacts,
)

BIRTH_YEAR_WINDOW = 2


def normalize_name(s: str) -> str:
    """Lowercase, strip accents, collapse whitespace."""
    decomposed = unicodedata.normalize("NFKD", s)
    ascii_only = "".join(c for c in decomposed if not unicodedata.combining(c))
    return " ".join(ascii_only.lower().split())


def _key(p: PersonFacts) -> str:
    return normalize_name(f"{p.given} {p.surname}")


def find_duplicates(
    people: list[PersonFacts], threshold: float = 0.85
) -> list[DuplicateCandidate]:
    """Return candidate duplicate pairs within `people` (O(n²) over the batch)."""
    out: list[DuplicateCandidate] = []
    keyed = [(p, _key(p), p.birth.year if p.birth else None) for p in people]
    for i in range(len(keyed)):
        pa, ka, ya = keyed[i]
        if ya is None:
            continue
        for j in range(i + 1, len(keyed)):
            pb, kb, yb = keyed[j]
            if yb is None or abs(ya - yb) > BIRTH_YEAR_WINDOW:
                continue
            score = SequenceMatcher(None, ka, kb).ratio()
            if score >= threshold:
                out.append(DuplicateCandidate(
                    gramps_id_a=pa.gramps_id, gramps_id_b=pb.gramps_id,
                    score=round(score, 3),
                    reason=f"Homonymes ({ka!r} ≈ {kb!r}), naissances {ya}/{yb}."))
    return out
```

- [ ] **Step 4 : Vérifier le succès**

```bash
uv run python -m pytest tests/test_genealogy_duplicates.py -v
```

Attendu : 5 PASS.

- [ ] **Step 5 : Commit**

```bash
git add src/crewai_custom_tools/tools/genealogy/analysis/duplicates.py \
        tests/test_genealogy_duplicates.py
git commit -m "feat(genealogy): duplicate finder R10 (difflib, birth-year window)"
```

---

### Task 5 : Bump de version + smoke d'import

**Files:**

- Modify: `src/crewai_custom_tools/__init__.py` (`__version__`)
- Modify: `pyproject.toml` (`version`)
- Modify: `tests/test_scaffold.py` (attente de version)

**Interfaces:** aucune nouvelle ; on ne touche PAS à `__all__` (les fonctions d'analyse ne sont pas des `BaseTool` ; genecrew les importe par chemin de module).

- [ ] **Step 1 : Bump 0.7.0 → 0.8.0**

`__version__ = "0.8.0"` dans `src/crewai_custom_tools/__init__.py` ; `version = "0.8.0"` dans `pyproject.toml` ; mettre à jour l'attente `0.7.0` → `0.8.0` dans `tests/test_scaffold.py`.

- [ ] **Step 2 : Smoke d'import des modules d'analyse**

```bash
uv run python -c "from crewai_custom_tools.tools.genealogy.analysis.rules import check_person, check_family; from crewai_custom_tools.tools.genealogy.analysis.duplicates import find_duplicates; from crewai_custom_tools.tools.genealogy.models.domain import PersonFacts; import crewai_custom_tools as c; print(c.__version__)"
```

Attendu : `0.8.0`, aucune exception.

- [ ] **Step 3 : Suite complète**

```bash
uv run python -m pytest -q
```

Attendu : tout passe (438 existants + 25 nouveaux).

- [ ] **Step 4 : Commit**

```bash
git add src/crewai_custom_tools/__init__.py pyproject.toml tests/test_scaffold.py
git commit -m "chore(genealogy): bump to 0.8.0 (analysis submodule)"
```

---

### Task 6 : genecrew — reprise des lots (`checkpoint.py`)

> À partir d'ici : dépôt `/Users/fjacquet/Projects/genecrew`, branche `feat/phase1a-audit`.

**Files:**

- Create: `genecrew/src/genecrew/checkpoint.py`
- Test: `genecrew/tests/test_checkpoint.py`

**Interfaces:**

- Produces : `Checkpoint` (dataclass : `workflow: str`, `scope: str`, `done_handles: set[str]`) ; `load_checkpoint(path) -> Checkpoint | None` ; `save_checkpoint(path, cp) -> None`.

- [ ] **Step 1 : Test qui échoue** — `genecrew/tests/test_checkpoint.py` :

```python
from genecrew.checkpoint import Checkpoint, load_checkpoint, save_checkpoint


def test_roundtrip(tmp_path):
    path = tmp_path / "cp.json"
    cp = Checkpoint(workflow="audit", scope="all", done_handles={"h1", "h2"})
    save_checkpoint(path, cp)
    loaded = load_checkpoint(path)
    assert loaded.workflow == "audit" and loaded.scope == "all"
    assert loaded.done_handles == {"h1", "h2"}


def test_load_missing_returns_none(tmp_path):
    assert load_checkpoint(tmp_path / "absent.json") is None
```

- [ ] **Step 2 : Vérifier l'échec**

```bash
cd /Users/fjacquet/Projects/genecrew
uv run python -m pytest genecrew/tests/test_checkpoint.py -v
```

Attendu : ÉCHEC — module absent.

- [ ] **Step 3 : Implémenter** — `genecrew/src/genecrew/checkpoint.py` :

```python
"""Resumable batch checkpoints for long-running workflows (JSON on disk)."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class Checkpoint:
    workflow: str
    scope: str
    done_handles: set[str] = field(default_factory=set)


def load_checkpoint(path: Path) -> Checkpoint | None:
    """Load a checkpoint, or None if the file does not exist."""
    if not Path(path).exists():
        return None
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    return Checkpoint(workflow=data["workflow"], scope=data["scope"],
                      done_handles=set(data.get("done_handles", [])))


def save_checkpoint(path: Path, cp: Checkpoint) -> None:
    """Persist a checkpoint atomically-enough for a single-writer CLI."""
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps({
        "workflow": cp.workflow, "scope": cp.scope,
        "done_handles": sorted(cp.done_handles),
    }, ensure_ascii=False, indent=2), encoding="utf-8")
```

- [ ] **Step 4 : Vérifier le succès**

```bash
uv run python -m pytest genecrew/tests/test_checkpoint.py -v
```

Attendu : 2 PASS.

- [ ] **Step 5 : Commit**

```bash
git add genecrew/src/genecrew/checkpoint.py genecrew/tests/test_checkpoint.py
git commit -m "feat(audit): resumable JSON checkpoints"
```

---

### Task 7 : genecrew — construction des faits (`facts.py`)

**Files:**

- Create: `genecrew/src/genecrew/facts.py`
- Test: `genecrew/tests/test_facts.py`

**Interfaces:**

- Consumes : `GrampsClient` (Phase 0) ; `PersonFacts`, `FamilyFacts`, `EventFact` (crewai_custom_tools).
- Produces : `person_from_json(raw: dict) -> PersonFacts` (pur) ; `family_from_json(raw: dict) -> FamilyFacts` (pur) ; `FactsFetcher(client)` avec `list_people_facts(page, pagesize) -> list[PersonFacts]`, `get_person_facts(handle) -> PersonFacts | None` (caché), `get_family_facts(handle) -> FamilyFacts | None`.

**Contexte data (vérifié en direct sur l'arbre réel)** — un `GET /people/?profile=all&extend=event_ref_list` renvoie par personne :

- `gramps_id`, `handle`, `gender` (int 0=F,1=M,2=U), `citation_list` (liste), `family_list`, `parent_family_list`, `birth_ref_index`, `death_ref_index` (index dans `event_ref_list`, -1 si absent) ;
- `primary_name` → `first_name` (str) et `surname_list` (liste de `{surname: str, ...}`) ;
- `profile.birth` / `profile.death` : `{}` si absent, sinon `{"date": str, "citations": int, "type": str, ...}` ;
- `extended.events` : liste alignée sur `event_ref_list`, chaque entrée = événement brut avec `type` (str), `citation_list` (liste), et `date` = `{"sortval": int, "year": int, "dateval": [...], "modifier": int, "quality": int}`.

Un `GET /families/{handle}?extend=event_ref_list` renvoie `father_handle`, `mother_handle`, `child_ref_list` (chaque `{"ref": handle}`), et `extended.events` (chercher `type == "Marriage"`).

- [ ] **Step 1 : Test qui échoue** — `genecrew/tests/test_facts.py` (utilise les vraies formes JSON, client mické) :

```python
import httpx

from genecrew.facts import FactsFetcher, person_from_json, family_from_json
from crewai_custom_tools.tools.genealogy.gramps.client import GrampsClient, GrampsConfig

CONFIG = GrampsConfig(api_url="http://g.test/api", username="u", password="p")

PERSON_RAW = {
    "gramps_id": "I0001", "handle": "h1", "gender": 1,
    "citation_list": ["c1"], "family_list": ["f1"], "parent_family_list": ["pf1"],
    "birth_ref_index": 0, "death_ref_index": 1,
    "primary_name": {"first_name": "Jean", "surname_list": [{"surname": "Dupont"}]},
    "profile": {"birth": {"date": "1712", "citations": 1},
                "death": {"date": "1786", "citations": 0}},
    "event_ref_list": [{"ref": "e1"}, {"ref": "e2"}],
    "extended": {"events": [
        {"type": "Birth", "citation_list": ["c1"],
         "date": {"sortval": 2346578, "year": 1712, "dateval": [11, 8, 1712, False],
                  "modifier": 0, "quality": 0}},
        {"type": "Death", "citation_list": [],
         "date": {"sortval": 2373544, "year": 1786, "dateval": [0, 0, 1786, False],
                  "modifier": 0, "quality": 0}},
    ]},
}


def test_person_from_json_maps_vitals_and_sex():
    p = person_from_json(PERSON_RAW)
    assert p.gramps_id == "I0001" and p.sex == "M"
    assert p.given == "Jean" and p.surname == "Dupont"
    assert p.birth.sortval == 2346578 and p.birth.year == 1712
    assert p.death.year == 1786
    assert p.has_any_citation is True          # person citation_list non vide
    assert p.parent_family_handles == ["pf1"] and p.family_handles == ["f1"]
    assert len(p.events) == 2


def test_person_without_any_citation():
    raw = {**PERSON_RAW, "citation_list": [],
           "profile": {"birth": {"date": "1712", "citations": 0}, "death": {}},
           "extended": {"events": [
               {"type": "Birth", "citation_list": [],
                "date": {"sortval": 2346578, "year": 1712, "dateval": [], "modifier": 0, "quality": 0}}]},
           "birth_ref_index": 0, "death_ref_index": -1,
           "event_ref_list": [{"ref": "e1"}]}
    p = person_from_json(raw)
    assert p.has_any_citation is False and p.death is None


def test_family_from_json():
    raw = {"gramps_id": "F0001", "handle": "f1",
           "father_handle": "hp", "mother_handle": "hm",
           "child_ref_list": [{"ref": "hc1"}, {"ref": "hc2"}],
           "extended": {"events": [
               {"type": "Marriage",
                "date": {"sortval": 2350000, "year": 1740, "dateval": [], "modifier": 0, "quality": 0}}]}}
    f = family_from_json(raw)
    assert f.father_handle == "hp" and f.mother_handle == "hm"
    assert f.child_handles == ["hc1", "hc2"] and f.marriage.year == 1740


def test_get_person_facts_is_cached():
    calls = {"n": 0}

    def handler(request):
        if request.url.path == "/api/token/":
            return httpx.Response(200, json={"access_token": "t"})
        calls["n"] += 1
        return httpx.Response(200, json=PERSON_RAW)

    client = GrampsClient(CONFIG, transport=httpx.MockTransport(handler))
    fetcher = FactsFetcher(client)
    a = fetcher.get_person_facts("h1")
    b = fetcher.get_person_facts("h1")
    assert a.gramps_id == b.gramps_id == "I0001"
    assert calls["n"] == 1                       # deuxième appel servi par le cache
```

- [ ] **Step 2 : Vérifier l'échec**

```bash
uv run python -m pytest genecrew/tests/test_facts.py -v
```

Attendu : ÉCHEC — module absent.

- [ ] **Step 3 : Implémenter** — `genecrew/src/genecrew/facts.py` :

```python
"""Build normalized PersonFacts / FamilyFacts from the Gramps Web API.

Pure mappers (`person_from_json` / `family_from_json`) plus a `FactsFetcher`
that performs the I/O and caches related-person lookups. One list call per page
uses `profile=all&extend=event_ref_list`, so vital dates (raw, with sortval)
and citation counts arrive together.
"""

from __future__ import annotations

from crewai_custom_tools.tools.genealogy.gramps.client import GrampsClient
from crewai_custom_tools.tools.genealogy.models.domain import (
    EventFact, FamilyFacts, PersonFacts,
)

_SEX = {0: "F", 1: "M", 2: "U"}
_LIST_PARAMS = {"profile": "all", "extend": "event_ref_list", "sort": "gramps_id"}


def _event_from_raw(raw: dict) -> EventFact:
    date = raw.get("date") or {}
    return EventFact(
        type=raw.get("type", ""),
        sortval=date.get("sortval", 0) or 0,
        year=date.get("year"),
        modifier=date.get("modifier", 0) or 0,
        quality=date.get("quality", 0) or 0,
        dateval=date.get("dateval") or [],
        has_citation=bool(raw.get("citation_list")),
    )


def person_from_json(raw: dict) -> PersonFacts:
    """Map one raw person (profile=all & extend=event_ref_list) to PersonFacts."""
    name = raw.get("primary_name") or {}
    surnames = name.get("surname_list") or [{}]
    surname = surnames[0].get("surname", "") if surnames else ""
    given = name.get("first_name", "")
    events = [_event_from_raw(e) for e in (raw.get("extended") or {}).get("events", [])]

    bi, di = raw.get("birth_ref_index", -1), raw.get("death_ref_index", -1)
    birth = events[bi] if 0 <= bi < len(events) else None
    death = events[di] if 0 <= di < len(events) else None

    profile = raw.get("profile") or {}
    prof_cites = sum((profile.get(k) or {}).get("citations", 0) for k in ("birth", "death"))
    has_cite = bool(raw.get("citation_list")) or prof_cites > 0 or any(e.has_citation for e in events)

    return PersonFacts(
        gramps_id=raw.get("gramps_id", ""), handle=raw.get("handle", ""),
        name=f"{given} {surname}".strip(), surname=surname, given=given,
        sex=_SEX.get(raw.get("gender", 2), "U"),
        birth=birth, death=death, events=events, has_any_citation=has_cite,
        parent_family_handles=list(raw.get("parent_family_list") or []),
        family_handles=list(raw.get("family_list") or []),
    )


def family_from_json(raw: dict) -> FamilyFacts:
    """Map one raw family (extend=event_ref_list) to FamilyFacts."""
    events = [_event_from_raw(e) for e in (raw.get("extended") or {}).get("events", [])]
    marriage = next((e for e in events if e.type == "Marriage"), None)
    return FamilyFacts(
        gramps_id=raw.get("gramps_id", ""), handle=raw.get("handle", ""),
        father_handle=raw.get("father_handle"), mother_handle=raw.get("mother_handle"),
        child_handles=[c["ref"] for c in (raw.get("child_ref_list") or []) if "ref" in c],
        marriage=marriage,
    )


class FactsFetcher:
    """I/O layer: fetches raw JSON and caches per-handle person/family facts."""

    def __init__(self, client: GrampsClient) -> None:
        self._client = client
        self._people: dict[str, PersonFacts] = {}
        self._families: dict[str, FamilyFacts] = {}

    def list_people_facts(self, page: int, pagesize: int) -> list[PersonFacts]:
        raw = self._client.get_json(
            "/people/", params={**_LIST_PARAMS, "page": page, "pagesize": pagesize})
        facts = [person_from_json(r) for r in raw]
        for f in facts:
            self._people[f.handle] = f
        return facts

    def get_person_facts(self, handle: str) -> PersonFacts | None:
        if handle not in self._people:
            raw = self._client.get_json(
                f"/people/{handle}", params={"profile": "all", "extend": "event_ref_list"})
            self._people[handle] = person_from_json(raw)
        return self._people.get(handle)

    def get_family_facts(self, handle: str) -> FamilyFacts | None:
        if handle not in self._families:
            raw = self._client.get_json(
                f"/families/{handle}", params={"extend": "event_ref_list"})
            self._families[handle] = family_from_json(raw)
        return self._families.get(handle)
```

- [ ] **Step 4 : Vérifier le succès**

```bash
uv run python -m pytest genecrew/tests/test_facts.py -v
```

Attendu : 4 PASS.

- [ ] **Step 5 : Commit**

```bash
git add genecrew/src/genecrew/facts.py genecrew/tests/test_facts.py
git commit -m "feat(audit): build PersonFacts/FamilyFacts from Gramps API"
```

---

### Task 8 : genecrew — rapport Markdown (`report.py`, pur)

**Files:**

- Create: `genecrew/src/genecrew/report.py`
- Test: `genecrew/tests/test_report.py`

**Interfaces:**

- Consumes : `Anomaly`, `DuplicateCandidate`.
- Produces : `render_report(scope: str, date: str, anomalies: list[Anomaly], duplicates: list[DuplicateCandidate], people_count: int, base_url: str = "http://localhost") -> str` (pur).

Format : titre + synthèse (compte par sévérité) + tableau des anomalies trié `haute > moyenne > basse` (colonnes : personne avec lien `<base_url>/person/<gramps_id>`, règle, message) + section doublons triée par score décroissant.

- [ ] **Step 1 : Test qui échoue** — `genecrew/tests/test_report.py` :

```python
from crewai_custom_tools.tools.genealogy.models.domain import Anomaly, DuplicateCandidate
from genecrew.report import render_report


def _a(rule, sev, gid, msg):
    return Anomaly(rule=rule, severity=sev, gramps_id=gid, handle=gid, message=msg)


def test_report_orders_by_severity_and_counts():
    anoms = [_a("R9", "basse", "I3", "sans source"),
             _a("R1", "haute", "I1", "naissance après décès"),
             _a("R6", "moyenne", "I2", "événement hors vie")]
    out = render_report("all", "2026-07-17", anoms, [], people_count=3)
    assert "# Audit qualité" in out
    # la ligne haute apparaît avant la moyenne, qui apparaît avant la basse
    assert out.index("I1") < out.index("I2") < out.index("I3")
    assert "1 haute" in out and "1 moyenne" in out and "1 basse" in out


def test_report_includes_person_links_and_duplicates():
    dups = [DuplicateCandidate(gramps_id_a="I1", gramps_id_b="I2", score=0.92,
                               reason="homonymes")]
    out = render_report("all", "2026-07-17", [], dups, people_count=2)
    assert "http://localhost/person/I1" in out
    assert "0.92" in out


def test_report_empty_is_clean():
    out = render_report("branch:I0042", "2026-07-17", [], [], people_count=0)
    assert "Aucune anomalie" in out
```

- [ ] **Step 2 : Vérifier l'échec**

```bash
uv run python -m pytest genecrew/tests/test_report.py -v
```

Attendu : ÉCHEC — module absent.

- [ ] **Step 3 : Implémenter** — `genecrew/src/genecrew/report.py` :

```python
"""Pure Markdown rendering of an audit run (no I/O)."""

from __future__ import annotations

from crewai_custom_tools.tools.genealogy.models.domain import Anomaly, DuplicateCandidate

_SEVERITY_ORDER = {"haute": 0, "moyenne": 1, "basse": 2}


def _link(gramps_id: str, base_url: str) -> str:
    return f"[{gramps_id}]({base_url}/person/{gramps_id})"


def render_report(
    scope: str, date: str, anomalies: list[Anomaly],
    duplicates: list[DuplicateCandidate], people_count: int,
    base_url: str = "http://localhost",
) -> str:
    counts = {"haute": 0, "moyenne": 0, "basse": 0}
    for a in anomalies:
        counts[a.severity] = counts.get(a.severity, 0) + 1

    lines = [
        f"# Audit qualité — {scope} — {date}", "",
        "## Synthèse", "",
        f"- Personnes analysées : {people_count}",
        f"- Anomalies : {len(anomalies)} "
        f"({counts['haute']} haute, {counts['moyenne']} moyenne, {counts['basse']} basse)",
        f"- Candidats doublons : {len(duplicates)}", "",
    ]

    lines.append("## Anomalies")
    lines.append("")
    if anomalies:
        ordered = sorted(anomalies, key=lambda a: (_SEVERITY_ORDER.get(a.severity, 9), a.gramps_id))
        lines += ["| Personne | Sévérité | Règle | Détail |", "|---|---|---|---|"]
        for a in ordered:
            lines.append(f"| {_link(a.gramps_id, base_url)} | {a.severity} | {a.rule} | {a.message} |")
    else:
        lines.append("Aucune anomalie détectée.")
    lines.append("")

    lines.append("## Candidats doublons")
    lines.append("")
    if duplicates:
        lines += ["| Personne A | Personne B | Score | Motif |", "|---|---|---|---|"]
        for d in sorted(duplicates, key=lambda x: -x.score):
            lines.append(f"| {_link(d.gramps_id_a, base_url)} | {_link(d.gramps_id_b, base_url)} "
                         f"| {d.score} | {d.reason} |")
    else:
        lines.append("Aucun doublon candidat.")
    lines.append("")
    return "\n".join(lines)
```

- [ ] **Step 4 : Vérifier le succès**

```bash
uv run python -m pytest genecrew/tests/test_report.py -v
```

Attendu : 3 PASS.

- [ ] **Step 5 : Commit**

```bash
git add genecrew/src/genecrew/report.py genecrew/tests/test_report.py
git commit -m "feat(audit): pure Markdown report renderer"
```

---

### Task 9 : genecrew — résolution de périmètre (`scope.py`)

**Files:**

- Create: `genecrew/src/genecrew/scope.py`
- Test: `genecrew/tests/test_scope.py`

**Interfaces:**

- Consumes : `GrampsClient`.
- Produces : `parse_scope(spec: str) -> tuple[str, str | None]` (pur ; rend `("all", None)`, `("person", "I0042")`, ou `("branch", "I0042")`) ; `resolve_handles(client, spec: str, limit: int | None = None) -> list[tuple[str, str]]` (I/O ; rend une liste triée de `(handle, gramps_id)`).

Périmètre 1a : `all` (toutes les personnes paginées) et `person:I0042` (une personne). Le mode `branch:` est **reporté** (nécessite le graphe de parenté) et lèvera `NotImplementedError` avec un message clair — la Phase 1b l'ajoutera. `all` avec `--limit N` s'arrête après N personnes (utile pour valider vite sur un échantillon).

- [ ] **Step 1 : Test qui échoue** — `genecrew/tests/test_scope.py` :

```python
import httpx
import pytest

from genecrew.scope import parse_scope, resolve_handles
from crewai_custom_tools.tools.genealogy.gramps.client import GrampsClient, GrampsConfig

CONFIG = GrampsConfig(api_url="http://g.test/api", username="u", password="p")


def test_parse_scope_variants():
    assert parse_scope("all") == ("all", None)
    assert parse_scope("person:I0042") == ("person", "I0042")
    assert parse_scope("branch:I0042") == ("branch", "I0042")


def test_resolve_person_scope_single():
    def handler(request):
        if request.url.path == "/api/token/":
            return httpx.Response(200, json={"access_token": "t"})
        assert request.url.params["gramps_id"] == "I0042"
        return httpx.Response(200, json=[{"handle": "h42", "gramps_id": "I0042"}])

    client = GrampsClient(CONFIG, transport=httpx.MockTransport(handler))
    assert resolve_handles(client, "person:I0042") == [("h42", "I0042")]


def test_resolve_all_paginates_until_empty_and_respects_limit():
    pages = {1: [{"handle": f"h{i}", "gramps_id": f"I{i}"} for i in range(25)],
             2: [{"handle": f"h{i}", "gramps_id": f"I{i}"} for i in range(25, 40)],
             3: []}

    def handler(request):
        if request.url.path == "/api/token/":
            return httpx.Response(200, json={"access_token": "t"})
        page = int(request.url.params["page"])
        return httpx.Response(200, json=pages.get(page, []))

    client = GrampsClient(CONFIG, transport=httpx.MockTransport(handler))
    got = resolve_handles(client, "all", limit=30)
    assert len(got) == 30 and got[0] == ("h0", "I0")


def test_branch_scope_not_implemented():
    client = GrampsClient(CONFIG, transport=httpx.MockTransport(lambda r: httpx.Response(200, json={"access_token": "t"})))
    with pytest.raises(NotImplementedError):
        resolve_handles(client, "branch:I0042")
```

- [ ] **Step 2 : Vérifier l'échec**

```bash
uv run python -m pytest genecrew/tests/test_scope.py -v
```

Attendu : ÉCHEC — module absent.

- [ ] **Step 3 : Implémenter** — `genecrew/src/genecrew/scope.py` :

```python
"""Resolve an audit scope specification into an ordered list of person handles."""

from __future__ import annotations

from crewai_custom_tools.tools.genealogy.gramps.client import GrampsClient

_PAGESIZE = 200


def parse_scope(spec: str) -> tuple[str, str | None]:
    """Parse 'all' | 'person:<id>' | 'branch:<id>' into (kind, gramps_id)."""
    if spec == "all":
        return ("all", None)
    if ":" in spec:
        kind, _, gid = spec.partition(":")
        if kind in ("person", "branch"):
            return (kind, gid)
    raise ValueError(f"Périmètre invalide : {spec!r} (attendu 'all', 'person:ID', 'branch:ID')")


def resolve_handles(
    client: GrampsClient, spec: str, limit: int | None = None
) -> list[tuple[str, str]]:
    """Return sorted (handle, gramps_id) pairs for the given scope."""
    kind, gid = parse_scope(spec)
    if kind == "person":
        raw = client.get_json("/people/", params={"gramps_id": gid})
        return [(r["handle"], r["gramps_id"]) for r in raw]
    if kind == "branch":
        raise NotImplementedError(
            "Le périmètre 'branch:' arrive en Phase 1b (graphe de parenté).")
    # kind == "all" : pagination jusqu'à épuisement
    out: list[tuple[str, str]] = []
    page = 1
    while True:
        raw = client.get_json(
            "/people/", params={"page": page, "pagesize": _PAGESIZE, "sort": "gramps_id"})
        if not raw:
            break
        out.extend((r["handle"], r["gramps_id"]) for r in raw)
        if limit is not None and len(out) >= limit:
            return out[:limit]
        page += 1
    return out
```

- [ ] **Step 4 : Vérifier le succès**

```bash
uv run python -m pytest genecrew/tests/test_scope.py -v
```

Attendu : 4 PASS.

- [ ] **Step 5 : Commit**

```bash
git add genecrew/src/genecrew/scope.py genecrew/tests/test_scope.py
git commit -m "feat(audit): scope resolution (all + person; branch deferred)"
```

---

### Task 10 : genecrew — moteur d'audit (`audit.py`)

**Files:**

- Create: `genecrew/src/genecrew/audit.py`
- Test: `genecrew/tests/test_audit.py`

**Interfaces:**

- Consumes : `FactsFetcher` (T7), `resolve_handles` (T9), `check_person`/`check_family` (T2/T3), `find_duplicates` (T4), `render_report` (T8), `Checkpoint`/`save_checkpoint`/`load_checkpoint` (T6).
- Produces : `run_audit(client, scope: str, output_dir: Path, *, date: str, batch_size: int = 25, limit: int | None = None, resume: bool = False) -> Path` (écrit le rapport, rend son chemin).

Logique : résoudre les handles → parcourir par lots de `batch_size` → pour chaque lot, charger les `PersonFacts` (via `get_person_facts`, qui remplit le cache), appliquer `check_person` ; collecter les handles de familles des personnes du lot, charger `FamilyFacts` + les `PersonFacts` liés, appliquer `check_family` (dédupliquer les familles déjà vues) ; accumuler les `PersonFacts` pour `find_duplicates` en fin de run ; écrire un checkpoint après chaque lot ; rendre le rapport.

- [ ] **Step 1 : Test qui échoue** — `genecrew/tests/test_audit.py` (client mické, arbre minuscule avec une anomalie R1 connue) :

```python
import httpx

from genecrew.audit import run_audit
from crewai_custom_tools.tools.genealogy.gramps.client import GrampsClient, GrampsConfig

CONFIG = GrampsConfig(api_url="http://g.test/api", username="u", password="p")

# Une personne avec naissance (1850) APRÈS décès (1820) → R1 attendu.
PERSON = {
    "gramps_id": "I0001", "handle": "h1", "gender": 1, "citation_list": ["c"],
    "family_list": [], "parent_family_list": [], "birth_ref_index": 0, "death_ref_index": 1,
    "primary_name": {"first_name": "Jean", "surname_list": [{"surname": "Test"}]},
    "profile": {"birth": {"citations": 1}, "death": {"citations": 1}},
    "event_ref_list": [{"ref": "e1"}, {"ref": "e2"}],
    "extended": {"events": [
        {"type": "Birth", "citation_list": ["c"],
         "date": {"sortval": 2396758, "year": 1850, "dateval": [1, 1, 1850, False], "modifier": 0, "quality": 0}},
        {"type": "Death", "citation_list": ["c"],
         "date": {"sortval": 2385800, "year": 1820, "dateval": [1, 1, 1820, False], "modifier": 0, "quality": 0}},
    ]},
}


def _handler(request):
    if request.url.path == "/api/token/":
        return httpx.Response(200, json={"access_token": "t"})
    path = request.url.path
    if path == "/api/people/" and "gramps_id" not in request.url.params:
        page = int(request.url.params.get("page", 1))
        # liste de scope (sans profile) page 1 = [I0001], page 2 = []
        if "profile" not in request.url.params:
            return httpx.Response(200, json=[{"handle": "h1", "gramps_id": "I0001"}] if page == 1 else [])
        # liste de faits (avec profile) — non utilisée ici car get_person_facts va par handle
        return httpx.Response(200, json=[PERSON] if page == 1 else [])
    if path == "/api/people/h1":
        return httpx.Response(200, json=PERSON)
    return httpx.Response(200, json=[])


def test_run_audit_writes_report_with_r1(tmp_path):
    client = GrampsClient(CONFIG, transport=httpx.MockTransport(_handler))
    report_path = run_audit(client, "all", tmp_path, date="2026-07-17", batch_size=25)
    assert report_path.exists()
    text = report_path.read_text(encoding="utf-8")
    assert "R1" in text and "I0001" in text
    # un checkpoint a été écrit
    assert (tmp_path / "checkpoints").exists()


def test_run_audit_resume_skips_done(tmp_path):
    client = GrampsClient(CONFIG, transport=httpx.MockTransport(_handler))
    # premier run
    run_audit(client, "all", tmp_path, date="2026-07-17", batch_size=25)
    # second run avec resume : ne doit pas replanter et reproduire un rapport
    p = run_audit(client, "all", tmp_path, date="2026-07-18", batch_size=25, resume=True)
    assert p.exists()
```

- [ ] **Step 2 : Vérifier l'échec**

```bash
uv run python -m pytest genecrew/tests/test_audit.py -v
```

Attendu : ÉCHEC — module absent.

- [ ] **Step 3 : Implémenter** — `genecrew/src/genecrew/audit.py` :

```python
"""Deterministic audit engine: batches → rules → Markdown report (no LLM)."""

from __future__ import annotations

from pathlib import Path

from crewai_custom_tools.tools.genealogy.analysis.duplicates import find_duplicates
from crewai_custom_tools.tools.genealogy.analysis.rules import check_family, check_person
from crewai_custom_tools.tools.genealogy.gramps.client import GrampsClient

from genecrew.checkpoint import Checkpoint, load_checkpoint, save_checkpoint
from genecrew.facts import FactsFetcher
from genecrew.report import render_report
from genecrew.scope import resolve_handles


def _batches(items, size):
    for i in range(0, len(items), size):
        yield items[i:i + size]


def run_audit(
    client: GrampsClient, scope: str, output_dir: Path, *,
    date: str, batch_size: int = 25, limit: int | None = None, resume: bool = False,
) -> Path:
    """Run the deterministic audit over `scope` and write a Markdown report."""
    output_dir = Path(output_dir)
    cp_path = output_dir / "checkpoints" / f"audit_{scope.replace(':', '_')}.json"
    checkpoint = load_checkpoint(cp_path) if resume else None
    if checkpoint is None:
        checkpoint = Checkpoint(workflow="audit", scope=scope)

    fetcher = FactsFetcher(client)
    handles = resolve_handles(client, scope, limit=limit)

    anomalies = []
    all_people = []
    seen_families: set[str] = set()

    for batch in _batches(handles, batch_size):
        batch_people = []
        for handle, _gid in batch:
            if handle in checkpoint.done_handles:
                continue
            person = fetcher.get_person_facts(handle)
            if person is None:
                continue
            batch_people.append(person)
            anomalies.extend(check_person(person))

        for person in batch_people:
            for fam_handle in person.parent_family_handles:
                if fam_handle in seen_families:
                    continue
                seen_families.add(fam_handle)
                family = fetcher.get_family_facts(fam_handle)
                if family is None:
                    continue
                related = {}
                for h in filter(None, [family.father_handle, family.mother_handle,
                                        *family.child_handles]):
                    pf = fetcher.get_person_facts(h)
                    if pf is not None:
                        related[h] = pf
                anomalies.extend(check_family(family, related))

        all_people.extend(batch_people)
        checkpoint.done_handles.update(h for h, _ in batch)
        save_checkpoint(cp_path, checkpoint)

    duplicates = find_duplicates(all_people)
    report = render_report(scope, date, anomalies, duplicates, people_count=len(all_people))

    report_dir = output_dir / "audit"
    report_dir.mkdir(parents=True, exist_ok=True)
    report_path = report_dir / f"{date}_audit_{scope.replace(':', '_')}.md"
    report_path.write_text(report, encoding="utf-8")
    return report_path
```

- [ ] **Step 4 : Vérifier le succès**

```bash
uv run python -m pytest genecrew/tests/test_audit.py -v
```

Attendu : 2 PASS.

- [ ] **Step 5 : Commit**

```bash
git add genecrew/src/genecrew/audit.py genecrew/tests/test_audit.py
git commit -m "feat(audit): deterministic audit engine (batches, checkpoints, report)"
```

---

### Task 11 : genecrew — sous-commande CLI `audit`

**Files:**

- Modify: `genecrew/src/genecrew/main.py` (ajouter le sous-parseur `audit` et sa fonction)
- Test: `genecrew/tests/test_cli_audit.py`

**Interfaces:**

- Consumes : `run_audit` (T10), `GrampsClient`/`GrampsConfig`.
- Produces : commande `uv run genecrew audit --scope <all|person:ID> [--limit N] [--batch-size 25] [--resume]`.

- [ ] **Step 1 : Test qui échoue** — `genecrew/tests/test_cli_audit.py` :

```python
import subprocess
import sys


def test_audit_help_lists_options():
    out = subprocess.run(
        [sys.executable, "-m", "genecrew.main", "audit", "--help"],
        capture_output=True, text=True, cwd="genecrew/src",
    )
    assert out.returncode == 0
    assert "--scope" in out.stdout and "--resume" in out.stdout
```

Note : `main.py` doit rester exécutable en module ; ajouter `if __name__ == "__main__": main()` en fin de fichier s'il n'y est pas.

- [ ] **Step 2 : Vérifier l'échec**

```bash
uv run python -m pytest genecrew/tests/test_cli_audit.py -v
```

Attendu : ÉCHEC (retour non nul ou `audit` inconnu).

- [ ] **Step 3 : Implémenter** — dans `genecrew/src/genecrew/main.py`, ajouter une fonction `audit_cmd` et l'enregistrer dans `main()` :

```python
def audit_cmd(args) -> None:
    """Run the deterministic audit and print the report path."""
    import os
    from pathlib import Path

    from crewai_custom_tools.tools.genealogy.gramps.client import GrampsClient, GrampsConfig

    from genecrew.audit import run_audit

    client = GrampsClient(GrampsConfig.from_env())
    output_dir = Path(os.environ.get("GENECREW_OUTPUT_DIR", "output"))
    date = args.date or __import__("datetime").date.today().isoformat()
    path = run_audit(
        client, args.scope, output_dir, date=date,
        batch_size=args.batch_size, limit=args.limit, resume=args.resume,
    )
    print(f"Rapport écrit : {path}")
```

Dans `main()`, après le sous-parseur `stats`, ajouter :

```python
    audit_p = sub.add_parser("audit", help="Audit qualité déterministe (sans LLM)")
    audit_p.add_argument("--scope", default="all",
                         help="all | person:ID (branch:ID en Phase 1b)")
    audit_p.add_argument("--limit", type=int, default=None,
                         help="limiter à N personnes (échantillon)")
    audit_p.add_argument("--batch-size", type=int,
                         default=int(os.environ.get("GENECREW_BATCH_SIZE", "25")))
    audit_p.add_argument("--resume", action="store_true",
                         help="reprendre depuis le dernier checkpoint")
    audit_p.add_argument("--date", default=None, help="date du rapport (défaut : aujourd'hui)")
```

et dans le dispatch : `elif args.command == "audit": audit_cmd(args)`. Ajouter `import os` en tête de `main.py` s'il manque (il est déjà importé pour la Phase 0).

- [ ] **Step 4 : Vérifier le succès**

```bash
uv run python -m pytest genecrew/tests/test_cli_audit.py -v
uv run genecrew audit --help
```

Attendu : test PASS ; l'aide affiche `--scope`, `--limit`, `--batch-size`, `--resume`, `--date`.

- [ ] **Step 5 : Commit**

```bash
git add genecrew/src/genecrew/main.py genecrew/tests/test_cli_audit.py
git commit -m "feat(audit): CLI sous-commande genecrew audit"
```

---

### Task 12 : Validation terrain + documentation

**Files:**

- Create: `docs/adr/0006-audit-deterministe-personfacts.md`
- Modify: `docs/USER_GUIDE.md` (section Phase 1a)

**Interfaces:** aucune ; c'est le **critère de sortie** de la Phase 1a + la doc.

- [ ] **Step 1 : Exécution réelle sur un échantillon**

```bash
cd /Users/fjacquet/Projects/genecrew
uv run genecrew audit --scope all --limit 200
```

Attendu : un rapport `output/audit/AAAA-MM-JJ_audit_all.md` en quelques secondes, sans coût LLM. Ouvrir le rapport, examiner les anomalies. **Critère de sortie (spec §9 Phase 1)** : les anomalies de gravité haute correspondent à de vrais problèmes de l'arbre (ou des faux positifs explicables), le taux de faux positifs est acceptable. Noter le temps d'exécution et le nombre d'anomalies par règle dans le rapport de tâche.

- [ ] **Step 2 : Suite complète des deux dépôts**

```bash
uv run python -m pytest genecrew/tests/ -q
(cd /Users/fjacquet/Projects/crewai_custom_tools && uv run python -m pytest -q)
```

Attendu : tout passe.

- [ ] **Step 3 : ADR 0006** — `docs/adr/0006-audit-deterministe-personfacts.md`, format Contexte / Décision / Conséquences, Statut Accepté, date 2026-07-17. Décision : les règles opèrent sur un modèle normalisé `PersonFacts`/`FamilyFacts` construit depuis `profile=all&extend=event_ref_list` ; les comparaisons de dates utilisent le `sortval` Gramps (jour julien) ; les règles sont des fonctions pures hors-ligne, la Phase 1a n'a ni LLM ni écriture. Citer les règles R1–R10 depuis `document-de-travail.md` §6.1.

- [ ] **Step 4 : USER_GUIDE** — ajouter une section « Phase 1a — Audit déterministe » : prérequis (Phase 0 opérationnelle), commande `uv run genecrew audit --scope all --limit 200`, où trouver le rapport (`output/audit/`), comment lire les sévérités, et la note « aucun coût LLM, aucune écriture dans Gramps à ce stade ». Conserver la promesse « chaque phase ajoute sa section ».

- [ ] **Step 5 : Commit**

```bash
git add docs/adr/0006-audit-deterministe-personfacts.md docs/USER_GUIDE.md
git commit -m "docs: ADR 0006 audit déterministe + USER_GUIDE Phase 1a"
```

---

## Self-Review (fait à l'écriture du plan)

- **Couverture spec §6.1** : R1–R10 couvertes — R1,R2,R6,R7,R8,R9 (T2), R3,R4,R5 (T3), R10 (T4). Orchestration/lots/reprise (§6.5) : T6,T9,T10. Rapport Markdown + liens Gramps (§8) : T8. Critère de sortie (§9) : T12.
- **Hors périmètre assumé (YAGNI, → Phase 1b)** : crew LLM, agents.yaml/tasks, `BaseTool` `GenealogyConsistencyTool`/`DuplicateFinderTool`, écritures (tags `ia-anomalie`/notes), PDF, périmètre `branch:`, propositions YAML. Explicitement notés.
- **Placeholders** : aucun — tout le code est fourni.
- **Cohérence des types** : `PersonFacts`/`FamilyFacts`/`Anomaly`/`DuplicateCandidate` (T1) consommés partout ; `check_person`/`check_family` (T2/T3) et `find_duplicates` (T4) consommés par `run_audit` (T10) ; `FactsFetcher.get_person_facts`/`get_family_facts` (T7) et `resolve_handles` (T9) consommés par T10 ; `render_report` (T8) signature alignée sur son appel dans T10 ; `sortval`/`year`/`modifier`/`quality`/`dateval` cohérents entre `EventFact` (T1), les règles (T2/T3) et le mapping (T7).
- **Décision de conception à valider en terrain (T12)** : les seuils (105 ans, ±2 ans doublons, 280 j) viennent de la spec ; leur pertinence réelle se juge sur le rapport de T12 et s'ajuste si trop de faux positifs.
