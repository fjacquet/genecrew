# Détection des doublons de lieux (`merge places --scope`)

> Conception validée le 2026-07-21. Donne à `merge places` le mode détection qui lui manque,
> sur le modèle de `merge people`. Chantier **complémentaire** du référentiel des subdivisions
> administratives (`2026-07-21-referentiel-lieux-design.md`), qui signale les doublons sans
> jamais les fusionner (§5.4 et §10 de cette spec-là) — celle-ci prend le relais exactement là.

## 1. L'angle mort, mesuré

`apply places` ne traite **que** les lieux de type `Unknown` : la première chose que fait sa
boucle est de sauter tout lieu déjà typé (`places_apply.py:129`), au nom de l'idempotence — un
lieu déjà structuré n'a plus rien à recevoir. La garde est justifiée et ne doit pas bouger.

Mais c'est aussi `apply places` qui produit le YAML de fusions, et il ne le compose que pour les
lieux qu'il vient lui-même de résoudre : deux lieux tombant sur le même chemin canonique
(`places_apply.py:158-164`). **Un doublon déjà typé n'entre donc dans le champ d'aucune
commande.** Il est invisible pour le pipeline entier.

Mesure du 2026-07-21 sur l'arbre : 11 groupes de communes homonymes, toutes de type
`Municipality`, donc toutes hors de portée. L'utilisateur a fini par les fusionner à la main dans
l'interface Gramps, une par une.

`merge places` existe pourtant, mais il n'est qu'un **exécutant** : `--yaml` est requis, il
consomme des paires déjà relues. Son voisin `merge people` a les **deux** modes — `--scope`
détecte et fusionne sur preuve puis dépose le reste en arbitrage, `--yaml` exécute des paires
relues. La symétrie manque, et c'est tout le sujet : il manque un producteur, pas un exécutant.

## 2. Frontière avec le chantier référentiel

Les deux chantiers touchent les mêmes objets ; la frontière est posée par la spec du référentiel
et reprise telle quelle ici.

- **Référentiel** : crée et complète les *contenants* (pays, subdivisions administratives), et
  **signale** les doublons dans une section de son rapport, sans jamais écrire sur eux.
- **Celui-ci** : détecte les doublons parmi les lieux existants, fusionne ceux qui sont prouvés,
  dépose les autres en arbitrage.

Une conséquence à ne pas manquer : le référentiel **donnera des coordonnées aux départements et
aux régions**, qui n'en ont aucune aujourd'hui. C'est précisément ce qui rend indispensable la
garde du §3 sur les types croisés — voir le cas Paris. Le danger n'est pas théorique, il est
programmé.

Point de convergence à surveiller : les deux chantiers détectent des doublons, sur des critères
différents (nom + type + parent pour le référentiel, voir §3 ici). Si la seconde livraison
constate que les deux détections divergent sur des cas réels, **la détection pure de ce
chantier-ci fait autorité** : elle vit dans la bibliothèque, elle est testée sur des cas nommés,
et c'est elle qui décide d'écrire.

## 3. La preuve

Deux lieux sont **candidats** s'ils portent le même **nom normalisé** — accents, casse,
séparateurs, ligatures (`œ`, `æ`) et apostrophe typographique (`’`) neutralisés.

Un **veto** s'applique d'abord, avant toute autre considération : deux codes **non vides et
différents** interdisent la fusion automatique, quels que soient les types et les coordonnées.

Hors veto, la fusion est **automatique** si l'une des deux conditions tient :

1. **codes identiques et non vides** — un code INSEE, ou son équivalent national, est un
   identifiant canonique, pas une ressemblance. Vaut quel que soit le type des deux lieux ;
2. **même type** et **coordonnées identiques** — la voie des lieux sans code, comme Rhodt unter
   Rietburg. Les coordonnées ne prouvent jamais rien entre types différents.

Les deux conditions sont disjointes en pratique : dès qu'un code non vide existe des deux côtés,
soit il est égal et la condition 1 tranche, soit il diffère et le veto a déjà refusé. La
condition 2 ne s'exerce donc que sur des lieux dont au moins un côté n'a pas de code.

Tout le reste part en **YAML d'arbitrage**, avec types, codes, coordonnées et nombre de
rétroliens en clair pour que la relecture soit possible sans ouvrir Gramps.

Ces bornes ne sont pas déduites d'un principe : elles viennent des cas réels de l'arbre.

| Cas mesuré | Verdict | Raison |
|---|---|---|
| Paris `Department` code 75 / `Municipality` code 75056 | **refus** | deux entités administratives réelles ; codes différents, et la garde « même type » empêche que le géocodage à venir des départements les rapproche par coordonnées |
| Annaba, Sétif — `Department` / `Wilaya` | **arbitrage** | même objet réel, mais code vide d'un côté ; seul un humain le sait |
| Souk Ahras `Wilaya` 41 / `Department` 4101 | **arbitrage** | codes et coordonnées différents |
| Rhodt unter Rietburg, deux `Municipality` | **fusion** | aucun code, coordonnées identiques à sept décimales |
| Cerbois, Quantilly, Reuilly, Saint-Michel… | **fusion** | même code INSEE |

