# Contrat de consignation des pistes — plan d'implémentation

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Poser le contrat de sortie des pistes de recherche — un modèle, une règle de force, un marqueur idempotent, une écriture append-only, un rapport — et le prouver en branchant la source MatchID déjà en place.

**Architecture:** Le modèle `Piste` vit dans `crewai_custom_tools` (les futures sources y seront des outils de bibliothèque), ré-exporté par un shim genecrew comme le fait déjà `propositions.py`. Toute la logique de consignation vit dans `genecrew/src/genecrew/pistes.py` : règle de force pure, marqueur, lecture d'idempotence, écriture note+tag, rendu du rapport. `deces.py` gagne l'émission de pistes sans changer son comportement actuel.

**Tech Stack:** Python 3, `pydantic`, `hashlib`, `pytest`, `pytest-mock`, `uv`, API Gramps Web.

## Global Constraints

- **Une piste n'est jamais un fait.** Aucune citation n'est créée à ce stade (`document-de-travail.md` §6.3). La note rapporte, elle ne conclut pas.
- **Aucune URL fabriquée.** Si la source ne donne pas de permalien, `url` vaut `None` et la note dit « permalien ABSENT de la source » avec la marche à suivre manuelle. Fabriquer une URL par motif produirait des liens morts écrits comme preuves — interdit.
- **Idempotence par identité, jamais par date.** Marqueur `[genecrew:piste:<source>:<identite>]`. Un second passage qui retrouve le marqueur n'écrit rien.
- **Clé dérivée déterministe entre processus** : `hashlib`, **jamais `hash()`** (salé à chaque exécution). Champs normalisés avant hachage (casse, accents, espaces).
- **`force` est calculée, jamais fournie** par l'appelant. Typée `Literal["forte", "faible"]`, pas `str` libre.
- **Forte** = au moins **deux facteurs concordants indépendants** ET **aucune divergence dure**. L'année seule n'est pas un facteur.
- **Fortes dans l'arbre, faibles au rapport seulement.**
- Tests **offline** : client Gramps mocké, aucun accès réseau.
- Deux dépôts : `/Users/fjacquet/Projects/crewai_custom_tools` et `/Users/fjacquet/Projects/genecrew`. **Opérations git de chaque dépôt dans des appels séparés** — un `cd A && git … && cd B && git …` exécute les deux git dans A.
- Branche `genecrew` déjà créée : `feat/pistes-contrat`. Ne pas travailler sur `main`.
- Messages de commit en **français accentué**.
- Spec de référence : `docs/superpowers/specs/2026-07-20-contrat-pistes-design.md`.

### Séquencement imposé par la CI

La CI de `genecrew` checkoute le dépôt voisin sur le **tag** `v<version>` lu dans `uv.lock`, pas sur `main`. La Task 1 doit donc **taguer et pousser** la bibliothèque avant que la Task 2 puisse faire un `uv sync` cohérent. Ce n'est pas une précaution : `uv sync --locked` échoue en CI sinon, avec un message qui ne dit pas pourquoi.

---

### Task 1 : Le modèle `Piste` dans la bibliothèque

**Files:**

- Modify: `crewai_custom_tools/src/crewai_custom_tools/tools/genealogy/models/domain.py`
- Test: `crewai_custom_tools/tests/test_genealogy_domain.py`
- Modify (release): `crewai_custom_tools/pyproject.toml`, `crewai_custom_tools/src/crewai_custom_tools/__init__.py`, `crewai_custom_tools/CHANGELOG.md`

**Interfaces:**

- Produces: `Piste` — modèle pydantic aux champs `gramps_id: str`, `handle: str`, `source: str`, `identite: str`, `identite_derivee: bool = False`, `url: str | None = None`, `requete: str`, `concordances: list[str]`, `divergences: list[str]`, `force: Literal["forte", "faible"]`.

Le dépôt bibliothèque est sur `main` (propre, poussé). **Crée une branche `feat/modele-piste` depuis `main`** — c'est la seule task autorisée à créer une branche.

- [ ] **Step 1: Écrire le test qui échoue**

Ajouter à la fin de `crewai_custom_tools/tests/test_genealogy_domain.py` :

```python
def test_piste_champs_et_defauts():
    from crewai_custom_tools.tools.genealogy.models.domain import Piste

    p = Piste(gramps_id="I1123", handle="h1", source="matchid",
              identite="a1b2c3d4", requete="nom=SOULAT&prenom=Kleber",
              concordances=["nom", "date de naissance complète"],
              divergences=[], force="forte")
    assert p.identite_derivee is False       # défaut : identité native de la source
    assert p.url is None                     # défaut : aucune URL inventée
    assert p.force == "forte"


def test_piste_force_est_un_ensemble_ferme():
    import pytest
    from pydantic import ValidationError
    from crewai_custom_tools.tools.genealogy.models.domain import Piste

    # `force` est Literal, pas str libre : le contrat est garanti par le modèle,
    # pas par la discipline de chaque émetteur.
    with pytest.raises(ValidationError):
        Piste(gramps_id="I1", handle="h", source="s", identite="i",
              requete="q", concordances=[], divergences=[], force="moyenne")
```

