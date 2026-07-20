# Résolveur des ex-communes françaises (communes associées / déléguées)

> Conception validée le 2026-07-20. Extension du chantier lieux GeneCrew, dans le prolongement
> du **résolveur France par nom**. Objectif : résoudre de façon **autoritaire** les communes
> françaises **fusionnées** (loi Marcellin de 1971 et fusions ultérieures), aujourd'hui invisibles
> pour `resolve_fr` et donc dégradées en proposition Nominatim sans hiérarchie.

## 1. Contexte

Le cas déclencheur est le lieu `P0080` de l'arbre : un lieu plat de titre

```
, , , Saint-Agnant-sous-les-Côtes, 55012, Meuse, Grand Est, France
```

référencé par un seul événement, `E1820` — le **décès de Kléber Soulat le 26/09/1914**, appuyé
par la fiche Mémoire des hommes `C1789`.

Saint-Agnant-sous-les-Côtes a été **fusionnée en 1973** dans Apremont-la-Forêt, dont elle est
depuis *commune associée*. Deux conséquences mesurées :

1. `resolve_fr` interroge `geo.api.gouv.fr/communes`, où la commune **n'existe plus**.
   `_resolve_fr_by_name` ne trouve aucune correspondance exacte et rend `None`. Le registre
   bascule sur Nominatim/OSM, qui trouve bien le point mais ne rend qu'une chaîne
   `France > Saint-Agnant-sous-les-Côtes` — **hiérarchie perdue** — et lève `ambiguous`.
   Résultat observé : `import place` → `proposition (confiance basse)`, aucune écriture.
2. Le champ `code` du lieu est **vide** (vérifié en base). Le `55012` visible dans le titre est
celui d'**Apremont-la-Forêt**, pas celui de Saint-Agnant (**55451**), et le parseur le range
en `postal`. Il n'y a donc pas de code erroné à écraser, mais un code absent à renseigner.

`transitions.py` ne couvre que les transitions de **souveraineté entre pays** ; il n'a aucune
prise sur les fusions de communes.

**Le trou n'est pas isolé** : `geo.api.gouv.fr` recense **66 ex-communes pour la seule Meuse**.

### Vérification rassurante sur le code faux

`parse_pname` range `55012` dans `postal`, **pas** dans `insee` :

```python
{'commune': 'Saint-Agnant-sous-les-Côtes', 'insee': None, 'postal': '55012',
 'departement': 'Meuse', 'region': 'Grand Est', 'country': 'France', 'shifted': True}
```

Le chemin `parsed.insee → /communes/55012` n'est donc **pas** emprunté, et le résolveur ne
risque pas de renommer le lieu en « Apremont-la-Forêt ». Le correctif peut se loger en aval
sans neutraliser ce piège au préalable.

## 2. Sources de données (vérifiées en direct le 2026-07-20)

### `geo.api.gouv.fr/communes_associees_deleguees`

```
GET /communes_associees_deleguees/55451?fields=nom,code,type,chefLieu,centre,departement,region
→ {"nom":"Saint-Agnant-sous-les-Côtes","code":"55451","type":"commune-associee",
   "chefLieu":"55012","centre":{"coordinates":[5.6317,48.8427]},
   "departement":{"code":"55","nom":"Meuse"},"region":{"code":"44","nom":"Grand Est"}}
```

Donne le **rattachement** (`chefLieu`) et le **code INSEE propre**. La recherche par `nom` est
également disponible. **Ne donne aucune date de fusion.**

### Wikidata (`Q25398054`, « former commune in France »)

| Propriété | Valeur | Usage |
|---|---|---|
| `P576` date de dissolution | `+1972-12-31`, **précision 11 (jour)** | qualificatif des placerefs |
| `P1366` remplacé par | `Q286407` (Apremont-la-Forêt) | recoupement du successeur |
| `P374` code INSEE | `55451` | recoupement de l'identité |
| `P625` coordonnées | `48.842142, 5.622588` | GPS retenu (cf. §5) |

La précision **jour** de `P576` est structurante : `date_qualifier_to_gramps_date` exige un
`YYYY-MM-DD` complet et fonctionne donc **sans retouche**. Aucun relâchement du convertisseur.

