# Sources d'archives en ligne (Wikidata, DHS, Gallica) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Alimenter le contrat `Piste` (cct 0.20.0) par trois sources d'archives — Wikidata, le DHS (via P902) et Gallica — exposées par trois feuilles CLI `propose wikidata|dhs|gallica`.

**Architecture:** Un paquet `genealogy/pistes/` dans `crewai_custom_tools` regroupe une fonction **pure** par source (`pistes_<source>(person, resultats) -> list[Piste]`), sans aucun appel réseau — la collecte reste dans les outils existants (`WikidataSparqlTool`/`sparql_rows`, `GallicaSearchTool`/`parse_sru`). `piste_depuis_match` y déménage depuis genecrew. Côté genecrew, trois feuilles réutilisent tel quel `consigner()` et `render_rapport_pistes()`.

**Tech Stack:** Python 3.12, pydantic v2, `requests` (transport existant), pytest, `uv`. Deux dépôts frères : `crewai_custom_tools` (Tasks 1-6) et `genecrew` (Tasks 7-9).

## Global Constraints

- **`uv` partout** : `uv run`, `uv sync`, `uv add`. Jamais `pip` ni `python` directs.
- **Aucune citation, aucun fait.** Ces sources n'émettent que des `Piste`. Aucun outil d'écriture nouveau.
- **`Piste.force` est dérivé, jamais saisi.** Ne jamais passer `force=` à un constructeur `Piste`.
- **Vocabulaire des concordances clos** à `"nom" | "prénom" | "date complète" | "lieu" | "unité militaire" | "profession"`. Toute autre valeur est rejetée par pydantic. **L'année seule n'est jamais un facteur.**
- **Fonctions `pistes_*` pures** : aucun appel réseau, aucune écriture. Testables hors-ligne par fixtures.
- **Jamais d'URL fabriquée.** Si une source ne donne pas de permalien, `url=None` et `identite_derivee=True`.
- **Ordre de livraison inter-dépôts** : la CI de genecrew checkoute `crewai_custom_tools` sur le **tag** `v<version>` lu dans `uv.lock`. Il faut donc **taguer et pousser la bibliothèque** (Task 6) avant que la CI de genecrew puisse verdir. `uv sync` seul ne suffit pas.
- Tests de la bibliothèque : `cd /Users/fjacquet/Projects/crewai_custom_tools && uv run python -m pytest tests/ -q`
- Tests de genecrew : `cd /Users/fjacquet/Projects/genecrew && uv run python -m pytest genecrew/tests/ -q`

---

### Task 1: Exposer le lieu des événements dans `EventFact`

Le spec fait reposer le filtrage Gallica et le facteur de concordance `lieu` sur une donnée que le modèle ne porte pas : `EventFact` n'a aucun champ de lieu. Vérifié contre l'API réelle, le `profile` **déjà demandé** par `FactsFetcher` (`profile=all`) contient le lieu — donc l'exposer ne coûte **aucune requête supplémentaire** :

```json
{"date": "1677-07-15", "place": "Montbéliard, Doubs, Bourgogne-Franche-Comté, France",
 "place_name": "Montbéliard", "citations": 0, "type": "Birth"}
```

Le lieu vit dans `profile.birth` / `profile.death`, alors que les `EventFact` sont construits depuis `extended.events`. Il faut donc le **surimposer** après coup, sur la naissance et le décès seulement.

**Files:**
- Modify: `/Users/fjacquet/Projects/crewai_custom_tools/src/crewai_custom_tools/tools/genealogy/models/domain.py` (classe `EventFact`)
- Modify: `/Users/fjacquet/Projects/crewai_custom_tools/src/crewai_custom_tools/tools/genealogy/gramps/facts.py` (`person_from_json`)
- Test: `/Users/fjacquet/Projects/crewai_custom_tools/tests/test_genealogy_facts.py`

**Interfaces:**
- Consumes: rien (première tâche).
- Produces: `EventFact.place: str` (hiérarchie complète, ex. `"Montbéliard, Doubs, …, France"`) et `EventFact.place_name: str` (commune seule, ex. `"Montbéliard"`), tous deux `""` par défaut. Peuplés **uniquement** sur `PersonFacts.birth` et `PersonFacts.death`.

- [ ] **Step 1: Écrire le test qui échoue**

Ajouter à `tests/test_genealogy_facts.py` :

```python
def test_person_from_json_expose_le_lieu_de_naissance_depuis_le_profile():
    raw = {"gramps_id": "I1234", "handle": "H1", "gender": 1,
           "primary_name": {"first_name": "Jean",
                            "surname_list": [{"surname": "Dupont"}]},
           "profile": {"birth": {"date": "1677-07-15", "citations": 0,
                                 "place": "Montbéliard, Doubs, Bourgogne-Franche-Comté, France",
                                 "place_name": "Montbéliard"},
                       "death": {}},
           "extended": {"events": [
               {"type": "Birth", "citation_list": [],
                "date": {"sortval": 2334000, "year": 1677,
                         "dateval": [15, 7, 1677, False], "modifier": 0, "quality": 0}}]},
           "birth_ref_index": 0, "death_ref_index": -1,
           "event_ref_list": [{"ref": "e1"}]}
    p = person_from_json(raw)
    assert p.birth.place == "Montbéliard, Doubs, Bourgogne-Franche-Comté, France"
    assert p.birth.place_name == "Montbéliard"


def test_person_from_json_lieu_absent_donne_chaine_vide():
    raw = {"gramps_id": "I2016", "handle": "H2", "gender": 1,
           "primary_name": {"first_name": "Silvain", "surname_list": [{"surname": "Roy"}]},
           "profile": {"birth": {"date": "about 1762-12", "citations": 0,
                                 "place": "", "place_name": ""}, "death": {}},
           "extended": {"events": [
               {"type": "Birth", "citation_list": [],
                "date": {"sortval": 0, "year": 1762, "dateval": [], "modifier": 3,
                         "quality": 0}}]},
           "birth_ref_index": 0, "death_ref_index": -1,
           "event_ref_list": [{"ref": "e1"}]}
    p = person_from_json(raw)
    assert p.birth.place == "" and p.birth.place_name == ""
```

- [ ] **Step 2: Lancer le test pour vérifier qu'il échoue**

Run: `cd /Users/fjacquet/Projects/crewai_custom_tools && uv run python -m pytest tests/test_genealogy_facts.py -q -k lieu`
Expected: FAIL — `AttributeError: 'EventFact' object has no attribute 'place'`

- [ ] **Step 3: Ajouter les deux champs au modèle**

Dans `domain.py`, classe `EventFact`, après `has_citation` :

```python
    place: str = ""                 # hiérarchie complète, depuis profile.<birth|death>.place
    place_name: str = ""            # commune seule, depuis profile.<birth|death>.place_name
```

- [ ] **Step 4: Surimposer le lieu dans `person_from_json`**

Dans `facts.py`, `person_from_json`, **après** la ligne `profile = raw.get("profile") or {}` et **avant** le `return` :

```python
    # Le lieu ne vit que dans le profile (chaînes lisibles), pas dans extended.events.
    # On le surimpose donc sur la naissance et le décès, seuls événements que le profile
    # décrit. Aucune requête supplémentaire : profile=all est déjà demandé.
    for fact, cle in ((birth, "birth"), (death, "death")):
        if fact is not None:
            bloc = profile.get(cle) or {}
            fact.place = bloc.get("place") or ""
            fact.place_name = bloc.get("place_name") or ""
```

- [ ] **Step 5: Lancer les tests**

Run: `cd /Users/fjacquet/Projects/crewai_custom_tools && uv run python -m pytest tests/ -q`
Expected: PASS — les deux nouveaux tests passent, et **aucun test existant ne régresse** (les champs ont un défaut, donc les fixtures sans lieu restent valides).

- [ ] **Step 6: Commit**

```bash
cd /Users/fjacquet/Projects/crewai_custom_tools
git add src/crewai_custom_tools/tools/genealogy/models/domain.py \
        src/crewai_custom_tools/tools/genealogy/gramps/facts.py \
        tests/test_genealogy_facts.py
git commit -m "feat(genealogy): exposer le lieu de naissance et de décès dans EventFact

Le profile demandé par FactsFetcher (profile=all) porte déjà place et
place_name ; ils étaient jetés. Les exposer ne coûte aucune requête
supplémentaire et débloque le filtrage géographique des pistes.

Surimposé sur birth/death seulement : le profile ne décrit que ces
deux événements, les autres viennent de extended.events."
```

---

### Task 2: Créer le paquet `pistes/` et y déménager MatchID

Établit le paquet et l'interface commune. Le déménagement se fait **à comportement identique** : les assertions des tests existants ne changent pas — c'est le critère qui prouve que rien n'a bougé.

