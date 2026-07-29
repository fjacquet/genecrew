# Lieux-dits et lisibilité du compte rendu — plan d'implémentation

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `import releve` attache aux événements le lieu le plus fin que l'acte donne (le lieu-dit quand il existe, sinon la commune), et son compte rendu affiche des identifiants Gramps vérifiables au lieu de handles internes.

**Architecture:** Un champ `evenement_lieu_dit` rend la granularité explicite dans `ReleveIndexe` au lieu de la laisser deviner. Un nouveau module `genecrew/lieux_dits.py` porte une cascade à trois étages — l'arbre d'abord (gratuit, déterministe), puis Nominatim **borné à l'emprise de la commune résolue**, puis création sans GPS. Le bornage remplace le seuil de score : la garde devient géométrique, donc non contournable par un score de 1.0 sur un homonyme lointain.

**Tech Stack:** Python 3.13, `uv`, pydantic v2, pytest + pytest-mock, httpx (`MockTransport` en test), Gramps Web REST.

**Spec :** `docs/superpowers/specs/2026-07-29-lieux-dits-import-releves-design.md`

## Global Constraints

- **Aucune ligne ajoutée à `crewai_custom_tools`.** On en *importe* (`get_rate_limiter`, `GrampsCreatePlaceTool`, `effective_dry_run`), on n'y écrit pas. Toute modification de la bibliothèque imposerait un cycle bump → tag → push avant que la CI de genecrew puisse verdir.
- **Aucun test ne touche le réseau.** `test_releves_import.py` (76 Ko) n'en fait pas ; ça ne commence pas ici.
- **Tests en français**, `snake_case`, nom décrivant le CAS et non le résultat, **docstring obligatoire** (convention du fichier).
- **Normalisation des noms de lieux : `strip()` puis `casefold()`.** La mesure des 3 collisions de l'arbre ne vaut que pour celle-là.
- `uv run ruff check .` vert. Configuration : `select = E,W,I,UP,B,C4,SIM,RUF`, `line-length 120`, RUF001-003 ignorés.
- Tout se lance depuis la racine du dépôt : `uv run python -m pytest genecrew/tests/ -q`.
- Branche de travail : `spec/lieux-dits-import-releves` (la spec y est déjà commitée).

---

## Structure des fichiers

| Fichier | Rôle | Sort |
|---|---|---|
| `genecrew/src/genecrew/lieux_dits.py` | **Nouveau.** Toute la cascade lieu-dit : recherche arbre, requête OSM bornée, création. Aucune dépendance à `releves_import`. | Créé (tâche 2) |
| `genecrew/tests/test_lieux_dits.py` | **Nouveau.** Tests unitaires de la cascade, isolés. | Créé (tâche 2) |
| `genecrew/src/genecrew/releves.py` | `ReleveIndexe` gagne un champ. | Modifié (tâche 1) |
| `genecrew/src/genecrew/releves_import.py` | Prompt, branchement de la cascade, rendu du rapport. Déjà 1234 lignes — **on n'y met que le branchement**, la logique vit dans `lieux_dits.py`. | Modifié (tâches 1, 4, 6) |
| `genecrew/tests/test_releves_import.py` | Tests d'intégration du branchement et du rapport. | Modifié (tâches 1, 4, 5, 6, 7) |

Le module séparé n'est pas de la coquetterie : `releves_import.py` fait 1234 lignes et son fichier de tests 76 Ko. Y ajouter une cascade réseau rendrait les deux plus durs à tenir en tête, et la cascade est testable seule.

---

### Task 1: Le champ `evenement_lieu_dit` et le prompt

**Files:**
- Modify: `genecrew/src/genecrew/releves.py:141` (après `evenement_departement`)
- Modify: `genecrew/src/genecrew/releves_import.py:68-110` (`PROMPT_INTERPRETATION`)
- Test: `genecrew/tests/test_releves_import.py`

**Interfaces:**
- Consumes: rien.
- Produces: `ReleveIndexe.evenement_lieu_dit: str = ""` — lu par toutes les tâches suivantes.

- [ ] **Step 1: Écrire le test qui échoue**

Dans `genecrew/tests/test_releves_import.py`, à côté des autres tests de `parse_releve` :

```python
def test_parse_extrait_le_lieu_dit_distinct_de_la_commune():
    """Le lieu-dit ne doit PAS atterrir dans evenement_lieu.

    C'est le défaut d'origine : le LLM écrivait « Les Roches » dans un champ
    dont le contrat dit « commune », et le résolveur partait chercher une
    commune homonyme — qu'il trouvait, en Ardèche. Les deux échelons ont
    désormais chacun leur champ.
    """
    attendu = dict(_JSON_ATTENDU)
    attendu["evenement_lieu"] = "Saint-Martin-d'Auxigny"
    attendu["evenement_lieu_dit"] = "Les Roches"
    releve = parse_releve("peu importe", llm=_LLMStub(json.dumps(attendu)))
    assert releve.evenement_lieu == "Saint-Martin-d'Auxigny"
    assert releve.evenement_lieu_dit == "Les Roches"


def test_releve_sans_lieu_dit_garde_un_champ_vide():
    """Un relevé sans lieu-dit est un cas NORMAL, pas un échec.

    La grande majorité des relevés n'en portent pas. Le défaut vide garantit
    aussi que les appels existants ne cassent pas.
    """
    releve = parse_releve("peu importe", llm=_LLMStub(json.dumps(_JSON_ATTENDU)))
    assert releve.evenement_lieu_dit == ""
```

- [ ] **Step 2: Lancer le test, vérifier qu'il échoue**

Run: `uv run python -m pytest genecrew/tests/test_releves_import.py::test_parse_extrait_le_lieu_dit_distinct_de_la_commune -v`
Expected: FAIL — `AttributeError: 'ReleveIndexe' object has no attribute 'evenement_lieu_dit'`

- [ ] **Step 3: Ajouter le champ au modèle**

Dans `genecrew/src/genecrew/releves.py`, juste après `evenement_departement: str = ""` :

```python
    # Le LIEU-DIT (hameau, écart, ferme) quand l'acte le nomme — « Les Roches »,
    # « La Rose ». Distinct de `evenement_lieu`, qui reste la COMMUNE NUE et la clé
    # de `lieux_resolus`. La séparation est le cœur de la correction : un champ dont
    # le contrat dit « commune » recevait des lieux-dits, et le résolveur partait
    # alors chercher une commune homonyme — qu'il trouvait, à 400 km. Ce champ ne
    # participe JAMAIS à l'appariement, seulement au lieu posé sur l'événement.
    # Défaut "" → rétrocompatible, et un champ vide est un résultat correct.
    evenement_lieu_dit: str = ""
```

- [ ] **Step 4: Ajouter la clé au prompt**

