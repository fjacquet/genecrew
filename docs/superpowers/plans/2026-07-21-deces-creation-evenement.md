# `apply deaths` — création d'événements décès sourcés : plan d'implémentation

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Écrire dans Gramps les décès que `propose deaths` / `propose military` trouvent mais que l'arbre ignore — événement daté, situé, sourcé — depuis un YAML relu par un humain.

**Architecture:** Une nouvelle cible `apply deaths` consomme le même YAML relu que `apply citations`, mais y prend les propositions disjointes `type: date`. L'écriture réutilise `GrampsCreateEventTool`, qui existe déjà et couvre création + rattachement + `death_ref_index`. Le seul ajout bibliothèque est deux champs structurés sur `PropositionAudit`, pour que la date et la commune voyagent en donnée machine et non en prose française.

**Tech Stack:** Python 3.12, `uv`, pydantic v2, `httpx` (+ `MockTransport` pour les tests), pytest, argparse. Deux dépôts : `crewai_custom_tools` (bibliothèque) et `genecrew` (orchestration/CLI).

## Global Constraints

- Spec de référence : `docs/superpowers/specs/2026-07-21-deces-creation-evenement-design.md` (commit `32522df`).
- Toutes les commandes se lancent **depuis la racine du dépôt** concerné, jamais depuis un sous-dossier.
- Python toujours via `uv` — jamais `pip` ni `python` direct.
- Tests genecrew : `uv run python -m pytest genecrew/tests/ -q`.
- Tests bibliothèque : `uv run python -m pytest tests/ -q` depuis `/Users/fjacquet/Projects/crewai_custom_tools`.
- Lint : `uv run ruff check .` doit passer avant chaque commit.
- Les tests sont **offline** : aucun appel réseau réel, `httpx.MockTransport` partout.
- Écriture Gramps toujours derrière `effective_dry_run` ; le rapport affiche le dry-run **effectif** (variable d'environnement comprise).
- Confiance Gramps des citations plafonnée à 2 (l'outil s'en charge).
- Commits en français, préfixe conventionnel (`feat:`, `test:`, `docs:`, `refactor:`), et se terminant par `Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>`.
- **Aucun agent ne pousse, ne tague ni ne merge.** Ces gestes sont des portes humaines, explicitement marquées dans le plan.
- Branche genecrew : `feat/deces-creation-evenement` (déjà créée, contient les deux commits de spec).

## Écart assumé avec la spec

La spec §4 prévoit **trois** champs (`date_iso`, `lieu_nom`, `lieu_code`). Le plan n'en implémente que **deux**.

`lieu_code` est abandonné : la réponse MatchID n'expose, dans tout le code existant (`matchid.py:69-86`), qu'un `location.city` et un `location.country`. Aucun code INSEE de commune n'y est lu nulle part. Remplir `lieu_code` demanderait de deviner un nom de clé d'API non vérifié, pour un champ que la v2 ne consomme pas (§7 résout par nom). YAGNI : il s'ajoutera le jour où une source le fournit vraiment.

---

### Task 1 : les champs structurés sur `PropositionAudit` (bibliothèque)

**Files:**
- Modify: `/Users/fjacquet/Projects/crewai_custom_tools/src/crewai_custom_tools/tools/genealogy/models/domain.py:167-182`
- Test: `/Users/fjacquet/Projects/crewai_custom_tools/tests/test_genealogy_domain.py`

**Interfaces:**
- Consumes: rien (première tâche).
- Produces: `PropositionAudit.date_iso: str` et `PropositionAudit.lieu_nom: str`, tous deux `default=""`. Consommés par les Tasks 3, 5 et 7.

- [ ] **Step 1 : se placer sur une branche dédiée dans le dépôt bibliothèque**

```bash
cd /Users/fjacquet/Projects/crewai_custom_tools
git status --short          # doit être vide
git checkout -b feat/proposition-champs-structures
```

- [ ] **Step 2 : écrire les tests qui échouent**

Ajouter à la fin de `/Users/fjacquet/Projects/crewai_custom_tools/tests/test_genealogy_domain.py` :

```python
def test_proposition_audit_champs_structures_par_defaut_vides():
    """Un YAML antérieur à ces champs reste chargeable : défauts vides, pas d'erreur."""
    p = PropositionAudit(
        type="date", gramps_id="I0174", handle="H174", personne="Alain Rolland",
        cible="décès de I0174 (absent de l'arbre)",
        action="Renseigner le décès : 2021-12-23 à Saint-Palais.",
        priorite="moyenne", confiance=2)
    assert p.date_iso == ""
    assert p.lieu_nom == ""


def test_proposition_audit_porte_la_donnee_machine():
    """La date et la commune voyagent en champs typés, pas seulement dans la phrase."""
    p = PropositionAudit(
        type="date", gramps_id="I0174", handle="H174", personne="Alain Rolland",
        cible="décès de I0174 (absent de l'arbre)",
        action="Renseigner le décès : 2021-12-23 à Saint-Palais.",
        priorite="moyenne", confiance=2,
        date_iso="2021-12-23", lieu_nom="Saint-Palais")
    assert (p.date_iso, p.lieu_nom) == ("2021-12-23", "Saint-Palais")
```

Vérifier que `PropositionAudit` est bien importé en haut du fichier ; s'il ne l'est pas, ajouter :

```python
from crewai_custom_tools.tools.genealogy.models.domain import PropositionAudit
```

- [ ] **Step 3 : lancer les tests pour les voir échouer**

```bash
cd /Users/fjacquet/Projects/crewai_custom_tools
uv run python -m pytest tests/test_genealogy_domain.py -q -k champs_structures
```

Attendu : ÉCHEC. Pydantic v2 ignore silencieusement un champ inconnu passé au constructeur seulement si `model_config` l'autorise ; ici l'échec se lit soit en `ValidationError`, soit en `AttributeError: 'PropositionAudit' object has no attribute 'date_iso'`.

- [ ] **Step 4 : ajouter les deux champs**

Dans `src/crewai_custom_tools/tools/genealogy/models/domain.py`, à la fin de la classe `PropositionAudit` (juste après la ligne `confiance: int = Field(...)`) :

```python
    date_iso: str = Field(
        default="",
        description="Date ISO (AAAA-MM-JJ) du fait proposé, quand la source la donne.")
    lieu_nom: str = Field(
        default="",
        description="Commune du fait proposé, telle que la source l'écrit.")
```

Ajouter juste au-dessus de `date_iso` ce commentaire, qui explique pourquoi ces champs existent :

```python
    # La donnée machine, à côté de la phrase française. `action` reste ce qu'un humain
    # relit ; ces champs sont ce qu'une commande `apply` applique. Sans eux il faudrait
    # re-parser la prose, et une reformulation de la phrase casserait une écriture.
    # Optionnels : les règles D pures et le crew LLM émettent le même modèle sans avoir
    # rien à y mettre.
```

- [ ] **Step 5 : lancer les tests pour les voir passer**

```bash
cd /Users/fjacquet/Projects/crewai_custom_tools
uv run python -m pytest tests/test_genealogy_domain.py -q
```

Attendu : PASS, tous les tests du fichier.

- [ ] **Step 6 : vérifier que rien d'autre n'a bougé**

```bash
cd /Users/fjacquet/Projects/crewai_custom_tools
uv run python -m pytest tests/ -q && uv run ruff check .
```

Attendu : suite complète au vert, ruff sans erreur.

- [ ] **Step 7 : commiter**

```bash
cd /Users/fjacquet/Projects/crewai_custom_tools
git add src/crewai_custom_tools/tools/genealogy/models/domain.py tests/test_genealogy_domain.py
git commit -F - <<'EOF'
feat(domain): champs structurés date_iso et lieu_nom sur PropositionAudit

La donnée machine à côté de la phrase française : `action` reste ce qu'un
humain relit, ces champs sont ce qu'une commande `apply` applique. Sans eux,
`apply deaths` devrait re-parser la prose, et toute reformulation de la
phrase casserait une écriture.

Optionnels et par défaut vides : les règles D pures et le crew LLM émettent
le même modèle sans avoir rien à y mettre, et un YAML antérieur reste
chargeable.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>
EOF
```

---

### PORTE HUMAINE 1 : publication de la bibliothèque

**Aucun agent n'exécute cette étape.** Le tag est un contrôle qualité délibéré du projet.

À faire par un humain, depuis `/Users/fjacquet/Projects/crewai_custom_tools` :

1. relire le diff de la Task 1 ;
2. fusionner `feat/proposition-champs-structures` dans `main` ;
3. porter la version de `0.23.1` à `0.24.0` **aux deux endroits** : `pyproject.toml:7`
   **et** `src/crewai_custom_tools/__init__.py:3` (`__version__`). Le test
   `tests/test_scaffold.py::test_version_matches_pyproject` compare les deux sources ;
   un bump d'un seul côté passe en local si la suite tourne avant le bump, et rougit en CI ;
4. **relancer la suite APRÈS le bump** (`uv run python -m pytest tests/ -q`) — leçon d'un
   incident réel sur la 0.22.0 ;
5. commiter, **taguer `v0.24.0` en tag ANNOTÉ** (`git tag -a v0.24.0 -m "..."` ; le dépôt
   refuse les tags légers), pousser la branche **et** le tag.

Sans tag poussé, la CI de genecrew ne peut pas verdir : elle checkoute le voisin sur le tag lu dans `uv.lock`, et `uv sync --locked` refusera le lock.

**Cette porte ne bloque PAS les Tasks 2-9.** `crewai-custom-tools` est une dépendance
**éditable** (`[tool.uv.sources] … path = "../crewai_custom_tools", editable = true`) : genecrew
résout la bibliothèque vers l'arbre de travail local du dépôt voisin, pas vers une version
publiée. Les champs de la Task 1 sont donc visibles depuis genecrew dès qu'ils sont commités
localement — vérifié. La porte bloque uniquement **la CI et la fusion**, pas le développement.

En contrepartie, tant que les Tasks 2-9 tournent, le dépôt voisin doit **rester** sur
`feat/proposition-champs-structures` (ou sur `main` une fois la fusion faite). Si une autre
session le bascule ailleurs, les champs disparaissent sous les pieds de genecrew et les tests
se mettent à échouer sans que rien n'ait changé dans genecrew. Vérifier en cas d'échec
inexpliqué :

```bash
cd /Users/fjacquet/Projects/crewai_custom_tools && git rev-parse --abbrev-ref HEAD
```

---

### Task 2 : extraire la brique d'écriture d'événement (genecrew)

`releves_import.py:481` contient déjà la séquence « créer un événement et décoder l'orphelin », mais couplée à `ReleveIndexe` : elle appelle `resoudre_ou_creer_lieu(client, releve)` et `_creer_citation_releve(client, releve)`. On n'extrait donc **pas** la fonction telle quelle — on en sort la partie réellement générique : l'appel à l'outil et la lecture de son succès qualifié.

**Files:**
- Create: `genecrew/src/genecrew/evenements.py`
- Modify: `genecrew/src/genecrew/releves_import.py:438-452` (`_dateval_iso`) et `:481-515` (`_creer_evenement`)
- Test: `genecrew/tests/test_evenements.py`

**Interfaces:**
- Consumes: `GrampsCreateEventTool` et `effective_dry_run` de `crewai_custom_tools.tools.genealogy.gramps.write_tools`.
- Produces:
  - `dateval_iso(iso: str) -> list[int] | None`
  - `creer_evenement_source(person_handle: str, *, event_type: str, dateval: list[int] | None = None, place_handle: str | None = None, citation_handle: str | None = None, modifier: int = 0, quality: int = 0, dry_run: bool = False) -> dict` rendant les clés `posee: bool`, `event_handle: str | None`, `attache: bool`, `raison: str`.
  - Les deux sont consommés par la Task 7.

- [ ] **Step 1 : vérifier que les champs de la Task 1 sont visibles**

```bash
cd /Users/fjacquet/Projects/genecrew
git rev-parse --abbrev-ref HEAD      # doit être feat/deces-creation-evenement
uv run python -c "from crewai_custom_tools.tools.genealogy.models.domain import PropositionAudit as P; print('date_iso' in P.model_fields, 'lieu_nom' in P.model_fields)"
```

Attendu : `True True`. La dépendance est **éditable** : elle résout vers l'arbre de travail du
dépôt voisin, donc le commit local de la Task 1 suffit — ni tag ni fusion nécessaires ici.

Si `False False`, le dépôt voisin a été basculé sur une autre branche par une session
concurrente ; le signaler plutôt que d'essayer de le réparer :

```bash
cd /Users/fjacquet/Projects/crewai_custom_tools && git rev-parse --abbrev-ref HEAD
```

- [ ] **Step 2 : écrire les tests qui échouent**

Créer `genecrew/tests/test_evenements.py` :

```python
"""Tests offline de la brique partagée de création d'événement."""

import json

import pytest

from genecrew import evenements
from genecrew.evenements import creer_evenement_source, dateval_iso


@pytest.fixture(autouse=True)
def _real_writes(monkeypatch):
    monkeypatch.setenv("GENECREW_DRY_RUN", "false")


def test_dateval_sur_date_complete():
    assert dateval_iso("2021-12-23") == [23, 12, 2021]


def test_dateval_refuse_annee_seule():
    """Une année seule n'est jamais discriminante : pas de date inventée."""
    assert dateval_iso("2021") is None


def test_dateval_refuse_chaine_vide_ou_batarde():
    assert dateval_iso("") is None
    assert dateval_iso("le 23 décembre") is None


def _stub_outil(monkeypatch, payload):
    class _Outil:
        def _run(self, **kwargs):
            _Outil.vu = kwargs
            return json.dumps(payload)

    monkeypatch.setattr(evenements, "GrampsCreateEventTool", _Outil)
    return _Outil


def test_evenement_cree_et_rattache(monkeypatch):
    _stub_outil(monkeypatch, {"success": True, "data": {
        "handle": "EV1", "created": True, "attached": True}})
    res = creer_evenement_source("H1", event_type="Death", dateval=[23, 12, 2021])
    assert res == {"posee": True, "event_handle": "EV1", "attache": True,
                   "raison": "Death créé"}


def test_orphelin_signale_avec_son_handle(monkeypatch):
    """Événement créé mais non rattaché : le handle est la seule prise pour le retrouver."""
    _stub_outil(monkeypatch, {"success": True, "data": {
        "handle": "EV_ORPH", "created": True, "attached": False,
        "attach_error": "timeout"}})
    res = creer_evenement_source("H1", event_type="Death", dateval=[23, 12, 2021])
    assert res["posee"] is True
    assert res["attache"] is False
    assert "EV_ORPH" in res["raison"]
    assert "orphelin" in res["raison"].lower()


def test_creation_refusee(monkeypatch):
    _stub_outil(monkeypatch, {"success": False, "error": "500"})
    res = creer_evenement_source("H1", event_type="Death", dateval=[23, 12, 2021])
    assert res["posee"] is False
    assert res["event_handle"] is None
    assert "refusée" in res["raison"]


def test_parametres_transmis_a_l_outil(monkeypatch):
    outil = _stub_outil(monkeypatch, {"success": True, "data": {
        "handle": "EV1", "created": True, "attached": True}})
    creer_evenement_source("H1", event_type="Death", dateval=[23, 12, 2021],
                           place_handle="P9", citation_handle="C7", dry_run=True)
    assert outil.vu["person_handle"] == "H1"
    assert outil.vu["event_type"] == "Death"
    assert outil.vu["dateval"] == [23, 12, 2021]
    assert outil.vu["place_handle"] == "P9"
    assert outil.vu["citation_handle"] == "C7"
    assert outil.vu["dry_run"] is True
```

- [ ] **Step 3 : lancer les tests pour les voir échouer**

```bash
cd /Users/fjacquet/Projects/genecrew
uv run python -m pytest genecrew/tests/test_evenements.py -q
```

Attendu : ÉCHEC — `ModuleNotFoundError: No module named 'genecrew.evenements'`.

- [ ] **Step 4 : créer le module**

Créer `genecrew/src/genecrew/evenements.py` :

```python
"""Création d'un événement sourcé sur une personne — brique partagée.

`import releve` et `apply deaths` créent tous deux un événement daté, situé et cité
sur une personne existante. Ce qu'ils ont en commun n'est PAS la collecte — un relevé
de cercle et une correspondance INSEE n'ont rien à voir — mais l'ÉCRITURE : appeler
`GrampsCreateEventTool`, puis décoder son succès *qualifié*. Cet outil rend
`attached: False` quand l'événement a bien été créé mais n'a pas pu être rattaché à
la personne ; le handle rendu est alors la seule prise pour retrouver l'orphelin.
Lire ce cas correctement ne doit exister qu'à un seul endroit — deux copies, c'est
une copie qui finira par le rapporter comme un simple succès.
"""

from __future__ import annotations

import json

from crewai_custom_tools.tools.genealogy.gramps.write_tools import (
    GrampsCreateEventTool,
    effective_dry_run,
)


def dateval_iso(iso: str) -> list[int] | None:
    """« AAAA-MM-JJ » → `[jour, mois, année]` pour un `dateval` Gramps ; None sinon.

    None fait poser l'événement SANS date plutôt qu'avec une date inventée. Une année
    seule rend donc None : elle n'est jamais discriminante (règle projet — trop
    d'homonymes naissent et meurent la même année).
    """
    parts = (iso or "").split("-")
    if len(parts) != 3:
        return None
    try:
        annee, mois, jour = (int(p) for p in parts)
    except ValueError:
        return None
    return [jour, mois, annee]


def creer_evenement_source(person_handle: str, *, event_type: str,
                           dateval: list[int] | None = None,
                           place_handle: str | None = None,
                           citation_handle: str | None = None,
                           modifier: int = 0, quality: int = 0,
                           dry_run: bool = False) -> dict:
    """Crée un événement rattaché à une personne, et décode le résultat de l'outil.

    Rend `{"posee", "event_handle", "attache", "raison"}` :
      - `posee` : l'événement EXISTE dans la base ;
      - `attache` : il est rattaché à la personne. `False` = orphelin, et `raison`
        porte alors son handle en clair — jamais un « créé » trompeur.
    """
    dry_run = effective_dry_run(dry_run)
    evt = json.loads(GrampsCreateEventTool()._run(
        person_handle=person_handle, event_type=event_type, dateval=dateval,
        modifier=modifier, quality=quality, place_handle=place_handle,
        citation_handle=citation_handle, dry_run=dry_run))
    if not evt["success"]:
        return {"posee": False, "event_handle": None, "attache": False,
                "raison": f"création {event_type} refusée : {evt['error']}"}
    data = evt["data"]
    event_handle = data["handle"]
    attache = data.get("attached", True)
    raison = (f"{event_type} créé"
              if attache else
              f"{event_type} créé mais NON rattaché (orphelin {event_handle}) : "
              f"{data.get('attach_error', '')}")
    return {"posee": True, "event_handle": event_handle, "attache": attache,
            "raison": raison}
```

- [ ] **Step 5 : lancer les tests pour les voir passer**

```bash
cd /Users/fjacquet/Projects/genecrew
uv run python -m pytest genecrew/tests/test_evenements.py -q
```

Attendu : PASS, 7 tests.

- [ ] **Step 6 : faire déléguer `releves_import.py`**

Dans `genecrew/src/genecrew/releves_import.py`, ajouter l'import auprès des autres imports `genecrew` :

```python
from genecrew.evenements import creer_evenement_source, dateval_iso
```

**Supprimer entièrement** la fonction `_dateval_iso` (lignes 438-452) et remplacer son unique site d'appel, ligne 495, par la fonction partagée :

```python
    dv = dateval if dateval is not None else dateval_iso(releve.evenement_date)
```

Vérifier d'abord qu'il n'en reste aucun autre usage — un alias de compatibilité serait de l'indirection morte, la fonction n'ayant qu'un appelant et aucune référence en test :

```bash
grep -n "_dateval_iso" genecrew/src/genecrew/ genecrew/tests/ -r
```

Attendu après modification : aucune occurrence.

Dans `_creer_evenement`, remplacer le bloc allant de `evt = json.loads(GrampsCreateEventTool()._run(` jusqu'au `return` final par :

```python
    res = creer_evenement_source(
        person_handle, event_type=etype, dateval=dv, place_handle=lieu_handle,
        citation_handle=citation_handle, modifier=modifier, quality=quality,
        dry_run=dry_run)
    if not res["posee"]:
        return {"posee": False, "raison": res["raison"]}
    # `posee` a ici un sens PROPRE à l'import de relevés : « la citation est posée »,
    # pas « l'événement existe ». On ne l'aligne pas sur la brique partagée, sous peine
    # de changer le rapport de `import releve` que ses tests verrouillent.
    posee = citation_handle is not None
    raison = res["raison"] if not res["attache"] else (
        f"{etype} créé" + ("" if posee else f" (sans citation : {raison_cit})"))
    return {"posee": posee, "event_handle": res["event_handle"], "lieu": lieu_handle,
            "attache": res["attache"], "raison": raison}
```

Si `GrampsCreateEventTool` n'est plus référencé ailleurs dans `releves_import.py`, retirer son import ; le vérifier avec :

```bash
grep -n "GrampsCreateEventTool" genecrew/src/genecrew/releves_import.py
```

- [ ] **Step 7 : prouver que l'extraction n'a rien cassé**

```bash
cd /Users/fjacquet/Projects/genecrew
uv run python -m pytest genecrew/tests/test_releves_import.py genecrew/tests/test_evenements.py -q
```

Attendu : PASS partout. C'est la suite existante de `releves_import` (73 Ko) qui prouve que le refactor est sûr — si elle rougit, revenir en arrière plutôt que d'ajuster les tests.

- [ ] **Step 8 : commiter**

```bash
cd /Users/fjacquet/Projects/genecrew
uv run ruff check . && \
git add genecrew/src/genecrew/evenements.py genecrew/src/genecrew/releves_import.py genecrew/tests/test_evenements.py && \
git commit -F - <<'EOF'
refactor(evenements): extraire la brique de création d'événement sourcé

`import releve` et `apply deaths` créent tous deux un événement daté, situé
et cité sur une personne. Leur part commune n'est pas la collecte mais
l'écriture : appeler GrampsCreateEventTool puis décoder son succès qualifié
— un `attached: False` est un orphelin, et le handle rendu est la seule
prise pour le retrouver.

Cette lecture ne doit exister qu'à un endroit : deux copies, c'est une copie
qui finira par rapporter l'orphelin comme un simple succès.

`_creer_evenement` garde sa sémantique propre (`posee` y signifie « citation
posée »), verrouillée par la suite existante de releves_import.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>
EOF
```

---

### Task 3 : `deces.py` et `militaires.py` remplissent les champs structurés

**Files:**
- Modify: `genecrew/src/genecrew/deces.py:103-110`
- Modify: `genecrew/src/genecrew/militaires.py:42-51`
- Test: `genecrew/tests/test_deces.py`, `genecrew/tests/test_militaires.py`

**Interfaces:**
- Consumes: `PropositionAudit.date_iso` / `.lieu_nom` (Task 1).
- Produces: les propositions `type: date` de `build_deces_proposition` et de son équivalent militaire portent désormais `date_iso` et `lieu_nom`. Consommé par les Tasks 5 et 7.

- [ ] **Step 1 : écrire le test qui échoue (décès INSEE)**

Ajouter à `genecrew/tests/test_deces.py` :

```python
def test_proposition_date_porte_la_donnee_machine():
    """La date et la commune sortent en champs typés, pas seulement dans la phrase."""
    from crewai_custom_tools.tools.genealogy.models.domain import PersonFacts

    from genecrew.deces import build_deces_proposition

    person = PersonFacts(gramps_id="I0174", handle="H174", name="Alain Rolland",
                         surname="Rolland", given="Alain", sex="M")
    match = {"id": "0gGveHZwLxLg",
             "death": {"date": "20211223", "certificateId": "12",
                       "location": {"city": "Saint-Palais"}},
             "source": "2021", "sourceLine": "610579"}

    prop = build_deces_proposition(person, match, 1.0, exact_birth=True)

    assert prop.type == "date"
    assert prop.date_iso == "2021-12-23"
    assert prop.lieu_nom == "Saint-Palais"
```

`PersonFacts` exige `gramps_id`, `handle`, `name`, `surname`, `given` et `sex` ; `birth` et `death` valent `None` par défaut, ce qui est exactement le cas visé (décès absent de l'arbre).

- [ ] **Step 2 : lancer le test pour le voir échouer**

```bash
cd /Users/fjacquet/Projects/genecrew
uv run python -m pytest genecrew/tests/test_deces.py -q -k donnee_machine
```

Attendu : ÉCHEC — `assert '' == '2021-12-23'`.

- [ ] **Step 3 : remplir les champs dans `deces.py`**

Dans `build_deces_proposition`, branche `if person.death is None:` (ligne 103), ajouter les deux champs au `PropositionAudit` :

```python
    if person.death is None:
        return PropositionAudit(
            type="date", gramps_id=person.gramps_id, handle=person.handle,
            personne=person.name, cible=f"décès de {person.gramps_id} (absent de l'arbre)",
            action=f"Renseigner le décès : {insee_iso}"
                   + (f" à {lieu}" if lieu else "") + ", avec la source INSEE en citation.",
            preuve_url=_match_url(match), preuve_detail=detail,
            # Mêmes valeurs que la phrase ci-dessus, en donnée machine : c'est ce que
            # `apply deaths` applique. La phrase reste ce que l'humain relit.
            date_iso=insee_iso, lieu_nom=lieu,
            priorite="moyenne", confiance=confiance)
```

Ne rien changer aux deux autres branches : la branche `type="source"` vise un événement existant (rien à créer), et la branche « dates divergentes » naît en confiance 1, donc hors du périmètre de `apply deaths`.

- [ ] **Step 4 : lancer le test pour le voir passer**

```bash
cd /Users/fjacquet/Projects/genecrew
uv run python -m pytest genecrew/tests/test_deces.py -q
```

Attendu : PASS, tout le fichier.

- [ ] **Step 5 : écrire le test qui échoue (décès militaire)**

Ajouter à `genecrew/tests/test_militaires.py` :

```python
def test_proposition_date_militaire_porte_la_donnee_machine():
    """Mémoire des hommes hérite du même contrat que l'INSEE : date et commune typées."""
    from crewai_custom_tools.tools.genealogy.models.domain import PersonFacts

    from genecrew.militaires import build_militaire_proposition

    person = PersonFacts(gramps_id="I0500", handle="H500", name="Jean Dupont",
                         surname="Dupont", given="Jean", sex="M")
    row = {"deces_date": "1916-05-12", "deces_lieu": "Verdun",
           "base": "Morts pour la France 1914-1918", "unite": "42e RI",
           "reference": "1916/123", "lien_ark": "https://ark.example/x"}

    prop = build_militaire_proposition(person, row, 1.0, exact_birth=True)

    assert prop.type == "date"
    assert prop.date_iso == "1916-05-12"
    assert prop.lieu_nom == "Verdun"
```

`build_militaire_proposition(person, row, score, *, exact_birth)` lit la date dans `row["deces_date"]` et la commune dans `row["deces_lieu"]` (`militaires.py:31-32`).

- [ ] **Step 6 : lancer le test pour le voir échouer**

```bash
cd /Users/fjacquet/Projects/genecrew
uv run python -m pytest genecrew/tests/test_militaires.py -q -k donnee_machine
```

Attendu : ÉCHEC — les champs sont vides.

- [ ] **Step 7 : remplir les champs dans `militaires.py`**

Dans la branche `if person.death is None:` (ligne 42), ajouter à l'appel `PropositionAudit(...)`, juste avant `priorite=` :

```python
            date_iso=insee_iso, lieu_nom=lieu,
```

- [ ] **Step 8 : lancer les tests et commiter**

```bash
cd /Users/fjacquet/Projects/genecrew
uv run python -m pytest genecrew/tests/test_deces.py genecrew/tests/test_militaires.py -q && \
uv run ruff check . && \
git add genecrew/src/genecrew/deces.py genecrew/src/genecrew/militaires.py \
        genecrew/tests/test_deces.py genecrew/tests/test_militaires.py && \
git commit -F - <<'EOF'
feat(deces): émettre la date et la commune en donnée machine

Les propositions `type: date` de l'INSEE et de Mémoire des hommes portent
désormais date_iso et lieu_nom, en plus de la phrase française qui les
contenait seule. `apply deaths` les appliquera sans jamais re-parser la
prose.

Les branches `source` et « dates divergentes » ne changent pas : la
première vise un événement existant, la seconde naît en confiance 1 et
reste un arbitrage humain.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>
EOF
```

---

### Task 4 : l'index de lieux et sa résolution (pur)

**Files:**
- Create: `genecrew/src/genecrew/deces_event.py`
- Test: `genecrew/tests/test_deces_event.py`

**Interfaces:**
- Consumes: `GrampsClient.get_json` (pagination `/places/`).
- Produces:
  - `normaliser_lieu(nom: str) -> str`
  - `index_lieux(client) -> dict[str, str | None]` — clé = nom normalisé ; valeur = handle, ou `None` quand plusieurs lieux portent ce nom (ambigu).
  - `resoudre_lieu(index: dict[str, str | None], nom: str) -> str | None`
  - Consommés par les Tasks 6 et 7.

- [ ] **Step 1 : écrire les tests qui échouent**

Créer `genecrew/tests/test_deces_event.py` :

```python
"""Tests offline de `apply deaths` — création d'événements décès sourcés."""

import httpx
import pytest
from crewai_custom_tools.tools.genealogy.gramps.client import GrampsClient, GrampsConfig

from genecrew.deces_event import index_lieux, normaliser_lieu, resoudre_lieu

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


def _places_client(places):
    def _h(request):
        if request.url.path == "/api/places/":
            page = int(request.url.params.get("page", 1))
            return httpx.Response(200, json=places if page == 1 else [])
        return httpx.Response(404, json={})
    return _client(_h)


def test_normalisation_ignore_casse_accents_et_separateurs():
    assert normaliser_lieu("Saint-Palais") == normaliser_lieu("SAINT PALAIS")
    assert normaliser_lieu("Nohant-en-Goût") == normaliser_lieu("nohant en gout")


def test_index_rend_le_handle_d_un_lieu_unique():
    client = _places_client([
        {"handle": "P1", "name": {"value": "Bourges"}},
        {"handle": "P2", "name": {"value": "Vierzon"}},
    ])
    index = index_lieux(client)
    assert resoudre_lieu(index, "bourges") == "P1"


def test_lieu_absent_rend_none():
    client = _places_client([{"handle": "P1", "name": {"value": "Bourges"}}])
    index = index_lieux(client)
    assert resoudre_lieu(index, "Saint-Palais") is None


def test_homonymes_rendent_none_plutot_qu_un_choix():
    """Deux lieux du même nom : rattacher au hasard poserait un décès dans la
    mauvaise commune sans que rien ne le signale."""
    client = _places_client([
        {"handle": "P1", "name": {"value": "Saint-Palais"}},
        {"handle": "P2", "name": {"value": "Saint-Palais"}},
    ])
    index = index_lieux(client)
    assert "saint palais" in index          # connu…
    assert resoudre_lieu(index, "Saint-Palais") is None   # …mais pas résolu


def test_lieu_sans_nom_est_ignore():
    client = _places_client([
        {"handle": "P1", "name": {}},
        {"handle": "P2", "name": {"value": "Bourges"}},
    ])
    index = index_lieux(client)
    assert resoudre_lieu(index, "Bourges") == "P2"
```

- [ ] **Step 2 : lancer les tests pour les voir échouer**

```bash
cd /Users/fjacquet/Projects/genecrew
uv run python -m pytest genecrew/tests/test_deces_event.py -q
```

Attendu : ÉCHEC — `ModuleNotFoundError: No module named 'genecrew.deces_event'`.

- [ ] **Step 3 : créer le module avec la résolution de lieux**

Créer `genecrew/src/genecrew/deces_event.py` :

```python
"""`apply deaths` — création d'événements décès sourcés depuis un YAML relu.

La v2 de l'ADR 0011 : là où `apply citations` pose une citation sur un décès qui
existe déjà (`type: source`), cette commande écrit le décès ABSENT de l'arbre
(`type: date`). Elle crée donc une donnée cœur, ce que l'ADR 0011 s'interdisait —
voir l'ADR 0014 pour ce que ça relâche et ce qui l'encadre.

L'écriture elle-même est déléguée à `evenements.creer_evenement_source` ; ce module
tient le filtre, la résolution de lieu, l'orchestration et le rapport.
"""

from __future__ import annotations

import re
import unicodedata

from crewai_custom_tools.tools.genealogy.gramps.client import GrampsClient

TAG_DECES = "genecrew:deces"


def normaliser_lieu(nom: str) -> str:
    """Nom de commune → clé de comparaison : sans accents, minuscule, séparateurs unifiés.

    « Nohant-en-Goût », « nohant en gout » et « NOHANT-EN-GOUT » désignent la même
    commune ; l'INSEE et l'arbre ne les écrivent pas pareil.
    """
    sans_accents = "".join(
        c for c in unicodedata.normalize("NFD", nom or "")
        if unicodedata.category(c) != "Mn")
    return re.sub(r"[\s\-']+", " ", sans_accents).strip().lower()


def index_lieux(client: GrampsClient) -> dict[str, str | None]:
    """Index `{nom normalisé -> handle}` des lieux de l'arbre ; `None` si homonymes.

    Le `None` est porteur d'information : il distingue l'AMBIGU (clé présente, valeur
    None) de l'INCONNU (clé absente). Les deux mènent au même geste — un événement sans
    lieu — mais pas au même diagnostic dans le rapport.
    """
    index: dict[str, str | None] = {}
    page = 1
    while True:
        batch = client.get_json("/places/", params={"page": page, "pagesize": 200})
        if not batch:
            break
        for place in batch:
            if not isinstance(place, dict):
                continue
            cle = normaliser_lieu((place.get("name") or {}).get("value", ""))
            if not cle:
                continue
            # Deuxième occurrence (ou plus) du même nom : on écrase par None. Choisir
            # au hasard rattacherait un décès à la mauvaise commune, en silence.
            index[cle] = None if cle in index else place.get("handle")
        page += 1
    return index


def resoudre_lieu(index: dict[str, str | None], nom: str) -> str | None:
    """Handle du lieu nommé, ou None s'il est inconnu ou ambigu. Pur."""
    return index.get(normaliser_lieu(nom))
```

- [ ] **Step 4 : lancer les tests pour les voir passer**

```bash
cd /Users/fjacquet/Projects/genecrew
uv run python -m pytest genecrew/tests/test_deces_event.py -q
```

Attendu : PASS, 5 tests.

- [ ] **Step 5 : commiter**

```bash
cd /Users/fjacquet/Projects/genecrew
uv run ruff check . && \
git add genecrew/src/genecrew/deces_event.py genecrew/tests/test_deces_event.py && \
git commit -F - <<'EOF'
feat(deces): résolution de lieu par nom pour apply deaths

Index {nom normalisé -> handle} des lieux de l'arbre. Un nom porté par
plusieurs lieux rend None plutôt qu'un choix : rattacher un décès à la
mauvaise commune homonyme est une faute silencieuse, un événement sans
lieu est une lacune visible.

Aucun lieu n'est créé — c'est le métier de `apply places`, qui a son
propre cycle de relecture.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>
EOF
```

---

### Task 5 : le filtre à quatre conditions (pur)

**Files:**
- Modify: `genecrew/src/genecrew/deces_event.py`
- Test: `genecrew/tests/test_deces_event.py`

**Interfaces:**
- Consumes: `PropositionAudit` (Tasks 1 et 3).
- Produces: `trier_propositions(propositions: list[PropositionAudit]) -> tuple[list[PropositionAudit], dict[str, int]]` — les propositions retenues, et le décompte des motifs de rejet sous les clés `hors_perimetre` et `sans_donnee`. La condition « décès déjà présent » n'est PAS ici : elle exige de lire l'arbre, et vit dans la Task 7.

- [ ] **Step 1 : écrire les tests qui échouent**

Ajouter à `genecrew/tests/test_deces_event.py` :

```python
from genecrew.deces_event import trier_propositions


def _prop(**kw):
    base = {
        "type": "date", "gramps_id": "I0174", "handle": "H174",
        "personne": "Alain Rolland", "cible": "décès de I0174 (absent de l'arbre)",
        "action": "Renseigner le décès : 2021-12-23 à Saint-Palais.",
        "preuve_url": "https://deces.matchid.io/id/X",
        "preuve_detail": "Fichier des décès INSEE : 2021-12-23 à Saint-Palais "
                         "(score 1.000).",
        "priorite": "moyenne", "confiance": 2,
        "date_iso": "2021-12-23", "lieu_nom": "Saint-Palais",
    }
    base.update(kw)
    from crewai_custom_tools.tools.genealogy.models.domain import PropositionAudit
    return PropositionAudit(**base)


def test_retient_une_proposition_date_confiance_2_datee():
    retenues, motifs = trier_propositions([_prop()])
    assert len(retenues) == 1
    assert motifs == {"hors_perimetre": 0, "sans_donnee": 0}


def test_ecarte_le_type_source():
    """`type: source` est le métier de `apply citations`, pas de `apply deaths`."""
    retenues, motifs = trier_propositions([_prop(type="source")])
    assert retenues == []
    assert motifs["hors_perimetre"] == 1


def test_ecarte_la_confiance_1():
    """Confiance 1 = date de naissance non concordante : homonyme possible."""
    retenues, motifs = trier_propositions([_prop(confiance=1)])
    assert retenues == []
    assert motifs["hors_perimetre"] == 1


def test_ecarte_un_yaml_sans_champs_structures():
    """Un lot produit avant les champs structurés ne doit pas se lire comme un lot vide."""
    retenues, motifs = trier_propositions([_prop(date_iso="", lieu_nom="")])
    assert retenues == []
    assert motifs["sans_donnee"] == 1
    assert motifs["hors_perimetre"] == 0


def test_ecarte_une_date_incomplete():
    retenues, motifs = trier_propositions([_prop(date_iso="2021")])
    assert retenues == []
    assert motifs["sans_donnee"] == 1
```

- [ ] **Step 2 : lancer les tests pour les voir échouer**

```bash
cd /Users/fjacquet/Projects/genecrew
uv run python -m pytest genecrew/tests/test_deces_event.py -q -k "retient or ecarte"
```

Attendu : ÉCHEC — `ImportError: cannot import name 'trier_propositions'`.

- [ ] **Step 3 : implémenter le filtre**

Ajouter à `genecrew/src/genecrew/deces_event.py` (après `resoudre_lieu`) :

```python
def trier_propositions(propositions: list) -> tuple[list, dict[str, int]]:
    """Sépare les propositions applicables du reste. Pur.

    Trois des quatre conditions de l'ADR 0014 se jugent sur la proposition seule :
    `type: date`, `confiance == 2`, et une date ISO complète. La quatrième — « la
    personne n'a toujours pas de décès » — exige de lire l'arbre au moment de
    l'écriture, et vit dans `run_deces_event`.

    Les deux motifs de rejet sont comptés SÉPARÉMENT : « hors périmètre » est un
    non-sujet (c'est le travail d'`apply citations`), « sans donnée » est un signal
    — un YAML trop ancien, à régénérer. Les confondre ferait lire un lot périmé
    comme un lot vide.
    """
    retenues, motifs = [], {"hors_perimetre": 0, "sans_donnee": 0}
    for prop in propositions:
        if prop.type != "date" or prop.confiance != 2:
            motifs["hors_perimetre"] += 1
            continue
        if dateval_iso(prop.date_iso) is None:
            motifs["sans_donnee"] += 1
            continue
        retenues.append(prop)
    return retenues, motifs
```

Compléter l'import en tête du module :

```python
from genecrew.evenements import creer_evenement_source, dateval_iso
```

- [ ] **Step 4 : lancer les tests pour les voir passer**

```bash
cd /Users/fjacquet/Projects/genecrew
uv run python -m pytest genecrew/tests/test_deces_event.py -q
```

Attendu : PASS, 10 tests.

- [ ] **Step 5 : commiter**

```bash
cd /Users/fjacquet/Projects/genecrew
uv run ruff check . && \
git add genecrew/src/genecrew/deces_event.py genecrew/tests/test_deces_event.py && \
git commit -F - <<'EOF'
feat(deces): filtre des propositions applicables par apply deaths

type: date + confiance 2 + date ISO complète. Les deux motifs de rejet
sont comptés séparément : « hors périmètre » est le travail d'apply
citations, « sans donnée » signale un YAML antérieur aux champs
structurés — les confondre ferait lire un lot périmé comme un lot vide.

La quatrième condition (décès déjà présent) exige de lire l'arbre et
vient avec l'orchestration.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>
EOF
```

---

### Task 6 : le rapport (pur)

**Files:**
- Modify: `genecrew/src/genecrew/deces_event.py`
- Test: `genecrew/tests/test_deces_event.py`

**Interfaces:**
- Produces: `render_deaths_report(date: str, crees: list, refuses: list, lieux_non_resolus: list, motifs: dict, errors: list, dry_run: bool) -> str`, où `crees` est une liste de tuples `(gramps_id, personne, event_gramps_id_ou_handle, lieu_ou_vide)`, `refuses` une liste de `(gramps_id, motif)`, `lieux_non_resolus` une liste de `(gramps_id, nom_commune)`, et `errors` une liste de `(gramps_id, message)`. Consommé par la Task 7.

- [ ] **Step 1 : écrire les tests qui échouent**

Ajouter à `genecrew/tests/test_deces_event.py` :

```python
from genecrew.deces_event import render_deaths_report


def test_rapport_annonce_le_mode_effectif():
    md = render_deaths_report("2026-07-21", [], [], [], {"hors_perimetre": 0,
                              "sans_donnee": 0}, [], dry_run=True)
    assert "simulation" in md
    assert "écritures appliquées" not in md


def test_rapport_liste_les_evenements_crees():
    md = render_deaths_report(
        "2026-07-21",
        [("I0174", "Alain Rolland", "E9001", "Saint-Palais")],
        [], [], {"hors_perimetre": 0, "sans_donnee": 0}, [], dry_run=False)
    assert "I0174 Alain Rolland" in md
    assert "E9001" in md
    assert "Saint-Palais" in md
    assert "Décès créés : 1" in md


def test_rapport_distingue_les_deux_motifs_de_rejet():
    md = render_deaths_report("2026-07-21", [], [], [],
                              {"hors_perimetre": 8, "sans_donnee": 3}, [], dry_run=False)
    assert "Hors périmètre" in md and "8" in md
    assert "sans donnée machine" in md.lower() and "3" in md


def test_rapport_signale_les_lieux_non_resolus():
    md = render_deaths_report("2026-07-21", [], [], [("I0186", "Nohant-en-Goût")],
                              {"hors_perimetre": 0, "sans_donnee": 0}, [], dry_run=False)
    assert "Lieux non résolus" in md
    assert "Nohant-en-Goût" in md


def test_rapport_porte_le_handle_de_l_orphelin():
    """Un événement non rattaché doit être retrouvable : son handle en clair."""
    md = render_deaths_report(
        "2026-07-21", [], [], [], {"hors_perimetre": 0, "sans_donnee": 0},
        [("I0174", "Death créé mais NON rattaché (orphelin EV_ORPH) : timeout")],
        dry_run=False)
    assert "EV_ORPH" in md
```

- [ ] **Step 2 : lancer les tests pour les voir échouer**

```bash
cd /Users/fjacquet/Projects/genecrew
uv run python -m pytest genecrew/tests/test_deces_event.py -q -k rapport
```

Attendu : ÉCHEC — `ImportError: cannot import name 'render_deaths_report'`.

- [ ] **Step 3 : implémenter le rapport**

Ajouter à `genecrew/src/genecrew/deces_event.py` :

```python
def render_deaths_report(date: str, crees: list, refuses: list, lieux_non_resolus: list,
                         motifs: dict, errors: list, dry_run: bool) -> str:
    """Rapport Markdown d'un passage de `apply deaths`. Pur.

    `Mode:` reflète le dry-run EFFECTIF (variable d'environnement comprise) : le
    rapport ne doit jamais annoncer une écriture qui n'a pas eu lieu.
    """
    mode = "simulation (dry-run, aucune écriture)" if dry_run else "écritures appliquées"
    lines = [f"# Création d'événements décès sourcés — {date}", "",
             f"Mode : {mode}.", "",
             f"- Décès créés : {len(crees)}",
             f"- Refusés (décès déjà présent dans l'arbre) : {len(refuses)}",
             f"- Sans donnée machine exploitable (YAML antérieur) : {motifs['sans_donnee']}",
             f"- Hors périmètre (type ≠ date ou confiance < 2) : {motifs['hors_perimetre']}",
             f"- Erreurs : {len(errors)}", ""]
    if crees:
        lines += ["| Personne | Événement | Lieu |", "|---|---|---|"]
        lines += [f"| {gid} {nom} | {ev} | {lieu or '—'} |"
                  for gid, nom, ev, lieu in crees]
        lines.append("")
    if lieux_non_resolus:
        lines += ["## Lieux non résolus", "",
                  "Événement créé sans lieu : la commune est inconnue de l'arbre, ou "
                  "plusieurs lieux portent ce nom. À traiter avec `apply places`.", ""]
        lines += [f"- {gid} : {nom}" for gid, nom in lieux_non_resolus]
        lines.append("")
    if refuses:
        lines += ["## Refusés", ""]
        lines += [f"- {gid} : {motif}" for gid, motif in refuses]
        lines.append("")
    if errors:
        lines += ["## Erreurs", ""]
        lines += [f"- {gid} : {msg}" for gid, msg in errors]
        lines.append("")
    return "\n".join(lines)
```

- [ ] **Step 4 : lancer les tests pour les voir passer**

```bash
cd /Users/fjacquet/Projects/genecrew
uv run python -m pytest genecrew/tests/test_deces_event.py -q
```

Attendu : PASS, 15 tests.

- [ ] **Step 5 : commiter**

```bash
cd /Users/fjacquet/Projects/genecrew
uv run ruff check . && \
git add genecrew/src/genecrew/deces_event.py genecrew/tests/test_deces_event.py && \
git commit -F - <<'EOF'
feat(deces): rapport de apply deaths

Compteurs séparés pour les deux motifs de rejet, section « Lieux non
résolus » qui renvoie vers apply places, et handle des orphelins en clair
sous Erreurs. La ligne Mode reflète le dry-run effectif, variable
d'environnement comprise.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>
EOF
```

---

### Task 7 : l'orchestration `run_deces_event`

**Files:**
- Modify: `genecrew/src/genecrew/deces_event.py`
- Test: `genecrew/tests/test_deces_event.py`

**Interfaces:**
- Consumes: `trier_propositions`, `index_lieux`, `resoudre_lieu`, `render_deaths_report` (Tasks 4-6) ; `creer_evenement_source`, `dateval_iso` (Task 2) ; `citation_page`, `source_title_for` de `genecrew.deces_apply` ; `GrampsEnsureSourceTool`, `GrampsCreateCitationTool`, `GrampsCreateNoteTool`, `GrampsEnsureTagTool`, `GrampsAttachTool`, `effective_dry_run` de la bibliothèque ; `PropositionsLot` de `genecrew.propositions`.
- Produces: `run_deces_event(client, propositions_yaml: Path, output_dir, *, date: str, dry_run: bool = False) -> Path` — écrit le rapport et rend son chemin. Consommé par la Task 8.

- [ ] **Step 1 : écrire les tests qui échouent**

Ajouter à `genecrew/tests/test_deces_event.py` :

```python
import json

import yaml

from genecrew import deces_event
from genecrew.deces_event import run_deces_event


def _yaml_lot(tmp_path, props):
    p = tmp_path / "props.yaml"
    p.write_text(yaml.safe_dump({"propositions": props}, allow_unicode=True),
                 encoding="utf-8")
    return p


PROP_DATE = {
    "type": "date", "gramps_id": "I0174", "handle": "H174",
    "personne": "Alain Rolland", "cible": "décès de I0174 (absent de l'arbre)",
    "action": "Renseigner le décès : 2021-12-23 à Saint-Palais.",
    "preuve_url": "https://deces.matchid.io/id/X",
    "preuve_detail": "Fichier des décès INSEE : 2021-12-23 à Saint-Palais "
                     "(score 1.000).",
    "priorite": "moyenne", "confiance": 2,
    "date_iso": "2021-12-23", "lieu_nom": "Saint-Palais",
}

SANS_DECES = {"handle": "H174", "gramps_id": "I0174", "death_ref_index": -1,
              "event_ref_list": [{"ref": "EV_B"}]}
AVEC_DECES = {"handle": "H174", "gramps_id": "I0174", "death_ref_index": 1,
              "event_ref_list": [{"ref": "EV_B"}, {"ref": "EV_D"}]}
PLACES = [{"handle": "P1", "name": {"value": "Saint-Palais"}}]


def _arbre(person, places=PLACES):
    def _h(request):
        path = request.url.path
        if path == "/api/places/":
            page = int(request.url.params.get("page", 1))
            return httpx.Response(200, json=places if page == 1 else [])
        if path == "/api/sources/":
            page = int(request.url.params.get("page", 1))
            return httpx.Response(200, json=[] if page > 1 else [])
        if path == "/api/tags/":
            return httpx.Response(200, json=[])
        if path.startswith("/api/people/"):
            return httpx.Response(200, json=person)
        return httpx.Response(200, json={})
    return _client(_h)


def _stub_ecritures(monkeypatch, *, evenement=None):
    """Neutralise les outils d'écriture : on teste l'orchestration, pas l'API."""
    vus = {"evenement": None, "attach": None}

    def _fake_creer(person_handle, **kw):
        vus["evenement"] = {"person_handle": person_handle, **kw}
        return evenement or {"posee": True, "event_handle": "EV_NEW",
                             "attache": True, "raison": "Death créé"}

    class _Ok:
        def __init__(self, key):
            self.key = key

        def _run(self, **kw):
            if self.key == "attach":
                vus["attach"] = kw
            return json.dumps({"success": True, "data": {"handle": f"{self.key}1"}})

    monkeypatch.setattr(deces_event, "creer_evenement_source", _fake_creer)
    monkeypatch.setattr(deces_event, "GrampsEnsureSourceTool", lambda: _Ok("src"))
    monkeypatch.setattr(deces_event, "GrampsCreateCitationTool", lambda: _Ok("cit"))
    monkeypatch.setattr(deces_event, "GrampsCreateNoteTool", lambda: _Ok("note"))
    monkeypatch.setattr(deces_event, "GrampsEnsureTagTool", lambda: _Ok("tag"))
    monkeypatch.setattr(deces_event, "GrampsAttachTool", lambda: _Ok("attach"))
    return vus


def test_cree_le_deces_absent(tmp_path, monkeypatch):
    vus = _stub_ecritures(monkeypatch)
    chemin = run_deces_event(_arbre(SANS_DECES), _yaml_lot(tmp_path, [PROP_DATE]),
                             tmp_path, date="2026-07-21")
    md = chemin.read_text(encoding="utf-8")
    assert "Décès créés : 1" in md
    assert vus["evenement"]["event_type"] == "Death"
    assert vus["evenement"]["dateval"] == [23, 12, 2021]
    assert vus["evenement"]["place_handle"] == "P1"


def test_refuse_une_personne_deja_decedee(tmp_path, monkeypatch):
    """L'outil protège le pointeur death_ref_index, pas la liste : sans cette garde
    on créerait un SECOND événement décès, invisible mais bien présent."""
    vus = _stub_ecritures(monkeypatch)
    chemin = run_deces_event(_arbre(AVEC_DECES), _yaml_lot(tmp_path, [PROP_DATE]),
                             tmp_path, date="2026-07-21")
    md = chemin.read_text(encoding="utf-8")
    assert "Décès créés : 0" in md
    assert "Refusés (décès déjà présent dans l'arbre) : 1" in md
    assert vus["evenement"] is None


def test_lieu_inconnu_donne_un_evenement_sans_lieu(tmp_path, monkeypatch):
    vus = _stub_ecritures(monkeypatch)
    chemin = run_deces_event(_arbre(SANS_DECES, places=[]),
                             _yaml_lot(tmp_path, [PROP_DATE]), tmp_path,
                             date="2026-07-21")
    md = chemin.read_text(encoding="utf-8")
    assert "Décès créés : 1" in md
    assert vus["evenement"]["place_handle"] is None
    assert "Lieux non résolus" in md
    assert "Saint-Palais" in md


def test_orphelin_rapporte_avec_son_handle(tmp_path, monkeypatch):
    _stub_ecritures(monkeypatch, evenement={
        "posee": True, "event_handle": "EV_ORPH", "attache": False,
        "raison": "Death créé mais NON rattaché (orphelin EV_ORPH) : timeout"})
    chemin = run_deces_event(_arbre(SANS_DECES), _yaml_lot(tmp_path, [PROP_DATE]),
                             tmp_path, date="2026-07-21")
    assert "EV_ORPH" in chemin.read_text(encoding="utf-8")


def test_note_et_tag_poses_sur_la_personne(tmp_path, monkeypatch):
    vus = _stub_ecritures(monkeypatch)
    run_deces_event(_arbre(SANS_DECES), _yaml_lot(tmp_path, [PROP_DATE]), tmp_path,
                    date="2026-07-21")
    assert vus["attach"]["handle"] == "H174"
    assert vus["attach"]["note_handle"] == "note1"
    assert vus["attach"]["tag_handle"] == "tag1"


def test_dry_run_effectif_annonce_la_simulation(tmp_path, monkeypatch):
    _stub_ecritures(monkeypatch)
    chemin = run_deces_event(_arbre(SANS_DECES), _yaml_lot(tmp_path, [PROP_DATE]),
                             tmp_path, date="2026-07-21", dry_run=True)
    assert "simulation" in chemin.read_text(encoding="utf-8")
```

- [ ] **Step 2 : lancer les tests pour les voir échouer**

```bash
cd /Users/fjacquet/Projects/genecrew
uv run python -m pytest genecrew/tests/test_deces_event.py -q -k "cree_le or refuse_une or lieu_inconnu or orphelin_rapporte or note_et_tag or dry_run_effectif"
```

Attendu : ÉCHEC — `ImportError: cannot import name 'run_deces_event'`.

- [ ] **Step 3 : implémenter l'orchestration**

Compléter les imports en tête de `genecrew/src/genecrew/deces_event.py` :

```python
import json
from pathlib import Path

import yaml

from crewai_custom_tools.tools.genealogy.gramps.write_tools import (
    GrampsAttachTool,
    GrampsCreateCitationTool,
    GrampsCreateNoteTool,
    GrampsEnsureSourceTool,
    GrampsEnsureTagTool,
    effective_dry_run,
)

from genecrew.deces_apply import citation_page, source_title_for
from genecrew.propositions import PropositionsLot
```

Puis ajouter en fin de module :

```python
def _a_un_deces(person: dict) -> bool:
    """La personne porte-t-elle déjà un décès ? (garde d'invariant d'`apply deaths`)

    `GrampsCreateEventTool` refuse d'ÉCRASER un `death_ref_index` existant, mais il
    créerait quand même un second événement Death et l'ajouterait à la liste —
    invisible dans les vues qui suivent l'index, bien présent dans la base. La garde
    doit donc être ici, en plus.
    """
    return person.get("death_ref_index", -1) >= 0


def run_deces_event(client: GrampsClient, propositions_yaml, output_dir, *,
                    date: str, dry_run: bool = False) -> Path:
    """Applique les propositions `type: date` d'un YAML relu : crée les décès absents."""
    dry_run = effective_dry_run(dry_run)
    data = yaml.safe_load(Path(propositions_yaml).read_text(encoding="utf-8")) or {}
    lot = PropositionsLot(**data)                   # validation stricte du YAML relu
    retenues, motifs = trier_propositions(lot.propositions)

    index = index_lieux(client) if retenues else {}
    source_handles: dict[str, str] = {}             # titre -> handle (une source/registre)

    def _ensure_source(title: str, author: str) -> str:
        if title not in source_handles:
            payload = json.loads(GrampsEnsureSourceTool()._run(
                title=title, author=author, dry_run=dry_run))
            if not payload["success"]:
                raise RuntimeError(f"source '{title}' : {payload['error']}")
            source_handles[title] = payload["data"]["handle"]
        return source_handles[title]

    crees, refuses, lieux_non_resolus, errors = [], [], [], []
    for prop in retenues:
        try:
            person = client.get_object("people", prop.handle)
        except Exception:
            errors.append((prop.gramps_id, "personne introuvable"))
            continue
        if _a_un_deces(person):
            refuses.append((prop.gramps_id,
                            "un décès existe déjà dans l'arbre (lot périmé ?)"))
            continue

        title, author = source_title_for(prop.preuve_detail)
        source_handle = _ensure_source(title, author)
        citation = json.loads(GrampsCreateCitationTool()._run(
            source_handle=source_handle,
            page=citation_page(prop.preuve_detail, prop.preuve_url),
            dry_run=dry_run))
        if not citation["success"]:
            errors.append((prop.gramps_id, f"citation : {citation['error']}"))
            continue

        lieu_handle = resoudre_lieu(index, prop.lieu_nom) if prop.lieu_nom else None
        if prop.lieu_nom and lieu_handle is None:
            lieux_non_resolus.append((prop.gramps_id, prop.lieu_nom))

        evt = creer_evenement_source(
            prop.handle, event_type="Death", dateval=dateval_iso(prop.date_iso),
            place_handle=lieu_handle, citation_handle=citation["data"]["handle"],
            dry_run=dry_run)
        if not evt["posee"]:
            errors.append((prop.gramps_id, evt["raison"]))
            continue
        if not evt["attache"]:
            # L'événement EXISTE : on le dit en erreur (avec le handle de l'orphelin)
            # et NON en créé, pour ne pas annoncer un décès que l'arbre ne montre pas.
            errors.append((prop.gramps_id, evt["raison"]))
            continue

        # L'écriture irréversible est faite. Note et tag sont des annotations : leur
        # échec ne remet pas l'événement en cause, il se rapporte.
        note = json.loads(GrampsCreateNoteTool()._run(
            text=f"[genecrew:deces:{date}] {prop.action} — {prop.preuve_url}",
            note_type="Research", dry_run=dry_run))
        tag = json.loads(GrampsEnsureTagTool()._run(name=TAG_DECES, dry_run=dry_run))
        if note["success"] and tag["success"]:
            attache = json.loads(GrampsAttachTool()._run(
                handle=prop.handle, note_handle=note["data"]["handle"],
                tag_handle=tag["data"]["handle"], dry_run=dry_run))
            if not attache["success"]:
                errors.append((prop.gramps_id,
                               f"décès {evt['event_handle']} créé, "
                               f"annotation refusée : {attache['error']}"))
        else:
            refus = note.get("error") or tag.get("error")
            errors.append((prop.gramps_id,
                           f"décès {evt['event_handle']} créé, "
                           f"note/tag refusé : {refus}"))

        crees.append((prop.gramps_id, prop.personne, evt["event_handle"],
                      prop.lieu_nom if lieu_handle else ""))

    report = render_deaths_report(date, crees, refuses, lieux_non_resolus, motifs,
                                  errors, dry_run)
    out = Path(output_dir) / "deces"
    out.mkdir(parents=True, exist_ok=True)
    report_path = out / f"{date}_apply_deaths_{Path(propositions_yaml).stem}.md"
    report_path.write_text(report, encoding="utf-8")
    return report_path
```

- [ ] **Step 4 : lancer les tests pour les voir passer**

```bash
cd /Users/fjacquet/Projects/genecrew
uv run python -m pytest genecrew/tests/test_deces_event.py -q
```

Attendu : PASS, 21 tests.

- [ ] **Step 5 : commiter**

```bash
cd /Users/fjacquet/Projects/genecrew
uv run ruff check . && \
git add genecrew/src/genecrew/deces_event.py genecrew/tests/test_deces_event.py && \
git commit -F - <<'EOF'
feat(deces): orchestration de apply deaths

Source, citation, résolution de lieu, création de l'événement rattaché,
puis note et tag sur la personne. La garde « décès déjà présent » est
vérifiée au moment de l'écriture, pas seulement à la proposition :
l'outil bibliothèque protège le pointeur death_ref_index mais pas la
liste, et un lot périmé créerait un second événement décès.

Un événement non rattaché est rapporté en erreur avec son handle, jamais
en créé : annoncer un décès que l'arbre ne montre pas serait pire que
l'échec lui-même.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>
EOF
```

---

### Task 8 : la surface CLI

**Files:**
- Modify: `genecrew/src/genecrew/cli.py` (après le bloc `apply citations`, vers la ligne 126)
- Modify: `genecrew/src/genecrew/main.py` (nouveau `deces_event_cmd`, et la table `dispatch` vers la ligne 445)
- Test: `genecrew/tests/test_cli_parser.py`, `genecrew/tests/test_cli_dispatch.py`

**Interfaces:**
- Consumes: `run_deces_event` (Task 7).
- Produces: la feuille `apply deaths` (avec `--yaml`, `--dry-run`, `--date`), routée vers `main.deces_event_cmd`.

- [ ] **Step 1 : écrire les tests qui échouent**

Dans `genecrew/tests/test_cli_parser.py`, ajouter à la liste `LEAVES`, après la ligne `apply citations` :

```python
    (["apply", "deaths", "--yaml", "relu.yaml"], "apply", "deaths"),
```

Mettre à jour le commentaire au-dessus de la liste : « les 16 feuilles de la grammaire ».

Dans `genecrew/tests/test_cli_dispatch.py`, ajouter à la liste `ROUTES`, après la ligne `apply citations` :

```python
    (["apply", "deaths", "--yaml", "relu.yaml"], "deces_event_cmd"),
```

- [ ] **Step 2 : lancer les tests pour les voir échouer**

```bash
cd /Users/fjacquet/Projects/genecrew
uv run python -m pytest genecrew/tests/test_cli_parser.py genecrew/tests/test_cli_dispatch.py -q
```

Attendu : ÉCHEC — `SystemExit: 2` (`invalid choice: 'deaths'`).

- [ ] **Step 3 : déclarer la feuille dans `cli.py`**

Dans `build_parser()`, juste après le bloc `apply citations` (qui se termine par `_add_date(p)` avant le bloc `all`), insérer :

```python
    p = apply_sub.add_parser(
        "deaths",
        help="Crée les décès ABSENTS de l'arbre depuis un YAML relu (type: date, "
             "confiance 2) — écrit une donnée cœur, ADR 0014")
    _add_yaml(p)
    _add_dry_run(p)
    _add_date(p)
```

- [ ] **Step 4 : ajouter la commande et la route dans `main.py`**

Ajouter la fonction, juste après `deces_apply_cmd` :

```python
def deces_event_cmd(args) -> None:
    """Create the missing death events from a reviewed YAML; print the report path."""
    from pathlib import Path

    from crewai_custom_tools.tools.genealogy.gramps.client import get_client

    from genecrew.deces_event import run_deces_event

    client = get_client()
    output_dir = Path(os.environ.get("GENECREW_OUTPUT_DIR", "output"))
    date = args.date or __import__("datetime").date.today().isoformat()
    report = run_deces_event(client, Path(args.yaml), output_dir,
                             date=date, dry_run=args.dry_run)
    print(f"Rapport : {report}")
```

Puis, dans la table `dispatch`, juste après la ligne `("apply", "citations")` :

```python
        # `citations` pose une source sur un événement EXISTANT ; `deaths` CRÉE
        # l'événement absent. Deux commandes, un même YAML, des propositions
        # disjointes (`type: source` / `type: date`) — ADR 0014.
        ("apply", "deaths"): lambda: deces_event_cmd(args),
```

- [ ] **Step 5 : lancer les tests pour les voir passer**

```bash
cd /Users/fjacquet/Projects/genecrew
uv run python -m pytest genecrew/tests/ -q && uv run ruff check .
```

Attendu : suite complète au vert.

- [ ] **Step 6 : vérifier l'aide de la commande à la main**

```bash
cd /Users/fjacquet/Projects/genecrew
uv run genecrew apply deaths --help
```

Attendu : l'aide affiche `--yaml` (requis), `--dry-run` et `--date`.

- [ ] **Step 7 : commiter**

```bash
cd /Users/fjacquet/Projects/genecrew
git add genecrew/src/genecrew/cli.py genecrew/src/genecrew/main.py \
        genecrew/tests/test_cli_parser.py genecrew/tests/test_cli_dispatch.py && \
git commit -F - <<'EOF'
feat(cli): cible apply deaths

Une feuille de plus sous un verbe existant, la grammaire à sept verbes ne
bouge pas (ADR 0012). `apply citations` garde son sens strict — poser une
source sur un objet existant — et `apply deaths` crée l'événement absent :
deux commandes lisent le même YAML et y prennent des propositions
disjointes.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>
EOF
```

---

### Task 9 : ADR 0014 et documentation

**Files:**
- Create: `docs/adr/0014-creation-evenements-deces.md`
- Modify: `CLAUDE.md` (sections « CrewAI project structure », « Where the genealogy code lives », « Commands », « Gotchas »)
- Modify: `docs/USER_GUIDE.md`

**Interfaces:**
- Consumes: le comportement livré aux Tasks 2-8.
- Produces: la documentation de référence. Rien ne dépend de cette tâche.

- [ ] **Step 1 : écrire l'ADR**

Créer `docs/adr/0014-creation-evenements-deces.md`, au format des ADR existants (relire `0011-citations-insee-deces-apply.md` pour le ton et la longueur) :

```markdown
# ADR 0014 — Création d'événements décès sourcés (`apply deaths`)

Date : 2026-07-21 — Statut : accepté

## Contexte

L'ADR 0011 a ouvert l'écriture des citations sur les décès **existants** (`type:
source`) et renvoyé explicitement à une v2 les propositions `type: date` — les décès
qu'une source officielle atteste mais que l'arbre ignore. Sur le lot du 2026-07-21 :
2 citations posées, 8 décès laissés à la ressaisie manuelle.

`GrampsCreateEventTool` existe déjà dans `crewai_custom_tools` et tourne en production
via `import releve` : il crée l'événement, le rattache à la personne, et ne pose le
`death_ref_index` que si la personne n'en avait pas.

## Décision

`genecrew apply deaths --yaml <yaml relu>` crée l'événement décès pour les propositions
**`type: date`, confiance 2, date ISO complète**, sur une personne **sans décès**. La
chaîne : source du registre (idempotente) → citation (référence d'archive rejouable) →
événement `Death` daté et situé, rattaché → note `[genecrew:deces:<date>]` et tag
`genecrew:deces` sur la personne.

C'est le troisième assouplissement de l'ADR 0008 (après 0009 genre, 0010 lieux), et le
premier qui **crée** une donnée cœur au lieu d'en corriger une. Garanti dans le code :

- **jamais auto** : la commande consomme un YAML explicitement passé, relu ;
- **dry-run par défaut** (`effective_dry_run`) ;
- **confiance 2 seulement** : date de naissance concordante au jour près, le seul
  discriminateur d'homonymie accepté par le projet ;
- **garde décès-absent**, vérifiée au moment de l'écriture — l'outil protège le
  pointeur `death_ref_index`, pas la liste : sans cette garde, un lot périmé créerait
  un **second** événement décès, invisible dans les vues, bien présent en base ;
- **aucun lieu créé** : un lieu inconnu ou homonyme fait poser l'événement sans lieu,
  signalé au rapport et renvoyé à `apply places` ;
- un événement créé mais non rattaché est rapporté **en erreur avec son handle**,
  jamais en succès.

`apply citations` ne change pas : les deux commandes lisent le même YAML et y prennent
des propositions disjointes.

## Conséquences

Les décès attestés par l'INSEE et par Mémoire des hommes entrent dans l'arbre sans
ressaisie, sourcés dès leur création. Le tag `genecrew:deces` permet de relire ou
d'annuler un lot en masse ; la suppression de l'événement suffit à revenir en arrière.

Contrepartie assumée : note et tag portent sur la **personne**, pas sur l'événement —
`GrampsAttachTool` n'écrit que sur `/people/`. Marquer l'événement lui-même demanderait
d'élargir cet outil à un `object_type`, remis au jour où le besoin se posera.
```

- [ ] **Step 2 : mettre `CLAUDE.md` à jour**

Quatre retouches, chacune sur une ligne ou deux :

1. dans la description de `cli.py`, remplacer `apply {case|gender|places|citations|all}` par `apply {case|gender|places|citations|deaths|all}` ;
2. dans « Where the genealogy code lives », ajouter `evenements.py` (brique partagée de création d'événement) et `deces_event.py` (orchestration d'`apply deaths`) à la liste des modules genecrew ;
3. dans « Commands », ajouter sous la ligne `apply places` :

```bash
uv run genecrew apply deaths --yaml <relu.yaml> --dry-run  # crée les décès absents (ADR 0014)
```

4. dans « Gotchas », sous le point « Form vs fact », ajouter :

```markdown
- **Créer un décès** : `apply deaths` (ADR 0014) écrit une donnée cœur, contrairement à
  `apply citations` qui reste append-only. La garde « la personne n'a pas de décès » est
  vérifiée **au moment de l'écriture** : `GrampsCreateEventTool` refuse d'écraser un
  `death_ref_index` existant, mais créerait quand même un second événement `Death` dans
  la liste — invisible dans les vues qui suivent l'index, bien présent en base.
```

- [ ] **Step 3 : mettre `docs/USER_GUIDE.md` à jour**

Ajouter, à la suite de la section qui décrit `apply citations`, un paragraphe décrivant le cycle complet du chantier décès :

```markdown
### Créer les décès absents de l'arbre

`propose deaths` produit deux familles de propositions : `source` (le décès est dans
l'arbre, il lui manque une source) et `date` (le décès est absent). Après relecture du
YAML :

```bash
uv run genecrew apply citations --yaml <relu.yaml>   # les `source`
uv run genecrew apply deaths --yaml <relu.yaml>      # les `date`
```

Les deux commandes lisent le même fichier et y prennent des propositions disjointes ;
l'ordre n'a pas d'importance. `apply deaths` simule par défaut — poser
`GENECREW_DRY_RUN=false` dans `.env` pour écrire réellement.

Un décès créé porte le tag `genecrew:deces` sur la personne : c'est le filtre à utiliser
dans Gramps Web pour relire ou annuler un lot.
```

- [ ] **Step 4 : vérifier la cohérence documentaire**

```bash
cd /Users/fjacquet/Projects/genecrew
grep -n "apply deaths" CLAUDE.md docs/USER_GUIDE.md docs/adr/0014-creation-evenements-deces.md | head
uv run python -m pytest genecrew/tests/ -q && uv run ruff check .
```

Attendu : les trois fichiers mentionnent la commande ; suite au vert.

- [ ] **Step 5 : commiter**

```bash
cd /Users/fjacquet/Projects/genecrew
git add docs/adr/0014-creation-evenements-deces.md CLAUDE.md docs/USER_GUIDE.md && \
git commit -F - <<'EOF'
docs(adr): ADR 0014 — création d'événements décès sourcés

Referme le « hors périmètre v2 » laissé ouvert par l'ADR 0011. Troisième
assouplissement de l'ADR 0008, et le premier qui CRÉE une donnée cœur au
lieu d'en corriger une.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>
EOF
```

---

### PORTE HUMAINE 2 : validation sur l'arbre réel

**Aucun agent n'exécute cette étape.**

Le premier passage réel se fait sur **une seule proposition**, pas sur le lot de 8 :

```bash
cd /Users/fjacquet/Projects/genecrew
# 1. en simulation d'abord, sur le lot complet — lire le rapport en entier
uv run genecrew apply deaths --yaml output/deces/2026-07-21_propositions_deces_all.yaml --dry-run

# 2. puis pour de vrai, sur un YAML réduit à UNE proposition
#    (copier le lot, n'y garder qu'une entrée `type: date`)
uv run genecrew apply deaths --yaml <lot-d-une-ligne.yaml>
```

À vérifier dans Gramps Web avant d'élargir :

- l'événement décès apparaît bien **comme le décès** de la personne (et non comme un
  événement quelconque) — c'est ce qui prouve que le `death_ref_index` a été posé ;
- la date s'affiche correctement et **se trie** au bon endroit dans la chronologie —
  c'est ce qui prouve que le `sortval` est bien calculé côté serveur ;
- la citation pointe la bonne source et porte la référence d'archive complète ;
- le tag `genecrew:deces` est présent sur la personne.

Si le tri chronologique est faux, s'arrêter : cela signifierait qu'il faut calculer le
`sortval` côté client (jour julien grégorien = `date.toordinal() + 1721425`) et rouvrir
la question dans `crewai_custom_tools`.

Puis ouvrir la PR de `feat/deces-creation-evenement` vers `main`.

---

## Auto-revue du plan

**Couverture de la spec.** §1 → Tasks 7-8. §2 (garde-fous) → Tasks 5, 7, 9. §3 (filtre à 4 conditions) → Task 5 (trois conditions) et Task 7 (`_a_un_deces`). §4 (champs structurés) → Tasks 1 et 3, **moins `lieu_code`**, écart documenté en tête du plan. §5 (outils existants) → Task 2, qui délègue au lieu de reconstruire. §6 (séquence, note/tag sur la personne) → Task 7. §7 (lieu, aucune création) → Task 4. §8 (CLI, fichiers, rapport, ADR) → Tasks 6, 8, 9. §9 (tests) → répartis dans chaque tâche. §10 (ordre de livraison) → Task 1 puis Porte humaine 1 puis Task 2.

**Cohérence des noms.** `dateval_iso` et `creer_evenement_source` (Task 2) sont importés sous ces noms exacts en Tasks 5 et 7. `trier_propositions` rend `(retenues, motifs)` avec les clés `hors_perimetre` / `sans_donnee`, consommées telles quelles par `render_deaths_report` (Task 6) et `run_deces_event` (Task 7). `run_deces_event` est le nom routé en Task 8. `TAG_DECES` est défini en Task 4 et utilisé en Task 7.

**Points de vigilance pour l'implémenteur.**

- Task 3 : la construction de `PersonFacts` dans le test est à copier sur les tests voisins du fichier, dont la signature exacte n'est pas reproduite ici.
- Task 7 : les stubs remplacent les outils **par leur nom dans le module `deces_event`** (`monkeypatch.setattr(deces_event, ...)`), pas dans la bibliothèque — c'est ce qui rend le test offline sans toucher `write_tools`.
- Task 7 : `_arbre()` répond `people` pour n'importe quel handle ; suffisant tant qu'un test ne manipule qu'une personne.
