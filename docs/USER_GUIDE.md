# GeneCrew — Guide d'utilisation

Ce guide couvre l'usage courant de GeneCrew, phase par phase. **Chaque phase ajoute sa
section** : ce document n'est complet qu'après la Phase 6 (voir le phasage,
`docs/document-de-travail.md`, §9). Pour l'instant, la Phase 0 (« Plomberie ») et la Phase 1a
(« Audit déterministe », le socle sans LLM de la Phase 1 — voir §9) sont livrées.

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
| `GENECREW_OUTPUT_DIR` | dossier des rapports/checkpoints (défaut `output/`) |

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
moteur d'audit déterministe (règles R1–R10, §6.1) + rapport Markdown + checkpoints reprenables.
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
| `--resume` | reprend depuis le dernier checkpoint au lieu de repartir de zéro. |
| `--date` | force la date du rapport (défaut : aujourd'hui). |

### Où trouver le rapport

La commande écrit un rapport Markdown dans `output/audit/<AAAA-MM-JJ>_audit_<scope>.md` (par
exemple `output/audit/2026-07-17_audit_all.md`) et affiche son chemin sur la sortie standard.
Les checkpoints de reprise vivent sous `output/checkpoints/` (un fichier JSON par couple
workflow/périmètre, voir §6.5 du document de travail) — ils permettent d'interrompre un run
long et de le reprendre avec `--resume` sans perdre le travail déjà fait.

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

## Phases suivantes

Les sections Phase 1b (interprétation LLM, tags, PDF) à Phase 6 (Archiviste Numérique) seront
ajoutées au fil de leur livraison, conformément au phasage décrit dans
`docs/document-de-travail.md`, §9.