Dans `genecrew/src/genecrew/releves_import.py`, dans `PROMPT_INTERPRETATION`, après la ligne `evenement_departement` de la liste des clés :

```
  evenement_lieu_dit : le hameau/lieu-dit de l'événement, "" si absent
```

et dans la section « Règles », après la règle `evenement_departement` :

```
- evenement_lieu_dit : le HAMEAU ou lieu-dit quand l'acte le nomme (« aux Roches »,
  « à La Rose », « au Montet »). Il ne remplace PAS la commune : « décédé aux Roches,
  commune de Saint-Martin-d'Auxigny » donne evenement_lieu="Saint-Martin-d'Auxigny"
  ET evenement_lieu_dit="Les Roches". Si le texte ne nomme qu'une commune, laisse "".
  N'en invente pas : un champ vide est un résultat correct, pas un échec.
```

- [ ] **Step 5: Lancer les tests, vérifier qu'ils passent**

Run: `uv run python -m pytest genecrew/tests/test_releves_import.py -q`
Expected: PASS, y compris toute la suite existante (le champ a un défaut, rien ne casse).

- [ ] **Step 6: Commit**

```bash
git add genecrew/src/genecrew/releves.py genecrew/src/genecrew/releves_import.py genecrew/tests/test_releves_import.py
git commit -m "feat(releves): separer le lieu-dit de la commune dans ReleveIndexe"
```

---

### Task 2: Étage 1 — chercher le lieu-dit dans l'arbre

**Files:**
- Create: `genecrew/src/genecrew/lieux_dits.py`
- Test: `genecrew/tests/test_lieux_dits.py` (nouveau)

**Interfaces:**
- Consumes: `GrampsClient` (de `crewai_custom_tools.tools.genealogy.gramps.client`).
- Produces:
  - `TYPES_LIEU_DIT: frozenset[str]` — `{"Hamlet", "Locality", "Village", "Farm"}`
  - `class RechercheArbreIndisponible(Exception)`
  - `normaliser_nom(nom: str) -> str`
  - `chercher_dans_arbre(client: GrampsClient, nom: str, parent_handle: str) -> str | None`
    — rend le **handle** du lieu-dit, `None` s'il est absent, **lève** `RechercheArbreIndisponible` si la lecture échoue.

L'exception distincte du `None` est l'invariant central de la tâche 4 : une **absence** autorise une création, une **panne de lecture** ne l'autorise pas.

- [ ] **Step 1: Écrire les tests qui échouent**

Créer `genecrew/tests/test_lieux_dits.py` :

```python
"""Cascade de résolution d'un lieu-dit — hors ligne, aucun appel réseau."""

import httpx
import pytest
from crewai_custom_tools.tools.genealogy.gramps.client import GrampsClient, GrampsConfig

from genecrew.lieux_dits import (
    RechercheArbreIndisponible,
    chercher_dans_arbre,
    normaliser_nom,
)

CONFIG = GrampsConfig(
    base_url="http://x/api", username="u", password="p", tree_id="t"
)


def _client(handler):
    """Client Gramps sur transport simulé, jeton servi automatiquement."""

    def _h(request):
        if request.url.path == "/api/token/":
            return httpx.Response(200, json={"access_token": "t"})
        return handler(request)

    return GrampsClient(CONFIG, transport=httpx.MockTransport(_h))


def _place(gramps_id, handle, nom, place_type, parent_handle):
    """Un lieu Gramps réaliste, réduit aux clés que la cascade lit."""
    return {
        "gramps_id": gramps_id,
        "handle": handle,
        "name": {"value": nom},
        "place_type": place_type,
        "placeref_list": [{"ref": parent_handle}],
    }


def _handler_places(*places):
    """Répond /api/places/ avec la liste donnée."""

    def _h(request):
        if request.url.path == "/api/places/":
            return httpx.Response(200, json=list(places))
        return httpx.Response(404, json={})

    return _h


def test_trouve_le_lieu_dit_sous_sa_commune():
    """Nom + type + parent suffisent : 663 lieux, 3 collisions, toutes inter-types."""
    client = _client(
        _handler_places(
            _place("P0661", "h_roches", "Les Roches", "Hamlet", "h_commune")
        )
    )
    assert chercher_dans_arbre(client, "Les Roches", "h_commune") == "h_roches"


def test_ignore_l_homonyme_rattache_a_une_autre_commune():
    """Le parent est ce qui rend la recherche déterministe.

    Sans lui, un « Les Roches » d'ailleurs dans l'arbre serait attrapé — la
    version arbre du bug d'origine.
    """
    client = _client(
        _handler_places(
            _place("P0999", "h_ailleurs", "Les Roches", "Hamlet", "h_autre_commune")
        )
    )
    assert chercher_dans_arbre(client, "Les Roches", "h_commune") is None


def test_la_casse_et_les_espaces_ne_font_pas_manquer_le_lieu():
    """Normalisation : strip() puis casefold(), celle de la mesure des collisions."""
    client = _client(
        _handler_places(
            _place("P0661", "h_roches", "Les Roches", "Hamlet", "h_commune")
        )
    )
    assert chercher_dans_arbre(client, "  les roches ", "h_commune") == "h_roches"


def test_un_lieu_du_mauvais_type_n_est_pas_retenu():
    """Une COMMUNE nommée comme le lieu-dit n'est pas le lieu-dit."""
    client = _client(
        _handler_places(
            _place("P0500", "h_ville", "Les Roches", "Municipality", "h_commune")
        )
    )
    assert chercher_dans_arbre(client, "Les Roches", "h_commune") is None


def test_deux_homonymes_de_meme_type_sous_la_meme_commune_font_refuser():
    """Un refus coûte moins qu'un choix arbitraire entre deux lieux réels."""
    client = _client(
        _handler_places(
            _place("P0661", "h_a", "Les Roches", "Hamlet", "h_commune"),
            _place("P0662", "h_b", "Les Roches", "Hamlet", "h_commune"),
        )
    )
    assert chercher_dans_arbre(client, "Les Roches", "h_commune") is None


def test_une_panne_de_lecture_leve_au_lieu_de_rendre_none():
    """L'invariant central : une panne n'est PAS une absence.

    Rendre None ferait croire à la cascade que le lieu-dit n'existe pas, et
    elle en créerait un doublon. La fusion de lieux est délicate (ADR 0015) ;
    mieux vaut ne rien poser.
    """

    def _h(request):
        return httpx.Response(500, json={"error": "boom"})

    with pytest.raises(RechercheArbreIndisponible):
        chercher_dans_arbre(_client(_h), "Les Roches", "h_commune")


def test_normaliser_nom_est_strip_puis_casefold():
    """Verrouille la normalisation : la mesure des collisions n'a de sens qu'ainsi."""
    assert normaliser_nom("  Les Roches ") == "les roches"
```

