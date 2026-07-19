# Règles D internes + gazetteer « Morts pour la France » (Canopé) — zéro LLM

> Conception validée le 2026-07-19 (« Les deux »). Suite du chantier « déterministe
> d'abord » : reproduire gratuitement les deux trouvailles de la crew v5, puis un
> premier fournisseur de preuves 14-18 (couverture partielle assumée : 12 186 fiches).

## 1. Tranche A — règles D internes (détecteurs de corrections)

Deux détecteurs **purs** dans cct (`analysis/corrections.py`), émis par l'audit :

- **D-mariage-des-parents** (cas I0010) : un événement non-Birth/Death de la personne,
  daté AVANT sa naissance, dont le `sortval` égale exactement celui du mariage d'une de
  ses familles parentales → proposition `relation` : « détacher l'événement (c'est le
  mariage des parents), le rattacher à la famille F… ». Confiance 2 (données internes
  concordantes), priorité moyenne.
- **D-coquille-de-siècle** (cas I2002) : naissance incompatible avec les parents (parent
  décédé avant, ou âge parental > 100 ans à la naissance) ET `année − 100` redevient
  plausible (parents vivants, âgés de 15–60 ans ; cohérent avec la fratrie ± 25 ans) →
  proposition `date` : « remplacer par about (année−100), vérifier la citation d'abord ».
  Confiance 1, priorité haute.

**Modèle partagé** : `PropositionAudit`/`PropositionsLot` migrent de genecrew vers cct
`models/domain.py` (vocabulaire de bibliothèque, pydantic pur) ; `genecrew/propositions.py`
devient un ré-export (aucun import consommateur ne change).

**Émission** : `collect_audit_findings` retourne désormais
`(anomalies, duplicates, all_people, propositions)` — les détecteurs tournent dans la
boucle famille existante (contexte parents/fratrie déjà chargé, zéro fetch en plus).
`run_audit` écrit en plus `<date>_propositions_audit_deterministes_<scope>.yaml` ;
`crew_audit` ignore le 4e élément pour l'instant.

## 2. Tranche B — gazetteer MPF (Canopé, 12 186 fiches)

- **Donnée** : CSV Canopé (data.gouv, indexation participative de Mémoire des hommes),
  réduit aux colonnes utiles et embarqué dans cct `data/mpf_canope.csv` (~1,5 Mo) —
  patron du gazetteer allemand. Couverture **0,9 %** de la base 1914-18 : assumé,
  documenté dans le rapport ; le lien `images-href` pointe la **fiche image officielle**.
- **Matching** (`tools/genealogy/mpf.py`, pur, hors-ligne) : `load_mpf()` (cache),
  `best_mpf_match(surname, given, birth_iso, birth_place) -> (row, score) | None`.
  Score : 0.40·sim(nom) + 0.15·sim(prénom) + naissance (0.35 date complète exacte /
  0.15 année seule) + 0.10·sim(lieu de naissance). Seuil 0.90 → **la date complète est
  requise en pratique** (règle : l'année seule ne prouve jamais). Ambiguïté 0.05 →
  abstention. Le nom Canopé est « Prénoms NOM » (patronyme en capitales finales) → parseur.
- **CLI** `genecrew mpf --scope --limit` : candidates = personnes nées 1866–1904 sans
  décès sourcé ; issues completer/source/contradiction comme `deces` ; preuve_url = lien
  fiche Mémoire des hommes. Lecture seule.

## 3. Tests & validation

Tout hors-ligne (fixtures réelles). A : détecteurs purs (cas I0010/I2002 reconstitués,
cas négatifs), audit émet le YAML. B : parseur de nom, scoring (date complète requise),
CLI. Validation réelle : `genecrew audit --scope all --limit 300` doit re-trouver
I0010 + I2002 en propositions **gratuites** (ce que la crew a payé 554k tokens) ;
`genecrew mpf --scope all` sur tout l'arbre (rapide, hors-ligne).

## 4. Exécution

cct `feat/regles-d-et-mpf` (→ 0.16.0) ; genecrew `feat/corrections-deterministes`.
