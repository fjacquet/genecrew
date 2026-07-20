# Tranche outillage — outils d'analyse purs + APIs externes gratuites

> Conception validée le 2026-07-19 (découpage « A. Outils d'abord »). Prépare la Tranche 2
> (personas Historien + Standardisateur, propositions actionnables **entre** personas).

## 1. Contexte

Les personas à venir ont besoin d'outils que la bibliothèque ne expose pas encore aux agents :
les règles R1–R10 et le chercheur de doublons existent en **fonctions pures** (`analysis/`),
le moteur de résolution de lieux existe (`geo/`), mais **aucun n'est un outil CrewAI**. Côté
APIs externes, Wikidata, Gallica et le fichier des décès INSEE (MatchID) manquent — tous
gratuits. Décision utilisateur : livrer d'abord l'outillage (hors-ligne testable, 0 coût LLM),
puis les personas naîtront équipés.

## 2. Décisions actées

1. Tout dans **`crewai_custom_tools`** (branche `feat/outils-analyse-apis`), version → 0.13.0.
2. **Migration préalable `FactsFetcher`** : le mapping API→`PersonFacts`/`FamilyFacts` vit dans
   `genecrew/facts.py` alors que c'est de la logique domaine. Il migre dans cct
   (`tools/genealogy/gramps/facts.py`) ; genecrew importe depuis cct (comportement identique).
3. **Aucun outil d'écriture** dans cette tranche — lecture/analyse uniquement.
4. Les propositions actionnables ne sont PAS ici : elles émergeront de la collaboration entre
   personas (Tranche 2).

## 3. Les 6 outils

### Analyse pure (`tools/genealogy/analysis/tools.py`)

- **`genealogy_check_person`** — entrée `handle` → FactsFetcher + `check_person` + règles
  famille sur ses familles parentes → anomalies JSON (règle, gravité, message). Permet à un
  agent de re-vérifier une personne à la demande.
- **`genealogy_find_duplicates`** — entrée `surname` (optionnel, filtre) + `limit` (défaut 200,
  borne dure : jamais l'O(n²) plein arbre depuis un agent) → paires candidates scorées (R10).

### Résolveur de lieux (`geo/tools.py`)

- **`genealogy_resolve_place`** — entrée chaîne brute (« Bourges, Cher, France ») →
  `parse_pname` + `registry.resolve_place` → hiérarchie, GPS WGS84, score, source, action
  (`ecrire`/`proposition`/`indecidable`). Expose le moteur FR/CH/DE/US/monde déjà validé.

### APIs externes gratuites

- **`wikidata_sparql`** (`tools/web/wikidata.py`) — POST/GET `query.wikidata.org/sparql`,
  `format=json`, User-Agent dédié ; renvoie les bindings aplatis, tronqués à `limit`.
- **`gallica_search`** (`tools/web/gallica.py`) — SRU 1.2 `gallica.bnf.fr/SRU`
  (`searchRetrieve`, CQL) ; parse le XML Dublin Core → titre, date, type, ark/URL.
- **`insee_deces_search`** (`tools/genealogy/matchid.py`) — API MatchID
  (`deces.matchid.io/deces/api/v1/search`) : nom/prénom/date-lieu de naissance approx →
  décès INSEE post-1970 avec score. Critère Phase 4 du plan : retrouver un décès connu.

## 4. Patrons imposés (existants)

`BaseTool` + `args_schema` Pydantic ; `@api_tool(provider=…, endpoint=…)` ; enveloppe
`ok()/err()` ; client Gramps via `get_client()` ; docstrings et descriptions en anglais comme
le reste de la bibliothèque, sorties destinées aux agents.

## 5. Tests & validation

- Hors-ligne par outil : httpx.MockTransport (outils Gramps) / mock requests (outils web),
  fixtures réalistes relevées par sonde live unique pendant l'implémentation.
- Migration FactsFetcher : les suites genecrew (71) et cct passent inchangées.
- Validation réelle finale : `genealogy_resolve_place("Bourges, Cher, France")` → INSEE 18033 ;
  `insee_deces_search` retrouve un décès post-1970 connu de l'arbre ; `gallica_search` et
  `wikidata_sparql` renvoient des résultats plausibles sur un patronyme de l'arbre.

## 6. Exécution

Inline (TDD, commits par outil). cct `feat/outils-analyse-apis` (base edd2a5d) ; genecrew :
mise à jour des imports facts + uv sync (0.13.0) en fin de tranche.
