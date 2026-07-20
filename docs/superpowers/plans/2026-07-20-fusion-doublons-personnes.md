# Fusion des doublons de personnes — Plan 1 : le pipeline déterministe

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fusionner automatiquement, par l'API Gramps, les doublons de personnes prouvés par des règles structurelles, et déposer tout le reste dans un YAML relisible — sans jamais fusionner sur une simple ressemblance de nom.

**Architecture:** Trois étages (auto / arbitrage / rejet). Les paires candidates sortent d'un blocking multi-clés déterministe ; l'étagement applique trois règles structurelles booléennes ; l'exécution raisonne en grappes union-find, avec un unique patch de genre avant fusion. Toute l'analyse est pure et testée hors ligne ; seul `people_merge.py` touche au réseau.

**Tech Stack:** Python 3.12, pydantic v2, `httpx` via `GrampsClient`, `pytest`, `uv`, `ruff`.

Spec de référence : `docs/superpowers/specs/2026-07-20-fusion-doublons-personnes-design.md`.

**Périmètre de ce plan.** L'arbitrage LLM de la spec §4.3 fait l'objet d'un **Plan 2**. Ici, l'étage « arbitrage » produit un YAML de paires **sans verdict LLM** — le fichier est déjà relisible et actionnable, le Plan 2 ne fera qu'y ajouter `verdict`, `confiance` et `piege_ecarte`.

## Global Constraints

- **La similarité de nom n'est jamais une preuve** — uniquement une clé de blocage (spec §3.1). Aucune règle de l'étage auto ne doit consulter un score de similarité.
- **Un `sortval == 0` ne compte jamais comme une concordance** (spec §4.1).
- **« Mêmes parents + même prénom sans date » ne fusionne jamais automatiquement** — signature du frère homonyme (spec §4.1).
- Toute écriture passe par `effective_dry_run(dry_run)` — l'environnement ne peut que *forcer* la simulation, et l'absence de la variable simule.
- Les fonctions d'analyse sont **pures** : pas d'I/O, pas de réseau, pas d'horloge. Elles vivent dans `crewai_custom_tools`, jamais dans `genecrew`.
- Genres : `0=F, 1=M, 2=U` côté API ; `PersonFacts.sex` vaut `"F"`, `"M"` ou `"U"`.
- Le français est la langue des docstrings de haut niveau, des rapports et des messages de commit ; les identifiants restent en anglais quand le code alentour l'est.
- **Ordre de livraison inter-dépôts** : la CI de genecrew checkoute `crewai_custom_tools` sur le **tag** lu dans `uv.lock`. La bibliothèque doit être taguée et poussée (Task 7) avant que les tâches genecrew puissent verdir en CI.

## État des dépôts au moment de la rédaction

- `genecrew` : branche `feat/sources-archives-pistes`, HEAD `96131bc`.
- `crewai_custom_tools` : branche `feat/sources-archives-pistes`, HEAD `53c28b4`, version `0.21.0`.

**Une autre session travaille sur ces deux branches.** Vérifier `git branch --show-current` et `git log --oneline -1` avant et après chaque tâche. Ne jamais changer de branche, ne jamais `git push`, ne jamais taguer sans accord explicite de l'utilisateur (Task 7).

## Structure des fichiers

**`crewai_custom_tools`, sous `src/crewai_custom_tools/tools/genealogy/` :**

| Fichier | Responsabilité |
|---|---|
| `analysis/phonetics.py` *(créé)* | La clé phonétique française. Une fonction, aucune dépendance. |
| `analysis/duplicates.py` *(modifié)* | R10 inchangé, plus : clés de blocage, paires candidates, étagement. |
| `analysis/merge_plan.py` *(créé)* | Grappes union-find, choix du phoenix, décision de patch du genre. |
| `models/domain.py` *(modifié)* | `MergeTier`, `MergePair`, `MergeCluster`. |
| `gramps/write_tools.py` *(modifié)* | `GrampsMergePeopleTool`. |

**`genecrew`, sous `genecrew/src/genecrew/` :**

| Fichier | Responsabilité |
|---|---|
| `people_merge.py` *(créé)* | Orchestration : passes, appels API, YAML d'arbitrage, rapport. |
| `cli.py` *(modifié)* | La feuille `merge people`. |
| `main.py` *(modifié)* | Le routage `("merge", "people")`. |

`duplicates.py` reste sous les 250 lignes ; si l'étagement le fait déborder, extraire les règles dans `analysis/merge_rules.py` plutôt que de laisser grossir le fichier.

---

### Task 1 : La clé phonétique française

**Files:**
- Create: `/Users/fjacquet/Projects/crewai_custom_tools/src/crewai_custom_tools/tools/genealogy/analysis/phonetics.py`
- Test: `/Users/fjacquet/Projects/crewai_custom_tools/tests/test_genealogy_phonetics.py`

**Interfaces:**
- Consumes: rien.
- Produces: `normalize_name(s: str) -> str` (**déplacée** depuis `duplicates.py`) et
  `cle_phonetique(nom: str) -> str`. Consommés par la Task 3.

> **Pourquoi déplacer `normalize_name`.** Si `phonetics.py` l'importait depuis `duplicates.py`
> pendant que `duplicates.py` importe `cle_phonetique`, le chargement échouerait sur un cycle.
> On la déplace donc ici et `duplicates.py` la réexporte : la dépendance devient à sens unique
> (`duplicates` → `phonetics`), et `test_genealogy_duplicates.py`, qui l'importe depuis
> `duplicates`, continue de passer sans modification.

- [ ] **Step 1: Écrire le test qui échoue**

Créer `/Users/fjacquet/Projects/crewai_custom_tools/tests/test_genealogy_phonetics.py` :

```python
"""Clé phonétique française — rappel uniquement, jamais une preuve."""

import pytest

from crewai_custom_tools.tools.genealogy.analysis.phonetics import cle_phonetique


@pytest.mark.parametrize("nom,attendu", [
    ("Villaudy", "vilaudi"),
    ("VILLAUDY", "vilaudi"),
    ("Villaudi", "vilaudi"),
    ("Jacquet", "jak"),
    ("JACQUET", "jak"),
    ("Jaquet", "jak"),
    ("Jacquier", "jakier"),
    ("Pagan", "pagan"),
    ("Pagani", "pagani"),
    ("Fouquet", "fouk"),
    ("Foucquet", "fouk"),
    ("Lelièvre", "lelievr"),
    ("Le Lievre", "lelievr"),
    ("Schneider", "sxneider"),
    ("Larpent", "larpen"),
    ("LARPENT", "larpen"),
    ("Clavier", "klavier"),
    ("Cuvier", "kuvier"),
    ("Besson", "beson"),
    ("Bessons", "beson"),
])
def test_cle_phonetique(nom, attendu):
    assert cle_phonetique(nom) == attendu


def test_chaine_vide_rend_vide():
    assert cle_phonetique("") == ""
    assert cle_phonetique("  ") == ""
    assert cle_phonetique("?") == ""


def test_separe_les_familles_voisines_de_l_arbre():
    """Pagan/Pagani et Jacquet/Jacquier sont des lignées distinctes (spec §3.1)."""
    assert cle_phonetique("Pagan") != cle_phonetique("Pagani")
    assert cle_phonetique("Jacquet") != cle_phonetique("Jacquier")


def test_limite_assumee_les_voyelles_internes_ne_sont_pas_reduites():
    """Documente une limite réelle : la clé ne sert qu'au rappel (spec §4.2)."""
    assert cle_phonetique("Lelevre") != cle_phonetique("Lelièvre")
```

- [ ] **Step 2: Lancer le test pour vérifier qu'il échoue**

```bash
cd /Users/fjacquet/Projects/crewai_custom_tools && uv run python -m pytest tests/test_genealogy_phonetics.py -q
```

Attendu : `ModuleNotFoundError: No module named 'crewai_custom_tools.tools.genealogy.analysis.phonetics'`.

- [ ] **Step 3: Écrire l'implémentation minimale**

Créer `/Users/fjacquet/Projects/crewai_custom_tools/src/crewai_custom_tools/tools/genealogy/analysis/phonetics.py` :

```python
"""Clé phonétique française d'un patronyme — pure, stdlib only.

Sert UNIQUEMENT au rappel : elle regroupe des candidats à examiner, elle ne prouve
jamais une identité (spec §3.1). Ses limites sont assumées — elle rapproche les
graphies partageant la même ossature consonantique, pas les variations de voyelle
interne (`Lelevre` ne rejoint pas `Lelièvre`).
"""

from __future__ import annotations

import unicodedata


def normalize_name(s: str) -> str:
    """Lowercase, strip accents, collapse whitespace.

    Déplacée depuis `duplicates.py`, qui la réexporte : `phonetics` ne doit
    dépendre de rien, sans quoi l'import de `cle_phonetique` par `duplicates`
    formerait un cycle.
    """
    decomposed = unicodedata.normalize("NFKD", s)
    ascii_only = "".join(c for c in decomposed if not unicodedata.combining(c))
    return " ".join(ascii_only.lower().split())


# Ordre significatif : "ch" est neutralisé en "x" AVANT que "c" ne devienne "k",
# faute de quoi Schneider deviendrait "skneider".
_REMPLACEMENTS = [
    ("ph", "f"),
    ("ch", "x"),
    ("qu", "k"),
    ("gu", "g"),
    ("c", "k"),
    ("y", "i"),
]

_TERMINAISONS_MUETTES = ("e", "s", "t", "d", "x", "z")

_LONGUEUR_MINIMALE = 2
"""On ne rabote jamais en deçà : "Est" ne doit pas se réduire à la chaîne vide."""


def cle_phonetique(nom: str) -> str:
    """Rend la clé phonétique d'un patronyme, ou la chaîne vide s'il est inexploitable."""
    lettres = "".join(c for c in normalize_name(nom) if c.isalpha())
    if not lettres:
        return ""
    for avant, apres in _REMPLACEMENTS:
        lettres = lettres.replace(avant, apres)
    deduplique: list[str] = []
    for caractere in lettres:
        if not deduplique or deduplique[-1] != caractere:
            deduplique.append(caractere)
    cle = "".join(deduplique)
    while len(cle) > _LONGUEUR_MINIMALE and cle[-1] in _TERMINAISONS_MUETTES:
        cle = cle[:-1]
    return cle
```

Puis, dans `/Users/fjacquet/Projects/crewai_custom_tools/src/crewai_custom_tools/tools/genealogy/analysis/duplicates.py`, **supprimer** la définition de `normalize_name` (lignes 16-20) ainsi que l'import `import unicodedata` devenu inutile, et la réexporter :

