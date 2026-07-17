# GeneCrew — Guide d'utilisation

Ce guide couvre l'usage courant de GeneCrew, phase par phase. **Chaque phase ajoute sa
section** : ce document n'est complet qu'après la Phase 6 (voir le phasage,
`docs/document-de-travail.md`, §9). Pour l'instant, seule la Phase 0 (« Plomberie ») est
livrée.

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

## Phases suivantes

Les sections Phase 1 (Audit lecture seule) à Phase 6 (Archiviste Numérique) seront ajoutées
au fil de leur livraison, conformément au phasage décrit dans
`docs/document-de-travail.md`, §9.
