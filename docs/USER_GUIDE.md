# GeneCrew — Guide d'utilisation

Ce guide couvre l'usage courant de GeneCrew, phase par phase. **Chaque phase ajoute sa
section** : ce document n'est complet qu'après la Phase 6 (voir le phasage,
`docs/document-de-travail.md`, §9). Pour l'instant, la Phase 0 (« Plomberie ») et la Phase 1a
(« Audit déterministe », le socle sans LLM de la Phase 1 — voir §9) sont livrées, ainsi qu'un
premier sous-système du Standardisateur : la standardisation de la casse des noms (voir
« Standardisation — noms » plus bas).

---

## Phase 0 — Plomberie

Livrable de la Phase 0 : client Gramps en lecture seule + modèles générés + dépendance
`genecrew` → `crewai_custom_tools` + CLI `genecrew stats`. Critère de sortie (§9 du document de
travail) : `uv run genecrew stats` affiche les statistiques identiques au tableau de bord
Gramps Web.

### Prérequis

- `uv` installé.
- Une instance **Gramps Web** accessible (voir ci-dessous — ce n'est **pas** ce dépôt qui la
  démarre).
- Le dépôt frère `crewai_custom_tools` cloné à côté de `genecrew`, sous
  `/Users/fjacquet/Projects/crewai_custom_tools` (dépendance éditable déclarée dans
  `genecrew/pyproject.toml`, voir `docs/document-de-travail.md`, §3.4).

#### Démarrer Gramps Web

Le fichier `docker-compose.yml` qui vivait à la racine de ce dépôt a été **supprimé** : il
était redondant avec la pile Gramps Web déjà provisionnée par le projet frère
**`gramps-mcp`**. GeneCrew **ne démarre pas** Gramps Web lui-même et **il ne faut pas**
recréer de `docker-compose.yml` ici, ni lancer `docker compose` depuis ce dépôt.

Pour disposer d'un Gramps Web local, utiliser le docker-compose du projet `gramps-mcp` (dépôt
frère, sous `/Users/fjacquet/Projects/gramps-mcp`) :

```bash
cd /Users/fjacquet/Projects/gramps-mcp
docker compose up -d
```

Cela démarre notamment les conteneurs `gramps-mcp-grampsweb-1`, `grampsweb_celery`,
`grampsweb_redis` et `gramps-mcp-grampsweb_postgres-1`. Gramps Web est alors exposé sur le port
hôte `80`.

### Installation des dépendances

Depuis la racine du dépôt `genecrew` :

```bash
uv sync
```

### Configuration (`.env`)

Copier `genecrew/.env.example` vers `genecrew/.env` et renseigner les valeurs (jamais commiter
ce fichier — il est exclu par `genecrew/.gitignore`). Clés attendues, telles que listées dans
`genecrew/.env.example` :

| Clé | Rôle |
|---|---|
| `MODEL` | modèle LiteLLM par défaut |
| `GRAMPS_API_URL` | URL de base de l'API Gramps Web |
| `GRAMPS_USERNAME` | compte Gramps Web (lecture seule suffit en Phase 0) |
| `GRAMPS_PASSWORD` | mot de passe du compte ci-dessus |
| `GENECREW_DRY_RUN` | simule les écritures (défaut `true`) |
| `GENECREW_BATCH_SIZE` | taille des lots (défaut `25`) |
| `GENECREW_OUTPUT_DIR` | dossier des rapports d'audit (défaut `output/`) |

Aucune valeur n'est donnée ici volontairement — voir `genecrew/.env.example` pour les valeurs
par défaut non sensibles, et compléter `GRAMPS_USERNAME`/`GRAMPS_PASSWORD` avec les
identifiants réels de l'instance Gramps Web utilisée.

**Point d'attention Phase 0 — `GRAMPS_API_URL`** : GeneCrew tourne sur l'hôte (pas dans un
conteneur), contrairement à `gramps-mcp`. Les deux projets peuvent réutiliser les mêmes
identifiants Gramps Web, mais **pas la même URL** :

