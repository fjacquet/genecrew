# Référentiel des subdivisions administratives — plan d'implémentation

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Peupler l'arbre Gramps avec les pays et leurs subdivisions administratives (9 pays,
~430 entités) — coordonnées WGS84, QID Wikidata et article Wikipédia compris — puis rendre les
19 communes suisses rattachables sous leur canton.

**Architecture:** Une requête SPARQL par pays sélectionne les entités portant un code ISO 3166-2 ;
un mapper **pur** en déduit le niveau par le rattachement `P131`, le type Gramps par une table de
configuration, et signale les collisions. Le réseau est isolé dans deux fonctions. genecrew
n'orchestre que le cycle `propose` (rapport + YAML) → relecture → `apply` (écriture).

**Tech Stack:** Python 3.12, pydantic v2, pytest, `uv`. Wikidata SPARQL via
`crewai_custom_tools.tools.web.wikidata.sparql_rows` (déjà présent). Écritures Gramps via
`GrampsCreatePlaceTool`, `GrampsUpdatePlaceTool`, `GrampsAddUrlTool` (tous déjà présents).

**Spec :** `docs/superpowers/specs/2026-07-21-referentiel-lieux-design.md`

## Global Constraints

- **Deux worktrees, côte à côte.** genecrew :
  `/Users/fjacquet/Projects/genecrew/.claude/worktrees/init-referentiel-lieux`, branche
  `feat/init-referentiel-lieux`. Bibliothèque :
  `/Users/fjacquet/Projects/genecrew/.claude/worktrees/crewai_custom_tools`, branche
  `feat/referentiel-subdivisions`. Le chemin éditable `../crewai_custom_tools` ne résout que
  parce qu'ils sont voisins — ne pas les déplacer.
- **Toujours `uv`**, jamais `pip` ni `python` direct.
- **Ne jamais fusionner, pousser ni taguer** sans demande explicite de l'humain. Le tag de la
  bibliothèque est un contrôle qualité délibéré (tâche 7).
- **Coordonnées WGS84 décimales.** Le WKT Wikidata est `Point(lon lat)` — **longitude d'abord**.
  Réutiliser `parse_wkt_point` (`geo/france_ex_communes.py:87`), ne pas le réécrire.
- **Aucun type Gramps personnalisé nouveau.** Types natifs seulement (spec §4).
- **Aucune écriture destructive**, à l'unique exception du retypage des 5 `Wilaya` en `Province`.
- **Français** pour les libellés, les rapports, les commentaires et les messages de commit.
- Tests bibliothèque : `uv run python -m pytest tests/ -q` depuis le worktree bibliothèque, après
  un `uv sync --extra dev`. Tests genecrew : `uv run python -m pytest genecrew/tests/ -q` depuis le
  worktree genecrew. Bases de référence au départ : **871** et **365**.

## Ordre des livraisons

Les tâches 1 à 6 modifient la bibliothèque, la tâche 7 la publie, les tâches 8 à 11 modifient
genecrew. L'ordre d'**exécution des commandes** par l'utilisateur (référentiel d'abord, rattachement
des communes suisses ensuite) est indépendant de l'ordre de livraison du code : les deux correctifs
de bibliothèque tiennent dans un seul bump.

---

### Task 1 : modèles et table des 9 pays

**Files:**
- Create: `src/crewai_custom_tools/tools/genealogy/referentiel/__init__.py` (vide)
- Create: `src/crewai_custom_tools/tools/genealogy/referentiel/config.py`
- Modify: `src/crewai_custom_tools/tools/genealogy/models/domain.py` (ajout en fin de fichier)
- Test: `tests/test_genealogy_referentiel_config.py`

**Interfaces:**
- Produces: `Subdivision`, `CollisionIso` (dans `models/domain.py`) ; `PaysReferentiel` et
  `PAYS_REFERENTIEL: dict[str, PaysReferentiel]` (dans `referentiel/config.py`).

Tous les QID de la table ont été **vérifiés en ligne** le 2026-07-21 contre les libellés Wikidata.
Ne pas les modifier sans revérifier.

- [ ] **Step 1: écrire le test qui échoue**

Créer `tests/test_genealogy_referentiel_config.py` :

```python
# tests/test_genealogy_referentiel_config.py
"""La table des pays est une donnée dure : QID vérifiés, niveaux cohérents."""
from crewai_custom_tools.tools.genealogy.referentiel.config import PAYS_REFERENTIEL

from genecrew.batching import iter_places


def test_les_neuf_pays_attendus_sont_presents():
    assert set(PAYS_REFERENTIEL) == {"FR", "CH", "DE", "IT", "DZ", "US", "PL", "BE", "SY"}


def test_qid_des_pays_verifies_en_ligne_le_2026_07_21():
    attendus = {"FR": "Q142", "CH": "Q39", "DE": "Q183", "IT": "Q38", "DZ": "Q262",
                "US": "Q30", "PL": "Q36", "BE": "Q31", "SY": "Q858"}
    assert {c: p.qid for c, p in PAYS_REFERENTIEL.items()} == attendus


def test_niveaux_par_pays():
    # Deux niveaux là où l'arbre en a déjà deux ; un seul ailleurs (spec §4).
    assert PAYS_REFERENTIEL["FR"].niveaux == ("Region", "Department")
    assert PAYS_REFERENTIEL["IT"].niveaux == ("Region", "Province")
    assert PAYS_REFERENTIEL["BE"].niveaux == ("Region", "Province")
    assert PAYS_REFERENTIEL["CH"].niveaux == ("State",)
    assert PAYS_REFERENTIEL["DZ"].niveaux == ("Province",)


def test_langue_locale_par_pays():
    """Sert à récupérer le nom vernaculaire, seule prise pour apparier les 4 Länder
    déjà en base sous `Bayern`, `Hessen`… avant qu'aucun QID ne soit posé."""
    assert PAYS_REFERENTIEL["DE"].langue == "de"
    assert PAYS_REFERENTIEL["IT"].langue == "it"
    assert PAYS_REFERENTIEL["PL"].langue == "pl"
    assert PAYS_REFERENTIEL["US"].langue == "en"
    assert PAYS_REFERENTIEL["FR"].langue == "fr"


def test_aucun_type_personnalise():
    # Gramps ne connaît que ses types natifs ; Canton et Wilaya n'en font pas partie.
    natifs = {"Country", "State", "County", "City", "Province", "Region", "Department",
              "Municipality", "District", "Borough", "Town", "Village", "Locality"}
    for pays in PAYS_REFERENTIEL.values():
        assert set(pays.niveaux) <= natifs, pays.nom


def test_le_code_iso_de_la_cle_est_celui_du_pays():
    for code, pays in PAYS_REFERENTIEL.items():
        assert pays.code_iso == code
```

- [ ] **Step 2: lancer le test, vérifier qu'il échoue**

Depuis le worktree bibliothèque :

```bash
uv run python -m pytest tests/test_genealogy_referentiel_config.py -q
```

Attendu : `ModuleNotFoundError: No module named 'crewai_custom_tools.tools.genealogy.referentiel'`

- [ ] **Step 3: ajouter les modèles au domaine**

À la fin de `src/crewai_custom_tools/tools/genealogy/models/domain.py` :

```python
class Subdivision(BaseModel):
    """Une subdivision administrative résolue depuis Wikidata (référentiel des lieux)."""

    qid: str                            # "Q12771"
    iso: str                            # "CH-VD"
    code: str                           # "VD" — l'ISO amputé du préfixe pays
    libelle_fr: str
    noms: list[str] = Field(default_factory=list)   # appariement : français, puis vernaculaire
    place_type: str                     # type Gramps NATIF ("State", "Department"…)
    niveau: int                         # 1 = sous le pays, 2 = sous une subdivision de niveau 1
    parent_qid: str                     # QID du pays ou de la subdivision de niveau 1
    lat: str | None = None              # WGS84 décimal
    long: str | None = None
    frwiki: str | None = None           # URL de l'article français


class CollisionIso(BaseModel):
    """Plusieurs entités retenues sous un même code ISO : signalé, jamais écrit."""

    iso: str
    qids: list[str]
    libelles: list[str]
```

- [ ] **Step 4: écrire la table des pays**

Créer `src/crewai_custom_tools/tools/genealogy/referentiel/__init__.py` vide, puis
`src/crewai_custom_tools/tools/genealogy/referentiel/config.py` :

```python
"""Table des pays du référentiel : préfixe ISO, QID Wikidata, types Gramps par niveau.

Ajouter un pays = ajouter une ligne. Les QID ont été vérifiés en ligne le 2026-07-21 ;
ne pas les modifier sans revérifier contre les libellés Wikidata.

Les types sont exclusivement des types Gramps NATIFS : ni `Canton` ni `Wilaya` n'en sont.
Un type personnalisé est une ligne de plus à ne pas oublier dans chaque filtre par type,
et un contenant oublié dans une liste d'inclusion se traduit par un rattachement muet.
"""

from __future__ import annotations

from pydantic import BaseModel


class PaysReferentiel(BaseModel):
    """Un pays du référentiel et la forme de sa hiérarchie administrative."""

    code_iso: str                       # "FR" — préfixe des codes ISO 3166-2
    qid: str                            # "Q142"
    nom: str                            # "France" — le nom du lieu Gramps
    langue: str                         # langue du nom vernaculaire, pour l'appariement
    niveaux: tuple[str, ...]            # types Gramps, du niveau 1 vers le niveau 2


PAYS_REFERENTIEL: dict[str, PaysReferentiel] = {
    "FR": PaysReferentiel(code_iso="FR", qid="Q142", nom="France", langue="fr",
                          niveaux=("Region", "Department")),
    "IT": PaysReferentiel(code_iso="IT", qid="Q38", nom="Italie", langue="it",
                          niveaux=("Region", "Province")),
    "BE": PaysReferentiel(code_iso="BE", qid="Q31", nom="Belgique", langue="nl",
                          niveaux=("Region", "Province")),
    "CH": PaysReferentiel(code_iso="CH", qid="Q39", nom="Suisse", langue="de",
                          niveaux=("State",)),
    "DE": PaysReferentiel(code_iso="DE", qid="Q183", nom="Allemagne", langue="de",
                          niveaux=("State",)),
    "US": PaysReferentiel(code_iso="US", qid="Q30", nom="États-Unis", langue="en",
                          niveaux=("State",)),
    "DZ": PaysReferentiel(code_iso="DZ", qid="Q262", nom="Algérie", langue="ar",
                          niveaux=("Province",)),
    "PL": PaysReferentiel(code_iso="PL", qid="Q36", nom="Pologne", langue="pl",
                          niveaux=("Region",)),
    "SY": PaysReferentiel(code_iso="SY", qid="Q858", nom="Syrie", langue="ar",
                          niveaux=("Province",)),
}
```

- [ ] **Step 5: lancer le test, vérifier qu'il passe**

```bash
uv run python -m pytest tests/test_genealogy_referentiel_config.py -q
```

Attendu : `6 passed`

- [ ] **Step 6: commit**

```bash
git add src/crewai_custom_tools/tools/genealogy/referentiel/ \
        src/crewai_custom_tools/tools/genealogy/models/domain.py \
        tests/test_genealogy_referentiel_config.py
git commit -m "feat(referentiel): modèles Subdivision/CollisionIso et table des 9 pays"
```

---

### Task 2 : requête SPARQL et helpers purs

**Files:**
- Create: `src/crewai_custom_tools/tools/genealogy/referentiel/wikidata.py`
- Test: `tests/test_genealogy_referentiel_wikidata.py`

**Interfaces:**
- Consumes: `PAYS_REFERENTIEL`, `PaysReferentiel` (tâche 1).
- Produces: `build_query(prefixe: str) -> str`, `build_query_pays(qids: list[str]) -> str`,
  `qid_of(uri: str) -> str`, `code_sans_prefixe(iso: str, prefixe: str) -> str`.

- [ ] **Step 1: écrire le test qui échoue**

Créer `tests/test_genealogy_referentiel_wikidata.py` :

```python
# tests/test_genealogy_referentiel_wikidata.py
"""Construction de requête et helpers purs du référentiel."""
from crewai_custom_tools.tools.genealogy.referentiel.wikidata import (
    build_query, build_query_pays, code_sans_prefixe, qid_of,
)


def test_qid_of_extrait_le_dernier_segment():
    assert qid_of("http://www.wikidata.org/entity/Q39") == "Q39"


def test_qid_of_laisse_passer_un_qid_nu():
    assert qid_of("Q39") == "Q39"


def test_qid_of_vide_sur_entree_vide():
    assert qid_of("") == ""
    assert qid_of(None) == ""


def test_code_sans_prefixe_reproduit_la_convention_de_larbre():
    # FR-03 -> 03, le code en base de l'Allier ; DZ-41 -> 41, celui de Souk Ahras.
    assert code_sans_prefixe("FR-03", "FR") == "03"
    assert code_sans_prefixe("DZ-41", "DZ") == "41"
    assert code_sans_prefixe("CH-VD", "CH") == "VD"


def test_code_sans_prefixe_rend_lentree_telle_quelle_si_le_prefixe_ne_colle_pas():
    assert code_sans_prefixe("IT-NA", "FR") == "IT-NA"


def test_build_query_filtre_le_prefixe_et_les_entites_dissoutes():
    q = build_query("CH", "de")
    assert 'STRSTARTS(?iso, "CH-")' in q
    assert "wdt:P576" in q            # dissolution : exclue
    assert "wdt:P300" in q            # ISO 3166-2 : le sélecteur
    assert "wdt:P625" in q            # coordonnées
    assert "wdt:P131" in q            # rattachement, d'où vient le niveau
    assert "fr.wikipedia.org" in q    # sitelink de l'article français


def test_build_query_demande_le_nom_vernaculaire():
    """Sans lui, `Bayern` déjà en base ne serait apparié par aucun nom au premier run,
    et un doublon `Bavière` serait créé à côté."""
    q = build_query("DE", "de")
    assert "rdfs:label" in q
    assert '"de"' in q


def test_build_query_pays_liste_les_qid_en_values():
    q = build_query_pays(["Q142", "Q39"])
    assert "wd:Q142" in q and "wd:Q39" in q
    assert "VALUES" in q
```

- [ ] **Step 2: lancer le test, vérifier qu'il échoue**

```bash
uv run python -m pytest tests/test_genealogy_referentiel_wikidata.py -q
```

Attendu : `ModuleNotFoundError: ... referentiel.wikidata`

- [ ] **Step 3: écrire le module**

Créer `src/crewai_custom_tools/tools/genealogy/referentiel/wikidata.py` :

