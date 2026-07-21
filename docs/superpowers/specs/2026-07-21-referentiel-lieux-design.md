# Référentiel des subdivisions administratives (`propose` / `apply referentiel`)

> Conception validée le 2026-07-21. Nouveau chantier du domaine lieux : peupler l'arbre avec les
> pays et leurs subdivisions administratives — coordonnées, identité Wikidata et article
> Wikipédia compris — pour que les communes aient un contenant identifié où se rattacher.

## 1. Contexte

Le cas déclencheur est la constatation qu'**aucun canton suisse n'existe dans l'arbre**. Vérifié :
aucun lieu de type `Canton` ni `State`, aucun lieu nommé `Vaud`, `Berne`, `Genève`. Le mot « Vaud »
n'apparaît que dans le *titre* texte des communes et dans des notes MyHeritage importées.

L'enquête a établi deux problèmes distincts, qui se ressemblent mais n'ont pas la même cause.

### 1.1 Le parseur ne détecte pas la Suisse

`place.name.value` de `P0001` vaut `Montreux (VD)` : une seule chaîne, aucune virgule.
`parse_pname` (`standardize/places.py:48`) déduit le pays du **dernier segment séparé par
virgule**. Le seul segment est `Montreux (VD)`, inconnu de la table `_COUNTRY`, donc la règle de
repli (`places.py:94`) le rebascule en commune et laisse `country=''`.

Conséquence en cascade : `registry.resolve_place` ne trouve pas de résolveur pour `''`, tombe sur
Nominatim monde, qui ne rend **aucun niveau parent**. `resolve_ch` — le seul qui sache poser
`Suisse › Canton › Commune`, table des 26 cantons comprise (`geo/suisse.py:22-29`) — n'est
**jamais appelé**. Sortie observée sur `P0001` :

```yaml
country: ''
resolution:
  chains:
  - levels: []          # aucune hiérarchie
  source: Nominatim/OSM
  score: 0.7619         # le « (VD) » resté dans la requête dégrade aussi le score
```

Sur les 25 lieux suisses de l'arbre, **19 portent la forme `Commune (XX)`** et sont donc cassés
(Berne 9, Vaud 7, Genève 1, Thurgovie 1, Argovie 1) ; les 6 autres sont à plat avec un segment
`Switzerland` final, que `_COUNTRY` normalise correctement en `Suisse`.

### 1.2 L'arbre n'a pas de référentiel de contenants

Inventaire au 2026-07-21, sur 304 lieux :

| Type | Nombre | Observations |
|---|---|---|
| `Municipality` | 175 | |
| `Unknown` | 56 | non typés |
| `Department` | 38 | code INSEE nu (`03`, `31`), **aucun GPS** |
| `Region` | 12 | code INSEE nu (`28`, `93`), **aucun GPS** |
| `Wilaya` | 5 | seul type personnalisé de l'arbre, 2 GPS sur 5 |
| `State` | 4 | Länder allemands, sans code ni GPS |
| `Country` | 6 → 5 | **France en double**, GPS seulement sur la Syrie |
| autres | 8 | `City`, `Building`, `County`, `Locality` |

Deux manques structurants : **presque aucun contenant n'a de coordonnées**, et des pays présents
dans les noms de lieux n'existent pas comme entité (États-Unis, Pologne, Belgique).

### 1.3 Le doublon France, et ce qu'il apprend

Deux `Country` nommés `France`, rigoureusement identiques (titre, code, GPS, `alt_names` tous
vides), créés à un jour d'écart, avec la hiérarchie coupée en deux : 15 enfants sous `P0295`
(les régions), 1 seul sous `P0386` (Apremont-la-Forêt). L'utilisateur a supprimé `P0386` le
2026-07-21.

Le mécanisme de création du doublon **n'a pas été prouvé** : la pagination a été écartée (304
lieux, aucun perdu entre les pages) et les deux seuls points de création partagent le même index.
Aucune cause n'est affirmée ici.

Ce qui **est** établi, en revanche, est que rien ne l'a signalé. `_seed_parent_index`
(`places_apply.py:28`) construit un dictionnaire `chemin → handle` ; deux lieux de chemin `France`
écrivent la **même clé** et le second écrase le premier sans bruit. L'index comptait 293 entrées
pour 304 lieux. **La structure qui sert à décider est celle qui rend les doublons invisibles** —
c'est une contrainte de conception pour ce chantier, pas une anecdote.

### 1.4 `enrich wiki` ne peut pas couvrir ces lieux

99 lieux sur 303 portent une URL `fr.wikipedia.org`, avec une convention établie :

