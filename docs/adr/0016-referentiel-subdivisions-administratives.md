# ADR 0016 — Référentiel des subdivisions administratives (Wikidata, écritures non destructives)

Date : 2026-07-22 — Statut : accepté

## Contexte

Le chantier a été déclenché par un constat simple : **aucun canton suisse n'existe dans
l'arbre**, ni comme lieu de type `Canton` ni comme `State`, ni sous aucun nom (`Vaud`,
`Berne`, `Genève`). L'enquête a montré deux problèmes distincts. D'abord un défaut de
parseur : `Montreux (VD)` ne comporte aucune virgule, et `parse_pname` déduit le pays du
dernier segment séparé par virgule — il rebascule le lieu en commune sans pays, ce qui
empêche `resolve_ch` (le seul résolveur qui pose `Suisse › Canton › Commune`) d'être appelé.
Ensuite, et plus profondément, un défaut de structure : sur les 304 lieux de l'arbre,
**presque aucun contenant n'a de coordonnées** (38 `Department` et 12 `Region` au code INSEE
nu, sans GPS) et des pays entiers manquent comme entités (Italie, États-Unis, Pologne,
Belgique). Le correctif de parseur ne peut rien tant que le contenant qu'il faudrait
rattacher n'existe pas — `_ensure_parents` (`places_apply.py`) crée un parent manquant, mais
nu, ni GPS ni QID ni article. D'où l'ordre retenu : d'abord peupler le référentiel des pays et
subdivisions, puis corriger le parseur, pour qu'aucun canton ne soit jamais créé comme stub.

Ce chantier (livraison 1, propose/apply referentiel) fait l'objet de cet ADR. Le correctif de
parseur (livraison 2, §8 de la spec) et le câblage des deux feuilles CLI restent hors de ce
qui est livré à ce jour — voir « Hors périmètre ». Détail complet des mesures :
`docs/superpowers/specs/2026-07-21-referentiel-lieux-design.md`.

## Décision

### 1. Sélection par code ISO 3166-2 (`P300`), jamais par classe (`P31`)

Un sondage par classe Wikidata a été mesuré pays par pays avant toute décision : la wilaya
algérienne (`Q192498`) n'en trouve que 11 sur 58 attendues, la province belge (`Q104158`) 0
sur 10, alors que le canton suisse (`Q23058`), le Land allemand (`Q1221156`) et l'État
américain (`Q35657`) tombent juste. Le cas rédhibitoire : **Naples et Milan ne sont pas des
`provincia`**, ce sont des *città metropolitana*, une autre classe — la sélection par `P31`
aurait raté précisément les deux lieux attendus pour les lignées Pagano/Pagani. L'univers
retenu est donc l'ensemble des entités portant un code `P300` du préfixe pays voulu, non
dissoutes (`P576` absent) — 100 % de couverture mesurée sur les 9 pays, GPS et article
Wikipédia compris.

### 2. Le niveau vient du rattachement (`P131`), jamais de la forme du code

Découper sur la forme du code serait un piège spécifique à chaque pays : en France les
régions sont alphabétiques (`FR-ARA`) et les départements numériques (`FR-01`) ; **en Italie
c'est l'inverse** — `IT-25` est la Lombardie (région), `IT-NA` Naples (province). Le niveau
d'une entité vaut 1 + celui de son parent `P131` le moins profond parmi les parents qui
appartiennent à l'univers et portent un code ISO différent du sien ; sans cette dernière
condition, deux entités en collision (cas réel de `FR-69`, le Rhône) se prendraient
mutuellement pour parent et aucune ne se résoudrait. Le mapper pur est
`map_subdivisions` (`crewai_custom_tools/tools/genealogy/referentiel/wikidata.py`).

### 3. Le filtre par sous-classes a été essayé puis rejeté

Une version antérieure envisageait `?item wdt:P31/wdt:P279* wd:Q56061` (« entité territoriale
administrative ») pour écarter le bruit. Rejeté : la fermeture transitive fait rendre un 504 à
l'endpoint public, y compris pour un pays aussi petit que la Pologne.

### 4. Ancre pays, à trois sauts de `P131`

Les régions métropolitaines françaises ne pendent pas sous la France mais sous `Q212429`
*France métropolitaine*, qui n'a aucun code ISO 3166-2. Une première version des règles,
sans ancre, ne retenait **que 12 entités françaises sur 125**, toutes ultramarines — les 18
régions et les 96 départements métropolitains tombaient tous, faute de parent résolu, la
collision `FR-69` disparaissant avec eux. La requête vérifie donc, en plus, si le pays est
atteignable en un, deux ou **trois** sauts de `P131` ; l'ancre ne s'applique qu'aux entités
dont *aucun* `P131` ne pointe déjà dans l'univers, sinon Venise-la-ville (dont l'unique parent
partage son code ISO) serait promue région. Trois sauts est une valeur mesurée : à quatre,
l'ancre repêche l'entité sans libellé de `IT-82`, dont la chaîne remonte par une commune puis
une province, et la fait collisionner avec la Sicile.