```python
"""Requêtes Wikidata du référentiel : construction pure, puis transport isolé.

Le sélecteur est le code ISO 3166-2 (`P300`) et non la classe `P31`. Vérifié le 2026-07-21 :
sélectionner par classe rate Naples et Milan, qui sont des *villes métropolitaines* et non des
provinces. Le filtre par sous-classes (`P31/P279*` vers Q56061) a été essayé puis rejeté —
l'endpoint public rend un 504 sur la fermeture transitive.
"""

from __future__ import annotations

_SUBDIVISIONS = """SELECT ?item ?itemLabel ?nomLocal ?iso ?coord ?parent ?art WHERE {{
  ?item wdt:P300 ?iso .
  FILTER(STRSTARTS(?iso, "{prefixe}-"))
  FILTER NOT EXISTS {{ ?item wdt:P576 ?dissous }}
  OPTIONAL {{ ?item wdt:P625 ?coord }}
  OPTIONAL {{ ?item wdt:P131 ?parent }}
  OPTIONAL {{ ?item rdfs:label ?nomLocal . FILTER(lang(?nomLocal) = "{langue}") }}
  OPTIONAL {{ ?art schema:about ?item ; schema:isPartOf <https://fr.wikipedia.org/> }}
  SERVICE wikibase:label {{ bd:serviceParam wikibase:language "fr,en". }}
}}"""

_PAYS = """SELECT ?item ?itemLabel ?coord ?art WHERE {{
  VALUES ?item {{ {valeurs} }}
  OPTIONAL {{ ?item wdt:P625 ?coord }}
  OPTIONAL {{ ?art schema:about ?item ; schema:isPartOf <https://fr.wikipedia.org/> }}
  SERVICE wikibase:label {{ bd:serviceParam wikibase:language "fr,en". }}
}}"""


def build_query(prefixe: str, langue: str) -> str:
    """Requête des subdivisions d'un pays, par préfixe ISO 3166-2 ('FR', 'CH'…).

    `langue` rapatrie le nom vernaculaire en plus du libellé français : c'est la seule prise
    pour apparier `Bayern`, déjà en base en allemand, avant qu'un QID n'y soit posé.
    """
    return _SUBDIVISIONS.format(prefixe=prefixe, langue=langue)


def build_query_pays(qids: list[str]) -> str:
    """Requête des pays eux-mêmes (libellé, centroïde, article), en un seul appel."""
    return _PAYS.format(valeurs=" ".join(f"wd:{q}" for q in qids))


def qid_of(uri: str | None) -> str:
    """'http://www.wikidata.org/entity/Q39' -> 'Q39'. Chaîne vide si rien à extraire."""
    if not uri:
        return ""
    return uri.rsplit("/", 1)[-1]


def code_sans_prefixe(iso: str, prefixe: str) -> str:
    """'FR-03' -> '03'. Reproduit la convention des codes déjà en base.

    Rendu tel quel si le préfixe ne correspond pas : mieux vaut un code inhabituel
    qu'un code tronqué au hasard.
    """
    debut = f"{prefixe}-"
    return iso[len(debut):] if iso.startswith(debut) else iso
```

- [ ] **Step 4: lancer le test, vérifier qu'il passe**

```bash
uv run python -m pytest tests/test_genealogy_referentiel_wikidata.py -q
```

Attendu : `8 passed`

- [ ] **Step 5: commit**

```bash
git add src/crewai_custom_tools/tools/genealogy/referentiel/wikidata.py \
        tests/test_genealogy_referentiel_wikidata.py
git commit -m "feat(referentiel): requêtes SPARQL par code ISO 3166-2 et helpers purs"
```

---

### Task 3 : le mapper pur — les cinq règles de filtrage

C'est le cœur du lot. Les quatre cas de contrôle sont **réels**, relevés sur Wikidata le
2026-07-21 (spec §3.4).

**Files:**
- Modify: `src/crewai_custom_tools/tools/genealogy/referentiel/wikidata.py`
- Test: `tests/test_genealogy_referentiel_mapper.py`

**Interfaces:**
- Consumes: `Subdivision`, `CollisionIso`, `PaysReferentiel`, `qid_of`, `code_sans_prefixe`,
  `parse_wkt_point` (importé depuis `geo/france_ex_communes.py`).
- Produces: `map_subdivisions(rows: list[dict], pays: PaysReferentiel) -> tuple[list[Subdivision], list[CollisionIso]]`

- [ ] **Step 1: écrire le test qui échoue**

Créer `tests/test_genealogy_referentiel_mapper.py` :

```python
# tests/test_genealogy_referentiel_mapper.py
"""Les cinq règles du mapper, sur les cas réels relevés sur Wikidata le 2026-07-21."""
from crewai_custom_tools.tools.genealogy.referentiel.config import PAYS_REFERENTIEL
from crewai_custom_tools.tools.genealogy.referentiel.wikidata import map_subdivisions

FR = PAYS_REFERENTIEL["FR"]
IT = PAYS_REFERENTIEL["IT"]
PL = PAYS_REFERENTIEL["PL"]
CH = PAYS_REFERENTIEL["CH"]

ENTITE = "http://www.wikidata.org/entity/"


def ligne(qid, label, iso, parent=None, coord=None, art=None, nom_local=None):
    """Une ligne aplatie telle que sparql_rows la rend (clés absentes si non liées)."""
    r = {"item": ENTITE + qid, "itemLabel": label, "iso": iso}
    if parent:
        r["parent"] = ENTITE + parent
    if coord:
        r["coord"] = coord
    if art:
        r["art"] = art
    if nom_local:
        r["nomLocal"] = nom_local
    return r


def test_les_noms_dapariement_portent_le_francais_puis_le_vernaculaire():
    DE = PAYS_REFERENTIEL["DE"]
    rows = [ligne("Q980", "Bavière", "DE-BY", parent="Q183", nom_local="Bayern")]
    subs, _ = map_subdivisions(rows, DE)
    assert subs[0].libelle_fr == "Bavière"
    assert subs[0].noms == ["Bavière", "Bayern"]


def test_les_noms_ne_repetent_pas_un_libelle_identique():
    rows = [ligne("Q12771", "Vaud", "CH-VD", parent="Q39", nom_local="Vaud")]
    subs, _ = map_subdivisions(rows, CH)
    assert subs[0].noms == ["Vaud"]


def test_niveau_1_quand_le_parent_est_le_pays():
    rows = [ligne("Q12771", "Vaud", "CH-VD", parent="Q39",
                  coord="Point(6.6 46.6)", art="https://fr.wikipedia.org/wiki/Canton_de_Vaud")]
    subs, collisions = map_subdivisions(rows, CH)
    assert collisions == []
    assert len(subs) == 1
    s = subs[0]
    assert (s.qid, s.iso, s.code, s.niveau) == ("Q12771", "CH-VD", "VD", 1)
    assert s.place_type == "State"          # jamais "Canton" : type natif seulement
    assert s.parent_qid == "Q39"
    assert (s.lat, s.long) == ("46.6", "6.6")   # WKT = Point(lon lat), ne pas inverser
    assert s.frwiki == "https://fr.wikipedia.org/wiki/Canton_de_Vaud"


def test_niveau_2_quand_le_parent_est_une_subdivision_de_niveau_1():
    rows = [ligne("Q18338206", "Auvergne-Rhône-Alpes", "FR-ARA", parent="Q142"),
            ligne("Q3113", "Allier", "FR-03", parent="Q18338206")]
    subs, _ = map_subdivisions(rows, FR)
    par_iso = {s.iso: s for s in subs}
    assert par_iso["FR-ARA"].niveau == 1 and par_iso["FR-ARA"].place_type == "Region"
    assert par_iso["FR-03"].niveau == 2 and par_iso["FR-03"].place_type == "Department"
    assert par_iso["FR-03"].code == "03"     # la convention de l'arbre


def test_parent_hors_ensemble_et_different_du_pays_ecarte_lentite():
    # IT-82 : Q134470541, sans libellé, rattachée à une commune. Règle 2.
    rows = [ligne("Q1460", "Sicile", "IT-82", parent="Q38"),
            ligne("Q134470541", "Q134470541", "IT-82", parent="Q31151")]
    subs, collisions = map_subdivisions(rows, IT)
    assert [s.qid for s in subs] == ["Q1460"]
    assert collisions == []                  # une seule retenue : pas de collision


def test_un_parent_de_niveau_2_donne_un_niveau_3_donc_ecarte():
    # IT-VE : Venise la ville pend sous la ville métropolitaine, qui pend sous la Vénétie.
    rows = [ligne("Q1225", "Vénétie", "IT-34", parent="Q38"),
            ligne("Q3678587", "ville métropolitaine de Venise", "IT-VE", parent="Q1225"),
            ligne("Q641", "Venise", "IT-VE", parent="Q3678587")]
    subs, collisions = map_subdivisions(rows, IT)
    assert sorted(s.qid for s in subs) == ["Q1225", "Q3678587"]
    assert collisions == []


def test_niveau_superieur_aux_niveaux_configures_ecarte():
    # PL-KI : Kielce, une ville sous une voïvodie. La Pologne n'a qu'un niveau.
    rows = [ligne("Q54193", "voïvodie de Sainte-Croix", "PL-26", parent="Q36"),
            ligne("Q102317", "Kielce", "PL-KI", parent="Q54193")]
    subs, _ = map_subdivisions(rows, PL)
    assert [s.iso for s in subs] == ["PL-26"]


def test_deux_entites_retenues_sous_un_meme_iso_font_une_collision_sans_ecriture():
    # FR-69 : le département et la circonscription départementale, même code, même niveau.
    rows = [ligne("Q18338206", "Auvergne-Rhône-Alpes", "FR-ARA", parent="Q142"),
            ligne("Q46130", "Rhône", "FR-69", parent="Q18338206"),
            ligne("Q18914778", "Rhône", "FR-69", parent="Q18338206")]
    subs, collisions = map_subdivisions(rows, FR)
    assert [s.iso for s in subs] == ["FR-ARA"]     # ni l'une ni l'autre n'est écrite
    assert len(collisions) == 1
    assert collisions[0].iso == "FR-69"
    assert sorted(collisions[0].qids) == ["Q18914778", "Q46130"]


def test_un_parent_de_meme_code_iso_que_lenfant_est_ignore():
    # Sans cette exclusion, Q46130 et Q18914778 se prendraient mutuellement pour parent.
    rows = [ligne("Q18338206", "Auvergne-Rhône-Alpes", "FR-ARA", parent="Q142"),
            ligne("Q46130", "Rhône", "FR-69", parent="Q18914778"),
            ligne("Q46130", "Rhône", "FR-69", parent="Q18338206")]
    subs, _ = map_subdivisions(rows, FR)
    assert {s.iso: s.niveau for s in subs} == {"FR-ARA": 1, "FR-69": 2}


def test_les_p131_historiques_sont_neutralises_par_labsence_de_lentite_dissoute():
    # Rhône-Alpes est dissoute : la requête ne la rend pas, elle n'est donc pas candidate.
    rows = [ligne("Q18338206", "Auvergne-Rhône-Alpes", "FR-ARA", parent="Q142"),
            ligne("Q3113", "Allier", "FR-03", parent="Q3084"),      # Rhône-Alpes, absente
            ligne("Q3113", "Allier", "FR-03", parent="Q18338206")]
    subs, _ = map_subdivisions(rows, FR)
    assert {s.iso: s.parent_qid for s in subs} == {"FR-ARA": "Q142", "FR-03": "Q18338206"}


def test_une_entite_sans_aucun_parent_est_ecartee():
    rows = [ligne("Q999999", "orpheline", "FR-99")]
    subs, collisions = map_subdivisions(rows, FR)
    assert subs == [] and collisions == []


def test_coordonnees_absentes_ne_font_pas_echouer():
    rows = [ligne("Q12771", "Vaud", "CH-VD", parent="Q39")]
    subs, _ = map_subdivisions(rows, CH)
    assert subs[0].lat is None and subs[0].long is None
```

- [ ] **Step 2: lancer le test, vérifier qu'il échoue**

```bash
uv run python -m pytest tests/test_genealogy_referentiel_mapper.py -q
```

Attendu : `ImportError: cannot import name 'map_subdivisions'`

- [ ] **Step 3: écrire le mapper**

Ajouter à la fin de `src/crewai_custom_tools/tools/genealogy/referentiel/wikidata.py` :