```python
from crewai_custom_tools.tools.genealogy.analysis.phonetics import normalize_name

__all__ = ["find_duplicates", "normalize_name"]
```

- [ ] **Step 4: Lancer le test pour vérifier qu'il passe**

```bash
cd /Users/fjacquet/Projects/crewai_custom_tools && uv run python -m pytest tests/test_genealogy_phonetics.py tests/test_genealogy_duplicates.py -q && uv run ruff check src/
```

Attendu : `28 passed` — les 23 nouveaux (20 cas paramétrés + 3 tests) **et les 5 de R10**, dont `test_normalize_strips_accents_and_case` qui importe `normalize_name` depuis `duplicates` et prouve que la réexportation fonctionne. Puis `All checks passed!`.

- [ ] **Step 5: Commit**

```bash
cd /Users/fjacquet/Projects/crewai_custom_tools
git add src/crewai_custom_tools/tools/genealogy/analysis/phonetics.py \
        src/crewai_custom_tools/tools/genealogy/analysis/duplicates.py \
        tests/test_genealogy_phonetics.py
git commit -m "feat(doublons): clé phonétique française, pour le rappel seulement

Rapproche Jacquet/Jaquet et Lelièvre/Le Lievre, et sépare correctement
Jacquet/Jacquier et Pagan/Pagani — les deux plus grosses familles de
l'arbre, qui sont des lignées distinctes. Limite assumée et testée :
les voyelles internes ne sont pas réduites.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 2 : Les modèles de domaine

**Files:**
- Modify: `/Users/fjacquet/Projects/crewai_custom_tools/src/crewai_custom_tools/tools/genealogy/models/domain.py`
- Test: `/Users/fjacquet/Projects/crewai_custom_tools/tests/test_genealogy_merge_models.py`

**Interfaces:**
- Consumes: rien.
- Produces: `MergeTier` (alias `Literal`), `MergePair`, `MergeCluster`. Consommés par les Tasks 3, 4, 5, 6, 8.

- [ ] **Step 1: Écrire le test qui échoue**

Créer `/Users/fjacquet/Projects/crewai_custom_tools/tests/test_genealogy_merge_models.py` :

```python
"""Contrats des modèles de fusion."""

import pytest
from pydantic import ValidationError

from crewai_custom_tools.tools.genealogy.models.domain import MergeCluster, MergePair


def test_paire_minimale():
    p = MergePair(gramps_id_a="I1", gramps_id_b="I2", handle_a="h1", handle_b="h2",
                  tier="auto", regle="date_complete+parents")
    assert p.tier == "auto"
    assert p.blocs == []


def test_tier_est_un_vocabulaire_ferme():
    with pytest.raises(ValidationError):
        MergePair(gramps_id_a="I1", gramps_id_b="I2", handle_a="h1", handle_b="h2",
                  tier="peut-etre", regle="")


def test_grappe_sans_patch_de_genre_par_defaut():
    g = MergeCluster(phoenix_handle="h1", phoenix_gramps_id="I1",
                     titanic_handles=["h2"], titanic_gramps_ids=["I2"])
    assert g.gender_patch is None


def test_grappe_refuse_un_genre_hors_vocabulaire():
    with pytest.raises(ValidationError):
        MergeCluster(phoenix_handle="h1", phoenix_gramps_id="I1",
                     titanic_handles=["h2"], titanic_gramps_ids=["I2"], gender_patch=7)
```

- [ ] **Step 2: Lancer le test pour vérifier qu'il échoue**

```bash
cd /Users/fjacquet/Projects/crewai_custom_tools && uv run python -m pytest tests/test_genealogy_merge_models.py -q
```

Attendu : `ImportError: cannot import name 'MergeCluster'`.

- [ ] **Step 3: Écrire l'implémentation minimale**

Ajouter à la fin de `/Users/fjacquet/Projects/crewai_custom_tools/src/crewai_custom_tools/tools/genealogy/models/domain.py` (le module importe déjà `Literal`, `BaseModel` et `Field` ; ne pas dupliquer les imports) :

```python
MergeTier = Literal["auto", "arbitrage", "rejet"]
"""Les trois étages de la fusion (spec §4.1).

`auto` : preuve structurelle, fusion sans relecture. `arbitrage` : preuve
partielle, passe par un YAML relu. `rejet` : ressemblance de nom seule — jamais
une preuve.
"""


class MergePair(BaseModel):
    """Une paire de personnes, avec l'étage qui lui a été attribué."""

    gramps_id_a: str
    gramps_id_b: str
    handle_a: str
    handle_b: str
    tier: MergeTier
    regle: str = ""
    """Règle de l'étage auto qui a conclu : `date_complete+parents`,
    `date_complete`, `conjoint+enfant`. Vide pour les étages arbitrage et rejet."""
    blocs: list[str] = Field(default_factory=list)
    """Clés de blocage ayant produit la paire — traçabilité du rappel."""


class MergeCluster(BaseModel):
    """Une grappe de doublons réduite à un seul survivant (spec §4.5)."""

    phoenix_handle: str
    phoenix_gramps_id: str
    titanic_handles: list[str] = Field(default_factory=list)
    titanic_gramps_ids: list[str] = Field(default_factory=list)
    gender_patch: Literal[0, 1] | None = None
    """Genre à écrire sur le phoenix AVANT la fusion, ou None. `Person.merge()`
    ignore le genre : sans ce patch, un phoenix « Inconnu » perdrait sans trace le
    genre connu d'un titanic (spec §2)."""
```

- [ ] **Step 4: Lancer le test pour vérifier qu'il passe**

```bash
cd /Users/fjacquet/Projects/crewai_custom_tools && uv run python -m pytest tests/test_genealogy_merge_models.py -q
```

Attendu : `4 passed`.

- [ ] **Step 5: Commit**

```bash
cd /Users/fjacquet/Projects/crewai_custom_tools
git add src/crewai_custom_tools/tools/genealogy/models/domain.py tests/test_genealogy_merge_models.py
git commit -m "feat(doublons): MergeTier, MergePair et MergeCluster

gender_patch est borné à Literal[0,1]|None : c'est le seul champ que
Person.merge() perd sans trace, il n'a pas à accepter n'importe quel int.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 3 : Clés de blocage et paires candidates

**Files:**
- Modify: `/Users/fjacquet/Projects/crewai_custom_tools/src/crewai_custom_tools/tools/genealogy/analysis/duplicates.py`
- Test: `/Users/fjacquet/Projects/crewai_custom_tools/tests/test_genealogy_blocking.py`

**Interfaces:**
- Consumes: `cle_phonetique` (Task 1) ; `PersonFacts`, `FamilyFacts` (existants).
- Produces:
  - `blocking_keys(p: PersonFacts) -> set[str]`
  - `MAX_BLOC: int`
  - `candidate_pairs(people: list[PersonFacts], max_bloc: int = MAX_BLOC) -> tuple[dict[tuple[str, str], set[str]], list[str]]` — rend `{(handle_a, handle_b): {clés}}` avec `handle_a < handle_b`, plus la liste des clés ignorées pour cause de bloc trop gros. Consommé par la Task 4.

- [ ] **Step 1: Écrire le test qui échoue**

Créer `/Users/fjacquet/Projects/crewai_custom_tools/tests/test_genealogy_blocking.py` :

```python
"""Génération des paires candidates — c'est du RAPPEL, pas de la preuve."""

from crewai_custom_tools.tools.genealogy.analysis.duplicates import (
    MAX_BLOC, blocking_keys, candidate_pairs,
)
from crewai_custom_tools.tools.genealogy.models.domain import EventFact, PersonFacts


def _p(gid, given, surname, year=None, familles=(), parents=()):
    return PersonFacts(
        gramps_id=gid, handle=f"h{gid}", name=f"{given} {surname}",
        surname=surname, given=given, sex="U",
        birth=EventFact(type="Birth", sortval=year * 366, year=year) if year else None,
        family_handles=list(familles), parent_family_handles=list(parents),
    )


def test_cle_nom_exact_ignore_casse_et_accents():
    a = blocking_keys(_p("I1", "Jean", "VILLAUDY"))
    b = blocking_keys(_p("I2", "Jean", "Villaudy"))
    assert a & b


def test_cle_phonetique_rapproche_les_graphies():
    a = blocking_keys(_p("I1", "Jean", "Jacquet"))
    b = blocking_keys(_p("I2", "Jean", "Jaquet"))
    assert a & b


def test_personne_sans_nom_ne_produit_aucune_cle():
    assert blocking_keys(_p("I1", "", "")) == set()


def test_annee_proche_bloque_ensemble_annee_lointaine_non():
    proches = blocking_keys(_p("I1", "Jean", "Dupont", 1850)) & \
        blocking_keys(_p("I2", "Jean", "Dupont", 1852))
    assert any(k.startswith("an:") for k in proches)
    lointaines = blocking_keys(_p("I1", "Jean", "Dupont", 1850)) & \
        blocking_keys(_p("I2", "Jean", "Dupont", 1860))
    assert not any(k.startswith("an:") for k in lointaines)


def test_famille_conjugale_commune_bloque_sans_aucune_date():
    """Le cas que R10 rate totalement aujourd'hui (spec §4.2)."""
    a = _p("I1", "Marie", "Sestre", familles=["F1"])
    b = _p("I2", "Marie", "Sestre", familles=["F1"])
    pairs, _ = candidate_pairs([a, b])
    assert ("hI1", "hI2") in pairs
    assert any(k.startswith("fam:") for k in pairs[("hI1", "hI2")])


def test_paires_normalisees_et_sans_doublon():
    a, b = _p("I1", "Jean", "Dupont", 1850), _p("I2", "Jean", "Dupont", 1850)
    pairs, _ = candidate_pairs([a, b])
    assert list(pairs) == [("hI1", "hI2")]
    assert len(pairs[("hI1", "hI2")]) >= 2


def test_une_personne_ne_se_paire_pas_avec_elle_meme():
    pairs, _ = candidate_pairs([_p("I1", "Jean", "Dupont", 1850)])
    assert pairs == {}


def test_bloc_trop_gros_est_ignore_et_signale():
    gros = [_p(f"I{i}", "Jean", "Pagan") for i in range(MAX_BLOC + 5)]
    pairs, ignores = candidate_pairs(gros, max_bloc=MAX_BLOC)
    assert pairs == {}
    assert any(k.startswith("nom:") for k in ignores)
```

- [ ] **Step 2: Lancer le test pour vérifier qu'il échoue**

```bash
cd /Users/fjacquet/Projects/crewai_custom_tools && uv run python -m pytest tests/test_genealogy_blocking.py -q
```

Attendu : `ImportError: cannot import name 'blocking_keys'`.

- [ ] **Step 3: Écrire l'implémentation minimale**

