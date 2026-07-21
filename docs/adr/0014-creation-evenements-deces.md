# ADR 0014 — Création d'événements décès sourcés (`apply deaths`)

Date : 2026-07-21 — Statut : accepté

## Contexte

L'ADR 0011 a ouvert l'écriture des citations sur les décès **existants** (`type:
source`) et renvoyé explicitement à une v2 les propositions `type: date` — les décès
qu'une source officielle atteste mais que l'arbre ignore. Sur le lot du 2026-07-21 :
2 citations posées, 8 décès laissés à la ressaisie manuelle
(`output/deces/2026-07-21_apply_2026-07-21_propositions_deces_all.md`).

`GrampsCreateEventTool` existe déjà dans `crewai_custom_tools` et tourne en production
via `import releve` : il crée l'événement, le rattache à la personne, et ne pose le
`death_ref_index` que si la personne n'en avait pas.

## Décision

`genecrew apply deaths --yaml <yaml relu>` crée l'événement décès pour les propositions
**`type: date`, confiance 2, date ISO complète**, sur une personne **sans décès**. La
chaîne : source du registre (idempotente) → citation (référence d'archive rejouable) →
événement `Death` daté et situé, rattaché → note `[genecrew:deces:<date>]` et tag
`genecrew:deces` sur la personne.

C'est le troisième assouplissement de l'ADR 0008 (après 0009 genre, 0010 lieux), et le
premier qui **crée** une donnée cœur au lieu d'en corriger une. Garanti dans le code :

- **jamais auto** : la commande consomme un YAML explicitement passé, relu ;
- **dry-run par défaut** (`effective_dry_run`). L'aperçu produit en simulation est le seul
  garde-fou avant l'écriture irréversible : il doit donc rester complet et exploitable.
  `GrampsCreateEventTool` rend `attached: False` aussi bien pour un événement réellement
  orphelin que pour un passage simulé (rien n'est écrit, donc rien n'est rattaché) ;
  `creer_evenement_source` (`genecrew/src/genecrew/evenements.py`) distingue les deux et
  force `attache=True` en simulation. Sans cette distinction, un aperçu lirait chaque
  simulation comme un rattachement échoué, et l'appelant s'arrêterait là : la note, le tag
  et le reste de la chaîne ne seraient jamais simulés, et l'humain ne verrait pas dans son
  aperçu ce qui sera réellement écrit. Le rapport de simulation et celui d'écriture
  portent pour la même raison des **noms distincts** (`…_simulation.md` /
  `…_ecritures.md`, sur le dry-run effectif) : au même nom, la séquence nominale
  — simuler, relire, écrire — détruisait l'aperçu par l'écriture qu'il venait
  d'autoriser, et ne laissait rien à quoi confronter le résultat ;
- **confiance 2 seulement** : date de naissance concordante au jour près, le seul
  discriminateur d'homonymie accepté par le projet ;
- **garde décès-absent**, vérifiée au moment de l'écriture — l'outil protège le
  pointeur `death_ref_index`, pas la liste : sans cette garde, un lot périmé créerait
  un **second** événement décès, invisible dans les vues, bien présent en base ;
- **aucun lieu créé** : un lieu inconnu ou homonyme fait poser l'événement sans lieu,
  signalé au rapport et renvoyé à `apply places`. L'index de résolution ne retient que
  les types de **feuille** posés par les résolveurs `geo/` (`Municipality`, `City`) —
  liste d'inclusion, parce que l'ensemble des contenants s'allonge à chaque pays
  ajouté et qu'un contenant oublié rattacherait un décès à un département **en
  silence**. Un type imprévu, ou un lieu que `apply places` n'a pas encore
  standardisé (`Unknown`), tombe donc du côté sûr : non résolu, donc visible ;
- un événement créé mais non rattaché est rapporté **en erreur avec son handle**,
  jamais en succès. Il en va de même de la **citation**, seul objet créé avant le
  point de non-retour : dès que l'événement échoue, elle reste dans l'arbre sans que
  rien n'y mène, et son handle est la seule prise pour la supprimer.

`apply citations` ne change pas : les deux commandes lisent le même YAML et y prennent
des propositions disjointes.

## Conséquences

Les décès attestés par l'INSEE et par Mémoire des hommes entrent dans l'arbre sans
ressaisie, sourcés dès leur création. Le tag `genecrew:deces` permet de relire ou
d'annuler un lot en masse ; la suppression de l'événement suffit à revenir en arrière.

Contrepartie assumée : note et tag portent sur la **personne**, pas sur l'événement —
`GrampsAttachTool` n'écrit que sur `/people/`. Marquer l'événement lui-même demanderait
d'élargir cet outil à un `object_type`, remis au jour où le besoin se posera.