```python
from collections import defaultdict

from crewai_custom_tools.tools.genealogy.geo.france_ex_communes import parse_wkt_point
from crewai_custom_tools.tools.genealogy.models.domain import CollisionIso, Subdivision
from crewai_custom_tools.tools.genealogy.referentiel.config import PaysReferentiel

_NIVEAU_IMPOSSIBLE = 99


def _grouper(rows: list[dict]) -> dict[str, dict]:
    """Regroupe les lignes aplaties par entité. SPARQL éclate les propriétés multivaluées :
    une entité à trois P131 revient sur trois lignes, et c'est bénin — on réunit ici."""
    par_qid: dict[str, dict] = {}
    for row in rows:
        qid = qid_of(row.get("item"))
        if not qid:
            continue
        entree = par_qid.setdefault(qid, {"qid": qid, "iso": row.get("iso", ""),
                                          "label": row.get("itemLabel", ""),
                                          "nom_local": None, "parents": set(),
                                          "coord": None, "art": None})
        parent = qid_of(row.get("parent"))
        if parent:
            entree["parents"].add(parent)
        entree["coord"] = entree["coord"] or row.get("coord")
        entree["art"] = entree["art"] or row.get("art")
        entree["nom_local"] = entree["nom_local"] or row.get("nomLocal")
    return par_qid


def _noms(entree: dict) -> list[str]:
    """Noms d'appariement, français d'abord, vernaculaire ensuite, sans répétition."""
    noms = [n for n in (entree["label"], entree["nom_local"]) if n]
    return list(dict.fromkeys(noms))


def _choisir_parent(entree: dict, par_qid: dict[str, dict], qid_pays: str) -> str | None:
    """Règle 2 : le parent est le P131 qui est lui-même candidat, à défaut le pays.

    Un parent portant le MÊME code ISO que l'enfant est ignoré : sans cela, deux entités
    en collision (FR-69) se prendraient mutuellement pour parent et aucune ne se résoudrait.
    """
    candidats = sorted(p for p in entree["parents"]
                       if p in par_qid and par_qid[p]["iso"] != entree["iso"])
    if candidats:
        return candidats[0]
    if qid_pays in entree["parents"]:
        return qid_pays
    return None


def _niveau(qid: str, parents: dict[str, str], qid_pays: str, vus: frozenset = frozenset()) -> int:
    """Règle 3 : 1 sous le pays, 1 + niveau(parent) sinon. Cycle ou orpheline -> impossible."""
    if qid in vus:
        return _NIVEAU_IMPOSSIBLE
    parent = parents.get(qid)
    if parent is None:
        return _NIVEAU_IMPOSSIBLE
    if parent == qid_pays:
        return 1
    return min(_NIVEAU_IMPOSSIBLE, 1 + _niveau(parent, parents, qid_pays, vus | {qid}))


def map_subdivisions(rows: list[dict],
                     pays: PaysReferentiel) -> tuple[list[Subdivision], list[CollisionIso]]:
    """Charge SPARQL -> subdivisions retenues + collisions signalées. Pure, hors ligne.

    Les cinq règles de la spec §3.4, dans l'ordre : univers ISO, parent, niveau, niveaux
    configurés, collision. Aucune liste de QID à exclure — vérifié le 2026-07-21, un code
    ISO correspond à une entité et une seule sauf trois exceptions, que ces règles traitent.
    """
    par_qid = _grouper(rows)
    parents = {}
    for qid, entree in par_qid.items():
        parent = _choisir_parent(entree, par_qid, pays.qid)
        if parent is not None:
            parents[qid] = parent

    retenues: list[Subdivision] = []
    for qid, entree in par_qid.items():
        if qid not in parents:
            continue                                    # règle 2 : aucun parent valide
        niveau = _niveau(qid, parents, pays.qid)
        if niveau > len(pays.niveaux):                  # règles 3 et 4
            continue
        lat, long = (parse_wkt_point(entree["coord"]) or (None, None))
        retenues.append(Subdivision(
            qid=qid, iso=entree["iso"],
            code=code_sans_prefixe(entree["iso"], pays.code_iso),
            libelle_fr=entree["label"], noms=_noms(entree),
            place_type=pays.niveaux[niveau - 1],
            niveau=niveau, parent_qid=parents[qid],
            lat=lat, long=long, frwiki=entree["art"]))

    # Règle 5 : un code ISO porté par deux entités retenues est indécidable -> aucune écriture.
    par_iso: dict[str, list[Subdivision]] = defaultdict(list)
    for sub in retenues:
        par_iso[sub.iso].append(sub)
    collisions = [CollisionIso(iso=iso, qids=[s.qid for s in lot],
                               libelles=[s.libelle_fr for s in lot])
                  for iso, lot in sorted(par_iso.items()) if len(lot) > 1]
    propres = [lot[0] for _, lot in sorted(par_iso.items()) if len(lot) == 1]
    return propres, collisions
```

Déplacer les imports en tête de fichier plutôt qu'au milieu — ils sont écrits ici groupés
seulement pour la lisibilité du plan.

- [ ] **Step 4: lancer le test, vérifier qu'il passe**

```bash
uv run python -m pytest tests/test_genealogy_referentiel_mapper.py -q
```

Attendu : `12 passed`

- [ ] **Step 5: vérifier que rien d'autre n'a bougé**

```bash
uv run python -m pytest tests/ -q
```

Attendu : **zéro échec**, et un total supérieur aux 871 de référence (6 + 8 + 12 tests ajoutés
par les tâches 1 à 3). C'est l'absence d'échec qui compte, pas le compte exact.

- [ ] **Step 6: commit**

```bash
git add src/crewai_custom_tools/tools/genealogy/referentiel/wikidata.py \
        tests/test_genealogy_referentiel_mapper.py
git commit -m "feat(referentiel): mapper pur, niveau par P131 et collisions ISO signalées"
```

---

### Task 3bis : corriger le mapper — ancre pays, écartées, déterminisme

> **Cette tâche corrige la tâche 3, déjà livrée au commit `73fd37b`.** La revue de code a fait
> passer la **vraie** charge Wikidata dans le mapper : sur 125 entités françaises, **12
> seulement** étaient retenues, toutes ultramarines, et la collision `FR-69` exigée par la spec
> n'apparaissait pas. Cause : les régions métropolitaines pendent sous `Q212429`
> *France métropolitaine*, qui n'a pas de code ISO et n'entre donc pas dans l'univers. Les
> régions tombaient, puis les 96 départements avec elles. **En silence** : rien ne signalait les
> 113 disparues.
>
> Quatre autres constats de la même revue sont corrigés ici.

