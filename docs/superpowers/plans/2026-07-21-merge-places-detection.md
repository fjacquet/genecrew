# Détection des doublons de lieux — plan d'implémentation

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Donner à `merge places` le mode détection qui lui manque — trouver les doublons de lieux, fusionner ceux qui sont prouvés, déposer les autres en arbitrage — pour que les doublons déjà typés cessent d'être invisibles au pipeline.

**Architecture:** La détection est **pure** et vit dans `crewai_custom_tools/analysis/place_duplicates.py`, à côté de `duplicates.py` qui fait la même chose pour les personnes. L'orchestration — collecte paginée, exécution des fusions, rapport, YAML d'arbitrage — reste dans `genecrew/places_merge.py`, à côté de l'exécutant existant. La grammaire CLI ne bouge pas : `merge places` gagne `--scope` et son `--yaml` devient optionnel, exactement comme `merge people`.

**Tech Stack:** Python 3.12, `uv`, pydantic v2, `httpx` (+ `MockTransport` pour les tests), pytest, argparse.

## Global Constraints

- Spec de référence : `docs/superpowers/specs/2026-07-21-merge-places-detection-design.md` (commit `52d562f`).
- **Deux arbres de travail isolés**, à ne pas confondre :
  - genecrew → `/Users/fjacquet/Projects/fusions-lieux/genecrew`, branche `feat/merge-places-detection` ;
  - bibliothèque → `/Users/fjacquet/Projects/fusions-lieux/crewai_custom_tools`, branche `feat/fusion-doublons-lieux`.
- Chaque commande se lance **depuis la racine de l'arbre concerné**. Ne jamais toucher aux clones principaux (`/Users/fjacquet/Projects/genecrew`, `/Users/fjacquet/Projects/crewai_custom_tools`) ni aux arbres sous `.claude/worktrees/` — ils portent un autre chantier.
- Python **toujours via `uv`** — jamais `pip` ni `python` direct.
- Tests genecrew : `uv run python -m pytest genecrew/tests/ -q` (ligne de base : **365 passed**).
- Tests bibliothèque : `uv run python -m pytest tests/ -q` (ligne de base : **871 passed**).
- Lint : `uv run ruff check .` dans les deux dépôts.
- Tests **offline** : aucun appel réseau réel, `httpx.MockTransport` ou stub.
- Écriture Gramps toujours derrière `effective_dry_run` ; le rapport affiche le dry-run **effectif**.
- Commits en français, préfixe conventionnel, se terminant par `Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>`.
- **Aucun agent ne pousse, ne tague ni ne merge.** Ces gestes sont des portes humaines.
- Projet en français : accents et Unicode préservés exactement, code et messages de commit compris.

## Écart assumé avec la spec

La spec §5 prévoit des **passes de convergence** bornées par `--max-passes`, par symétrie avec `merge people`. Ce plan n'en implémente **aucune**, et n'ajoute pas l'option.

Raison : chez les personnes, une fusion peut en révéler d'autres — deux enfants deviennent doublons une fois leurs parents fusionnés, d'où la transitivité et les passes. Chez les lieux, les candidats sont groupés par **égalité de nom normalisé**, qui est une relation d'équivalence : les groupes sont complets dès la première lecture, et fusionner deux lieux ne renomme aucun autre. Verrens-Arvey en trois exemplaires forme un seul groupe, traité en une passe.

Une boucle de convergence serait donc du code mort, et une option `--max-passes` une promesse creuse. Elles s'ajouteront le jour où un critère de candidature non transitif apparaîtra.

---

### Task 1 : les modèles (bibliothèque)

**Files:**
- Modify: `/Users/fjacquet/Projects/fusions-lieux/crewai_custom_tools/src/crewai_custom_tools/tools/genealogy/models/domain.py:156-165`
- Test: `/Users/fjacquet/Projects/fusions-lieux/crewai_custom_tools/tests/test_genealogy_merge_models.py`

**Interfaces:**
- Consumes: rien.
- Produces: `PlaceFacts` (nouveau modèle) et deux champs optionnels sur `PlaceMergeProposition` (`verdict: str = ""`, `perte_evitee: str = ""`). Consommés par les Tasks 2 à 8.

- [ ] **Step 1 : se placer dans l'arbre bibliothèque**

```bash
cd /Users/fjacquet/Projects/fusions-lieux/crewai_custom_tools
git branch --show-current      # doit afficher feat/fusion-doublons-lieux
git status --short             # doit être vide
```

- [ ] **Step 2 : écrire les tests qui échouent**

Ajouter à la fin de `tests/test_genealogy_merge_models.py` :

```python
def test_place_facts_defauts_vides():
    """Un lieu sans code ni coordonnées se construit : l'arbre en est plein."""
    from crewai_custom_tools.tools.genealogy.models.domain import PlaceFacts

    p = PlaceFacts(gramps_id="P0068", handle="H68", nom="Saint-Palais")
    assert p.place_type == ""
    assert p.code == ""
    assert p.lat == "" and p.long == ""
    assert p.a_parent is False
    assert p.retroliens == 0


def test_place_facts_complet():
    from crewai_custom_tools.tools.genealogy.models.domain import PlaceFacts

    p = PlaceFacts(gramps_id="P0000", handle="H0", nom="Bourges",
                   place_type="Municipality", code="18033",
                   lat="47.0810", long="2.3988", a_parent=True, retroliens=53)
    assert (p.code, p.retroliens, p.a_parent) == ("18033", 53, True)


def test_place_merge_proposition_champs_de_rapport_optionnels():
    """Un YAML de fusions antérieur reste chargeable : les deux champs sont optionnels."""
    from crewai_custom_tools.tools.genealogy.models.domain import PlaceMergeProposition

    p = PlaceMergeProposition(
        gramps_id_keep="P0002", handle_keep="HA", gramps_id_merge="P0188",
        handle_merge="HB", canonical="Saint-Martin-d'Auxigny", reason="doublon")
    assert p.verdict == ""
    assert p.perte_evitee == ""
```

- [ ] **Step 3 : lancer les tests pour les voir échouer**

```bash
cd /Users/fjacquet/Projects/fusions-lieux/crewai_custom_tools
uv run python -m pytest tests/test_genealogy_merge_models.py -q
```

Attendu : ÉCHEC — `ImportError: cannot import name 'PlaceFacts'` sur les deux premiers, `AttributeError` sur `verdict` pour le troisième.

- [ ] **Step 4 : ajouter les modèles**

Dans `src/crewai_custom_tools/tools/genealogy/models/domain.py`, **juste avant** la classe `PlaceMergeProposition` (ligne 156), insérer :

```python
class PlaceFacts(BaseModel):
    """Faits normalisés d'un lieu, pour la détection de doublons. Pur.

    Volontairement plat : la détection ne raisonne que sur ce qui distingue deux
    lieux homonymes — leur type, leur code officiel, leurs coordonnées, et le
    poids qu'ils portent dans l'arbre. Tout le reste appartient à l'orchestration.
    """

    gramps_id: str
    handle: str
    nom: str
    place_type: str = ""
    code: str = Field(default="", description="Code officiel (INSEE ou équivalent national).")
    lat: str = ""
    long: str = ""
    a_parent: bool = Field(default=False, description="Le lieu est rattaché à un contenant.")
    retroliens: int = Field(default=0, description="Nombre d'objets qui référencent ce lieu.")
```

Puis, à la fin de la classe `PlaceMergeProposition` (après le champ `reason`), ajouter :

```python
    # Renseignés par la détection ; absents des YAML écrits avant elle, d'où les défauts.
    verdict: str = Field(default="", description="'auto' (preuve) ou 'arbitrage' (relecture).")
    perte_evitee: str = Field(
        default="",
        description="Ce que l'ordre inverse aurait effacé — la fusion Gramps écrase "
                    "les champs simples du lieu absorbé.")
```

- [ ] **Step 5 : lancer les tests pour les voir passer**

```bash
cd /Users/fjacquet/Projects/fusions-lieux/crewai_custom_tools
uv run python -m pytest tests/test_genealogy_merge_models.py -q && uv run python -m pytest tests/ -q
```

Attendu : le fichier au vert, puis **874 passed** sur la suite complète (871 + 3).

- [ ] **Step 6 : commiter**

```bash
cd /Users/fjacquet/Projects/fusions-lieux/crewai_custom_tools
uv run ruff check . && \
git add src/crewai_custom_tools/tools/genealogy/models/domain.py tests/test_genealogy_merge_models.py && \
git commit -F - <<'EOF'
feat(domain): PlaceFacts et champs de rapport sur PlaceMergeProposition

PlaceFacts est volontairement plat : la détection de doublons ne raisonne
que sur ce qui distingue deux lieux homonymes — type, code officiel,
coordonnées, poids dans l'arbre.

`verdict` et `perte_evitee` sont optionnels : les YAML de fusions écrits
avant la détection restent chargeables.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>
EOF
```

---

### Task 2 : la normalisation canonique des noms (bibliothèque)

**Files:**
- Create: `/Users/fjacquet/Projects/fusions-lieux/crewai_custom_tools/src/crewai_custom_tools/tools/genealogy/analysis/place_duplicates.py`
- Test: `/Users/fjacquet/Projects/fusions-lieux/crewai_custom_tools/tests/test_genealogy_place_duplicates.py`