C'est la doctrine de l'ADR 0013 transposée aux lieux : **la ressemblance ne prouve jamais
l'identité**. Avec un avantage que les personnes n'ont pas — une commune possède un identifiant
canonique, ce qui rend ici la preuve plus forte et plus simple à énoncer.

## 4. Quel lieu survit

Ordre de sélection, appliqué dans cet ordre exact :

1. **richesse** — présence de coordonnées, d'un code, d'un parent hiérarchique ;
2. **rétroliens** — nombre d'objets qui référencent le lieu ;
3. **identifiant le plus petit**, pour que la règle soit totale et déterministe.

La raison est mécanique et irréversible : la fusion Gramps **unionne les listes** mais les
**champs simples restent ceux du survivant**. Garder Apremont-la-Forêt `P0387`, une coquille sans
coordonnées ni code, contre `P0148` qui a les deux, effacerait définitivement ces coordonnées.

Le rapport nomme le survivant, l'absorbé, **et ce qui aurait été perdu dans l'ordre inverse**.
C'est inhabituel dans ce projet, et délibéré : une règle de sélection qu'on ne peut pas vérifier
après coup est une règle qu'on croit sur parole.

## 5. Transitivité

Verrens-Arvey existe en trois exemplaires. Comme pour les personnes, la déduplication est
**transitive** : les candidats forment des grappes, et une passe peut en révéler de nouvelles.
Passes successives jusqu'à convergence, bornées par `--max-passes` (défaut 5), au patron de
`people_merge.run_people_merge`.

## 6. Surface CLI

```
genecrew merge places --scope all [--limit N] [--dry-run]   # détecte, fusionne sur preuve
genecrew merge places --yaml <relu.yaml>                    # inchangé
```

`--yaml` passe de **requis à optionnel** (`cli.py:149`). C'est exactement la surface de
`merge people`, `--max-passes` compris. Aucun verbe, aucune feuille nouvelle : la grammaire à
sept verbes de l'ADR 0012 ne bouge pas.

Simulation par défaut via `effective_dry_run`, comme partout : le premier passage ne peut rien
casser.

## 7. Où vit le code

**Détection pure** → `crewai_custom_tools`, à côté de `analysis/duplicates.py` qui fait déjà
exactement cela pour les personnes : candidats par nom normalisé, évaluation de la preuve, choix
du survivant, construction des grappes. C'est de la logique généalogique pure, sans réseau ; la
règle du dépôt l'y envoie.

**Orchestration** → `places_merge.py` dans genecrew, à côté de l'exécutant existant : collecte
paginée, passes de convergence, rapport Markdown, YAML d'arbitrage.

### 7.1 La normalisation de nom, et une dépendance à ne pas manquer

La normalisation décrite au §3 existe déjà, sous le nom `normaliser_lieu` — mais **uniquement sur
la branche `feat/deces-creation-evenement`, non fusionnée** (`deces_event.py`), où elle a reçu le
traitement des ligatures et de l'apostrophe typographique.

Ce chantier crée donc la version **canonique dans la bibliothèque**, où cette fonction pure aurait
dû naître. Deux conséquences à tenir :

- tant que les deux branches ne sont pas fusionnées, deux implémentations coexistent et **ne
  doivent pas diverger** — le comportement attendu est identique, cas de test compris ;
- une fois les deux fusionnées, `deces_event.normaliser_lieu` est remplacée par un import de la
  bibliothèque. C'est un suivi explicite, pas un vœu : à faire dans la première branche qui touche
  `deces_event.py` après la seconde fusion.

## 8. Tests

Purs, dans la bibliothèque :

- chaque branche de preuve — codes égaux ; codes différents (veto) ; coordonnées + même type ;
  coordonnées + types différents (refus) ; aucun code des deux côtés ;
- le choix du survivant, **dont le cas où le plus référencé est le plus pauvre** — c'est là que la
  règle se distingue d'un simple comptage ;
- les grappes à trois éléments, et la convergence.

Avec client simulé, dans genecrew : une passe complète en simulation, le contenu du YAML
d'arbitrage, l'arrêt sur `--max-passes`.

Les cinq lignes du tableau du §3 deviennent des tests nommés. Ce sont des cas réels de l'arbre,
pas des exemples inventés — et Paris est celui qui doit rester rouge si la garde disparaît.

## 9. ADR 0015

Il prolonge l'ADR 0013 et énonce ce que les lieux ont de particulier :

- un **identifiant canonique** (le code de commune) que les personnes n'ont pas, qui autorise une
  preuve plus forte ;
- une **asymétrie de perte** propre à la fusion Gramps — les listes fusionnent, les champs simples
  s'écrasent — qui fait du choix du survivant une décision de conservation, pas de confort ;
- la **garde des types croisés**, motivée par un cas réel (Paris) et par le fait que le chantier
  référentiel va rendre ce cas atteignable en géocodant les départements.

## 10. Hors périmètre

- **Créer ou compléter des lieux** : c'est le chantier référentiel, et `apply places`.
- **Corriger `apply places`** pour qu'il regarde les lieux déjà typés : sa garde d'idempotence est
  juste ; le manque était un producteur de fusions, pas un défaut de cette commande.
- **Fusionner sur ressemblance de nom seule** : jamais, dans aucun mode.
