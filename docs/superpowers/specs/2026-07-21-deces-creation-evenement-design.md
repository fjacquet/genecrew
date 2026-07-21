# Création d'événements décès sourcés — `apply deaths`

> Conception validée le 2026-07-21. La v2 annoncée par l'ADR 0011 : les propositions
> `type: date` que la v1 laissait de côté. Une cible d'`apply` de plus, pas un verbe de plus.
>
> **Révisée le 2026-07-21**, après vérification du code réel. La première rédaction
> affirmait qu'aucun outil de création d'événement n'existait et prévoyait d'en construire
> deux. C'était faux, et l'erreur venait d'une sortie de `grep` tronquée lue comme
> complète. `GrampsCreateEventTool` existe et couvre l'essentiel. Le §5 dit ce qui est
> déjà là ; la v2 est bien plus petite qu'annoncé.

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
citations s'allonge*. La v2 la rompt, délibérément : elle **crée un fait** — un événement
décès, avec sa date et son lieu — et fait pointer le `death_ref_index` de la personne
dessus.

C'est le troisième assouplissement du même patron (0009 genre, 0010 lieux) : périmètre
étroit, garanti par le code et non par un prompt, réversible. Les garde-fous :

- **jamais auto** — YAML relu, passé explicitement ;
- **dry-run par défaut** ;
- **confiance 2 uniquement** — donc concordance de la date de naissance au jour près
  (`deces.py:101`), le seul discriminateur d'homonymie que le projet accepte ;
- **garde décès-absent** — §3, vérifiée au moment de l'écriture ;
- **tag + note** — §6, pour retrouver et annuler le lot en masse ;
- confiance Gramps de la citation plafonnée à 2 par l'outil.

Deux protections viennent gratuitement de `GrampsCreateEventTool` : il ne pose le
`death_ref_index` **que si la personne n'en avait pas** (un pointeur vital existant n'est
jamais écrasé), et il est strictement append-only sur tous les autres champs de la personne.

## 3. Le filtre, et pourquoi la garde reste nécessaire

Une proposition est appliquée si, **et seulement si** :

1. `type == "date"`
2. `confiance == 2`
3. `date_iso` est renseigné et complet (AAAA-MM-JJ)
4. la personne n'a **toujours pas** d'événement décès au moment de l'application

La condition 3 écarte les YAML produits avant l'ajout des champs structurés (§4) et toute
proposition dont la date serait incomplète ; le motif est distinct au rapport, pour qu'un
lot ancien ne se lise pas comme un lot vide.

La condition 4 semble doublonner deux fois : avec `deces.py:103`, qui n'émet un `type: date`
que si `person.death is None`, et avec la protection du `death_ref_index` dans l'outil
bibliothèque. Elle ne doublonne ni l'une ni l'autre.

- Contre `deces.py` : le YAML est produit à une date, relu à une autre, appliqué à une
  troisième ; l'arbre bouge entre-temps, à la main ou par une autre commande.
- Contre l'outil : celui-ci protège le **pointeur**, pas la **liste**. Sans la condition 4,
  une personne déjà décédée dans l'arbre se verrait créer un **second événement décès**,
  ajouté à son `event_ref_list` — invisible dans les vues qui suivent le `death_ref_index`,
  bien présent dans la base.

C'est donc la garde d'invariant de `apply deaths`, l'analogue du refus de tout changement
non-casse dans `apply case`. Une personne dont le `death_ref_index >= 0` est refusée et
comptée au rapport.

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

## 5. Ce qui existe déjà — et le seul ajout bibliothèque

Vérifié dans le code, pas supposé.

**`GrampsCreateEventTool`** (`write_tools.py:783`) fait déjà tout le travail d'écriture :

- POST de l'événement — `type` (chaîne nue, `"Death"`), `dateval` `[jour, mois, année]`
  complété en `[…, False]`, `modifier`, `quality`, `place` (handle nu), `citation_list` ;
- PUT de la personne — ajout d'un `EventRef` `{ref, role: "Primary"}` en append-only, et
  `death_ref_index` posé **uniquement si absent** ;