- [ ] **Step 2: Lancer les tests, vérifier qu'ils échouent**

Run: `uv run python -m pytest genecrew/tests/test_lieux_dits.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'genecrew.lieux_dits'`

- [ ] **Step 3: Écrire le module**

Créer `genecrew/src/genecrew/lieux_dits.py` :

```python
"""Résolution d'un lieu-dit sous sa commune — l'arbre d'abord, OSM borné ensuite.

Le défaut que ce module répare : `import releve` cherchait un lieu-dit comme s'il
était une COMMUNE, via un Nominatim non borné. « Les Roches, Saint-Martin-d'Auxigny,
Cher, France » rendait alors un homonyme ardéchois avec un score de 1.0 — la
similarité de chaîne ne mesure pas la plausibilité géographique.

La garde n'est donc PAS un seuil de score mais l'EMPRISE : bornée à la commune
déjà résolue, la requête ne peut plus ramener l'Ardèche, quel que soit son score.
"""

from __future__ import annotations

import logging

import httpx
from crewai_custom_tools.core.rate_limiter import get_rate_limiter
from crewai_custom_tools.tools.genealogy.gramps.client import GrampsClient

_LOG = logging.getLogger(__name__)

TYPES_LIEU_DIT = frozenset({"Hamlet", "Locality", "Village", "Farm"})
"""Types Gramps qu'un lieu-dit peut porter.

Liste d'INCLUSION, comme `TYPES_LIEU_DECES` : un type oublié fait manquer un
lieu (on retombe sur la commune, sans dégât), tandis qu'un type de trop
attraperait un contenant — rattacher un décès à un département en silence.
"""


class RechercheArbreIndisponible(Exception):
    """La lecture de l'arbre a échoué : on ne SAIT PAS si le lieu-dit existe.

    Distincte d'un `None`, qui signifie « lu, et absent ». La cascade a le droit
    de créer sur une absence, jamais sur une ignorance : créer sur une panne de
    lecture produirait un doublon du lieu qu'on n'a pas su lire.
    """


def normaliser_nom(nom: str) -> str:
    """`strip()` puis `casefold()` — la normalisation de la mesure des collisions.

    L'arbre porte 663 lieux pour 3 noms partagés, tous inter-types. Ce chiffre ne
    vaut que pour CETTE normalisation ; la changer invalide la garantie.
    """
    return (nom or "").strip().casefold()


def chercher_dans_arbre(
    client: GrampsClient, nom: str, parent_handle: str
) -> str | None:
    """Handle du lieu-dit `nom` rattaché à `parent_handle`, ou None s'il est absent.

    Lève `RechercheArbreIndisponible` si l'arbre n'a pas pu être lu. Refuse (rend
    None) si deux lieux de même nom ET de même type pendent sous le même parent :
    un refus coûte moins qu'un choix arbitraire entre deux lieux réels.
    """
    cible = normaliser_nom(nom)
    if not cible or not parent_handle:
        return None
    try:
        places = client.get_json("/places/?keys=handle,name,place_type,placeref_list")
    except (httpx.HTTPError, RuntimeError, ValueError) as exc:
        raise RechercheArbreIndisponible(str(exc)) from exc

    trouves = [
        p["handle"]
        for p in places
        if normaliser_nom((p.get("name") or {}).get("value", "")) == cible
        and (p.get("place_type") or "") in TYPES_LIEU_DIT
        and any(
            ref.get("ref") == parent_handle for ref in (p.get("placeref_list") or [])
        )
    ]
    if len(trouves) != 1:
        if len(trouves) > 1:
            _LOG.warning(
                "Lieu-dit « %s » ambigu sous %s (%d homonymes de même type) : refusé",
                nom, parent_handle, len(trouves),
            )
        return None
    return trouves[0]
```

- [ ] **Step 4: Lancer les tests, vérifier qu'ils passent**

Run: `uv run python -m pytest genecrew/tests/test_lieux_dits.py -v`
Expected: PASS — 7 tests.

Si `client.get_json` sur une réponse 500 ne lève pas mais rend un objet, adapter le `except` au comportement réel de `GrampsClient` — le test `test_une_panne_de_lecture_leve_au_lieu_de_rendre_none` est l'arbitre.

- [ ] **Step 5: Commit**

```bash
git add genecrew/src/genecrew/lieux_dits.py genecrew/tests/test_lieux_dits.py
git commit -m "feat(lieux-dits): chercher le lieu-dit dans l'arbre sous sa commune"
```

---

### Task 3: Étage 2 — Nominatim borné à l'emprise de la commune

**Files:**
- Modify: `genecrew/src/genecrew/lieux_dits.py`
- Test: `genecrew/tests/test_lieux_dits.py`

**Interfaces:**
- Consumes: `normaliser_nom` (tâche 2), `get_rate_limiter` (bibliothèque, importé seulement).
- Produces:
  - `TYPES_OSM_LIEU_DIT: frozenset[str]` — `{"hamlet", "locality", "village", "isolated_dwelling"}`
  - `MARGE_EMPRISE_DEG: float` = `0.06`
  - `emprise_de_commune(lat: float | None, lon: float | None, bbox: tuple[float, float, float, float] | None) -> str | None` — rend le paramètre `viewbox` Nominatim (`"lon_min,lat_max,lon_max,lat_min"`), ou `None` si rien n'est calculable.
  - `interroger_osm(nom: str, viewbox: str) -> tuple[str, str] | None` — rend `(lat, lon)` en chaînes, ou `None`.

- [ ] **Step 1: Écrire les tests qui échouent**

Ajouter à `genecrew/tests/test_lieux_dits.py` :

