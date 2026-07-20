# Fusion des doublons de personnes, assistée par LLM

> Conception validée le 2026-07-20. Objectif de l'utilisateur, mot pour mot : « si on sait que
> c'est un doublon, je veux que le smart merge soit fait en API pas manuellement par moi ».
>
> Deux résultats de mesure ont façonné cette conception plus que les intuitions de départ :
> le moteur de fusion de Gramps n'offre **aucun** contrôle champ par champ (§2), et la
> similarité lexicale des noms produit du faux positif en masse sur **les deux plus grosses
> familles de l'arbre** (§3). Il en découle que le « smart » ne vit pas dans l'appel de fusion,
> et que le nom n'est jamais une preuve.

## 1. Contexte

### 1.1 Ce qui existe

`analysis/duplicates.py` (bibliothèque `crewai_custom_tools`, 47 lignes) implémente la règle R10 :

- exige une **année de naissance sur les deux** personnes ;
- écart ≤ 2 ans (`BIRTH_YEAR_WINDOW`) ;
- `difflib.SequenceMatcher ≥ 0.85` sur la chaîne `"prénom nom"` normalisée (minuscules, sans accents) ;
- O(n²) sur le lot.

Ses résultats vont **uniquement dans le rapport Markdown** (`report.py`, section « Candidats
doublons »). Aucune fusion de personnes n'existe. Pire, `crew_audit.py:181` écrit
`anomalies, _duplicates, all_people, _det_props = collect_audit_findings(...)` : **le crew LLM ne
voit même pas les doublons**.

Le précédent à suivre est `merge places` : YAML relu, exécution par
`GrampsMergePlacesTool`, rapport d'application, jamais d'automatisme.

### 1.2 Ce que la règle fondatrice disait

`document-de-travail.md:68` : « Interdites aux agents, toujours en proposition pour revue
humaine : suppression, **fusion** ».

**Cette spec amende cette règle**, de façon délibérée et bornée : la fusion devient automatique
pour un étage de preuve strictement défini (§4.1), et reste en proposition pour tout le reste.
L'amendement doit être porté par un ADR à l'implémentation. Il n'est pas un relâchement général :
c'est l'inverse, il substitue une preuve structurelle vérifiable à une relecture humaine dont
l'expérience montre qu'elle se fatigue sur des listes longues.

### 1.3 La contrainte que rien ne lève

**La fusion n'a pas d'annulation.** Le titanic est supprimé. L'attribut `Merged Gramps ID`
atteste qu'une fusion a eu lieu, mais rien n'indique quel événement, quelle citation ou quel
parent venait de qui : les listes sont unionnées à plat.

L'asymétrie des erreurs est donc brutale et doit gouverner tous les seuils :

- **rater un doublon** coûte un doublon de plus dans un arbre qui en a déjà ;
- **fusionner à tort** confond deux individus réels, de façon invisible et permanente, et
  contamine toute la descendance.

Précédent direct : le 2026-07-19, un seuil de confiance à 0.90 face à un score de 0.91 a fait
déclarer mortes trois personnes vivantes. Un seuil calibré à l'œil sur des scores se trompe ; la
seule question est à quelle fréquence.

## 2. Ce que l'API de fusion permet réellement

Vérifié en lisant le moteur installé localement
(`gramps/gen/lib/person.py`, `Person.merge()`), et non supposé.

`POST /api/people/{phoenix_handle}/merge/{titanic_handle}` — « Phoenix survives; titanic is
deleted ». Le corps est `PersonMergeArgs`, qui n'a **qu'une seule propriété** :

```json
{ "family_merger": true }
```

Il n'existe **aucun** contrôle champ par champ. On ne peut pas dire à l'API « garde la date de
celui-ci, le nom de celui-là ». Comportement réel de `Person.merge()` :