- [ ] **Step 2: Lancer le test, vérifier qu'il échoue**

```bash
cd /Users/fjacquet/Projects/crewai_custom_tools
uv run python -m pytest tests/test_genealogy_domain.py -v
```

Attendu : `ImportError` — `cannot import name 'Piste'`.

- [ ] **Step 3: Implémenter**

Dans `models/domain.py`, après la classe `PropositionsLot`, ajouter :

```python
class Piste(BaseModel):
    """Une piste de recherche : ce qu'une source suggère, jamais ce qu'elle prouve.

    Aucune citation n'est créée à ce stade (document-de-travail §6.3). L'identité
    est celle de la source (ark, id MatchID, Q-item) ; à défaut, une clé dérivée
    des champs identifiants — jamais une URL fabriquée, qui serait un lien mort
    présenté comme preuve.
    """

    gramps_id: str
    handle: str
    source: str                       # "matchid" | "mdh" | "gallica" | "wikidata" | …
    identite: str                     # identifiant externe stable, OU clé dérivée
    identite_derivee: bool = False    # True -> la note dira le permalien absent
    url: str | None = None            # None si la source n'en donne pas
    requete: str                      # la requête exacte, rejouable telle quelle
    concordances: list[str] = Field(default_factory=list)
    divergences: list[str] = Field(default_factory=list)
    force: Literal["forte", "faible"]
```

Si `Literal` n'est pas déjà importé en tête du fichier, ajouter `from typing import Literal`.

- [ ] **Step 4: Lancer les tests, vérifier qu'ils passent**

```bash
cd /Users/fjacquet/Projects/crewai_custom_tools
uv run python -m pytest tests/test_genealogy_domain.py -v
uv run python -m pytest tests/ -q
uv run ruff check src/ tests/
```

Attendu : les deux nouveaux tests passent ; la suite complète reste verte (739 avant, 741 après) ; ruff propre.

- [ ] **Step 5: Release 0.19.3**

Le rituel du dépôt exige la version à **deux** endroits — `pyproject.toml` **et** `src/crewai_custom_tools/__init__.py` — et `tests/test_scaffold.py` compare les deux, donc un oubli casse un test. Passer `0.19.2` → `0.19.3` dans les deux.

Ajouter en tête de `CHANGELOG.md`, avant l'entrée `[0.19.2]` :

```markdown
## [0.19.3] - 2026-07-20

### Added

- **`Piste`** (`models/domain.py`) : le modèle des pistes de recherche (Phase 4).
  Une piste n'est jamais un fait — aucune citation n'est créée à ce stade. Porte
  l'identité de la source (ark, id MatchID, Q-item) ou, à défaut, une clé dérivée
  marquée comme telle ; `url` reste `None` plutôt que d'être fabriquée. `force`
  est un `Literal["forte", "faible"]`, calculé et non saisi.

---

```

- [ ] **Step 6: Commit, tag et push**

```bash
cd /Users/fjacquet/Projects/crewai_custom_tools
git add src/crewai_custom_tools/tools/genealogy/models/domain.py tests/test_genealogy_domain.py
git commit -m "feat(models): Piste, le modèle des pistes de recherche

Une piste n'est jamais un fait : aucune citation à ce stade. L'identité
vient de la source (ark, id MatchID, Q-item) ou d'une clé dérivée marquée
comme telle ; url reste None plutôt que d'être fabriquée. force est un
Literal, pas un str libre — le contrat est garanti par le modèle."
git add pyproject.toml src/crewai_custom_tools/__init__.py CHANGELOG.md
git commit -m "chore(release): 0.19.3 — modèle Piste"
git tag -a v0.19.3 -m "0.19.3 — modèle Piste"
git push -u origin feat/modele-piste
git push origin v0.19.3
```

**Le tag doit être poussé** : la Task 2 en dépend, et la CI de genecrew checkoute le voisin par tag.

---

### Task 2 : La règle de force, le marqueur et la clé dérivée

**Files:**

- Create: `genecrew/src/genecrew/pistes.py`
- Test: `genecrew/tests/test_pistes.py` (créer)

**Interfaces:**

- Consumes: `Piste` (Task 1).
- Produces:
  - `evaluer_force(concordances: list[str], divergences: list[str]) -> Literal["forte", "faible"]`
  - `cle_derivee(source: str, champs: list[str]) -> str` — hachage stable, 8 caractères hexadécimaux
  - `marqueur(source: str, identite: str, derivee: bool = False) -> str`
  - `Piste` (ré-export)

Ces trois fonctions sont **pures** : ni réseau, ni Gramps, ni horloge.

