# ADR 0013 — Fusion automatique des doublons de personnes sur preuve structurelle

Date : 2026-07-21 — Statut : accepté

## Contexte

Le document de travail (§ principes) posait une interdiction fondatrice : « Interdites aux
agents, toujours en proposition pour revue humaine : suppression, **fusion**, modification de
tout champ existant… ». La détection de doublons (règle R10) existait, mais ses candidats
n'allaient que dans un rapport Markdown : la fusion elle-même restait manuelle, dans l'interface
Gramps.

Deux constats ont motivé le changement :

1. **Le besoin réel** de l'utilisateur : « si on sait que c'est un doublon, je veux que le smart
   merge soit fait en API, pas manuellement par moi ».
2. **La mesure de l'arbre** : deux GEDCOM d'origines différentes réunis produisent beaucoup de
   doublons, souvent avec des parents eux-mêmes dupliqués. La déduplication est **transitive** et
   volumineuse — la faire à la main est le goulot.

Le danger est asymétrique et absolu : une fusion est **irréversible** (le doublon est supprimé,
les listes unionnées à plat). Rater un doublon coûte un doublon de plus ; fusionner à tort
**confond deux individus réels** de façon permanente et contamine leur descendance. Sur l'arbre,
`marie pagan` et `marie pagani` — les deux plus gros patronymes, ~10 % des personnes — ont 0,957
de similarité lexicale tout en étant des lignées distinctes : **la ressemblance de nom ne prouve
jamais l'identité**.

## Décision

L'interdiction de fusion est **relâchée de façon bornée**, dans l'esprit de l'ADR 0009 (écriture
du genre à haute confiance) qui avait déjà relâché l'ADR 0008 : la fusion **de personnes** devient
automatique **uniquement** sur une **preuve structurelle vérifiable**, exécutée par `merge people`.

Trois règles, et trois seulement, autorisent la fusion automatique (nom complet normalisé
identique exigé dans les trois cas) :

1. date de naissance **exacte** identique **et** mêmes père et mère ;
2. date de naissance **exacte** identique seule ;
3. même conjoint **et** au moins un enfant commun (couvre les personnes sans date).

Tout le reste est étagé en **arbitrage** (dossier déposé en YAML relu par un humain) ou **rejet**
(ressemblance de nom seule — jamais soumise). Les garde-fous :

- **Aucun seuil numérique.** Les règles sont des invariants booléens structurels, pas un score.
  C'est délibéré : le 2026-07-19, un seuil à 0,90 face à un score de 0,91 avait déclaré mortes
  trois personnes vivantes.
- **`date_complete` n'accepte que le modificateur exact.** « avant / après / environ / intervalle
  / span » bornent une date sans la fixer → arbitrage, jamais auto.
- **La similarité de nom (phonétique, `SequenceMatcher`) ne sert qu'au rappel** (générer des
  candidats), jamais à conclure.
- **Isolation d'écriture préservée (ADR 0001).** L'outil de fusion (`GrampsMergePeopleTool`)
  existe dans la bibliothèque mais **n'est câblé à aucun agent** du crew ; il n'est appelé que par
  l'orchestration déterministe `people_merge.py`. La garantie structurelle « aucun agent ne peut
  fusionner » tient.
- La suppression et les autres fusions (familles, événements, sources, lieux) **restent
  interdites** et hors de ce périmètre.

## Conséquences

- Nouvelle feuille CLI `merge people` (pas de verbe neuf — grammaire de l'ADR 0012 respectée).
- La commande est **relançable jusqu'à convergence** : fusionner des parents dupliqués débloque
  la règle « mêmes parents » à la passe suivante (transitivité).
- Une contradiction de genres entre doublons d'une même grappe, ou l'échec du patch de genre
  préalable, **abandonne** la grappe au lieu de fusionner (le genre n'est pas unionné par
  `Person.merge()` : le patcher après serait sans effet).
- Cet ADR **amende** la règle fondatrice du document de travail ; il ne l'abroge pas. Il s'inscrit
  dans la lignée de l'ADR 0005 (déterministe d'abord : le code calcule, le LLM interprète) — ici,
  la décision de fusion est **entièrement déterministe**, aucun LLM n'y intervient à l'étage auto.

Spec : `docs/superpowers/specs/2026-07-20-fusion-doublons-personnes-design.md`.
Voir aussi ADR 0001 (isolation d'écriture), 0005 (déterministe d'abord), 0009 (relâchement borné
d'une interdiction sur preuve forte), 0012 (grammaire CLI).
