# Création d'événements décès sourcés — `apply deaths`

> Conception validée le 2026-07-21. La v2 annoncée par l'ADR 0011 : les propositions
> `type: date` que la v1 laissait de côté. Une cible d'`apply` de plus, pas un verbe de plus.

## 1. Ce que c'est

`propose deaths` interroge MatchID et produit trois familles de propositions. La v1
(`apply citations`, ADR 0011) n'en applique qu'une : `type: source`, l'ajout d'une citation
INSEE sur un événement décès **déjà présent** dans l'arbre. Les décès **absents** de l'arbre
— `type: date` — restaient à saisir à la main. Sur le lot du 2026-07-21 : 2 citations posées,
8 propositions renvoyées à la ressaisie manuelle.

La v2 les écrit.

```
genecrew apply deaths --yaml output/deces/2026-07-21_propositions_deces_all.yaml
genecrew apply deaths --yaml <fichier> --dry-run
```

**Simulation par défaut.** `effective_dry_run` simule tant que `GENECREW_DRY_RUN=false`
n'est pas posé dans `.env`. Comme `merge places`, la commande ne s'exécute jamais toute
seule : elle consomme un YAML explicitement passé, que l'humain a relu.

`militaires.py` émet exactement les mêmes propositions, du même moule (mêmes trois cas,
mêmes types, `source_title_for` route déjà Mémoire des hommes). Il hérite donc de la v2
sans une ligne de plus.

## 2. Ce que la v2 relâche, et ce qui l'encadre

L'ADR 0011 tenait une garantie forte : *aucune donnée cœur modifiée, seule la liste de
citations s'allonge*. La v2 la rompt, délibérément, et sur deux fronts :

- elle **crée un fait** — un événement décès, avec sa date et son lieu ;
- elle **modifie un scalaire de la personne** — le `death_ref_index`, sans lequel Gramps
  aurait l'événement en base mais ne le reconnaîtrait pas comme *le* décès de l'intéressé.

C'est le troisième assouplissement du même patron (0009 genre, 0010 lieux) : périmètre
étroit, garanti par le code et non par un prompt, réversible. Les garde-fous :

- **jamais auto** — YAML relu, passé explicitement ;
- **dry-run par défaut** ;
- **confiance 2 uniquement** — donc concordance de la date de naissance au jour près
  (`deces.py:101`), le seul discriminateur d'homonymie que le projet accepte ;
- **garde décès-absent** — voir §3, vérifiée au moment de l'écriture ;
- **tag + note** — voir §6, pour retrouver et annuler le lot en masse ;
- confiance Gramps de la citation plafonnée à 2 par l'outil.

## 3. Le filtre, et pourquoi la troisième condition n'est pas redondante

Une proposition est appliquée si, **et seulement si** :

1. `type == "date"`
2. `confiance == 2`
3. `date_iso` est renseigné et complet (AAAA-MM-JJ)
4. la personne n'a **toujours pas** d'événement décès au moment de l'application

La condition 3 écarte les YAML produits avant l'ajout des champs structurés (§4) et toute
proposition dont la date serait incomplète ; le motif est distinct au rapport, pour qu'un
lot ancien ne se lise pas comme un lot vide.

La quatrième condition semble doublonner avec la première : `deces.py:103` n'émet un
`type: date` que si `person.death is None`. Elle ne doublonne pas. Le YAML est produit à
une date, relu à une autre, appliqué à une troisième ; l'arbre bouge entre-temps, à la
main ou par une autre commande. C'est la **garde d'invariant** de `apply deaths`, l'analogue
du refus de tout changement non-casse dans `apply case` : une personne dont le
`death_ref_index >= 0` est refusée et comptée au rapport, jamais écrasée.

Le cas « dates divergentes » (`deces.py:124`, priorité haute) est exclu mécaniquement : il
naît en confiance 1. Trancher un conflit entre l'arbre et l'INSEE reste un geste humain,
sur pièce.

## 4. Le transport de la donnée machine

`deces.py:107` compose aujourd'hui une phrase française — *« Renseigner le décès :
2021-12-23 à Saint-Palais, avec la source INSEE en citation. »* La date ISO et la commune
n'existent que dans cette prose. Créer un événement demande un `dateval` et un handle de
lieu.

`PropositionAudit` (bibliothèque, `models/domain.py`) gagne trois champs **optionnels,
défaut vide** :

```python
date_iso: str = Field(default="", description="Date ISO du fait proposé (AAAA-MM-JJ).")
lieu_nom: str = Field(default="", description="Nom de la commune du fait proposé.")
lieu_code: str = Field(default="", description="Code lieu préfixé pays (ex. FR:18033).")
```