```json
{"desc": "Wikipédia", "path": "https://fr.wikipedia.org/wiki/Sedrata_(Souk_Ahras)",
 "private": false, "type": "Web Home"}
```

Mais `enrich wiki` cherche l'article par **géolocalisation** : `lieux_wiki.py:85` ne retient que
les lieux ayant déjà `lat` et `long`. Les 38 départements, 12 régions et 5 pays n'en ont pas, donc
la commande ne les a jamais vus. Chercher l'article d'un département autour de son barycentre
attraperait de toute façon le village le plus proche du centroïde, pas le département.

## 2. Objectif

Deux livraisons, **dans cet ordre**.

1. **`propose` puis `apply referentiel`** — créer et compléter les pays et leurs subdivisions
   administratives (~430 entités sur 9 pays), avec coordonnées, identité Wikidata et article
   Wikipédia.
2. **Correctif `parse_pname`** — rendre `Montreux (VD)` résoluble, pour que `apply places`
   rattache les 19 communes suisses sous des cantons **déjà en place**.

L'ordre est imposé par une raison technique. `_ensure_parents` (`places_apply.py:55`) ne bloque
pas sur un parent manquant : il le **crée**, mais nu — ni GPS, ni QID, ni article. Livrer le
correctif en premier produirait un `Vaud` stub que le référentiel devrait ensuite reconnaître
**par comparaison de chaînes**, c'est-à-dire par le mécanisme fragile que tout ce design cherche à
éliminer. Dans l'ordre retenu, aucun stub n'est jamais créé.

## 3. Source de données : Wikidata, sélection par ISO 3166-2

### 3.1 Pourquoi pas une classe `P31` par niveau

Sondage effectué le 2026-07-21 sur les classes candidates :

| Classe | Trouvés | Attendu |
|---|---|---|
| `Q23058` canton suisse | 26 | 26 ✓ |
| `Q1221156` Land allemand | 16 | 16 ✓ |
| `Q35657` État américain | 50 | 50 ✓ |
| `Q36784` région française | 18 | 18 ✓ |
| `Q6465` département français | 97 | 101 |
| `Q16110` région italienne | 15 | 20 |
| `Q15089` province italienne | 85 | 107 |
| `Q192498` wilaya algérienne | 11 | 58 |
| `Q104158` province belge | 0 | 10 |
| `Q1620990` gouvernorat syrien | 0 | 14 |

Le cas rédhibitoire : **Naples et Milan ne sont pas des `provincia`**, ce sont des
*città metropolitana*, une autre classe. La sélection par `P31` raterait précisément les deux
lieux attendus pour les lignées Pagano (Napoli) et Pagani (Milano).

### 3.2 Le sélecteur retenu

L'univers est l'ensemble des entités portant un **code ISO 3166-2** du préfixe pays voulu, non
dissoutes (`P576` absent). Couverture mesurée :

| Pays | Subdivisions | avec GPS | avec article frwiki |
|---|---|---|---|
| FR | 124 | 124 | 124 |
| IT | 124 | 124 | 124 |
| DZ | 58 | 58 | 58 |
| US | 56 | 56 | 56 |
| CH | 26 | 26 | 26 |
| PL | 17 | 17 | 17 |
| DE | 16 | 16 | 16 |
| SY | 14 | 14 | 14 |
| BE | 13 | 13 | 13 |

**100 % de couverture, GPS et article compris**, et `IT-NA` → *ville métropolitaine de Naples*,
`IT-MI` → *ville métropolitaine de Milan* sont bien présents.

Chaque ligne rend : QID, libellé français, code ISO, centroïde `P625`, article `frwiki`
(via `schema:about` / `schema:isPartOf`), rattachement `P131`.

### 3.3 Le niveau vient du rattachement, jamais de la forme du code

Une subdivision dont le `P131` est le pays est de **niveau 1** ; celle dont le `P131` est une
subdivision de niveau 1 est de **niveau 2**. La règle donne au passage le parent à poser dans
Gramps.

Découper sur la forme du code serait un piège : en France les régions sont alphabétiques
(`FR-ARA`) et les départements numériques (`FR-01`) ; **en Italie c'est l'inverse** — `IT-25` est
la Lombardie, `IT-NA` est Naples.

### 3.4 Filtrage du bruit

Des entités parasites portent un `P300` : `montagne`, `position géographique`,
`circonscription électorale`, une ville isolée en Pologne. Le filtre est une **liste d'exclusion**
sur `P31`, jamais une liste d'inclusion — l'inclusion aurait raté les villes métropolitaines
italiennes, c'est-à-dire l'erreur qu'on vient d'écarter en 3.1.