- [ ] **Step 1: Écrire les tests qui échouent**

Créer `genecrew/tests/test_pistes.py` :

```python
from genecrew.pistes import cle_derivee, evaluer_force, marqueur


def test_deux_facteurs_independants_font_une_piste_forte():
    assert evaluer_force(["nom", "date de naissance complète"], []) == "forte"


def test_un_seul_facteur_ne_suffit_pas():
    assert evaluer_force(["nom"], []) == "faible"
    assert evaluer_force([], []) == "faible"


def test_une_divergence_dure_degrade_malgre_les_concordances():
    # Règle du projet : une contradiction irréductible l'emporte sur n'importe
    # quel nombre de concordances.
    assert evaluer_force(["nom", "prénom", "lieu"], ["départements incompatibles"]) == "faible"


def test_cle_derivee_est_stable_entre_appels():
    a = cle_derivee("mdh", ["SOULAT", "Hoche", "1915-05-09", "154e RI"])
    b = cle_derivee("mdh", ["SOULAT", "Hoche", "1915-05-09", "154e RI"])
    assert a == b and len(a) == 8


def test_cle_derivee_normalise_casse_accents_et_espaces():
    # La même fiche rendue différemment doit produire la MÊME clé, sinon
    # l'idempotence saute au premier changement de formatage de la source.
    assert cle_derivee("mdh", ["SOULAT", "Hoche"]) == cle_derivee("mdh", ["  soulat ", "HOCHÉ".replace("É", "e")])


def test_cle_derivee_distingue_des_fiches_differentes():
    assert cle_derivee("mdh", ["SOULAT", "Hoche"]) != cle_derivee("mdh", ["SOULAT", "Kléber"])


def test_marqueur_natif_et_derive():
    assert marqueur("matchid", "a1b2c3d4") == "[genecrew:piste:matchid:a1b2c3d4]"
    # Le préfixe k= signale une identité dérivée, lisible d'un coup d'œil dans Gramps.
    assert marqueur("mdh", "6f2a91c4", derivee=True) == "[genecrew:piste:mdh:k=6f2a91c4]"


def test_cle_derivee_ne_depend_pas_du_salage_du_processus():
    # hash() est salé à chaque exécution : une clé qui en dépendrait casserait
    # l'idempotence entre deux lancements. On verrouille la valeur attendue.
    assert cle_derivee("mdh", ["SOULAT", "Hoche"]) == cle_derivee("mdh", ["SOULAT", "Hoche"])
    import subprocess, sys
    autre = subprocess.run(
        [sys.executable, "-c",
         "from genecrew.pistes import cle_derivee; print(cle_derivee('mdh', ['SOULAT','Hoche']))"],
        capture_output=True, text=True, check=True).stdout.strip()
    assert autre == cle_derivee("mdh", ["SOULAT", "Hoche"])
```

- [ ] **Step 2: Lancer les tests, vérifier qu'ils échouent**

```bash
cd /Users/fjacquet/Projects/genecrew
uv run python -m pytest genecrew/tests/test_pistes.py -v
```

Attendu : `ModuleNotFoundError: No module named 'genecrew.pistes'`.

- [ ] **Step 3: Synchroniser la bibliothèque**

```bash
cd /Users/fjacquet/Projects/genecrew
uv sync
uv run python -c "import importlib.metadata as m; print(m.version('crewai-custom-tools'))"
```

Attendu : `0.19.3`. Sinon, la Task 1 n'a pas été poussée — **arrête-toi et signale-le**.

- [ ] **Step 4: Implémenter**

Créer `genecrew/src/genecrew/pistes.py` :