**Interfaces:**
- Consumes: rien.
- Produces: `normaliser_nom_lieu(nom: str) -> str`. Consommée par les Tasks 5 et 8.

- [ ] **Step 1 : écrire les tests qui échouent**

Créer `tests/test_genealogy_place_duplicates.py` :

```python
"""Tests de la détection pure des doublons de lieux."""

from crewai_custom_tools.tools.genealogy.analysis.place_duplicates import (
    normaliser_nom_lieu,
)


def test_casse_accents_et_separateurs_convergent():
    assert normaliser_nom_lieu("Saint-Palais") == normaliser_nom_lieu("SAINT PALAIS")
    assert normaliser_nom_lieu("Nohant-en-Goût") == normaliser_nom_lieu("nohant en gout")


def test_apostrophe_typographique_equivaut_a_l_ascii():
    """L'apostrophe courbe est l'usage typographique standard ; elle arrive par copier-coller."""
    assert normaliser_nom_lieu("L'Isle-Adam") == normaliser_nom_lieu("L’Isle-Adam")


def test_ligature_oe_equivaut_a_oe():
    """NFD décompose les accents, pas les ligatures : Vœuil-et-Giget est une commune réelle."""
    assert normaliser_nom_lieu("Vœuil-et-Giget") == normaliser_nom_lieu("Voeuil-et-Giget")
    assert normaliser_nom_lieu("Œuilly") == normaliser_nom_lieu("Oeuilly")
    assert normaliser_nom_lieu("Ænes") == normaliser_nom_lieu("Aenes")


def test_les_lettres_barrees_ne_sont_pas_des_ligatures():
    """Frontière délibérée : `ø` n'est pas une ligature mais une lettre à part entière,
    qu'Unicode ne décompose pas. La table couvre les ligatures et rien d'autre — la
    translittérer sans translittérer aussi `ł` ou `đ` serait arbitraire."""
    assert normaliser_nom_lieu("Tønder") != normaliser_nom_lieu("Tonder")


def test_l_apostrophe_reste_un_separateur_et_ne_disparait_pas():
    """Si l'apostrophe était supprimée au lieu d'être séparée, deux communes
    distinctes se confondraient."""
    assert normaliser_nom_lieu("L'Isle-Adam") != normaliser_nom_lieu("Lisle-Adam")


def test_chaine_vide_et_blancs():
    assert normaliser_nom_lieu("") == ""
    assert normaliser_nom_lieu("   ") == ""
```

- [ ] **Step 2 : lancer les tests pour les voir échouer**

```bash
cd /Users/fjacquet/Projects/fusions-lieux/crewai_custom_tools
uv run python -m pytest tests/test_genealogy_place_duplicates.py -q
```

Attendu : ÉCHEC — `ModuleNotFoundError: No module named '...analysis.place_duplicates'`.

- [ ] **Step 3 : créer le module**

Créer `src/crewai_custom_tools/tools/genealogy/analysis/place_duplicates.py` :

```python
"""Détection des doublons de lieux : candidats, preuve, survivant. Pur, sans réseau.

Pendant de `duplicates.py`, qui fait le même travail pour les personnes, avec une
différence décisive : une commune possède un **identifiant canonique** — son code
officiel — que les personnes n'ont pas. La preuve y est donc plus forte et plus
simple à énoncer. La doctrine, elle, ne change pas : la ressemblance ne prouve
jamais l'identité (ADR 0013).
"""

from __future__ import annotations

import re
import unicodedata

__all__ = ["normaliser_nom_lieu"]

# Les ligatures ne sont pas des accents : NFD ne les décompose pas. « Vœuil-et-Giget »
# et « Voeuil-et-Giget » désignent pourtant la même commune de Charente.
_LIGATURES = str.maketrans({"œ": "oe", "Œ": "OE", "æ": "ae", "Æ": "AE"})

# L'apostrophe typographique ’ (U+2019) est l'usage standard et arrive par
# copier-coller ; elle rejoint la classe des séparateurs plutôt que d'être
# supprimée — sinon « L'Isle-Adam » se confondrait avec « Lisle-Adam ».
_SEPARATEURS = re.compile(r"[\s\-'’]+")


def normaliser_nom_lieu(nom: str) -> str:
    """Nom de lieu → clé de comparaison : sans accents, minuscule, séparateurs unifiés."""
    deplie = (nom or "").translate(_LIGATURES)
    sans_accents = "".join(
        c for c in unicodedata.normalize("NFD", deplie)
        if unicodedata.category(c) != "Mn")
    return _SEPARATEURS.sub(" ", sans_accents).strip().lower()
```

- [ ] **Step 4 : lancer les tests pour les voir passer**

```bash
cd /Users/fjacquet/Projects/fusions-lieux/crewai_custom_tools
uv run python -m pytest tests/test_genealogy_place_duplicates.py -q
```

Attendu : PASS, 6 tests.

- [ ] **Step 5 : commiter**

```bash
cd /Users/fjacquet/Projects/fusions-lieux/crewai_custom_tools
uv run ruff check . && \
git add src/crewai_custom_tools/tools/genealogy/analysis/place_duplicates.py tests/test_genealogy_place_duplicates.py && \
git commit -F - <<'EOF'
feat(analysis): normalisation canonique des noms de lieux

Sa place est la bibliothèque : c'est une fonction pure de logique
généalogique. Elle neutralise casse, accents, séparateurs, ligatures
(œ, æ) et apostrophe typographique — mais garde l'apostrophe comme
SÉPARATEUR et non comme caractère supprimé, sans quoi L'Isle-Adam se
confondrait avec Lisle-Adam.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>
EOF
```

---

### Task 3 : la preuve (bibliothèque)

**Files:**
- Modify: `.../analysis/place_duplicates.py`
- Test: `.../tests/test_genealogy_place_duplicates.py`

**Interfaces:**
- Consumes: `PlaceFacts` (Task 1).
- Produces: `evaluer_preuve(a: PlaceFacts, b: PlaceFacts) -> str` rendant `"code"`, `"coordonnees"` ou `""` (pas de preuve). Consommée par la Task 5.

- [ ] **Step 1 : écrire les tests qui échouent**

Ajouter à `tests/test_genealogy_place_duplicates.py` :

```python
from crewai_custom_tools.tools.genealogy.analysis.place_duplicates import evaluer_preuve
from crewai_custom_tools.tools.genealogy.models.domain import PlaceFacts


def _lieu(gid, **kw):
    base = {"gramps_id": gid, "handle": "H" + gid, "nom": "X"}
    base.update(kw)
    return PlaceFacts(**base)


def test_codes_identiques_prouvent_quel_que_soit_le_type():
    """Un code officiel est un identifiant canonique, pas une ressemblance."""
    a = _lieu("P1", code="18044", place_type="Municipality")
    b = _lieu("P2", code="18044", place_type="City")
    assert evaluer_preuve(a, b) == "code"


def test_codes_differents_opposent_un_veto():
    """Paris : Department 75 contre Municipality 75056 — deux entités réelles."""
    a = _lieu("P0301", code="75", place_type="Department", lat="48.8589", long="2.347")
    b = _lieu("P0008", code="75056", place_type="Municipality", lat="48.8589", long="2.347")
    assert evaluer_preuve(a, b) == ""


def test_coordonnees_identiques_prouvent_a_type_egal():
    """Rhodt unter Rietburg : deux Municipality sans code, mêmes coordonnées."""
    a = _lieu("P0119", place_type="Municipality", lat="49.2708776", long="8.1234")
    b = _lieu("P0103", place_type="Municipality", lat="49.2708776", long="8.1234")
    assert evaluer_preuve(a, b) == "coordonnees"


def test_coordonnees_ne_prouvent_rien_entre_types_differents():
    """Le chantier référentiel va géocoder les départements : ce refus doit tenir."""
    a = _lieu("P0301", place_type="Department", lat="48.8589", long="2.347")
    b = _lieu("P0008", place_type="Municipality", lat="48.8589", long="2.347")
    assert evaluer_preuve(a, b) == ""


def test_un_seul_code_renseigne_ne_prouve_pas():
    """Annaba : Department sans code contre Wilaya code 23 — arbitrage humain."""
    a = _lieu("P0343", place_type="Department")
    b = _lieu("P0383", place_type="Wilaya", code="23")
    assert evaluer_preuve(a, b) == ""


def test_sans_code_ni_coordonnees_aucune_preuve():
    a = _lieu("P1", place_type="Municipality")
    b = _lieu("P2", place_type="Municipality")
    assert evaluer_preuve(a, b) == ""


def test_coordonnees_partielles_ne_prouvent_pas():
    """Une latitude égale et une longitude vide n'est pas une coïncidence de position."""
    a = _lieu("P1", place_type="Municipality", lat="47.1147")
    b = _lieu("P2", place_type="Municipality", lat="47.1147", long="2.0")
    assert evaluer_preuve(a, b) == ""
```

- [ ] **Step 2 : lancer les tests pour les voir échouer**

```bash
cd /Users/fjacquet/Projects/fusions-lieux/crewai_custom_tools
uv run python -m pytest tests/test_genealogy_place_duplicates.py -q
```