## 4. Types Gramps : natifs uniquement

Types natifs de Gramps (relevés sur `/types/default/place_types`) : `Unknown`, `Country`, `State`,
`County`, `City`, `Parish`, `Locality`, `Street`, `Province`, `Region`, `Department`,
`Neighborhood`, `District`, `Borough`, `Municipality`, `Town`, `Village`, `Hamlet`, `Farm`,
`Building`, `Number`. Types personnalisés de l'arbre : `['Wilaya']`, et un seul.

Ni `Canton` ni `Wilaya` ne sont natifs. **Aucun type personnalisé nouveau ne sera créé.**

| Pays | Niveau 1 | Niveau 2 |
|---|---|---|
| France | `Region` (18 + les collectivités d'outre-mer) | `Department` (101) |
| Italie | `Region` (20) | `Province` (104, villes métropolitaines comprises) |
| Belgique | `Region` (3) | `Province` (10) |
| Suisse | `State` (26) | — |
| Allemagne | `State` (16) | — |
| États-Unis | `State` (56, DC et territoires compris) | — |
| Algérie | `Province` (58) | — |
| Pologne | `Region` (16) | — |
| Syrie | `Province` (14) | — |

Les comptes de ce tableau sont ceux **après** filtrage du bruit (§3.4) et peuvent donc être
inférieurs aux totaux ISO du §3.2. Deux écarts connus : la France compte 124 entrées ISO pour
18 régions et 101 départements, le reliquat étant les **collectivités d'outre-mer**, rattachées
directement au pays par `P131` et donc traitées en niveau 1 (`Region`) ; la Pologne compte 17
entrées ISO pour 16 voïvodies, la dernière étant une ville isolée qu'exclut le filtre.

Règle sous-jacente : `State` quand l'entité est un État fédéré d'une fédération (Suisse,
Allemagne, États-Unis) ; `Region` / `Department` / `Province` par profondeur dans les États
unitaires.

Raison du choix : le coût d'un type personnalisé n'est pas sa création, c'est que **tout filtre par
type doit le connaître**. Le CLAUDE.md documente déjà le risque pour les décès — `TYPES_LIEU_DECES`
est une liste d'*inclusion*, et un contenant oublié rattacherait un décès à un département en
silence. Chaque type vernaculaire supplémentaire est une occasion de plus d'oublier une ligne, avec
une erreur muette au bout.

Deux conséquences assumées :

- **`geo/suisse.py:61` change** : `place_type="Canton"` devient `"State"`. La mention de `Canton`
  dans la mise en garde « Créer un décès » du CLAUDE.md est à corriger. `TYPES_LIEU_DECES` n'est
  pas touché : il n'inclut que `Municipality` et `City`.
- **Les 5 `Wilaya` existants sont retypés en `Province`**, en écriture directe. C'est la seule
  écriture destructive du lot. Justification : un `place_type` n'est pas une donnée saisie avec une
  intention généalogique, c'est une étiquette de structure — même famille que la casse des noms,
  que le projet autorise déjà en écriture directe. Cinq lieux, réversible d'un run.

## 5. Ce qui est écrit en base

### 5.1 Champs

| Champ | Contenu | Règle d'écriture |
|---|---|---|
| `name.value` | libellé français Wikidata | **création seulement** — un nom existant n'est jamais réécrit |
| `place_type` | table §4 | création, **plus** le retypage des 5 wilayas |
| `code` | code ISO amputé du préfixe pays | posé si vide, jamais écrasé |
| `lat` / `long` | `P625`, WGS84 décimal | posé si vide, jamais écrasé |
| `urls` | QID Wikidata + article `frwiki` | ajout, jamais de suppression |
| `alt_names` | libellé français si ≠ nom existant | ajout |
| `placeref_list` | parent = pays ou subdivision de niveau 1 | posé si absent |

**L'amputation du préfixe reproduit la convention déjà en base** : `FR-03` → `03`, le code de
l'Allier ; `DZ-41` → `41`, celui de Souk Ahras ; `CH-VD` → `VD` ; `IT-NA` → `NA`.

Exception assumée : les régions françaises portent en base leur code INSEE (`28` pour la
Normandie) là où l'ISO donne `NOR`. Comme un code existant n'est jamais écrasé, les 12 régions
gardent le leur ; seule une région nouvelle arriverait en `NOR`. Incohérence réelle, bornée à
douze lieux déjà corrects.

**Noms et langues.** Un nom existant n'est jamais réécrit : `Bayern` reste `Bayern`, et `Bavière`
rejoint ses `alt_names`. Conséquence à documenter dans l'ADR : les `alt_names` porteront désormais
**deux sens** — variante historique d'un lieu *et* traduction — et une relecture doit savoir
lequel elle regarde.

**Article Wikipédia posé par `apply referentiel` lui-même**, depuis le sitelink de la même requête
SPARQL, sans passer par `enrich wiki` (§1.4), en suivant la convention de `urls` déjà en base
(`desc: "Wikipédia"`, `type: "Web Home"`). Le QID prend une seconde entrée, `desc: "Wikidata"`.

En posant le GPS sur ~430 subdivisions, `apply referentiel` les rend **éligibles au passage suivant
d'`enrich wiki`**. L'ADR doit dire qui pose quoi, sinon les deux commandes se marcheront dessus.

### 5.2 Pays

L'arbre n'a que 5 `Country`, aucun avec GPS sauf la Syrie. `apply referentiel` crée les manquants —
Italie, États-Unis, Pologne, Belgique — et complète les cinq autres : centroïde, code ISO 3166-1
alpha-2, QID, article.

### 5.3 Appariement

Dans cet ordre : **QID** trouvé dans les `urls` ; sinon **nom + type sous le même parent** ; sinon
**code**. Le QID est posé au premier passage, donc dès le second run l'identité ne dépend plus des
chaînes — c'est ce qui règle `Bayern` contre `Bavière` sans rien renommer.

### 5.4 Doublons : signalés, jamais fusionnés

`propose referentiel` rend une section « doublons » listant les lieux partageant nom + type +
parent. Aucune écriture n'est faite sur eux. La fusion reste manuelle, via `merge places` : rien ne
prouve lequel des deux enregistrements porte la vérité, et `Person.merge()` a déjà appris au projet
ce que coûte une fusion irréversible.

### 5.5 Invariant

Toute écriture est **une création, le remplissage d'un champ vide, ou un ajout dans une liste** —
à la seule exception du retypage des 5 wilayas (§4). Aucun autre chemin de code ne réécrit une
valeur existante. C'est cet invariant qui autorise `apply referentiel` à écrire directement, sans
le détour par la relecture qu'impose une donnée cœur comme `apply deaths`.

## 6. Grammaire CLI

Deux feuilles sous des verbes existants, **aucun verbe nouveau** : l'ADR 0012 fige sept verbes et
pose que toute nouveauté est une feuille.

```bash
uv run genecrew propose referentiel --country FR,CH        # lecture seule : rapport + YAML
uv run genecrew apply referentiel --yaml <relu.yaml> --dry-run
```

Le nom `referentiel` a été préféré à `init` parce que la fonction **n'est pas une installation
unique** : elle se relance à chaque pays nouveau dans l'arbre — l'Italie d'abord, puis les
suivants. `init` suggérait un one-shot de démarrage.

`apply referentiel` **consomme le YAML relu et ne réinterroge pas Wikidata**, comme `apply deaths`
et `merge places`. C'est ce qui rend l'écriture reproductible : Wikidata bouge entre deux appels,
et il serait absurde d'écrire autre chose que ce qui a été relu. Cet argument est ce qui rendait
Wikidata acceptable en §3 ; il doit être tenu ici.

## 7. Découpage et dépôts

Règle du projet : la logique généalogique vit dans `crewai_custom_tools`, genecrew ne garde que
l'orchestration et la CLI.

**Dans `crewai_custom_tools`** — paquet `genealogy/referentiel/` :

- `config.py` — table des 9 pays : préfixe ISO, type Gramps par niveau, liste d'exclusion `P31`.
  Données pures, aucun appel.
- `wikidata.py` — construction de la requête SPARQL et **mapper pur** `payload → list[Subdivision]`
  (niveau par `P131`, amputation du préfixe ISO, filtrage du bruit). Le réseau est isolé dans une
  seule fonction, exactement le découpage `map_swiss` / `resolve_ch` (`geo/suisse.py:49` et `:72`),
  qui rend le mapper testable hors ligne.
- `models/domain.py` — modèle `Subdivision` : `qid`, `iso`, `libelle_fr`, `place_type`, `lat`,
  `long`, `parent_qid`, `frwiki`, `niveau`.
- correctif `geo/suisse.py:61` — `"Canton"` → `"State"`.
- correctif `standardize/places.py` — la règle §8.

**Dans genecrew** :

- `cli.py` — feuilles `propose referentiel` et `apply referentiel`, drapeau `--country FR,CH`.
- `referentiel.py` — le `propose` : interroge les pays, rend le rapport Markdown et le YAML, avec
  la section doublons. Lecture seule.
- `referentiel_apply.py` — le `apply` : indexe l'arbre, apparie (§5.3), crée ou complète, retype
  les 5 wilayas, écrit le rapport.
- `main.py` — routage des deux couples `(commande, cible)`.

**Ordre de livraison inter-dépôts** : la CI checkoute le voisin sur le **tag** `v<version>` lu dans
`uv.lock`. La bibliothèque part donc d'abord — bump, tag, push — avant que la CI de genecrew puisse
verdir. Les deux correctifs de bibliothèque (§4 et §8) tiennent dans un seul bump.

## 8. Correctif `parse_pname` (livraison 2)

Règle : un nom **sans virgule** portant en suffixe `(XX)` où `XX` est l'un des 26 codes cantonaux
⇒ `country="Suisse"`, `commune` = le nom amputé du suffixe.

La condition « sans virgule » est le garde-fou : `(XX)` en suffixe existe ailleurs (`(NY)`,
`(BW)`), et des codes comme `GE`, `BE`, `JU` sont des chaînes courtes. Un nom à virgules a déjà un
segment pays exploitable et n'a pas besoin de cette règle.

La table des 26 codes et la fonction de découpe existent déjà — `_CANTONS` et `_split_label`
(`geo/suisse.py:21-39`) — et doivent être réutilisées, pas dupliquées.

Effet attendu : `parse_pname("Montreux (VD)")` → `commune="Montreux"`, `country="Suisse"` ; puis
`resolve_ch` rend `Suisse › Vaud › Montreux` avec un score de 1.0 au lieu de 0.762, le `(VD)`
n'étant plus dans la requête.

## 9. Tests et gestion d'erreur

**Testable hors ligne, sans un seul appel** : la table de config, la construction de la requête
SPARQL, le mapper `payload → Subdivision`, l'affectation du niveau par `P131`, l'amputation du
préfixe ISO, le filtre d'exclusion, la logique d'appariement, le rendu des rapports, et la règle
§8. Le réseau se limite à deux points — le GET SPARQL et les lectures/écritures Gramps.

**Jeux d'essai figés** : une charge SPARQL réelle par pays, capturée et versionnée. Elle doit
contenir les cas qui ont fait basculer le design — `IT-NA` en ville métropolitaine, `IT-25`
numérique face à `FR-01` numérique de l'autre niveau, une entité parasite à exclure, une
subdivision sans code national propre.

**Cas d'appariement à couvrir** : QID déjà posé ; nom identique mais langue différente (`Bayern`
contre `Bavière`) ; deux lieux de même nom et même type sous le même parent, qui doivent produire
un signalement et **aucune écriture** ; un lieu avec GPS déjà rempli, qui ne doit pas bouger.