```python
"""Contrat de consignation des pistes de recherche (Phase 4, document-de-travail §6.3).

Une piste n'est jamais un fait : aucune citation n'est créée ici. Ce module définit
ce qui fait une piste forte, comment on l'identifie de façon stable dans le temps,
et comment on la consigne sans jamais écrire deux fois la même.
"""

from __future__ import annotations

import hashlib
import unicodedata
from typing import Literal

from crewai_custom_tools.tools.genealogy.models.domain import Piste  # noqa: F401

_LONGUEUR_CLE = 8


def evaluer_force(concordances: list[str],
                  divergences: list[str]) -> Literal["forte", "faible"]:
    """Forte = au moins DEUX facteurs concordants indépendants ET aucune divergence dure.

    Catégoriel, pas numérique. Un score peut valoir 1.0 en masquant une ambiguïté
    (mesuré sur le résolveur de lieux), et la règle projet « une année seule n'est
    jamais discriminante » est catégorielle par nature. L'appelant est responsable
    de ne PAS lister l'année seule comme concordance : elle qualifie une date, elle
    n'en constitue pas une.
    """
    if divergences:
        return "faible"
    return "forte" if len(concordances) >= 2 else "faible"


def _normaliser(valeur: str) -> str:
    """Casse, accents et espaces retirés — la même fiche doit donner la même clé."""
    sans_accent = "".join(c for c in unicodedata.normalize("NFD", valeur)
                          if unicodedata.category(c) != "Mn")
    return " ".join(sans_accent.split()).upper()


def cle_derivee(source: str, champs: list[str]) -> str:
    """Identité de repli quand la source ne fournit aucun identifiant stable.

    Ce n'est PAS une URL : elle ne s'affiche jamais comme preuve, elle sert
    uniquement à reconnaître une piste déjà consignée. Le pire qu'une collision
    puisse produire est un doublon manqué — pas un lien mort donné pour une source.

    `hashlib` et non `hash()` : ce dernier est salé à chaque exécution, ce qui
    casserait l'idempotence entre deux lancements du pipeline.
    """
    graine = "|".join([source] + [_normaliser(c) for c in champs])
    return hashlib.sha256(graine.encode("utf-8")).hexdigest()[:_LONGUEUR_CLE]


def marqueur(source: str, identite: str, derivee: bool = False) -> str:
    """Marqueur d'idempotence, porté par le corps de la note.

    Il porte l'IDENTITÉ, jamais la date : le pipeline repasse sur les mêmes
    personnes pendant des mois, et un marqueur daté recréerait la même piste à
    chaque exécution.
    """
    return f"[genecrew:piste:{source}:{'k=' if derivee else ''}{identite}]"
```

- [ ] **Step 5: Lancer les tests, vérifier qu'ils passent**

```bash
cd /Users/fjacquet/Projects/genecrew
uv run python -m pytest genecrew/tests/test_pistes.py -v
uv run ruff check .
```

Attendu : `8 passed`, ruff propre.

- [ ] **Step 6: Commit**

```bash
cd /Users/fjacquet/Projects/genecrew
git add genecrew/src/genecrew/pistes.py genecrew/tests/test_pistes.py uv.lock
git commit -m "feat(pistes): règle de force, marqueur et clé dérivée

Forte = deux facteurs concordants indépendants ET aucune divergence dure.
Catégoriel et non numérique : un score peut valoir 1.0 en masquant une
ambiguïté, et « une année seule n'est jamais discriminante » ne s'exprime
pas par un seuil.

Le marqueur porte l'identité, jamais la date — sans quoi chaque passage
recréerait les mêmes pistes. La clé dérivée utilise hashlib et non hash(),
salé à chaque exécution, et normalise casse et accents avant hachage."
```

---

### Task 3 : Idempotence et écriture

**Files:**

- Modify: `genecrew/src/genecrew/pistes.py`
- Modify: `genecrew/tests/test_pistes.py`

**Interfaces:**

- Consumes: `marqueur()` (Task 2), `Piste` (Task 1).
- Produces:
  - `marqueurs_existants(client, gramps_id: str) -> set[str]` — les marqueurs déjà posés sur une personne
  - `consigner(client, piste: Piste, *, dry_run: bool = False) -> dict` — rend `{"ecrite": bool, "raison": str}`

Chaîne d'écriture Gramps, vérifiée : `GrampsCreateNoteTool` (crée la note) → `GrampsEnsureTagTool` (tag idempotent) → `GrampsAttachTool` (rattache note **et** tag à la personne, append-only strict sur `note_list`/`tag_list`).

Lecture d'idempotence, vérifiée en direct : `GET /people/?gramps_id=…&extend=note_list` rend `extended.notes`, chaque note portant son corps dans `note["text"]["string"]`. **Un seul appel par personne**, pas de N+1.

- [ ] **Step 1: Écrire les tests qui échouent**

Ajouter à `genecrew/tests/test_pistes.py` :

