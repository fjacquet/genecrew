# Standardisateur de noms — Design

| | |
|---|---|
| **Date** | 2026-07-18 |
| **Statut** | Validé — prêt pour le plan d'implémentation |
| **Périmètre** | Premier sous-système du Standardisateur (les lieux feront une spec séparée) |
| **Précède** | Phase 1a (audit déterministe) — réutilise son infra de lecture |

---

## 1. Contexte et intention

L'arbre Gramps « My Family Tree » (2119 personnes) a été importé depuis un GEDCOM
Geneanet/Heredis. Les patronymes sont massivement **en capitales** (`JACQUET`) — une séquelle
d'import, pas une donnée voulue. Mesures sur l'export `samples/data.gramps` :

- **686 patronymes entièrement en capitales** (à corriger).
- **1428 patronymes déjà en casse mixte** (probablement intentionnels — à **ne pas** toucher).
- **57 prénoms entièrement en capitales**.
- **25 noms contenant « ? »** et **7 contenant un chiffre** (faits incomplets, pas des problèmes de casse).

Le Standardisateur de noms **normalise la casse** de ces noms, et **liste** séparément les
noms « ? »/chiffres pour la recherche humaine.

## 2. Principe directeur : forme vs fait

Correction majeure du principe du projet (raffine l'ADR 0001) :

> **La preuve est requise pour les faits, pas pour la forme.**

- **Assertion factuelle** (une date, l'orthographe d'un nom, un lien de parenté, un lieu) →
  exige une source ; jamais de modification autonome.
- **Présentation / forme** (casse, espaces) → n'affirme aucun fait nouveau → aucune preuve
  nécessaire → **écriture directe autorisée**.

Normaliser `JACQUET → Jacquet` ne change pas le nom, seulement son écriture. La garantie
technique en est l'**invariant de casse** (§4) : l'outil ne peut écrire que si les deux formes
sont identiques une fois la casse repliée. Il peut donc *seulement recapitaliser, jamais
ré-orthographier*. C'est ce qui rend l'écriture directe conforme à l'exigence de preuve.

Les noms « ? » et à chiffres sont des **faits incomplets** : on ne les invente pas, on les
liste pour revue humaine.

## 3. Architecture

Suit le patron du projet : logique pure dans `crewai_custom_tools`, orchestration + CLI dans
`genecrew`.

### 3.1 crewai_custom_tools — logique pure (`tools/genealogy/standardize/names.py`)
- `normalize_case(name: str) -> str` — casse titre française (§5).
- `needs_normalization(name: str) -> bool` — vrai **uniquement** si `name` est entièrement en
  capitales ou entièrement en minuscules (parties alphabétiques) ; faux pour une casse déjà
  mixte ou une chaîne vide. C'est ce qui protège les 1428 noms déjà corrects.
- `is_case_only_change(old: str, new: str) -> bool` — l'invariant : `old.casefold() == new.casefold()`.
- `is_incomplete_name(name: str) -> bool` — vrai si `name` contient « ? » ou un chiffre (pour
  la liste de nettoyage).

### 3.2 crewai_custom_tools — outil d'écriture (`tools/genealogy/gramps/write_tools.py`)
- `GrampsUpdateNameTool` (`BaseTool`) : GET personne (par handle) → recase `primary_name.first_name`
  et chaque `primary_name.surname_list[].surname` → PUT. **Refuse** (renvoie `err(...)`) tout
  champ dont le changement viole `is_case_only_change`. Respecte `GENECREW_DRY_RUN` : en
  simulation, ne PUT pas et renvoie `ok({"dry_run": true, changements: [...]})`.
- Périmètre v1 : `primary_name` uniquement (pas les `alternate_names`).
- C'est le **premier outil d'écriture** de la bibliothèque généalogie : il inaugure le compte
  Gramps dédié `genecrew-ia` (rôle Editor) et le mode `GENECREW_DRY_RUN`.

### 3.3 genecrew — orchestration + CLI (`names.py` + sous-commande)
- `genecrew names --scope all|person:ID [--limit N] [--batch-size 25] [--dry-run]`.
- Réutilise l'infra d'audit : `FactsFetcher.list_people_facts` (lecture en lot), `scope.resolve_handles`.
- Pour chaque personne : calcule les corrections de casse candidates (patronymes + prénom),
  écrit via `GrampsUpdateNameTool` (ou simule si `--dry-run`), et collecte les noms incomplets.
- Sorties : `output/standardize/AAAA-MM-JJ_noms_<scope>.md` (rapport des changements
  faits/simulés) + `..._noms_a_verifier.md` (liste des noms « ? »/chiffres).
- Défaut = écriture réelle (choix utilisateur) ; `--dry-run` disponible pour un aperçu.

## 4. Garde-fous

1. **Invariant de casse** (structurel) : `GrampsUpdateNameTool` ne PUT jamais un champ dont la
   nouvelle valeur diffère de l'ancienne autrement que par la casse. Encodé dans l'outil, pas
   dans le prompt.
2. **Cible restreinte** : `needs_normalization` limite l'action aux noms tout-capitales /
   tout-minuscules ; les 1428 casses mixtes ne sont jamais modifiées.
3. **Traçabilité + réversibilité** : écritures faites par le compte `genecrew-ia`, visibles
   dans l'historique des transactions Gramps (`GET /api/transactions/history/`), annulables
   (`POST …/{id}/undo`).
4. **Aperçu optionnel** : `--dry-run` produit le rapport sans écrire.

## 5. Règles de casse (déterministes)

`normalize_case` applique une casse titre adaptée au français, testée par table :

| Cas | Entrée | Sortie |
|---|---|---|
| Simple | `JACQUET` | `Jacquet` |
| Particule interne | `BERNARD DE SAINT-AFFRIQUE` | `Bernard de Saint-Affrique` |
| Apostrophe | `D'ABBADIE D'ARRAST` | `d'Abbadie d'Arrast` |
| Trait d'union | `SAINT-AFFRIQUE` | `Saint-Affrique` |
| Mc/Mac | `MACDONALD` | `MacDonald` |
| Déjà mixte | `van Beethoven` | *(inchangé — `needs_normalization` = faux)* |

Règles :
- Découper sur les espaces et les traits d'union ; l'apostrophe est traitée à part (la
  particule élidée `d'` colle au mot suivant, ex. `d'Abbadie`).
- **Particules toujours en minuscule**, quelle que soit leur position (y compris en tête —
  un patronyme français peut légitimement commencer par `de`/`d'`). Liste de jetons :
  `de, du, des, d', la, le, les, von, van, der, den, ten, ter, zur, zum, y`. Ces jetons ne
  sont abaissés que lorsqu'ils sont un **mot entier** (donc `LEROY → Leroy`, mais `LE ROY → le Roy`).
- **Tout segment non-particule** est capitalisé (première lettre majuscule, reste minuscule),
  y compris après un trait d'union (`SAINT-AFFRIQUE → Saint-Affrique`) et après une particule
  élidée (`D'ABBADIE → d'Abbadie`).
- Mc/Mac suivis d'une lettre → `Mc`/`Mac` + majuscule (léger, cas anglo-saxon rare).
- Cohérence vérifiée sur les exemples du tableau : `D'ABBADIE D'ARRAST → d'Abbadie d'Arrast`
  (les deux `d'` en minuscule, `Abbadie`/`Arrast` capitalisés) ; `BERNARD DE SAINT-AFFRIQUE →
  Bernard de Saint-Affrique` (`de` en minuscule bien qu'interne, `Bernard`/`Saint-Affrique`
  capitalisés).
- Les segments purement numériques ou « ? » restent tels quels (mais `is_incomplete_name` les
  aura de toute façon dirigés vers la liste, pas vers l'écriture).

## 6. Flux de données

```
scope (--scope) ──> resolve_handles / list_people_facts (lecture en lot)
        │
        ▼  pour chaque personne
  primary_name (first_name, surname_list[].surname)
        │
        ├─ is_incomplete_name ? ──► liste "à vérifier" (aucune écriture)
        │
        ▼  sinon, par champ
  needs_normalization ? ──non──► ignorer
        │ oui
        ▼
  candidate = normalize_case(champ)
        │
        ▼
  is_case_only_change(champ, candidate) ? ──non──► ignorer + journaliser (anomalie de règle)
        │ oui
        ▼
  GrampsUpdateNameTool (PUT, ou simulation si --dry-run) ──► rapport
```

## 7. Tests

- **crewai_custom_tools** (100 % hors-ligne) :
  - `normalize_case` : table couvrant simple / particule / apostrophe / trait d'union / Mc-Mac
    / déjà-mixte-inchangé / vide.
  - `needs_normalization` : capitales → vrai, minuscules → vrai, mixte → faux, vide → faux.
  - `is_case_only_change` : même-casse → vrai, lettre différente → faux.
  - `is_incomplete_name` : « ? » → vrai, chiffre → vrai, normal → faux.
  - `GrampsUpdateNameTool` (mock httpx) : écriture réussie (PUT émis), refus d'invariant
    (aucun PUT, `err`), mode `GENECREW_DRY_RUN` (aucun PUT, `ok` avec `dry_run`).
- **genecrew** : fonctions pures d'orchestration (sélection des champs à corriger, construction
  du rapport) ; tests d'intégration CLI avec client mické.

## 8. Critère de sortie

`genecrew names --scope all --limit 200 --dry-run` produit un rapport des recapitalisations
proposées cohérent avec l'échantillon (patronymes capitales → casse propre, casses mixtes
ignorées) et une liste des noms « ? »/chiffres. Puis `genecrew names --scope all --limit 200`
(sans dry-run) applique réellement les changements, visibles dans Gramps Web et dans
l'historique des transactions, chacun ne modifiant que la casse.

## 9. Hors périmètre (YAGNI / plus tard)

- Normalisation des **lieux** (spec séparée — le gros chantier).
- `alternate_names` (v1 = `primary_name` seulement).
- Restructuration des patronymes dans le champ `prefix` de Gramps (c'est une modification
  structurelle/factuelle, pas de la forme).
- Résolution des noms « ? » (recherche humaine).
- Écriture par lots transactionnelle (`POST /api/objects/`) — optimisation ultérieure.

## 10. Impact sur la documentation

- **ADR 0001** à raffiner : la preuve est requise pour les faits, pas pour la forme ; les
  écritures purement formelles (casse, garanties par l'invariant) sont autorisées en direct.
- **Nouvel ADR** (« standardisation de la casse par écriture directe encadrée par invariant »).
- **USER_GUIDE** : section « Standardisation — noms ».