Attendu : ÉCHEC — `ImportError: cannot import name 'evaluer_preuve'`.

- [ ] **Step 3 : implémenter**

Dans `place_duplicates.py`, remplacer la ligne `__all__` par :

```python
__all__ = ["evaluer_preuve", "normaliser_nom_lieu"]
```

Ajouter l'import du modèle en tête, sous `import unicodedata` :

```python
from crewai_custom_tools.tools.genealogy.models.domain import PlaceFacts
```

Puis, à la fin du module :

```python
PREUVE_CODE = "code"
PREUVE_COORDONNEES = "coordonnees"


def evaluer_preuve(a: PlaceFacts, b: PlaceFacts) -> str:
    """La preuve qui autorise une fusion automatique, ou la chaîne vide. Pur.

    Un VETO passe avant tout : deux codes non vides et différents interdisent la
    fusion, quels que soient les types et les coordonnées. C'est lui qui protège
    Paris — le département 75 et la commune 75056 sont deux entités réelles.

    Hors veto, deux voies :
      - codes identiques et non vides : un code officiel est canonique, il prouve
        quel que soit le type des deux lieux ;
      - même type ET coordonnées complètes identiques : la voie des lieux sans
        code. Les coordonnées ne prouvent JAMAIS rien entre types différents —
        un département géocodé reçoit le point de sa préfecture, c'est-à-dire
        celui de sa commune-chef-lieu.
    """
    if a.code and b.code and a.code != b.code:
        return ""
    if a.code and b.code:                       # égaux, et non vides : canonique
        return PREUVE_CODE
    if a.place_type != b.place_type:
        return ""
    if a.lat and a.long and (a.lat, a.long) == (b.lat, b.long):
        return PREUVE_COORDONNEES
    return ""
```

- [ ] **Step 4 : lancer les tests pour les voir passer**

```bash
cd /Users/fjacquet/Projects/fusions-lieux/crewai_custom_tools
uv run python -m pytest tests/test_genealogy_place_duplicates.py -q
```

Attendu : PASS, 13 tests.

- [ ] **Step 5 : commiter**

```bash
cd /Users/fjacquet/Projects/fusions-lieux/crewai_custom_tools
uv run ruff check . && \
git add src/crewai_custom_tools/tools/genealogy/analysis/place_duplicates.py tests/test_genealogy_place_duplicates.py && \
git commit -F - <<'EOF'
feat(analysis): la preuve qui autorise une fusion de lieux

Veto d'abord : deux codes non vides et différents interdisent la fusion.
C'est lui qui protège Paris, où le département 75 et la commune 75056
sont deux entités réelles.

Hors veto, deux voies : codes identiques (canonique, vaut entre types
différents), ou même type et coordonnées identiques (les lieux sans
code). Les coordonnées ne prouvent jamais rien entre types différents —
un département géocodé reçoit le point de son chef-lieu.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>
EOF
```

---

### Task 4 : le choix du survivant (bibliothèque)

**Files:**
- Modify: `.../analysis/place_duplicates.py`
- Test: `.../tests/test_genealogy_place_duplicates.py`

**Interfaces:**
- Consumes: `PlaceFacts` (Task 1).
- Produces:
  - `richesse(p: PlaceFacts) -> int` — nombre d'attributs renseignés parmi coordonnées, code, parent (0 à 3) ;
  - `choisir_survivant(lieux: list[PlaceFacts]) -> PlaceFacts` ;
  - `perte_evitee(survivant: PlaceFacts, absorbe: PlaceFacts) -> str`.
  Consommées par la Task 5.

- [ ] **Step 1 : écrire les tests qui échouent**

Ajouter à `tests/test_genealogy_place_duplicates.py` :

```python
from crewai_custom_tools.tools.genealogy.analysis.place_duplicates import (
    choisir_survivant, perte_evitee, richesse,
)


def test_richesse_compte_les_attributs_renseignes():
    assert richesse(_lieu("P1")) == 0
    assert richesse(_lieu("P1", lat="47.1", long="2.3")) == 1
    assert richesse(_lieu("P1", lat="47.1", long="2.3", code="18044", a_parent=True)) == 3


def test_le_plus_riche_gagne_meme_avec_moins_de_retroliens():
    """C'est le cœur de la règle : garder la coquille vide effacerait ses coordonnées."""
    pauvre = _lieu("P0387", retroliens=50)
    riche = _lieu("P0148", lat="48.8467", long="5.6", code="55012", retroliens=1)
    assert choisir_survivant([pauvre, riche]).gramps_id == "P0148"


def test_a_richesse_egale_les_retroliens_departagent():
    a = _lieu("P0064", lat="47.1", long="2.3", code="18044", retroliens=53)
    b = _lieu("P0070", lat="47.1", long="2.3", code="18044", retroliens=4)
    assert choisir_survivant([a, b]).gramps_id == "P0064"


def test_a_egalite_complete_le_plus_petit_identifiant_tranche():
    """Quantilly : cinq événements de chaque côté, mêmes données. La règle reste totale."""
    a = _lieu("P0184", lat="47.2", long="2.5", code="18189", retroliens=5)
    b = _lieu("P0059", lat="47.2", long="2.5", code="18189", retroliens=5)
    assert choisir_survivant([a, b]).gramps_id == "P0059"


def test_survivant_sur_une_grappe_de_trois():
    a = _lieu("P0178", lat="45.6", long="6.4", code="73312", retroliens=4)
    b = _lieu("P0192", lat="45.6", long="6.4", code="73312", retroliens=19)
    c = _lieu("P0198", lat="45.6", long="6.4", code="73312", retroliens=5)
    assert choisir_survivant([a, b, c]).gramps_id == "P0192"


def test_perte_evitee_nomme_ce_qui_aurait_disparu():
    riche = _lieu("P0148", lat="48.8467", long="5.6", code="55012")
    pauvre = _lieu("P0387")
    assert perte_evitee(riche, pauvre) == ""          # rien à perdre dans ce sens
    texte = perte_evitee(pauvre, riche)
    assert "coordonnées" in texte and "code" in texte


def test_perte_evitee_vide_quand_les_deux_sont_egaux():
    a = _lieu("P1", lat="47.1", long="2.3", code="18044")
    b = _lieu("P2", lat="47.1", long="2.3", code="18044")
    assert perte_evitee(a, b) == ""
```

- [ ] **Step 2 : lancer les tests pour les voir échouer**

```bash
cd /Users/fjacquet/Projects/fusions-lieux/crewai_custom_tools
uv run python -m pytest tests/test_genealogy_place_duplicates.py -q
```

Attendu : ÉCHEC — `ImportError: cannot import name 'choisir_survivant'`.

- [ ] **Step 3 : implémenter**

Dans `place_duplicates.py`, porter `__all__` à :

```python
__all__ = [
    "choisir_survivant", "evaluer_preuve", "normaliser_nom_lieu",
    "perte_evitee", "richesse",
]
```

Puis ajouter à la fin du module :

```python
def richesse(p: PlaceFacts) -> int:
    """Nombre d'attributs renseignés parmi coordonnées, code, parent (0 à 3). Pur."""
    return sum((bool(p.lat and p.long), bool(p.code), bool(p.a_parent)))


def choisir_survivant(lieux: list[PlaceFacts]) -> PlaceFacts:
    """Le lieu qui survit à la fusion du groupe. Pur.

    Richesse d'abord, rétroliens ensuite, identifiant le plus petit en dernier
    recours — la règle doit être TOTALE pour que deux exécutions donnent le même
    résultat sur des données identiques.

    L'ordre n'est pas un confort : la fusion Gramps unionne les listes mais les
    champs simples restent ceux du survivant. Garder une coquille vide contre un
    lieu renseigné effacerait définitivement ses coordonnées et son code.
    """
    return min(lieux, key=lambda p: (-richesse(p), -p.retroliens, p.gramps_id))


def perte_evitee(survivant: PlaceFacts, absorbe: PlaceFacts) -> str:
    """Ce que l'ordre inverse aurait effacé, en clair ; vide s'il n'y a rien. Pur.

    Sert le rapport : une règle de sélection qu'on ne peut pas vérifier après coup
    est une règle qu'on croit sur parole.
    """
    manquants = []
    if (absorbe.lat and absorbe.long) and not (survivant.lat and survivant.long):
        manquants.append("coordonnées")
    if absorbe.code and not survivant.code:
        manquants.append("code")
    if absorbe.a_parent and not survivant.a_parent:
        manquants.append("rattachement")
    return ", ".join(manquants)
```

- [ ] **Step 4 : lancer les tests pour les voir passer**

```bash
cd /Users/fjacquet/Projects/fusions-lieux/crewai_custom_tools
uv run python -m pytest tests/test_genealogy_place_duplicates.py -q
```

Attendu : PASS, 20 tests.

- [ ] **Step 5 : commiter**