```python
import json

import httpx
import pytest
from crewai_custom_tools.tools.genealogy.gramps import write_tools
from crewai_custom_tools.tools.genealogy.gramps.client import GrampsClient, GrampsConfig

from genecrew import pistes as pistes_mod
from genecrew.pistes import Piste, consigner, marqueurs_existants

CONFIG = GrampsConfig(api_url="http://g.test/api", username="u", password="p")


@pytest.fixture(autouse=True)
def _ecriture_reelle(monkeypatch):
    monkeypatch.setenv("GENECREW_DRY_RUN", "false")


def _client(records, notes=()):
    """Client Gramps mocké. `notes` = corps des notes déjà rattachées à la personne."""
    def handler(request):
        if request.url.path == "/api/token/":
            return httpx.Response(200, json={"access_token": "t"})
        if request.url.path == "/api/people/" and request.method == "GET":
            return httpx.Response(200, json=[{
                "handle": "h1", "gramps_id": "I1123",
                "note_list": [], "tag_list": [],
                "extended": {"notes": [{"text": {"string": n}} for n in notes]},
            }])
        records.append((request.method, str(request.url.path),
                        json.loads(request.content) if request.content else None))
        if request.method == "POST":
            return httpx.Response(201, json=[{"new": [{"handle": "nouveau"}]}])
        return httpx.Response(200, json={})
    return GrampsClient(CONFIG, transport=httpx.MockTransport(handler))


def _piste(force="forte", **kw):
    base = dict(gramps_id="I1123", handle="h1", source="matchid", identite="a1b2c3d4",
                requete="nom=SOULAT&prenom=Kleber", url="https://deces.matchid.io/id/a1b2c3d4",
                concordances=["nom", "date de naissance complète"], divergences=[], force=force)
    base.update(kw)
    return Piste(**base)


def test_marqueurs_existants_lit_les_notes_de_la_personne():
    client = _client([], notes=["[genecrew:piste:matchid:a1b2c3d4] Piste de décès…",
                                "Note humaine sans marqueur"])
    assert marqueurs_existants(client, "I1123") == {"[genecrew:piste:matchid:a1b2c3d4]"}


def test_une_piste_forte_est_ecrite(mocker):
    records = []
    client = _client(records)
    mocker.patch.object(write_tools, "get_client", return_value=client)
    out = consigner(client, _piste())
    assert out["ecrite"] is True
    posts = [r for r in records if r[0] == "POST"]
    assert any("/notes/" in r[1] for r in posts), "la note n'a pas été créée"


def test_une_piste_faible_ne_touche_jamais_l_arbre(mocker):
    records = []
    client = _client(records)
    mocker.patch.object(write_tools, "get_client", return_value=client)
    out = consigner(client, _piste(force="faible"))
    assert out["ecrite"] is False and out["raison"] == "faible"
    assert not [r for r in records if r[0] in ("POST", "PUT")], "une faible a écrit dans l'arbre"


def test_second_passage_n_ecrit_rien(mocker):
    # LE test qui justifie tout le mécanisme de marqueur.
    records = []
    client = _client(records, notes=["[genecrew:piste:matchid:a1b2c3d4] déjà consignée"])
    mocker.patch.object(write_tools, "get_client", return_value=client)
    out = consigner(client, _piste())
    assert out["ecrite"] is False and out["raison"] == "déjà consignée"
    assert not [r for r in records if r[0] in ("POST", "PUT")]


def test_dry_run_n_ecrit_rien(mocker):
    records = []
    client = _client(records)
    mocker.patch.object(write_tools, "get_client", return_value=client)
    out = consigner(client, _piste(), dry_run=True)
    assert out["ecrite"] is False and out["raison"] == "simulation"
    assert not [r for r in records if r[0] == "PUT"]


def test_le_corps_de_la_note_dit_l_absence_de_permalien(mocker):
    records = []
    client = _client(records)
    mocker.patch.object(write_tools, "get_client", return_value=client)
    consigner(client, _piste(url=None, identite="6f2a91c4", identite_derivee=True, source="mdh"))
    corps = next(r[2]["text"]["string"] for r in records
                 if r[0] == "POST" and "/notes/" in r[1])
    assert "ABSENT" in corps
    assert "http" not in corps, "aucune URL ne doit apparaître quand la source n'en donne pas"
    assert corps.startswith("[genecrew:piste:mdh:k=6f2a91c4]")


def test_le_corps_ne_conclut_pas(mocker):
    records = []
    client = _client(records)
    mocker.patch.object(write_tools, "get_client", return_value=client)
    consigner(client, _piste())
    corps = next(r[2]["text"]["string"] for r in records
                 if r[0] == "POST" and "/notes/" in r[1])
    assert "Une piste n'est pas un fait" in corps
```

- [ ] **Step 2: Lancer les tests, vérifier qu'ils échouent**

```bash
cd /Users/fjacquet/Projects/genecrew
uv run python -m pytest genecrew/tests/test_pistes.py -v
```

Attendu : `ImportError` — `cannot import name 'consigner'`.

- [ ] **Step 3: Implémenter**

Ajouter en tête de `pistes.py`, aux imports :

```python
import json

from crewai_custom_tools.tools.genealogy.gramps.write_tools import (
    GrampsAttachTool, GrampsCreateNoteTool, GrampsEnsureTagTool, effective_dry_run,
)
```

puis, à la fin du fichier :