**Files:**
- Modify: `src/crewai_custom_tools/tools/genealogy/referentiel/wikidata.py`
- Modify: `src/crewai_custom_tools/tools/genealogy/models/domain.py` (ajout d'un modèle)
- Modify: `tests/test_genealogy_referentiel_mapper.py` (réécriture des fixtures)
- Modify: `tests/test_genealogy_referentiel_wikidata.py` (signature de `build_query`)
- Create: `tests/fixtures/referentiel/{FR,IT,CH,PL}.json`
- Create: `scripts/capturer_charges_referentiel.py`

**Interfaces:**
- Produces (signatures modifiées) :
  - `build_query(prefixe: str, langue: str, qid_pays: str) -> str`
  - `map_subdivisions(rows, pays) -> tuple[list[Subdivision], list[CollisionIso], list[EntiteEcartee]]`
  - `EntiteEcartee(qid, iso, libelle_fr, motif)` dans `models/domain.py`
- La tâche 4, qui n'est pas encore écrite, consommera ces signatures.

**Les six corrections, chacune avec le cas qui la motive :**

1. **Ancre pays.** La requête demande en plus si le pays est atteignable en un, deux ou trois
   sauts de `P131`. Sans parent candidat, l'ancre donne le niveau 1. Cas : Auvergne-Rhône-Alpes.
2. **L'ancre ne rattrape que les entités sans aucun `P131` dans l'univers.** Cas : Venise-la-ville,
   dont l'unique parent porte le même code ISO qu'elle — sans cette condition l'ancre la promeut
   région.
3. **Trois sauts, pas quatre.** Mesuré : à quatre sauts, l'entité sans libellé de `IT-82` remonte
   par une commune puis une province et collisionne avec la Sicile.
4. **Parent le moins profond**, et non le plus petit QID. Le départage lexicographique laissait un
   accident de numérotation décider du niveau. Cas : le Bas-Rhin, qui pend à la fois sous la
   Collectivité européenne d'Alsace et sous le Grand Est — le rattachement direct fait foi.
5. **Écartées rendues à l'appelant** avec leur motif. Sans ce canal, « ce pays a 12 subdivisions »
   est indiscernable de « 113 entités sont tombées ».
6. **Collisions ordonnées par QID.** L'ordre suivait celui des lignes SPARQL : sur les 24
   permutations de la charge `FR-69`, deux sorties distinctes.

**Et les jeux d'essai, qui étaient faux.** Les QID des fixtures actuelles sont inventés : `Q1225`
est Bruce Springsteen et non la Vénétie, `Q1273` la Toscane et non Vaud, `Q54193` une catégorie
Wikipédia. C'est ce qui a laissé passer le défaut : la logique n'avait jamais rencontré la charge
qu'elle doit traiter. Les tests portent désormais sur des **charges réelles figées**.

- [ ] **Step 1: capturer les charges réelles**

Créer `scripts/capturer_charges_referentiel.py` — un utilitaire hors suite de tests, lancé à la
main quand les fixtures doivent être rafraîchies :

```python
"""Capture les charges SPARQL réelles servant de fixtures au référentiel.

À relancer à la main quand les fixtures doivent être rafraîchies. Wikidata bouge : les
fixtures sont figées précisément pour que la suite de tests ne dépende ni du réseau ni de
l'humeur de l'endpoint.

    uv run python scripts/capturer_charges_referentiel.py
"""

import json
import pathlib
import time

from crewai_custom_tools.tools.genealogy.referentiel.config import PAYS_REFERENTIEL
from crewai_custom_tools.tools.genealogy.referentiel.wikidata import build_query
from crewai_custom_tools.tools.web.wikidata import sparql_rows

DESTINATION = pathlib.Path(__file__).parent.parent / "tests" / "fixtures" / "referentiel"
# Quatre pays suffisent : ils portent tous les cas qui ont fait basculer la conception.
# FR = conteneur intermédiaire sans ISO + collision FR-69 ; IT = villes métropolitaines,
# entité sans libellé, Venise ; CH = un sommet portant un code cantonal ; PL = une ville.
PAYS_CAPTURES = ("FR", "IT", "CH", "PL")


def main() -> None:
    DESTINATION.mkdir(parents=True, exist_ok=True)
    for code in PAYS_CAPTURES:
        pays = PAYS_REFERENTIEL[code]
        rows = sparql_rows(build_query(pays.code_iso, pays.langue, pays.qid), timeout=180.0)
        cible = DESTINATION / f"{code}.json"
        cible.write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"{code}: {len(rows)} lignes -> {cible}")
        time.sleep(4)


if __name__ == "__main__":
    main()
```

Ce script ne peut pas tourner avant l'étape 3, qui donne à `build_query` son troisième paramètre.
Écris-le maintenant, lance-le à l'étape 4.

- [ ] **Step 2: écrire les tests qui échouent**

Remplacer **intégralement** `tests/test_genealogy_referentiel_mapper.py` :

```python
# tests/test_genealogy_referentiel_mapper.py
"""Le mapper, éprouvé sur des charges Wikidata RÉELLES figées.

Les fixtures viennent de `scripts/capturer_charges_referentiel.py`. Les QID écrits à la main
dans ce fichier ont tous été vérifiés en ligne — une version antérieure de ces tests portait
des QID inventés et n'a pas vu que la France entière tombait.
"""
import json
import pathlib

import pytest

from crewai_custom_tools.tools.genealogy.referentiel.config import PAYS_REFERENTIEL
from crewai_custom_tools.tools.genealogy.referentiel.wikidata import map_subdivisions

FIXTURES = pathlib.Path(__file__).parent / "fixtures" / "referentiel"
ENTITE = "http://www.wikidata.org/entity/"


def charge(code: str) -> list[dict]:
    return json.loads((FIXTURES / f"{code}.json").read_text(encoding="utf-8"))


def ligne(qid, label, iso, parent=None, coord=None, art=None, nom_local=None, ancre=False):
    """Une ligne aplatie telle que sparql_rows la rend (clés absentes si non liées)."""
    r = {"item": ENTITE + qid, "itemLabel": label, "iso": iso}
    if parent:
        r["parent"] = ENTITE + parent
    if coord:
        r["coord"] = coord
    if art:
        r["art"] = art
    if nom_local:
        r["nomLocal"] = nom_local
    if ancre:
        r["ancre"] = "true"
    return r


# --- charges réelles : ce que les fixtures écrites à la main ne pouvaient pas voir ---

def test_la_france_ne_se_reduit_pas_a_loutre_mer():
    """Régression : les régions métropolitaines pendent sous Q212429 France métropolitaine,
    qui n'a pas de code ISO. Sans l'ancre pays, 12 entités survivaient sur 125."""
    subs, collisions, ecartees = map_subdivisions(charge("FR"), PAYS_REFERENTIEL["FR"])
    assert len(subs) > 110
    niveaux = {n: sum(1 for s in subs if s.niveau == n) for n in (1, 2)}
    assert niveaux[1] > 20 and niveaux[2] > 90
    codes = {s.code for s in subs}
    assert {"ARA", "01", "75"} & codes           # au moins une région et un département


def test_la_collision_fr_69_est_signalee_sur_la_charge_reelle():
    """Le département du Rhône et la circonscription départementale partagent FR-69."""
    subs, collisions, _ = map_subdivisions(charge("FR"), PAYS_REFERENTIEL["FR"])
    fr69 = [c for c in collisions if c.iso == "FR-69"]
    assert len(fr69) == 1
    assert sorted(fr69[0].qids) == ["Q18914778", "Q46130"]
    assert "FR-69" not in {s.iso for s in subs}   # aucune des deux n'est écrite


def test_litalie_garde_ses_villes_metropolitaines_et_ecarte_le_reste():
    subs, collisions, ecartees = map_subdivisions(charge("IT"), PAYS_REFERENTIEL["IT"])
    par_iso = {s.iso: s for s in subs}
    assert par_iso["IT-NA"].place_type == "Province"     # Naples, ville métropolitaine
    assert par_iso["IT-MI"].place_type == "Province"     # Milan, idem
    assert par_iso["IT-25"].place_type == "Region"       # Lombardie
    assert par_iso["IT-VE"].qid == "Q3678587"            # la ville métropolitaine, pas la ville
    assert collisions == []
    ecartes = {e.iso for e in ecartees}
    assert {"IT-VE", "IT-82"} <= ecartes                 # Venise-ville et l'entité sans libellé


def test_la_suisse_rend_ses_26_cantons_en_type_natif():
    subs, collisions, _ = map_subdivisions(charge("CH"), PAYS_REFERENTIEL["CH"])
    assert len(subs) == 26
    assert {s.place_type for s in subs} == {"State"}
    assert collisions == []


def test_la_pologne_ecarte_la_ville_de_kielce():
    subs, _, ecartees = map_subdivisions(charge("PL"), PAYS_REFERENTIEL["PL"])
    assert len(subs) == 16
    assert "PL-KI" in {e.iso for e in ecartees}


@pytest.mark.parametrize("code", ["FR", "IT", "CH", "PL"])
def test_toute_entite_est_retenue_ecartee_ou_en_collision(code):
    """Aucune disparition muette : chaque entité de la charge ressort quelque part."""
    rows = charge(code)
    subs, collisions, ecartees = map_subdivisions(rows, PAYS_REFERENTIEL[code])
    entrees = {r["item"].rsplit("/", 1)[-1] for r in rows}
    sorties = ({s.qid for s in subs} | {e.qid for e in ecartees}
               | {q for c in collisions for q in c.qids})
    assert entrees == sorties


@pytest.mark.parametrize("code", ["FR", "IT"])
def test_le_resultat_ne_depend_pas_de_lordre_des_lignes(code):
    """SPARQL ne garantit pas l'ordre. Deux exécutions doivent rendre le même résultat."""
    import random

    rows = charge(code)
    pays = PAYS_REFERENTIEL[code]
    reference = map_subdivisions(rows, pays)
    melange = list(rows)
    random.Random(1789).shuffle(melange)
    obtenu = map_subdivisions(melange, pays)
    assert [s.model_dump() for s in obtenu[0]] == [s.model_dump() for s in reference[0]]
    assert [c.model_dump() for c in obtenu[1]] == [c.model_dump() for c in reference[1]]


def test_les_coordonnees_ne_sont_pas_inversees():
    """WKT = Point(lon lat). Venise est à 45.4 N, 12.3 E — pas l'inverse."""
    subs, _, _ = map_subdivisions(charge("IT"), PAYS_REFERENTIEL["IT"])
    venise = next(s for s in subs if s.iso == "IT-VE")
    assert venise.lat.startswith("45.")
    assert venise.long.startswith("12.")


# --- cas qu'une charge réelle ne contient pas, en lignes vérifiées à la main ---

def test_charge_vide():
    subs, collisions, ecartees = map_subdivisions([], PAYS_REFERENTIEL["FR"])
    assert (subs, collisions, ecartees) == ([], [], [])


def test_un_cycle_de_rattachement_ecarte_les_deux_entites():
    """A parent de B, B parent de A : sans garde, la récursion ne terminerait pas."""
    rows = [ligne("Q1", "A", "FR-01", parent="Q2"),
            ligne("Q2", "B", "FR-02", parent="Q1")]
    subs, _, ecartees = map_subdivisions(rows, PAYS_REFERENTIEL["FR"])
    assert subs == []
    assert {e.iso for e in ecartees} == {"FR-01", "FR-02"}


def test_le_parent_le_moins_profond_lemporte():
    """Le Bas-Rhin pend sous la Collectivité européenne d'Alsace ET sous le Grand Est.
    Le rattachement direct fait foi, sinon il tomberait au niveau 3 et serait écarté."""
    rows = [ligne("Q1142", "Grand Est", "FR-GES", parent="Q212429", ancre=True),
            ligne("Q3153299", "Collectivité européenne d'Alsace", "FR-6AE", parent="Q1142"),
            ligne("Q1180", "Bas-Rhin", "FR-67", parent="Q3153299"),
            ligne("Q1180", "Bas-Rhin", "FR-67", parent="Q1142")]
    subs, _, _ = map_subdivisions(rows, PAYS_REFERENTIEL["FR"])
    assert {s.iso: s.niveau for s in subs} == {"FR-GES": 1, "FR-6AE": 2, "FR-67": 2}


def test_lancre_ne_rattrape_pas_une_entite_dont_un_parent_est_dans_lunivers():
    """Venise-ville : son seul parent porte le même code ISO qu'elle, donc n'est pas
    candidat — mais il est dans l'univers, donc l'ancre ne doit pas la promouvoir."""
    rows = [ligne("Q1243", "Vénétie", "IT-34", parent="Q38", ancre=True),
            ligne("Q3678587", "ville métropolitaine de Venise", "IT-VE", parent="Q1243"),
            ligne("Q641", "Venise", "IT-VE", parent="Q3678587", ancre=True)]
    subs, collisions, ecartees = map_subdivisions(rows, PAYS_REFERENTIEL["IT"])
    assert sorted(s.qid for s in subs) == ["Q1243", "Q3678587"]
    assert collisions == []
    assert [e.qid for e in ecartees] == ["Q641"]


def test_un_parent_de_meme_code_iso_nest_jamais_candidat():
    """Sans cette clause, les deux FR-69 se prennent mutuellement pour parent et l'une
    est écrite seule, sans collision signalée."""
    rows = [ligne("Q18338206", "Auvergne-Rhône-Alpes", "FR-ARA", parent="Q212429", ancre=True),
            ligne("Q46130", "Rhône", "FR-69", parent="Q18914778"),
            ligne("Q46130", "Rhône", "FR-69", parent="Q18338206"),
            ligne("Q18914778", "Rhône", "FR-69", parent="Q18338206")]
    subs, collisions, _ = map_subdivisions(rows, PAYS_REFERENTIEL["FR"])
    assert [s.iso for s in subs] == ["FR-ARA"]
    assert len(collisions) == 1 and collisions[0].qids == ["Q18914778", "Q46130"]


def test_les_noms_dapariement_portent_le_francais_puis_le_vernaculaire():
    rows = [ligne("Q980", "Bavière", "DE-BY", parent="Q183", nom_local="Bayern", ancre=True)]
    subs, _, _ = map_subdivisions(rows, PAYS_REFERENTIEL["DE"])
    assert subs[0].noms == ["Bavière", "Bayern"]


def test_les_noms_ne_repetent_pas_un_libelle_identique():
    rows = [ligne("Q12146", "Vaud", "CH-VD", parent="Q39", nom_local="Vaud", ancre=True)]
    subs, _, _ = map_subdivisions(rows, PAYS_REFERENTIEL["CH"])
    assert subs[0].noms == ["Vaud"]


def test_une_entite_sans_parent_ni_ancre_est_ecartee_avec_son_motif():
    rows = [ligne("Q999999", "orpheline", "FR-99", parent="Q888888")]
    subs, collisions, ecartees = map_subdivisions(rows, PAYS_REFERENTIEL["FR"])
    assert subs == [] and collisions == []
    assert ecartees[0].iso == "FR-99"
    assert ecartees[0].motif                      # un motif non vide, lisible par un humain
```

- [ ] **Step 3: lancer les tests, constater l'échec**

```bash
uv run python -m pytest tests/test_genealogy_referentiel_mapper.py -q
```

Attendu : échec — les fixtures n'existent pas encore et `map_subdivisions` rend deux valeurs.

- [ ] **Step 4: ajouter le modèle, l'ancre, et corriger le mapper**

Dans `models/domain.py`, après `CollisionIso` :

```python
class EntiteEcartee(BaseModel):
    """Une entité que les règles de filtrage n'ont pas retenue, et pourquoi.

    Ce canal existe pour qu'aucune disparition ne soit muette : sans lui, « ce pays a 12
    subdivisions » est indiscernable de « 113 entités sont tombées ».
    """

    qid: str
    iso: str
    libelle_fr: str
    motif: str
```

Dans `referentiel/wikidata.py`, ajouter la clause d'ancre au gabarit `_SUBDIVISIONS`, juste avant
la ligne `SERVICE wikibase:label` :

```
  OPTIONAL {{ ?item (wdt:P131|wdt:P131/wdt:P131|wdt:P131/wdt:P131/wdt:P131) wd:{qid_pays} .
              BIND(true AS ?ancre) }}
```

et donner son troisième paramètre à `build_query` :

```python
def build_query(prefixe: str, langue: str, qid_pays: str) -> str:
    """Requête des subdivisions d'un pays, par préfixe ISO 3166-2 ('FR', 'CH'…).

    `langue` rapatrie le nom vernaculaire en plus du libellé français : c'est la seule prise
    pour apparier `Bayern`, déjà en base en allemand, avant qu'un QID n'y soit posé.

    `qid_pays` sert l'**ancre** : une entité dont le pays est atteignable en un à trois sauts
    de `P131` est de premier niveau, même si le conteneur qui l'en sépare n'a pas de code ISO.
    Sans cette ancre, les régions françaises — qui pendent sous `Q212429` France métropolitaine —
    tombent toutes, et les 96 départements avec elles.
    """
    return _SUBDIVISIONS.format(prefixe=prefixe, langue=langue, qid_pays=qid_pays)
```

Puis remplacer `_choisir_parent`, `_niveau` et `map_subdivisions` par :

```python
def _candidats(entree: dict, par_qid: dict[str, dict]) -> list[str]:
    """Parents recevables : dans l'univers, et de code ISO différent de celui de l'enfant.

    La comparaison des codes est indispensable : sans elle, deux entités en collision se
    prennent mutuellement pour parent et aucune ne se résout — cas réel de `FR-69`, où
    Wikidata donne bien `Q46130 wdt:P131 Q18914778`.
    """
    return sorted(p for p in entree["parents"]
                  if p in par_qid and par_qid[p]["iso"] != entree["iso"])


def _niveaux(par_qid: dict[str, dict], qid_pays: str) -> dict[str, int]:
    """Niveau de chaque entité : 1 + celui du parent le MOINS profond, ou 1 par l'ancre.

    Le parent le moins profond l'emporte parce que le rattachement le plus direct fait foi :
    le Bas-Rhin pend sous la Collectivité européenne d'Alsace *et* sous le Grand Est ; retenir
    le plus profond le classerait au niveau 3 et le ferait écarter.

    L'ancre ne s'applique qu'aux entités dont AUCUN `P131` ne pointe dans l'univers. Sans cette
    condition, Venise-la-ville — dont l'unique parent porte le même code ISO qu'elle, donc n'est
    pas candidat — serait promue au rang de région.
    """
    candidats = {q: _candidats(e, par_qid) for q, e in par_qid.items()}
    dans_univers = {q: any(p in par_qid for p in e["parents"]) for q, e in par_qid.items()}
    memo: dict[str, int] = {}

    def niveau(qid: str, vus: frozenset) -> int:
        if qid in memo:
            return memo[qid]
        if qid in vus:                                   # cycle de rattachement
            return _NIVEAU_IMPOSSIBLE
        entree = par_qid[qid]
        resultat = _NIVEAU_IMPOSSIBLE
        profondeurs = [niveau(p, vus | {qid}) for p in candidats[qid]]
        recevables = [d for d in profondeurs if d < _NIVEAU_IMPOSSIBLE]
        if recevables:
            resultat = min(recevables) + 1
        elif not dans_univers[qid] and (entree["ancre"] or not entree["parents"]):
            resultat = 1
        if not vus:                                      # ne mémoïser que les appels racines
            memo[qid] = resultat
        return resultat

    return {qid: niveau(qid, frozenset()) for qid in par_qid}


def map_subdivisions(
    rows: list[dict], pays: PaysReferentiel,
) -> tuple[list[Subdivision], list[CollisionIso], list[EntiteEcartee]]:
    """Charge SPARQL -> subdivisions retenues, collisions, écartées. Pure, hors ligne.

    Les cinq règles de la spec §3.4. Toute entité de la charge ressort dans exactement une des
    trois listes : rien ne disparaît en silence.
    """
    par_qid = _grouper(rows)
    niveaux = _niveaux(par_qid, pays.qid)

    retenues: list[Subdivision] = []
    ecartees: list[EntiteEcartee] = []
    for qid, entree in sorted(par_qid.items()):
        niveau = niveaux[qid]
        if niveau > len(pays.niveaux):
            motif = ("rattachement introuvable" if niveau >= _NIVEAU_IMPOSSIBLE
                     else f"niveau {niveau}, or {pays.nom} en compte {len(pays.niveaux)}")
            ecartees.append(EntiteEcartee(qid=qid, iso=entree["iso"],
                                          libelle_fr=entree["label"], motif=motif))
            continue
        lat, long = (parse_wkt_point(entree["coord"]) or (None, None))
        retenues.append(Subdivision(
            qid=qid, iso=entree["iso"],
            code=code_sans_prefixe(entree["iso"], pays.code_iso),
            libelle_fr=entree["label"], noms=_noms(entree),
            place_type=pays.niveaux[niveau - 1], niveau=niveau,
            parent_qid=_parent_retenu(qid, par_qid, niveaux, pays.qid),
            lat=lat, long=long, frwiki=entree["art"]))

    par_iso: dict[str, list[Subdivision]] = defaultdict(list)
    for sub in retenues:
        par_iso[sub.iso].append(sub)
    collisions = [CollisionIso(iso=iso, qids=[s.qid for s in sorted(lot, key=lambda s: s.qid)],
                               libelles=[s.libelle_fr for s in sorted(lot, key=lambda s: s.qid)])
                  for iso, lot in sorted(par_iso.items()) if len(lot) > 1]
    propres = [lot[0] for _, lot in sorted(par_iso.items()) if len(lot) == 1]
    return propres, collisions, ecartees
```

Il te reste à écrire `_parent_retenu(qid, par_qid, niveaux, qid_pays) -> str` : le QID du parent
effectivement retenu — le candidat de niveau minimal quand il en existe, le QID du pays sinon.
Il doit rendre le **même** parent que celui qui a servi au calcul du niveau, sans quoi la
hiérarchie écrite en base ne correspondrait pas au niveau annoncé. Écris-le de façon à ne pas
dupliquer la logique de départage de `_niveaux` — extraire la sélection dans une fonction
partagée est la voie propre.

- [ ] **Step 5: adapter les tests de `build_query`**

Dans `tests/test_genealogy_referentiel_wikidata.py`, les appels à `build_query` prennent un
troisième argument. Ajouter aussi un test de la clause d'ancre :

```python
def test_build_query_demande_lancre_pays():
    """Sans elle, les régions françaises — qui pendent sous France métropolitaine, sans code
    ISO — tombent toutes, et les 96 départements avec elles."""
    q = build_query("FR", "fr", "Q142")
    assert "wd:Q142" in q
    assert "wdt:P131/wdt:P131/wdt:P131" in q      # trois sauts, pas plus
    assert "wdt:P131/wdt:P131/wdt:P131/wdt:P131" not in q
```

- [ ] **Step 6: capturer les fixtures, puis lancer les tests**

```bash
uv run python scripts/capturer_charges_referentiel.py
uv run python -m pytest tests/test_genealogy_referentiel_mapper.py -q
```

Attendu : tous les tests passent. Si une charge réelle contredit un test, **ne modifie pas le
test pour qu'il passe** — rapporte la contradiction, c'est exactement ce qu'on cherche à voir.

Ordres de grandeur mesurés le 2026-07-21, à titre de contrôle : France 121 retenues
(26 de niveau 1, 95 de niveau 2), 1 collision, 2 écartées ; Italie 124 retenues (20 régions,
104 provinces), 0 collision, 2 écartées ; Suisse 26, 0, 1 ; Pologne 16, 0, 1.

- [ ] **Step 7: suite complète, puis commit**

```bash
uv run python -m pytest tests/ -q
uv run ruff check .
git add src/ tests/ scripts/
git commit -m "fix(referentiel): ancre pays, écartées rendues, départage et ordre déterministes"
```

---

### Task 4 : couche réseau, reprises et pays en échec

**Files:**
- Create: `src/crewai_custom_tools/tools/genealogy/referentiel/chargement.py`
- Test: `tests/test_genealogy_referentiel_chargement.py`

**Interfaces:**
- Consumes: `build_query`, `build_query_pays`, `map_subdivisions`, `qid_of`, `PAYS_REFERENTIEL`.
- Produces:
  - `charger_pays(pays: PaysReferentiel, *, essais: int = 3, pause: float = 5.0) -> ResultatPays`
  - `charger_entites_pays(qids: list[str]) -> dict[str, EntitePays]`
  - modèles `ResultatPays` (`code_iso`, `subdivisions`, `collisions`, `erreur`) et `EntitePays`
    (`qid`, `libelle_fr`, `lat`, `long`, `frwiki`), définis dans ce module.

Wikidata a rendu un 502 dès le second pays pendant la conception : les reprises ne sont pas
décoratives.

- [ ] **Step 1: écrire le test qui échoue**

Créer `tests/test_genealogy_referentiel_chargement.py` :

```python
# tests/test_genealogy_referentiel_chargement.py
"""Transport : reprises, pays en échec isolé, temporisation."""
import pytest

from crewai_custom_tools.tools.genealogy.referentiel import chargement
from crewai_custom_tools.tools.genealogy.referentiel.config import PAYS_REFERENTIEL

CH = PAYS_REFERENTIEL["CH"]
ENTITE = "http://www.wikidata.org/entity/"


def test_charger_pays_rend_les_subdivisions(monkeypatch):
    monkeypatch.setattr(chargement, "sparql_rows", lambda q, timeout=0: [
        {"item": ENTITE + "Q12771", "itemLabel": "Vaud", "iso": "CH-VD",
         "parent": ENTITE + "Q39"}])
    res = chargement.charger_pays(CH)
    assert res.erreur is None
    assert [s.iso for s in res.subdivisions] == ["CH-VD"]


def test_charger_pays_reessaye_puis_reussit(monkeypatch):
    appels = {"n": 0}

    def flaky(query, timeout=0):
        appels["n"] += 1
        if appels["n"] < 3:
            raise chargement.RequestException("502 Bad Gateway")
        return [{"item": ENTITE + "Q12771", "itemLabel": "Vaud", "iso": "CH-VD",
                 "parent": ENTITE + "Q39"}]

    monkeypatch.setattr(chargement, "sparql_rows", flaky)
    monkeypatch.setattr(chargement.time, "sleep", lambda s: None)
    res = chargement.charger_pays(CH, essais=3, pause=0.0)
    assert appels["n"] == 3
    assert res.erreur is None and len(res.subdivisions) == 1


def test_un_pays_en_echec_est_signale_et_ne_leve_pas(monkeypatch):
    def toujours_ko(query, timeout=0):
        raise chargement.RequestException("504 Gateway Timeout")

    monkeypatch.setattr(chargement, "sparql_rows", toujours_ko)
    monkeypatch.setattr(chargement.time, "sleep", lambda s: None)
    res = chargement.charger_pays(CH, essais=2, pause=0.0)
    assert res.subdivisions == [] and res.collisions == []
    assert "504" in res.erreur


def test_temporisation_avant_chaque_appel(monkeypatch):
    acquis = []
    monkeypatch.setattr(chargement, "sparql_rows", lambda q, timeout=0: [])
    monkeypatch.setattr(chargement, "get_rate_limiter",
                        lambda: type("L", (), {"acquire": lambda self, p: acquis.append(p)})())
    chargement.charger_pays(CH)
    assert acquis == ["Wikidata"]


def test_charger_entites_pays(monkeypatch):
    monkeypatch.setattr(chargement, "sparql_rows", lambda q, timeout=0: [
        {"item": ENTITE + "Q39", "itemLabel": "Suisse", "coord": "Point(8.23 46.80)",
         "art": "https://fr.wikipedia.org/wiki/Suisse"}])
    entites = chargement.charger_entites_pays(["Q39"])
    assert entites["Q39"].libelle_fr == "Suisse"
    assert (entites["Q39"].lat, entites["Q39"].long) == ("46.80", "8.23")
    assert entites["Q39"].frwiki.endswith("/Suisse")


def test_charger_entites_pays_en_echec_rend_un_dictionnaire_vide(monkeypatch):
    def ko(query, timeout=0):
        raise chargement.RequestException("boom")

    monkeypatch.setattr(chargement, "sparql_rows", ko)
    monkeypatch.setattr(chargement.time, "sleep", lambda s: None)
    assert chargement.charger_entites_pays(["Q39"], essais=1, pause=0.0) == {}
```

- [ ] **Step 2: lancer le test, vérifier qu'il échoue**

```bash
uv run python -m pytest tests/test_genealogy_referentiel_chargement.py -q
```

Attendu : `ModuleNotFoundError: ... referentiel.chargement`

- [ ] **Step 3: écrire le module**

Créer `src/crewai_custom_tools/tools/genealogy/referentiel/chargement.py` :

```python
"""Transport du référentiel : appels Wikidata temporisés, avec reprises.

Un pays qui échoue après reprises est *signalé*, pas fatal : les autres sont livrés.
Wikidata a rendu un 502 dès le second pays pendant la conception du chantier.
"""

from __future__ import annotations

import time

from pydantic import BaseModel, Field
from requests.exceptions import RequestException

from crewai_custom_tools.core.rate_limiter import get_rate_limiter
from crewai_custom_tools.tools.genealogy.geo.france_ex_communes import parse_wkt_point
from crewai_custom_tools.tools.genealogy.models.domain import (
    CollisionIso, EntiteEcartee, Subdivision,
)
from crewai_custom_tools.tools.genealogy.referentiel.config import PaysReferentiel
from crewai_custom_tools.tools.genealogy.referentiel.wikidata import (
    build_query, build_query_pays, map_subdivisions, qid_of,
)
from crewai_custom_tools.tools.web.wikidata import sparql_rows

_PROVIDER = "Wikidata"
_TIMEOUT = 120.0


class ResultatPays(BaseModel):
    """Ce qu'un pays a rendu : ses subdivisions, ses collisions, ou son erreur."""

    code_iso: str
    subdivisions: list[Subdivision] = Field(default_factory=list)
    collisions: list[CollisionIso] = Field(default_factory=list)
    ecartees: list[EntiteEcartee] = Field(default_factory=list)
    erreur: str | None = None


class EntitePays(BaseModel):
    """Le pays lui-même : ce qu'on posera sur son lieu Gramps."""

    qid: str
    libelle_fr: str
    lat: str | None = None
    long: str | None = None
    frwiki: str | None = None


def _interroger(query: str, essais: int, pause: float) -> list[dict]:
    """Appel temporisé, avec reprises à attente croissante. Relève la dernière erreur."""
    derniere: Exception | None = None
    for tentative in range(essais):
        try:
            get_rate_limiter().acquire(_PROVIDER)
            return sparql_rows(query, timeout=_TIMEOUT)
        except RequestException as exc:
            derniere = exc
            if tentative < essais - 1:
                time.sleep(pause * (tentative + 1))
    raise derniere if derniere else RuntimeError("échec sans exception")


def charger_pays(pays: PaysReferentiel, *, essais: int = 3,
                 pause: float = 5.0) -> ResultatPays:
    """Interroge Wikidata pour un pays et applique le mapper. N'lève jamais."""
    try:
        rows = _interroger(build_query(pays.code_iso, pays.langue, pays.qid), essais, pause)
    except RequestException as exc:
        return ResultatPays(code_iso=pays.code_iso, erreur=str(exc))
    subdivisions, collisions, ecartees = map_subdivisions(rows, pays)
    return ResultatPays(code_iso=pays.code_iso, subdivisions=subdivisions,
                        collisions=collisions, ecartees=ecartees)


def charger_entites_pays(qids: list[str], *, essais: int = 3,
                         pause: float = 5.0) -> dict[str, EntitePays]:
    """Les pays eux-mêmes, en un seul appel. Dictionnaire vide si l'appel échoue."""
    try:
        rows = _interroger(build_query_pays(qids), essais, pause)
    except RequestException:
        return {}
    entites: dict[str, EntitePays] = {}
    for row in rows:
        qid = qid_of(row.get("item"))
        if not qid or qid in entites:
            continue
        lat, long = (parse_wkt_point(row.get("coord")) or (None, None))
        entites[qid] = EntitePays(qid=qid, libelle_fr=row.get("itemLabel", ""),
                                  lat=lat, long=long, frwiki=row.get("art"))
    return entites
```

- [ ] **Step 4: lancer le test, vérifier qu'il passe**

```bash
uv run python -m pytest tests/test_genealogy_referentiel_chargement.py -q
```

Attendu : `6 passed`

- [ ] **Step 5: commit**

```bash
git add src/crewai_custom_tools/tools/genealogy/referentiel/chargement.py \
        tests/test_genealogy_referentiel_chargement.py
git commit -m "feat(referentiel): chargement Wikidata temporisé, un pays en échec n'arrête rien"
```

---

### Task 5 : le résolveur suisse rend un type natif

**Files:**
- Modify: `src/crewai_custom_tools/tools/genealogy/geo/suisse.py:19-20,61`
- Test: `tests/test_genealogy_geo_suisse.py`

**Interfaces:**
- Produces: aucun changement de signature. `map_swiss` rend désormais
  `PlaceLevel(place_type="State")` là où il rendait `"Canton"`.

- [ ] **Step 1: écrire le test qui échoue**

Ajouter à la fin de `tests/test_genealogy_geo_suisse.py` :

```python
def test_le_canton_est_pose_avec_un_type_gramps_natif():
    """`Canton` n'est pas un type Gramps natif. Un type personnalisé est une ligne de plus
    à ne pas oublier dans chaque filtre par type — on s'en tient à `State`."""
    from crewai_custom_tools.tools.genealogy.geo.suisse import map_swiss
    from crewai_custom_tools.tools.genealogy.models.domain import ParsedPlace

    payload = {"results": [{"attrs": {"label": "Montreux (VD)", "lat": 46.43, "lon": 6.91}}]}
    resolved = map_swiss(payload, ParsedPlace(raw="Montreux", commune="Montreux"))
    types = [niveau.place_type for niveau in resolved.chains[0].levels]
    assert types == ["Country", "State"]
    assert "Canton" not in types
```

- [ ] **Step 2: lancer le test, vérifier qu'il échoue**

```bash
uv run python -m pytest tests/test_genealogy_geo_suisse.py -q
```

Attendu : `AssertionError: assert ['Country', 'Canton'] == ['Country', 'State']`

- [ ] **Step 3: corriger le résolveur**

Dans `src/crewai_custom_tools/tools/genealogy/geo/suisse.py`, remplacer la ligne 61 :

```python
        levels.append(PlaceLevel(name=canton, place_type="State"))
```

et corriger le commentaire des lignes 19-20 :

```python
# swisstopo étiquette chaque commune "Nom (XX)" où XX = code du canton. On récupère le canton
# comme niveau parent (Suisse › Canton › Commune), analogue au département FR / Land DE.
# Le type Gramps posé est `State` et non `Canton` : `Canton` n'est pas un type natif, et
# chaque type personnalisé est une ligne de plus à ne pas oublier dans les filtres par type.
```

- [ ] **Step 4: lancer toute la suite bibliothèque**

```bash
uv run python -m pytest tests/ -q
```

Attendu : zéro échec. Si un autre test attendait `"Canton"`, le corriger — c'est la même
décision, pas une régression.

- [ ] **Step 5: commit**

```bash
git add src/crewai_custom_tools/tools/genealogy/geo/suisse.py tests/test_genealogy_geo_suisse.py
git commit -m "fix(geo): le canton suisse prend le type Gramps natif State"
```

---

### Task 6 : `parse_pname` reconnaît le suffixe de code cantonal

C'est le correctif du bug d'origine : sans lui, `resolve_ch` n'est jamais appelé et les cantons
restent vides.

**Files:**
- Modify: `src/crewai_custom_tools/tools/genealogy/standardize/places.py`
- Test: `tests/test_genealogy_places_parse.py`

**Interfaces:**
- Consumes: `_CANTONS` et `_split_label` (`geo/suisse.py:21-39`) — **réutiliser, ne pas dupliquer**.
- Produces: aucun changement de signature de `parse_pname`.

Attention à l'import : `standardize/places.py` importerait `geo/suisse.py`. Vérifier qu'aucun
cycle n'apparaît (`geo/suisse.py` importe `models.domain` et `geo.score`, pas `standardize`).

- [ ] **Step 1: écrire le test qui échoue**

Ajouter à `tests/test_genealogy_places_parse.py` :

```python
def test_suffixe_de_code_cantonal_sur_un_nom_sans_virgule_donne_la_suisse():
    """Forme réelle de 19 lieux de l'arbre : `Montreux (VD)`. Sans cette règle, le pays
    reste vide, resolve_ch n'est jamais appelé et la hiérarchie revient vide."""
    from crewai_custom_tools.tools.genealogy.standardize.places import parse_pname

    parsed = parse_pname("Montreux (VD)")
    assert parsed.country == "Suisse"
    assert parsed.commune == "Montreux"


def test_le_suffixe_est_retire_de_la_commune_interrogee():
    from crewai_custom_tools.tools.genealogy.standardize.places import parse_pname

    assert parse_pname("Genève (GE)").commune == "Genève"


def test_un_nom_a_virgules_ne_declenche_pas_la_regle_cantonale():
    """Un nom à virgules a déjà un segment pays exploitable : la règle n'a pas à s'en mêler."""
    from crewai_custom_tools.tools.genealogy.standardize.places import parse_pname

    parsed = parse_pname("Springfield (BE), Illinois, United States")
    assert parsed.country == "États-Unis"


def test_un_suffixe_a_deux_lettres_hors_table_reste_non_suisse():
    from crewai_custom_tools.tools.genealogy.standardize.places import parse_pname

    parsed = parse_pname("Springfield (NY)")
    assert parsed.country != "Suisse"
```

- [ ] **Step 2: lancer le test, vérifier qu'il échoue**

```bash
uv run python -m pytest tests/test_genealogy_places_parse.py -q
```

Attendu : `AssertionError: assert '' == 'Suisse'`

- [ ] **Step 3: écrire la règle**

Dans `src/crewai_custom_tools/tools/genealogy/standardize/places.py`, ajouter l'import en tête :

```python
from crewai_custom_tools.tools.genealogy.geo.suisse import split_canton_suffix
```

et insérer, dans `parse_pname`, **juste avant** le calcul de `used` (l'actuelle ligne 100) :

```python
    # Forme `Montreux (VD)` : un nom sans virgule suffixé d'un code cantonal suisse. Le
    # segment unique a été pris pour la commune et le pays est resté vide, donc resolve_ch
    # n'aurait jamais été appelé. La condition « sans virgule » est le garde-fou : `(XX)`
    # en suffixe existe ailleurs (`(NY)`), et `GE`/`BE`/`JU` sont des chaînes courtes.
    if not country and len(segments) == 1:
        nom_nu, canton = split_canton_suffix(commune)
        if canton:
            commune = nom_nu
            country = "Suisse"
```

Dans `geo/suisse.py`, exposer la fonction existante sous un nom public sans la dupliquer,
juste après `_split_label` :

```python
def split_canton_suffix(label: str) -> tuple[str, str | None]:
    """'Montreux (VD)' -> ('Montreux', 'Vaud'). Alias public de `_split_label`, utilisé par
    le parseur de lieux pour reconnaître un nom suisse dépourvu de segment pays."""
    return _split_label(label)
```

- [ ] **Step 4: lancer le test, vérifier qu'il passe**

```bash
uv run python -m pytest tests/test_genealogy_places_parse.py -q
```

Attendu : zéro échec, 4 tests nouveaux passés.

- [ ] **Step 5: vérifier de bout en bout, sans réseau**

```bash
uv run python -c "
from crewai_custom_tools.tools.genealogy.standardize.places import parse_pname
p = parse_pname('Montreux (VD)')
print(p.commune, '|', p.country)
"
```

Attendu : `Montreux | Suisse`

- [ ] **Step 6: toute la suite, puis commit**

```bash
uv run python -m pytest tests/ -q
git add src/crewai_custom_tools/tools/genealogy/standardize/places.py \
        src/crewai_custom_tools/tools/genealogy/geo/suisse.py \
        tests/test_genealogy_places_parse.py
git commit -m "fix(lieux): reconnaître le suffixe de code cantonal sur un nom sans virgule"
```

---

### Task 7 : publier la bibliothèque — **étape humaine**

**Files:**
- Modify: `pyproject.toml` (worktree bibliothèque), `version = "0.23.1"` → `"0.24.0"`
- Modify: `uv.lock` (worktree genecrew), via `uv sync`

**Interfaces:**
- Produces: le tag `v0.24.0` sur lequel la CI de genecrew checkoutera la bibliothèque.

> **Un agent ne fusionne, ne pousse ni ne tague jamais.** Cette friction inter-dépôts est un
> contrôle qualité délibéré. Les commandes ci-dessous sont à exécuter par l'humain, ou par
> l'agent uniquement sur demande explicite.

- [ ] **Step 1: bumper la version de la bibliothèque**

Dans le worktree bibliothèque, `pyproject.toml` ligne 7 :

```toml
version = "0.24.0"
```

- [ ] **Step 2: commit, puis fusion et tag par l'humain**

```bash
git add pyproject.toml && git commit -m "chore: 0.24.0 — référentiel des subdivisions"
# puis, côté humain : fusionner feat/referentiel-subdivisions dans main,
# taguer v0.24.0 et pousser le tag.
```

- [ ] **Step 3: rafraîchir le lock de genecrew**

Depuis le worktree genecrew :

```bash
uv sync
uv run python -c "import crewai_custom_tools, importlib.metadata as m; print(m.version('crewai-custom-tools'))"
```

Attendu : `0.24.0`

- [ ] **Step 4: commit du lock**

```bash
git add uv.lock pyproject.toml
git commit -m "chore(deps): crewai-custom-tools 0.24.0"
```

---

### Task 8 : `propose referentiel` — rapport et YAML, lecture seule

**Files:**
- Create: `genecrew/src/genecrew/referentiel.py`
- Test: `genecrew/tests/test_referentiel.py`

**Interfaces:**
- Consumes: `PAYS_REFERENTIEL`, `charger_pays`, `charger_entites_pays`, `ResultatPays`,
  `EntitePays`, `Subdivision`, `CollisionIso`.
- Produces:
  - `doublons_de_larbre(places: list[dict]) -> list[dict]`
  - `render_referentiel_report(date, resultats, entites, doublons, base_url="http://localhost") -> str`
  - `render_referentiel_yaml(resultats, entites, doublons) -> str`
  - `run_referentiel(client, output_dir, *, date, codes_pays) -> tuple[Path, Path]`

Deux natures de doublons, à ne pas confondre : les **collisions ISO** viennent de Wikidata
(deux entités sous un même code), les **doublons de l'arbre** viennent de Gramps (deux lieux de
même nom, même type, même parent — le cas des deux `France`). Le rapport les sépare.

Le YAML est le contrat avec la tâche 9 : `apply referentiel` ne lit que lui, et ne réinterroge
jamais Wikidata (spec §6).

- [ ] **Step 1: écrire le test qui échoue**

Créer `genecrew/tests/test_referentiel.py` :

```python
# genecrew/tests/test_referentiel.py
"""Rendu du rapport et du YAML de `propose referentiel`. Pur, hors ligne."""
import yaml

from crewai_custom_tools.tools.genealogy.models.domain import CollisionIso, Subdivision
from crewai_custom_tools.tools.genealogy.referentiel.chargement import EntitePays, ResultatPays

from genecrew.referentiel import (
    doublons_de_larbre, render_referentiel_report, render_referentiel_yaml,
)

VAUD = Subdivision(qid="Q12771", iso="CH-VD", code="VD", libelle_fr="canton de Vaud",
                   place_type="State", niveau=1, parent_qid="Q39",
                   lat="46.6", long="6.6", frwiki="https://fr.wikipedia.org/wiki/Canton_de_Vaud")
SUISSE = EntitePays(qid="Q39", libelle_fr="Suisse", lat="46.8", long="8.2",
                    frwiki="https://fr.wikipedia.org/wiki/Suisse")


def test_le_rapport_compte_les_subdivisions_par_pays():
    md = render_referentiel_report("2026-07-21", [ResultatPays(code_iso="CH", subdivisions=[VAUD])],
                                   {"Q39": SUISSE}, [])
    assert "CH" in md and "canton de Vaud" in md
    assert "State" in md


def test_doublons_de_larbre_repere_deux_lieux_identiques():
    """Le cas des deux `France` : même nom, même type, même parent. L'index chemin -> handle
    de places_apply écrase silencieusement la clé, donc rien ne les signalait."""
    places = [
        {"handle": "h1", "gramps_id": "P0295", "name": {"value": "France"},
         "place_type": "Country", "placeref_list": []},
        {"handle": "h2", "gramps_id": "P0386", "name": {"value": "France"},
         "place_type": "Country", "placeref_list": []},
        {"handle": "h3", "gramps_id": "P0340", "name": {"value": "Suisse"},
         "place_type": "Country", "placeref_list": []},
    ]
    doublons = doublons_de_larbre(places)
    assert len(doublons) == 1
    assert doublons[0]["nom"] == "France"
    assert sorted(doublons[0]["gramps_ids"]) == ["P0295", "P0386"]


def test_deux_homonymes_sous_des_parents_differents_ne_sont_pas_des_doublons():
    places = [
        {"handle": "a", "gramps_id": "P1", "name": {"value": "Saint-Jean"},
         "place_type": "Municipality", "placeref_list": [{"ref": "p1"}]},
        {"handle": "b", "gramps_id": "P2", "name": {"value": "Saint-Jean"},
         "place_type": "Municipality", "placeref_list": [{"ref": "p2"}]},
    ]
    assert doublons_de_larbre(places) == []


def test_le_rapport_signale_les_doublons_de_larbre():
    md = render_referentiel_report(
        "2026-07-21", [], {},
        [{"nom": "France", "place_type": "Country", "gramps_ids": ["P0295", "P0386"]}])
    assert "P0295" in md and "P0386" in md
    assert "merge places" in md          # la fusion reste manuelle


def test_le_rapport_signale_les_collisions_sans_les_ecrire():
    collision = CollisionIso(iso="FR-69", qids=["Q46130", "Q18914778"],
                             libelles=["Rhône", "Rhône"])
    md = render_referentiel_report(
        "2026-07-21", [ResultatPays(code_iso="FR", collisions=[collision])], {}, [])
    assert "FR-69" in md
    assert "Q46130" in md and "Q18914778" in md


def test_le_rapport_nomme_les_pays_en_echec():
    md = render_referentiel_report(
        "2026-07-21", [ResultatPays(code_iso="IT", erreur="504 Gateway Timeout")], {}, [])
    assert "IT" in md and "504" in md


def test_le_yaml_porte_les_subdivisions_et_les_pays():
    doc = yaml.safe_load(render_referentiel_yaml(
        [ResultatPays(code_iso="CH", subdivisions=[VAUD])], {"Q39": SUISSE}, []))
    assert doc["pays"][0]["qid"] == "Q39"
    assert doc["subdivisions"][0]["iso"] == "CH-VD"
    assert doc["subdivisions"][0]["place_type"] == "State"
    assert doc["subdivisions"][0]["parent_qid"] == "Q39"


def test_le_yaml_ne_contient_pas_les_collisions_dans_les_subdivisions():
    collision = CollisionIso(iso="FR-69", qids=["Q46130", "Q18914778"],
                             libelles=["Rhône", "Rhône"])
    doc = yaml.safe_load(render_referentiel_yaml(
        [ResultatPays(code_iso="FR", subdivisions=[], collisions=[collision])], {}, []))
    assert doc["subdivisions"] == []
    assert doc["collisions"][0]["iso"] == "FR-69"
```

- [ ] **Step 2: lancer le test, vérifier qu'il échoue**

Depuis le worktree genecrew :

```bash
uv run python -m pytest genecrew/tests/test_referentiel.py -q
```

Attendu : `ModuleNotFoundError: No module named 'genecrew.referentiel'`

- [ ] **Step 3: écrire le module**

Créer `genecrew/src/genecrew/referentiel.py` :

```python
"""`propose referentiel` : les subdivisions administratives des pays, en lecture seule.

Interroge Wikidata pays par pays, rend un rapport Markdown et le YAML que `apply referentiel`
consommera. N'écrit jamais dans Gramps.
"""

from __future__ import annotations

from collections import defaultdict
from pathlib import Path

import yaml

from crewai_custom_tools.tools.genealogy.referentiel.chargement import (
    EntitePays, ResultatPays, charger_entites_pays, charger_pays,
)
from crewai_custom_tools.tools.genealogy.referentiel.config import PAYS_REFERENTIEL


def doublons_de_larbre(places: list[dict]) -> list[dict]:
    """Lieux partageant nom + type + parent : signalés, jamais fusionnés (spec §5.4).

    C'est le cas des deux `France`. Rien ne les signalait parce que l'index
    `chemin -> handle` de `places_apply._seed_parent_index` écrase silencieusement la clé
    quand deux lieux mènent au même chemin — la structure qui sert à décider est celle qui
    les rend invisibles.
    """
    groupes: dict[tuple[str, str, str], list[dict]] = defaultdict(list)
    for place in places:
        nom = (place.get("name") or {}).get("value", "")
        if not nom:
            continue
        refs = place.get("placeref_list") or []
        parent = refs[0].get("ref", "") if refs else ""
        groupes[(nom, place.get("place_type", ""), parent)].append(place)
    return [{"nom": nom, "place_type": type_, "parent": parent,
             "gramps_ids": [p.get("gramps_id", "") for p in lot],
             "handles": [p["handle"] for p in lot]}
            for (nom, type_, parent), lot in sorted(groupes.items()) if len(lot) > 1]


def render_referentiel_report(date: str, resultats: list[ResultatPays],
                              entites: dict[str, EntitePays],
                              doublons: list[dict],
                              base_url: str = "http://localhost") -> str:
    """Rapport Markdown pur : synthèse par pays, collisions, doublons, pays en échec."""
    total = sum(len(r.subdivisions) for r in resultats)
    lignes = [f"# Référentiel des subdivisions — {date}", "",
              "## Synthèse", "",
              f"- Pays interrogés : {len(resultats)}",
              f"- Pays en échec : {sum(1 for r in resultats if r.erreur)}",
              f"- Subdivisions retenues : {total}",
              f"- Collisions signalées : {sum(len(r.collisions) for r in resultats)}",
              f"- Entités écartées : {sum(len(r.ecartees) for r in resultats)}",
              f"- Entités pays résolues : {len(entites)}", "",
              "## Par pays", "",
              "| Pays | Niveau 1 | Niveau 2 | Collisions | Écartées | Erreur |",
              "|---|---|---|---|---|---|"]
    for res in sorted(resultats, key=lambda r: r.code_iso):
        n1 = sum(1 for s in res.subdivisions if s.niveau == 1)
        n2 = sum(1 for s in res.subdivisions if s.niveau == 2)
        lignes.append(f"| {res.code_iso} | {n1} | {n2} | {len(res.collisions)} "
                      f"| {len(res.ecartees)} | {res.erreur or '—'} |")
    lignes += ["", "## Subdivisions", "",
               "| Pays | ISO | Code | Nom | Type | Niveau | GPS | Article |",
               "|---|---|---|---|---|---|---|---|"]
    for res in sorted(resultats, key=lambda r: r.code_iso):
        for sub in sorted(res.subdivisions, key=lambda s: s.iso):
            gps = f"{sub.lat},{sub.long}" if sub.lat and sub.long else "—"
            art = "oui" if sub.frwiki else "—"
            lignes.append(f"| {res.code_iso} | {sub.iso} | {sub.code} | {sub.libelle_fr} "
                          f"| {sub.place_type} | {sub.niveau} | {gps} | {art} |")

    collisions = [(r.code_iso, c) for r in resultats for c in r.collisions]
    if collisions:
        lignes += ["", "## Collisions — signalées, jamais écrites", "",
                   "Deux entités partagent un code ISO au même niveau : rien ne dit laquelle "
                   "porte la vérité, donc aucune des deux n'est écrite.", "",
                   "| Pays | ISO | QID | Libellés |", "|---|---|---|---|"]
        for code_pays, col in collisions:
            lignes.append(f"| {code_pays} | {col.iso} | {', '.join(col.qids)} "
                          f"| {', '.join(col.libelles)} |")

    if doublons:
        lignes += ["", "## Doublons déjà dans l'arbre — à fusionner à la main", "",
                   "Ces lieux partagent nom, type et parent. La fusion n'est jamais "
                   "automatique : rien ne dit lequel porte la vérité. Les arbitrer avec "
                   "`merge places`.", "",
                   "| Nom | Type | Lieux |", "|---|---|---|"]
        for doublon in doublons:
            liens = ", ".join(f"[{gid}]({base_url}/place/{gid})"
                              for gid in doublon["gramps_ids"])
            lignes.append(f"| {doublon['nom']} | {doublon['place_type']} | {liens} |")
    lignes.append("")
    return "\n".join(lignes)


def render_referentiel_yaml(resultats: list[ResultatPays],
                            entites: dict[str, EntitePays],
                            doublons: list[dict]) -> str:
    """Le YAML relu par l'humain, et seule entrée de `apply referentiel`."""
    doc = {
        "pays": [e.model_dump() for e in entites.values()],
        "subdivisions": [s.model_dump() for r in resultats for s in r.subdivisions],
        "collisions": [c.model_dump() for r in resultats for c in r.collisions],
        "ecartees": [e.model_dump() for r in resultats for e in r.ecartees],
        "doublons_arbre": doublons,
        "echecs": [{"code_iso": r.code_iso, "erreur": r.erreur}
                   for r in resultats if r.erreur],
    }
    return yaml.safe_dump(doc, allow_unicode=True, sort_keys=False)


def run_referentiel(client, output_dir, *, date: str,
                    codes_pays: list[str] | None = None) -> tuple[Path, Path]:
    """Interroge les pays demandés (tous par défaut) ; écrit rapport et YAML. Lecture seule."""
    codes = codes_pays or sorted(PAYS_REFERENTIEL)
    resultats = [charger_pays(PAYS_REFERENTIEL[code]) for code in codes]
    entites = charger_entites_pays([PAYS_REFERENTIEL[code].qid for code in codes])
    places = [place for lot in iter_places(client, "all", 200, None) for place in lot]
    doublons = doublons_de_larbre(places)

    out = Path(output_dir) / "referentiel"
    out.mkdir(parents=True, exist_ok=True)
    suffixe = "tous" if codes_pays is None else "-".join(codes)
    report_path = out / f"{date}_referentiel_{suffixe}.md"
    report_path.write_text(render_referentiel_report(date, resultats, entites, doublons),
                           encoding="utf-8")
    yaml_path = out / f"{date}_propositions_referentiel_{suffixe}.yaml"
    yaml_path.write_text(render_referentiel_yaml(resultats, entites, doublons),
                         encoding="utf-8")
    return report_path, yaml_path
```

- [ ] **Step 4: lancer le test, vérifier qu'il passe**

```bash
uv run python -m pytest genecrew/tests/test_referentiel.py -q
```

Attendu : `8 passed`

- [ ] **Step 5: commit**

```bash
git add genecrew/src/genecrew/referentiel.py genecrew/tests/test_referentiel.py
git commit -m "feat(referentiel): propose referentiel, rapport et YAML en lecture seule"
```

---

### Task 9 : `apply referentiel` — appariement et écritures

**Files:**
- Create: `genecrew/src/genecrew/referentiel_apply.py`
- Test: `genecrew/tests/test_referentiel_apply.py`

**Interfaces:**
- Consumes: le YAML de la tâche 8 ; `GrampsCreatePlaceTool`, `GrampsUpdatePlaceTool`,
  `GrampsAddUrlTool`, `effective_dry_run`.
- Produces:
  - `TYPES_CONTENANTS: frozenset[str]`
  - `index_par_qid(places: list[dict]) -> dict[str, str]` — QID → handle, lu dans les `urls`
  - `index_par_nom_type(places: list[dict]) -> dict[tuple[str, str], str]`
  - `index_par_nom_contenant(places: list[dict]) -> dict[str, str]`
  - `apparier(sub, par_qid, par_nom_type, par_nom) -> str | None`
  - `decider(sub, place) -> dict` — les champs à écrire, jamais ceux déjà remplis
  - `run_referentiel_apply(client, yaml_path, output_dir, *, date, dry_run) -> Path`

L'appariement se fait en trois prises, dans l'ordre : le QID, puis (nom, type), puis le nom seul
**parmi les lieux contenants uniquement**. La troisième prise n'est pas un luxe : sans elle,
`Souk Ahras` typée `Wilaya` ne serait jamais reconnue par une subdivision de type `Province`, et
le retypage promis au §4 de la spec n'aurait jamais lieu. La restriction aux contenants évite
qu'une commune nommée `Genève` soit prise pour le canton.

Rappel de l'invariant (spec §5.5) : création, remplissage d'un champ vide, ou ajout dans une
liste. Seule exception, le retypage des `Wilaya` en `Province`.

- [ ] **Step 1: écrire le test qui échoue**

Créer `genecrew/tests/test_referentiel_apply.py` :

```python
# genecrew/tests/test_referentiel_apply.py
"""Appariement et invariant d'écriture de `apply referentiel`. Pur, hors ligne."""
from crewai_custom_tools.tools.genealogy.models.domain import Subdivision

from genecrew.referentiel_apply import (
    apparier, decider, index_par_nom_contenant, index_par_nom_type, index_par_qid,
)

VAUD = Subdivision(qid="Q12771", iso="CH-VD", code="VD", libelle_fr="canton de Vaud",
                   noms=["canton de Vaud"], place_type="State", niveau=1, parent_qid="Q39",
                   lat="46.6", long="6.6", frwiki="https://fr.wikipedia.org/wiki/Canton_de_Vaud")


def test_le_qid_prime_sur_les_noms():
    par_qid = {"Q12771": "h_qid"}
    par_nom_type = {("canton de Vaud", "State"): "h_nom"}
    assert apparier(VAUD, par_qid, par_nom_type, {}) == "h_qid"


def test_appariement_par_nom_vernaculaire_quand_aucun_qid_nest_pose():
    """Premier run : `Bayern` est en base en allemand, la subdivision arrive en français."""
    bayern = Subdivision(qid="Q980", iso="DE-BY", code="BY", libelle_fr="Bavière",
                         noms=["Bavière", "Bayern"], place_type="State", niveau=1,
                         parent_qid="Q183")
    par_nom_type = {("Bayern", "State"): "h_bayern"}
    assert apparier(bayern, {}, par_nom_type, {}) == "h_bayern"


def test_appariement_par_nom_seul_pour_retyper_une_wilaya():
    """Souk Ahras est typée `Wilaya` : aucune clé (nom, type) ne peut la retrouver."""
    souk = Subdivision(qid="Q236772", iso="DZ-41", code="41", libelle_fr="Souk Ahras",
                       noms=["Souk Ahras"], place_type="Province", niveau=1, parent_qid="Q262")
    assert apparier(souk, {}, {}, {"Souk Ahras": "h_wilaya"}) == "h_wilaya"


def test_index_par_nom_contenant_ignore_les_communes():
    """Une commune homonyme ne doit jamais être prise pour son canton."""
    places = [{"handle": "h_commune", "name": {"value": "Genève"},
               "place_type": "Municipality"},
              {"handle": "h_wilaya", "name": {"value": "Souk Ahras"},
               "place_type": "Wilaya"}]
    assert index_par_nom_contenant(places) == {"Souk Ahras": "h_wilaya"}


def test_index_par_qid_lit_lurl_wikidata():
    places = [{"handle": "h1", "urls": [
        {"path": "https://www.wikidata.org/wiki/Q12771", "desc": "Wikidata"}]}]
    assert index_par_qid(places) == {"Q12771": "h1"}


def test_index_par_qid_ignore_les_autres_urls():
    places = [{"handle": "h1", "urls": [
        {"path": "https://fr.wikipedia.org/wiki/Vaud", "desc": "Wikipédia"}]}]
    assert index_par_qid(places) == {}


def test_index_par_nom_type():
    places = [{"handle": "h2", "name": {"value": "Bayern"}, "place_type": "State"}]
    assert index_par_nom_type(places) == {("Bayern", "State"): "h2"}


def test_creation_quand_le_lieu_est_absent():
    plan = decider(VAUD, None)
    assert plan["action"] == "creer"
    assert plan["name"] == "canton de Vaud"
    assert plan["place_type"] == "State"
    assert plan["code"] == "VD"
    assert plan["lat"] == "46.6" and plan["long"] == "6.6"


def test_un_nom_existant_nest_jamais_reecrit():
    """Bayern reste Bayern ; le libellé français rejoint les alt_names (spec §5.1)."""
    bayern = Subdivision(qid="Q980", iso="DE-BY", code="BY", libelle_fr="Bavière",
                         noms=["Bavière", "Bayern"], place_type="State", niveau=1,
                         parent_qid="Q183")
    place = {"handle": "h", "name": {"value": "Bayern"}, "place_type": "State",
             "lat": "", "long": "", "code": "", "alt_names": []}
    plan = decider(bayern, place)
    assert plan["action"] == "completer"
    assert "name" not in plan                 # aucune réécriture du nom
    assert plan["alt_names"] == [{"value": "Bavière"}]


def test_un_gps_deja_rempli_nest_pas_ecrase():
    place = {"handle": "h", "name": {"value": "canton de Vaud"}, "place_type": "State",
             "lat": "46.0", "long": "6.0", "code": "VD", "alt_names": []}
    plan = decider(VAUD, place)
    assert "lat" not in plan and "long" not in plan


def test_un_code_deja_rempli_nest_pas_ecrase():
    place = {"handle": "h", "name": {"value": "Allier"}, "place_type": "Department",
             "lat": "", "long": "", "code": "03", "alt_names": []}
    allier = Subdivision(qid="Q3113", iso="FR-03", code="03", libelle_fr="Allier",
                         noms=["Allier"], place_type="Department", niveau=2,
                         parent_qid="Q18338206")
    plan = decider(allier, place)
    assert "code" not in plan


def test_le_retypage_dune_wilaya_est_la_seule_reecriture_permise():
    place = {"handle": "h", "name": {"value": "Souk Ahras"}, "place_type": "Wilaya",
             "lat": "", "long": "", "code": "41", "alt_names": []}
    souk = Subdivision(qid="Q236772", iso="DZ-41", code="41", libelle_fr="Souk Ahras",
                       noms=["Souk Ahras"], place_type="Province", niveau=1,
                       parent_qid="Q262")
    plan = decider(souk, place)
    assert plan["place_type"] == "Province"


def test_le_libelle_francais_identique_nentre_pas_en_alt_names():
    place = {"handle": "h", "name": {"value": "canton de Vaud"}, "place_type": "State",
             "lat": "", "long": "", "code": "", "alt_names": []}
    plan = decider(VAUD, place)
    assert plan.get("alt_names", []) == []


def test_les_urls_a_poser_sont_le_qid_et_larticle():
    plan = decider(VAUD, None)
    chemins = [u["path"] for u in plan["urls"]]
    assert "https://www.wikidata.org/wiki/Q12771" in chemins
    assert "https://fr.wikipedia.org/wiki/Canton_de_Vaud" in chemins
```

- [ ] **Step 2: lancer le test, vérifier qu'il échoue**

```bash
uv run python -m pytest genecrew/tests/test_referentiel_apply.py -q
```

Attendu : `ModuleNotFoundError: No module named 'genecrew.referentiel_apply'`

- [ ] **Step 3: écrire le module**

Créer `genecrew/src/genecrew/referentiel_apply.py` :

```python
"""`apply referentiel` : écrit les pays et subdivisions du YAML relu.

Invariant (spec §5.5) : toute écriture est une création, le remplissage d'un champ vide, ou
un ajout dans une liste. Seule exception assumée, le retypage des `Wilaya` en `Province`.
C'est cet invariant qui autorise l'écriture directe, sans détour par une seconde relecture.

Ne réinterroge JAMAIS Wikidata : le YAML relu est la seule entrée (spec §6).
"""

from __future__ import annotations

import json
from pathlib import Path

import yaml

from crewai_custom_tools.tools.genealogy.gramps.write_tools import (
    GrampsAddUrlTool, GrampsCreatePlaceTool, GrampsUpdatePlaceTool, effective_dry_run,
)
from crewai_custom_tools.tools.genealogy.models.domain import Subdivision

from genecrew.batching import iter_places      # pagination déjà écrite, triée par gramps_id

_WIKIDATA = "https://www.wikidata.org/wiki/"

# Types de lieux qui peuvent CONTENIR : ceux-là seuls sont candidats à l'appariement par nom
# seul. `Wilaya` y figure parce qu'il faut retrouver les 5 lieux algériens pour les retyper —
# c'est précisément leur type qui doit changer, donc la clé (nom, type) ne peut pas les voir.
TYPES_CONTENANTS = frozenset({"Country", "State", "Region", "Department", "Province",
                              "County", "District", "Wilaya"})


def index_par_qid(places: list[dict]) -> dict[str, str]:
    """QID → handle, lu dans les `urls` des lieux. L'identité durable de l'appariement."""
    index: dict[str, str] = {}
    for place in places:
        for url in place.get("urls") or []:
            chemin = url.get("path") or ""
            if chemin.startswith(_WIKIDATA):
                index.setdefault(chemin[len(_WIKIDATA):], place["handle"])
    return index


def index_par_nom_type(places: list[dict]) -> dict[tuple[str, str], str]:
    """(nom, type) → handle. Repli du premier passage, avant que les QID soient posés."""
    index: dict[tuple[str, str], str] = {}
    for place in places:
        nom = (place.get("name") or {}).get("value", "")
        if nom:
            index.setdefault((nom, place.get("place_type", "")), place["handle"])
    return index


def index_par_nom_contenant(places: list[dict]) -> dict[str, str]:
    """nom → handle, restreint aux lieux CONTENANTS. Dernière prise de l'appariement."""
    index: dict[str, str] = {}
    for place in places:
        nom = (place.get("name") or {}).get("value", "")
        if nom and place.get("place_type", "") in TYPES_CONTENANTS:
            index.setdefault(nom, place["handle"])
    return index


def apparier(sub: Subdivision, par_qid: dict[str, str],
             par_nom_type: dict[tuple[str, str], str],
             par_nom: dict[str, str]) -> str | None:
    """Trois prises, dans l'ordre : QID, puis (nom, type), puis nom seul chez les contenants.

    Les noms essayés sont ceux de `sub.noms` — français d'abord, vernaculaire ensuite —
    parce que l'arbre porte `Bayern` là où Wikidata rend `Bavière`.
    """
    if sub.qid in par_qid:
        return par_qid[sub.qid]
    for nom in sub.noms:
        if (nom, sub.place_type) in par_nom_type:
            return par_nom_type[(nom, sub.place_type)]
    for nom in sub.noms:
        if nom in par_nom:
            return par_nom[nom]
    return None


def _urls_de(sub: Subdivision) -> list[dict]:
    urls = [{"path": f"{_WIKIDATA}{sub.qid}", "desc": "Wikidata"}]
    if sub.frwiki:
        urls.append({"path": sub.frwiki, "desc": "Wikipédia"})
    return urls


def decider(sub: Subdivision, place: dict | None) -> dict:
    """Les champs à écrire pour une subdivision, selon le lieu existant (None = absent).

    Rien de ce qui est déjà rempli n'est touché — le nom en particulier n'est jamais réécrit :
    `Bayern` reste `Bayern` et `Bavière` rejoint ses `alt_names`.
    """
    if place is None:
        return {"action": "creer", "name": sub.libelle_fr, "place_type": sub.place_type,
                "code": sub.code, "lat": sub.lat, "long": sub.long, "urls": _urls_de(sub)}

    plan: dict = {"action": "completer", "handle": place["handle"], "urls": _urls_de(sub)}
    if not place.get("lat") and sub.lat:
        plan["lat"] = sub.lat
    if not place.get("long") and sub.long:
        plan["long"] = sub.long
    if not place.get("code") and sub.code:
        plan["code"] = sub.code
    # Unique réécriture permise : normaliser un type personnalisé vers un type natif.
    if place.get("place_type") != sub.place_type:
        plan["place_type"] = sub.place_type
    nom_existant = (place.get("name") or {}).get("value", "")
    deja = {a.get("value") for a in (place.get("alt_names") or [])}
    plan["alt_names"] = ([{"value": sub.libelle_fr}]
                         if sub.libelle_fr and sub.libelle_fr != nom_existant
                         and sub.libelle_fr not in deja else [])
    return plan


def run_referentiel_apply(client, yaml_path, output_dir, *, date: str,
                          dry_run: bool = False) -> Path:
    """Applique le YAML relu : crée les lieux absents, complète les autres. Rend le rapport."""
    dry_run = effective_dry_run(dry_run)
    doc = yaml.safe_load(Path(yaml_path).read_text(encoding="utf-8")) or {}
    subs = [Subdivision(**s) for s in doc.get("subdivisions", [])]

    places = [place for lot in iter_places(client, "all", 200, None) for place in lot]
    par_qid = index_par_qid(places)
    par_nom_type = index_par_nom_type(places)
    par_nom = index_par_nom_contenant(places)
    par_handle = {p["handle"]: p for p in places}

    createur, majeur, urleur = (GrampsCreatePlaceTool(), GrampsUpdatePlaceTool(),
                                GrampsAddUrlTool())
    handles_qid = dict(par_qid)
    crees, completes, erreurs = [], [], []

    # Niveau 1 avant niveau 2 : un enfant ne peut pas se rattacher à un parent inexistant.
    for sub in sorted(subs, key=lambda s: s.niveau):
        handle = apparier(sub, par_qid, par_nom_type, par_nom)
        place = par_handle.get(handle) if handle else None
        plan = decider(sub, place)
        parent_handle = handles_qid.get(sub.parent_qid)
        try:
            if plan["action"] == "creer":
                payload = json.loads(createur._run(
                    name=plan["name"], place_type=plan["place_type"],
                    parent_handle=parent_handle, lat=plan["lat"], long=plan["long"],
                    code=plan["code"], dry_run=dry_run))
                if not payload["success"]:
                    raise RuntimeError(payload["error"])
                handle = payload["data"]["handle"]
                crees.append((sub.iso, sub.libelle_fr))
            else:
                payload = json.loads(majeur._run(
                    handle=handle, name=(place.get("name") or {}).get("value", ""),
                    place_type=plan.get("place_type", place.get("place_type")),
                    lat=plan.get("lat"), long=plan.get("long"), code=plan.get("code"),
                    alt_names=plan["alt_names"], dry_run=dry_run))
                if not payload["success"]:
                    raise RuntimeError(payload["error"])
                completes.append((sub.iso, sub.libelle_fr))
            handles_qid[sub.qid] = handle
            for url in plan["urls"]:
                urleur._run(object_type="places", handle=handle, url=url["path"],
                            description=url["desc"], dry_run=dry_run)
        except (RuntimeError, KeyError) as exc:
            erreurs.append((sub.iso, str(exc)))

    mode = "simulation" if dry_run else "ecritures"
    lignes = [f"# Référentiel appliqué — {date}", "",
              f"Mode : {'simulation' if dry_run else 'écritures'}", "",
              f"- Lieux créés : {len(crees)}",
              f"- Lieux complétés : {len(completes)}",
              f"- Erreurs : {len(erreurs)}", ""]
    for titre, lot in (("Créés", crees), ("Complétés", completes)):
        if lot:
            lignes += [f"## {titre}", "", "| ISO | Nom |", "|---|---|"]
            lignes += [f"| {iso} | {nom} |" for iso, nom in lot] + [""]
    if erreurs:
        lignes += ["## Erreurs", "", "| ISO | Message |", "|---|---|"]
        lignes += [f"| {iso} | {msg} |" for iso, msg in erreurs] + [""]

    out = Path(output_dir) / "referentiel"
    out.mkdir(parents=True, exist_ok=True)
    report_path = out / f"{date}_referentiel_applique_{mode}.md"
    report_path.write_text("\n".join(lignes), encoding="utf-8")
    return report_path
```

- [ ] **Step 4: lancer le test, vérifier qu'il passe**

```bash
uv run python -m pytest genecrew/tests/test_referentiel_apply.py -q
```

Attendu : `14 passed`

- [ ] **Step 5: commit**

```bash
git add genecrew/src/genecrew/referentiel_apply.py genecrew/tests/test_referentiel_apply.py
git commit -m "feat(referentiel): apply referentiel, appariement par QID et écritures non destructives"
```

---

### Task 10 : les deux feuilles de la CLI

**Files:**
- Modify: `genecrew/src/genecrew/cli.py`
- Modify: `genecrew/src/genecrew/main.py`
- Test: `genecrew/tests/test_cli.py` (fichier existant ; sinon le créer)

**Interfaces:**
- Consumes: `run_referentiel` (tâche 8), `run_referentiel_apply` (tâche 9).
- Produces: les couples `("propose", "referentiel")` et `("apply", "referentiel")` dans la
  table de routage de `main()`.

Aucun verbe nouveau : l'ADR 0012 fige les sept verbes, une nouveauté est une feuille.

- [ ] **Step 1: écrire le test qui échoue**

Ajouter à `genecrew/tests/test_cli.py` :

```python
def test_propose_referentiel_accepte_country():
    from genecrew.cli import build_parser

    args = build_parser().parse_args(["propose", "referentiel", "--country", "FR,CH"])
    assert (args.command, args.target) == ("propose", "referentiel")
    assert args.country == "FR,CH"


def test_propose_referentiel_sans_country_vise_tous_les_pays():
    from genecrew.cli import build_parser

    args = build_parser().parse_args(["propose", "referentiel"])
    assert args.country is None


def test_apply_referentiel_exige_le_yaml_relu():
    import pytest

    from genecrew.cli import build_parser

    args = build_parser().parse_args(
        ["apply", "referentiel", "--yaml", "relu.yaml", "--dry-run"])
    assert (args.command, args.target) == ("apply", "referentiel")
    assert args.yaml == "relu.yaml" and args.dry_run is True
    with pytest.raises(SystemExit):
        build_parser().parse_args(["apply", "referentiel"])


def test_aucun_verbe_nouveau():
    """L'ADR 0012 fige sept verbes ; `referentiel` est une feuille, pas un huitième verbe."""
    import pytest

    from genecrew.cli import build_parser

    with pytest.raises(SystemExit):
        build_parser().parse_args(["init"])
```

- [ ] **Step 2: lancer le test, vérifier qu'il échoue**

```bash
uv run python -m pytest genecrew/tests/test_cli.py -q
```

Attendu : `SystemExit: 2` sur `invalid choice: 'referentiel'`

- [ ] **Step 3: ajouter les feuilles au parseur**

Dans `genecrew/src/genecrew/cli.py`, après le dernier `propose_sub.add_parser(...)` :

```python
    p = propose_sub.add_parser(
        "referentiel",
        help="Subdivisions administratives des pays (Wikidata, lecture seule)")
    p.add_argument("--country", default=None,
                   help="codes ISO séparés par des virgules (défaut : tous les pays)")
    _add_date(p)
```

et après le dernier `apply_sub.add_parser(...)` :

```python
    p = apply_sub.add_parser(
        "referentiel", help="Écrit les pays et subdivisions du YAML relu")
    _add_yaml(p)
    _add_dry_run(p)
    _add_date(p)
```

- [ ] **Step 4: brancher le routage**

Dans `genecrew/src/genecrew/main.py`, ajouter les deux commandes près de `lieux_cmd` :

```python
def referentiel_cmd(args) -> None:
    """Propose the administrative referentiel (read-only); print the report paths."""
    from pathlib import Path

    from crewai_custom_tools.tools.genealogy.gramps.client import get_client

    from genecrew.referentiel import run_referentiel

    client = get_client()
    output_dir = Path(os.environ.get("GENECREW_OUTPUT_DIR", "output"))
    date = args.date or __import__("datetime").date.today().isoformat()
    codes = [c.strip().upper() for c in args.country.split(",")] if args.country else None
    report, proposals = run_referentiel(client, output_dir, date=date, codes_pays=codes)
    print(f"Rapport : {report}")
    print(f"Propositions : {proposals}")


def referentiel_apply_cmd(args) -> None:
    """Apply the reviewed referentiel YAML (writes); print the report path."""
    from pathlib import Path

    from crewai_custom_tools.tools.genealogy.gramps.client import get_client

    from genecrew.referentiel_apply import run_referentiel_apply

    client = get_client()
    output_dir = Path(os.environ.get("GENECREW_OUTPUT_DIR", "output"))
    date = args.date or __import__("datetime").date.today().isoformat()
    report = run_referentiel_apply(client, args.yaml, output_dir, date=date,
                                   dry_run=args.dry_run)
    print(f"Rapport : {report}")
```

et dans la table `dispatch` de `main()` :

```python
        ("propose", "referentiel"): lambda: referentiel_cmd(args),
        ("apply", "referentiel"): lambda: referentiel_apply_cmd(args),
```

- [ ] **Step 5: lancer les tests, vérifier qu'ils passent**

```bash
uv run python -m pytest genecrew/tests/ -q
uv run genecrew propose referentiel --help
```

Attendu : zéro échec, et l'aide affiche `--country`.

- [ ] **Step 6: commit**

```bash
git add genecrew/src/genecrew/cli.py genecrew/src/genecrew/main.py genecrew/tests/test_cli.py
git commit -m "feat(cli): feuilles propose/apply referentiel"
```

---

### Task 11 : ADR et documentation

**Files:**
- Create: `docs/adr/0016-referentiel-subdivisions-administratives.md`
- Modify: `CLAUDE.md`
- Modify: `docs/adr/0012-cli-grammaire-verbes.md` (table de correspondance des feuilles)

- [ ] **Step 1: écrire l'ADR**

Créer `docs/adr/0016-referentiel-subdivisions-administratives.md`, en suivant la forme des ADR
existants (contexte, décision, conséquences). Il doit consigner, chacun avec sa raison :

1. Sélection Wikidata par **ISO 3166-2**, pas par classe `P31` — la classe `provincia` rate
   Naples et Milan, qui sont des villes métropolitaines.
2. Niveau déduit du **rattachement `P131`**, jamais de la forme du code — `FR-ARA`/`FR-01` et
   `IT-25`/`IT-NA` sont inversés d'un pays à l'autre.
3. Le filtre par sous-classes `P31/P279*` a été **essayé et rejeté** : 504 sur l'endpoint public.
4. **Types Gramps natifs uniquement.** `Canton` disparaît du résolveur suisse, les 5 `Wilaya`
   sont retypées `Province`. Un type personnalisé est une ligne de plus à ne pas oublier dans
   chaque filtre par type.
5. **Identité par QID** stocké dans les `urls`, pour ne plus apparier sur des chaînes dans deux
   langues (`Bayern` contre `Bavière`).
6. **Doublons signalés, jamais fusionnés** — et la raison pour laquelle ils passaient inaperçus :
   `_seed_parent_index` écrase silencieusement la clé `chemin → handle`.
7. **Dette assumée** : les `alt_names` portent désormais deux sens, variante historique d'un lieu
   **et** traduction. Une relecture doit savoir lequel elle regarde.
8. **Partage du travail avec `enrich wiki`** : `apply referentiel` pose l'article des subdivisions
   depuis le sitelink ; `enrich wiki` continue de traiter les feuilles par géolocalisation.

- [ ] **Step 2: mettre à jour le CLAUDE.md**

Trois retouches :

- dans la liste des fichiers de genecrew, ajouter `referentiel.py` et `referentiel_apply.py` ;
- dans la mise en garde « Créer un décès », remplacer `Canton` par `State` dans l'énumération des
  contenants, puisque le type n'existe plus ;
- dans les commandes, ajouter les deux lignes :

```bash
uv run genecrew propose referentiel --country FR,CH   # subdivisions Wikidata (lecture seule)
uv run genecrew apply referentiel --yaml <relu.yaml> --dry-run   # écrit pays + subdivisions
```

- [ ] **Step 3: compléter l'ADR 0012**

Ajouter `referentiel` aux feuilles listées sous `propose` et sous `apply`, avec un renvoi vers
l'ADR 0016.

- [ ] **Step 4: vérifier que la documentation construit**

```bash
uv run mkdocs build --strict 2>&1 | tail -5
```

Attendu : aucun avertissement bloquant. Si `mkdocs` n'est pas installé dans le worktree,
`uv sync --extra docs` d'abord ; si la cible n'existe pas, sauter cette étape et le signaler.

- [ ] **Step 5: commit**

```bash
git add docs/adr/0016-referentiel-subdivisions-administratives.md \
        docs/adr/0012-cli-grammaire-verbes.md CLAUDE.md
git commit -m "docs(adr): ADR 0016 — référentiel des subdivisions administratives"
```

---

## Vérification finale

- [ ] **Les deux suites, vertes**

```bash
# worktree bibliothèque
uv run python -m pytest tests/ -q
# worktree genecrew
uv run python -m pytest genecrew/tests/ -q
uv run ruff check .
```

- [ ] **Un essai réel, borné et simulé**

Nécessite un `.env` dans le worktree (lien symbolique vers celui du dépôt principal) et la
pile Gramps Web démarrée depuis `gramps-mcp`.

```bash
uv run genecrew propose referentiel --country CH
# relire le rapport et le YAML dans output/referentiel/
uv run genecrew apply referentiel --yaml output/referentiel/<date>_propositions_referentiel_CH.yaml --dry-run
```

Attendu : 26 subdivisions suisses de type `State`, GPS et article sur chacune, zéro collision,
et un rapport de simulation qui annonce 26 créations sans avoir rien écrit.

- [ ] **Le bug d'origine, résolu dans le bon ordre**

```bash
# après avoir appliqué le référentiel pour de vrai
uv run genecrew propose places --scope place:P0001
```

Attendu : `country: Suisse`, source `swisstopo`, score `1.0`, et une chaîne
`Suisse › canton de Vaud` — là où le run de conception rendait `country: ''`,
`chains: [levels: []]` et un score de 0.762.
