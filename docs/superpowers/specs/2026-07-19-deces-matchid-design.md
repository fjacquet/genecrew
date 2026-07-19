# Enrichissement décès déterministe (MatchID) — zéro LLM

> Conception validée le 2026-07-19 (chantier « déterministe d'abord », périmètre « MatchID
> d'abord »). Constat fondateur : les 554k tokens de la v5 n'ont rien trouvé qu'une règle
> ne trouve gratuitement. Le fichier des décès INSEE (1970+) via l'API MatchID se traite
> comme les lieux : requête + score déterministe + seuil, pas de jugement LLM.

## 1. Principe

Pour chaque personne plausiblement couverte par le fichier (née entre 1850 et aujourd'hui) :
requête MatchID (nom, prénom, date de naissance) → **score déterministe** du meilleur
candidat (patron du résolveur lieux) → selon l'état de l'arbre, une proposition typée :

- **compléter** — pas de décès dans l'arbre + correspondance ≥ seuil → proposer date+lieu
  de décès (avec acte et URL MatchID) ;
- **confirmer** — décès présent mais sans citation + INSEE concorde (même date) →
  proposer d'ajouter la source ;
- **contradiction** — décès présent mais date INSEE divergente + correspondance forte →
  proposer la vérification (priorité haute).

Un décès reste une **donnée cœur → toujours proposition**, jamais d'écriture automatique.
Sous le seuil : rien (pas de bruit).

## 2. Score déterministe

`score = 0.5·sim(nom) + 0.2·sim(prénom) + 0.3·concordance_naissance`, avec
`concordance_naissance` = 1.0 (date exacte YYYYMMDD), 0.7 (année seule), 0.0 (divergente —
élimine). `sim` = la similarité normalisée existante (`geo/score.similarity` : ASCII, casse,
espaces). Seuil défaut **0.95**. Le score ES de MatchID n'est qu'informatif (jamais décideur).

## 3. Composants

### cct (`feat/deces-scoring`, → 0.15.0)
- `tools/genealogy/matchid.py` : extraire `search_deces(last_name, first_name="",
  birth_date="", limit=10) -> list[dict]` (le `_run` du BaseTool l'appelle — un seul code
  HTTP) ; ajouter les fonctions **pures** `score_deces_match(surname, given, birth_iso,
  match) -> float` et `best_deces_match(surname, given, birth_iso, matches) ->
  tuple[dict, float] | None`.
- Tests offline : fixtures du payload réel (Odette Rippert) ; score fort/faible/éliminé ;
  année seule vs date exacte.

### genecrew (`feat/deces-enrichissement`)
- `src/genecrew/propositions.py` (créer) : `PropositionAudit`/`PropositionsLot` migrent ici
  depuis `crew.py` (module neutre, sans import crewai) ; `crew.py` ré-importe.
- `src/genecrew/deces.py` (créer) : `run_deces(client, scope, output_dir, *, date,
  min_score=0.95, batch_size=25, limit=None) -> tuple[Path, Path]` — itère les personnes
  (batching existant), sélectionne les candidates (année de naissance ∈ [1850, aujourd'hui]),
  interroge, score, construit les `PropositionAudit` (type `date`/`source`, `preuve_url` =
  lien MatchID, confiance 2 si date exacte, 1 sinon), rend rapport MD + YAML dans
  `output/deces/`. Lecture seule.
- `main.py` : sous-commande `genecrew deces --scope --limit --batch-size --min-score --date`.
- Tests offline : sélection des candidates ; les trois issues (compléter/confirmer/
  contradiction) ; sous le seuil → rien ; rapport/YAML.

## 4. Validation réelle
`uv run genecrew deces --scope all --limit 300` (couvre I0300 Odette Rippert, cas connu :
décès 19/12/2021 Bourges, acte 1511). Critère : la retrouve avec le bon type de proposition,
zéro faux positif choquant dans le rapport, coût LLM = 0.

## 5. Hors périmètre
Écriture des sources/citations (Phase 5) ; règles D internes (événement-des-parents,
coquille de siècle — tranche suivante) ; notes/tags déterministes.
