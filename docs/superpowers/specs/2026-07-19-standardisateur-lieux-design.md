# Standardisateur de lieux — Design

> Statut : approuvé (brainstorming) — 2026-07-19
> Portée : un incrément autonome de GeneCrew, **implémenté en 6 phases** à critère de sortie.
> Écrit une **donnée cœur** (lieu) → relâche de façon bornée la politique « lieu = proposition »
> (nouvel **ADR 0010**, dans l'esprit de l'ADR 0009 pour le genre).

## 1. Contexte & objectif

Après les noms (casse) et le genre, le **Standardisateur de lieux** normalise les lieux d'un arbre
Gramps Web : parser les chaînes de lieux importées à plat (GEDCOM Geneanet/Heredis), résoudre le
nom officiel + la hiérarchie + les coordonnées, et **reconstruire dans Gramps le modèle natif que
l'import GEDCOM a jeté** (`Place` typé, `PlaceName`, `placeref` hiérarchiques datés, `lat/long`).

**C'est un OUTIL générique, pas le nettoyage d'un arbre.** L'outil ne connaît que des **classes de
problèmes** et des **points d'extension** ; il ne présume rien d'un dataset particulier. L'arbre de
l'auteur (franco-suisse + Algérie française + Italie) est le **premier jeu qui exerce l'outil** et
la **source des fixtures de test** — il n'apparaît pas dans l'architecture. Extensibilité **par
données** (une ligne de dataset, un résolveur de plus), jamais par code spécifique à un dataset.
Borné dans le scope (YAGNI) : standardiser des lieux Gramps, pas une plateforme SIG.

### Classes de problèmes traitées

| Classe | Résolution | Score |
| --- | --- | --- |
| Pays à référentiel autoritaire (code → 1 lieu) | résolveur par code (INSEE `geo.api.gouv.fr`, OFS) | **1.0** |
| Pays sans référentiel | géocodage par nom (résolveur mondial) | **< 1.0** (confiance × similarité) |
| Lieux à transition temporelle (nom/souveraineté datés) | capacité data-driven + dataset de transitions | selon la chaîne |

### Décisions actées (brainstorming)

1. **Périmètre = pipeline complet jusqu'à l'écriture**, implémenté en phases (déterministe → flou →
   écriture → transitions → dédup), chaque phase à critère de sortie.
2. **Modèle d'écriture = hiérarchie complète** : créer/réutiliser les lieux parents (`Pays > Région
   > Département > Commune`),`placeref` enfant→parent, enrichir la feuille (nom + type + GPS).
3. **Source de référence = API live + cache** (`geo.api.gouv.fr`, OFS/swisstopo, Nominatim/
   Géoplateforme), mise en cache par le cache SHA-256 de `crewai_custom_tools`.
4. **Sûreté d'écriture = auto sur score** : autoritaire (1.0) écrit ; flou ≥ `min_score` écrit ;
   `< min_score` → proposition. Curseur `--min-score` (défaut 0.90).
5. **Chaîne de résolveurs routée par pays**, contrat `ResolvedPlace` ; l'orchestrateur ne connaît
   pas les APIs.
6. **Nom principal = moderne canonique** ; le nom d'origine → `alt_name`. Non daté par défaut ;
   **daté** quand une transition connue s'applique (souveraineté/nom).
7. **Dédup : parents auto-réutilisés** (dedup sûre) ; **fusion de feuilles existantes = toujours
   proposition** (déplace des backlinks d'événements), jamais auto.
8. **Transitions temporelles = capacité générique data-driven** : Gramps modélise nativement les
   noms/`placeref` datés ; l'outil émet des chaînes datées **quand le dataset de transitions
   l'indique**. Dataset vide → tout le monde a une chaîne unique non datée.
9. **Géocodage : jamais Google** (ses CGU interdisent le stockage permanent des lat/long) ;
   OSM/Nominatim (monde, ODbL + attribution), Géoplateforme (FR), swisstopo (CH), tout
   stockage-safe. Provenance (fournisseur + requête + date) écrite en note/citation (devoir de preuve).
10. **Deux commandes** `genecrew lieux` (lecture seule) / `genecrew lieux-apply` (écriture), même
    idiome que `gender`/`gender-apply`, un seul moteur de score. Déterministe (pas d'agent LLM).

## 2. Architecture

### 2.1 Pipeline par lieu

```
pname (chaîne à N segments)
  └─ 1. PARSE positionnel + détection de décalage          [pur, offline]
  └─ 2. NORMALISE le pays → ISO                             [pur, table]
  └─ 3. ROUTE vers le résolveur du pays (registre) :
         référentiel autoritaire → code → 1 lieu   (score 1.0)
         sinon                   → géocodage par nom (score < 1.0)
  └─ 4. ResolvedPlace {nom moderne, type, chains[], lat/long, score, source, query}
  └─ 5. nom d'origine → alt_name (daté si transition connue)
  └─ 6. score ≥ seuil → écriture (parents réutilisés/créés + placeref + GPS + provenance)
         score < seuil → proposition YAML
         feuilles doublons → proposition de fusion (jamais auto)