- un handle synthétique `DRYRUN:` de lieu ou de citation n'entre jamais dans un objet
  réellement écrit ;
- en cas d'échec du second write, il rend un **succès qualifié** — `attached: False`,
  `attach_error`, et le handle de l'orphelin — plutôt qu'une erreur qui perdrait le handle.

Il n'envoie **jamais** de `sortval`, et tourne en production depuis `import releve` : la
question du calcul côté serveur est donc déjà tranchée par l'usage, sans spike.

Existent aussi : `GrampsEnsureSourceTool`, `GrampsCreateCitationTool`,
`GrampsCreateNoteTool`, `GrampsEnsureTagTool`, `GrampsAttachTool` (note et/ou tag sur une
**personne** — `/people/` est codé en dur), et la conversion ISO → `dateval`
(`_dateval_iso`, `releves_import.py:438`).

**Le seul ajout bibliothèque de la v2 : les trois champs du §4.** Aucun outil nouveau.

## 6. La séquence d'écriture

`releves_import.py:481` contient déjà cette séquence sous le nom `_creer_evenement` —
lieu, citation, événement, décodage de l'orphelin. Elle est privée à ce module.

**Elle est extraite** vers `genecrew/src/genecrew/evenements.py`, avec `_dateval_iso`, et
importée par les deux surfaces. Une seule implémentation de « créer un événement sourcé »,
donc un seul endroit où le traitement de l'orphelin peut être juste ou faux.
`releves_import.py` (73 Ko de tests offline) verrouille le comportement pendant le
déplacement — c'est ce qui rend le refactor sûr.

Par proposition retenue :

1. `ensure_source` — INSEE ou Mémoire des hommes, `source_title_for` route sur
   `preuve_detail` ; mutualisé sur le lot (une source par registre, pas par personne)
2. `create_citation` — page = `citation_page(preuve_detail, preuve_url)`, la référence
   d'archive rejouable, confiance plafonnée à 2
3. résolution du lieu (§7) — sans création
4. `create_event` — type `Death`, `dateval` issu de `date_iso`, lieu et citation ;
   rattachement et `death_ref_index` compris
5. `create_note` — marqueur `[genecrew:deces:<date>]`, la phrase `action` de la
   proposition, et le `preuve_url`
6. `ensure_tag` — `genecrew:deces`
7. `attach` — note et tag **sur la personne**

**Note et tag vont sur la personne**, pas sur l'événement : `GrampsAttachTool` n'écrit que
sur `/people/`, et c'est le patron déjà éprouvé par `import releve`. Marquer l'événement
demanderait d'élargir l'outil à un `object_type` — un changement réel, remis à plus tard
faute d'en avoir besoin ici. Contrepartie assumée : une personne touchée par plusieurs
passages porte plusieurs marques, et le tag désigne la personne concernée plutôt que
l'objet exact créé.

L'ordre place les écritures irréversibles avant les écritures d'annotation. Si la note ou
le tag échoue, l'événement est déjà créé et correctement rattaché ; le rapport le dit, avec
les handles. L'API Gramps Web n'offre pas de transaction sur cette séquence : mieux vaut
une panne lisible qu'une panne cachée.

**Sur la note.** Elle fait volontairement doublon partiel avec la citation, qui porte déjà
la référence d'archive. Ce qu'elle ajoute, et que rien d'autre ne dit : *cet événement
a été créé par la machine, ce jour-là*. Une citation ne distingue pas un fait créé d'un
fait sourcé après coup.

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

**Aucun lieu n'est créé.** `releves_import.resoudre_ou_creer_lieu` fait la cascade complète
(résolveurs géo, hiérarchie, GPS) et **crée** le lieu manquant ; `apply deaths` ne
l'appelle pas. Créer un lieu est le métier de `propose places` / `apply places`, qui ont
leur propre cycle de relecture. Les y renvoyer garde chaque commande sur un seul type de
donnée cœur, et évite d'embarquer le réseau des résolveurs dans une commande qui n'en a pas
besoin. L'information n'est pas perdue : la commune figure déjà dans la page de citation.