#### Interrogation : SPARQL par code INSEE (validée en direct)

`tools/web/wikidata.py` expose déjà un `WikidataSparqlTool` sur l'endpoint public. On interroge
**par `P374`**, pas par nom — le code est l'identité, la recherche par libellé rendait deux
entités concurrentes (`Q25398054` et `Q112864538`).

```sparql
SELECT ?item ?dissolved ?succInsee ?coord WHERE {
  ?item wdt:P374 "55451" .
  OPTIONAL { ?item wdt:P576 ?dissolved }
  OPTIONAL { ?item wdt:P1366 ?succ . ?succ wdt:P374 ?succInsee }
  OPTIONAL { ?item wdt:P625 ?coord }
} LIMIT 10
```

Réponse mesurée — **une seule ligne**, ce qui rend la résolution déterministe :

```
item=Q25398054  dissolved=1972-12-31T00:00:00Z  succInsee=55012
coord=Point(5.622588 48.842142)
```

Deux conséquences pour l'implémentation :

- `succInsee` sort **directement** de la requête : la garde de recoupement (§6.1) se résout en
  un seul appel réseau, sans second aller-retour pour déréférencer `P1366`.
- **`P625` sort en WKT `Point(lon lat)` — longitude d'abord**, comme GeoJSON. Le parser doit
  inverser. C'est exactement le piège déjà consigné pour les coordonnées du projet ; s'y laisser
  prendre placerait le lieu au large de la Somalie.
- Plus d'une ligne (plusieurs entités partageant un `P374`) → traité comme une **ambiguïté** :
  pas de datation, chaîne unique non datée.

> Nota : l'infobox Wikipédia affiche « Fusion 1973 » tandis que Wikidata date la dissolution au
> 1972-12-31 — l'arrêté prenant effet au 1er janvier 1973. Les deux sont cohérents ; on retient
> la date Wikidata, plus précise et directement exploitable.

## 3. La couche d'écriture n'a besoin de rien

Vérifié dans le code : `run_places_apply` construit déjà un `placeref_list` **multi-chaînes**
avec un `_date_qualifier` par chaîne (`places_apply.py:131-137`), et `GrampsUpdatePlaceTool`
convertit chaque `_date_qualifier` en objet `Date` Gramps avec son `modifier`
(`write_tools.py:270-278`).

**Aucun changement côté writer.** Tout le correctif est dans le résolveur.

## 4. Décisions actées (avec l'utilisateur)

1. **Modélisation par placerefs datées.** Le lieu porte **deux** rattachements datés plutôt
   qu'un seul. Le décès de 1914 est antérieur à la fusion de 1973 : rattacher purement et
   simplement Saint-Agnant à Apremont-la-Forêt ferait mourir le soldat dans une commune qui
   n'existait pas encore. C'est le modèle natif de Gramps, et celui que `transitions.py`
   applique déjà aux pays.

   ```
   France (Country)
   └─ Grand Est (Region, 44)
      └─ Meuse (Department, 55)
         ├─ [placeref : avant 1972-12-31]
         │  └─ Saint-Agnant-sous-les-Côtes (Municipality, 55451)
         └─ Apremont-la-Forêt (Municipality, 55012)
            └─ [placeref : après 1972-12-31]
               └─ Saint-Agnant-sous-les-Côtes   ← même lieu, 2ᵉ référence
   ```

2. **Garde de recoupement à deux sources** (cf. §6) — on ne date jamais sur une source seule.
3. **GPS Wikidata** pour les ex-communes, par exception documentée (cf. §5).
4. **Nom canonique** `Saint-Agnant-sous-les-Côtes` ; l'ancien titre plat est conservé en
   `alt_name` (comportement actuel de `run_places_apply`, rien à ajouter).
5. Périmètre : un module de résolution dans `crewai_custom_tools`, un scope dans `genecrew`.
   Aucun changement de contrat d'écriture.

## 5. Choix du GPS (exception assumée)

Les deux sources divergent d'environ **700 m en longitude** :