```bash
cd /Users/fjacquet/Projects/fusions-lieux/crewai_custom_tools
uv run ruff check . && \
git add src/crewai_custom_tools/tools/genealogy/analysis/place_duplicates.py tests/test_genealogy_place_duplicates.py && \
git commit -F - <<'EOF'
feat(analysis): choix du survivant d'une fusion de lieux

Richesse d'abord, rétroliens ensuite, identifiant en dernier recours —
règle totale, donc reproductible. L'ordre n'est pas un confort : Gramps
unionne les listes mais garde les champs simples du survivant, donc
conserver une coquille vide effacerait coordonnées et code.

`perte_evitee` nomme ce que l'ordre inverse aurait détruit, pour que le
rapport laisse vérifier la règle au lieu de la faire croire.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>
EOF
```

---

### Task 5 : l'étagement des groupes (bibliothèque)

**Files:**
- Modify: `.../analysis/place_duplicates.py`
- Test: `.../tests/test_genealogy_place_duplicates.py`

**Interfaces:**
- Consumes: `normaliser_nom_lieu`, `evaluer_preuve`, `choisir_survivant`, `perte_evitee` (Tasks 2-4) ; `PlaceFacts`, `PlaceMergeProposition` (Task 1).
- Produces: `etager_lieux(lieux: list[PlaceFacts]) -> list[PlaceMergeProposition]`, chaque proposition portant `verdict` à `"auto"` ou `"arbitrage"`. Consommée par la Task 8.

- [ ] **Step 1 : écrire les tests qui échouent**

Ajouter à `tests/test_genealogy_place_duplicates.py` :

```python
from crewai_custom_tools.tools.genealogy.analysis.place_duplicates import etager_lieux


def _commune(gid, nom, **kw):
    base = {"gramps_id": gid, "handle": "H" + gid, "nom": nom,
            "place_type": "Municipality"}
    base.update(kw)
    return PlaceFacts(**base)


def test_un_lieu_unique_ne_produit_rien():
    assert etager_lieux([_commune("P1", "Vierzon", code="18279")]) == []


def test_deux_communes_meme_code_donnent_une_proposition_auto():
    props = etager_lieux([
        _commune("P0064", "Cerbois", code="18044", lat="47.1", long="2.3", retroliens=53),
        _commune("P0070", "Cerbois", code="18044", lat="47.1", long="2.3", retroliens=4),
    ])
    assert len(props) == 1
    p = props[0]
    assert p.verdict == "auto"
    assert (p.gramps_id_keep, p.gramps_id_merge) == ("P0064", "P0070")
    assert p.canonical == "Cerbois"
    assert "code" in p.reason


def test_noms_differents_ne_sont_pas_candidats():
    props = etager_lieux([
        _commune("P1", "Bourges", code="18033"),
        _commune("P2", "Vierzon", code="18279"),
    ])
    assert props == []


def test_types_differents_sans_code_partagent_le_nom_mais_partent_en_arbitrage():
    """Annaba : Department sans code contre Wilaya code 23."""
    props = etager_lieux([
        PlaceFacts(gramps_id="P0343", handle="HA", nom="Annaba", place_type="Department"),
        PlaceFacts(gramps_id="P0383", handle="HB", nom="Annaba", place_type="Wilaya",
                   code="23"),
    ])
    assert len(props) == 1
    assert props[0].verdict == "arbitrage"


def test_paris_part_en_arbitrage_et_jamais_en_auto():
    """Le cas qui doit rester rouge si le veto disparaît."""
    props = etager_lieux([
        PlaceFacts(gramps_id="P0301", handle="HA", nom="Paris", place_type="Department",
                   code="75", lat="48.8589", long="2.347"),
        PlaceFacts(gramps_id="P0008", handle="HB", nom="Paris", place_type="Municipality",
                   code="75056", lat="48.8589", long="2.347"),
    ])
    assert len(props) == 1
    assert props[0].verdict == "arbitrage"


def test_grappe_de_trois_produit_deux_propositions_sur_le_meme_survivant():
    """Verrens-Arvey : l'égalité de nom est transitive, une seule passe suffit."""
    props = etager_lieux([
        _commune("P0178", "Verrens-Arvey", code="73312", lat="45.6", long="6.4", retroliens=4),
        _commune("P0192", "Verrens-Arvey", code="73312", lat="45.6", long="6.4", retroliens=19),
        _commune("P0198", "Verrens-Arvey", code="73312", lat="45.6", long="6.4", retroliens=5),
    ])
    assert len(props) == 2
    assert {p.gramps_id_keep for p in props} == {"P0192"}
    assert {p.gramps_id_merge for p in props} == {"P0178", "P0198"}
    assert all(p.verdict == "auto" for p in props)


def test_la_perte_evitee_est_rapportee():
    props = etager_lieux([
        _commune("P0387", "Apremont-la-Forêt", retroliens=50),
        _commune("P0148", "Apremont-la-Forêt", code="55012", lat="48.8", long="5.6",
                 retroliens=1),
    ])
    assert props[0].gramps_id_keep == "P0148"
    assert "coordonnées" in props[0].perte_evitee


def test_lieu_sans_nom_est_ignore():
    props = etager_lieux([
        _commune("P1", "", code="18044"),
        _commune("P2", "", code="18044"),
    ])
    assert props == []
```

- [ ] **Step 2 : lancer les tests pour les voir échouer**

```bash
cd /Users/fjacquet/Projects/fusions-lieux/crewai_custom_tools
uv run python -m pytest tests/test_genealogy_place_duplicates.py -q
```

Attendu : ÉCHEC — `ImportError: cannot import name 'etager_lieux'`.

- [ ] **Step 3 : implémenter**

Dans `place_duplicates.py`, porter `__all__` à :

```python
__all__ = [
    "choisir_survivant", "etager_lieux", "evaluer_preuve",
    "normaliser_nom_lieu", "perte_evitee", "richesse",
]
```

Compléter l'import du modèle :

```python
from crewai_custom_tools.tools.genealogy.models.domain import (
    PlaceFacts, PlaceMergeProposition,
)
```

Ajouter `from collections import defaultdict` en tête, puis à la fin du module :

```python
_MOTIFS = {
    PREUVE_CODE: "code officiel identique",
    PREUVE_COORDONNEES: "coordonnées identiques, même type, aucun code",
}


def etager_lieux(lieux: list[PlaceFacts]) -> list[PlaceMergeProposition]:
    """Groupe les homonymes, choisit un survivant par groupe, évalue chaque autre. Pur.

    Le groupement se fait sur l'ÉGALITÉ de nom normalisé, qui est une relation
    d'équivalence : les groupes sont donc complets dès la première lecture, et
    fusionner deux lieux n'en renomme aucun autre. C'est ce qui rend inutile la
    boucle de convergence que la déduplication des personnes exige — voir l'écart
    documenté en tête du plan.
    """
    groupes: dict[str, list[PlaceFacts]] = defaultdict(list)
    for lieu in lieux:
        cle = normaliser_nom_lieu(lieu.nom)
        if cle:                                  # un lieu sans nom exploitable n'est pas candidat
            groupes[cle].append(lieu)

    propositions: list[PlaceMergeProposition] = []
    for _, membres in sorted(groupes.items()):
        if len(membres) < 2:
            continue
        survivant = choisir_survivant(membres)
        for absorbe in sorted(membres, key=lambda p: p.gramps_id):
            if absorbe.handle == survivant.handle:
                continue
            preuve = evaluer_preuve(survivant, absorbe)
            propositions.append(PlaceMergeProposition(
                gramps_id_keep=survivant.gramps_id, handle_keep=survivant.handle,
                gramps_id_merge=absorbe.gramps_id, handle_merge=absorbe.handle,
                canonical=survivant.nom,
                reason=(f"homonymes — {_MOTIFS[preuve]}" if preuve
                        else "homonymes — aucune preuve : relecture humaine"),
                verdict="auto" if preuve else "arbitrage",
                perte_evitee=perte_evitee(survivant, absorbe)))
    return propositions
```

- [ ] **Step 4 : lancer les tests pour les voir passer**

```bash
cd /Users/fjacquet/Projects/fusions-lieux/crewai_custom_tools
uv run python -m pytest tests/test_genealogy_place_duplicates.py -q && uv run python -m pytest tests/ -q
```

Attendu : le fichier au vert (28 tests), puis la suite complète au vert.

- [ ] **Step 5 : commiter**

```bash
cd /Users/fjacquet/Projects/fusions-lieux/crewai_custom_tools
uv run ruff check . && \
git add src/crewai_custom_tools/tools/genealogy/analysis/place_duplicates.py tests/test_genealogy_place_duplicates.py && \
git commit -F - <<'EOF'
feat(analysis): étagement des groupes de lieux homonymes

Le groupement se fait sur l'ÉGALITÉ de nom normalisé, qui est une
relation d'équivalence : les groupes sont complets dès la première
lecture et fusionner deux lieux n'en renomme aucun autre. D'où une seule
passe, là où les personnes exigent une boucle de convergence.

Cas réels verrouillés en test : Paris en arbitrage (le veto), Annaba en
arbitrage, Cerbois en auto, Verrens-Arvey en grappe de trois sur un
survivant unique, Apremont dont la perte évitée est rapportée.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>
EOF
```

---

### PORTE HUMAINE 1 : publication de la bibliothèque

**Aucun agent n'exécute cette étape.**

À faire par un humain, depuis `/Users/fjacquet/Projects/fusions-lieux/crewai_custom_tools` :