Ajouter à la fin de `/Users/fjacquet/Projects/crewai_custom_tools/src/crewai_custom_tools/tools/genealogy/analysis/duplicates.py`, et ajouter en tête `from itertools import combinations` :

```python
MAX_BLOC = 60
"""Au-delà, un bloc est ignoré : `Pagan` (151 personnes) produirait 11 325 paires
à lui seul. Le rappel perdu est couvert par les quatre autres clés (spec §4.2)."""

_FENETRE_ANNEE = 2
"""Chaque personne enregistre ses années ±2, si bien que deux personnes distantes
d'au plus 2 ans partagent forcément une clé."""


def blocking_keys(p: PersonFacts) -> set[str]:
    """Rend les clés de blocage d'une personne — du RAPPEL, jamais une preuve."""
    cles: set[str] = set()
    nom = normalize_name(f"{p.given} {p.surname}")
    patronyme = normalize_name(p.surname)
    if nom:
        cles.add(f"nom:{nom}")
    initiale = normalize_name(p.given)[:1]
    phonetique = cle_phonetique(p.surname)
    if phonetique and initiale:
        cles.add(f"pho:{phonetique}:{initiale}")
    if patronyme and p.birth and p.birth.year:
        for delta in range(-_FENETRE_ANNEE, _FENETRE_ANNEE + 1):
            cles.add(f"an:{patronyme}:{p.birth.year + delta}")
    for handle in p.family_handles:
        cles.add(f"fam:{handle}")
    for handle in p.parent_family_handles:
        cles.add(f"par:{handle}")
    return cles


def candidate_pairs(
    people: list[PersonFacts], max_bloc: int = MAX_BLOC
) -> tuple[dict[tuple[str, str], set[str]], list[str]]:
    """Rend les paires candidates et les clés écartées pour cause de bloc trop gros."""
    blocs: dict[str, list[PersonFacts]] = {}
    for personne in people:
        for cle in blocking_keys(personne):
            blocs.setdefault(cle, []).append(personne)
    paires: dict[tuple[str, str], set[str]] = {}
    ignores: list[str] = []
    for cle, membres in blocs.items():
        if len(membres) < 2:
            continue
        if len(membres) > max_bloc:
            ignores.append(cle)
            continue
        for a, b in combinations(membres, 2):
            paires.setdefault(tuple(sorted((a.handle, b.handle))), set()).add(cle)
    return paires, ignores
```

Compléter l'import de `phonetics` en tête du fichier, déjà présent depuis la Task 1 :

```python
from crewai_custom_tools.tools.genealogy.analysis.phonetics import (
    cle_phonetique, normalize_name,
)
```

Aucun cycle possible : la Task 1 a rendu `phonetics` autonome, la dépendance ne va que dans un sens.

- [ ] **Step 4: Lancer le test pour vérifier qu'il passe**

```bash
cd /Users/fjacquet/Projects/crewai_custom_tools && uv run python -m pytest tests/test_genealogy_blocking.py tests/test_genealogy_duplicates.py -q && uv run ruff check src/
```

Attendu : `13 passed` (8 nouveaux + 5 de R10, qui doivent rester verts), `All checks passed!`.

- [ ] **Step 5: Commit**

```bash
cd /Users/fjacquet/Projects/crewai_custom_tools
git add src/crewai_custom_tools/tools/genealogy/analysis/duplicates.py tests/test_genealogy_blocking.py
git commit -m "feat(doublons): blocking multi-clés, cinq clés dont deux sans date

Les clés fam:/par: rattrapent les personnes sans date de naissance, que
R10 ignore totalement. MAX_BLOC borne le quadratique : Pagan seul (151
personnes) produirait 11 325 paires.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 4 : L'étagement et le corpus de pièges

C'est la tâche critique du plan : **c'est ici que se joue la sécurité du système.** Une erreur ici fusionne deux individus réels, de façon invisible et permanente.

**Files:**
- Modify: `/Users/fjacquet/Projects/crewai_custom_tools/src/crewai_custom_tools/tools/genealogy/analysis/duplicates.py`
- Test: `/Users/fjacquet/Projects/crewai_custom_tools/tests/test_genealogy_merge_tiers.py`

**Interfaces:**
- Consumes: `candidate_pairs` (Task 3) ; `MergePair`, `MergeTier` (Task 2) ; `FamilyFacts` (existant).
- Produces:
  - `date_complete(ev: EventFact | None) -> bool`
  - `etager(people: list[PersonFacts], familles: dict[str, FamilyFacts], max_bloc: int = MAX_BLOC) -> tuple[list[MergePair], list[str]]` — rend les paires étagées et les clés ignorées. Consommé par les Tasks 5 et 8.

- [ ] **Step 1: Écrire le test qui échoue**

Créer `/Users/fjacquet/Projects/crewai_custom_tools/tests/test_genealogy_merge_tiers.py` :

```python
"""Étagement auto/arbitrage/rejet — et le CORPUS DE PIÈGES, filet de sécurité du système.

Chaque piège ici correspond à une confusion généalogique réelle et fréquente.
Aucun ne doit atteindre l'étage `auto` : une fusion est irréversible.
"""

from crewai_custom_tools.tools.genealogy.analysis.duplicates import date_complete, etager
from crewai_custom_tools.tools.genealogy.models.domain import (
    EventFact, FamilyFacts, PersonFacts,
)


def _naissance(jour, mois, annee):
    """Date de précision au jour : dateval = [jour, mois, année, slash]."""
    return EventFact(type="Birth", sortval=annee * 366 + mois * 31 + jour,
                     year=annee, modifier=0, dateval=[jour, mois, annee, False])


def _annee_seule(annee):
    """Date réduite à l'année — jour et mois à zéro."""
    return EventFact(type="Birth", sortval=annee * 366, year=annee,
                     modifier=0, dateval=[0, 0, annee, False])


def _p(gid, given, surname, birth=None, familles=(), parents=(), sex="U"):
    return PersonFacts(
        gramps_id=gid, handle=f"h{gid}", name=f"{given} {surname}",
        surname=surname, given=given, sex=sex, birth=birth,
        family_handles=list(familles), parent_family_handles=list(parents),
    )


def _famille(handle, pere=None, mere=None, enfants=()):
    return FamilyFacts(gramps_id=handle, handle=handle, father_handle=pere,
                       mother_handle=mere, child_handles=list(enfants))


def _tier(paires, gid_a, gid_b):
    for p in paires:
        if {p.gramps_id_a, p.gramps_id_b} == {gid_a, gid_b}:
            return p.tier, p.regle
    return None, None


# --- date_complete -----------------------------------------------------------

def test_date_complete_exige_jour_et_mois():
    assert date_complete(_naissance(3, 4, 1850)) is True
    assert date_complete(_annee_seule(1850)) is False
    assert date_complete(None) is False


def test_sortval_nul_n_est_jamais_complet():
    """Contrainte globale : sortval 0 ne compte jamais comme une concordance."""
    ev = EventFact(type="Birth", sortval=0, year=1850, dateval=[3, 4, 1850, False])
    assert date_complete(ev) is False


def test_date_textuelle_n_est_pas_complete():
    """modifier == 6 : date en texte libre, non exploitable."""
    ev = EventFact(type="Birth", sortval=677000, year=1850, modifier=6,
                   dateval=[3, 4, 1850, False])
    assert date_complete(ev) is False


# --- les trois règles de l'étage auto ---------------------------------------

def test_regle_date_complete_et_memes_parents():
    familles = {"F1": _famille("F1", "hPERE", "hMERE")}
    a = _p("I1", "Jean", "Dupont", _naissance(3, 4, 1850), parents=["F1"])
    b = _p("I2", "Jean", "Dupont", _naissance(3, 4, 1850), parents=["F1"])
    paires, _ = etager([a, b], familles)
    assert _tier(paires, "I1", "I2") == ("auto", "date_complete+parents")


def test_regle_date_complete_seule():
    a = _p("I1", "Jean", "Dupont", _naissance(3, 4, 1850))
    b = _p("I2", "Jean", "Dupont", _naissance(3, 4, 1850))
    paires, _ = etager([a, b], {})
    assert _tier(paires, "I1", "I2") == ("auto", "date_complete")


def test_regle_conjoint_et_enfant_commun_sans_aucune_date():
    familles = {
        "F1": _famille("F1", "hCONJ", "hI1", enfants=["hENF"]),
        "F2": _famille("F2", "hCONJ", "hI2", enfants=["hENF"]),
    }
    a = _p("I1", "Marie", "Sestre", familles=["F1"])
    b = _p("I2", "Marie", "Sestre", familles=["F2"])
    paires, _ = etager([a, b], familles)
    assert _tier(paires, "I1", "I2") == ("auto", "conjoint+enfant")


def test_conjoint_commun_sans_enfant_commun_reste_en_arbitrage():
    familles = {
        "F1": _famille("F1", "hCONJ", "hI1", enfants=["hENF1"]),
        "F2": _famille("F2", "hCONJ", "hI2", enfants=["hENF2"]),
    }
    a = _p("I1", "Marie", "Sestre", familles=["F1"])
    b = _p("I2", "Marie", "Sestre", familles=["F2"])
    paires, _ = etager([a, b], familles)
    assert _tier(paires, "I1", "I2")[0] == "arbitrage"


def test_noms_differents_ne_fusionnent_jamais_en_auto():
    familles = {"F1": _famille("F1", "hPERE", "hMERE")}
    a = _p("I1", "Jean", "Dupont", _naissance(3, 4, 1850), parents=["F1"])
    b = _p("I2", "Pierre", "Dupont", _naissance(3, 4, 1850), parents=["F1"])
    paires, _ = etager([a, b], familles)
    assert _tier(paires, "I1", "I2")[0] != "auto"


# --- LE CORPUS DE PIÈGES ----------------------------------------------------

def test_piege_freres_homonymes():
    """Un enfant meurt en bas âge, le suivant reçoit le même prénom.
    Mêmes parents, même nom, dates différentes. Très fréquent avant 1900."""
    familles = {"F1": _famille("F1", "hPERE", "hMERE", enfants=["hI1", "hI2"])}
    a = _p("I1", "Jean", "Dupont", _naissance(3, 4, 1850), parents=["F1"])
    b = _p("I2", "Jean", "Dupont", _naissance(7, 9, 1853), parents=["F1"])
    paires, _ = etager([a, b], familles)
    assert _tier(paires, "I1", "I2")[0] != "auto"