```python
from genecrew.lieux_dits import (
    MARGE_EMPRISE_DEG,
    emprise_de_commune,
    interroger_osm,
)


def test_emprise_preferee_est_la_bounding_box_de_la_commune():
    """La bbox réelle vaut mieux qu'un carré approché autour du centre."""
    assert emprise_de_commune(47.2164, 2.35, (2.29, 47.27, 2.42, 47.16)) == (
        "2.29,47.27,2.42,47.16"
    )


def test_emprise_de_repli_est_un_carre_autour_du_centre():
    """Sans bbox, un carré de ±MARGE_EMPRISE_DEG — la valeur de la mesure."""
    viewbox = emprise_de_commune(47.2164, 2.35, None)
    lon_min, lat_max, lon_max, lat_min = (float(v) for v in viewbox.split(","))
    assert lon_min == pytest.approx(2.35 - MARGE_EMPRISE_DEG)
    assert lon_max == pytest.approx(2.35 + MARGE_EMPRISE_DEG)
    assert lat_max == pytest.approx(47.2164 + MARGE_EMPRISE_DEG)
    assert lat_min == pytest.approx(47.2164 - MARGE_EMPRISE_DEG)


def test_commune_sans_coordonnees_ne_donne_aucune_emprise():
    """Sans centre ni bbox, rien n'est calculable — l'étage 2 sera sauté."""
    assert emprise_de_commune(None, None, None) is None


def test_osm_retient_un_hameau(monkeypatch):
    """Cas mesuré le 2026-07-29 : La Rose est dans OSM, correctement typée."""
    monkeypatch.setattr(
        "genecrew.lieux_dits._http_get_osm",
        lambda params: [
            {"addresstype": "hamlet", "lat": "47.19476", "lon": "2.37858"}
        ],
    )
    assert interroger_osm("La Rose", "2.29,47.27,2.42,47.16") == ("47.19476", "2.37858")


def test_osm_rejette_une_rue(monkeypatch):
    """« Rue de la Rose » n'est PAS le lieu-dit La Rose.

    La BAN en rend quatre pour cette commune ; les accepter poserait un
    événement sur une voie.
    """
    monkeypatch.setattr(
        "genecrew.lieux_dits._http_get_osm",
        lambda params: [{"addresstype": "road", "lat": "47.19", "lon": "2.37"}],
    )
    assert interroger_osm("La Rose", "2.29,47.27,2.42,47.16") is None


def test_osm_muet_rend_none(monkeypatch):
    """Les Roches est absent d'OSM — lacune connue, pas une erreur."""
    monkeypatch.setattr("genecrew.lieux_dits._http_get_osm", lambda params: [])
    assert interroger_osm("Les Roches", "2.29,47.27,2.42,47.16") is None


def test_la_requete_osm_est_bien_bornee(monkeypatch):
    """La garde est GÉOMÉTRIQUE : sans bounded=1, le score de 1.0 de l'Ardèche gagne."""
    vus = {}
    monkeypatch.setattr(
        "genecrew.lieux_dits._http_get_osm",
        lambda params: vus.update(params) or [],
    )
    interroger_osm("Les Roches", "2.29,47.27,2.42,47.16")
    assert vus["viewbox"] == "2.29,47.27,2.42,47.16"
    assert vus["bounded"] == 1


def test_une_panne_osm_rend_none_sans_lever(monkeypatch):
    """Le réseau qui tombe fait retomber sur l'étage 3, il ne tue pas l'import."""

    def _boom(params):
        raise httpx.ConnectError("réseau")

    monkeypatch.setattr("genecrew.lieux_dits._http_get_osm", _boom)
    assert interroger_osm("La Rose", "2.29,47.27,2.42,47.16") is None
```

- [ ] **Step 2: Lancer les tests, vérifier qu'ils échouent**

Run: `uv run python -m pytest genecrew/tests/test_lieux_dits.py -v -k "emprise or osm"`
Expected: FAIL — `ImportError: cannot import name 'emprise_de_commune'`

- [ ] **Step 3: Implémenter**

Ajouter à `genecrew/src/genecrew/lieux_dits.py` :

```python
_URL_OSM = "https://nominatim.openstreetmap.org/search"
_UA_OSM = "genecrew/1.0 (genealogy place standardizer; +https://github.com/)"
_PROVIDER_OSM = "Nominatim"

TYPES_OSM_LIEU_DIT = frozenset({"hamlet", "locality", "village", "isolated_dwelling"})
"""Types OSM acceptés pour un lieu-dit.

`road`, `administrative`, `house` sont rejetés : « Rue de la Rose » n'est pas le
lieu-dit La Rose, et la BAN en rend quatre variantes pour cette seule commune.
"""

MARGE_EMPRISE_DEG = 0.06
"""Demi-côté du carré de repli, en degrés (≈ 6,7 km en latitude).

Valeur employée pour la mesure de conception ; elle a suffi à trouver La Rose à
2,7 km du bourg. Volontairement généreuse : une emprise trop large ne peut
ramener qu'un lieu-dit de la commune voisine, jamais l'Ardèche.
"""


def emprise_de_commune(
    lat: float | None,
    lon: float | None,
    bbox: tuple[float, float, float, float] | None,
) -> str | None:
    """Paramètre `viewbox` Nominatim (`lon_min,lat_max,lon_max,lat_min`), ou None.

    Préfère la bounding box réelle de la commune ; à défaut, un carré de
    ±`MARGE_EMPRISE_DEG` autour de son centre. Sans centre ni bbox, rend None :
    l'étage 2 est alors sauté plutôt que borné sur du vide.
    """
    if bbox is not None:
        return ",".join(str(v) for v in bbox)
    if lat is None or lon is None:
        return None
    return (
        f"{lon - MARGE_EMPRISE_DEG},{lat + MARGE_EMPRISE_DEG},"
        f"{lon + MARGE_EMPRISE_DEG},{lat - MARGE_EMPRISE_DEG}"
    )


def _http_get_osm(params: dict) -> list:
    """Appel Nominatim, cadencé par le limiteur PARTAGÉ de la bibliothèque.

    Le limiteur est importé, pas réimplémenté : la politique d'usage de Nominatim
    est d'une requête par seconde tous appelants confondus, donc un compteur
    propre à ce module la violerait dès qu'un autre chemin appelle aussi.
    """
    get_rate_limiter().acquire(_PROVIDER_OSM)
    resp = httpx.get(
        _URL_OSM, params=params, headers={"User-Agent": _UA_OSM}, timeout=15.0
    )
    resp.raise_for_status()
    return resp.json()


def interroger_osm(nom: str, viewbox: str) -> tuple[str, str] | None:
    """(lat, lon) du lieu-dit dans l'emprise, ou None.

    `bounded=1` est ce qui rend la garde géométrique : hors de la boîte, aucun
    résultat ne remonte, quel que soit son score de similarité.
    """
    if not nom or not viewbox:
        return None
    try:
        resultats = _http_get_osm(
            {
                "q": nom,
                "format": "jsonv2",
                "limit": 5,
                "accept-language": "fr",
                "viewbox": viewbox,
                "bounded": 1,
            }
        )
    except (httpx.HTTPError, ValueError) as exc:
        _LOG.warning("Nominatim borné indisponible pour « %s » : %s", nom, exc)
        return None
    for r in resultats:
        if (r.get("addresstype") or r.get("type") or "") in TYPES_OSM_LIEU_DIT:
            return str(r["lat"]), str(r["lon"])
    return None
```

- [ ] **Step 4: Lancer les tests, vérifier qu'ils passent**

Run: `uv run python -m pytest genecrew/tests/test_lieux_dits.py -v`
Expected: PASS — 15 tests.

- [ ] **Step 5: Commit**