| Élément | Comportement |
|---|---|
| Listes (événements, LDS, médias, adresses, attributs, URL, refs de personnes, notes, citations, tags) | **unionnées**, avec déduplication `IDENTICAL` / `EQUAL` |
| Familles (parentales et conjugales) | ajoutées au phoenix ; `family_merger` fusionne ensuite les familles devenues doublons |
| Nom principal | phoenix gagne ; **celui du titanic est inséré en tête des noms alternatifs** — récupérable |
| Traçabilité | un attribut **`Merged Gramps ID`** portant l'ID du titanic est ajouté |
| `birth_ref_index` / `death_ref_index` | celui du phoenix gagne **s'il est renseigné** ; sinon celui du titanic est adopté (`_merge_event_ref_list`) |
| Confidentialité | `_merge_privacy` |
| **Genre** | **absent de `merge()`** — celui du phoenix survit, celui du titanic disparaît **sans trace** |

**Conséquence de conception :** le « smart merge » ne peut pas être exprimé *à* l'appel de
fusion. Il n'existe que deux leviers — **qui est phoenix**, et **patcher les scalaires du phoenix
avant** l'appel. Tout le reste, Gramps l'unionne correctement seul. Le périmètre s'en trouve
fortement réduit, et un seul patch est nécessaire (§4.4).

## 3. Ce que la mesure de l'arbre impose

Mesuré sur `samples/data.gramps` (2119 personnes, 485 patronymes distincts) le 2026-07-20.

### 3.1 La similarité de nom est un piège, pas une preuve

Les deux plus gros patronymes de l'arbre sont `Pagan` (151) et `Pagani` (53) — 204 personnes,
près de 10 % du total. Viennent `Jacquet` (63) et `Jacquier` (50), 113 de plus.

```text
0.957   'marie pagan'  vs 'marie pagani'
0.880   'jean jacquet' vs 'jean jacquier'
```

Le seuil de R10 est à **0.85**. R10 produit donc du faux positif en masse sur précisément les
familles les plus nombreuses de l'arbre, qui sont selon toute vraisemblance des lignées
distinctes — ou, pour `Pagan`/`Pagani`, une francisation, ce qui est un lien de filiation et non
un doublon de personne.

**Règle qui en découle, structurante pour tout le système :**

> La similarité de nom n'est **jamais** une preuve. C'est **uniquement une clé de blocage** :
> elle sert à proposer des paires à examiner, jamais à conclure. Toute la précision provient de
> la preuve structurelle.

### 3.2 L'arbre est la fusion de deux sources de casse différente

95 des 485 patronymes distincts ne sont qu'une variante de casse ou d'accent : `VILLAUDY` (57) /
`Villaudy` (33), `LARPENT` (32) / `Larpent` (34), `JACQUET` (20) / `Jacquet` (43), `JACQUIER`
(20) / `Jacquier` (30), `CLAVIER` (18) / `Clavier` (29).

C'est la signature de deux GEDCOM d'origines distinctes réunis dans un même arbre — donc un
**a priori fort que les doublons sont nombreux**, et qu'ils opposent souvent un enregistrement
majuscule à un enregistrement en casse mixte. `normalize_name` neutralisant déjà casse et
accents, ce point ne demande aucun traitement particulier ; il justifie l'effort.

### 3.3 Les patronymes sont massivement français

Seuls **1,3 %** des patronymes portent un marqueur non français (27 occurrences sur 2119) :
`Feschotte`, `Schneider`, `Schauffelberger`, `Tscheppet`, `Hartmann`, `Coulmann`, `Schaffter` —
de l'alsacien et du suisse-allemand. Aucun polonais, aucun arabe. (L'objection initiale visant
une clé phonétique « trop franco-centrée » transposait à tort la mémoire portant sur les
**lieux**, où figurent Pologne et Algérie.)

Une clé phonétique française est donc légitime. Et comme elle ne sert qu'au **rappel** (§3.1),
son imperfection sur ces 1,3 % coûte au pire quelques candidats manqués, que les quatre autres
clés de blocage rattrapent.

### 3.4 La déduplication est transitive

Deux copies d'une même personne issues de deux GEDCOM ont en général aussi des **parents
dupliqués**, donc des `father_handle` **différents**. La règle « mêmes parents » ne se déclenche
qu'une fois les parents eux-mêmes fusionnés.