- `gramps-mcp` (s'exécutant lui-même en conteneur) atteint Gramps Web via
  `host.docker.internal:80`, **sans** le suffixe `/api`.
- `genecrew` (s'exécutant sur l'hôte) doit utiliser
  `GRAMPS_API_URL=http://localhost:80/api` — accès hôte direct, **avec** le suffixe `/api`
  (c'est la valeur déjà présente dans `genecrew/.env.example`).

### Statistiques de l'arbre

Une fois Gramps Web démarré (via `gramps-mcp`, voir plus haut) et `genecrew/.env` renseigné :

```bash
uv run genecrew stats
```

Affiche le nom de l'arbre et le nombre d'objets par type (personnes, familles, événements,
lieux, sources, citations, dépôts, médias, notes, tags), collectés sans appel LLM (module
`genealogy/gramps/client.py`, voir `docs/document-de-travail.md`, §3.3). Ces chiffres doivent
correspondre à ceux affichés dans le tableau de bord de Gramps Web — c'est le critère de
sortie de la Phase 0.

---

## Phase 1a — Audit déterministe

Livrable de la Phase 1a : le socle sans LLM de la Phase 1 (§9 du document de travail) —
moteur d'audit déterministe (règles R1–R10, §6.1) + rapport Markdown.
Aucune interprétation LLM, aucun tag, aucune note, aucune écriture dans Gramps à ce stade : ce
sera l'objet de la Phase 1b (ADR 0006, `docs/adr/0006-audit-deterministe-personfacts.md`).

### Prérequis

- Phase 0 opérationnelle : `uv run genecrew stats` fonctionne déjà (voir ci-dessus) — le client
  Gramps, la configuration `.env` et la dépendance à `crewai_custom_tools` sont en place.
- Aucun prérequis supplémentaire : l'audit ne consomme aucune clé LLM (`MODEL` n'est pas
  utilisé par cette commande).

### Lancer un audit

Depuis la racine du dépôt `genecrew` :

```bash
uv run genecrew audit --scope all --limit 200
```

Options de la sous-commande `audit` :

| Option | Rôle |
|---|---|
| `--scope` | périmètre à auditer : `all` (toutes les personnes, paginées) ou `person:ID` (une seule personne). `branch:ID` (ascendants/descendants) est différé à la Phase 1b. |
| `--limit N` | limite l'échantillon à N personnes (utile pour un run rapide ou un test terrain). |
| `--batch-size N` | taille des lots traités (défaut : `GENECREW_BATCH_SIZE`, voir Phase 0). |
| `--date` | force la date du rapport (défaut : aujourd'hui). |

### Où trouver le rapport

La commande écrit un rapport Markdown dans `output/audit/<AAAA-MM-JJ>_audit_<scope>.md` (par
exemple `output/audit/2026-07-17_audit_all.md`) et affiche son chemin sur la sortie standard.

L'audit déterministe est rapide (environ 1 minute pour tout l'arbre, aucun appel LLM) : en cas
d'interruption, il suffit de relancer la commande plutôt que de reprendre un run partiel. Le
« resumable batching » (checkpoints de reprise) est réservé à la Phase 1b (interprétation LLM,
plus coûteuse et donc plus utile à reprendre).

### Lire les sévérités

Le rapport liste les anomalies par personne, avec pour chacune une règle (R1 à R10) et une
sévérité :

- **haute** — problème quasiment certain (ex. R3 : âge parental impossible à la naissance
  d'un enfant ; R5 : naissance après le décès d'un parent). À vérifier en priorité.
- **moyenne** — incohérence de date à examiner (ex. R6, R7 : événement daté hors de la vie de
  la personne, ou dans un ordre anormal).
- **basse** — signal d'hygiène des données plutôt qu'anomalie factuelle (ex. R9 : personne sans
  aucune source ni citation rattachée). Le volume de cette catégorie peut être élevé sur un
  arbre peu sourcé — c'est attendu.

Une section « Candidats doublons » (règle R10) liste séparément les paires de personnes dont le
nom normalisé et la date de naissance se recoupent (voir §6.1 et §8 du document de travail pour
le détail des règles et des sévérités).

### Aucun coût LLM, aucune écriture dans Gramps

L'audit est un calcul 100 % déterministe (fonctions pures sur `PersonFacts`/`FamilyFacts`, voir
ADR 0006) : il ne fait aucun appel LLM et ne modifie rien dans Gramps (ni tag, ni note, ni
citation). Sur l'arbre réel, un run `--scope all --limit 200` s'exécute en quelques secondes.
Il peut donc être relancé aussi souvent que nécessaire, y compris avant que la Phase 1b (pose
des tags `ia-anomalie`/`ia-a-verifier`, interprétation LLM, export PDF) ne soit livrée.