```

### 2.2 Emplacement du code (respecte le layout existant)

- `crewai_custom_tools/…/genealogy/standardize/places.py` — **pur** : parse pname, détection de
  décalage, normalisation pays. (à côté de `names.py`)
- `crewai_custom_tools/…/genealogy/geo/` — résolveurs `france.py`, `suisse.py`, `nominatim.py`
  (outils `@api_tool` + cache), + `registry.py` (routage par pays), + `score.py`, + `transitions.py`
  (capacité data-driven) et `data/transitions.csv` (dataset, peut être vide).
- `crewai_custom_tools/…/genealogy/gramps/write_tools.py` — `GrampsCreatePlaceTool`,
  `GrampsUpdatePlaceTool` (gated dry-run via `effective_dry_run`).
- `crewai_custom_tools/…/genealogy/models/domain.py` — les modèles § 3.
- `genecrew/…/places.py` (`run_places`, read-only) + `places_apply.py` (`run_places_apply`) +
  `render_*` Markdown purs ; `iter_places` (pagination `/api/places/`) dans `batching.py`.

## 3. Modèles de données (`domain.py`)

Modèles dédiés (le `Proposition` du genre est trop spécifique). Chacun une responsabilité.

```python
class PlaceLevel(BaseModel):
    """Un maillon d'une chaîne de parents (haut→bas)."""
    name: str
    place_type: str            # "Country" | "Region" | "Department" | "Municipality"…
    code: str | None = None    # INSEE / OFS / postal, si connu

class DatedChain(BaseModel):
    """Une chaîne de parents valable sur une période."""
    date_qualifier: str | None = None      # None | "avant AAAA-MM-JJ" | "après AAAA-MM-JJ"
    levels: list[PlaceLevel]

class DatedName(BaseModel):
    value: str
    date_qualifier: str | None = None

class ResolvedPlace(BaseModel):
    """Sortie NORMALISÉE que TOUT résolveur pays renvoie (le contrat de la chaîne)."""
    name: str                          # nom canonique moderne de la feuille
    place_type: str
    lat: str | None = None             # WGS84 décimal (jamais grille suisse x/y)
    long: str | None = None
    code: str | None = None
    chains: list[DatedChain] = []      # parents ; cas générique = 1 chaîne non datée
    alt_names: list[DatedName] = []    # nom d'origine + variantes
    score: float                       # 1.0 autoritaire ; <1.0 flou
    source: str                        # "geo.api.gouv.fr" | "swisstopo+OFS" | "Nominatim/OSM"
    query: str                         # requête exacte émise (provenance / rejouable)

class PlaceProposition(BaseModel):
    """La proposition d'un lieu (rapport MD + YAML). Miroir du flux gender/gender-apply."""
    type: str                  # "lieu_resolu" | "lieu_indecidable"
    gramps_id: str
    handle: str
    original: str              # pname brut → alt_name d'origine
    country: str               # pays normalisé
    resolution: ResolvedPlace | None = None   # None si indécidable
    action: str                # "ecrire" | "proposition" | "indecidable"
    confiance: str             # "haute" | "moyenne" | "basse" (dérivée du score)
    priorite: str
    preuve: str                # provenance lisible (source + requête + score)

class PlaceMergeProposition(BaseModel):
    """Deux feuilles existantes résolvant vers le même lieu canonique (dédup). JAMAIS auto."""
    gramps_id_keep: str;  handle_keep: str
    gramps_id_merge: str; handle_merge: str
    canonical: str
    reason: str