def test_piege_freres_homonymes_sans_aucune_date():
    """La règle explicitement rejetée par la spec §4.1 : mêmes parents + même
    prénom, sans date, ne fusionne JAMAIS automatiquement."""
    familles = {"F1": _famille("F1", "hPERE", "hMERE", enfants=["hI1", "hI2"])}
    a = _p("I1", "Jean", "Dupont", parents=["F1"])
    b = _p("I2", "Jean", "Dupont", parents=["F1"])
    paires, _ = etager([a, b], familles)
    assert _tier(paires, "I1", "I2")[0] != "auto"


def test_piege_jumeaux():
    """Mêmes parents, MÊME date de naissance, prénoms différents."""
    familles = {"F1": _famille("F1", "hPERE", "hMERE", enfants=["hI1", "hI2"])}
    a = _p("I1", "Jean", "Dupont", _naissance(3, 4, 1850), parents=["F1"])
    b = _p("I2", "Paul", "Dupont", _naissance(3, 4, 1850), parents=["F1"])
    paires, _ = etager([a, b], familles)
    assert _tier(paires, "I1", "I2")[0] != "auto"


def test_piege_pere_et_fils_homonymes():
    """Même nom complet, ~28 ans d'écart."""
    a = _p("I1", "Jean", "Dupont", _naissance(3, 4, 1822))
    b = _p("I2", "Jean", "Dupont", _naissance(3, 4, 1850))
    paires, _ = etager([a, b], {})
    assert _tier(paires, "I1", "I2")[0] != "auto"


def test_piege_pagan_contre_pagani():
    """Les deux plus grosses familles de l'arbre : 0.957 de similarité lexicale
    pour un seuil R10 à 0.85, et pourtant des lignées distinctes (spec §3.1)."""
    a = _p("I1", "Marie", "Pagan", _naissance(3, 4, 1850))
    b = _p("I2", "Marie", "Pagani", _naissance(3, 4, 1850))
    paires, _ = etager([a, b], {})
    assert _tier(paires, "I1", "I2")[0] != "auto"


def test_piege_annee_seule_identique():
    """Même nom, même ANNÉE, rien d'autre : le faux positif de 2026-07-19."""
    a = _p("I1", "Jean", "Dupont", _annee_seule(1850))
    b = _p("I2", "Jean", "Dupont", _annee_seule(1850))
    paires, _ = etager([a, b], {})
    assert _tier(paires, "I1", "I2")[0] != "auto"


def test_piege_deux_dates_inconnues_ne_concordent_pas():
    """Deux sortval à 0 ne sont pas « la même date »."""
    inconnue = EventFact(type="Birth", sortval=0, year=None, dateval=[])
    a = _p("I1", "Jean", "Dupont", inconnue)
    b = _p("I2", "Jean", "Dupont", inconnue)
    paires, _ = etager([a, b], {})
    assert _tier(paires, "I1", "I2")[0] != "auto"


def test_ressemblance_de_nom_seule_est_rejetee():
    a = _p("I1", "Jean", "Dupont", _naissance(3, 4, 1850))
    b = _p("I2", "Jean", "Dupond", _naissance(7, 9, 1851))
    paires, _ = etager([a, b], {})
    tier, _regle = _tier(paires, "I1", "I2")
    assert tier in (None, "rejet")
```

- [ ] **Step 2: Lancer le test pour vérifier qu'il échoue**

```bash
cd /Users/fjacquet/Projects/crewai_custom_tools && uv run python -m pytest tests/test_genealogy_merge_tiers.py -q
```

Attendu : `ImportError: cannot import name 'date_complete'`.

- [ ] **Step 3: Écrire l'implémentation minimale**

Ajouter à la fin de `/Users/fjacquet/Projects/crewai_custom_tools/src/crewai_custom_tools/tools/genealogy/analysis/duplicates.py` :

```python
REGLE_DATE_PARENTS = "date_complete+parents"
REGLE_DATE = "date_complete"
REGLE_CONJOINT_ENFANT = "conjoint+enfant"

_MODIFIER_TEXTE = 6
"""Date en texte libre : non exploitable comme concordance."""


def date_complete(ev: EventFact | None) -> bool:
    """Vrai si l'événement porte une date exacte de précision au JOUR.

    Un `sortval` à 0 (inconnu ou non triable) et une date textuelle
    (`modifier == 6`) ne comptent jamais — c'est le piège « année seule » sous
    ses différentes formes (spec §4.1).
    """
    if ev is None or ev.sortval == 0 or ev.modifier == _MODIFIER_TEXTE:
        return False
    if len(ev.dateval) < 3:
        return False
    jour, mois = ev.dateval[0], ev.dateval[1]
    return bool(jour) and bool(mois)


def _memes_parents(a: PersonFacts, b: PersonFacts,
                   familles: dict[str, FamilyFacts]) -> bool:
    """Vrai si les deux personnes ont un père ET une mère identiques et connus."""
    def parents(p: PersonFacts) -> tuple[str | None, str | None]:
        for handle in p.parent_family_handles:
            famille = familles.get(handle)
            if famille and famille.father_handle and famille.mother_handle:
                return famille.father_handle, famille.mother_handle
        return None, None

    pere_a, mere_a = parents(a)
    if pere_a is None or mere_a is None:
        return False
    return (pere_a, mere_a) == parents(b)


def _conjoints_et_enfants(p: PersonFacts, familles: dict[str, FamilyFacts]
                          ) -> tuple[set[str], set[str]]:
    conjoints: set[str] = set()
    enfants: set[str] = set()
    for handle in p.family_handles:
        famille = familles.get(handle)
        if famille is None:
            continue
        for candidat in (famille.father_handle, famille.mother_handle):
            if candidat and candidat != p.handle:
                conjoints.add(candidat)
        enfants.update(famille.child_handles)
    return conjoints, enfants


def _meme_conjoint_et_enfant(a: PersonFacts, b: PersonFacts,
                             familles: dict[str, FamilyFacts]) -> bool:
    conjoints_a, enfants_a = _conjoints_et_enfants(a, familles)
    conjoints_b, enfants_b = _conjoints_et_enfants(b, familles)
    return bool(conjoints_a & conjoints_b) and bool(enfants_a & enfants_b)


def _regle_auto(a: PersonFacts, b: PersonFacts,
                familles: dict[str, FamilyFacts]) -> str:
    """Rend la règle de l'étage auto qui conclut, ou la chaîne vide.

    Prérequis commun aux trois règles : le nom normalisé complet doit être
    identique et non vide. La similarité n'entre JAMAIS en jeu (spec §3.1).
    """
    nom = normalize_name(f"{a.given} {a.surname}")
    if not nom or nom != normalize_name(f"{b.given} {b.surname}"):
        return ""
    dates_identiques = (
        date_complete(a.birth) and date_complete(b.birth)
        and a.birth.sortval == b.birth.sortval
    )
    if dates_identiques and _memes_parents(a, b, familles):
        return REGLE_DATE_PARENTS
    if dates_identiques:
        return REGLE_DATE
    if _meme_conjoint_et_enfant(a, b, familles):
        return REGLE_CONJOINT_ENFANT
    return ""


def etager(people: list[PersonFacts], familles: dict[str, FamilyFacts],
           max_bloc: int = MAX_BLOC) -> tuple[list[MergePair], list[str]]:
    """Classe chaque paire candidate en auto / arbitrage / rejet (spec §4.1)."""
    par_handle = {p.handle: p for p in people}
    paires_candidates, ignores = candidate_pairs(people, max_bloc=max_bloc)
    resultat: list[MergePair] = []
    for (handle_a, handle_b), blocs in sorted(paires_candidates.items()):
        a, b = par_handle[handle_a], par_handle[handle_b]
        regle = _regle_auto(a, b, familles)
        if regle:
            tier = "auto"
        elif blocs == {cle for cle in blocs if cle.startswith("pho:")}:
            # Rapprochées par la seule ressemblance de nom : jamais une preuve.
            tier = "rejet"
        else:
            tier = "arbitrage"
        resultat.append(MergePair(
            gramps_id_a=a.gramps_id, gramps_id_b=b.gramps_id,
            handle_a=handle_a, handle_b=handle_b,
            tier=tier, regle=regle, blocs=sorted(blocs)))
    return resultat, ignores
```

Compléter les imports en tête du fichier :

```python
from crewai_custom_tools.tools.genealogy.models.domain import (
    DuplicateCandidate,
    EventFact,
    FamilyFacts,
    MergePair,
    PersonFacts,
)
```

- [ ] **Step 4: Lancer le test pour vérifier qu'il passe**

```bash
cd /Users/fjacquet/Projects/crewai_custom_tools && uv run python -m pytest tests/test_genealogy_merge_tiers.py tests/test_genealogy_blocking.py tests/test_genealogy_duplicates.py -q && uv run ruff check src/
```

Attendu : `29 passed` (16 d'étagement + 8 de blocking + 5 de R10), `All checks passed!`.

Si `test_piege_pagan_contre_pagani` échoue en rendant `auto` : c'est que la comparaison de nom laisse passer `pagan` ≠ `pagani`. Vérifier que `_regle_auto` compare bien par **égalité stricte** et n'appelle aucun `SequenceMatcher`.

- [ ] **Step 5: Commit**

```bash
cd /Users/fjacquet/Projects/crewai_custom_tools
git add src/crewai_custom_tools/tools/genealogy/analysis/duplicates.py tests/test_genealogy_merge_tiers.py
git commit -m "feat(doublons): étagement auto/arbitrage/rejet et corpus de pièges

Les trois règles de l'étage auto sont booléennes et structurelles : aucune
ne consulte un score de similarité. Le corpus de pièges (frères homonymes,
jumeaux, père/fils, Pagan/Pagani, année seule) est le filet de sécurité du
système — une fusion est irréversible.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 5 : Grappes, choix du phoenix, patch du genre

**Files:**
- Create: `/Users/fjacquet/Projects/crewai_custom_tools/src/crewai_custom_tools/tools/genealogy/analysis/merge_plan.py`
- Test: `/Users/fjacquet/Projects/crewai_custom_tools/tests/test_genealogy_merge_plan.py`

**Interfaces:**
- Consumes: `MergePair`, `MergeCluster` (Task 2) ; `PersonFacts` (existant).
- Produces:
  - `score_completude(p: PersonFacts) -> int`
  - `choisir_phoenix(membres: list[PersonFacts]) -> PersonFacts`
  - `plan_fusions(paires: list[MergePair], par_handle: dict[str, PersonFacts]) -> list[MergeCluster]`
  Consommés par la Task 8.

- [ ] **Step 1: Écrire le test qui échoue**

Créer `/Users/fjacquet/Projects/crewai_custom_tools/tests/test_genealogy_merge_plan.py` :

