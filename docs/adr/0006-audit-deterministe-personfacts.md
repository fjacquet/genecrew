# 0006 — Audit déterministe : modèle PersonFacts/FamilyFacts et comparaison de dates par sortval

| | |
|---|---|
| **Statut** | Accepté |
| **Date** | 2026-07-17 |
| **Source** | `docs/document-de-travail.md`, §6.1 (Workflow 1 — Audit qualité) et §8.1 (tags) |

## Contexte

Le Workflow 1 (§6.1) est le socle de tout le pipeline : avant que le LLM n'interprète quoi que
ce soit, il faut détecter les incohérences mécaniques de l'arbre (âges impossibles, dates
malformées, doublons potentiels, absence de source) par des règles déterministes R1–R10,
gratuites et rejouables (ADR 0005 — « Déterministe d'abord »). Ces règles ont besoin d'un
modèle de faits normalisé par personne et par famille — construit une seule fois depuis l'API
Gramps Web — et d'une méthode fiable de comparaison de dates, sachant que la généalogie
manipule en permanence des dates partielles, approximatives ou inconnues (une naissance
« vers 1750 », un décès sans jour ni mois, un événement non daté du tout).

## Décision

- **Modèle normalisé** : les règles R1–R10 opèrent exclusivement sur `PersonFacts` /
  `FamilyFacts` (module `crewai_custom_tools.tools.genealogy.models.domain`), construits par des
  mappeurs purs (`person_from_json` / `family_from_json`, `genecrew/src/genecrew/facts.py`) à
  partir d'un seul appel liste ou détail à l'API Gramps Web avec
  `profile=all&extend=event_ref_list` — ce paramétrage ramène en un seul aller-retour les dates
  vitales brutes (avec leur `sortval`) et les décomptes de citations, sans appel supplémentaire
  par personne.
- **Comparaison de dates par `sortval`** : toute comparaison temporelle (âge, antériorité ou
  postériorité) utilise le `sortval` Gramps — un entier de jour julien calculé côté serveur qui
  reste comparable même pour des dates partielles ou approximatives. Une règle qui a besoin
  d'une date est **systématiquement ignorée quand cette date est inconnue** (`sortval == 0`) :
  l'absence de donnée ne produit jamais de faux positif, seule une date réellement incohérente
  en produit un.
- **Fonctions pures, hors ligne** : `check_person` et `check_family`
  (`crewai_custom_tools/tools/genealogy/analysis/rules.py`) sont des fonctions pures — entrées
  `PersonFacts`/`FamilyFacts` → sorties `list[Anomaly]`, sans appel réseau ni effet de bord. La
  Phase 1a **n'appelle aucun LLM et n'écrit rien dans Gramps** (ni tag, ni note) : elle se limite
  à la collecte (déterministe) et au rapport Markdown.
- **Règles R1–R10** (document-de-travail.md, §6.1) :

  | # | Règle |
  |---|---|
  | R1 | naissance postérieure au décès |
  | R2 | âge au décès > 105 ans |
  | R3 | mère < 13 ou > 55 ans à la naissance d'un enfant ; père < 13 ou > 80 |
  | R4 | mariage avant 13 ans |
  | R5 | enfant né après le décès de la mère, ou > 9 mois après celui du père |
  | R6 | événement daté hors de la vie de la personne |
  | R7 | baptême avant naissance ; inhumation avant décès |
  | R8 | dates malformées ou incohérentes (quality/modifier aberrants) |
  | R9 | personne ou événement sans source ni citation |
  | R10 | candidats doublons : nom normalisé (sans accents, minuscules) + naissance à ±2 ans + `difflib.SequenceMatcher` ≥ 0,85 |

- **Interfaces** : `uv run genecrew audit --scope <all|person:ID> [--limit N] [--batch-size N]
  [--date AAAA-MM-JJ]` (le périmètre `branch:ID` est différé à la Phase 1b, cf. Hors périmètre
  ci-dessous). Sortie : `output/audit/<date>_audit_<scope>.md`. L'audit étant rapide et sans
  coût LLM (~1 min pour tout l'arbre), il n'y a pas de reprise sur checkpoint à ce stade : un
  run interrompu se relance simplement depuis le début. Le module
  `genecrew/src/genecrew/checkpoint.py` existe déjà mais n'est pas câblé ici — le « resumable
  batching » est réservé à la Phase 1b (interprétation LLM, plus coûteuse).

## Conséquences

- **Ajustement terrain de R8** : le run réel (200 personnes de l'arbre, cf. rapport
  `output/audit/2026-07-17_audit_all.md`) a révélé que Gramps renvoie `dateval=[0,0,0]` /
  année `0` pour des événements non datés ; la règle R8 a été resserrée pour **ignorer les
  événements non datés** plutôt que de les signaler comme « date malformée », ce qui a supprimé
  un flot de faux positifs (commit `7fb658b` du dépôt `crewai_custom_tools`, « R8 skips undated
  events »). La règle ne signale désormais que les dates réellement hors bornes (jour > 31,
  mois > 12) ou une date apparente dont le `sortval` reste malgré tout non calculable.
- **Résultat du run terrain** (200 personnes, `--scope all --limit 200`) : environ 6 secondes,
  aucun coût LLM, aucune écriture Gramps ; 148 anomalies — 17 haute (R3 âges parentaux
  impossibles, R5 naissance après le décès d'un parent), 3 moyenne (R6/R7), 128 basse (R9,
  absence de source ou de citation) ; section doublons (R10) présente dans le rapport (aucun
  candidat sur cet échantillon). Ce résultat satisfait le critère de sortie de la Phase 1 (§9) :
  les anomalies de gravité haute correspondent à de vrais problèmes de l'arbre, sans faux
  positif observé en gravité haute ou moyenne sur l'échantillon.
- **Hors périmètre (→ Phase 1b)** : l'interprétation LLM des anomalies (élimination des faux
  positifs restants, classement contextuel), la pose des tags `ia-anomalie`/`ia-a-verifier`
  (§8.1), la génération PDF et le périmètre `branch:ID` restent à construire — la Phase 1a ne
  livre que le calcul déterministe et le rapport Markdown.
- Toute nouvelle règle ou tout nouveau champ de fait devra respecter la même contrainte : rester
  une fonction pure sur `PersonFacts`/`FamilyFacts`, et ignorer plutôt que deviner une date ou
  une quantité inconnue.