La commande doit donc être **relançable**, chaque passe débloquant la suivante, jusqu'à
convergence (plus aucune fusion automatique). Ce n'est pas un défaut d'implémentation, c'est la
nature du problème ; le rapport doit l'exposer (« passe 3 : 12 fusions, relancer »).

## 4. Conception

### 4.1 Les trois étages

| Étage | Critère | Action |
|---|---|---|
| **Auto** | une des trois règles structurelles ci-dessous | fusion API immédiate, sans relecture |
| **Arbitrage** | bloc de candidats partagé, preuve partielle | dossier soumis au LLM, puis YAML pour relecture humaine |
| **Rejet** | ressemblance de nom seule | écarté, comptabilisé au rapport |

**Règles de l'étage auto** (retenues explicitement par l'utilisateur). Dans les trois cas, le nom
normalisé — prénom et patronyme, minuscules, sans accents — doit être **identique** :

1. **Date de naissance complète identique + mêmes parents** — jour, mois et année exacts
   (`sortval` non nul, précision au jour), `father_handle` **et** `mother_handle` identiques.
2. **Date de naissance complète identique seule** — mêmes exigences sur la date, sans condition
   sur les parents. Couvre les personnes dont les parents manquent dans l'arbre.
3. **Même conjoint + au moins un enfant commun** — même handle de conjoint **et** intersection
   non vide des `child_handles`. Couvre les personnes sans date de naissance connue, que R10
   ignore totalement aujourd'hui.

**Règle explicitement rejetée**, consignée pour que le refus soit un choix et non un oubli :

> **« mêmes parents + même prénom, sans date » ne fusionne jamais automatiquement.** C'est la
> signature exacte du **frère homonyme** — un enfant meurt en bas âge, le suivant reçoit le même
> prénom. Très fréquent avant 1900.

Un `sortval` à `0` (date inconnue ou non triable) ne compte **jamais** comme une concordance :
c'est le piège « année seule » sous une autre forme.

### 4.2 Génération des candidats

2119 personnes représentent 2,24 M de paires : ni scorables finement, ni soumettables au LLM. Le
filtre actuel de R10 (année de naissance obligatoire des deux côtés) résout ce volume au prix
d'un rappel désastreux — il exclut d'emblée toute personne sans date, et rend la règle 3 de
§4.1 impossible à déclencher.

**Approche retenue : blocking multi-clés.** Standard du record linkage, déterministe, testable
par tables, sans dépendance nouvelle. Les paires candidates sont l'**union** des blocs produits
par cinq clés :

| # | Clé | Rattrape |
|---|---|---|
| 1 | nom normalisé exact (prénom + patronyme) | le cas majoritaire, dont la fracture de casse (§3.2) |
| 2 | clé phonétique française du patronyme + initiale du prénom | variantes orthographiques : `Lelièvre` / `Le Lievre` → `lelievr`, `Jacquet` / `Jaquet` → `jak`, `Fouquet` / `Foucquet` → `fouk`, `Villaudy` / `Villaudi` → `vilaudi` |
| 3 | patronyme normalisé + année de naissance ± 2 | l'équivalent de R10, élargi |
| 4 | famille de conjoint commune | **les personnes sans date** |
| 5 | famille parentale commune | **les personnes sans date** |

Alternatives écartées : *embeddings + recherche par voisinage* (surdimensionné pour 2119
personnes, dépendance lourde, non déterministe) ; *balayage LLM par lots* (coûteux, non
reproductible, et contraire au principe « le LLM interprète, il ne calcule pas »).

**Clé phonétique** : fonction pure d'une trentaine de lignes, adaptée au français (`ph` → `f`,
`ch` protégé, `qu` → `k`, `c` → `k`, `y` → `i`, doubles lettres réduites, terminaisons muettes
retirées), testée par table. Préférée à une dépendance type `jellyfish` : un Soundex anglais gère
mal les patronymes français, et le besoin est trop étroit pour justifier une dépendance.

Ses limites sont assumées et documentées : elle rapproche les variantes de graphie qui partagent
la même ossature consonantique, mais **pas** les variations de voyelle interne — `Lelevre` donne
`lelevr` et ne rejoint pas `lelievr`. C'est acceptable parce qu'elle ne sert qu'au rappel et que
quatre autres clés opèrent en parallèle. Elle sépare par ailleurs correctement les familles
voisines de §3.1 : `Jacquet` → `jak` contre `Jacquier` → `jakier`, `Pagan` → `pagan` contre
`Pagani` → `pagani`.

