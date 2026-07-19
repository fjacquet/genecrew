# Backlog — idées d'amélioration (différées)

Suivis non bloquants notés au fil de l'eau (revues, usage). Aucun n'est urgent ;
à piocher quand utile. Rangés par thème.

## UX / observabilité

- **Progression pendant les runs longs** — `names` / `gender-apply` / `apply-all` itèrent en
  silence (plusieurs minutes sur tout l'arbre), rapports écrits seulement à la fin. Ajouter une
  ligne de progression sur **stderr** au fil des lots (ex. `… 300 personnes traitées`), en gardant
  les chemins de rapport sur stdout. Décider : par défaut (interactif) vs derrière `--verbose`.
- **Surfacer les logs** — `facts.py` émet des `logger.warning` (404 personnes/familles) mais aucun
  `logging.basicConfig` n'est configuré → invisibles. Ajouter un flag `--verbose` /
  `GENECREW_LOG_LEVEL` qui active le logging.

## Robustesse / données cœur

- **Borner `gender`** dans `GrampsUpdateGenderTool` — accepte aujourd'hui n'importe quel `int`.
  Ajouter `Literal[0,1,2]` sur le schéma **et/ou** une garde dans `_run` (le path direct `_run`
  n'est pas validé par `args_schema`). Durcissement sur une écriture de fait. (Revue finale cct.)
- **`@api_tool` retry 429** — les outils Gramps lèvent des `httpx` alors que le retry teste des
  `requests.HTTPError` → le retry sur 429 ne se déclenche jamais pour Gramps. (Différé depuis Phase 1a.)

## Rapports / contrats

- **Liens `base_url` non-localhost** — les rapports (`report.py`, `names.py`, `gender_apply.py`)
  hardcodent `http://localhost` ; dériver l'URL web depuis la config client (`GRAMPS_API_URL`) pour
  des liens corrects hors déploiement localhost. (M1 revue finale gender-apply.)
- **Types `Literal` sur `Proposition`** — champs à ensemble fermé (`type`, `valeur_*`, `confiance`,
  `priorite`) en `str` libre ; les resserrer en `Literal[...]` pour que Pydantic garantisse le
  contrat du premier émetteur (avant que le pattern se répande aux lieux/dates). (Revue finale cct.)
- **Label `raison` à 3 valeurs** — le rapport des « indécidables » (gender inference) fond
  « unisexe » et « rare » en un seul libellé ; les séparer (unisexe / rare / non couvert).

## Garde-fous gender-apply (optionnels)

- **Warn `--min-ratio < 0.95`** — le plancher interne d'`infer_sex` (0.95) domine, donc un
  `--min-ratio 0.90` est silencieusement sans effet. Avertir (ou rejeter). (M2 revue finale.)

---

Voir aussi les gros chantiers (roadmap) dans `docs/document-de-travail.md` et la mémoire projet :
Standardisateur de **lieux**, et la vraie **crew CrewAI** (Détective/Historien/Chroniqueur) sur les
tâches de jugement.