```python
TAG_PISTE = "ia-piste"


def marqueurs_existants(client, gramps_id: str) -> set[str]:
    """Les marqueurs de piste déjà posés sur cette personne.

    Filtre par `gramps_id` côté serveur et demande `extend=note_list` : les notes
    complètes arrivent en UN appel, pour UNE personne. Vérifié en direct contre
    l'API — `extended.notes[i]["text"]["string"]` porte le corps de la note.
    """
    gens = client.get_json("/people/",
                           params={"gramps_id": gramps_id, "extend": "note_list"}) or []
    if not gens:
        return set()
    notes = (gens[0].get("extended") or {}).get("notes") or []
    marqueurs = set()
    for note in notes:
        corps = (note.get("text") or {}).get("string", "")
        if corps.startswith("[genecrew:piste:") and "]" in corps:
            marqueurs.add(corps[:corps.index("]") + 1])
    return marqueurs


def corps_note(piste: Piste) -> str:
    """Rend le corps de la note. Rapporte, ne conclut jamais."""
    lignes = [marqueur(piste.source, piste.identite, piste.identite_derivee),
              f"Piste — {piste.source}",
              "",
              f"Correspondance : {piste.force.upper()}",
              f"  concordent : {', '.join(piste.concordances) or '—'}",
              f"  divergent  : {', '.join(piste.divergences) or '—'}",
              ""]
    if piste.url:
        lignes.append(f"URL : {piste.url}")
    else:
        lignes += ["Permalien ABSENT de la source.",
                   "Pour retrouver la fiche : recherche manuelle par nom + date."]
    lignes += [f"Requête rejouable : {piste.requete}",
               "",
               "Une piste n'est pas un fait : à vérifier avant toute citation."]
    return "\n".join(lignes)


def consigner(client, piste: Piste, *, dry_run: bool = False) -> dict:
    """Écrit une piste FORTE dans l'arbre, une seule fois. Rend le verdict et sa raison.

    Une faible n'entre jamais dans l'arbre : elle vit dans le rapport seul.
    """
    if piste.force != "forte":
        return {"ecrite": False, "raison": "faible"}
    if marqueur(piste.source, piste.identite, piste.identite_derivee) in marqueurs_existants(
            client, piste.gramps_id):
        return {"ecrite": False, "raison": "déjà consignée"}
    if effective_dry_run(dry_run):
        return {"ecrite": False, "raison": "simulation"}

    note = json.loads(GrampsCreateNoteTool()._run(text=corps_note(piste), note_type="Research"))
    if not note["success"]:
        return {"ecrite": False, "raison": f"note refusée : {note['error']}"}
    tag = json.loads(GrampsEnsureTagTool()._run(name=TAG_PISTE))
    if not tag["success"]:
        return {"ecrite": False, "raison": f"tag refusé : {tag['error']}"}
    attache = json.loads(GrampsAttachTool()._run(
        handle=piste.handle, note_handle=note["data"]["handle"],
        tag_handle=tag["data"]["handle"]))
    if not attache["success"]:
        return {"ecrite": False, "raison": f"rattachement refusé : {attache['error']}"}
    return {"ecrite": True, "raison": "consignée"}
```

- [ ] **Step 4: Lancer les tests, vérifier qu'ils passent**

```bash
cd /Users/fjacquet/Projects/genecrew
uv run python -m pytest genecrew/tests/test_pistes.py -v
uv run ruff check .
```

Attendu : `15 passed`, ruff propre.

- [ ] **Step 5: Commit**

```bash
cd /Users/fjacquet/Projects/genecrew
git add genecrew/src/genecrew/pistes.py genecrew/tests/test_pistes.py
git commit -m "feat(pistes): idempotence et écriture append-only

Le marqueur est lu dans les notes déjà rattachées à la personne, via
extend=note_list — un seul appel, pas de N+1. Un second passage sur la
même piste n'écrit rien : c'est ce qui rend le pipeline rejouable pendant
des mois sans accumuler de doublons.

Une piste faible ne touche jamais l'arbre. Une source sans permalien
produit une note qui le DIT, sans jamais fabriquer d'URL."
```

---

### Task 4 : Le rapport

**Files:**

- Modify: `genecrew/src/genecrew/pistes.py`
- Modify: `genecrew/tests/test_pistes.py`

**Interfaces:**

- Consumes: `Piste` (Task 1).
- Produces: `render_rapport_pistes(pistes: list[Piste], date: str, *, dry_run: bool) -> str` — Markdown pur, fonction sans effet de bord.

- [ ] **Step 1: Écrire les tests qui échouent**

Ajouter à `genecrew/tests/test_pistes.py` :

```python
def test_rapport_separe_fortes_et_faibles():
    from genecrew.pistes import render_rapport_pistes
    md = render_rapport_pistes([_piste(), _piste(force="faible", identite="zzz")],
                               "2026-07-20", dry_run=False)
    assert "Pistes fortes" in md and "Pistes faibles" in md
    assert "écritures appliquées" in md


def test_rapport_dit_le_mode_simulation():
    from genecrew.pistes import render_rapport_pistes
    md = render_rapport_pistes([_piste()], "2026-07-20", dry_run=True)
    assert "simulation" in md


def test_rapport_contient_les_faibles_absentes_de_l_arbre():
    # Les faibles n'existent QUE là : si le rapport les perd, elles sont perdues.
    from genecrew.pistes import render_rapport_pistes
    md = render_rapport_pistes([_piste(force="faible", identite="zzz",
                                       concordances=["nom"])], "2026-07-20", dry_run=False)
    assert "zzz" in md


def test_rapport_sans_piste_le_dit():
    from genecrew.pistes import render_rapport_pistes
    md = render_rapport_pistes([], "2026-07-20", dry_run=False)
    assert "Aucune piste" in md
```