**Garde de volume** : un bloc dépassant `MAX_BLOC` membres est ignoré et consigné au rapport.
Un patronyme très fréquent produirait sinon un nombre quadratique de paires — `Pagan` seul
(151 personnes) en génèrerait 11 325.

### 4.3 L'arbitrage par le LLM

L'étage intermédiaire est le seul où le LLM intervient — conformément au principe du projet
(« déterministe d'abord ; le LLM interprète, priorise, contextualise et rédige — il ne calcule
pas les anomalies »).

**Entrée** — un dossier compact des deux personnes : noms et noms alternatifs, dates et lieux de
naissance et de décès, **prénoms des parents, du conjoint et des enfants**, nombre de citations.

**Sortie** — JSON strict validé par un modèle Pydantic (précédent : `PropositionsLot`) :

- `verdict` : `fusion` | `distinct` | `indecis` ;
- `confiance` : entier **≤ 2**, même échelle et même plafond que `PropositionsLot` ;
- `phoenix` : l'ID retenu, et sa justification ;
- `piege_ecarte` : lequel des pièges connus a été examiné et écarté (frère homonyme, père/fils
  homonymes, jumeaux, lignée voisine du type `Pagan`/`Pagani`).

**Exécution** : aucune. Le LLM ne dispose d'aucun outil d'écriture ; sa sortie alimente le YAML
d'arbitrage. Rôle `detective`, modèle `MODEL_DETECTIVE` (`glm-5.2`), `is_litellm=True`.

C'est précisément là que le LLM apporte ce que le code ne sait pas faire : reconnaître que
*Johannes* et *Jean* désignent le même prénom, qu'une graphie ancienne correspond à une graphie
moderne, ou que `Pagani` est la forme italienne de `Pagan` — donc une filiation, pas un doublon.

### 4.4 Choix du phoenix et unique patch

**Choix du phoenix**, entièrement déterministe et reproductible. Critères appliqués dans cet
ordre, le premier qui départage l'emportant :

1. **score de complétude** — nombre de champs renseignés parmi : genre connu (`sex != "U"`),
   événement de naissance présent, événement de décès présent, date de naissance de précision
   au jour, lieu de naissance renseigné, au moins une famille parentale, au moins une famille
   conjugale ;
2. **nombre de citations** — le mieux sourcé l'emporte ;
3. **`gramps_id` le plus petit** — départage stable, garantissant qu'une seconde exécution sur
   les mêmes données choisit le même phoenix.

Ce classement porte sur la **grappe entière** (§4.5), pas sur une paire isolée.

**Un seul patch avant fusion — le genre.** C'est la conséquence directe de §2 : `Person.merge()`
ignore le genre, donc un phoenix « Inconnu » fusionné avec un titanic « M » perd le « M » sans
laisser de trace. Si `phoenix.sex == "U"` et `titanic.sex != "U"`, le genre du phoenix est mis à
jour par `PATCH` **avant** l'appel à `/merge`.

Ce n'est pas une inférence : c'est la préservation d'une valeur déjà enregistrée dans l'arbre.
ADR 0009 autorise déjà l'écriture du genre.

Aucun autre patch n'est nécessaire : le nom du titanic devient un nom alternatif, l'index de
naissance et de décès est adopté si le phoenix n'en a pas, et toutes les listes sont unionnées.
**Un patch, pas quinze.**

### 4.5 Grappes, et non paires

Si l'étage auto contient A ≈ B **et** B ≈ C, fusionner A/B **supprime B** ; l'appel B/C part
alors sur un handle mort et échoue en 404. Tout lot un peu dense se terminerait en erreurs.