```

`ResolvedPlace` est **le contrat** : France, Suisse, Nominatim renvoient tous cette forme ; ajouter
un pays = un résolveur de plus qui la remplit. Le `score` porte la sûreté et décide `action`.

## 4. Résolveurs par pays

Registre `{pays_iso → résolveur}` + résolveur de repli mondial. Chaque résolveur est un outil
`@api_tool` (timeout/retry/rate-limit/cache/ok-err), mappe le JSON fournisseur → `ResolvedPlace`.

| Résolveur | Source | Entrée | Sortie clé | Gotchas |
| --- | --- | --- | --- | --- |
| `france.py` | `geo.api.gouv.fr/communes/{code}` (autoritaire) + Géoplateforme (flou) | code INSEE / nom | `centre`=`[lon,lat]` WGS84, dép, région, fusions | ordre `[lon,lat]` |
| `suisse.py` | registre **OFS** (identité/hiérarchie) + **swisstopo** GeoAdmin (GPS) | n° OFS / nom | `attrs.lat`/`attrs.lon` WGS84 | lire `lat/lon`, **jamais `x/y`** (grille LV95) |
| `nominatim.py` | Nominatim/OSM (repli mondial) | nom + pays | `lat`/`lon` WGS84, `importance` | 1 req/s, User-Agent, ODbL attribution, cache obligatoire |

**Invariants GPS (verrouillés par tests)** : tout est **WGS84**, aucune reprojection ; GeoJSON =
`[lon, lat]` (ne pas inverser) ; swisstopo `lat/lon` uniquement.

## 5. Score & seuils

- Autoritaire (code → 1 lieu) : **score = 1.0**.
- Flou : `score = confiance_fournisseur × similarité(nom_demandé, nom_rendu)` ∈ [0,1].
- **Garde-fou d'ambiguïté** (constante interne) : si le 2ᵉ candidat est à marge < 0.1 du 1ᵉ →
  forcé en `proposition`, même si le top score est haut.

Mapping (identique dans `lieux` et `lieux-apply`) :

```
score == 1.0                     → "ecrire"       (haute)
score >= min_score  (non ambigu) → "ecrire"       (moyenne)
score <  min_score               → "proposition"  (basse)
pas de candidat / parse KO / pays inconnu → "indecidable"
fusion de feuilles               → "proposition"  (toujours ; jamais "ecrire")
```

**Config minimale** (YAGNI) : `--min-score` (défaut **0.90**) est le seul curseur propre aux lieux.
Le garde-fou d'ambiguïté et la spine des transitions sont des **données/constantes**, pas des flags.
Partagés : `--scope`, `--limit`, `--batch-size`, `--date`, `--dry-run` (+ `GENECREW_DRY_RUN`
effectif via `effective_dry_run`). `--min-score 1.0` = mode « autoritaire seul ».

## 6. Flux d'écriture de la hiérarchie

Endpoints Gramps : `GET /api/places/` (charger), `POST /api/places/` (créer parent),
`PUT /api/places/{handle}` (enrichir feuille), `POST /api/places/{a}/merge/{b}` (dédup, proposée).

**Index de parents**, construit au démarrage du run, clé = **chemin complet** :

```
"France" → h_a ; "France>Centre-Val de Loire" → h_b ; "France>…>Cher" → h_c
```

Reconstruit depuis les lieux existants (`name.value` + `place_type` + `placeref_list`). Les feuilles
plates (`type Unknown`, 0 placeref) ne matchent aucune clé de parent → jamais confondues. Les
parents créés lors d'un run **précédent** sont retrouvés → **idempotence entre runs**.

**Écriture d'une feuille (`action="ecrire"`), parents haut→bas d'abord :**

```
pour chaque DatedChain de resolved.chains :
  parent = None
  pour level de chain.levels (haut→bas) :
    key = chemin(chain, level)
    parent = index.setdefault(key, CreatePlace(name, type, placeref=[{ref:parent, date:chain.date_qualifier}] si parent))
UpdatePlace(leaf.handle,
    name=resolved.name, place_type=resolved.place_type,
    lat=resolved.lat, long=resolved.long, code=resolved.code,
    placeref_list=[{ref: feuille_parent, date: chain.date_qualifier} par chaîne],
    alt_names += DatedName absents,
    note de provenance = f"{source} | {query} | score {score}")