1. relire le diff des Tasks 1 à 5 ;
2. fusionner `feat/fusion-doublons-lieux` dans `main` ;
3. bumper la version **aux deux endroits** — `pyproject.toml` **et** `src/crewai_custom_tools/__init__.py` (`__version__`). Le test `tests/test_scaffold.py::test_version_matches_pyproject` compare les deux sources ;
4. **relancer la suite APRÈS le bump** ;
5. commiter, **taguer en tag ANNOTÉ** (`git tag -a vX.Y.Z -m "..."` — le dépôt refuse les tags légers), pousser la branche **et** le tag ;
6. depuis l'arbre genecrew, `uv sync` puis commiter `uv.lock`.

Sans tag poussé, la CI de genecrew ne peut pas verdir : elle checkoute le voisin sur le tag lu dans `uv.lock`.

**Cette porte ne bloque pas les Tasks 6 à 10** : la dépendance est éditable et résout vers l'arbre voisin, donc les commits locaux des Tasks 1-5 suffisent au développement. Elle bloque la CI et la fusion.

---

### Task 6 : la collecte des faits de lieux (genecrew)

**Files:**
- Modify: `/Users/fjacquet/Projects/fusions-lieux/genecrew/genecrew/src/genecrew/places_merge.py`
- Test: `/Users/fjacquet/Projects/fusions-lieux/genecrew/genecrew/tests/test_places_detect.py`

**Interfaces:**
- Consumes: `PlaceFacts` (Task 1) ; `iter_places(client, scope, batch_size, limit)` de `genecrew.batching`.
- Produces: `collecter_lieux(client, scope: str, batch_size: int = 200, limit: int | None = None) -> list[PlaceFacts]`. Consommée par la Task 8.

- [ ] **Step 1 : écrire les tests qui échouent**

Créer `genecrew/tests/test_places_detect.py` :

```python
"""Tests offline du mode détection de `merge places`."""

import httpx
import pytest
from crewai_custom_tools.tools.genealogy.gramps.client import GrampsClient, GrampsConfig

from genecrew.places_merge import collecter_lieux

CONFIG = GrampsConfig(api_url="http://g.test/api", username="u", password="p")


@pytest.fixture(autouse=True)
def _real_writes(monkeypatch):
    monkeypatch.setenv("GENECREW_DRY_RUN", "false")


def _client(handler):
    def _h(request):
        if request.url.path == "/api/token/":
            return httpx.Response(200, json={"access_token": "t"})
        return handler(request)
    return GrampsClient(CONFIG, transport=httpx.MockTransport(_h))


def _arbre(places, backlinks=None):
    backlinks = backlinks or {}

    def _h(request):
        p = request.url.path
        if p == "/api/places/":
            page = int(request.url.params.get("page", 1))
            return httpx.Response(200, json=places if page == 1 else [])
        if p.startswith("/api/places/"):
            handle = p.rsplit("/", 1)[-1]
            return httpx.Response(200, json={"backlinks": backlinks.get(handle, {})})
        return httpx.Response(404, json={})
    return _client(_h)


PLACE = {"handle": "H1", "gramps_id": "P0001", "name": {"value": "Bourges"},
         "place_type": "Municipality", "code": "18033", "lat": "47.081",
         "long": "2.398", "placeref_list": [{"ref": "HP"}]}


def test_collecte_les_champs_utiles():
    lieux = collecter_lieux(_arbre([PLACE]), "all")
    assert len(lieux) == 1
    p = lieux[0]
    assert (p.gramps_id, p.handle, p.nom) == ("P0001", "H1", "Bourges")
    assert p.place_type == "Municipality"
    assert p.code == "18033"
    assert (p.lat, p.long) == ("47.081", "2.398")
    assert p.a_parent is True


def test_compte_les_retroliens():
    client = _arbre([PLACE], backlinks={"H1": {"event": ["e1", "e2", "e3"],
                                               "place": ["p1"]}})
    assert collecter_lieux(client, "all")[0].retroliens == 4


def test_absence_de_retroliens_donne_zero():
    assert collecter_lieux(_arbre([PLACE]), "all")[0].retroliens == 0


def test_lieu_sans_nom_collecte_quand_meme_avec_nom_vide():
    """Le filtrage des noms vides appartient à la détection, pas à la collecte."""
    sans_nom = {**PLACE, "name": {}}
    assert collecter_lieux(_arbre([sans_nom]), "all")[0].nom == ""


def test_champs_absents_donnent_des_defauts_vides():
    nu = {"handle": "H2", "gramps_id": "P0002", "name": {"value": "X"}}
    p = collecter_lieux(_arbre([nu]), "all")[0]
    assert (p.place_type, p.code, p.lat, p.long, p.a_parent) == ("", "", "", "", False)
```

- [ ] **Step 2 : lancer les tests pour les voir échouer**

```bash
cd /Users/fjacquet/Projects/fusions-lieux/genecrew
uv run python -m pytest genecrew/tests/test_places_detect.py -q
```

Attendu : ÉCHEC — `ImportError: cannot import name 'collecter_lieux'`.

- [ ] **Step 3 : implémenter**

Dans `genecrew/src/genecrew/places_merge.py`, ajouter aux imports en tête :

```python
from crewai_custom_tools.tools.genealogy.models.domain import PlaceFacts

from genecrew.batching import iter_places
from genecrew.logging_setup import get_logger
```

Puis, après la fonction `_link`, insérer :

```python
def _retroliens(client: GrampsClient, handle: str) -> int:
    """Nombre d'objets qui référencent ce lieu ; 0 si l'API ne répond pas.

    Un appel par lieu : coûteux, mais c'est la seule mesure qui dise lequel de deux
    homonymes l'arbre utilise réellement. Un échec ne doit pas faire échouer la
    détection — il dégrade seulement le départage vers les critères suivants.
    """
    try:
        objet = client.get_json(f"/places/{handle}", params={"backlinks": "1"}) or {}
    except Exception as exc:
        get_logger().warning("rétroliens de %s indisponibles : %s", handle, exc)
        return 0
    return sum(len(refs) for refs in (objet.get("backlinks") or {}).values())


def collecter_lieux(client: GrampsClient, scope: str, batch_size: int = 200,
                    limit: int | None = None) -> list[PlaceFacts]:
    """Lit les lieux du périmètre et les réduit aux faits utiles à la détection."""
    lieux: list[PlaceFacts] = []
    for lot in iter_places(client, scope, batch_size, limit):
        for place in lot:
            if not isinstance(place, dict):
                continue
            handle = place.get("handle", "")
            lieux.append(PlaceFacts(
                gramps_id=place.get("gramps_id", ""),
                handle=handle,
                nom=(place.get("name") or {}).get("value", "") or "",
                place_type=place.get("place_type") or "",
                code=place.get("code") or "",
                lat=place.get("lat") or "",
                long=place.get("long") or "",
                a_parent=bool(place.get("placeref_list")),
                retroliens=_retroliens(client, handle)))
    return lieux
```

- [ ] **Step 4 : lancer les tests pour les voir passer**

```bash
cd /Users/fjacquet/Projects/fusions-lieux/genecrew
uv run python -m pytest genecrew/tests/test_places_detect.py -q
```

Attendu : PASS, 5 tests.

- [ ] **Step 5 : commiter**

```bash
cd /Users/fjacquet/Projects/fusions-lieux/genecrew
uv run ruff check . && \
git add genecrew/src/genecrew/places_merge.py genecrew/tests/test_places_detect.py && \
git commit -F - <<'EOF'
feat(lieux): collecte des faits de lieux pour la détection

Réduit chaque lieu Gramps aux seuls attributs qui distinguent deux
homonymes. Le comptage des rétroliens coûte un appel par lieu, mais
c'est la seule mesure qui dise lequel des deux l'arbre utilise vraiment ;
son échec est absorbé et dégrade seulement le départage.

Le filtrage des noms vides reste à la détection : la collecte rapporte
ce qu'elle voit.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>
EOF
```

---

### Task 7 : le rapport de détection (genecrew)

**Files:**
- Modify: `genecrew/src/genecrew/places_merge.py`
- Test: `genecrew/tests/test_places_detect.py`

**Interfaces:**
- Consumes: `PlaceMergeProposition` (Task 1).
- Produces: `render_detect_report(date: str, fusions: list, arbitrage: list, errors: list, total_lieux: int, dry_run: bool, base_url: str = "http://localhost") -> str`, où `fusions` est une liste de `PlaceMergeProposition` effectivement appliquées, `arbitrage` une liste de `PlaceMergeProposition`, et `errors` une liste de tuples `(gramps_id_merge, message)`. Consommée par la Task 8.

- [ ] **Step 1 : écrire les tests qui échouent**

Ajouter à `genecrew/tests/test_places_detect.py` :

