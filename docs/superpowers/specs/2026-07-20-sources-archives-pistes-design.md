# Sources d'archives en ligne : Wikidata, DHS, Gallica

> Conception validée le 2026-07-20. Deuxième sous-projet de la **Phase 4 — Pistes de recherche**
> (`document-de-travail.md` §6.3). Il consomme le contrat livré par
> [le contrat de consignation des pistes](2026-07-20-contrat-pistes-design.md) (cct 0.20.0) et
> l'alimente par **trois** sources d'archives. Aucune citation n'est créée : une piste n'est jamais
> un fait.
>
> **Scriptorium a été écarté** en cours de conception, sur mesure et non sur intuition : il ne
> couvre que la presse vaudoise, soit **9 personnes** de l'arbre, et son accès programmatique
> n'est pas documenté. Voir §3.4 et `docs/BACKLOG.md`.

## 1. Contexte

### 1.1 Ce qui existe déjà — et que l'inventaire initial avait manqué

Une première analyse avait conclu que Gallica et Wikidata restaient à écrire. **C'est faux**, et
l'erreur a été commitée avant d'être corrigée (`6ce585b`) : l'inventaire ne cherchait que sous
`tools/genealogy/` et tronquait ses résultats, masquant `tools/web/`. État réel :

| Source | Existant | Nature |
| --- | --- | --- |
| Gallica | `GallicaSearchTool` (`tools/web/gallica.py`, 80 l.) — SRU, `parse_sru` pure, rend titre/auteur/date/**ark** | générique |
| Wikidata | `WikidataSparqlTool` + `sparql_rows()` (`tools/web/wikidata.py`, 76 l.) | générique |
| DHS | rien | — |
| Scriptorium | rien | — |

« Générique » est le mot important : ces deux outils prennent une requête et rendent des
enregistrements. Ils ignorent tout d'une personne, de ses bornes de vie et du contrat `Piste`.

**Le chantier n'est donc pas « intégrer quatre API »** mais **« traduire des résultats d'archives
en `Piste` »** — une seule fois, avec trois alimentations.

### 1.2 Le partage actuel est incohérent

`piste_depuis_match` (MatchID → `Piste`) vit dans **genecrew** (`deces.py:247`), alors que le
docstring de `Piste` énonce l'intention inverse :

> « La règle vit ici, à côté du modèle, pour que toute source de cette bibliothèque (MatchID
> aujourd'hui, Gallica/Wikidata demain) puisse l'invoquer sans dépendre de l'application
> appelante. »

C'est `piste_depuis_match` qui est l'anomalie — écrit avant l'extraction du contrat. Ce
sous-projet la corrige plutôt que de la dupliquer.

### 1.3 Les pistes de presse seront « faibles », et c'est correct

`Piste.force` vaut `forte` s'il y a **au moins deux facteurs de concordance distincts et aucune
divergence**. Une occurrence dans un journal donne le nom, parfois le lieu — jamais une date
complète d'état civil. Gallica produira donc presque exclusivement des pistes
faibles.

**Décision** : la presse ne sert pas à *retrouver* une personne mais à *contextualiser* une
personne **déjà identifiée**. On n'interroge Gallica que pour des personnes dont
la date et le lieu sont connus, et ces bornes filtrent les résultats. Volume faible, valeur haute.
Cela s'écarte du §6.3 du document de travail, qui visait les personnes à lacunes ; l'écart est
assumé et documenté ici.

## 2. Architecture

### 2.1 Un paquet `pistes/` dans la bibliothèque

```
crewai_custom_tools/tools/genealogy/pistes/
  __init__.py       # ré-exports
  matchid.py        # pistes_matchid   — déménagé depuis genecrew/deces.py
  wikidata.py       # pistes_wikidata  — la seule source à pistes fortes
  dhs.py            # pistes_dhs       — projection de wikidata via P902
  gallica.py        # pistes_gallica   — presse FR, contextualisation
```

(Pas de `scriptorium.py` : la source est écartée, voir §3.4.)

**Interface commune, uniforme sur les quatre modules :**

```python
def pistes_<source>(person: PersonFacts, resultats: list[dict]) -> list[Piste]: ...
```

Ces fonctions sont **pures** : elles ne font aucun appel réseau. La collecte reste dans les outils
(`GallicaSearchTool`, `WikidataSparqlTool`, `search_deces`). Cette séparation est ce qui rend
l'ensemble testable hors-ligne, conformément à la convention de la bibliothèque.

### 2.2 Côté genecrew : trois feuilles, zéro mécanique nouvelle

Conformément à l'ADR 0012 (« une base de données ajoute une feuille sous `propose`, jamais un
verbe ») :

```
propose wikidata  |  propose dhs  |  propose gallica
```

Chaque feuille réutilise **tel quel** l'appareil livré en 0.20.0 : `consigner()` (idempotence par
marqueur), `render_rapport_pistes()` (fortes et faibles séparées), `effective_dry_run`. Aucune
écriture d'un type nouveau n'est introduite.

## 3. Les sources

### 3.1 Wikidata — la seule à produire des pistes fortes

Requête SPARQL par nom et bornes de dates, via `sparql_rows()`. Les propriétés étant structurées,
on peut en tirer plusieurs facteurs distincts (`nom`, `date complète`, `lieu`) et donc atteindre
`forte`.

`identite` = le **Q-item** (stable). `url` = l'URL de l'entité.

Réserve de couverture : Wikidata ne décrit que des personnes notables. Sur un arbre de 2119
personnes ordinaires, le rendement sera faible. C'est acceptable — le coût est faible aussi, et
les rares correspondances sont de haute valeur.

### 3.2 DHS — une projection de Wikidata, pas un protocole

Vérifié, pas supposé : la propriété Wikidata **P902** (« HDS ID ») porte l'identifiant du
*Dictionnaire historique de la Suisse*, dont les articles existent en allemand, français et
italien sous le même identifiant.

Le DHS n'est donc **pas une API de plus** : une fois un Q-item candidat obtenu par §3.1, `P902`
donne l'identifiant et l'URL de l'article. `pistes_dhs` est une projection de quelques dizaines de
lignes au-dessus de `pistes_wikidata`.

`identite` = l'identifiant HDS. Concordances : celles de la piste Wikidata dont elle dérive.

### 3.3 Gallica — presse et registres, sur personne déjà identifiée

Requête CQL construite depuis une personne dont la date **et** le lieu sont connus, la fenêtre
temporelle étant bornée par sa vie. Les résultats hors fenêtre sont écartés avant émission.

`identite` = l'**ark** rendu par l'API — stable, donc `identite_derivee=False` et pas de clé
dérivée. C'est le bon cas : l'ark est un permalien réel, contrairement au trou structurel constaté
sur Mémoire des hommes (cf. `docs/BACKLOG.md`), où 68,8 % des lignes n'ont aucun permalien et où
l'URL n'est **pas** reconstructible.

Concordances attendues : `nom`, parfois `lieu`. Donc `faible` presque toujours — voir §1.3.

### 3.4 Scriptorium — écarté, et pourquoi

Deux raisons indépendantes, chacune suffisante.

**Le périmètre.** Scriptorium ne couvre que la presse **vaudoise**. Mesuré sur
`samples/data.gramps` (2119 personnes) :

| Périmètre | Lieux | Événements | Personnes |
| --- | --- | --- | --- |
| Vaud — territoire de Scriptorium | 8 | 12 | **9** |
| Romandie | 13 | 26 | 19 |
| Suisse entière | 25 | 224 | 122 |

La Suisse pèse 6 % de l'arbre, mais elle est massivement **alémanique** (Berne, Argovie,
Thurgovie, Emmental). La cible de Scriptorium est de **neuf personnes**.

**L'accès.** Le document de travail annonce « BCUL, OAI-PMH ». **Non vérifié et probablement
faux** : `https://www.scriptorium.ch/api` répond « MediaINFO API is up and running », ce qui
n'est ni Omeka S ni OAI-PMH. Aucune documentation d'accès programmatique n'a été trouvée.

**Décision** : la source est écartée de ce sous-projet et consignée dans `docs/BACKLOG.md` avec
ces chiffres. Condition de réouverture : que la branche vaudoise s'étoffe sensiblement. En aucun
cas on n'écrira de scraping pour y suppléer — il produirait des URL fabriquées, consignées dans
Gramps comme preuves, ce que le projet a déjà refusé sur Mémoire des hommes.

Noter la dissymétrie avec le DHS (§3.2), qui couvre la Suisse **entière** : même origine
géographique, cibles incomparables (122 personnes contre 9), et coût bien moindre puisqu'il n'est
qu'une projection de Wikidata.

## 4. Ce qui ne change pas

- **Aucune citation, aucun fait.** Les quatre sources n'émettent que des `Piste`, consignées en
  notes append-only avec le marqueur du contrat 0.20.0.
- **`force` reste dérivé** et vit dans la bibliothèque, invoqué identiquement par les quatre
  sources. Aucun module n'a le droit de le saisir.
- **Le vocabulaire des concordances reste clos** aux six facteurs existants. Une source qui
  voudrait faire valoir « né en 1888 » se fait refuser par pydantic — l'année seule n'est jamais
  discriminante.

## 5. Tests

- **Bibliothèque** : les quatre `pistes_*` étant pures, elles se testent par tables de cas sur des
  résultats d'API figés (fixtures) — aucun réseau. Au minimum, par source : une piste forte quand
  c'est possible, une faible, un rejet hors fenêtre temporelle.
- **Non-régression du déménagement** : les tests existants de `piste_depuis_match` suivent la
  fonction vers `pistes/matchid.py` et doivent passer **sans modification de leurs assertions**.
  C'est le critère qui prouve que le déplacement n'a rien changé au comportement.
- **genecrew** : les trois feuilles se testent au niveau du parseur (`test_cli_parser.py`), comme
  les feuilles existantes.

## 6. Risques

| Risque | Traitement |
| --- | --- |
| DHS ne couvre que les personnes notables | cible large (122 personnes suisses), coût faible (projection de Wikidata) ; on le saura vite |
| Wikidata à faible rendement (personnes non notables) | assumé — coût faible, valeur unitaire haute |
| Déménagement de `piste_depuis_match` | livraison inter-dépôts : **taguer et pousser la bibliothèque avant** que la CI de genecrew puisse verdir (la CI checkoute le voisin sur le tag lu dans `uv.lock`) |
| Volume de pistes faibles noyant la relecture | la presse ne cible que des personnes déjà identifiées (§1.3) ; le rapport sépare déjà fortes et faibles |

## 7. Ordre de livraison

1. Déménagement de `piste_depuis_match` → `pistes/matchid.py` (établit le paquet et l'interface).
2. Wikidata (la source à pistes fortes, celle qui a le plus de valeur).
3. DHS (projection quasi gratuite de 2, cible de 122 personnes).
4. Gallica (presse FR, le plus gros volume, pistes faibles par construction).

Chaque étape est livrable seule : le spec est unique, la livraison reste incrémentale.