```bash
git add genecrew/src/genecrew/lieux_dits.py genecrew/tests/test_lieux_dits.py
git commit -m "feat(lieux-dits): interroger Nominatim borne a l'emprise de la commune"
```

---

### Task 4: Étage 3 et cascade complète

**Files:**
- Modify: `genecrew/src/genecrew/lieux_dits.py`
- Test: `genecrew/tests/test_lieux_dits.py`

**Interfaces:**
- Consumes: `chercher_dans_arbre`, `RechercheArbreIndisponible` (tâche 2) ; `emprise_de_commune`, `interroger_osm` (tâche 3).
- Produces: `resoudre_lieu_dit(client, nom, commune_handle, commune_lat, commune_lon, commune_bbox=None, dry_run=False) -> tuple[str | None, str]`
  — rend `(handle, provenance)`. `provenance` ∈ `{"arbre", "osm", "cree_sans_gps", "abandon"}`. Le rapport (tâche 6) l'affiche telle quelle.

- [ ] **Step 1: Écrire les tests qui échouent**

```python
from genecrew.lieux_dits import resoudre_lieu_dit


def test_l_arbre_gagne_et_le_reseau_n_est_pas_appele(monkeypatch):
    """Étage 1 : trouvé dans l'arbre, aucune requête OSM ne part.

    Vérifie l'ORDRE de la cascade, pas seulement son résultat : un étage 1 qui
    marcherait tout en appelant OSM passerait un test de résultat seul.
    """
    appels = []
    monkeypatch.setattr(
        "genecrew.lieux_dits._http_get_osm", lambda p: appels.append(p) or []
    )
    client = _client(
        _handler_places(_place("P0661", "h_roches", "Les Roches", "Hamlet", "h_com"))
    )
    handle, provenance = resoudre_lieu_dit(client, "Les Roches", "h_com", 47.2, 2.35)
    assert (handle, provenance) == ("h_roches", "arbre")
    assert appels == []


def test_absent_de_l_arbre_mais_dans_osm_est_cree_avec_gps(monkeypatch):
    """Étage 2 : OSM connaît La Rose, le lieu naît avec ses coordonnées."""
    monkeypatch.setattr(
        "genecrew.lieux_dits._http_get_osm",
        lambda p: [{"addresstype": "hamlet", "lat": "47.19476", "lon": "2.37858"}],
    )
    poses = {}
    monkeypatch.setattr(
        "genecrew.lieux_dits._creer_lieu",
        lambda **kw: poses.update(kw) or "h_neuf",
    )
    handle, provenance = resoudre_lieu_dit(
        _client(_handler_places()), "La Rose", "h_com", 47.2, 2.35
    )
    assert (handle, provenance) == ("h_neuf", "osm")
    assert poses["lat"] == "47.19476"
    assert poses["parent_handle"] == "h_com"


def test_absent_partout_est_cree_sans_gps(monkeypatch):
    """Étage 3 : Les Roches n'est ni dans l'arbre ni dans OSM. Décision assumée."""
    monkeypatch.setattr("genecrew.lieux_dits._http_get_osm", lambda p: [])
    monkeypatch.setattr("genecrew.lieux_dits._creer_lieu", lambda **kw: "h_neuf")
    handle, provenance = resoudre_lieu_dit(
        _client(_handler_places()), "Les Roches", "h_com", 47.2, 2.35
    )
    assert (handle, provenance) == ("h_neuf", "cree_sans_gps")


def test_une_panne_de_lecture_n_autorise_aucune_creation(monkeypatch):
    """L'ASYMÉTRIE centrale : lecture ratée → on n'écrit rien.

    Créer ici produirait un doublon du lieu qu'on n'a pas su lire, et la fusion
    de lieux est délicate (ADR 0015). Le point le plus facile à rater du chantier.
    """
    creations = []
    monkeypatch.setattr(
        "genecrew.lieux_dits._creer_lieu", lambda **kw: creations.append(kw) or "h_x"
    )
    monkeypatch.setattr("genecrew.lieux_dits._http_get_osm", lambda p: [])

    def _panne(request):
        return httpx.Response(500, json={"error": "boom"})

    handle, provenance = resoudre_lieu_dit(
        _client(_panne), "Les Roches", "h_com", 47.2, 2.35
    )
    assert (handle, provenance) == (None, "abandon")
    assert creations == []


def test_commune_sans_gps_saute_osm_et_cree_sans_coordonnees(monkeypatch):
    """Sans emprise calculable, pas d'étage 2 — on ne borne pas sur du vide."""
    appels = []
    monkeypatch.setattr(
        "genecrew.lieux_dits._http_get_osm", lambda p: appels.append(p) or []
    )
    monkeypatch.setattr("genecrew.lieux_dits._creer_lieu", lambda **kw: "h_neuf")
    handle, provenance = resoudre_lieu_dit(
        _client(_handler_places()), "Les Roches", "h_com", None, None
    )
    assert (handle, provenance) == ("h_neuf", "cree_sans_gps")
    assert appels == []
```

- [ ] **Step 2: Lancer les tests, vérifier qu'ils échouent**

Run: `uv run python -m pytest genecrew/tests/test_lieux_dits.py -v -k "resoudre or arbre_gagne or panne_de_lecture"`
Expected: FAIL — `ImportError: cannot import name 'resoudre_lieu_dit'`

- [ ] **Step 3: Implémenter**

