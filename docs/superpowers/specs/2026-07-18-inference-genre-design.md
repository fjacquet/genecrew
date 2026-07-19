# Inférence de genre à partir du prénom — Design

> Statut : approuvé (brainstorming) — 2026-07-18
> Portée : un incrément autonome de GeneCrew. Premier **émetteur de propositions** du projet.

## 1. Contexte & objectif

L'arbre Gramps (« My Family Tree », ~2 100 personnes, racine franco-suisse) contient des
personnes de **genre inconnu** (`gender=2`). L'objectif est d'**inférer** leur sexe (F/M) à
partir de leur prénom, à l'aide d'un dictionnaire *prénom → sexe* **souverain et hors-ligne**
(INSEE + OFS), et d'émettre des **propositions pour revue humaine** — jamais d'écriture directe,
car le genre est un **fait** (principe forme-vs-fait, ADR 0001).

Le même dictionnaire sert aussi à **détecter les contradictions** : une personne dont le genre
posé (M ou F) est contredit par un prénom très marqué est probablement une erreur de saisie.

### Ce que fait / ne fait pas cet incrément

- **Fait** : lecture seule sur Gramps ; inférence pure ; production d'un rapport Markdown + d'un
  fichier YAML de propositions.
- **Ne fait pas** : aucune écriture Gramps (ni `gender`, ni note, ni tag) ; pas d'outil CrewAI ;
  pas d'agent LLM. C'est un composant déterministe, comme l'audit et le standardisateur de noms.

## 2. Décisions actées (brainstorming)

1. **Dataset = INSEE + OFS/BFS fusionnés** en un dictionnaire compact embarqué. Souverain,
   hors-ligne. Couvre la branche FR (INSEE) et CH y compris suisse-allemande (OFS).
2. **Politique conservatrice** : proposer un sexe **seulement si** le sexe dominant représente
   **≥ 95 %** des naissances **et** un volume **≥ 50**. Tout le reste (unisexe, rare, 80–95 %,
   prénom non couvert) → **abstention**, listé à part comme « indécidable ».
3. **Périmètre = inconnus + contradictions**. Deux catégories de propositions :
   - `genre_inconnu` : `gender=2` + prénom tranchable → proposer F ou M.
   - `genre_contradiction` : `gender ∈ {M,F}` contredit par un prénom tranchable → « à vérifier ».
4. **Sortie** : rapport Markdown (humain) **+** fichier YAML de `Proposition` (machine-readable,
   pour un futur « apply »). Établit le modèle `Proposition` du pipeline (premier émetteur).

## 3. Sources de données

### 3.1 INSEE — Fichier des prénoms (national)

- Source : `insee.fr` / `data.gouv.fr` (« Fichier des prénoms depuis 1900 »).
- Colonnes : `SEXE` (**1 = masculin, 2 = féminin** — convention INSEE, **≠** Gramps),
  `PREUSUEL` (prénom, **majuscules, sans diacritiques**, longueur 25), `ANNAIS` (année 1900→2025
  ou `XXXX`), `NOMBRE` (effectif, **arrondi au multiple de 5**).
- Licence : **Licence Ouverte / Etalab**.
- Pièges :
  - Les prénoms rares sont **regroupés** sous la valeur `_PRENOMS_RARES` (à **exclure** au build ;
    ils tomberaient de toute façon en abstention).
  - Les lignes `ANNAIS = "XXXX"` (année inconnue) sont **conservées** : elles agrègent des
    effectifs réels, utiles pour le total par prénom.

### 3.2 OFS/BFS — Prénoms des nouveau-nés (Suisse)

- Source : `bfs.admin.ch` / `opendata.swiss` (organisation *Bundesamt für Statistik BFS*),
  statistiques STATPOP/BEVNAT. Fichiers px-x (PC-Axis) / CSV.