**Files:**
- Create: `/Users/fjacquet/Projects/crewai_custom_tools/src/crewai_custom_tools/tools/genealogy/pistes/__init__.py`
- Create: `/Users/fjacquet/Projects/crewai_custom_tools/src/crewai_custom_tools/tools/genealogy/pistes/matchid.py`
- Create: `/Users/fjacquet/Projects/crewai_custom_tools/tests/test_genealogy_pistes_matchid.py`
- Modify: `/Users/fjacquet/Projects/genecrew/genecrew/src/genecrew/deces.py` (retirer `piste_depuis_match` et `_norm_nom`)
- Modify: `/Users/fjacquet/Projects/genecrew/genecrew/tests/test_deces_pistes.py` (importer `pistes_matchid` depuis la bibliothèque ; assertions inchangées)

**Interfaces:**
- Consumes: `EventFact.place` (Task 1) — non utilisé ici, mais le paquet en dépend pour les tâches suivantes.
- Produces:
  - `crewai_custom_tools.tools.genealogy.pistes.pistes_matchid(person: PersonFacts, match: dict, url: str) -> Piste`
  - `crewai_custom_tools.tools.genealogy.pistes.norm_nom(valeur: str) -> str` — normalisation partagée (sans accents, majuscules), réutilisée par les Tasks 3 et 5.
  - `crewai_custom_tools.tools.genealogy.pistes.event_iso(event: EventFact | None) -> str` — rend `"AAAA-MM-JJ"` si la date est complète, `"AAAA"` si l'année est seule, `""` sinon. **La longueur de la chaîne est ce qui distingue les deux** : c'est le mécanisme qui empêche une année seule de compter comme facteur.

- [ ] **Step 1: Écrire le test qui échoue**

Créer `tests/test_genealogy_pistes_matchid.py` :

```python
from crewai_custom_tools.tools.genealogy.models.domain import EventFact, PersonFacts
from crewai_custom_tools.tools.genealogy.pistes import event_iso, norm_nom, pistes_matchid


def _person(surname="DUPONT", given="Jean", birth_dateval=None):
    birth = EventFact(type="Birth", year=1900,
                      dateval=birth_dateval or [14, 7, 1900, False])
    return PersonFacts(gramps_id="I0042", handle="H42", name=f"{given} {surname}",
                       surname=surname, given=given, sex="M", birth=birth)


def test_norm_nom_retire_accents_et_majuscule():
    assert norm_nom("Mérigot") == "MERIGOT"


def test_event_iso_date_complete_fait_dix_caracteres():
    assert event_iso(EventFact(type="Birth", year=1900,
                               dateval=[14, 7, 1900, False])) == "1900-07-14"


def test_event_iso_annee_seule_fait_quatre_caracteres():
    assert event_iso(EventFact(type="Birth", year=1900, dateval=[0, 0, 1900, False])) == "1900"


def test_piste_forte_avec_nom_et_date_complete():
    match = {"id": "abc123", "name": {"last": "Dupont"},
             "birth": {"date": "19000714"}}
    piste = pistes_matchid(_person(), match, "https://deces.matchid.io/id/abc123")
    assert piste.source == "matchid" and piste.identite == "abc123"
    assert set(piste.concordances) == {"nom", "date complète"}
    assert piste.force == "forte"


def test_annee_seule_ne_donne_pas_de_second_facteur():
    # L'arbre ne connaît que l'année -> event_iso rend "1900" (4 car.), pas 10.
    person = _person(birth_dateval=[0, 0, 1900, False])
    match = {"id": "abc123", "name": {"last": "Dupont"}, "birth": {"date": "19000714"}}
    piste = pistes_matchid(person, match, "")
    assert piste.concordances == ["nom"]
    assert piste.force == "faible"


def test_dates_completes_differentes_donnent_une_divergence():
    match = {"id": "abc123", "name": {"last": "Dupont"}, "birth": {"date": "19010203"}}
    piste = pistes_matchid(_person(), match, "")
    assert piste.divergences == ["dates de naissance différentes"]
    assert piste.force == "faible"
```

- [ ] **Step 2: Lancer le test pour vérifier qu'il échoue**

Run: `cd /Users/fjacquet/Projects/crewai_custom_tools && uv run python -m pytest tests/test_genealogy_pistes_matchid.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'crewai_custom_tools.tools.genealogy.pistes'`

- [ ] **Step 3: Créer `pistes/matchid.py`**

```python
"""MatchID (INSEE décès) → Piste. Pure : n'écrit rien, ne conclut rien."""

import unicodedata

from crewai_custom_tools.tools.genealogy.models.domain import EventFact, PersonFacts, Piste


def norm_nom(valeur: str) -> str:
    """Sans accents, sans espaces de bord, en majuscules. Partagé par les sources."""
    sans = "".join(c for c in unicodedata.normalize("NFD", valeur or "")
                   if unicodedata.category(c) != "Mn")
    return sans.strip().upper()


def event_iso(event: EventFact | None) -> str:
    """"AAAA-MM-JJ" si la date est complète, "AAAA" si l'année est seule, "" sinon.

    La LONGUEUR distingue les deux cas, et c'est ce qui empêche une année seule de
    compter comme facteur de concordance : règle projet, une année n'est jamais
    discriminante (trop d'homonymes naissent la même année).

    COPIE EXACTE de genecrew/deces.py — ne pas « améliorer » en la déplaçant, sous
    peine de changer le comportement que les tests existants verrouillent.
    """
    if event is None or not event.year:
        return ""
    dv = event.dateval or []
    if len(dv) >= 3 and dv[0] and dv[1]:
        return f"{dv[2]:04d}-{dv[1]:02d}-{dv[0]:02d}"
    return f"{event.year:04d}"


def first_given(given: str) -> str:
    """Premier prénom, virgules de l'arbre retirées ('Paul, Marcel' -> 'Paul'). Pure.

    MatchID répond 422 sur 'Paul,'. COPIE EXACTE de genecrew/deces.py.
    """
    return (given.replace(",", " ").split() or [""])[0]


def pistes_matchid(person: PersonFacts, match: dict, url: str) -> Piste:
    """Transforme un résultat MatchID en piste. N'écrit rien, ne conclut rien.

    L'année de naissance seule ne compte PAS comme facteur : il faut une date
    complète (jour + mois + année) pour constituer un second facteur à côté du nom.
    """
    concordances: list[str] = []
    divergences: list[str] = []
    nom_insee = (match.get("name") or {}).get("last", "")
    if nom_insee and norm_nom(nom_insee) == norm_nom(person.surname):
        concordances.append("nom")
    naissance_insee = ((match.get("birth") or {}).get("date") or "")
    naissance_arbre = event_iso(person.birth)
    if len(naissance_insee) == 8 and len(naissance_arbre) == 10:
        iso_insee = f"{naissance_insee[:4]}-{naissance_insee[4:6]}-{naissance_insee[6:]}"
        if iso_insee == naissance_arbre:
            concordances.append("date complète")
        else:
            divergences.append("dates de naissance différentes")
    return Piste(
        gramps_id=person.gramps_id, handle=person.handle,
        source="matchid", identite=str(match.get("id") or ""),
        url=url or None,
        requete=f"nom={person.surname}&prenom={first_given(person.given)}",
        concordances=concordances, divergences=divergences,
    )
```

Puis `pistes/__init__.py` :

```python
"""Traduction « résultat d'archive → Piste ». Une fonction pure par source."""

from crewai_custom_tools.tools.genealogy.pistes.matchid import (
    event_iso,
    first_given,
    norm_nom,
    pistes_matchid,
)

__all__ = ["event_iso", "first_given", "norm_nom", "pistes_matchid"]
```

- [ ] **Step 4: Lancer les tests**

Run: `cd /Users/fjacquet/Projects/crewai_custom_tools && uv run python -m pytest tests/test_genealogy_pistes_matchid.py -q`
Expected: PASS (6 tests)

- [ ] **Step 5: Retirer le doublon de genecrew**

Dans `/Users/fjacquet/Projects/genecrew/genecrew/src/genecrew/deces.py` : **supprimer** les fonctions `_norm_nom` et `piste_depuis_match`.

