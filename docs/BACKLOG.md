# Backlog — idées d'amélioration (différées)

Suivis non bloquants notés au fil de l'eau (revues, usage). Aucun n'est urgent ;
à piocher quand utile. Rangés par thème.

## UX / observabilité

- **Progression pendant les runs longs** — `apply case` / `apply gender` / `apply all` itèrent en
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
- **`>=3.11` promis mais jamais vérifié** — `pyproject.toml` déclare
  `requires-python = ">=3.11,<3.13"` ; la CI ne teste que 3.12 (pas de matrice, choix
  assumé au 2026-07-20). Soit ajouter `3.11` à une matrice `strategy.matrix.python`, soit
  restreindre la déclaration à `>=3.12`. En l'état, la promesse est invérifiée.

## Rapports / contrats

- **Liens `base_url` non-localhost** — les rapports (`report.py`, `names.py`, `gender_apply.py`)
  hardcodent `http://localhost` ; dériver l'URL web depuis la config client (`GRAMPS_API_URL`) pour
  des liens corrects hors déploiement localhost. (M1 revue finale apply gender.)
- **Types `Literal` sur `Proposition`** — champs à ensemble fermé (`type`, `valeur_*`, `confiance`,
  `priorite`) en `str` libre ; les resserrer en `Literal[...]` pour que Pydantic garantisse le
  contrat du premier émetteur (avant que le pattern se répande aux lieux/dates). (Revue finale cct.)
- **Label `raison` à 3 valeurs** — le rapport des « indécidables » (gender inference) fond
  « unisexe » et « rare » en un seul libellé ; les séparer (unisexe / rare / non couvert).

## Relecture des propositions militaires

- **Permalien Mémoire des hommes absent de 68,8 % du gazetteer** — mesuré le 2026-07-20 sur
  `militaires.sqlite` : `lien_ark` est vide pour 1 798 071 des 2 613 297 lignes. Le trou est
  structurel, pas aléatoire : seule la base *Guerre 1914-1918* en porte (39 % de ses lignes) ;
  *1939-1945* (413 621), *Indochine* (48 476), *Algérie/Maroc/Tunisie* (27 668), *Théâtres
  d'opérations extérieurs* (20 226) et toutes les autres sont à **100 % sans lien**.

  **L'URL n'est pas reconstructible** — vérifié, pas supposé : pour SOULAT Hoche, le permalien
  réel est `ark:40699/m00523be48140748`, alors que la ligne ne porte que
  `reference: arko_fiche_66deb7075d3e1` et un `source_fichier` mentionnant
  `arko_default_69a9869206744`. Trois identifiants sans relation dérivable. Fabriquer une URL
  par motif produirait des liens morts écrits dans Gramps *comme preuves* — le pire résultat
  possible pour une base généalogique.

  Conséquence : le pipeline exige une relecture humaine mais ne fournit la preuve cliquable que
  dans un tiers des cas. À traiter, par ordre de coût croissant :
  1. Faire dire au rapport de `propose military`, quand `preuve_url` est vide : « permalien
     absent de la source — chercher sur memoiredeshommes.defense.gouv.fr par nom + date de
     décès », plutôt que de laisser une colonne vide sans explication.
  2. Prévoir un champ où l'humain colle le permalien trouvé (le flux fonctionne déjà : le
     `preuve_url` du YAML part dans la page de citation Gramps — fait pour les frères Soulat).
  3. Étudier si l'API/moteur de recherche de Mémoire des hommes permet de résoudre
     `nom + date de décès` → ark. À vérifier contre le site réel, jamais par déduction.

## Sources de pistes écartées

- **Scriptorium (presse vaudoise, BCUL) — écarté le 2026-07-20**, sur mesure et non sur intuition.
  Mesuré sur `samples/data.gramps` (2119 personnes) : la Suisse pèse 25 lieux / 224 événements /
  **122 personnes**, mais elle est massivement **alémanique**. Le territoire de Scriptorium, le
  canton de Vaud, ne représente que 8 lieux / 12 événements / **9 personnes** (Romandie entière :
  19).

  S'y ajoute un doute sur l'accès : `docs/document-de-travail.md` annonçait « BCUL, OAI-PMH »,
  mais `https://www.scriptorium.ch/api` répond « MediaINFO API is up and running » — ni Omeka S ni
  OAI-PMH, et aucune documentation d'accès programmatique trouvée.

  **Condition de réouverture** : que la branche vaudoise s'étoffe sensiblement. Ne jamais y
  suppléer par du scraping — cela fabriquerait des URL consignées dans Gramps comme preuves, ce
  que le projet a déjà refusé sur Mémoire des hommes (voir plus haut).

  À noter, la dissymétrie avec le **DHS**, retenu lui : même origine géographique, mais il couvre
  la Suisse entière (122 personnes contre 9) et ne coûte qu'une projection de la propriété
  Wikidata P902. Voir `docs/superpowers/specs/2026-07-20-sources-archives-pistes-design.md`.

## Discoverabilité de la grammaire de verbes

- **`propose military` → `apply citations`, asymétrie non devinable** — cas réel : l'utilisateur a
  tenté `apply military`, puis le chemin du YAML en positionnel. La table de correspondance vit
  dans l'ADR 0012, c'est-à-dire nulle part au moment où on en a besoin. Deux remèdes : terminer
  le rapport de `propose military`/`propose deaths` par la commande exacte de la suite
  (`→ après relecture : genecrew apply citations --yaml <ce fichier>`), et/ou mentionner dans
  l'aide d'`apply` que `deaths` et `military` s'appliquent tous deux via `citations`.

## Garde-fous apply gender (optionnels)

- **Warn `--min-ratio < 0.95`** — le plancher interne d'`infer_sex` (0.95) domine, donc un
  `--min-ratio 0.90` est silencieusement sans effet. Avertir (ou rejeter). (M2 revue finale.)

---

Voir aussi les gros chantiers (roadmap) dans `docs/document-de-travail.md` et la mémoire projet :
Standardisateur de **lieux**, et la vraie **crew CrewAI** (Détective/Historien/Chroniqueur) sur les
tâches de jugement.