```python
from crewai_custom_tools.tools.genealogy.models.domain import PlaceMergeProposition

from genecrew.places_merge import render_detect_report


def _prop(keep="P0064", merge="P0070", verdict="auto", perte="", canonical="Cerbois"):
    return PlaceMergeProposition(
        gramps_id_keep=keep, handle_keep="H" + keep,
        gramps_id_merge=merge, handle_merge="H" + merge,
        canonical=canonical, reason="homonymes — code officiel identique",
        verdict=verdict, perte_evitee=perte)


def test_mode_simulation_annonce_et_conjugue_au_conditionnel():
    md = render_detect_report("2026-07-21", [_prop()], [], [], 303, dry_run=True)
    assert "simulation" in md
    assert "Fusions à appliquer : 1" in md
    assert "Fusions appliquées" not in md


def test_mode_reel_annonce_les_ecritures():
    md = render_detect_report("2026-07-21", [_prop()], [], [], 303, dry_run=False)
    assert "écritures appliquées" in md
    assert "Fusions appliquées : 1" in md


def test_le_tableau_nomme_survivant_et_absorbe():
    md = render_detect_report("2026-07-21", [_prop()], [], [], 303, dry_run=False)
    assert "P0064" in md and "P0070" in md and "Cerbois" in md


def test_la_perte_evitee_apparait_quand_il_y_en_a_une():
    md = render_detect_report(
        "2026-07-21", [_prop(perte="coordonnées, code")], [], [], 303, dry_run=False)
    assert "coordonnées, code" in md


def test_l_arbitrage_est_une_section_distincte():
    md = render_detect_report("2026-07-21", [], [_prop(verdict="arbitrage",
                                                       canonical="Paris")], [], 303,
                              dry_run=False)
    assert "Arbitrage" in md
    assert "À relire : 1" in md
    assert "Paris" in md


def test_rien_a_faire_reste_lisible():
    md = render_detect_report("2026-07-21", [], [], [], 303, dry_run=False)
    assert "Fusions appliquées : 0" in md
    assert "À relire : 0" in md
    assert "Aucun doublon" in md


def test_les_erreurs_sont_rapportees():
    md = render_detect_report("2026-07-21", [], [], [("P0070", "HTTP 500")], 303,
                              dry_run=False)
    assert "P0070" in md and "HTTP 500" in md
```

- [ ] **Step 2 : lancer les tests pour les voir échouer**

```bash
cd /Users/fjacquet/Projects/fusions-lieux/genecrew
uv run python -m pytest genecrew/tests/test_places_detect.py -q
```

Attendu : ÉCHEC — `ImportError: cannot import name 'render_detect_report'`.

- [ ] **Step 3 : implémenter**

Ajouter à `genecrew/src/genecrew/places_merge.py`, après `render_merge_report` :

```python
def render_detect_report(date: str, fusions: list, arbitrage: list, errors: list,
                         total_lieux: int, dry_run: bool,
                         base_url: str = "http://localhost") -> str:
    """Rapport Markdown du mode détection. Pur.

    Les libellés se conjuguent avec le mode : en simulation rien n'est écrit, et un
    rapport ne doit jamais annoncer au présent une fusion qui n'a pas eu lieu.
    """
    mode = "simulation (dry-run, aucune fusion)" if dry_run else "écritures appliquées"
    titre_fusions = "Fusions à appliquer" if dry_run else "Fusions appliquées"
    lines = [f"# Doublons de lieux — {date}", "",
             f"Mode : {mode}.", "",
             f"- Lieux examinés : {total_lieux}",
             f"- {titre_fusions} : {len(fusions)}",
             f"- À relire : {len(arbitrage)}",
             f"- Erreurs : {len(errors)}", ""]
    if fusions:
        lines += [f"## {titre_fusions}", "",
                  "| Gardé | Absorbé | Nom | Preuve | Perte évitée |",
                  "|---|---|---|---|---|"]
        lines += [f"| {_link(p.gramps_id_keep, base_url)} "
                  f"| {_link(p.gramps_id_merge, base_url)} | {p.canonical} "
                  f"| {p.reason} | {p.perte_evitee or '—'} |" for p in fusions]
        lines.append("")
    if arbitrage:
        lines += ["## Arbitrage", "",
                  "Aucune preuve ne les départage : à relire, puis à exécuter avec "
                  "`merge places --yaml`.", "",
                  "| Gardé | Absorbé | Nom | Motif |", "|---|---|---|---|"]
        lines += [f"| {_link(p.gramps_id_keep, base_url)} "
                  f"| {_link(p.gramps_id_merge, base_url)} | {p.canonical} "
                  f"| {p.reason} |" for p in arbitrage]
        lines.append("")
    if errors:
        lines += ["## Erreurs", ""]
        lines += [f"- {gid} : {msg}" for gid, msg in errors]
        lines.append("")
    if not fusions and not arbitrage and not errors:
        lines += ["Aucun doublon détecté.", ""]
    return "\n".join(lines)
```

- [ ] **Step 4 : lancer les tests pour les voir passer**

```bash
cd /Users/fjacquet/Projects/fusions-lieux/genecrew
uv run python -m pytest genecrew/tests/test_places_detect.py -q
```

Attendu : PASS, 12 tests.

- [ ] **Step 5 : commiter**

```bash
cd /Users/fjacquet/Projects/fusions-lieux/genecrew
uv run ruff check . && \
git add genecrew/src/genecrew/places_merge.py genecrew/tests/test_places_detect.py && \
git commit -F - <<'EOF'
feat(lieux): rapport du mode détection

Compteurs, fusions avec leur preuve et la perte évitée, arbitrage en
section distincte renvoyant vers `merge places --yaml`. Les libellés se
conjuguent avec le mode : en simulation le rapport dit « à appliquer »,
jamais « appliquées ».

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>
EOF
```

---

### Task 8 : l'orchestration de la détection (genecrew)

**Files:**
- Modify: `genecrew/src/genecrew/places_merge.py`
- Test: `genecrew/tests/test_places_detect.py`

**Interfaces:**
- Consumes: `collecter_lieux` (Task 6), `render_detect_report` (Task 7), `etager_lieux` (Task 5), `GrampsMergePlacesTool` et `effective_dry_run` (déjà importés dans le module).
- Produces: `run_places_detect(client, output_dir, *, scope: str, date: str, limit: int | None = None, dry_run: bool = False) -> Path`. Consommée par la Task 9.

- [ ] **Step 1 : écrire les tests qui échouent**

Ajouter à `genecrew/tests/test_places_detect.py` :

```python
import json

import yaml

from genecrew import places_merge
from genecrew.places_merge import run_places_detect

DOUBLONS = [
    {"handle": "HA", "gramps_id": "P0064", "name": {"value": "Cerbois"},
     "place_type": "Municipality", "code": "18044", "lat": "47.1", "long": "2.3"},
    {"handle": "HB", "gramps_id": "P0070", "name": {"value": "Cerbois"},
     "place_type": "Municipality", "code": "18044", "lat": "47.1", "long": "2.3"},
]
PARIS = [
    {"handle": "HC", "gramps_id": "P0301", "name": {"value": "Paris"},
     "place_type": "Department", "code": "75"},
    {"handle": "HD", "gramps_id": "P0008", "name": {"value": "Paris"},
     "place_type": "Municipality", "code": "75056"},
]


def _stub_fusion(monkeypatch, succes=True):
    vus = []

    class _Outil:
        def _run(self, **kw):
            vus.append(kw)
            return json.dumps({"success": True, "data": kw} if succes
                              else {"success": False, "error": "HTTP 500"})

    monkeypatch.setattr(places_merge, "GrampsMergePlacesTool", _Outil)
    return vus


def test_fusionne_les_doublons_prouves(tmp_path, monkeypatch):
    vus = _stub_fusion(monkeypatch)
    chemin = run_places_detect(_arbre(DOUBLONS), tmp_path, scope="all",
                               date="2026-07-21")
    md = chemin.read_text(encoding="utf-8")
    assert "Fusions appliquées : 1" in md
    assert len(vus) == 1
    assert vus[0]["keep_handle"] == "HA" and vus[0]["merge_handle"] == "HB"


def test_paris_n_est_jamais_fusionne(tmp_path, monkeypatch):
    """Le cas qui doit rester rouge si le veto disparaît."""
    vus = _stub_fusion(monkeypatch)
    chemin = run_places_detect(_arbre(PARIS), tmp_path, scope="all", date="2026-07-21")
    md = chemin.read_text(encoding="utf-8")
    assert vus == []
    assert "Fusions appliquées : 0" in md
    assert "À relire : 1" in md


def test_l_arbitrage_est_ecrit_en_yaml_consommable(tmp_path, monkeypatch):
    """Le YAML doit être relisible par `merge places --yaml` sans transformation."""
    _stub_fusion(monkeypatch)
    run_places_detect(_arbre(PARIS), tmp_path, scope="all", date="2026-07-21")
    p = tmp_path / "lieux" / "2026-07-21_arbitrage_lieux_all.yaml"
    lignes = yaml.safe_load(p.read_text(encoding="utf-8"))
    assert len(lignes) == 1
    assert set(lignes[0]) >= {"handle_keep", "handle_merge",
                              "gramps_id_keep", "gramps_id_merge", "canonical"}


def test_la_simulation_n_execute_aucune_fusion(tmp_path, monkeypatch):
    vus = _stub_fusion(monkeypatch)
    chemin = run_places_detect(_arbre(DOUBLONS), tmp_path, scope="all",
                               date="2026-07-21", dry_run=True)
    assert vus == []
    md = chemin.read_text(encoding="utf-8")
    assert "simulation" in md
    assert "Fusions à appliquer : 1" in md


def test_un_echec_de_fusion_est_rapporte(tmp_path, monkeypatch):
    _stub_fusion(monkeypatch, succes=False)
    chemin = run_places_detect(_arbre(DOUBLONS), tmp_path, scope="all",
                               date="2026-07-21")
    md = chemin.read_text(encoding="utf-8")
    assert "Fusions appliquées : 0" in md
    assert "P0070" in md and "HTTP 500" in md
```