L'exécution raisonne donc en **grappes** : union-find sur les paires de l'étage auto, un phoenix
unique par grappe (choisi selon §4.4 sur l'ensemble des membres), les autres membres fusionnés
dedans successivement.

## 5. Surface

Aucun verbe nouveau — `merge` gagne une feuille, la grammaire de l'ADR 0012 est respectée :

```bash
# détecte, fusionne l'étage auto, écrit le YAML d'arbitrage et le rapport
uv run genecrew merge people --scope all --limit 200 --dry-run

# exécute les paires d'arbitrage conservées après relecture
uv run genecrew merge people --yaml <arbitrage.yaml>
```

`--dry-run` par défaut simule (`effective_dry_run`, l'environnement ne pouvant que *forcer* la
simulation) — d'autant plus justifié que l'opération est irréversible. `--max-passes` borne la
boucle de convergence (§3.4) pour qu'une oscillation ne tourne pas indéfiniment.

Le rapport indique, par passe : fusions automatiques exécutées, paires envoyées en arbitrage,
paires rejetées, erreurs, et s'il faut relancer.

## 6. Découpage du code

Selon la règle du dépôt — la logique généalogique va dans la bibliothèque, l'orchestration reste
dans genecrew.

**`crewai_custom_tools`, sous `tools/genealogy/` :**

- `analysis/duplicates.py` — étendu : clés de blocage, clé phonétique, étagement. Pur.
- `analysis/merge_plan.py` — nouveau : grappes (union-find), choix du phoenix, décision de patch
  du genre. Pur.
- `models/domain.py` — `MergePair`, `MergeTier`, et le modèle du contrat LLM.
- `gramps/` — `GrampsMergePeopleTool`, calqué sur `GrampsMergePlacesTool`.

**`genecrew` :**

- `people_merge.py` — orchestration, passes, rapport.
- `cli.py` — la feuille `merge people`.
- `main.py` — le routage `(merge, people)`.

Contrainte de livraison inchangée : la bibliothèque doit être **taguée et poussée** avant que la
CI de genecrew puisse verdir, la CI checkoutant le voisin sur le tag lu dans `uv.lock`.

## 7. Tests

Le cœur du dispositif de sécurité est un **corpus de pièges**. Toutes les fonctions d'analyse
étant pures, il se teste hors ligne, par tables.

| Cas | Attendu |
|---|---|
| Frères homonymes (mêmes parents, même prénom, dates différentes) | jamais en auto |
| Jumeaux (mêmes parents, même date de naissance, prénoms différents) | jamais en auto |
| Père et fils homonymes (~28 ans d'écart) | jamais en auto |
| `Marie Pagan` / `Marie Pagani` | rejet, ou arbitrage — jamais auto |
| `sortval == 0` des deux côtés | ne compte jamais comme concordance |

Complété par :

- tables sur la clé phonétique et sur chacune des cinq clés de blocage ;
- choix du phoenix (complétude, puis citations, puis `gramps_id`) ;
- patch du genre : phoenix `U` + titanic `M` → patch émis ; phoenix `M` + titanic `U` → aucun
  patch ;
- grappes : A≈B et B≈C produisent une grappe unique à un seul phoenix, jamais deux appels dont
  le second porte sur un handle supprimé ;
- exécution sur client simulé, avec vérification qu'un `--dry-run` n'écrit **rien** ;
- convergence : une seconde passe sur des données déjà fusionnées rend zéro fusion.

## 8. Erreurs

Un échec de fusion est consigné dans le rapport et le lot continue, comme le fait déjà
`places_merge`. Un handle introuvable est traité comme une erreur consignée, non comme une
exception fatale — la logique de grappes (§4.5) doit toutefois rendre ce cas résiduel.

## 9. Hors périmètre

- La fusion des **familles**, **événements**, **sources** et **lieux** — les points de terminaison
  existent (`/api/families/…/merge/…`, etc.), et `family_merger: true` traite déjà les familles
  devenues doublons du fait d'une fusion de personnes. Le reste demande sa propre conception.
- La **rétro-alimentation du crew** : brancher les doublons sur `crew_audit.py:181`, qui les jette
  aujourd'hui, est un chantier distinct.
- La **calibration d'un seuil numérique** de confiance pour l'étage auto : l'étage auto ne repose
  sur aucun seuil, mais sur des règles structurelles booléennes. C'est délibéré (§1.3).