- [ ] **Step 2: Lancer les tests, vérifier qu'ils échouent**

```bash
cd /Users/fjacquet/Projects/genecrew
uv run python -m pytest genecrew/tests/test_pistes.py -v
```

Attendu : `ImportError` — `cannot import name 'render_rapport_pistes'`.

- [ ] **Step 3: Implémenter**

Ajouter à la fin de `pistes.py` :

```python
def render_rapport_pistes(pistes: list[Piste], date: str, *, dry_run: bool) -> str:
    """Rapport Markdown. Les faibles n'existent QUE là — les perdre les perdrait."""
    mode = "simulation (dry-run, aucune écriture)" if dry_run else "écritures appliquées"
    fortes = [p for p in pistes if p.force == "forte"]
    faibles = [p for p in pistes if p.force == "faible"]
    lignes = [f"# Pistes de recherche — {date}", "",
              f"Mode : {mode}.", "",
              f"- Pistes fortes (écrites dans l'arbre) : {len(fortes)}",
              f"- Pistes faibles (ce rapport seulement) : {len(faibles)}", ""]
    if not pistes:
        lignes += ["Aucune piste.", ""]
        return "\n".join(lignes)
    for titre, lot in (("Pistes fortes", fortes), ("Pistes faibles", faibles)):
        lignes += [f"## {titre}", ""]
        if not lot:
            lignes += ["Aucune.", ""]
            continue
        lignes += ["| Personne | Source | Identité | Concordances | Divergences | URL |",
                   "|---|---|---|---|---|---|"]
        for p in lot:
            url = p.url or "— (permalien absent de la source)"
            lignes.append(f"| {p.gramps_id} | {p.source} | {p.identite} | "
                          f"{', '.join(p.concordances) or '—'} | "
                          f"{', '.join(p.divergences) or '—'} | {url} |")
        lignes.append("")
    lignes += ["> Une piste n'est pas un fait : aucune citation n'a été créée.", ""]
    return "\n".join(lignes)
```

- [ ] **Step 4: Lancer les tests, vérifier qu'ils passent**

```bash
cd /Users/fjacquet/Projects/genecrew
uv run python -m pytest genecrew/tests/test_pistes.py -v
uv run ruff check .
```

Attendu : `19 passed`, ruff propre.

- [ ] **Step 5: Commit**

```bash
cd /Users/fjacquet/Projects/genecrew
git add genecrew/src/genecrew/pistes.py genecrew/tests/test_pistes.py
git commit -m "feat(pistes): rapport Markdown, fortes et faibles séparées

Les faibles n'existent que dans ce rapport : elles ne sont jamais écrites
dans l'arbre. Le perdre les perdrait, d'où le test qui vérifie qu'elles y
figurent bien. Le mode affiché est le mode EFFECTIF, donc le rapport ne
prétend jamais avoir écrit ce qui a été simulé."
```

---

### Task 5 : Brancher MatchID

**Files:**

- Modify: `genecrew/src/genecrew/deces.py`
- Test: `genecrew/tests/test_deces_pistes.py` (créer)

**Interfaces:**

- Consumes: `Piste`, `evaluer_force` (Tasks 1–2).
- Produces: `piste_depuis_match(person, match: dict, url: str) -> Piste` dans `deces.py`.

**Le comportement actuel de `deces.py` ne change pas.** Il continue de produire ses propositions de citation ; on ajoute seulement une fonction qui transforme un résultat MatchID en `Piste`. Le câblage dans le flux complet viendra avec le sous-projet « détection de lacunes ».

- [ ] **Step 1: Écrire les tests qui échouent**

Créer `genecrew/tests/test_deces_pistes.py` :