```

**Idempotence** : parents créés une fois (clé de chemin) ; feuille **no-op si déjà conforme**
(nom + placerefs + GPS déjà posés → aucun PUT) ; `alt_name` ajouté seulement si absent.
**Dry-run** : `CreatePlace` en simulation renvoie un **handle synthétique** (`"DRYRUN:<chemin>"`)
pour que les `placeref` suivants se lient (simulés) et que le rapport montre l'arbre complet ;
aucun POST/PUT réel.

## 7. Capacité de transitions temporelles (data-driven)

Générique : un dataset `transitions.csv` décrit des changements connus (souveraineté/nom, à date
fixe). Le résolveur consulte les transitions applicables au pays/contexte ; si une s'applique, il
émet **deux `DatedChain`** (avant/après) + un `alt_name` **daté**, sinon **une** chaîne non datée.

- **Chaîne moderne** (après transition) : issue du géocodage (nom + GPS actuels).
- **Chaîne historique** (avant transition) : issue des **segments du pname d'origine** (contexte
  admin conservé par le GEDCOM) + spine + date de la transition. Dégradation gracieuse si segments
  absents.

**Dataset vide = comportement identique au générique (1 chaîne non datée).** Aucune connaissance
d'un pays particulier n'est codée : ajouter une transition = ajouter une ligne. (Le cas de l'arbre
de l'auteur — Algérie 1962 — est **une ligne de données**, pas du code.)

## 8. Dédup des feuilles

Après résolution, grouper par identité canonique (`name` + chemin parent + pays). ≥ 2 handles
existants sur le même canonique → `PlaceMergeProposition` (garder le plus petit `gramps_id`,
fusionner les autres via `/merge/`). **Écrit dans le YAML/rapport, jamais exécuté en auto**
(la fusion déplace des backlinks d'événements = donnée cœur, revue humaine obligatoire).

## 9. Sûreté d'écriture, réversibilité, ADR

- Double interrupteur **dry-run** (`--dry-run` OU `GENECREW_DRY_RUN`), défaut **sûr** (absent →
  simuler), rapports au mode **effectif** (`effective_dry_run`) — comme `gender-apply`.
- **Réversible** : POST/PUT tracés dans l'historique des transactions Gramps ; sauvegarde des
  volumes conseillée avant la première écriture de phase.
- **ADR 0010** : relâche de façon bornée la politique « lieu = proposition ». Autorisé en auto :
  enrichir une feuille (nom/type/GPS) + créer/lier des lieux parents, au-dessus de `min_score`.
  **Reste proposition** : la fusion de feuilles existantes (déplacement de backlinks).

## 10. Tests & phasage

**Fixtures par CLASSE** (synthétiques, minimales — pas des extraits de l'arbre) : autoritaire FR,
autoritaire CH, flou mondial, transition temporelle, décalé/dégradé, feuilles doublons.

**Unitaires purs / offline (cct)** : parser (propre/décalé/sans pays), normaliseur pays, résolveurs
(HTTP mocké → `ResolvedPlace`, invariants GPS), score (autoritaire/flou/ambiguïté), transitions
(**dataset vide → 1 chaîne ; 1 ligne → 2 chaînes datées** = preuve de généricité), flux d'écriture
(idempotence, parents 1×, dry-run handles synthétiques).

**E2e orchestration (genecrew, mock transport)** : `run_places` (aucun PUT/POST) ; `run_places_apply`
(autoritaire écrit, flou ≥ seuil écrit, < seuil proposition, dry-run n'écrit rien, fusion proposée
non exécutée) ; `--help` des deux commandes.

| Phase | Livrable | Critère de sortie |
| --- | --- | --- |
| **P1** Parse + normalise | `standardize/places.py` (pur) | tests par classe verts, 0 réseau |
| **P2** Résolveurs + score | `geo/{france,suisse,nominatim}.py` + `registry.py` + `score.py` | chaque résolveur → `ResolvedPlace` (HTTP mocké) ; score correct |
| **P3** `lieux` (lecture) | `genecrew/places.py` + CLI + rapport MD/YAML | plan correct sur fixtures, **aucune écriture** |
| **P4** write + `lieux-apply` | `GrampsCreate/UpdatePlaceTool` + `places_apply.py` | autoritaire écrit (parents 1×, feuille enrichie), **idempotent**, dry-run n'écrit rien |
| **P5** transitions datées | `transitions.py` + dataset | dataset vide = 1 chaîne ; 1 ligne = 2 chaînes datées |
| **P6** dédup feuilles | groupement canonique → `PlaceMergeProposition` | doublons **proposés**, jamais fusionnés en auto |

P1→P4 = cœur déterministe + flou **jusqu'à l'écriture** ; P5 et P6 = incréments séparables. Chaque
phase = logiciel qui tourne et se teste seul.

## 11. Annexes

- **Endpoints Gramps** : `GET/POST /api/places/`, `PUT /api/places/{handle}`,
  `POST /api/places/{phoenix}/merge/{titanic}`. Schéma `Place` : `name` (PlaceName `{value,lang,date}`),
  `alt_names[]`, `place_type`, `lat`/`long`, `code`, `placeref_list[]` (PlaceReference `{ref,date}`).
- **Sources externes** : `geo.api.gouv.fr` (FR communes, ouvert), Géoplateforme `data.geopf.fr/geocodage`
  (FR, 50 req/s), swisstopo GeoAdmin `api3.geo.admin.ch` (CH), OFS (registre communes CH), Nominatim
  (monde, 1 req/s, ODbL). Specs vendorées : `docs/swagger/geoplateforme-geocodage*.{yaml}`.
- **Note de provenance** (sur chaque lieu écrit) : `[genecrew:lieux:<date>] <source> | <query> | score <s>`.
- **Env/config** : `--min-score` (0.90), `GENECREW_DRY_RUN`, cache SHA-256 cct. Jamais Google Maps
  (CGU : stockage permanent interdit).