### 5. Rien n'est écarté en silence

`map_subdivisions` rend **trois** listes — retenues, collisions (même code ISO porté par deux
entités retenues, ordonnées par QID pour la reproductibilité), et entités écartées avec leur
motif. C'est l'absence de ce troisième canal qui a masqué, lors de la conception, le défaut du
point 4 : « ce pays a 12 subdivisions » était indiscernable de « 113 entités sont tombées ».
`propose referentiel` porte les trois listes dans son rapport et son YAML.

### 6. Types Gramps natifs uniquement

Ni `Canton` ni `Wilaya` ne sont des types natifs (relevés sur `/types/default/place_types`).
Aucun type personnalisé nouveau n'est créé : le résolveur suisse pose désormais `State` et non
`Canton` (`geo/suisse.py`), et les 5 `Wilaya` existants de l'arbre sont retypés `Province` par
`apply referentiel`. Raison : le coût d'un type personnalisé n'est pas sa création, c'est que
**tout filtre par type doit le connaître** — une liste d'inclusion qui l'oublie rattache un
lieu en silence. C'est le même risque que documente déjà le CLAUDE.md pour les décès. Le
retypage des 5 wilayas est la **seule écriture destructive** de ce chantier : un `place_type`
n'est pas une donnée saisie avec une intention généalogique, c'est une étiquette de structure —
même famille que la casse des noms, déjà écrite directement (ADR 0001) — et reste réversible
d'un run puisqu'il ne porte que sur cinq lieux.

### 7. Identité par QID, stocké dans les `urls`

Le premier appariement (spec §5.3) essaie, dans l'ordre : le QID déjà posé dans les `urls` ;
sinon nom + type sous le même parent ; sinon le nom seul chez les lieux qui peuvent contenir.
Le nom vernaculaire (`Bayern`, `Bavière`) est rapatrié dans la requête SPARQL pour ce premier
passage — mais dès que le QID est posé, au premier run, l'identité ne dépend plus des chaînes.
C'est ce qui règle `Bayern` contre `Bavière` sans jamais renommer le lieu existant : le nom en
base n'est jamais réécrit, seule la variante rejoint `alt_names`.

### 8. Doublons de l'arbre : signalés, jamais fusionnés — et jamais écrits

`propose referentiel` rend une section « doublons » (lieux partageant nom, type et parent) ;
aucune écriture n'est faite sur eux, la fusion restant l'affaire de `merge places`. Cette
décision explique aussi pourquoi ces doublons passaient inaperçus jusqu'ici : l'index
`chemin → handle` construit par `_seed_parent_index` (`places_apply.py`) écrase silencieusement
la clé quand deux lieux mènent au même chemin — la structure qui sert à décider quel parent
rattacher est précisément celle qui rend les doublons invisibles. Le cas mesuré du doublon
`France` (deux `Country` identiques, hiérarchie coupée en deux) est ce qui a révélé le défaut.

### 9. En cas de doute sur la cible d'une écriture, on crée plutôt qu'on écrit

C'est l'arbitrage le plus important du lot, découvert en revue de code plutôt que posé a
priori. Écrire sur le mauvais lieu est **irréversible en pratique** — une fois la donnée
posée, plus rien ne distingue le juste du faux — alors qu'un doublon est réversible et déjà
outillé par `merge places`. `_candidat_recevable` (`referentiel_apply.py`) refuse donc un
appariement par nom quand il mène vers une cible non plausible, sur deux cas réels reproduits
en cours de conception :

- un lieu typé `Country` n'est jamais la cible d'une **subdivision** : sans cette règle,
  l'État américain « Géorgie » s'apparie au **pays** Géorgie et reçoit le GPS d'Atlanta, le
  code `GA`, un rattachement sous les États-Unis ;
- quand le parent attendu est connu, le candidat doit être rattaché sous ce parent — mais un
  candidat **non rattaché** ne passe pas non plus, puisque c'est l'état normal de l'arbre au
  premier run : une province `Limbourg` néerlandaise non rattachée aurait sinon reçu les
  données du Limbourg belge.

L'invariant d'écriture (§5.5 de la spec) — toute écriture est une création, un remplissage de
champ vide, ou un ajout dans une liste, à la seule exception du retypage des wilayas — protège
contre la **destruction** ; il ne protège pas contre l'écriture d'une valeur juste sur le
**mauvais objet**. C'est cette distinction que la règle « dans le doute, on crée » vient
couvrir, et c'est elle qui autorise `apply referentiel` à écrire directement, sans détour par
une seconde relecture humaine du résultat.