Ajouter à `genecrew/src/genecrew/lieux_dits.py` (avec `import json` et l'import de `GrampsCreatePlaceTool` en tête de fichier) :

```python
def _creer_lieu(
    *,
    nom: str,
    parent_handle: str,
    lat: str | None,
    long: str | None,
    dry_run: bool,
) -> str:
    """Crée le lieu-dit sous sa commune. Rend son handle. Lève si l'écriture échoue."""
    creator = GrampsCreatePlaceTool()
    payload = json.loads(
        creator._run(
            name=nom,
            place_type="Hamlet",
            parent_handle=parent_handle,
            lat=lat,
            long=long,
            dry_run=dry_run,
        )
    )
    if not payload["success"]:
        raise RuntimeError(f"création du lieu-dit '{nom}' : {payload['error']}")
    return payload["data"]["handle"]


def resoudre_lieu_dit(
    client: GrampsClient,
    nom: str,
    commune_handle: str,
    commune_lat: float | None,
    commune_lon: float | None,
    commune_bbox: tuple[float, float, float, float] | None = None,
    *,
    dry_run: bool = False,
) -> tuple[str | None, str]:
    """(handle, provenance) du lieu-dit. Cascade à trois étages, le premier qui répond.

    provenance ∈ {"arbre", "osm", "cree_sans_gps", "abandon"} — le rapport
    l'affiche telle quelle, pour que le relecteur distingue un hameau confirmé
    par OSM d'un hameau créé sur la seule foi d'une transcription.
    """
    if not nom or not commune_handle:
        return None, "abandon"

    # Étage 1 — l'arbre. Une PANNE n'est pas une absence : on abandonne plutôt
    # que de créer un doublon du lieu qu'on n'a pas su lire.
    try:
        handle = chercher_dans_arbre(client, nom, commune_handle)
    except RechercheArbreIndisponible as exc:
        _LOG.warning(
            "Arbre illisible pour le lieu-dit « %s », aucun lieu posé : %s", nom, exc
        )
        return None, "abandon"
    if handle:
        return handle, "arbre"

    # Étage 2 — OSM borné à l'emprise de la commune.
    viewbox = emprise_de_commune(commune_lat, commune_lon, commune_bbox)
    coords = interroger_osm(nom, viewbox) if viewbox else None
    if coords:
        lat, long = coords
        return (
            _creer_lieu(
                nom=nom, parent_handle=commune_handle,
                lat=lat, long=long, dry_run=dry_run,
            ),
            "osm",
        )

    # Étage 3 — création sans coordonnées.
    return (
        _creer_lieu(
            nom=nom, parent_handle=commune_handle,
            lat=None, long=None, dry_run=dry_run,
        ),
        "cree_sans_gps",
    )
```

- [ ] **Step 4: Lancer les tests, vérifier qu'ils passent**

Run: `uv run python -m pytest genecrew/tests/test_lieux_dits.py -v`
Expected: PASS — 20 tests.

- [ ] **Step 5: Commit**

```bash
git add genecrew/src/genecrew/lieux_dits.py genecrew/tests/test_lieux_dits.py
git commit -m "feat(lieux-dits): cascade complete arbre puis OSM puis creation"
```

---

### Task 5: Brancher la cascade dans `import releve`, sans polluer `lieux_resolus`

**Files:**
- Modify: `genecrew/src/genecrew/releves_import.py:689-717` (`resoudre_ou_creer_lieu`)
- Test: `genecrew/tests/test_releves_import.py`

**Interfaces:**
- Consumes: `resoudre_lieu_dit` (tâche 4), `ReleveIndexe.evenement_lieu_dit` (tâche 1).
- Produces: `resoudre_ou_creer_lieu(...)` rend désormais `tuple[str | None, str]` — `(handle, provenance)`. `provenance` vaut `"commune"` quand aucun lieu-dit n'est demandé. **Tous les appelants doivent être mis à jour** (`_creer_evenement`, ligne 529).

- [ ] **Step 1: Écrire les tests qui échouent**

```python
def test_le_lieu_dit_est_pose_sur_l_evenement(mocker):
    """Le lieu le plus fin que l'acte donne — la décision de granularité."""
    mocker.patch(
        "genecrew.releves_import.run_lieu_import",
        return_value={"action": "ecrire", "handle": "h_com", "created": False},
    )
    mocker.patch(
        "genecrew.releves_import.resoudre_lieu_dit",
        return_value=("h_roches", "arbre"),
    )
    releve = _releve_lieu()
    releve.evenement_lieu_dit = "Les Roches"
    handle, provenance = resoudre_ou_creer_lieu(_arbre(), releve, dry_run=True)
    assert (handle, provenance) == ("h_roches", "arbre")


def test_sans_lieu_dit_le_comportement_ne_change_pas(mocker):
    """Rétrocompatibilité : la grande majorité des relevés n'en portent pas."""
    mocker.patch(
        "genecrew.releves_import.run_lieu_import",
        return_value={"action": "ecrire", "handle": "h_com", "created": False},
    )
    appels = mocker.patch("genecrew.releves_import.resoudre_lieu_dit")
    handle, provenance = resoudre_ou_creer_lieu(_arbre(), _releve_lieu(), dry_run=True)
    assert (handle, provenance) == ("h_com", "commune")
    appels.assert_not_called()


def test_commune_non_resolue_n_essaie_aucun_lieu_dit(mocker):
    """L'ordre est imposé : le parent ET l'emprise dépendent de la commune."""
    mocker.patch(
        "genecrew.releves_import.run_lieu_import",
        return_value={"action": "proposition", "handle": None},
    )
    appels = mocker.patch("genecrew.releves_import.resoudre_lieu_dit")
    releve = _releve_lieu()
    releve.evenement_lieu_dit = "Les Roches"
    handle, provenance = resoudre_ou_creer_lieu(_arbre(), releve, dry_run=True)
    assert handle is None
    appels.assert_not_called()


def test_le_lieu_dit_abandonne_retombe_sur_la_commune(mocker):
    """Abandon (arbre illisible) → la commune, pas rien. On ne perd pas l'événement."""
    mocker.patch(
        "genecrew.releves_import.run_lieu_import",
        return_value={"action": "ecrire", "handle": "h_com", "created": False},
    )
    mocker.patch(
        "genecrew.releves_import.resoudre_lieu_dit", return_value=(None, "abandon")
    )
    releve = _releve_lieu()
    releve.evenement_lieu_dit = "Les Roches"
    handle, provenance = resoudre_ou_creer_lieu(_arbre(), releve, dry_run=True)
    assert (handle, provenance) == ("h_com", "commune")


def test_le_lieu_dit_n_entre_jamais_dans_lieux_resolus():
    """INVARIANT : `lieux_resolus` ne contient que des COMMUNES.

    Le veto d'appariement compare des codes INSEE. Un code de hameau y serait
    incomparable et produirait un veto FAUX — or un candidat vetoé ne revient
    jamais devant le relecteur humain. `_raw_lieu` doit donc ignorer le lieu-dit.
    """
    releve = _releve_lieu()
    releve.evenement_lieu = "Saint-Martin-d'Auxigny"
    releve.evenement_departement = "Cher"
    releve.evenement_pays = "France"
    releve.evenement_lieu_dit = "Les Roches"
    assert "Roches" not in _raw_lieu(releve)
    assert _raw_lieu(releve) == "Saint-Martin-d'Auxigny, Cher, France"
```

- [ ] **Step 2: Lancer les tests, vérifier qu'ils échouent**

Run: `uv run python -m pytest genecrew/tests/test_releves_import.py -v -k "lieu_dit"`
Expected: FAIL — `resoudre_ou_creer_lieu` rend une chaîne, pas un tuple.

- [ ] **Step 3: Implémenter**

Remplacer le corps de `resoudre_ou_creer_lieu` (`releves_import.py:689-717`). **Ne toucher ni `_raw_lieu` ni `code_commune_prefixe`** : `_raw_lieu` ignore déjà `evenement_lieu_dit` puisqu'il ne lit que commune/département/pays — c'est ce que verrouille le dernier test.

```python
def resoudre_ou_creer_lieu(
    client: GrampsClient, releve: ReleveIndexe, *, dry_run: bool = False
) -> tuple[str | None, str]:
    """(handle, provenance) du lieu de l'événement — le plus fin que l'acte donne.

    La COMMUNE est résolue d'abord, toujours : elle sert de parent au lieu-dit et
    d'emprise à la requête OSM bornée. Commune non résolue → aucun lieu-dit tenté.

    provenance ∈ {"commune", "arbre", "osm", "cree_sans_gps"}. Un lieu-dit
    abandonné (arbre illisible) retombe sur la commune plutôt que sur rien.
    """
    raw = _raw_lieu(releve)
    if not raw:
        return None, "commune"
    try:
        out = run_lieu_import(client, raw, dry_run=dry_run)
    except (RuntimeError, httpx.HTTPError) as exc:
        _LOG.warning(
            "Cascade de lieu « %s » échouée, événement sans lieu : %s", raw, exc
        )
        return None, "commune"
    commune_handle = out.get("handle")
    if not commune_handle or not releve.evenement_lieu_dit.strip():
        return commune_handle, "commune"

    resolved = out.get("resolved") or {}
    lat = float(resolved["lat"]) if resolved.get("lat") else None
    lon = float(resolved["long"]) if resolved.get("long") else None
    handle, provenance = resoudre_lieu_dit(
        client,
        releve.evenement_lieu_dit.strip(),
        commune_handle,
        lat,
        lon,
        dry_run=dry_run,
    )
    if handle:
        return handle, provenance
    return commune_handle, "commune"
```

Puis, à `releves_import.py:529-531`, dans `_creer_evenement` :

```python
    lieu_handle, lieu_provenance = (
        resoudre_ou_creer_lieu(client, releve, dry_run=dry_run)
        if avec_lieu
        else (None, "commune")
    )
```

et ajouter `"lieu_provenance": lieu_provenance` au dict rendu, à côté de `"lieu": lieu_handle`.

Ajouter l'import en tête : `from genecrew.lieux_dits import resoudre_lieu_dit`.

- [ ] **Step 4: Lancer toute la suite**

Run: `uv run python -m pytest genecrew/tests/ -q`
Expected: PASS. Les tests existants qui appelaient `resoudre_ou_creer_lieu` et attendaient une chaîne doivent être adaptés au tuple — c'est attendu et fait partie de la tâche.

- [ ] **Step 5: Commit**

```bash
git add genecrew/src/genecrew/releves_import.py genecrew/tests/test_releves_import.py
git commit -m "feat(import releve): poser le lieu-dit quand l'acte le nomme"
```

---

### Task 6: Le compte rendu affiche des identifiants Gramps

**Files:**
- Modify: `genecrew/src/genecrew/releves_import.py:1213-1227` (rendu) et `1215-1217` (sujet créé)
- Test: `genecrew/tests/test_releves_import.py`

**Interfaces:**
- Consumes: `lieu_provenance` (tâche 5).
- Produces:
  - `_id_lisible(client: GrampsClient, genre: str, handle: str | None) -> str` — traduit un handle en `gramps_id`. Appelée **par `run_import_releve`**, jamais par le formateur.
  - Le dict `resultat["evenement"]` gagne `event_gramps_id` et `lieu_gramps_id`.

**`format_import_releve(resultat: dict)` garde sa signature à un seul argument.** Elle lit
tout depuis le dict (`resultat["releve"]`, `resultat["appariement"]`) et son unique
appelant est `main.py:573`. Y injecter un `client` ferait entrer des entrées-sorties
dans une fonction de rendu — la traduction se fait donc en amont, au moment de
l'écriture, et le formateur ne lit que des chaînes déjà résolues. Aucun test de
rendu n'a alors besoin de simulacre.

- [ ] **Step 1: Écrire les tests qui échouent**

```python
def test_le_rapport_montre_le_gramps_id_pas_le_handle():
    """Un relecteur doit pouvoir vérifier ce qui a été écrit sans traduire à la main.

    Gramps porte deux identifiants : le `handle` interne (32 hexadécimaux, jamais
    affiché dans l'interface) et le `gramps_id` (E0332). Le rapport montrait le
    premier, donc rien n'était vérifiable à l'œil.
    """
    out = {
        "releve": _releve_lieu(),
        "appariement": _appariement_net(),
        "dry_run": False,
        "ecrit": True,
        "raison": "importée",
        "evenement": {
            "event_handle": "h_evt",
            "event_gramps_id": "E0332",
            "lieu": "h_lieu",
            "lieu_gramps_id": "P0661",
            "lieu_provenance": "arbre",
        },
    }
    texte = format_import_releve(out)
    assert "E0332" in texte
    assert "P0661" in texte
    assert "h_evt" not in texte


def test_le_rapport_nomme_la_provenance_du_lieu():
    """Garde-fou de la création automatique.

    Un hameau créé sans GPS est exactement ce qu'une graphie mal lue produirait.
    Il doit se distinguer à l'œil d'un hameau confirmé par OSM.
    """
    out = {
        "releve": _releve_lieu(),
        "appariement": _appariement_net(),
        "dry_run": False,
        "ecrit": True,
        "raison": "importée",
        "evenement": {
            "event_handle": "h_evt",
            "event_gramps_id": "E0334",
            "lieu": "h_lieu",
            "lieu_gramps_id": "P0663",
            "lieu_provenance": "cree_sans_gps",
        },
    }
    assert "sans GPS" in format_import_releve(out)


def test_en_simulation_aucun_faux_identifiant_n_est_imprime():
    """Le dry-run rend des handles synthétiques `DRYRUN:…` — pas d'identifiant réel.

    Un rapport de simulation qui ressemble trop à un rapport d'écriture est un
    piège : les rapports sont relus avant d'être consommés par `apply`.
    """
    out = {
        "releve": _releve_lieu(),
        "appariement": _appariement_net(),
        "dry_run": True,
        "ecrit": False,
        "raison": "simulation",
        "evenement": {
            "event_handle": "DRYRUN:evt",
            "event_gramps_id": "à créer",
            "lieu": "DRYRUN:lieu",
            "lieu_gramps_id": "à créer",
            "lieu_provenance": "cree_sans_gps",
        },
    }
    texte = format_import_releve(out)
    assert "DRYRUN" not in texte
    assert "à créer" in texte


def test_id_lisible_ne_fabrique_pas_d_identifiant_en_simulation():
    """`DRYRUN:…` n'a pas de gramps_id : en inventer un tromperait le relecteur."""
    assert _id_lisible(None, "event", "DRYRUN:evt") == "à créer"


def test_id_lisible_retombe_sur_le_handle_si_la_lecture_echoue():
    """Mieux vaut une valeur laide qu'un rapport muet sur ce qui vient d'être écrit."""

    def _panne(request):
        return httpx.Response(500, json={})

    assert _id_lisible(_client(_panne), "event", "h_evt") == "h_evt"
```

Ajouter le helper `_appariement_net()` près des autres constructeurs du fichier :

```python
def _appariement_net():
    """Un Appariement NET minimal, pour les tests qui ne portent que sur le rendu."""
    return Appariement(verdict="net", gramps_id="I0305", handle="h_p", poids=0)
```

- [ ] **Step 2: Lancer les tests, vérifier qu'ils échouent**

Run: `uv run python -m pytest genecrew/tests/test_releves_import.py -v -k "rapport or simulation or id_lisible"`
Expected: FAIL — `_id_lisible` n'existe pas ; le rapport imprime encore `h_evt`.

- [ ] **Step 3: Implémenter la traduction**

Ajouter dans `releves_import.py` :

```python
_LIBELLE_PROVENANCE = {
    "arbre": "déjà dans l'arbre",
    "osm": "créé avec GPS (OSM)",
    "cree_sans_gps": "créé sans GPS",
    "commune": "commune",
}


def _id_lisible(client: GrampsClient | None, genre: str, handle: str | None) -> str:
    """`gramps_id` de l'objet, ou "à créer" en simulation, ou le handle en dernier repli.

    En simulation le handle est synthétique (`DRYRUN:…`) : aucun identifiant réel
    n'existe encore, et en inventer un tromperait le relecteur qui valide sur ce
    rapport. Le repli sur le handle brut couvre l'échec de lecture — un rapport ne
    doit jamais faire échouer l'import qu'il décrit.
    """
    if not handle:
        return "aucun"
    if handle.startswith("DRYRUN:"):
        return "à créer"
    if client is None:
        return handle
    try:
        obj = client.get_object(f"{genre}s", handle)
    except Exception:  # noqa: BLE001 — un rapport ne fait jamais échouer un import
        return handle
    return (obj or {}).get("gramps_id") or handle
```

- [ ] **Step 4: Peupler le dict à l'écriture**

Dans `run_import_releve`, juste après que l'événement a été créé et avant que le
résultat soit rendu, traduire les deux handles :

```python
    evt = resultat.get("evenement") or {}
    if evt.get("event_handle"):
        evt["event_gramps_id"] = _id_lisible(client, "event", evt["event_handle"])
        evt["lieu_gramps_id"] = _id_lisible(client, "place", evt.get("lieu"))
```

- [ ] **Step 5: Rendre le rapport**

Remplacer le bloc `releves_import.py:1218-1223` :

```python
    evt = resultat.get("evenement") or {}
    if evt.get("event_handle"):
        lieu_txt = "aucun"
        if evt.get("lieu"):
            provenance = _LIBELLE_PROVENANCE.get(
                evt.get("lieu_provenance", "commune"),
                evt.get("lieu_provenance", ""),
            )
            lieu_txt = f"{evt.get('lieu_gramps_id') or evt['lieu']} — {provenance}"
        lignes.append(
            f"  {releve.evenement_type} créé : "
            f"{evt.get('event_gramps_id') or evt['event_handle']} (lieu {lieu_txt})"
        )
```

- [ ] **Step 4: Lancer toute la suite**

Run: `uv run python -m pytest genecrew/tests/ -q && uv run ruff check .`
Expected: PASS, ruff vert.

- [ ] **Step 5: Commit**

```bash
git add genecrew/src/genecrew/releves_import.py genecrew/tests/test_releves_import.py
git commit -m "feat(import releve): afficher les gramps_id et la provenance du lieu"
```

---

### Task 7: Éprouver par mutation les tests qui vérifient une absence

**Files:**
- Aucune modification attendue si les tests sont bons.

Trois tests vérifient qu'une chose **n'arrive pas**. Ce sont ceux qui passent au vert sans rien protéger si on casse ce qu'ils gardent.

- [ ] **Step 1: Lancer le chasseur de tests muets**

Dispatcher le sous-agent `chasseur-de-tests-muets` sur le diff de la branche, en lui désignant nommément les trois cibles :

1. `test_l_arbre_gagne_et_le_reseau_n_est_pas_appele` — mutation : faire appeler `interroger_osm` **avant** `chercher_dans_arbre`. Le test doit tomber.
2. `test_une_panne_de_lecture_n_autorise_aucune_creation` — mutation : remplacer `return None, "abandon"` par une chute vers l'étage 3. Le test doit tomber.
3. `test_le_lieu_dit_n_entre_jamais_dans_lieux_resolus` — mutation : faire `_raw_lieu` préfixer la chaîne par `evenement_lieu_dit`. Le test doit tomber.

- [ ] **Step 2: Corriger tout test qui survit à sa mutation**

Un test qui reste vert sous sa mutation ne protège rien : le réécrire pour qu'il observe le mécanisme (ordre d'appel, absence d'écriture) et non seulement le résultat final.

- [ ] **Step 3: Commit**

```bash
git add genecrew/tests/
git commit -m "test(lieux-dits): durcir les tests d'absence eprouves par mutation"
```

---

### Task 8: Rattraper les deux événements déjà écrits

**Files:**
- Aucun code. Opération de données.

E0332 et E0333 ont été écrits avant ce chantier et portent le mauvais lieu.

- [ ] **Step 1: Vérifier l'état réel avant d'écrire**

```bash
uv run python -c "
from dotenv import load_dotenv
from crewai_custom_tools.tools.genealogy.gramps.client import GrampsClient, GrampsConfig
load_dotenv()
c = GrampsClient(GrampsConfig.from_env())
for gid in ('E0332', 'E0333'):
    e = c.find_by_gramps_id('events', gid)
    print(gid, e.get('place') or 'aucun lieu')
"
```

- [ ] **Step 2: Corriger dans l'interface Gramps Web**

| Événement | État attendu | Cible |
|---|---|---|
| E0332 († Ursin Charles, 5 août 1868) | aucun lieu | **P0661** Les Roches |
| E0333 († Jeanne Marie Mélanie, 21 mars 1935) | P0504 commune | **P0661** Les Roches |

Aucun verbe de la CLI n'attache un lieu à un événement existant ; l'interface est le chemin le plus court, et l'opération porte sur deux objets.

- [ ] **Step 3: Vérifier**

Relancer la commande du Step 1 : les deux doivent porter le handle de P0661.

---

## Après le plan

Le dépouillement de la file d'actes (Jacques Villaudy, mariages 1888/1890/1925, correction de la naissance de Marie Antoinette au 14 janvier 1879, décès de Silvain entre 1921 et 1935) vient **après** ce chantier, comme la spec l'établit : celui-ci change la façon dont les lieux se posent, donc saisir avant produirait des événements à reprendre.