```python
"""Grappes union-find, choix du phoenix, patch du genre."""

from crewai_custom_tools.tools.genealogy.analysis.merge_plan import (
    choisir_phoenix, plan_fusions, score_completude,
)
from crewai_custom_tools.tools.genealogy.models.domain import (
    EventFact, MergePair, PersonFacts,
)


def _p(gid, sex="U", birth=None, death=None, citations=False, familles=(), parents=()):
    return PersonFacts(
        gramps_id=gid, handle=f"h{gid}", name="Jean Dupont",
        surname="Dupont", given="Jean", sex=sex, birth=birth, death=death,
        has_any_citation=citations,
        family_handles=list(familles), parent_family_handles=list(parents),
    )


def _naissance(annee=1850, place="Bourges"):
    return EventFact(type="Birth", sortval=annee * 366, year=annee,
                     dateval=[3, 4, annee, False], place_name=place)


def _auto(gid_a, gid_b):
    return MergePair(gramps_id_a=gid_a, gramps_id_b=gid_b,
                     handle_a=f"h{gid_a}", handle_b=f"h{gid_b}",
                     tier="auto", regle="date_complete")


# --- complétude et phoenix ---------------------------------------------------

def test_score_completude_croit_avec_les_champs_renseignes():
    vide = _p("I1")
    garni = _p("I2", sex="M", birth=_naissance(), parents=["F1"], familles=["F2"])
    assert score_completude(garni) > score_completude(vide)


def test_phoenix_est_le_plus_complet():
    pauvre, riche = _p("I1"), _p("I2", sex="M", birth=_naissance())
    assert choisir_phoenix([pauvre, riche]).gramps_id == "I2"


def test_a_completude_egale_le_mieux_source_gagne():
    sans = _p("I1", sex="M", birth=_naissance())
    avec = _p("I2", sex="M", birth=_naissance(), citations=True)
    assert choisir_phoenix([sans, avec]).gramps_id == "I2"


def test_departage_stable_par_gramps_id():
    """Deux exécutions sur les mêmes données doivent choisir le même phoenix."""
    a, b = _p("I9", sex="M"), _p("I2", sex="M")
    assert choisir_phoenix([a, b]).gramps_id == "I2"
    assert choisir_phoenix([b, a]).gramps_id == "I2"


# --- grappes -----------------------------------------------------------------

def test_grappe_transitive_a_un_seul_phoenix():
    """A≈B et B≈C : fusionner A/B supprime B, l'appel B/C partirait sur un
    handle mort. Une seule grappe, un seul phoenix (spec §4.5)."""
    gens = {f"h{g}": _p(g, sex="M") for g in ("I1", "I2", "I3")}
    grappes = plan_fusions([_auto("I1", "I2"), _auto("I2", "I3")], gens)
    assert len(grappes) == 1
    assert grappes[0].phoenix_gramps_id == "I1"
    assert sorted(grappes[0].titanic_gramps_ids) == ["I2", "I3"]


def test_deux_grappes_disjointes_restent_separees():
    gens = {f"h{g}": _p(g, sex="M") for g in ("I1", "I2", "I3", "I4")}
    grappes = plan_fusions([_auto("I1", "I2"), _auto("I3", "I4")], gens)
    assert len(grappes) == 2


def test_seul_l_etage_auto_est_planifie():
    gens = {f"h{g}": _p(g) for g in ("I1", "I2")}
    arbitrage = MergePair(gramps_id_a="I1", gramps_id_b="I2", handle_a="hI1",
                          handle_b="hI2", tier="arbitrage", regle="")
    assert plan_fusions([arbitrage], gens) == []


# --- patch du genre ----------------------------------------------------------

def test_phoenix_inconnu_recupere_le_genre_du_titanic():
    """Person.merge() ignore le genre : sans patch, le M serait perdu (spec §2)."""
    gens = {"hI1": _p("I1", sex="U", birth=_naissance()), "hI2": _p("I2", sex="M")}
    grappes = plan_fusions([_auto("I1", "I2")], gens)
    assert grappes[0].phoenix_gramps_id == "I1"
    assert grappes[0].gender_patch == 1


def test_phoenix_feminin_donne_un_patch_a_zero():
    gens = {"hI1": _p("I1", sex="U", birth=_naissance()), "hI2": _p("I2", sex="F")}
    assert plan_fusions([_auto("I1", "I2")], gens)[0].gender_patch == 0


def test_phoenix_deja_genre_n_est_jamais_patche():
    gens = {"hI1": _p("I1", sex="M", birth=_naissance()), "hI2": _p("I2", sex="F")}
    grappes = plan_fusions([_auto("I1", "I2")], gens)
    assert grappes[0].phoenix_gramps_id == "I1"
    assert grappes[0].gender_patch is None


def test_aucun_genre_connu_aucun_patch():
    gens = {"hI1": _p("I1", sex="U", birth=_naissance()), "hI2": _p("I2", sex="U")}
    assert plan_fusions([_auto("I1", "I2")], gens)[0].gender_patch is None
```

- [ ] **Step 2: Lancer le test pour vérifier qu'il échoue**

```bash
cd /Users/fjacquet/Projects/crewai_custom_tools && uv run python -m pytest tests/test_genealogy_merge_plan.py -q
```

Attendu : `ModuleNotFoundError: No module named '...analysis.merge_plan'`.

- [ ] **Step 3: Écrire l'implémentation minimale**

Créer `/Users/fjacquet/Projects/crewai_custom_tools/src/crewai_custom_tools/tools/genealogy/analysis/merge_plan.py` :

```python
"""Du lot de paires au plan de fusion : grappes, phoenix, patch du genre.

Pur, stdlib only. Ne fait aucun appel réseau — l'exécution vit dans genecrew.
"""

from __future__ import annotations

from crewai_custom_tools.tools.genealogy.models.domain import (
    MergeCluster,
    MergePair,
    PersonFacts,
)

_GENRE_PAR_SEXE = {"F": 0, "M": 1}
"""PersonFacts.sex vers l'entier attendu par l'API Gramps. "U" n'y figure pas :
un genre inconnu ne se patche pas."""


def score_completude(p: PersonFacts) -> int:
    """Nombre de champs renseignés parmi les sept retenus par la spec §4.4."""
    return sum((
        p.sex != "U",
        p.birth is not None,
        p.death is not None,
        bool(p.birth and p.birth.sortval),
        bool(p.birth and p.birth.place_name),
        bool(p.parent_family_handles),
        bool(p.family_handles),
    ))


def _rang(p: PersonFacts) -> tuple[int, int, str]:
    """Clé de tri décroissante-puis-croissante : complétude, citations, id.

    Le `gramps_id` clôt le départage pour qu'une seconde exécution sur les mêmes
    données choisisse le même phoenix.
    """
    return (-score_completude(p), -int(p.has_any_citation), p.gramps_id)


def choisir_phoenix(membres: list[PersonFacts]) -> PersonFacts:
    """Rend le survivant d'une grappe (spec §4.4)."""
    return min(membres, key=_rang)


def _grappes(paires: list[MergePair]) -> list[list[str]]:
    """Union-find sur les handles : rend les composantes connexes."""
    parent: dict[str, str] = {}

    def trouver(x: str) -> str:
        parent.setdefault(x, x)
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def unir(a: str, b: str) -> None:
        racine_a, racine_b = trouver(a), trouver(b)
        if racine_a != racine_b:
            parent[racine_b] = racine_a

    for paire in paires:
        unir(paire.handle_a, paire.handle_b)

    composantes: dict[str, list[str]] = {}
    for handle in parent:
        composantes.setdefault(trouver(handle), []).append(handle)
    return [sorted(membres) for membres in composantes.values()]


def _patch_genre(phoenix: PersonFacts, titanics: list[PersonFacts]) -> int | None:
    """Genre à écrire sur le phoenix avant fusion, ou None.

    `Person.merge()` n'unit pas le genre : celui du phoenix survit, celui du
    titanic disparaît sans trace (spec §2). C'est le seul patch nécessaire.
    """
    if phoenix.sex != "U":
        return None
    for titanic in sorted(titanics, key=lambda p: p.gramps_id):
        if titanic.sex in _GENRE_PAR_SEXE:
            return _GENRE_PAR_SEXE[titanic.sex]
    return None


def plan_fusions(paires: list[MergePair],
                 par_handle: dict[str, PersonFacts]) -> list[MergeCluster]:
    """Rend une grappe par groupe de doublons de l'étage `auto`."""
    auto = [p for p in paires if p.tier == "auto"]
    grappes: list[MergeCluster] = []
    for handles in _grappes(auto):
        membres = [par_handle[h] for h in handles if h in par_handle]
        if len(membres) < 2:
            continue
        phoenix = choisir_phoenix(membres)
        titanics = [m for m in membres if m.handle != phoenix.handle]
        grappes.append(MergeCluster(
            phoenix_handle=phoenix.handle,
            phoenix_gramps_id=phoenix.gramps_id,
            titanic_handles=[t.handle for t in titanics],
            titanic_gramps_ids=[t.gramps_id for t in titanics],
            gender_patch=_patch_genre(phoenix, titanics)))
    return sorted(grappes, key=lambda g: g.phoenix_gramps_id)
```

- [ ] **Step 4: Lancer le test pour vérifier qu'il passe**

```bash
cd /Users/fjacquet/Projects/crewai_custom_tools && uv run python -m pytest tests/test_genealogy_merge_plan.py -q && uv run ruff check src/
```

Attendu : `11 passed`, `All checks passed!`.

- [ ] **Step 5: Commit**

```bash
cd /Users/fjacquet/Projects/crewai_custom_tools
git add src/crewai_custom_tools/tools/genealogy/analysis/merge_plan.py tests/test_genealogy_merge_plan.py
git commit -m "feat(doublons): grappes union-find, phoenix et patch du genre

A≈B et B≈C forment UNE grappe à un seul phoenix : fusionner par paires
supprimerait B puis partirait sur un handle mort. Le genre est le seul
champ que Person.merge() perd sans trace, d'où l'unique patch préalable.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 6 : L'outil d'écriture `GrampsMergePeopleTool`

**Files:**
- Modify: `/Users/fjacquet/Projects/crewai_custom_tools/src/crewai_custom_tools/tools/genealogy/gramps/write_tools.py`
- Test: `/Users/fjacquet/Projects/crewai_custom_tools/tests/test_genealogy_merge_people_tool.py`

**Interfaces:**
- Consumes: `effective_dry_run`, `get_client`, `ok`, `api_tool` (existants dans le module).
- Produces: `GrampsMergePeopleInput`, `GrampsMergePeopleTool` avec
  `_run(phoenix_handle: str, titanic_handle: str, family_merger: bool = True, dry_run: bool = False) -> str`. Consommé par la Task 8.

- [ ] **Step 1: Écrire le test qui échoue**

Créer `/Users/fjacquet/Projects/crewai_custom_tools/tests/test_genealogy_merge_people_tool.py` :

```python
"""GrampsMergePeopleTool — phoenix survit, titanic disparaît. Irréversible."""

