# Import de relevés collés avec smart match — plan d'implémentation

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `genecrew import releve` lit un relevé collé, l'apparie à l'arbre par une règle pondérée déterministe, et écrit les correspondances nettes avec leur citation.

**Architecture:** Deux modules dans genecrew. `releves.py` porte les modèles et le moteur d'appariement — **pur, sans réseau, testable hors-ligne**. `releves_import.py` porte l'orchestration : l'appel LLM d'interprétation, la collecte Gramps, l'écriture et le rapport. Le LLM lit ; il ne décide pas.

**Tech Stack:** Python 3.12, pydantic v2, argparse, httpx (`MockTransport` en test), pytest, `crewai_custom_tools` (client Gramps, `PersonFacts`, `effective_dry_run`, outils d'écriture).

## Global Constraints

- Spec de référence : `docs/superpowers/specs/2026-07-20-import-releves-smart-match-design.md`.
- Tout le code neuf vit dans `genecrew/src/genecrew/` — **aucune extraction vers `crewai_custom_tools`** (elle se fera si une deuxième source de relevés apparaît).
- Docstrings et messages utilisateur **en français**, comme le reste du dépôt.
- `from __future__ import annotations` en tête de chaque module neuf.
- Tests **hors-ligne** : jamais d'appel réseau réel. Gramps via `httpx.MockTransport`, LLM via stub.
- Toute écriture passe par `effective_dry_run(dry_run)` — **la simulation est le défaut** quand `GENECREW_DRY_RUN` est absent.
- Aucun verbe CLI nouveau : `import releve` est une feuille sous le verbe `import` existant (ADR 0012).
- Commandes lancées **depuis la racine du dépôt** : `uv run python -m pytest genecrew/tests/ -q`.
- Fixture de référence : le relevé Rose JACQUET, CGHB, réf. `106710046161418286`.

---

## File Structure

| Fichier | Responsabilité |
| --- | --- |
| `genecrew/src/genecrew/releves.py` | Modèles (`ReleveIndexe`, `Appariement`) + moteur d'appariement pur : rareté, blocage, pondération, verdict |
| `genecrew/src/genecrew/releves_import.py` | Orchestration : parse LLM, collecte Gramps, idempotence, écriture, rapport |
| `genecrew/src/genecrew/cli.py` | +1 feuille `import releve` |
| `genecrew/src/genecrew/main.py` | +1 entrée dans la table de dispatch |
| `genecrew/tests/test_releves.py` | Tests du moteur pur |
| `genecrew/tests/test_releves_import.py` | Tests d'orchestration et d'écriture |

Le partage suit la convention du dépôt (`deces.py`/`deces_apply.py`, `places.py`/`places_apply.py`) : la règle d'un côté, l'effet de bord de l'autre.

---

### Task 1: Modèles d'entrée et de verdict

**Files:**
- Create: `genecrew/src/genecrew/releves.py`
- Test: `genecrew/tests/test_releves.py`

**Interfaces:**
- Consomme : rien.
- Produit : `FacteurReleve` (Literal fermé), `POIDS`, `FACTEURS_FORTS`, `SEUIL_NET`, `PersonneLiee`, `ReleveIndexe`, `Appariement`.

- [ ] **Step 1: Write the failing test**

```python
"""Tests hors-ligne du moteur d'appariement des relevés (pur, sans réseau)."""

import pytest
from pydantic import ValidationError

from genecrew.releves import Appariement, PersonneLiee, ReleveIndexe


def test_releve_indexe_minimal():
    r = ReleveIndexe(
        fonds="Cercle Généalogique du Haut-Berry", reference="106710046161418286",
        sujet_nom="JACQUET", sujet_prenom="Rose", evenement_type="Death",
        texte_brut="Rose JACQUET\nLe 10 décembre 1894",
    )
    assert r.evenement_date == ""
    assert r.personnes_liees == []


def test_personne_liee_porte_son_role():
    p = PersonneLiee(nom="Pierre JACQUET", role="père", detail="décédé avant 1894")
    assert p.role == "père"


def test_facteur_hors_vocabulaire_refuse():
    """Vocabulaire fermé : « né en 1821 » ne doit pas pouvoir gonfler un score."""
    with pytest.raises(ValidationError):
        Appariement(verdict="net", facteurs=["né en 1821"])


def test_annee_approximative_est_un_facteur_distinct_de_la_date():
    """Règle projet : une année seule n'est jamais discriminante."""
    a = Appariement(verdict="gris", facteurs=["année approximative"])
    assert "date complète" not in a.facteurs
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run python -m pytest genecrew/tests/test_releves.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'genecrew.releves'`

- [ ] **Step 3: Write minimal implementation**

```python
"""Appariement d'un relevé collé avec les personnes de l'arbre.

Le moteur est PUR : aucun appel réseau, aucune écriture. C'est ce qui le rend
testable hors-ligne et auditable ligne à ligne — un verdict doit toujours pouvoir
s'expliquer par les facteurs qui l'ont produit.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

FacteurReleve = Literal[
    "parent nommé", "date complète", "lieu", "patronyme rare",
    "prénom", "année approximative",
]
"""Vocabulaire fermé des facteurs qu'un appariement peut invoquer.

Clos volontairement, sur le procédé de `FacteurConcordance` : un relevé qui
voudrait faire valoir « né vers 1821 » se fait refuser par pydantic plutôt que
de gonfler son poids. L'année approximative y figure, mais comme facteur FAIBLE
et distinct de la date — une année seule n'est jamais discriminante.
"""

POIDS: dict[str, int] = {
    "parent nommé": 5,
    "date complète": 5,
    "lieu": 3,
    "patronyme rare": 3,
    "prénom": 1,
    "année approximative": 1,
}

FACTEURS_FORTS: frozenset[str] = frozenset(
    {"parent nommé", "date complète", "lieu", "patronyme rare"})

SEUIL_NET = 8
"""Poids minimal d'un verdict `net`. Atteignable par deux facteurs forts, jamais
par un empilement de faibles (voir `apparier`)."""


class PersonneLiee(BaseModel):
    """Une personne citée par le relevé sans en être le sujet."""

    nom: str
    role: str = Field(description="père | mère | conjoint | témoin | autre")
    detail: str = ""


class ReleveIndexe(BaseModel):
    """Le relevé, une fois interprété. Le texte brut est conservé intégralement."""

    fonds: str
    reference: str
    sujet_nom: str
    sujet_prenom: str
    evenement_type: str = Field(description="Death | Birth | Marriage")
    evenement_date: str = ""            # ISO "1894-12-10", "" si absente
    evenement_lieu: str = ""
    naissance_estimee: int | None = None
    personnes_liees: list[PersonneLiee] = Field(default_factory=list)
    texte_brut: str


class Appariement(BaseModel):
    """Le verdict, et surtout ce qui l'a produit."""

    verdict: Literal["net", "gris", "aucun"]
    gramps_id: str | None = None
    handle: str | None = None
    facteurs: list[FacteurReleve] = Field(default_factory=list)
    divergences: list[str] = Field(default_factory=list)
    poids: int = 0
    candidats: list[str] = Field(default_factory=list)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run python -m pytest genecrew/tests/test_releves.py -q`
Expected: PASS (4 tests)

- [ ] **Step 5: Commit**

```bash
git add genecrew/src/genecrew/releves.py genecrew/tests/test_releves.py
git commit -m "feat(releves): modèles d'entrée et de verdict, vocabulaire fermé"
```

---

### Task 2: Rareté du patronyme, comptée sur l'arbre

**Files:**
- Modify: `genecrew/src/genecrew/releves.py`
- Test: `genecrew/tests/test_releves.py`

**Interfaces:**
- Consomme : `PersonFacts` (`crewai_custom_tools.tools.genealogy.models.domain`).
- Produit : `rarete_patronymes(people) -> dict[str, float]`, `est_rare(surname, rarete, seuil=0.02) -> bool`.

- [ ] **Step 1: Write the failing test**

Ajouter à `genecrew/tests/test_releves.py` :

```python
from crewai_custom_tools.tools.genealogy.models.domain import PersonFacts

from genecrew.releves import est_rare, rarete_patronymes


def _p(gramps_id, surname, given, **kw):
    return PersonFacts(gramps_id=gramps_id, handle=f"h{gramps_id}",
                       name=f"{given} {surname}", surname=surname, given=given,
                       sex=kw.pop("sex", "U"), **kw)


def test_rarete_est_une_fraction_de_l_arbre():
    people = [_p("I1", "JACQUET", "Rose"), _p("I2", "JACQUET", "Pierre"),
              _p("I3", "JACQUET", "Jean"), _p("I4", "VILLEPELLET", "Marie")]
    r = rarete_patronymes(people)
    assert r["JACQUET"] == 0.75
    assert r["VILLEPELLET"] == 0.25


def test_rarete_ignore_casse_et_accents():
    people = [_p("I1", "Jacquet", "Rose"), _p("I2", "JACQUET", "Pierre")]
    r = rarete_patronymes(people)
    assert r["JACQUET"] == 1.0


def test_est_rare_distingue_le_courant_du_rare():
    r = {"JACQUET": 0.75, "VILLEPELLET": 0.01}
    assert est_rare("VILLEPELLET", r) is True
    assert est_rare("JACQUET", r) is False


def test_patronyme_absent_de_l_arbre_n_est_pas_rare():
    """Absent ≠ rare : sans mesure, on n'accorde pas de poids fort."""
    assert est_rare("INCONNU", {"JACQUET": 0.75}) is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run python -m pytest genecrew/tests/test_releves.py -q`
Expected: FAIL — `ImportError: cannot import name 'rarete_patronymes'`

- [ ] **Step 3: Write minimal implementation**

Ajouter à `genecrew/src/genecrew/releves.py` (l'import en tête du module) :

```python
from collections import Counter

from crewai_custom_tools.tools.genealogy.models.domain import EventFact, PersonFacts

from genecrew.pistes import _normaliser

SEUIL_RARETE = 0.02
```

puis les fonctions :

```python
def rarete_patronymes(people: list[PersonFacts]) -> dict[str, float]:
    """Fréquence de chaque patronyme DANS L'ARBRE, normalisée casse et accents.

    Mesurée, jamais devinée : « JACQUET » dans le Cher n'a pas la valeur
    discriminante de « VILLEPELLET », et seul un comptage sur tes données peut
    le dire. Recalculé à chaque passage — l'arbre bouge.
    """
    noms = [_normaliser(p.surname) for p in people if p.surname]
    if not noms:
        return {}
    total = len(noms)
    return {nom: n / total for nom, n in Counter(noms).items()}


def est_rare(surname: str, rarete: dict[str, float],
             seuil: float = SEUIL_RARETE) -> bool:
    """Un patronyme absent de l'arbre n'est PAS déclaré rare.

    Absent veut dire non mesuré, pas exceptionnel. Lui accorder un facteur fort
    sur une non-mesure ferait basculer des verdicts sur du vide.
    """
    return rarete.get(_normaliser(surname), 1.0) <= seuil
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run python -m pytest genecrew/tests/test_releves.py -q`
Expected: PASS (8 tests)

- [ ] **Step 5: Commit**

```bash
git add genecrew/src/genecrew/releves.py genecrew/tests/test_releves.py
git commit -m "feat(releves): rareté du patronyme mesurée sur l'arbre"
```

---

### Task 3: Blocage — réduire l'arbre à une poignée de candidats

**Files:**
- Modify: `genecrew/src/genecrew/releves.py`
- Test: `genecrew/tests/test_releves.py`

**Interfaces:**
- Consomme : `ReleveIndexe`, `PersonFacts`, `_normaliser`.
- Produit : `VARIANTES: dict[str, str]`, `candidats_blocage(releve, people) -> list[PersonFacts]`.

- [ ] **Step 1: Write the failing test**

```python
from genecrew.releves import candidats_blocage


def _releve(**kw):
    base = dict(fonds="CGHB", reference="106710046161418286", sujet_nom="JACQUET",
                sujet_prenom="Rose", evenement_type="Death", texte_brut="…")
    base.update(kw)
    return ReleveIndexe(**base)


def test_blocage_retient_le_patronyme_et_rejette_le_reste():
    people = [_p("I1", "JACQUET", "Rose"), _p("I2", "VILLEPELLET", "Marie")]
    assert [c.gramps_id for c in candidats_blocage(_releve(), people)] == ["I1"]


def test_blocage_tolere_casse_et_accents():
    people = [_p("I1", "Jacquèt", "Rose")]
    assert len(candidats_blocage(_releve(sujet_nom="JACQUET"), people)) == 1


def test_blocage_suit_les_variantes_de_graphie():
    """Sans table de variantes, « absent » voudrait dire « mal cherché »."""
    people = [_p("I1", "JACQUET", "Rose")]
    assert len(candidats_blocage(_releve(sujet_nom="JAQUET"), people)) == 1


def test_blocage_vide_quand_le_patronyme_est_inconnu():
    people = [_p("I1", "JACQUET", "Rose")]
    assert candidats_blocage(_releve(sujet_nom="MARTIN"), people) == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run python -m pytest genecrew/tests/test_releves.py -q`
Expected: FAIL — `ImportError: cannot import name 'candidats_blocage'`

- [ ] **Step 3: Write minimal implementation**

```python
VARIANTES: dict[str, str] = {
    "JAQUET": "JACQUET",
    "JACQUES": "JACQUET",
    "VILLEPELET": "VILLEPELLET",
    "VILAUDY": "VILLAUDY",
}
"""Graphies vues en relevé → forme retenue dans l'arbre.

Table volontairement explicite plutôt qu'un algorithme phonétique : Soundex est
calibré sur l'anglais et rapproche des patronymes français sans rapport. On
préfère rater une variante — visible au rapport — qu'en inventer.
"""


def _cle_blocage(surname: str) -> str:
    norme = _normaliser(surname)
    return VARIANTES.get(norme, norme)


def candidats_blocage(releve: ReleveIndexe,
                      people: list[PersonFacts]) -> list[PersonFacts]:
    """Les personnes qui méritent une comparaison fine.

    Sans cette étape, N relevés × 2 119 personnes explose. Le blocage est
    DÉLIBÉRÉMENT large : c'est la pondération qui tranche, pas lui. Un blocage
    trop serré ferait dire « absent de l'arbre » à une personne présente, et
    l'import créerait un doublon.
    """
    cle = _cle_blocage(releve.sujet_nom)
    return [p for p in people if _cle_blocage(p.surname) == cle]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run python -m pytest genecrew/tests/test_releves.py -q`
Expected: PASS (12 tests)

- [ ] **Step 5: Commit**

```bash
git add genecrew/src/genecrew/releves.py genecrew/tests/test_releves.py
git commit -m "feat(releves): blocage par patronyme avec table de variantes"
```

---

### Task 4: Pondération et verdict — le cœur

**Files:**
- Modify: `genecrew/src/genecrew/releves.py`
- Test: `genecrew/tests/test_releves.py`

**Interfaces:**
- Consomme : tout ce qui précède, plus `EventFact` via `PersonFacts.death`/`.birth`.
- Produit : `facteurs_et_divergences(releve, person, rarete, parents) -> tuple[list[str], list[str]]` et `apparier(releve, people, rarete, parents_par_handle) -> Appariement`.

`parents_par_handle: dict[str, list[str]]` associe le handle d'une personne aux **noms complets de ses parents** dans l'arbre. Il est construit côté orchestration (Task 7) ; le moteur le reçoit tout fait pour rester pur.

- [ ] **Step 1: Write the failing test**

```python
from crewai_custom_tools.tools.genealogy.models.domain import EventFact

from genecrew.releves import apparier


def _ev(type_, jour=0, mois=0, annee=0, lieu="", modifier=0):
    """`EventFact` ne porte PAS de champ `date` : la source est `dateval`, au
    format Gramps [jour, mois, année, slash]. 0 = composante inconnue."""
    return EventFact(type=type_, dateval=[jour, mois, annee, False],
                     year=annee or None, modifier=modifier, place=lieu,
                     sortval=1 if annee else 0)


def _mort(person, jour, mois, annee, lieu=""):
    person.death = _ev("Death", jour, mois, annee, lieu)
    return person


ROSE = _releve(evenement_date="1894-12-10", evenement_lieu="Saint-Martin-d'Auxigny",
               naissance_estimee=1821,
               personnes_liees=[PersonneLiee(nom="Pierre JACQUET", role="père"),
                                PersonneLiee(nom="Marie Anne VILLEPELLET", role="mère")])


def test_deux_facteurs_forts_donnent_net():
    p = _mort(_p("I1", "JACQUET", "Rose"), 10, 12, 1894, "Saint-Martin-d'Auxigny")
    a = apparier(ROSE, [p], {"JACQUET": 0.75}, {})
    assert a.verdict == "net"
    assert "date complète" in a.facteurs and "lieu" in a.facteurs
    assert a.gramps_id == "I1"


def test_divergence_de_date_est_un_veto_pas_un_malus():
    """Un empilement de concordances ne doit jamais écraser une contradiction."""
    p = _mort(_p("I1", "JACQUET", "Rose"), 2, 3, 1901, "Saint-Martin-d'Auxigny")
    a = apparier(ROSE, [p], {"JACQUET": 0.75}, {})
    assert a.verdict == "aucun"
    assert a.divergences


def test_annee_seule_ne_fait_pas_une_date_complete():
    """dateval [0, 0, 1894] est une année, pas une date : aucun facteur fort."""
    p = _p("I1", "JACQUET", "Rose")
    p.death = _ev("Death", annee=1894)
    a = apparier(ROSE, [p], {"JACQUET": 0.75}, {})
    assert "date complète" not in a.facteurs
    assert a.divergences == []          # une année n'est pas non plus une divergence


def test_date_texte_n_est_ni_concordance_ni_divergence():
    """modifier==6 : date en texte libre, non comparable terme à terme."""
    p = _p("I1", "JACQUET", "Rose")
    p.death = _ev("Death", 10, 12, 1894, modifier=6)
    a = apparier(ROSE, [p], {"JACQUET": 0.75}, {})
    assert "date complète" not in a.facteurs
    assert a.divergences == []


def test_facteurs_faibles_seuls_ne_font_jamais_un_net():
    p = _p("I1", "JACQUET", "Rose")          # ni date ni lieu : prénom + année seuls
    p.birth = _ev("Birth", annee=1821, modifier=3)      # 3 = about
    a = apparier(ROSE, [p], {"JACQUET": 0.75}, {})
    assert a.verdict != "net"


def test_parent_nomme_concordant_pese_lourd():
    p = _p("I1", "JACQUET", "Rose")
    a = apparier(ROSE, [p], {"JACQUET": 0.75},
                 {"hI1": ["Pierre JACQUET", "Marie Anne VILLEPELLET"]})
    assert "parent nommé" in a.facteurs
    assert a.verdict == "net"


def test_candidats_multiples_a_poids_egal_donnent_gris():
    a1 = _mort(_p("I1", "JACQUET", "Rose"), "1894-12-10", "Saint-Martin-d'Auxigny")
    a2 = _mort(_p("I2", "JACQUET", "Rose"), "1894-12-10", "Saint-Martin-d'Auxigny")
    a = apparier(ROSE, [a1, a2], {"JACQUET": 0.75}, {})
    assert a.verdict == "gris"
    assert sorted(a.candidats) == ["I1", "I2"]
    assert a.gramps_id is None


def test_aucun_candidat_donne_aucun():
    a = apparier(ROSE, [], {"JACQUET": 0.75}, {})
    assert a.verdict == "aucun"
    assert a.candidats == []


def test_patronyme_rare_ajoute_un_facteur_fort():
    p = _mort(_p("I1", "VILLEPELLET", "Marie"), "1894-12-10")
    r = _releve(sujet_nom="VILLEPELLET", sujet_prenom="Marie",
                evenement_date="1894-12-10")
    a = apparier(r, [p], {"VILLEPELLET": 0.01}, {})
    assert "patronyme rare" in a.facteurs
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run python -m pytest genecrew/tests/test_releves.py -q`
Expected: FAIL — `ImportError: cannot import name 'apparier'`

- [ ] **Step 3: Write minimal implementation**

```python
def _evenement_compare(person: PersonFacts, type_: str) -> EventFact | None:
    return person.death if type_ == "Death" else person.birth


def _date_iso(ev: EventFact | None) -> str:
    """La date de l'événement en AAAA-MM-JJ, "" si elle n'est pas complète.

    `EventFact` ne porte pas de date texte : la source est `dateval`, au format
    Gramps `[jour, mois, année, slash]`, où 0 signale une composante inconnue.
    Une date n'est COMPLÈTE que si les trois composantes sont non nulles — c'est
    exactement ce qui sépare le facteur fort « date complète » du facteur faible
    « année approximative ».

    `modifier == 6` (date en texte libre) est écarté : elle n'est comparable ni
    comme concordance ni comme divergence.
    """
    if ev is None or ev.modifier == 6 or len(ev.dateval) < 3:
        return ""
    jour, mois, annee = ev.dateval[0], ev.dateval[1], ev.dateval[2]
    if not (jour and mois and annee):
        return ""
    return f"{annee:04d}-{mois:02d}-{jour:02d}"


def facteurs_et_divergences(
    releve: ReleveIndexe, person: PersonFacts, rarete: dict[str, float],
    parents_par_handle: dict[str, list[str]],
) -> tuple[list[str], list[str]]:
    """Ce qui concorde et ce qui contredit, sans encore trancher."""
    facteurs: list[str] = []
    divergences: list[str] = []
    ev = _evenement_compare(person, releve.evenement_type)

    date_arbre = _date_iso(ev)
    if releve.evenement_date and date_arbre:
        if date_arbre == releve.evenement_date:
            facteurs.append("date complète")
        else:
            divergences.append(f"date {date_arbre} ≠ relevé {releve.evenement_date}")

    if releve.evenement_lieu and ev and ev.place:
        if _normaliser(ev.place) == _normaliser(releve.evenement_lieu):
            facteurs.append("lieu")
        else:
            divergences.append(f"lieu {ev.place} ≠ relevé {releve.evenement_lieu}")

    if est_rare(releve.sujet_nom, rarete):
        facteurs.append("patronyme rare")

    if _normaliser(person.given) == _normaliser(releve.sujet_prenom):
        facteurs.append("prénom")

    annee_arbre = person.birth.year if person.birth else None
    if releve.naissance_estimee and annee_arbre:
        if abs(annee_arbre - releve.naissance_estimee) <= 2:
            facteurs.append("année approximative")

    parents_arbre = {_normaliser(n) for n in parents_par_handle.get(person.handle, [])}
    parents_releve = {_normaliser(pl.nom) for pl in releve.personnes_liees
                      if pl.role in ("père", "mère")}
    if parents_arbre & parents_releve:
        facteurs.append("parent nommé")

    return facteurs, divergences


def _verdict_candidat(facteurs: list[str], divergences: list[str]) -> tuple[str, int]:
    """Poids et éligibilité d'UN candidat. La divergence est un veto."""
    if divergences:
        return "aucun", 0
    poids = sum(POIDS[f] for f in facteurs)
    if not (set(facteurs) & FACTEURS_FORTS):
        return "aucun", poids       # un faible ne suffit jamais, même à plusieurs
    return ("net" if poids >= SEUIL_NET else "gris"), poids


def apparier(releve: ReleveIndexe, people: list[PersonFacts],
             rarete: dict[str, float],
             parents_par_handle: dict[str, list[str]]) -> Appariement:
    """Le verdict, motivé. `gris` est un état EXPLICITE, pas un effet de seuil.

    C'est ce qui borne la facture : le nombre de lignes qui partiront au LLM est
    connu avant le moindre appel.
    """
    evalues = []
    for p in candidats_blocage(releve, people):
        facteurs, divergences = facteurs_et_divergences(
            releve, p, rarete, parents_par_handle)
        verdict, poids = _verdict_candidat(facteurs, divergences)
        evalues.append((verdict, poids, p, facteurs, divergences))

    retenus = [e for e in evalues if e[0] != "aucun"]
    if not retenus:
        div = [d for e in evalues for d in e[4]]
        return Appariement(verdict="aucun", divergences=div)

    retenus.sort(key=lambda e: e[1], reverse=True)
    meilleur = retenus[0]
    ex_aequo = [e for e in retenus if e[1] == meilleur[1]]

    if len(ex_aequo) > 1:
        return Appariement(verdict="gris", poids=meilleur[1],
                           facteurs=meilleur[3],
                           candidats=[e[2].gramps_id for e in ex_aequo])

    verdict, poids, person, facteurs, _ = meilleur
    return Appariement(verdict=verdict, gramps_id=person.gramps_id,
                       handle=person.handle, facteurs=facteurs, poids=poids,
                       candidats=[person.gramps_id])
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run python -m pytest genecrew/tests/test_releves.py -q`
Expected: PASS (19 tests)

- [ ] **Step 5: Commit**

```bash
git add genecrew/src/genecrew/releves.py genecrew/tests/test_releves.py
git commit -m "feat(releves): pondération et verdict, veto sur divergence"
```

---

### Task 5: Interprétation LLM du texte collé

**Files:**
- Create: `genecrew/src/genecrew/releves_import.py`
- Test: `genecrew/tests/test_releves_import.py`

**Interfaces:**
- Consomme : `ReleveIndexe`, `build_llm` (`genecrew.crew`).
- Produit : `PROMPT_INTERPRETATION: str`, `parse_releve(texte, llm=None) -> ReleveIndexe`.

- [ ] **Step 1: Write the failing test**

```python
"""Tests hors-ligne de l'import de relevés (LLM stubbé, Gramps via MockTransport)."""

import json

import pytest

from genecrew.releves_import import parse_releve

COLLAGE_ROSE = """Rose JACQUET
Le 10 décembre 1894
Saint-Martin-D'auxigny
(location_on Saint-Martin-D'auxigny, Cher )
Détails
Rose JACQUET
Naissance
Vers 1821
Âge : 73
Parents
Pierre JACQUET
Décès
Avant 1894
Marie Anne VILLEPELLET
Décès
Avant 1894
Référence n° 106710046161418286
Source du relevé : Cercle Généalogique du Haut-Berry
"""

_JSON_ATTENDU = {
    "fonds": "Cercle Généalogique du Haut-Berry",
    "reference": "106710046161418286",
    "sujet_nom": "JACQUET", "sujet_prenom": "Rose",
    "evenement_type": "Death", "evenement_date": "1894-12-10",
    "evenement_lieu": "Saint-Martin-d'Auxigny", "naissance_estimee": 1821,
    "personnes_liees": [{"nom": "Pierre JACQUET", "role": "père", "detail": ""},
                        {"nom": "Marie Anne VILLEPELLET", "role": "mère", "detail": ""}],
}


class _LLMStub:
    def __init__(self, reponse):
        self.reponse = reponse
        self.prompts = []

    def call(self, prompt):
        self.prompts.append(prompt)
        return self.reponse


def test_parse_produit_un_releve_indexe():
    r = parse_releve(COLLAGE_ROSE, llm=_LLMStub(json.dumps(_JSON_ATTENDU)))
    assert r.reference == "106710046161418286"
    assert r.evenement_date == "1894-12-10"
    assert [p.role for p in r.personnes_liees] == ["père", "mère"]


def test_texte_brut_est_conserve_integralement():
    """Quoi qu'il arrive à l'interprétation, la source reste lisible dans l'arbre."""
    r = parse_releve(COLLAGE_ROSE, llm=_LLMStub(json.dumps(_JSON_ATTENDU)))
    assert r.texte_brut == COLLAGE_ROSE


def test_le_llm_ne_choisit_pas_le_texte_brut():
    """Même si le LLM en renvoie un, c'est le collage réel qui fait foi."""
    menteur = dict(_JSON_ATTENDU, texte_brut="inventé")
    r = parse_releve(COLLAGE_ROSE, llm=_LLMStub(json.dumps(menteur)))
    assert r.texte_brut == COLLAGE_ROSE


def test_json_entoure_de_texte_est_extrait():
    bavard = "Voici le JSON :\n```json\n" + json.dumps(_JSON_ATTENDU) + "\n```\n"
    r = parse_releve(COLLAGE_ROSE, llm=_LLMStub(bavard))
    assert r.reference == "106710046161418286"


def test_reponse_illisible_leve_clairement():
    with pytest.raises(ValueError, match="JSON"):
        parse_releve(COLLAGE_ROSE, llm=_LLMStub("je ne sais pas"))
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run python -m pytest genecrew/tests/test_releves_import.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'genecrew.releves_import'`

- [ ] **Step 3: Write minimal implementation**

```python
"""Import d'un relevé collé : interprétation, appariement, écriture.

Le LLM LIT, il ne décide pas : il ne sert qu'à transformer un texte libre en
`ReleveIndexe`. L'appariement — le seul endroit où une erreur écrirait une
fausseté dans l'arbre — est déterministe et vit dans `releves.py`.
"""

from __future__ import annotations

import json
import re

from genecrew.crew import build_llm
from genecrew.releves import ReleveIndexe

PROMPT_INTERPRETATION = """Tu interprètes un relevé généalogique copié depuis un site.

Rends UNIQUEMENT un objet JSON, sans commentaire, avec exactement ces clés :
  fonds            : le cercle ou l'organisme qui a fait le relevé
  reference        : le numéro de référence du relevé
  sujet_nom        : le PATRONYME du sujet, en majuscules
  sujet_prenom     : son prénom
  evenement_type   : "Death", "Birth" ou "Marriage"
  evenement_date   : la date de l'événement en ISO AAAA-MM-JJ, "" si absente
  evenement_lieu   : la commune de l'événement, sans le département
  naissance_estimee: l'ANNÉE de naissance si elle est approximative, sinon null
  personnes_liees  : [{{"nom": …, "role": "père"|"mère"|"conjoint"|"témoin"|"autre",
                        "detail": …}}]

Règles :
- N'invente rien. Un champ absent du texte vaut "" ou null.
- Une date approximative ("vers 1821") ne va JAMAIS dans evenement_date.
- Les abréviations de relevé se lisent : prts=parents, prop=propriétaire,
  gdre=gendre, bfr=beau-frère, tem=témoin.

Le relevé :
---
{texte}
---"""

_BLOC_JSON = re.compile(r"\{.*\}", re.DOTALL)


def parse_releve(texte: str, llm=None) -> ReleveIndexe:
    """Un appel LLM, un relevé. Le texte brut n'est JAMAIS celui du modèle.

    Le collage réel fait foi : c'est lui qu'on recopiera dans la note, pour que
    la source reste lisible même si l'interprétation a dérapé.
    """
    llm = llm or build_llm("standardisateur")
    brut = llm.call(PROMPT_INTERPRETATION.format(texte=texte))
    trouve = _BLOC_JSON.search(brut or "")
    if not trouve:
        raise ValueError(f"Réponse du modèle sans JSON exploitable : {brut!r}")
    try:
        donnees = json.loads(trouve.group(0))
    except json.JSONDecodeError as exc:
        raise ValueError(f"JSON invalide dans la réponse du modèle : {exc}") from exc
    donnees["texte_brut"] = texte
    return ReleveIndexe.model_validate(donnees)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run python -m pytest genecrew/tests/test_releves_import.py -q`
Expected: PASS (5 tests)

- [ ] **Step 5: Commit**

```bash
git add genecrew/src/genecrew/releves_import.py genecrew/tests/test_releves_import.py
git commit -m "feat(releves): interprétation LLM du texte collé, JSON strict"
```

---

### Task 6: Marqueur d'idempotence

**Files:**
- Modify: `genecrew/src/genecrew/releves_import.py`
- Test: `genecrew/tests/test_releves_import.py`

**Interfaces:**
- Consomme : `marqueurs_existants` (`genecrew.pistes`), `GrampsClient`.
- Produit : `TAG_RELEVE`, `code_fonds(fonds) -> str`, `marqueur_releve(fonds, reference) -> str`, `deja_importe(client, gramps_id, marqueur) -> bool`.

- [ ] **Step 1: Write the failing test**

```python
import httpx
from crewai_custom_tools.tools.genealogy.gramps.client import GrampsClient, GrampsConfig

from genecrew.releves_import import code_fonds, deja_importe, marqueur_releve

CONFIG = GrampsConfig(api_url="http://g.test/api", username="u", password="p")


def _client(handler):
    def _h(request):
        if request.url.path == "/api/token/":
            return httpx.Response(200, json={"access_token": "t"})
        return handler(request)
    return GrampsClient(CONFIG, transport=httpx.MockTransport(_h))


def test_code_fonds_est_stable_et_sobre():
    assert code_fonds("Cercle Généalogique du Haut-Berry") == "cercle-genealogique-du-haut-berry"


def test_marqueur_porte_l_identite_jamais_la_date():
    m = marqueur_releve("Cercle Généalogique du Haut-Berry", "106710046161418286")
    assert m == "[genecrew:releve:cercle-genealogique-du-haut-berry:106710046161418286]"
    assert "2026" not in m


def test_deja_importe_detecte_le_marqueur_pose():
    m = marqueur_releve("CGHB", "106710046161418286")
    def h(request):
        return httpx.Response(200, json=[{"extended": {"notes": [
            {"text": {"string": m + "\nRelevé — CGHB"}}]}}])
    assert deja_importe(_client(h), "I0001", m) is True


def test_deja_importe_faux_sur_une_autre_reference():
    autre = marqueur_releve("CGHB", "999")
    def h(request):
        return httpx.Response(200, json=[{"extended": {"notes": [
            {"text": {"string": autre}}]}}])
    m = marqueur_releve("CGHB", "106710046161418286")
    assert deja_importe(_client(h), "I0001", m) is False


def test_deja_importe_faux_sans_note():
    def h(request):
        return httpx.Response(200, json=[{"extended": {"notes": []}}])
    assert deja_importe(_client(h), "I0001", marqueur_releve("CGHB", "1")) is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run python -m pytest genecrew/tests/test_releves_import.py -q`
Expected: FAIL — `ImportError: cannot import name 'code_fonds'`

- [ ] **Step 3: Write minimal implementation**

Ajouter à `releves_import.py` (imports en tête) :

```python
import unicodedata

from crewai_custom_tools.tools.genealogy.gramps.client import GrampsClient

TAG_RELEVE = "ia-releve"
```

puis :

```python
def code_fonds(fonds: str) -> str:
    """Identifiant sobre et stable du fonds, pour le marqueur."""
    sans_accent = "".join(c for c in unicodedata.normalize("NFD", fonds)
                          if unicodedata.category(c) != "Mn")
    return "-".join(sans_accent.lower().split())


def marqueur_releve(fonds: str, reference: str) -> str:
    """Marqueur d'idempotence : il porte l'IDENTITÉ, jamais la date.

    Même procédé que les pistes. La référence du relevé est un identifiant
    externe stable — donc pas de clé dérivée ici. Recoller le même relevé
    n'écrit rien.
    """
    return f"[genecrew:releve:{code_fonds(fonds)}:{reference}]"


def deja_importe(client: GrampsClient, gramps_id: str, marqueur: str) -> bool:
    """Ce relevé a-t-il déjà été posé sur cette personne ?

    Un seul appel, pour une personne : filtre serveur sur `gramps_id` et
    `extend=note_list` (même lecture que `pistes.marqueurs_existants`).
    """
    gens = client.get_json("/people/", params={"gramps_id": gramps_id,
                                               "extend": "note_list"}) or []
    if not gens:
        return False
    notes = (gens[0].get("extended") or {}).get("notes") or []
    return any((n.get("text") or {}).get("string", "").startswith(marqueur)
               for n in notes)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run python -m pytest genecrew/tests/test_releves_import.py -q`
Expected: PASS (10 tests)

- [ ] **Step 5: Commit**

```bash
git add genecrew/src/genecrew/releves_import.py genecrew/tests/test_releves_import.py
git commit -m "feat(releves): marqueur d'idempotence porté par la référence"
```

---

### Task 7: Route de source et corps de note

**Files:**
- Modify: `genecrew/src/genecrew/releves_import.py`
- Modify: `genecrew/src/genecrew/deces_apply.py` (fonction `source_title_for`)
- Test: `genecrew/tests/test_releves_import.py`

**Interfaces:**
- Consomme : `source_title_for` (`genecrew.deces_apply`), `ReleveIndexe`, `Appariement`.
- Produit : `corps_note_releve(releve, appariement) -> str`, plus la route « relevé » dans `source_title_for`.

- [ ] **Step 1: Write the failing test**

```python
from genecrew.deces_apply import source_title_for
from genecrew.releves import Appariement
from genecrew.releves_import import corps_note_releve


def test_source_title_route_un_releve_de_cercle():
    titre, auteur = source_title_for("Relevé — Cercle Généalogique du Haut-Berry")
    assert titre == "Cercle Généalogique du Haut-Berry — relevés"
    assert auteur == "Cercle Généalogique du Haut-Berry"


def test_source_title_leve_toujours_sur_un_registre_inconnu():
    """Pas de repli silencieux sur l'INSEE : ce serait une fausse attribution."""
    with pytest.raises(ValueError):
        source_title_for("provenance mystérieuse")


def test_note_recopie_le_texte_brut():
    r = parse_releve(COLLAGE_ROSE, llm=_LLMStub(json.dumps(_JSON_ATTENDU)))
    corps = corps_note_releve(r, Appariement(verdict="net", gramps_id="I1",
                                             facteurs=["date complète", "lieu"],
                                             poids=8))
    assert COLLAGE_ROSE.strip() in corps


def test_note_porte_le_marqueur_en_tete_et_les_facteurs():
    r = parse_releve(COLLAGE_ROSE, llm=_LLMStub(json.dumps(_JSON_ATTENDU)))
    corps = corps_note_releve(r, Appariement(verdict="net", facteurs=["date complète"],
                                             poids=5))
    assert corps.startswith("[genecrew:releve:")
    assert "date complète" in corps


def test_note_dit_que_le_releve_est_une_source_derivee():
    r = parse_releve(COLLAGE_ROSE, llm=_LLMStub(json.dumps(_JSON_ATTENDU)))
    corps = corps_note_releve(r, Appariement(verdict="net"))
    assert "dérivée" in corps and "acte" in corps
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run python -m pytest genecrew/tests/test_releves_import.py -q`
Expected: FAIL — `ImportError: cannot import name 'corps_note_releve'`

- [ ] **Step 3: Write minimal implementation**

Dans `genecrew/src/genecrew/deces_apply.py`, ajouter la constante et la route **avant** le `raise` final de `source_title_for` :

```python
_RELEVE_RE = re.compile(r"(?i)^\s*relev[ée]\s*[—-]\s*(.+?)\s*$")
```

```python
    m = _RELEVE_RE.match(detail)
    if m:
        cercle = m.group(1).strip()
        return f"{cercle} — relevés", cercle
```

Dans `releves_import.py` :

```python
from genecrew.releves import Appariement


def corps_note_releve(releve: ReleveIndexe, appariement: Appariement) -> str:
    """Le corps de la note. Rapporte le relevé ET ce qui a motivé l'appariement."""
    lignes = [
        marqueur_releve(releve.fonds, releve.reference),
        f"Relevé — {releve.fonds}",
        f"Référence : {releve.reference}",
        "",
        f"Appariement : {appariement.verdict.upper()} (poids {appariement.poids})",
        f"  facteurs   : {', '.join(appariement.facteurs) or '—'}",
        f"  divergences: {', '.join(appariement.divergences) or '—'}",
        "",
        "Source dérivée : un relevé est un dépouillement, pas l'acte original.",
        "",
        "Texte relevé tel que copié :",
        releve.texte_brut.strip(),
    ]
    return "\n".join(lignes)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run python -m pytest genecrew/tests/test_releves_import.py genecrew/tests/test_deces_apply.py -q`
Expected: PASS — les tests existants de `deces_apply` restent verts

- [ ] **Step 5: Commit**

```bash
git add genecrew/src/genecrew/releves_import.py genecrew/src/genecrew/deces_apply.py genecrew/tests/test_releves_import.py
git commit -m "feat(releves): route de source par cercle et corps de note"
```

---

### Task 8: Orchestration — collecte, appariement, écriture

**Files:**
- Modify: `genecrew/src/genecrew/releves_import.py`
- Test: `genecrew/tests/test_releves_import.py`

**Interfaces:**
- Consomme : `FactsFetcher` (`crewai_custom_tools...gramps.facts`), `iter_people_batches` (`genecrew.batching`), `GrampsCreateNoteTool`, `GrampsEnsureTagTool`, `GrampsAttachTool`, `effective_dry_run`.
- Produit : `_parents_par_handle(fetcher, people) -> dict[str, list[str]]`, `run_import_releve(client, texte, *, llm=None, dry_run=False) -> dict` avec les clés `releve`, `appariement`, `ecrit`, `raison`, `dry_run`.

**Avant d'écrire les fixtures :** `_ROSE_ARBRE` ci-dessous est la forme JSON brute que `person_from_json` doit savoir lire. **Vérifie sa forme réelle** dans `crewai_custom_tools/tools/genealogy/gramps/facts.py` (fonction `person_from_json`) et aligne la fixture dessus plutôt que de la deviner — les tests existants de `test_deces.py` et `test_gender.py` en contiennent des exemples fiables à recopier.

- [ ] **Step 1: Write the failing test**

```python
from genecrew.releves_import import run_import_releve


def _arbre(*people_json):
    """Répond aux appels Gramps : /people/ paginé, /people/?gramps_id= (idempotence).

    La page 2 rend une liste vide : `iter_people_batches` pagine jusqu'à
    l'épuisement, et un mock qui renvoie toujours la même page boucle sans fin.
    """
    def h(request):
        if request.url.path == "/api/people/":
            if "gramps_id" in request.url.params:
                return httpx.Response(200, json=[{"extended": {"notes": []}}])
            if request.url.params.get("page", "1") != "1":
                return httpx.Response(200, json=[])
            return httpx.Response(200, json=list(people_json))
        return httpx.Response(200, json=[])
    return _client(h)


_ROSE_ARBRE = {
    "gramps_id": "I0001", "handle": "h1", "gender": 0,
    "profile": {"name_given": "Rose", "name_surname": "JACQUET",
                "death": {"date": "1894-12-10", "place": "Saint-Martin-d'Auxigny"}},
}


def test_simulation_par_defaut_n_ecrit_rien(monkeypatch):
    monkeypatch.delenv("GENECREW_DRY_RUN", raising=False)
    out = run_import_releve(_arbre(_ROSE_ARBRE), COLLAGE_ROSE,
                            llm=_LLMStub(json.dumps(_JSON_ATTENDU)))
    assert out["dry_run"] is True
    assert out["ecrit"] is False
    assert out["raison"] == "simulation"
    assert out["appariement"].verdict == "net"


def test_gris_n_ecrit_pas_meme_hors_simulation(monkeypatch):
    monkeypatch.setenv("GENECREW_DRY_RUN", "false")
    jumeau = dict(_ROSE_ARBRE, gramps_id="I0002", handle="h2")
    out = run_import_releve(_arbre(_ROSE_ARBRE, jumeau), COLLAGE_ROSE,
                            llm=_LLMStub(json.dumps(_JSON_ATTENDU)))
    assert out["appariement"].verdict == "gris"
    assert out["ecrit"] is False
    assert out["raison"] == "gris — relecture requise"


def test_deuxieme_passage_n_ecrit_rien(monkeypatch):
    monkeypatch.setenv("GENECREW_DRY_RUN", "false")
    m = marqueur_releve("Cercle Généalogique du Haut-Berry", "106710046161418286")

    def h(request):
        if request.url.path == "/api/people/":
            if "gramps_id" in request.url.params:
                return httpx.Response(200, json=[{"extended": {"notes": [
                    {"text": {"string": m}}]}}])
            if request.url.params.get("page", "1") != "1":
                return httpx.Response(200, json=[])
            return httpx.Response(200, json=[_ROSE_ARBRE])
        return httpx.Response(200, json=[])

    out = run_import_releve(_client(h), COLLAGE_ROSE,
                            llm=_LLMStub(json.dumps(_JSON_ATTENDU)))
    assert out["ecrit"] is False
    assert out["raison"] == "déjà importée"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run python -m pytest genecrew/tests/test_releves_import.py -q`
Expected: FAIL — `ImportError: cannot import name 'run_import_releve'`

- [ ] **Step 3: Write minimal implementation**

```python
from crewai_custom_tools.tools.genealogy.gramps.facts import FactsFetcher
from crewai_custom_tools.tools.genealogy.gramps.write_tools import (
    GrampsAttachTool, GrampsCreateNoteTool, GrampsEnsureTagTool, effective_dry_run,
)

from genecrew.batching import iter_people_batches
from genecrew.releves import apparier, rarete_patronymes


def _parents_par_handle(fetcher: FactsFetcher, people) -> dict[str, list[str]]:
    """handle → noms complets des parents, pour le facteur « parent nommé ».

    Passe par `get_family_facts` : c'est la FAMILLE qui porte `father_handle` et
    `mother_handle` ; `PersonFacts` ne connaît que les handles de ses familles
    parentales. Le fetcher met les familles en cache, donc une famille partagée
    par une fratrie n'est lue qu'une fois.

    Construit ici, côté orchestration : le moteur d'appariement le reçoit tout
    fait pour rester pur.
    """
    par_handle = {p.handle: p for p in people}
    index: dict[str, list[str]] = {}
    for p in people:
        noms: list[str] = []
        for fam_handle in p.parent_family_handles:
            famille = fetcher.get_family_facts(fam_handle)
            if not famille:
                continue
            for parent_handle in (famille.father_handle, famille.mother_handle):
                parent = par_handle.get(parent_handle) if parent_handle else None
                if parent:
                    noms.append(parent.name)
        index[p.handle] = noms
    return index


def run_import_releve(client: GrampsClient, texte: str, *, llm=None,
                      dry_run: bool = False) -> dict:
    """Interprète, apparie, écrit si le verdict est net. Rend le verdict et sa raison."""
    dry_run = effective_dry_run(dry_run)
    releve = parse_releve(texte, llm=llm)
    fetcher = FactsFetcher(client)
    people = [p for lot in iter_people_batches(client, fetcher, "all", 200, None)
              for p in lot]
    appariement = apparier(releve, people, rarete_patronymes(people),
                           _parents_par_handle(fetcher, people))
    out = {"releve": releve, "appariement": appariement, "ecrit": False,
           "raison": "", "dry_run": dry_run}

    if appariement.verdict == "gris":
        out["raison"] = "gris — relecture requise"
        return out
    if appariement.verdict == "aucun":
        out["raison"] = "aucun candidat — création du sujet différée (voir Notes d'exécution)"
        return out

    marqueur = marqueur_releve(releve.fonds, releve.reference)
    if deja_importe(client, appariement.gramps_id, marqueur):
        out["raison"] = "déjà importée"
        return out
    if dry_run:
        out["raison"] = "simulation"
        return out

    note = json.loads(GrampsCreateNoteTool()._run(
        text=corps_note_releve(releve, appariement), note_type="Research"))
    if not note["success"]:
        out["raison"] = f"note refusée : {note['error']}"
        return out
    tag = json.loads(GrampsEnsureTagTool()._run(name=TAG_RELEVE))
    if not tag["success"]:
        out["raison"] = f"tag refusé : {tag['error']}"
        return out
    attache = json.loads(GrampsAttachTool()._run(
        handle=appariement.handle, note_handle=note["data"]["handle"],
        tag_handle=tag["data"]["handle"]))
    if not attache["success"]:
        out["raison"] = f"rattachement refusé : {attache['error']}"
        return out

    out["ecrit"] = True
    out["raison"] = "importée"
    return out
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run python -m pytest genecrew/tests/test_releves_import.py -q`
Expected: PASS (18 tests)

- [ ] **Step 5: Commit**

```bash
git add genecrew/src/genecrew/releves_import.py genecrew/tests/test_releves_import.py
git commit -m "feat(releves): orchestration — collecte, appariement, écriture du net"
```

---

### Task 9: Citation sur l'événement visé

**Files:**
- Modify: `genecrew/src/genecrew/releves_import.py`
- Test: `genecrew/tests/test_releves_import.py`

**Interfaces:**
- Consomme : `source_title_for` (Task 7), `GrampsEnsureSourceTool`, `GrampsCreateCitationTool`, `GrampsAttachCitationTool`.
- Produit : `handle_evenement(client, gramps_id, type_) -> str | None`, `ecrire_citation(client, releve, appariement) -> dict` (clés `posee`, `raison`).

**Limite v1, assumée :** la citation se pose sur un événement **existant**. Si l'événement du relevé est absent de l'arbre, il est *rapporté*, pas créé — même posture que `apply citations` (ADR 0011, « les types `date` restent manuels jusqu'à la v2 »). Créer un événement est une surface d'écriture qui mérite sa propre décision, pas un effet de bord d'un import.

- [ ] **Step 1: Write the failing test**

```python
from genecrew.releves_import import ecrire_citation, handle_evenement


def _arbre_avec_evenement(type_="Death", handle="e1"):
    def h(request):
        if request.url.path == "/api/people/":
            return httpx.Response(200, json=[{
                "gramps_id": "I0001", "handle": "h1",
                "extended": {"events": [{"handle": handle, "type": type_}]},
            }])
        return httpx.Response(200, json=[])
    return _client(h)


def test_handle_evenement_trouve_le_deces():
    assert handle_evenement(_arbre_avec_evenement(), "I0001", "Death") == "e1"


def test_handle_evenement_rend_none_si_absent():
    assert handle_evenement(_arbre_avec_evenement("Birth"), "I0001", "Death") is None


def test_citation_non_posee_si_l_evenement_manque(monkeypatch):
    monkeypatch.setenv("GENECREW_DRY_RUN", "false")
    r = parse_releve(COLLAGE_ROSE, llm=_LLMStub(json.dumps(_JSON_ATTENDU)))
    app = Appariement(verdict="net", gramps_id="I0001", handle="h1")
    out = ecrire_citation(_arbre_avec_evenement("Birth"), r, app)
    assert out["posee"] is False
    assert "absent" in out["raison"]


def test_citation_porte_la_reference_et_une_confiance_normal(monkeypatch):
    """Un relevé est une source dérivée : jamais `High`, ou on ferait passer
    un dépouillement pour l'acte original."""
    monkeypatch.setenv("GENECREW_DRY_RUN", "false")
    vus = {}

    class _Citation:
        def _run(self, **kw):
            vus.update(kw)
            return json.dumps({"success": True, "data": {"handle": "c1"}})

    monkeypatch.setattr("genecrew.releves_import.GrampsCreateCitationTool", _Citation)
    monkeypatch.setattr("genecrew.releves_import.GrampsEnsureSourceTool",
                        lambda: type("T", (), {"_run": lambda s, **k: json.dumps(
                            {"success": True, "data": {"handle": "s1"}})})())
    monkeypatch.setattr("genecrew.releves_import.GrampsAttachCitationTool",
                        lambda: type("T", (), {"_run": lambda s, **k: json.dumps(
                            {"success": True, "data": {}})})())

    r = parse_releve(COLLAGE_ROSE, llm=_LLMStub(json.dumps(_JSON_ATTENDU)))
    app = Appariement(verdict="net", gramps_id="I0001", handle="h1")
    out = ecrire_citation(_arbre_avec_evenement(), r, app)
    assert out["posee"] is True
    assert "106710046161418286" in vus["page"]
    assert vus["confidence"] == 2
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run python -m pytest genecrew/tests/test_releves_import.py -q`
Expected: FAIL — `ImportError: cannot import name 'ecrire_citation'`

- [ ] **Step 3: Write minimal implementation**

Ajouter les imports en tête de `releves_import.py` :

```python
from crewai_custom_tools.tools.genealogy.gramps.write_tools import (
    GrampsAttachCitationTool, GrampsCreateCitationTool, GrampsEnsureSourceTool,
)

from genecrew.deces_apply import source_title_for
```

puis :

```python
def handle_evenement(client: GrampsClient, gramps_id: str, type_: str) -> str | None:
    """Le handle de l'événement de ce type, s'il existe déjà.

    `extend=event_ref_list` rend les événements complets en UN appel pour UNE
    personne (gotcha documenté dans CLAUDE.md).
    """
    gens = client.get_json("/people/", params={"gramps_id": gramps_id,
                                               "extend": "event_ref_list"}) or []
    if not gens:
        return None
    for ev in (gens[0].get("extended") or {}).get("events") or []:
        if ev.get("type") == type_:
            return ev.get("handle")
    return None


def ecrire_citation(client: GrampsClient, releve: ReleveIndexe,
                    appariement: Appariement) -> dict:
    """Pose la citation du relevé sur l'événement visé. Ne crée jamais l'événement."""
    cible = handle_evenement(client, appariement.gramps_id, releve.evenement_type)
    if not cible:
        return {"posee": False,
                "raison": f"événement {releve.evenement_type} absent de l'arbre — "
                          "à créer à la main, l'import ne crée pas d'événement"}

    titre, auteur = source_title_for(f"Relevé — {releve.fonds}")
    source = json.loads(GrampsEnsureSourceTool()._run(title=titre, author=auteur))
    if not source["success"]:
        return {"posee": False, "raison": f"source refusée : {source['error']}"}

    citation = json.loads(GrampsCreateCitationTool()._run(
        source_handle=source["data"]["handle"],
        page=f"Relevé n° {releve.reference}",
        confidence=2,   # Normal : un relevé est un dépouillement, pas l'acte
    ))
    if not citation["success"]:
        return {"posee": False, "raison": f"citation refusée : {citation['error']}"}

    attache = json.loads(GrampsAttachCitationTool()._run(
        handle=cible, citation_handle=citation["data"]["handle"],
        object_type="event"))
    if not attache["success"]:
        return {"posee": False, "raison": f"rattachement refusé : {attache['error']}"}
    return {"posee": True, "raison": "citation posée"}
```

Enfin, brancher l'appel dans `run_import_releve`, **après** le rattachement de la note et avant le `return` final :

```python
    citation = ecrire_citation(client, releve, appariement)
    out["citation"] = citation

    out["ecrit"] = True
    out["raison"] = "importée" if citation["posee"] else f"importée sans citation ({citation['raison']})"
    return out
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run python -m pytest genecrew/tests/test_releves_import.py -q`
Expected: PASS (22 tests)

- [ ] **Step 5: Commit**

```bash
git add genecrew/src/genecrew/releves_import.py genecrew/tests/test_releves_import.py
git commit -m "feat(releves): citation du relevé sur l'événement existant"
```

---

### Task 10: Rapport, CLI et dispatch

**Files:**
- Modify: `genecrew/src/genecrew/releves_import.py`
- Modify: `genecrew/src/genecrew/cli.py:153-158`
- Modify: `genecrew/src/genecrew/main.py:393`
- Test: `genecrew/tests/test_releves_import.py`, `genecrew/tests/test_cli_parser.py`

**Interfaces:**
- Consomme : la sortie de `run_import_releve`.
- Produit : `format_import_releve(resultat) -> str`, la feuille CLI `import releve`, l'entrée de dispatch `("import", "releve")`.

- [ ] **Step 1: Write the failing test**

Dans `genecrew/tests/test_releves_import.py` :

```python
from genecrew.releves_import import format_import_releve


def test_rapport_affiche_le_mode_effectif(monkeypatch):
    monkeypatch.delenv("GENECREW_DRY_RUN", raising=False)
    out = run_import_releve(_arbre(_ROSE_ARBRE), COLLAGE_ROSE,
                            llm=_LLMStub(json.dumps(_JSON_ATTENDU)))
    texte = format_import_releve(out)
    assert "simulation" in texte
    assert "I0001" in texte
    assert "date complète" in texte


def test_rapport_liste_les_candidats_d_un_gris(monkeypatch):
    monkeypatch.setenv("GENECREW_DRY_RUN", "false")
    jumeau = dict(_ROSE_ARBRE, gramps_id="I0002", handle="h2")
    out = run_import_releve(_arbre(_ROSE_ARBRE, jumeau), COLLAGE_ROSE,
                            llm=_LLMStub(json.dumps(_JSON_ATTENDU)))
    texte = format_import_releve(out)
    assert "I0001" in texte and "I0002" in texte
```

Dans `genecrew/tests/test_cli_parser.py` :

```python
def test_import_releve_lit_stdin_par_defaut():
    args = build_parser().parse_args(["import", "releve"])
    assert (args.command, args.target) == ("import", "releve")
    assert args.file is None


def test_import_releve_accepte_un_fichier():
    args = build_parser().parse_args(["import", "releve", "--file", "acte.txt"])
    assert args.file == "acte.txt"
    assert args.dry_run is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run python -m pytest genecrew/tests/test_releves_import.py genecrew/tests/test_cli_parser.py -q`
Expected: FAIL — `ImportError: cannot import name 'format_import_releve'` puis erreur argparse sur `releve`

- [ ] **Step 3: Write minimal implementation**

Dans `releves_import.py` :

```python
def format_import_releve(resultat: dict) -> str:
    """Rapport lisible d'un import. Le mode affiché est le mode EFFECTIF."""
    releve, app = resultat["releve"], resultat["appariement"]
    mode = ("simulation (dry-run, aucune écriture)" if resultat["dry_run"]
            else "écritures appliquées")
    lignes = [
        f"Relevé {releve.reference} — {releve.fonds}",
        f"Sujet : {releve.sujet_prenom} {releve.sujet_nom} "
        f"({releve.evenement_type} {releve.evenement_date or 'sans date'})",
        f"Mode : {mode}",
        "",
        f"Verdict : {app.verdict.upper()} (poids {app.poids})",
        f"  facteurs    : {', '.join(app.facteurs) or '—'}",
        f"  divergences : {', '.join(app.divergences) or '—'}",
        f"  candidats   : {', '.join(app.candidats) or '—'}",
        "",
        f"Résultat : {'écrit' if resultat['ecrit'] else 'non écrit'} "
        f"({resultat['raison']})",
    ]
    if app.verdict == "gris":
        lignes += ["", "Relis les candidats, puis relance en désignant le bon :",
                   "  genecrew import releve --file <fichier> --person <ID>"]
    return "\n".join(lignes)
```

Dans `cli.py`, après la feuille `import place` (ligne ~158) :

```python
    p = import_sub.add_parser(
        "releve", help="Importer un relevé collé (stdin par défaut) avec smart match")
    p.add_argument("--file", default=None,
                   help="fichier contenant le relevé (défaut : stdin)")
    p.add_argument("--person", default=None,
                   help="forcer le rattachement à cette personne (ID Gramps)")
    _add_dry_run(p)
```

Dans `main.py`, ajouter à la table de dispatch, sous l'entrée `("import", "place")` :

```python
        ("import", "releve"): lambda: releve_import_cmd(args),
```

et la fonction de commande, sur le patron de `lieu_import_cmd` :

```python
def releve_import_cmd(args) -> None:
    """`genecrew import releve` : lit le collage, apparie, écrit le net."""
    texte = Path(args.file).read_text(encoding="utf-8") if args.file else sys.stdin.read()
    if not texte.strip():
        raise SystemExit("Rien à importer : le relevé est vide.")
    client = GrampsClient(GrampsConfig.from_env())
    resultat = run_import_releve(client, texte, dry_run=args.dry_run)
    print(format_import_releve(resultat))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run python -m pytest genecrew/tests/ -q`
Expected: PASS — toute la suite, y compris les tests CLI existants

- [ ] **Step 5: Commit**

```bash
git add genecrew/src/genecrew/releves_import.py genecrew/src/genecrew/cli.py genecrew/src/genecrew/main.py genecrew/tests/
git commit -m "feat(releves): rapport, feuille CLI import releve et dispatch"
```

---

### Task 11: Documentation et vérification finale

**Files:**
- Modify: `CLAUDE.md` (sections « Commands » et « Where the genealogy code lives »)
- Modify: `docs/USER_GUIDE.md`

- [ ] **Step 1: Lancer la suite complète et ruff**

Run:
```bash
uv run python -m pytest genecrew/tests/ -q && uv run ruff check .
```
Expected: PASS, aucun avertissement ruff.

- [ ] **Step 2: Ajouter la commande à CLAUDE.md**

Dans la section « Commands », après la ligne `import place` :

```bash
uv run genecrew import releve --file acte.txt --dry-run   # relevé collé → smart match
pbpaste | uv run genecrew import releve                   # depuis le presse-papier
```

Dans « Where the genealogy code lives », ajouter `releves.py` (moteur d'appariement pur) et `releves_import.py` (orchestration) à la liste des modules genecrew.

- [ ] **Step 3: Documenter le cycle dans USER_GUIDE.md**

Une section « Importer un relevé trouvé en ligne » : le collage, la simulation par défaut, la lecture du verdict, et la marche à suivre sur un `gris`.

- [ ] **Step 4: Vérifier la commande en simulation contre l'arbre réel**

Run:
```bash
cat docs/exemples/releve-rose-jacquet.txt | uv run genecrew import releve
```
Expected: un rapport avec `Mode : simulation`, un verdict motivé, aucune écriture.

- [ ] **Step 5: Commit**

```bash
git add CLAUDE.md docs/USER_GUIDE.md
git commit -m "docs(releves): documenter import releve et son cycle"
```

---

## Notes d'exécution

- **Deux écarts assumés par rapport à la spec, tous deux sur la création d'objets Gramps.** La spec §5 prévoit que l'import crée le sujet absent et écrive la naissance estimée ; ce plan ne le fait pas. Le verdict `aucun` est *rapporté*, et un événement absent est *rapporté* (Task 9) plutôt que créé. Raison : créer une personne ou un événement est une surface d'écriture qui mérite sa propre décision — c'est la posture qu'`apply citations` tient déjà (ADR 0011). Le bon moment pour la lever est après avoir lu les verdicts d'un vrai lot en simulation, ce que le défaut dry-run garantit. **Si tu veux la création dès la v1, dis-le : c'est deux tâches de plus, pas une reconception.**
- **Les poids de la Task 4 sont un point de départ, pas un acquis.** Le premier lot réel se lit en simulation ; si des `net` sont faux ou des `gris` évidents, ce sont `POIDS` et `SEUIL_NET` qu'on ajuste, avec un test de non-régression par correction.
- **Ne pas toucher à `crewai_custom_tools`** : aucune tâche de ce plan ne le demande, et le faire imposerait le cycle tag/push décrit dans les gotchas de `CLAUDE.md`.