### 10. Dette assumée sur `alt_names`

Un nom existant n'étant jamais réécrit, les `alt_names` accueillent désormais deux natures de
contenu : la variante historique d'un même lieu (le cas déjà en base) **et** la traduction
d'un nom vernaculaire vers le français, ou l'inverse (`Bavière` face à `Bayern`). Une relecture
future doit savoir laquelle des deux elle regarde ; rien dans le modèle ne les distingue.

### 11. Partage du travail avec `enrich wiki`

`apply referentiel` pose l'article Wikipédia des pays et subdivisions depuis le sitelink de la
même requête SPARQL (`schema:about`/`schema:isPartOf`), sans passer par `enrich wiki`. Raison :
`enrich wiki` ne retient que les lieux ayant déjà `lat`/`long` — il n'a donc jamais vu les
contenants, qui n'en avaient pas avant ce chantier — et chercher l'article d'un département
autour de son barycentre géocodé attraperait de toute façon le village le plus proche du
centroïde, pas le département. Une fois `apply referentiel` passé, les ~430 subdivisions
gagnent des coordonnées et deviennent de ce fait éligibles au passage suivant d'`enrich wiki`
pour leurs propres feuilles ; les deux commandes ne se recouvrent donc pas.

### 12. Limites connues

Paris (`FR-75C`) et la Polynésie française (`FR-PF`) pendent respectivement sous *Métropole du
Grand Paris* et *France d'outre-mer*, au-delà de la portée de l'ancre à trois sauts (point 4) ;
les repêcher en l'allongeant les classerait au niveau 1 (`Region`), ce que Paris n'est pas.
Les deux restent hors référentiel et ressortent dans la liste des écartées avec leur motif —
traitement à la main. Sur les 9 pays de la table, seuls **4** (France, Italie, Suisse,
Pologne) ont une charge SPARQL réelle figée en fixture de test
(`crewai_custom_tools/tests/fixtures/referentiel/{FR,IT,CH,PL}.json`) ; les 5 autres reposent
sur les mêmes règles sans charge réelle versionnée.

## Grammaire CLI

Aucun verbe nouveau : la décision pose deux feuilles sous des verbes déjà fixés par l'ADR 0012,
`propose referentiel --country FR,CH` (lecture seule) et `apply referentiel --yaml <relu.yaml>
--dry-run` (consomme le YAML relu, ne réinterroge jamais Wikidata — même discipline que
`apply deaths` et `merge places`, pour que l'écriture reste reproductible face à une source qui
bouge entre deux appels). Le nom `referentiel` a été préféré à `init` : la commande n'est pas
un one-shot de démarrage, elle se relance à chaque pays nouveau dans l'arbre. **Le câblage de
ces deux feuilles dans `cli.py`/`main.py` n'est pas encore livré** ; cet ADR consigne la
décision de leur forme, pas leur mise en service.

## Conséquences

- `docs/adr/0012-cli-grammaire-verbes.md` référence cet ADR pour les feuilles `referentiel`.
- `merge places` reste le seul chemin de fusion pour les doublons signalés — ni `propose
  referentiel` ni `apply referentiel` n'y touchent.
- Le retypage des 5 wilayas est à surveiller au premier run réel : si l'arbre en portait plus
  que les 5 mesurées, le rapport doit le montrer ligne à ligne (aucun retypage de masse muet).
- Une relecture de `alt_names` sur un lieu du référentiel doit désormais distinguer variante
  historique et traduction (point 10) — aucun champ ne porte cette distinction à ce jour.

## Hors périmètre

- Le correctif `parse_pname` pour les 19 communes suisses `Commune (XX)` (livraison 2, spec §8).
- Le câblage des feuilles CLI `propose referentiel`/`apply referentiel` (tâche 10 du plan).
- La fusion des doublons détectés par `propose referentiel` : signalés seulement, traités par
  `merge places` (ADR 0015).
- Le typage des 56 lieux `Unknown` : chantier distinct.
- `Region: Algérie française` et ses départements historiques : entité disparue de Wikidata,
  sans équivalent comme subdivision actuelle. Laissée intacte.
- Le troisième niveau administratif (arrondissements, districts) et le rattachement des
  communes non suisses aux nouvelles subdivisions : hors de ce lot.

Spec : `docs/superpowers/specs/2026-07-21-referentiel-lieux-design.md`.
Voir aussi ADR 0001 (écriture directe encadrée sur la forme), 0005 (déterministe d'abord),
0012 (grammaire CLI), 0013 et 0015 (la ressemblance ne prouve jamais l'identité — doctrine
transposée ici aux lieux via QID plutôt que noms).
