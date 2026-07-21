# Import de relevés collés, avec smart match

> Conception validée le 2026-07-20. Une commande, une entrée : le copier-coller.
> Pas de source distante, pas de YAML intermédiaire, pas de nouveau verbe.

## 1. Ce que c'est

Tu colles un relevé trouvé en ligne. La commande l'interprète, cherche à qui il
correspond dans l'arbre, et écrit ce qui est certain. Le reste part au rapport.

```
genecrew import releve              # lit stdin — ton collage
genecrew import releve --file x.txt
```

`import` existe déjà (`import place`) : c'est une feuille de plus, pas un verbe de plus
(ADR 0012).

**Simulation par défaut.** `effective_dry_run` simule tant que `GENECREW_DRY_RUN=false`
n'est pas posé. Le premier passage ne peut donc rien casser, et c'est là qu'on regarde si
les verdicts tiennent avant de lâcher la main.

## 2. Pourquoi pas une source automatique

Mesuré, pas supposé : Geneanet n'expose aucune API de lecture publique, et ses CGU
définissent nommément le « robot » — tout outil reproduisant les actions d'un utilisateur
en vue de téléchargements de masse — pour en interdire l'usage, sous peine de résiliation
du compte. L'accès partenaire est réservé aux associations contributrices, pas aux
adhérents individuels.

Le collage manuel n'est donc pas un pis-aller en attendant mieux : c'est la seule entrée
légitime. La conception s'y range.

## 3. Les quatre étapes

1. **Lecture.** Le texte brut est conservé intégralement et recopié dans la note finale.
   Quoi qu'il arrive à l'interprétation, la source reste lisible dans l'arbre.
2. **Interprétation.** Un appel LLM, sortie JSON stricte validée par `ReleveIndexe`
   (sujet, événement, estimations, personnes liées et leur rôle, source, référence).
   Générique : aucun template par site. C'est la seule étape non déterministe, et la
   seule payante — un appel par collage.
3. **Appariement.** Déterministe. Blocage sur le patronyme normalisé
   (`pistes._normaliser`), puis pondération. Verdict `net`, `gris` ou `aucun`, toujours
   accompagné du détail des facteurs qui l'ont produit.
4. **Écriture.** Les `net` s'écrivent. Les `gris`, les `aucun` et les conflits vont au
   rapport.

Le LLM lit ; il ne décide pas. L'appariement — le seul endroit où une erreur écrit une
fausseté dans l'arbre — est du code testable hors-ligne.

## 4. La règle pesée

| Facteur | Poids | Raison |
| --- | --- | --- |
| Parent nommé concordant | très fort | Deux JACQUET du Cher ont rarement la même mère |
| Date d'événement complète identique | très fort | |
| Lieu d'événement identique | fort | Après le résolveur de lieux existant |
| Patronyme rare | fort | Rareté **comptée sur l'arbre** : VILLEPELLET pèse, JACQUET non |
| Prénom | faible | |
| Année approximative (±2) | faible | *Jamais discriminante seule* |

Trois clauses qui comptent plus que les poids :

- **La divergence est un veto, pas un malus.** Deux dates complètes contradictoires, ou
  deux lieux incompatibles, donnent `aucun` quel que soit le reste — un empilement de
  faibles concordances ne doit jamais écraser une contradiction franche.
- **Un facteur faible ne fait jamais un `net`**, ni seul ni à plusieurs. Il faut au moins
  un facteur fort.
- **`gris` est un verdict explicite**, pas l'effet de bord d'un seuil : candidats
  multiples à poids comparables. C'est le seul cas qui repart au LLM, et son volume est
  connu avant l'appel.

## 5. Ce qui s'écrit sur un `net`

Le verdict qualifie **l'identification de la personne, pas la fiabilité de chaque champ.**
Rose est bien Rose — sa naissance « vers 1821 » ne devient pas pour autant aussi solide
que sa date de décès.