---

## Standardisation — noms

Livrable : premier sous-système du Standardisateur (`docs/document-de-travail.md`, §5.2) — la
normalisation de la **casse** des noms importés depuis GEDCOM. Voir la spec complète
(`docs/superpowers/specs/2026-07-18-standardisateur-noms-design.md`) et la décision d'écriture
(`docs/adr/0007-standardisation-casse-invariant.md`). C'est le **premier composant du dépôt qui
écrit réellement dans Gramps** — jusqu'ici, `genecrew stats` et `genecrew audit` étaient tous
deux en lecture seule.

### Prérequis

- Phase 0 opérationnelle (client Gramps, `.env`, voir plus haut).
- Un compte Gramps Web avec le rôle **Editor** (la lecture seule ne suffit plus). Le compte
  dédié `genecrew-ia` mentionné dans `genecrew/.env.example` est prévu pour ce rôle ;
  `GRAMPS_USERNAME`/`GRAMPS_PASSWORD` doivent pointer vers un compte disposant des droits
  d'écriture avant de lancer la commande sans `--dry-run`.

### Lancer une standardisation

Depuis la racine du dépôt `genecrew` :

```bash
uv run genecrew names --scope all --limit 200 --dry-run
```

Options de la sous-commande `names` :

| Option | Rôle |
|---|---|
| `--scope` | périmètre : `all` (toutes les personnes, paginées) ou `person:ID` (une seule personne). |
| `--limit N` | limite l'échantillon à N personnes. |
| `--batch-size N` | taille des lots traités (défaut : `GENECREW_BATCH_SIZE`, voir Phase 0). |
| `--dry-run` | aperçu sans écrire (voir ci-dessous). |
| `--date` | force la date du rapport (défaut : aujourd'hui). |

Note : l'écriture est bornée par **deux** leviers — le flag `--dry-run` (par appel) **et**
l'interrupteur global `GENECREW_DRY_RUN` (table d'environnement, Phase 0). Si l'un ou l'autre
est actif, l'écriture est simulée. `GENECREW_DRY_RUN=true` (le défaut de `.env.example`) force
donc la simulation même sans `--dry-run` : mets-le à `false` pour écrire réellement.

### Où trouver les rapports

Deux fichiers Markdown sous `output/standardize/` :

- `<AAAA-MM-JJ>_noms_<scope>.md` — le rapport des changements de casse faits ou simulés, avec
  une colonne **Type** (`prénom` ou `nom` — prénom et patronyme sont deux entrées distinctes et
  étiquetées séparément), les valeurs avant/après, et une section **Erreurs** listant les rares
  cas où l'invariant de casse a refusé une écriture (aucun PUT dans ce cas — la ligne apparaît en
  erreur, jamais en changement silencieux).
- `<AAAA-MM-JJ>_noms_a_verifier_<scope>.md` — la liste séparée des noms incomplets (contenant
  « ? » ou un chiffre) : des faits incomplets, jamais écrits ni inventés, seulement proposés à la
  recherche humaine.

### Écriture réelle vs aperçu (`--dry-run` et `GENECREW_DRY_RUN`)

La commande écrit réellement (recapitalisations appliquées dans Gramps Web via
`GrampsUpdateNameTool`) **uniquement** si aucun des deux leviers de simulation n'est actif :
ni `--dry-run`, ni `GENECREW_DRY_RUN=true`. Dès que l'un est actif, le même calcul est effectué
et le même rapport produit, mais aucun PUT n'est envoyé (`dry_run: true` dans les données du
rapport). Comme `.env.example` fixe `GENECREW_DRY_RUN=true`, le comportement par défaut est donc
la **simulation** ; pour l'écriture réelle, mets `GENECREW_DRY_RUN=false` (le choix « écriture
directe » de l'ADR 0007 reste vrai au niveau de l'outil, sous l'interrupteur global).