| Source | Latitude | Longitude |
|---|---|---|
| `geo.api.gouv.fr` `centre` | 48.8427 | **5.6317** |
| Wikidata `P625` | 48.842142 | **5.622588** |
| Nominatim/OSM | 48.8427464 | 5.6227392 |
| Infobox Wikipédia (48°50′32″N, 5°37′21″E) | 48.84222 | 5.62250 |

Trois sources sur quatre convergent autour de `5.6225` : c'est le **centre du village**.
La valeur de `geo.api.gouv.fr` est le **centroïde du territoire communal**, seule à l'écart.

En généalogie on veut l'église et le bourg — le lieu où les actes ont été dressés — pas le
barycentre cadastral. On retient donc **`P625`** pour les ex-communes. C'est une **exception à
`map_commune`**, qui prend systématiquement le `centre` de l'API pour les communes vivantes ;
elle doit être commentée comme telle dans le code, sans quoi elle passera pour une incohérence.

## 6. Le nouveau module `geo/france_ex_communes.py`

Module séparé plutôt qu'extension de `france.py` (82 lignes, un propos unique : les communes
vivantes). Frontière nette : entrée `ParsedPlace`, sortie `ResolvedPlace | None`, aucun état.

```
resolve_fr_ex_commune(parsed) -> ResolvedPlace | None

  1. GET /communes_associees_deleguees?nom=<commune>&fields=…
     Filtre sur correspondance de nom EXACTE (même règle `_norm` que `_resolve_fr_by_name`),
     désambiguïsée par `departement` / `region` du ParsedPlace.
        0 candidat   -> None            (le registre poursuit vers Nominatim)
        >1 après filtre -> ambiguous=True (proposition, jamais d'écriture)

  2. GET /communes/{chefLieu} -> réutilise `map_commune()` pour obtenir la hiérarchie
     moderne complète (France > Région > Département > chef-lieu).

  3. SPARQL Wikidata par code INSEE (§2) -> une ligne : dissolution, INSEE du successeur,
     GPS en WKT (lon lat -> à inverser). Zéro ligne ou plus d'une -> pas de datation.

  4. Garde de recoupement (§6.1).

  5. Émission de deux DatedChain (§6.2).
```

Branchement dans `resolve_fr` : **après** l'échec de `_resolve_fr_by_name`, **avant** le repli
Nominatim du registre. L'ordre est structurant — une commune vivante ne doit jamais emprunter
ce chemin.

### 6.1 Garde de recoupement

**On ne date que si deux sources indépendantes concordent** : le `succInsee` rendu par la
requête SPARQL (le `P374` du successeur `P1366`) doit être **égal** au `chefLieu` de
`geo.api.gouv.fr`. Ici `55012 == 55012` ✓ — les deux valeurs sont déjà en main, la garde ne
coûte aucun appel réseau supplémentaire.

En cas de **désaccord**, ou de **`P576` absent** :

- une **seule** chaîne, **non datée**, portant le rattachement actuel ;
- l'ex-commune reste identifiée par son nom et son code propre, plus l'`alt_name` ;
- **aucune date inventée**.

C'est la transposition aux lieux de la discipline déjà retenue pour le rapprochement nominatif :
un facteur isolé ne tranche pas. Une date de fusion fausse est pire qu'une date absente, parce
qu'elle route silencieusement les événements vers la mauvaise branche de la hiérarchie.

### 6.2 Les deux chaînes émises

| Chaîne | `date_qualifier` | `levels` |
|---|---|---|
| historique | `avant 1972-12-31` | France, Grand Est, Meuse |
| moderne | `après 1972-12-31` | France, Grand Est, Meuse, Apremont-la-Forêt |

Le `ResolvedPlace` porte par ailleurs : `name` = `Saint-Agnant-sous-les-Côtes`,
`place_type` = `Municipality`, `code` = `55451`, GPS = `P625`, `score` = `1.0`,
`source` = `geo.api.gouv.fr + Wikidata`.

Le contrat de `chains` est respecté : **les niveaux sont les parents seuls**, la feuille vit
dans `name`/`code`/GPS — même lecture que `places_apply` et `lieu_import`.