Optionnels parce que le modèle est le **vocabulaire partagé** du projet : les règles D
pures, le crew LLM et tous les pipelines déterministes émettent des `PropositionAudit`, et
la plupart n'ont rien à mettre dans ces champs. `deces.py` et `militaires.py` les
remplissent à l'endroit exact où ils composent déjà la phrase : une seule expression de la
donnée, deux rendus. La phrase reste ce que l'humain relit, les champs ce que la machine
applique. **Aucun parsing de prose nulle part** — la phrase française n'est pas un format
de données, et une reformulation ne doit jamais casser une écriture.

Un YAML produit avant ce changement se charge toujours (champs vides, pydantic content) et
sera refusé par `apply deaths` avec un motif explicite au rapport — pas un crash, pas une
écriture partielle.

`lieu_code` n'est pas consommé par la v2 (§7 résout par nom). Il est rempli dès maintenant
parce que la donnée est là, gratuite, au moment de la proposition — et parce que c'est la
clé qui permettra plus tard une résolution de lieu sans ambiguïté.

## 5. Deux outils nouveaux dans la bibliothèque

Aucun outil de création d'événement n'existe : `write_tools.py` s'arrête à
source / citation / note / tag / lieu / fusion. Deux ajouts, au patron des existants
(`args_schema` pydantic, décorateur `@api_tool`, `effective_dry_run`, retour `ok(...)`,
handle `DRYRUN:` en simulation).

Le schéma généré (`models/gramps_generated.py`) fixe les formes, vérifiées et non
supposées :

- `Event.type` est une **chaîne nue** (`"Death"`), pas un objet `EventType` ;
- `Event.place` est un **handle nu** ;
- `Event.date` est un `Date` : `dateval` (tableau mixte), `sortval`, `year`, `modifier`,
  `quality`, `calendar` ;
- `EventReference` porte `ref` et `role`.

**`GrampsCreateEventTool`** — crée un événement typé.
Entrées : `event_type`, `date_iso`, `place_handle` (optionnel), `citation_handles`,
`note_handles`, `tag_handles`, `dry_run`.
Il compose le `Date` Gramps depuis l'ISO : `dateval=[jour, mois, année, False]`,
`modifier=0` (date exacte), `quality=0`, `calendar=0` (grégorien), `year`, et le `sortval`
(voir §9). Une date incomplète (année seule) ou vide est **refusée** : une année seule
n'est jamais discriminante, règle projet.

**`GrampsAttachEventTool`** — rattache un événement à une personne.
Ajoute `{ref, role: "Primary"}` au `event_ref_list` **et** positionne le `death_ref_index`
sur le nouvel index quand le type est `Death`. Idempotent : un `ref` déjà présent n'est pas
ajouté deux fois.

## 6. La séquence d'écriture

Par proposition retenue :

1. `ensure_source` — INSEE ou Mémoire des hommes, `source_title_for` route déjà sur
   `preuve_detail` ; mutualisé sur le lot (une source par registre, pas par personne)
2. `create_citation` — page = `citation_page(preuve_detail, preuve_url)`, la référence
   d'archive rejouable, confiance plafonnée à 2
3. `ensure_tag` — `genecrew:deces`
4. `create_note` — marqueur `[genecrew:deces:<date>]`, la phrase `action` de la
   proposition, et le `preuve_url`
5. `create_event` — citation, note et tag **déjà dans ses listes** : l'événement naît
   complet
6. `attach_event` — sur la personne, plus le `death_ref_index`

L'ordre est choisi pour la forme de la panne. L'API Gramps Web n'offre pas de transaction
multi-objets sur cette séquence ; le seul échec partiel possible est donc un événement
complet mais **orphelin** (étape 6 en échec). Le rapport imprime alors son handle en clair
sous « Erreurs », pour que la reprise ou le nettoyage se fasse sans fouiller la base. Mieux
vaut une panne lisible qu'une panne cachée.

**Sur la note.** Elle fait volontairement doublon partiel avec la citation, qui porte déjà
la référence d'archive. Ce qu'elle ajoute, et que rien d'autre ne dit : *cet événement
lui-même a été créé par la machine, ce jour-là*. Une citation ne distingue pas un fait créé
d'un fait sourcé après coup. Le tag donne le filtrage en masse dans Gramps Web (relire le
lot, en supprimer un ou tous) ; la note donne le contexte quand on ouvre l'événement.

## 7. Le lieu

Un index `nom normalisé → handle` est construit une fois par lot sur les lieux de l'arbre,
au patron de `_seed_parent_index` (`places_apply.py:28`). Normalisation : casse, accents,
tirets et espaces.

- correspondance **unique** → `place` posé sur l'événement ;
- **zéro** correspondance, ou **plusieurs** → événement créé **sans lieu**, commune listée
  dans une section « Lieux non résolus » du rapport.

Refuser l'ambiguïté plutôt que deviner : deux lieux homonymes dans l'arbre, c'est
exactement la situation où un choix automatique rattacherait un décès à la mauvaise
commune, sans que rien ne le signale.