Les écritures réelles sont **réversibles** : elles apparaissent dans l'historique des
transactions Gramps (`GET /api/transactions/history/`) et peuvent être annulées individuellement
(`POST …/{id}/undo`), comme toute autre écriture du projet (ADR 0001).

### Sécurité : seule la casse change

- **Invariant de casse** : `GrampsUpdateNameTool` refuse (erreur, aucune écriture) tout champ
  dont la nouvelle valeur diffère de l'ancienne autrement que par la casse
  (`old.casefold() == new.casefold()`) — il ne peut donc jamais ré-orthographier un nom, tout au
  plus le recapitaliser.
- **Cible restreinte** : seuls les noms **entièrement en capitales ou entièrement en
  minuscules** sont candidats à la correction ; un nom déjà en casse mixte (ex.
  `van Beethoven`) n'est **jamais** modifié.
- **Périmètre v1** : seul le nom principal (`primary_name`) est traité, pas les
  `alternate_names`.

### Un outil réutilisable, pas un nettoyage ponctuel

Le Standardisateur de noms n'est pas un script à usage unique pour « nettoyer une fois » l'import
GEDCOM initial : c'est une **capacité répétable**, à relancer à chaque nouvelle donnée importée
dans l'arbre (par exemple un nouvel import GEDCOM qui remettrait des patronymes tout en
capitales). Sur l'échantillon hors ligne `samples/data.gramps` utilisé pour concevoir l'outil,
686 patronymes et 57 prénoms étaient entièrement en capitales — mais lors de la validation
terrain sur l'arbre réel (`--scope all --limit 200`), seules **4 corrections** ont été trouvées
(`JACQUET → Jacquet` ×2, `VILLAUDY → Villaudy` ×2) et aucun nom incomplet. C'est attendu : l'arbre
réel est déjà largement normalisé au moment de cette validation. La valeur de l'outil n'est pas
dans le volume corrigé ce jour-là, mais dans la capacité à le relancer sans risque — grâce à
l'invariant de casse et à la cible restreinte — chaque fois que des données moins propres
entreront dans l'arbre.

---

## Inférence de genre (lecture seule)

Propose un genre (F/M) pour les personnes de genre inconnu et signale les
contradictions genre/prénom, à partir d'un dictionnaire prénom→sexe INSEE
(couverture suisse OFS en option). **Aucune écriture Gramps** : sortie en
propositions pour revue humaine.

```bash
cd genecrew && uv run genecrew gender --scope all --limit 200
```

Produit dans `output/inference/` : un rapport Markdown (`*_genres_*.md`) et un
fichier de propositions YAML (`*_propositions_genre_*.yaml`, pour un futur
« apply »). **Prêt à l'emploi** : la table prénom→sexe (INSEE, 43 460 prénoms)
est embarquée dans `crewai_custom_tools`. Pour la rafraîchir, l'outil se
provisionne seul en une commande — `uv run python scripts/build_prenoms_sexe.py`
(dans `crewai_custom_tools`) télécharge l'INSEE et régénère la table
(voir `.../data/README.md` ; couverture suisse OFS en option).

---

## Appliquer les corrections de genre (écriture)

Écrit dans Gramps les corrections de genre à haute confiance : remplit les genres inconnus et
corrige les contradictions, au-dessus d'un seuil (défaut 0.98) sur la table INSEE+OFS. **Écrit une
donnée cœur** (ADR 0009) — réversible via l'historique des transactions Gramps.

```bash
# 1) Simuler d'abord (aucune écriture) et relire le rapport :
cd genecrew && uv run genecrew gender-apply --scope all --dry-run
# 2) Écrire pour de vrai (nécessite GENECREW_DRY_RUN=false dans .env) :
cd genecrew && uv run genecrew gender-apply --scope all
```

Rapport dans `output/inference/*_genres_appliques_*.md` : genres écrits, cas sous le seuil, erreurs.
Le global `GENECREW_DRY_RUN=true` (défaut du `.env`) force la simulation quel que soit le flag.

---

## Phases suivantes

Les sections Phase 1b (interprétation LLM, tags, PDF) à Phase 6 (Archiviste Numérique) seront
ajoutées au fil de leur livraison, conformément au phasage décrit dans
`docs/document-de-travail.md`, §9.