- Contenu : effectifs de prénoms de nouveau-nés par sexe (fichiers séparés masculin/féminin).
- Licence : conditions OFS open data (usage libre avec mention de la source).
- Piège : format et libellés (accents présents, contrairement à l'INSEE) → **normalisation
  au build** pour aligner les clés sur la forme canonique (§4.1).

Les fichiers bruts (plusieurs Mo) **ne sont pas embarqués**. Seule la table agrégée l'est.

## 4. Composants

### 4.1 Table embarquée (dans `crewai_custom_tools`)

- **`tools/genealogy/data/prenoms_sexe.csv`** — table compacte **versionnée** :
  colonnes `prenom` (clé normalisée), `n_f` (int), `n_m` (int). Une ligne par prénom distinct.
  Estimé ~40–50k lignes, ~1 Mo.
- **`tools/genealogy/data/README.md`** — provenance : URLs sources, licences, date d'extraction,
  commande de régénération.
- **`scripts/build_prenoms_sexe.py`** — script de build **one-off** (hors runtime) : lit les
  fichiers bruts INSEE + OFS depuis un chemin local, normalise les clés, **fusionne les effectifs
  par prénom** (`n_f += …`, `n_m += …` en croisant les deux sources), exclut `_PRENOMS_RARES`,
  écrit le CSV. Idempotent, sans réseau au moment de l'exécution (les bruts sont fournis en entrée).

**Clé canonique** `_normkey(prenom)` (partagée build + runtime, donc **une seule
implémentation** importée des deux côtés) :

1. `strip()` + passage en MAJUSCULES ;
2. suppression des diacritiques (NFD → filtrage des marques combinantes) : `JOSÉ → JOSE` ;
3. normalisation des apostrophes/tirets en variantes ASCII canoniques (`’→'`, tirets Unicode → `-`).

### 4.2 Inférence pure (dans `crewai_custom_tools`)

**`tools/genealogy/analysis/gender.py`** — aucune I/O réseau, testable hors-ligne.

```python
DATA_PATH = Path(__file__).parents[1] / "data" / "prenoms_sexe.csv"
MIN_TOTAL = 50
MIN_RATIO = 0.95

@lru_cache(maxsize=1)
def load_prenoms_table() -> dict[str, tuple[int, int]]:
    """Charge {clé_normalisée: (n_f, n_m)} depuis le CSV embarqué (une fois)."""

def _first_forename(given: str) -> str:
    """Premier prénom d'un champ `given` = 1er segment séparé par ESPACE.
    'Jean Baptiste Marie' -> 'Jean' ; 'Jean-Marie Claude' -> 'Jean-Marie'
    (le composé à tiret est conservé tel quel pour l'essai composé)."""

class GenderInference(BaseModel):
    sex: str | None        # "M" | "F" | None (abstention)
    ratio: float           # dominant / total (0.0 si total == 0)
    total: int             # n_f + n_m sur la clé retenue
    key: str               # clé effectivement trouvée (ou "" si aucune)

def infer_sex(given: str, table: Mapping[str, tuple[int, int]]) -> GenderInference:
    """1) clé = _normkey(_first_forename(given));
    2) si absente et composée à tiret -> réessaie avec le 1er segment de tiret;
    3) total = n_f+n_m; dominant = 'F' si n_f>=n_m sinon 'M';
    4) propose ssi total>=MIN_TOTAL et dominant/total>=MIN_RATIO; sinon sex=None."""
```

**Gestion des prénoms composés** (`Jean-Marie`, `Marie-Claude`) : essai du **composé entier**
d'abord (l'INSEE les recense souvent comme `PREUSUEL` distincts) ; si absent, repli sur le **1er
segment de tiret**. Pas de combinaison inter-tokens (source de faux positifs). Si le repli n'est
pas tranchable → abstention. Conforme à la politique conservatrice.

### 4.3 Modèle `Proposition` (nouveau — dans `models/domain.py`)

Premier émetteur de propositions ; établit le contrat réutilisé par les futurs chantiers
(lieux, dates, fiabilisation).

```python
class Proposition(BaseModel):
    type: str            # "genre_inconnu" | "genre_contradiction"
    gramps_id: str
    handle: str
    personne: str        # nom lisible
    champ: str           # "gender"
    valeur_actuelle: str # "U" | "M" | "F"
    valeur_proposee: str # "M" | "F"
    preuve: str          # ex. "prénom « SUZANNE » : 99,7% F sur 41 230 (INSEE+OFS)"
    confiance: str       # "haute" (ratio>=0.99) | "moyenne" (0.95<=ratio<0.99)
    priorite: str        # "haute" (contradiction) | "moyenne" (inconnu)
```

### 4.4 Orchestration (dans `genecrew`)

**`genecrew/src/genecrew/gender.py`**

- `run_gender(client, scope, output_dir, *, date, limit=None) -> tuple[Path, Path]`
  - réutilise `parse_scope` / `resolve_handles` (scope.py), `iter_people_batches` (batching.py),
    `FactsFetcher` (facts.py). `PersonFacts` porte déjà `given` et `sex` — pas de nouvel appel API.
  - pour chaque personne : `inf = infer_sex(p.given, table)`.
    - `p.sex == "U"` et `inf.sex` non nul → `Proposition(type="genre_inconnu", …)`.
    - `p.sex in {"M","F"}` et `inf.sex` non nul et `inf.sex != p.sex` →
      `Proposition(type="genre_contradiction", …)`.
    - sinon, si `inf.sex is None` et `p.sex == "U"` → ajouté à la liste **indécidables**.
  - écrit deux fichiers dans `output/inference/` : `genres-<scope>-<date>.md` et
    `propositions-genre-<scope>-<date>.yaml`.