- [ ] **Step 2 : lancer les tests pour les voir échouer**

```bash
cd /Users/fjacquet/Projects/fusions-lieux/genecrew
uv run python -m pytest genecrew/tests/test_places_detect.py -q
```

Attendu : ÉCHEC — `ImportError: cannot import name 'run_places_detect'`.

- [ ] **Step 3 : implémenter**

Ajouter l'import de la détection en tête de `places_merge.py` :

```python
from crewai_custom_tools.tools.genealogy.analysis.place_duplicates import etager_lieux
```

Puis, à la fin du module :

```python
def run_places_detect(client: GrampsClient, output_dir, *, scope: str, date: str,
                      limit: int | None = None, dry_run: bool = False) -> Path:
    """Détecte les doublons de lieux, fusionne les prouvés, dépose le reste en YAML.

    Une seule passe : les candidats sont groupés par égalité de nom normalisé, une
    relation d'équivalence — les groupes sont complets dès la lecture, et fusionner
    deux lieux n'en renomme aucun autre.
    """
    eff = effective_dry_run(dry_run)
    output_dir = Path(output_dir)
    lieux = collecter_lieux(client, scope, limit=limit)
    propositions = etager_lieux(lieux)
    arbitrage = [p for p in propositions if p.verdict != "auto"]

    tool = GrampsMergePlacesTool()
    fusions: list = []
    errors: list = []
    for prop in (p for p in propositions if p.verdict == "auto"):
        if eff:
            fusions.append(prop)                 # simulation : rapporté, jamais exécuté
            continue
        payload = json.loads(tool._run(keep_handle=prop.handle_keep,
                                       merge_handle=prop.handle_merge, dry_run=eff))
        if payload["success"]:
            fusions.append(prop)
        else:
            errors.append((prop.gramps_id_merge, payload["error"]))

    out = output_dir / "lieux"
    out.mkdir(parents=True, exist_ok=True)
    scope_slug = scope.replace(":", "_")
    (out / f"{date}_arbitrage_lieux_{scope_slug}.yaml").write_text(
        yaml.safe_dump([p.model_dump() for p in arbitrage], allow_unicode=True,
                       sort_keys=False), encoding="utf-8")
    path = out / f"{date}_doublons_lieux_{scope_slug}.md"
    path.write_text(render_detect_report(date, fusions, arbitrage, errors,
                                         len(lieux), eff), encoding="utf-8")
    return path
```

- [ ] **Step 4 : lancer les tests pour les voir passer**

```bash
cd /Users/fjacquet/Projects/fusions-lieux/genecrew
uv run python -m pytest genecrew/tests/test_places_detect.py -q
```

Attendu : PASS, 17 tests.

- [ ] **Step 5 : commiter**

```bash
cd /Users/fjacquet/Projects/fusions-lieux/genecrew
uv run ruff check . && \
git add genecrew/src/genecrew/places_merge.py genecrew/tests/test_places_detect.py && \
git commit -F - <<'EOF'
feat(lieux): orchestration du mode détection

Collecte, étagement, exécution des fusions prouvées, dépôt de l'arbitrage
en YAML directement consommable par `merge places --yaml`.

Une seule passe : les candidats sont groupés par égalité de nom
normalisé, une relation d'équivalence, donc fusionner deux lieux n'en
renomme aucun autre.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>
EOF
```

---

### Task 9 : la surface CLI (genecrew)

**Files:**
- Modify: `genecrew/src/genecrew/cli.py:148-151`
- Modify: `genecrew/src/genecrew/main.py:266-278`
- Test: `genecrew/tests/test_cli_parser.py`, `genecrew/tests/test_cli_dispatch.py`

**Interfaces:**
- Consumes: `run_places_detect` (Task 8), `run_places_merge` (existant).
- Produces: `merge places` accepte `--scope`/`--limit` et rend `--yaml` optionnel.

- [ ] **Step 1 : écrire les tests qui échouent**

Dans `genecrew/tests/test_cli_parser.py`, remplacer la ligne `merge places` de la liste `LEAVES` par ces deux lignes :

```python
    (["merge", "places", "--yaml", "fusions.yaml"], "merge", "places"),
    (["merge", "places", "--scope", "all"], "merge", "places"),
```

Ajouter à la fin du même fichier :

```python
def test_merge_places_accepte_le_mode_detection_sans_yaml():
    """`--yaml` devient optionnel : sans lui, la commande détecte."""
    args = build_parser().parse_args(["merge", "places", "--scope", "all"])
    assert args.yaml is None
    assert args.scope == "all"
    assert args.limit is None
```

Dans `genecrew/tests/test_cli_dispatch.py`, remplacer la ligne `merge places` de `ROUTES` par :

```python
    (["merge", "places", "--yaml", "f.yaml"], "lieux_merge_cmd"),
    (["merge", "places", "--scope", "all"], "lieux_merge_cmd"),
```

- [ ] **Step 2 : lancer les tests pour les voir échouer**

```bash
cd /Users/fjacquet/Projects/fusions-lieux/genecrew
uv run python -m pytest genecrew/tests/test_cli_parser.py genecrew/tests/test_cli_dispatch.py -q
```

Attendu : ÉCHEC — `SystemExit: 2`, `the following arguments are required: --yaml`.

- [ ] **Step 3 : rendre `--yaml` optionnel et ajouter le périmètre**

Dans `genecrew/src/genecrew/cli.py`, remplacer le bloc `merge places` (lignes 148-151) par :

```python
    p = merge_sub.add_parser(
        "places",
        help="Détecte les doublons de lieux et fusionne les prouvés ; "
             "ou exécute un YAML relu (ADR 0015)")
    _add_scope(p, "all | place:ID")
    p.add_argument("--yaml", default=None,
                   help="exécuter les fusions d'un YAML relu, au lieu de détecter")
    _add_dry_run(p)
    _add_date(p)
```

- [ ] **Step 4 : router les deux modes**

Dans `genecrew/src/genecrew/main.py`, remplacer le corps de `lieux_merge_cmd` (lignes 266-278) par :

```python
def lieux_merge_cmd(args) -> None:
    """Détecte et fusionne les doublons de lieux prouvés, ou exécute un YAML relu."""
    from pathlib import Path

    from crewai_custom_tools.tools.genealogy.gramps.client import get_client

    from genecrew.places_merge import run_places_detect, run_places_merge

    client = get_client()
    output_dir = Path(os.environ.get("GENECREW_OUTPUT_DIR", "output"))
    date = args.date or __import__("datetime").date.today().isoformat()
    if args.yaml:
        report = run_places_merge(client, args.yaml, output_dir, date=date,
                                  dry_run=args.dry_run)
    else:
        report = run_places_detect(client, output_dir, scope=args.scope, date=date,
                                   limit=args.limit, dry_run=args.dry_run)
    print(f"Rapport : {report}")
```

- [ ] **Step 5 : lancer la suite complète**

```bash
cd /Users/fjacquet/Projects/fusions-lieux/genecrew
uv run python -m pytest genecrew/tests/ -q && uv run ruff check .
```

Attendu : suite au vert.

- [ ] **Step 6 : vérifier l'aide à la main**

```bash
cd /Users/fjacquet/Projects/fusions-lieux/genecrew
uv run genecrew merge places --help
```

Attendu : `--scope`, `--limit`, `--yaml` (optionnel), `--dry-run`, `--date`.

- [ ] **Step 7 : commiter**

```bash
cd /Users/fjacquet/Projects/fusions-lieux/genecrew
git add genecrew/src/genecrew/cli.py genecrew/src/genecrew/main.py \
        genecrew/tests/test_cli_parser.py genecrew/tests/test_cli_dispatch.py && \
git commit -F - <<'EOF'
feat(cli): merge places gagne son mode détection

`--yaml` devient optionnel et `--scope` apparaît, exactement comme
`merge people`. Sans `--yaml`, la commande détecte les doublons et
fusionne les prouvés ; avec, elle exécute des paires relues.

La grammaire à sept verbes ne bouge pas : c'est la même feuille, avec
deux modes.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>
EOF
```

---

### Task 10 : ADR 0015 et documentation (genecrew)

**Files:**
- Create: `docs/adr/0015-detection-doublons-lieux.md`
- Modify: `CLAUDE.md`, `docs/USER_GUIDE.md`

**Interfaces:**
- Consumes: le comportement livré aux Tasks 1-9. Rien ne dépend de cette tâche.

- [ ] **Step 1 : vérifier les faits avant d'écrire**

```bash
cd /Users/fjacquet/Projects/fusions-lieux/genecrew
uv run genecrew merge places --help
grep -n "merge places" CLAUDE.md
ls docs/adr/ | tail -3
```