## 8. Surface CLI, fichiers, ADR

`deaths` s'ajoute aux cibles d'`apply` dans `cli.py`, et `("apply", "deaths")` à la table
de dispatch de `main.py`. La grammaire à sept verbes ne bouge pas (ADR 0012) : c'est une
feuille de plus sous un verbe existant.

`apply citations` **ne change pas**. Il garde son sens strict — poser une citation sur un
objet existant — et son invariant append-only. Deux commandes lisent le même YAML et y
prennent des propositions disjointes (`type: source` d'un côté, `type: date` de l'autre) ;
la frontière entre « j'ajoute une source » et « je crée un fait » reste lisible depuis la
ligne de commande. `apply all` ne change pas non plus : il reste sur les écritures de forme.

Fichiers :

- **créé** `genecrew/src/genecrew/evenements.py` — la brique partagée extraite de
  `releves_import.py` (§6) ;
- **créé** `genecrew/src/genecrew/deces_event.py` — le filtre, l'index de lieux,
  l'orchestration et le rapport d'`apply deaths` ; plutôt qu'un gonflement de
  `deces_apply.py` (185 lignes, une responsabilité claire aujourd'hui). Il importe
  `citation_page` et `source_title_for` depuis `deces_apply`.

Rapport : `output/deces/<date>_apply_deaths_<stem>.md`, aux compteurs de la v1 —
événements créés, refusés (décès déjà présent), sans donnée machine exploitable (§3
condition 3), hors périmètre (type ou confiance), erreurs — plus la section « Lieux non
résolus ». La ligne `Mode:` reflète le dry-run **effectif**, variable d'environnement
comprise, pour ne jamais annoncer une écriture qui n'a pas eu lieu.

**ADR 0014** — création d'événements décès sourcés. Il énonce ce que la v2 relâche par
rapport à 0011 (§2) et ce qui l'encadre, et referme le « hors périmètre v2 » que 0011
avait laissé ouvert.

## 9. Tests

Offline, dans `genecrew/tests/`, au patron du dépôt : `httpx.MockTransport`, fixture
`GENECREW_DRY_RUN=false`, YAML écrit dans `tmp_path`.

Purs :

- conversion ISO → `dateval` — date complète ; année seule → `None` ; chaîne vide →
  `None` (comportement existant de `_dateval_iso`, verrouillé à l'endroit de sa nouvelle
  adresse) ;
- normalisation et résolution de lieu — unique, absent, ambigu ;
- le filtre des quatre conditions, **dont** le refus d'une personne ayant acquis un décès
  entre la proposition et l'application, et le refus d'un YAML sans champs structurés ;
- rendu du rapport, y compris la section « Lieux non résolus ».

Avec client simulé :

- la séquence complète en dry-run — aucune écriture, tous les handles `DRYRUN:` ;
- un événement créé mais non rattaché (`attached: False`) — le rapport doit porter le
  handle de l'orphelin ;
- un échec de note ou de tag après création réussie — l'événement reste rapporté comme créé.

`releves_import.py` garde sa suite existante inchangée : c'est elle qui prouve que
l'extraction du §6 n'a rien cassé.

Côté `crewai_custom_tools`, un test des trois nouveaux champs (défauts vides, YAML ancien
toujours chargeable).

## 10. Ordre de livraison entre les deux dépôts

La CI de genecrew checkoute le voisin sur le **tag** `v<version>` lu dans `uv.lock`, pas
sur `main` : sans tag poussé, elle ne peut pas verdir, et `uv sync --locked` refuse le lock.
Le seul changement bibliothèque étant les trois champs du §4 :

1. `crewai_custom_tools` — les trois champs de `PropositionAudit` et leur test ;
2. bump de version (0.23.1 → 0.24.0), **tag et push** ;
3. `uv sync` depuis la racine de genecrew ;
4. genecrew — `evenements.py` (extraction), `deces.py`, `militaires.py`,
   `deces_event.py`, `cli.py`, `main.py`, tests, ADR 0014, documentation.

Cette friction est un contrôle qualité délibéré, pas un obstacle à contourner.
