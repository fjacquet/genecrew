# Tranche 2 — chaîne complète à 4 personas, propositions actionnables entre personas

> Conception validée le 2026-07-19 (architecture « A. Chaîne enrichie »). S'appuie sur la
> tranche outillage (cct 0.13.0) et la crew Audit validée live.

## 1. Principe

`crew-audit` passe de 2 à **4 agents séquentiels** ; les propositions actionnables émergent
de la collaboration (décision utilisateur : « entre les personas ») :

1. **Détective** — constate (inchangé : interprète les anomalies déterministes).
2. **Historien Contextuel** — cherche la **preuve** là où une source peut trancher
   (anomalies fermes + personnes sans source) : `insee_deces_search`, `gallica_search`,
   `wikidata_sparql`, Wikipédia, lecture Gramps. Ramène URL + requête rejouable + degré de
   correspondance. **Une piste n'est jamais un fait.** Discipline de coût : ≤ 4 appels
   d'outil par personne, ne recherche pas les cas où aucune source ne peut aider.
3. **Standardisateur** — convertit verdict + preuve en **proposition précise** : objet
   Gramps visé, action exacte, preuve, priorité, confiance (**plafonnée à 2/4** — seul
   l'humain monte au-dessus). Outils : `genealogy_check_person`, `genealogy_find_duplicates`,
   `genealogy_resolve_place`, `gramps_get_object`. Sortie **structurée** (`output_pydantic`)
   — jamais de parsing de texte libre.
4. **Chroniqueur** — inchangé (notes + tags append-only, seul écrivain).

## 2. Décisions actées

- YAML de propositions = **seulement les personnes avec action** (décision antérieure).
- L'émission du YAML est **déterministe** (orchestrateur, depuis la sortie Pydantic du
  Standardisateur) — le LLM ne rédige pas de YAML.
- **Multi-modèles par agent** (décision n°2 du plan initial) : `build_llm(role)` lit
  `MODEL_<ROLE>` (ex. `MODEL_HISTORIEN`) avec repli sur `MODEL`.
- Aucun nouvel outil d'écriture ; Historien et Standardisateur n'écrivent pas
  (isolation structurelle identique).

## 3. Composants (tout dans genecrew)

- `crew.py` : agents `historien` + `standardisateur` (outils ci-dessus), `build_llm(role)`,
  modèles Pydantic `PropositionAudit` (type, gramps_id, handle, personne, cible, action,
  preuve_url, preuve_detail, priorite, confiance ≤ 2) et `PropositionsLot` ;
  `output_pydantic=PropositionsLot` sur la tâche du Standardisateur.
- `config/agents.yaml` : personas historien/standardisateur (français).
- `config/tasks/audit.yaml` : + `rechercher_preuves` (historien) et
  `formuler_propositions` (standardisateur), insérées entre l'interprétation et la greffe.
- `crew_audit.py` : extrait `PropositionsLot` de `tasks_output` après chaque lot (repli
  gracieux si le LLM n'a pas structuré : avertissement loggé, lot compté 0, signalé au
  rapport) ; écrit `<date>_propositions_audit_<scope>.yaml` (toujours, même vide) ;
  rapport MD/YAML : compteur de propositions + section par lot.

## 4. Tests & validation

- `test_crew_wiring.py` : 4 agents ; isolation d'écriture (seul le chroniqueur a les
  3 write tools ; historien/standardisateur zéro write) ; `build_llm("historien")` lit
  `MODEL_HISTORIEN` puis retombe sur `MODEL`.
- `test_crew_audit.py` : fake crew avec `tasks_output` structuré → YAML propositions
  écrit ; lot sans sortie structurée → repli sans crash.
- Bout-en-bout live dry-run `--limit 25` (coût réel LLM → go utilisateur explicite),
  coût/lot comparé aux 231k tokens de la chaîne à 2 agents.

## 5. Exécution

Inline, TDD, genecrew branche `feat/crew-chaine-complete`. cct inchangé (0.13.0 suffit).