import json

import pytest

from crewai_custom_tools.tools.genealogy.gramps import write_tools
from crewai_custom_tools.tools.genealogy.gramps.write_tools import GrampsMergePeopleTool


class _ClientEspion:
    def __init__(self):
        self.appels = []

    def request(self, methode, chemin, **kwargs):
        self.appels.append((methode, chemin, kwargs))
        return type("R", (), {"content": b"", "json": lambda self: {}})()


@pytest.fixture
def espion(monkeypatch):
    client = _ClientEspion()
    monkeypatch.setattr(write_tools, "get_client", lambda: client)
    monkeypatch.delenv("GENECREW_DRY_RUN", raising=False)
    return client


def test_dry_run_n_ecrit_rien(espion):
    payload = json.loads(GrampsMergePeopleTool()._run(
        phoenix_handle="hA", titanic_handle="hB", dry_run=True))
    assert payload["success"] is True
    assert payload["data"]["dry_run"] is True
    assert espion.appels == []


def test_ecriture_reelle_appelle_le_bon_endpoint(espion):
    payload = json.loads(GrampsMergePeopleTool()._run(
        phoenix_handle="hA", titanic_handle="hB", dry_run=False))
    assert payload["success"] is True
    methode, chemin, kwargs = espion.appels[0]
    assert methode == "POST"
    assert chemin == "/people/hA/merge/hB"
    assert kwargs["json"] == {"family_merger": True}


def test_family_merger_desactivable(espion):
    GrampsMergePeopleTool()._run(phoenix_handle="hA", titanic_handle="hB",
                                 family_merger=False, dry_run=False)
    assert espion.appels[0][2]["json"] == {"family_merger": False}


def test_env_force_la_simulation(espion, monkeypatch):
    """GENECREW_DRY_RUN ne peut que rendre l'appel PLUS sûr."""
    monkeypatch.setenv("GENECREW_DRY_RUN", "true")
    payload = json.loads(GrampsMergePeopleTool()._run(
        phoenix_handle="hA", titanic_handle="hB", dry_run=False))
    assert payload["data"]["dry_run"] is True
    assert espion.appels == []
```

- [ ] **Step 2: Lancer le test pour vérifier qu'il échoue**

```bash
cd /Users/fjacquet/Projects/crewai_custom_tools && uv run python -m pytest tests/test_genealogy_merge_people_tool.py -q
```

Attendu : `ImportError: cannot import name 'GrampsMergePeopleTool'`.

- [ ] **Step 3: Écrire l'implémentation minimale**

Insérer dans `/Users/fjacquet/Projects/crewai_custom_tools/src/crewai_custom_tools/tools/genealogy/gramps/write_tools.py`, juste après `GrampsMergePlacesTool` (avant le commentaire `# --- Écriture encadrée append-only pour la crew`) :

```python
class GrampsMergePeopleInput(BaseModel):
    phoenix_handle: str = Field(..., description="Handle of the person that survives.")
    titanic_handle: str = Field(..., description="Handle of the person that is deleted.")
    family_merger: bool = Field(
        True, description="Also merge spouse/parent families made duplicate by the merge.")
    dry_run: bool = Field(False, description="If true, POST nothing and report the intent.")


class GrampsMergePeopleTool(BaseTool):
    """Merge two people. Phoenix survives; titanic is deleted. IRREVERSIBLE.

    Gramps unions every list (events, citations, notes, media, attributes, tags,
    families), demotes the titanic's primary name to an alternate name, and records
    a `Merged Gramps ID` attribute. It does NOT merge gender — the caller must patch
    the phoenix beforehand when needed (see analysis/merge_plan.py).
    """

    name: str = "gramps_merge_people"
    description: str = (
        "Merges the titanic person into the phoenix person in Gramps. The phoenix "
        "survives and the titanic is deleted — this cannot be undone. Writes unless "
        "dry_run is set or GENECREW_DRY_RUN is enabled."
    )
    args_schema: type[BaseModel] = GrampsMergePeopleInput

    @api_tool(provider="GrampsWeb", endpoint="MergePeople")
    def _run(self, phoenix_handle: str, titanic_handle: str,
             family_merger: bool = True, dry_run: bool = False) -> str:
        dry_run = effective_dry_run(dry_run)
        change = {"phoenix": phoenix_handle, "titanic": titanic_handle,
                  "family_merger": family_merger, "dry_run": dry_run}
        if not dry_run:
            get_client().request(
                "POST", f"/people/{phoenix_handle}/merge/{titanic_handle}",
                json={"family_merger": family_merger})
        return ok(change)
```

- [ ] **Step 4: Lancer le test pour vérifier qu'il passe**

```bash
cd /Users/fjacquet/Projects/crewai_custom_tools && uv run python -m pytest tests/test_genealogy_merge_people_tool.py -q && uv run python -m pytest tests/ -q && uv run ruff check src/
```

Attendu : `4 passed` puis la suite complète verte, `All checks passed!`.

- [ ] **Step 5: Commit**

```bash
cd /Users/fjacquet/Projects/crewai_custom_tools
git add src/crewai_custom_tools/tools/genealogy/gramps/write_tools.py tests/test_genealogy_merge_people_tool.py
git commit -m "feat(doublons): GrampsMergePeopleTool, phoenix survit et titanic disparaît

PersonMergeArgs n'a qu'un bouton, family_merger. Aucun contrôle champ par
champ n'existe : le seul levier est le choix du phoenix, plus le patch de
genre décidé en amont.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 7 : Publier la bibliothèque

Cette tâche franchit la frontière entre les deux dépôts. La CI de genecrew checkoute `crewai_custom_tools` sur le **tag** lu dans `uv.lock` : sans tag poussé, les Tasks 8 et 9 ne peuvent pas verdir.

**Le tag et la publication sont un contrôle qualité délibéré. Ne jamais taguer ni pousser sans accord explicite de l'utilisateur.**

**Files:**
- Modify: `/Users/fjacquet/Projects/crewai_custom_tools/pyproject.toml` (ligne 7)
- Modify: `/Users/fjacquet/Projects/genecrew/uv.lock` (via `uv sync`)

- [ ] **Step 1: Vérifier que la suite complète est verte**

```bash
cd /Users/fjacquet/Projects/crewai_custom_tools && uv run python -m pytest tests/ -q && uv run ruff check src/
```

Attendu : tout vert. Ne pas continuer sinon.

- [ ] **Step 2: Monter la version**

Dans `/Users/fjacquet/Projects/crewai_custom_tools/pyproject.toml`, ligne 7 : remplacer `version = "0.21.0"` par `version = "0.22.0"`.

Version mineure : trois modules publics s'ajoutent (`phonetics`, `merge_plan`, l'outil de fusion) sans rien casser.

- [ ] **Step 3: Commiter la version**

```bash
cd /Users/fjacquet/Projects/crewai_custom_tools
git add pyproject.toml
git commit -m "chore(release): 0.22.0 — fusion des doublons de personnes

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

- [ ] **Step 4: DEMANDER À L'UTILISATEUR de taguer et pousser**

S'arrêter et présenter la commande sans l'exécuter :

```bash
cd /Users/fjacquet/Projects/crewai_custom_tools
git tag v0.22.0 && git push && git push --tags
```

Attendre l'accord explicite. Ne pas enchaîner.

- [ ] **Step 5: Resynchroniser genecrew**

Une fois le tag poussé :

```bash
cd /Users/fjacquet/Projects/genecrew && uv sync && uv run python -c "import crewai_custom_tools.tools.genealogy.analysis.merge_plan as m; print(m.__name__, 'ok')"
```

Attendu : `crewai_custom_tools.tools.genealogy.analysis.merge_plan ok`.

- [ ] **Step 6: Commit du lock**

```bash
cd /Users/fjacquet/Projects/genecrew
git add uv.lock
git commit -m "chore: crewai-custom-tools 0.22.0 (fusion des doublons)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 8 : L'orchestration `people_merge.py`

**Files:**
- Create: `/Users/fjacquet/Projects/genecrew/genecrew/src/genecrew/people_merge.py`
- Test: `/Users/fjacquet/Projects/genecrew/genecrew/tests/test_people_merge.py`

**Interfaces:**
- Consumes: `etager` (Task 4), `plan_fusions` (Task 5), `GrampsMergePeopleTool` (Task 6), `GrampsUpdateGenderTool` (existant), `iter_people_batches` (existant), `FactsFetcher` (existant).
- Produces:
  - `executer_grappes(grappes, *, dry_run=False) -> tuple[list, list]` — rend `(faites, erreurs)`.
  - `render_people_merge_report(date, passes, arbitrage, ignores, dry_run, base_url="http://localhost") -> str`
  - `run_people_merge(client, output_dir, *, scope, date, limit=None, max_passes=5, dry_run=False) -> Path`
  - `run_people_merge_yaml(client, merges_yaml, output_dir, *, date, dry_run=False) -> Path`
  Consommés par la Task 9.

- [ ] **Step 1: Écrire le test qui échoue**

Créer `/Users/fjacquet/Projects/genecrew/genecrew/tests/test_people_merge.py` :

```python
"""Orchestration des fusions de personnes : exécution, patch de genre, rapport."""

import json

import pytest

from crewai_custom_tools.tools.genealogy.models.domain import MergeCluster
from genecrew import people_merge


class _OutilEspion:
    def __init__(self, echecs=()):
        self.appels = []
        self._echecs = set(echecs)

    def _run(self, **kwargs):
        self.appels.append(kwargs)
        titanic = kwargs.get("titanic_handle") or kwargs.get("handle")
        if titanic in self._echecs:
            return json.dumps({"success": False, "error": "boom"})
        return json.dumps({"success": True, "data": kwargs})


@pytest.fixture
def outils(monkeypatch):
    fusion, genre = _OutilEspion(), _OutilEspion()
    monkeypatch.setattr(people_merge, "GrampsMergePeopleTool", lambda: fusion)
    monkeypatch.setattr(people_merge, "GrampsUpdateGenderTool", lambda: genre)
    return fusion, genre


def _grappe(gender_patch=None, titanics=("hI2",)):
    return MergeCluster(phoenix_handle="hI1", phoenix_gramps_id="I1",
                        titanic_handles=list(titanics),
                        titanic_gramps_ids=[t.replace("h", "") for t in titanics],
                        gender_patch=gender_patch)