**Aucun lieu n'est créé.** Créer un lieu — hiérarchie, code INSEE, GPS, résolveurs géo
routés par pays — est le métier de `propose places` / `apply places`, qui ont leur propre
cycle de relecture. Les y renvoyer garde chaque commande sur un seul type de donnée cœur,
et évite d'embarquer le réseau des résolveurs dans une commande qui n'en a pas besoin.
L'information n'est pas perdue : la commune figure déjà dans la page de citation.

## 8. Surface CLI, fichiers, ADR

`deaths` s'ajoute aux cibles d'`apply` dans `cli.py`, et `("apply", "deaths")` à la table
de dispatch de `main.py`. La grammaire à sept verbes ne bouge pas (ADR 0012) : c'est une
feuille de plus sous un verbe existant.

`apply citations` **ne change pas**. Il garde son sens strict — poser une citation sur un
objet existant — et son invariant append-only. Deux commandes lisent le même YAML et y
prennent des propositions disjointes (`type: source` d'un côté, `type: date` de l'autre) ;
la frontière entre « j'ajoute une source » et « je crée un fait » reste lisible depuis la
ligne de commande. `apply all` ne change pas non plus : il reste sur les écritures de forme.

Nouveau fichier `genecrew/src/genecrew/deces_event.py`, plutôt qu'un gonflement de
`deces_apply.py` (185 lignes, une responsabilité claire aujourd'hui). Les deux partagent
`citation_page` et `source_title_for`, importés depuis `deces_apply`.

Rapport : `output/deces/<date>_apply_deaths_<stem>.md`, aux compteurs de la v1 —
événements créés, refusés (décès déjà présent), sans donnée machine exploitable (§3
condition 3), hors périmètre (type ou confiance), erreurs — plus la section « Lieux non
résolus ». La ligne `Mode:` reflète le dry-run
**effectif**, variable d'environnement comprise, pour ne jamais annoncer une écriture qui
n'a pas eu lieu.

**ADR 0014** — création d'événements décès sourcés. Il énonce ce que la v2 relâche par
rapport à 0011 (§2) et ce qui l'encadre, et referme le « hors périmètre v2 » que 0011
avait laissé ouvert.

## 9. À vérifier avant d'écrire le code applicatif

Deux points que le schéma généré ne tranche pas, et sur lesquels il ne faut pas parier.
C'est la **première tâche du plan** :

1. **Le `sortval` est-il calculé côté serveur au POST ?** Si oui, ne pas l'envoyer ; sinon,
   le calculer côté client (jour julien grégorien = `date.toordinal() + 1721425`). Un
   `sortval` faux ou nul casserait silencieusement tout le tri chronologique et les
   règles R/D qui s'appuient dessus.
2. **Le `death_ref_index` est-il recalculé par l'API** quand on PUT une personne dont le
   `event_ref_list` contient un nouveau `Death` ? Si oui, ne pas le poser ; sinon, le poser
   explicitement.

Méthode : un aller-retour sur une personne de test — POST d'un événement décès daté, GET
de l'événement et de la personne, lecture de `sortval` et de `death_ref_index`, puis
nettoyage. Les deux questions se tranchent d'un coup.

## 10. Tests

Offline, dans `genecrew/tests/`, au patron existant du dépôt.

Purs :

- composition du `Date` Gramps depuis un ISO — date complète ; année seule → refus ;
  chaîne vide → refus ; calcul du `sortval` ;
- normalisation et résolution de lieu — unique, absent, ambigu ;
- le filtre des quatre conditions, **dont** le refus d'une personne ayant acquis un décès
  entre la proposition et l'application, et le refus d'un YAML sans champs structurés ;
- rendu du rapport, y compris la section « Lieux non résolus ».

Avec client simulé :

- la séquence complète des six étapes en dry-run — aucune écriture, tous les handles
  `DRYRUN:` ;
- l'échec de l'étape 6, qui doit produire un orphelin **signalé avec son handle**.

Côté `crewai_custom_tools`, sa propre suite offline pour les deux nouveaux outils.

## 11. Ordre de livraison entre les deux dépôts

La CI de genecrew checkoute le voisin sur le **tag** `v<version>` lu dans `uv.lock`, pas
sur `main` : sans tag poussé, elle ne peut pas verdir, et `uv sync --locked` refuse le lock.
Les deux outils vivant dans la bibliothèque, l'ordre est contraint :

1. `crewai_custom_tools` — les trois champs de `PropositionAudit`, les deux outils, leurs
   tests ;
2. bump de version, **tag et push** ;
3. `uv sync` depuis la racine de genecrew ;
4. genecrew — `deces.py`, `militaires.py`, `deces_event.py`, `cli.py`, `main.py`, tests,
   ADR 0014, documentation.

Cette friction est un contrôle qualité délibéré, pas un obstacle à contourner.