```python
from crewai_custom_tools.tools.genealogy.models.domain import EventFact, PersonFacts

from genecrew.deces import piste_depuis_match


def _personne(**kw):
    # PersonFacts exige name et sex ; EventFact exige type et n'a PAS de champ `iso` —
    # la date ISO se dérive de `dateval` via event_iso() (deces.py). dateval = [jour, mois, année, ...]
    base = dict(gramps_id="I1123", handle="h1", name="Kléber SOULAT", sex="M",
                given="Kléber", surname="SOULAT",
                birth=EventFact(type="Birth", year=1888, dateval=[5, 7, 1888, False]),
                death=None)
    base.update(kw)
    return PersonFacts(**base)


_MATCH = {"id": "a1b2c3d4", "name": {"last": "Soulat", "first": ["Kleber"]},
          "birth": {"date": "18880705"}, "death": {"date": "19140926"}}


def test_nom_et_date_complete_font_une_piste_forte():
    p = piste_depuis_match(_personne(), _MATCH, "https://deces.matchid.io/id/a1b2c3d4")
    assert p.force == "forte"
    assert p.source == "matchid" and p.identite == "a1b2c3d4"
    assert p.identite_derivee is False
    assert p.url == "https://deces.matchid.io/id/a1b2c3d4"
    assert "nom=" in p.requete or "SOULAT" in p.requete


def test_annee_seule_ne_fait_pas_une_piste_forte():
    # Règle du projet : l'année seule n'est jamais discriminante. Une naissance
    # sans jour ni mois ne fournit qu'UN facteur avec le nom.
    # dateval vide -> event_iso() rend "1888" (année seule), pas une date complète.
    sans_jour = _personne(birth=EventFact(type="Birth", year=1888, dateval=[]))
    maigre = {"id": "x", "name": {"last": "Soulat", "first": ["Kleber"]},
              "birth": {"date": "1888"}, "death": {"date": "19140926"}}
    p = piste_depuis_match(sans_jour, maigre, "https://deces.matchid.io/id/x")
    assert p.force == "faible"
    assert "année" in " ".join(p.concordances + p.divergences).lower() or p.concordances == ["nom"]
```

- [ ] **Step 2: Lancer les tests, vérifier qu'ils échouent**

```bash
cd /Users/fjacquet/Projects/genecrew
uv run python -m pytest genecrew/tests/test_deces_pistes.py -v
```

Attendu : `ImportError` — `cannot import name 'piste_depuis_match'`.

- [ ] **Step 3: Implémenter**

Ajouter à `deces.py` (les imports en tête, la fonction à la fin) :

```python
from genecrew.pistes import Piste, evaluer_force
```

`event_iso` et `first_given` existent déjà dans `deces.py` — ne les redéfinis pas.

```python
def piste_depuis_match(person, match: dict, url: str) -> Piste:
    """Transforme un résultat MatchID en piste. N'écrit rien, ne conclut rien.

    L'année de naissance seule ne compte PAS comme facteur : la règle du projet
    veut qu'une année ne soit jamais discriminante. Il faut une date complète
    (jour + mois + année) pour qu'elle constitue un second facteur à côté du nom.
    """
    concordances, divergences = [], []
    nom_insee = (match.get("name") or {}).get("last", "")
    if nom_insee and _norm_nom(nom_insee) == _norm_nom(person.surname):
        concordances.append("nom")
    naissance_insee = ((match.get("birth") or {}).get("date") or "")
    # `EventFact` n'a pas de champ ISO : event_iso() rend "AAAA-MM-JJ" si la date est
    # complète, "AAAA" si l'année est seule. C'est cette longueur qui distingue les deux,
    # et c'est ce qui empêche une année seule de compter comme second facteur.
    naissance_arbre = event_iso(person.birth)
    if len(naissance_insee) == 8 and len(naissance_arbre) == 10:
        iso_insee = f"{naissance_insee[:4]}-{naissance_insee[4:6]}-{naissance_insee[6:]}"
        if iso_insee == naissance_arbre:
            concordances.append("date de naissance complète")
        else:
            divergences.append("dates de naissance différentes")
    return Piste(
        gramps_id=person.gramps_id, handle=person.handle,
        source="matchid", identite=str(match.get("id") or ""),
        url=url or None,
        requete=f"nom={person.surname}&prenom={first_given(person.given)}",
        concordances=concordances, divergences=divergences,
        force=evaluer_force(concordances, divergences),
    )


def _norm_nom(valeur: str) -> str:
    import unicodedata
    sans = "".join(c for c in unicodedata.normalize("NFD", valeur or "")
                   if unicodedata.category(c) != "Mn")
    return sans.strip().upper()
```

- [ ] **Step 4: Lancer les tests, vérifier qu'ils passent**

```bash
cd /Users/fjacquet/Projects/genecrew
uv run python -m pytest genecrew/tests/ -q
uv run ruff check .
```

Attendu : toute la suite verte (167 avant ce plan, + les nouveaux), ruff propre.

- [ ] **Step 5: Commit**

```bash
cd /Users/fjacquet/Projects/genecrew
git add genecrew/src/genecrew/deces.py genecrew/tests/test_deces_pistes.py
git commit -m "feat(deces): émettre des pistes depuis les résultats MatchID

deces.py garde son comportement : il continue de produire ses propositions
de citation. Il gagne seulement la traduction d'un résultat MatchID en
Piste, ce qui donnera une sortie à ses candidats faibles, aujourd'hui
jetés en silence.

L'année de naissance seule ne compte pas comme facteur concordant : il
faut une date complète pour qu'elle en constitue un second à côté du nom."
```

---

## Suite (hors périmètre de ce plan)

La détection de lacunes, les sources Gallica et Wikidata, et le classement par probabilité sont des sous-projets distincts. Chacun aura sa spec et son plan, et consommera ce contrat sans le redéfinir.
