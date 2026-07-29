# Lieux-dits et lisibilité du compte rendu — `import releve`

Date : 2026-07-29
Statut : validé, prêt pour le plan d'implémentation

## Le problème

Le 2026-07-29, l'import du relevé de décès d'Ursin Charles Villaudy (acte n° 37,
Saint-Martin-d'Auxigny, 1868) a créé l'événement **E0332** *sans lieu*, alors que
l'acte dit « décédé aux Roches » et que le hameau **P0661 « Les Roches »**
existait déjà dans l'arbre, correctement rattaché à sa commune.

Trois défauts distincts se superposent, et il a fallu les démêler un par un.

### 1. Un champ dont le contrat est violé

`_raw_lieu()` assemble une chaîne « **commune**, département, pays » à partir de
`ReleveIndexe.evenement_lieu`. Son propre docstring dit « commune ». Or le LLM
d'interprétation y a écrit **« Les Roches »**, un lieu-dit, parce que la
transcription de l'acte le nommait ainsi.

Le résolveur a donc cherché une *commune* nommée « Les Roches ». Il en a trouvé
une — en Ardèche.

C'est le défaut de fond : **rien dans le pipeline ne distingue une commune d'un
lieu-dit**, et un champ documenté pour l'une reçoit indifféremment l'autre.

### 2. L'arbre n'est jamais consulté

`resoudre_ou_creer_lieu()` (`releves_import.py:689`) délègue **entièrement** à
`run_lieu_import()`, donc aux résolveurs `geo/`, donc au réseau. Il ne cherche à
aucun moment le lieu dans l'arbre par son nom.

P0661 avait beau exister depuis des heures, ce chemin ne pouvait pas le voir.

> Ne pas confondre avec `TYPES_LIEU_DECES` (`deces_event.py:87`), la liste
> d'inclusion `{Municipality, City}` qui filtre `index_lieux()`. Celle-là ne sert
> qu'à `apply deaths` et n'a aucun effet sur `import releve`. La confusion a été
> faite une fois pendant la conception ; elle est notée ici pour ne pas l'être deux.

### 3. Le score ne mesure pas ce qu'on croit

Mesures du 2026-07-29 contre Nominatim, sans bornage :

| Requête | Résultat | Score | Réalité |
|---|---|---|---|
| `Les Roches, Saint-Martin-d'Auxigny, Cher, France` | 44.9859 / 4.1897 | **1.0** | Ardèche |
| `La Rose, Saint-Martin-d'Auxigny, Cher, France` | 43.3332 / 5.4297 | **1.0** | Marseille |

Saint-Martin-d'Auxigny est à 47.2164 / 2.35. Le score de similarité mesure la
ressemblance de chaîne, pas la plausibilité géographique : il ne peut pas savoir
que le résultat est à 400 km. Seul le seuil `--min-score` a bloqué l'écriture, et
il l'a bloquée pour la mauvaise raison — la confiance, pas la distance.

**Abaisser `--min-score` pour « rattraper » ce cas écrirait la mauvaise position.**

### 4. Le compte rendu n'est pas relisable

`releves_import.py:1221` imprime la valeur brute écrite :

```
  Death créé : de0043e5bfb6427d8c4493482148b482 (lieu aucun)
```

Gramps porte deux identifiants par objet : le `handle` (clé primaire interne,
32 caractères hexadécimaux, jamais affichée dans l'interface) et le `gramps_id`
(`E0332`, `P0661`, celui que voit l'utilisateur). Le rapport imprime le premier.
Un humain qui relit ne peut rien vérifier sans traduction manuelle.

`report.py::_link()` fait déjà bien pour l'audit : `gramps_id` + lien cliquable.

## Ce qui a été mesuré

Faits établis pendant la conception, contre l'arbre et les API réelles. Ils
fondent les décisions qui suivent.

**L'arbre** — 663 lieux. **3 noms seulement** sont portés par plusieurs lieux
(`souk ahras`, `bourges`, `paris`), et les trois collisions sont **inter-types**
(le Paris `Department` et le Paris `Municipality` du gotcha connu). Un filtre
nom + type + parent est donc déterministe sur cet arbre.

**La hiérarchie des hameaux est déjà correcte** :

```
P0661 'Les Roches' [Hamlet] ──┐
P0662 'La Rose'    [Hamlet] ──┴─→ P0504 Saint-Martin-d'Auxigny [Municipality] → P0271 Cher [Department]
```

Les deux sont rattachés à leur commune et sans GPS.

**La Base Adresse Nationale ne connaît pas ces lieux-dits.** `type=locality` sur
`citycode=18223` ne rend rien pour « La Rose », « Les Roches » ni « Le Montet » —
le seul résultat obtenu est un parking. La BAN ne peut pas fournir de coordonnées
de lieu-dit ici.

Elle rend en revanche les rues qui en portent le nom, et **filtrer par code postal
ne suffirait pas** : le 18110 couvre plusieurs communes, et « Route de la Rose »
existe à Vasselay (18271) et Saint-Éloy-de-Gy (18206), toutes deux **mieux
scorées** que celle de Saint-Martin-d'Auxigny (18223).

**Nominatim borné à l'emprise de la commune rend le bon résultat** :

| Requête bornée à `viewbox=2.29,47.27,2.42,47.16` | Résultat |
|---|---|
| `La Rose` | `hamlet` — La Rose, Saint-Martin-d'Auxigny, Cher — 47.19476 / 2.37858 |
| `Les Roches` | aucun résultat |

Le bornage élimine l'Ardèche **par la géométrie**, pas par un seuil : l'homonyme
n'est pas dans la boîte. La couverture d'OSM reste partielle — Les Roches y est
absent, alors que les rues « des Roches » de la BAN se groupent à 400 m de
La Rose, ce qui confirme que le hameau existe et que l'absence est une lacune
d'OSM, pas une erreur de lecture d'acte.

## Décisions

1. **Granularité : le plus fin que l'acte donne.** Si l'acte nomme un lieu-dit,
   l'événement pointe ce lieu-dit ; sinon la commune. Rien n'est perdu en
   remontant, la hiérarchie Gramps portant déjà le rattachement à la commune.

2. **Un lieu-dit absent de l'arbre est créé automatiquement**, sous sa commune.
   *Décision prise en connaissance du risque* : chaque graphie mal lue
   (« aux Rochers », « à la Roze ») deviendra un lieu permanent qu'il faudra
   fusionner plus tard, et la fusion de lieux est délicate (ADR 0015). Deux
   garde-fous compensent, sans contredire la décision : tout lieu créé est nommé
   dans le rapport avec sa provenance, et la création reste soumise au `--dry-run`.

3. **La granularité devient explicite dans le modèle**, plutôt que devinée. C'est
   ce qui distingue cette conception d'un simple ajout de recherche dans l'arbre :
   consulter l'arbre corrigerait le cas d'Ursin Charles par chance — parce que
   P0661 existe — mais laisserait le lieu-dit suivant repartir chercher une
   commune homonyme.

4. **Rien ne bouge dans `crewai_custom_tools`.** On en *importe* — `get_rate_limiter`,
   `GrampsCreatePlaceTool`, `effective_dry_run` — on n'y écrit pas. Donc pas de
   cycle bump → tag → `uv sync` entre les deux dépôts.

   Cette décision a un coût, découvert à la rédaction du plan :
   `geo/nominatim.py::map_nominatim()` **code en dur `place_type="Municipality"`**
   et est donc structurellement incapable de rendre un `hamlet`. L'étage 2 ne peut
   pas la réutiliser. La cascade vit par conséquent dans un module genecrew dédié,
   **`genecrew/src/genecrew/lieux_dits.py`**, qui fait sa propre requête bornée.
   Ce n'est pas une duplication gratuite : `releves_import.py` fait déjà 1234 lignes
   et son fichier de tests 76 Ko, et une cascade réseau y serait moins testable
   qu'isolée.

   *Écarté* : généraliser `index_lieux()` en index partagé monté dans la
   bibliothèque. Ça règlerait la classe entière, mais le CLAUDE.md réserve
   l'extraction au **second consommateur avéré**, et il n'existe pas ici —
   `apply deaths` a déjà son index et sa liste d'inclusion, qui répondent à un
   besoin différent.

## Conception

### Le modèle

`ReleveIndexe` gagne `evenement_lieu_dit: str = ""`, distinct de `evenement_lieu`.
Champ **optionnel, défaut vide** — la très grande majorité des relevés n'en portent
pas, et un défaut vide évite de casser les appels existants.

Le prompt d'interprétation demande explicitement la séparation : la commune d'un
côté, le lieu-dit de l'autre, et **n'en invente aucun** — un champ laissé vide est
un résultat correct, pas un échec.

Sans lieu-dit, le comportement actuel est inchangé, y compris le contenu du rapport.

### La cascade

Avec un lieu-dit, trois étages du moins cher au plus cher ; le premier qui répond
gagne.

| Étage | Source | Coût | Rend |
|---|---|---|---|
| 1 | L'arbre, sous la commune résolue | gratuit | Le handle existant |
| 2 | Nominatim **borné à l'emprise de la commune** | 1 requête | Un lieu créé, avec GPS |
| 3 | Création sous la commune | 0 | Un lieu créé, sans GPS |

**Étage 1** — appariement sur nom normalisé + type + parent. **Normalisation :
`strip()` puis `casefold()`**, exactement celle qui a servi à mesurer les
3 collisions ci-dessus ; le chiffre ne vaut que pour cette normalisation-là.
Déterministe sur cet arbre.

**Étage 2** — n'accepte qu'un `type` OSM parmi `hamlet`, `locality`, `village`,
`isolated_dwelling`. Un `street` ou un `administrative` est **rejeté** : « Rue de
la Rose » n'est pas le lieu-dit La Rose. Le bornage remplace le seuil de score ;
la garde devient géométrique, donc non contournable par un score de 1.0.

**D'où vient l'emprise.** Elle se dérive de la commune **déjà résolue**, dans cet
ordre de préférence :

1. La `boundingbox` que Nominatim rend pour la commune elle-même, si la résolution
   de commune l'a conservée — c'est l'emprise réelle, pas une approximation.
2. À défaut, un carré de **±0,06° autour des coordonnées de la commune**
   (≈ 6,7 km en latitude, ≈ 4,5 km en longitude à cette latitude). C'est la valeur
   employée pour la mesure de conception, et elle a suffi à trouver La Rose à
   2,7 km du bourg.

Le repli 2 est volontairement généreux : une emprise trop large ne peut ramener
qu'un lieu-dit de la commune voisine, à quelques kilomètres — jamais l'Ardèche.
Le coût d'erreur reste sans commune mesure avec celui de l'appel non borné.

**Commune sans coordonnées → pas d'étage 2.** Sans centre ni bounding box, aucune
emprise n'est calculable ; on passe directement à l'étage 3. C'est le cas des
communes que l'arbre porte sans GPS.

**Étage 3** — décision 2. Le lieu-dit entre dans l'arbre même invérifiable.

Deux invariants encadrent la cascade :

- **`lieux_resolus` ne voit jamais un lieu-dit.** `code_commune_prefixe()`
  continue de n'accepter qu'une commune. Le veto d'appariement raisonne sur des
  codes INSEE ; un code de hameau y serait incomparable et produirait un **veto
  faux** — or un candidat vetoé ne revient jamais devant le relecteur humain.
  C'est le contrat de granularité déjà documenté à `releves_import.py:733`, qu'on
  ne touche pas.
- **La commune est résolue d'abord, toujours.** L'emprise de l'étage 2 en dépend,
  et le parent des étages 1 et 3 aussi. Commune non résolue → aucun lieu-dit tenté,
  l'événement retombe sur le comportement actuel.

### Le compte rendu

```
  Death créé : E0332 (lieu P0661 « Les Roches », créé sans GPS)
```

Trois changements sur cette ligne :

- l'événement par son `gramps_id`, cliquable, sur le modèle de `report.py::_link()`
- le lieu par son identifiant **et** son nom, au lieu de `lieu aucun` ou d'un handle nu
- **la provenance du lieu** — trouvé dans l'arbre, créé avec GPS depuis OSM, ou
  créé sans coordonnées

La provenance est le garde-fou de la décision 2. Un hameau créé sans GPS à
l'étage 3 est précisément celui qu'une graphie mal lue produirait : il doit se
distinguer à l'œil d'un hameau confirmé par OSM.

**En simulation, il n'y a pas d'identifiant.** Le dry-run rend des handles
synthétiques `DRYRUN:…`. Le rapport n'invente pas un `E0332` qui n'existe pas
encore : il annonce l'intention (`Death à créer`, `lieu Les Roches à créer sans
GPS`). Un rapport de simulation qui ressemble trop à un rapport d'écriture est un
piège pour le relecteur — d'autant que les rapports sont relus avant d'être
consommés par `apply`.

## Erreurs

**Une panne à l'étage 1 ne devient jamais une création à l'étage 3.** Si la
recherche dans l'arbre échoue — API en vrac, timeout — on ignore si le lieu-dit
existe déjà ; continuer la cascade créerait un doublon de P0661. Donc : erreur à
l'étage 1 → on abandonne le lieu-dit et on attache la commune. **Une lecture ratée
n'autorise pas une écriture.**

C'est l'asymétrie centrale du traitement d'erreur, et le point le plus facile à
rater de cette spec.

Les autres pannes retombent proprement :

| Panne | Conduite |
|---|---|
| Nominatim injoignable ou lent | Étage 3, création sans GPS |
| Deux hameaux homonymes sous la même commune | Refus, commune attachée |
| Commune non résolue | Aucun lieu-dit tenté |

Le repli sur exception existe déjà à cet endroit (`RuntimeError`, `httpx.HTTPError`
attrapés en `releves_import.py:712`) pour qu'une exception ne tue pas un import à
mi-parcours en laissant un sujet orphelin invisible. La cascade s'y conforme.

**Cadence Nominatim** — **déjà câblée**, contrairement à ce que disait la première
rédaction de cette spec. `geo/nominatim.py::_http_get()` appelle
`get_rate_limiter().acquire("Nominatim")` avant chaque requête. La cascade importe
ce limiteur **partagé** plutôt que d'en réimplémenter un : la politique d'usage de
Nominatim est d'une requête par seconde tous appelants confondus, donc un compteur
propre au module la violerait dès qu'un autre chemin appelle aussi. Rien à câbler.

## Tests

Tout hors ligne, résolveurs simulés — la suite existante (`test_releves_import.py`,
76 Ko) ne touche pas au réseau et ne doit pas commencer.

| # | Cas | Ce qu'il protège |
|---|---|---|
| 1 | Lieu-dit dans l'arbre → étage 1, **le résolveur réseau n'est pas appelé** | L'ordre de la cascade |
| 2 | Absent, OSM rend un `hamlet` → créé avec GPS | Étage 2 |
| 3 | OSM rend un `street` → rejeté, étage 3 | Le filtre de type |
| 4 | L'emprise est bien transmise à la requête | La garde géométrique |
| 5 | **Erreur à l'étage 1 → commune attachée, aucune création** | L'anti-doublon |
| 6 | Commune non résolue → aucun lieu-dit tenté | L'ordre de résolution |
| 7 | **`lieux_resolus` ne contient jamais de hameau** | Le veto d'appariement |
| 8 | Dry-run → aucun faux `gramps_id` | L'honnêteté du rapport |
| 9 | Chaque lieu créé est nommé avec sa provenance | Le garde-fou de la décision 2 |

Les cas **1, 5 et 7 vérifient une absence** : ils passent au vert sans rien
protéger si on casse ce qu'ils gardent. Ils passent par `chasseur-de-tests-muets`
(sous-agent de mutation du dépôt) avant que le chantier soit considéré fait.

Régression : le changement de modèle (champ ajouté) ripple sur la suite existante,
qui doit rester entièrement verte. `uv run ruff check .` vert des deux côtés.

## Hors périmètre

**Le dépouillement de la file d'actes** — créer Jacques Villaudy, saisir les
mariages de 1888/1890/1925, corriger la naissance de Marie Antoinette au 14 janvier
1879, chercher le décès de Silvain entre 1921 et 1935. C'est de l'exécution avec
des verbes qui existent déjà, sans arbitrage de conception. Ce travail se fait
**après** ce chantier : celui-ci change *comment* les lieux se posent, donc
dépouiller avant produirait des événements à reprendre.

**Les deux lieux déjà écrits** restent à corriger à la main ou par un second
passage une fois la cascade en place :

| Événement | État | Cible |
|---|---|---|
| E0332 († Ursin Charles, 1868) | aucun lieu | P0661 Les Roches |
| E0333 († Jeanne Marie Mélanie, 1935) | P0504 commune | P0661 Les Roches |

## À établir à l'implémentation

**D'où vient le `gramps_id`** — soit la réponse du POST le porte déjà (gratuit),
soit il faut un GET par objet créé. Non vérifié. Repli sur le GET si la réponse ne
le porte pas ; le surcoût d'une requête par événement est négligeable devant les
appels LLM du même import.
