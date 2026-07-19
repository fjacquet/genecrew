# ADR 0011 — Écriture de citations INSEE sur les événements décès (deces-apply v1)

Date : 2026-07-19 — Statut : accepté

## Contexte

L'enrichissement décès déterministe (`genecrew deces`, spec 2026-07-19) produit des
propositions relues par l'humain. 38 propositions confiance 2 attendaient une injection
manuelle fastidieuse. ADR 0008 réserve les données cœur aux propositions ; 0009 (genre)
et 0010 (lieux) ont montré le patron d'assouplissement : périmètre étroit, garanti par
le code, réversible.

## Décision

`genecrew deces-apply --propositions <yaml>` écrit, pour les propositions **type
`source` et confiance 2 uniquement**, la chaîne : source « INSEE — Fichier des personnes
décédées » (une fois, idempotente) → citation (page = référence d'archive rejouable :
fichier/millésime, ligne, acte + permalien) → **ajout append-only** à la `citation_list`
de l'événement décès **existant**. Garanties dans le code, pas dans les prompts :

- **jamais auto** : la commande consomme un YAML explicitement passé (patron
  `lieux-merge`), relu par l'humain ;
- **dry-run par défaut** (`effective_dry_run`) ;
- confiance Gramps de la citation **plafonnée à 2** dans l'outil (`min(confidence, 2)`) ;
- idempotent : événement déjà citoyen de la source INSEE → ignoré ;
- aucune donnée cœur modifiée : ni date, ni lieu, ni lien — seule la liste de
  citations s'allonge.

## Hors périmètre (v2 sur ADR dédié)

Les propositions type `date` (créer l'événement décès manquant) : elles créent une
donnée cœur et suivront leur propre relecture.

## Conséquences

Les décès déjà présents dans l'arbre gagnent une source officielle rejouable sans
ressaisie ; l'historique des transactions Gramps reste la piste d'audit ; un retrait
de citation suffit à annuler.