def test_une_grappe_fusionne_chaque_titanic(outils):
    fusion, _ = outils
    faites, erreurs = people_merge.executer_grappes(
        [_grappe(titanics=("hI2", "hI3"))], dry_run=False)
    assert len(fusion.appels) == 2
    assert erreurs == []
    assert len(faites) == 2


def test_le_patch_de_genre_precede_la_fusion(outils):
    """Person.merge() ignore le genre : patcher APRÈS ne servirait à rien."""
    fusion, genre = outils
    ordre = []
    genre._run = lambda **kw: (ordre.append("genre"), json.dumps({"success": True}))[1]
    fusion._run = lambda **kw: (ordre.append("fusion"), json.dumps({"success": True}))[1]
    people_merge.executer_grappes([_grappe(gender_patch=1)], dry_run=False)
    assert ordre == ["genre", "fusion"]


def test_sans_patch_le_genre_n_est_pas_touche(outils):
    _, genre = outils
    people_merge.executer_grappes([_grappe(gender_patch=None)], dry_run=False)
    assert genre.appels == []


def test_une_erreur_est_consignee_et_le_lot_continue(outils):
    fusion, _ = outils
    fusion._echecs = {"hI2"}
    faites, erreurs = people_merge.executer_grappes(
        [_grappe(titanics=("hI2", "hI3"))], dry_run=False)
    assert len(erreurs) == 1
    assert len(faites) == 1


def test_dry_run_transmis_aux_outils(outils):
    fusion, genre = outils
    people_merge.executer_grappes([_grappe(gender_patch=1)], dry_run=True)
    assert fusion.appels[0]["dry_run"] is True
    assert genre.appels[0]["dry_run"] is True


def test_rapport_annonce_le_mode_et_invite_a_relancer():
    rapport = people_merge.render_people_merge_report(
        "2026-07-20", passes=[(1, 3, 0)], arbitrage=[], ignores=["nom:pagan"],
        dry_run=True)
    assert "simulation" in rapport
    assert "nom:pagan" in rapport
    assert "relancer" in rapport.lower()


def test_rapport_sans_fusion_n_invite_pas_a_relancer():
    rapport = people_merge.render_people_merge_report(
        "2026-07-20", passes=[(1, 0, 0)], arbitrage=[], ignores=[], dry_run=False)
    assert "relancer" not in rapport.lower()
```

- [ ] **Step 2: Lancer le test pour vérifier qu'il échoue**

```bash
cd /Users/fjacquet/Projects/genecrew && uv run python -m pytest genecrew/tests/test_people_merge.py -q
```

Attendu : `ModuleNotFoundError: No module named 'genecrew.people_merge'`.

- [ ] **Step 3: Écrire l'implémentation minimale**

Créer `/Users/fjacquet/Projects/genecrew/genecrew/src/genecrew/people_merge.py` :

```python
"""Fusion des doublons de personnes : étage auto exécuté, reste déposé en YAML.

Seul module du chantier à toucher au réseau — toute l'analyse est pure et vit
dans crewai_custom_tools. Voir docs/superpowers/specs/2026-07-20-fusion-doublons-personnes-design.md.
"""

from __future__ import annotations

import json
from pathlib import Path

import yaml

from crewai_custom_tools.tools.genealogy.analysis.duplicates import etager
from crewai_custom_tools.tools.genealogy.analysis.merge_plan import plan_fusions
from crewai_custom_tools.tools.genealogy.gramps.client import GrampsClient
from crewai_custom_tools.tools.genealogy.gramps.facts import FactsFetcher
from crewai_custom_tools.tools.genealogy.gramps.write_tools import (
    GrampsMergePeopleTool,
    GrampsUpdateGenderTool,
    effective_dry_run,
)
from crewai_custom_tools.tools.genealogy.models.domain import MergeCluster
from genecrew.batching import iter_people_batches

_TAILLE_LOT = 200


def _link(gramps_id: str, base_url: str) -> str:
    return f"[{gramps_id}]({base_url}/person/{gramps_id})"


def executer_grappes(grappes: list[MergeCluster], *, dry_run: bool = False
                     ) -> tuple[list[tuple[str, str]], list[tuple[str, str]]]:
    """Exécute les fusions d'une liste de grappes. Rend (faites, erreurs).

    Le patch de genre précède impérativement la fusion : `Person.merge()` ignore
    le genre, le patcher après n'aurait aucun effet sur le résultat (spec §4.4).
    """
    fusion = GrampsMergePeopleTool()
    genre = GrampsUpdateGenderTool()
    faites: list[tuple[str, str]] = []
    erreurs: list[tuple[str, str]] = []
    for grappe in grappes:
        if grappe.gender_patch is not None:
            genre._run(handle=grappe.phoenix_handle, gender=grappe.gender_patch,
                       dry_run=dry_run)
        for titanic_handle, titanic_id in zip(grappe.titanic_handles,
                                              grappe.titanic_gramps_ids):
            payload = json.loads(fusion._run(phoenix_handle=grappe.phoenix_handle,
                                             titanic_handle=titanic_handle,
                                             dry_run=dry_run))
            if payload["success"]:
                faites.append((grappe.phoenix_gramps_id, titanic_id))
            else:
                erreurs.append((titanic_id, payload["error"]))
    return faites, erreurs


def render_people_merge_report(date, passes, arbitrage, ignores, dry_run,
                               base_url: str = "http://localhost") -> str:
    """Rapport Markdown : une ligne par passe, plus les paires à relire."""
    mode = "simulation (dry-run, aucune fusion)" if dry_run else "fusions appliquées"
    total = sum(faites for _, faites, _ in passes)
    lines = [f"# Fusion des doublons de personnes — {date}", "",
             f"Mode : {mode}.", "",
             f"- Fusions automatiques : {total}",
             f"- Paires en arbitrage : {len(arbitrage)}",
             f"- Blocs ignorés (trop gros) : {len(ignores)}", "",
             "## Passes", "", "| Passe | Fusions | Erreurs |", "|---|---|---|"]
    for numero, faites, erreurs in passes:
        lines.append(f"| {numero} | {faites} | {erreurs} |")
    derniere = passes[-1][1] if passes else 0
    if derniere:
        lines += ["", "La dernière passe a encore fusionné : la déduplication est "
                  "transitive, **relancer** la commande pour aller plus loin."]
    lines += ["", "## Paires en arbitrage", ""]
    if arbitrage:
        lines += ["| A | B | Blocs |", "|---|---|---|"]
        for paire in arbitrage:
            lines.append(f"| {_link(paire.gramps_id_a, base_url)} | "
                         f"{_link(paire.gramps_id_b, base_url)} | "
                         f"{', '.join(paire.blocs)} |")
    else:
        lines.append("Aucune.")
    lines += ["", "## Blocs ignorés", ""]
    lines.append(", ".join(f"`{c}`" for c in ignores) if ignores else "Aucun.")
    lines.append("")
    return "\n".join(lines)


def _collecter(client: GrampsClient, scope: str, limit: int | None):
    """Rend (personnes, familles) pour le périmètre demandé."""
    fetcher = FactsFetcher(client)
    personnes = []
    for lot in iter_people_batches(client, fetcher, scope, _TAILLE_LOT, limit):
        personnes.extend(lot)
    familles: dict = {}
    for personne in personnes:
        for handle in (*personne.parent_family_handles, *personne.family_handles):
            if handle not in familles:
                famille = fetcher.get_family_facts(handle)
                if famille is not None:
                    familles[handle] = famille
    return personnes, familles


def run_people_merge(client: GrampsClient, output_dir, *, scope: str, date: str,
                     limit: int | None = None, max_passes: int = 5,
                     dry_run: bool = False) -> Path:
    """Détecte, fusionne l'étage auto, dépose l'arbitrage en YAML. Rend le rapport."""
    output_dir = Path(output_dir)
    passes: list[tuple[int, int, int]] = []
    arbitrage: list = []
    ignores: list[str] = []
    for numero in range(1, max_passes + 1):
        personnes, familles = _collecter(client, scope, limit)
        paires, ignores = etager(personnes, familles)
        arbitrage = [p for p in paires if p.tier == "arbitrage"]
        grappes = plan_fusions(paires, {p.handle: p for p in personnes})
        faites, erreurs = executer_grappes(grappes, dry_run=dry_run)
        passes.append((numero, len(faites), len(erreurs)))
        # En simulation, rien n'a changé côté serveur : une seconde passe
        # relirait les mêmes données et boucler serait sans objet.
        if not faites or dry_run:
            break
    out = output_dir / "doublons"
    out.mkdir(parents=True, exist_ok=True)
    scope_slug = scope.replace(":", "_")
    (out / f"{date}_arbitrage_doublons_{scope_slug}.yaml").write_text(
        yaml.safe_dump([p.model_dump() for p in arbitrage], allow_unicode=True,
                       sort_keys=False), encoding="utf-8")
    path = out / f"{date}_fusions_doublons_{scope_slug}.md"
    path.write_text(render_people_merge_report(date, passes, arbitrage, ignores,
                                               effective_dry_run(dry_run)),
                    encoding="utf-8")
    return path


def run_people_merge_yaml(client: GrampsClient, merges_yaml, output_dir, *,
                          date: str, dry_run: bool = False) -> Path:
    """Exécute les paires d'arbitrage conservées après relecture humaine."""
    output_dir = Path(output_dir)
    paires = yaml.safe_load(Path(merges_yaml).read_text(encoding="utf-8")) or []
    grappes = [MergeCluster(phoenix_handle=p["handle_a"],
                            phoenix_gramps_id=p["gramps_id_a"],
                            titanic_handles=[p["handle_b"]],
                            titanic_gramps_ids=[p["gramps_id_b"]])
               for p in paires]
    faites, erreurs = executer_grappes(grappes, dry_run=dry_run)
    out = output_dir / "doublons"
    out.mkdir(parents=True, exist_ok=True)
    slug = Path(merges_yaml).stem
    path = out / f"{date}_fusions_relues_{slug}.md"
    path.write_text(
        render_people_merge_report(date, [(1, len(faites), len(erreurs))], [], [],
                                   effective_dry_run(dry_run)),
        encoding="utf-8")
    return path
```

- [ ] **Step 4: Lancer le test pour vérifier qu'il passe**

```bash
cd /Users/fjacquet/Projects/genecrew && uv run python -m pytest genecrew/tests/test_people_merge.py -q && uv run ruff check genecrew/src/genecrew/people_merge.py
```

Attendu : `7 passed`, `All checks passed!`.

- [ ] **Step 5: Commit**

```bash
cd /Users/fjacquet/Projects/genecrew
git add genecrew/src/genecrew/people_merge.py genecrew/tests/test_people_merge.py
git commit -m "feat(doublons): orchestration des fusions, passes jusqu'à convergence

