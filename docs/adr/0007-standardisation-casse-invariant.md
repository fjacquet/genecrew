# 0007 — Standardisation de la casse des noms par écriture directe encadrée par invariant

| | |
|---|---|
| **Statut** | Accepté |
| **Date** | 2026-07-18 |
| **Source** | `docs/superpowers/specs/2026-07-18-standardisateur-noms-design.md` |

## Contexte

L'arbre Gramps « My Family Tree » a été importé depuis un GEDCOM Geneanet/Heredis ; les
patronymes y sont massivement **en capitales** (`JACQUET`), séquelle de l'import et non une
donnée voulue. Sur l'échantillon `samples/data.gramps` utilisé pour concevoir l'outil : 686
patronymes entièrement en capitales et 57 prénoms entièrement en capitales, contre 1428
patronymes déjà en casse mixte (vraisemblablement intentionnels, à ne pas toucher) ; 25 noms
contiennent en outre « ? » et 7 un chiffre — ce ne sont pas des problèmes de casse mais des
**faits incomplets**.

L'ADR 0001 interdit aux agents toute modification autonome d'un champ existant, y compris les
noms. Son raffinement du 2026-07-18 (voir ci-dessus) distingue désormais **forme** et **fait** :
une recapitalisation n'affirme aucun fait nouveau et ne requiert donc aucune source. Il fallait
une garantie **technique**, pas seulement documentaire, pour que cette écriture directe reste
conforme à l'exigence de preuve.

## Décision

- **Écriture directe, gardée par un invariant de casse** : `GrampsUpdateNameTool` (premier outil
  d'écriture de la bibliothèque généalogie) recapitalise `primary_name.first_name` et chaque
  `primary_name.surname_list[].surname`, mais **refuse** (`err(...)`, aucun PUT) tout changement
  qui ne serait pas purement une question de casse. L'invariant `is_case_only_change(old, new)`
  (`old.casefold() == new.casefold()`) est vérifié avant chaque écriture : l'outil peut donc
  seulement **recapitaliser**, jamais **ré-orthographier**. C'est ce qui rend l'écriture directe
  conforme au raffinement forme/fait de l'ADR 0001.
- **Cible restreinte** : `needs_normalization(name)` n'est vrai que pour un nom entièrement en
  capitales ou entièrement en minuscules (parties alphabétiques) ; un nom déjà en casse mixte
  (ex. `van Beethoven`) n'est **jamais** touché — cela protège les 1428 patronymes déjà corrects
  de l'échantillon de conception.
- **Noms incomplets listés, jamais écrits** : `is_incomplete_name(name)` détecte les noms
  contenant « ? » ou un chiffre ; ils sont uniquement **listés** pour recherche humaine
  (rapport `..._noms_a_verifier_<scope>.md`), jamais inventés ni écrits.
- **Casse de titre française déterministe** (`normalize_case`) : les particules (`de, du, des,
  d', la, le, les, von, van, der, den, ten, ter, zur, zum, y`) restent toujours en minuscule
  quand elles forment un mot entier, y compris en tête de nom (`LEROY → Leroy` mais
  `LE ROY → le Roy`) ; tout autre segment est capitalisé, y compris après un trait d'union ou une
  apostrophe élidée (`D'ABBADIE D'ARRAST → d'Abbadie d'Arrast`) ; `Mc`/`Mac` traités comme cas
  anglo-saxon léger.
- **Premier composant qui écrit dans Gramps** : `GrampsUpdateNameTool` inaugure le compte Gramps
  Web dédié `genecrew-ia` (rôle Editor) et un chemin d'écriture réel dans la bibliothèque
  généalogie — jusqu'ici tous les composants (`genecrew stats`, `genecrew audit`) étaient en
  lecture seule.
- **Défaut = écriture réelle** : `uv run genecrew names --scope all|person:ID [--limit N]
  [--dry-run]` écrit directement par défaut (choix utilisateur) ; `--dry-run` simule sans écrire
  et produit le même rapport, avec `dry_run: true`.
- **Périmètre v1** : `primary_name` uniquement (pas `alternate_names`) ; pas de restructuration
  du champ `prefix` (ce serait une modification structurelle/factuelle, pas de la forme) ; pas
  d'écriture par lots transactionnelle (`POST /api/objects/`).

## Conséquences

- Les recapitalisations sont visibles dans Gramps Web et dans l'historique des transactions
  Gramps (`GET /api/transactions/history/`) ; ne modifiant chacune que la casse, elles sont
  annulables individuellement (`POST …/{id}/undo`) — traçabilité et réversibilité conformes à
  celles déjà prévues par l'ADR 0001 pour les écritures autonomes.
- Toute violation de l'invariant de casse (changement qui ne serait pas purement de forme)
  produit une erreur (`err(...)`) sans écriture, journalisée dans la section « Erreurs » du
  rapport — jamais une écriture silencieusement incorrecte.
- Résultat du run terrain (`--scope all --limit 200`, arbre réel) : 4 corrections de casse
  trouvées (`JACQUET → Jacquet` ×2, `VILLAUDY → Villaudy` ×2), aucun nom incomplet sur cet
  échantillon. L'arbre réel s'est révélé déjà largement normalisé par rapport à l'échantillon
  hors ligne utilisé pour la conception (`samples/data.gramps`, 686 patronymes capitales). Cela
  ne remet pas en cause l'outil : il reste une capacité réutilisable, à relancer à chaque nouvel
  import de données (voir `docs/USER_GUIDE.md`, « Standardisation — noms »).
- Hors périmètre (YAGNI, cf. spec §9) : normalisation des lieux (spec séparée), `alternate_names`,
  restructuration du `prefix`, résolution des noms « ? » (recherche humaine), écriture par lots
  transactionnelle.