N'écris **aucune** affirmation que ces commandes n'ont pas confirmée : numéro d'ADR libre, surface réelle de la commande, formulation actuelle de `CLAUDE.md`.

- [ ] **Step 2 : écrire l'ADR**

Créer `docs/adr/0015-detection-doublons-lieux.md`. Lire d'abord `docs/adr/0013-fusion-doublons-preuve-structurelle.md` pour le ton — français, court, Contexte / Décision / Conséquences, contreparties assumées sans enjolivement.

```markdown
# ADR 0015 — Détection et fusion automatique des doublons de lieux

Date : 2026-07-21 — Statut : accepté

## Contexte

`apply places` ne traite que les lieux de type `Unknown` : sa boucle saute tout lieu déjà
structuré, au nom de l'idempotence. C'est aussi lui qui produit le YAML de fusions, et il ne
le compose que pour les lieux qu'il vient de résoudre. **Un doublon déjà typé n'entre donc
dans le champ d'aucune commande.**

Mesure du 2026-07-21 : 11 groupes de communes homonymes, tous de type `Municipality`, tous
invisibles au pipeline. Ils ont dû être fusionnés à la main, un par un.

`merge places` existait, mais seulement comme exécutant : `--yaml` requis. Son voisin
`merge people` a les deux modes depuis l'ADR 0013.

## Décision

`merge places --scope` détecte les doublons, fusionne ceux qui sont **prouvés**, et dépose le
reste en YAML d'arbitrage — que `merge places --yaml` exécute après relecture.

Deux lieux sont candidats s'ils portent le même **nom normalisé**. Un **veto** passe avant
tout : deux codes officiels non vides et différents interdisent la fusion. Hors veto, la
preuve est soit **des codes identiques** (un code officiel est canonique, il vaut entre types
différents), soit **le même type et des coordonnées identiques** (la voie des lieux sans code).

Les coordonnées ne prouvent **jamais** rien entre types différents. Paris existe en
`Department` (code 75) et en `Municipality` (code 75056) : deux entités administratives
réelles. Le chantier référentiel donnera des coordonnées aux départements, et un département
géocodé reçoit le point de son chef-lieu — sans cette garde, le piège deviendrait atteignable.

Le survivant est choisi par **richesse d'abord** (coordonnées, code, rattachement), puis
rétroliens, puis identifiant le plus petit. La fusion Gramps unionne les listes mais conserve
les champs simples du survivant : garder une coquille vide effacerait définitivement les
coordonnées de l'autre. Le rapport nomme ce que l'ordre inverse aurait perdu.

C'est la doctrine de l'ADR 0013 transposée : la ressemblance ne prouve jamais l'identité. Avec
un avantage que les personnes n'ont pas — une commune possède un identifiant canonique.

## Conséquences

Les doublons de lieux cessent d'être invisibles. La déduplication se fait en **une seule
passe** : le groupement par égalité de nom normalisé est une relation d'équivalence, et
fusionner deux lieux n'en renomme aucun autre — contrairement aux personnes, où une fusion
peut en révéler d'autres.

Contrepartie assumée : le comptage des rétroliens coûte un appel API par lieu. C'est la seule
mesure qui dise lequel de deux homonymes l'arbre utilise réellement.

Hors périmètre : créer ou compléter des lieux — c'est `apply places` et le chantier
référentiel.
```

- [ ] **Step 3 : mettre `CLAUDE.md` à jour**

Deux retouches :

1. dans la section « Commands », sous la ligne `merge places --yaml`, ajouter :

```bash
uv run genecrew merge places --scope all --dry-run   # détecte les doublons de lieux (ADR 0015)
```

2. dans « Gotchas », après le point sur la fusion de personnes, ajouter :

```markdown
- **Doublons de lieux** : `merge places --scope` (ADR 0015) les détecte, ce qu'`apply places`
  ne peut pas faire — il ne regarde que les lieux de type `Unknown`. Veto sur codes officiels
  différents, et les coordonnées ne prouvent rien entre types différents : Paris existe en
  `Department` 75 et en `Municipality` 75056, deux entités réelles. Le survivant est le plus
  riche, pas le plus référencé — Gramps garde ses champs simples et effacerait ceux de l'autre.
```

- [ ] **Step 4 : mettre `docs/USER_GUIDE.md` à jour**

Ajouter une section de niveau `##`, après celle qui décrit les lieux :

```markdown
## Fusionner les doublons de lieux

```bash
uv run genecrew merge places --scope all --dry-run   # détecte, simule
uv run genecrew merge places --scope all             # détecte et fusionne les prouvés
uv run genecrew merge places --yaml <arbitrage.yaml> # exécute les paires relues
```

Le premier passage écrit deux fichiers dans `output/lieux/` : un rapport Markdown et un YAML
d'arbitrage. Les fusions **prouvées** — même code officiel, ou mêmes coordonnées à type égal —
sont faites automatiquement. Les autres attendent votre relecture dans le YAML, que la
troisième commande exécute une fois relu.

Le rapport indique, pour chaque fusion, quel lieu survit et **ce qui aurait été perdu** dans
l'ordre inverse : Gramps conserve les champs simples du survivant et efface ceux du lieu
absorbé.
```

- [ ] **Step 5 : vérifier et commiter**

```bash
cd /Users/fjacquet/Projects/fusions-lieux/genecrew
uv run python -m pytest genecrew/tests/ -q && uv run ruff check . && uv run mkdocs build --strict 2>&1 | tail -3
git add docs/adr/0015-detection-doublons-lieux.md CLAUDE.md docs/USER_GUIDE.md && \
git commit -F - <<'EOF'
docs(adr): ADR 0015 — détection des doublons de lieux

Comble l'angle mort : apply places ne regarde que les lieux Unknown, donc
un doublon déjà typé n'entrait dans le champ d'aucune commande. 11 groupes
de communes homonymes avaient dû être fusionnés à la main.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>
EOF
```

---

### PORTE HUMAINE 2 : validation sur l'arbre réel

**Aucun agent n'exécute cette étape.**

**Prérequis** : l'arbre de travail n'a **pas** de fichier `.env` — il est ignoré par git, donc absent de tout worktree, et sans lui la commande échoue sur `Missing environment variable: GRAMPS_API_URL`. Copier celui du clone principal avant de lancer :

```bash
cp /Users/fjacquet/Projects/genecrew/.env /Users/fjacquet/Projects/fusions-lieux/genecrew/.env
```

Ce fichier porte des secrets : il reste ignoré par git dans le worktree comme ailleurs, et n'a pas à être commité.

```bash
cd /Users/fjacquet/Projects/fusions-lieux/genecrew
uv run genecrew merge places --scope all --dry-run
```

À vérifier dans le rapport avant d'écrire pour de vrai :

- **Paris est en arbitrage, pas en fusion.** C'est le contrôle qui compte le plus.
- Annaba, Sétif et Souk Ahras sont en arbitrage.
- Les groupes de communes attendus apparaissent en fusion prouvée.
- Pour chaque fusion, le survivant est bien le lieu le plus renseigné, et la colonne « perte
  évitée » est cohérente.

Puis, seulement si tout concorde, relancer sans `--dry-run`.

---

## Auto-revue du plan

**Couverture de la spec.** §1 (l'angle mort) → Tasks 8-9. §2 (frontière avec le référentiel) →
Task 10, ADR. §3 (la preuve, veto compris) → Tasks 2, 3, 5. §4 (survivant et perte évitée) →
Tasks 4, 7. §5 (transitivité) → Task 5, **avec l'écart documenté en tête du plan** : groupement
par équivalence, donc une seule passe et pas de `--max-passes`. §6 (surface CLI) → Task 9.
§7 (où vit le code) → Tasks 1-5 bibliothèque, 6-9 genecrew. §7.1 (normalisation canonique) →
Task 2. §8 (tests) → répartis, les cinq cas réels sont nommés en Tasks 3 et 5. §9 (ADR) →
Task 10. §10 (hors périmètre) → rappelé dans l'ADR.

**Cohérence des noms.** `PlaceFacts` et les champs `verdict`/`perte_evitee` (Task 1) sont
consommés sous ces noms exacts en Tasks 3-8. `evaluer_preuve` rend `"code"` / `"coordonnees"` /
`""`, valeurs utilisées telles quelles par `etager_lieux` (Task 5) via `_MOTIFS`.
`choisir_survivant` prend une **liste** et rend un `PlaceFacts` — signature respectée en Task 5.
`collecter_lieux`, `render_detect_report` et `run_places_detect` portent en Task 9 les noms
définis en Tasks 6, 7 et 8.

**Points de vigilance pour l'implémenteur.**

- Task 6 : `_retroliens` fait **un appel par lieu**. Le test `_arbre()` répond sur
  `/api/places/<handle>` ; ne pas confondre avec `/api/places/` (la liste), qui est le même
  préfixe — l'ordre des tests de chemin dans le stub compte.
- Task 8 : le stub remplace `GrampsMergePlacesTool` **par son nom dans le module
  `places_merge`**, pas dans la bibliothèque.
- Tasks 1-5 se font dans l'arbre **bibliothèque**, Tasks 6-10 dans l'arbre **genecrew**. Les
  deux ont un `git status` distinct : vérifier le répertoire avant chaque commit.