Le patch de genre précède la fusion — l'inverse serait sans effet. Le
rapport invite à relancer tant qu'une passe fusionne encore : deux copies
d'une personne ont souvent des parents eux-mêmes dupliqués, et la règle
« mêmes parents » ne se débloque qu'une fois ceux-ci fusionnés.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 9 : La feuille CLI et la documentation

**Files:**
- Modify: `/Users/fjacquet/Projects/genecrew/genecrew/src/genecrew/cli.py:142-149`
- Modify: `/Users/fjacquet/Projects/genecrew/genecrew/src/genecrew/main.py:409` et la section des commandes
- Modify: `/Users/fjacquet/Projects/genecrew/CLAUDE.md`
- Modify: `/Users/fjacquet/Projects/genecrew/docs/document-de-travail.md:68`
- Test: `/Users/fjacquet/Projects/genecrew/genecrew/tests/test_cli_parser.py`, `/Users/fjacquet/Projects/genecrew/genecrew/tests/test_cli_dispatch.py`

**Interfaces:**
- Consumes: `run_people_merge`, `run_people_merge_yaml` (Task 8).
- Produces: la commande `genecrew merge people`.

- [ ] **Step 1: Écrire les tests qui échouent**

Ajouter à `/Users/fjacquet/Projects/genecrew/genecrew/tests/test_cli_parser.py` :

```python
def test_merge_people_accepte_le_mode_detection():
    args = build_parser().parse_args(
        ["merge", "people", "--scope", "all", "--limit", "50", "--dry-run"])
    assert (args.command, args.target) == ("merge", "people")
    assert args.scope == "all"
    assert args.limit == 50
    assert args.dry_run is True
    assert args.yaml is None
    assert args.max_passes == 5


def test_merge_people_accepte_un_yaml_relu():
    args = build_parser().parse_args(["merge", "people", "--yaml", "arbitrage.yaml"])
    assert args.yaml == "arbitrage.yaml"
```

Ajouter à `/Users/fjacquet/Projects/genecrew/genecrew/tests/test_cli_dispatch.py` :

```python
def test_merge_people_est_route():
    from genecrew.cli import build_parser
    args = build_parser().parse_args(["merge", "people"])
    assert (args.command, args.target) == ("merge", "people")
```

- [ ] **Step 2: Lancer les tests pour vérifier qu'ils échouent**

```bash
cd /Users/fjacquet/Projects/genecrew && uv run python -m pytest genecrew/tests/test_cli_parser.py genecrew/tests/test_cli_dispatch.py -q
```

Attendu : `argparse` sort en erreur sur `invalid choice: 'people'`.

- [ ] **Step 3: Écrire l'implémentation**

**3a.** Dans `/Users/fjacquet/Projects/genecrew/genecrew/src/genecrew/cli.py`, remplacer le bloc `merge` (lignes 142-149) par :

```python
    # --- merge : la fusion des lieux vient d'un YAML relu ; celle des personnes
    # est automatique au-dessus d'une preuve STRUCTURELLE, jamais d'un score
    # (voir docs/superpowers/specs/2026-07-20-fusion-doublons-personnes-design.md).
    merge_p = sub.add_parser("merge", help="Fusions : lieux relus, personnes sur preuve")
    merge_sub = merge_p.add_subparsers(dest="target", required=True)

    p = merge_sub.add_parser("places", help="Fusionne les lieux listés dans un YAML relu")
    _add_yaml(p)
    _add_dry_run(p)
    _add_date(p)

    p = merge_sub.add_parser(
        "people",
        help="Fusionne les doublons prouvés ; dépose le reste en YAML d'arbitrage")
    _add_scope(p)
    p.add_argument("--yaml", default=None,
                   help="exécuter les paires d'un YAML d'arbitrage relu, au lieu de détecter")
    p.add_argument("--max-passes", type=int, default=5,
                   help="bornes des passes de convergence (défaut : 5)")
    _add_dry_run(p)
    _add_date(p)
```

> `_add_yaml` impose l'argument ; pour `people` le YAML est optionnel, d'où l'`add_argument` explicite.

**3b.** Dans `/Users/fjacquet/Projects/genecrew/genecrew/src/genecrew/main.py`, ajouter la fonction de commande à côté de `lieux_merge_cmd` (vers la ligne 272) :

```python
def people_merge_cmd(args) -> None:
    from genecrew.people_merge import run_people_merge, run_people_merge_yaml

    client = GrampsClient()
    output_dir = Path(os.environ.get("GENECREW_OUTPUT_DIR", "output"))
    date = args.date or datetime.now().date().isoformat()
    if args.yaml:
        report = run_people_merge_yaml(client, args.yaml, output_dir, date=date,
                                       dry_run=args.dry_run)
    else:
        report = run_people_merge(client, output_dir, scope=args.scope, date=date,
                                  limit=args.limit, max_passes=args.max_passes,
                                  dry_run=args.dry_run)
    print(f"Rapport : {report}")
```

> Reprendre exactement la façon dont `lieux_merge_cmd` construit `client`, `output_dir` et `date` : si elle utilise des helpers locaux, les réutiliser plutôt que de dupliquer.

**3c.** Ajouter au dictionnaire `dispatch` de `main.py`, juste après la ligne `("merge", "places")` :

```python
        ("merge", "people"): lambda: people_merge_cmd(args),
```

**3d.** Dans `/Users/fjacquet/Projects/genecrew/docs/document-de-travail.md`, ligne 68, remplacer la mention de la fusion par :

```markdown
- **Interdites aux agents, toujours en proposition pour revue humaine** : suppression, fusion
  — **sauf** la fusion de personnes adossée à une preuve structurelle vérifiable (date de
  naissance complète identique, mêmes parents, conjoint et enfant communs), automatisée par
  `merge people`. L'amendement est borné : il ne repose sur aucun seuil numérique, et toute
  paire à preuve partielle repasse par un YAML relu.
  Voir `docs/superpowers/specs/2026-07-20-fusion-doublons-personnes-design.md`.
```

**3e.** Dans `/Users/fjacquet/Projects/genecrew/CLAUDE.md` :

- section `cli.py`, remplacer `merge {places}` par `merge {places|people}` ;
- ajouter à la liste des commandes :

```bash
uv run genecrew merge people --scope all --limit 200 --dry-run  # fusionne les doublons prouvés, YAML pour le reste
uv run genecrew merge people --yaml <arbitrage.yaml>            # exécute les paires relues
```

- ajouter aux gotchas :

```markdown
- **Fusion de personnes irréversible** : `Person.merge()` supprime le titanic et unionne les
  listes à plat — rien ne dit ensuite quel événement venait de qui. `merge people` ne fusionne
  donc automatiquement que sur preuve **structurelle** (date complète identique, mêmes parents,
  conjoint + enfant communs), jamais sur une ressemblance de nom : `marie pagan` et
  `marie pagani` scorent 0.957 alors que ce sont deux lignées. `PersonMergeArgs` n'offre aucun
  contrôle champ par champ, et **le genre n'est pas unionné** — d'où l'unique patch préalable.
  La déduplication est transitive : relancer jusqu'à ce qu'une passe ne fusionne plus rien.
```

- [ ] **Step 4: Lancer la suite complète**

```bash
cd /Users/fjacquet/Projects/genecrew && uv run python -m pytest genecrew/tests/ -q && uv run ruff check .
```

Attendu : toute la suite verte, `All checks passed!`.

- [ ] **Step 5: Vérifier la commande de bout en bout, en simulation**

```bash
cd /Users/fjacquet/Projects/genecrew && uv run genecrew merge people --help
```

Attendu : l'aide affiche `--scope`, `--limit`, `--yaml`, `--max-passes`, `--dry-run`, `--date`.

> Un essai contre la base vivante (`--scope person:I0042 --dry-run`) suppose la pile Gramps Web démarrée depuis le dépôt `gramps-mcp`. Le proposer à l'utilisateur ; ne pas la démarrer d'autorité.

- [ ] **Step 6: Commit**

```bash
cd /Users/fjacquet/Projects/genecrew
git add genecrew/src/genecrew/cli.py genecrew/src/genecrew/main.py \
        genecrew/tests/test_cli_parser.py genecrew/tests/test_cli_dispatch.py \
        CLAUDE.md docs/document-de-travail.md
git commit -m "feat(doublons): merge people, et l'amendement assumé de la règle de fusion

merge gagne une feuille, aucun verbe nouveau (ADR 0012). Le document de
travail interdisait toute fusion automatique : l'interdiction est levée
pour la seule preuve structurelle, et le reste continue de passer par un
YAML relu.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Auto-revue

**Couverture de la spec.**

| Section | Tâche |
|---|---|
| §2 — un seul bouton, genre non unionné | Tasks 5, 6 |
| §3.1 — le nom n'est jamais une preuve | Task 4 (`test_piege_pagan_contre_pagani`) |
| §3.4 — transitivité | Tasks 5, 8 |
| §4.1 — trois étages, trois règles, règle rejetée | Task 4 |
| §4.2 — cinq clés, `MAX_BLOC`, clé phonétique | Tasks 1, 3 |
| §4.3 — arbitrage LLM | **Plan 2**, hors périmètre |
| §4.4 — phoenix et patch du genre | Task 5 |
| §4.5 — grappes | Task 5 |
| §5 — surface CLI | Task 9 |
| §6 — découpage | Tasks 1-9 |
| §7 — corpus de pièges | Task 4 |
| §8 — erreurs | Task 8 |
| §1.2 — amendement de la règle fondatrice | Task 9 (étape 3d) |

**Cohérence des types.** `MergePair.tier` / `MergeCluster.gender_patch` (Task 2) sont consommés tels quels par `etager` (Task 4), `plan_fusions` (Task 5) et `executer_grappes` (Task 8). `etager` rend un **tuple** `(paires, ignores)` partout où il est appelé. `candidate_pairs` rend un tuple `(paires, ignores)`, cohérent entre Tasks 3 et 4. Les handles de paires sont normalisés par `tuple(sorted(...))` en Task 3 et supposés tels en Task 5.

**Cycle d'import : résolu par conception, pas laissé en surveillance.** `normalize_name` déménage dans `phonetics.py` dès la Task 1, et `duplicates.py` la réexporte. `phonetics` ne dépend de rien, `duplicates` dépend de `phonetics` — un seul sens. `test_genealogy_duplicates.py` importe `normalize_name` depuis `duplicates` et sert de test de non-régression à cette réexportation, sans être modifié.

**Ce que ce plan ne fait pas.** L'arbitrage LLM (Plan 2) ; la fusion des familles, événements et sources ; le rebranchement des doublons sur `crew_audit.py:181`, qui continue de les jeter.