- **Rendu pur** (pas d'I/O), comme `report.py`/`names.py` :
  - `render_gender_report(scope, date, propositions, indecidables, people_count, base_url) -> str`
    — synthèse + tableau des propositions trié par priorité (IDs cliquables `…/person/<id>`) +
    section « Indécidables » (prénom, pourquoi : unisexe / rare / non couvert).
  - `render_propositions_yaml(propositions) -> str` — sérialisation YAML de `list[Proposition]`.

### 4.5 CLI

Sous-commande **`genecrew gender [--scope all|…] [--limit N]`** dans `main.py`.
**Pas de `--dry-run`** : la commande est en lecture seule par nature (aucune écriture possible).

## 5. Flux de données

```
Gramps API (lecture) --FactsFetcher--> PersonFacts(given, sex)
                                          |
prenoms_sexe.csv --load_prenoms_table--> infer_sex(given) -> GenderInference
                                          |
                        classement (inconnu / contradiction / indécidable)
                                          |
                         list[Proposition] + list[indécidables]
                                          |
                 render_gender_report (.md) + render_propositions_yaml (.yaml)
```

## 6. Gestion d'erreur

- Personne sans prénom (`given == ""`) → `infer_sex` retourne abstention ; **non** listée en
  indécidable (rien à inférer), simplement ignorée.
- Prénom non couvert par la table → abstention (indécidable si `gender=2`).
- CSV embarqué illisible/absent → `load_prenoms_table` lève une erreur explicite au démarrage de
  la commande (échec franc, pas de dégradation silencieuse).
- `FactsFetcher` : 404 par personne déjà géré (log + skip), réutilisé tel quel.

## 7. Tests

### 7.1 Fonctions pures (`crewai_custom_tools`)

- `_normkey` : accents, casse, apostrophe/tiret Unicode.
- `infer_sex` (table de cas, avec une petite table de test en dur) :
  - masculin net (`Pierre`), féminin net (`Suzanne`) → proposition ;
  - unisexe (`Dominique` ~50/50) → abstention ;
  - volume < 50 → abstention même si ratio 100 % ;
  - ratio entre 80 % et 95 % → abstention (politique conservatrice) ;
  - composé présent (`Jean-Pierre`) → proposition ; composé absent → repli 1er segment ;
  - `given` multi-prénoms (`Jean Baptiste`) → 1er prénom ;
  - prénom vide / non couvert → abstention.

### 7.2 Orchestration (`genecrew`)

- e2e avec client httpx `MockTransport` : jeu de personnes (inconnu tranchable, inconnu unisexe,
  contradiction, genre correct) → vérifie le contenu des propositions et de la liste indécidables.
- **Garantie lecture seule** : le handler du mock **lève `AssertionError` sur tout PUT/POST** ;
  le test passe donc uniquement si `run_gender` n'écrit rien (analogue au test des noms incomplets).
- Rendu : `render_gender_report` contient les bons IDs cliquables et les sections attendues ;
  `render_propositions_yaml` reparse en `list[Proposition]` identiques (round-trip).

## 8. Fichiers touchés

**`crewai_custom_tools`**

- `src/crewai_custom_tools/tools/genealogy/data/prenoms_sexe.csv` (nouveau, versionné)
- `src/crewai_custom_tools/tools/genealogy/data/README.md` (nouveau, provenance)
- `scripts/build_prenoms_sexe.py` (nouveau, build one-off)
- `src/crewai_custom_tools/tools/genealogy/analysis/gender.py` (nouveau : `_normkey`,
  `load_prenoms_table`, `infer_sex`, `GenderInference`)
- `src/crewai_custom_tools/tools/genealogy/models/domain.py` (ajout `Proposition`)
- `tests/test_genealogy_gender.py` (nouveau)
- `pyproject.toml` : inclusion du fichier de données dans le wheel ; bump de version.

**`genecrew`**

- `genecrew/src/genecrew/gender.py` (nouveau : `run_gender` + rendus purs)
- `genecrew/src/genecrew/main.py` (sous-commande `gender`)
- `genecrew/tests/test_gender.py` (nouveau)
- `uv.lock` après bump de la lib.

**Docs**

- `docs/adr/0008-inference-genre-proposition.md` (ADR : le genre est un fait → proposition ;
  premier modèle `Proposition`).
- `docs/USER_GUIDE.md` : section « Inférence de genre ».

## 9. Hors périmètre (YAGNI / plus tard)

- Écriture des propositions dans Gramps (tags `ia-a-verifier`, notes) : chantier « écritures
  encadrées » ultérieur.
- Étape « apply » qui relit le YAML validé par l'humain et écrit les genres retenus.
- Prénoms hors FR/CH (autres pays) : abstention assumée.
- Inférence à partir des relations familiales (père/mère/épouse) plutôt que du prénom.

## Sources

- [INSEE — Fichier des prénoms](https://www.insee.fr/fr/statistiques/8595130)
- [data.gouv.fr — Fichier des prénoms depuis 1900](https://www.data.gouv.fr/datasets/fichier-des-prenoms-depuis-1900)
- [OFS/BFS — Prénoms des nouveau-nés](https://www.bfs.admin.ch/bfs/fr/home/statistiques/population/naissances-deces/prenoms-nouveaux-nes.html)
- [opendata.swiss — Office fédéral de la statistique](https://opendata.swiss/fr/organization/bundesamt-fur-statistik-bfs)