**Cas `parse_pname` à couvrir** : `Montreux (VD)` ; `Genève (GE)` ; un nom à virgules avec suffixe,
qui ne doit **pas** déclencher la règle ; un suffixe à deux lettres hors table (`Springfield (NY)`),
qui doit rester non suisse.

**Erreurs réseau.** Wikidata a rendu un 502 dès le second pays pendant les sondages de conception —
ce n'est pas hypothétique. Un pays en échec après reprises devient un pays **absent du rapport et
signalé comme tel** ; les autres sont livrés. Un seul point de sortie muet ne doit pas faire tomber
le lot, exactement comme `build_proposition` (`places.py:33`) capture déjà l'erreur de géocodage
lieu par lieu.

**Temporisation.** Les appels passent par `get_rate_limiter()`, déjà utilisé par les résolveurs
`geo/`, avec un `User-Agent` identifiant le projet — Wikidata bloque les clients anonymes.

**Simulation par défaut.** `apply referentiel` passe par `effective_dry_run`, et son rapport porte
le mode dans son nom, comme `apply deaths` : `…_simulation.md` contre `…_ecritures.md`, pour que
l'écriture n'écrase pas l'aperçu qui l'a autorisée.

## 10. Hors périmètre

- **La fusion des doublons détectés** : signalés seulement (§5.4), traités par `merge places`.
- **Les 56 lieux `Unknown`** : leur typage est un chantier distinct.
- **`Region: Algérie française`** et ses départements historiques : entité disparue, sans
  équivalent comme subdivision actuelle dans Wikidata. Laissée intacte.
- **Le troisième niveau** (arrondissements, districts) : ~430 subdivisions pour 175 communes
  réellement utilisées suffisent ; descendre plus bas noierait la vue Lieux.
- **Le rattachement des communes non suisses** aux subdivisions nouvelles : c'est le travail
  d'`apply places`, hors de ce lot sauf pour les 19 communes suisses (§8).