| Le relevé donne | Sur un `net` |
| --- | --- |
| Événement + lieu + citation | Écrit. Si l'événement existe à la même date : citation seule, en confirmation |
| Naissance estimée | Écrite **seulement si l'arbre n'a rien**, en `about AAAA`. Ne remplace jamais une date connue |
| Parents nommés | Rattachés s'ils existent. Rapportés s'il faudrait les créer |
| Témoins, professions, alliances | Rapportés, jamais écrits — partie abrégée, la plus exposée à une mauvaise lecture |

**Sujet absent de l'arbre** (`aucun` candidat) : créé, avec sa citation. **Jamais un
parent.** L'asymétrie est volontaire : un sujet créé à tort est une fiche orpheline qu'on
supprime ; un parent créé à tort corrompt une filiation, et la filiation contamine tout ce
qui pend dessous.

**Zéro candidat doit être auditable.** La recherche préalable est large — variantes de
graphie, fenêtre de dates — et sa requête exacte figure au rapport. Sinon « absent » veut
dire « mal cherché », et on fabrique des doublons.

**Décisions de création (fixées le 2026-07-21).** Le §5 mandate trois écritures que la
première livraison avait à tort différées en « rapport ». Elles sont désormais construites,
avec ces deux choix tranchés :

- **Lieu d'un événement créé — cascade.** Quand l'import crée un événement (le décès d'un
  sujet créé, ou un décès absent d'un `net`), la commune du relevé est résolue puis créée
  si absente, avec sa hiérarchie et son géocodage, par la machinerie de lieux existante
  (`run_lieu_import` : mêmes résolveurs que `propose places`). Une résolution ambiguë ou
  sous le seuil ne crée aucun lieu : l'événement est posé sans lieu et le rapport le dit
  (jamais un lieu faux). L'extraction capte pour cela `evenement_departement` en plus de
  `evenement_pays`, sans quoi une commune homonyme ne se résout pas en France.
- **Genre d'un sujet créé — inféré.** Le prénom du sujet créé passe par l'inférence de genre
  déjà en place (table INSEE+OFS, `infer_sex`) ; prénom absent de la table ⇒ genre Inconnu
  (U). Cohérent avec `apply gender` (réversible), jamais un fait posé sans base.

La **filiation reste hors création** : un sujet créé n'est jamais rattaché automatiquement à
ses parents, même existants — l'asymétrie ci-dessus le proscrit. Les parents restent
rapportés.

## 6. Citation, idempotence, conflits

**La citation dit ce qu'elle est.** Source Gramps par fonds (« Cercle Généalogique du
Haut-Berry — relevés »), locator = la référence du relevé, confiance Gramps **`Normal`,
pas `High`** : un relevé est une source dérivée, pas l'acte. Écrire l'inverse ferait passer
un dépouillement pour un original. Ajoute une route dans `source_title_for()`, qui lève
aujourd'hui sur un registre inconnu plutôt que de retomber en silence sur l'INSEE.

**Idempotence : le patron des pistes, tel quel.** Marqueur portant l'identité, jamais la
date — `[genecrew:releve:<fonds>:<référence>]`. La référence du relevé est un identifiant
externe stable, donc pas de `cle_derivee`. Recoller le même relevé n'écrit rien.

**Les conflits ne s'écrasent jamais.** Un relevé qui contredit l'arbre produit une ligne
de conflit au rapport, pas une correction. Arbitrer deux sources est un travail de
généalogiste.

## 7. Tests

Hors-ligne, sur l'appariement, qui est pur. Fixtures à partir du relevé Rose JACQUET
(CGHB, réf. 106710046161418286). Quatre pièges à couvrir : le veto de divergence, le
patronyme rare contre le courant, « un faible ne suffit jamais », et l'idempotence au
second passage.

## 8. Hors périmètre

- Toute collecte distante (voir §2).
- Le traitement par lot d'un fichier d'export : si le CGHB fournit un jour un CSV,
  l'adaptateur fait vingt lignes et se branche à l'étape 3 en sautant le LLM. Rien à
  reconcevoir.
- L'extraction vers `crewai_custom_tools` : elle se fera si une deuxième source de relevés
  apparaît, pas avant.