**Aucun alias de compatibilité** : vérifié, `piste_depuis_match` n'a qu'un seul consommateur, son propre fichier de tests (`run_deces` ne l'appelle pas). Un alias serait du code mort.

Migrer donc `genecrew/tests/test_deces_pistes.py` — remplacer son import :

```python
from crewai_custom_tools.tools.genealogy.pistes import pistes_matchid
```

et les trois appels `piste_depuis_match(...)` par `pistes_matchid(...)`. **Ne toucher à aucune assertion** : c'est ce qui prouve que le déménagement n'a rien changé au comportement.

**Ne pas** supprimer les fonctions `event_iso` et `first_given` locales de `deces.py` si d'autres fonctions du module les utilisent — vérifier d'abord :

```bash
cd /Users/fjacquet/Projects/genecrew
grep -n 'event_iso\|first_given' genecrew/src/genecrew/deces.py
```

Si elles ne servent qu'à `piste_depuis_match`, les supprimer aussi ; sinon les laisser.

- [ ] **Step 6: Vérifier la non-régression de genecrew**

Run: `cd /Users/fjacquet/Projects/genecrew && uv run python -m pytest genecrew/tests/ -q`
Expected: PASS — **sans modifier aucune assertion existante**. Si un test échoue, c'est que le déménagement a changé le comportement : corriger le code, jamais le test.

- [ ] **Step 7: Commit (deux dépôts, deux commits)**

```bash
cd /Users/fjacquet/Projects/crewai_custom_tools
git add src/crewai_custom_tools/tools/genealogy/pistes/ tests/test_genealogy_pistes_matchid.py
git commit -m "feat(pistes): paquet pistes/ et déménagement de MatchID

Le docstring de Piste appelait la bibliothèque à héberger les sources ;
piste_depuis_match était resté dans genecrew, écrit avant l'extraction
du contrat. Il devient pistes_matchid, à comportement identique.

norm_nom et event_iso sont exposés : les sources suivantes en ont besoin."
```

```bash
cd /Users/fjacquet/Projects/genecrew
git add genecrew/src/genecrew/deces.py genecrew/tests/test_deces_pistes.py
git commit -m "refactor(deces): consommer pistes_matchid depuis la bibliothèque

Aucun alias : la fonction n'avait qu'un consommateur, son test."
```

---

### Task 3: `pistes_wikidata` — la seule source à pistes fortes

**Files:**
- Create: `/Users/fjacquet/Projects/crewai_custom_tools/src/crewai_custom_tools/tools/genealogy/pistes/wikidata.py`
- Modify: `/Users/fjacquet/Projects/crewai_custom_tools/src/crewai_custom_tools/tools/genealogy/pistes/__init__.py`
- Create: `/Users/fjacquet/Projects/crewai_custom_tools/tests/test_genealogy_pistes_wikidata.py`

**Interfaces:**
- Consumes: `norm_nom`, `event_iso` (Task 2) ; `EventFact.place_name` (Task 1).
- Produces:
  - `requete_wikidata(person: PersonFacts) -> str` — construit la requête SPARQL, **pure**. Rendue telle quelle dans `Piste.requete` pour être rejouable.
  - `pistes_wikidata(person: PersonFacts, resultats: list[dict]) -> list[Piste]` — `resultats` est ce que rend `sparql_rows()` : une liste de `{variable: valeur}`. Variables attendues : `item` (URI), `itemLabel`, `birthDate` (ISO), `birthPlaceLabel`, `p902` (optionnel).

- [ ] **Step 1: Écrire le test qui échoue**

Créer `tests/test_genealogy_pistes_wikidata.py` :

```python
from crewai_custom_tools.tools.genealogy.models.domain import EventFact, PersonFacts
from crewai_custom_tools.tools.genealogy.pistes import pistes_wikidata, requete_wikidata


def _person(surname="Dupont", given="Jean", dateval=None, place_name="Montbéliard"):
    birth = EventFact(type="Birth", year=1677, dateval=dateval or [15, 7, 1677, False],
                      place_name=place_name,
                      place=f"{place_name}, Doubs, France" if place_name else "")
    return PersonFacts(gramps_id="I1234", handle="H1", name=f"{given} {surname}",
                       surname=surname, given=given, sex="M", birth=birth)


def test_requete_passe_par_le_service_indexe_pas_par_un_filtre():
    # Un FILTER(CONTAINS(...)) sur rdfs:label balaie les ~10 M d'humains de
    # Wikidata et rend 504 après 65 s — mesuré. La recherche DOIT être indexée.
    q = requete_wikidata(_person())
    assert "Dupont" in q and "SELECT" in q.upper()
    assert "EntitySearch" in q and "wikibase:mwapi" in q
    assert "CONTAINS" not in q.upper()


def test_roy_ne_correspond_pas_a_leroy():
    """Le faux positif qui motive la comparaison par mots entiers."""
    person = _person(surname="Roy", given="Silvain")
    rows = [{"item": "http://www.wikidata.org/entity/Q99", "itemLabel": "Silvain Leroy",
             "birthDate": "1677-07-15T00:00:00Z", "birthPlaceLabel": "Montbéliard"}]
    assert "nom" not in pistes_wikidata(person, rows)[0].concordances


def test_prenom_en_liste_a_virgules_correspond_au_prenom_d_usage():
    # 20 % de l'arbre : 'Marcel, Hubert, Andre' = trois prénoms, pas un composé.
    person = _person(surname="Soulat", given="Marcel, Hubert, Andre")
    rows = [{"item": "http://www.wikidata.org/entity/Q99", "itemLabel": "Marcel Soulat",
             "birthDate": "1677-07-15T00:00:00Z", "birthPlaceLabel": "Montbéliard"}]
    assert "nom" in pistes_wikidata(person, rows)[0].concordances


def test_trait_d_union_eclate_correspond_a_la_forme_espacee():
    # Cas réel vérifié : la recherche 'Guillaume-Henri Dufour' rend le libellé
    # Wikidata 'Guillaume Henri Dufour'. Sans éclatement, vrai positif perdu.
    person = _person(surname="Dufour", given="Guillaume-Henri")
    rows = [{"item": "http://www.wikidata.org/entity/Q99",
             "itemLabel": "Guillaume Henri Dufour",
             "birthDate": "1677-07-15T00:00:00Z", "birthPlaceLabel": "Montbéliard"}]
    assert "nom" in pistes_wikidata(person, rows)[0].concordances


def test_accents_ne_font_pas_diverger_les_prenoms():
    # L'arbre porte 'Andre' comme 'André' : norm_nom les rejoint.
    person = _person(surname="Soulat", given="Andre")
    rows = [{"item": "http://www.wikidata.org/entity/Q99", "itemLabel": "André Soulat",
             "birthDate": "1677-07-15T00:00:00Z", "birthPlaceLabel": "Montbéliard"}]
    assert "nom" in pistes_wikidata(person, rows)[0].concordances


def test_piste_forte_nom_date_complete_et_lieu():
    rows = [{"item": "http://www.wikidata.org/entity/Q42",
             "itemLabel": "Jean Dupont",
             "birthDate": "1677-07-15T00:00:00Z",
             "birthPlaceLabel": "Montbéliard"}]
    pistes = pistes_wikidata(_person(), rows)
    assert len(pistes) == 1
    p = pistes[0]
    assert p.source == "wikidata" and p.identite == "Q42"
    assert p.url == "http://www.wikidata.org/entity/Q42"
    assert set(p.concordances) == {"nom", "date complète", "lieu"}
    assert p.force == "forte"


def test_date_divergente_rend_la_piste_faible():
    rows = [{"item": "http://www.wikidata.org/entity/Q42", "itemLabel": "Jean Dupont",
             "birthDate": "1680-01-02T00:00:00Z", "birthPlaceLabel": "Montbéliard"}]
    p = pistes_wikidata(_person(), rows)[0]
    assert "dates de naissance différentes" in p.divergences
    assert p.force == "faible"


def test_annee_seule_dans_l_arbre_ne_compte_pas_comme_date():
    person = _person(dateval=[0, 0, 1677, False])
    rows = [{"item": "http://www.wikidata.org/entity/Q42", "itemLabel": "Jean Dupont",
             "birthDate": "1677-07-15T00:00:00Z", "birthPlaceLabel": "Montbéliard"}]
    p = pistes_wikidata(person, rows)[0]
    assert "date complète" not in p.concordances


def test_lieu_absent_de_l_arbre_ne_compte_pas():
    person = _person(place_name="")
    rows = [{"item": "http://www.wikidata.org/entity/Q42", "itemLabel": "Jean Dupont",
             "birthDate": "1677-07-15T00:00:00Z", "birthPlaceLabel": "Montbéliard"}]
    p = pistes_wikidata(person, rows)[0]
    assert "lieu" not in p.concordances


def test_aucun_resultat_rend_liste_vide():
    assert pistes_wikidata(_person(), []) == []
```

- [ ] **Step 2: Lancer le test pour vérifier qu'il échoue**

Run: `cd /Users/fjacquet/Projects/crewai_custom_tools && uv run python -m pytest tests/test_genealogy_pistes_wikidata.py -q`
Expected: FAIL — `ImportError: cannot import name 'pistes_wikidata'`

- [ ] **Step 3: Écrire `pistes/wikidata.py`**

```python
"""Wikidata → Piste. Pure : la collecte passe par sparql_rows(), pas par ce module.

Seule source capable de pistes FORTES : ses propriétés sont structurées, donc on
peut en tirer plusieurs facteurs distincts. Réserve connue : Wikidata ne décrit
que des personnes notables, le rendement sur un arbre ordinaire sera faible.
"""

import re

from crewai_custom_tools.tools.genealogy.models.domain import PersonFacts, Piste
from crewai_custom_tools.tools.genealogy.pistes.matchid import event_iso, norm_nom

# La recherche passe par le service INDEXÉ (mwapi/EntitySearch), jamais par un
# FILTER(CONTAINS(…)) sur rdfs:label : mesuré, ce dernier balaie les ~10 M d'humains
# de Wikidata et rend 504 Gateway Timeout après 65 s sur le point d'accès public.
# La version ci-dessous répond en ~0,9 s. Vérifiée en direct, pas supposée.
_SPARQL = """SELECT ?item ?itemLabel ?birthDate ?birthPlaceLabel ?p902 WHERE {{
  SERVICE wikibase:mwapi {{
    bd:serviceParam wikibase:api "EntitySearch" .
    bd:serviceParam wikibase:endpoint "www.wikidata.org" .
    bd:serviceParam mwapi:search "{nom}" .
    bd:serviceParam mwapi:language "fr" .
    bd:serviceParam mwapi:limit 25 .
    ?item wikibase:apiOutputItem mwapi:item .
  }}
  ?item wdt:P31 wd:Q5 .
  OPTIONAL {{ ?item wdt:P569 ?birthDate . }}
  OPTIONAL {{ ?item wdt:P19 ?birthPlace . }}
  OPTIONAL {{ ?item wdt:P902 ?p902 . }}
  SERVICE wikibase:label {{ bd:serviceParam wikibase:language "fr,de,en". }}
}} LIMIT 25"""

_SEPARATEURS = re.compile(r"[,\-\s]+")


def mots(valeur: str) -> set[str]:
    """Découpe un nom en mots normalisés : virgules, espaces ET traits d'union.

    Mesuré sur l'arbre : 79 % des prénoms sont simples, 20 % sont des LISTES
    séparées par des virgules ('Marcel, Hubert, Andre' = trois prénoms distincts,
    pas un composé), 1 % portent un trait d'union ('Georges-Frédéric').

    Le trait d'union est éclaté volontairement : Wikidata répond
    'Guillaume Henri Dufour' à une recherche 'Guillaume-Henri Dufour' — vérifié.
    Sans éclatement, ce vrai positif serait perdu. Le patronyme devant lui aussi
    correspondre, la permissivité sur le prénom ne coûte rien.
    """
    return {norm_nom(m) for m in _SEPARATEURS.split(valeur or "") if m.strip()}


def requete_wikidata(person: PersonFacts) -> str:
    """La requête SPARQL exacte, rejouable telle quelle. Pure."""
    nom = f"{person.given} {person.surname}".strip()
    return _SPARQL.format(nom=nom.replace('"', ""))


def q_item(uri: str) -> str:
    """"http://www.wikidata.org/entity/Q42" -> "Q42". Chaîne vide si non reconnaissable."""
    return uri.rsplit("/", 1)[-1] if uri else ""


def pistes_wikidata(person: PersonFacts, resultats: list[dict]) -> list[Piste]:
    """Une piste par résultat SPARQL. N'écrit rien, ne conclut rien."""
    requete = requete_wikidata(person)
    naissance_arbre = event_iso(person.birth)
    lieu_arbre = person.birth.place_name if person.birth else ""
    pistes: list[Piste] = []
    for row in resultats:
        identite = q_item(row.get("item", ""))
        if not identite:
            continue
        concordances: list[str] = []
        divergences: list[str] = []

        # Comparaison par MOTS ENTIERS des deux côtés, jamais par sous-chaîne :
        # `norm_nom(surname) in norm_nom(label)` ferait correspondre « Roy » à
        # « LEROY » et fabriquerait des pistes fortes fausses — or une piste forte
        # est ÉCRITE dans l'arbre, une faible reste dans le rapport.
        # On exige le patronyme ET au moins un prénom commun.
        mots_label = mots(row.get("itemLabel", ""))
        if mots_label and mots(person.surname) <= mots_label and (
                mots(person.given) & mots_label):
            concordances.append("nom")

        # wdt:P569 rend un dateTime complet quelle que soit la précision réelle ;
        # on ne compare donc que les 10 premiers caractères, et seulement si
        # l'arbre porte lui aussi une date COMPLÈTE (10 caractères).
        naissance_wd = (row.get("birthDate") or "")[:10]
        if len(naissance_wd) == 10 and len(naissance_arbre) == 10:
            if naissance_wd == naissance_arbre:
                concordances.append("date complète")
            else:
                divergences.append("dates de naissance différentes")

        lieu_wd = row.get("birthPlaceLabel", "")
        if lieu_arbre and lieu_wd and norm_nom(lieu_arbre) == norm_nom(lieu_wd):
            concordances.append("lieu")

        pistes.append(Piste(
            gramps_id=person.gramps_id, handle=person.handle,
            source="wikidata", identite=identite,
            url=row.get("item") or None,
            requete=requete,
            concordances=concordances, divergences=divergences,
        ))
    return pistes
```

Ajouter aux ré-exports de `pistes/__init__.py` :

```python
from crewai_custom_tools.tools.genealogy.pistes.wikidata import (
    mots,
    pistes_wikidata,
    q_item,
    requete_wikidata,
)
```

et à `__all__` : `"mots", "pistes_wikidata", "q_item", "requete_wikidata"`.

- [ ] **Step 4: Lancer les tests**

Run: `cd /Users/fjacquet/Projects/crewai_custom_tools && uv run python -m pytest tests/test_genealogy_pistes_wikidata.py -q`
Expected: PASS (6 tests)

- [ ] **Step 5: Commit**

```bash
cd /Users/fjacquet/Projects/crewai_custom_tools
git add src/crewai_custom_tools/tools/genealogy/pistes/ tests/test_genealogy_pistes_wikidata.py
git commit -m "feat(pistes): source Wikidata, la seule à produire des pistes fortes

wdt:P569 rend un dateTime complet quelle que soit la précision réelle :
on tronque à 10 caractères et on n'invoque « date complète » que si
l'arbre porte lui aussi une date complète."
```

---

### Task 4: `pistes_dhs` — une projection de Wikidata via P902

Le DHS n'est pas une API : la propriété Wikidata **P902** (« HDS ID », vérifiée) porte l'identifiant du *Dictionnaire historique de la Suisse*. Une piste DHS dérive donc d'une ligne SPARQL qui porte `p902`.

**Files:**
- Create: `/Users/fjacquet/Projects/crewai_custom_tools/src/crewai_custom_tools/tools/genealogy/pistes/dhs.py`
- Modify: `/Users/fjacquet/Projects/crewai_custom_tools/src/crewai_custom_tools/tools/genealogy/pistes/__init__.py`
- Create: `/Users/fjacquet/Projects/crewai_custom_tools/tests/test_genealogy_pistes_dhs.py`

**Interfaces:**
- Consumes: `pistes_wikidata`, `requete_wikidata` (Task 3).
- Produces: `pistes_dhs(person: PersonFacts, resultats: list[dict]) -> list[Piste]` — même `resultats` que Task 3 ; ne retient que les lignes portant `p902`. `source="dhs"`, `identite` = l'identifiant HDS, `url` = `https://hls-dhs-dss.ch/fr/articles/<id>/`.

- [ ] **Step 1: Écrire le test qui échoue**

Créer `tests/test_genealogy_pistes_dhs.py` :

```python
from crewai_custom_tools.tools.genealogy.models.domain import EventFact, PersonFacts
from crewai_custom_tools.tools.genealogy.pistes import pistes_dhs


def _person():
    birth = EventFact(type="Birth", year=1800, dateval=[3, 4, 1800, False],
                      place_name="Lausanne", place="Lausanne, Vaud, Suisse")
    return PersonFacts(gramps_id="I0500", handle="H5", name="Louis Perret",
                       surname="Perret", given="Louis", sex="M", birth=birth)


def test_ligne_sans_p902_ne_produit_aucune_piste():
    rows = [{"item": "http://www.wikidata.org/entity/Q42", "itemLabel": "Louis Perret",
             "birthDate": "1800-04-03T00:00:00Z", "birthPlaceLabel": "Lausanne"}]
    assert pistes_dhs(_person(), rows) == []


def test_ligne_avec_p902_produit_une_piste_dhs():
    rows = [{"item": "http://www.wikidata.org/entity/Q42", "itemLabel": "Louis Perret",
             "birthDate": "1800-04-03T00:00:00Z", "birthPlaceLabel": "Lausanne",
             "p902": "012345"}]
    pistes = pistes_dhs(_person(), rows)
    assert len(pistes) == 1
    p = pistes[0]
    assert p.source == "dhs"
    assert p.identite == "012345"
    assert p.url == "https://hls-dhs-dss.ch/fr/articles/012345/"
    # Les concordances sont héritées de la ligne Wikidata dont elle dérive.
    assert set(p.concordances) == {"nom", "date complète", "lieu"}
    assert p.force == "forte"
```

- [ ] **Step 2: Lancer le test pour vérifier qu'il échoue**

Run: `cd /Users/fjacquet/Projects/crewai_custom_tools && uv run python -m pytest tests/test_genealogy_pistes_dhs.py -q`
Expected: FAIL — `ImportError: cannot import name 'pistes_dhs'`

- [ ] **Step 3: Écrire `pistes/dhs.py`**

```python
"""DHS (Dictionnaire historique de la Suisse) → Piste.

Pas une API de plus : la propriété Wikidata P902 porte l'identifiant HDS, dont
les articles existent en allemand, français et italien sous le même identifiant.
Ce module est donc une PROJECTION de la source Wikidata, pas un client.
"""

from crewai_custom_tools.tools.genealogy.models.domain import PersonFacts, Piste
from crewai_custom_tools.tools.genealogy.pistes.wikidata import pistes_wikidata

_ARTICLE = "https://hls-dhs-dss.ch/fr/articles/{id}/"


def pistes_dhs(person: PersonFacts, resultats: list[dict]) -> list[Piste]:
    """Une piste DHS par ligne SPARQL portant un P902. Les autres sont ignorées.

    On dérive ligne par ligne plutôt que d'apparier deux listes : `pistes_wikidata`
    saute les lignes dont l'URI n'est pas exploitable, donc un appariement
    positionnel décalerait silencieusement les identifiants HDS.
    """
    pistes: list[Piste] = []
    for row in resultats:
        identifiant = row.get("p902")
        if not identifiant:
            continue
        base = pistes_wikidata(person, [row])
        if not base:                      # URI Wikidata inexploitable -> on passe
            continue
        pistes.append(Piste(
            gramps_id=person.gramps_id, handle=person.handle,
            source="dhs", identite=identifiant,
            url=_ARTICLE.format(id=identifiant),
            requete=base[0].requete,
            concordances=list(base[0].concordances),
            divergences=list(base[0].divergences),
        ))
    return pistes
```

Ajouter aux ré-exports de `pistes/__init__.py` :

```python
from crewai_custom_tools.tools.genealogy.pistes.dhs import pistes_dhs
```

et à `__all__` : `"pistes_dhs"`.

- [ ] **Step 4: Lancer les tests**

Run: `cd /Users/fjacquet/Projects/crewai_custom_tools && uv run python -m pytest tests/test_genealogy_pistes_dhs.py -q`
Expected: PASS (2 tests)

- [ ] **Step 5: Commit**

```bash
cd /Users/fjacquet/Projects/crewai_custom_tools
git add src/crewai_custom_tools/tools/genealogy/pistes/ tests/test_genealogy_pistes_dhs.py
git commit -m "feat(pistes): source DHS, projection de Wikidata via P902

Le DHS n'est pas un protocole : P902 porte son identifiant sur le Q-item.
Les concordances sont héritées de la ligne Wikidata dont la piste dérive."
```

---

### Task 5: `pistes_gallica` — presse, sur personne déjà identifiée

Gallica ne sert pas à *retrouver* une personne mais à *contextualiser* une personne **déjà identifiée**. On n'émet donc rien si la date **et** le lieu ne sont pas connus. Les pistes seront presque toujours `faible` : c'est correct et voulu.

**Files:**
- Create: `/Users/fjacquet/Projects/crewai_custom_tools/src/crewai_custom_tools/tools/genealogy/pistes/gallica.py`
- Modify: `/Users/fjacquet/Projects/crewai_custom_tools/src/crewai_custom_tools/tools/genealogy/pistes/__init__.py`
- Create: `/Users/fjacquet/Projects/crewai_custom_tools/tests/test_genealogy_pistes_gallica.py`

**Interfaces:**
- Consumes: `norm_nom`, `event_iso` (Task 2) ; `EventFact.place_name` (Task 1).
- Produces:
  - `personne_eligible(person: PersonFacts) -> bool` — vraie si la date de naissance **et** le lieu sont connus.
  - `requete_gallica(person: PersonFacts) -> str` — la requête CQL exacte, rejouable.
  - `fenetre_vie(person: PersonFacts) -> tuple[int, int]` — `(année_min, année_max)`. Sans décès, `année_max = année_naissance + 105` (la borne de R2).
  - `dates_du_texte(texte: str) -> set[str]` — toutes les dates COMPLÈTES en ISO ; une année seule n'est jamais rendue.
  - `date_concordante(person: PersonFacts, rec: dict) -> bool` — le titre porte-t-il une date complète égale à la naissance ou au décès.
  - `pistes_gallica(person: PersonFacts, resultats: list[dict]) -> list[Piste]` — `resultats` = la clé `records` de `parse_sru()`, soit des `{"title", "creator", "date", "type", "url"}`.

- [ ] **Step 1: Écrire le test qui échoue**

Créer `tests/test_genealogy_pistes_gallica.py` :

```python
from crewai_custom_tools.tools.genealogy.models.domain import EventFact, PersonFacts
from crewai_custom_tools.tools.genealogy.pistes import (
    fenetre_vie, personne_eligible, pistes_gallica, requete_gallica,
)


def _person(dateval=None, place_name="Montbéliard", deces_annee=None):
    birth = EventFact(type="Birth", year=1900, dateval=dateval or [14, 7, 1900, False],
                      place_name=place_name,
                      place=f"{place_name}, Doubs, France" if place_name else "")
    death = (EventFact(type="Death", year=deces_annee,
                       dateval=[1, 1, deces_annee, False]) if deces_annee else None)
    return PersonFacts(gramps_id="I0042", handle="H42", name="Jean Dupont",
                       surname="Dupont", given="Jean", sex="M", birth=birth, death=death)


def test_personne_sans_lieu_est_ineligible():
    assert personne_eligible(_person(place_name="")) is False


def test_personne_sans_date_complete_est_ineligible():
    assert personne_eligible(_person(dateval=[0, 0, 1900, False])) is False


def test_personne_datee_et_localisee_est_eligible():
    assert personne_eligible(_person()) is True


def test_fenetre_sans_deces_borne_a_cent_cinq_ans():
    assert fenetre_vie(_person()) == (1900, 2005)


def test_fenetre_avec_deces_utilise_l_annee_du_deces():
    assert fenetre_vie(_person(deces_annee=1970)) == (1900, 1970)


def test_requete_contient_nom_et_lieu():
    q = requete_gallica(_person())
    assert "Dupont" in q and "Montbéliard" in q


def test_resultat_hors_fenetre_est_ecarte():
    records = [{"title": "Le Journal", "creator": "", "date": "2020",
                "type": "text", "url": "https://gallica.bnf.fr/ark:/12148/bpt6k1"}]
    assert pistes_gallica(_person(deces_annee=1970), records) == []


def test_resultat_dans_la_fenetre_donne_une_piste_faible():
    records = [{"title": "Le Journal de Montbéliard", "creator": "", "date": "1935",
                "type": "text", "url": "https://gallica.bnf.fr/ark:/12148/bpt6k1"}]
    pistes = pistes_gallica(_person(deces_annee=1970), records)
    assert len(pistes) == 1
    p = pistes[0]
    assert p.source == "gallica"
    assert p.identite == "ark:/12148/bpt6k1"
    assert p.identite_derivee is False
    assert p.url == "https://gallica.bnf.fr/ark:/12148/bpt6k1"
    assert p.force == "faible"


def test_nom_et_lieu_dans_le_meme_titre_ne_font_qu_un_facteur():
    """Le titre est UNE preuve. Sans cette règle, « Le Journal de Montbéliard »
    rendrait FORTE une piste pour un Dupont né à Montbéliard — donc écrite
    dans l'arbre — sans qu'aucune identité n'ait été vérifiée."""
    records = [{"title": "Dupont et le Journal de Montbéliard", "creator": "",
                "date": "1935", "type": "text",
                "url": "https://gallica.bnf.fr/ark:/12148/bpt6k1"}]
    p = pistes_gallica(_person(deces_annee=1970), records)[0]
    assert len(set(p.concordances)) == 1
    assert p.force == "faible"


def test_titre_portant_la_date_complete_atteint_forte():
    records = [{"title": "Dupont — acte du 14 juillet 1900", "creator": "",
                "date": "1935", "type": "text",
                "url": "https://gallica.bnf.fr/ark:/12148/bpt6k1"}]
    p = pistes_gallica(_person(deces_annee=1970), records)[0]
    assert set(p.concordances) == {"nom", "date complète"}
    assert p.force == "forte"


def test_roy_ne_correspond_pas_a_leroy_dans_un_titre():
    person = _person(dateval=[14, 7, 1900, False], place_name="Montbéliard")
    person.surname = "Roy"
    records = [{"title": "Le Leroy de Belfort", "creator": "", "date": "1935",
                "type": "text", "url": "https://gallica.bnf.fr/ark:/12148/bpt6k1"}]
    assert pistes_gallica(person, records)[0].concordances == []


def test_annee_seule_dans_le_titre_n_est_pas_une_date():
    assert dates_du_texte("Le Journal de 1900") == set()
    assert dates_du_texte("acte du 14/07/1900") == {"1900-07-14"}
    assert dates_du_texte("acte du 1900-07-14") == {"1900-07-14"}


def test_personne_ineligible_ne_produit_rien():
    records = [{"title": "Le Journal", "creator": "", "date": "1935",
                "type": "text", "url": "https://gallica.bnf.fr/ark:/12148/bpt6k1"}]
    assert pistes_gallica(_person(place_name=""), records) == []


def test_resultat_sans_ark_est_ecarte():
    # Jamais d'URL fabriquée : sans permalien, pas de piste.
    records = [{"title": "Le Journal", "creator": "", "date": "1935",
                "type": "text", "url": ""}]
    assert pistes_gallica(_person(), records) == []
```

- [ ] **Step 2: Lancer le test pour vérifier qu'il échoue**

Run: `cd /Users/fjacquet/Projects/crewai_custom_tools && uv run python -m pytest tests/test_genealogy_pistes_gallica.py -q`
Expected: FAIL — `ImportError: cannot import name 'pistes_gallica'`

- [ ] **Step 3: Écrire `pistes/gallica.py`**

```python
"""Gallica (BnF) → Piste. Pure : la collecte passe par GallicaSearchTool.

La presse ne sert pas à RETROUVER une personne mais à la CONTEXTUALISER : on
n'émet que pour des personnes dont la date ET le lieu sont connus, et ces
bornes filtrent les résultats. Les pistes seront presque toujours faibles —
un journal donne le nom, jamais une date d'état civil. C'est voulu.
"""

import re

from crewai_custom_tools.tools.genealogy.models.domain import PersonFacts, Piste
from crewai_custom_tools.tools.genealogy.pistes.matchid import event_iso, norm_nom
from crewai_custom_tools.tools.genealogy.pistes.wikidata import mots

_AGE_MAX = 105  # la borne de R2 : au-delà, l'audit signale déjà une anomalie
_ARK = re.compile(r"(ark:/\d+/[A-Za-z0-9]+)")


def personne_eligible(person: PersonFacts) -> bool:
    """Date de naissance COMPLÈTE et lieu connus — sinon on n'interroge pas."""
    if person.birth is None:
        return False
    return len(event_iso(person.birth)) == 10 and bool(person.birth.place_name)


def fenetre_vie(person: PersonFacts) -> tuple[int, int]:
    """(année_min, année_max). Sans décès connu, on borne à 105 ans."""
    debut = person.birth.year if person.birth and person.birth.year else 0
    if person.death is not None and person.death.year:
        return debut, person.death.year
    return debut, debut + _AGE_MAX


def requete_gallica(person: PersonFacts) -> str:
    """La requête CQL exacte, rejouable telle quelle."""
    lieu = person.birth.place_name if person.birth else ""
    return f'gallica all "{person.surname} {person.given} {lieu}"'.strip()


def ark_de(url: str) -> str:
    """Extrait l'ark d'une URL Gallica. Chaîne vide si absent — jamais fabriqué."""
    trouve = _ARK.search(url or "")
    return trouve.group(1) if trouve else ""


def _annee(valeur: str) -> int | None:
    trouve = re.search(r"\d{4}", valeur or "")
    return int(trouve.group(0)) if trouve else None


_MOIS = {
    "janvier": 1, "fevrier": 2, "mars": 3, "avril": 4, "mai": 5, "juin": 6,
    "juillet": 7, "aout": 8, "septembre": 9, "octobre": 10, "novembre": 11,
    "decembre": 12,
}
_DATE_NUM = re.compile(r"\b(\d{1,2})[/-](\d{1,2})[/-](\d{4})\b")
_DATE_ISO = re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b")
_DATE_TXT = re.compile(r"\b(\d{1,2})\s+([A-Za-zÉÛéûàç]+)\s+(\d{4})\b")


def dates_du_texte(texte: str) -> set[str]:
    """Toutes les dates COMPLÈTES d'un texte, en ISO. Pure.

    Trois formes rencontrées dans les titres de presse : « 14/07/1900 »,
    « 1900-07-14 » et « 14 juillet 1900 ». Une année seule n'est jamais
    rendue — elle ne constitue pas une date (règle cardinale du projet).
    """
    trouvees: set[str] = set()
    for j, m, a in _DATE_NUM.findall(texte or ""):
        trouvees.add(f"{int(a):04d}-{int(m):02d}-{int(j):02d}")
    for a, m, j in _DATE_ISO.findall(texte or ""):
        trouvees.add(f"{int(a):04d}-{int(m):02d}-{int(j):02d}")
    for j, mot, a in _DATE_TXT.findall(texte or ""):
        mois = _MOIS.get(norm_nom(mot).lower())
        if mois:
            trouvees.add(f"{int(a):04d}-{mois:02d}-{int(j):02d}")
    return trouvees


def date_concordante(person: PersonFacts, rec: dict) -> bool:
    """Le titre porte-t-il une date complète égale à la naissance ou au décès ?

    C'est le SEUL moyen pour une piste Gallica d'atteindre « forte » : le titre
    ne fournissant qu'un facteur (voir `pistes_gallica`), il en faut un second,
    et seule une date complète en est un. En pratique un titre de presse en
    porte rarement une — c'est assumé : la presse contextualise, elle n'identifie pas.
    """
    du_titre = dates_du_texte(rec.get("title", ""))
    if not du_titre:
        return False
    attendues = {event_iso(person.birth), event_iso(person.death)}
    return bool(du_titre & {d for d in attendues if len(d) == 10})


def pistes_gallica(person: PersonFacts, resultats: list[dict]) -> list[Piste]:
    """Une piste par enregistrement SRU retenu. N'écrit rien, ne conclut rien."""
    if not personne_eligible(person):
        return []
    debut, fin = fenetre_vie(person)
    requete = requete_gallica(person)
    lieu_arbre = person.birth.place_name if person.birth else ""
    pistes: list[Piste] = []
    for rec in resultats:
        # Sans ark, pas de permalien : on n'invente pas d'URL (cf. Mémoire des hommes).
        identite = ark_de(rec.get("url", ""))
        if not identite:
            continue
        annee = _annee(rec.get("date", ""))
        if annee is None or not (debut <= annee <= fin):
            continue
        # Le titre est UNE preuve, pas deux. `nom` et `lieu` en sont tous deux
        # extraits : les compter séparément ferait basculer « Le Journal de
        # Montbéliard » en piste FORTE pour un Dupont né à Montbéliard — donc
        # écrite dans l'arbre — sans qu'aucune identité n'ait été vérifiée.
        # Le titre ne contribue donc qu'un seul facteur ; seule une date
        # complète concordante peut en apporter un second.
        # Comparaison par MOTS ENTIERS, jamais par sous-chaîne (« Roy »/« LEROY »).
        concordances: list[str] = []
        mots_titre = mots(rec.get("title", ""))
        if mots(person.surname) and mots(person.surname) <= mots_titre:
            concordances.append("nom")
        elif lieu_arbre and mots(lieu_arbre) <= mots_titre:
            concordances.append("lieu")
        if date_concordante(person, rec):
            concordances.append("date complète")
        pistes.append(Piste(
            gramps_id=person.gramps_id, handle=person.handle,
            source="gallica", identite=identite, identite_derivee=False,
            url=rec.get("url") or None,
            requete=requete,
            concordances=concordances, divergences=[],
        ))
    return pistes
```

Ajouter aux ré-exports de `pistes/__init__.py` :

```python
from crewai_custom_tools.tools.genealogy.pistes.gallica import (
    ark_de, date_concordante, dates_du_texte, fenetre_vie, personne_eligible,
    pistes_gallica, requete_gallica,
)
```

et à `__all__` : `"ark_de", "date_concordante", "dates_du_texte", "fenetre_vie", "personne_eligible", "pistes_gallica", "requete_gallica"`.

- [ ] **Step 4: Lancer les tests**

Run: `cd /Users/fjacquet/Projects/crewai_custom_tools && uv run python -m pytest tests/test_genealogy_pistes_gallica.py -q`
Expected: PASS (10 tests)

- [ ] **Step 5: Commit**

```bash
cd /Users/fjacquet/Projects/crewai_custom_tools
git add src/crewai_custom_tools/tools/genealogy/pistes/ tests/test_genealogy_pistes_gallica.py
git commit -m "feat(pistes): source Gallica, contextualisation sur personne identifiée

N'émet que si la date ET le lieu sont connus, et filtre les résultats
sur la fenêtre de vie. Sans ark dans l'URL, aucune piste : on n'invente
pas de permalien."
```

---

### Task 6: Livrer la bibliothèque (bump, tag, push)

**Sans cette tâche, la CI de genecrew ne peut pas verdir** : elle checkoute le voisin sur le tag `v<version>` lu dans `uv.lock`, pas sur `main`.

**Files:**
- Modify: `/Users/fjacquet/Projects/crewai_custom_tools/pyproject.toml` (champ `version`)
- Modify: `/Users/fjacquet/Projects/crewai_custom_tools/CLAUDE.md` (compte de tests, mention du paquet `pistes/`)

**Interfaces:**
- Consumes: Tasks 1-5.
- Produces: le tag `v0.21.0`, consommable par `uv.lock` de genecrew (Task 7).

- [ ] **Step 1: Suite complète et lint**

```bash
cd /Users/fjacquet/Projects/crewai_custom_tools
uv run python -m pytest tests/ -q
uv run ruff check .
```

Expected: tous les tests passent, ruff ne signale rien.

- [ ] **Step 2: Bump de version**

Dans `pyproject.toml`, passer `version` à `0.21.0` (mineure : ajout de fonctionnalité, `EventFact` étendu de façon rétro-compatible).

- [ ] **Step 3: Mettre à jour le CLAUDE.md de la bibliothèque**

Mettre à jour le compte de tests (le relever de la sortie de l'étape 1) et ajouter une ligne décrivant `tools/genealogy/pistes/` — une fonction pure par source, sans réseau.

- [ ] **Step 4: Commit, tag et push**

```bash
cd /Users/fjacquet/Projects/crewai_custom_tools
git add pyproject.toml CLAUDE.md
git commit -m "chore(release): 0.21.0 — sources de pistes Wikidata, DHS et Gallica"
git tag v0.21.0
git push origin main --tags
```

Expected: le tag `v0.21.0` existe sur le distant.

---

### Task 7: Les trois feuilles CLI dans genecrew

**Files:**
- Create: `/Users/fjacquet/Projects/genecrew/genecrew/src/genecrew/archives.py`
- Modify: `/Users/fjacquet/Projects/genecrew/genecrew/src/genecrew/cli.py` (sous `propose`)
- Modify: `/Users/fjacquet/Projects/genecrew/genecrew/src/genecrew/main.py` (table de dispatch + trois `*_cmd`)
- Modify: `/Users/fjacquet/Projects/genecrew/uv.lock` (via `uv sync`)
- Test: `/Users/fjacquet/Projects/genecrew/genecrew/tests/test_cli_parser.py`
- Create: `/Users/fjacquet/Projects/genecrew/genecrew/tests/test_archives.py`

**Interfaces:**
- Consumes: `pistes_wikidata`, `pistes_dhs`, `pistes_gallica`, `requete_wikidata`, `personne_eligible` (bibliothèque 0.21.0) ; `consigner(client, piste, *, dry_run)` et `render_rapport_pistes(pistes, date, *, dry_run)` (`genecrew.pistes`, déjà livrés).
- Produces: `run_archives(client, source, scope, output_dir, *, date, batch_size=25, limit=None, dry_run=False) -> Path` — rend le chemin du rapport Markdown.

- [ ] **Step 1: Synchroniser la dépendance**

```bash
cd /Users/fjacquet/Projects/genecrew
uv sync
grep -A2 'name = "crewai-custom-tools"' uv.lock | head -5
```

Expected: la version résolue est `0.21.0`.

- [ ] **Step 2: Écrire le test de parseur qui échoue**

Ajouter à `genecrew/tests/test_cli_parser.py` :

```python
import pytest

from genecrew.cli import build_parser


@pytest.mark.parametrize("cible", ["wikidata", "dhs", "gallica"])
def test_propose_accepte_les_trois_sources_d_archives(cible):
    args = build_parser().parse_args(["propose", cible, "--scope", "all"])
    assert args.command == "propose" and args.target == cible


def test_propose_scriptorium_est_refuse():
    # La source a été écartée : voir docs/BACKLOG.md.
    with pytest.raises(SystemExit):
        build_parser().parse_args(["propose", "scriptorium"])
```

- [ ] **Step 3: Lancer le test pour vérifier qu'il échoue**

Run: `cd /Users/fjacquet/Projects/genecrew && uv run python -m pytest genecrew/tests/test_cli_parser.py -q -k archives`
Expected: FAIL — `SystemExit: 2` (`invalid choice: 'wikidata'`)

- [ ] **Step 4: Ajouter les trois feuilles au parseur**

Dans `cli.py`, après la feuille `gender` du bloc `propose` :

```python
    p = propose_sub.add_parser(
        "wikidata", help="Pistes Wikidata (personnes notables ; seules pistes fortes)")
    _add_scope(p)
    _add_batch(p)
    _add_date(p)

    p = propose_sub.add_parser(
        "dhs", help="Pistes DHS — Dictionnaire historique de la Suisse (via Wikidata P902)")
    _add_scope(p)
    _add_batch(p)
    _add_date(p)

    p = propose_sub.add_parser(
        "gallica", help="Pistes Gallica — presse ; personnes déjà datées ET localisées")
    _add_scope(p)
    _add_batch(p)
    _add_date(p)
```

- [ ] **Step 5: Lancer le test du parseur**

Run: `cd /Users/fjacquet/Projects/genecrew && uv run python -m pytest genecrew/tests/test_cli_parser.py -q`
Expected: PASS

- [ ] **Step 6: Écrire le test d'orchestration qui échoue**

Créer `genecrew/tests/test_archives.py` :

```python
from crewai_custom_tools.tools.genealogy.models.domain import EventFact, PersonFacts

from genecrew.archives import collecter_pistes


def _person():
    birth = EventFact(type="Birth", year=1900, dateval=[14, 7, 1900, False],
                      place_name="Montbéliard", place="Montbéliard, Doubs, France")
    return PersonFacts(gramps_id="I0042", handle="H42", name="Jean Dupont",
                       surname="Dupont", given="Jean", sex="M", birth=birth)


def test_collecter_wikidata_traduit_les_lignes_sparql(mocker):
    mocker.patch("genecrew.archives.sparql_rows", return_value=[
        {"item": "http://www.wikidata.org/entity/Q42", "itemLabel": "Jean Dupont",
         "birthDate": "1900-07-14T00:00:00Z", "birthPlaceLabel": "Montbéliard"}])
    pistes = collecter_pistes("wikidata", _person())
    assert len(pistes) == 1 and pistes[0].source == "wikidata"
    assert pistes[0].force == "forte"


def test_collecter_gallica_saute_une_personne_ineligible(mocker):
    appel = mocker.patch("genecrew.archives.chercher_gallica", return_value=[])
    person = _person()
    person.birth.place_name = ""          # plus de lieu -> inéligible
    assert collecter_pistes("gallica", person) == []
    appel.assert_not_called()             # on n'interroge même pas l'API


def test_source_inconnue_leve():
    import pytest
    with pytest.raises(ValueError, match="source inconnue"):
        collecter_pistes("scriptorium", _person())
```

- [ ] **Step 7: Lancer le test pour vérifier qu'il échoue**

Run: `cd /Users/fjacquet/Projects/genecrew && uv run python -m pytest genecrew/tests/test_archives.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'genecrew.archives'`

- [ ] **Step 8: Écrire `archives.py`**

```python
"""Orchestration des sources d'archives en ligne : Wikidata, DHS, Gallica.

Ce module fait le RÉSEAU et la boucle ; la traduction en Piste est pure et vit
dans la bibliothèque (crewai_custom_tools.tools.genealogy.pistes).

Voir docs/superpowers/specs/2026-07-20-sources-archives-pistes-design.md.
"""
from __future__ import annotations

import logging
from datetime import date as _date
from pathlib import Path

import requests
from crewai_custom_tools.tools.genealogy.gramps.client import GrampsClient
from crewai_custom_tools.tools.genealogy.gramps.facts import FactsFetcher
from crewai_custom_tools.tools.genealogy.models.domain import PersonFacts, Piste
from crewai_custom_tools.tools.genealogy.pistes import (
    personne_eligible,
    pistes_dhs,
    pistes_gallica,
    pistes_wikidata,
    requete_gallica,
    requete_wikidata,
)
from crewai_custom_tools.tools.web.gallica import SRU_ENDPOINT, USER_AGENT, parse_sru
from crewai_custom_tools.tools.web.wikidata import sparql_rows

from genecrew.pistes import consigner, render_rapport_pistes

logger = logging.getLogger(__name__)

SOURCES = ("wikidata", "dhs", "gallica")


def chercher_gallica(cql: str, max_records: int = 10) -> list[dict]:
    """Interroge Gallica en SRU et rend les enregistrements. Effet de bord isolé ici."""
    response = requests.get(
        SRU_ENDPOINT,
        params={"operation": "searchRetrieve", "version": "1.2",
                "query": cql, "maximumRecords": max_records},
        headers={"User-Agent": USER_AGENT}, timeout=30,
    )
    response.raise_for_status()
    return parse_sru(response.text).get("records", [])


def collecter_pistes(source: str, person: PersonFacts) -> list[Piste]:
    """Interroge la source pour UNE personne et rend ses pistes. Réseau ici."""
    if source in ("wikidata", "dhs"):
        rows = sparql_rows(requete_wikidata(person))
        return pistes_wikidata(person, rows) if source == "wikidata" else pistes_dhs(person, rows)
    if source == "gallica":
        # Filtrer AVANT d'appeler : inutile d'interroger pour une personne
        # dont on ne pourra rien contextualiser.
        if not personne_eligible(person):
            return []
        return pistes_gallica(person, chercher_gallica(requete_gallica(person)))
    raise ValueError(f"source inconnue : {source}")


def run_archives(client: GrampsClient, source: str, scope: str, output_dir: Path, *,
                 date: str | None = None, batch_size: int = 25,
                 limit: int | None = None, dry_run: bool = False) -> Path:
    """Parcourt `scope`, interroge `source`, consigne les fortes, rend le rapport."""
    if source not in SOURCES:
        raise ValueError(f"source inconnue : {source}")
    date = date or _date.today().isoformat()
    fetcher = FactsFetcher(client)
    toutes: list[Piste] = []
    vues = 0
    page = 1
    while True:
        lot = fetcher.list_people_facts(page=page, pagesize=batch_size)
        if not lot:
            break
        for person in lot:
            if limit is not None and vues >= limit:
                break
            vues += 1
            try:
                pistes = collecter_pistes(source, person)
            except Exception as exc:                       # noqa: BLE001
                logger.warning("%s : %s a échoué (%s)", person.gramps_id, source, exc)
                continue
            for piste in pistes:
                consigner(client, piste, dry_run=dry_run)
            toutes.extend(pistes)
        if limit is not None and vues >= limit:
            break
        page += 1

    output_dir.mkdir(parents=True, exist_ok=True)
    chemin = output_dir / f"{date}_pistes_{source}_{scope.replace(':', '-')}.md"
    chemin.write_text(render_rapport_pistes(toutes, date, dry_run=dry_run), encoding="utf-8")
    logger.info("%s pistes depuis %s (%s personnes vues)", len(toutes), source, vues)
    return chemin
```

- [ ] **Step 9: Lancer les tests**

Run: `cd /Users/fjacquet/Projects/genecrew && uv run python -m pytest genecrew/tests/test_archives.py -q`
Expected: PASS (3 tests)

- [ ] **Step 10: Brancher le dispatch**

Dans `main.py`, ajouter les trois entrées à la table de dispatch, après `("propose", "gender")` :

```python
        ("propose", "wikidata"): lambda: archives_cmd(args, "wikidata"),
        ("propose", "dhs"): lambda: archives_cmd(args, "dhs"),
        ("propose", "gallica"): lambda: archives_cmd(args, "gallica"),
```

et définir la fonction, à côté des autres `*_cmd` :

```python
def archives_cmd(args, source: str) -> None:
    """Pistes depuis une source d'archives en ligne (lecture seule + notes append-only)."""
    from genecrew.archives import run_archives

    client = GrampsClient(GrampsConfig.from_env())
    chemin = run_archives(
        client, source, args.scope, Path(args.output_dir),
        date=args.date, batch_size=args.batch_size,
        limit=getattr(args, "limit", None), dry_run=getattr(args, "dry_run", False),
    )
    print(f"Rapport : {chemin}")
```

**Vérifier d'abord** comment les autres `*_cmd` construisent le client et lisent `output_dir` — reprendre exactement le même motif plutôt que celui esquissé ci-dessus s'il diffère :

```bash
cd /Users/fjacquet/Projects/genecrew
grep -n -A12 'def gender_cmd' genecrew/src/genecrew/main.py
```

- [ ] **Step 11: Vérifier l'aide de bout en bout**

```bash
cd /Users/fjacquet/Projects/genecrew
uv run genecrew propose --help
uv run genecrew propose gallica --help
```

Expected: les trois nouvelles cibles apparaissent sous `propose` ; `propose gallica --help` liste `--scope`, `--batch-size`, `--date`.

- [ ] **Step 12: Suite complète et lint**

```bash
cd /Users/fjacquet/Projects/genecrew
uv run python -m pytest genecrew/tests/ -q
uv run ruff check .
```

Expected: tout passe.

- [ ] **Step 13: Commit**

```bash
cd /Users/fjacquet/Projects/genecrew
git add genecrew/src/genecrew/archives.py genecrew/src/genecrew/cli.py \
        genecrew/src/genecrew/main.py genecrew/tests/test_archives.py \
        genecrew/tests/test_cli_parser.py uv.lock
git commit -m "feat(archives): propose wikidata|dhs|gallica

Trois feuilles sous propose, conformes à l'ADR 0012. L'orchestration
fait le réseau, la traduction en Piste reste pure côté bibliothèque.

Gallica n'interroge même pas l'API pour une personne sans date complète
ni lieu : rien à contextualiser."
```

---

### Task 8: Documentation

**Files:**
- Modify: `/Users/fjacquet/Projects/genecrew/docs/USER_GUIDE.md`
- Modify: `/Users/fjacquet/Projects/genecrew/CLAUDE.md`
- Modify: `/Users/fjacquet/Projects/genecrew/docs/adr/0012-cli-grammaire-verbes.md`
- Modify: `/Users/fjacquet/Projects/genecrew/docs/document-de-travail.md` (§9.1)

**Interfaces:**
- Consumes: la surface livrée par la Task 7.
- Produces: rien de programmatique.

- [ ] **Step 1: Mode d'emploi**

Dans `docs/USER_GUIDE.md`, ajouter une section « Pistes depuis les archives en ligne » : les trois commandes, ce que chacune cible (Wikidata = personnes notables, rendement faible mais pistes fortes ; DHS = Suisse, 122 personnes concernées dans l'arbre ; Gallica = presse, uniquement pour des personnes déjà datées et localisées, pistes faibles par construction), et le rappel qu'aucune citation n'est créée. Une phase n'est pas terminée si son mode d'emploi n'y est pas (§11 du document de travail).

- [ ] **Step 2: CLAUDE.md**

Mettre à jour la liste des modules de `genecrew/src/genecrew/` pour y ajouter `archives.py`, et la grammaire de la CLI (`propose {audit|places|deaths|military|gender|wikidata|dhs|gallica}`).

- [ ] **Step 3: ADR 0012**

Ajouter les trois nouvelles feuilles à la table de la grammaire — l'ADR décrit la surface, elle a changé.

- [ ] **Step 4: §9.1 du document de travail**

Passer la ligne de la **phase 4** de 🟡 à ✅ si le critère de sortie est atteint (« pistes jugées utiles par l'utilisateur » — à confirmer avec l'utilisateur, ne pas le décréter seul), sinon mettre à jour son contenu pour refléter les trois sources livrées.

- [ ] **Step 5: Vérifier qu'aucun ancien nom ne subsiste**

```bash
cd /Users/fjacquet/Projects/genecrew
grep -rn 'propose scriptorium' docs/ CLAUDE.md README.md
```

Expected: aucune sortie (la source est écartée, elle ne doit apparaître que dans `BACKLOG.md` et le §3.4 du spec).

- [ ] **Step 6: Commit**

```bash
cd /Users/fjacquet/Projects/genecrew
git add docs/ CLAUDE.md
git commit -m "docs(archives): mode d'emploi des trois sources de pistes"
```

---

### Task 9: Épreuve du réel (bornée)

Les tests sont hors-ligne ; rien ne prouve encore que les requêtes réelles rendent quoi que ce soit. Le principal risque du spec est là : **Wikidata ne décrit que des personnes notables**, donc la cible théorique de 122 personnes suisses pour le DHS pourrait s'avérer proche de zéro.

**Files:** aucun (exécution et compte rendu).

**Interfaces:**
- Consumes: la CLI livrée en Task 7.
- Produces: un verdict chiffré sur le rendement réel de chaque source.

- [ ] **Step 1: Vérifier que la stack tourne**

```bash
docker ps --format '{{.Names}}' | grep -i gramps
```

Expected: `gramps-mcp-grampsweb-1` et consorts. Sinon : `cd /Users/fjacquet/Projects/gramps-mcp && docker compose up -d`.

- [ ] **Step 2: Un run borné par source, en simulation**

```bash
cd /Users/fjacquet/Projects/genecrew
uv run genecrew propose wikidata --scope all --limit 50 --dry-run
uv run genecrew propose dhs --scope all --limit 50 --dry-run
uv run genecrew propose gallica --scope all --limit 50 --dry-run
```

Expected: trois rapports Markdown écrits sous `output/`. **Borner avec `--limit` est impératif** — un run complet interroge des API externes une fois par personne sur 2119 personnes.

- [ ] **Step 3: Relever les chiffres et rendre compte**

Pour chaque source : nombre de personnes vues, de pistes fortes, de pistes faibles. Rapporter ces chiffres à l'utilisateur **sans les enjoliver** — un rendement nul est un résultat exploitable, il dit que la source ne convient pas à cet arbre et qu'il faut la retirer plutôt que la garder pour la forme.

- [ ] **Step 4: Décider avec l'utilisateur**

Selon les chiffres : garder les trois sources, en retirer une, ou ajuster les requêtes. **Ne pas décider seul** — c'est son arbre et son jugement sur l'utilité des pistes qui est le critère de sortie de la phase 4.