## 7. Ajout `genecrew` : scope `place:<ID>`

`iter_places` refuse aujourd'hui tout ce qui n'est pas `--scope all`
(`batching.py:39-42`), ce qui interdit de valider le correctif sur un lieu avant de le lâcher
sur l'arbre entier.

- `parse_scope` accepte `place:<gramps_id>` en plus de `all` / `person:` / `branch:` ;
- `iter_places` le résout par `GET /places/?gramps_id=<ID>` et rend un lot unique ;
- les autres appelants de `parse_scope` (personnes) sont inchangés — `place:` leur reste
  invalide, comme `person:` l'est pour les lieux.

## 8. Résultat attendu sur `P0080`

`genecrew apply places --scope place:P0080`, en dry-run puis en écriture :

- renomme le lieu en `Saint-Agnant-sous-les-Côtes` ;
- pose `place_type = Municipality` ;
- renseigne le code **55451**, jusqu'ici **vide** ;
- écrit le GPS `48.842142 / 5.622588` ;
- crée les parents manquants (France, Grand Est, Meuse, Apremont-la-Forêt) — l'arbre n'en
  contient aucun aujourd'hui ;
- attache les **deux placerefs datées** ;
- conserve l'ancien titre plat en `alt_name`.

**`E1820` reste rattaché au même handle** : c'est un enrichissement sur place
(`GrampsUpdatePlaceTool`), ni fusion ni suppression. La citation MdH `C1789` et la note `N0088`
sont donc préservées.

## 9. Tests

Suite **offline** de `crewai_custom_tools`, sur payloads enregistrés (`_http_get` monkeypatché,
patron déjà en place pour France/Suisse/Allemagne) :

1. **Cas nominal Saint-Agnant** (golden) — deux chaînes datées, `code == "55451"`,
   GPS Wikidata, `score == 1.0`, `ambiguous is False`.
2. **Filtre nom exact** — une réponse floue de l'API ne produit aucune résolution quand aucun
   nom ne correspond exactement.
3. **Homonymes** — deux ex-communes de même nom sans contexte discriminant → `ambiguous=True`,
   donc proposition.
4. **Garde de recoupement** — `P1366` désignant un successeur ≠ `chefLieu` → **une seule
   chaîne non datée**, pas d'exception.
5. **`P576` absent**, et **SPARQL rendant 0 ou >1 ligne** → une seule chaîne non datée.
6. **Inversion WKT** — `Point(5.622588 48.842142)` doit produire `lat=48.842142`,
   `long=5.622588`. Test dédié : c'est la faute la plus facile à commettre et la plus
   silencieuse, puisqu'elle rend des coordonnées parfaitement bien formées.
7. **Non-régression `resolve_fr`** — une commune vivante (ex. Bourges) ne passe pas par le
   nouveau chemin.
8. **`parse_scope('place:P0080')`** et refus de `place:` côté personnes.

## 10. Portée et livraison

| Dépôt | Changement |
|---|---|
| `crewai_custom_tools` | `geo/france_ex_communes.py` (nouveau) ; une ligne de branchement dans `resolve_fr` ; helper ex-commune dans `tools/web/wikidata.py` ; tests offline |
| `genecrew` | `parse_scope` + `iter_places` : scope `place:<ID>` ; test |

Livraison en deux temps : bump de version de la bibliothèque, puis `uv sync` à la racine de
`genecrew` pour la récupérer — conformément à la garde de cohérence lock/bibliothèque.

## 11. Hors périmètre (YAGNI)

- Le **traitement de masse** des autres lieux plats de l'arbre. Le scope `place:` existe
  précisément pour valider d'abord sur un cas ; élargir sera une décision distincte, prise en
  lisant le rapport.
- Les **communes déléguées** (communes nouvelles depuis 2015) : le même endpoint les couvre et
  le code les traitera sans distinction, mais aucun cas n'est présent dans l'arbre aujourd'hui —
  on ne construit pas de traitement spécifique tant qu'il n'y en a pas.
- Toute **retouche du convertisseur de dates** : `P576` étant en précision jour, elle serait
  sans objet.
